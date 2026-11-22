import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from database.supplier_notification_delivery_schema import ensure_supplier_notification_delivery_schema
from supplier.orchestration.alert_repository import SupplierIncidentAlertRepository
from supplier.orchestration.notification_fake import FakeNotificationProvider
from supplier.orchestration.notification_models import (
    NotificationChannel,
    NotificationDeliveryError,
    NotificationProviderReceipt,
    NotificationRetryPolicy,
)
from supplier.orchestration.notification_policy import NotificationDeliveryPolicy, build_notification_messages
from supplier.orchestration.notification_repository import SupplierNotificationDeliveryRepository
from supplier.orchestration.notification_service import SupplierNotificationDeliveryService

SUPPLIER = "demo_supplier"
INCIDENT_ID = "a" * 64


def factory():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.commit()

    return connection, connection_factory


def route(*, route_event_id=1, route_name="immediate_alert", severity="critical", source_event_type="incident_escalated"):
    return SimpleNamespace(
        route_event_id=route_event_id,
        incident_id=INCIDENT_ID,
        supplier_code=SUPPLIER,
        source_event_type=source_event_type,
        severity=severity,
        route=route_name,
        policy_fingerprint="b" * 64,
        route_fingerprint="c" * 64,
        created_at="2026-11-22 12:00:00",
    )


def build_service(connection_factory, *, retry_policy=None):
    alert_repo = SupplierIncidentAlertRepository(connection_factory=connection_factory)
    delivery_repo = SupplierNotificationDeliveryRepository(connection_factory=connection_factory)
    service = SupplierNotificationDeliveryService(
        alert_repository=alert_repo,
        delivery_repository=delivery_repo,
        retry_policy=retry_policy or NotificationRetryPolicy(),
    )
    return alert_repo, delivery_repo, service


def test_schema_creates_delivery_table():
    connection, _ = factory()
    ensure_supplier_notification_delivery_schema(connection)
    row = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='supplier_notification_delivery_events';").fetchone()
    assert row is not None


def test_schema_is_idempotent():
    connection, _ = factory()
    ensure_supplier_notification_delivery_schema(connection)
    ensure_supplier_notification_delivery_schema(connection)


def test_delivery_ledger_update_is_blocked():
    connection, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("UPDATE supplier_notification_delivery_events SET provider_name='x';")


def test_delivery_ledger_delete_is_blocked():
    connection, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        connection.execute("DELETE FROM supplier_notification_delivery_events;")


def test_dashboard_has_no_external_messages():
    assert build_notification_messages(alert_route=route(route_name="dashboard", severity="warning")) == ()


def test_operator_review_maps_to_slack():
    messages = build_notification_messages(alert_route=route(route_name="operator_review", severity="warning"))
    assert [message.channel for message in messages] == [NotificationChannel.SLACK]


def test_immediate_alert_maps_to_three_channels():
    messages = build_notification_messages(alert_route=route())
    assert {message.channel for message in messages} == {NotificationChannel.EMAIL, NotificationChannel.SLACK, NotificationChannel.WEBHOOK}


def test_recovery_notice_maps_to_email_and_slack():
    messages = build_notification_messages(alert_route=route(route_name="recovery_notice", severity="info", source_event_type="incident_closed"))
    assert {message.channel for message in messages} == {NotificationChannel.EMAIL, NotificationChannel.SLACK}


def test_delivery_id_is_deterministic():
    first = build_notification_messages(alert_route=route())
    second = build_notification_messages(alert_route=route())
    assert [m.delivery_id for m in first] == [m.delivery_id for m in second]


def test_delivery_ids_differ_by_channel():
    messages = build_notification_messages(alert_route=route())
    assert len({m.delivery_id for m in messages}) == 3


def test_idempotency_key_is_sha256_shape():
    message = build_notification_messages(alert_route=route())[0]
    assert len(message.idempotency_key) == 64
    assert all(c in "0123456789abcdef" for c in message.idempotency_key)


