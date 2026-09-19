"""
Pydantic v2 schemas for API request/response validation.

All API endpoints should use these schemas for:
1. Input validation (reject malformed requests early)
2. Output serialization (consistent response shapes)
3. OpenAPI documentation generation

The schemas mirror the Firestore document structures but add:
- Type enforcement
- Required field validation
- Value constraints (min/max, regex patterns, enums)
- Sensitive field handling (exclude from logs)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


# =============================================================================
# Enums
# =============================================================================

class CaseState(str, Enum):
    """Valid case states in the workflow."""
    INTAKE = "INTAKE"
    PENDING_ANALYSIS = "PENDING_ANALYSIS"
    ANALYSIS_COMPLETE = "ANALYSIS_COMPLETE"
    HELD_FOR_REVIEW = "HELD_FOR_REVIEW"
    PENDING_HUMAN = "PENDING_HUMAN"
    AUTO_CLEARED = "AUTO_CLEARED"
    ESCALATED = "ESCALATED"
    DEAD_LETTER = "DEAD_LETTER"
    RELEASED = "RELEASED"
    BLOCKED = "BLOCKED"


class ReviewAction(str, Enum):
    """Valid review actions a human can take."""
    RELEASE = "release"
    BLOCK = "block"
    REQUEST_INFO = "request_info"


# =============================================================================
# Shipment schemas
# =============================================================================

class ShipmentBase(BaseModel):
    """Base shipment fields."""
    model_config = ConfigDict(str_strip_whitespace=True)

    shipment_id: str = Field(..., min_length=1, max_length=100)
    origin: str = Field(..., min_length=1, max_length=200)
    destination: str = Field(..., min_length=1, max_length=200)
    weight_kg: float = Field(..., ge=0, le=1_000_000)
    declared_value: float = Field(..., ge=0)
    shipping_cost: float = Field(..., ge=0)
    currency: str = Field(..., min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    shipper_name: str = Field(..., max_length=200)
    shipper_company: str = Field(..., max_length=200)
    shipper_country: str = Field(..., max_length=100)
    shipper_tax_id: str = Field(..., max_length=50)

    receiver_name: str = Field(..., max_length=200)
    receiver_company: str = Field(..., max_length=200)
    receiver_country: str = Field(..., max_length=100)

    cargo_description: str = Field(..., max_length=1000)
    hs_code: str = Field(..., max_length=20)
    route_details: str = Field(..., max_length=500)
    transit_points: str | None = Field(None, max_length=500)

    status: str = Field(default="pending", max_length=50)
    extraction_notes: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ShipmentCreate(ShipmentBase):
    """Schema for creating a new shipment via API."""
    pass


class ShipmentResponse(ShipmentBase):
    """Schema for shipment in API responses."""
    created_at: datetime | None = None


# =============================================================================
# Case schemas
# =============================================================================

class ReconciliationInfo(BaseModel):
    """Risk reconciliation between model and deterministic floor."""
    model_risk: float = Field(..., ge=0, le=100)
    risk_floor: float = Field(..., ge=0, le=100)
    effective: float = Field(..., ge=0, le=100)
    floor_applied: bool = False
    disputed: bool = False
    dispute_delta: float | None = None


class GateDenial(BaseModel):
    """Record of a governance gate denial."""
    gate: str
    reason: str
    timestamp: datetime


class ReviewEntry(BaseModel):
    """Record of a human review action."""
    action: ReviewAction
    reviewer: str
    at: datetime
    note: str | None = None
    state_before: str
    state_after: str


class CaseResponse(BaseModel):
    """Schema for case in API responses."""
    case_id: str
    state: CaseState
    shipment: ShipmentResponse | None = None
    risk_score: float | None = Field(None, ge=0, le=100)
    recommendation: str | None = None
    reconciliation: ReconciliationInfo | None = None
    gate_denials: list[GateDenial] = Field(default_factory=list)
    proposed_outcome: str | None = None
    reviews: list[ReviewEntry] = Field(default_factory=list)
    version: int = 1
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CaseListResponse(BaseModel):
    """Schema for listing multiple cases."""
    cases: list[CaseResponse]
    total: int
    has_more: bool = False


# =============================================================================
# Review queue schemas
# =============================================================================

class ReviewQueueItem(BaseModel):
    """A case in the review queue."""
    case_id: str
    state: CaseState
    risk_score: float | None = None
    shipment_id: str | None = None
    shipper_company: str | None = None
    receiver_company: str | None = None
    declared_value: float | None = None
    currency: str | None = None
    waiting_since: datetime | None = None


class ReviewQueueResponse(BaseModel):
    """Schema for review queue API response."""
    cases: list[ReviewQueueItem]
    total: int


class ReviewDecisionRequest(BaseModel):
    """Schema for submitting a review decision."""
    action: ReviewAction
    note: str | None = Field(None, max_length=1000)

    @field_validator("note")
    @classmethod
    def sanitize_note(cls, v: str | None) -> str | None:
        if v is None:
            return v
        # Basic XSS prevention
        return v.replace("<", "&lt;").replace(">", "&gt;")


class ReviewDecisionResponse(BaseModel):
    """Schema for review decision API response."""
    success: bool
    case_id: str
    new_state: CaseState
    message: str | None = None


# =============================================================================
# Simulation schemas
# =============================================================================

class SimulationRequest(BaseModel):
    """Schema for triggering a simulation."""
    shipment: ShipmentCreate | None = None
    scenario: str | None = Field(None, max_length=100)


class SimulationResponse(BaseModel):
    """Schema for simulation API response."""
    case_id: str
    state: CaseState
    message: str


# =============================================================================
# Health/status schemas
# =============================================================================

class HealthResponse(BaseModel):
    """Schema for health check response."""
    status: str
    version: str | None = None
    timestamp: datetime


class AgentInfo(BaseModel):
    """Schema for agent info in /agents endpoint."""
    name: str
    model: str
    capabilities: list[str]


class AgentsResponse(BaseModel):
    """Schema for /agents endpoint response."""
    agents: list[AgentInfo]


# =============================================================================
# Error schemas
# =============================================================================

class ErrorResponse(BaseModel):
    """Standard error response schema."""
    error: str
    detail: str | None = None
    code: str | None = None


class ValidationErrorDetail(BaseModel):
    """Detail for a single validation error."""
    field: str
    message: str
    value: Any | None = None


class ValidationErrorResponse(BaseModel):
    """Schema for validation error responses (422)."""
    error: str = "Validation error"
    details: list[ValidationErrorDetail]
