"""
Child process of tests/test_sim_hard_kill.py: executes one approval and is killed
outright the moment the broker has accepted the decision, before any record of the
publish is saved. Nothing after the kill runs: no except clause, no finally, no shield.

Usage: python sim_hard_kill_child.py CASE_ID APPROVAL_ID EXECUTOR
"""

from __future__ import annotations

import asyncio
import os
import signal
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from vf_logistics import evidence, tools  # noqa: E402

real_audit = tools._audit


async def killed_before_the_record(case_id, action, detail, status="done", tenant_id=None):
    if action == "publish_decision":
        # The broker has the message. TerminateProcess on Windows, SIGKILL elsewhere.
        os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))
    return await real_audit(case_id, action, detail, status, tenant_id)


tools._audit = killed_before_the_record
case_id, approval_id, executor = sys.argv[1:4]
asyncio.run(evidence.execute_approval(case_id, approval_id, executor, actor_auth="password"))
