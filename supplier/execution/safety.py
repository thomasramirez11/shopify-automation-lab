from __future__ import annotations

import os

from supplier.execution.models import SupplierExecutionError


LIVE_WRITE_ENV_VAR = "SUPPLIER_SYNC_LIVE_WRITES"


def live_writes_enabled_from_environment() -> bool:
    """
    Read the V2 live-write kill switch.

    Safe default: disabled.
    """

    raw_value = os.getenv(
        LIVE_WRITE_ENV_VAR,
        "false",
    )

    normalized = raw_value.strip().lower()

    if normalized in {"false", "0", "no", "off"}:
        return False

    if normalized in {"true", "1", "yes", "on"}:
        return True

    raise SupplierExecutionError(
        f"{LIVE_WRITE_ENV_VAR} must be an explicit boolean value."
    )
