"""
The console decides whether to OFFER Re-evaluate from its own copy of the states the
API accepts it in. The API is the authority (409 for anything else), so a copy that
drifts is either a button that always fails or a case that can be re-evaluated and
shows no button. Rev2 N05: the two had drifted (ESCALATED and PENDING_HUMAN were
accepted by the API and unreachable from the console).
"""

from __future__ import annotations

import re
from pathlib import Path

from vf_logistics import evidence

TYPES = Path(__file__).resolve().parent.parent / "frontend" / "src" / "lib" / "types.ts"


def test_the_console_offers_re_evaluate_in_exactly_the_states_the_api_accepts_it_in():
    source = TYPES.read_text(encoding="utf-8")
    block = re.search(r"REEVALUABLE_STATES: readonly string\[\] = \[(.*?)\];", source, re.S)
    assert block, "frontend/src/lib/types.ts no longer defines REEVALUABLE_STATES"
    console = re.findall(r'"([A-Z_]+)"', block.group(1))
    assert sorted(console) == sorted(evidence.REEVALUABLE)
