"""
Shared helpers for the model-comparison scripts (compare_fraud_models.py and
compare_debate_models.py --corpus).

Both read the labelled synthetic corpus, never call a real Tavily search (the stub
returns an empty list with status OK, exactly as run_massive_benchmark.py's stub does,
so the comparison does not spend the free tier the live service needs), and stop when
the running cost estimate crosses a ceiling.

The Nebius key is read from NEBIUS_API_KEY by nebius_client; nothing here reads,
prints or writes it.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import sys
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

CASES_FILE = ROOT / "data" / "synthetic_test_cases.json"
OUT_DIR = ROOT / "data" / "model_comparison"

NANO = "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"

# Same banding as the orchestrator and run_massive_benchmark.REVIEW_THRESHOLD: a model
# score below this is eligible for auto-clear, at or above it the case is held.
FLAG_AT = 40


def split_of(case_id: str) -> str:
    """Identical to run_massive_benchmark.split_of: dev or holdout by SHA-256."""
    return "dev" if hashlib.sha256(case_id.encode("utf-8")).digest()[0] % 2 == 0 else "holdout"


def load_cases() -> list[dict[str, Any]]:
    return json.loads(CASES_FILE.read_text(encoding="utf-8"))["cases"]


def install_empty_tavily() -> None:
    """Every search returns no results with status OK; nothing leaves the process."""
    from vf_logistics import tavily_client

    async def search_with_status(query, max_results=5, **kwargs):
        return [], tavily_client.OK

    async def search(query, max_results=5, **kwargs):
        return []

    async def search_cached(query, max_results=5, *, ttl_seconds=0, **kwargs):
        return [], tavily_client.OK, False

    tavily_client.search_with_status = search_with_status  # type: ignore[assignment]
    tavily_client.search = search  # type: ignore[assignment]
    tavily_client.search_cached = search_cached  # type: ignore[assignment]


def rate(successes: int, n: int) -> dict[str, Any]:
    """A rate with its 95% Wilson interval, as evaluation.py computes them."""
    from vf_logistics.evaluation import wilson

    ci = wilson(successes, n)
    return {
        "count": successes,
        "of": n,
        "rate": round(successes / n, 4) if n else None,
        "ci95": list(ci) if ci else None,
    }


def write_report(name: str, report: dict[str, Any]) -> pathlib.Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / name
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
