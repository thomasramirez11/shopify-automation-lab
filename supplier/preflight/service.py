from __future__ import annotations

import hashlib
import json

from supplier.batch.models import (
    BatchSafetyStatus,
)
from supplier.execution.models import (
    SupplierExecutionError,
)
from supplier.plan.models import (
    SyncPlanAction,
)
from supplier.preflight.models import (
    BatchPreflightError,
    BatchPreflightItem,
    BatchPreflightItemStatus,
    BatchPreflightReason,
    BatchPreflightReport,
    BatchPreflightStatus,
)


def evaluate_live_batch_preflight(
    *,
    plan,
    manifest,
    approval_report,
    target_resolver,
    readback_port,
    expected_location_id: str,
) -> BatchPreflightReport:
    """
    Read-only final batch preflight.

    This function never mutates Shopify and never writes SQLite.

    Safety layers:
    1. exact approved manifest
    2. strict plan <-> manifest mutation identity
    3. exact Shopify inventory target + location
    4. fresh live Shopify read
    5. baseline drift detection
    """

    location_id = _normalize_location_id(
        expected_location_id
    )

    structural_reason = (
        _validate_approval_and_identity(
            plan=plan,
            manifest=manifest,
            approval_report=approval_report,
        )
    )

    if structural_reason is not None:
        return _build_report(
            plan=plan,
            manifest=manifest,
            approval_report=approval_report,
            location_id=location_id,
            status=BatchPreflightStatus.BLOCKED,
            reasons=(
                structural_reason,
            ),
            items=(),
        )

    items = []

    for index, mutation in enumerate(
        manifest.mutations,
        start=1,
    ):
        items.append(
            _preflight_one_mutation(
                item_index=index,
                mutation=mutation,
                target_resolver=target_resolver,
                readback_port=readback_port,
                expected_location_id=location_id,
            )
        )

    item_tuple = tuple(
        items
    )

    if any(
        item.status
        == BatchPreflightItemStatus.BLOCKED
        for item in item_tuple
    ):
        status = (
            BatchPreflightStatus.BLOCKED
        )

    elif any(
        item.status
        == BatchPreflightItemStatus.STALE
        for item in item_tuple
    ):
        status = (
            BatchPreflightStatus.STALE
        )

    else:
        status = (
            BatchPreflightStatus.READY
        )

    reasons = _collect_report_reasons(
        items=item_tuple,
        status=status,
    )

    return _build_report(
        plan=plan,
        manifest=manifest,
        approval_report=approval_report,
        location_id=location_id,
        status=status,
        reasons=reasons,
        items=item_tuple,
    )


def validate_plan_manifest_identity(
    *,
    plan,
    manifest,
) -> None:
    """
    Strict ordered identity validation.

    A future live executor must never trust only mutation counts.
    """

    if (
        manifest.source_plan_fingerprint
        != plan.fingerprint
    ):
        raise BatchPreflightError(
            "Manifest source-plan fingerprint does not match the current plan."
        )

    plan_mutations = tuple(
        item
        for item in plan.items
        if (
            item.action
            == SyncPlanAction.SET_INVENTORY
        )
    )

    if len(plan_mutations) != len(
        manifest.mutations
    ):
        raise BatchPreflightError(
            "Plan mutation count does not match manifest mutation count."
        )

    for index, (
        plan_item,
        manifest_item,
    ) in enumerate(
        zip(
            plan_mutations,
            manifest.mutations,
        ),
        start=1,
    ):
        _validate_plan_mutation(
            plan_item,
            index=index,
        )

        expected = (
            plan_item.supplier_sku,
            plan_item.shopify_variant_id,
            plan_item.shopify_sku,
            plan_item.current_inventory_quantity,
            plan_item.proposed_inventory_quantity,
            plan_item.inventory_delta,
        )

        observed = (
            manifest_item.supplier_sku,
            manifest_item.shopify_variant_id,
            manifest_item.shopify_sku,
            manifest_item.current_inventory_quantity,
            manifest_item.proposed_inventory_quantity,
            manifest_item.inventory_delta,
        )

        if expected != observed:
            raise BatchPreflightError(
                "Plan/manifest mutation identity mismatch "
                f"at ordered item #{index}."
            )


def _validate_approval_and_identity(
    *,
    plan,
    manifest,
    approval_report,
):
    if (
        manifest.status
        != BatchSafetyStatus.READY
        or not approval_report.can_execute
    ):
        return (
            BatchPreflightReason
            .APPROVAL_NOT_READY
        )

    if (
        approval_report.current_plan_fingerprint
        != plan.fingerprint
        or approval_report.source_plan_fingerprint
        != manifest.source_plan_fingerprint
    ):
        return (
            BatchPreflightReason
            .SOURCE_PLAN_MISMATCH
        )

    if (
        approval_report.current_manifest_fingerprint
        != manifest.manifest_fingerprint
        or approval_report.approved_manifest_fingerprint
        != manifest.manifest_fingerprint
    ):
        return (
            BatchPreflightReason
            .APPROVAL_NOT_READY
        )

    try:
        validate_plan_manifest_identity(
            plan=plan,
            manifest=manifest,
        )

    except BatchPreflightError:
        return (
            BatchPreflightReason
            .MANIFEST_MUTATION_MISMATCH
        )

    return None


