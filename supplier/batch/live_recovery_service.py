"""V2.8B/3 conservative recovery state machine (no write transport).

A crash after durable DISPATCH_ARMED could have occurred before, during or
AFTER a request reached Shopify. Never auto-retry, even if readback equals
baseline: time-of-check / time-of-use and other actors make that ambiguous.
"""

from __future__ import annotations

from supplier.batch.live_intent_repository import SupplierLiveBatchIntentRepository
from supplier.batch.live_atomic_preparation import SupplierLiveBatchAtomicPreparationRepository
from supplier.batch.live_preflight_bridge import PreparedBatchRequest
from supplier.batch.live_recovery_models import (
    RecoveryConflict, RecoveryDecision, RecoveryEventKind, RecoveryState,
)
from supplier.batch.live_recovery_repository import SupplierLiveBatchRecoveryRepository


class SupplierLiveBatchRecoveryService:
    def __init__(
        self, *, intent_repository: SupplierLiveBatchIntentRepository,
        recovery_repository: SupplierLiveBatchRecoveryRepository,
    ) -> None:
        self._intents = intent_repository
        self._recovery = recovery_repository

    def prepare(self, prepared: PreparedBatchRequest):
        """Atomically persist both intent AND immutable snapshot, or neither.

        Require the two injected repositories to share an identical connection
        factory; this prevents silently preparing a snapshot in one database and
        reserving its identity in a different database. No Shopify I/O.
        """
        factory = self._intents._connection_factory
        if factory is not self._recovery._connection_factory:
            raise RecoveryConflict("atomic preparation requires a shared SQLite connection factory")
        atomic = SupplierLiveBatchAtomicPreparationRepository(connection_factory=factory)
        return atomic.prepare(prepared)

    def arm_dispatch(self, *, operation_id: str, request_digest: str):
        """Durable pre-send journal entry; NOT a Shopify send or permission to retry.

        Future live code must call this once BEFORE network mutation I/O. If it
        crashes after this step it must reconcile, never assume unsent.
        """
        snapshot = self._recovery.load_snapshot(operation_id)
        if snapshot.request_digest != request_digest:
            raise RecoveryConflict("operation ID is not bound to the supplied request digest")
        if self._recovery.events(operation_id):
            raise RecoveryConflict("already armed; second dispatch attempt blocked")
        return self._recovery.append_event(
            operation_id, kind=RecoveryEventKind.DISPATCH_ARMED,
            details={"request_digest": request_digest}, expected_event_count=0,
        )

    def note_outcome_unknown(self, *, operation_id: str):
        """Record a simulated transport timeout/unknown result; never retry."""
        events = self._recovery.events(operation_id)
        if not events or events[-1].kind != RecoveryEventKind.DISPATCH_ARMED:
            raise RecoveryConflict("unknown transport outcome requires one fresh armed event")
        return self._recovery.append_event(
            operation_id, kind=RecoveryEventKind.OUTCOME_UNKNOWN,
            details={"reason": "transport_result_unavailable"},
            expected_event_count=len(events),
        )

    def observe_current_inventory(self, *, operation_id: str, readback_port):
        """Read both Shopify inventory targets after uncertainty (READ ONLY).

        The caller must provide an authenticated *read-only* adapter in a future
        live controller. This method only uses read_available(). Observing the
        proposed quantity does NOT prove which actor caused it, and observing
        baseline does NOT prove the mutation never reached Shopify.
        """
        snapshot = self._recovery.load_snapshot(operation_id)
        events = self._recovery.events(operation_id)
        if not events or events[0].kind != RecoveryEventKind.DISPATCH_ARMED:
            raise RecoveryConflict("readback reconciliation requires a prior armed attempt")
        if events[-1].kind not in (
            RecoveryEventKind.DISPATCH_ARMED, RecoveryEventKind.OUTCOME_UNKNOWN,
            RecoveryEventKind.READBACK_OBSERVED, RecoveryEventKind.READBACK_FAILED,
        ):
            raise RecoveryConflict("unexpected recovery state")
        quantities = snapshot.payload["variables"]["input"]["quantities"]
        skus = snapshot.payload["skus"]
        readings = []
        try:
            for sku, target in zip(skus, quantities):
                state = readback_port.read_available(
                    inventory_item_id=target["inventoryItemId"],
                    location_id=target["locationId"],
                )
                if (
                    state.inventory_item_id != target["inventoryItemId"]
                    or state.location_id != target["locationId"]
                    or state.sku != sku
                    or state.tracked is not True
                    or state.location_active is not True
                    or state.level_active is not True
                    or type(state.available_quantity) is not int
                    or state.available_quantity < 0
                ):
                    raise RecoveryConflict("readback target or integrity check failed")
                before, after = target["changeFromQuantity"], target["quantity"]
                actual = state.available_quantity
                readings.append({
                    "sku": sku,
                    "inventory_item_id": target["inventoryItemId"],
                    "before": before,
                    "after": after,
                    "observed": actual,
                    "classification": (
                        "TARGET" if actual == after else
                        "BASELINE" if actual == before else "DIVERGED"
                    ),
                })
        except Exception:
            # Do not expose Shopify response details, credentials or user data.
            return self._recovery.append_event(
                operation_id, kind=RecoveryEventKind.READBACK_FAILED,
                details={"reason": "readback_unavailable_or_untrusted"},
                expected_event_count=len(events),
            )
        return self._recovery.append_event(
            operation_id, kind=RecoveryEventKind.READBACK_OBSERVED,
            details={"observations": readings}, expected_event_count=len(events),
        )

    def decision(self, *, operation_id: str) -> RecoveryDecision:
        """Always fail closed. No automatic replay or mutation authorization."""
        self._recovery.load_snapshot(operation_id)
        events = self._recovery.events(operation_id)
        state = RecoveryState.PREPARED_NOT_SENT
        reason = "durably prepared, but no dispatch was armed; execution remains disabled"
        if events:
            if events[0].kind != RecoveryEventKind.DISPATCH_ARMED:
                raise RecoveryConflict("invalid first dispatch journal event")
            final = events[-1]
            if final.kind in (RecoveryEventKind.DISPATCH_ARMED, RecoveryEventKind.OUTCOME_UNKNOWN):
                state = RecoveryState.ARMED_OUTCOME_UNCERTAIN
                reason = "possibly transmitted; require human review and fresh Shopify readback"
            elif final.kind == RecoveryEventKind.READBACK_FAILED:
                state = RecoveryState.READBACK_FAILED
                reason = "no trustworthy inventory observation; do not resend"
            elif final.kind == RecoveryEventKind.READBACK_OBSERVED:
                observed = final.details.get("observations")
                if not isinstance(observed, list) or len(observed) != 2:
                    raise RecoveryConflict("readback record malformed")
                classes = [x.get("classification") for x in observed if isinstance(x, dict)]
                if classes == ["TARGET", "TARGET"]:
                    state = RecoveryState.READBACK_TARGET_OBSERVED
                    reason = "targets currently match proposal; source/cause not proven"
                elif classes == ["BASELINE", "BASELINE"]:
                    state = RecoveryState.READBACK_BASELINE_OBSERVED
                    reason = "baseline observed; still not proof Shopify never applied an update"
                else:
                    state = RecoveryState.READBACK_MIXED_OR_DIVERGED
                    reason = "mixed or changed inventory; manual investigation required"
            else:
                raise RecoveryConflict("unexpected journal event")
        return RecoveryDecision(
            operation_id=operation_id, state=state,
            dispatch_allowed=False, automatic_retry_allowed=False,
            human_review_required=bool(events), event_count=len(events), reason=reason,
        )
