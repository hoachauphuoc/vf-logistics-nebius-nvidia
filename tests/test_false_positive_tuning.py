"""
The false-positive tuning, pinned: which signals are findings and which are context.

WHY THIS FILE EXISTS

On the synthetic corpus the deterministic layer held 84% of the clean shipments on
the dev split (96 of 114), and two signals accounted for most of it
(scripts/analyse_false_positives.py):

  * FREIGHT_ANOMALY's "overpriced" branch, comparing a consignment's freight
    against a per-consignment lane figure that does not scale with size. It fired
    on 60 of 114 clean shipments and separated nothing.
  * SHIPPER_THIN_HISTORY (2-9 prior shipments), which alone held 25 clean
    shipments; the attacks it alone caught sat inside the clean range.

Both are now OBSERVATIONS: visible on the case, carrying no floor, not counted as
findings -- so they neither hold a shipment nor block the boundary's
require_zero_deterministic_findings. Measured on the holdout split, which played no
part in choosing this: false positive rate 76.7% -> 38.4%, sanctions-alias and
shell-company recall unchanged at 100%.

Everything a finding still does is pinned below too, because the risk of this
change is not that it goes too far now but that the next edit takes it further.
"""

from __future__ import annotations

from vf_logistics import verifier

# A routine commercial consignment on a lane the table knows, with nothing wrong.
BASE = {
    "shipment_id": "FP-TUNE-1",
    "origin": "Ho Chi Minh City, Vietnam",
    "destination": "Tokyo, Japan",
    "shipper_company": "Saigon Furniture Export JSC",
    "shipper_country": "Vietnam",
    "shipper_tax_id": "0311122233",
    "receiver_company": "Kanto Interiors KK",
    "receiver_country": "Japan",
    "shipper_tx_count": 40,
    "hs_code": "9403.60",
    "cargo_description": "Wooden office desks, flat packed",
    "declared_value": 200_000,
    "weight_kg": 9_000,
    "shipping_cost": 2_000,
    "transit_points": "none",
    "route_details": "direct sailing",
}


def run(**overrides):
    return verifier.validate({**BASE, **overrides}, screen_sanctions=False)


def codes(result, key="findings"):
    return [f["code"] for f in result[key]]


class TestTheBaselineShipmentIsClean:
    def test_nothing_to_report(self):
        result = run()
        assert result["findings"] == []
        assert result["risk_floor"] == 0


class TestFreightAboveTheLaneFigureIsContext:
    def test_a_large_consignment_is_not_scored_for_its_size(self):
        # 14,000 USD against the 1,900 USD Vietnam-Japan lane figure: 7x, which the
        # old branch scored MEDIUM 50 -- for a 200,000 USD consignment, where 7% of
        # value is ordinary freight.
        result = run(shipping_cost=14_000)
        assert "FREIGHT_ANOMALY" not in codes(result)
        assert "FREIGHT_ABOVE_LANE_TYPICAL" in codes(result, "observations")
        assert result["risk_floor"] == 0
        assert result["finding_count"] == 0

    def test_the_observation_carries_the_numbers(self):
        obs = next(
            o for o in run(shipping_cost=14_000)["observations"]
            if o["code"] == "FREIGHT_ABOVE_LANE_TYPICAL"
        )
        assert obs["measured"]["ratio"] > 3.0
        assert obs["measured"]["freight_to_value"] == 0.07

    def test_against_the_records_own_average_it_is_still_a_finding(self):
        """A like-for-like baseline makes overpricing measurable again."""
        result = run(shipping_cost=14_000, avg_route_cost=2_000)
        finding = next(f for f in result["findings"] if f["code"] == "FREIGHT_ANOMALY")
        assert finding["floor"] == 50
        assert result["risk_floor"] == 50

    def test_underpriced_freight_is_still_a_finding_against_the_lane_table(self):
        """Far below a single consignment's typical is not explained by size."""
        result = run(shipping_cost=300)
        finding = next(f for f in result["findings"] if f["code"] == "FREIGHT_ANOMALY")
        assert finding["severity"] == "CRITICAL"
        assert result["risk_floor"] == 90


class TestAShortTradingRecordIsContext:
    def test_thin_history_is_an_observation(self):
        result = run(shipper_tx_count=5)
        assert "SHIPPER_THIN_HISTORY" not in codes(result)
        assert "SHIPPER_THIN_HISTORY" in codes(result, "observations")
        assert result["risk_floor"] == 0
        assert result["finding_count"] == 0

    def test_no_history_is_still_a_high_finding(self):
        result = run(shipper_tx_count=1)
        assert "SHIPPER_NO_HISTORY" in codes(result)
        assert result["risk_floor"] == 65

    def test_unverified_history_is_still_a_finding(self):
        shipment = dict(BASE)
        del shipment["shipper_tx_count"]
        result = verifier.validate(shipment, screen_sanctions=False)
        assert "SHIPPER_HISTORY_UNVERIFIED" in codes(result)


class TestObservationsNeverCorroborate:
    def test_observations_do_not_count_towards_the_high_severity_tally(self):
        """
        Two HIGH findings corroborate to a floor of 80. An observation is not a
        finding of any severity, so it must never be the second one.
        """
        result = run(shipper_tx_count=5, shipping_cost=14_000, destination="Karachi, Pakistan",
                     receiver_country="Pakistan")
        assert codes(result) == ["HIGH_RISK_DESTINATION"]
        assert result["high_severity_count"] == 1
        assert result["risk_floor"] == 70

    def test_auto_clear_is_now_reachable_for_an_ordinary_new_customer(self):
        """
        The point of the change, stated as the pipeline sees it: a five-shipment
        customer paying normal freight on a big consignment is no longer vetoed.
        """
        result = run(shipper_tx_count=5, shipping_cost=14_000)
        reconciled = verifier.reconcile(10, result)
        assert reconciled["auto_clear_permitted"] is True


class TestASelfContradictingHsReplyIsNotActedOn:
    """
    Seen on the local board: "does not match declared HS 9403; the goods appear
    to belong to 9403" -- scored as a MEDIUM mismatch with a floor of 40.
    """

    def verdict(self, suggested):
        return {"verdict": "inconsistent", "suggested_hs": suggested,
                "confidence": 0.9, "reasoning": "office furniture"}

    def test_naming_the_declared_heading_is_context_not_a_finding(self):
        result = verifier.validate(BASE, hs_verdict=self.verdict("9403"), screen_sanctions=False)
        assert "HS_DESCRIPTION_MISMATCH" not in codes(result)
        assert "HS_DESCRIPTION_CHECK_CONTRADICTORY" in codes(result, "observations")
        assert result["risk_floor"] == 0

    def test_a_real_mismatch_is_still_a_finding(self):
        result = verifier.validate(BASE, hs_verdict=self.verdict("9401"), screen_sanctions=False)
        assert "HS_DESCRIPTION_MISMATCH" in codes(result)
        assert result["risk_floor"] == 40
