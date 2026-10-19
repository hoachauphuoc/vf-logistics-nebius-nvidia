"""
The worked examples shown to the HS classifier. A measurement is only honest if the example that would leak
its answer is held out, and only attributable if the selection is the same every run and reports which
examples were used.
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics.agents import hs_cot  # noqa: E402


class TestBuildExemplars:
    def test_the_selection_is_a_stable_prefix_of_the_pool_and_names_the_pairs_used(self):
        text, pairs = hs_cot.build_exemplars()
        again = hs_cot.build_exemplars()
        assert (text, pairs) == again
        assert pairs == [ex["pair"] for ex in hs_cot._POOL[: hs_cot.EXEMPLAR_COUNT]]
        assert text.startswith("\n\nWorked examples.")

    def test_each_example_shows_its_description_heading_and_answer(self):
        text, pairs = hs_cot.build_exemplars(count=1)
        first = hs_cot._POOL[0]
        assert f'Description: "{first["description"]}"' in text
        assert f"Declared heading: {first['declared_hs']}" in text
        assert len(pairs) == 1

    def test_the_pair_being_measured_is_held_out(self):
        held = hs_cot._POOL[0]["pair"]
        _, pairs = hs_cot.build_exemplars(exclude_pair=held, count=len(hs_cot._POOL))
        assert held not in pairs
        assert len(pairs) == len(hs_cot._POOL) - 1

    def test_every_example_sharing_the_measured_heading_is_held_out(self):
        heading = hs_cot._POOL[0]["declared_hs"]
        _, pairs = hs_cot.build_exemplars(exclude_heading=heading, count=len(hs_cot._POOL))
        left = {ex["pair"] for ex in hs_cot._POOL if ex["declared_hs"] != heading}
        assert set(pairs) == left

    def test_an_empty_pool_gives_no_examples_and_no_text(self):
        from unittest.mock import patch

        with patch.object(hs_cot, "_POOL", []):
            assert hs_cot.build_exemplars() == ("", [])


class TestRendering:
    def test_fields_are_written_in_the_order_of_the_method_with_the_verdict_last(self):
        answer = {k: k for k in reversed(hs_cot._FIELD_ORDER)}
        assert list(json.loads(hs_cot._render(answer))) == list(hs_cot._FIELD_ORDER)

    def test_non_ascii_text_is_kept_as_written(self):
        answer = {k: "" for k in hs_cot._FIELD_ORDER}
        answer["reasoning"] = "gỗ dán"
        assert "gỗ dán" in hs_cot._render(answer)


class TestPairs:
    def test_the_pairs_file_loads(self):
        pairs = hs_cot.load_pairs()
        assert isinstance(pairs, dict) and pairs
