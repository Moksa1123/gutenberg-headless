#!/usr/bin/env python3
"""Turn a live-site block dump into the skill's data files.

Usage:
    python tools/build-indexes.py data/block-dump.json --out data/

Produces:
    block-schema.json   the queryable database (gb.py reads this - never read it into context)
    blocks.csv          one row per registered block type
    attributes.csv      one row per attribute of every block
    supports.csv        one row per (block, support-path) - flattened
    presets.csv         every theme.json preset slug: colors, gradients, font sizes,
                        font families, spacing, shadows - with origin and CSS var
    styles.csv          registered block style variations
    patterns.csv        registered patterns (names, not content)
    block-categories.csv

If a verification CSV from sweep runs is supplied, its verdicts are merged into
block-schema.json so gb.py can print them:
    --render-verification data/render-verification.csv
"""
import argparse
import csv
import json
import sys
from pathlib import Path


def flatten(prefix, val, out):
    if isinstance(val, dict):
        for k, v in val.items():
            flatten(f"{prefix}.{k}" if prefix else k, v, out)
    else:
        out.append((prefix, val))


def preset_rows(settings):
    """Yield (kind, slug, value, name, origin, css_var) for every preset."""
    spec = [
        ("color",      ("color", "palette"),              "color",    "--wp--preset--color--{}"),
        ("gradient",   ("color", "gradients"),            "gradient", "--wp--preset--gradient--{}"),
        ("duotone",    ("color", "duotone"),              "colors",   "--wp--preset--duotone--{}"),
        ("font-size",  ("typography", "fontSizes"),       "size",     "--wp--preset--font-size--{}"),
        ("font-family",("typography", "fontFamilies"),    "fontFamily","--wp--preset--font-family--{}"),
        ("spacing",    ("spacing", "spacingSizes"),       "size",     "--wp--preset--spacing--{}"),
        ("shadow",     ("shadow", "presets"),             "shadow",   "--wp--preset--shadow--{}"),
    ]
    for kind, path, value_key, var_tpl in spec:
        node = settings
        for p in path:
            node = node.get(p, {}) if isinstance(node, dict) else {}
        if not isinstance(node, dict):
            continue
        for origin in ("default", "theme", "custom"):
            for item in node.get(origin) or []:
                slug = item.get("slug", "")
                val = item.get(value_key, "")
                if isinstance(val, (dict, list)):
                    val = json.dumps(val, ensure_ascii=False)
                yield (kind, slug, val, item.get("name", ""), origin, var_tpl.format(slug))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dump")
    ap.add_argument("--out", default="data")
    ap.add_argument("--render-verification", help="CSV of render verdicts to merge")
    ap.add_argument("--render-sweep", help="raw JSON from sweep-render.php - converted and merged directly")
    args = ap.parse_args()

    d = json.loads(Path(args.dump).read_text(encoding="utf-8"))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    verdicts = {}
    if args.render_sweep and Path(args.render_sweep).exists():
        raw = json.loads(Path(args.render_sweep).read_text(encoding="utf-8"))
        for name, v in raw.items():
            verdicts[name] = {"block": name, "verdict": v.get("verdict", ""), "note": v.get("note", "")}
        vp = out / "render-verification.csv"
        with open(vp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["block", "verdict", "note"])
            for name in sorted(verdicts):
                w.writerow([name, verdicts[name]["verdict"], verdicts[name]["note"]])
    elif args.render_verification and Path(args.render_verification).exists():
        with open(args.render_verification, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                verdicts[row["block"]] = row

    # ---- blocks.csv --------------------------------------------------------
    with open(out / "blocks.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "title", "category", "dynamic", "api_version", "parent",
                    "ancestor", "attrs", "variations", "styles", "namespace", "render_verdict"])
        for name, b in sorted(d["blocks"].items()):
            v = verdicts.get(name, {})
            w.writerow([
                name, b["title"], b.get("category") or "", "yes" if b["is_dynamic"] else "no",
                b.get("api_version", ""),
                "|".join(b.get("parent") or []), "|".join(b.get("ancestor") or []),
                len(b.get("attributes", {})), len(b.get("variations", [])),
                len(b.get("styles", [])), name.split("/")[0],
                v.get("verdict", ""),
            ])

    # ---- attributes.csv ----------------------------------------------------
    with open(out / "attributes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["block", "attribute", "type", "source", "selector", "enum", "default", "role"])
        for name, b in sorted(d["blocks"].items()):
            for an, a in (b.get("attributes") or {}).items():
                t = a.get("type", "")
                if isinstance(t, list):
                    t = "|".join(map(str, t))
                dv = a.get("default", "")
                if isinstance(dv, (dict, list, bool)):
                    dv = json.dumps(dv, ensure_ascii=False)
                w.writerow([name, an, t, a.get("source", ""), a.get("selector", ""),
                            "|".join(map(str, a.get("enum", []))), dv, a.get("role", "")])

    # ---- supports.csv ------------------------------------------------------
    with open(out / "supports.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["block", "support", "value"])
        for name, b in sorted(d["blocks"].items()):
            rows = []
            flatten("", b.get("supports") or {}, rows)
            for path, val in rows:
                w.writerow([name, path, json.dumps(val, ensure_ascii=False)])

    # ---- presets.csv -------------------------------------------------------
    with open(out / "presets.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["kind", "slug", "value", "name", "origin", "css_var"])
        for row in preset_rows(d.get("global_settings", {})):
            w.writerow(row)

    # ---- styles.csv --------------------------------------------------------
    with open(out / "styles.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["block", "style", "label", "is_default", "class"])
        for name, b in sorted(d["blocks"].items()):
            for s in b.get("styles", []):
                w.writerow([name, s["name"], s.get("label", ""),
                            "yes" if s.get("isDefault") else "no", f"is-style-{s['name']}"])

    # ---- patterns.csv ------------------------------------------------------
    with open(out / "patterns.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["name", "title", "categories", "inserter", "bytes"])
        for p in d.get("patterns", []):
            w.writerow([p["name"], p["title"], "|".join(p.get("categories") or []),
                        "yes" if p.get("inserter") else "no", p.get("bytes", 0)])

    # ---- block-categories.csv ---------------------------------------------
    with open(out / "block-categories.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["slug", "title"])
        for c in d.get("block_categories", []):
            w.writerow([c["slug"], c["title"]])

    # ---- block-schema.json (the database) ---------------------------------
    if verdicts:
        for name, v in verdicts.items():
            if name in d["blocks"]:
                d["blocks"][name]["render_verdict"] = v.get("verdict", "")
                d["blocks"][name]["render_note"] = v.get("note", "")
    (out / "block-schema.json").write_text(
        json.dumps(d, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    n = d["block_count"]
    print(f"OK  {n} blocks -> {out}/  (blocks/attributes/supports/presets/styles/patterns CSVs + block-schema.json)")


if __name__ == "__main__":
    sys.exit(main())
