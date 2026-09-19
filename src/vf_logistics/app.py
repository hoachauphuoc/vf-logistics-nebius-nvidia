"""
VF Logistics Fraud Detection - Main Flask Application
AI model layer on Nebius Token Factory (NVIDIA Nemotron + a vision model);
infrastructure (Cloud Run, Firestore, Pub/Sub, Model Armor) stays on Google Cloud.

Track: Best Apps and Agents
Hackathon: Nebius x NVIDIA Global AI Hackathon
"""

import asyncio
import base64
import json
import os
import re
import threading
from datetime import datetime, timezone
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import auth after dotenv so IAP_ENABLED is read correctly
from vf_logistics.auth import (
    require_auth,
    require_viewer,
    require_reviewer,
    require_operator,
    require_governance_admin,
    get_auth_context,
)

from vf_logistics import document_store
from vf_logistics import governance
from vf_logistics import orchestrator
from vf_logistics import simulator
from vf_logistics import tools
from vf_logistics import config as model_config
from vf_logistics.store import store_status
from vf_logistics.observability import (
    configure_logging,
    get_logger,
    get_metrics,
    init_request_context,
    set_trace_context,
    log_business_event,
    METRIC_CASES_INGESTED,
    METRIC_CASES_AUTO_CLEARED,
    METRIC_AUTH_FAILURES,
)

from vf_logistics.agents import (
    analyze_shipment,
    batch_analyze,
    screen_shipment,
    screen_entity,
    investigate_case,
    generate_report,
    mime_for,
    get_fraud_agent_info,
    get_compliance_agent_info,
    get_investigation_agent_info,
    get_document_agent_info
)

import pathlib as _pathlib

app = Flask(__name__,
            static_folder=str(_pathlib.Path(__file__).parent / "static"),
            static_url_path="/static")

# Rate limiting — protects AI-invoking and external API endpoints from abuse
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://",
)

# CORS: restrict to known origins (wildcard CORS allows any site to call our API)
_ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()
] or [
    "https://vf-logistics-f7rcctz26a-as.a.run.app",
    "https://vf-logistics-350828852747.asia-southeast1.run.app",
    "http://localhost:5000",
    "http://127.0.0.1:5000",
]
CORS(app, origins=_ALLOWED_ORIGINS)


@app.after_request
def _security_headers(response):
    """Add security headers to every response."""
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response

# Configure structured logging
configure_logging(os.getenv("LOG_LEVEL", "INFO"))
logger = get_logger(__name__)

_IS_PRODUCTION = os.getenv("STORE_BACKEND", "") == "firestore"


def _safe_error(e: Exception, status: int = 500):
    """Return a sanitized error response. Logs the real exception server-side."""
    logger.exception("Request failed: %s", e)
    if _IS_PRODUCTION:
        return jsonify({"error": "Internal server error"}), status
    return jsonify({"error": str(e)}), status


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


# ============== BACKGROUND WORKER ==============
#
# Every coroutine in the process runs on this one loop, including Flask request
# handlers via async_route below. Handlers used to call asyncio.run(), which
# closes its loop on the way out and left the module-level Vertex AI client
# holding a dead loop, so the second analysis in a container's life failed.
#
# In WORKER_MODE=poll the loop also drives the pipeline unattended, which needs
# --no-cpu-throttling and --min-instances=1 because Cloud Run otherwise freezes
# CPU between requests. The deployed default is WORKER_MODE=ondemand, where
# request handlers advance the pipeline and no always-on CPU is required.

_worker_loop: asyncio.AbstractEventLoop | None = None
_worker_lock = threading.Lock()


def _ensure_worker() -> asyncio.AbstractEventLoop:
    """Start the background loop once, on first use."""
    global _worker_loop
    with _worker_lock:
        if _worker_loop and _worker_loop.is_running():
            return _worker_loop

        loop = asyncio.new_event_loop()

        def _run() -> None:
            asyncio.set_event_loop(loop)
            loop.run_forever()

        threading.Thread(target=_run, name="orchestrator", daemon=True).start()
        orchestrator.start_worker(loop)
        _worker_loop = loop
        return loop


def _on_worker(coro):
    """Run a coroutine on the worker loop and wait for its result."""
    loop = _ensure_worker()
    return asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)


