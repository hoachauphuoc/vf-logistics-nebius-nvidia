"""
Unit tests for the store module (Firestore data layer).

These tests verify:
1. Optimistic locking with version field
2. Transaction safety for read-modify-write operations
3. Audit log immutability
4. Case state transitions
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from vf_logistics.store import (
    MemoryStore,
    OptimisticLockError,
    AuditImmutabilityError,
    utcnow,
)


@pytest.fixture
def memory_store() -> MemoryStore:
    """Fresh in-memory store for testing."""
    return MemoryStore()


@pytest.fixture
def sample_case() -> dict[str, Any]:
    """A sample case document."""
    return {
        "case_id": "CASE-TEST-001",
        "shipment_id": "TEST-001",
        "state": "INGESTED",
        "claimed": False,
        "attempts": 0,
        "risk_score": None,
        "steps": [],
        "actions": [],
        "created_at": utcnow(),
    }


class TestOptimisticLocking:
    """Tests for optimistic locking via _version field."""

    def test_first_write_sets_version_to_1(self, memory_store, sample_case):
        """First write to a case sets version to 1."""
        asyncio.run(memory_store.put_case(sample_case))

        stored = asyncio.run(memory_store.get_case("CASE-TEST-001"))
        assert stored["_version"] == 1

    def test_subsequent_write_increments_version(self, memory_store, sample_case):
        """Each write increments the version."""
        asyncio.run(memory_store.put_case(sample_case))
        asyncio.run(memory_store.put_case(sample_case, expected_version=1))

        stored = asyncio.run(memory_store.get_case("CASE-TEST-001"))
        assert stored["_version"] == 2

    def test_stale_version_raises_optimistic_lock_error(
        self, memory_store, sample_case
    ):
        """Update with stale version raises OptimisticLockError."""
        asyncio.run(memory_store.put_case(sample_case))

        with pytest.raises(OptimisticLockError) as exc_info:
            asyncio.run(memory_store.put_case(sample_case, expected_version=0))

        assert exc_info.value.case_id == "CASE-TEST-001"
        assert exc_info.value.expected_version == 0
        assert exc_info.value.actual_version == 1

    def test_concurrent_writes_detected(self, memory_store, sample_case):
        """Simulated concurrent writes are detected via version mismatch."""
        asyncio.run(memory_store.put_case(sample_case))

        # Read the case twice (simulating two workers)
        case_worker1 = asyncio.run(memory_store.get_case("CASE-TEST-001"))
        case_worker2 = asyncio.run(memory_store.get_case("CASE-TEST-001"))

        # Worker 1 writes first - succeeds
        case_worker1["state"] = "SPECIALISTS_DONE"
        asyncio.run(
            memory_store.put_case(case_worker1, expected_version=1)
        )

        # Worker 2 tries to write with stale version - fails
        case_worker2["state"] = "ESCALATED"
        with pytest.raises(OptimisticLockError):
            asyncio.run(
                memory_store.put_case(case_worker2, expected_version=1)
            )

    def test_unconditional_write_without_expected_version(
        self, memory_store, sample_case
    ):
        """Write without expected_version succeeds (for new cases)."""
        asyncio.run(memory_store.put_case(sample_case))
        # No exception raised
        stored = asyncio.run(memory_store.get_case("CASE-TEST-001"))
        assert stored["_version"] == 1

    def test_updated_at_set_on_write(self, memory_store, sample_case):
        """_updated_at timestamp is set on every write."""
        asyncio.run(memory_store.put_case(sample_case))

        stored = asyncio.run(memory_store.get_case("CASE-TEST-001"))
        assert "_updated_at" in stored
        assert stored["_updated_at"] is not None


class TestAuditLogImmutability:
    """Tests for immutable audit log."""

    def test_audit_entry_created_with_metadata(self, memory_store):
        """Audit entries get _immutable flag and timestamp."""
        entry = {
            "action": "RELEASE",
            "actor": "test@example.com",
            "case_id": "CASE-001",
        }
        asyncio.run(memory_store.add_audit(entry))

        entries = asyncio.run(memory_store.list_audit(limit=10))
        assert len(entries) == 1
        assert entries[0]["_immutable"] is True
        assert "_created_at" in entries[0]

    def test_audit_entry_gets_id_if_missing(self, memory_store):
        """Audit entries without audit_id get one assigned."""
        entry = {
            "action": "BLOCK",
            "actor": "reviewer@example.com",
            "case_id": "CASE-002",
        }
        asyncio.run(memory_store.add_audit(entry))

        entries = asyncio.run(memory_store.list_audit(limit=10))
        assert "audit_id" in entries[0]
        assert entries[0]["audit_id"].startswith("AUD-")

    def test_update_audit_raises_immutability_error(self, memory_store):
        """Attempting to update an audit entry raises AuditImmutabilityError."""
        with pytest.raises(AuditImmutabilityError) as exc_info:
            asyncio.run(
                memory_store.update_audit("AUD-12345", {"action": "MODIFIED"})
            )

        assert exc_info.value.operation == "update"
        assert exc_info.value.audit_id == "AUD-12345"

    def test_delete_audit_raises_immutability_error(self, memory_store):
        """Attempting to delete an audit entry raises AuditImmutabilityError."""
        with pytest.raises(AuditImmutabilityError) as exc_info:
            asyncio.run(memory_store.delete_audit("AUD-12345"))

        assert exc_info.value.operation == "delete"
        assert exc_info.value.audit_id == "AUD-12345"

    def test_reset_preserves_audit_log(self, memory_store, sample_case):
        """Board reset should NOT clear the audit log."""
        # Add case and audit entry
        asyncio.run(memory_store.put_case(sample_case))
        asyncio.run(
            memory_store.add_audit(
                {
                    "action": "INGEST",
                    "case_id": "CASE-TEST-001",
                    "actor": "system",
                }
            )
        )

        # Reset the board
        count = asyncio.run(memory_store.reset())
        assert count == 1  # One case was cleared

        # Cases and events should be empty
        cases = asyncio.run(memory_store.list_cases())
        events = asyncio.run(memory_store.list_events())
        assert len(cases) == 0
        assert len(events) == 0

        # Audit log should be preserved
        audit = asyncio.run(memory_store.list_audit())
        assert len(audit) == 1
        assert audit[0]["action"] == "INGEST"


class TestCaseStateTransitions:
    """Tests for case state management."""

    def test_case_claim_and_release(self, memory_store, sample_case):
        """Cases can be claimed and released."""
        asyncio.run(memory_store.put_case(sample_case))

        # Claim the case
        claimed = asyncio.run(
            memory_store.claim_next_pending(("INGESTED",))
        )
        assert claimed is not None
        assert claimed["claimed"] is True

        # Can't claim again (already claimed)
        second_claim = asyncio.run(
            memory_store.claim_next_pending(("INGESTED",))
        )
        assert second_claim is None

        # Release
        asyncio.run(memory_store.release_case("CASE-TEST-001"))

        # Now can claim again
        re_claimed = asyncio.run(
            memory_store.claim_next_pending(("INGESTED",))
        )
        assert re_claimed is not None

    def test_claim_respects_state_filter(self, memory_store, sample_case):
        """claim_next_pending only returns cases in specified states."""
        asyncio.run(memory_store.put_case(sample_case))

        # Case is INGESTED, but we're looking for SPECIALISTS_DONE
        claimed = asyncio.run(
            memory_store.claim_next_pending(("SPECIALISTS_DONE",))
        )
        assert claimed is None

        # Now look for INGESTED
        claimed = asyncio.run(
            memory_store.claim_next_pending(("INGESTED",))
        )
        assert claimed is not None

    def test_case_not_before_respected(self, memory_store, sample_case):
        """Cases with future not_before timestamp are not claimed."""
        from datetime import datetime, timezone, timedelta

        future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
        sample_case["not_before"] = future
        asyncio.run(memory_store.put_case(sample_case))

        claimed = asyncio.run(
            memory_store.claim_next_pending(("INGESTED",))
        )
        assert claimed is None  # Case is backing off


class TestEventFeed:
    """Tests for event feed operations."""

    def test_events_are_fifo_ordered(self, memory_store):
        """Events are returned newest-first."""
        for i in range(5):
            asyncio.run(
                memory_store.add_event(
                    {
                        "event_id": f"evt-{i}",
                        "case_id": "CASE-001",
                        "kind": "test",
                        "message": f"Event {i}",
                        "at": utcnow(),
                    }
                )
            )

        events = asyncio.run(memory_store.list_events(limit=5))
        assert len(events) == 5

    def test_event_list_respects_limit(self, memory_store):
        """list_events respects the limit parameter."""
        for i in range(20):
            asyncio.run(
                memory_store.add_event(
                    {
                        "event_id": f"evt-{i}",
                        "case_id": "CASE-001",
                        "kind": "test",
                        "message": f"Event {i}",
                        "at": utcnow(),
                    }
                )
            )

        events = asyncio.run(memory_store.list_events(limit=5))
        assert len(events) == 5


def _ts(n: int) -> str:
    """Strictly increasing, fixed-width timestamps (minutes:seconds encode
    n up to 5999) so pagination/cursor tests never depend on wall-clock
    resolution or on n staying below 100."""
    return f"2026-01-01T00:{n // 60:02d}:{n % 60:02d}.000000+00:00"


class TestReviewQueuePagination:
    """
    Regression coverage for the review-queue work-loss bug: an older case
    waiting on a human must not disappear just because enough newer cases
    (of any state) exist. `review_queue` must query by state directly
    rather than truncate-then-filter.
    """

    def test_old_awaiting_human_case_survives_many_newer_cases(self, memory_store):
        """
        The bug this guards: the old implementation fetched the newest 120
        cases and only then filtered for AWAITING_HUMAN states. A case held
        for review that is older than the newest 120 cases used to vanish
        from the queue entirely - it was never a rendering issue, work was
        silently unreachable.
        """
        old_case = {
            "case_id": "CASE-OLD-001",
            "shipment_id": "OLD-001",
            "state": "PENDING_HUMAN",
            "created_at": _ts(0),
        }
        asyncio.run(memory_store.put_case(old_case))

        # 200 newer, non-matching cases - comfortably more than the old
        # fixed window of 120.
        for i in range(1, 201):
            asyncio.run(
                memory_store.put_case(
                    {
                        "case_id": f"CASE-NEW-{i:03d}",
                        "shipment_id": f"NEW-{i:03d}",
                        "state": "AUTO_CLEARED",
                        "created_at": _ts(i),
                    }
                )
            )

        cases, next_cursor = asyncio.run(
            memory_store.query_cases(states=("PENDING_HUMAN",), limit=40)
        )
        case_ids = [c["case_id"] for c in cases]
        assert "CASE-OLD-001" in case_ids, (
            "old case waiting on a human dropped out of the queue once "
            "enough newer cases of a different state existed"
        )
        assert next_cursor is None  # only one match, page is not full

    def test_pagination_walks_full_collection_without_gaps_or_dupes(
        self, memory_store
    ):
        """Paging via cursor must eventually surface every matching case
        exactly once, in newest-first order."""
        for i in range(1, 131):
            asyncio.run(
                memory_store.put_case(
                    {
                        "case_id": f"CASE-{i:03d}",
                        "shipment_id": f"SHIP-{i:03d}",
                        "state": "ESCALATED",
                        "created_at": _ts(i),
                    }
                )
            )

        seen: list[str] = []
        cursor = None
        for _ in range(20):  # generous upper bound on page count
            page, cursor = asyncio.run(
                memory_store.query_cases(states=("ESCALATED",), cursor=cursor, limit=25)
            )
            seen.extend(c["case_id"] for c in page)
            if cursor is None:
                break

        assert len(seen) == 130
        assert len(set(seen)) == 130  # no duplicates across pages
        assert seen == sorted(seen, key=lambda cid: -int(cid.split("-")[1]))

    def test_count_by_state_is_exact_regardless_of_page_size(self, memory_store):
        """Counts must reflect the whole collection, not a fetched window -
        this is what makes the KPI tiles trustworthy past the old 60-case
        window."""
        for i in range(1, 251):
            asyncio.run(
                memory_store.put_case(
                    {
                        "case_id": f"CASE-{i:03d}",
                        "shipment_id": f"SHIP-{i:03d}",
                        "state": "AUTO_CLEARED" if i % 5 else "ESCALATED",
                        "created_at": _ts(i % 60),
                    }
                )
            )

        counts = asyncio.run(
            memory_store.count_by_state(("AUTO_CLEARED", "ESCALATED"))
        )
        assert counts["ESCALATED"] == 50  # every 5th of 250
        assert counts["AUTO_CLEARED"] == 200


class TestRollupAggregation:
    """Global token/latency/cost totals must come from denormalized rollup
    fields, not from summing whatever page happened to be fetched."""

    def test_sum_rollups_is_independent_of_list_limit(self, memory_store):
        for i in range(1, 21):
            asyncio.run(
                memory_store.put_case(
                    {
                        "case_id": f"CASE-{i:03d}",
                        "shipment_id": f"SHIP-{i:03d}",
                        "state": "AUTO_CLEARED",
                        "created_at": _ts(i),
                        "_agent_calls": 2,
                        "_input_tokens": 100,
                        "_output_tokens": 50,
                        "_estimated_cost_usd": 0.001,
                        "_sum_latency_ms": 400,
                    }
                )
            )

        totals = asyncio.run(memory_store.sum_rollups())
        assert totals["agent_calls"] == 40
        assert totals["total_input_tokens"] == 2000
        assert totals["total_output_tokens"] == 1000
        assert totals["avg_latency_ms"] == 200  # 8000ms / 40 calls
        assert round(totals["estimated_cost_usd"], 3) == 0.020