def _preflight_one_mutation(
    *,
    item_index,
    mutation,
    target_resolver,
    readback_port,
    expected_location_id,
):
    target = target_resolver.resolve(
        mutation.shopify_variant_id
    )

    if target is None:
        return _blocked_item(
            item_index=item_index,
            mutation=mutation,
            inventory_item_id=None,
            location_id=expected_location_id,
            reason=(
                BatchPreflightReason
                .TARGET_NOT_RESOLVED
            ),
            error_message=(
                "Could not resolve a Shopify InventoryItem target."
            ),
        )

    if (
        target.location_id
        != expected_location_id
    ):
        return _blocked_item(
            item_index=item_index,
            mutation=mutation,
            inventory_item_id=(
                target.inventory_item_id
            ),
            location_id=(
                target.location_id
            ),
            reason=(
                BatchPreflightReason
                .TARGET_LOCATION_MISMATCH
            ),
            error_message=(
                "Resolved Shopify location does not match the "
                "explicit preflight location."
            ),
        )

    try:
        live = readback_port.read_available(
            inventory_item_id=(
                target.inventory_item_id
            ),
            location_id=(
                expected_location_id
            ),
        )

    except SupplierExecutionError as exc:
        return _blocked_item(
            item_index=item_index,
            mutation=mutation,
            inventory_item_id=(
                target.inventory_item_id
            ),
            location_id=(
                expected_location_id
            ),
            reason=(
                BatchPreflightReason
                .LIVE_READ_FAILED
            ),
            error_message=str(
                exc
            ),
        )

    blocking_reasons = []

    if (
        live.sku is None
        or live.sku
        != mutation.shopify_sku
    ):
        blocking_reasons.append(
            BatchPreflightReason
            .SKU_MISMATCH
        )

    if not live.tracked:
        blocking_reasons.append(
            BatchPreflightReason
            .INVENTORY_NOT_TRACKED
        )

    if not live.location_active:
        blocking_reasons.append(
            BatchPreflightReason
            .LOCATION_INACTIVE
        )

    if not live.level_active:
        blocking_reasons.append(
            BatchPreflightReason
            .INVENTORY_LEVEL_INACTIVE
        )

    if blocking_reasons:
        return BatchPreflightItem(
            item_index=item_index,
            supplier_sku=(
                mutation.supplier_sku
            ),
            shopify_variant_id=(
                mutation.shopify_variant_id
            ),
            shopify_sku=(
                mutation.shopify_sku
            ),
            inventory_item_id=(
                target.inventory_item_id
            ),
            location_id=(
                expected_location_id
            ),
            approved_baseline_quantity=(
                mutation.current_inventory_quantity
            ),
            fresh_shopify_quantity=(
                live.available_quantity
            ),
            proposed_inventory_quantity=(
                mutation.proposed_inventory_quantity
            ),
            inventory_delta=(
                mutation.inventory_delta
            ),
            status=(
                BatchPreflightItemStatus
                .BLOCKED
            ),
            reasons=tuple(
                blocking_reasons
            ),
        )

    if (
        live.available_quantity
        != mutation.current_inventory_quantity
    ):
        return BatchPreflightItem(
            item_index=item_index,
            supplier_sku=(
                mutation.supplier_sku
            ),
            shopify_variant_id=(
                mutation.shopify_variant_id
            ),
            shopify_sku=(
                mutation.shopify_sku
            ),
            inventory_item_id=(
                target.inventory_item_id
            ),
            location_id=(
                expected_location_id
            ),
            approved_baseline_quantity=(
                mutation.current_inventory_quantity
            ),
            fresh_shopify_quantity=(
                live.available_quantity
            ),
            proposed_inventory_quantity=(
                mutation.proposed_inventory_quantity
            ),
            inventory_delta=(
                mutation.inventory_delta
            ),
            status=(
                BatchPreflightItemStatus.STALE
            ),
            reasons=(
                BatchPreflightReason
                .BASELINE_DRIFT,
            ),
        )

    return BatchPreflightItem(
        item_index=item_index,
        supplier_sku=(
            mutation.supplier_sku
        ),
        shopify_variant_id=(
            mutation.shopify_variant_id
        ),
        shopify_sku=(
            mutation.shopify_sku
        ),
        inventory_item_id=(
            target.inventory_item_id
        ),
        location_id=(
            expected_location_id
        ),
        approved_baseline_quantity=(
            mutation.current_inventory_quantity
        ),
        fresh_shopify_quantity=(
            live.available_quantity
        ),
        proposed_inventory_quantity=(
            mutation.proposed_inventory_quantity
        ),
        inventory_delta=(
            mutation.inventory_delta
        ),
        status=(
            BatchPreflightItemStatus.READY
        ),
        reasons=(
            BatchPreflightReason.READY,
        ),
    )


