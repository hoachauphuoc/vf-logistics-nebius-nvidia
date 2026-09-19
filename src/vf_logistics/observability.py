"""
Structured logging and OpenTelemetry observability for the fraud detection service.

Provides:
- JSON-structured logging for Cloud Logging ingestion
- Distributed tracing with OpenTelemetry
- Metrics collection for key business and operational events
- Request context propagation

Track: The Taskmaster - Autonomous Workflow Automation
Hackathon: All Things Agentic 2026
"""

from __future__ import annotations

import json
import logging
import os
import time
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from functools import wraps
from typing import Any, Callable

# Context variables for request tracing
_trace_context: ContextVar[dict[str, Any]] = ContextVar("trace_context", default={})


@dataclass
class RequestContext:
    """Context for a single request, propagated through the call stack."""

    trace_id: str = ""
    span_id: str = ""
    case_id: str | None = None
    user_email: str | None = None
    request_path: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


def get_trace_context() -> dict[str, Any]:
    """Get current trace context."""
    return _trace_context.get()


def set_trace_context(**kwargs: Any) -> None:
    """Set trace context values."""
    ctx = _trace_context.get().copy()
    ctx.update(kwargs)
    _trace_context.set(ctx)


class StructuredFormatter(logging.Formatter):
    """
    JSON formatter for Cloud Logging.

    Output format matches Cloud Logging's structured payload spec so fields like
    severity, trace, and labels are correctly parsed.
    """

    SEVERITY_MAP = {
        logging.DEBUG: "DEBUG",
        logging.INFO: "INFO",
        logging.WARNING: "WARNING",
        logging.ERROR: "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_trace_context()

        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": self.SEVERITY_MAP.get(record.levelno, "DEFAULT"),
            "message": record.getMessage(),
            "logger": record.name,
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # Add trace context if available
        if ctx.get("trace_id"):
            project_id = os.getenv("PROJECT_ID", "")
            log_entry["logging.googleapis.com/trace"] = (
                f"projects/{project_id}/traces/{ctx['trace_id']}"
            )
        if ctx.get("span_id"):
            log_entry["logging.googleapis.com/spanId"] = ctx["span_id"]

        # Add business context
        if ctx.get("case_id"):
            log_entry["case_id"] = ctx["case_id"]
        if ctx.get("user_email"):
            log_entry["user_email"] = ctx["user_email"]
        if ctx.get("request_path"):
            log_entry["httpRequest"] = {"requestUrl": ctx["request_path"]}

        # Add any extra fields from the log record
        if hasattr(record, "extra") and isinstance(record.extra, dict):
            log_entry.update(record.extra)

        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def configure_logging(log_level: str = "INFO") -> None:
    """
    Configure structured logging for the application.

    In production (Cloud Run), outputs JSON for Cloud Logging.
    In development, outputs human-readable format.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)

    # Remove existing handlers
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)

    handler = logging.StreamHandler()

    # Use JSON format in production, readable format in development
    if os.getenv("K_SERVICE"):  # Cloud Run sets this
        handler.setFormatter(StructuredFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
            )
        )

    root_logger.addHandler(handler)

    # Reduce noise from third-party libraries
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google").setLevel(logging.WARNING)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger with the given name."""
    return logging.getLogger(name)


# --------------------------------------------------------------------------
# Metrics collection
# --------------------------------------------------------------------------

class Metrics:
    """
    Simple in-memory metrics collection.

    In a production deployment, this would push to Cloud Monitoring or
    Prometheus. For the hackathon demo, metrics are aggregated in memory
    and exposed via the /metrics endpoint.
    """

    _instance: "Metrics | None" = None

    def __new__(cls) -> "Metrics":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._counters = {}
            cls._instance._histograms = {}
            cls._instance._gauges = {}
        return cls._instance

    def increment(self, name: str, value: int = 1, labels: dict[str, str] | None = None) -> None:
        """Increment a counter."""
        key = (name, tuple(sorted((labels or {}).items())))
        self._counters[key] = self._counters.get(key, 0) + value

    def observe(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Record a histogram observation (e.g., latency)."""
        key = (name, tuple(sorted((labels or {}).items())))
        if key not in self._histograms:
            self._histograms[key] = {"count": 0, "sum": 0, "min": float("inf"), "max": 0}
        self._histograms[key]["count"] += 1
        self._histograms[key]["sum"] += value
        self._histograms[key]["min"] = min(self._histograms[key]["min"], value)
        self._histograms[key]["max"] = max(self._histograms[key]["max"], value)

    def set_gauge(self, name: str, value: float, labels: dict[str, str] | None = None) -> None:
        """Set a gauge value."""
        key = (name, tuple(sorted((labels or {}).items())))
        self._gauges[key] = value

    def snapshot(self) -> dict[str, Any]:
        """Return current metrics state."""
        return {
            "counters": {
                f"{name}[{dict(labels)}]" if labels else name: value
                for (name, labels), value in self._counters.items()
            },
            "histograms": {
                f"{name}[{dict(labels)}]" if labels else name: stats
                for (name, labels), stats in self._histograms.items()
            },
            "gauges": {
                f"{name}[{dict(labels)}]" if labels else name: value
                for (name, labels), value in self._gauges.items()
            },
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }


def get_metrics() -> Metrics:
    """Get the singleton metrics instance."""
    return Metrics()


# --------------------------------------------------------------------------
# Tracing decorators
# --------------------------------------------------------------------------

def trace_operation(operation_name: str) -> Callable:
    """
    Decorator to trace an operation with timing and error tracking.

    Logs start/end, records latency metrics, and captures errors.
    """
    def decorator(func: Callable) -> Callable:
        logger = get_logger(func.__module__)

        @wraps(func)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            metrics = get_metrics()

            logger.info(
                f"Starting {operation_name}",
                extra={"extra": {"operation": operation_name, "phase": "start"}},
            )

            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000

                metrics.increment(f"{operation_name}_success")
                metrics.observe(f"{operation_name}_latency_ms", elapsed_ms)

                logger.info(
                    f"Completed {operation_name} in {elapsed_ms:.1f}ms",
                    extra={
                        "extra": {
                            "operation": operation_name,
                            "phase": "complete",
                            "latency_ms": elapsed_ms,
                        }
                    },
                )
                return result

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start) * 1000
                metrics.increment(f"{operation_name}_error", labels={"error_type": type(e).__name__})
                metrics.observe(f"{operation_name}_latency_ms", elapsed_ms, labels={"status": "error"})

                logger.error(
                    f"Failed {operation_name} after {elapsed_ms:.1f}ms: {e}",
                    extra={
                        "extra": {
                            "operation": operation_name,
                            "phase": "error",
                            "latency_ms": elapsed_ms,
                            "error_type": type(e).__name__,
                            "error_message": str(e),
                        }
                    },
                    exc_info=True,
                )
                raise

        @wraps(func)
        def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
            start = time.perf_counter()
            metrics = get_metrics()

            logger.info(
                f"Starting {operation_name}",
                extra={"extra": {"operation": operation_name, "phase": "start"}},
            )

            try:
                result = func(*args, **kwargs)
                elapsed_ms = (time.perf_counter() - start) * 1000

                metrics.increment(f"{operation_name}_success")
                metrics.observe(f"{operation_name}_latency_ms", elapsed_ms)

                logger.info(
                    f"Completed {operation_name} in {elapsed_ms:.1f}ms",
                    extra={
                        "extra": {
                            "operation": operation_name,
                            "phase": "complete",
                            "latency_ms": elapsed_ms,
                        }
                    },
                )
                return result

            except Exception as e:
                elapsed_ms = (time.perf_counter() - start) * 1000
                metrics.increment(f"{operation_name}_error", labels={"error_type": type(e).__name__})

                logger.error(
                    f"Failed {operation_name} after {elapsed_ms:.1f}ms: {e}",
                    extra={
                        "extra": {
                            "operation": operation_name,
                            "phase": "error",
                            "latency_ms": elapsed_ms,
                            "error_type": type(e).__name__,
                        }
                    },
                    exc_info=True,
                )
                raise

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def log_business_event(
    event_type: str,
    case_id: str | None = None,
    **event_data: Any,
) -> None:
    """
    Log a business event for analytics and audit.

    Business events are higher-level than operational logs - they capture
    domain-meaningful occurrences like case state changes, decisions made,
    and policy violations detected.
    """
    logger = get_logger("business_events")
    metrics = get_metrics()

    metrics.increment(f"business_event_{event_type}")

    ctx = get_trace_context()
    logger.info(
        f"Business event: {event_type}",
        extra={
            "extra": {
                "event_type": event_type,
                "case_id": case_id or ctx.get("case_id"),
                **event_data,
            }
        },
    )


# --------------------------------------------------------------------------
# Flask middleware helpers
# --------------------------------------------------------------------------

def extract_trace_from_request(request: Any) -> tuple[str, str]:
    """
    Extract trace and span IDs from incoming request headers.

    Supports Cloud Trace header format: X-Cloud-Trace-Context
    Format: TRACE_ID/SPAN_ID;o=TRACE_TRUE
    """
    trace_header = request.headers.get("X-Cloud-Trace-Context", "")
    if not trace_header:
        return "", ""

    parts = trace_header.split("/")
    trace_id = parts[0] if parts else ""
    span_id = parts[1].split(";")[0] if len(parts) > 1 else ""
    return trace_id, span_id


def init_request_context(request: Any) -> None:
    """Initialize trace context for an incoming request."""
    trace_id, span_id = extract_trace_from_request(request)
    set_trace_context(
        trace_id=trace_id,
        span_id=span_id,
        request_path=request.path,
    )


# --------------------------------------------------------------------------
# Key metrics to track
# --------------------------------------------------------------------------

# Business metrics
METRIC_CASES_INGESTED = "cases_ingested_total"
METRIC_CASES_AUTO_CLEARED = "cases_auto_cleared_total"
METRIC_CASES_ESCALATED = "cases_escalated_total"
METRIC_CASES_HELD_FOR_REVIEW = "cases_held_for_review_total"
METRIC_CASES_DEAD_LETTER = "cases_dead_letter_total"
METRIC_GATE_DENIALS = "gate_denials_total"
METRIC_HUMAN_DECISIONS = "human_decisions_total"

# Operational metrics
METRIC_AGENT_LATENCY = "agent_latency_ms"
METRIC_LLM_TOKENS_INPUT = "llm_tokens_input_total"
METRIC_LLM_TOKENS_OUTPUT = "llm_tokens_output_total"
METRIC_OPTIMISTIC_LOCK_CONFLICTS = "optimistic_lock_conflicts_total"
METRIC_AUDIT_ENTRIES = "audit_entries_total"

# Security metrics
METRIC_INJECTION_BLOCKED = "injection_blocked_total"
METRIC_MODEL_ARMOR_BLOCKED = "model_armor_blocked_total"
METRIC_AUTH_FAILURES = "auth_failures_total"
