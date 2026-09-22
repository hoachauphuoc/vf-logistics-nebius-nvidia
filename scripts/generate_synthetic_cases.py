#!/usr/bin/env python3
"""
Generate the synthetic benchmark corpus.

Run
    python scripts/generate_synthetic_cases.py                 # 1000 cases
    python scripts/generate_synthetic_cases.py --count 200 --seed 7

Composition, per the specification: 30% shell companies routed through
UAE/Turkey/Singapore/Hong Kong, 30% HS-code mismatch, 20% sanctions alias evasion,
20% clean.

Why every case carries an explicit label
----------------------------------------
Each case records `expected_flagged`, `expected_codes` and `attack` -- what the
system SHOULD conclude and why. Without that a benchmark measures agreement with
itself: you learn what the pipeline did, not whether it was right, and a run where
everything is flagged scores identically to a run where everything is correct.

Why the clean cases are the hardest part to write
-------------------------------------------------
Generating suspicious shipments is easy and nearly worthless on its own. A system
that flags everything catches every attack, so recall alone cannot distinguish a
working detector from a broken one -- only the false-positive rate can, and that
requires clean traffic that genuinely resembles the attacks.

So the clean 20% deliberately carries individual features that look bad in
isolation: high-value electronics, transit through Singapore and Dubai, first-time
shippers, air freight ratios. Each is legitimate in combination. If those trip the
pipeline, the precision number says so, and a precision number measured against
easy clean cases would not.

The attacks are drawn from the real techniques
----------------------------------------------
Two are grounded in work already done in this project rather than invented:

  HS mismatch      uses the substitutions in data/hs_pairs.yaml and
                   data/hs_holdout.yaml, where the holdout set was built
                   specifically to contain substitutions the reference table has
                   never seen.

  alias evasion    uses the alias variants in sanctions_seed.json -- typosquats,
                   homoglyphs (capital I for lowercase l), transliteration
                   variants, legal-form suffix swaps. These are the near-misses an
                   exact-match filter lets through, which is the entire technique.

Determinism
-----------
Seeded, and the seed is written into the output. A benchmark whose corpus changes
between runs cannot tell an improvement from a reshuffle.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys
from typing import Any

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import yaml  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEED_INDEX = ROOT / "src" / "vf_logistics" / "data" / "sanctions_seed.json"

DEFAULT_OUT = DATA / "synthetic_test_cases.json"

# The four buckets, as fractions. Kept as a dict so the generator reports what it
# actually produced rather than what was asked for -- an off-by-one in rounding
# would otherwise silently change the denominator of every rate in the report.
MIX = {
    "shell_company": 0.30,
    "hs_mismatch": 0.30,
    "alias_evasion": 0.20,
    "clean": 0.20,
}

# Transshipment hubs named in the specification. These are real diversion routes,
# and verifier.DIVERSION_HUBS already knows them -- reused rather than restated so
# a change to the detector's list does not silently stop the corpus exercising it.
HUBS = [
    ("Jebel Ali, UAE", "United Arab Emirates"),
    ("Dubai, UAE", "United Arab Emirates"),
    ("Mersin, Turkey", "Turkey"),
    ("Istanbul, Turkey", "Turkey"),
    ("Singapore", "Singapore"),
    ("Hong Kong", "Hong Kong"),
]

# Where a diverted shipment is actually going. The declared destination is the hub;
# these appear in the route text, which is how the deception is detectable at all.
FINAL_DESTINATIONS = [
    "Bandar Abbas, Iran", "Tehran, Iran", "Moscow, Russia",
    "Vladivostok, Russia", "Minsk, Belarus", "Damascus, Syria",
    "Pyongyang, North Korea",
]

ORIGINS_EU_US = [
    ("Hamburg, Germany", "Germany"), ("Rotterdam, Netherlands", "Netherlands"),
    ("Antwerp, Belgium", "Belgium"), ("Los Angeles, USA", "USA"),
    ("Newark, USA", "USA"), ("Milan, Italy", "Italy"),
]

# City-level origins for the clean bucket.
#
# Needed because the attack generators wrote "Los Angeles, USA" into `origin` while
# the clean generator wrote the bare country, so `origin` separated the two classes
# on formatting. Same type confusion as the destination field had: a place field
# has to hold places of the same granularity everywhere, or the granularity itself
# becomes the label.
# Origins for the attack buckets. Includes the Asian export hubs the clean bucket
# uses, because restricting attacks to EU/US ports made origin a separating
# feature: every Los Angeles shipment was an attack and every Vietnamese one was
# clean. Diversion originates wherever the goods are made.
ATTACK_ORIGINS = [
    ("Hamburg, Germany", "Germany"), ("Rotterdam, Netherlands", "Netherlands"),
    ("Antwerp, Belgium", "Belgium"), ("Los Angeles, USA", "USA"),
    ("Milan, Italy", "Italy"),
    ("Ho Chi Minh City, Vietnam", "Vietnam"),
    ("Laem Chabang, Thailand", "Thailand"),
    ("Kobe, Japan", "Japan"), ("Gothenburg, Sweden", "Sweden"),
]

ORIGIN_CITIES = {
    "Vietnam": "Ho Chi Minh City, Vietnam",
    "Thailand": "Laem Chabang, Thailand",
    "Germany": "Hamburg, Germany",
    "Sweden": "Gothenburg, Sweden",
    "Japan": "Kobe, Japan",
    "Italy": "Milan, Italy",
    "USA": "Los Angeles, USA",
    "Belgium": "Antwerp, Belgium",
    "Netherlands": "Rotterdam, Netherlands",
}

# Shell-company name shapes. Deliberately bland: a shell company's name is chosen
# to be forgettable and to survive a search, not to look sinister.
SHELL_PATTERNS = [
    "{a} {b} Trading FZE", "{a} {b} General Trading LLC",
    "{a} {b} Commercial Ltd", "{a}-{b} Enterprises Pte Ltd",
    "{a} {b} International Ltd", "{a} {b} Holdings Ltd",
    "{a} {b} Global DMCC", "{a} {b} Import Export Co",
]
SHELL_A = [
    "Meridian", "Apex", "Vertex", "Summit", "Orion", "Zenith", "Pinnacle",
    "Crescent", "Falcon", "Horizon", "Atlas", "Nexus", "Cobalt", "Sable",
]
SHELL_B = [
    "Pacific", "Continental", "Eastern", "Gulf", "Maritime", "Star", "Delta",
    "Anchor", "Bridge", "Compass", "Harbour", "Keystone",
]

LEGITIMATE_SHIPPERS = [
    ("Mekong Garment Export JSC", "Vietnam", "0312998877"),
    ("Siam Precision Components Ltd", "Thailand", "0105539012345"),
    ("Bavaria Maschinenbau GmbH", "Germany", "DE811234567"),
    ("Nordic Timber Partners AB", "Sweden", "SE556789012301"),
    ("Kyoto Fine Instruments KK", "Japan", "1234567890123"),
    ("Lombardy Textile Mills SpA", "Italy", "IT12345670017"),
    ("Cascade Medical Devices Inc", "USA", "91-1234567"),
    # Belgium and the Netherlands are here because they are in ORIGINS_EU_US, which
    # only the attack buckets drew from. Without a clean shipper in each, those two
    # countries appeared exclusively on attacks and `shipper_country` became a
    # separating feature -- an artefact of which list each generator reached for,
    # not a fact about Antwerp or Rotterdam.
    ("Antwerp Chemical Traders NV", "Belgium", "BE0123456789"),
    ("Rotterdam Bulk Handling BV", "Netherlands", "NL001234567B01"),
]

LEGITIMATE_RECEIVERS = [
    ("Nippon Retail KK", "Japan"), ("Hanseatic Distribution GmbH", "Germany"),
    ("Pacific Coast Wholesale Inc", "USA"), ("Sydney Hardware Group Pty", "Australia"),
    ("Seoul Electronics Trading Co", "South Korea"),
    ("Toronto Industrial Supply Ltd", "Canada"),
]

# Destinations are PLACES. Kept separate from LEGITIMATE_RECEIVERS because using
# that list for both put company names in the destination field of the attack
# buckets while the clean bucket held country names -- which made `destination`
# perfectly separate the two classes on a distinction with no meaning. A leak from
# a type confusion in the generator, not from anything about trade.
LEGITIMATE_DESTINATIONS = [
    ("Yokohama, Japan", "Japan"), ("Hamburg, Germany", "Germany"),
    ("Long Beach, USA", "USA"), ("Sydney, Australia", "Australia"),
    ("Busan, South Korea", "South Korea"), ("Vancouver, Canada", "Canada"),
    ("Felixstowe, United Kingdom", "United Kingdom"),
    ("Gothenburg, Sweden", "Sweden"), ("Genoa, Italy", "Italy"),
]


def _receiver_in(country: str, rng: random.Random) -> str:
    """A plausible company name for a destination country."""
    matches = [name for name, c in LEGITIMATE_RECEIVERS if c == country]
    return rng.choice(matches) if matches else rng.choice(LEGITIMATE_RECEIVERS)[0]

# Goods that are genuinely high-value and genuinely ordinary. The clean cases need
# to look expensive, because "expensive" on its own must not be a flag.
BENIGN_GOODS = [
    ("6109", "Cotton t-shirts, knitted, 800 cartons", 18_000, 2_400),
    ("8471", "Laptop computers, retail packed, 300 units", 240_000, 900),
    ("9403", "Office chairs, flat packed, 400 units", 32_000, 4_800),
    ("8517", "Mobile telephone handsets, 1200 units", 380_000, 600),
    ("3004", "Packaged pharmaceutical tablets, temperature controlled", 95_000, 750),
    ("8708", "Automotive brake pads, aftermarket, 5000 sets", 58_000, 6_200),
    ("4202", "Leather handbags, 600 pieces", 72_000, 480),
    ("0901", "Roasted coffee beans, 18 tonnes", 64_000, 18_000),
    ("8544", "Insulated copper cable, 12 tonnes", 88_000, 12_000),
    ("9018", "Diagnostic ultrasound probes, 40 units", 310_000, 220),
]


def _load_hs_pairs() -> list[dict[str, Any]]:
    """
    Substitutions from both the dev and holdout sets.

    The holdout set matters more: it was built specifically to contain
    substitutions data/hs_reference.yaml has never seen, so a benchmark that used
    only hs_pairs.yaml would measure recall on cases the reference table was tuned
    against and report a number that does not generalise.

    The two files differ in shape and the difference is meaningful. hs_holdout.yaml
    carries a written `cargo_description` -- the actual sentence a declarant would
    put on a manifest. hs_pairs.yaml carries only `controlled_goods`, which is the
    WCO heading text, so a description has to be built from it. Heading text used
    verbatim as a cargo description would be an unrealistically easy case: no
    declarant writes "turbojets, turbopropellers and other gas turbines" on a
    manifest, and a classifier matching heading text against heading text is not
    doing the job the real one has to do.
    """
    pairs: list[dict[str, Any]] = []
    for name, path in (("pairs", "hs_pairs.yaml"), ("holdout", "hs_holdout.yaml")):
        full = DATA / path
        if not full.exists():
            continue
        loaded = yaml.safe_load(full.read_text(encoding="utf-8")) or {}
        for entry in loaded.get("pairs") or []:
            controlled = str(entry.get("controlled_hs") or "").strip()
            benign = str(entry.get("benign_hs") or "").strip()
            if not controlled or not benign:
                continue
            pairs.append({
                # Declared under the benign heading, which is the evasion.
                "declared_hs": benign,
                "true_hs": controlled,
                "description": str(entry.get("cargo_description") or "").strip(),
                "controlled_goods": str(entry.get("controlled_goods") or "").strip(),
                "obfuscation": entry.get("obfuscation"),
                "set": name,
            })
    return pairs


# Shapes a manifest line actually takes. Used only for hs_pairs.yaml entries, which
# supply heading text rather than a written description.
MANIFEST_TEMPLATES = [
    "{goods}, {qty} units, palletised",
    "{goods} -- {qty} pcs, industrial grade, crated",
    "{goods}, commercial consignment, {qty} units in {cartons} cartons",
    "{goods} for industrial use, {qty} units, export packed",
    "{goods}, {qty} units, new, original manufacturer packaging",
]


def _manifest_line(rng: random.Random, pair: dict[str, Any]) -> str:
    """The cargo description as a declarant would write it."""
    if pair["description"]:
        return pair["description"]

    goods = pair["controlled_goods"]
    # Heading text is a list of alternatives ("turbojets, turbopropellers and
    # other gas turbines"). A declarant names one thing, so take the first and
    # drop the residual "and other ..." tail.
    first = goods.split(",")[0].strip()
    first = first.split(" and other ")[0].strip()
    return rng.choice(MANIFEST_TEMPLATES).format(
        goods=first[:1].upper() + first[1:],
        qty=rng.choice([12, 24, 40, 60, 120, 250, 400]),
        cartons=rng.choice([6, 10, 18, 30]),
    )


def _load_benign_controls() -> list[dict[str, str]]:
    """
    Genuinely benign goods declared under headings adjacent to controlled ones.

    These are the hardest possible clean cases for the HS check, because the
    declared heading is exactly the one an evader would reach for. A classifier that
    flags "Industrial ventilation fans" under 8414 because 8414 is the cover
    heading for 8411 turbines has learnt the wrong thing, and only these cases
    reveal it.
    """
    out = []
    for path in ("hs_pairs.yaml", "hs_holdout.yaml"):
        full = DATA / path
        if not full.exists():
            continue
        loaded = yaml.safe_load(full.read_text(encoding="utf-8")) or {}
        for entry in loaded.get("benign_controls") or []:
            hs = str(entry.get("hs_code") or "").strip()
            description = str(entry.get("cargo_description") or "").strip()
            if hs and description:
                out.append({"hs_code": hs, "cargo_description": description})
    return out


def _load_sanctions_aliases() -> list[dict[str, str]]:
    """Alias variants from the seed index -- the near-misses an exact matcher
    lets through."""
    payload = json.loads(SEED_INDEX.read_text(encoding="utf-8"))
    out = []
    for entity in payload.get("entities") or []:
        for alias in entity.get("aliases") or []:
            out.append({
                "alias": alias,
                "canonical": entity["name"],
                "entity_id": entity["entity_id"],
                "topics": ",".join(entity.get("topics") or []),
            })
    return out


def _shell_name(rng: random.Random) -> str:
    return rng.choice(SHELL_PATTERNS).format(
        a=rng.choice(SHELL_A), b=rng.choice(SHELL_B),
    )


def _base(rng: random.Random, case_id: str) -> dict[str, Any]:
    return {
        "shipment_id": case_id,
        "currency": "USD",
        "incoterm": rng.choice(["FOB", "CIF", "DAP", "EXW"]),
        "transport_mode": rng.choice(["sea", "air"]),
    }


# --------------------------------------------------------------------------
# Generators, one per bucket
# --------------------------------------------------------------------------

def make_shell_company(rng: random.Random, case_id: str) -> dict[str, Any]:
    """
    A newly-incorporated intermediary in a transshipment hub, with the real
    destination visible only in the route text.

    The detectable signals are the combination, not any one field: a company with
    no trading history, a declared destination that is a known diversion hub, a
    final destination in the route that is not the declared one, and a value
    density that does not match the declared goods.
    """
    hub, hub_country = rng.choice(HUBS)
    final = rng.choice(FINAL_DESTINATIONS)
    origin, origin_country = rng.choice(ATTACK_ORIGINS)
    hs, description, value, weight = rng.choice(BENIGN_GOODS)

    # Half declare the hub as the destination, half declare a respectable country
    # and carry the hub in transit only.
    #
    # This split is not decoration. Without it every attack case had a hub city as
    # its destination and every clean case had a country name, so a one-line rule
    # -- "is the destination a hub city?" -- scored near-perfectly on the corpus.
    # The benchmark would then have measured how the corpus was built rather than
    # whether the system detects anything.
    declares_hub = rng.random() < 0.5
    if declares_hub:
        destination, destination_country = hub, hub_country
        route = f"{origin} to {hub}, onward carriage to {final}"
    else:
        destination, destination_country = rng.choice(LEGITIMATE_DESTINATIONS)
        route = (
            f"{origin} to {destination} via {hub}, onward carriage to {final}"
        )

    shipment = _base(rng, case_id)
    shipment.update({
        "origin": origin,
        "destination": destination,
        "shipper_company": rng.choice(LEGITIMATE_SHIPPERS)[0],
        "shipper_name": "Export Desk",
        "shipper_country": origin_country,
        "shipper_tax_id": f"{rng.randint(10**8, 10**9 - 1)}",
        # The tell. A counterparty taking a six-figure consignment on its first
        # transaction is the shape of a pass-through, and it is the one field an
        # incorporation agent cannot fake.
        "shipper_tx_count": rng.choice([0, 0, 1]),
        "receiver_company": _shell_name(rng),
        "receiver_name": _shell_name(rng),
        "receiver_country": destination_country,
        "consignee_name": _shell_name(rng),
        "hs_code": hs,
        "cargo_description": description,
        "declared_value": int(value * rng.uniform(0.9, 1.4)),
        "weight_kg": int(weight * rng.uniform(0.8, 1.2)),
        "route_details": route,
        "transit_points": hub,
        "notes": "Consignee incorporated within the last 90 days",
    })
    shipment["freight_cost"] = int(shipment["declared_value"] * rng.uniform(0.01, 0.04))
    shipment["shipping_cost"] = shipment["freight_cost"]

    return {
        "case_id": case_id,
        "attack": "shell_company_transshipment",
        "expected_flagged": True,
        "expected_codes": ["ROUTE_DIVERSION_HUB", "COUNTERPARTY_NO_HISTORY"],
        "declared_hub_as_destination": declares_hub,
        "notes": (
            f"Routed through {hub}; route text names {final} as the real endpoint. "
            f"Consignee has no trading history. Declared destination is "
            + ("the hub itself." if declares_hub else f"{destination}.")
        ),
        "shipment": shipment,
    }


def make_hs_mismatch(
    rng: random.Random, case_id: str, pairs: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    A controlled item declared under a heading that does not cover it.

    Drawn from hs_pairs.yaml and hs_holdout.yaml so the corpus exercises the
    actual substitutions the classifier was measured on, including the holdout
    substitutions the reference table has never seen.
    """
    pair = rng.choice(pairs)
    description = _manifest_line(rng, pair)
    shipper, shipper_country, tax_id = rng.choice(LEGITIMATE_SHIPPERS)
    origin, origin_country = rng.choice(ATTACK_ORIGINS)

    # Most of these declare an ordinary destination. An HS substitution is a
    # documentation attack, not a routing one, and it works perfectly well on a
    # shipment going somewhere unremarkable -- tying it to a hub destination would
    # have let the benchmark score it on the route instead of on the description.
    if rng.random() < 0.3:
        destination, destination_country = rng.choice(HUBS)
        transit = destination
    else:
        destination, destination_country = rng.choice(LEGITIMATE_DESTINATIONS)
        transit = "none"

    value = rng.randint(40_000, 400_000)
    shipment = _base(rng, case_id)
    shipment.update({
        "origin": origin,
        "destination": destination,
        "shipper_company": shipper,
        "shipper_name": "Export Compliance Desk",
        "shipper_country": origin_country,
        "shipper_tax_id": tax_id,
        "shipper_tx_count": rng.randint(3, 40),
        "receiver_company": _receiver_in(destination_country, rng),
        "receiver_name": "Procurement",
        "receiver_country": destination_country,
        "consignee_name": _receiver_in(destination_country, rng),
        "hs_code": pair["declared_hs"],
        "cargo_description": description,
        "declared_value": value,
        "weight_kg": rng.randint(20, 400),
        "freight_cost": int(value * rng.uniform(0.01, 0.05)),
        "route_details": (
            f"{origin} to {destination}"
            + (f" via {transit}" if transit != "none" else ", direct sailing")
        ),
        "transit_points": transit,
    })
    shipment["shipping_cost"] = shipment["freight_cost"]

    return {
        "case_id": case_id,
        "attack": "hs_code_mismatch",
        "expected_flagged": True,
        "expected_codes": ["HS_DESCRIPTION_MISMATCH"],
        "ground_truth_hs": pair["true_hs"],
        "declared_hs": pair["declared_hs"],
        # Recorded so the report can separate the two. Recall on `holdout` is the
        # number that says whether the reference table generalises; recall on
        # `pairs` is measured against cases it was tuned on.
        "hs_set": pair["set"],
        "obfuscation": pair.get("obfuscation"),
        "notes": (
            f"Goods are {pair['true_hs']} declared as {pair['declared_hs']}."
        ),
        "shipment": shipment,
    }


