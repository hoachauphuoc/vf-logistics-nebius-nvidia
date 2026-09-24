"""
Unit tests for the observability module.

These tests verify:
1. Structured logging formatter
2. Metrics collection
3. Trace context propagation
4. Business event logging
"""

from __future__ import annotations

import json
import logging

import pytest

from vf_logistics.observability import (
    StructuredFormatter,
    Metrics,
    set_trace_context,
    get_trace_context,
    log_business_event,
    configure_logging,
    trace_operation,
)


class TestStructuredFormatter:
    """Tests for JSON structured logging."""

    def test_format_produces_valid_json(self):
        """Formatter produces valid JSON output."""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)

        # Should be valid JSON
        parsed = json.loads(output)
        assert parsed["message"] == "Test message"
        assert parsed["severity"] == "INFO"
        assert "timestamp" in parsed

    def test_format_includes_trace_context(self):
        """Formatter includes trace context when set."""
        set_trace_context(trace_id="abc123", span_id="def456", case_id="CASE-001")

        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=42,
            msg="Test with context",
            args=(),
            exc_info=None,
        )

        output = formatter.format(record)
        parsed = json.loads(output)

        assert "abc123" in parsed.get("logging.googleapis.com/trace", "")
        assert parsed.get("logging.googleapis.com/spanId") == "def456"
        assert parsed.get("case_id") == "CASE-001"

        # Clean up context
        set_trace_context(trace_id="", span_id="", case_id=None)

    def test_format_maps_severity_correctly(self):
        """Severity levels are mapped to Cloud Logging format."""
        formatter = StructuredFormatter()

        test_cases = [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ]

        for level, expected_severity in test_cases:
            record = logging.LogRecord(
                name="test",
                level=level,
                pathname="test.py",
                lineno=1,
                msg="Test",
                args=(),
                exc_info=None,
            )
            output = formatter.format(record)
            parsed = json.loads(output)
            assert parsed["severity"] == expected_severity


class TestMetrics:
    """Tests for metrics collection."""

    def test_increment_counter(self):
        """Counter can be incremented."""
        metrics = Metrics()
        # Clear existing counters for test isolation
        metrics._counters.clear()

        metrics.increment("test_counter")
        metrics.increment("test_counter")
        metrics.increment("test_counter", value=3)

        snapshot = metrics.snapshot()
        assert snapshot["counters"]["test_counter"] == 5

    def test_increment_with_labels(self):
        """Counter supports labels."""
        metrics = Metrics()
        metrics._counters.clear()

        metrics.increment("http_requests", labels={"method": "GET", "status": "200"})
        metrics.increment("http_requests", labels={"method": "POST", "status": "201"})
        metrics.increment("http_requests", labels={"method": "GET", "status": "200"})

        snapshot = metrics.snapshot()
        # Labels create separate counter keys
        assert len([k for k in snapshot["counters"] if "http_requests" in k]) == 2

    def test_observe_histogram(self):
        """Histogram observations are recorded."""
        metrics = Metrics()
        metrics._histograms.clear()

        metrics.observe("latency_ms", 100)
        metrics.observe("latency_ms", 200)
        metrics.observe("latency_ms", 150)

        snapshot = metrics.snapshot()
        latency = snapshot["histograms"]["latency_ms"]
        assert latency["count"] == 3
        assert latency["sum"] == 450
        assert latency["min"] == 100
        assert latency["max"] == 200

    def test_set_gauge(self):
        """Gauge can be set to a value."""
        metrics = Metrics()
        metrics._gauges.clear()

        metrics.set_gauge("queue_depth", 42)
        metrics.set_gauge("queue_depth", 38)  # Overwrites

        snapshot = metrics.snapshot()
        assert snapshot["gauges"]["queue_depth"] == 38

    def test_singleton_instance(self):
        """Metrics is a singleton."""
        m1 = Metrics()
        m2 = Metrics()
        assert m1 is m2


class TestTraceContext:
    """Tests for trace context propagation."""

    def test_set_and_get_context(self):
        """Context can be set and retrieved."""
        set_trace_context(trace_id="trace-123", case_id="CASE-456")

        ctx = get_trace_context()
        assert ctx["trace_id"] == "trace-123"
        assert ctx["case_id"] == "CASE-456"

        # Clean up
        set_trace_context(trace_id="", case_id=None)

    def test_context_updates_are_merged(self):
        """Setting context merges with existing values."""
        set_trace_context(trace_id="trace-abc")
        set_trace_context(case_id="CASE-789")

        ctx = get_trace_context()
        assert ctx["trace_id"] == "trace-abc"
        assert ctx["case_id"] == "CASE-789"

        # Clean up
        set_trace_context(trace_id="", case_id=None)


class TestTraceDecorator:
    """Tests for the trace_operation decorator."""

    def test_sync_function_traced(self):
        """Synchronous functions are traced."""
        metrics = Metrics()
        metrics._counters.clear()
        metrics._histograms.clear()

        @trace_operation("test_sync_op")
        def sync_func():
            return "result"

        result = sync_func()

        assert result == "result"
        snapshot = metrics.snapshot()
        assert "test_sync_op_success" in snapshot["counters"]
        assert any("test_sync_op_latency_ms" in k for k in snapshot["histograms"])

    def test_async_function_traced(self):
        """Async functions are traced."""
        import asyncio

        metrics = Metrics()
        metrics._counters.clear()
        metrics._histograms.clear()

        @trace_operation("test_async_op")
        async def async_func():
            return "async result"

        result = asyncio.run(async_func())

        assert result == "async result"
        snapshot = metrics.snapshot()
        assert "test_async_op_success" in snapshot["counters"]

    def test_errors_are_tracked(self):
        """Errors are tracked in metrics."""
        metrics = Metrics()
        metrics._counters.clear()

        @trace_operation("test_error_op")
        def failing_func():
            raise ValueError("Test error")

        with pytest.raises(ValueError):
            failing_func()

        snapshot = metrics.snapshot()
        assert any("test_error_op_error" in k for k in snapshot["counters"])


class TestBusinessEvents:
    """Tests for business event logging."""

    def test_business_event_logged(self, caplog):
        """Business events are logged with correct structure."""
        metrics = Metrics()
        metrics._counters.clear()

        with caplog.at_level(logging.INFO):
            log_business_event(
                "case_state_change",
                case_id="CASE-001",
                from_state="INGESTED",
                to_state="SPECIALISTS_DONE",
            )

        # Check metrics were updated
        snapshot = metrics.snapshot()
        assert any("business_event_case_state_change" in k for k in snapshot["counters"])


class TestConfigureLogging:
    """Tests for logging configuration."""

    def test_configure_sets_level(self):
        """configure_logging sets the root logger level."""
        configure_logging("DEBUG")
        assert logging.getLogger().level == logging.DEBUG

        configure_logging("WARNING")
        assert logging.getLogger().level == logging.WARNING

        # Reset to INFO for other tests
        configure_logging("INFO")

    def test_configure_reduces_library_noise(self):
        """Third-party library loggers are quieted."""
        configure_logging("DEBUG")

        # These should be WARNING or higher
        assert logging.getLogger("urllib3").level >= logging.WARNING
        assert logging.getLogger("google").level >= logging.WARNING
