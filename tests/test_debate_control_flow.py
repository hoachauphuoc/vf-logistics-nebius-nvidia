"""
How the debate loop terminates -- the four ways out, and what each records.

This is the file that needs its reason for existing stated, because
`tests/test_decision_paths.py` excluded `debate_agent`'s model-calling bodies as
"covered at the interpret/parse boundary, where the logic is, rather than by stubbing a
completion and asserting the stub came back". That criterion is right and it is the test
this file has to pass: nothing below scripts a debate and then asserts the script came
back.

What is tested is the control flow around the calls, which is not at the parse boundary
and is not covered anywhere else:

  - a verdict on the first round stops the loop, so a debate costs one call and not four
  - a tool round feeds the result back and continues, and the conversation it builds is
    well-formed -- every assistant message carrying tool_calls has a matching role:"tool"
    reply, which is a hard API requirement rather than a stylistic one
  - a model that calls no tool at all still yields a verdict rather than None
  - rounds exhausting produces a forced verdict whose RATIONALE IS TRUE

That last one is why this file exists. A malformed-JSON verdict used to be recorded as
"Senior Auditor did not render verdict after 3 rounds", which was false -- the model did
render one, it was unreadable -- and on a project whose central claim is that the record
is checkable, a false sentence in the record is the defect, not the missing coverage.

`nebius_client.complete_with_tools` is patched because the alternative is a paid call to
a 253B model on every test run. `_usage` is left real: it is the thing that converts a
response into the token counts, and a mock that returned numbers directly would skip the
`getattr(usage, "prompt_tokens", 0) or 0` that makes a bare MagicMock raise TypeError.
"""

from __future__ import annotations

import asyncio
import copy
import json
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics.agents import debate_agent  # noqa: E402


