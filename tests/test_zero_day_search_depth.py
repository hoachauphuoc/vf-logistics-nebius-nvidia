"""
The zero-day agent lets the model pick a search depth. Only "basic" and "advanced" exist, so anything else the
model writes must become "basic" before it reaches the search API, as the debate agent already does.
"""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics.agents import zero_day_agent as zd  # noqa: E402


def run_tool(args):
    seen = {}

    async def fake_search(query, max_results=5, **kwargs):
        seen.update(max_results=max_results, **kwargs)
        return [], "ok"

    with patch.object(zd.tavily_client, "search_with_status", new=fake_search):
        asyncio.run(zd._run_tool("tavily_zero_day_search", {"query": "Acme Ltd sanctions", **args}))
    return seen


class TestSearchDepthReachesTheApiOnlyIfItIsValid:
    def test_advanced_is_kept_and_widens_the_search(self):
        seen = run_tool({"search_depth": "advanced"})
        assert (seen["search_depth"], seen["max_results"]) == ("advanced", 5)

    def test_basic_is_kept(self):
        seen = run_tool({"search_depth": "basic"})
        assert (seen["search_depth"], seen["max_results"]) == ("basic", 3)

    def test_an_absent_depth_is_basic(self):
        assert run_tool({})["search_depth"] == "basic"

    @pytest.mark.parametrize("value", ["deep", "ADVANCED", "", None, 3, ["advanced"]])
    def test_a_value_the_model_invented_becomes_basic(self, value):
        seen = run_tool({"search_depth": value})
        assert (seen["search_depth"], seen["max_results"]) == ("basic", 3)