# Helper to run async functions in Flask
def async_route(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # These handlers run on the long-lived worker loop rather than a private
        # asyncio.run() loop per request. asyncio.run() closes its loop on the way
        # out, and the Vertex AI client is created once and cached at module level,
        # so it kept a reference to a loop that no longer existed - the second
        # single-agent analysis in a container's life failed with "Event loop is
        # closed". One loop for every coroutine in the process removes the class
        # of bug rather than the symptom.
        return _on_worker(f(*args, **kwargs))
    return wrapper


@app.before_request
def before_request_hook():
    """Initialize observability context for each request."""
    init_request_context(request)
    logger.debug(f"Request started: {request.method} {request.path}")


@app.after_request
def after_request_hook(response):
    """Log request completion."""
    logger.debug(
        f"Request completed: {request.method} {request.path} -> {response.status_code}"
    )
    return response


@app.route("/", methods=["GET"])
def index():
    """Serve the web dashboard."""
    return send_from_directory("static", "index.html")


@app.route("/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({
        "status": "healthy",
        "service": "VF Logistics Fraud Detection",
        "version": "2.0.0",
        "timestamp": utcnow(),
        "hackathon": "Nebius x NVIDIA Global AI Hackathon",
        "track": "Best Apps and Agents",
        "store": store_status(),
        "worker": orchestrator.worker_status()
    })


@app.route("/metrics", methods=["GET"])
@require_viewer
def metrics():
    """Expose application metrics for monitoring."""
    return jsonify(get_metrics().snapshot())


@app.route("/agents", methods=["GET"])
def list_agents():
    """List all available agents and their capabilities."""
    return jsonify({
        "agents": [
            get_document_agent_info(),
            get_fraud_agent_info(),
            get_compliance_agent_info(),
            get_investigation_agent_info()
        ]
    })


# ============== FRAUD DETECTION ENDPOINTS ==============

@app.route("/api/v1/fraud/analyze", methods=["POST"])
@require_operator
@limiter.limit("10 per minute")
@async_route
async def fraud_analyze():
    """Analyze a single shipment for fraud indicators."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        result = await analyze_shipment(data)
        return jsonify(result)
    
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/fraud/batch", methods=["POST"])
@require_operator
@async_route
async def fraud_batch():
    """Analyze multiple shipments in batch."""
    try:
        data = request.get_json()
        if not data or "shipments" not in data:
            return jsonify({"error": "No shipments provided"}), 400
        
        results = await batch_analyze(data["shipments"])
        return jsonify({
            "results": results,
            "count": len(results)
        })
    
    except Exception as e:
        return _safe_error(e)


# ============== COMPLIANCE ENDPOINTS ==============

@app.route("/api/v1/compliance/screen", methods=["POST"])
@require_operator
@async_route
async def compliance_screen():
    """Screen a shipment for compliance issues."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        result = await screen_shipment(data)
        return jsonify(result)
    
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/compliance/entity", methods=["POST"])
@require_operator
@async_route
async def compliance_entity():
    """Screen an entity for sanctions/compliance."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        result = await screen_entity(data)
        return jsonify(result)
    
    except Exception as e:
        return _safe_error(e)


# ============== INVESTIGATION ENDPOINTS ==============

@app.route("/api/v1/investigation/case", methods=["POST"])
@require_operator
@async_route
async def investigation_case():
    """Investigate a flagged case."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        result = await investigate_case(data)
        return jsonify(result)
    
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/investigation/report", methods=["POST"])
@require_operator
@async_route
async def investigation_report():
    """Generate consolidated investigation report."""
    try:
        data = request.get_json()
        if not data or "investigations" not in data:
            return jsonify({"error": "No investigations provided"}), 400
        
        result = await generate_report(data["investigations"])
        return jsonify(result)
    
    except Exception as e:
        return _safe_error(e)


# ============== AUTONOMOUS ORCHESTRATION ==============
#
# These endpoints are the Taskmaster surface. Nothing here waits for an agent:
# ingestion returns as soon as the case is durably recorded, and the background
# worker drives the multi-step workflow to completion on its own.

@app.route("/api/v1/events/shipment", methods=["POST"])
def event_shipment():
    """
    Shipment-created event sink.

    Accepts either a bare shipment object or a Pub/Sub push envelope, so the
    same endpoint serves a real subscription and a direct producer.
    """
    try:
        body = request.get_json(silent=True) or {}

        # Pub/Sub push: {"message": {"data": "<base64>"}, "subscription": ...}
        if "message" in body and isinstance(body["message"], dict):
            encoded = body["message"].get("data", "")
            try:
                shipment = json.loads(base64.b64decode(encoded).decode("utf-8"))
            except Exception:
                return jsonify({"error": "could not decode Pub/Sub message data"}), 400
        else:
            shipment = body

        if not shipment:
            return jsonify({"error": "No shipment provided"}), 400

        case = _on_worker(orchestrator.ingest_shipment(shipment))

        # In request-driven mode this delivery is the only wake-up we get, so
        # the workflow is run to completion before responding. The Pub/Sub
        # subscription must therefore carry a generous ack deadline; see README.
        if orchestrator.WORKER_MODE != "poll":
            case = _on_worker(orchestrator.advance_until_terminal(case))

        return jsonify({
            "accepted": True,
            "case_id": case["case_id"],
            "state": case["state"],
            "decision": case.get("decision")
        }), 202

    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/simulate", methods=["POST"])
