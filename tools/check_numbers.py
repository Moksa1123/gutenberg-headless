#!/usr/bin/env python3
"""
check_numbers.py - every number in SKILL.md must be accounted for and match the data.

skill-SOP 6-1: numbers that change (versions, counts, dates) are not hand-written
unchecked. This is a whitelist, not a spot check: every number in SKILL.md
(outside code blocks, inline `code` and URLs) must be claimed by a rule below,
or the check fails. Adding a number means adding a rule.

Rule kinds:
    fact   computed from data/ (block-schema.json, editor-surface.json,
           roundtrip-verification.csv), examples/ and package.json - the same
           values `gb.py stats` prints; --fix rewrites SKILL.md when they drift
    fixed  not from the data (historical measurement, product generation, pass
           criterion); the reason is written next to it

Engine copied from line-api / elementor-headless check_numbers.py; only FACTS
and RULES are ours.

    python tools/check_numbers.py          # exit 1 on any problem
    python tools/check_numbers.py --fix    # rewrite drifted facts in SKILL.md
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
SKILL_MD = ROOT / "SKILL.md"

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------------------
# This skill's facts and rules
# ---------------------------------------------------------------------------
def _facts() -> dict:
    sys.path.insert(0, str(HERE))
    import blockmark

    s = json.loads((DATA / "block-schema.json").read_text(encoding="utf-8"))
    blocks = s["blocks"]
    sourced = {n for n, b in blocks.items()
               if any(a.get("source") for a in (b.get("attributes") or {}).values())}
    dyn = {n for n, b in blocks.items() if b["is_dynamic"]}
    ns = {}
    for n in blocks:
        ns[n.split("/")[0]] = ns.get(n.split("/")[0], 0) + 1
    verdict = {}
    for b in blocks.values():
        verdict[b.get("render_verdict")] = verdict.get(b.get("render_verdict"), 0) + 1

    sf = json.loads((DATA / "editor-surface.json").read_text(encoding="utf-8"))["blocks"]
    trans = sum(len(b["transforms"]["from"]) + len(b["transforms"]["to"])
                for b in sf.values() if b.get("transforms"))

    with (DATA / "roundtrip-verification.csv").open(encoding="utf-8", newline="") as f:
        rt = list(csv.DictReader(f))
    rt_date = re.search(r"\d{4}-\d\d-\d\d", rt[0]["measured_on"]).group(0)

    demo = blockmark.parse((ROOT / "examples" / "demo-page.html").read_text(encoding="utf-8"))
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))

    return {
        "version": pkg["version"],
        "wp": s["wp_version"],
        "theme": s["theme"]["version"],
        "extracted": s["extracted_at"][:10],
        "blocks": str(len(blocks)),
        "core": str(ns.get("core", 0)),
        "woo": str(ns.get("woocommerce", 0)),
        "blocksy": str(ns.get("blocksy", 0)),
        "patterns": str(len(s.get("patterns", []))),
        "renders": str(verdict.get("renders", 0)),
        "empty": str(verdict.get("empty", 0)),
        "content": str(verdict.get("content-block", 0)),
        "dynamic": str(len(dyn)),
        "fam_content": str(len(sourced)),
        "fam_static": str(len(set(blocks) - dyn - sourced)),
        "fam_dynamic": str(len(dyn - sourced)),
        "editor": str(len(sf)),
        "variations": str(sum(len(b.get("variations") or []) for b in sf.values())),
        "transforms": str(trans),
        "deprecated": str(sum(len(b.get("deprecated") or []) for b in sf.values())),
        "absent": str(len(set(blocks) - set(sf))),
        "rt_posts": str(len(rt)),
        "rt_kb": str(round(sum(int(r["bytes"]) for r in rt) / 1000)),
        "rt_date": rt_date,
        "demo": str(sum(1 for _ in blockmark.walk(demo))),
    }


# (regex, kind, arg). Group 1 is the claimed number; no group claims the whole match.
# Every number inside a matched span counts as claimed.
RULES: list[tuple[str, str, str]] = [
    # ---- from the data ----
    (r'^version: "(\d+\.\d+\.\d+)"', "fact", "version"),
    (r"WP (\d+\.\d+), Blocksy", "fact", "wp"),
    (r"Blocksy (\d+\.\d+\.\d+), extracted", "fact", "theme"),
    (r"extracted (\d{4}-\d\d-\d\d)\*\*", "fact", "extracted"),
    (r"\((\d+) block types, every attribute", "fact", "blocks"),
    (r"^\| Size \| (\d+) block types", "fact", "blocks"),
    (r"block types \((\d+) `core", "fact", "core"),
    (r"(\d+) `woocommerce/\*`", "fact", "woo"),
    (r"(\d+) `blocksy/\*`", "fact", "blocksy"),
    (r"(\d+) registered patterns", "fact", "patterns"),
    (r"(\d+) render, \d+ render NOTHING", "fact", "renders"),
    (r"render, (\d+) render NOTHING", "fact", "empty"),
    (r"(\d+) are content blocks", "fact", "content"),
    (r"\): (\d+) block types, \d+ variations", "fact", "editor"),
    (r"(\d+) variations, \d+ transforms", "fact", "variations"),
    (r"(\d+) transforms, \d+ deprecated forms", "fact", "transforms"),
    (r"(\d+) deprecated forms the PHP", "fact", "deprecated"),
    (r"(\d+) registered blocks are absent", "fact", "absent"),
    (r"(\d+) posts, \d+ KB", "fact", "rt_posts"),
    (r"posts, (\d+) KB", "fact", "rt_kb"),
    (r"re-measured (\d{4}-\d\d-\d\d)", "fact", "rt_date"),
    (r"\((\d+)/\d+\s+carry a render callback", "fact", "dynamic"),
    (r"\(\d+/(\d+)\s+carry a render callback", "fact", "blocks"),
    (r"^\| CONTENT-IN-HTML \(has sourced attrs\) \| (\d+) \|", "fact", "fam_content"),
    (r"^\| STATIC WRAPPER \| (\d+) \|", "fact", "fam_static"),
    (r"^\| PURE DYNAMIC \| (\d+) \|", "fact", "fam_dynamic"),
    (r"^(\d+) of \d+ blocks render NOTHING", "fact", "empty"),
    (r"^\d+ of (\d+) blocks render NOTHING", "fact", "blocks"),
    (r"\((\d+) blocks\) passes every check", "fact", "demo"),
    # ---- not from the data ----
    (r"do_blocks\(\)` on a bare page, 0 errors", "fixed", "sweep result: no block raised an error (render-verification.csv)"),
    (r"2026-11-15: self-test", "fixed", "date of the last full self-test + number check"),
    (r"WP 7\.0/7\.1 surface|7\.0/7\.1, measured", "fixed", "WordPress releases the wp71-new-surface.md measurements cover"),
    (r"exit [01]\b", "fixed", "validator pass criteria"),
    (r"wp71-new-surface\.md", "fixed", "file name in link text"),
]


# ---------------------------------------------------------------------------
# Engine (copied from line-api)
# ---------------------------------------------------------------------------
NUM = re.compile(r"\d+(?:[.,]\d+)*")
_MASKS = [
    re.compile(r"^```.*?^```", re.S | re.M),   # code blocks
    re.compile(r"`[^`\n]+`"),                  # inline code
    re.compile(r"\]\([^)\n]*\)"),              # markdown link targets
    re.compile(r"https?://[^\s)）（，、|]+"),    # URLs
]


def _masked(text: str, keep_inline: bool = False) -> str:
    """Blank out unchecked spans, keeping positions."""
    for i, rx in enumerate(_MASKS):
        if keep_inline and i == 1:
            continue
        text = rx.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return text


def check(path: Path = SKILL_MD, fix: bool = False) -> tuple[list[str], int]:
    """(problems, numbers checked). fix=True rewrites drifted facts in place."""
    text = path.read_text(encoding="utf-8")
    scan = _masked(text)
    match_view = _masked(text, keep_inline=True)
    facts = _facts()
    problems: list[str] = []
    covered: set[int] = set()
    edits: list[tuple[int, int, str]] = []

    for pattern, kind, arg in RULES:
        found = list(re.finditer(pattern, match_view, re.M))
        if not found:
            problems.append(f"rule unused (SKILL.md wording changed?): {pattern}")
            continue
        for m in found:
            span = m.span(1) if m.re.groups else m.span()
            covered.update(range(*m.span()))
            if kind == "fact":
                got, want = text[span[0]:span[1]], facts[arg]
                if got != want:
                    problems.append(f"fact {arg}: SKILL.md says {got}, data says {want}")
                    edits.append((span[0], span[1], want))

    line_of = lambda pos: text.count("\n", 0, pos) + 1  # noqa: E731
    for m in NUM.finditer(scan):
        if not any(i in covered for i in range(*m.span())):
            problems.append(f"line {line_of(m.start())}: {m.group(0)} is not claimed by any rule")

    if fix and edits:
        for start, end, want in sorted(edits, reverse=True):
            text = text[:start] + want + text[end:]
        path.write_text(text, encoding="utf-8", newline="\n")
    return problems, sum(1 for _ in NUM.finditer(scan))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--fix", action="store_true", help="rewrite drifted facts in SKILL.md")
    args = ap.parse_args()
    problems, n = check(fix=args.fix)
    if not problems:
        print(f"all {n} numbers in SKILL.md are claimed and match the data.")
        return 0
    print(f"SKILL.md has {len(problems)} number problem(s):")
    for p in problems:
        print("  x", p)
    if args.fix:
        print("(facts rewritten; the rest needs a human)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
