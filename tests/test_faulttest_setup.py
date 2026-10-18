"""
The settings of vf-app-faulttest: the fault is switched on only there, it has its own topic, ledger,
tenant and secrets, and the secrets are written to files, never printed.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import faulttest_setup as setup  # noqa: E402


def env_of(path):
    return {line.split(": ", 1)[0]: json.loads(line.split(": ", 1)[1]) for line in path.read_text(encoding="utf-8").splitlines()}


def test_the_service_runs_the_fault_module_on_its_own_topic_tenant_and_secrets(tmp_path):
    env = env_of(setup.write(tmp_path, "proj-1", "kill_after_publish"))
    assert env["FLASK_APP_MODULE"] == "vf_logistics.faulttest:app"
    assert (env["FAULT_TEST_ALLOWED"], env["FAULT"]) == ("true", "kill_after_publish")
    assert (env["DECISIONS_TOPIC"], env["SENT_LEDGER_SUBSCRIPTION"]) == ("faulttest-decisions", "faulttest-sent-ledger")
    assert env["MULTI_TENANT"] == "true"
    assert json.loads(env["VF_TENANT_MEMBERS"]) == {"op@faulttest.test": {"faulttest": "operator"}, "service": {"faulttest": "operator"}}
    assert env["VF_API_KEY"] == (tmp_path / "api_key.txt").read_text().strip()
    assert len(env["VF_SESSION_SECRET"]) >= 32
    assert "case-decisions" not in env.values()


def test_switching_the_fault_keeps_the_secrets(tmp_path):
    first = env_of(setup.write(tmp_path, "proj-1", "kill_after_publish"))
    second = env_of(setup.write(tmp_path, "proj-1", "slow_after_execute"))
    assert second["FAULT"] == "slow_after_execute"
    assert (second["VF_API_KEY"], second["VF_SESSION_SECRET"]) == (first["VF_API_KEY"], first["VF_SESSION_SECRET"])


def test_an_unknown_fault_is_refused():
    with pytest.raises(ValueError, match="fault must be one of"):
        setup.settings("proj-1", "drop_everything", "k", "s")


def test_nothing_secret_is_printed(tmp_path, capsys):
    setup.main(["--project", "proj-1", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert (tmp_path / "api_key.txt").read_text().strip() not in out
    assert (tmp_path / "session_secret.txt").read_text().strip() not in out
