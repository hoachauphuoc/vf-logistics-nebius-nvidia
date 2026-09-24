"""
Check docs/DEMO_SCRIPT.md quotes the narration that SCENES actually synthesises.

Nothing else validates this. `build_narration.py` never opens the markdown, the
markdown is a hand-maintained copy, and the document says so itself -- "if you
change one, change both". That instruction has been followed by hand up to now,
which is the same arrangement that let the nine-clip table, the per-clip
blockquotes and the cumulative timecodes drift apart from each other.

Checks three things:
  1. every scene's narration appears verbatim as a blockquote, ignoring the
     line wrapping the markdown adds
  2. the length table, the summary block and SCENES agree on every clip length
  3. the cumulative timecode in each clip heading is the running sum of the
     lengths before it -- the old script had clip 5 starting at 0:49, repeating
     clip 4's start

    python scripts/check_demo_script_sync.py
"""

from __future__ import annotations

import importlib.util
import os
import re
import sys

# The document is full of em-dashes and arrows and a Windows console is cp1252, so
# printing one crashes with UnicodeEncodeError -- which killed this script mid-report
# and looked like "no output" rather than like a failure. Patterns may contain them;
# output must not.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DOC = os.path.join(ROOT, "docs", "DEMO_SCRIPT.md")


def load_scenes():
    path = os.path.join(HERE, "build_narration.py")
    spec = importlib.util.spec_from_file_location("_bn_for_sync", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SCENES


def flatten(text: str) -> str:
    """Collapse whitespace so markdown's line wrapping does not count as a difference."""
    return re.sub(r"\s+", " ", text).strip()


def main() -> int:
    scenes = load_scenes()
    doc = open(DOC, encoding="utf-8").read()
    problems = 0

    # 1. narration text, verbatim
    quotes = [
        flatten(re.sub(r"^>\s?", "", block, flags=re.M))
        for block in re.findall(r"(?:^>.*\n)+", doc, flags=re.M)
    ]
    print(f"{len(scenes)} scenes, {len(quotes)} blockquotes in the document\n")
    for name, _clip, text in scenes:
        if flatten(text) in quotes:
            print(f"  ok      {name}")
        else:
            print(f"  MISSING {name}")
            print(f"          SCENES says: {flatten(text)[:100]}...")
            problems += 1

    # 2. clip lengths, in three places
    table = [int(n) for n in re.findall(r"^\| \d+ \| [^|]+\| (\d+)s \|", doc, flags=re.M)]
    summary = [int(n) for n in re.findall(r"\d+:\s*(\d+)s", doc)]
    actual = [int(c) for _n, c, _t in scenes]

    print()
    if table == actual:
        print(f"  ok      length table matches SCENES {actual}")
    else:
        print(f"  MISMATCH length table {table} vs SCENES {actual}")
        problems += 1

    if summary == actual:
        print("  ok      summary block matches SCENES")
    else:
        print(f"  MISMATCH summary block {summary} vs SCENES {actual}")
        problems += 1

    total = sum(actual)
    stated = re.findall(r"\*\*(\d+)s\*\*", doc) + re.findall(r"total (\d+)s", doc)
    wrong = [s for s in stated if int(s) != total]
    if wrong:
        print(f"  MISMATCH document states total(s) {wrong}, SCENES sums to {total}")
        problems += 1
    else:
        print(f"  ok      stated totals all agree with {total}s")

    # 3. cumulative timecodes in the clip headings
    print()
    heads = re.findall(r"^## Clip (\d+) — .*?\((\d+):(\d+) → (\d+):(\d+), (\d+)s\)",
                       doc, flags=re.M)
    if len(heads) != len(actual):
        print(f"  MISMATCH {len(heads)} clip headings for {len(actual)} scenes")
        problems += 1
    running = 0
    for (num, sm, ss, em, es, length), clip in zip(heads, actual):
        start, end = int(sm) * 60 + int(ss), int(em) * 60 + int(es)
        issues = []
        if start != running:
            issues.append(f"starts {start}s, expected {running}s")
        if int(length) != clip:
            issues.append(f"says {length}s, SCENES says {clip:.0f}s")
        if end - start != clip:
            issues.append(f"span {end - start}s does not match {clip:.0f}s")
        if issues:
            print(f"  BAD     clip {num}: " + "; ".join(issues))
            problems += 1
        else:
            print(f"  ok      clip {num}: {sm}:{ss} -> {em}:{es} ({length}s)")
        running += clip

    print()
    if problems:
        print(f"{problems} problem(s). The script is the authority -- fix the markdown.")
        return 1
    print("In sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