def make_alias_evasion(
    rng: random.Random, case_id: str, aliases: list[dict[str, str]],
) -> dict[str, Any]:
    """
    A designated party named with a near-miss spelling.

    The point is that the name is close enough to pass a customs officer reading a
    manifest and far enough to miss an exact-match filter. Homoglyphs are the
    sharpest version: `SheII` with two capital I's is visually identical to `Shell`
    in most printed fonts.
    """
    variant = rng.choice(aliases)
    role = rng.choice(["shipper", "receiver", "consignee"])
    hs, description, value, weight = rng.choice(BENIGN_GOODS)
    origin, origin_country = rng.choice(ATTACK_ORIGINS)

    # A designated party can appear on an entirely ordinary route. Pinning these to
    # a hub destination would have made the route, not the name, the separating
    # feature -- and the name is the whole point of this bucket.
    if rng.random() < 0.35:
        destination, destination_country = rng.choice(HUBS)
        transit = destination
    else:
        destination, destination_country = rng.choice(LEGITIMATE_DESTINATIONS)
        transit = "none"

    shipment = _base(rng, case_id)
    shipment.update({
        "origin": origin,
        "destination": destination,
        "hs_code": hs,
        "cargo_description": description,
        "declared_value": int(value * rng.uniform(0.8, 1.3)),
        "weight_kg": int(weight * rng.uniform(0.9, 1.1)),
        "route_details": (
            f"{origin} to {destination}"
            + (f" via {transit}" if transit != "none" else ", direct sailing")
        ),
        "transit_points": transit,
        "shipper_tx_count": rng.randint(2, 25),
    })
    shipment["freight_cost"] = int(shipment["declared_value"] * rng.uniform(0.02, 0.06))
    shipment["shipping_cost"] = shipment["freight_cost"]

    honest_shipper, honest_country, honest_tax = rng.choice(LEGITIMATE_SHIPPERS)
    honest_receiver = _receiver_in(destination_country, rng)

    if role == "shipper":
        shipment.update({
            "shipper_company": variant["alias"],
            "shipper_name": variant["alias"],
            "shipper_country": origin_country,
            "shipper_tax_id": f"{rng.randint(10**8, 10**9 - 1)}",
            "receiver_company": honest_receiver,
            "receiver_name": "Procurement",
            "receiver_country": destination_country,
            "consignee_name": honest_receiver,
        })
    elif role == "receiver":
        shipment.update({
            "shipper_company": honest_shipper,
            "shipper_name": "Export Desk",
            "shipper_country": honest_country,
            "shipper_tax_id": honest_tax,
            "receiver_company": variant["alias"],
            "receiver_name": variant["alias"],
            "receiver_country": destination_country,
            "consignee_name": variant["alias"],
        })
    else:
        shipment.update({
            "shipper_company": honest_shipper,
            "shipper_name": "Export Desk",
            "shipper_country": honest_country,
            "shipper_tax_id": honest_tax,
            "receiver_company": honest_receiver,
            "receiver_name": "Procurement",
            "receiver_country": destination_country,
            "consignee_name": variant["alias"],
        })

    return {
        "case_id": case_id,
        "attack": "sanctions_alias_evasion",
        "expected_flagged": True,
        "expected_codes": ["SANCTIONS_MATCH"],
        "expected_entity_id": variant["entity_id"],
        "alias_used": variant["alias"],
        "canonical_name": variant["canonical"],
        "evaded_role": role,
        "notes": (
            f"{role} declared as \"{variant['alias']}\", a near-miss for the "
            f"designated \"{variant['canonical']}\" ({variant['entity_id']})."
        ),
        "shipment": shipment,
    }


