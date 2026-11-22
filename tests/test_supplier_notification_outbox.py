import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from database.supplier_notification_outbox_schema import (
    ensure_supplier_notification_outbox_schema,
)
from supplier.orchestration.alert_repository import (
    SupplierIncidentAlertRepository,
)
from supplier.orchestration.notification_fake import (
    FakeNotificationProvider,
)
from supplier.orchestration.notification_models import (
    NotificationChannel,
    NotificationRetryPolicy,
)
from supplier.orchestration.notification_policy import (
    build_notification_messages,
)
from supplier.orchestration.notification_repository import (
    SupplierNotificationDeliveryRepository,
)
from supplier.orchestration.notification_service import (
    SupplierNotificationDeliveryService,
)
from supplier.orchestration.outbox_models import (
    NotificationOutboxEventType,
    NotificationOutboxState,
)
from supplier.orchestration.outbox_repository import (
    SupplierNotificationOutboxRepository,
)
from supplier.orchestration.outbox_service import (
    SupplierNotificationOutboxService,
)
from supplier.orchestration.outbox_worker import (
    SupplierNotificationOutboxWorker,
)


SUPPLIER = "demo_supplier"


def factory():
    connection = sqlite3.connect(
        ":memory:"
    )
    connection.row_factory = sqlite3.Row

    @contextmanager
    def connection_factory():
        try:
            yield connection
        finally:
            connection.commit()

    return (
        connection,
        connection_factory,
    )


def alert_route(
    *,
    route_event_id=1,
    route="immediate_alert",
    severity="critical",
    incident_id="a" * 64,
):
    return SimpleNamespace(
        route_event_id=route_event_id,
        incident_id=incident_id,
        supplier_code=SUPPLIER,
        source_event_type="incident_escalated",
        severity=severity,
        route=route,
        policy_fingerprint="b" * 64,
        route_fingerprint="c" * 64,
        created_at="2026-11-22 12:00:00",
    )


def stack(
    connection_factory,
    *,
    retry_policy=None,
):
    alert_repo = SupplierIncidentAlertRepository(
        connection_factory=(
            connection_factory
        )
    )

    outbox_repo = SupplierNotificationOutboxRepository(
        connection_factory=(
            connection_factory
        )
    )

    delivery_repo = SupplierNotificationDeliveryRepository(
        connection_factory=(
            connection_factory
        )
    )

    delivery_service = SupplierNotificationDeliveryService(
        alert_repository=alert_repo,
        delivery_repository=delivery_repo,
        retry_policy=(
            retry_policy
            or NotificationRetryPolicy()
        ),
    )

    outbox_service = SupplierNotificationOutboxService(
        alert_repository=alert_repo,
        outbox_repository=outbox_repo,
        retry_policy=(
            retry_policy
            or NotificationRetryPolicy()
        ),
    )

    worker = SupplierNotificationOutboxWorker(
        outbox_repository=outbox_repo,
        delivery_service=delivery_service,
        worker_id="test-worker",
    )

    return (
        alert_repo,
        outbox_repo,
        delivery_repo,
        outbox_service,
        worker,
    )


def test_schema_creates_outbox_table():
    connection, _ = factory()

    ensure_supplier_notification_outbox_schema(
        connection
    )

    row = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table'
          AND name = 'supplier_notification_outbox_events';
        """
    ).fetchone()

    assert row is not None


def test_schema_is_idempotent():
    connection, _ = factory()

    ensure_supplier_notification_outbox_schema(
        connection
    )
    ensure_supplier_notification_outbox_schema(
        connection
    )


def test_outbox_update_is_blocked():
    connection, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            UPDATE supplier_notification_outbox_events
            SET worker_id = 'changed';
            """
        )


def test_outbox_delete_is_blocked():
    connection, connection_factory = factory()

    _, _, _, outbox_service, _ = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    with pytest.raises(
        sqlite3.IntegrityError,
        match="append-only",
    ):
        connection.execute(
            """
            DELETE FROM supplier_notification_outbox_events;
            """
        )


def test_immediate_alert_enqueues_three_jobs():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    result = outbox_service.enqueue_alert_route(
        alert_route()
    )

    assert result.messages_planned == 3
    assert result.jobs_enqueued == 3
    assert outbox_repo.count_jobs(
        SUPPLIER
    ) == 3


def test_dashboard_route_enqueues_zero_jobs():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    result = outbox_service.enqueue_alert_route(
        alert_route(
            route="dashboard",
            severity="warning",
        )
    )

    assert result.messages_planned == 0
    assert result.jobs_enqueued == 0
    assert outbox_repo.count_jobs(
        SUPPLIER
    ) == 0


