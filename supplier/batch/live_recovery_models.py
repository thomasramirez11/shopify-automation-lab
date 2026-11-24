"""V2.8B/3 recovery types. No live Shopify mutation entry point exists here."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class RecoveryConflict(ValueError):
    """A replay, inconsistent record or unsafe recovery action was blocked."""


class RecoveryEventKind(str, Enum):
    DISPATCH_ARMED = "DISPATCH_ARMED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    READBACK_OBSERVED = "READBACK_OBSERVED"
    READBACK_FAILED = "READBACK_FAILED"


class RecoveryState(str, Enum):
    PREPARED_NOT_SENT = "PREPARED_NOT_SENT"
    ARMED_OUTCOME_UNCERTAIN = "ARMED_OUTCOME_UNCERTAIN"
    READBACK_TARGET_OBSERVED = "READBACK_TARGET_OBSERVED"
    READBACK_BASELINE_OBSERVED = "READBACK_BASELINE_OBSERVED"
    READBACK_MIXED_OR_DIVERGED = "READBACK_MIXED_OR_DIVERGED"
    READBACK_FAILED = "READBACK_FAILED"


@dataclass(frozen=True, slots=True)
class RecoveryEvent:
    operation_id: str
    sequence: int
    kind: RecoveryEventKind
    details: dict[str, Any]
    previous_hash: str
    event_hash: str


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    operation_id: str
    state: RecoveryState
    dispatch_allowed: bool
    automatic_retry_allowed: bool
    human_review_required: bool
    event_count: int
    reason: str


@dataclass(frozen=True, slots=True)
class ImmutableRequestSnapshot:
    """Database snapshot for audit/recovery. Access doesn't authorize sending it."""

    operation_id: str
    request_digest: str
    payload_sha256: str
    payload: dict[str, Any]
