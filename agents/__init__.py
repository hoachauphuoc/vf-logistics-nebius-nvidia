"""Agents package for VF Logistics Fraud Detection System."""

from .fraud_detection_agent import (
    analyze_shipment,
    batch_analyze,
    get_agent_info as get_fraud_agent_info
)

from .compliance_agent import (
    screen_shipment,
    screen_entity,
    get_agent_info as get_compliance_agent_info
)

from .investigation_agent import (
    investigate_case,
    generate_report,
    get_agent_info as get_investigation_agent_info
)

from .document_agent import (
    extract_shipment,
    mime_for,
    get_agent_info as get_document_agent_info
)

__all__ = [
    "analyze_shipment",
    "batch_analyze",
    "get_fraud_agent_info",
    "screen_shipment",
    "screen_entity",
    "get_compliance_agent_info",
    "investigate_case",
    "generate_report",
    "get_investigation_agent_info",
    "extract_shipment",
    "mime_for",
    "get_document_agent_info",
]
