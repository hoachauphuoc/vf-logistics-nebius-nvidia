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
from dataclasses import dataclass, replace
from typing import Any

from vf_logistics import hs_reference

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


# --------------------------------------------------------------------------
# The rule set as a value, rather than as five module globals
# --------------------------------------------------------------------------
#
# The five names above are the bundled *defaults*. They used to also be the live
# configuration, rebound in place by update_prefilter_rules() with `global`. That
# made a single-tenant assumption load-bearing in the worst possible place: one
# customer editing their blacklist changed what every other customer's shipments
# were screened against, and the change was invisible -- no audit record on the
# affected tenants, no diff, just a different verdict on the next shipment.
#
# Threading a `tenant_id` parameter down to the check functions could not fix
# that, because the values were not reachable from a parameter. So the rule set
# becomes a value that is passed in, and the per-tenant copy lives in the store.
# `defaults()` rebuilds it from the constants above, which stay as the seed a
# tenant starts from.
#
# Deliberately frozen. A check function receiving a mutable rule set could edit
# it, and then whether a shipment cleared would depend on which checks had
# already run against the same object.

@dataclass(frozen=True)
class PrefilterRules:
    """The pre-AI screening configuration for one tenant."""

    vip_registry: tuple[tuple[str, str], ...]
    blacklist_companies: frozenset[str]
    blacklist_tax_ids: frozenset[str]
    safe_routes: frozenset[tuple[str, str]]
    low_value_threshold_usd: float

    @classmethod
    def defaults(cls) -> "PrefilterRules":
        """The bundled rule set, which a tenant with no stored rules gets."""
        return cls(
            vip_registry=tuple(
                (e["company"], e["tax_id"]) for e in VIP_REGISTRY
            ),
            blacklist_companies=frozenset(BLACKLIST_COMPANIES),
            blacklist_tax_ids=frozenset(BLACKLIST_TAX_IDS),
            safe_routes=frozenset(DOMESTIC_SAFE_ROUTES),
            low_value_threshold_usd=LOW_VALUE_THRESHOLD_USD,
        )

    def to_dict(self) -> dict[str, Any]:
        """The wire/storage shape. Sorted so a diff between two versions reads."""
        return {
            "vip_registry": [
                {"company": c, "tax_id": t} for c, t in sorted(self.vip_registry)
            ],
            "blacklist_companies": sorted(self.blacklist_companies),
            "blacklist_tax_ids": sorted(self.blacklist_tax_ids),
            "safe_routes": [
                {"origin": o, "destination": d} for o, d in sorted(self.safe_routes)
            ],
            "low_value_threshold_usd": self.low_value_threshold_usd,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "PrefilterRules":
        """
        Rebuild from stored form, falling back to a default per missing key.

        Per key rather than all-or-nothing: a stored document written before a
        key existed should not silently reset the four keys it does have.
        """
        if not data:
            return cls.defaults()
        base = cls.defaults()
        registry = data.get("vip_registry")
        routes = data.get("safe_routes")
        return cls(
            vip_registry=(
                tuple(
                    (_normalize(e.get("company")), str(e.get("tax_id") or "").strip())
                    for e in registry
                    if isinstance(e, dict) and e.get("company")
                )
                if isinstance(registry, list)
                else base.vip_registry
            ),
            blacklist_companies=(
                frozenset(_normalize(c) for c in data["blacklist_companies"] if c)
                if isinstance(data.get("blacklist_companies"), list)
                else base.blacklist_companies
            ),
            blacklist_tax_ids=(
                frozenset(str(t).strip() for t in data["blacklist_tax_ids"] if t)
                if isinstance(data.get("blacklist_tax_ids"), list)
                else base.blacklist_tax_ids
            ),
            safe_routes=(
                frozenset(
                    (_normalize(r.get("origin")), _normalize(r.get("destination")))
                    for r in routes
                    if isinstance(r, dict) and "origin" in r and "destination" in r
                )
                if isinstance(routes, list)
                else base.safe_routes
            ),
            low_value_threshold_usd=(
                float(data["low_value_threshold_usd"])
                if isinstance(data.get("low_value_threshold_usd"), (int, float))
                else base.low_value_threshold_usd
            ),
        )


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

# The same hubs, mapped to the PLACE each one names.
#
# Three of the entries above are nested names for one location: Jebel Ali is a port in
# Dubai, which is in the UAE. Counting them as separate hubs made a single port call
# read as two or three, and both consumers of this list count hubs to decide something:
# MULTIPLE_DIVERSION_HUBS below raises the risk floor to 70 on two, and
# zero_day_agent.should_screen() spends up to four Nemotron completions on two.
#
# Measured against the real generator inputs: "Jebel Ali, UAE" yielded
# ['jebel ali', 'uae'] and "Dubai, UAE" yielded ['dubai', 'uae'], so a shipment through
# one Emirati port tripped a rule whose own name says MULTIPLE. Canonicalising collapses
# each to `uae` and the count becomes one.
HUB_ALIASES = {
    "jebel ali": "uae",
    "dubai": "uae",
    "uae": "uae",
    "port klang": "port klang",
    "hong kong": "hong kong",
    "singapore": "singapore",
    "kaohsiung": "kaohsiung",
    "busan": "busan",
}


def distinct_hubs(text: str, exclude: str = "") -> set[str]:
    """
    The set of distinct transhipment PLACES named in `text`.

    `exclude` removes a value before matching, and it exists because route text
    restates the destination: `route_details` is written as
    "<origin> to <hub>, onward carriage to <final>", so a shipment whose final
    destination is Busan picked up `busan` as a hub. A destination is where the cargo is
    going, not evidence it is being concealed -- and Busan, Singapore and Hong Kong are
    all ordinary destinations that also appear on this list.
    """
    haystack = str(text or "").lower()
    if exclude:
        haystack = haystack.replace(str(exclude).lower(), " ")
    return {
        HUB_ALIASES[alias] for alias in DIVERSION_HUBS if alias in haystack
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

def check_whitelist(
    shipment: dict[str, Any], rules: PrefilterRules | None = None,
) -> dict[str, Any] | None:
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
    rules = rules or PrefilterRules.defaults()
    company = _normalize(shipment.get("shipper_company"))
    tax_id = str(shipment.get("shipper_tax_id") or "").strip()

    by_company = dict(rules.vip_registry)
    by_taxid = {t: c for c, t in rules.vip_registry if t}

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


def check_blacklist(
    shipment: dict[str, Any], rules: PrefilterRules | None = None,
) -> dict[str, Any] | None:
    """
    Check if shipper is on the internal blacklist.
    
    Returns a "BLACKLIST_MATCH" finding with floor=100, blocking immediately.
    """
    rules = rules or PrefilterRules.defaults()
    company = _normalize(shipment.get("shipper_company"))
    tax_id = str(shipment.get("shipper_tax_id") or "").strip()
    
    if company in rules.blacklist_companies:
        return {
            "code": "BLACKLIST_MATCH",
            "severity": "CRITICAL",
            "floor": 100,
            "detail": f"Shipper company '{company}' is on the internal blacklist. Auto-rejected by rules.",
            "auto_reject_by_rules": True,
            "skip_ai": True,
        }
    
    if tax_id in rules.blacklist_tax_ids:
        return {
            "code": "BLACKLIST_TAX_ID",
            "severity": "CRITICAL",
            "floor": 100,
            "detail": f"Shipper tax ID '{tax_id}' is on the internal blacklist. Auto-rejected by rules.",
            "auto_reject_by_rules": True,
            "skip_ai": True,
        }
    
    return None


def check_low_value_domestic(
    shipment: dict[str, Any], rules: PrefilterRules | None = None,
) -> dict[str, Any] | None:
    """
    Auto-clear low-value domestic shipments without AI.
    
    Criteria:
    - Declared value < $100 USD
    - Domestic safe route (e.g., HCMC <-> Hanoi)
    - No dual-use HS codes
    """
    rules = rules or PrefilterRules.defaults()
    value = _num(shipment.get("declared_value"))
    if value is None or value >= rules.low_value_threshold_usd:
        return None
    
    origin = _normalize(shipment.get("origin"))
    dest = _normalize(shipment.get("destination"))
    route_key = (origin, dest)
    
    # Check if it's a safe domestic route
    if route_key not in rules.safe_routes:
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


def check_freight_ratio(
    shipment: dict[str, Any], rules: PrefilterRules | None = None,
) -> dict[str, Any] | None:
    rules = rules or PrefilterRules.defaults()
    cost = _num(shipment.get("shipping_cost"))
    if cost is None or cost <= 0:
        return {
            "code": "FREIGHT_MISSING",
            "severity": "HIGH",
            "floor": 60,
            "detail": "No freight charge on the record; pricing cannot be validated.",
        }

    # Below the low-value threshold the lane baseline is the wrong yardstick, and
    # using it anyway made a documented cost-control path unreachable.
    #
    # lane_baseline() returns what it costs to move a commercial consignment on the
    # lane -- hundreds of dollars on a domestic Vietnamese route. A 99 dollar parcel
    # ships for a few dollars, so every such shipment came out under 25% of the
    # baseline, which is CRITICAL, which defeats skip_ai. Sweeping freight from 1
    # to 50 dollars on a 99 dollar consignment produced FREIGHT_ANOMALY at every
    # single value: LOW_VALUE_DOMESTIC could never actually skip the models, so
    # every parcel paid for two model calls to reach the answer arithmetic had
    # already given.
    #
    # Not a threshold to tune -- a category error. A parcel is not an underpriced
    # container. FREIGHT_MISSING above still applies at any scale, because an absent
    # freight charge is a data-quality problem rather than a pricing one, and the
    # exposure this forgoes is bounded by the same threshold that already permits
    # auto-clear.
    value = _num(shipment.get("declared_value"))
    if value is not None and value < rules.low_value_threshold_usd:
        return None

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


# Model judgement sits one step below a code-resident list match, on purpose.
# DUAL_USE_HS_CODE floors at 85 because it is a lookup: the declared prefix
# either is in the dict or is not. HS_DESCRIPTION_MISMATCH_DUAL_USE floors at 80
# because it is a semantic call about what the goods are. A reviewer reading the
# number alone can therefore tell which kind of evidence drove the case.
HS_MISMATCH_DUAL_USE_FLOOR = 80
HS_MISMATCH_FLOOR = 40
HS_MISMATCH_MIN_CONFIDENCE = 0.7


def check_hs_description_consistency(
    shipment: dict[str, Any],
    hs_verdict: dict[str, Any] | None,
    *,
    min_confidence: float = HS_MISMATCH_MIN_CONFIDENCE,
) -> list[dict[str, Any]]:
    """
    Turn an HS classifier verdict into a finding, upward only.

    This is the check check_hs_code() cannot be: it reads cargo_description,
    which the rest of this module touches exactly once, as a presence test. The
    declarant chooses the code, so comparing the declared code against a list of
    sensitive prefixes cannot catch a declarant who wrote a benign code over
    controlled goods. Deciding whether the prose matches the heading is a
    judgement, so it is made by a model -- and then handled here, under the same
    rules as every other finding.

    The function takes the verdict rather than calling the model, which keeps it
    pure and synchronous like its neighbours, and keeps the model call where it
    belongs: in the orchestrator, alongside the other agents, where its tokens
    are accounted for.

    What a model is allowed to do here
    ----------------------------------
    Raise risk, never lower it. A "consistent" verdict produces no finding at
    all, so a model that is mistaken, overconfident or manipulated into blessing
    a shipment changes nothing -- the deterministic floor still stands and the
    case proceeds exactly as it would have without the check. Only a mismatch
    can move anything, and it can only move it up. That asymmetry is the whole
    safety argument, and it is why this returns findings instead of a score.

    An unavailable answer is recorded rather than dropped. A model outage that
    quietly produced no finding would be indistinguishable from a model that
    looked and found nothing, and those two must not read the same to a human.
    """
    verdict = (hs_verdict or {}).get("verdict")
    declared = re.sub(r"\D", "", str(shipment.get("hs_code") or ""))[:4]

    if not hs_verdict or verdict is None:
        return []

    if verdict in ("unknown", "error"):
        return [{
            "code": "HS_DESCRIPTION_CHECK_UNAVAILABLE",
            "severity": "INFO",
            "floor": 0,
            "detail": (
                "The HS description consistency check did not return a usable "
                f"answer ({hs_verdict.get('reasoning') or 'no detail'}). The goods "
                "description has NOT been compared against the declared heading."
            ),
        }]

    if verdict == "consistent":
        # Deliberately nothing. A model cannot clear a shipment here.
        return []

    suggested = hs_verdict.get("suggested_hs")
    confidence = float(hs_verdict.get("confidence") or 0.0)
    reasoning = str(hs_verdict.get("reasoning") or "").strip()
    obfuscation = hs_verdict.get("obfuscation")

    if confidence < min_confidence:
        return [{
            "code": "HS_DESCRIPTION_MISMATCH_LOW_CONFIDENCE",
            "severity": "LOW",
            "floor": 0,
            "detail": (
                f"Possible HS misclassification, below the {min_confidence:.0%} "
                f"confidence needed to act on: {reasoning or 'no reasoning given'}"
            ),
            "measured": {"declared_hs": declared, "suggested_hs": suggested,
                         "confidence": confidence},
        }]

    basis = hs_reference.control_basis(suggested)
    dual_use = hs_reference.is_dual_use(suggested)

    detail = (
        f"Cargo description does not match declared HS {declared or 'unknown'}; "
        f"the goods appear to belong to {suggested or 'another heading'}. {reasoning}"
    )
    if basis:
        detail += f" Heading {suggested} is export-control sensitive: {basis}."
    if obfuscation and obfuscation != "none":
        detail += f" Description shows signs of {obfuscation.replace('_', ' ')}."

    return [{
        "code": "HS_DESCRIPTION_MISMATCH_DUAL_USE" if dual_use else "HS_DESCRIPTION_MISMATCH",
        "severity": "CRITICAL" if dual_use else "MEDIUM",
        "floor": HS_MISMATCH_DUAL_USE_FLOOR if dual_use else HS_MISMATCH_FLOOR,
        "detail": detail,
        "measured": {
            "declared_hs": declared,
            "suggested_hs": suggested,
            "suggested_is_dual_use": dual_use,
            "confidence": confidence,
            "obfuscation": obfuscation,
        },
    }]


def check_sanctions_screening(
    shipment: dict[str, Any],
    screening: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Turn a sanctions index lookup into findings.

    This is a deterministic lookup, not a judgement, so unlike
    check_hs_description_consistency() it does its own work rather than taking a
    model's verdict. `screening` is injectable so callers already holding a result
    -- and tests -- do not repeat the lookup.

    Three outcomes, and the difference between the last two is the whole point:

      HIT         a designated party is on the shipment. floor 100 and
                  auto_reject_by_rules, the same treatment as the code-resident
                  blacklist, because a designation is not a risk signal to weigh
                  against others.

      UNAVAILABLE the list could not be read. A HIGH finding that blocks
                  auto-clear, because "we screened and found nothing" and "we did
                  not screen" are opposite facts and must not read the same. An
                  empty index would otherwise clear every shipment while
                  producing paperwork saying a check was performed -- which is
                  worse than having no check at all.

      CLEAN       no finding, but the snapshot is still recorded on the case so a
                  reviewer can see which list version was screened and how old it
                  was.

    source_entity_ids goes into `measured` because lineage.source_entity_ids()
    reads it from there. That field is what turns "flagged as high risk" into
    "matched OFAC SDN entry 12345", which is the difference between an answer a
    customs authority accepts and an assertion it does not.
    """
    if screening is None:
        from vf_logistics import sanctions

        screening = sanctions.screen_shipment(shipment)

    status = screening.get("status")

    if status == "UNAVAILABLE":
        return [{
            "code": "SANCTIONS_SCREENING_UNAVAILABLE",
            "severity": "HIGH",
            "floor": 60,
            "detail": (
                "The sanctions list could not be read, so no screening was "
                f"performed on this shipment ({screening.get('reason') or 'no detail'}). "
                "The absence of a match below is not a clearance."
            ),
            "measured": {"screening_status": "UNAVAILABLE"},
        }]

    matches = screening.get("matches") or []
    if not matches:
        return []

    snapshot = screening.get("snapshot") or {}
    worst = "MEDIUM"
    for order in ("CRITICAL", "HIGH", "MEDIUM"):
        if any(m.get("risk_level") == order for m in matches):
            worst = order
            break

    roles = sorted({str(m.get("role")) for m in matches})
    named = "; ".join(
        f"{m.get('role')} \"{m.get('matched_value')}\" matches "
        f"{m.get('entity_name')} ({m.get('entity_id')}, "
        f"{', '.join(m.get('programs') or []) or 'no programme stated'})"
        for m in matches[:4]
    )

    detail = f"Sanctions screening matched {len(matches)} record(s): {named}."
    age = snapshot.get("age_days")
    if age is not None:
        detail += f" Screened against {snapshot.get('source')} list published {age} day(s) ago."

    return [{
        "code": "SANCTIONS_MATCH",
        "severity": "CRITICAL" if worst == "CRITICAL" else "HIGH",
        "floor": 100 if worst == "CRITICAL" else 85,
        # A full designation is not a score to weigh; it is a prohibition. Only
        # the CRITICAL tier auto-rejects -- an export-control listing or a
        # sanction.linked association is serious but is a human's call.
        "auto_reject_by_rules": worst == "CRITICAL",
        "detail": detail,
        "measured": {
            "screening_status": "HIT",
            "match_count": len(matches),
            "roles": roles,
            "worst_risk_level": worst,
            "source_entity_ids": sorted({
                str(m.get("entity_id")) for m in matches
            }),
            "programs": sorted({
                p for m in matches for p in (m.get("programs") or [])
            }),
            "sanctions_list_version": snapshot.get("version"),
            "sanctions_synced_at": snapshot.get("synced_at"),
            "sanctions_list_age_days": age,
        },
    }]


def check_zero_day(
    shipment: dict[str, Any],
    zero_day: dict[str, Any] | None,
    *,
    min_confidence: float = 0.7,
) -> list[dict[str, Any]]:
    """
    Turn a zero-day adverse-media verdict into a finding, upward only.

    Floors below the sanctions-match tiers on purpose. A news report is weaker
    evidence than a designation: SANCTIONS_MATCH at 100 or 85 rests on a
    government listing, this rests on a model's reading of press coverage, and the
    number a reviewer sees should say which kind of evidence drove the case.

    A "no risk found" verdict produces nothing at all, so a model that is mistaken
    or manipulated into blessing a counterparty changes nothing -- the
    deterministic floor still stands. That asymmetry is the entire safety
    argument, the same one behind check_hs_description_consistency().

    The searched/unknown cases are recorded rather than dropped. tavily_client
    returns an empty list for a missing API key, a timeout and a genuinely empty
    result alike, so silence about a failed search would be indistinguishable from
    a counterparty that came back clean.
    """
    if not zero_day:
        return []

    verdict = zero_day.get("verdict")

    if verdict == "unknown":
        return [{
            "code": "ZERO_DAY_CHECK_UNAVAILABLE",
            "severity": "LOW",
            "floor": 0,
            "detail": (
                "Adverse-media screening returned no usable verdict "
                f"({zero_day.get('reasoning') or 'no detail'}). The counterparties "
                "have NOT been checked against recent news."
            ),
            "measured": {"zero_day_status": "unknown"},
        }]

    if verdict == "no_risk_found" and not zero_day.get("searched"):
        # The model concluded nothing was found, but nothing was searched. Not a
        # clearance, and not silent either.
        return [{
            "code": "ZERO_DAY_SEARCH_DID_NOT_RUN",
            "severity": "MEDIUM",
            "floor": 40,
            "detail": (
                "Adverse-media screening reported no findings but no search "
                "actually ran, so absence of evidence here is not evidence of "
                "absence."
            ),
            "measured": {"zero_day_status": "not_searched"},
        }]

    if verdict != "risk_found":
        return []

    confidence = float(zero_day.get("confidence") or 0.0)
    reasoning = str(zero_day.get("reasoning") or "").strip()
    urls = [str(u) for u in (zero_day.get("evidence_urls") or [])[:6]]

    if confidence < min_confidence:
        return [{
            "code": "ZERO_DAY_ADVERSE_MEDIA_LOW_CONFIDENCE",
            "severity": "LOW",
            "floor": 0,
            "detail": (
                f"Possible adverse media, below the {min_confidence:.0%} "
                f"confidence needed to act on: {reasoning or 'no reasoning given'}"
            ),
            "measured": {"confidence": confidence, "evidence_urls": urls},
        }]

    return [{
        "code": "ZERO_DAY_ADVERSE_MEDIA",
        "severity": "HIGH",
        "floor": 70,
        "detail": (
            "Recent adverse coverage on a counterparty absent from the official "
            f"sanctions list: {reasoning}"
            + (f" Sources: {', '.join(urls)}" if urls else "")
        ),
        "measured": {
            "zero_day_status": "risk_found",
            "confidence": confidence,
            "evidence_urls": urls,
            "entities_checked": zero_day.get("entities_checked") or [],
        },
    }]


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

    hubs = sorted(distinct_hubs(transit, exclude=dest))
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


def validate(
    shipment: dict[str, Any],
    hs_verdict: dict[str, Any] | None = None,
    sanctions_screening: dict[str, Any] | None = None,
    screen_sanctions: bool = True,
    zero_day: dict[str, Any] | None = None,
    rules: PrefilterRules | None = None,
) -> dict[str, Any]:
    """
    Run every deterministic check and return findings plus the risk floor.

    `hs_verdict` is the optional output of the HS classification agent, passed as
    data rather than fetched, so this function stays synchronous and free. When
    supplied it takes part in the ordinary floor and corroboration arithmetic
    instead of being merged in afterwards -- one code path computes the floor, so
    there is no second path to drift out of agreement with it.

    `sanctions_screening` is the sanctions index lookup. Unlike hs_verdict it is
    computed here when absent, because it is a deterministic lookup rather than a
    model call. It is not quite free: the first call in a container's life reads
    the index from GCS or from the bundled seed, which is I/O, and this module's
    header claims there is none. The claim holds for every subsequent call --
    sanctions.load() caches for SANCTIONS_RELOAD_SECONDS and the check is then a
    dict lookup -- and the alternative was worse. Requiring every caller to inject
    a screening result means a caller who forgot gets a clean-looking validation
    from a check that never ran, and that mistake is invisible.

    Pass `screen_sanctions=False` only to isolate the other checks in a test.

    The floor is computed twice, with and without the model's finding, and
    `hs_floor_effect` records the difference. That is not diagnostics: it is how
    the claim that a model can raise risk but never lower it gets checked on every
    call rather than argued in a comment.
    """
    findings: list[dict[str, Any]] = []
    # Defaulted here, once, rather than in each check: four checks defaulting
    # independently could disagree if the default ever stops being a pure
    # function of the module constants.
    rules = rules or PrefilterRules.defaults()
    
    # Run pre-filter checks first (whitelist/blacklist/low-value)
    prefilter_checks = [
        check_whitelist(shipment, rules),
        check_blacklist(shipment, rules),
        check_low_value_domestic(shipment, rules),
    ]
    for check in prefilter_checks:
        if check:
            findings.append(check)

    for single in (check_freight_ratio(shipment, rules), check_value_density(shipment)):
        if single:
            findings.append(single)

    findings.extend(check_mandatory_fields(shipment))
    findings.extend(check_hs_code(shipment))
    findings.extend(check_routing(shipment))
    findings.extend(check_counterparty(shipment))

    # Deterministic, so it counts as part of the baseline rather than as a model
    # contribution -- it is included before the deterministic_only snapshot below.
    screening: dict[str, Any] | None = sanctions_screening
    if screening is None and screen_sanctions:
        from vf_logistics import sanctions as sanctions_index

        screening = sanctions_index.screen_shipment(shipment)
    if screening is not None:
        findings.extend(check_sanctions_screening(shipment, screening))

    deterministic_only = list(findings)
    hs_findings = check_hs_description_consistency(shipment, hs_verdict)
    findings.extend(hs_findings)
    model_findings = list(hs_findings)
    zero_day_findings = check_zero_day(shipment, zero_day)
    findings.extend(zero_day_findings)
    model_findings.extend(zero_day_findings)

    # Determine if auto-clear/reject by rules
    skip_ai_findings = [f for f in findings if f.get("skip_ai")]

    floor, high_count, auto_clear_by_rules, auto_reject_by_rules = _floor_for(findings)

    # The same arithmetic on the deterministic findings alone. If adding the
    # model's finding ever moved the floor down, that is a bug in
    # check_hs_description_consistency() and must surface as a loud failure
    # rather than as a quietly discounted shipment.
    base_floor, base_high, _, _ = _floor_for(deterministic_only)
    if floor < base_floor:
        raise AssertionError(
            "model-derived finding lowered the risk floor "
            f"({base_floor} -> {floor}); a model must only ever raise it"
        )

    return {
        "risk_floor": floor,
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
        "hs_description_checked": hs_verdict is not None,
        "zero_day_checked": zero_day is not None,
        "sanctions_screening": (screening or {}).get("status"),
        "sanctions_snapshot": (screening or {}).get("snapshot") or {},
        "hs_floor_effect": {
            "floor_without_model": base_floor,
            "floor_with_model": floor,
            "raised_by": floor - base_floor,
            "high_severity_without_model": base_high,
            "findings_added": [f["code"] for f in model_findings],
        },
        "checks_run": [
            "whitelist", "blacklist", "low_value_domestic",
            "freight_ratio", "value_density", "mandatory_fields",
            "hs_code", "routing", "counterparty",
        ]
        + (["sanctions_screening"] if screening is not None else [])
        + (["hs_description_consistency"] if hs_verdict is not None else [])
        + (["zero_day_adverse_media"] if zero_day is not None else []),
    }


def _floor_for(findings: list[dict[str, Any]]) -> tuple[int, int, bool, bool]:
    """
    The floor arithmetic, factored out so it can be run on two finding sets.

    Returns (floor, high_severity_count, auto_clear, auto_reject).
    """
    auto_clear = any(f.get("auto_clear_by_rules") for f in findings)
    auto_reject = any(f.get("auto_reject_by_rules") for f in findings)

    if auto_reject:
        floor = 100
    elif auto_clear and not any(
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

    return min(floor, 100), high_count, auto_clear, auto_reject


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
# Pre-filter Rules API
# --------------------------------------------------------------------------
#
# Pure functions over a PrefilterRules value. Neither one touches module state,
# which is the whole change: update_prefilter_rules() used to rebind the five
# globals with `global`, so the last tenant to save their rules decided what
# every tenant's shipments were screened against until the next container start.
#
# Persistence is the caller's job (app.py reads and writes the per-tenant copy
# through the store). Keeping it out of here means the rule arithmetic stays
# synchronous and testable without a store, and there is no import cycle.


def serialise_prefilter_rules(rules: PrefilterRules | None = None) -> dict[str, Any]:
    """The rule set in wire form, for display and for storage."""
    return (rules or PrefilterRules.defaults()).to_dict()


def apply_prefilter_update(
    current: PrefilterRules, patch: dict[str, Any]
) -> tuple[PrefilterRules | None, list[str]]:
    """
    Validate a partial rule update and return the new rule set.

    Returns `(rules, [])` on success and `(None, errors)` on failure. All or
    nothing on purpose: the previous version applied each valid key as it went
    and returned the errors afterwards, so a request with one bad key left the
    tenant with a half-applied rule set and an error response that looked like
    nothing had happened.

    A key that is absent from `patch` is left as it was, which is what makes the
    governance screen able to edit one list without resubmitting the other four.
    """
    errors: list[str] = []
    fields: dict[str, Any] = {}

    if "vip_registry" in patch:
        items = patch["vip_registry"]
        if not isinstance(items, list):
            errors.append("vip_registry must be a list of {company, tax_id}")
        else:
            # A dict collapses duplicate companies to the last one supplied,
            # which is the documented behaviour and stops one company holding
            # two different tax IDs -- the state check_whitelist() reads as an
            # identity mismatch against itself.
            registry: dict[str, str] = {}
            for entry in items:
                if not isinstance(entry, dict) or not entry.get("company"):
                    errors.append(
                        "vip_registry entries must each have a non-empty 'company'"
                    )
                    break
                company = _normalize(entry.get("company"))
                if company:
                    registry[company] = str(entry.get("tax_id") or "").strip()
            else:
                fields["vip_registry"] = tuple(registry.items())

    if "blacklist_companies" in patch:
        items = patch["blacklist_companies"]
        if isinstance(items, list):
            fields["blacklist_companies"] = frozenset(
                _normalize(c) for c in items if c
            )
        else:
            errors.append("blacklist_companies must be a list")

    if "blacklist_tax_ids" in patch:
        items = patch["blacklist_tax_ids"]
        if isinstance(items, list):
            fields["blacklist_tax_ids"] = frozenset(
                str(t).strip() for t in items if t
            )
        else:
            errors.append("blacklist_tax_ids must be a list")

    if "safe_routes" in patch:
        routes = patch["safe_routes"]
        if isinstance(routes, list):
            fields["safe_routes"] = frozenset(
                (_normalize(r["origin"]), _normalize(r["destination"]))
                for r in routes
                if isinstance(r, dict) and "origin" in r and "destination" in r
            )
        else:
            errors.append("safe_routes must be a list of {origin, destination}")

    if "low_value_threshold_usd" in patch:
        try:
            threshold = float(patch["low_value_threshold_usd"])
        except (TypeError, ValueError):
            errors.append("low_value_threshold_usd must be a number")
        else:
            if threshold < 0:
                errors.append("low_value_threshold_usd must be non-negative")
            else:
                fields["low_value_threshold_usd"] = threshold

    if errors:
        return None, errors

    return replace(current, **fields), []


def prefilter_diff(
    before: PrefilterRules, after: PrefilterRules
) -> dict[str, Any]:
    """
    What a rule update actually changed.

    Recorded in the audit entry rather than just the submitted payload. The
    payload says what was asked for; this says what moved -- and for a control
    that decides which shipments skip screening entirely, "the blacklist lost an
    entry" is the fact an auditor needs, not "someone POSTed a list".
    """
    diff: dict[str, Any] = {}

    added = set(after.blacklist_companies) - set(before.blacklist_companies)
    removed = set(before.blacklist_companies) - set(after.blacklist_companies)
    if added or removed:
        diff["blacklist_companies"] = {
            "added": sorted(added), "removed": sorted(removed),
        }

    added = set(after.blacklist_tax_ids) - set(before.blacklist_tax_ids)
    removed = set(before.blacklist_tax_ids) - set(after.blacklist_tax_ids)
    if added or removed:
        diff["blacklist_tax_ids"] = {
            "added": sorted(added), "removed": sorted(removed),
        }

    added = set(after.vip_registry) - set(before.vip_registry)
    removed = set(before.vip_registry) - set(after.vip_registry)
    if added or removed:
        diff["vip_registry"] = {
            "added": [{"company": c, "tax_id": t} for c, t in sorted(added)],
            "removed": [{"company": c, "tax_id": t} for c, t in sorted(removed)],
        }

    added = set(after.safe_routes) - set(before.safe_routes)
    removed = set(before.safe_routes) - set(after.safe_routes)
    if added or removed:
        diff["safe_routes"] = {
            "added": [{"origin": o, "destination": d} for o, d in sorted(added)],
            "removed": [{"origin": o, "destination": d} for o, d in sorted(removed)],
        }

    if before.low_value_threshold_usd != after.low_value_threshold_usd:
        diff["low_value_threshold_usd"] = {
            "from": before.low_value_threshold_usd,
            "to": after.low_value_threshold_usd,
        }

    return diff


