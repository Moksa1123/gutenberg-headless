#!/usr/bin/env python3
"""Report every Elementor control in a page that the converter does NOT read.

    python tools/audit-coverage.py _elementor_data.json
    python tools/audit-coverage.py _elementor_data.json --all   # include handled

WHY THIS EXISTS
A converted page can validate, round-trip byte-identically, and still be wrong,
because a dropped control is silent at every stage: no error, no warning, just
a setting that never became CSS. Every fidelity bug found on the reference page
was one of these, and each was found by NOTICING it in a screenshot - which
does not scale and does not finish.

This inverts the search. Instead of looking at the rendered page and asking
"what looks off", it reads the SOURCE and asks "which of these settings did the
converter never even look at". That list is finite, and it can be driven to
the point where everything left on it is a deliberate, named decision.

The check is a real dry run: it converts the tree with instrumentation on the
lookups, so a control counts as handled only if the converter genuinely read
it - not if it merely appears in some table.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import el2blocks as E  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Controls that carry no visual meaning for a converted page. Named here so the
# report is a list of DECISIONS, not noise.
IGNORED = {
    "_title", "_id", "_element_id", "_css_classes", "content_width",
    "__globals__", "__dynamic__", "_element_cache_ttl",
    # `*_typography` is the group's "use custom typography" FLAG (its value is
    # the literal string "custom"), not a value of its own - the sizes and
    # families it unlocks are separate controls and are checked on their own.
    "typography_typography", "icon_typography_typography",
}
IGNORED_PREFIX = ("__", "_transform_", "_animation", "motion_fx", "sticky",
                  "_background_hover", "e_", "advanced_rules")


# Controls that ARE dropped, on purpose, with the reason. Keeping them out of
# the "not read" list is only honest if the reason is written down, so they get
# their own section in the report rather than disappearing.
DELIBERATE = {
    ("html", "_element_width"):
        "core/html emits the raw markup with no wrapper of its own, so there is "
        "no element to carry a width; measured at 390/820/1440, the SVGs land at "
        "the same size and position as the original without it",
    ("button", "selected_icon"):
        "Font Awesome is not loaded on a block page - reported as a warning by "
        "the converter so the icon can be re-added as an inline SVG",
}


def interesting(ctrl: str) -> bool:
    if ctrl in IGNORED:
        return False
    return not ctrl.startswith(IGNORED_PREFIX)


def collect(els, out, path=""):
    for i, e in enumerate(els):
        who = e.get("widgetType") or e.get("elType") or "?"
        for ctrl, val in (e.get("settings") or {}).items():
            if val in (None, "", [], {}):
                continue
            out.append((who, ctrl))
        collect(e.get("elements") or [], out, f"{path}{i}.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--all", action="store_true", help="also list the handled controls")
    ap.add_argument("--el-skill", type=Path,
                    default=Path("~/.claude/skills/elementor-headless").expanduser())
    a = ap.parse_args()

    tree = json.loads(Path(a.file).read_text(encoding="utf-8"))

    present = []
    collect(tree, present)

    # Instrument the two lookups every mapped control must pass through, then
    # convert for real. Anything that never appears in `read` was not consumed.
    read: set[tuple[str, str]] = set()

    real_auto, real_resp = E.auto_style, E.responsive_css

    def spy_auto(st, widget, settings, elmap, cssmap, **kw):
        before = dict(settings)
        real_auto(st, widget, settings, elmap, cssmap, **kw)
        for ctrl in before:
            base, bp = E.split_breakpoint(ctrl)
            if ctrl.startswith("hide_") or base in E.LAYOUT_HANDLED or base in E.UNSUPPORTED:
                read.add((widget, ctrl))
            elif elmap.get((widget, base)) or bp:
                read.add((widget, ctrl))
    E.auto_style = spy_auto

    # The container/widget converters also read settings directly (width,
    # flex_gap, flex_grow, background_*, and every widget's own content keys).
    # Capture those by watching dict access on a proxy.
    class Spy(dict):
        def __init__(self, d, who):
            super().__init__(d)
            self._who = who

        def get(self, k, default=None):
            if k in self:
                read.add((self._who, k))
            return super().get(k, default)

        def __getitem__(self, k):
            read.add((self._who, k))
            return super().__getitem__(k)

    def wrap(els):
        for e in els:
            who = e.get("widgetType") or e.get("elType") or "?"
            if isinstance(e.get("settings"), dict):
                e["settings"] = Spy(e["settings"], who)
            wrap(e.get("elements") or [])
    wrap(tree)

    ctx = {"elmap": E.load_el_css_map(a.el_skill if a.el_skill.exists() else None),
           "cssmap": E.css_to_style_path()}
    for e in tree:
        E.convert_element(e, ctx)
    E.auto_style = real_auto
    E.responsive_css = real_resp

    counts = collections.Counter(present)
    handled = {k: n for k, n in counts.items() if k in read and interesting(k[1])}
    rest = {k: n for k, n in counts.items()
            if k not in read and interesting(k[1])}
    deliberate = {k: n for k, n in rest.items() if k in DELIBERATE}
    missed = {k: n for k, n in rest.items() if k not in DELIBERATE}

    total = sum(counts.values())
    nh, nd, nm = sum(handled.values()), sum(deliberate.values()), sum(missed.values())
    print(f"{total} control values set on this page")
    print(f"  {nh:5} read by the converter")
    print(f"  {nd:5} dropped ON PURPOSE (reason recorded below)")
    print(f"  {nm:5} NOT read  <- every one of these is silently dropped")
    print(f"  {total - nh - nd - nm:5} ignored by policy (ids, classes, editor-only)")
    print("=" * 78)

    if deliberate:
        print("\nDROPPED ON PURPOSE")
        for (who, ctrl), n in sorted(deliberate.items()):
            print(f"    x{n:<4} {who}.{ctrl}\n           {DELIBERATE[(who, ctrl)]}")

    if missed:
        by_widget = collections.defaultdict(list)
        for (who, ctrl), n in missed.items():
            by_widget[who].append((n, ctrl))
        for who in sorted(by_widget, key=lambda w: -sum(n for n, _ in by_widget[w])):
            rows = sorted(by_widget[who], reverse=True)
            print(f"\n{who}  ({sum(n for n, _ in rows)} values)")
            for n, ctrl in rows:
                print(f"    x{n:<4} {ctrl}")
    else:
        print("\nEvery control on this page is read by the converter.")

    if a.all and handled:
        print("\n" + "-" * 78 + "\nHANDLED")
        for (who, ctrl), n in sorted(handled.items(), key=lambda x: (-x[1], x[0])):
            print(f"    x{n:<4} {who}.{ctrl}")
    return 1 if missed else 0


if __name__ == "__main__":
    sys.exit(main())
