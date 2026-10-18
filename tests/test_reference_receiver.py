"""
The reference receiver applies a decision once per idempotency key (N01).

The sender publishes at least once: a process killed after the broker accepted a
decision cannot know it went out, and its Resume publishes it again under the same
key. The receiver turns that into once. The last class runs the Firestore claim
against the emulator and is skipped without it.
"""

from __future__ import annotations

import os
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from reference_receiver import apply_once, firestore_claim  # noqa: E402

FIRESTORE = os.getenv("FIRESTORE_EMULATOR_HOST", "")
PROJECT = "vf-receiver-test"


def _memory_claim():
    seen: set[str] = set()

    def claim(key: str) -> bool:
        if key in seen:
            return False
        seen.add(key)
        return True

    return claim


class TestApplyOnce:
    def test_a_repeat_of_the_same_key_is_not_applied_again(self):
        applied: list[str] = []
        claim = _memory_claim()
        first = apply_once({"idempotency_key": "exec-apr-1"}, claim, lambda: applied.append("a"))
        second = apply_once({"idempotency_key": "exec-apr-1"}, claim, lambda: applied.append("b"))
        assert (first, second) == ("applied", "duplicate")
        assert applied == ["a"]

    def test_another_key_is_applied(self):
        applied: list[str] = []
        claim = _memory_claim()
        apply_once({"idempotency_key": "exec-apr-1"}, claim, lambda: applied.append("1"))
        apply_once({"idempotency_key": "exec-apr-2"}, claim, lambda: applied.append("2"))
        assert applied == ["1", "2"]

    @pytest.mark.parametrize("attributes", [{}, {"idempotency_key": ""}])
    def test_a_decision_without_a_key_is_rejected_not_applied(self, attributes):
        # It cannot be deduplicated, so it is left for a person rather than applied.
        applied: list[str] = []
        assert apply_once(attributes, _memory_claim(), lambda: applied.append("x")) == "rejected"
        assert applied == []


@pytest.mark.skipif(not FIRESTORE, reason="FIRESTORE_EMULATOR_HOST is not set")
class TestTheFirestoreClaim:
    def setup_method(self):
        request = urllib.request.Request(
            f"http://{FIRESTORE}/emulator/v1/projects/{PROJECT}/databases/(default)/documents",
            method="DELETE",
        )
        urllib.request.urlopen(request, timeout=10).close()  # noqa: S310 - local emulator
        from google.cloud import firestore

        self.db = firestore.Client(project=PROJECT)

    def test_only_one_of_many_concurrent_claims_of_a_key_wins(self):
        claim = firestore_claim(self.db)
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(claim, ["exec-apr-1"] * 8))
        assert results.count(True) == 1
        assert claim("exec-apr-2") is True
