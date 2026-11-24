"""V2.8B/5: conservative classification of a Shopify mutation *response*.

A GraphQL acknowledgment is NOT evidence that both inventory items currently
match the target. Only a later, independent readback can establish that state.
No I/O or credential handling happens here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class SimulatedResponseStatus(str, Enum):
    ACKNOWLEDGED_NEEDS_READBACK = "ACKNOWLEDGED_NEEDS_READBACK"
    USER_ERRORS_REQUIRE_REVIEW = "USER_ERRORS_REQUIRE_REVIEW"
    UNKNOWN_REQUIRES_REVIEW = "UNKNOWN_REQUIRES_REVIEW"


@dataclass(frozen=True, slots=True)
class ResponseAssessment:
    status: SimulatedResponseStatus
    reason_code: str
    automatic_retry_allowed: bool = False
    inventory_verified: bool = False


def _unknown(reason_code: str) -> ResponseAssessment:
    return ResponseAssessment(SimulatedResponseStatus.UNKNOWN_REQUIRES_REVIEW, reason_code)


def classify_shopify_response(response: Any, *, expected_reference_uri: str) -> ResponseAssessment:
    """Recognize Shopify data envelopes AND the existing ShopifyClient's unwrapped data.

    This parser is deliberately conservative: any unknown or contradictory
    envelope results in human review. No raw error/message text is persisted.
    Shopify can report multiple inventory-state changes (e.g. available and
    on_hand) with null quantityAfterChange; we do not infer per-SKU success
    from the adjustment list.
    """
    if not isinstance(expected_reference_uri, str) or not expected_reference_uri.startswith(
        "shopify-automation-lab://v2/operations/"
    ):
        return _unknown("INVALID_EXPECTED_IDENTITY")
    if not isinstance(response, dict):
        return _unknown("NON_OBJECT_RESPONSE")
    if response.get("errors"):
        return _unknown("TOP_LEVEL_GRAPHQL_ERRORS")
    if "errors" in response and response["errors"] not in (None, []):
        return _unknown("INVALID_GRAPHQL_ERRORS_FIELD")

    if "data" in response:
        if "inventorySetQuantities" in response:
            return _unknown("AMBIGUOUS_ENVELOPE")
        data = response["data"]
        if not isinstance(data, dict):
            return _unknown("INVALID_DATA")
    else:
        data = response  # ShopifyClient.graphql returns its unwrapped `data`.

    payload = data.get("inventorySetQuantities")
    if not isinstance(payload, dict):
        return _unknown("MISSING_MUTATION_PAYLOAD")
    errors = payload.get("userErrors")
    if not isinstance(errors, list):
        return _unknown("INVALID_USER_ERRORS")
    for item in errors:
        if (not isinstance(item, dict)
                or not isinstance(item.get("message"), str)
                or not item["message"].strip()
                or (item.get("code") is not None and not isinstance(item["code"], str))):
            return _unknown("MALFORMED_USER_ERROR")
    group = payload.get("inventoryAdjustmentGroup")
    if errors:
        # A contradictory group + userErrors may reflect a partially evaluated
        # response. Do not assert rejection is proof that no write occurred.
        if group is not None:
            return _unknown("CONTRADICTORY_MUTATION_RESPONSE")
        return ResponseAssessment(
            SimulatedResponseStatus.USER_ERRORS_REQUIRE_REVIEW,
            "EXPLICIT_SHOPIFY_USER_ERRORS",
        )
    if not isinstance(group, dict):
        return _unknown("MISSING_ADJUSTMENT_GROUP")
    if group.get("referenceDocumentUri") != expected_reference_uri:
        return _unknown("REFERENCE_URI_MISMATCH")
    if not isinstance(group.get("reason"), str) or not group["reason"].strip():
        return _unknown("INVALID_ADJUSTMENT_REASON")
    changes = group.get("changes")
    if not isinstance(changes, list) or not changes:
        return _unknown("MISSING_ADJUSTMENT_CHANGES")
    for change in changes:
        if (not isinstance(change, dict)
                or not isinstance(change.get("name"), str)
                or not change["name"].strip()
                or type(change.get("delta")) is not int
                or (change.get("quantityAfterChange") is not None
                    and (type(change["quantityAfterChange"]) is not int
                         or change["quantityAfterChange"] < 0))):
            return _unknown("MALFORMED_ADJUSTMENT_CHANGE")
    if not any(change["name"] == "available" for change in changes):
        return _unknown("AVAILABLE_CHANGE_NOT_REPORTED")
    return ResponseAssessment(
        SimulatedResponseStatus.ACKNOWLEDGED_NEEDS_READBACK,
        "SHOPIFY_ACKNOWLEDGED_READBACK_REQUIRED",
    )
