#!/usr/bin/env python3
"""gb.py - query the extracted block-editor schema. The front door.

    python tools/gb.py stats
    python tools/gb.py blocks --grep button --static
    python tools/gb.py block core/group
    python tools/gb.py block paragraph --grep color
    python tools/gb.py supports core/heading
    python tools/gb.py presets color
    python tools/gb.py styles core/image
    python tools/gb.py patterns --grep hero
    python tools/gb.py var "var:preset|spacing|50"
    python tools/gb.py skeleton
    python tools/gb.py grammar

Add --json for machine-readable output.
Never read data/block-schema.json into context - it is the database, this is the query.
"""
import argparse
import json
import sys

import gblib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def j(x):
    return json.dumps(x, ensure_ascii=False)


def cmd_stats(s, a):
    blocks = s["blocks"]
    dyn = sum(1 for b in blocks.values() if b["is_dynamic"])
    ns = {}
    for n in blocks:
        ns[n.split("/")[0]] = ns.get(n.split("/")[0], 0) + 1
    verified = sum(1 for b in blocks.values() if b.get("render_verdict"))
    print(f"extracted   : {s['extracted_at']}  from {s['site_url']}")
    print(f"WordPress   : {s['wp_version']}   theme: {s['theme']['name']} {s['theme']['version']}"
          f" (block theme: {'yes' if s['theme']['is_block_theme'] else 'NO - classic/hybrid'})")
    print(f"blocks      : {len(blocks)} registered  ({dyn} dynamic, {len(blocks)-dyn} static)")
    print(f"namespaces  : " + "  ".join(f"{k}:{v}" for k, v in sorted(ns.items(), key=lambda x: -x[1])))
    print(f"render-swept: {verified}/{len(blocks)}")
    pres = gblib.presets(s)
    print("presets     : " + "  ".join(f"{k}:{len(v)}" for k, v in pres.items() if v))
    print(f"patterns    : {len(s.get('patterns', []))}   plugins: {', '.join(s.get('active_plugins', []))}")


def cmd_blocks(s, a):
    rows = []
    for name, b in sorted(s["blocks"].items()):
        if a.namespace and name.split("/")[0] != a.namespace:
            continue
        if a.dynamic and not b["is_dynamic"]:
            continue
        if a.static and b["is_dynamic"]:
            continue
        if a.top_level and (b.get("parent") or b.get("ancestor")):
            continue
        hay = f"{name} {b['title']} {' '.join(b.get('keywords') or [])}".lower()
        if a.grep and a.grep.lower() not in hay:
            continue
        rows.append((name, b))
    if a.json:
        print(j([n for n, _ in rows]))
        return
    for name, b in rows:
        flags = []
        if b["is_dynamic"]:
            flags.append("dynamic")
        if b.get("parent"):
            flags.append("parent:" + ",".join(b["parent"]))
        if b.get("ancestor"):
            flags.append("ancestor:" + ",".join(b["ancestor"]))
        if b.get("render_verdict"):
            flags.append(b["render_verdict"])
        print(f"{name:46} {b['title'][:28]:28} {' '.join(flags)}")
    print(f"-- {len(rows)} blocks")


def _attr_line(name, attr, block_def):
    bits = []
    t = attr.get("type", "?")
    bits.append("|".join(t) if isinstance(t, list) else str(t))
    if attr.get("source"):
        sel = attr.get("selector", "")
        loc = f"IN-HTML source:{attr['source']}" + (f" selector:{sel}" if sel else "")
        if attr.get("attribute"):
            loc += f" attribute:{attr['attribute']}"
        bits.append(loc)
    if "enum" in attr:
        bits.append("enum:" + ",".join(map(str, attr["enum"])))
    if "default" in attr:
        bits.append(f"default:{j(attr['default'])}")
    kind = gblib.preset_kind_for(name)
    if kind:
        tpl, _ = gblib.SLUG_ATTR_CLASSES[name]
        bits.append(f"slug-of:{kind}-preset  class:{'+'.join(tpl)}")
    elif name in ("align", "textAlign"):
        bits.append("class:align*/has-text-align-*")
    elif name == "style":
        bits.append("object -> INLINE STYLE in saved HTML (gb.py grammar)")
    elif name == "className":
        bits.append("appended to class attr of saved HTML")
    elif name == "anchor":
        bits.append("id attr of saved HTML")
    return f"  {name:24} {'  '.join(bits)}"


