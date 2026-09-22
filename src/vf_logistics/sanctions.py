"""
Sanctions screening index.

Why this is a deterministic lookup and not a model call
------------------------------------------------------
Sanctions lists are published as structured data. There is nothing to extract,
and running them through a language model would add cost and hallucination risk to
the single highest-stakes dataset in the system. This session produced direct
evidence of the risk: handed "electronic integrated circuits" under a declared
heading of 8543, Nemotron Nano replied that 8543 covers integrated circuits. It
does not -- 8542 does. The model confabulated fluently, in the direction of the
input it was primed with, and "DO NOT hallucinate" in a prompt is not an
enforcement mechanism.

The same failure on an entity name means either a sanctioned party passing
screening or an innocent company being blocked. So the list is parsed by code, and
the model's role is confined to judgements the code cannot make.

Storage shape
-------------
The index is a compressed blob in GCS plus a small versioned metadata document in
Firestore, rather than one document per entity. Three reasons:

  * a weekly refresh of ~100k entities as Firestore writes costs real money every
    week, for data that is identical between refreshes
  * screening runs on every shipment, and a per-shipment Firestore query is a
    network round trip on the hot path; an in-memory dict is not
  * verifier.py's whole design is deterministic checks with no network and no I/O,
    and a lookup that reached out to Firestore would break that

Cloud Run is configured with --memory=512Mi, so the feed is streamed and filtered
line by line and never fully materialised.

Fail-closed
-----------
If the index cannot be loaded, screening returns UNAVAILABLE, never CLEAN. An
empty index would silently clear every shipment -- the exact failure mode that
makes a compliance system worse than no compliance system, because it produces
confident paperwork saying a check was performed.
"""

from __future__ import annotations

import gzip
import json
import os
import pathlib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterator

from vf_logistics import shipper_registry

# Where a built index lives. GCS in production; the local path is the bundled
# fallback so a container without GCS access still screens against something
# rather than silently passing everything.
INDEX_BUCKET = os.getenv("SANCTIONS_INDEX_BUCKET", "")
INDEX_OBJECT = os.getenv("SANCTIONS_INDEX_OBJECT", "sanctions/index.json.gz")

# Under src/ because Dockerfile copies only src/ -- a file in data/ is not in the
# image. See the survey note in the plan.
BUNDLED_INDEX = (
    pathlib.Path(__file__).resolve().parent / "data" / "sanctions_seed.json"
)

# Screening outcomes. Strings so they survive a JSON round trip onto a case.
HIT = "HIT"
CLEAN = "CLEAN"
UNAVAILABLE = "UNAVAILABLE"


@dataclass
class SanctionedEntity:
    """One screenable record, reduced to what matching needs."""
    entity_id: str
    name: str
    programs: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    countries: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    identifiers: list[str] = field(default_factory=list)
    source: str = ""

    def risk_level(self) -> str:
        """
        Derived from the programme, not hardcoded.

        A single hardcoded "HIGH" on every record -- as the original
        specification had it -- makes the field carry no information, and the
        programmes genuinely differ: a full blocking designation is not the same
        obligation as a sectoral restriction or an export-control listing, and a
        compliance officer acts differently on each.
        """
        topics = {t.lower() for t in self.topics}
        if "sanction" in topics:
            return "CRITICAL"
        if "export.control" in topics or "debarment" in topics:
            return "HIGH"
        if "sanction.linked" in topics:
            return "MEDIUM"
        return "HIGH"


