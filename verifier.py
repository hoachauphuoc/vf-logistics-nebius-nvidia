"""
Deterministic grounding validation.

No model calls, no network, no I/O. Every function here is arithmetic or a list
lookup, and that is the entire point.

Two problems this solves:

1. **An agent can overstate or understate.** The pipeline holds and releases real
   cargo based on `risk_score`. If the fraud agent returns 5 for a grossly
   underpriced shipment from a shell company, nothing in a purely
   model-driven design disagrees with it. `shipping_cost / avg_route_cost` is a
   division; it does not need a language model's opinion.

2. **Documents are untrusted input.** A bill of lading can carry injected text
   aimed at the extractor or the downstream agents. The floor computed here is
   derived from numbers and code-resident lists, so a successful injection still
   cannot talk its way past it. This is the last line of defence, and the only
   one that does not depend on a model behaving.

The governing rule is asymmetric:

    An agent may RAISE risk. It may never LOWER risk below the
    deterministic floor.

Escalating on model judgement is acceptable. Exonerating on model judgement is
not, because the cost of a wrong exoneration is released contraband and the cost
of a wrong escalation is a human spending ten minutes on a clean shipment.
"""

from __future__ import annotations

import re
from typing import Any

# --------------------------------------------------------------------------
# Code-resident reference data
#
# These belong in code, not in model recall. A model asked "is 8504.40 dual-use"
# will usually be right and occasionally confabulate, and there is no way to tell
# which happened from the output.
# --------------------------------------------------------------------------

# Indicative freight baselines in USD by lane, used when the source record has
# no avg_route_cost. Bills of lading never carry a market average, so a
# document-sourced shipment would otherwise skip the pricing check entirely.
LANE_BASELINES_USD: dict[tuple[str, str], float] = {
    ("vietnam", "singapore"): 1_200,
    ("vietnam", "south korea"): 1_680,
    ("vietnam", "taiwan"): 1_450,
    ("vietnam", "usa"): 3_400,
    ("vietnam", "united states"): 3_400,
    ("vietnam", "netherlands"): 4_100,
    ("vietnam", "pakistan"): 2_720,
    ("vietnam", "china"): 1_100,
    ("vietnam", "japan"): 1_900,
    ("vietnam", "malaysia"): 900,
    ("vietnam", "uae"): 2_900,
    ("vietnam", "india"): 2_300,
}

DEFAULT_LANE_BASELINE_USD = 1_800.0

# --------------------------------------------------------------------------
# SQL Pre-processing Rules: Whitelist / Blacklist / Low-value auto-clear
#
# These rules run BEFORE any AI agent is called to optimize cost:
# - Whitelist: VIP customers auto-cleared instantly (risk_floor = 0)
# - Blacklist: Known bad actors auto-rejected (risk_floor = 100)
# - Low-value: Small domestic shipments auto-cleared (risk_floor = 0)
#
# This "Cost-Aware Hybrid Architecture" handles ~70% of volume with zero
# token cost, reserving AI for the 30% "grey area" that needs reasoning.
# --------------------------------------------------------------------------

