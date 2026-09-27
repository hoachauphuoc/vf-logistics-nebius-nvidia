"""
Prove the new tests fail when the behaviour they describe is broken.

A test that has never been seen to fail is a claim, not evidence. This project already
learned that the expensive way: `test_documents.py` reported "All 7 matched" while
pointing at the wrong deployment, and three separate UI fields read a key the backend
never sent while every test stayed green.

So for each mutation below: break one line, run the test that should catch it, and
require it to go RED. A mutation that leaves the suite green means the test is decorative
and the report says so.

Safety, because this edits source files:
  - refuses to run unless `git status --porcelain` is clean, so a crash can always be
    undone with `git checkout`
  - restores the original bytes in a `finally`, not on the happy path
  - verifies the restore actually matched before moving on, and stops if it did not

Run: python scripts/check_test_sensitivity.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent

# (label, file, find, replace, test selector that MUST fail)
MUTATIONS = [
    (
        "an unparseable verdict is reported as one that was never rendered",
        "src/vf_logistics/agents/debate_agent.py",
        'if tool_name == "render_final_verdict" and not args_unparseable:',
        'if tool_name == "render_final_verdict":',
        "tests/test_debate_control_flow.py::TestUnparseableVerdict",
    ),
    (
        "the raw arguments of an unreadable verdict are discarded",
        "src/vf_logistics/agents/debate_agent.py",
        'unparseable_verdict = str(tool_call.function.arguments)',
        'unparseable_verdict = None',
        "tests/test_debate_control_flow.py::TestUnparseableVerdict",
    ),
    (
        "a decisive verdict does not stop the loop",
        "src/vf_logistics/agents/debate_agent.py",
        "            if final_verdict:\n                break",
        "            if final_verdict and False:\n                break",
        "tests/test_debate_control_flow.py::TestVerdictOnFirstRound",
    ),
    (
        "the whole document is no longer screened as one window",
        "src/vf_logistics/model_armor.py",
        "windows = [text]  # the whole thing first",
        "windows = []  # the whole thing first",
        "tests/test_security_screen_logic.py::TestWindowing",
    ),
    (
        "the window count is capped one too low, dropping a real window",
        "src/vf_logistics/model_armor.py",
        "if len(windows) >= MAX_WINDOWS + 1:",
        "if len(windows) >= MAX_WINDOWS:",
        "tests/test_security_screen_logic.py::TestWindowing",
    ),
    (
        "a screen that reached no verdict stops asking for a person",
        "src/vf_logistics/model_armor.py",
        '        verdict["detail"] = "; ".join(errors[:3]) or "no successful screen"\n'
        '        verdict["requires_human"] = True',
        '        verdict["detail"] = "; ".join(errors[:3]) or "no successful screen"',
        "tests/test_security_screen_logic.py::TestFailClosed",
    ),
    (
        "an unreadable PDF page loses every page after it",
        "src/vf_logistics/model_armor.py",
        "            except Exception:  # noqa: BLE001 - one bad page must not lose the rest\n"
        "                continue",
        "            except Exception:  # noqa: BLE001 - one bad page must not lose the rest\n"
        "                break",
        "tests/test_security_screen_logic.py::TestPdfTextExtraction",
    ),
    (
        "result_count reports what was kept instead of what was found",
        "src/vf_logistics/agents/debate_agent.py",
        '"result_count": len(results),',
        '"result_count": len(results[:max_results]),',
        "tests/test_debate_logic.py::TestTavilySearchFromTheDebate",
    ),
    (
        "a failed search arrives as an innocent empty list",
        "src/vf_logistics/agents/debate_agent.py",
        "if status in tavily_client.FAILED_STATUSES:",
        "if False:",
        "tests/test_debate_logic.py::TestTavilySearchFromTheDebate",
    ),
    (
        "the debate focus mutates the caller's stored shipment",
        "src/vf_logistics/agents/debate_agent.py",
        'shipment = case.get("shipment", {}).copy()',
        'shipment = case.get("shipment", {})',
        "tests/test_debate_logic.py::TestNanoReevaluation",
    ),
    (
        "an unknown tool name is silently swallowed",
        "src/vf_logistics/agents/debate_agent.py",
        'return {"error": f"Unknown tool: {tool_name}"}',
        "return {}",
        "tests/test_debate_logic.py::TestToolDispatch",
    ),
    # The two below are the reason this script exists rather than a coverage number.
    # Both of these tests originally re-implemented the code in the test body and
    # asserted on their own literal, so they passed no matter what orchestrator.py did --
    # the same failure mode as the UI bug they were written to catch.
    (
        "a step is recorded with no cost, blanking the cost card",
        "src/vf_logistics/orchestrator.py",
        '    step["cost_usd"] = round(step_cost, 8)',
        "    pass  # cost not recorded",
        "tests/test_console_contract.py::TestStepFieldNames::test_step_shape_has_cost_usd",
    ),
    (
        "citations are written under the key the console used to read",
        "src/vf_logistics/orchestrator.py",
        '        step["external_search_results"] = response.get("external_search_results", [])',
        '        step["urls"] = response.get("external_search_results", [])',
        "tests/test_console_contract.py::TestStepFieldNames",
    ),
    # --- Security hardening pass ---
    (
        "governance author is taken from the body instead of the identity",
        "src/vf_logistics/app.py",
        "context = get_auth_context()\n        if context is not None and context.acts_for_a_person:\n            author = context.email\n        else:\n            author = str(body.get(\"author\") or \"\").strip()\n        if not author:\n            return jsonify({\"error\": \"an authenticated identity is required to publish a boundary\"}), 403",
        "author = str(body.get(\"author\") or \"\").strip()\n        if not author:\n            return jsonify({\"error\": \"an authenticated identity is required to publish a boundary\"}), 403",
        "tests/test_audit_integrity.py::TestAuditAuthorIntegrity",
    ),
    (
        "CSP drops base-uri entirely",
        "src/vf_logistics/app.py",
        '"base-uri \'none\'; "',
        '""',
        "tests/test_network_defence.py::SecurityHeaderTests::test_csp_contains_base_uri_and_form_action",
    ),
    (
        "a dangerous MIME type is added to the upload allow-list",
        "src/vf_logistics/agents/document_agent.py",
        '    ".webp": "image/webp",',
        '    ".webp": "image/webp",\n    ".html": "text/html",',
        "tests/test_network_defence.py::SecurityHeaderTests::test_document_content_type_is_pinned_to_the_upload_allow_list",
    ),
    # --- Real RBAC ---
    # Each of these puts back, in one line, a way the role hierarchy was decorative
    # before: everyone admin, a bad session tolerated, a list entry unmatchable, the
    # queue locked so the console had to lend anonymous readers its key.
    (
        "every signed-in person gets the key's admin role again",
        "src/vf_logistics/auth.py",
        "roles=narrow_roles(_get_user_roles(acting), API_KEY_GRANT),",
        "roles={API_KEY_GRANT},",
        "tests/test_rbac.py::TestRoleMatrix",
    ),
    (
        "a session that fails to verify is tolerated instead of refused",
        "src/vf_logistics/auth.py",
        "    acting = _console_session_email()\n    if acting is None:",
        "    acting = _console_session_email() or SERVICE_IDENTITY_EMAIL\n    if acting is None:",
        "tests/test_console_session.py::TestForgedSessionsAreRefused",
    ),
    (
        "role list entries are compared without trimming or case-folding",
        "src/vf_logistics/auth.py",
        "        entry.strip().lower()\n        for entry in os.getenv(variable, \"\").split(\",\")",
        "        entry\n        for entry in os.getenv(variable, \"\").split(\",\")",
        "tests/test_rbac.py::TestRoleLists",
    ),
    (
        "the review queue is locked back to reviewers",
        "src/vf_logistics/app.py",
        "# case, and opening its original document, still need reviewer.\n@require_viewer",
        "# case, and opening its original document, still need reviewer.\n@require_reviewer",
        "tests/test_rbac.py::TestReviewQueueIsReadable",
    ),
    (
        "the published policy loses the role a route enforces",
        "src/vf_logistics/auth.py",
        "        decorated._required_role = required_role.value  # type: ignore[attr-defined]",
        "        pass",
        "tests/test_rbac.py::TestRoutePolicy",
    ),
    # --- The auto-debate verdict acts, upward only ---
    # The first is the bug itself -- a verdict nothing reads. The rest are each a way
    # the fix could let the debate act when it must not, or lower what it must not.
    (
        "routing ignores the Senior Auditor's verdict again",
        "src/vf_logistics/orchestrator.py",
        "            or bool(case.get(\"debate_escalated\"))\n        )",
        "            or False\n        )",
        "tests/test_debate_routing.py::TestTheVerdictNowActs",
    ),
    (
        "a forced default verdict is treated as a judgement",
        "src/vf_logistics/orchestrator.py",
        "    if verdict.get(\"forced\"):\n        return False, (",
        "    if False:\n        return False, (",
        "tests/test_debate_routing.py::TestItNeverLowersAnything::test_a_forced_verdict_changes_nothing",
    ),
    (
        "a low-confidence disagreement escalates anyway",
        "src/vf_logistics/orchestrator.py",
        "    if confidence < threshold:\n        return False, (",
        "    if False:\n        return False, (",
        "tests/test_debate_routing.py::TestItNeverLowersAnything::test_a_timid_disagree_changes_nothing_and_says_why",
    ),
    (
        "the auditor's adjusted score may lower the effective risk",
        "src/vf_logistics/orchestrator.py",
        "            after = max(before, min(100, proposed))",
        "            after = min(100, proposed)",
        "tests/test_debate_routing.py::TestItNeverLowersAnything::test_a_lower_adjusted_score_does_not_lower_risk",
    ),
    (
        "shipper history discounts risk below the deterministic floor",
        "src/vf_logistics/orchestrator.py",
        "            reconciled[\"effective_risk\"] = max(floor, min(100, old_risk + adj))",
        "            reconciled[\"effective_risk\"] = max(0, min(100, old_risk + adj))",
        "tests/test_debate_routing.py::TestLearningLoopRespectsTheFloor",
    ),
    # --- False-positive tuning ---
    # Each undoes one half of the change, or lets an observation back into the
    # arithmetic by the side door. The last is the one that matters most: a finding
    # quietly demoted to context would lower recall and nothing else would notice.
    (
        "a thin trading record is scored as a finding again",
        "src/vf_logistics/verifier.py",
        "            \"code\": \"SHIPPER_THIN_HISTORY\",\n            \"observation\": True,",
        "            \"code\": \"SHIPPER_THIN_HISTORY\",",
        "tests/test_false_positive_tuning.py::TestAShortTradingRecordIsContext",
    ),
    (
        "freight above the lane figure is scored as a finding again",
        "src/vf_logistics/verifier.py",
        "        if source != STATED_BASELINE_SOURCE:",
        "        if False:",
        "tests/test_false_positive_tuning.py::TestFreightAboveTheLaneFigureIsContext",
    ),
    (
        "observations are counted with the findings",
        "src/vf_logistics/verifier.py",
        "    findings = [f for f in findings if not f.get(\"observation\")]",
        "    pass",
        "tests/test_false_positive_tuning.py",
    ),
    (
        "underpriced freight is demoted along with overpriced",
        "src/vf_logistics/verifier.py",
        "    if ratio < 0.25:\n        sev, floor = \"CRITICAL\", 90",
        "    if ratio < 0.25 and source == STATED_BASELINE_SOURCE:\n        sev, floor = \"CRITICAL\", 90",
        "tests/test_false_positive_tuning.py::TestFreightAboveTheLaneFigureIsContext::test_underpriced_freight_is_still_a_finding_against_the_lane_table",
    ),
    (
        "the classifier is told the subheading instead of the heading",
        "src/vf_logistics/agents/hs_classifier_agent.py",
        "        f\"Declared heading: {declared_heading}\\n\"",
        "        f\"Declared heading: {declared_hs}\\n\"",
        "tests/test_decision_paths.py::HsDeclaredHeadingTests",
    ),
]


def require_clean_tree() -> None:
    out = subprocess.run(
        ["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True,
    ).stdout.strip()
    if out:
        print("REFUSING TO RUN: the working tree is not clean.")
        print("This script edits source files. Commit or stash first, so that an")
        print("interrupted run can always be undone with `git checkout`.\n")
        print(out)
        sys.exit(2)


def run_test(selector: str) -> bool:
    """True if the tests passed."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", selector, "-q", "--no-header", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode == 0


