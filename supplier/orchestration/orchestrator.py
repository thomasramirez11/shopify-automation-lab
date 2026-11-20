from __future__ import annotations

import hashlib
import json

from supplier.batch.builder import build_batch_safety_manifest
from supplier.batch.models import BatchSafetyPolicy
from supplier.comparison.engine import compare_supplier_to_shopify
from supplier.decision.models import InventorySyncPolicy
from supplier.decision.policy import evaluate_supplier_sync_decision
from supplier.orchestration.models import (
    SupplierOperationsBacklog,
    SupplierOperationsSnapshot,
)
from supplier.orchestration.policy_engine import (
    DEFAULT_CONTROL_PLANE_POLICY,
    evaluate_control_plane_policy,
)
from supplier.plan.builder import build_dry_run_sync_plan


class SupplierOperationsOrchestrator:
    """
    Unified READ-ONLY application layer with configurable operational policy.
    """

    def __init__(
        self,
        *,
        supplier_code: str,
        supplier_adapter,
        mapping_loader,
        snapshot_adapter,
        item_policy: InventorySyncPolicy,
        batch_policy: BatchSafetyPolicy,
        backlog_reader=None,
        control_plane_policy=None,
        policy_history_reader=None,
    ) -> None:
        if (
            not isinstance(
                supplier_code,
                str,
            )
            or not supplier_code.strip()
        ):
            raise ValueError(
                "supplier_code must be a non-empty string."
            )

        self._supplier_code = (
            supplier_code.strip()
        )
        self._supplier_adapter = supplier_adapter
        self._mapping_loader = mapping_loader
        self._snapshot_adapter = snapshot_adapter
        self._item_policy = item_policy
        self._batch_policy = batch_policy
        self._backlog_reader = backlog_reader
        self._control_plane_policy = (
            control_plane_policy
            or DEFAULT_CONTROL_PLANE_POLICY
        )
        self._policy_history_reader = (
            policy_history_reader
        )

    def build_snapshot(
        self,
    ) -> SupplierOperationsSnapshot:
        supplier_products = {
            product.supplier_sku: product
            for product
            in self._supplier_adapter
            .list_products()
        }

        registry = (
            self._mapping_loader
            .load_registry()
        )

        mappings = tuple(
            mapping
            for mapping
            in registry.list_mappings(
                active_only=True
            )
            if (
                mapping.supplier_code
                == self._supplier_code
            )
        )

        decisions = []

        for mapping in mappings:
            supplier_product = (
                supplier_products.get(
                    mapping.supplier_sku
                )
            )

            snapshot = (
                self._snapshot_adapter
                .get_snapshot(
                    mapping.shopify_variant_id
                )
            )

            comparison = (
                compare_supplier_to_shopify(
                    mapping=mapping,
                    supplier_product=(
                        supplier_product
                    ),
                    shopify_variant=(
                        snapshot.shopify_variant
                        if snapshot is not None
                        else None
                    ),
                    stored_cost=(
                        snapshot.stored_cost
                        if snapshot is not None
                        else None
                    ),
                )
            )

            decisions.append(
                evaluate_supplier_sync_decision(
                    comparison=comparison,
                    policy=self._item_policy,
                )
            )

        decision_tuple = tuple(
            decisions
        )

        plan = build_dry_run_sync_plan(
            decision_tuple
        )

        manifest = build_batch_safety_manifest(
            plan=plan,
            policy=self._batch_policy,
        )

        backlog = (
            self._backlog_reader.read()
            if self._backlog_reader
            is not None
            else SupplierOperationsBacklog()
        )

        consecutive = (
            self._policy_history_reader
            .consecutive_human_attention_runs(
                self._supplier_code
            )
            if self._policy_history_reader
            is not None
            else 0
        )

        policy_decision = (
            evaluate_control_plane_policy(
                manifest=manifest,
                backlog=backlog,
                policy=(
                    self._control_plane_policy
                ),
                consecutive_human_attention_runs=(
                    consecutive
                ),
            )
        )

        fingerprint = (
            build_orchestration_fingerprint(
                supplier_code=(
                    self._supplier_code
                ),
                manifest=manifest,
                backlog=backlog,
                posture=(
                    policy_decision.posture
                ),
                next_action=(
                    policy_decision.next_action
                ),
                policy_fingerprint=(
                    policy_decision
                    .policy_fingerprint
                ),
            )
        )

        return SupplierOperationsSnapshot(
            supplier_code=(
                self._supplier_code
            ),
            active_mapping_count=(
                len(mappings)
            ),
            supplier_product_count=(
                len(supplier_products)
            ),
            decisions=decision_tuple,
            plan=plan,
            manifest=manifest,
            backlog=backlog,
            posture=(
                policy_decision.posture
            ),
            next_action=(
                policy_decision.next_action
            ),
            policy_gate_status=(
                policy_decision
                .gate_status.value
            ),
            policy_reasons=tuple(
                reason.value
                for reason
                in policy_decision.reasons
            ),
            policy_fingerprint=(
                policy_decision
                .policy_fingerprint
            ),
            consecutive_human_attention_runs=(
                policy_decision
                .consecutive_human_attention_runs
            ),
            orchestration_fingerprint=(
                fingerprint
            ),
        )


def determine_system_posture(
    *,
    manifest,
    backlog,
):
    """
    Backward-compatible wrapper around the default control-plane policy.
    """

    decision = (
        evaluate_control_plane_policy(
            manifest=manifest,
            backlog=backlog,
            policy=(
                DEFAULT_CONTROL_PLANE_POLICY
            ),
            consecutive_human_attention_runs=0,
        )
    )

    return (
        decision.posture,
        decision.next_action,
    )


def build_orchestration_fingerprint(
    *,
    supplier_code: str,
    manifest,
    backlog,
    posture,
    next_action,
    policy_fingerprint: str = "",
) -> str:
    payload = {
        "supplier_code":
            supplier_code,
        "manifest_fingerprint":
            manifest.manifest_fingerprint,
        "policy_fingerprint":
            policy_fingerprint,
        "backlog": {
            "queued_retry_attempts":
                backlog.queued_retry_attempts,
            "dead_letter_awaiting_human":
                backlog.dead_letter_awaiting_human,
            "dead_letter_acknowledged":
                backlog.dead_letter_acknowledged,
            "resolution_recorded":
                backlog.resolution_recorded,
            "reentry_authorized":
                backlog.reentry_authorized,
            "reentry_started":
                backlog.reentry_started,
            "reentry_failed":
                backlog.reentry_failed,
            "resolution_closed":
                backlog.resolution_closed,
        },
        "posture":
            posture.value,
        "next_action":
            next_action.value,
    }

    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    )

    return hashlib.sha256(
        canonical.encode(
            "utf-8"
        )
    ).hexdigest()
