from __future__ import annotations

import hashlib
import json

from supplier.batch.case_resolution_models import (
    AcknowledgedDeadLetterCase,
    ResolutionCode,
)


def build_resolution_fingerprint(
    *,
    case: AcknowledgedDeadLetterCase,
    resolution_code: ResolutionCode,
    actor: str,
    note: str,
) -> str:
    """
    Freeze the exact human resolution statement and target into one approval
    fingerprint.

    Any change to the case, quantity, resolution code, actor, or note creates
    a different fingerprint and invalidates an old approval.
    """

    payload = {
        "case_id": case.case_id,
        "source_retry_id":
            case.source_retry_id,
        "source_batch_id":
            case.source_batch_id,
        "operation_id":
            case.operation_id,
        "shopify_variant_id":
            case.shopify_variant_id,
        "shopify_sku":
            case.shopify_sku,
        "requested_quantity":
            case.requested_quantity,
        "reason_code":
            case.reason_code,
        "resolution_code":
            resolution_code.value,
        "actor":
            actor.strip(),
        "note":
            note.strip(),
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