# VIP customers with excellent history - auto-clear without AI.
#
# Both `shipper_company` and `shipper_tax_id` are self-reported fields on an
# untrusted shipment record - neither is authenticated. A company name is
# public knowledge, so matching on it alone (or on either field independently,
# as this used to do) means anyone who can type a known name gets the same
# treatment as the real VIP. shipper_registry.py already established the
# right doctrine for exactly this problem: identity is matched on tax ID
# *and* company name together, and a claim that gets one right but not the
# other is treated as worse than a claim that matches neither - it means the
# name or number was deliberately reused, not merely absent.
#
# Entries with a tax_id on file are the "verified" tier: a shipment naming
# that company must also state that exact tax_id, or the mismatch itself
# becomes a CRITICAL finding (WHITELIST_IDENTITY_MISMATCH) rather than a
# silent pass-through. Entries with no tax_id on file yet ("" below) are the
# weaker "name-only" tier - matching still happens, but check_whitelist()
# cannot detect impersonation on an identifier it doesn't have, and validate()
# still runs the full deterministic battery (freight ratio, value density,
# dual-use HS, high-risk destination, mandatory fields) before this tier is
# allowed to skip AI, precisely because the identity claim alone is weak.
VIP_REGISTRY: list[dict[str, str]] = [
    {"company": "vf logistics", "tax_id": ""},
    {"company": "vinamilk joint stock company", "tax_id": "0100107518"},
    {"company": "fpt corporation", "tax_id": "0101245486"},
    {"company": "vietjet air", "tax_id": "0102120939"},
    {"company": "masan group corporation", "tax_id": "0303728041"},
    {"company": "the gioi di dong", "tax_id": "0101384485"},
    {"company": "hoa phat group", "tax_id": ""},
    {"company": "petrovietnam", "tax_id": ""},
    {"company": "viettel group", "tax_id": ""},
    {"company": "vingroup", "tax_id": ""},
    {"company": "samsung vietnam", "tax_id": "0101256055"},
    {"company": "intel vietnam", "tax_id": ""},
    {"company": "nike vietnam", "tax_id": ""},
    {"company": "adidas vietnam", "tax_id": ""},
]

# Known bad actors - auto-reject without AI
BLACKLIST_COMPANIES: set[str] = {
    "shell trading ltd",
    "global import export llc",
    "phoenix logistics inc",
    "dragon shipping co",
    "golden star trading",
    "abc freight forwarders",
    "quick ship solutions",
    "infinite logistics group",
}

BLACKLIST_TAX_IDS: set[str] = {
    "9999999999",  # Known fraudulent
    "0000000001",  # Invalid placeholder
    "1234567890",  # Test/fake ID often used in fraud
}

# Safe domestic routes for low-value auto-clear
DOMESTIC_SAFE_ROUTES: set[tuple[str, str]] = {
    ("ho chi minh city", "hanoi"),
    ("hanoi", "ho chi minh city"),
    ("ho chi minh city", "da nang"),
    ("da nang", "ho chi minh city"),
    ("hanoi", "da nang"),
    ("da nang", "hanoi"),
    ("ho chi minh city", "can tho"),
    ("hanoi", "hai phong"),
    ("ho chi minh city", "binh duong"),
    ("ho chi minh city", "dong nai"),
}

# Low-value threshold for auto-clear (USD)
LOW_VALUE_THRESHOLD_USD = 100.0


def _normalize(text: Any) -> str:
    """Normalize text for matching: lowercase, strip, remove extra spaces."""
    return " ".join(str(text or "").lower().strip().split())


# HS prefixes with dual-use or export-control sensitivity relevant to this
# corridor. Not exhaustive, and deliberately conservative: a false positive
# costs a human review, a false negative costs an export-control violation.
DUAL_USE_HS_PREFIXES = {
    "8504": "Electrical transformers, static converters and inductors",
    "9026": "Instruments for measuring flow, level, pressure",
    "8458": "Numerically controlled lathes",
    "8471": "Automatic data processing machines",
    "8542": "Electronic integrated circuits",
    "9014": "Navigational instruments",
    "9030": "Oscilloscopes, spectrum analysers",
    "8479": "Machines with individual functions, incl. isotope separation",
    "2844": "Radioactive chemical elements",
    "8411": "Turbojets, turbopropellers, gas turbines",
}

# Destinations attracting enhanced due diligence on this corridor.
HIGH_RISK_DESTINATIONS = {
    "pakistan", "iran", "north korea", "syria", "belarus", "russia",
    "myanmar", "afghanistan", "sudan", "venezuela", "cuba",
}

# Transhipment hubs commonly used to obscure final destination.
DIVERSION_HUBS = {
    "jebel ali", "dubai", "uae", "port klang", "hong kong",
    "singapore", "kaohsiung", "busan",
}

MISSING_MARKERS = {"", "not stated", "n/a", "na", "none", "not provided", "unknown", "-"}


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    return str(value).strip().lower() in MISSING_MARKERS