@require_operator
def simulate():
    """Inject the scripted demo batch and return immediately."""
    try:
        run_tag = datetime.now(timezone.utc).strftime("%H%M%S")
        shipments = simulator.scripted_shipments(run_tag)

        cases = [
            _on_worker(orchestrator.ingest_shipment(s))["case_id"]
            for s in shipments
        ]

        return jsonify({
            "injected": len(cases),
            "case_ids": cases,
            "note": "Workflow is running in the background; poll /api/v1/orchestrator/state"
        }), 202

    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/orchestrator/state", methods=["GET"])
@require_viewer
def orchestrator_state():
    """
    Full projection for the operations dashboard.

    In request-driven mode this endpoint also advances the pipeline, because the
    dashboard polling it is the only thing keeping the container awake. Pass
    `drain=0` for a pure read.
    """
    try:
        limit = int(request.args.get("limit", 60))
        drain = request.args.get("drain", "1") != "0"

        drained = None
        if drain and orchestrator.WORKER_MODE != "poll":
            drained = _on_worker(orchestrator.drain(max_cases=1))

        snapshot = _on_worker(orchestrator.snapshot(limit))
        if drained:
            snapshot["drained_this_request"] = drained
        return jsonify(snapshot)
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/cases", methods=["GET"])
@require_viewer
def list_cases():
    """
    Cursor-paginated, slim case listing for the board.

    Unlike `/api/v1/orchestrator/state`, this scales past a fixed window:
    pass `cursor` (the `next_cursor` from the previous response) to walk
    forward through the whole collection, and `state` to filter server-side
    on an indexed field rather than filtering a fetched page client-side.
    """
    try:
        cursor = request.args.get("cursor")
        limit = min(int(request.args.get("limit", 50)), 200)
        state_param = request.args.get("state", "").strip()
        states = tuple(s.strip() for s in state_param.split(",") if s.strip()) or None

        items, next_cursor = _on_worker(
            orchestrator.list_cases_page(states=states, cursor=cursor, limit=limit)
        )
        return jsonify({"items": items, "next_cursor": next_cursor})
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/audit", methods=["GET"])
@require_viewer
def list_audit():
    """
    Cursor-paginated audit search.

    Filters are exact-match on an indexed field (`case_id`, `action`, or
    `status`) and mutually exclusive - combining more than one would need a
    wider composite index than this project declares. The UI enforces this
    by clearing the other filters when one is chosen, rather than silently
    returning a partial combined result.
    """
    try:
        cursor = request.args.get("cursor")
        limit = min(int(request.args.get("limit", 50)), 200)
        case_id = request.args.get("case_id") or None
        action = request.args.get("action") or None
        status = request.args.get("status") or None

        from vf_logistics.store import get_store

        items, next_cursor = _on_worker(
            get_store().query_audit(
                case_id=case_id,
                action=action,
                status=status,
                cursor=cursor,
                limit=limit,
            )
        )
        return jsonify({"items": items, "next_cursor": next_cursor})
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/events", methods=["GET"])
@require_viewer
def list_events():
    """Cursor-paginated event feed."""
    try:
        cursor = request.args.get("cursor")
        limit = min(int(request.args.get("limit", 80)), 200)

        from vf_logistics.store import get_store

        items, next_cursor = _on_worker(
            get_store().query_events(cursor=cursor, limit=limit)
        )
        return jsonify({"items": items, "next_cursor": next_cursor})
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/metrics/summary", methods=["GET"])
@require_viewer
def metrics_summary():
    """
    Exact counts and token/cost/latency totals across the whole collection,
    from a briefly TTL-cached aggregation query (see
    `orchestrator.global_metrics`) rather than from whatever page of cases a
    client happened to fetch - the KPI tiles are correct at any case volume.
    """
    try:
        return jsonify(_on_worker(orchestrator.global_metrics()))
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/orchestrator/drain", methods=["POST"])
@require_operator
def orchestrator_drain():
    """
    Run pending cases to completion.

    The explicit lever for request-driven mode: usable from a script, from
    Cloud Scheduler, or to clear a backlog without waiting for the dashboard to
    poll it away one case at a time.
    """
    try:
        body = request.get_json(silent=True) or {}
        cases = int(body.get("cases") or request.args.get("cases") or 3)
        return jsonify(_on_worker(orchestrator.drain(max_cases=max(1, min(cases, 10)))))
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/orchestrator/tick", methods=["POST"])
@require_operator
def orchestrator_tick():
    """
    Advance the pipeline one step per in-flight case.

    The background loop already does this continuously; this endpoint exists so
    Cloud Scheduler can drive the pipeline if CPU throttling is ever left on.
    """
    try:
        moved = _on_worker(orchestrator.tick())
        return jsonify({"advanced": moved})
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/events/document", methods=["POST"])
@require_operator
@limiter.limit("10 per minute")
def event_document():
    """
    Shipping document intake.

    Accepts a PDF or scanned image as multipart form-data under `file`. Gemini
    3.5 Flash transcribes it into a shipment record, the original is archived to
    Cloud Storage for audit, and the background worker takes it from there.

    This is the realistic event source: in production a document lands, not a
    tidy JSON payload.
    """
    try:
        upload = request.files.get("file")
        if upload is None or not upload.filename:
            return jsonify({"error": "No file provided under form field 'file'"}), 400

        mime = mime_for(upload.filename)
        if mime is None:
            return jsonify({
                "error": f"Unsupported file type: {upload.filename}",
                "supported": sorted(get_document_agent_info()["supported_types"])
            }), 415

        data = upload.read()
        if not data:
            return jsonify({"error": "Uploaded file is empty"}), 400

        max_mb = int(os.getenv("MAX_DOCUMENT_MB", "20"))
        if len(data) > max_mb * 1024 * 1024:
            return jsonify({"error": f"File exceeds {max_mb}MB limit"}), 413

        result = _on_worker(
            orchestrator.ingest_document(data, upload.filename, mime)
        )

        if result.get("accepted") and orchestrator.WORKER_MODE != "poll":
            from vf_logistics.store import get_store

            case = _on_worker(get_store().get_case(result["case_id"]))
            if case:
                case = _on_worker(orchestrator.advance_until_terminal(case))
                result["state"] = case.get("state")
                result["decision"] = case.get("decision")

        return jsonify(result), (202 if result.get("accepted") else 422)

    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/simulate/bulk", methods=["POST"])
