"""
Edges of two reporting modules: the structured log line Cloud Logging reads (trace, case and user context, extra
fields, exceptions), the tracing decorator on async work, the Cloud Trace header; and the work list's count of
refused actions and its reading of timestamps and resolutions.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from vf_logistics import observability, worklist  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def clean_context():
    token = observability._trace_context.set({})
    yield
    observability._trace_context.reset(token)


def record(message="hello", level=logging.INFO, exc_info=None, extra=None):
    made = logging.LogRecord("vf.test", level, __file__, 7, message, None, exc_info, func="fn")
    if extra is not None:
        made.extra = extra
    return made


class TestStructuredLogLine:
    def line(self, **kwargs):
        return json.loads(observability.StructuredFormatter().format(record(**kwargs)))

    def test_the_basics_are_present_and_an_unknown_level_is_default(self):
        entry = self.line(level=35)
        assert entry["severity"] == "DEFAULT"
        assert (entry["message"], entry["logger"], entry["function"], entry["line"]) == ("hello", "vf.test", "fn", 7)

    def test_trace_case_user_and_path_are_attached_when_known(self):
        observability.set_trace_context(
            trace_id="T1", span_id="S1", case_id="CASE-1", user_email="a@x.com", request_path="/api/v1/cases",
        )
        with patch.dict(os.environ, {"PROJECT_ID": "proj"}):
            entry = self.line()
        assert entry["logging.googleapis.com/trace"] == "projects/proj/traces/T1"
        assert entry["logging.googleapis.com/spanId"] == "S1"
        assert (entry["case_id"], entry["user_email"]) == ("CASE-1", "a@x.com")
        assert entry["httpRequest"] == {"requestUrl": "/api/v1/cases"}

    def test_nothing_is_attached_when_nothing_is_known(self):
        entry = self.line()
        assert not any(k in entry for k in ("case_id", "user_email", "httpRequest", "logging.googleapis.com/trace"))

    def test_extra_fields_are_merged_and_a_non_object_extra_is_ignored(self):
        assert self.line(extra={"operation": "x"})["operation"] == "x"
        assert "extra" not in self.line(extra="not a dict")

    def test_an_exception_is_included_as_text(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys as _sys

            entry = self.line(level=logging.ERROR, exc_info=_sys.exc_info())
        assert "ValueError: boom" in entry["exception"]


class TestTracedAsyncOperations:
    def test_success_counts_and_times_the_operation(self):
        metrics = MagicMock()

        @observability.trace_operation("do_work")
        async def work(x):
            return x + 1

        with patch.object(observability, "get_metrics", return_value=metrics):
            assert run(work(1)) == 2
        metrics.increment.assert_called_once_with("do_work_success")
        assert metrics.observe.call_args.args[0] == "do_work_latency_ms"

    def test_failure_counts_the_error_by_type_and_re_raises_it(self):
        metrics = MagicMock()

        @observability.trace_operation("do_work")
        async def work():
            raise KeyError("missing")

        with patch.object(observability, "get_metrics", return_value=metrics), pytest.raises(KeyError):
            run(work())
        metrics.increment.assert_called_once_with("do_work_error", labels={"error_type": "KeyError"})
        assert metrics.observe.call_args.kwargs["labels"] == {"status": "error"}

    def test_the_wrapped_function_keeps_its_name(self):
        @observability.trace_operation("x")
        async def named():
            return None

        assert named.__name__ == "named"


class TestCloudTraceHeader:
    def request(self, header):
        request = MagicMock()
        request.headers = {"X-Cloud-Trace-Context": header} if header is not None else {}
        request.path = "/p"
        return request

    def test_trace_and_span_are_split_and_the_option_flag_is_dropped(self):
        assert observability.extract_trace_from_request(self.request("abc/123;o=1")) == ("abc", "123")

    def test_a_header_with_only_a_trace_has_no_span(self):
        assert observability.extract_trace_from_request(self.request("abc")) == ("abc", "")

    def test_no_header_is_nothing(self):
        assert observability.extract_trace_from_request(self.request(None)) == ("", "")

    def test_a_request_starts_a_context_carrying_its_trace_and_path(self):
        observability.init_request_context(self.request("abc/123;o=1"))
        ctx = observability.get_trace_context()
        assert (ctx["trace_id"], ctx["span_id"], ctx["request_path"]) == ("abc", "123", "/p")


class TestLoggingSetup:
    def test_on_cloud_run_the_handler_writes_json_and_elsewhere_plain_text(self):
        root = logging.getLogger()
        saved = root.handlers[:], root.level
        try:
            with patch.dict(os.environ, {"K_SERVICE": "vf-app"}):
                observability.configure_logging("debug")
            assert isinstance(root.handlers[0].formatter, observability.StructuredFormatter)
            assert root.level == logging.DEBUG
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("K_SERVICE", None)
                observability.configure_logging("nonsense")
            assert not isinstance(root.handlers[0].formatter, observability.StructuredFormatter)
            assert root.level == logging.INFO
        finally:
            root.handlers[:] = saved[0]
            root.setLevel(saved[1])


class TestTimestampsAndResolutions:
    def test_a_z_suffixed_timestamp_is_read_and_junk_is_nothing(self):
        assert worklist._parse("2026-10-12T01:00:00Z").year == 2026
        for value in (None, "", 5, "yesterday"):
            assert worklist._parse(value) is None

    def test_a_case_is_resolved_by_who_resolved_it(self):
        assert worklist.resolution_kind({"state": "RELEASED_BY_HUMAN"}) == "released_by_reviewer"
        assert worklist.resolution_kind({"state": "BLOCKED_BY_HUMAN"}) == "blocked_by_reviewer"
        assert worklist.resolution_kind({"state": "AUTO_CLEARED", "cleared_by": "ai"}) == "cleared_by_ai"
        assert worklist.resolution_kind({"state": "AUTO_CLEARED"}) == "cleared_by_rules"

    def test_a_case_with_no_bucket_has_no_next_action(self):
        with patch.object(worklist, "bucket_for", return_value=None):
            assert worklist.next_action({}) is None

    def test_a_case_in_no_special_state_is_just_reviewed(self):
        with patch.object(worklist, "bucket_for", return_value="needs_review"):
            assert worklist.next_action({"validation": {"findings": []}}) == {"code": "review_case", "text": "Review the case and decide it."}


class TestRefusedActionsInTheWindow:
    def count(self, pages, since=None, until=None):
        store = MagicMock()
        store.query_audit = AsyncMock(side_effect=pages)
        with patch.object(worklist, "get_store", return_value=store):
            return run(worklist._refused_actions("t", since, until)), store

    def test_every_denied_entry_counts_across_pages(self):
        n, store = self.count([([{"at": "2026-10-03"}, {"at": "2026-10-02"}], "next"), ([{"at": "2026-10-01"}], None)])
        assert n == 3
        assert store.query_audit.call_count == 2

    def test_entries_after_the_end_of_the_window_are_skipped(self):
        n, _ = self.count([([{"at": "2026-10-09"}, {"at": "2026-10-03"}], None)], until="2026-10-05")
        assert n == 1

    def test_reaching_the_start_of_the_window_stops_the_scan(self):
        n, store = self.count([([{"at": "2026-10-09"}, {"at": "2026-09-01"}], "more")], since="2026-10-01")
        assert n == 1
        assert store.query_audit.call_count == 1
