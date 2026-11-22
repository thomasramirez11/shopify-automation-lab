from __future__ import annotations
from typing import Protocol
from supplier.orchestration.notification_models import NotificationMessage, NotificationProviderReceipt


class NotificationDeliveryPort(Protocol):
    @property
    def provider_name(self) -> str: ...

    def send(self, message: NotificationMessage) -> NotificationProviderReceipt: ...
