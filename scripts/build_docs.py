#!/usr/bin/env python3
"""
Write docs/swagger.json from the Pydantic request and response models.

Run
    python scripts/build_docs.py

Why this is generated rather than written
----------------------------------------
A hand-maintained OpenAPI file is accurate on the day it is written and wrong
within a month. It is the kind of wrong that does real damage too: an integrator
codes against the document, their payload is rejected by a field the document
never mentioned, and the failure looks like our bug because in the only sense that
matters it is.

So the spec is derived from vf_logistics.schemas -- the same classes the routes
validate against. A field cannot appear in the document without existing in the
model, and cannot change meaning in the model without changing in the document.

The route also serves it live at GET /api/v1/openapi.json, unauthenticated, so an
integrator can fetch the contract before they have credentials. The committed file
is for reading in a browser and for diffing in review: a pull request that changes
the customer-facing contract shows that change as a diff rather than hiding it
inside a model edit.
"""

from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from vf_logistics import openapi  # noqa: E402

REF_KEY = "$" + "ref"


def collect_refs(node, into: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == REF_KEY and isinstance(value, str):
                into.add(value.rsplit("/", 1)[-1])
            else:
                collect_refs(value, into)
    elif isinstance(node, list):
        for item in node:
            collect_refs(item, into)


def main() -> int:
    spec = openapi.build_spec()

    out = ROOT / "docs" / "swagger.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(spec, indent=2) + "\n", encoding="utf-8")

    print(f"wrote {out.relative_to(ROOT)}")
    print(f"  openapi {spec['openapi']}")
    print(f"  paths   {len(spec['paths'])}")
    for path, operations in sorted(spec["paths"].items()):
        methods = " ".join(sorted(m.upper() for m in operations))
        print(f"    {methods:<6} {path}")

    schemas = spec.get("components", {}).get("schemas", {})
    print(f"  schemas {len(schemas)}")
    for name in sorted(schemas):
        print(f"    {name}")

    refs: set[str] = set()
    collect_refs(spec, refs)
    dangling = sorted(refs - set(schemas))
    if dangling:
        # A dangling reference renders as an empty box in Swagger UI and as a
        # missing type in a generated client, so it fails the build rather than
        # shipping a document that looks complete.
        print(f"\nERROR: unresolved references: {dangling}", file=sys.stderr)
        return 1
    print("  unresolved references: none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
