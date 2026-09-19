"""
Tavily search client.

A minimal wrapper around Tavily's REST search API used by the compliance
agent to pull a live web signal (news, sanctions-list mentions, shell-company
reporting) for the shipper and receiver named in a shipment - something the
original Gemini-only design only ever simulated via the model's own training
knowledge. httpx is already a project dependency, so no new HTTP library is
introduced.
"""

from __future__ import annotations

import os
from typing import Any

import httpx

TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")
TAVILY_URL = "https://api.tavily.com/search"


async def search(query: str, max_results: int = 5) -> list[dict[str, Any]]:
    """
    Run a Tavily search and return a list of {title, url, content} results.

    Returns an empty list (rather than raising) when TAVILY_API_KEY is unset or
    the request fails, so a Tavily outage degrades the compliance agent to its
    pre-Tavily behaviour instead of blocking the pipeline.
    """
    if not TAVILY_API_KEY or not query.strip():
        return []

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                TAVILY_URL,
                headers={"Authorization": f"Bearer {TAVILY_API_KEY}"},
                json={
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "basic",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []

    results = data.get("results") or []
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("url", ""),
            "content": (r.get("content") or "")[:500],
        }
        for r in results
    ]


def format_findings(results: list[dict[str, Any]]) -> str:
    """Render Tavily results as a labelled, untrusted-evidence text block."""
    if not results:
        return "No external web search findings (Tavily returned nothing or is unavailable)."
    lines = []
    for r in results:
        lines.append(f"  - {r['title']}: {r['content']} ({r['url']})")
    return "\n".join(lines)
