# Flow 2 — Zero-Day Radar

The sanctions index refreshes weekly. A company designated on Tuesday is invisible
to it until the following Sunday, and that window is exactly when a designated
party is most motivated to ship. This flow covers it by searching recent news —
but only when there is a reason to.

## Sequence

```mermaid
sequenceDiagram
    autonumber
    participant ORC as orchestrator
    participant VER as verifier.validate()
    participant GATE as should_screen()<br/>deterministic
    participant NANO as Nemotron Nano
    participant TAV as Tavily
    participant CHK as check_zero_day()

    ORC->>VER: validate(shipment)
    VER-->>ORC: findings, risk_floor, sanctions_screening

    ORC->>GATE: should_screen(shipment, validation)

    alt no reason to look
        GATE-->>ORC: (False, reason)
        Note over ORC,GATE: Recorded on the case either way.<br/>"We did not search, and here is why"<br/>belongs in an audit trail as much<br/>as a finding does.
    else a risk indicator is present
        GATE-->>ORC: (True, reason)
        ORC->>NANO: shipment + tool schema

        loop up to MAX_TOOL_ROUNDS
            NANO-->>ORC: tool_call(query, search_depth)
            ORC->>TAV: search, topic=news, days=45
            TAV-->>ORC: results + status
            ORC-->>NANO: results, and searched: true/false stated explicitly
        end

        alt the model stopped and answered
            NANO-->>ORC: verdict JSON
        else every round was spent searching
            rect rgb(255, 245, 235)
                ORC->>NANO: same history, tools withdrawn,<br/>"give your verdict now"
                NANO-->>ORC: verdict JSON
                Note over ORC,NANO: Without this the loop exits with no verdict.<br/>It happened on 73 of 93 cases — 78% — billing<br/>for three completions and returning nothing.
            end
        end

        ORC->>ORC: correct searched=true when no search returned OK
        ORC->>CHK: interpret(verdict)
        CHK-->>ORC: finding, upward only
    end
```

## The gate is code, not the model

```mermaid
flowchart TD
    S["shipment + validation"] --> A{"sanctions<br/>status?"}

    A -->|"HIT"| X1["do not screen<br/>already matched on a designation"]
    A -->|"UNAVAILABLE"| X2["do not screen<br/>no 'absent from list' to act on"]
    A -->|"CLEAN"| B{"skip_ai set by<br/>the pre-filter?"}

    B -->|"yes"| X3["do not screen<br/>already resolved"]
    B -->|"no"| C{"any risk<br/>indicator?"}

    C -->|"dual-use HS heading"| Y["SCREEN"]
    C -->|"high-risk destination"| Y
    C -->|"routed via a diversion hub"| Y
    C -->|"no trading history"| Y
    C -->|"none"| X4["do not screen<br/>no indicator present"]

    style Y fill:#dff0d8,stroke:#3c763d
    style X1 fill:#eee,stroke:#999
    style X2 fill:#eee,stroke:#999
    style X3 fill:#eee,stroke:#999
    style X4 fill:#eee,stroke:#999
```

A model deciding when to spend money has a cost bounded only by its own judgement,
and the budget is USD 50 of inference credit. So the decision to spend is code and
the model's autonomy is over the search *query* and the verdict, which is where
judgement helps.

There is a second reason beyond cost. `compliance_agent.py` fires two Tavily
searches on every single shipment, and an unconditional search on clean traffic
produces a stream of irrelevant results the model then has to reason its way past.
On the HS work the false-positive rate went **up** when the model was given more
material to be cautious about. A search that fires when there is a reason produces
evidence; one that always fires produces noise.

Measured on 200 synthetic cases: the gate fired on 73 attacks and 20 clean cases —
78.5% precision, against 46.5% if it fired on everything.

## Verdict to finding, upward only

```mermaid
flowchart TD
    V{"verdict"} -->|"risk_found<br/>confidence >= 0.7"| A["ZERO_DAY_ADVERSE_MEDIA<br/>HIGH, floor 70"]
    V -->|"risk_found<br/>confidence < 0.7"| B["..._LOW_CONFIDENCE<br/>LOW, floor 0"]
    V -->|"no_risk_found<br/>searched true"| C["no finding"]
    V -->|"no_risk_found<br/>searched FALSE"| D["ZERO_DAY_SEARCH_DID_NOT_RUN<br/>MEDIUM, floor 40"]
    V -->|"unknown"| E["ZERO_DAY_CHECK_UNAVAILABLE<br/>LOW, floor 0, recorded"]

    A --> F["floor = max(deterministic, model)"]
    B --> F
    C --> F
    D --> F
    E --> F

    F --> G{"did the model<br/>lower the floor?"}
    G -->|"yes"| H["AssertionError<br/>raised in validate()"]
    G -->|"no"| I["proceed"]

    style A fill:#f2dede,stroke:#a94442
    style D fill:#fcf8e3,stroke:#8a6d3b
    style C fill:#dff0d8,stroke:#3c763d
    style H fill:#f2dede,stroke:#a94442,stroke-width:3px
```

Two properties carry the safety argument.

**A `no_risk_found` verdict produces nothing at all.** It cannot clear a shipment
the deterministic checks flagged. So a model that is mistaken, or manipulated by
text inside the cargo description, changes nothing — and `validate()` proves it on
every call by computing the floor twice, with and without the model's findings, and
raising if the second came out lower.

**`searched` is separate from `risk_found`, and both are required.**
`tavily_client` returns an empty list for a missing API key, a timeout, a 429 and a
genuinely empty result. Collapsing those would clear a shipment on a search that
never ran, so a verdict claiming `searched: true` when no search returned `ok` is
corrected in code rather than trusted — it is the one field whose truth the caller
can check.

A news report is also weaker evidence than a government listing, so the floor is 70
rather than the 85 or 100 a `SANCTIONS_MATCH` carries. The number a reviewer sees
should say which kind of evidence drove the case.

## Cost per shipment

```mermaid
flowchart LR
    A["1000 shipments"] --> B{"deterministic<br/>pre-filter"}
    B -->|"resolved, ~51%"| C["USD 0<br/>no model call"]
    B -->|"needs a model"| D["HS classifier<br/>~USD 0.0003"]
    D --> E{"zero-day<br/>gate"}
    E -->|"fires, ~47%"| F["+ Nano with tools<br/>~USD 0.0006"]
    E -->|"does not fire"| G["no further spend"]

    style C fill:#dff0d8,stroke:#3c763d
```

Measured end to end: **USD 0.89 per 1,000 shipments**, mean latency 31s, p95 76s.
The latency is the cost of two sequential tool rounds on a 30B model, and it is why
the API offers `?async=true` with a webhook rather than holding the connection.
