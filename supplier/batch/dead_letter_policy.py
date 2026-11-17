from __future__ import annotations

import hashlib

from supplier.batch.dead_letter_models import (
    DeadLetterCandidate,
)


def build_dead_letter_case_id(
    candidate: DeadLetterCandidate,
) -> str:
    """
    Deterministic case identity.

    The same failed operation can never silently become multiple human cases.
    """

    payload = (
        "supplier-dead-letter:"
        + candidate.source_retry_id
    )

    return hashlib.sha256(
        payload.encode(
            "utf-8"
        )
    ).hexdigest()