def make_clean(
    rng: random.Random, case_id: str, benign_controls: list[dict[str, str]],
) -> dict[str, Any]:
    """
    Legitimate traffic that resembles the attacks.

    This is the hardest bucket to write and the most important. A detector that
    flags everything scores perfect recall, so only the false-positive rate
    separates a working system from a broken one -- and a false-positive rate
    measured against obviously-benign cases measures nothing.

    Two kinds of hard negative are mixed in:

      route/history   transit through Singapore or Dubai, a first-time shipper,
                      six-figure electronics, an air-freight ratio that would be
                      absurd for sea cargo. Each is ordinary in context.

      adjacent HS     goods from benign_controls, declared under the heading an
                      evader would use as cover. A classifier that flags
                      "Industrial ventilation fans" under 8414 because 8414 hides
                      8411 turbines has learnt the wrong thing, and only these
                      cases reveal it.
    """
    shipper, shipper_country, tax_id = rng.choice(LEGITIMATE_SHIPPERS)
    origin = ORIGIN_CITIES.get(shipper_country, shipper_country)
    dest_city, receiver_country = rng.choice(LEGITIMATE_DESTINATIONS)
    receiver = _receiver_in(receiver_country, rng)

    # A third of clean cases declare goods under a heading adjacent to a controlled
    # one, which is the sharpest test of the HS check's precision.
    adjacent_hs = bool(benign_controls) and rng.random() < 0.35
    if adjacent_hs:
        control = rng.choice(benign_controls)
        hs, description = control["hs_code"], control["cargo_description"]
        value = rng.randint(30_000, 260_000)
        weight = rng.randint(200, 6_000)
    else:
        hs, description, value, weight = rng.choice(BENIGN_GOODS)

    hard_mode = rng.random() < 0.55
    if hard_mode:
        # A legitimate consolidation hub, INCLUDING Jebel Ali. Dubai, Singapore and
        # Hong Kong are among the largest consumer markets and transshipment ports
        # on earth, and the overwhelming majority of cargo moving through them is
        # honest -- which is precisely why diversion uses them. Excluding any hub
        # from the clean set would hand the detector a free separating feature and
        # inflate every number in the report.
        transit_city, transit_country = rng.choice(HUBS)
        # A third of hard negatives are genuine imports INTO the hub, so a hub as
        # the declared destination is not by itself evidence of anything.
        if rng.random() < 0.35:
            receiver, receiver_country = f"{transit_city} Retail Group", transit_country
            destination = transit_city
            route = f"{origin} to {transit_city}, direct sailing"
            transit = "none"
        else:
            destination = dest_city
            route = (
                f"{origin} to {dest_city} with consolidation "
                f"at {transit_city}"
            )
            transit = transit_city
        # Overlaps the attack buckets' range on purpose. Clean cases previously
        # only ever held 0-3 or 8-60 prior shipments, so the values in between
        # appeared exclusively on attacks -- a separating feature created by the
        # generator rather than by anything about the traffic.
        tx_count = rng.randint(0, 7)
        value = int(value * rng.uniform(1.0, 1.6))
    else:
        destination = dest_city
        transit = "none"
        route = f"{origin} to {dest_city}, direct sailing"
        tx_count = rng.randint(4, 60)

    mode = "air" if weight < 1000 and rng.random() < 0.5 else "sea"
    freight = int(value * (rng.uniform(0.04, 0.09) if mode == "air"
                           else rng.uniform(0.03, 0.08)))

    shipment = _base(rng, case_id)
    shipment.update({
        "origin": origin,
        "destination": destination,
        "shipper_company": shipper,
        "shipper_name": "Export Department",
        "shipper_country": shipper_country,
        "shipper_tax_id": tax_id,
        "shipper_tx_count": tx_count,
        "receiver_company": receiver,
        "receiver_name": "Procurement Department",
        "receiver_country": receiver_country,
        "consignee_name": receiver,
        "hs_code": hs,
        "cargo_description": description,
        "declared_value": value,
        "weight_kg": int(weight * rng.uniform(0.9, 1.1)),
        "freight_cost": freight,
        "shipping_cost": freight,
        "transport_mode": mode,
        "route_details": route,
        "transit_points": transit,
    })

    descriptors = []
    if hard_mode:
        descriptors.append(
            f"destination {destination}, transit {shipment['transit_points']}, "
            f"{tx_count} prior shipments, declared USD {value:,}"
        )
    if adjacent_hs:
        descriptors.append(
            f"declared under {hs}, a heading used as cover for controlled goods"
        )

    return {
        "case_id": case_id,
        "attack": None,
        "expected_flagged": False,
        "expected_codes": [],
        # Recorded so the report can give the false-positive rate on the
        # adversarially-similar clean cases separately. That is the number that
        # says whether the system is usable on real traffic, where most shipments
        # have at least one feature that looks odd.
        "hard_negative": hard_mode or adjacent_hs,
        "adjacent_hs_negative": adjacent_hs,
        "notes": (
            "Legitimate shipment, suspicious-looking in isolation: "
            + "; ".join(descriptors)
            if descriptors
            else "Routine legitimate shipment, established shipper."
        ),
        "shipment": shipment,
    }


