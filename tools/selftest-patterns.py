#!/usr/bin/env python3
"""Run the validator's rules over every pattern WordPress itself ships.

    python tools/selftest-patterns.py
    python tools/selftest-patterns.py --all        # list every finding
    python tools/selftest-patterns.py --code E-PRESET

WHY
Every other check in this repo asks whether a page agrees with the model. This
one asks whether the MODEL agrees with WordPress. A pattern's content is
serialized block markup written by core, by WooCommerce and by the theme -
86 of them on the reference site - which makes it the largest corpus of
canonical markup the target site has. If the validator's rules are right,
core's own markup passes.

It is run in `--pattern` mode, because a pattern is not stored post_content: it
is parsed and re-serialized before it ever becomes page content, so its HTML is
only a parsing vehicle. Measured: a group whose comment declares padding and
whose HTML carries no style attribute parses as valid and reserializes WITH
`style="padding-top:100px"`. The same markup stored as post_content is a real
defect, because the front end renders the HTML verbatim.

WHAT IT FOUND
Two validator bugs, both fixed:
  - `"dimensions":{"minHeight":""}` - an explicitly empty value is "not set",
    and the validator was demanding `min-height:` with no value.
  - a sourced attribute duplicated in the comment was reported as an ERROR.
    Core's own patterns do it 22 times; when the HTML carries the same value it
    is redundant, not broken (W-SOURCED).

And four things that are true of WordPress's own content:
  - 30 preset slugs that do not exist on a classic-theme site, so those
    patterns really do style nothing here;
  - 29 attributes belonging to a DEPRECATED form of their block;
  - 22 redundant sourced copies;
  - 5 duplicate anchors inside a single pattern.
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import blockmark  # noqa: E402
import gblib      # noqa: E402

_spec = importlib.util.spec_from_file_location("vp", HERE / "validate-post.py")
vp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(vp)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--patterns", default=str(HERE.parent / "data" / "patterns.json"))
    ap.add_argument("--schema")
    ap.add_argument("--code", help="show every finding with this code")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()

    path = Path(a.patterns)
    if not path.exists():
        sys.exit(f"{path} not found - extract it with tools/extract-patterns.php")
    data = json.loads(path.read_text(encoding="utf-8"))
    schema = gblib.load_schema(a.schema)

    codes = collections.Counter()
    by_code = collections.defaultdict(list)
    clean = 0
    total = 0
    for p in data["patterns"]:
        if not p["content"].strip():
            continue
        total += 1
        try:
            tree = blockmark.parse(p["content"])
        except Exception as e:
            codes["PARSE-CRASH"] += 1
            by_code["PARSE-CRASH"].append((p["name"], str(e)[:100]))
            continue
        rep = vp.Report()
        try:
            # A pattern is parsed, never rendered - see the module docstring.
            vp.validate(tree, schema, rep, pattern=True)
        except Exception as e:
            codes["VALIDATOR-CRASH"] += 1
            by_code["VALIDATOR-CRASH"].append((p["name"], f"{type(e).__name__}: {e}"[:100]))
            continue
        rows = rep.errors + rep.warnings
        if not rows:
            clean += 1
            continue
        for r in rows:
            code, rest = r.split(None, 1)
            codes[code] += 1
            by_code[code].append((p["name"], rest.strip()))

    print(f"{total} patterns from {data.get('site_url', '?')}")
    print(f"  {clean} completely clean   {total - clean} with findings")
    if codes["VALIDATOR-CRASH"] or codes["PARSE-CRASH"]:
        print("  a CRASH is always this repo's bug, never WordPress's")
    print("=" * 88)

    show = [a.code] if a.code else list(codes)
    for code in show:
        rows = by_code.get(code) or []
        if not rows:
            continue
        print(f"\n{code}  x{len(rows)}")
        for name, msg in (rows if (a.all or a.code) else rows[:3]):
            print(f"    {name[:32]:34} {msg[:110]}")
        if not (a.all or a.code) and len(rows) > 3:
            print(f"    ... {len(rows) - 3} more (--code {code})")
    return 1 if (codes["VALIDATOR-CRASH"] or codes["PARSE-CRASH"]) else 0


if __name__ == "__main__":
    sys.exit(main())
