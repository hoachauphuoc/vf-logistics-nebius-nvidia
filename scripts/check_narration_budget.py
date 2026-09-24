"""
Offline pre-check for the narration budget.

Exists because the real fit check in build_narration.py runs AFTER the billable
Google TTS call, prints to stdout only, and exits 0 even when a scene overruns --
so without this you pay for a full nine-, now ten-scene synthesis run to discover
that one scene is half a second long.

It reads SCENES out of build_narration.py directly rather than duplicating the
text, because a copy of the narration is exactly the kind of drift the demo script
documentation already suffers from.

The estimate is words / 2.5 plus the fixed per-scene overhead, which IS exactly
computable: 0.6s lead-in plus 0.25s after every sentence but the last. Speech
duration is not knowable without the API; 2.5 words/second is the conservative
figure (the old scene 3 sat at 2.59 and fitted).

    python scripts/check_narration_budget.py
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

WPS = 2.5
BUDGET_LO, BUDGET_HI = 150.0, 165.0
HARD_CEILING = 180.0


def load_scenes():
    path = os.path.join(os.path.dirname(__file__), "build_narration.py")
    spec = importlib.util.spec_from_file_location("_bn_for_budget", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCENES, module.LEAD_IN_S, module.GAP_AFTER_SENTENCE_S, path


def sentences(text: str) -> list[str]:
    # Same rule as build_narration.split_sentences: an ender FOLLOWED BY whitespace.
    return [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]


def main() -> int:
    scenes, lead_in, gap, path = load_scenes()

    print(f"{len(scenes)} scenes read from {os.path.relpath(path)}")
    print(f"lead-in {lead_in}s, gap {gap}s, estimating at {WPS} words/second\n")
    print(f"{'at':>6}  {'scene':32s} {'clip':>5} {'sent':>4} {'words':>5} "
          f"{'needs':>6} {'slack':>6}")

    start = total_clip = total_need = 0.0
    thin: list[str] = []
    over: list[str] = []

    for name, clip, text in scenes:
        sents = sentences(text)
        words = len(text.split())
        needs = lead_in + (len(sents) - 1) * gap + words / WPS
        slack = clip - needs
        if slack < 0:
            over.append(f"{name} ({slack:+.1f}s)")
        elif slack < 1.0:
            thin.append(f"{name} ({slack:+.1f}s)")
        stamp = f"{int(start) // 60}:{int(start) % 60:02d}"
        flag = "  OVER" if slack < 0 else ("  thin" if slack < 1.0 else "")
        print(f"{stamp:>6}  {name:32s} {clip:>5.0f} {len(sents):>4} {words:>5} "
              f"{needs:>6.1f} {slack:>+6.1f}{flag}")
        start += clip
        total_clip += clip
        total_need += needs

    mm, ss = int(total_clip) // 60, int(total_clip) % 60
    print(f"\ntotal clip {total_clip:.0f}s = {mm}:{ss:02d}   "
          f"estimated speech {total_need:.1f}s   slack {total_clip - total_need:+.1f}s")

    problems = 0

    if over:
        print("\nOVERRUNS -- shorten the writing, not the read:")
        for line in over:
            print(f"  {line}")
        print("  An overrun is not contained: build_narration advances the timeline by")
        print("  max(clip, spoken), so every later scene drifts off its cut.")
        problems += 1

    if thin:
        print("\nUnder a second of headroom (2.5 w/s is an estimate, not a measurement):")
        for line in thin:
            print(f"  {line}")

    if not BUDGET_LO <= total_clip <= BUDGET_HI:
        print(f"\nTotal is outside the {BUDGET_LO:.0f}-{BUDGET_HI:.0f}s shooting budget.")
        problems += 1

    if total_clip >= HARD_CEILING:
        print(f"\nTotal is at or over {HARD_CEILING:.0f}s. The rules ask for a video "
              f"'less than three (3) minutes'.")
        problems += 1

    # A missing trailing space between concatenated fragments silently merges two
    # sentences into one timing unit and one caption, because splitting needs
    # whitespace after the full stop.
    source = open(path, encoding="utf-8").read()
    merged = re.findall(r'"[^"\n]*[.!?]"\s*\n\s*"[A-Z]', source)
    if merged:
        print(f"\n{len(merged)} fragment join(s) end a sentence with no trailing space.")
        print("  Sentence splitting needs whitespace after the ender, so those two")
        print("  sentences will be timed and captioned as one.")
        problems += 1

    if problems == 0:
        print("\nOK. Safe to spend a TTS run.")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