# --------------------------------------------------------------------------

def generate(count: int, seed: int) -> dict[str, Any]:
    rng = random.Random(seed)
    pairs = _load_hs_pairs()
    aliases = _load_sanctions_aliases()
    benign_controls = _load_benign_controls()

    if not pairs:
        raise SystemExit("no HS pairs found; data/hs_pairs.yaml is required")
    if not aliases:
        raise SystemExit("no sanctions aliases found in the seed index")

    # Largest-remainder so the counts sum to exactly `count`. Reported as produced
    # rather than as requested, because a rounding drift would silently change the
    # denominator of every rate in the report.
    raw = {k: count * v for k, v in MIX.items()}
    counts = {k: int(v) for k, v in raw.items()}
    remainder = count - sum(counts.values())
    for key in sorted(raw, key=lambda k: raw[k] - int(raw[k]), reverse=True):
        if remainder <= 0:
            break
        counts[key] += 1
        remainder -= 1

    cases: list[dict[str, Any]] = []
    index = 0
    for bucket, n in counts.items():
        for _ in range(n):
            index += 1
            case_id = f"SYN-{index:04d}"
            if bucket == "shell_company":
                cases.append(make_shell_company(rng, case_id))
            elif bucket == "hs_mismatch":
                cases.append(make_hs_mismatch(rng, case_id, pairs))
            elif bucket == "alias_evasion":
                cases.append(make_alias_evasion(rng, case_id, aliases))
            else:
                cases.append(make_clean(rng, case_id, benign_controls))

    rng.shuffle(cases)

    hard_negatives = sum(
        1 for c in cases if c["attack"] is None and c.get("hard_negative")
    )
    adjacent_negatives = sum(
        1 for c in cases if c.get("adjacent_hs_negative")
    )
    holdout_hs = sum(1 for c in cases if c.get("hs_set") == "holdout")

    return {
        "meta": {
            "count": len(cases),
            "seed": seed,
            "composition": counts,
            "composition_pct": {
                k: round(100 * v / len(cases), 1) for k, v in counts.items()
            },
            "hard_negatives": hard_negatives,
            "adjacent_hs_negatives": adjacent_negatives,
            "hs_holdout_cases": holdout_hs,
            "hs_pair_sources": sorted({p["set"] for p in pairs}),
            "alias_variants_available": len(aliases),
            "benign_controls_available": len(benign_controls),
            "note": (
                "expected_flagged / expected_codes are the ground truth. Without "
                "them a benchmark measures agreement with itself: a run that "
                "flags everything would score identically to a correct one."
            ),
        },
        "cases": cases,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--count", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=20260920)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    args = ap.parse_args()

    payload = generate(args.count, args.seed)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    meta = payload["meta"]
    print(f"wrote {out} -- {meta['count']} cases, seed {meta['seed']}")
    for bucket, n in meta["composition"].items():
        print(f"  {bucket:<16} {n:>5}  ({meta['composition_pct'][bucket]}%)")
    print(f"  hard negatives   {meta['hard_negatives']:>5}  "
          f"(clean cases that look suspicious in isolation)")
    print(f"  adjacent-HS neg  {meta['adjacent_hs_negatives']:>5}  "
          f"(benign goods under a heading used as cover)")
    print(f"  HS holdout       {meta['hs_holdout_cases']:>5}  "
          f"(substitutions the reference table has never seen)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