def cmd_block(s, a):
    name = gblib.full_name(a.name)
    b = s["blocks"].get(name)
    if not b:
        cand = [n for n in s["blocks"] if a.name in n]
        sys.exit(f"no block {name!r} on this site."
                 + (f" close: {', '.join(cand[:8])}" if cand else " (the surface is a property of the SITE)"))
    if a.json:
        print(j(b))
        return
    has_sourced = any(x.get("source") for x in (b.get("attributes") or {}).values())
    if has_sourced:
        kind = "CONTENT-IN-HTML - sourced attrs live in the saved HTML, not the comment; write the HTML"
        if b["is_dynamic"]:
            kind += " (server also filters the output at render)"
    elif b["is_dynamic"]:
        kind = "DYNAMIC - serialize as void <!-- wp:x {...} /-->; attrs are the source of truth, server renders"
    else:
        kind = "STATIC WRAPPER - you write the full saved HTML; comment attrs alone render nothing"
    print(f"{name}  ({b['title']})  api_version:{b.get('api_version')}")
    print(f"  {kind}")
    if b.get("render_verdict"):
        print(f"  render-sweep: {b['render_verdict']}"
              + (f" - {b['render_note']}" if b.get("render_note") else ""))
    if b.get("parent"):
        print(f"  parent-ONLY inside: {', '.join(b['parent'])}")
    if b.get("ancestor"):
        print(f"  ancestor-needs: {', '.join(b['ancestor'])}")
    if b.get("uses_context"):
        print(f"  uses_context: {', '.join(b['uses_context'])}")
    if b.get("styles"):
        print("  styles: " + ", ".join(f"is-style-{x['name']}" for x in b["styles"]))
    if b.get("variations"):
        print("  variations: " + ", ".join(x["name"] for x in b["variations"]))
    print("attributes:")
    for an, attr in sorted(b.get("attributes", {}).items()):
        if a.grep and a.grep.lower() not in an.lower():
            continue
        print(_attr_line(an, attr, b))
    sup = []
    gblib_flat(b.get("supports") or {}, "", sup)
    shown = [f"{k}={j(v)}" for k, v in sup if not a.grep or a.grep.lower() in k.lower()]
    if shown:
        print("supports: " + "  ".join(shown))


def gblib_flat(d, prefix, out):
    if isinstance(d, dict):
        for k, v in d.items():
            gblib_flat(v, f"{prefix}.{k}" if prefix else k, out)
    else:
        out.append((prefix, d))


def cmd_supports(s, a):
    name = gblib.full_name(a.name)
    b = s["blocks"].get(name) or sys.exit(f"no block {name!r}")
    rows = []
    gblib_flat(b.get("supports") or {}, "", rows)
    if a.json:
        print(j(dict(rows)))
        return
    for k, v in rows:
        print(f"  {k:56} {j(v)}")


def cmd_presets(s, a):
    pres = gblib.presets(s)
    kinds = [a.kind] if a.kind else list(pres)
    for kind in kinds:
        for slug, val in pres.get(kind, {}).items():
            if a.grep and a.grep.lower() not in slug.lower():
                continue
            v = j(val) if isinstance(val, (dict, list)) else str(val)
            print(f"{kind:12} {slug:24} var(--wp--preset--{kind}--{slug})  = {v[:60]}")


def cmd_styles(s, a):
    for name, b in sorted(s["blocks"].items()):
        if a.name and gblib.full_name(a.name) != name:
            continue
        for st in b.get("styles", []):
            print(f"{name:40} is-style-{st['name']:22} {st.get('label','')}")


def cmd_patterns(s, a):
    for p in s.get("patterns", []):
        if a.grep and a.grep.lower() not in (p["name"] + p["title"]).lower():
            continue
        print(f"{p['name']:56} {p['title'][:34]:34} {p.get('bytes',0)}b")


def cmd_categories(s, a):
    for c in s.get("block_categories", []):
        print(f"{c['slug']:20} {c['title']}")