def test_policy_fingerprint_is_deterministic():
    assert NotificationDeliveryPolicy().fingerprint == NotificationDeliveryPolicy().fingerprint


def test_policy_fingerprint_changes_when_channels_change():
    first = NotificationDeliveryPolicy()
    second = NotificationDeliveryPolicy(operator_review_channels=(NotificationChannel.EMAIL,))
    assert first.fingerprint != second.fingerprint


def test_duplicate_channels_are_rejected():
    with pytest.raises(NotificationDeliveryError, match="duplicate"):
        NotificationDeliveryPolicy(recovery_notice_channels=(NotificationChannel.EMAIL, NotificationChannel.EMAIL))


def test_empty_channel_group_is_rejected():
    with pytest.raises(NotificationDeliveryError, match="non-empty tuple"):
        NotificationDeliveryPolicy(immediate_alert_channels=())


def test_fake_provider_success_receipt():
    provider = FakeNotificationProvider()
    receipt = provider.send(build_notification_messages(alert_route=route())[0])
    assert receipt.delivered is True
    assert receipt.provider_message_id


def test_fake_provider_provider_side_idempotency():
    provider = FakeNotificationProvider()
    message = build_notification_messages(alert_route=route())[0]
    first = provider.send(message)
    second = provider.send(message)
    assert first.provider_message_id == second.provider_message_id
    assert second.deduplicated is True
    assert len(provider.messages) == 1


def test_fake_provider_persistent_failure():
    provider = FakeNotificationProvider(fail_channels={NotificationChannel.EMAIL})
    message = next(m for m in build_notification_messages(alert_route=route()) if m.channel == NotificationChannel.EMAIL)
    receipt = provider.send(message)
    assert receipt.delivered is False
    assert "persistent" in receipt.error_message


def test_fake_provider_fail_once_then_succeeds():
    provider = FakeNotificationProvider(fail_once_channels={NotificationChannel.WEBHOOK})
    message = next(m for m in build_notification_messages(alert_route=route()) if m.channel == NotificationChannel.WEBHOOK)
    assert provider.send(message).delivered is False
    assert provider.send(message).delivered is True


def test_delivered_receipt_requires_message_id():
    with pytest.raises(NotificationDeliveryError, match="provider_message_id"):
        NotificationProviderReceipt(delivered=True, provider_name="fake")


def test_failed_receipt_requires_error():
    with pytest.raises(NotificationDeliveryError, match="error_message"):
        NotificationProviderReceipt(delivered=False, provider_name="fake")


def test_successful_route_attempts_three_deliveries():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    result = service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    assert (result.messages_planned, result.attempted, result.delivered, result.failed) == (3, 3, 3, 0)


def test_success_writes_started_then_delivered():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    result = service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    message = result.results[0].message
    assert [event.event_type for event in repo.get_events(message.delivery_id)] == ["delivery_started", "delivery_delivered"]


def test_failure_writes_started_then_failed():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    result = service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider(fail_channels={NotificationChannel.EMAIL}))
    failed = next(item for item in result.results if not item.delivered)
    assert [event.event_type for event in repo.get_events(failed.message.delivery_id)] == ["delivery_started", "delivery_failed"]


def test_failed_delivery_does_not_auto_retry_on_rescan():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    provider = FakeNotificationProvider(fail_channels={NotificationChannel.EMAIL})
    service.deliver_alert_route(alert_route=route(), provider=provider)
    second = service.deliver_alert_route(alert_route=route(), provider=provider)
    email = next(item for item in second.results if item.message.channel == NotificationChannel.EMAIL)
    assert email.attempted is False
    assert email.skipped is True
    assert email.reason == "failed_delivery_requires_explicit_retry"


