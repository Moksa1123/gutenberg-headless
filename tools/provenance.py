#!/usr/bin/env python3
"""
provenance.py - stamp every row of the main tables with where it came from.

skill-SOP data rule: each row carries a source column and a trust level
(measured > documented > inferred). The main tables are all generated from one
extraction of one live site, so the stamp is the same for every row of a table:

    measured_on   <host> WP <ver> / <theme> <ver>[ / WooCommerce <ver>] live registry, extracted <date>
    trust         measured

What "measured" means per table:

    blocks.csv, attributes.csv,     read off WP_Block_Type_Registry on the live site
    supports.csv, styles.csv,       (extract-block-schema.php), not from block.json
    block-categories.csv            files or docs
    presets.csv                     the site's merged theme.json (wp_get_global_settings)
    patterns.csv                    WP_Block_Patterns_Registry on the live site
    render-verification.csv         every block rendered through do_blocks() on a bare
                                    page (sweep-render.php); the verdict is observed output

WooCommerce's version is in the label only when the dump recorded it
(`plugin_versions`, added to extract-block-schema.php 2026-11-15); the
2026-08-28 extraction predates that.

build-indexes.py calls stamp() after writing the tables. Run it by hand only to
re-stamp tables that predate it:

    python tools/provenance.py data/
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

TABLES = ("blocks.csv", "attributes.csv", "supports.csv", "styles.csv",
          "block-categories.csv", "presets.csv", "patterns.csv", "render-verification.csv")
COLUMNS = ("measured_on", "trust")


def label(meta: dict) -> str:
    host = (meta.get("site_url") or "").split("//")[-1].rstrip("/")
    theme = meta.get("theme") or {}
    date = (meta.get("extracted_at") or "")[:10]
    woo = (meta.get("plugin_versions") or {}).get("woocommerce")
    parts = [f"{host} WP {meta.get('wp_version')}", f"{theme.get('name')} {theme.get('version')}"]
    if woo:
        parts.append(f"WooCommerce {woo}")
    return " / ".join(parts) + f" live registry, extracted {date}"


def stamp(out: Path, meta: dict, tables: tuple[str, ...] = TABLES) -> list[str]:
    """Add or overwrite measured_on/trust on every table in `out`. Returns the tables touched."""
    value = label(meta)
    done = []
    for name in tables:
        p = out / name
        if not p.exists():
            continue
        with p.open(encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        if not rows:
            continue
        keep = [i for i, h in enumerate(rows[0]) if h not in COLUMNS]
        head = [rows[0][i] for i in keep] + list(COLUMNS)
        body = [[r[i] if i < len(r) else "" for i in keep] + [value, "measured"] for r in rows[1:]]
        with p.open("w", encoding="utf-8", newline="") as f:
            csv.writer(f, lineterminator="\n").writerows([head] + body)
        done.append(name)
    return done


def main() -> int:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "data")
    meta = json.loads((out / "block-schema.json").read_text(encoding="utf-8"))
    meta.pop("blocks", None)
    for name in stamp(out, meta):
        print(f"stamped {name}: {label(meta)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