class SanctionsIndex:
    """
    Name and identifier lookup over a sanctions snapshot.

    Matching uses shipper_registry's normalisers rather than verifier's. That is
    not a style preference: verifier._normalize only lowercases and collapses
    whitespace, so "Shell Trading Ltd." with a trailing period misses
    "shell trading ltd", and the tax id "0100-107-518" misses "0100107518".
    shipper_registry._norm_company strips punctuation and legal-form suffixes and
    _norm_tax_id strips non-digits. On a sanctions list those near-misses are the
    whole attack: a declarant does not have to spell the name exactly right, only
    close enough to pass and far enough to miss an exact-match filter.
    """

    def __init__(self, meta: dict[str, Any], entities: list[SanctionedEntity]):
        self.meta = meta
        self.entities = entities
        self._by_name: dict[str, list[SanctionedEntity]] = {}
        self._by_identifier: dict[str, list[SanctionedEntity]] = {}

        for entity in entities:
            for raw in [entity.name, *entity.aliases]:
                key = shipper_registry._norm_company(raw)
                if key:
                    self._by_name.setdefault(key, []).append(entity)
            for raw in entity.identifiers:
                key = shipper_registry._norm_tax_id(raw)
                if key:
                    self._by_identifier.setdefault(key, []).append(entity)

    def __len__(self) -> int:
        return len(self.entities)

    @property
    def version(self) -> int:
        return int(self.meta.get("version") or 0)

    @property
    def synced_at(self) -> str | None:
        return self.meta.get("synced_at")

    @property
    def source(self) -> str:
        return str(self.meta.get("source") or "unknown")

    def age_days(self) -> int | None:
        """
        How stale the list is.

        Surfaced on every finding rather than kept internal. A weekly refresh
        means this legitimately reads up to 7, and a consumer who assumes
        currency will over-trust a CLEAN result on an entity designated four days
        ago.
        """
        stamp = self.synced_at
        if not stamp:
            return None
        try:
            when = datetime.fromisoformat(stamp)
        except ValueError:
            return None
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - when).days)

    def snapshot(self) -> dict[str, Any]:
        """Provenance for the case document and the lineage record."""
        return {
            "version": self.version,
            "synced_at": self.synced_at,
            "age_days": self.age_days(),
            "source": self.source,
            "entity_count": len(self.entities),
        }

    def match_name(self, name: str | None) -> list[SanctionedEntity]:
        if not name:
            return []
        return list(self._by_name.get(shipper_registry._norm_company(name), []))

    def match_identifier(self, identifier: str | None) -> list[SanctionedEntity]:
        if not identifier:
            return []
        return list(
            self._by_identifier.get(shipper_registry._norm_tax_id(identifier), [])
        )

    def screen(self, shipment: dict[str, Any]) -> dict[str, Any]:
        """
        Screen every counterparty on a shipment.

        Both the company field and the person-name field are checked for each
        side. Designations name individuals as well as companies, and a
        consignee's named officer being designated is the same exposure as the
        company being designated.
        """
        parties = {
            "shipper": (
                shipment.get("shipper_company"), shipment.get("shipper_name"),
            ),
            "receiver": (
                shipment.get("receiver_company"), shipment.get("receiver_name"),
            ),
            "consignee": (shipment.get("consignee_name"), None),
        }

        matches: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()

        for role, names in parties.items():
            for name in names:
                for entity in self.match_name(name):
                    key = (role, entity.entity_id)
                    if key in seen:
                        continue
                    seen.add(key)
                    matches.append({
                        "role": role,
                        "matched_on": "name",
                        "matched_value": name,
                        "entity_id": entity.entity_id,
                        "entity_name": entity.name,
                        "programs": entity.programs,
                        "topics": entity.topics,
                        "risk_level": entity.risk_level(),
                        "source": entity.source,
                    })

        for role, field_name in (
            ("shipper", "shipper_tax_id"), ("receiver", "receiver_tax_id"),
        ):
            for entity in self.match_identifier(shipment.get(field_name)):
                key = (role, entity.entity_id)
                if key in seen:
                    continue
                seen.add(key)
                matches.append({
                    "role": role,
                    "matched_on": "identifier",
                    "matched_value": shipment.get(field_name),
                    "entity_id": entity.entity_id,
                    "entity_name": entity.name,
                    "programs": entity.programs,
                    "topics": entity.topics,
                    "risk_level": entity.risk_level(),
                    "source": entity.source,
                })

        return {
            "status": HIT if matches else CLEAN,
            "matches": matches,
            "snapshot": self.snapshot(),
        }


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------

_lock = threading.Lock()
_cached: SanctionsIndex | None = None
_load_error: str | None = None
_loaded_at: float = 0.0

# Rebuilt at most this often within one container, so a refresh lands without a
# redeploy but the hot path is not re-reading GCS.
RELOAD_AFTER_SECONDS = float(os.getenv("SANCTIONS_RELOAD_SECONDS", "900"))


