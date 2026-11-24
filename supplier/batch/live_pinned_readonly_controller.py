"""V2.8B/11: one shop-pinned, strictly READ-ONLY live candidate controller.

A single authenticated client is used for fixed shop-identity queries and the
existing allowlisted inventory readback query. The shop is checked *before and
after* four inventory reads (two preflight, two independent rechecks).

A successful result is evidence for further human review only. It cannot arm,
authorize, persist, or send Shopify inventory mutations. No SQLite writes.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from enum import Enum
from typing import Any

from supplier.batch.live_preflight_bridge import prepare_from_fresh_preflight
from supplier.batch.live_readonly_inspection import InspectionStatus, inspect_fresh_candidate
from supplier.batch.live_readonly_query_fence import (
    ReadOnlyQueryRejected, ReadOnlyShopifyQueryFence,
)
from supplier.batch.live_request_contract import LOCATION_GID_RE
from supplier.batch.live_store_identity import (
    SHOP_GID_RE, ShopifyStoreIdentityReadOnly, StoreIdentityRejected,
    VerifiedShopIdentity,
)
from supplier.execution.readback import ShopifyInventoryReadbackAdapter


class PinnedReadOnlyStatus(str, Enum):
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    INVALID_SCOPE = "INVALID_SCOPE"
    SHOP_UNAVAILABLE_OR_MISMATCH = "SHOP_UNAVAILABLE_OR_MISMATCH"
    PREFLIGHT_BLOCKED = "PREFLIGHT_BLOCKED"
    SECOND_READ_BLOCKED = "SECOND_READ_BLOCKED"
    INVENTORY_STALE = "INVENTORY_STALE"
    SHOP_CHANGED_DURING_REVIEW = "SHOP_CHANGED_DURING_REVIEW"
    BASELINES_MATCH = "BASELINES_MATCH"


@dataclass(frozen=True, slots=True)
class PinnedReadOnlyReport:
    status: PinnedReadOnlyStatus
    shop_id: str | None = None
    shop_domain: str | None = None
    plan_fingerprint: str | None = None
    manifest_fingerprint: str | None = None
    inspection_fingerprint: str | None = None
    inventory_reads: int = 0
    shop_identity_reads: int = 0
    inspected_items: tuple[tuple[str, int, int, int], ...] = ()
    can_continue_to_operator_review: bool = False
    live_execution_allowed: bool = False
    automatic_retry_allowed: bool = False
    operator_authenticated: bool = False


class PinnedReadOnlySession:
    """Small allowlisted GraphQL surface with an enforced read-only lifecycle.

    - First read: authenticated, pinned shop identity.
    - Then: at most four validated inventory queries.
    - Final read: authenticated shop identity *after* the inventory reads.
    - Afterwards: closed; all further queries rejected.
    
    No arbitrary GraphQL is passed through this adapter. ShopifyClient may
    itself have write features; nothing here calls or exposes a write method.
    """

    def __init__(self, client: Any, *, expected_shop_id: str) -> None:
        if type(expected_shop_id) is not str or SHOP_GID_RE.fullmatch(expected_shop_id) is None:
            raise StoreIdentityRejected("expected Shop GID must be independently pinned")
        self._identity_reader = ShopifyStoreIdentityReadOnly(client)
        self._inventory_fence = ReadOnlyShopifyQueryFence(client)
        self._expected_shop_id = expected_shop_id
        self._before: VerifiedShopIdentity | None = None
        self._state = "NEED_INITIAL_IDENTITY"

    @property
    def inventory_reads(self) -> int:
        return self._inventory_fence.read_queries

    @property
    def identity_reads(self) -> int:
        return self._identity_reader.read_queries

    @property
    def before(self) -> VerifiedShopIdentity | None:
        return self._before

    def verify_shop_before(self) -> VerifiedShopIdentity:
        if self._state != "NEED_INITIAL_IDENTITY":
            raise ReadOnlyQueryRejected("shop identity cannot be re-initialized")
        self._state = "BLOCKED"
        identity = self._identity_reader.read()
        if not hmac.compare_digest(identity.shop_id, self._expected_shop_id):
            raise StoreIdentityRejected("authenticated shop ID does not match pinned shop")
        self._before = identity
        self._state = "INVENTORY_READS"
        return identity

    def graphql(self, query: str, variables: dict | None = None) -> dict:
        if self._state != "INVENTORY_READS" or self.inventory_reads >= 4:
            raise ReadOnlyQueryRejected("read-only session is not accepting inventory queries")
        # The existing inventory fence independently checks the exact GraphQL
        # query, the two exact GID variables, and strict Shopify Boolean fields.
        return self._inventory_fence.graphql(query, variables)

    def verify_shop_after(self) -> VerifiedShopIdentity:
        if self._state != "INVENTORY_READS" or self.inventory_reads != 4 or self._before is None:
            raise ReadOnlyQueryRejected("four verified inventory reads are required")
        # Close *before* network I/O so a failure can never reopen the session.
        self._state = "CLOSED"
        identity = self._identity_reader.read()
        if (not hmac.compare_digest(identity.shop_id, self._before.shop_id)
                or not hmac.compare_digest(identity.domain, self._before.domain)):
            raise StoreIdentityRejected("authenticated shop identity changed during inspection")
        return identity


def inspect_pinned_live_candidate(
    *, client: Any, expected_shop_id: str, expected_location_id: str,
    plan: Any, manifest: Any, approval_report: Any, target_resolver: Any,
) -> PinnedReadOnlyReport:
    """Run one whole shop-bound read-only controller for two synthetic targets.

    Precondition failures contact no Shopify API. Positive results do not
    authorize execution or authenticate any operator. No project DB writes.
    """
    if not approval_report or getattr(approval_report, "can_execute", None) is not True:
        return PinnedReadOnlyReport(PinnedReadOnlyStatus.APPROVAL_REQUIRED)
    if (type(expected_shop_id) is not str or SHOP_GID_RE.fullmatch(expected_shop_id) is None
            or type(expected_location_id) is not str
            or LOCATION_GID_RE.fullmatch(expected_location_id) is None):
        return PinnedReadOnlyReport(PinnedReadOnlyStatus.INVALID_SCOPE)
    session: PinnedReadOnlySession | None = None
    try:
        session = PinnedReadOnlySession(client, expected_shop_id=expected_shop_id)
        first = session.verify_shop_before()
    except Exception:
        # Count attempted authenticated reads even on mismatch or timeout.
        # Never include raw Shopify exception text or an untrusted Shop ID.
        return PinnedReadOnlyReport(
            PinnedReadOnlyStatus.SHOP_UNAVAILABLE_OR_MISMATCH,
            shop_identity_reads=session.identity_reads if session else 0,
            inventory_reads=session.inventory_reads if session else 0,
        )

    def result(status: PinnedReadOnlyStatus, *, fingerprint: str | None = None,
               items: tuple[tuple[str, int, int, int], ...] = (),
               review: bool = False) -> PinnedReadOnlyReport:
        return PinnedReadOnlyReport(
            status, shop_id=first.shop_id, shop_domain=first.domain,
            plan_fingerprint=getattr(plan, "fingerprint", None),
            manifest_fingerprint=getattr(manifest, "manifest_fingerprint", None),
            inspection_fingerprint=fingerprint,
            inventory_reads=session.inventory_reads,
            shop_identity_reads=session.identity_reads,
            inspected_items=items, can_continue_to_operator_review=review,
        )

    port = ShopifyInventoryReadbackAdapter(session)
    try:
        prepared = prepare_from_fresh_preflight(
            plan=plan, manifest=manifest, approval_report=approval_report,
            target_resolver=target_resolver, readback_port=port,
            expected_location_id=expected_location_id,
        )
    except Exception:
        return result(PinnedReadOnlyStatus.PREFLIGHT_BLOCKED)
    try:
        inspected = inspect_fresh_candidate(prepared, readback_port=port)
    except Exception:
        return result(PinnedReadOnlyStatus.SECOND_READ_BLOCKED)
    if inspected.status is InspectionStatus.BLOCKED:
        return result(PinnedReadOnlyStatus.SECOND_READ_BLOCKED)
    if inspected.status is not InspectionStatus.BASELINES_MATCH or not inspected.can_continue_to_operator_review:
        return result(PinnedReadOnlyStatus.INVENTORY_STALE)

    # Check shop identity again after all four reads. This is a consistency
    # check, NOT an atomic transaction or authorization to write to Shopify.
    try:
        second = session.verify_shop_after()
    except Exception:
        return result(PinnedReadOnlyStatus.SHOP_CHANGED_DURING_REVIEW)

    if session.inventory_reads != 4 or session.identity_reads != 2 or len(inspected.items) != 2:
        return result(PinnedReadOnlyStatus.SECOND_READ_BLOCKED)
    items = tuple((item.sku, item.baseline, item.observed, item.proposed)
                  for item in inspected.items)
    if any(baseline != observed for _, baseline, observed, _ in items):
        return result(PinnedReadOnlyStatus.INVENTORY_STALE)

    canonical = json.dumps({
        "kind": "V2.8B11_READ_ONLY_SHOP_BOUND_REVIEW",
        "shop_id": second.shop_id,
        "shop_domain": second.domain,
        "location_id": expected_location_id,
        "plan_fingerprint": prepared.plan_fingerprint,
        "manifest_fingerprint": prepared.manifest_fingerprint,
        "preflight_fingerprint": prepared.preflight_fingerprint,
        "request_digest": prepared.request_digest,
        "items": items,
    }, sort_keys=True, separators=(",", ":"))
    fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return result(PinnedReadOnlyStatus.BASELINES_MATCH, fingerprint=fingerprint,
                  items=items, review=True)
