"""
The pre-filter rule update decides which shipments skip screening, so it is all-or-nothing: one bad key
refuses the whole update and leaves the rules as they were, and every accepted change is reported as a diff
an auditor can read ("the blacklist lost an entry").
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import verifier  # noqa: E402
from vf_logistics.verifier import PrefilterRules, apply_prefilter_update, prefilter_diff  # noqa: E402

n = verifier._normalize


@pytest.fixture
def current():
    return PrefilterRules.defaults()


class TestRefusals:
    @pytest.mark.parametrize("patch,phrase", [
        ({"vip_registry": "x"}, "vip_registry must be a list"),
        ({"vip_registry": ["x"]}, "vip_registry entries must each have a non-empty 'company'"),
        ({"vip_registry": [{"company": ""}]}, "vip_registry entries must each have a non-empty 'company'"),
        ({"blacklist_companies": "x"}, "blacklist_companies must be a list"),
        ({"blacklist_tax_ids": {"a": 1}}, "blacklist_tax_ids must be a list"),
        ({"safe_routes": "x"}, "safe_routes must be a list"),
        ({"low_value_threshold_usd": "cheap"}, "low_value_threshold_usd must be a number"),
        ({"low_value_threshold_usd": None}, "low_value_threshold_usd must be a number"),
        ({"low_value_threshold_usd": -1}, "low_value_threshold_usd must be non-negative"),
    ])
    def test_a_bad_value_is_refused_with_the_reason(self, current, patch, phrase):
        rules, errors = apply_prefilter_update(current, patch)
        assert rules is None
        assert any(phrase in e for e in errors)

    def test_one_bad_key_refuses_the_whole_update_even_beside_a_good_one(self, current):
        rules, errors = apply_prefilter_update(current, {"blacklist_companies": ["Evil Co"], "safe_routes": "x"})
        assert rules is None
        assert len(errors) == 1

    def test_every_bad_key_is_reported_at_once(self, current):
        _, errors = apply_prefilter_update(current, {"blacklist_companies": 1, "blacklist_tax_ids": 2, "safe_routes": 3})
        assert len(errors) == 3


class TestAcceptedUpdates:
    def test_an_empty_patch_changes_nothing(self, current):
        rules, errors = apply_prefilter_update(current, {})
        assert errors == [] and rules == current

    def test_the_vip_registry_is_normalised_and_a_duplicate_company_keeps_the_last_tax_id(self, current):
        rules, errors = apply_prefilter_update(current, {"vip_registry": [
            {"company": "Acme Ltd", "tax_id": " 111 "},
            {"company": "ACME LTD", "tax_id": "222"},
            {"company": "Bolt", "tax_id": None},
        ]})
        assert errors == []
        assert dict(rules.vip_registry) == {n("Acme Ltd"): "222", n("Bolt"): ""}

    def test_blacklists_drop_blanks_and_are_normalised(self, current):
        rules, _ = apply_prefilter_update(current, {
            "blacklist_companies": ["Evil Co", "", None], "blacklist_tax_ids": [" 99 ", "", 0],
        })
        assert rules.blacklist_companies == frozenset({n("Evil Co")})
        assert rules.blacklist_tax_ids == frozenset({"99"})

    def test_safe_routes_skip_entries_that_are_not_complete_pairs(self, current):
        rules, _ = apply_prefilter_update(current, {"safe_routes": [
            {"origin": "Hai Phong", "destination": "Busan"}, {"origin": "only"}, "junk",
        ]})
        assert rules.safe_routes == frozenset({(n("Hai Phong"), n("Busan"))})

    def test_the_threshold_may_be_a_numeric_string_or_zero(self, current):
        assert apply_prefilter_update(current, {"low_value_threshold_usd": "250.5"})[0].low_value_threshold_usd == 250.5
        assert apply_prefilter_update(current, {"low_value_threshold_usd": 0})[0].low_value_threshold_usd == 0

    def test_a_key_left_out_keeps_its_current_value(self, current):
        rules, _ = apply_prefilter_update(current, {"blacklist_companies": ["Evil Co"]})
        assert rules.safe_routes == current.safe_routes
        assert rules.vip_registry == current.vip_registry


class TestDiff:
    def test_no_change_is_an_empty_diff(self, current):
        assert prefilter_diff(current, current) == {}

    def test_every_kind_of_change_is_named_with_what_was_added_and_removed(self, current):
        after, _ = apply_prefilter_update(current, {
            "blacklist_companies": ["Evil Co"], "blacklist_tax_ids": ["99"],
            "vip_registry": [{"company": "Acme", "tax_id": "1"}],
            "safe_routes": [{"origin": "A", "destination": "B"}],
            "low_value_threshold_usd": 123,
        })
        diff = prefilter_diff(current, after)
        assert set(diff) == {"blacklist_companies", "blacklist_tax_ids", "vip_registry", "safe_routes", "low_value_threshold_usd"}
        assert diff["blacklist_companies"]["added"] == [n("Evil Co")]
        assert diff["blacklist_tax_ids"]["added"] == ["99"]
        assert {"company": n("Acme"), "tax_id": "1"} in diff["vip_registry"]["added"]
        assert diff["safe_routes"]["added"] == [{"origin": n("A"), "destination": n("B")}]
        assert diff["low_value_threshold_usd"] == {"from": current.low_value_threshold_usd, "to": 123.0}

    def test_removing_an_entry_is_reported_as_removed(self, current):
        with_entry, _ = apply_prefilter_update(current, {"blacklist_companies": ["Evil Co"], "blacklist_tax_ids": ["99"]})
        back, _ = apply_prefilter_update(with_entry, {"blacklist_companies": [], "blacklist_tax_ids": []})
        diff = prefilter_diff(with_entry, back)
        assert diff["blacklist_companies"] == {"added": [], "removed": [n("Evil Co")]}
        assert diff["blacklist_tax_ids"] == {"added": [], "removed": ["99"]}
