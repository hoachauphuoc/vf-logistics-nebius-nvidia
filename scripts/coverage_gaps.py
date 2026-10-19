"""
List what a coverage run did not execute, by file and by the function that owns each line, so a gap
becomes a named piece of work instead of a percentage.

  python -m pytest tests --cov=vf_logistics --cov-report=json:cov.json
  python scripts/coverage_gaps.py cov.json                      the files with the most missed lines
  python scripts/coverage_gaps.py cov.json src/vf_logistics/app.py    one file, by function
"""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path


def owners(source: str) -> list[tuple[int, int, str]]:
    """(first line, last line, dotted name) of every function and method, innermost last."""
    found: list[tuple[int, int, str]] = []

    def walk(node: ast.AST, prefix: str) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}{child.name}"
                if not isinstance(child, ast.ClassDef):
                    found.append((child.lineno, child.end_lineno or child.lineno, name))
                walk(child, name + ".")
            else:
                walk(child, prefix)

    walk(ast.parse(source), "")
    return sorted(found)


def by_function(path: str, missing: list[int]) -> list[tuple[int, str, list[int]]]:
    """(missed lines, function, the lines) for each function with a gap, biggest first."""
    spans = owners(Path(path).read_text(encoding="utf-8"))
    grouped: dict[str, list[int]] = {}
    for line in missing:
        inside = [s for s in spans if s[0] <= line <= s[1]]
        name = min(inside, key=lambda s: s[1] - s[0])[2] if inside else "(module level)"
        grouped.setdefault(name, []).append(line)
    return sorted(((len(v), k, v) for k, v in grouped.items()), reverse=True)


def spans_of(lines: list[int]) -> str:
    """12-15, 20, 31-33 from a list of line numbers."""
    out: list[str] = []
    start = prev = lines[0]
    for n in lines[1:] + [None]:  # type: ignore[list-item]
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ", ".join(out)


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__)
        return 2
    data = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    files = data["files"]
    if len(argv) == 1:
        rows = sorted(((len(v["missing_lines"]), k, v["summary"]["num_statements"]) for k, v in files.items()), reverse=True)
        total = sum(r[0] for r in rows)
        statements = sum(r[2] for r in rows)
        print(f"{total} lines missed of {statements} = {100 * (1 - total / statements):.2f}% covered")
        for missed, name, count in rows[:25]:
            print(f"{missed:5d} of {count:5d}  {name}")
        return 0
    key = next(k for k in files if k.replace("\\", "/").endswith(argv[1].replace("\\", "/")))
    for missed, name, lines in by_function(key, files[key]["missing_lines"]):
        print(f"{missed:4d}  {name}  [{spans_of(lines)}]")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
