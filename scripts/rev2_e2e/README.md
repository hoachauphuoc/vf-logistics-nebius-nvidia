# Rev2 end-to-end re-test (deployed console)

Drives two plywood cases through the verification loop in a real browser: a reviewer
requests documents, an anonymous shipper uploads them through the per-document links,
the reviewer re-evaluates and decides (A: release, B: block). The judge account is used
only to inject the two shipments through the API.

    cd scripts/rev2_e2e
    npm install && node gen.mjs          # installs playwright-core, writes docs/*.pdf
    export E2E_JUDGE_PASSWORD=... E2E_REVIEWER_PASSWORD=...
    node run.mjs                         # writes results/summary.json and screenshots
    node api.mjs show <case-id> ...      # read a case back without a browser

Cases are named `CASE-<shipment id>`. The script is given shipment ids (and `CASE_IDS` may carry
either form); lookups and the `/cases/<id>` page use the `CASE-` name, taken from the seed
response when it is there. Using the bare shipment id was a 404 on the first check.

`negative.mjs` covers what the happy path cannot, with plain requests and no browser. It is
written against the behaviour in the code and has been run only against a local stand-in for the
console (its mechanics), not against a deployment:

    CLOSED_CASES=CASE-REV2-E2E-A-123,CASE-REV2-E2E-B-123 node negative.mjs   # no model spend
    RUN_S1=1 node negative.mjs                                               # also S1: one model extraction

S2 re-evaluate on released/blocked cases (409, case untouched; 404; 401), S3 forged/missing evidence
links (403), S4 a one-click session at approve/execute (403; skipped when the guest door is closed),
S1 one of three documents then re-evaluate (request stays open, `missing`, approve is a 409,
cancel, then a release with no note is a 400). S1 seeds a case and leaves it held; nothing is
executed, so no Pub/Sub message. Results go to `results/negative-summary.json`.

Environment: `BASE` (default the production console), `REVIEWER_EMAIL`, `JUDGE_EMAIL`,
`SKIP_SEED=1` with `CASE_IDS=a,b` to reuse existing cases, `SLOW_MS` for model-bound steps,
`CHROME_PATH` for a specific browser.

It spends real model tokens and publishes two real Pub/Sub messages (one release, one
block) on the target deployment. Passwords are read from the environment and never printed.