def _num(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # reject NaN


def _country(text: Any) -> str:
    return str(text or "").strip().lower().split(",")[-1].strip()


def lane_baseline(shipment: dict[str, Any]) -> tuple[float, str]:
    """
    Return a freight baseline and where it came from.

    `avg_route_cost` is excluded from the document schema in untrusted.py for the
    same reason as transaction history: a document able to state its own route
    average could set it low and make any freight figure look normal. When it is
    absent the code-resident lane table is used, which is precisely what that
    table exists for.
    """
    stated = _num(shipment.get("avg_route_cost"))
    if stated and stated > 0:
        return stated, "avg_route_cost on the record"

    origin = _country(shipment.get("origin"))
    dest = _country(shipment.get("destination"))
    key = (origin, dest)
    if key in LANE_BASELINES_USD:
        return LANE_BASELINES_USD[key], f"lane table {origin} to {dest}"

    for (o, d), baseline in LANE_BASELINES_USD.items():
        if d == dest:
            return baseline, f"lane table any origin to {d}"

    return DEFAULT_LANE_BASELINE_USD, "corridor default"


# --------------------------------------------------------------------------
# Individual checks
#
# Each returns a finding dict or None. `floor` is the minimum risk score this
# single fact justifies on its own.
# --------------------------------------------------------------------------

def check_whitelist(shipment: dict[str, Any]) -> dict[str, Any] | None:
    """
    Resolve a claimed shipper identity against the VIP registry.

    Returns one of three outcomes:
    - None: neither the company nor the tax_id matches any VIP entry.
    - WHITELIST_MATCH (severity CLEAR, skip_ai): the company matches, and
      either there is no tax_id on file to check (name-only tier) or the
      stated tax_id agrees with the one on file (verified tier).
    - WHITELIST_IDENTITY_MISMATCH (severity CRITICAL, skip_ai,
      auto_reject_by_rules): the company and tax_id each resolve to a VIP
      entry, but not to *each other*. This is not treated as "unknown" -
      per shipper_registry.py's doctrine, a half-right identity claim means
      the name or number was deliberately reused, which is worse than a
      claim that matches nothing.
    """
    company = _normalize(shipment.get("shipper_company"))
    tax_id = str(shipment.get("shipper_tax_id") or "").strip()

    by_company = {e["company"]: e["tax_id"] for e in VIP_REGISTRY}
    by_taxid = {e["tax_id"]: e["company"] for e in VIP_REGISTRY if e["tax_id"]}

    company_taxid = by_company.get(company) if company in by_company else None
    taxid_company = by_taxid.get(tax_id) if tax_id in by_taxid else None

    if company_taxid is None and taxid_company is None:
        return None

    mismatch_reason = None
    if company_taxid and tax_id and tax_id != company_taxid:
        mismatch_reason = (
            f"Shipper company '{company}' is a VIP account on record with tax ID "
            f"'{company_taxid}', but this shipment states tax ID '{tax_id}'."
        )
    elif taxid_company and company and company != taxid_company:
        mismatch_reason = (
            f"Tax ID '{tax_id}' is on file for VIP account '{taxid_company}', but "
            f"this shipment names the shipper as '{company}'."
        )

    if mismatch_reason:
        return {
            "code": "WHITELIST_IDENTITY_MISMATCH",
            "severity": "CRITICAL",
            "floor": 95,
            "detail": mismatch_reason,
            "auto_reject_by_rules": True,
            "skip_ai": True,
        }

    verified = bool(company_taxid) and tax_id == company_taxid
    matched_on = company or tax_id
    return {
        "code": "WHITELIST_MATCH",
        "severity": "CLEAR",
        "floor": 0,
        "detail": (
            f"Shipper '{matched_on}' is on the VIP whitelist "
            + ("(verified: company and tax ID agree)." if verified
               else "(name-only match; no tax ID on file to corroborate).")
        ),
        "auto_clear_by_rules": True,
        "skip_ai": True,
        "identity_verified": verified,
    }


def check_blacklist(shipment: dict[str, Any]) -> dict[str, Any] | None:
    """
    Check if shipper is on the internal blacklist.
    
    Returns a "BLACKLIST_MATCH" finding with floor=100, blocking immediately.
    """
    company = _normalize(shipment.get("shipper_company"))
    tax_id = str(shipment.get("shipper_tax_id") or "").strip()
    
    if company in BLACKLIST_COMPANIES:
        return {
            "code": "BLACKLIST_MATCH",
            "severity": "CRITICAL",
            "floor": 100,
            "detail": f"Shipper company '{company}' is on the internal blacklist. Auto-rejected by rules.",
            "auto_reject_by_rules": True,
            "skip_ai": True,
        }
    
    if tax_id in BLACKLIST_TAX_IDS:
        return {
            "code": "BLACKLIST_TAX_ID",
            "severity": "CRITICAL",
            "floor": 100,
            "detail": f"Shipper tax ID '{tax_id}' is on the internal blacklist. Auto-rejected by rules.",
            "auto_reject_by_rules": True,
            "skip_ai": True,
        }
    
    return None


def check_low_value_domestic(shipment: dict[str, Any]) -> dict[str, Any] | None:
    """
    Auto-clear low-value domestic shipments without AI.
    
    Criteria:
    - Declared value < $100 USD
    - Domestic safe route (e.g., HCMC <-> Hanoi)
    - No dual-use HS codes
    """
    value = _num(shipment.get("declared_value"))
    if value is None or value >= LOW_VALUE_THRESHOLD_USD:
        return None
    
    origin = _normalize(shipment.get("origin"))
    dest = _normalize(shipment.get("destination"))
    route_key = (origin, dest)
    
    # Check if it's a safe domestic route
    if route_key not in DOMESTIC_SAFE_ROUTES:
        return None
    
    # Check for dual-use HS codes (still need AI review)
    hs_code = str(shipment.get("hs_code") or "").strip()
    if hs_code:
        digits = re.sub(r"\D", "", hs_code)
        if len(digits) >= 4 and digits[:4] in DUAL_USE_HS_PREFIXES:
            return None  # Dual-use items need AI review regardless of value
    
    return {
        "code": "LOW_VALUE_DOMESTIC",
        "severity": "CLEAR",
        "floor": 0,
        "detail": f"Low-value domestic shipment (${value:.0f} USD, {origin} → {dest}). Auto-cleared by rules.",
        "auto_clear_by_rules": True,
        "skip_ai": True,
    }


def check_freight_ratio(shipment: dict[str, Any]) -> dict[str, Any] | None:
    cost = _num(shipment.get("shipping_cost"))
    if cost is None or cost <= 0:
        return {
            "code": "FREIGHT_MISSING",
            "severity": "HIGH",
            "floor": 60,
            "detail": "No freight charge on the record; pricing cannot be validated.",
        }

    baseline, source = lane_baseline(shipment)
    ratio = cost / baseline

    if ratio < 0.25:
        sev, floor = "CRITICAL", 90
    elif ratio < 0.50:
        sev, floor = "HIGH", 75
    elif ratio < 0.70:
        sev, floor = "MEDIUM", 50
    elif ratio > 3.0:
        # Grossly overpriced is its own typology: over-invoicing to move value.
        sev, floor = "MEDIUM", 50
    else:
        return None

    return {
        "code": "FREIGHT_ANOMALY",
        "severity": sev,
        "floor": floor,
        "detail": (
            f"Freight {cost:,.0f} USD is {ratio:.0%} of the {baseline:,.0f} USD "
            f"baseline ({source})."
        ),
        "measured": {"shipping_cost": cost, "baseline": baseline, "ratio": round(ratio, 3)},
    }


def check_value_density(shipment: dict[str, Any]) -> dict[str, Any] | None:
    value = _num(shipment.get("declared_value"))
    weight = _num(shipment.get("weight_kg"))
    if not value or not weight or weight <= 0:
        return None

    per_kg = value / weight
    if per_kg > 500:
        return {
            "code": "VALUE_DENSITY_HIGH",
            "severity": "MEDIUM",
            "floor": 50,
            "detail": (
                f"Declared value is {per_kg:,.0f} USD/kg, consistent with "
                "high-value or controlled goods rather than general cargo."
            ),
            "measured": {"usd_per_kg": round(per_kg, 2)},
        }
    if per_kg < 1.0:
        return {
            "code": "VALUE_DENSITY_LOW",
            "severity": "MEDIUM",
            "floor": 45,
            "detail": (
                f"Declared value is only {per_kg:,.2f} USD/kg, which is a "
                "classic under-invoicing pattern."
            ),
            "measured": {"usd_per_kg": round(per_kg, 2)},
        }
    return None


def check_mandatory_fields(shipment: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Absent paperwork is a finding, never a blank to be helpfully filled in.

    This is also why the document agent is instructed to emit "not stated"
    rather than a plausible value: a fabricated tax ID would silence this check
    entirely.
    """
    required = {
        "shipper_tax_id": ("SHIPPER_TAX_ID_MISSING", "HIGH", 65),
        "hs_code": ("HS_CODE_MISSING", "HIGH", 60),
        "cargo_description": ("CARGO_DESCRIPTION_MISSING", "HIGH", 60),
        "shipper_country": ("SHIPPER_COUNTRY_MISSING", "MEDIUM", 45),
        "receiver_country": ("RECEIVER_COUNTRY_MISSING", "MEDIUM", 45),
    }

    findings = []
    for field, (code, sev, floor) in required.items():
        if _is_missing(shipment.get(field)):
            findings.append({
                "code": code,
                "severity": sev,
                "floor": floor,
                "detail": f"Mandatory field '{field}' is absent from the record.",
            })
    return findings


def check_hs_code(shipment: dict[str, Any]) -> list[dict[str, Any]]:
    raw = str(shipment.get("hs_code") or "").strip()
    if _is_missing(raw):
        return []  # already covered by mandatory-field check

    findings: list[dict[str, Any]] = []
    digits = re.sub(r"\D", "", raw)

    if len(digits) < 4:
        findings.append({
            "code": "HS_CODE_MALFORMED",
            "severity": "MEDIUM",
            "floor": 45,
            "detail": f"HS code '{raw}' is not a valid heading; at least 4 digits expected.",
        })
        return findings

    prefix = digits[:4]
    if prefix in DUAL_USE_HS_PREFIXES:
        findings.append({
            "code": "DUAL_USE_HS_CODE",
            "severity": "CRITICAL",
            "floor": 85,
            "detail": (
                f"HS {prefix} ({DUAL_USE_HS_PREFIXES[prefix]}) carries dual-use "
                "or export-control sensitivity."
            ),
            "measured": {"hs_prefix": prefix},
        })
    return findings


def check_routing(shipment: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    dest = _country(shipment.get("destination"))
    route = str(shipment.get("route_details") or "").lower()
    transit = str(shipment.get("transit_points") or "").lower()

    if dest in HIGH_RISK_DESTINATIONS:
        findings.append({
            "code": "HIGH_RISK_DESTINATION",
            "severity": "HIGH",
            "floor": 70,
            "detail": f"Destination '{dest}' is on the enhanced due diligence list.",
        })

    hubs = [h for h in DIVERSION_HUBS if h in transit]
    if len(hubs) >= 2:
        findings.append({
            "code": "MULTIPLE_DIVERSION_HUBS",
            "severity": "HIGH",
            "floor": 70,
            "detail": (
                f"Routed through {len(hubs)} transhipment hubs commonly used to "
                f"obscure final destination: {', '.join(sorted(hubs))}."
            ),
        })

    if re.search(r"(added|amended|changed|modified).{0,40}(after|post).{0,20}book", route):
        findings.append({
            "code": "ROUTE_CHANGED_AFTER_BOOKING",
            "severity": "HIGH",
            "floor": 75,
            "detail": "Routing was altered after the original booking was made.",
        })

    return findings


def check_counterparty(shipment: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []

    # Set by shipper_registry.enrich() when the tax ID on the document is one we
    # hold, but under a different company name. That is not a clerical problem:
    # it is paperwork presenting another company's tax number, which is the
    # cheapest way to try to inherit a good counterparty's history. The floor sits
    # above INVESTIGATE_AT deliberately, so it escalates rather than queueing -
    # otherwise "unknown shipper" and "shipper impersonating a known one" would
    # carry the same consequence, and the second is strictly worse.
    #
    # Only the document path is enriched today, so this only fires there. A data
    # event supplies its history directly from an internal system, which is a
    # different trust question and not one this check answers.
    if str(shipment.get("shipper_identity_status") or "") == "identity_mismatch":
        findings.append({
            "code": "SHIPPER_IDENTITY_MISMATCH",
            "severity": "HIGH",
            "floor": 75,
            "detail": str(
                shipment.get("shipper_identity_reason")
                or "The shipper tax ID on file belongs to a different company."
            ),
        })

    tx = _num(shipment.get("shipper_tx_count"))
    if tx is None:
        # Deliberate: `shipper_tx_count` is excluded from the document schema in
        # untrusted.py, because a document that could assert its own shipper's
        # history would defeat this check by claiming a long one. Absent history
        # therefore means unverified, and unverified is not clean.
        findings.append({
            "code": "SHIPPER_HISTORY_UNVERIFIED",
            "severity": "MEDIUM",
            "floor": 45,
            "detail": (
                "Shipper transaction history is not available from internal "
                "records and cannot be taken from the document."
            ),
        })
    elif tx <= 1:
        findings.append({
            "code": "SHIPPER_NO_HISTORY",
            "severity": "HIGH",
            "floor": 65,
            "detail": f"Shipper has {int(tx)} prior shipment(s) on file.",
            "measured": {"shipper_tx_count": int(tx)},
        })
    elif tx < 10:
        findings.append({
            "code": "SHIPPER_THIN_HISTORY",
            "severity": "MEDIUM",
            "floor": 45,
            "detail": f"Shipper has only {int(tx)} prior shipments on file.",
            "measured": {"shipper_tx_count": int(tx)},
        })

    company = str(shipment.get("shipper_company") or "")
    if re.search(r"registered\s+\d+\s+day", company, re.I) or re.search(
        r"issued\s+20\d\d-\d\d-\d\d", company, re.I
    ):
        findings.append({
            "code": "RECENTLY_REGISTERED_SHIPPER",
            "severity": "HIGH",
            "floor": 70,
            "detail": f"Shipper registration appears very recent: '{company}'.",
        })

    return findings


# --------------------------------------------------------------------------
# Fabrication guard
# --------------------------------------------------------------------------

def check_exposure_claim(
    shipment: dict[str, Any], investigation: dict[str, Any] | None
) -> dict[str, Any] | None:
    """
    Sanity-check the figure the investigation agent puts on the case.

    An agent inflating exposure by three orders of magnitude is not producing
    intelligence, it is producing a number that will end up in a regulatory
    filing. Flag it rather than pass it through.
    """
    if not investigation:
        return None

    claim = str(investigation.get("exposure_estimate") or "")
    value = _num(shipment.get("declared_value"))
    if not claim or not value or value <= 0:
        return None

    numbers = [
        float(n.replace(",", ""))
        for n in re.findall(r"\d[\d,]*(?:\.\d+)?", claim)
    ]
    if not numbers:
        return None

    biggest = max(numbers)
    if biggest > value * 100:
        return {
            "code": "EXPOSURE_CLAIM_UNSUPPORTED",
            "severity": "MEDIUM",
            "floor": 0,  # a reporting-quality problem, not a risk signal
            "detail": (
                f"Agent cited {biggest:,.0f} against a declared value of "
                f"{value:,.0f} USD, a {biggest / value:.0f}x multiple with no "
                "stated basis. Figure needs human substantiation before it is "
                "used in any filing."
            ),
            "measured": {"claimed": biggest, "declared_value": value},
        }
    return None


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------

# NOTE: There used to be a `prefilter()` function here that checked
# whitelist/blacklist/low-value in isolation, before any of the other
# deterministic checks. It was removed because it created a total bypass:
# a whitelist match alone would skip freight-ratio, value-density, dual-use
# HS, high-risk-destination, and mandatory-field checks, not just the AI
# call. The orchestrator now drives its fast-path decision off validate()
# below, whose skip_ai flag only fires when a clearance signal (whitelist,
# low-value domestic) is present AND no other HIGH/CRITICAL finding
# contradicts it. Do not reintroduce a narrower short-circuit that checks
# clearance signals without also running the rest of this battery.


def validate(shipment: dict[str, Any]) -> dict[str, Any]:
    """Run every deterministic check and return findings plus the risk floor."""
    findings: list[dict[str, Any]] = []
    
    # Run pre-filter checks first (whitelist/blacklist/low-value)
    prefilter_checks = [
        check_whitelist(shipment),
        check_blacklist(shipment),
        check_low_value_domestic(shipment),
    ]
    for check in prefilter_checks:
        if check:
            findings.append(check)

    for single in (check_freight_ratio(shipment), check_value_density(shipment)):
        if single:
            findings.append(single)

    findings.extend(check_mandatory_fields(shipment))
    findings.extend(check_hs_code(shipment))
    findings.extend(check_routing(shipment))
    findings.extend(check_counterparty(shipment))

    # Determine if auto-clear/reject by rules
    skip_ai_findings = [f for f in findings if f.get("skip_ai")]
    auto_clear_by_rules = any(f.get("auto_clear_by_rules") for f in findings)
    auto_reject_by_rules = any(f.get("auto_reject_by_rules") for f in findings)
    
    # Calculate floor (blacklist = 100, whitelist/low-value = 0)
    if auto_reject_by_rules:
        floor = 100
    elif auto_clear_by_rules and not any(
        f["severity"] in ("HIGH", "CRITICAL") 
        for f in findings 
        if not f.get("auto_clear_by_rules")
    ):
        floor = 0
    else:
        floor = max((f.get("floor", 0) for f in findings if not f.get("skip_ai")), default=0)

    # Corroboration matters: several independent mid-severity facts together are
    # worse than any one of them alone.
    high_count = sum(1 for f in findings if f["severity"] in ("HIGH", "CRITICAL"))
    if high_count >= 3:
        floor = max(floor, 90)
    elif high_count == 2:
        floor = max(floor, 80)

    return {
        "risk_floor": min(floor, 100),
        "findings": findings,
        "finding_count": len(findings),
        "high_severity_count": high_count,
        "skip_ai": bool(skip_ai_findings) and not any(
            f["severity"] in ("HIGH", "CRITICAL") 
            for f in findings 
            if not f.get("skip_ai")
        ),
        "auto_clear_by_rules": auto_clear_by_rules,
        "auto_reject_by_rules": auto_reject_by_rules,
        "cleared_by": "rules" if (auto_clear_by_rules or auto_reject_by_rules) else None,
        "checks_run": [
            "whitelist", "blacklist", "low_value_domestic",
            "freight_ratio", "value_density", "mandatory_fields",
            "hs_code", "routing", "counterparty",
        ],
    }


def reconcile(model_risk: Any, validation: dict[str, Any]) -> dict[str, Any]:
    """
    Combine the agent's score with the deterministic floor.

    Returns the effective risk plus enough detail for a human to see that the
    two disagreed, rather than a single laundered number.
    """
    floor = int(validation.get("risk_floor", 0))
    stated = _num(model_risk)
    model_score = int(stated) if stated is not None else None

    if model_score is None:
        # No usable model score: the floor is all we have, and a missing score
        # must never be read as a low one.
        return {
            "effective_risk": max(floor, 50),
            "model_risk": None,
            "risk_floor": floor,
            "source": "floor only, model returned no usable score",
            "score_disputed": True,
            "auto_clear_permitted": False,
            "veto_reasons": [f["detail"] for f in validation.get("findings", [])],
        }

    effective = max(model_score, floor)
    disputed = (floor - model_score) >= 15
    vetoed = effective > model_score

    return {
        "effective_risk": effective,
        "model_risk": model_score,
        "risk_floor": floor,
        "source": "deterministic floor" if vetoed else "agent score",
        "score_disputed": disputed,
        # Auto-clear needs both to agree. This is the line an agent cannot cross
        # on its own, whether it is mistaken, overconfident, or manipulated.
        "auto_clear_permitted": floor == 0,
        "veto_reasons": (
            [f["detail"] for f in validation.get("findings", [])] if vetoed else []
        ),
    }


# --------------------------------------------------------------------------
# Pre-filter Rules API: Get and Update SQL pre-processing rules
# --------------------------------------------------------------------------

def get_prefilter_rules() -> dict[str, Any]:
    """Return current SQL pre-filter rules for UI display."""
    return {
        "vip_registry": sorted(VIP_REGISTRY, key=lambda e: e["company"]),
        "blacklist_companies": sorted(BLACKLIST_COMPANIES),
        "blacklist_tax_ids": sorted(BLACKLIST_TAX_IDS),
        "safe_routes": [
            {"origin": o, "destination": d} 
            for o, d in sorted(DOMESTIC_SAFE_ROUTES)
        ],
        "low_value_threshold_usd": LOW_VALUE_THRESHOLD_USD,
    }


def update_prefilter_rules(rules: dict[str, Any]) -> dict[str, Any]:
    """
    Update SQL pre-filter rules from UI.
    
    Modifies the module-level sets/values so changes take effect immediately.
    Returns the updated rules for confirmation.
    """
    global VIP_REGISTRY
    global BLACKLIST_COMPANIES, BLACKLIST_TAX_IDS
    global DOMESTIC_SAFE_ROUTES, LOW_VALUE_THRESHOLD_USD
    
    errors = []
    
    # Validate and update the VIP registry (paired company + tax_id entries).
    # A tax_id is optional (name-only tier) but company is required, since an
    # entry with neither is meaningless. Duplicate companies are collapsed to
    # the last one supplied.
    if "vip_registry" in rules:
        items = rules["vip_registry"]
        if isinstance(items, list):
            new_registry: dict[str, str] = {}
            bad_entries = False
            for entry in items:
                if not isinstance(entry, dict) or not entry.get("company"):
                    bad_entries = True
                    continue
                company = _normalize(entry.get("company"))
                tax_id = str(entry.get("tax_id") or "").strip()
                if company:
                    new_registry[company] = tax_id
            if bad_entries:
                errors.append("vip_registry entries must each have a non-empty 'company'")
            else:
                VIP_REGISTRY = [
                    {"company": c, "tax_id": t} for c, t in new_registry.items()
                ]
        else:
            errors.append("vip_registry must be a list of {company, tax_id}")
    
    # Validate and update blacklist companies
    if "blacklist_companies" in rules:
        items = rules["blacklist_companies"]
        if isinstance(items, list):
            BLACKLIST_COMPANIES = {_normalize(c) for c in items if c}
        else:
            errors.append("blacklist_companies must be a list")
    
    # Validate and update blacklist tax IDs
    if "blacklist_tax_ids" in rules:
        items = rules["blacklist_tax_ids"]
        if isinstance(items, list):
            BLACKLIST_TAX_IDS = {str(t).strip() for t in items if t}
        else:
            errors.append("blacklist_tax_ids must be a list")
    
    # Validate and update safe routes
    if "safe_routes" in rules:
        routes = rules["safe_routes"]
        if isinstance(routes, list):
            new_routes = set()
            for r in routes:
                if isinstance(r, dict) and "origin" in r and "destination" in r:
                    new_routes.add((
                        _normalize(r["origin"]),
                        _normalize(r["destination"])
                    ))
            DOMESTIC_SAFE_ROUTES = new_routes
        else:
            errors.append("safe_routes must be a list of {origin, destination}")
    
    # Validate and update low-value threshold
    if "low_value_threshold_usd" in rules:
        val = rules["low_value_threshold_usd"]
        try:
            threshold = float(val)
            if threshold >= 0:
                LOW_VALUE_THRESHOLD_USD = threshold
            else:
                errors.append("low_value_threshold_usd must be non-negative")
        except (TypeError, ValueError):
            errors.append("low_value_threshold_usd must be a number")
    
    if errors:
        return {"ok": False, "errors": errors}
    
    return {"ok": True, "rules": get_prefilter_rules()}
