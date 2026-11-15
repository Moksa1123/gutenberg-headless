#!/usr/bin/env python3
"""roundtrip-check.py - round-trip every stored post through blockmark.py, record the result.

    wp eval-file tools/export-block-posts.php > block-posts.json      (on the site)
    python tools/roundtrip-check.py block-posts.json --out data/roundtrip-verification.csv

One row per post: bytes, blocks, whether parse() -> serialize() reproduces the
stored bytes, and if not, which divergence class explains it:

    escape   a literal & < > or -- inside comment JSON; every serializer writes
             \\u0026 \\u003c \\u003e \\u002d\\u002d, so the stored bytes are the
             ones WordPress will rewrite on the next save (validate-post W-ESCAPE)
    other    anything else - a parser bug until proven otherwise

Exit 1 when any post diverges for a reason other than `escape`.
Standard library only.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blockmark  # noqa: E402

ESCAPES = {"&": "\\u0026", "<": "\\u003c", ">": "\\u003e", "--": "\\u002d\\u002d"}
COLUMNS = ["post_id", "post_type", "bytes", "blocks", "byte_identical", "divergence",
           "measured_on", "trust"]


def _escape(s: str) -> str:
    s = s.replace("--", ESCAPES["--"])
    for ch in "&<>":
        s = s.replace(ch, ESCAPES[ch])
    return s


def classify(stored: str, canonical: str) -> str:
    """'escape' when every difference is a literal &, <, >, -- the serializer escapes."""
    sm = difflib.SequenceMatcher(None, stored, canonical, autojunk=False)
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        a, b = stored[a1:a2], canonical[b1:b2]
        if op != "equal" and (not a or set(a) - set("&<>-") or _escape(a) != b):
            return "other"
    return "escape"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("export", help="JSON written by tools/export-block-posts.php")
    ap.add_argument("--out", help="write the CSV here (default: print a summary only)")
    a = ap.parse_args()

    d = json.loads(Path(a.export).read_text(encoding="utf-8"))
    host = d.get("site", "").split("//")[-1].rstrip("/")
    label = f"{host} WP {d.get('wp')} / WooCommerce {d.get('woocommerce')}, {d.get('exported_at')}"
    rows, total, bad = [], 0, 0
    for p in d["posts"]:
        src = p["content"]
        size = len(src.encode("utf-8"))
        total += size
        try:
            tree = blockmark.parse(src)
            out = blockmark.serialize(tree)
            n = sum(1 for _ in blockmark.walk(tree))
        except ValueError as e:
            rows.append([p["id"], p["type"], size, 0, "no", f"parse error: {e}", label, "measured"])
            bad += 1
            continue
        same = out == src
        kind = "" if same else classify(src, out)
        bad += kind == "other"
        rows.append([p["id"], p["type"], size, n, "yes" if same else "no", kind, label, "measured"])

    same = sum(1 for r in rows if r[4] == "yes")
    print(f"{len(rows)} posts, {total} bytes: {same} byte-identical, "
          f"{sum(1 for r in rows if r[5] == 'escape')} escape-only, {bad} other")
    if a.out:
        with open(a.out, "w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, lineterminator="\n")
            w.writerow(COLUMNS)
            w.writerows(rows)
        print(f"wrote {a.out}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
