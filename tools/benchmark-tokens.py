#!/usr/bin/env python3
"""
benchmark-tokens.py - measure what this skill actually costs, and what it saves.

Run it yourself; every number in the README comes from this script:

    pip install tiktoken
    python tools/benchmark-tokens.py --wp-src /path/to/wordpress

--wp-src is a WordPress root (containing wp-includes/ and wp-content/); it
enables the source-reading baseline. Without it the rest still runs.

WHAT IS BEING COMPARED
An agent writing block markup needs to know, for the blocks it is touching:
which attributes exist, which half each one lives in (comment vs saved HTML),
the classes and inline CSS the saved HTML must carry, and which preset slugs
this site actually defines. Three ways to get that, priced on the same tasks:

  A. READ THE SOURCE  - open block.json files, the block-supports/*.php that
     define what each support does, and the theme.json files that define the
     presets. Accurate for what it covers - but the serialization rules (which
     class a support emits at save time) are in the JS packages, not here, and
     the render verdicts are in no file at all.

  B. LOAD THE SCHEMA  - put data/block-schema.json in context. Complete, and
     wasteful: you pay for 302 blocks to use one.

  C. QUERY THE SCHEMA - run tools/gb.py and read back only the answer.
     This is what the skill does.

HONESTY NOTES
  - Token counts use tiktoken cl100k_base - OpenAI's tokenizer, not Claude's,
    so absolute counts shift by roughly +-10%. Ratios under one tokenizer are
    stable, and the ratio is the claim.
  - Baseline A counts exactly the files that contain what a task needs - the
    block.json plus every block-supports/*.php whose behaviour the task
    touches, plus the theme.json files for preset tasks. Where source cannot
    answer at all (render verdicts, the save-time class formulas that live in
    JS, presets injected by plugin filters), A is still priced for the files
    an agent would read before discovering that - the generous reading.
  - The gb.py outputs measured are the exact commands an agent runs, captured
    by invoking the tool for real, and timed.
  - Baseline B is charged once, not once per task - the generous reading.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

try:
    import tiktoken
except ImportError:
    sys.exit("pip install tiktoken")

ENC = tiktoken.get_encoding("cl100k_base")


def tok(text: str) -> int:
    return len(ENC.encode(text))


QUERY_MS: list[float] = []


def run_gb(args: list[str]) -> str:
    """Invoke gb.py exactly as an agent would, capture what it prints - timed.
    The latency recorded is the real tool-side cost (process spawn + schema
    load + query) on this machine."""
    t0 = time.perf_counter()
    out = subprocess.run(
        [sys.executable, "-X", "utf8", str(HERE / "gb.py"), *args],
        capture_output=True, text=True, encoding="utf-8",
    )
    QUERY_MS.append((time.perf_counter() - t0) * 1000)
    if out.returncode != 0:
        raise RuntimeError(f"gb.py {' '.join(args)} failed: {out.stderr}")
    return out.stdout


# Real tasks: each is something you actually do to build a page, with the
# gb.py commands that answer it and the source files that would.
TASKS = [
    {
        "task": "Build a group section (layout, background, spacing presets)",
        "cmds": [["block", "core/group"], ["var", "var:preset|spacing|60"]],
        # group/block.json declares the supports; what each support DOES -
        # layout container classes, background render filter, padding
        # serialization - lives in block-supports/*.php.
        "src": [
            "wp-includes/blocks/group/block.json",
            "wp-includes/block-supports/layout.php",
            "wp-includes/block-supports/background.php",
            "wp-includes/block-supports/spacing.php",
        ],
    },
    {
        "task": "Color + typography on a heading, with valid preset slugs",
        "cmds": [["block", "core/heading"], ["presets", "color"]],
        # The slugs come from TWO theme.json files (core defaults + theme),
        # and the class formulas from the supports files.
        "src": [
            "wp-includes/blocks/heading/block.json",
            "wp-includes/block-supports/colors.php",
            "wp-includes/block-supports/typography.php",
            "wp-includes/theme.json",
            "wp-content/themes/blocksy/theme.json",
        ],
    },
    {
        "task": "Every preset slug this site can use",
        "cmds": [["presets"]],
        # Source CANNOT fully answer this one: the merged settings include
        # plugin filters no file shows. Priced for the two files an agent
        # would read before discovering that.
        "src": [
            "wp-includes/theme.json",
            "wp-content/themes/blocksy/theme.json",
        ],
    },
    {
        "task": "Will woocommerce/product-price render here, inside what?",
        "cmds": [["block", "woocommerce/product-price"]],
        # block.json gives attrs and context; the bare-page render verdict is
        # in NO source file - it was measured by the sweep. A is priced for
        # the file that answers the half it can.
        "src": [
            "wp-content/plugins/woocommerce/assets/client/blocks/product-price/block.json",
        ],
    },
    {
        "task": "Which style key drives box-shadow, and the valid presets",
        "cmds": [["presets", "shadow"], ["grammar"]],
        "src": [
            "wp-includes/style-engine/class-wp-style-engine.php",
        ],
    },
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wp-src", type=Path,
                    help="path to a WordPress root (enables the source baseline)")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "token-benchmark.csv")
    a = ap.parse_args()

    schema_raw = (ROOT / "data" / "block-schema.json").read_text(encoding="utf-8")
    schema_tokens = tok(schema_raw)

    print("SHIPPED DATA FILES")
    print("=" * 78)
    total_data = 0
    for p in sorted((ROOT / "data").glob("*")):
        t = tok(p.read_text(encoding="utf-8", errors="replace"))
        total_data += t
        print(f"  {p.name:28} {p.stat().st_size / 1024:9.1f} KB   {t:>9,} tokens")
    print(f"  {'TOTAL':28} {'':9}      {total_data:>9,} tokens")
    print()
    print("  None of this is ever loaded into context. It is queried. That is the whole")
    print("  design: the schema is a database, gb.py is the query, the answer is the cost.")
    print()

    rows = []
    print("PER-TASK COST")
    print("=" * 78)
    print(f"  {'task':<52} {'A:src':>8} {'B:schema':>9} {'C:query':>8}  {'saving':>7}")
    print("  " + "-" * 76)

    for t in TASKS:
        query_tokens = sum(tok(run_gb(c)) for c in t["cmds"])
        b = schema_tokens
        src_tokens = 0
        if a.wp_src:
            for rel in t["src"]:
                f = a.wp_src / rel
                if f.exists():
                    src_tokens += tok(f.read_text(encoding="utf-8", errors="replace"))

        if src_tokens:
            saving = (1 - query_tokens / src_tokens) * 100
            print(f"  {t['task']:<52} {src_tokens:>8,} {b:>9,} {query_tokens:>8,}  {saving:>6.1f}%")
        else:
            saving = float("nan")
            print(f"  {t['task']:<52} {'-':>8} {b:>9,} {query_tokens:>8,}  {'-':>7}")

        rows.append({
            "task": t["task"],
            "commands": " ; ".join("gb.py " + " ".join(c) for c in t["cmds"]),
            "tokens_read_source": src_tokens or "",
            "tokens_load_schema": b,
            "tokens_query": query_tokens,
            "saving_vs_source_pct": f"{saving:.1f}" if src_tokens else "",
            "saving_vs_schema_pct": f"{(1 - query_tokens / b) * 100:.2f}",
        })

    print()
    tot_src = sum(r["tokens_read_source"] for r in rows if r["tokens_read_source"])
    tot_q = sum(r["tokens_query"] for r in rows)
    print("TOTALS ACROSS THE 5 TASKS")
    print("=" * 78)
    if tot_src:
        print(f"  A. read the WordPress source     {tot_src:>9,} tokens")
    print(f"  B. load the whole schema         {schema_tokens:>9,} tokens  (x5 if re-read per task)")
    print(f"  C. query it with gb.py           {tot_q:>9,} tokens")
    if tot_src:
        print()
        print(f"  C vs A: {(1 - tot_q / tot_src) * 100:.1f}% fewer tokens "
              f"({tot_src:,} -> {tot_q:,})")
    print(f"  C vs B: {(1 - tot_q / schema_tokens) * 100:.2f}% fewer tokens "
          f"({schema_tokens:,} -> {tot_q:,})")
    print()
    print("  And baseline A does not even answer fully: the save-time class formulas")
    print("  live in the JS packages, the render verdicts in no file at all - the two")
    print("  places where getting it wrong fails silently.")

    RATE = 1000.0  # tokens/second ingest, reference rate - disclosed, adjustable
    print()
    print("TIME")
    print("=" * 78)
    if QUERY_MS:
        import statistics
        print(f"  gb.py tool latency (MEASURED, n={len(QUERY_MS)}): "
              f"median {statistics.median(QUERY_MS):.0f} ms, "
              f"max {max(QUERY_MS):.0f} ms per query")
    if tot_src:
        t_a = tot_src / RATE
        t_c = tot_q / RATE + sum(QUERY_MS) / 1000
        print(f"  model ingest at {RATE:.0f} tok/s (DERIVED estimate):")
        print(f"    A. read the source   ~{t_a:7.1f} s  for the 5 tasks")
        print(f"    B. load the schema   ~{schema_tokens / RATE:7.1f} s  once")
        print(f"    C. query             ~{t_c:7.1f} s  including measured tool latency")
        print(f"    C vs A: ~{t_a / t_c:.0f}x faster on ingest alone")

    with a.out.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print()
    print(f"  written: {a.out}")
    print(f"  tokenizer: tiktoken cl100k_base (proxy for Claude's; ratios hold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
