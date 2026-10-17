#!/usr/bin/env python3
"""
verify_review_vi.py - how much of the independent review of 2026-10-15
(Floorline_Independent_Review_VI) the repository already addresses.

Read-only: it edits no source file. It runs the existing tests that assert the CORRECT
behaviour, a few probes for findings that have no test, and prints one table with a
percentage. It writes orchestrator/runs/verify_review_vi.md and always exits 0, so a
runner records the table instead of stopping at the first open finding.

    python scripts/verify_review_vi.py
    python scripts/verify_review_vi.py --no-frontend      # skip the vitest part
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(os.environ.get("VF_REPO") or Path(__file__).resolve().parent.parent)
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "tests")]

PASS, FAIL, NO_TEST, OUT_OF_SCOPE, SKIP = "PASS", "FAIL", "NO TEST", "OUT OF SCOPE", "SKIP"
ITEMS = ["N01", "N02", "N03", "N04", "N05", "N06", "N07", "N08", "E01"]

# (id, item, what the review asks for, kind, spec)
#   py:    [(test file, test name prefix)]   every match must pass, at least one must exist
#   js:    [test title fragment]             every match must pass, at least one must exist
#   probe: name of a probe function below
#   none:  kind "no_test" or "out_of_scope", spec is the reason
CHECKS = [
    ("N01-a", "N01", "the same idempotency key on every retry", "py",
     [("test_evidence_execution.py", "test_n01_idempotency_key_is_fixed_per_approval")]),
    ("N01-b", "N01", "a resume is refused inside the lease and continues the same execution after it", "py",
     [("test_evidence_execution.py", "test_n01_a_second_person_cannot_resume_inside_the_lease"),
      ("test_evidence_execution.py", "test_n01_a_second_person_can_resume_after_the_lease_expires")]),
    ("N01-c", "N01", "a publish accepted but never confirmed is not published again on resume", "py",
     [("test_resume_after_publish.py", "test_the_resume_does_not_publish_the_decision_again"),
      ("test_publish_dedupe.py", "test_a_second_publish_with_the_same_key_returns_the_first_receipt"),
      ("test_publish_attribute.py", "test_the_idempotency_key_is_sent_as_an_attribute")]),
    ("N01-d", "N01", "an unknown send result is told apart from a send that did not happen", "probe",
     "probe_unknown_publish"),
    ("N01-e", "N01", "deduplication at the receiving system", "none",
     (OUT_OF_SCOPE, "the receiver is not in this repository")),
    ("N02-a", "N02", "a failed send is EXECUTION_FAILED, not completed", "py",
     [("test_evidence_execution.py", "test_a_publish_that_raises_is_a_failed_send_not_a_crash"),
      ("test_evidence_execution.py", "test_a_delegated_publish_that_did_not_happen_is_a_failed_send")]),
    ("N03-a", "N03", "a re-issued link is one typed link per missing document", "py",
     [("test_evidence_request.py", "test_n03_a_new_link_comes_as_one_typed_link_per_document"),
      ("test_evidence_respond.py", "test_a_reissued_link_still_files_each_document_under_its_own_type")]),
    ("N03-b", "N03", "three documents in any order are stored under their own type", "py",
     [("test_evidence_respond.py", "test_three_documents_in_any_order_are_each_stored_as_their_own_type")]),
    ("N04-a", "N04", "a request cancelled before any upload cannot lead to an unevaluated release", "py",
     [("test_evidence_eval_approve.py", "test_request_cancel_then_release_with_an_empty_note_is_refused"),
      ("test_evidence_eval_approve.py", "test_a_note_does_not_stand_in_for_the_missing_evaluation")]),
    ("N04-b", "N04", "a release over missing evidence needs a reason and stores the exception", "py",
     [("test_evidence_eval_approve.py", "test_n04_release_with_unresolved_evidence_needs_a_note"),
      ("test_evidence_eval_approve.py", "test_n04_release_of_that_case_is_an_exception_with_a_recorded_reason")]),
    ("N04-c", "N04", "an exception is its own operation: operator role, password, every waived item named", "py",
     [("test_exception_approval.py", "test_it_records_what_it_waives_and_why"),
      ("test_exception_route.py", "test_a_reviewer_may_not_make_an_exception"),
      ("test_exception_route.py", "test_an_operator_with_a_password_makes_a_recorded_exception")]),
    ("N05-a", "N05", "a closed case, or one that never asked for documents, is not re-evaluated", "py",
     [("test_evidence_eval_approve.py", "test_a_case_outside_the_loop_is_refused_and_left_untouched"),
      ("test_evidence_eval_approve.py", "test_a_case_that_never_asked_for_documents_is_refused_and_not_changed")]),
    ("N06-a", "N06", "placeholder values and missing required fields are not proof", "py",
     [("test_origin_inputs.py", "test_a_placeholder_producer_is_not_a_producer_to_mismatch_against"),
      ("test_origin_inputs.py", "test_a_declaration_that_names_the_producer_but_no_inputs_is_not_proof")]),
    ("N06-b", "N06", "a field naming several countries is not provided", "py",
     [("test_origin_inputs.py", "test_a_certificate_for_two_countries_is_not_provided"),
      ("test_origin_inputs.py", "test_an_invoice_listing_two_countries_is_not_provided")]),
    ("N06-c", "N06", "values of the wrong type (number, object) are not a stated value", "probe",
     "probe_value_types"),
    ("N06-d", "N06", "a partly read paper (pages_read < pages) is not unconditionally provided", "probe",
     "probe_unread_pages"),
    ("N07-a", "N07", "the legacy decide route is closed for any case with a verification record", "py",
     [("test_evidence_eval_approve.py", "test_a_case_with_a_verification_record_cannot_be_released_through_decide"),
      ("test_evidence_eval_approve.py", "test_release_without_a_password_is_refused_on_a_plain_case")]),
    ("N07-b", "N07", "the policy gate tests", "py", [("test_n07_policy_gate.py", "test_")]),
    ("N08-a", "N08", "after a failed first execution the case reloads and Retry appears", "js",
     ["reloads the case when approve-then-execute ends in EXECUTION_FAILED"]),
    ("N08-b", "N08", "an interrupted execution is shown and can be resumed after the lease", "js",
     ["offers Resume, and calls executeApproval with the claimed approval, once the claim has expired",
      "says the execution is interrupted once the lease has expired"]),
    ("N08-c", "N08", "shared links are full addresses, one per document", "js",
     ["shows the per-document links after Request info",
      "shows the request-level link as a full address"]),
    ("N08-d", "N08", "a shipper with no console session can submit a document (it was a 401)", "js",
     ["lets a shipper with no console session reach the API"]),
    ("N08-e", "N08", "nothing is sent before the reviewer confirms (Release, then Cancel)", "js",
     ["sends nothing when the reviewer cancels the confirmation"]),
    ("E01-a", "E01", "changing only the answer label changes the score, not the decision", "probe",
     "probe_e01_label"),
    ("E01-b", "E01", "the output says cost and time are mocked, not measured", "probe",
     "probe_e01_basis"),
]


# ---------------------------------------------------------------------------- runners


def run_pytest(files: list[str]) -> dict[tuple[str, str], str]:
    """{(test file name, test name incl. parameters): PASSED | FAILED | ERROR}."""
    base = Path(tempfile.mkdtemp(prefix="vf_verify_")) / "pt"
    cmd = [sys.executable, "-m", "pytest", *[f"tests/{f}" for f in files], "-q",
           "-p", "no:cacheprovider", "-rA", f"--basetemp={base}"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=900).stdout
    results: dict[tuple[str, str], str] = {}
    for line in out.splitlines():
        m = re.match(r"^(PASSED|FAILED|ERROR) (\S+)", line)
        if m:
            node = m.group(2).replace("\\", "/")
            results[(node.split("::")[0].split("/")[-1], node.split("::")[-1])] = m.group(1)
    return results


def run_vitest() -> dict[str, str] | None:
    """{test title: passed | failed}, or None when the frontend cannot be run here."""
    front = ROOT / "frontend"
    if not (front / "node_modules").exists():
        return None
    outfile = Path(tempfile.mkdtemp(prefix="vf_verify_")) / "vitest.json"
    cmd = (f'npx vitest run src/components/review/ReviewPanel.test.tsx route.test.ts '
           f'--reporter=json --outputFile="{outfile}"')
    try:
        subprocess.run(cmd, shell=True, cwd=front, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=900)
        data = json.loads(outfile.read_text(encoding="utf-8"))
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    titles: dict[str, str] = {}
    for suite in data.get("testResults", []):
        for t in suite.get("assertionResults", []):
            titles[t.get("title", "")] = t.get("status", "")
    return titles


# ------------------------------------------------------------------------------ probes

_ENV = None


def _env() -> dict[str, str]:
    global _ENV
    if _ENV is None:
        from test_evidence_eval_approve import ENV
        _ENV = {**ENV, "PROJECT_ID": "verify-project"}
    return _ENV


def probe_unknown_publish() -> tuple[bool, str]:
    from test_evidence_execution import _fake_pubsub, _with_pubsub
    from vf_logistics import store as store_mod
    from vf_logistics import tools

    with patch.dict(os.environ, _env()):
        store_mod._store = None
        module, _ = _fake_pubsub([TimeoutError("deadline exceeded")])
        with _with_pubsub(module):
            receipt = asyncio.run(tools.publish_decision("CASE-V", {"outcome": "RELEASED_BY_HUMAN"}))
        store_mod._store = None
    status = receipt.get("status")
    return status != "failed", f"a publish that timed out is recorded as '{status}'"


def _origin_documents(**override):
    from test_evidence_eval_approve import PAPERS

    papers = {**PAPERS, **override}
    return [{"doc_type": dt, "extracted": ext} for dt, ext in papers.items()]


def probe_value_types() -> tuple[bool, str]:
    from test_origin_inputs import plywood
    from vf_logistics.verifier import check_origin_evidence

    base = check_origin_evidence(plywood(), _origin_documents())
    if base.get("status") != "provided":
        return False, f"probe baseline is '{base.get('status')}', not provided"
    bad = check_origin_evidence(plywood(), _origin_documents(
        certificate_of_origin={"producer_name": 123, "origin_country": {"name": "Vietnam"}},
    ))
    ok = "certificate_of_origin" in (bad.get("missing") or [])
    return ok, f"a certificate with a number and an object as values gives status '{bad.get('status')}'"


def probe_unread_pages() -> tuple[bool, str]:
    from test_origin_inputs import plywood
    from vf_logistics.verifier import check_origin_evidence

    docs = _origin_documents()
    base = check_origin_evidence(plywood(), docs)
    if base.get("status") != "provided":
        return False, f"probe baseline is '{base.get('status')}', not provided"
    partly_read = [{**d, "pages": 2, "pages_read": 1} for d in docs]
    got = check_origin_evidence(plywood(), partly_read)
    return got.get("status") != "provided", f"three papers read 1 page of 2 give status '{got.get('status')}'"


def _verification_eval():
    path = ROOT / "scripts" / "run_verification_eval.py"
    spec = importlib.util.spec_from_file_location("run_verification_eval", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def probe_e01_label() -> tuple[bool, str]:
    module, _ = _verification_eval()
    cases = json.loads((ROOT / "data" / "verification_cases.json").read_text(encoding="utf-8"))
    spec = next((c for c in cases if c["id"] == "V-FRAUD-01"), None)
    if spec is None:
        return False, "case V-FRAUD-01 not found in data/verification_cases.json"
    flipped = dict(spec, expected_outcome=(
        "RELEASED_BY_HUMAN" if spec["expected_outcome"] != "RELEASED_BY_HUMAN" else "BLOCKED_BY_HUMAN"))
    with patch.dict(os.environ, module.ENV):
        first = module.evaluate_case(spec)
        second = module.evaluate_case(flipped)
    ok = (first["final_state"] == second["final_state"]
          and first["improper_execution"] != second["improper_execution"])
    return ok, (f"decision {first['final_state']} / {second['final_state']}; "
                f"improper_execution {first['improper_execution']} / {second['improper_execution']}")


def probe_e01_basis() -> tuple[bool, str]:
    _, path = _verification_eval()
    found = "measurement_basis" in path.read_text(encoding="utf-8")
    return found, "the summary carries measurement_basis" if found else "no measurement_basis in the summary"


# ------------------------------------------------------------------------------- report


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    no_frontend = "--no-frontend" in sys.argv

    files = sorted({f for c in CHECKS if c[3] == "py" for f, _ in c[4]})
    print(f"running {len(files)} backend test files ...", flush=True)
    py_results = run_pytest(files)
    print("running the frontend tests ...", flush=True)
    js_results = None if no_frontend else run_vitest()

    rows = []
    for cid, item, what, kind, spec in CHECKS:
        evidence = ""
        if kind == "py":
            found = [(py_results[k], k) for f, prefix in spec for k in py_results if k[0] == f and k[1].startswith(prefix)]
            missing = [prefix for f, prefix in spec if not any(k[0] == f and k[1].startswith(prefix) for k in py_results)]
            if missing:
                result, evidence = FAIL, "test not found or not run: " + ", ".join(missing)
            elif all(s == "PASSED" for s, _ in found):
                result, evidence = PASS, f"{len(found)} test(s) passed"
            else:
                bad = next(k[1] for s, k in found if s != "PASSED")
                result, evidence = FAIL, f"failing: {bad}"
        elif kind == "js":
            if js_results is None:
                result, evidence = SKIP, "frontend tests not run here"
            else:
                found = [(st, t) for frag in spec for t, st in js_results.items() if frag in t]
                missing = [frag for frag in spec if not any(frag in t for t in js_results)]
                if missing:
                    result, evidence = FAIL, "test not found: " + missing[0][:60]
                elif all(st == "passed" for st, _ in found):
                    result, evidence = PASS, f"{len(found)} test(s) passed"
                else:
                    result, evidence = FAIL, "failing: " + next(t for st, t in found if st != "passed")[:60]
        elif kind == "probe":
            try:
                ok, evidence = globals()[spec]()
                result = PASS if ok else FAIL
            except Exception as exc:  # noqa: BLE001 - a broken probe is a failed check, not a crash
                result, evidence = FAIL, f"probe error: {type(exc).__name__}: {exc}"
        else:
            result, evidence = spec
        rows.append((cid, item, what, result, evidence))

    lines = ["# Review VI check against the current repository", "",
             "| Check | Item | What the review asks | Result | Evidence |", "|---|---|---|---|---|"]
    lines += [f"| {c} | {i} | {w} | {r} | {e} |" for c, i, w, r, e in rows]

    lines += ["", "| Item | Status | Checks passed |", "|---|---|---|"]
    fixed = 0
    for item in ITEMS:
        mine = [r for r in rows if r[1] == item and r[3] in (PASS, FAIL)]
        passed = sum(1 for r in mine if r[3] == PASS)
        state = "fixed" if mine and passed == len(mine) else ("open" if passed == 0 else "partial")
        fixed += state == "fixed"
        extra = [r[0] for r in rows if r[1] == item and r[3] in (NO_TEST, OUT_OF_SCOPE, SKIP)]
        lines.append(f"| {item} | {state} | {passed}/{len(mine)}" + (f" (not counted: {', '.join(extra)})" if extra else "") + " |")

    counted = [r for r in rows if r[3] in (PASS, FAIL)]
    passed_all = sum(1 for r in counted if r[3] == PASS)
    pct = round(100 * passed_all / len(counted)) if counted else 0
    lines += ["", f"Checks passed: {passed_all} of {len(counted)} = {pct}%.",
              f"Items fully fixed: {fixed} of {len(ITEMS)}.",
              "Not counted: " + (", ".join(f"{r[0]} ({r[3]})" for r in rows if r[3] in (NO_TEST, OUT_OF_SCOPE, SKIP)) or "none") + ".",
              "A passing test means the correct behaviour is asserted and holds. It is not a production certificate."]

    text = "\n".join(lines)
    print(text)
    out = Path(os.environ.get("VF_VERIFY_OUT") or ROOT / "orchestrator" / "runs" / "verify_review_vi.md")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
