"""
The live-run measurement (open item: real-model extraction quality, time and cost): what a case
cost, how long the models took, and whether each extracted field is in the document's own text.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import measure_live_run as ml  # noqa: E402

SOURCE = """
BILL OF LADING
Shipper Company Saigon Textile Export JSC
Tax ID / MST 0301234567
Consignee Company Orchard Apparel Pte Ltd
Description of Goods Woven cotton garments, 164 cartons, retail packed
HS Code 6205.20
Declared Value USD 9,600.00
Port of Loading Cat Lai Port, Ho Chi Minh City, Vietnam
Port of Discharge PSA Singapore
"""


def case(**shipment):
    return {
        "case_id": "CASE-VFL-1", "state": "AUTO_CLEARED",
        "_estimated_cost_usd": 0.0123, "_sum_latency_ms": 41000, "_agent_calls": 5,
        "_input_tokens": 15000, "_output_tokens": 4000, "_tavily_searches": 2,
        "shipment": {
            "shipper_company": "Saigon Textile Export JSC", "shipper_tax_id": "0301234567",
            "receiver_company": "Orchard Apparel Pte Ltd",
            "cargo_description": "Woven cotton garments, 164 cartons, retail packed",
            "hs_code": "6205.20", "declared_value": 9600,
            "origin": "Cat Lai Port, Ho Chi Minh City, Vietnam", "destination": "PSA Singapore",
            **shipment,
        },
    }


class TestAFaithfulExtraction:
    def test_every_field_is_grounded_and_nothing_is_missed(self):
        row = ml.measure_case(case(), SOURCE)
        assert row["fields_checked"] == 8
        assert row["fields_grounded"] == 8
        assert row["ungrounded"] == []
        assert row["missed"] == []

    def test_cost_time_and_tokens_come_from_the_case(self):
        row = ml.measure_case(case(), SOURCE)
        assert row["cost_usd"] == 0.0123
        assert row["model_seconds"] == 41.0
        assert row["tokens"] == 19000
        assert row["agent_calls"] == 5
        assert row["tavily_searches"] == 2
        assert row["state"] == "AUTO_CLEARED"

    def test_a_number_is_matched_however_the_document_formats_it(self):
        row = ml.measure_case(case(declared_value=9600.0), SOURCE)
        assert "declared_value" not in row["ungrounded"]


class TestAnUnfaithfulExtraction:
    def test_a_value_that_is_not_in_the_source_is_named_as_ungrounded(self):
        row = ml.measure_case(case(shipper_company="Hanoi Garment Co"), SOURCE)
        assert row["ungrounded"] == ["shipper_company"]
        assert row["fields_grounded"] == 7

    def test_a_wrong_number_is_ungrounded(self):
        row = ml.measure_case(case(declared_value=96000), SOURCE)
        assert row["ungrounded"] == ["declared_value"]

    def test_a_field_the_model_left_empty_is_not_counted_as_checked(self):
        row = ml.measure_case(case(shipper_tax_id=None), SOURCE)
        assert row["fields_checked"] == 7
        assert row["fields_grounded"] == 7

    def test_an_identifier_in_the_source_that_was_not_extracted_is_missed(self):
        row = ml.measure_case(case(shipper_tax_id=None, hs_code=None), SOURCE)
        assert sorted(row["missed"]) == ["hs_code", "shipper_tax_id"]


class TestTheSummary:
    def test_totals_and_medians_over_cases(self):
        rows = [
            {"cost_usd": 0.01, "model_seconds": 30.0, "fields_checked": 8, "fields_grounded": 8, "missed": []},
            {"cost_usd": 0.03, "model_seconds": 50.0, "fields_checked": 8, "fields_grounded": 6, "missed": ["hs_code"]},
            {"cost_usd": 0.02, "model_seconds": 40.0, "fields_checked": 7, "fields_grounded": 7, "missed": []},
        ]
        summary = ml.summarise(rows)
        assert summary["cases"] == 3
        assert summary["total_cost_usd"] == 0.06
        assert summary["median_cost_usd"] == 0.02
        assert summary["median_model_seconds"] == 40.0
        assert summary["fields_checked"] == 23
        assert summary["fields_grounded"] == 21
        assert summary["grounded_rate"] == round(21 / 23, 4)
        assert summary["cases_with_a_missed_identifier"] == 1

    def test_an_empty_run_has_no_rate(self):
        summary = ml.summarise([])
        assert summary["cases"] == 0
        assert summary["grounded_rate"] is None