@require_operator
@limiter.limit("5 per minute")
def simulate_bulk():
    """
    Inject a larger randomised batch to show the pipeline under volume.

    Capped deliberately. Every case costs at least one Gemini call and up to
    three, so an uncapped endpoint is a quota and billing hazard rather than a
    better demo.
    """
    try:
        body = request.get_json(silent=True) or {}
        requested = int(body.get("count") or request.args.get("count") or 10)
        cap = int(os.getenv("MAX_BULK_COUNT", "10"))
        count = max(1, min(requested, cap))

        run_tag = datetime.now(timezone.utc).strftime("%H%M%S")
        shipments = simulator.bulk_shipments(count, run_tag)

        for s in shipments:
            _on_worker(orchestrator.ingest_shipment(s, source="bulk-simulator"))

        return jsonify({
            "injected": count,
            "requested": requested,
            "capped_at": cap if requested > cap else None,
            "profile_mix": _profile_mix(shipments),
            "note": (
                "Cases are queued; the background worker drains them at "
                f"{orchestrator.MAX_CONCURRENT} at a time. Poll "
                "/api/v1/orchestrator/state."
            )
        }), 202

    except Exception as e:
        return _safe_error(e)


def _profile_mix(shipments: list) -> dict:
    mix: dict[str, int] = {}
    for s in shipments:
        key = s.get("_generated_profile", "unknown")
        mix[key] = mix.get(key, 0) + 1
    return mix


