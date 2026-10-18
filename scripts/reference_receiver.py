"""
Reference receiver for the case-decisions topic: each approval is applied at most once.

The sender publishes at least once. A process killed after the broker accepted a
decision but before the sender saved that fact cannot know the decision went out, so
its Resume publishes it again with the same idempotency_key attribute (N01). The
repeat is harmless only if the receiver claims the key before it applies the decision.
This module is that contract, as code the hard-kill simulation
(tests/test_sim_hard_kill.py) runs against the Pub/Sub and Firestore emulators.

A real receiver must claim and apply in one transaction: a claim followed by a crash
before the apply would lose the decision. Here the apply is a callable so the
contract can be tested on its own.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


def apply_once(
    attributes: Mapping[str, str], claim: Callable[[str], bool], apply: Callable[[], None],
) -> str:
    """
    Apply one delivered decision unless its key was claimed before.

    Returns "applied", "duplicate", or "rejected" for a message without a key: such a
    message cannot be deduplicated, so it is left for a person rather than applied.
    """
    key = attributes.get("idempotency_key", "")
    if not key:
        return "rejected"
    if not claim(key):
        return "duplicate"
    apply()
    return "applied"


def firestore_claim(db: Any, collection: str = "applied_decisions") -> Callable[[str], bool]:
    """A claim backed by Firestore create(): only the first caller for a key succeeds."""
    from google.api_core.exceptions import AlreadyExists

    def claim(key: str) -> bool:
        try:
            db.collection(collection).document(key).create({"key": key})
        except AlreadyExists:
            return False
        return True

    return claim
