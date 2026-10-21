"""
scripts/compare_debate_models.py --corpus, end to end with the model calls replaced.

The first version of the checkpoint (a partial report every 10 debates) defined
build_report after the debates ran, so the run died with a NameError at debate 10 and
lost everything it had paid for. --dry-run never reaches that code, so only running the
whole flow catches it. Nothing here touches the network.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import pathlib

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parents[1] / "scripts"


@pytest.fixture()
def module(monkeypatch, tmp_path):
    monkeypatch.syspath_prepend(str(SCRIPTS))
    spec = importlib.util.spec_from_file_location("compare_debate_models_under_test", SCRIPTS / "compare_debate_models.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    import _eval_common

    from vf_logistics import tavily_client

    # install_empty_tavily() rebinds these for the process; restore them afterwards.
    for name in ("search_with_status", "search", "search_cached"):
        monkeypatch.setattr(tavily_client, name, getattr(tavily_client, name))
    monkeypatch.setattr(_eval_common, "OUT_DIR", tmp_path)
    return mod, _eval_common


def test_a_run_past_the_checkpoint_writes_partial_and_final_reports(module, tmp_path, monkeypatch):
    mod, common = module

    async def fake_screen(case, sem):
        return {
            "case_id": case["case_id"],
            "fraud": bool(case["expected_flagged"]),
            "disputed": True,
            "screen_cost_usd": 0.0001,
            "case": {"case_id": case["case_id"], "shipment": case["shipment"], "steps": []},
        }

    async def fake_run_one(case, model):
        return {
            "case_id": case["case_id"], "model": model, "verdict": "DISAGREE", "confidence": 0.8,
            "forced": False, "parsed": True, "error": None, "input_tokens": 1000,
            "output_tokens": 100, "cost_usd": 0.001, "seconds": 0.1,
        }

    monkeypatch.setattr(mod, "nano_screen", fake_screen)
    monkeypatch.setattr(mod, "run_one", fake_run_one)

    writes: list[bool] = []
    original = common.write_report

    def recording(name, report):
        writes.append(report["partial"])
        return original(name, report)

    monkeypatch.setattr(common, "write_report", recording)

    args = argparse.Namespace(
        per_label=6, screen_fraud=30, concurrency=4, max_cost_usd=10.0,
        dry_run=False, out="debate_test.json",
    )
    assert asyncio.run(mod.corpus_main(args)) == 0

    # 12 cases x 2 models = 24 debates: checkpoints at 10 and 20, then the final report.
    assert writes == [True, True, False]
    report = json.loads((tmp_path / "debate_test.json").read_text(encoding="utf-8"))
    assert report["partial"] is False
    assert report["debated"] == {"fraud": 6, "honest": 6}
    assert report["results"]["ultra"]["debates"] == 12
    assert report["results"]["super"]["disagree_on_fraud"]["count"] == 6
