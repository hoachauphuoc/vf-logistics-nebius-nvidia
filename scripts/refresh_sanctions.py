#!/usr/bin/env python3
"""
Weekly sanctions refresh, with a measured comparison between deterministic
parsing and model parsing.

Run
    python scripts/refresh_sanctions.py --limit 5000 --dry-run
    python scripts/refresh_sanctions.py --divergence-sample 40
    python scripts/refresh_sanctions.py            # full refresh, writes GCS

Why both parse paths run
------------------------
The obvious question about this pipeline is whether a language model should be
parsing the sanctions feed at all. OpenSanctions publishes structured JSON, so the
deterministic path is correct by construction and the model can only introduce
error. That argues for code alone.

The counter-argument is that the feed will not always be structured. OFAC publishes
an XML with free-text remarks that hide half the useful signal ("linked to X",
"acting on behalf of Y"), EU consolidated lists arrive as spreadsheets whose column
meanings shift between publications, and national lists arrive as PDFs. On those a
model is the only practical parser.

So the decision was to run both on the same records and measure the gap, rather
than pick one on argument. That produces a number: if the model reproduces the
deterministic result on structured input, it can be trusted on unstructured input
from the same publisher. If it does not, the disagreements say exactly where.

This session already produced a reason to expect disagreement. Told a shipment
declared heading 8543, Nemotron Nano replied that 8543 covers integrated circuits.
It does not -- 8542 does. The model confabulated fluently in the direction of the
input it had been primed with. On a sanctions name the equivalent error means a
designated party passing screening, so the number matters more here than anywhere
else in the system.

What is measured
----------------
For each sampled record, the deterministic parse and the model parse are compared
on four axes:

    name            exact after normalisation -- the field screening keys on
    aliases         Jaccard overlap; a missed alias is a missed evasion
    identifiers     exact set; a hallucinated tax number is worse than none
    topics          exact set; drives the risk tier

Reported per axis and in aggregate, with every disagreement listed. An aggregate
score alone would hide the case that matters: agreement on 39 of 40 records is
reassuring until the fortieth is the one whose name was wrong.
"""

from __future__ import annotations

import argparse
import asyncio
import gzip
import io
import json
import os
import pathlib
import sys
import time
from typing import Any, Iterator

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "src"))

# Sanctions names are Cyrillic, Arabic and Chinese as often as they are Latin, and
# a Windows console defaults to cp1252. Without this the script crashes printing
# the very records it is meant to report on.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from vf_logistics import nebius_client, sanctions, shipper_registry  # noqa: E402

# Newline-delimited FollowTheMoney entities. Chosen over targets.nested.json
# because it streams: the consolidated dataset is tens of megabytes and Cloud Run
# is configured with 512Mi, so a read-then-parse works on a laptop and dies in
# production.
DEFAULT_FEED = os.getenv(
    "SANCTIONS_FEED_URL",
    "https://data.opensanctions.org/datasets/latest/sanctions/entities.ftm.json",
)

# Only these FTM schemas can be a counterparty on a shipment. Vessels, aircraft,
# addresses and sanction-event objects are in the same feed and would bloat the
# index with records screening can never match.
SCREENABLE_SCHEMAS = {"Person", "Company", "Organization", "LegalEntity"}

# Identifier properties on FTM LegalEntity, Person and Organization.
#
# This list started as five names and was wrong, in a way the divergence
# measurement caught and no unit test would have. innCode and ogrnCode were
# missing, so every Russian tax and registration number in the feed was silently
# dropped -- an index with no INNs cannot match a shipment declaring one, and
# nothing about that failure is visible from the outside. The model parse found
# them, the comparison flagged them as "invented by the model", and inspecting
# the actual records showed the model was right and this tuple was wrong.
#
# Worth stating plainly, because the conclusion is the opposite of the one the
# headline number suggested: the first real finding of a measurement built to
# check whether the model could be trusted was a bug in the deterministic path.
IDENTIFIER_PROPS = (
    "taxNumber", "registrationNumber", "idNumber", "vatCode", "leiCode",
    "innCode", "ogrnCode", "okpoCode", "kppCode",
    "dunsCode", "swiftBic", "uniqueEntityId", "bvdId",
)

# Programme references. The feed uses programId far more than program -- checking
# only the latter left every finding reading "no programme stated", which reads as
# missing data rather than as a parser that looked in the wrong field.
PROGRAM_PROPS = ("program", "programId", "sanctionProgram")