@app.route("/api/v1/config", methods=["GET"])
@require_viewer
def config():
    """
    The active AI and routing configuration.

    Exposed because an autonomous system that acts on your cargo should be able
    to tell you exactly which model, sampling settings and thresholds produced a
    decision. Read-only on purpose: changing policy is a deploy, not an API call,
    so the configuration behind any past decision stays reconstructable.
    """
    return jsonify({
        "agents": [
            get_document_agent_info(),
            get_fraud_agent_info(),
            get_compliance_agent_info(),
            get_investigation_agent_info()
        ],
        "sampling": {
            "document_intake": {"temperature": 0.0, "note": "transcription, not generation"},
            "fraud_detection": {"temperature": 0.1},
            "compliance": {"temperature": 0.1},
            "investigation": {"temperature": 0.2, "thinking_budget": 8000}
        },
        "routing_thresholds": orchestrator.worker_status()["thresholds"],
        "response_contract": "application/json enforced on every agent call",
        "currency": "USD",
        "store": store_status(),
        "document_archive": document_store.status(),
        "decisions_topic": tools.DECISIONS_TOPIC,
        "notify_webhook_configured": bool(tools.NOTIFY_WEBHOOK_URL),
        "limits": {
            "max_document_mb": int(os.getenv("MAX_DOCUMENT_MB", "20")),
            "max_bulk_count": int(os.getenv("MAX_BULK_COUNT", "10"))
        },
        "demo_mode": os.getenv("DEMO_MODE", "false").lower() in ("1", "true", "yes")
    })


@app.route("/api/v1/config/model", methods=["GET"])
@require_viewer
def get_model_config():
    """Get current model configuration and available models."""
    return jsonify({
        "current_model": model_config.get_model(),
        "pricing": model_config.get_pricing(),
        "available_models": model_config.get_all_models()
    })


@app.route("/api/v1/config/model", methods=["POST"])
@require_operator
def set_model_config():
    """
    Change the active AI model at runtime.
    
    This allows switching between Gemini models without redeployment.
    Changes take effect immediately for new requests.
    """
    data = request.get_json(silent=True) or {}
    new_model = data.get("model", "").strip()
    
    if not new_model:
        return jsonify({"error": "model is required"}), 400
    
    if model_config.set_model(new_model):
        return jsonify({
            "success": True,
            "model": new_model,
            "pricing": model_config.get_pricing()
        })
    
    return jsonify({
        "error": f"Invalid model: {new_model}",
        "available": list(model_config.PRICING.keys())
    }), 400


# ============== GOVERNANCE: DELEGATION BOUNDARIES ==============
#
# An agent here does not earn authority by performing well. A human publishes a
# machine-readable boundary, and the agent operates inside it. With no active
# boundary the system is SUSPENDED: it can analyse and propose, but the
# execution gate refuses every protected action.