def run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def tool_call(name: str, arguments, call_id: str = "call_1"):
    """One tool call shaped like the SDK's. `arguments` is a STRING on the wire."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = (
        arguments if isinstance(arguments, str) else json.dumps(arguments)
    )
    return tc


def response(tool_calls=None, content=None):
    """
    A completion. `usage` carries real integers because `_usage` is not mocked: it does
    `getattr(usage, "prompt_tokens", 0) or 0`, and a bare MagicMock attribute returns a
    MagicMock which then raises TypeError on `+=`.
    """
    message = MagicMock()
    message.tool_calls = tool_calls
    message.content = content
    resp = MagicMock()
    resp.choices = [MagicMock(message=message)]
    resp.usage = MagicMock(prompt_tokens=100, completion_tokens=50)
    return resp


CASE = {
    "case_id": "CASE-DEBATE-1",
    "model_risk_score": 30,
    "risk_score": 45,
    "shipment": {"shipment_id": "VF-1", "declared_value": 1000},
    "steps": [{"agent": "fraud_detection", "result": {"flags": [], "confidence": 0.8}}],
}

GOOD_VERDICT = {
    "verdict": "DISAGREE",
    "confidence": 0.85,
    "rationale": "Declared value is inconsistent with the route cost.",
    "recommended_action": "escalate",
}


class DebateCase(unittest.TestCase):
    def _debate(self, *responses, max_tool_rounds=3):
        """
        `messages_at` holds a DEEP COPY of the conversation as each call saw it.

        Reading `complete.await_args_list[i].kwargs["messages"]` does not work: the loop
        appends to one list in place and the mock stores a reference, so after the debate
        every recorded call points at the same fully-accumulated list. A test asserting
        "one tool message at the second call" then sees four and fails for the wrong
        reason -- or worse, passes on a two-round debate where the final state happens to
        match, which proves nothing.
        """
        self.messages_at: list[list[dict]] = []
        pending = list(responses)

        async def capture(**kwargs):
            self.messages_at.append(copy.deepcopy(kwargs["messages"]))
            return pending.pop(0)

        with patch.object(
            debate_agent.nebius_client, "complete_with_tools", new_callable=AsyncMock,
        ) as complete:
            complete.side_effect = capture
            out = run(debate_agent.conduct_debate(CASE, max_tool_rounds=max_tool_rounds))
        self.complete = complete
        return out

    def assertToolCallsAllAnswered(self, messages):
        """
        Every assistant message carrying `tool_calls` must have a matching `role: "tool"`
        reply. An API requirement rather than a preference -- the provider rejects the
        conversation otherwise -- and the invariant the unparseable-verdict path broke.
        """
        ids_called = {
            tc["id"]
            for m in messages if m.get("role") == "assistant"
            for tc in (m.get("tool_calls") or [])
        }
        ids_answered = {m["tool_call_id"] for m in messages if m.get("role") == "tool"}
        self.assertEqual(
            ids_called, ids_answered,
            "every tool_call must have a matching role:'tool' reply or the provider "
            "rejects the conversation",
        )


class TestVerdictOnFirstRound(DebateCase):
    def test_a_verdict_stops_the_loop_immediately(self):
        """
        Four rounds are budgeted; a decisive model must cost one. At roughly $0.0145 a
        call on the Ultra hop -- the measured figure behind the cost card -- a loop that
        kept going after a verdict would quadruple the price of the project's headline
        argument.
        """
        out = self._debate(response([tool_call("render_final_verdict", GOOD_VERDICT)]))
        self.assertEqual(self.complete.await_count, 1)
        self.assertEqual(out["result"]["verdict"]["verdict"], "DISAGREE")
        self.assertEqual(out["result"]["rounds_used"], 1)

    def test_the_verdict_is_the_models_arguments_not_a_default(self):
        out = self._debate(response([tool_call("render_final_verdict", GOOD_VERDICT)]))
        self.assertEqual(out["result"]["verdict"]["confidence"], 0.85)
        self.assertNotIn("Defaulting", out["result"]["verdict"]["rationale"])

    def test_tokens_are_accumulated_from_the_real_usage_reader(self):
        out = self._debate(response([tool_call("render_final_verdict", GOOD_VERDICT)]))
        self.assertEqual(out["input_tokens"], 100)
        self.assertEqual(out["output_tokens"], 50)

    def test_the_prompt_the_auditor_saw_is_carried_out_for_the_trace(self):
        out = self._debate(response([tool_call("render_final_verdict", GOOD_VERDICT)]))
        self.assertIn("CASE-DEBATE-1", out["prompt"])


class TestToolRoundThenVerdict(DebateCase):
    def _two_rounds(self):
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([{"url": "https://e.test"}], "OK")
            return self._debate(
                response([tool_call("search_tavily", {"query": "Acme sanctions"}, "c1")]),
                response([tool_call("render_final_verdict", GOOD_VERDICT, "c2")]),
            )

    def test_a_tool_round_continues_to_a_second_call(self):
        out = self._two_rounds()
        self.assertEqual(self.complete.await_count, 2)
        self.assertEqual(out["result"]["rounds_used"], 2)

    def test_both_the_tool_and_the_verdict_are_in_the_trace(self):
        out = self._two_rounds()
        trace = out["result"]["debate_trace"]
        self.assertEqual(trace[0]["tool"], "search_tavily")
        self.assertEqual(trace[1]["tool"], "render_final_verdict")
        self.assertEqual(trace[0]["round"], 1)
        self.assertEqual(trace[1]["round"], 2)

    def test_the_tool_result_is_fed_back_to_the_model(self):
        """
        Without this the second call sees no search result and the tool round was a
        billed no-op.
        """
        self._two_rounds()
        tool_messages = [m for m in self.messages_at[1] if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("e.test", tool_messages[0]["content"])

    def test_every_tool_call_gets_a_matching_tool_reply(self):
        self._two_rounds()
        self.assertToolCallsAllAnswered(self.messages_at[1])


class TestNoToolCallAtAll(DebateCase):
    def test_a_bare_answer_still_yields_a_verdict(self):
        """
        `verdict` is read unconditionally downstream -- `orchestrator.py` compares it to
        decide whether the score is disputed -- so None here would be an AttributeError
        on a case that already needed a person.
        """
        out = self._debate(response(None, content="I think it looks fine."))
        verdict = out["result"]["verdict"]
        self.assertEqual(verdict["verdict"], "CONFIRM")
        self.assertEqual(verdict["confidence"], 0.5)
        self.assertIn("did not use tools", verdict["rationale"])

    def test_it_stops_rather_than_burning_the_remaining_rounds(self):
        self._debate(response(None, content="fine"))
        self.assertEqual(self.complete.await_count, 1)

    def test_the_models_words_are_kept_even_though_they_are_not_a_verdict(self):
        out = self._debate(response(None, content="Route looks plausible to me."))
        entry = out["result"]["debate_trace"][0]
        self.assertEqual(entry["type"], "no_tool_call")
        self.assertEqual(entry["content"], "Route looks plausible to me.")

    def test_a_confirm_by_default_is_distinguishable_from_a_real_confirm(self):
        """
        Both say CONFIRM. The confidence is what separates them -- 0.5 here against a
        model-supplied figure -- and the rationale says the word "Defaulting". A reviewer
        must be able to tell that nobody actually agreed.
        """
        out = self._debate(response(None, content=""))
        self.assertIn("Defaulting", out["result"]["verdict"]["rationale"])
        self.assertLess(out["result"]["verdict"]["confidence"], 0.6)


class TestRoundsExhausted(DebateCase):
    def _search_forever(self, rounds=3):
        with patch.object(
            debate_agent.tavily_client, "search_with_status", new_callable=AsyncMock,
        ) as search:
            search.return_value = ([], "OK")
            return self._debate(
                *[
                    response([tool_call("search_tavily", {"query": f"q{i}"}, f"c{i}")])
                    for i in range(rounds + 1)
                ],
                max_tool_rounds=rounds,
            )

    def test_the_loop_runs_max_rounds_plus_one_and_no_further(self):
        self._search_forever(rounds=3)
        self.assertEqual(self.complete.await_count, 4)

    def test_exhaustion_forces_a_low_confidence_verdict(self):
        out = self._search_forever()
        verdict = out["result"]["verdict"]
        self.assertEqual(verdict["verdict"], "CONFIRM")
        self.assertEqual(verdict["confidence"], 0.4)
        self.assertEqual(verdict["recommended_action"], "hold")

    def test_the_forced_verdict_is_marked_as_forced_in_the_trace(self):
        out = self._search_forever()
        last = out["result"]["debate_trace"][-1]
        self.assertEqual(last["type"], "forced_verdict")
        self.assertEqual(last["round"], 4)

    def test_a_model_that_never_rendered_is_described_as_exactly_that(self):
        out = self._search_forever()
        self.assertIn(
            "did not render verdict", out["result"]["verdict"]["rationale"],
        )


class TestUnparseableVerdict(DebateCase):
    """
    The defect this file was written for.

    `json.JSONDecodeError` at the parse gives `tool_args = {}`; `{}` is falsy, so the
    `if final_verdict:` break never fires, the loop exhausts, and the forced verdict
    recorded "Senior Auditor did not render verdict after 3 rounds".

    That sentence was false. The Senior Auditor rendered a verdict; nobody could read it.
    The two cases need different follow-up -- a model ignoring its instructions versus a
    parse failure with the model's words still on the wire -- and the whole argument of
    this project is that the record is checkable, so a record that quietly says the wrong
    thing is worse than one that says nothing.
    """

    MALFORMED = '{"verdict": "DISAGREE", "confidence": 0.9, rationale: unquoted}'

    def _malformed(self, rounds=3):
        return self._debate(
            *[
                response([tool_call("render_final_verdict", self.MALFORMED, f"c{i}")])
                for i in range(rounds + 1)
            ],
            max_tool_rounds=rounds,
        )

    def test_the_rationale_does_not_claim_no_verdict_was_rendered(self):
        out = self._malformed()
        rationale = out["result"]["verdict"]["rationale"]
        self.assertNotIn(
            "did not render verdict", rationale,
            "the model DID render a verdict -- it was unparseable. Recording that it "
            "rendered nothing is a false statement in an audit record.",
        )

    def test_the_rationale_says_the_arguments_would_not_parse(self):
        out = self._malformed()
        self.assertIn("not valid JSON", out["result"]["verdict"]["rationale"])

    def test_the_raw_arguments_survive_so_a_reviewer_can_see_them(self):
        """
        The model's actual words are the most useful thing on this path and they used to
        be discarded entirely.
        """
        out = self._malformed()
        forced = out["result"]["debate_trace"][-1]
        self.assertIn("unparsed_arguments", forced)
        self.assertIn("DISAGREE", forced["unparsed_arguments"])

    def test_the_trace_entry_does_not_report_a_recorded_verdict(self):
        """
        `_execute_tool` returns `{"recorded": True, **args}`, so an unparseable call left
        `arguments: {}, result: {recorded: true}` in the trace -- which reads as a
        verdict that was recorded, and as indistinguishable from a tool called with no
        arguments.
        """
        out = self._malformed()
        first = out["result"]["debate_trace"][0]
        self.assertTrue(first["arguments_unparseable"])
        self.assertIn("raw_arguments", first)

    def test_the_model_is_told_its_json_was_bad_so_it_can_retry(self):
        """
        The spare rounds exist for exactly this. Silently dropping the failure spent them
        without ever saying what was wrong, and left the conversation malformed.
        """
        self._malformed()
        tool_messages = [m for m in self.messages_at[1] if m.get("role") == "tool"]
        self.assertEqual(len(tool_messages), 1)
        self.assertIn("not valid JSON", tool_messages[0]["content"])

    def test_the_conversation_stays_well_formed_after_a_parse_failure(self):
        """
        The invariant the old code broke: the `break` at the verdict check skipped
        appending the tool result, then the assistant message with its `tool_calls` was
        appended anyway -- a tool call with no reply. Checked at every round, because the
        conversation has to be valid on each request and not just at the end.
        """
        self._malformed()
        for index, messages in enumerate(self.messages_at):
            with self.subTest(call=index):
                self.assertToolCallsAllAnswered(messages)

    def test_a_model_that_recovers_on_the_retry_gets_its_real_verdict_used(self):
        """
        The payoff for telling the model rather than dropping the failure: a malformed
        first attempt followed by a good one ends with the model's own verdict, not a
        0.4-confidence default.
        """
        out = self._debate(
            response([tool_call("render_final_verdict", self.MALFORMED, "c1")]),
            response([tool_call("render_final_verdict", GOOD_VERDICT, "c2")]),
        )
        verdict = out["result"]["verdict"]
        self.assertEqual(verdict["verdict"], "DISAGREE")
        self.assertEqual(verdict["confidence"], 0.85)
        self.assertEqual(self.complete.await_count, 2)

    def test_an_empty_verdict_object_is_not_treated_as_a_parse_failure(self):
        """
        The boundary case that makes the flag necessary rather than inferring it from
        `{}`: a model may legitimately call render_final_verdict with no arguments, and
        that is "did not render" rather than "would not parse". Both leave `tool_args`
        empty, so only an explicit flag can tell them apart.
        """
        out = self._debate(
            *[response([tool_call("render_final_verdict", {}, f"c{i}")]) for i in range(4)],
        )
        self.assertIn("did not render verdict", out["result"]["verdict"]["rationale"])
        self.assertNotIn("unparsed_arguments", out["result"]["debate_trace"][-1])


if __name__ == "__main__":
    unittest.main()
