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

import shutil
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
        "    acting = claims[0] if claims else None\n    if acting is None:",
        "    acting = (claims[0] if claims else None) or SERVICE_IDENTITY_EMAIL\n    if acting is None:",
        "tests/test_console_session.py::TestForgedSessionsAreRefused",
    ),
    # --- One-click judge sign-in ---
    # The button is public and its session is admin, so the only thing standing
    # between a stranger and an empty board is the sign-in method. Each of these
    # is one way that check could quietly stop meaning anything.
    (
        "a one-click session may clear the board",
        "src/vf_logistics/auth.py",
        "        if ctx is not None and ctx.via_session and ctx.session_method != PASSWORD_SESSION:",
        "        if ctx is not None and ctx.via_session and ctx.session_method == UNKNOWN_SESSION:",
        "tests/test_rbac.py::TestPasswordOnlyRoute",
    ),
    (
        "a missing sign-in claim is read as a password",
        "src/vf_logistics/auth.py",
        "    method = amr if isinstance(amr, str) and amr in _SESSION_METHODS else UNKNOWN_SESSION",
        "    method = amr if isinstance(amr, str) and amr in _SESSION_METHODS else PASSWORD_SESSION",
        "tests/test_console_session.py::TestSignInMethod",
    ),
    (
        "the published policy loses the password-only flag",
        "src/vf_logistics/auth.py",
        "    decorated._requires_password_session = True  # type: ignore[attr-defined]",
        "    pass",
        "tests/test_rbac.py::TestRoutePolicy",
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
    (
        "an unset PROJECT_ID falls back to a named project again",
        "src/vf_logistics/config.py",
        'configured = os.getenv("PROJECT_ID", "").strip()',
        'configured = os.getenv("PROJECT_ID", "another-deployments-project").strip()',
        "tests/test_pure_logic.py::TestGcpProject",
    ),
    (
        "a decision is published with no project to publish to",
        "src/vf_logistics/tools.py",
        "            if not project:\n"
        '                raise RuntimeError("no Google Cloud project to publish to: set PROJECT_ID")',
        "            if False:\n"
        '                raise RuntimeError("no Google Cloud project to publish to: set PROJECT_ID")',
        "tests/test_pure_logic.py::TestNoProjectIsRefusedNotGuessed",
    ),
    # Authorization review of bd6a210 -- findings A01, A03, A02 and T01.
    (
        "A01: a one-click session can publish the shared boundary again",
        "src/vf_logistics/app.py",
        "@require_password_session\ndef governance_publish():",
        "def governance_publish():",
        "tests/test_rbac.py::TestPublishNeedsAPassword",
    ),
    (
        "A03: the gate reads `permitted` by truthiness, so \"false\" releases",
        "src/vf_logistics/governance.py",
        'if rules.get("permitted") is not True:',
        'if not rules.get("permitted"):',
        "tests/test_boundary_schema.py::TestTheGateReadsStoredPoliciesStrictly",
    ),
    (
        "A03: a release grant with a missing ceiling has no ceiling",
        "src/vf_logistics/governance.py",
        "if not _is_number(ceiling) or not _is_number(max_value):",
        "if False:",
        "tests/test_boundary_schema.py::TestTheGateReadsStoredPoliciesStrictly",
    ),
    (
        "A03: publish accepts a non-boolean `permitted`",
        "src/vf_logistics/governance.py",
        "    if not isinstance(permitted, bool):",
        "    if False:",
        "tests/test_boundary_schema.py::TestTheSchemaRefusesWhatWouldBeMisread",
    ),
    (
        "A03: an unknown top-level key is stored as a control nobody reads",
        "src/vf_logistics/governance.py",
        "for key in sorted(set(permissions) - _TOP_LEVEL_KEYS):",
        "for key in []:",
        "tests/test_boundary_schema.py::TestTheSchemaRefusesWhatWouldBeMisread",
    ),
    (
        "A02: the next version is the ACTIVE one plus one again, reusing v1 after a revoke",
        "src/vf_logistics/store.py",
        '[self._boundary_counters.get(scope, 0)]\n'
        '                + [_as_version(b.get("version")) for b in owned.values()]',
        '[0]\n'
        '                + [_as_version(b.get("version")) for b in owned.values()'
        ' if b.get("status") == "ACTIVE"]',
        "tests/test_boundary_history.py::TestRepublishAfterRevoke",
    ),
    (
        "T01: every tenant's boundaries share one storage key again",
        "src/vf_logistics/store.py",
        'return f"{tenant_id}__{boundary_id}"',
        "return boundary_id",
        "tests/test_boundary_history.py::TestTenantsDoNotShareASlot",
    ),
    # Findings S01 and A04.
    (
        "S01: a guest token outlives the guest door being closed",
        "src/vf_logistics/auth.py",
        "if method == ONE_CLICK_SESSION and not one_click_sessions_allowed(normalised):",
        "if False:",
        "tests/test_console_session.py::TestClosingTheGuestDoorEndsGuestSessions",
    ),
    (
        "A04: the shared sign-in ledger never says limited",
        "src/vf_logistics/store.py",
        "            limited = len(stamps) >= limit",
        "            limited = False",
        "tests/test_login_throttle.py::TestTheLedger",
    ),
    (
        "A04/R04: a signed-in operator may consult and burn the sign-in ledger",
        "src/vf_logistics/auth.py",
        'if (request.headers.get(CONSOLE_SESSION_HEADER) or "").strip():\n'
        '            return jsonify({"error": "service identity only"}), 403',
        'if False:\n'
        '            return jsonify({"error": "service identity only"}), 403',
        "tests/test_login_throttle.py::TestTheRoute",
    ),
    # Findings T02 and T03.
    (
        "T02/T03: X-VF-Tenant may name a tenant the principal is not a member of",
        "src/vf_logistics/membership.py",
        "        if wanted not in granted:",
        "        if False:",
        "tests/test_membership.py::TestConsoleSessions",
    ),
    (
        "T03: console sessions land in the implicit tenant again under MULTI_TENANT",
        "src/vf_logistics/auth.py",
        "        tenant_id, member_roles = _membership(acting)",
        "        tenant_id, member_roles = tenant.SINGLE_TENANT_ID, _get_user_roles(acting)",
        "tests/test_membership.py::TestConsoleSessions",
    ),
    # Re-review findings R01-R04 (on 923d36f). Selectors under frontend/ run vitest.
    (
        "R01: the source is the caller-written first X-Forwarded-For entry again",
        "frontend/src/lib/rate-limit.ts",
        'const last = header.slice(header.lastIndexOf(",") + 1).trim();',
        'const last = header.split(",")[0].trim();',
        "frontend/src/lib/rate-limit.test.ts",
    ),
    (
        "R01: a malformed address is a bucket of its own",
        "frontend/src/lib/rate-limit.ts",
        "return last.length <= MAX_IP_LENGTH && isIP(last) !== 0 ? last : UNKNOWN_SOURCE;",
        "return last || UNKNOWN_SOURCE;",
        "frontend/src/lib/rate-limit.test.ts",
    ),
    (
        "R01: a ledger key carries the raw value, so a long one is a 400",
        "frontend/src/lib/rate-limit.ts",
        'return `${kind}:${createHash("sha256").update(value, "utf8").digest("hex")}`;',
        "return `${kind}:${value}`;",
        "frontend/src/lib/login-limit.test.ts",
    ),
    (
        "R01: a ledger failure falls through to fresh local counters again",
        "frontend/src/lib/login-limit.ts",
        "if (!mayCountLocally(apiKey)) {",
        "if (false) {",
        "frontend/src/lib/login-limit.test.ts",
    ),
    (
        "R01: the login route checks a password with no limit established",
        "frontend/src/app/api/auth/login/route.ts",
        'if (verdict === "unavailable") {',
        "if (false) {",
        "frontend/src/app/api/auth/login/route.test.ts",
    ),
    (
        "R04: the sign-in ledger goes through tenant selection again",
        "src/vf_logistics/app.py",
        '@app.route("/internal/login-throttle", methods=["POST"])\n@require_platform_key',
        '@app.route("/internal/login-throttle", methods=["POST"])\n@require_operator',
        "tests/test_login_throttle.py::TestUnderMultiTenancy",
    ),
    (
        "R02: a body tenant may differ from the organisation the role was checked in",
        "src/vf_logistics/app.py",
        "        if claimed is not None and claimed != tenant.resolve(target):",
        "        if False:",
        "tests/test_internal_execute.py::TestTheReviewsRequestsAreRefused",
    ),
    (
        "R02: a request acting for a person reaches the executor again",
        "src/vf_logistics/app.py",
        "if context is None or not context.is_machine_identity:",
        "if context is None or not context.is_service_identity:",
        "tests/test_internal_execute.py::TestTheReviewsRequestsAreRefused",
    ),
    (
        "R02: a case of another organisation is published",
        "src/vf_logistics/app.py",
        "if not case_id or _on_worker(get_store().get_case(case_id, tenant_id=target)) is None:",
        "if not case_id:",
        "tests/test_internal_execute.py::TestTheReviewsRequestsAreRefused",
    ),
    (
        "R02: the executor client stops selecting the organisation",
        "src/vf_logistics/executor_client.py",
        "        headers[membership.TENANT_HEADER] = tenant_id",
        "        pass",
        "tests/test_internal_execute.py::TestTheClientSelectsTheOrganisation",
    ),
    (
        "R03: a membership refusal no longer says why",
        "src/vf_logistics/auth.py",
        '        "reason": exc.reason,\n',
        "",
        "tests/test_membership.py::TestRoutesSeeTheResolvedTenant",
    ),
    (
        "R03: getAuth throws the choices in a 403 away again",
        "frontend/src/lib/identity.ts",
        "      if (choice) throw choice;",
        "      if (false) throw choice;",
        "frontend/src/components/layout/TenantSwitcher.test.tsx",
    ),
    (
        "R03: signing out keeps the organisation choice for the next person",
        "frontend/src/app/api/auth/logout/route.ts",
        '  response.cookies.set(TENANT_COOKIE, "", EXPIRED_TENANT_CHOICE);',
        "",
        "frontend/src/app/api/auth/login/route.test.ts",
    ),
    # Plan 2: the operator screens (Today, a case's page, Outcomes).
    (
        "P2: a request for information is grouped as waiting on a reviewer",
        "src/vf_logistics/worklist.py",
        '        if last is not None and last.get("action") == "request_info":\n'
        '            return "awaiting_documents"',
        '        if False:\n'
        '            return "awaiting_documents"',
        "tests/test_worklist.py::TestWhatEachCaseIsWaitingFor",
    ),
    (
        "P2: every review counts as a round of requests for information",
        "src/vf_logistics/worklist.py",
        '    return sum(1 for r in _reviews(case) if r.get("action") == "request_info")',
        "    return len(_reviews(case))",
        "tests/test_worklist.py::TestOutcomeArithmetic",
    ),
    (
        "P2: the boundary's refusal is not offered as the next action",
        "src/vf_logistics/worklist.py",
        '    denials = case.get("gate_denials") or []',
        "    denials = []",
        "tests/test_worklist.py::TestWhatEachCaseIsWaitingFor",
    ),
    (
        "P2: an unmeasured cost is reported as zero",
        "src/vf_logistics/worklist.py",
        '    cost_summary["mean"] = (sum(costs) / len(costs)) if costs else None',
        '    cost_summary["mean"] = (sum(costs) / len(costs)) if costs else 0.0',
        "tests/test_worklist.py::TestOutcomeArithmetic",
    ),
    (
        "P2: handling time is recorded under a name from the body",
        "src/vf_logistics/app.py",
        "store.add_activity(case_id, context.email, active_ms,",
        'store.add_activity(case_id, str(body.get("actor") or context.email), active_ms,',
        "tests/test_worklist.py::TestRecordingActivity",
    ),
    (
        "P2: handling time is recorded for a case outside the caller's tenant",
        "src/vf_logistics/app.py",
        "        if _on_worker(store.get_case(case_id, tenant_id=_tenant())) is None:\n"
        '            return jsonify({"error": "case not found"}), 404\n'
        "        _on_worker(store.add_activity(",
        "        _on_worker(store.add_activity(",
        "tests/test_worklist.py::TestRecordingActivity",
    ),
    (
        "P2: a refusal on the case timeline reads the key governance never writes",
        "frontend/src/lib/operations.ts",
        'const reason = typeof nested === "string" && nested ? nested : receipt.gate_reason ?? null;',
        "const reason = receipt.gate_reason ?? null;",
        "frontend/src/lib/operations.test.ts",
    ),
    (
        "P2: an idle tab keeps adding handling time",
        "frontend/src/lib/activity.ts",
        "      const activeUntil = Math.min(upTo, lastInput + IDLE_MS);",
        "      const activeUntil = upTo;",
        "frontend/src/lib/activity.test.ts",
    ),
    (
        "P2: a hidden page keeps adding handling time",
        "frontend/src/lib/activity.ts",
        "    if (visible) {",
        "    if (true) {",
        "frontend/src/lib/activity.test.ts",
    ),
    # Plan 1, step 1: the origin watch and the evidence check.
    (
        "P1: a whitelisted shipper's cargo on a watched lane is cleared by the rules",
        "src/vf_logistics/verifier.py",
        '        f["severity"] in ("HIGH", "CRITICAL") or f.get("blocks_auto_clear")\n'
        '        for f in findings\n'
        '        if not f.get("auto_clear_by_rules")',
        '        f["severity"] in ("HIGH", "CRITICAL")\n'
        '        for f in findings\n'
        '        if not f.get("auto_clear_by_rules")',
        "tests/test_origin_inputs.py::TestTheRulesCannotClearIt",
    ),
    (
        "P1: a watched lane is no longer flagged",
        "src/vf_logistics/verifier.py",
        "    rule = watched_lane(shipment)\n    if rule is None:\n        return []\n    declared = _canon_country",
        "    return []\n    declared = _canon_country",
        "tests/test_origin_inputs.py::TestTheWatch",
    ),
    (
        "P1: a country alias hides a watched destination",
        "src/vf_logistics/verifier.py",
        "    return _COUNTRY_ALIASES.get(name, name)",
        "    return name",
        "tests/test_origin_inputs.py::TestTheWatch",
    ),
    (
        "P1: complete, consistent papers lower the case's floor",
        "src/vf_logistics/verifier.py",
        '    status = "contradicted" if findings else ("provided" if not missing else "missing")',
        '    status = "contradicted" if findings else ("provided" if not missing else "missing")\n'
        '    if status == "provided":\n'
        '        findings = [{"code": "ORIGIN_CLEARED", "severity": "INFO", "floor": -45, "detail": "ok"}]',
        "tests/test_origin_inputs.py::TestTheEvidence",
    ),
    (
        "P1: a Chinese-origin input invoice is not a contradiction",
        "src/vf_logistics/verifier.py",
        "            if goods_origin == watched:",
        "            if False:",
        "tests/test_origin_inputs.py::TestTheEvidence",
    ),
    (
        "P1: a different producer on the certificate is not a mismatch",
        "src/vf_logistics/verifier.py",
        "    producer_mismatch = bool(certified and others and not (certified & others))",
        "    producer_mismatch = False",
        "tests/test_origin_inputs.py::TestTheEvidence",
    ),
    (
        "P1: company legal suffixes make the same producer look different",
        "src/vf_logistics/verifier.py",
        "    return \" \".join(w for w in words if w not in _COMPANY_SUFFIXES)",
        "    return \" \".join(words)",
        "tests/test_origin_inputs.py::TestTheEvidence",
    ),
    # Plan 1, step 2: requests for documents and the signed link.
    (
        "P1.2: the link is kept in the case, where a viewer can read it",
        "src/vf_logistics/evidence.py",
        '    request["status"] = "SENT"',
        '    request["status"] = "SENT"\n    request["token"] = token',
        "tests/test_evidence_request.py::TestRequestingDocuments",
    ),
    (
        "P1.2: an expired link is still accepted",
        "src/vf_logistics/evidence.py",
        "    if (time.time() if now is None else now) >= expires:",
        "    if False:",
        "tests/test_evidence_request.py::TestTheToken",
    ),
    (
        "P1.2: the link's signature is not checked",
        "src/vf_logistics/evidence.py",
        "        if not hmac.compare_digest(_unb64(signature), expected):\n            return None",
        "        if False:\n            return None",
        "tests/test_evidence_request.py::TestTheToken",
    ),
    (
        "P1.2: the link key is the session secret itself",
        "src/vf_logistics/evidence.py",
        '    return hmac.new(secret.encode("utf-8"), _KEY_CONTEXT, hashlib.sha256).digest()',
        '    return secret.encode("utf-8")',
        "tests/test_evidence_request.py::TestTheToken",
    ),
    (
        "P1.2: cancelling needs no reason",
        "src/vf_logistics/evidence.py",
        '    why = _clean_text(reason, MAX_NOTE_CHARS, "reason", required=True)',
        '    why = _clean_text(reason, MAX_NOTE_CHARS, "reason", required=False)',
        "tests/test_evidence_request.py::TestLinksAndCancelling",
    ),
    (
        "P1.2: cancelling sends an escalated case back as merely held",
        "src/vf_logistics/evidence.py",
        '        case["state"] = record.get("resume_state") or "HELD_FOR_REVIEW"',
        '        case["state"] = "HELD_FOR_REVIEW"',
        "tests/test_evidence_request.py::TestLinksAndCancelling",
    ),
    (
        "P1.2: a case with a request open can be decided",
        "src/vf_logistics/orchestrator.py",
        'AWAITING_HUMAN = ("PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED")',
        'AWAITING_HUMAN = ("PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED", "AWAITING_EVIDENCE")',
        "tests/test_evidence_request.py::TestWhileARequestIsOpen",
    ),
    (
        "P1.2: documents can be requested on a case that is already decided",
        "src/vf_logistics/evidence.py",
        'REQUESTABLE_STATES = ("PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED", AWAITING_EVIDENCE, "APPROVED")',
        'REQUESTABLE_STATES = ("PENDING_HUMAN", "HELD_FOR_REVIEW", "ESCALATED", AWAITING_EVIDENCE, "APPROVED", "AUTO_CLEARED", "RELEASED_BY_HUMAN", "BLOCKED_BY_HUMAN", "INGESTED", "DEAD_LETTER")',
        "tests/test_evidence_request.py::TestRequestingDocuments",
    ),
    (
        "P1.2: the same request can be made twice",
        "src/vf_logistics/evidence.py",
        '        if sorted(existing["documents"]) == sorted(wanted) and set(existing["finding_codes"]) == set(codes):',
        "        if False:",
        "tests/test_evidence_request.py::TestRequestingDocuments",
    ),
    (
        "P1.2: the response carrying a link may be cached",
        "src/vf_logistics/app.py",
        '        response.headers["Cache-Control"] = "no-store"',
        "        pass",
        "tests/test_evidence_request.py::TestTheRoutes",
    ),
    (
        "P1.2: the requester is recorded from the body, not the session",
        "src/vf_logistics/app.py",
        "    if context is not None and context.acts_for_a_person:\n        return context.email, context.actor_auth",
        "    if False:\n        return context.email, context.actor_auth",
        "tests/test_evidence_request.py::TestTheRoutes",
    ),
    # Rev2 backlog: the guards that were read as correct but never tested.
    (
        "N01: the claim is written without the version it read, so two callers can both win",
        "src/vf_logistics/evidence.py",
        '    case["updated_at"] = now\n    await _write(case, expected_version, tenant_id)\n    # If another caller claimed first',
        '    case["updated_at"] = now\n    await _write(case, None, tenant_id)\n    # If another caller claimed first',
        "tests/test_evidence_execution.py::TestN01TwoExecutesAtOnce",
    ),
    (
        "N01: the claimant may resume its own claim while the first send is still in flight",
        "src/vf_logistics/evidence.py",
        "        if time.time() < lease_ends:\n            raise EvidenceError(\n                \"Another execution of this approval is in progress. \"",
        "        if existing_exe.get(\"executor\") != executor and time.time() < lease_ends:\n            raise EvidenceError(\n                \"Another execution of this approval is in progress. \"",
        "tests/test_evidence_execution.py::TestN01TwoExecutesAtOnce",
    ),
    (
        "N05: a case that never asked for documents can be re-evaluated",
        "src/vf_logistics/evidence.py",
        "    if not isinstance(existing, dict) or not existing.get(\"requests\"):",
        "    if False:",
        "tests/test_evidence_eval_approve.py::TestN05OnlyInsideTheVerificationLoop",
    ),
    (
        "N05: a released case can be re-evaluated",
        "src/vf_logistics/evidence.py",
        '    REEVALUABLE = ("AWAITING_EVIDENCE", "HELD_FOR_REVIEW", "ESCALATED", "PENDING_HUMAN")',
        '    REEVALUABLE = ("AWAITING_EVIDENCE", "HELD_FOR_REVIEW", "ESCALATED", "PENDING_HUMAN", "RELEASED_BY_HUMAN")',
        "tests/test_evidence_eval_approve.py::TestN05OnlyInsideTheVerificationLoop",
    ),
    (
        "N06: a certificate that states no country contradicts the declared origin",
        "src/vf_logistics/verifier.py",
        "        if not _is_meaningful(raw_origin):\n            continue\n        stated = _canon_country(raw_origin)",
        "        stated = _canon_country(raw_origin)",
        "tests/test_origin_inputs.py::TestN06WhatCountsAsNothingStated",
    ),
    (
        "N06: a placeholder goods origin shadows a stated supplier country",
        "src/vf_logistics/verifier.py",
        "                    for v in (inv.get(\"goods_origin_country\"), inv.get(\"supplier_country\"))\n                    if _is_meaningful(v)",
        "                    for v in (inv.get(\"goods_origin_country\"), inv.get(\"supplier_country\"))\n                    if v",
        "tests/test_origin_inputs.py::TestN06WhatCountsAsNothingStated",
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
    """True if the tests passed. A selector under frontend/ is a vitest file."""
    if selector.startswith("frontend/"):
        npx = shutil.which("npx")
        if npx is None:
            raise SystemExit("npx is not on PATH; the frontend mutations need it.")
        # UTF-8 explicitly: vitest prints check marks, and the Windows default
        # code page cannot decode them, which raises in the reader thread.
        proc = subprocess.run(
            [npx, "vitest", "run", selector.removeprefix("frontend/")],
            cwd=ROOT / "frontend", capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        return proc.returncode == 0
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