def cmd_var(s, a):
    ref = a.ref
    var = gblib.preset_ref_to_var(ref)
    if not var:
        sys.exit(f"not a preset ref: {ref!r}  (want var:preset|<kind>|<slug>)")
    kind, slug = ref.split("|")[1], ref.split("|")[2]
    val = gblib.presets(s).get(kind, {}).get(slug)
    status = f"= {val}" if val is not None else "!! SLUG NOT ON THIS SITE - renders a var() that resolves to nothing"
    print(f"{ref}\n  css: {var}\n  {status}")


SKELETON = '''<!-- wp:group {"layout":{"type":"constrained"}} -->
<div class="wp-block-group"><!-- wp:heading {"level":2} -->
<h2 class="wp-block-heading">Title</h2>
<!-- /wp:heading -->

<!-- wp:paragraph -->
<p>Text.</p>
<!-- /wp:paragraph --></div>
<!-- /wp:group -->'''


def cmd_skeleton(s, a):
    print(SKELETON)


GRAMMAR = """serialized form
  static:   <!-- wp:namespace/name {"attr":...} -->SAVED HTML<!-- /wp:namespace/name -->
  dynamic:  <!-- wp:namespace/name {"attr":...} /-->            (usually void - no HTML)
  core/ namespace is OMITTED:  wp:paragraph, never wp:core/paragraph
  attrs JSON: '--' '<' '>' '&' must be \\u-escaped (serialize_block_attributes)

what lives where
  comment JSON : every attribute WITHOUT a source
  saved HTML   : every attribute WITH a source (rich-text/html/attribute/query)
                 - writing those into the comment does nothing
  both         : preset slugs -> comment attr AND the has-* class in the HTML
                 style object -> comment attr AND the inline style in the HTML

preset value refs (inside the style object)
  "var:preset|spacing|50"  ->  HTML must say  var(--wp--preset--spacing--50)

wrapper class conventions (saved HTML)
  block class   : wp-block-{name-with-/-as--}   e.g. wp-block-group, wp-block-media-text
                  (paragraph is the exception: <p> carries NO wp-block-paragraph)
  backgroundColor=x : has-x-background-color has-background
  textColor=x       : has-x-color has-text-color
  gradient=x        : has-x-gradient-background has-background
  fontSize=x        : has-x-font-size          fontFamily=x : has-x-font-family
  borderColor=x     : has-border-color has-x-border-color
  align             : alignwide / alignfull / has-text-align-{left,center,right}
  className         : appended verbatim        anchor: id="..."
  block style       : is-style-{name}

render-time (server injects - do NOT write these)
  layout attr    -> wp-container-* class + generated CSS
  style.elements -> wp-elements-* class + generated CSS
  duotone        -> wp-duotone-* class

WP 7.0/7.1 additions (references/wp71-new-surface.md)
  style {":hover":{...}}         button/navigation-link only; render-time wp-states-* CSS
  style {"@mobile":{...}}        any block; @mobile/@tablet/@desktop from theme.json viewport
  metadata.blockVisibility       false = not rendered; {"viewport":{"mobile":false}} = hidden per device
  style.css                      per-block custom CSS; HTML needs class has-custom-css
  fitText:true                   paragraph/heading; HTML needs class has-fit-text"""


def cmd_grammar(s, a):
    print(GRAMMAR)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--schema", help="alternate block-schema.json")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("stats")
    p = sub.add_parser("blocks")
    p.add_argument("--grep")
    p.add_argument("--namespace")
    p.add_argument("--dynamic", action="store_true")
    p.add_argument("--static", action="store_true")
    p.add_argument("--top-level", action="store_true")
    p = sub.add_parser("block")
    p.add_argument("name")
    p.add_argument("--grep")
    p = sub.add_parser("supports")
    p.add_argument("name")
    p = sub.add_parser("presets")
    p.add_argument("kind", nargs="?", choices=list(gblib.PRESET_KINDS))
    p.add_argument("--grep")
    p = sub.add_parser("styles")
    p.add_argument("name", nargs="?")
    p = sub.add_parser("patterns")
    p.add_argument("--grep")
    sub.add_parser("categories")
    p = sub.add_parser("var")
    p.add_argument("ref")
    sub.add_parser("skeleton")
    sub.add_parser("grammar")

    for _, sp in sub.choices.items():
        sp.add_argument("--json", action="store_true")

    a = ap.parse_args()
    s = gblib.load_schema(a.schema)
    globals()[f"cmd_{a.cmd}"](s, a)


if __name__ == "__main__":
    main()