@app.route("/api/v1/governance/agent", methods=["GET"])
@require_viewer
def governance_agent():
    """Agent readiness and the boundary currently in force."""
    try:
        return jsonify(_on_worker(governance.agent_readiness()))
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/drift", methods=["GET"])
@require_viewer
def governance_drift():
    """Return drift detection details for the governance banner."""
    try:
        readiness = _on_worker(governance.agent_readiness())
        drift = readiness.get("drift") or {"material": False, "reasons": []}
        return jsonify(drift)
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/boundaries", methods=["GET"])
@require_viewer
def governance_boundaries():
    """Full boundary history, including SUPERSEDED versions."""
    try:
        from vf_logistics.store import get_store

        return jsonify({
            "boundaries": _on_worker(get_store().list_boundaries(20)),
            "proposed_template": governance.proposed_boundary(),
        })
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/publish", methods=["POST"])
@require_governance_admin
def governance_publish():
    """
    Publish a delegation boundary. This is the only way an agent gains authority.

    `author` is mandatory and recorded on the boundary and in the audit log:
    delegated authority that nobody is named as having granted is not delegated
    authority, it is an accident.
    """
    try:
        body = request.get_json(silent=True) or {}
        author = str(body.get("author") or "").strip()
        if not author:
            return jsonify({"error": "author is required to publish a boundary"}), 400

        permissions = body.get("permissions") or governance.proposed_boundary(
            "Published from the default template"
        )
        note = str(body.get("note") or "").strip()

        boundary = _on_worker(governance.publish_boundary(permissions, author, note))
        return jsonify({"published": True, "boundary": boundary}), 201
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/verify-entity", methods=["POST"])
@require_viewer
@limiter.limit("20 per minute")
def verify_entity():
    """
    Use Tavily web search to verify that a company or tax ID actually exists.

    Body: {type: "company"|"tax_id", value: string, country?: string}
    Returns: {verified: bool, confidence: str, results: [{title, url, snippet}], summary: str}
    """
    try:
        from vf_logistics import tavily_client
        import asyncio

        body = request.get_json(silent=True) or {}
        entity_type = str(body.get("type") or "company").strip()
        value = str(body.get("value") or "").strip()
        country = str(body.get("country") or "vietnam").strip()

        if not value:
            return jsonify({"error": "value is required"}), 400

        if entity_type == "tax_id":
            query = f'"{value}" tax ID registration {country} company'
        else:
            query = f'"{value}" company {country} registration OR business OR official'

        results = _on_worker(tavily_client.search(query, max_results=5))

        if not results:
            return jsonify({
                "verified": False,
                "confidence": "none",
                "results": [],
                "summary": f"No web results found for {entity_type} '{value}'. "
                           "This entity may not exist or Tavily search is unavailable.",
            })

        value_lower = value.lower()
        matches = sum(1 for r in results if value_lower in (r.get("content") or "").lower()
                      or value_lower in (r.get("title") or "").lower())

        if matches >= 2:
            confidence = "high"
            verified = True
            summary = f"Found {matches} web sources confirming '{value}' exists."
        elif matches == 1:
            confidence = "medium"
            verified = True
            summary = f"Found 1 web source mentioning '{value}'. Review the result to confirm."
        else:
            confidence = "low"
            verified = False
            summary = f"Found {len(results)} results but none directly mention '{value}'."

        return jsonify({
            "verified": verified,
            "confidence": confidence,
            "results": [
                {"title": r.get("title", ""), "url": r.get("url", ""),
                 "snippet": (r.get("content") or "")[:300]}
                for r in results
            ],
            "summary": summary,
        })
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/tavily-scan", methods=["POST"])
@require_governance_admin
def governance_tavily_scan():
    """Search for recent sanctions or regulatory updates relevant to current watchlists."""
    try:
        from vf_logistics import tavily_client
        import asyncio
        from vf_logistics.store import get_store

        store = get_store()
        body = request.get_json(silent=True) or {}
        custom_queries = body.get("queries", [])

        default_queries = [
            "logistics sanctions updates latest 2026",
            "OFAC SDN list new additions logistics shipping",
            "trade compliance enforcement actions recent",
        ]
        queries = custom_queries[:5] if custom_queries else default_queries

        loop = asyncio.new_event_loop()
        all_results = []
        for q in queries:
            results = loop.run_until_complete(tavily_client.search(q, max_results=3))
            all_results.extend(results)
        loop.close()

        alerts = []
        for r in all_results:
            title = r.get("title", "")
            content = r.get("content", "")[:400]
            url = r.get("url", "")
            alerts.append({"title": title, "snippet": content, "url": url})

        return jsonify({
            "scan_count": len(queries),
            "alerts": alerts,
            "alert_count": len(alerts),
            "summary": f"Scanned {len(queries)} queries, found {len(alerts)} results",
        })
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/prefilter-rules", methods=["GET"])
@require_viewer
def get_prefilter_rules():
    """Return current SQL pre-filter rules (whitelist, blacklist, safe routes, threshold)."""
    try:
        from vf_logistics import verifier
        return jsonify(verifier.get_prefilter_rules())
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/governance/prefilter-rules", methods=["PUT"])
@require_governance_admin
def update_prefilter_rules():
    """
    Update SQL pre-filter rules.
    
    Body: {
        vip_registry: [{company: string, tax_id: string}],
        blacklist_companies: string[],
        blacklist_tax_ids: string[],
        safe_routes: [{origin: string, destination: string}],
        low_value_threshold_usd: number
    }
    """
    try:
        from vf_logistics import verifier
        from vf_logistics.store import get_store, new_id, utcnow
        
        body = request.get_json(silent=True) or {}
        author = str(body.get("author") or "").strip()
        
        if not author:
            return jsonify({"error": "author is required to update rules"}), 400
        
        # Get old rules for audit
        old_rules = verifier.get_prefilter_rules()
        
        # Update rules
        result = verifier.update_prefilter_rules(body)
        
        if not result.get("ok"):
            return jsonify({"error": "Validation failed", "details": result.get("errors")}), 400
        
        # Audit log the change
        _on_worker(get_store().add_audit({
            "audit_id": new_id("audit"),
            "case_id": "-",
            "action": "update_prefilter_rules",
            "status": "done",
            "detail": {
                "author": author,
                "old_rules": old_rules,
                "new_rules": result.get("rules"),
            },
            "at": utcnow(),
        }))
        
        return jsonify(result)
    except Exception as e:
        return _safe_error(e)


# ============== HUMAN REVIEW ==============

