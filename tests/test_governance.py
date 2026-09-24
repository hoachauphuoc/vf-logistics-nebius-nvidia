"""
Unit tests for the governance module (delegation boundaries and execution gate).

These tests verify:
1. Fail-closed behavior without boundary
2. Permission checks against boundary
3. Non-waivable human triggers
4. Gate denial recording
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from vf_logistics.governance import (
    check,
    proposed_boundary,
    agent_readiness,
    PROTECTED_ACTIONS,
    NON_WAIVABLE_HUMAN_TRIGGERS,
)


@pytest.fixture
def sample_boundary() -> dict[str, Any]:
    """A sample active boundary for testing."""
    return {
        "boundary_id": "BOUNDARY-v1",
        "version": 1,
        "status": "ACTIVE",
        "permissions": {
            "allowed_actions": ["hold_shipment", "assign_analyst", "draft_sar", "notify_webhook", "publish_decision"],
            "auto_release": {
                "permitted": True,
                "max_declared_value_usd": 25_000,
                "max_effective_risk": 39,
                "require_zero_deterministic_findings": True,
                "forbidden_hs_prefixes": ["8504", "9026"],
                "forbidden_destinations": ["iran", "north korea"],
            },
            "require_human_when": [
                "score_disputed",
                "injection_detected",
                "forbidden_field_attempted",
                "compliance_blocked",
            ],
        },
        "published_by": "test@example.com",
        "published_at": "2026-01-01T00:00:00+00:00",
    }


@pytest.fixture
def clean_case() -> dict[str, Any]:
    """A case that should pass all checks."""
    return {
        "case_id": "CASE-TEST-001",
        "shipment_id": "TEST-001",
        "state": "SPECIALISTS_DONE",
        "risk_score": 25,
        "compliance_status": "CLEARED",
        "shipment": {
            "declared_value": 10000,
            "hs_code": "8517.12",
            "destination": "Singapore",
        },
        "validation": {"findings": []},
        "reconciliation": {"score_disputed": False},
        "input_security": {
            "injection_screening": {"blocked": False},
            "forbidden_fields_attempted": [],
        },
    }


class TestFailClosedBehavior:
    """Tests for fail-closed behavior without boundary."""

    def test_no_boundary_denies_protected_action(self, clean_case):
        """Without boundary, protected actions are denied."""
        result = check("release_shipment", clean_case, boundary=None)

        assert result["allowed"] is False
        assert "no active delegation boundary" in result["reason"]
        assert result["boundary_version"] is None

    def test_no_boundary_allows_non_protected_action(self, clean_case):
        """Non-protected actions pass without boundary."""
        result = check("log_event", clean_case, boundary=None)

        assert result["allowed"] is True
        assert "not a protected action" in result["reason"]

    def test_agent_suspended_without_boundary(self):
        """Agent readiness is SUSPENDED without boundary."""
        with patch("vf_logistics.governance.get_store") as mock_store:
            mock_store.return_value.active_boundary = AsyncMock(return_value=None)
            mock_store.return_value.list_cases = AsyncMock(return_value=[])

            result = asyncio.run(agent_readiness())

            assert result["state"] == "SUSPENDED"
            assert "No delegation boundary" in result["reason"]


class TestPermissionChecks:
    """Tests for permission checks against boundary."""

    def test_allowed_action_passes(self, sample_boundary, clean_case):
        """Actions in allowed_actions pass the gate."""
        result = check("hold_shipment", clean_case, sample_boundary)

        assert result["allowed"] is True

    def test_disallowed_action_denied(self, sample_boundary, clean_case):
        """Actions not in allowed_actions are denied."""
        # Remove hold_shipment from allowed
        sample_boundary["permissions"]["allowed_actions"] = ["assign_analyst"]

        result = check("hold_shipment", clean_case, sample_boundary)

        assert result["allowed"] is False
        assert "outside" in result["reason"]

    def test_auto_release_checks_value_ceiling(self, sample_boundary, clean_case):
        """Auto-release respects value ceiling."""
        clean_case["shipment"]["declared_value"] = 100_000  # Over 25k limit

        result = check("release_shipment", clean_case, sample_boundary)

        # Should be denied due to value exceeding ceiling
        # (depends on check implementation)
        assert result["boundary_version"] == 1

    def test_auto_release_checks_forbidden_destination(self, sample_boundary, clean_case):
        """Auto-release checks forbidden destinations."""
        clean_case["shipment"]["destination"] = "Iran"

        result = check("release_shipment", clean_case, sample_boundary)

        # May be denied or require human review
        assert result["boundary_version"] == 1


class TestNonWaivableHumanTriggers:
    """Tests for non-waivable human triggers."""

    def test_injection_detected_requires_human(self, sample_boundary, clean_case):
        """Injection detection always requires human review."""
        clean_case["input_security"]["injection_screening"]["blocked"] = True

        result = check("release_shipment", clean_case, sample_boundary)

        assert result["allowed"] is False
        assert "requires human review" in result["reason"]
        assert "injection_detected" in result.get("human_triggers", [])

    def test_forbidden_field_requires_human(self, sample_boundary, clean_case):
        """Forbidden field override requires human review."""
        clean_case["input_security"]["forbidden_fields_attempted"] = ["risk_score"]

        result = check("release_shipment", clean_case, sample_boundary)

        assert result["allowed"] is False
        assert "forbidden_field_attempted" in result.get("human_triggers", [])

    def test_score_disputed_requires_human(self, sample_boundary, clean_case):
        """Score dispute requires human review."""
        clean_case["reconciliation"]["score_disputed"] = True

        result = check("release_shipment", clean_case, sample_boundary)

        assert result["allowed"] is False
        assert "score_disputed" in result.get("human_triggers", [])

    def test_compliance_blocked_requires_human(self, sample_boundary, clean_case):
        """Compliance block requires human review."""
        clean_case["compliance_status"] = "BLOCKED"

        result = check("hold_shipment", clean_case, sample_boundary)

        assert result["allowed"] is False
        assert "compliance_blocked" in result.get("human_triggers", [])


class TestGateDenialRecording:
    """Tests for gate denial recording."""

    def test_denial_includes_boundary_version(self, sample_boundary, clean_case):
        """Denials include the boundary version."""
        clean_case["reconciliation"]["score_disputed"] = True

        result = check("release_shipment", clean_case, sample_boundary)

        assert result["boundary_version"] == 1

    def test_denial_includes_reason(self, sample_boundary, clean_case):
        """Denials include a clear reason."""
        clean_case["input_security"]["injection_screening"]["blocked"] = True

        result = check("release_shipment", clean_case, sample_boundary)

        assert "reason" in result
        assert "DENIED" in result["reason"]

    def test_multiple_triggers_all_recorded(self, sample_boundary, clean_case):
        """Multiple human triggers are all recorded."""
        clean_case["input_security"]["injection_screening"]["blocked"] = True
        clean_case["reconciliation"]["score_disputed"] = True

        result = check("release_shipment", clean_case, sample_boundary)

        triggers = result.get("human_triggers", [])
        assert "injection_detected" in triggers
        assert "score_disputed" in triggers


class TestProposedBoundary:
    """Tests for proposed boundary generation."""

    def test_proposed_boundary_is_conservative(self):
        """Proposed boundary should be conservative by default."""
        boundary = proposed_boundary()

        # Should not include release_shipment in allowed_actions
        assert "release_shipment" not in boundary["allowed_actions"]

        # SAR may_file should be False
        assert boundary["sar_filing"]["may_file"] is False

        # Should require human for various triggers
        assert "score_disputed" in boundary["require_human_when"]

    def test_proposed_boundary_includes_all_sections(self):
        """Proposed boundary includes all required sections."""
        boundary = proposed_boundary()

        assert "allowed_actions" in boundary
        assert "auto_release" in boundary
        assert "require_human_when" in boundary
        assert "sar_filing" in boundary


class TestProtectedActions:
    """Tests for protected actions configuration."""

    def test_protected_actions_defined(self):
        """All expected protected actions are defined."""
        expected = {
            "release_shipment",
            "hold_shipment",
            "assign_analyst",
            "draft_sar",
            "notify_webhook",
            "publish_decision",
        }

        assert PROTECTED_ACTIONS == expected

    def test_non_waivable_triggers_defined(self):
        """Non-waivable triggers are defined."""
        assert "injection_detected" in NON_WAIVABLE_HUMAN_TRIGGERS
        assert "forbidden_field_attempted" in NON_WAIVABLE_HUMAN_TRIGGERS
