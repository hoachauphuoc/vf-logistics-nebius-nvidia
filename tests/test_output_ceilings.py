"""
Output ceilings: containment, not thrift.

Measured on a 20-case production run. Two calls returned exactly 8,192 output tokens
and both were `parse_error` -- two of only three parse errors on the whole board. The
investigation one ended

    ', {}, {}, {}, {}, {}, {}, {}, {},\\n...[truncated, 28364 more chars]'

a degenerate repetition loop emitting empty objects until it hit the provider's own
limit: 38.6 seconds and $0.007873 for a single call that returned nothing usable, or
29% of all investigation spend on that run. The compliance one burned 45.2 seconds the
same way. Nothing in the repository set `max_tokens`, and the three `nebius_client`
helpers did not even accept it, so no call site could have.

A ceiling does NOT stop the failure. A truncated JSON object is still invalid JSON, so
the case still routes to a human -- which it already did. What the ceiling changes is
the price: bounded tokens, bounded latency, a runaway that stops in seconds rather than
three quarters of a minute.

That is why every value has headroom over the largest LEGITIMATE output its agent has
produced rather than sitting near the average. Too tight a ceiling converts working
calls into parse errors, and one human review costs incomparably more than the tokens
it saved. The tests below pin that headroom, because the tempting change -- trimming
these numbers toward the median to save more -- is the one that would hurt.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import nebius_client  # noqa: E402
from vf_logistics.agents import (  # noqa: E402
    compliance_agent,
    debate_agent,
    document_agent,
    fraud_detection_agent,
    hs_classifier_agent,
    investigation_agent,
    zero_day_agent,
)

# The largest legitimate output each agent produced on the measured run, excluding the
# two runaway calls. A ceiling below any of these would truncate real work.
MEASURED_LEGITIMATE_MAX = {
    "fraud_detection": 1057,
    "compliance": 1940,
    "investigation": 1387,
    "hs_classifier": 3442,
    "zero_day": 5011,
    "debate": 403,
}

CEILINGS = {
    "fraud_detection": fraud_detection_agent.MAX_OUTPUT_TOKENS,
    "compliance": compliance_agent.MAX_OUTPUT_TOKENS,
    "investigation": investigation_agent.MAX_OUTPUT_TOKENS,
    "hs_classifier": hs_classifier_agent.MAX_OUTPUT_TOKENS,
    "zero_day": zero_day_agent.MAX_OUTPUT_TOKENS,
    "debate": debate_agent.MAX_OUTPUT_TOKENS,
}


class TestTheCeilingHelper(unittest.TestCase):
    def test_an_unset_ceiling_sends_no_parameter_at_all(self):
        """
        Omitted, not passed as None.

        An unset ceiling must produce exactly the request this client sent before the
        parameter existed. Passing `max_tokens=None` explicitly would be a different
        request, and whether a provider treats it as "no limit" or rejects it is not
        something to depend on.
        """
        self.assertEqual(nebius_client._ceiling(None), {})

    def test_a_set_ceiling_is_passed_through_as_an_int(self):
        self.assertEqual(nebius_client._ceiling(4000), {"max_tokens": 4000})
        self.assertEqual(nebius_client._ceiling("4000"), {"max_tokens": 4000})


class TestTheHelpersAcceptAndForwardIt(unittest.TestCase):
    def _captured(self, coro_factory):
        captured: dict = {}

        class FakeCompletions:
            async def create(self, **kw):
                captured.update(kw)

                class R:
                    choices = [type("C", (), {"message": type("M", (), {"content": "{}"})()})()]
                    usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()

                return R()

        class FakeClient:
            chat = type("Chat", (), {"completions": FakeCompletions()})()

        import asyncio

        with patch.object(nebius_client, "get_client", return_value=FakeClient()), \
             patch.object(nebius_client.budget, "assert_within_budget", new=AsyncMock()):
            asyncio.run(coro_factory())
        return captured

    def test_complete_json_forwards_the_ceiling(self):
        kw = self._captured(lambda: nebius_client.complete_json(
            model="m", system_prompt="s", user_text="u", max_tokens=1234,
        ))
        self.assertEqual(kw["max_tokens"], 1234)

    def test_complete_json_omits_it_when_unset(self):
        kw = self._captured(lambda: nebius_client.complete_json(
            model="m", system_prompt="s", user_text="u",
        ))
        self.assertNotIn("max_tokens", kw)

    def test_complete_with_tools_forwards_the_ceiling(self):
        kw = self._captured(lambda: nebius_client.complete_with_tools(
            model="m", messages=[], tools=[], max_tokens=777,
        ))
        self.assertEqual(kw["max_tokens"], 777)

    def test_complete_vision_json_forwards_the_ceiling(self):
        kw = self._captured(lambda: nebius_client.complete_vision_json(
            model="m", system_prompt="s", document_bytes=b"x",
            mime_type="image/png", user_text="u", max_tokens=555,
        ))
        self.assertEqual(kw["max_tokens"], 555)


class TestEveryCeilingHasHeadroom(unittest.TestCase):
    """
    The guard against the tempting optimisation.

    Trimming these toward the observed median would save tokens on paper and buy parse
    errors in production. Each ceiling must stay at least double the largest legitimate
    output its agent has been measured producing.
    """

    def test_each_ceiling_is_at_least_double_the_measured_legitimate_maximum(self):
        for agent, observed in MEASURED_LEGITIMATE_MAX.items():
            with self.subTest(agent=agent):
                ceiling = CEILINGS[agent]
                self.assertGreaterEqual(
                    ceiling, observed * 2,
                    f"{agent}: ceiling {ceiling} is too close to its measured "
                    f"legitimate maximum of {observed}; truncating valid JSON costs a "
                    f"human review, which is worth more than the tokens saved",
                )

    def test_no_ceiling_is_above_the_runaway_that_motivated_it(self):
        """
        A ceiling at or above 8,192 would not have bounded either observed runaway,
        which is the entire reason these exist. zero_day is excluded: its ceiling
        covers a whole multi-round screen rather than one reply.
        """
        for agent in ("fraud_detection", "compliance", "investigation", "debate"):
            with self.subTest(agent=agent):
                self.assertLess(
                    CEILINGS[agent], 8192,
                    f"{agent}: a ceiling at or above the observed runaway bounds nothing",
                )

    def test_the_forced_verdict_ceiling_is_tighter_than_a_tool_round(self):
        """That call supplies no tools and asks only for JSON, so length is not work --
        and it is the most repeated call in the agent."""
        self.assertLess(
            zero_day_agent.MAX_VERDICT_TOKENS, zero_day_agent.MAX_OUTPUT_TOKENS,
        )


class TestEveryCallSiteSetsOne(unittest.TestCase):
    """
    Source check. A ceiling that exists as a constant but is never passed is worse
    than none, because it reads as protection that is not there.
    """

    def test_no_model_call_is_left_without_a_ceiling(self):
        import pathlib
        import re

        def argument_text(source: str, open_paren: int) -> str:
            """
            The text between a call's parentheses, matched by balancing them.

            A non-greedy regex is not enough here: zero_day_agent's forced-verdict call
            contains a parenthesised string literal inside its `messages` argument, so
            a pattern stopping at the first `)` reads only part of the call and reports
            a ceiling as missing when it is four lines further down.
            """
            depth = 0
            for i in range(open_paren, len(source)):
                if source[i] == "(":
                    depth += 1
                elif source[i] == ")":
                    depth -= 1
                    if depth == 0:
                        return source[open_paren + 1:i]
            return source[open_paren:]

        agents_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "vf_logistics" / "agents"
        missing: list[str] = []
        for path in sorted(agents_dir.glob("*.py")):
            if path.name.startswith("_"):
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(
                r"nebius_client\.complete_(?:json|with_tools|vision_json)\s*\(", text,
            ):
                args = argument_text(text, match.end() - 1)
                if "max_tokens" not in args:
                    line = text[: match.start()].count("\n") + 1
                    missing.append(f"{path.name}:{line}")

        self.assertEqual(
            missing, [],
            "these model calls have no output ceiling: " + ", ".join(missing),
        )

    def test_the_scan_above_finds_the_calls_it_claims_to(self):
        """
        Guards the guard. A regex that matched nothing would pass the test above
        silently, which is the failure mode of every source-inspection check.
        """
        import pathlib
        import re

        agents_dir = pathlib.Path(__file__).resolve().parents[1] / "src" / "vf_logistics" / "agents"
        found = sum(
            len(re.findall(
                r"nebius_client\.complete_(?:json|with_tools|vision_json)\s*\(",
                p.read_text(encoding="utf-8"),
            ))
            for p in agents_dir.glob("*.py")
            if not p.name.startswith("_")
        )
        self.assertGreaterEqual(
            found, 9,
            "the scan should be finding every model call across the agents; a count "
            "this low means the pattern has drifted from the code",
        )


class TestTruncationIsReportedAsTruncation(unittest.TestCase):
    """
    `finish_reason: "length"` is Token Factory's documented truncation signal, and it
    separates two failures that look identical downstream.

    A truncated JSON object does not parse, so parse_model_json reports "model reply
    was not valid JSON" -- which reads as a model quality problem when the real cause is
    that the reply outgrew its ceiling. One calls for a prompt change, the other for a
    larger number. Without this log, a ceiling set too tight would look like the model
    getting worse.
    """

    def _response(self, finish_reason):
        class R:
            choices = [
                type("C", (), {
                    "finish_reason": finish_reason,
                    "message": type("M", (), {"content": "{}"})(),
                })()
            ]
            usage = type("U", (), {"prompt_tokens": 1, "completion_tokens": 1})()

        return R()

    def test_a_length_finish_is_logged_at_error(self):
        import logging

        with self.assertLogs("vf_logistics.nebius_client", level=logging.ERROR) as cap:
            nebius_client._note_truncation("agent[x]", self._response("length"), 4000)
        joined = "\n".join(cap.output)
        self.assertIn("OUTPUT TRUNCATED AT CEILING", joined)
        self.assertIn("agent[x]", joined)
        self.assertIn("4000", joined)

    def test_a_normal_finish_logs_nothing(self):
        import logging

        with self.assertNoLogs("vf_logistics.nebius_client", level=logging.ERROR):
            nebius_client._note_truncation("agent[x]", self._response("stop"), 4000)
        with self.assertNoLogs("vf_logistics.nebius_client", level=logging.ERROR):
            nebius_client._note_truncation("agent[x]", self._response("tool_calls"), 4000)

    def test_an_unset_ceiling_names_the_provider_default_in_the_log(self):
        """
        8,192 is Token Factory's documented default when max_tokens is omitted -- not a
        model limit. Both runaway calls on the measured run returned exactly that, and
        the log should say where the number came from so nobody hunts for a model bug.
        """
        import logging

        with self.assertLogs("vf_logistics.nebius_client", level=logging.ERROR) as cap:
            nebius_client._note_truncation("agent[x]", self._response("length"), None)
        self.assertIn("8192 (provider default)", "\n".join(cap.output))

    def test_a_malformed_response_does_not_raise(self):
        """Diagnostics must never be the thing that breaks a request."""
        class Empty:
            choices: list = []

        nebius_client._note_truncation("agent[x]", Empty(), 100)
        nebius_client._note_truncation("agent[x]", object(), 100)


if __name__ == "__main__":
    unittest.main()