def test_enqueue_is_idempotent():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    first = outbox_service.enqueue_alert_route(
        alert_route()
    )

    second = outbox_service.enqueue_alert_route(
        alert_route()
    )

    assert first.jobs_enqueued == 3
    assert second.jobs_enqueued == 0
    assert second.jobs_already_present == 3
    assert outbox_repo.count_jobs(
        SUPPLIER
    ) == 3


def test_enqueued_job_state_is_enqueued():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    jobs = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )

    assert len(jobs) == 1
    assert (
        jobs[0].state
        == NotificationOutboxState.ENQUEUED
    )


def test_outbox_event_reconstructs_notification_message():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    assert (
        job.message.channel
        == NotificationChannel.SLACK
    )
    assert (
        job.message.delivery_id
        == job.delivery_id
    )


def test_worker_delivers_three_pending_jobs():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert result.jobs_seen == 3
    assert result.delivered == 3
    assert result.failed == 0
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.DELIVERED,
        )
        == 3
    )


def test_worker_records_claim_before_delivery():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert [
        event.event_type
        for event in outbox_repo.get_events(
            job.delivery_id
        )
    ] == [
        "outbox_enqueued",
        "outbox_claimed",
        "outbox_delivered",
    ]


def test_worker_failure_records_failed_state():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(
            fail_channels={
                NotificationChannel.WEBHOOK
            }
        ),
    )

    assert result.delivered == 2
    assert result.failed == 1
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.FAILED,
        )
        == 1
    )


def test_failed_job_is_not_pending_until_recovery_queues_it():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(
            fail_channels={
                NotificationChannel.WEBHOOK
            }
        ),
    )

    assert (
        len(
            outbox_repo.get_pending_jobs(
                supplier_code=SUPPLIER
            )
        )
        == 0
    )


def test_recovery_queues_retry_for_failed_job():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    recovery = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    assert recovery.failed_jobs_seen == 1
    assert recovery.retries_queued == 1
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.RETRY_QUEUED,
        )
        == 1
    )


def test_retry_worker_delivers_recovered_job():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    second = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert second.jobs_seen == 1
    assert second.delivered == 1
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.DELIVERED,
        )
        == 3
    )


def test_retry_outbox_history_preserves_failure():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    failed_job = outbox_repo.get_failed_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert [
        event.event_type
        for event in outbox_repo.get_events(
            failed_job.delivery_id
        )
    ] == [
        "outbox_enqueued",
        "outbox_claimed",
        "outbox_failed",
        "outbox_retry_queued",
        "outbox_claimed",
        "outbox_delivered",
    ]


def test_retry_attempt_number_increments():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    failed_job = outbox_repo.get_failed_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    attempts = [
        event.attempt_number
        for event in outbox_repo.get_events(
            failed_job.delivery_id
        )
        if event.event_type
        == "outbox_claimed"
    ]

    assert attempts == [
        1,
        2,
    ]


def test_retry_limit_dead_letters_job():
    _, connection_factory = factory()

    retry_policy = NotificationRetryPolicy(
        max_attempts=1
    )

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory,
        retry_policy=retry_policy,
    )

    provider = FakeNotificationProvider(
        fail_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    recovery = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    assert recovery.dead_lettered == 1
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.DEAD_LETTERED,
        )
        == 1
    )


