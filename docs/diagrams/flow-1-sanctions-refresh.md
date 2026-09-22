# Flow 1 — Weekly sanctions refresh

Cloud Scheduler wakes a job that rebuilds the sanctions index from OpenSanctions,
publishes it to GCS, and measures a Nemotron Super parse against the deterministic
one on a sample.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    participant CS as Cloud Scheduler<br/>(weekly)
    participant RUN as Cloud Run<br/>vf-logistics
    participant OS as OpenSanctions<br/>entities.ftm.json
    participant CODE as parse_deterministic()
    participant SUP as Nemotron Super<br/>(sample only)
    participant GCS as GCS<br/>sanctions/index.json.gz
    participant IDX as sanctions.load()<br/>in-process cache

    CS->>RUN: POST /api/v1/sanctions/refresh<br/>(Cloud Run IAM, no public auth)
    RUN->>OS: GET, streamed
    Note over RUN,OS: httpx.stream + stream_jsonl().<br/>Never materialises the feed:<br/>tens of MB against a 512Mi container.

    loop each record
        OS-->>RUN: one FTM entity
        RUN->>CODE: parse
        CODE-->>RUN: entity, or None if not screenable
        Note right of CODE: Vessels, aircraft, addresses dropped.<br/>An index row screening can never<br/>match costs memory on every lookup.
    end

    rect rgb(245, 245, 235)
        Note over RUN,SUP: Divergence audit — sample only, never the full feed.<br/>USD 0.00089 per record means USD 80 for a 90k feed<br/>against a USD 50 total credit. It is an audit, not a parser.
        loop every Nth record
            RUN->>SUP: the raw record, "extract name/aliases/ids/topics"
            SUP-->>RUN: JSON
            RUN->>RUN: compare() on name, aliases, identifiers, topics
        end
    end

    alt index has entities
        RUN->>GCS: upload gzipped index + meta.divergence
        RUN->>IDX: load(force=True)
    else index is empty
        RUN--xGCS: REFUSE to publish
        Note right of RUN: An empty index answers CLEAN to every<br/>query. Publishing one would clear every<br/>shipment while producing paperwork<br/>saying a check was performed.
    end

    RUN-->>CS: 200 with entity_count, divergence, licence
```

## What the divergence audit found

The first run flagged five records where the model produced identifiers the
deterministic parser had not. The obvious reading was fabrication.

Inspecting the records showed the opposite. They were real FTM `innCode` and
`ogrnCode` values, and `IDENTIFIER_PROPS` did not list either — so the parser was
silently dropping every Russian tax and registration number in the feed. An index
with no INNs answers CLEAN to a shipment declaring one, and nothing about that
failure is visible from outside: the index loads, screening runs, no error appears.

```mermaid
flowchart LR
    A["Model finds an identifier<br/>the code did not"] --> B{"Inspect the<br/>source record"}
    B -->|"the field exists"| C["The PARSER is wrong.<br/>Add the property."]
    B -->|"the field does not exist"| D["The MODEL fabricated.<br/>Discard, do not index."]

    style C fill:#dff0d8,stroke:#3c763d
    style D fill:#f2dede,stroke:#a94442
```

A disagreement means inspect the record. It does not mean distrust the model — and
reading it that way would have shipped the bug and reported "the model fabricates
28% of the time", which was false.

Honest figures after the fix, n=25:

| measure | before | after |
|---|---|---|
| identifier agreement | 0.72 | **0.92** |
| records flagged as invented | 5 / 18 | 2 / 25 |
| topic agreement | 1.00 | 1.00 |
| mean alias Jaccard | 0.78 | 0.82 |

Name agreement reads 0.68, and almost all of it is the model choosing a different
*published* variant — `ROMERO SANCHEZ, Antonio` against `Antonio Romero Sanchez`,
Cyrillic against transliterated Latin. Both forms are in the record. It does not
affect screening because every variant is indexed as an alias.

## Where screening runs

```mermaid
flowchart TD
    S["shipment"] --> N["normalise<br/>shipper_registry._norm_company<br/>_norm_tax_id"]
    N --> L{"index<br/>loaded?"}

    L -->|"no"| U["status UNAVAILABLE<br/>floor 60, HIGH<br/>blocks auto-clear"]
    L -->|"yes"| M{"name or identifier<br/>match?"}

    M -->|"no"| C["status CLEAN<br/>no finding<br/>snapshot still recorded"]
    M -->|"yes"| T{"worst topic"}

    T -->|"sanction"| CR["CRITICAL<br/>floor 100<br/>auto_reject_by_rules"]
    T -->|"export.control<br/>debarment"| H["HIGH<br/>floor 85<br/>human decides"]
    T -->|"sanction.linked"| MD["HIGH<br/>floor 85"]

    style U fill:#fcf8e3,stroke:#8a6d3b
    style CR fill:#f2dede,stroke:#a94442
    style C fill:#dff0d8,stroke:#3c763d
```

`UNAVAILABLE` is a finding, not silence. "We screened and found nothing" and "we
did not screen" are opposite facts, and a system that reports the second as the
first is worse than one with no screening at all — the latter is known to have
none.

Normalisation uses `shipper_registry`'s helpers rather than `verifier._normalize`,
which only lowercases and collapses whitespace. On a sanctions list the near-miss
*is* the technique, and these all have to match:

| declared | matches | via |
|---|---|---|
| `Shell Trading Ltd.` | `Shell Trading Ltd` | punctuation stripped |
| `SHELL TRADING LIMITED` | `Shell Trading Ltd` | legal-form suffix |
| `Shel Trading Ltd` | `Shell Trading Ltd` | filed alias |
| `SheII Trading Ltd` | `Shell Trading Ltd` | homoglyph, capital I for l |
| `Kreshent Marine Services` | `Crescent Marine Services FZE` | transliteration |
| `9999-999-999` | `9999999999` | separators stripped |
