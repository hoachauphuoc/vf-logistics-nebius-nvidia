"""
Parsers for the two official sanctions lists the production index is built from.

Why these two, and not OpenSanctions
------------------------------------
The index used to be built from the OpenSanctions consolidated feed, whose bulk
data is licensed CC-BY-NC: fine for evaluation, not for a product anyone pays for.
These are the primary publications that feed aggregates:

  * OFAC's Specially Designated Nationals list, published by the US Treasury as
    three CSV files (sdn.csv, alt.csv for aliases, add.csv for addresses).
  * The UN Security Council Consolidated List, published as one XML file.

Both are published by the designating authority for anyone to screen against, so
the index no longer carries a non-commercial licence, and a finding can name the
authority that designated the party rather than an aggregator's id.

What is kept, and what is not
-----------------------------
Only records that can be a counterparty on a shipment: entities and individuals.
OFAC vessels and aircraft are skipped, as the FTM path skipped them -- a vessel is
not a shipper, and an index row that can never match costs memory on every lookup.

Aliases shorter than MIN_ALIAS_CHARS after normalisation are dropped. Matching is
exact on a normalised name, and a three-letter acronym such as an alias "ADF" would
hold every shipment from any company whose name normalises to it -- a false
positive on a sanctions screen is a held cargo, not a warning.

Identifiers come from OFAC's free-text remarks, where they are written as
"Tax ID No. 7702070139 (Russia)" and similar. Only the labelled forms in
IDENTIFIER_LABELS are taken; a number with no label next to it is not evidence of
anything. The UN list carries no company identifiers in a screenable form.
"""

from __future__ import annotations

import csv
import io
import re
import xml.etree.ElementTree as ET
from typing import Any, Iterable, Iterator

from vf_logistics import shipper_registry

OFAC_SDN_URL = "https://www.treasury.gov/ofac/downloads/sdn.csv"
OFAC_ALT_URL = "https://www.treasury.gov/ofac/downloads/alt.csv"
OFAC_ADD_URL = "https://www.treasury.gov/ofac/downloads/add.csv"
UN_CONSOLIDATED_URL = "https://scsanctions.un.org/resources/xml/en/consolidated.xml"

# OFAC writes "-0-" for an empty field.
_EMPTY = "-0-"

# SDN_Type values. Entities have no type at all ("-0-").
_SKIPPED_OFAC_TYPES = {"vessel", "aircraft"}

MIN_ALIAS_CHARS = 6

# Labels OFAC uses in remarks for identifiers a shipment can also carry.
IDENTIFIER_LABELS = (
    "Tax ID No.",
    "Registration Number",
    "Registration ID",
    "Business Registration Number",
    "Business Number",
    "Company Number",
    "V.A.T. Number",
    "VAT Number",
    "Unified Social Credit Code (USCC)",
    "Government Gazette Number",
    "Commercial Registry Number",
    "Enterprise Number",
    "Trade License No.",
    "Legal Entity Number",
)
_ID_RE = re.compile(
    r"(?:" + "|".join(re.escape(label) for label in IDENTIFIER_LABELS) + r")\s+([A-Za-z0-9][A-Za-z0-9./\-]{3,40})"
)


def _clean(value: str | None) -> str:
    text = (value or "").strip()
    return "" if text == _EMPTY else text


def _alias_usable(alias: str) -> bool:
    return len(shipper_registry._norm_company(alias).replace(" ", "")) >= MIN_ALIAS_CHARS


def _ofac_person_name(raw: str) -> str:
    """OFAC writes individuals as "LAST, First Middle"; screening sees "First Middle LAST"."""
    if "," not in raw:
        return raw
    last, _, given = raw.partition(",")
    return f"{given.strip()} {last.strip()}".strip()


def _rows(text: str) -> Iterator[list[str]]:
    for row in csv.reader(io.StringIO(text)):
        # The published files end with a single SUB (0x1A) byte on its own line.
        if row and row[0].strip() and row[0].strip() != "\x1a":
            yield row


