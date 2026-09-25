"""
The debate agent's pure logic -- the parts that are not a stubbed completion.

`tests/test_decision_paths.py` excluded this module on the grounds that the
model-calling bodies are "covered at the interpret/parse boundary, where the logic is,
rather than by stubbing a completion and asserting the stub came back". That reasoning
applies to `conduct_debate`'s happy path and it is respected -- nothing here scripts a
successful debate and then asserts the script came back.

It does not apply to any of these. None of them calls a model:

  `_build_debate_context`  builds a prompt string out of `case.get(...)` defaults
  `_truncate_context`      three branches of string arithmetic
  `_execute_tool`          a four-way dispatch with an unknown-tool fallback
  `_tavily_search`         depth normalisation, a result-count subtlety, and a
                           failed-status branch that changes what the model is told
  `_nano_reevaluate`       an except branch that decides what a failure looks like

Two of these carry consequences that are easy to miss, so they are pinned explicitly:
`result_count` counts BEFORE the slice, and a failed Tavily status must be named in the
tool result rather than arriving as an innocent empty list.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import tavily_client  # noqa: E402
from vf_logistics.agents import debate_agent  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


class TestContextBuilding(unittest.TestCase):
    """
    Every field is read with `.get()` and a default, which is a deliberate property
    rather than an accident: the debate fires on a disputed score, and a case that
    reached a dispute may be missing pieces. A prompt builder that raised would turn a
    reviewable disagreement into a 500.
    """

    def test_an_empty_case_does_not_raise(self):
        context = debate_agent._build_debate_context({})
        self.assertIsInstance(context, str)
        self.assertGreater(len(context), 0)

    def test_an_empty_case_still_produces_every_section(self):
        context = debate_agent._build_debate_context({})
        for anchor in (
            "CASE UNDER REVIEW:",
            "SHIPMENT DATA:",
            "JUNIOR ANALYST (NANO) FRAUD ASSESSMENT:",
            "JUNIOR ANALYST (NANO) COMPLIANCE ASSESSMENT:",
            "DETERMINISTIC VALIDATION:",
            "YOUR TASK:",
        ):
            with self.subTest(anchor=anchor):
                self.assertIn(anchor, context)

    def test_a_case_with_no_steps_says_N_A_rather_than_inventing_a_score(self):
        context = debate_agent._build_debate_context({})
        self.assertIn("N/A", context)

    def test_the_fraud_and_compliance_steps_are_found_by_agent_name(self):
        case = {
            "case_id": "CASE-TEST-1",
            "steps": [
                {"agent": "intake", "result": {"ignored": True}},
                {"agent": "fraud_detection", "result": {
                    "flags": ["UNDERVALUED"], "confidence": 0.9, "recommendations": [],
                }},
                {"agent": "compliance", "result": {"findings": ["SANCTIONS_HIT"]}},
            ],
        }
        context = debate_agent._build_debate_context(case)
        self.assertIn("CASE-TEST-1", context)
        self.assertIn("UNDERVALUED", context)
        self.assertIn("SANCTIONS_HIT", context)

    def test_the_last_matching_step_wins_when_an_agent_ran_twice(self):
        """
        The loop has no `break`, so a retried agent's later step overwrites the earlier
        one. That is the right way round -- a retry supersedes what it replaced -- but
        it is worth pinning, because the opposite would put a superseded score in front
        of the Senior Auditor.
        """
        case = {"steps": [
            {"agent": "fraud_detection", "result": {"flags": ["FIRST_ATTEMPT"]}},
            {"agent": "fraud_detection", "result": {"flags": ["RETRY_ATTEMPT"]}},
        ]}
        context = debate_agent._build_debate_context(case)
        self.assertIn("RETRY_ATTEMPT", context)
        self.assertNotIn("FIRST_ATTEMPT", context)


class TestContextTruncation(unittest.TestCase):
    def test_falsy_text_becomes_an_empty_string(self):
        self.assertEqual(debate_agent._truncate_context(""), "")
        self.assertEqual(debate_agent._truncate_context(None), "")

    def test_text_within_the_limit_is_returned_unchanged(self):
        text = "x" * 100
        self.assertEqual(debate_agent._truncate_context(text, limit=4000), text)

    def test_longer_text_reports_how_much_was_dropped(self):
        text = "y" * 4500
        out = debate_agent._truncate_context(text, limit=4000)
        self.assertIn("...[truncated, 500 more chars]", out)
        self.assertTrue(out.startswith("y" * 4000))


class TestToolDispatch(unittest.TestCase):
    def test_an_unknown_tool_is_reported_not_ignored(self):
        """
        The model chooses the tool name, so an unknown one is model output rather than a
        programming error. Returning an error dict puts it in the debate trace where a
        reviewer can see the Senior Auditor asked for something that does not exist.
        """
        out = run(debate_agent._execute_tool("no_such_tool", {}, {}))
        self.assertEqual(out, {"error": "Unknown tool: no_such_tool"})

    def test_render_final_verdict_echoes_its_arguments(self):
        args = {"verdict": "DISAGREE", "confidence": 0.9, "rationale": "because"}
        out = run(debate_agent._execute_tool("render_final_verdict", args, {}))
        self.assertTrue(out["recorded"])
        self.assertEqual(out["verdict"], "DISAGREE")

    def test_a_model_supplied_recorded_key_overwrites_the_marker(self):
        """
        `{"recorded": True, **args}` -- args win. Not a defect worth changing, but the
        marker is not trustworthy as a provenance signal, and a test is cheaper than
        rediscovering that.
        """
        out = run(debate_agent._execute_tool(
            "render_final_verdict", {"recorded": "no"}, {},
        ))
        self.assertEqual(out["recorded"], "no")

    def test_dispatch_reaches_tavily_with_the_models_arguments(self):
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([], "OK")
            run(debate_agent._execute_tool(
                "search_tavily", {"query": "Acme Ltd sanctions", "search_depth": "advanced"}, {},
            ))
        search.assert_awaited_once()
        self.assertEqual(search.await_args.args[0], "Acme Ltd sanctions")
        self.assertEqual(search.await_args.kwargs["search_depth"], "advanced")


class TestTavilySearchFromTheDebate(unittest.TestCase):
    def test_an_empty_query_never_reaches_the_api(self):
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            out = run(debate_agent._tavily_search("   ", "basic"))
        search.assert_not_awaited()
        self.assertEqual(out, {"error": "Empty query", "results": []})

    def test_an_unknown_depth_falls_back_to_basic(self):
        """
        The tool schema advertises a basic/advanced enum, so the model can send neither.
        Normalising rather than raising keeps a malformed tool call from ending a debate.
        """
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([], "OK")
            out = run(debate_agent._tavily_search("a query", "exhaustive"))
        self.assertEqual(out["depth"], "basic")
        self.assertEqual(search.await_args.kwargs["max_results"], 3)

    def test_advanced_depth_asks_for_more_results(self):
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([], "OK")
            out = run(debate_agent._tavily_search("a query", "advanced"))
        self.assertEqual(out["depth"], "advanced")
        self.assertEqual(search.await_args.kwargs["max_results"], 5)

    def test_result_count_is_what_was_returned_not_what_was_kept(self):
        """
        `result_count` is `len(results)` and `results` is `results[:max_results]`, so on
        a basic search returning five rows the two disagree: five found, three shown.

        That is the honest way round -- the count reports what the search produced -- but
        it means a reader cannot infer one from the other, which is exactly the kind of
        thing that gets miscopied into a summary.
        """
        rows = [{"url": f"https://e{i}.test"} for i in range(5)]
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = (rows, "OK")
            out = run(debate_agent._tavily_search("a query", "basic"))
        self.assertEqual(out["result_count"], 5)
        self.assertEqual(len(out["results"]), 3)

    def test_a_failed_search_is_named_rather_than_arriving_as_an_empty_list(self):
        """
        The reason this branch exists, stated in its own comment: an empty list reads as
        "nothing adverse found" to a model, and a search that did not run is not
        evidence of absence. The Senior Auditor is told which it was.
        """
        failed = next(iter(tavily_client.FAILED_STATUSES))
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([], failed)
            out = run(debate_agent._tavily_search("a query", "basic"))
        self.assertIn("error", out)
        self.assertIn("absence of findings here is not", out["error"])
        self.assertEqual(out["status"], failed)

    def test_an_ok_search_carries_no_error_key(self):
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([{"url": "https://ok.test"}], "OK")
            out = run(debate_agent._tavily_search("a query", "basic"))
        self.assertNotIn("error", out)

    def test_a_transport_failure_becomes_a_tool_result_not_an_exception(self):
        """
        An exception here would propagate out of `conduct_debate`, which has no
        try/except, and lose the whole debate over one failed search.
        """
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.side_effect = RuntimeError("connection reset")
            out = run(debate_agent._tavily_search("a query", "basic"))
        self.assertEqual(out["error"], "connection reset")
        self.assertEqual(out["query"], "a query")
        self.assertEqual(out["results"], [])


class TestNanoReevaluation(unittest.TestCase):
    """
    The tool that lets the Senior Auditor send the case back to Nano with a focus.

    Patch target is `vf_logistics.agents.analyze_shipment`, not
    `debate_agent.analyze_shipment`: the import at line 447 is function-local
    (`from . import analyze_shipment`), so it resolves off the package at call time.
    """

    def _case(self):
        return {
            "model_risk_score": 35,
            "shipment": {"shipment_id": "VF-TEST", "declared_value": 1000},
        }

    def test_a_failure_reports_the_original_score_alongside_the_error(self):
        """
        Returning the original score matters: without it the Senior Auditor has a tool
        result saying only "it broke", and no basis to reason about the score it was
        questioning.
        """
        with patch("vf_logistics.agents.analyze_shipment", new_callable=AsyncMock) as nano:
            nano.side_effect = RuntimeError("nano timed out")
            out = run(debate_agent._nano_reevaluate(self._case(), ["pricing"], "undervalued"))
        self.assertEqual(out["error"], "nano timed out")
        self.assertEqual(out["original_score"], 35)

    def test_a_success_reports_both_scores_so_the_change_is_visible(self):
        envelope = {
            "result": {"risk_score": 72, "risk_level": "HIGH", "flags": ["UNDERVALUED"],
                       "recommendations": ["escalate"]},
            "model": "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B",
            "latency_ms": 640,
        }
        with patch("vf_logistics.agents.analyze_shipment", new_callable=AsyncMock) as nano:
            nano.return_value = envelope
            out = run(debate_agent._nano_reevaluate(self._case(), ["pricing"], "undervalued"))
        self.assertEqual(out["original_score"], 35)
        self.assertEqual(out["new_score"], 72)
        self.assertEqual(out["new_flags"], ["UNDERVALUED"])

    def test_the_focus_is_injected_without_mutating_the_caller_s_case(self):
        """
        `case["shipment"].copy()` -- the stored case must not acquire a `_debate_focus`
        key, because it would then be persisted and reappear on a later hop as though
        the shipment had arrived with it.
        """
        case = self._case()
        with patch("vf_logistics.agents.analyze_shipment", new_callable=AsyncMock) as nano:
            nano.return_value = {"result": {}, "model": "m", "latency_ms": 1}
            run(debate_agent._nano_reevaluate(case, ["routing"], "diverted"))
            sent = nano.await_args.args[0]

        self.assertIn("_debate_focus", sent)
        self.assertNotIn(
            "_debate_focus", case["shipment"],
            "the caller's shipment must be untouched -- a persisted _debate_focus would "
            "look like an inbound field on the next hop",
        )
        self.assertEqual(sent["_debate_focus"]["areas"], ["routing"])


if __name__ == "__main__":
    unittest.main()