def test_dead_lettered_job_is_terminal():
    _, connection_factory = factory()

    retry_policy = NotificationRetryPolicy(
        max_attempts=1
    )

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory,
        retry_policy=retry_policy,
    )

    provider = FakeNotificationProvider(
        fail_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    assert (
        outbox_repo.get_pending_jobs(
            supplier_code=SUPPLIER
        )
        == []
    )


def test_worker_resumes_claimed_job_after_interruption():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_repo.append_event(
        message=job.message,
        event_type=(
            NotificationOutboxEventType.CLAIMED.value
        ),
        attempt_number=1,
        worker_id="crashed-worker",
        provider_name="fake_notification_provider",
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert result.jobs_resumed == 1
    assert result.delivered == 1


def test_crash_after_provider_send_is_provider_deduplicated():
    _, connection_factory = factory()

    _, outbox_repo, delivery_repo, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider()

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_repo.append_event(
        message=job.message,
        event_type=(
            NotificationOutboxEventType.CLAIMED.value
        ),
        attempt_number=1,
        worker_id="crashed-worker",
        provider_name=provider.provider_name,
    )

    provider.send(
        job.message
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert result.delivered == 1
    assert len(
        provider.messages
    ) == 1
    assert (
        delivery_repo.get_delivered_event(
            job.delivery_id
        )
        is not None
    )


def test_worker_rescan_after_success_sees_zero_jobs():
    _, connection_factory = factory()

    _, _, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    provider = FakeNotificationProvider()

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    second = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert second.jobs_seen == 0
    assert second.delivered == 0


def test_existing_v27i_delivery_is_adopted_without_duplicate_provider_send():
    _, connection_factory = factory()

    _, outbox_repo, delivery_repo, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider()

    route_obj = alert_route(
        route="operator_review",
        severity="warning",
    )

    message = build_notification_messages(
        alert_route=route_obj
    )[0]

    delivery_service = SupplierNotificationDeliveryService(
        alert_repository=(
            SupplierIncidentAlertRepository(
                connection_factory=(
                    connection_factory
                )
            )
        ),
        delivery_repository=delivery_repo,
    )

    delivery_service.deliver_message(
        message=message,
        provider=provider,
    )

    outbox_service.enqueue_alert_route(
        route_obj
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert result.delivered == 1
    assert len(
        provider.messages
    ) == 1
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.DELIVERED,
        )
        == 1
    )


def test_get_job_returns_latest_state():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    latest = outbox_repo.get_job(
        job.delivery_id
    )

    assert (
        latest.state
        == NotificationOutboxState.DELIVERED
    )


def test_get_job_returns_none_for_unknown_delivery():
    _, connection_factory = factory()

    _, outbox_repo, _, _, _ = stack(
        connection_factory
    )

    assert (
        outbox_repo.get_job(
            "f" * 64
        )
        is None
    )


def test_recent_events_are_newest_first():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    events = outbox_repo.get_recent_events(
        supplier_code=SUPPLIER,
        limit=10,
    )

    assert (
        events[0].event_type
        == "outbox_delivered"
    )


def test_recent_event_limit_validation():
    _, connection_factory = factory()

    _, outbox_repo, _, _, _ = stack(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="positive integer",
    ):
        outbox_repo.get_recent_events(
            supplier_code=SUPPLIER,
            limit=0,
        )


def test_worker_id_validation():
    _, connection_factory = factory()

    alert_repo = SupplierIncidentAlertRepository(
        connection_factory=(
            connection_factory
        )
    )

    delivery_repo = SupplierNotificationDeliveryRepository(
        connection_factory=(
            connection_factory
        )
    )

    delivery_service = SupplierNotificationDeliveryService(
        alert_repository=alert_repo,
        delivery_repository=delivery_repo,
    )

    with pytest.raises(
        ValueError,
        match="worker_id",
    ):
        SupplierNotificationOutboxWorker(
            outbox_repository=(
                SupplierNotificationOutboxRepository(
                    connection_factory=(
                        connection_factory
                    )
                )
            ),
            delivery_service=(
                delivery_service
            ),
            worker_id="",
        )


def test_failed_recovery_is_idempotent_after_retry_queued():
    _, connection_factory = factory()

    _, _, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    first = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    second = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    assert first.retries_queued == 1
    assert second.failed_jobs_seen == 0


def test_dead_letter_recovery_is_idempotent():
    _, connection_factory = factory()

    retry_policy = NotificationRetryPolicy(
        max_attempts=1
    )

    _, _, _, outbox_service, worker = stack(
        connection_factory,
        retry_policy=retry_policy,
    )

    provider = FakeNotificationProvider(
        fail_channels={
            NotificationChannel.WEBHOOK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    first = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    second = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    assert first.dead_lettered == 1
    assert second.failed_jobs_seen == 0


def test_multiple_channels_have_independent_outbox_jobs():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route()
    )

    jobs = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )

    assert {
        job.message.channel
        for job in jobs
    } == {
        NotificationChannel.EMAIL,
        NotificationChannel.SLACK,
        NotificationChannel.WEBHOOK,
    }


def test_delivery_id_is_same_as_v27i_message_identity():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    route_obj = alert_route(
        route="operator_review",
        severity="warning",
    )

    expected = build_notification_messages(
        alert_route=route_obj
    )[0]

    outbox_service.enqueue_alert_route(
        route_obj
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    assert (
        job.delivery_id
        == expected.delivery_id
    )
    assert (
        job.message.idempotency_key
        == expected.idempotency_key
    )


def test_outbox_preserves_subject_and_body():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, _ = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    assert "[WARNING]" in (
        job.message.subject
    )
    assert (
        "Incident:"
        in job.message.body
    )


def test_count_jobs_counts_distinct_deliveries():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert (
        outbox_repo.count_jobs(
            SUPPLIER
        )
        == 1
    )


def test_successful_delivery_has_terminal_property():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert (
        outbox_repo.get_job(
            job.delivery_id
        ).terminal
        is True
    )


def test_failed_job_is_not_terminal_until_dead_lettered():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_channels={
            NotificationChannel.SLACK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    job = outbox_repo.get_failed_jobs(
        supplier_code=SUPPLIER
    )[0]

    assert job.terminal is False


def test_outbox_worker_uses_delivery_audit_ledger():
    _, connection_factory = factory()

    _, _, delivery_repo, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert (
        delivery_repo.count_delivered(
            SUPPLIER
        )
        == 1
    )


def test_recovery_does_not_automatically_send():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.SLACK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    recovery = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    assert recovery.retries_queued == 1
    assert len(
        provider.messages
    ) == 0
    assert (
        outbox_repo.count_state(
            supplier_code=SUPPLIER,
            state=NotificationOutboxState.RETRY_QUEUED,
        )
        == 1
    )


def test_retry_worker_is_explicit_second_step():
    _, connection_factory = factory()

    _, _, _, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.SLACK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    first = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    second = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert first.failed == 1
    assert second.delivered == 1


def test_empty_outbox_worker_is_noop():
    _, connection_factory = factory()

    _, _, _, _, worker = stack(
        connection_factory
    )

    result = worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    assert result.jobs_seen == 0
    assert result.delivered == 0


def test_empty_recovery_is_noop():
    _, connection_factory = factory()

    _, _, _, outbox_service, _ = stack(
        connection_factory
    )

    result = outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name="fake_notification_provider",
    )

    assert result.failed_jobs_seen == 0
    assert result.retries_queued == 0
    assert result.dead_lettered == 0


def test_get_jobs_by_state_empty_state_list_is_empty():
    _, connection_factory = factory()

    _, outbox_repo, _, _, _ = stack(
        connection_factory
    )

    assert (
        outbox_repo.get_jobs_by_state(
            supplier_code=SUPPLIER,
            states=(),
        )
        == []
    )


def test_unsupported_state_is_rejected():
    _, connection_factory = factory()

    _, outbox_repo, _, _, _ = stack(
        connection_factory
    )

    with pytest.raises(
        ValueError,
        match="Unsupported outbox state",
    ):
        outbox_repo.get_jobs_by_state(
            supplier_code=SUPPLIER,
            states=("made_up",),
        )


def test_resumed_claimed_job_keeps_same_attempt_number():
    _, connection_factory = factory()

    _, outbox_repo, _, outbox_service, worker = stack(
        connection_factory
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    job = outbox_repo.get_pending_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_repo.append_event(
        message=job.message,
        event_type=(
            NotificationOutboxEventType.CLAIMED.value
        ),
        attempt_number=1,
        worker_id="crashed-worker",
        provider_name="fake_notification_provider",
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=FakeNotificationProvider(),
    )

    delivered = outbox_repo.get_job(
        job.delivery_id
    )

    assert delivered.attempt_number == 1


def test_retry_queued_job_uses_second_attempt_delivery_ledger():
    _, connection_factory = factory()

    _, outbox_repo, delivery_repo, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.SLACK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    job = outbox_repo.get_failed_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    delivery_events = delivery_repo.get_events(
        job.delivery_id
    )

    assert (
        delivery_events[-1].attempt_number
        == 2
    )


def test_outbox_and_delivery_ledgers_both_preserve_retry_failure_history():
    _, connection_factory = factory()

    _, outbox_repo, delivery_repo, outbox_service, worker = stack(
        connection_factory
    )

    provider = FakeNotificationProvider(
        fail_once_channels={
            NotificationChannel.SLACK
        }
    )

    outbox_service.enqueue_alert_route(
        alert_route(
            route="operator_review",
            severity="warning",
        )
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    job = outbox_repo.get_failed_jobs(
        supplier_code=SUPPLIER
    )[0]

    outbox_service.recover_failed_jobs(
        supplier_code=SUPPLIER,
        provider_name=provider.provider_name,
    )

    worker.process_pending(
        supplier_code=SUPPLIER,
        provider=provider,
    )

    assert any(
        event.event_type
        == "outbox_failed"
        for event in outbox_repo.get_events(
            job.delivery_id
        )
    )

    assert any(
        event.event_type
        == "delivery_failed"
        for event in delivery_repo.get_events(
            job.delivery_id
        )
    )
