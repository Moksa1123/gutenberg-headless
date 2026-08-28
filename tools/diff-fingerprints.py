#!/usr/bin/env python3
"""Diff two page fingerprints and report every real visual difference.

    # collect at the SAME viewport width on both pages (tools/collect-fingerprint.js)
    python tools/diff-fingerprints.py original.json converted.json
    python tools/diff-fingerprints.py original.json converted.json --all

Answers the question a screenshot cannot: *which properties, on which
elements, actually render differently* - and separates that from the many
differences that are only two spellings of the same thing.

WHY THIS EXISTS
"It looks about right" is not a verification. Building the Elementor converter,
every single visual bug that shipped was one a glance had already approved:
a whole type scale shrunk 20% by fluid typography, 25 list items inheriting the
theme's colour, six 1px dividers rendered as full boxes. Each was obvious in a
property diff and invisible in a thumbnail.

WHAT COUNTS AS EQUIVALENT (not reported)
  start/left, end/right               - the same computed alignment
  minHeight 0px/auto                  - the same "no minimum"
  normal/400, bold/700 (fontWeight)   - the same weight
  sub-pixel geometry within 3px       - layout rounding, not a difference
  a differing `tag` on the same text  - Elementor wraps text in <span>, blocks
                                        put it on the element itself; those are
                                        compared as BOXES (geometry + box
                                        decoration), never as typography
"""
from __future__ import annotations

import argparse
import collections
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Properties that describe the BOX rather than the text inside it - the only
# ones that can be compared across a tag mismatch.
BOX_PROPS = {
    "backgroundColor", "backgroundImage", "borderTopWidth", "borderRightWidth",
    "borderBottomWidth", "borderLeftWidth", "borderTopColor", "borderRadius",
    "boxShadow", "display", "flexDirection", "flexWrap", "justifyContent",
    "alignItems", "rowGap", "columnGap", "maxWidth", "minHeight", "overflow",
    "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
}
GEOMETRY = {"w", "h", "x", "y"}
IGNORE = {"key", "tag"}

# Properties whose value follows from WHICH ELEMENT was used, not from the
# design. Elementor lays a list out as <span>s inside padded divs; blocks use a
# real <ul>/<li>. The two render identically - same size, colour, height - but
# a <li> is display:list-item with its indent in the marker box, while a <span>
# is display:block with a 5px text pad. Reporting those as 50 differences
# buries the ones that matter, so they are excluded ACROSS a tag mismatch only:
# on same-tag pairs every one of them is still compared.
STRUCTURAL = {"display", "paddingLeft", "paddingRight", "paddingTop", "paddingBottom"}

EQUIVALENT = [
    {"start", "left"}, {"end", "right"},
    {"0px", "auto"},                    # minHeight
    {"normal", "400"}, {"bold", "700"},
]


def equivalent(prop, a, b):
    if a == b:
        return True
    for pair in EQUIVALENT:
        if {a, b} == pair:
            return True
    if prop in GEOMETRY:
        try:
            return abs(int(float(a)) - int(float(b))) <= 3
        except (TypeError, ValueError):
            return False
    return False


def load(path):
    raw = json.loads(open(path, encoding="utf-8").read())
    if isinstance(raw, str):
        raw = json.loads(raw)
    if isinstance(raw, dict) and "elements" in raw:
        return raw["elements"], raw
    return raw, {}


def renumber_boxes(rows):
    """Text-less elements are keyed BOX@<y>x<width>, and y shifts the moment
    anything above them changes height - which unpairs every box on the page
    and hides the differences inside them. Re-key them by document order and
    width instead, so a box still pairs with its counterpart after a rhythm
    change."""
    seq = collections.Counter()
    for r in sorted(rows, key=lambda x: (x.get("y", 0), x.get("x", 0))):
        if not str(r["key"]).startswith("BOX@"):
            continue
        w = r.get("w", 0)
        seq[w] += 1
        r["key"] = f"BOX[w{w}]#{seq[w]}"
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("original")
    ap.add_argument("converted")
    ap.add_argument("--all", action="store_true", help="list every differing element, not a summary")
    a = ap.parse_args()

    A_list, A_meta = load(a.original)
    B_list, B_meta = load(a.converted)
    A_list, B_list = renumber_boxes(A_list), renumber_boxes(B_list)
    A = {r["key"]: r for r in A_list}
    B = {r["key"]: r for r in B_list}

    if A_meta.get("viewport") and B_meta.get("viewport") and A_meta["viewport"] != B_meta["viewport"]:
        print(f"REFUSING: collected at different viewports "
              f"({A_meta['viewport']} vs {B_meta['viewport']}). Re-collect at the same width.")
        return 2

    common = [k for k in A if k in B]
    missing, extra = sorted(set(A) - set(B)), sorted(set(B) - set(A))
    print(f"original {len(A)} elements | converted {len(B)} | paired {len(common)}")
    if A_meta.get("pageHeight") and B_meta.get("pageHeight"):
        d = B_meta["pageHeight"] - A_meta["pageHeight"]
        print(f"page height {A_meta['pageHeight']} -> {B_meta['pageHeight']} "
              f"({d:+d}px, {d / A_meta['pageHeight'] * 100:+.1f}%)")
    if missing:
        print(f"MISSING from converted ({len(missing)}): " + " | ".join(m[:20] for m in missing[:6]))
    if extra:
        print(f"EXTRA in converted ({len(extra)}): " + " | ".join(m[:20] for m in extra[:6]))
    print()

    diffs = collections.defaultdict(list)
    for k in common:
        ra, rb = A[k], B[k]
        cross_tag = ra["tag"] != rb["tag"]
        for p in ra:
            if p in IGNORE:
                continue
            if cross_tag and p not in BOX_PROPS:
                continue          # typography across a tag mismatch is meaningless
            if cross_tag and p in STRUCTURAL:
                continue          # see STRUCTURAL: different element, same result
            va, vb = str(ra.get(p)), str(rb.get(p))
            if not equivalent(p, va, vb):
                diffs[p].append((k, va, vb))

    y_shifts = len(diffs.pop("y", []))
    total = sum(len(v) for v in diffs.values())
    comparable = sum(1 for k in common if A[k]["tag"] == B[k]["tag"])
    print(f"comparable pairs: {comparable} same-tag, {len(common) - comparable} cross-tag (box-only)")
    print(f"REAL DIFFERENCES: {total}"
          + (f"   (+{y_shifts} y-position shifts, downstream of the above)" if y_shifts else ""))
    print("=" * 88)
    for p, rows in sorted(diffs.items(), key=lambda x: -len(x[1])):
        print(f"\n{p}  ({len(rows)})")
        for k, va, vb in (rows if a.all else rows[:4]):
            print(f"    {k[:26]:28} orig={va[:26]:28} conv={vb[:26]}")
        if not a.all and len(rows) > 4:
            print(f"    … {len(rows) - 4} more (--all to list)")
    if not total:
        print("\nNo real differences. The converted page renders like the original.")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
