"""
OpenAPI 3.1 spec for the B2B integration surface.

Generated from the Pydantic models rather than written by hand, because a
hand-written spec drifts. The drift is not hypothetical in this codebase:
schemas.ReconciliationInfo declared `effective`, `disputed` and `dispute_delta`
while verifier.reconcile() returned `effective_risk`, `score_disputed` and
`auto_clear_permitted`. Nothing imported the model, so nothing caught it. A spec
derived from the models cannot develop that gap -- if the model changes, the
published contract changes with it.

Scope: the B2B endpoints only. The forty-odd routes behind the dashboard are
internal, change with the UI, and would be a liability to publish as a contract a
customer could hold us to.
"""

from __future__ import annotations

import os
from typing import Any

from vf_logistics.schemas import (
    ComplianceAuditAccepted,
    ComplianceAuditRequest,
    ComplianceAuditResponse,
    ComplianceReportsResponse,
    ErrorResponse,
    TenantUsageResponse,
    ValidationErrorResponse,
)

API_VERSION = "1.0.0"

# Every model that appears in a request or response body. Collected in one list
# so a model added to a route but forgotten here shows up as a broken $ref in the
# spec rather than as a silently missing definition.
_MODELS = (
    ComplianceAuditRequest,
    ComplianceAuditResponse,
    ComplianceAuditAccepted,
    ComplianceReportsResponse,
    TenantUsageResponse,
    ErrorResponse,
    ValidationErrorResponse,
)

_REF_TEMPLATE = "#/components/schemas/{model}"


def _components() -> dict[str, Any]:
    """
    Collect every model's JSON Schema under components/schemas.

    Pydantic emits nested models into a local `$defs` block. Those have to be
    hoisted to the top level, because `ref_template` already points every `$ref`
    at #/components/schemas/... -- leaving them in $defs would produce a spec
    whose references resolve to nothing.
    """
    schemas: dict[str, Any] = {}
    for model in _MODELS:
        schema = model.model_json_schema(ref_template=_REF_TEMPLATE)
        for name, defn in schema.pop("$defs", {}).items():
            schemas[name] = defn
        schemas[model.__name__] = schema
    return schemas


def _ref(model: type) -> dict[str, str]:
    return {"$ref": _REF_TEMPLATE.format(model=model.__name__)}


def _json(model: type) -> dict[str, Any]:
    return {"content": {"application/json": {"schema": _ref(model)}}}