def _blocked_item(
    *,
    item_index,
    mutation,
    inventory_item_id,
    location_id,
    reason,
    error_message,
):
    return BatchPreflightItem(
        item_index=item_index,
        supplier_sku=(
            mutation.supplier_sku
        ),
        shopify_variant_id=(
            mutation.shopify_variant_id
        ),
        shopify_sku=(
            mutation.shopify_sku
        ),
        inventory_item_id=(
            inventory_item_id
        ),
        location_id=(
            location_id
        ),
        approved_baseline_quantity=(
            mutation.current_inventory_quantity
        ),
        fresh_shopify_quantity=None,
        proposed_inventory_quantity=(
            mutation.proposed_inventory_quantity
        ),
        inventory_delta=(
            mutation.inventory_delta
        ),
        status=(
            BatchPreflightItemStatus.BLOCKED
        ),
        reasons=(
            reason,
        ),
        error_message=(
            error_message
        ),
    )


def _validate_plan_mutation(
    item,
    *,
    index,
):
    values = (
        item.current_inventory_quantity,
        item.proposed_inventory_quantity,
        item.inventory_delta,
    )

    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        for value in values
    ):
        raise BatchPreflightError(
            "Malformed SET_INVENTORY plan mutation "
            f"at ordered item #{index}."
        )

    if (
        item.proposed_inventory_quantity
        - item.current_inventory_quantity
        != item.inventory_delta
    ):
        raise BatchPreflightError(
            "Inconsistent SET_INVENTORY delta "
            f"at ordered item #{index}."
        )

    if item.inventory_delta == 0:
        raise BatchPreflightError(
            "Zero-delta SET_INVENTORY mutation "
            f"at ordered item #{index}."
        )


def _normalize_location_id(
    value,
):
    if (
        not isinstance(value, str)
        or not value.strip().startswith(
            "gid://shopify/Location/"
        )
    ):
        raise BatchPreflightError(
            "expected_location_id must be a Shopify Location GID."
        )

    return value.strip()


def _collect_report_reasons(
    *,
    items,
    status,
):
    if (
        status
        == BatchPreflightStatus.READY
    ):
        return (
            BatchPreflightReason.READY,
        )

    unique = []

    for item in items:
        for reason in item.reasons:
            if (
                reason
                not in unique
            ):
                unique.append(
                    reason
                )

    return tuple(
        unique
    )


def _build_report(
    *,
    plan,
    manifest,
    approval_report,
    location_id,
    status,
    reasons,
    items,
):
    fingerprint = (
        _build_preflight_fingerprint(
            plan=plan,
            manifest=manifest,
            approval_report=(
                approval_report
            ),
            location_id=(
                location_id
            ),
            status=status,
            reasons=reasons,
            items=items,
        )
    )

    return BatchPreflightReport(
        status=status,
        reasons=reasons,
        source_plan_fingerprint=(
            plan.fingerprint
        ),
        manifest_fingerprint=(
            manifest.manifest_fingerprint
        ),
        approved_manifest_fingerprint=(
            approval_report
            .approved_manifest_fingerprint
        ),
        location_id=location_id,
        preflight_fingerprint=(
            fingerprint
        ),
        items=items,
    )


def _build_preflight_fingerprint(
    *,
    plan,
    manifest,
    approval_report,
    location_id,
    status,
    reasons,
    items,
):
    payload = {
        "source_plan_fingerprint":
            plan.fingerprint,
        "manifest_fingerprint":
            manifest.manifest_fingerprint,
        "approved_manifest_fingerprint":
            approval_report
            .approved_manifest_fingerprint,
        "location_id":
            location_id,
        "status":
            status.value,
        "reasons": [
            reason.value
            for reason in reasons
        ],
        "items": [
            {
                "item_index":
                    item.item_index,
                "supplier_sku":
                    item.supplier_sku,
                "shopify_variant_id":
                    item.shopify_variant_id,
                "shopify_sku":
                    item.shopify_sku,
                "inventory_item_id":
                    item.inventory_item_id,
                "location_id":
                    item.location_id,
                "approved_baseline_quantity":
                    item.approved_baseline_quantity,
                "fresh_shopify_quantity":
                    item.fresh_shopify_quantity,
                "proposed_inventory_quantity":
                    item.proposed_inventory_quantity,
                "inventory_delta":
                    item.inventory_delta,
                "status":
                    item.status.value,
                "reasons": [
                    reason.value
                    for reason
                    in item.reasons
                ],
                "error_message":
                    item.error_message,
            }
            for item in items
        ],
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