def parse_ofac(sdn_csv: str, alt_csv: str = "", add_csv: str = "") -> list[dict[str, Any]]:
    """
    The SDN list as index rows.

    Columns, per OFAC's published layout: sdn.csv is ent_num, SDN_Name, SDN_Type,
    Program, Title, Call_Sign, Vess_type, Tonnage, GRT, Vess_flag, Vess_owner,
    Remarks; alt.csv is ent_num, alt_num, alt_type, alt_name, alt_remarks; add.csv
    is ent_num, add_num, address, city_state, country, add_remarks.
    """
    aliases: dict[str, list[str]] = {}
    for row in _rows(alt_csv):
        if len(row) < 4:
            continue
        name = _clean(row[3])
        if name:
            aliases.setdefault(row[0].strip(), []).append(name)

    countries: dict[str, list[str]] = {}
    for row in _rows(add_csv):
        if len(row) < 5:
            continue
        country = _clean(row[4])
        if country:
            bucket = countries.setdefault(row[0].strip(), [])
            if country not in bucket:
                bucket.append(country)

    out: list[dict[str, Any]] = []
    for row in _rows(sdn_csv):
        if len(row) < 12:
            continue
        ent_num = row[0].strip()
        kind = _clean(row[2]).lower()
        if kind in _SKIPPED_OFAC_TYPES:
            continue
        raw_name = _clean(row[1])
        if not ent_num or not raw_name:
            continue

        individual = kind == "individual"
        name = _ofac_person_name(raw_name) if individual else raw_name
        names = [a for a in aliases.get(ent_num, []) if _alias_usable(a)]
        if individual:
            names = [_ofac_person_name(a) for a in names]
            if raw_name != name and _alias_usable(raw_name):
                names.append(raw_name)

        remarks = _clean(row[11])
        identifiers: list[str] = []
        for match in _ID_RE.finditer(remarks):
            value = match.group(1).rstrip(".;,")
            if value not in identifiers:
                identifiers.append(value)

        programs = re.findall(r"\[([^\]]+)\]", row[3]) or [p for p in [_clean(row[3])] if p]

        out.append({
            "entity_id": f"OFAC-SDN-{ent_num}",
            "name": name,
            "aliases": _dedupe(names, exclude=name),
            "identifiers": identifiers,
            "programs": programs,
            "topics": ["sanction"],
            "countries": countries.get(ent_num, []),
            "kind": "person" if individual else "entity",
            "source": "ofac_sdn",
        })
    return out


def parse_un(xml_bytes: bytes) -> tuple[list[dict[str, Any]], str | None]:
    """The UN Security Council Consolidated List as index rows, plus its generation date."""
    root = ET.fromstring(xml_bytes)
    generated = root.attrib.get("dateGenerated")
    out: list[dict[str, Any]] = []

    for group, tag, alias_tag, kind in (
        ("INDIVIDUALS", "INDIVIDUAL", "INDIVIDUAL_ALIAS", "person"),
        ("ENTITIES", "ENTITY", "ENTITY_ALIAS", "entity"),
    ):
        holder = root.find(group)
        if holder is None:
            continue
        for record in holder.findall(tag):
            reference = (record.findtext("REFERENCE_NUMBER") or "").strip()
            parts = [
                (record.findtext(f) or "").strip()
                for f in ("FIRST_NAME", "SECOND_NAME", "THIRD_NAME", "FOURTH_NAME")
            ]
            name = " ".join(p for p in parts if p)
            if not reference or not name:
                continue

            aliases = []
            for alias in record.findall(alias_tag):
                value = (alias.findtext("ALIAS_NAME") or "").strip()
                if value and _alias_usable(value):
                    aliases.append(value)

            countries = []
            for path in ("NATIONALITY/VALUE", f"{tag}_ADDRESS/COUNTRY"):
                for node in record.findall(path):
                    value = (node.text or "").strip()
                    if value and value not in countries:
                        countries.append(value)

            out.append({
                "entity_id": f"UN-{reference}",
                "name": name,
                "aliases": _dedupe(aliases, exclude=name),
                "identifiers": [],
                "programs": [p for p in [(record.findtext("UN_LIST_TYPE") or "").strip()] if p],
                "topics": ["sanction"],
                "countries": countries,
                "kind": kind,
                "source": "un_sc_consolidated",
            })
    return out, generated


def _dedupe(values: Iterable[str], exclude: str = "") -> list[str]:
    seen: set[str] = {shipper_registry._norm_company(exclude)} if exclude else set()
    out = []
    for value in values:
        key = shipper_registry._norm_company(value)
        if key and key not in seen:
            seen.add(key)
            out.append(value)
    return out