@app.route("/api/v1/review/queue", methods=["GET"])
@require_reviewer
def review_queue():
    """Cases the agent could not close on its own. Cursor-paginated."""
    try:
        cursor = request.args.get("cursor")
        limit = min(int(request.args.get("limit", 40)), 200)
        cases, next_cursor = _on_worker(
            orchestrator.review_queue(cursor=cursor, limit=limit)
        )
        return jsonify({"cases": cases, "next_cursor": next_cursor})
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/review/<case_id>/decide", methods=["POST"])
@require_reviewer
def review_decide(case_id: str):
    """Apply a named reviewer's decision: release, block, or request_info."""
    try:
        body = request.get_json(silent=True) or {}
        result = _on_worker(orchestrator.human_decide(
            case_id,
            str(body.get("action") or "").strip(),
            str(body.get("reviewer") or "").strip(),
            str(body.get("note") or "").strip(),
        ))
        return jsonify(result), (200 if result.get("ok") else 400)
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/review/<case_id>/deep-review", methods=["POST"])
@require_reviewer
def review_deep_review(case_id: str):
    """
    Trigger Multi-Agent Debate: Nemotron Super reviews Nano's assessment.

    This is an expensive, opt-in operation. The Senior Auditor (Super 120B)
    can use function calling to:
    - Request Nano to re-evaluate with specific focus
    - Run additional Tavily searches
    - Render a CONFIRM or DISAGREE verdict
    """
    try:
        result = _on_worker(orchestrator.deep_review(case_id))
        return jsonify(result), (200 if result.get("ok") else 400)
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/review/<case_id>/document", methods=["GET"])
@require_reviewer
def review_document(case_id: str):
    """
    Stream the archived source document so a reviewer sees the paperwork itself,
    not only a transcription of it.

    Proxied rather than served via a signed URL: signing requires
    iam.serviceAccounts.signBlob on the runtime service account, and streaming
    needs no additional IAM at all.
    """
    try:
        from flask import Response

        from vf_logistics.store import get_store

        case = _on_worker(get_store().get_case(case_id))
        if not case:
            return jsonify({"error": "case not found"}), 404

        provenance = case.get("provenance") or {}
        uri = provenance.get("uri")
        if not uri:
            return jsonify({
                "error": "no archived document for this case",
                "reason": provenance.get("reason", "case did not originate from a document")
            }), 404

        data, content_type = _on_worker(document_store.fetch(uri))
        if data is None:
            return jsonify({"error": f"could not read {uri}"}), 502

        return Response(
            data,
            mimetype=content_type or "application/pdf",
            headers={
                "Content-Disposition":
                    'inline; filename="{}"'.format(
                        re.sub(r'[^\w\s\-.]', '_', provenance.get("filename", "document.pdf"))[:100]
                    )
            },
        )
    except Exception as e:
        return _safe_error(e)


# ============== EXECUTOR IDENTITY ==============
#
# Served by the second Cloud Run service, which runs under a service account
# holding `pubsub.publisher` that the analysis service does not have. The
# analysis service reaches this endpoint with a Google-issued OIDC token, and the
# executor service is deployed with --no-allow-unauthenticated, so nothing
# without `run.invoker` on it can call in.
#
# The separation is enforced by IAM, not by this file. If the analysis runtime
# were subverted and tried to publish directly, Google refuses it.

@app.route("/internal/execute", methods=["POST"])
def internal_execute():
    """Perform a protected action on behalf of the analysis runtime."""
    try:
        body = request.get_json(silent=True) or {}
        action = str(body.get("action") or "")
        case_id = str(body.get("case_id") or "")
        payload = body.get("payload") or {}

        # Only egress actions are delegated here. Everything else stays in the
        # analysis service, where it is only a Firestore write.
        if action != "publish_decision":
            return jsonify({
                "error": f"executor does not perform '{action}'",
                "delegated_actions": ["publish_decision"]
            }), 400

        receipt = _on_worker(tools.publish_decision_direct(case_id, payload))
        return jsonify({
            "executed": receipt.get("status") == "done",
            "status": receipt.get("status"),
            "message_id": (receipt.get("detail") or {}).get("message_id"),
            "error": (receipt.get("detail") or {}).get("error"),
            "executed_by": "executor identity"
        })
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/events/storage", methods=["POST"])
def event_storage():
    """
    Cloud Storage object-finalize sink.

    Drop a PDF into the bucket and it is processed with nobody clicking anything.
    This is the equivalent of a stage with change tracking on it: the bucket
    notification publishes to Pub/Sub, Pub/Sub pushes here, and the same document
    pipeline runs.

    Eventarc would be the more direct route but is not enabled on this project;
    bucket notifications need only the storage and pubsub APIs, which are.
    """
    try:
        body = request.get_json(silent=True) or {}

        message = body.get("message") or {}
        attrs = message.get("attributes") or {}
        payload: dict = {}
        if message.get("data"):
            try:
                payload = json.loads(base64.b64decode(message["data"]).decode("utf-8"))
            except Exception:
                payload = {}

        bucket = payload.get("bucket") or attrs.get("bucketId")
        name = payload.get("name") or attrs.get("objectId")

        if not bucket or not name:
            # Ack rather than 400: an un-parseable notification retried forever
            # is worse than one dropped with a reason recorded.
            return jsonify({"ignored": True, "reason": "no bucket/object in notification"}), 200

        # The service archives every intake into this prefix. Processing our own
        # output would loop forever.
        if name.startswith(orchestrator.ARCHIVE_PREFIX):
            return jsonify({"ignored": True, "reason": "own archive output"}), 200

        if mime_for(name) is None:
            return jsonify({"ignored": True, "reason": f"unsupported type: {name}"}), 200

        result = _on_worker(orchestrator.ingest_from_storage(bucket, name))

        if result.get("accepted") and not result.get("blocked") \
                and orchestrator.WORKER_MODE != "poll":
            from vf_logistics.store import get_store

            case = _on_worker(get_store().get_case(result["case_id"]))
            if case:
                case = _on_worker(orchestrator.advance_until_terminal(case))
                result["state"] = case.get("state")

        return jsonify(result), 200

    except Exception as e:
        # Always 200 to Pub/Sub: a 500 triggers redelivery, and a document that
        # crashes the handler will crash it again. The error is recorded instead.
        return jsonify({"error": str(e), "acked": True}), 200


