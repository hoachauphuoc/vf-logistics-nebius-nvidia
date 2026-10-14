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

Environment: `BASE` (default the production console), `REVIEWER_EMAIL`, `JUDGE_EMAIL`,
`SKIP_SEED=1` with `CASE_IDS=a,b` to reuse existing cases, `SLOW_MS` for model-bound steps,
`CHROME_PATH` for a specific browser.

It spends real model tokens and publishes two real Pub/Sub messages (one release, one
block) on the target deployment. Passwords are read from the environment and never printed.