def build_spec(server_url: str | None = None) -> dict[str, Any]:
    """The full spec. `server_url` lets a caller publish its own deployed host."""
    url = server_url or os.getenv("PUBLIC_BASE_URL", "/")

    error = {**_json(ErrorResponse), "description": "Error"}

    return {
        "openapi": "3.1.0",
        "info": {
            "title": "VF Logistics Trade Compliance API",
            "version": API_VERSION,
            "summary": "Automated trade-compliance auditing for ERP and TMS systems.",
            "description": (
                "Submit a shipment, receive a compliance verdict with the evidence "
                "behind it.\n\n"
                "### How a verdict is reached\n\n"
                "Two layers decide, and the split matters when you read a result. "
                "Deterministic checks -- arithmetic on freight ratios and value "
                "density, plus lookups against sanctions and dual-use lists -- set a "
                "**risk floor**. A language model then assesses the shipment for "
                "patterns the checks cannot express, such as a cargo description "
                "written to disguise a controlled tariff heading.\n\n"
                "The model can raise risk above the floor. It can never lower it. "
                "`risk_floor` and `model_risk` are both returned so you can see which "
                "layer drove the outcome.\n\n"
                "### When a model reply is unusable\n\n"
                "If a model times out or returns a response that fails its schema "
                "after retries, the audit does not fail and does not guess. The "
                "shipment is routed to human review with `requires_human_review` set "
                "and `review_reason` naming which agent failed. You will never "
                "receive `CLEARED` on the strength of a check that did not run.\n\n"
                "### Retries and idempotency\n\n"
                "Send `client_reference` on every submission. If your request times "
                "out and you retry, the original audit is returned with "
                "`idempotent_replay: true` and no tokens are spent twice.\n\n"
                "### Sanctions data freshness\n\n"
                "`lineage.sanctions_list_age_days` reports how old the screened list "
                "is. The list refreshes weekly, so this can legitimately read up to "
                "7. Treat it as part of the result, not as a footnote."
            ),
            "contact": {"name": "VF Logistics Compliance Engineering"},
        },
        "servers": [{"url": url}],
        "tags": [
            {"name": "compliance", "description": "Submit shipments and read verdicts"},
            # Declared because a path below tags an operation `billing`. An
            # undeclared tag is legal OpenAPI but renders as a bare string with no
            # description in Swagger UI, and validators flag it.
            {"name": "billing", "description": "Metered usage and spend for a period"},
        ],
        "paths": {
            "/api/v1/compliance/audit": {
                "post": {
                    "tags": ["compliance"],
                    "operationId": "createComplianceAudit",
                    "summary": "Audit a shipment",
                    "description": (
                        "Runs the full pipeline and returns a verdict.\n\n"
                        "Only `shipment_id` is required. Every other field is "
                        "optional, and this is deliberate rather than lax: a "
                        "shipment missing its cargo description or HS code is "
                        "precisely what the system exists to flag, and rejecting it "
                        "at the door would turn a detection into a silence. Send what "
                        "your system holds; absences become findings.\n\n"
                        "Pass `?async=true` for volume. The call then returns 202 "
                        "immediately and the verdict is POSTed to `webhook_url`."
                    ),
                    "parameters": [
                        {
                            "name": "async",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "boolean", "default": False},
                            "description": "Return 202 and deliver the verdict by webhook.",
                        },
                    ],
                    "requestBody": {"required": True, **_json(ComplianceAuditRequest)},
                    "responses": {
                        "200": {
                            "description": "Audit complete",
                            **_json(ComplianceAuditResponse),
                        },
                        "202": {
                            "description": "Accepted; verdict follows by webhook",
                            **_json(ComplianceAuditAccepted),
                        },
                        "400": error,
                        "403": {**error, "description": "Caller lacks the operator role"},
                        "422": {
                            "description": "Request failed validation",
                            **_json(ValidationErrorResponse),
                        },
                        "429": {**error, "description": "Rate limited"},
                        "500": error,
                    },
                },
            },
            "/api/v1/compliance/audit/{audit_id}": {
                "get": {
                    "tags": ["compliance"],
                    "operationId": "getComplianceAudit",
                    "summary": "Fetch one audit",
                    "description": "Poll this after an async submission.",
                    "parameters": [{
                        "name": "audit_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }],
                    "responses": {
                        "200": {
                            "description": "The audit",
                            **_json(ComplianceAuditResponse),
                        },
                        "404": {**error, "description": "No such audit"},
                        "500": error,
                    },
                },
            },
            "/api/v1/compliance/reports": {
                "get": {
                    "tags": ["compliance"],
                    "operationId": "listComplianceAudits",
                    "summary": "List completed audits",
                    "description": (
                        "Cursor paginated. Pass the `next_cursor` from the previous "
                        "page rather than an offset -- audits land continuously, and "
                        "an offset silently skips or repeats rows when new ones "
                        "arrive between your pages."
                    ),
                    "parameters": [
                        {
                            "name": "cursor",
                            "in": "query",
                            "schema": {"type": "string"},
                            "description": "next_cursor from the previous page.",
                        },
                        {
                            "name": "limit",
                            "in": "query",
                            "schema": {
                                "type": "integer", "default": 50,
                                "minimum": 1, "maximum": 200,
                            },
                        },
                        {
                            "name": "outcome",
                            "in": "query",
                            "schema": {
                                "type": "string",
                                "enum": ["CLEARED", "HELD_FOR_REVIEW", "BLOCKED",
                                         "PENDING_HUMAN", "ERROR"],
                            },
                        },
                        {
                            "name": "min_risk",
                            "in": "query",
                            "schema": {
                                "type": "number", "minimum": 0, "maximum": 100,
                            },
                            "description": "Only audits at or above this effective risk.",
                        },
                    ],
                    "responses": {
                        "200": {
                            "description": "A page of audits",
                            **_json(ComplianceReportsResponse),
                        },
                        "400": error,
                        "500": error,
                    },
                },
            },
            "/api/v1/billing/usage": {
                "get": {
                    "tags": ["billing"],
                    "operationId": "getTenantUsage",
                    "summary": "Billable usage for the calling tenant",
                    "description": (
                        "The tenant is taken from the authenticated identity, not "
                        "from a parameter, so one customer cannot read another's "
                        "usage by changing a query string.\n\n"
                        "`cleared_by_rules` against `cleared_by_ai` is the number "
                        "worth watching. A shipment the deterministic checks settle "
                        "consumes no model tokens at all, so the ratio is what "
                        "decides the marginal cost of serving an account -- traffic "
                        "the rules resolve is nearly free, traffic that reaches the "
                        "models is not."
                    ),
                    "responses": {
                        "200": {
                            "description": "Usage totals for the calling tenant",
                            **_json(TenantUsageResponse),
                        },
                        "403": error,
                        "500": error,
                    },
                },
            },
        },
        "components": {
            "schemas": _components(),
            "securitySchemes": {
                # Identity is asserted by Google IAP in front of the service, not by
                # a key this app issues. Documented as the header IAP sets so an
                # integrator's client generator produces something accurate.
                "iapAssertion": {
                    "type": "apiKey",
                    "in": "header",
                    "name": "X-Goog-IAP-JWT-Assertion",
                    "description": (
                        "Set by Google Identity-Aware Proxy. Integrators authenticate "
                        "to IAP with a service account; this header is not something "
                        "you construct yourself."
                    ),
                },
            },
        },
        "security": [{"iapAssertion": []}],
    }
