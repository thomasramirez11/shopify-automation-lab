from __future__ import annotations

import hashlib
from supplier.orchestration.notification_models import NotificationProviderReceipt


class FakeNotificationProvider:
    def __init__(self, *, fail_channels=None, fail_once_channels=None) -> None:
        self._fail_channels = set(fail_channels or ())
        self._fail_once_channels = set(fail_once_channels or ())
        self._failed_once = set()
        self._receipts = {}
        self.messages = []

    @property
    def provider_name(self) -> str:
        return "fake_notification_provider"

    def send(self, message):
        existing = self._receipts.get(message.idempotency_key)
        if existing is not None:
            return NotificationProviderReceipt(
                delivered=True,
                provider_name=self.provider_name,
                provider_message_id=existing.provider_message_id,
                deduplicated=True,
            )

        channel = message.channel
        if channel in self._fail_channels:
            return NotificationProviderReceipt(
                delivered=False,
                provider_name=self.provider_name,
                error_message=f"Configured persistent fake failure for {channel.value}.",
            )

        if channel in self._fail_once_channels and channel not in self._failed_once:
            self._failed_once.add(channel)
            return NotificationProviderReceipt(
                delivered=False,
                provider_name=self.provider_name,
                error_message=f"Configured one-time fake failure for {channel.value}.",
            )

        provider_message_id = "fake-" + hashlib.sha256(message.idempotency_key.encode("utf-8")).hexdigest()[:20]
        receipt = NotificationProviderReceipt(
            delivered=True,
            provider_name=self.provider_name,
            provider_message_id=provider_message_id,
        )
        self._receipts[message.idempotency_key] = receipt
        self.messages.append(message)
        return receipt