@app.route("/api/v1/ingest/bucket-sweep", methods=["POST"])
@require_operator
def bucket_sweep():
    """
    Process documents already sitting in the bucket.

    The batch equivalent of reading a stage. Idempotent: ingestion is keyed on
    shipment id, and objects already tied to a case are skipped, so sweeping
    twice does not double-process.
    """
    try:
        body = request.get_json(silent=True) or {}
        prefix = str(body.get("prefix") or request.args.get("prefix") or "inbox/")
        limit = int(body.get("limit") or request.args.get("limit") or 10)
        return jsonify(_on_worker(
            orchestrator.sweep_bucket(prefix, max(1, min(limit, 25)))
        ))
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/orchestrator/reset", methods=["POST"])
@require_operator
def orchestrator_reset():
    """Clear all cases, events and audit records so a demo starts clean."""
    try:
        from vf_logistics.store import get_store

        removed = _on_worker(get_store().reset())
        return jsonify({"cleared": removed})
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/admin/backfill-rollups", methods=["POST"])
@require_operator
def admin_backfill_rollups():
    """
    One-off migration: compute token/latency/cost rollup fields on cases
    written before those fields existed, so the metrics summary's exact
    global totals include full history instead of reading 0 for anything
    older than this feature. Safe to call more than once - already-rolled
    up cases are skipped.
    """
    try:
        from vf_logistics.store import get_store

        result = _on_worker(get_store().backfill_rollups())
        return jsonify(result)
    except Exception as e:
        return _safe_error(e)


@app.route("/api/v1/orchestrator/case/<case_id>", methods=["GET"])
@require_viewer
def orchestrator_case(case_id: str):
    """Single case with its full agent hop history and action receipts."""
    try:
        from vf_logistics.store import get_store

        case = _on_worker(get_store().get_case(case_id))
        if not case:
            return jsonify({"error": "case not found"}), 404
        return jsonify(case)
    except Exception as e:
        return _safe_error(e)


# ============== DEMO ENDPOINT ==============

@app.route("/demo", methods=["GET"])
@async_route
async def demo():
    """Demo endpoint with sample shipment analysis."""
    sample_shipment = {
        "shipment_id": "VF-2026-DEMO-001",
        "origin": "Ho Chi Minh City",
        "destination": "Hanoi",
        "weight_kg": 150,
        "declared_value": 2_000,     # USD
        "shipping_cost": 100,        # USD
        "shipper_name": "Demo Company Ltd",
        "receiver_name": "Sample Receiver Corp",
        "created_at": utcnow(),
        "status": "pending",
        "route_details": "HCMC → Da Nang → Hanoi",
        "avg_route_cost": 120,       # USD route average
        "shipper_tx_count": 5
    }
    
    result = await analyze_shipment(sample_shipment)
    
    return jsonify({
        "demo": True,
        "sample_shipment": sample_shipment,
        "analysis": result
    })


if __name__ == "__main__":
    _ensure_worker()
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
else:
    # Under gunicorn: start the background worker as the module is imported.
    _ensure_worker()