def main() -> int:
    require_clean_tree()

    print("Checking that each test actually fails when its subject is broken.\n")
    undetected = []

    for label, rel_path, find, replace, selector in MUTATIONS:
        path = ROOT / rel_path
        original = path.read_bytes()
        text = original.decode("utf-8")

        # The anchors are written with "\n" but these files are checked out with CRLF on
        # Windows, and `read_bytes` does no translation -- so a multi-line anchor matches
        # zero times while a single-line one matches fine. Normalise to whatever the file
        # actually uses rather than guessing.
        newline = "\r\n" if "\r\n" in text else "\n"
        find = find.replace("\n", newline)
        replace = replace.replace("\n", newline)

        occurrences = text.count(find)
        if occurrences != 1:
            print(f"  SKIP  {label}")
            print(f"        the anchor matches {occurrences} times in {rel_path}, so the")
            print("        mutation cannot be aimed at one line. Fix the anchor.")
            undetected.append((label, f"anchor matched {occurrences} times"))
            continue

        try:
            path.write_bytes(text.replace(find, replace).encode("utf-8"))
            passed = run_test(selector)
        finally:
            path.write_bytes(original)
            if path.read_bytes() != original:
                print(f"\nFATAL: could not restore {rel_path}. Run `git checkout {rel_path}`.")
                return 3

        if passed:
            print(f"  NOT CAUGHT  {label}")
            print(f"              {selector} still passed. The test does not check this.")
            undetected.append((label, selector))
        else:
            print(f"  caught      {label}")

    print()
    if undetected:
        print(f"{len(undetected)} of {len(MUTATIONS)} mutations were NOT caught:")
        for label, detail in undetected:
            print(f"  - {label}  ({detail})")
        return 1

    print(f"All {len(MUTATIONS)} mutations were caught. Every test above has been seen red.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
