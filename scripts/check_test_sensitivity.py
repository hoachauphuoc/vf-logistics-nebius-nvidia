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