SUPER_MODEL = os.getenv(
    "SANCTIONS_DIVERGENCE_MODEL", "nvidia/nemotron-3-super-120b-a12b",
)

EXTRACTION_PROMPT = """\
You are a data extraction engine for a trade-compliance system.

Read the sanctions record below and return ONLY JSON, no commentary:
{
  "name": "the entity's primary name, exactly as published",
  "aliases": ["every other name, spelling or transliteration in the record"],
  "identifiers": ["every tax, registration, VAT or LEI number, digits and all"],
  "topics": ["the classification topics present in the record"],
  "countries": ["ISO country codes present in the record"]
}

Copy values. Do not normalise, translate, expand abbreviations, or infer anything
that is not written in the record. If a field is absent, return an empty list --
an invented identifier is worse than a missing one, because screening will match
on it and the match will be wrong.\
"""


# --------------------------------------------------------------------------
# Deterministic path
# --------------------------------------------------------------------------

def parse_deterministic(record: dict[str, Any]) -> dict[str, Any] | None:
    """
    Parse one FTM record with code. Correct by construction on structured input.

    Returns None for records screening can never match, rather than a degraded
    entry -- an index row with no name is a row that matches nothing and costs
    memory on every lookup.
    """
    if record.get("schema") not in SCREENABLE_SCHEMAS:
        return None

    props = record.get("properties") or {}

    def values(key: str) -> list[str]:
        raw = props.get(key) or []
        if isinstance(raw, str):
            raw = [raw]
        return [str(v).strip() for v in raw if str(v).strip()]

    names = values("name")
    primary = record.get("caption") or (names[0] if names else "")
    if not primary:
        return None

    aliases = []
    for key in ("alias", "name", "weakAlias", "previousName"):
        for value in values(key):
            if value != primary and value not in aliases:
                aliases.append(value)

    identifiers = []
    for key in IDENTIFIER_PROPS:
        for value in values(key):
            if value not in identifiers:
                identifiers.append(value)

    programs = []
    for key in PROGRAM_PROPS:
        for value in values(key):
            if value not in programs:
                programs.append(value)

    return {
        "entity_id": str(record.get("id") or ""),
        "name": primary,
        "aliases": aliases,
        "identifiers": identifiers,
        "programs": programs,
        "topics": values("topics"),
        "countries": values("country") or values("jurisdiction"),
        "source": "opensanctions",
    }


# --------------------------------------------------------------------------
# Model path
# --------------------------------------------------------------------------

async def parse_with_model(
    record: dict[str, Any], model: str = SUPER_MODEL,
) -> tuple[dict[str, Any] | None, dict[str, int], str | None]:
    """
    Parse the same record with Nemotron Super. Returns (parsed, usage, error).

    The whole record goes in rather than a pre-extracted subset, because
    pre-extracting is the deterministic parse -- handing the model only the fields
    code already found would measure nothing.
    """
    text = json.dumps(record, ensure_ascii=False)[:6000]
    try:
        raw, used_in, used_out = await nebius_client.complete_json(
            model=model,
            system_prompt=EXTRACTION_PROMPT,
            user_text=text,
            temperature=0.0,
        )
    except Exception as exc:  # noqa: BLE001
        return None, {"input": 0, "output": 0}, f"{type(exc).__name__}: {exc}"

    usage = {"input": used_in, "output": used_out}

    from vf_logistics.agents._common import parse_model_json

    parsed, error = parse_model_json(raw)
    if error or not isinstance(parsed, dict):
        return None, usage, error or "reply was not an object"
    return parsed, usage, None


# --------------------------------------------------------------------------
# Divergence measurement
# --------------------------------------------------------------------------

def _norm_set(values: Any) -> set[str]:
    out = set()
    for value in values or []:
        key = shipper_registry._norm_company(value)
        if key:
            out.add(key)
    return out