def _entities_from_payload(payload: dict[str, Any]) -> list[SanctionedEntity]:
    out = []
    for row in payload.get("entities") or []:
        out.append(SanctionedEntity(
            entity_id=str(row.get("entity_id") or row.get("id") or ""),
            name=str(row.get("name") or ""),
            programs=[str(p) for p in row.get("programs") or []],
            topics=[str(t) for t in row.get("topics") or []],
            countries=[str(c) for c in row.get("countries") or []],
            aliases=[str(a) for a in row.get("aliases") or []],
            identifiers=[str(i) for i in row.get("identifiers") or []],
            source=str(row.get("source") or payload.get("source") or ""),
        ))
    return [e for e in out if e.entity_id and e.name]


def _read_gcs(bucket: str, obj: str) -> dict[str, Any]:
    from google.cloud import storage

    client = storage.Client()
    blob = client.bucket(bucket).blob(obj)
    raw = blob.download_as_bytes()
    if obj.endswith(".gz"):
        raw = gzip.decompress(raw)
    return json.loads(raw.decode("utf-8"))


def _read_bundled() -> dict[str, Any]:
    with open(BUNDLED_INDEX, encoding="utf-8") as fh:
        return json.load(fh)


def load(force: bool = False) -> SanctionsIndex | None:
    """
    The current index, or None with the reason recorded in load_error().

    Returning None rather than an empty index is the load-bearing decision. An
    empty index answers CLEAN to every query, so a failed load would clear every
    shipment while producing paperwork that says a sanctions check was performed.
    """
    global _cached, _load_error, _loaded_at

    with _lock:
        fresh = _cached is not None and (time.monotonic() - _loaded_at) < RELOAD_AFTER_SECONDS
        if fresh and not force:
            return _cached

        payload: dict[str, Any] | None = None
        error: str | None = None

        if INDEX_BUCKET:
            try:
                payload = _read_gcs(INDEX_BUCKET, INDEX_OBJECT)
            except Exception as exc:  # noqa: BLE001 - fall through to the bundle
                error = f"GCS load failed ({type(exc).__name__}: {exc})"

        if payload is None:
            try:
                payload = _read_bundled()
                if error:
                    error = f"{error}; using bundled seed index"
            except Exception as exc:  # noqa: BLE001
                _cached = None
                _load_error = f"{error + '; ' if error else ''}bundled index unreadable ({exc})"
                _loaded_at = time.monotonic()
                return None

        entities = _entities_from_payload(payload)
        if not entities:
            # An index that parsed but holds nothing is treated as a failed load,
            # not as a list on which everyone is clean.
            _cached = None
            _load_error = "index contained no usable entities"
            _loaded_at = time.monotonic()
            return None

        _cached = SanctionsIndex(payload.get("meta") or payload, entities)
        _load_error = error
        _loaded_at = time.monotonic()
        return _cached


def load_error() -> str | None:
    return _load_error


def screen_shipment(shipment: dict[str, Any]) -> dict[str, Any]:
    """
    Screen a shipment, fail-closed.

    Never returns CLEAN when the list could not be read. `reason` carries the
    load error so a reviewer sees why no screening happened instead of seeing an
    absence of matches.
    """
    index = load()
    if index is None:
        return {
            "status": UNAVAILABLE,
            "matches": [],
            "snapshot": {},
            "reason": load_error() or "sanctions index unavailable",
        }
    return index.screen(shipment)


def stream_jsonl(raw: Iterator[bytes | str]) -> Iterator[dict[str, Any]]:
    """
    Parse newline-delimited JSON one record at a time.

    Never builds the whole list. The consolidated OpenSanctions dataset is tens of
    megabytes and Cloud Run is configured with 512Mi, so a .read() followed by a
    json.loads would work on a laptop and die in production.
    """
    for line in raw:
        text = line.decode("utf-8") if isinstance(line, bytes) else line
        text = text.strip()
        if not text:
            continue
        try:
            yield json.loads(text)
        except json.JSONDecodeError:
            # One malformed line must not abort a 100k-record refresh.
            continue