def test_explicit_retry_succeeds_on_attempt_two():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    provider = FakeNotificationProvider(fail_once_channels={NotificationChannel.WEBHOOK})
    first = service.deliver_alert_route(alert_route=route(), provider=provider)
    failed = next(item for item in first.results if not item.delivered)
    retry = service.retry_failed_message(message=failed.message, provider=provider)
    assert retry.delivered is True
    assert retry.attempt_number == 2
    assert [event.event_type for event in repo.get_events(failed.message.delivery_id)] == [
        "delivery_started", "delivery_failed", "retry_queued", "delivery_started", "delivery_delivered"
    ]


def test_delivered_messages_are_skipped_on_rescan():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    provider = FakeNotificationProvider()
    service.deliver_alert_route(alert_route=route(), provider=provider)
    second = service.deliver_alert_route(alert_route=route(), provider=provider)
    assert second.attempted == 0
    assert second.skipped == 3


def test_retry_without_previous_failure_is_rejected():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    message = build_notification_messages(alert_route=route())[0]
    with pytest.raises(NotificationDeliveryError, match="previous delivery_failed"):
        service.retry_failed_message(message=message, provider=FakeNotificationProvider())


def test_retry_limit_is_enforced():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory, retry_policy=NotificationRetryPolicy(max_attempts=2))
    provider = FakeNotificationProvider(fail_channels={NotificationChannel.WEBHOOK})
    message = next(m for m in build_notification_messages(alert_route=route()) if m.channel == NotificationChannel.WEBHOOK)
    service.deliver_message(message=message, provider=provider)
    service.retry_failed_message(message=message, provider=provider)
    with pytest.raises(NotificationDeliveryError, match="limit exhausted"):
        service.retry_failed_message(message=message, provider=provider)


def test_retry_policy_rejects_zero():
    with pytest.raises(NotificationDeliveryError, match="greater than zero"):
        NotificationRetryPolicy(max_attempts=0)


def test_repository_counts_delivered_receipts():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    assert repo.count_delivered(SUPPLIER) == 3


def test_repository_counts_failed_attempts():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider(fail_channels={NotificationChannel.EMAIL}))
    assert repo.count_failed(SUPPLIER) == 1


def test_recent_event_limit_validation():
    _, connection_factory = factory()
    _, repo, _ = build_service(connection_factory)
    with pytest.raises(ValueError, match="positive integer"):
        repo.get_recent_events(supplier_code=SUPPLIER, limit=0)


def test_dashboard_route_attempts_zero_external_deliveries():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    result = service.deliver_alert_route(alert_route=route(route_name="dashboard", severity="warning"), provider=FakeNotificationProvider())
    assert result.messages_planned == 0
    assert result.attempted == 0


def test_empty_real_route_scan_attempts_nothing():
    _, connection_factory = factory()
    _, _, service = build_service(connection_factory)
    result = service.deliver_existing_alert_routes(supplier_code=SUPPLIER, provider=FakeNotificationProvider(), limit=100)
    assert result.alert_routes_seen == 0
    assert result.attempted == 0


def test_message_subject_contains_severity():
    assert "[CRITICAL]" in build_notification_messages(alert_route=route())[0].subject


def test_message_body_contains_incident_id():
    assert INCIDENT_ID in build_notification_messages(alert_route=route())[0].body


def test_provider_name_is_persisted():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    result = service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    delivered = repo.get_delivered_event(result.results[0].message.delivery_id)
    assert delivered.provider_name == "fake_notification_provider"


def test_provider_message_id_is_persisted():
    _, connection_factory = factory()
    _, repo, service = build_service(connection_factory)
    result = service.deliver_alert_route(alert_route=route(), provider=FakeNotificationProvider())
    delivered = repo.get_delivered_event(result.results[0].message.delivery_id)
    assert delivered.provider_message_id


def test_fake_provider_has_no_real_transport_clients():
    provider = FakeNotificationProvider()
    assert not hasattr(provider, "smtp_client")
    assert not hasattr(provider, "slack_client")
    assert not hasattr(provider, "requests_session")