def _id_set(values: Any) -> set[str]:
    out = set()
    for value in values or []:
        key = shipper_registry._norm_tax_id(value)
        if key:
            out.add(key)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def compare(code: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    """
    Compare one record's two parses.

    Names are compared after the same normalisation screening uses, so a
    difference in punctuation or legal-form suffix is not counted as a
    disagreement -- the index would match either spelling. Only a difference that
    would change a screening outcome counts.
    """
    code_name = shipper_registry._norm_company(code.get("name"))
    model_name = shipper_registry._norm_company(model.get("name"))

    code_aliases = _norm_set(code.get("aliases"))
    model_aliases = _norm_set(model.get("aliases"))
    code_ids = _id_set(code.get("identifiers"))
    model_ids = _id_set(model.get("identifiers"))
    code_topics = {str(t).lower() for t in code.get("topics") or []}
    model_topics = {str(t).lower() for t in model.get("topics") or []}

    return {
        "entity_id": code.get("entity_id"),
        "name_agrees": code_name == model_name,
        "code_name": code.get("name"),
        "model_name": model.get("name"),
        "alias_jaccard": round(_jaccard(code_aliases, model_aliases), 4),
        "aliases_missed_by_model": sorted(code_aliases - model_aliases),
        "aliases_invented_by_model": sorted(model_aliases - code_aliases),
        "identifiers_agree": code_ids == model_ids,
        "identifiers_missed_by_model": sorted(code_ids - model_ids),
        # The dangerous direction. A missed identifier means one fewer way to
        # catch a party; an invented one means screening matches an innocent
        # company on a number that was never published.
        "identifiers_invented_by_model": sorted(model_ids - code_ids),
        "topics_agree": code_topics == model_topics,
        "topic_jaccard": round(_jaccard(code_topics, model_topics), 4),
    }


def summarise(comparisons: list[dict[str, Any]]) -> dict[str, Any]:
    n = len(comparisons)
    if not n:
        return {"sampled": 0, "note": "no records compared"}

    invented_ids = [c for c in comparisons if c["identifiers_invented_by_model"]]
    return {
        "sampled": n,
        "name_agreement": round(
            sum(1 for c in comparisons if c["name_agrees"]) / n, 4,
        ),
        "identifier_agreement": round(
            sum(1 for c in comparisons if c["identifiers_agree"]) / n, 4,
        ),
        "topic_agreement": round(
            sum(1 for c in comparisons if c["topics_agree"]) / n, 4,
        ),
        "mean_alias_jaccard": round(
            sum(c["alias_jaccard"] for c in comparisons) / n, 4,
        ),
        "records_with_invented_identifiers": len(invented_ids),
        # Named "invented" because that is the hypothesis, not the conclusion. The
        # first run flagged five records and all five turned out to be real
        # identifiers the deterministic parser was missing, so a disagreement here
        # means "inspect the record", not "the model fabricated".
        "invented_identifier_examples": [
            {
                "entity_id": c["entity_id"],
                "invented": c["identifiers_invented_by_model"],
            }
            for c in invented_ids[:5]
        ],
        "disagreements": [
            {
                "entity_id": c["entity_id"],
                "code_name": c["code_name"],
                "model_name": c["model_name"],
                "alias_jaccard": c["alias_jaccard"],
            }
            for c in comparisons
            if not c["name_agrees"] or c["alias_jaccard"] < 0.8
        ][:20],
    }


# --------------------------------------------------------------------------
# Feed
# --------------------------------------------------------------------------

def iter_feed(url: str, limit: int | None) -> Iterator[dict[str, Any]]:
    """Stream the feed. Never materialises the whole dataset."""
    seen = 0
    with httpx.stream("GET", url, timeout=120.0, follow_redirects=True) as response:
        response.raise_for_status()
        for record in sanctions.stream_jsonl(response.iter_lines()):
            yield record
            seen += 1
            if limit and seen >= limit:
                return


def iter_local(path: str, limit: int | None) -> Iterator[dict[str, Any]]:
    seen = 0
    with open(path, encoding="utf-8") as fh:
        for record in sanctions.stream_jsonl(fh):
            yield record
            seen += 1
            if limit and seen >= limit:
                return


# --------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------

async def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--feed", default=DEFAULT_FEED)
    ap.add_argument("--local", help="read from a local JSONL file instead")
    ap.add_argument("--limit", type=int, default=0, help="0 means no limit")
    ap.add_argument(
        "--divergence-sample", type=int, default=0,
        help="how many records to also parse with Nemotron Super (costs money)",
    )
    ap.add_argument("--model", default=SUPER_MODEL)
    ap.add_argument(
        "--dry-run", action="store_true",
        help="build and report but do not write GCS or Firestore",
    )
    ap.add_argument("--out", help="also write the built index to this local path")
    args = ap.parse_args()

    limit = args.limit or None
    started = time.monotonic()

    source = iter_local(args.local, limit) if args.local else iter_feed(args.feed, limit)

    entities: list[dict[str, Any]] = []
    sampled: list[dict[str, Any]] = []
    read = skipped = 0

    # Every Nth record, so the sample spans the feed rather than the first page of
    # it. The feed is roughly grouped by source, so the first N records are all
    # from one publisher and would measure one format.
    stride = 0
    if args.divergence_sample and limit:
        stride = max(1, limit // args.divergence_sample)

    for record in source:
        read += 1
        parsed = parse_deterministic(record)
        if parsed is None:
            skipped += 1
            continue
        entities.append(parsed)
        if stride and len(sampled) < args.divergence_sample and read % stride == 0:
            sampled.append(record)
        elif not stride and args.divergence_sample and len(sampled) < args.divergence_sample:
            sampled.append(record)

    print(f"read {read} records, kept {len(entities)}, skipped {skipped} "
          f"non-screenable in {time.monotonic() - started:.1f}s")

    divergence: dict[str, Any] = {"sampled": 0, "note": "not measured"}
    cost = {"input": 0, "output": 0, "usd": 0.0, "errors": 0}

    if sampled:
        print(f"\ncomparing {len(sampled)} records against {args.model} ...")
        comparisons = []
        for i, record in enumerate(sampled, 1):
            code = parse_deterministic(record)
            if code is None:
                continue
            model_parse, usage, error = await parse_with_model(record, args.model)
            cost["input"] += usage["input"]
            cost["output"] += usage["output"]
            if error or model_parse is None:
                cost["errors"] += 1
                print(f"  [{i}/{len(sampled)}] {code['entity_id']}: {error}")
                continue
            comparisons.append(compare(code, model_parse))
            if i % 10 == 0:
                print(f"  [{i}/{len(sampled)}] ...")

        from vf_logistics import lineage
        cost["usd"] = round(
            lineage.cost_usd(args.model, cost["input"], cost["output"]), 6,
        )
        divergence = summarise(comparisons)
        divergence["model"] = args.model
        divergence["cost"] = cost

        print("\n=== divergence: deterministic parse vs model parse ===")
        for key in (
            "sampled", "name_agreement", "identifier_agreement",
            "topic_agreement", "mean_alias_jaccard",
            "records_with_invented_identifiers",
        ):
            print(f"  {key:<36} {divergence.get(key)}")
        print(f"  {'cost_usd':<36} {cost['usd']}")
        if divergence.get("invented_identifier_examples"):
            print("\n  IDENTIFIERS THE MODEL FOUND AND THE CODE DID NOT:")
            print("    (check the records before concluding the model invented")
            print("     them -- the first run of this comparison flagged five,")
            print("     and all five were real innCode/ogrnCode values that")
            print("     IDENTIFIER_PROPS was missing)")
            for example in divergence["invented_identifier_examples"]:
                print(f"    {example['entity_id']}: {example['invented']}")
        if divergence.get("disagreements"):
            print("\n  name or alias disagreements:")
            for d in divergence["disagreements"][:8]:
                print(f"    {d['entity_id']}")
                print(f"      code:  {d['code_name']}")
                print(f"      model: {d['model_name']}  (alias J={d['alias_jaccard']})")

    from vf_logistics.store import utcnow

    payload = {
        "meta": {
            "version": int(time.time()),
            "synced_at": utcnow(),
            "source": "opensanctions",
            "entity_count": len(entities),
            "records_read": read,
            "records_skipped": skipped,
            "feed": args.local or args.feed,
            "divergence": divergence,
            # Recorded on the index itself so a consumer can see the licence
            # without reading this script. OpenSanctions bulk data is CC-BY-NC:
            # fine for evaluation, not for a paid product.
            "licence": "CC-BY-NC-4.0 (OpenSanctions) -- non-commercial use only",
        },
        "entities": entities,
    }

    if args.out:
        out_path = pathlib.Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )
        print(f"\nwrote {args.out}")

    if args.dry_run:
        print("\n--dry-run: nothing written to GCS or Firestore")
        return 0

    if not entities:
        # Refusing to publish an empty index is the same fail-closed rule as
        # sanctions.load(). An empty index answers CLEAN to every query.
        print("\nREFUSING to publish: the built index has no entities", file=sys.stderr)
        return 1

    bucket = sanctions.INDEX_BUCKET
    if not bucket:
        print("\nSANCTIONS_INDEX_BUCKET is unset; nothing to publish to", file=sys.stderr)
        return 1

    from google.cloud import storage

    blob = storage.Client().bucket(bucket).blob(sanctions.INDEX_OBJECT)
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as gz:
        gz.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    blob.upload_from_string(buffer.getvalue(), content_type="application/gzip")
    print(f"\npublished {len(entities)} entities to "
          f"gs://{bucket}/{sanctions.INDEX_OBJECT}")

    sanctions.load(force=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
