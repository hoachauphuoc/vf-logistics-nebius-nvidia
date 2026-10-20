# Reproducing the N01 fix (review of 2026-10-19)

The review found that two reconciliations of one audit gap, running at the same time, could write two
`publish_decision` rows for one send. The fix gives the row an id derived from the tenant, the case and the
idempotency key, and creates it atomically (`store.add_audit_once`): the second writer is told "already
there". Fix commit: `88182be`. Reviewed commit: `298827f`.

## 1. The tests fail on the reviewed commit and pass on the fix

```
git worktree add ../n01-old 298827f
cp tests/test_publish_audit_concurrent.py tests/test_publish_audit_http_race.py ../n01-old/tests/
cd ../n01-old && PYTHONPATH=src python -m pytest tests/test_publish_audit_concurrent.py tests/test_publish_audit_http_race.py -q
```

Expected at `298827f`: `5 failed, 3 passed`. The failures include two reconciliations leaving two rows, and the
HTTP route (`POST /api/v1/audit/reconcile`, two operators at once) leaving two rows. The same command at `88182be`
or later: `8 passed`.

- `tests/test_publish_audit_concurrent.py`: the function, with both writers made to read "no row yet" first.
- `tests/test_publish_audit_http_race.py`: the HTTP route, two operators, both requests made to read the gap
  before either writes.

## 2. The two stores agree (Firestore emulator)

```
npx firebase-tools@14 emulators:exec --only firestore --project demo-floorline \
  --config infra/emulators/firebase.json "python -m pytest tests/test_store_parity.py -q -k fixed_id"
```

Expected: the fixed-id tests pass on MemoryStore and on FirestoreStore.

## 3. The real Firestore (needs credentials for the project)

```
python scripts/n01_contention_check.py --project <project id> --writers 12
```

Writes to the tenant `n01-contention`, which no board reads, and deletes its rows afterwards. Expected output:
`12 writers, 1 wrote the row, 1 row(s) stored` and `PASS: one writer, one row`. Run on 2026-10-20 against
`vf-fraud-detection-phuochoa` with that result.

## What this does not show

The production route was not called twice at once: that needs a real audit gap on the live board and an
operator password session.
