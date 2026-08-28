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


_SURFACE = [None]


def surface():
    """The half of the truth the PHP registry does not hold.

    Variations, transforms, deprecations and the exact shape each block's
    save() writes all live in JavaScript. Measured on the target site: the
    server reports 3 variations and no transforms or deprecations; the editor
    has 173, 168 and 192. Extracted by tools/extract-editor-surface.js."""
    if _SURFACE[0] is None:
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "data" / "editor-surface.json"
        _SURFACE[0] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"blocks": {}}
    return _SURFACE[0]


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

    sf = surface()["blocks"]
    if sf:
        tot = lambda k: sum(len(b.get(k) or []) for b in sf.values())  # noqa: E731
        trans = sum(len(b["transforms"]["from"]) + len(b["transforms"]["to"])
                    for b in sf.values() if b.get("transforms"))
        only_server = sorted(set(blocks) - set(sf))
        print(f"editor      : {len(sf)} block types in the EDITOR registry"
              + (f"  ({len(only_server)} registered server-side only - "
                 f"they render, but the editor cannot place or read them)" if only_server else ""))
        print(f"  variations: {tot('variations')}   transforms: {trans}   "
              f"deprecations: {tot('deprecated')}")
    t = s.get("templates") or {}
    if t:
        kind = ("block theme - wp_template/wp_template_part available"
                if t.get("is_block_theme") else
                "classic theme - NO wp_template; patterns and post-type templates only")
        print(f"templates   : {kind}")
        print(f"  synced patterns (wp_block): {t.get('synced_patterns', 0)}   "
              f"wp_template: {t.get('wp_template', 0)}   "
              f"post-type templates: {len(t.get('post_type_templates') or [])}")
    bs = s.get("binding_sources") or []
    if bs:
        print("bindings    : " + "  ".join(b["name"] for b in bs))


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

    # What the SITE already does to this block, before any markup is written.
    themed = (s.get("block_style_defaults") or {}).get(name)
    if themed:
        print(f"  theme.json already styles it: {', '.join(themed)}"
              f"  <- you inherit this; a value you write has to outrank it")
    bset = (s.get("block_settings") or {}).get(name)
    if bset:
        print(f"  block-specific settings: {', '.join(sorted(bset))}")

    # And what the editor knows that the server does not.
    sf = surface()["blocks"].get(name)
    if sf:
        bits = []
        if sf.get("variations"):
            bits.append(f"{len(sf['variations'])} variations (gb.py variations {name})")
        if sf.get("transforms"):
            n = len(sf["transforms"]["from"]) + len(sf["transforms"]["to"])
            bits.append(f"{n} transforms")
        if sf.get("deprecated"):
            mig = sum(1 for d in sf["deprecated"] if d["hasMigrate"])
            bits.append(f"{len(sf['deprecated'])} DEPRECATED forms"
                        + (f" ({mig} rewrite attributes on read)" if mig else ""))
        if sf.get("contentAttributes"):
            bits.append("bindable: " + ", ".join(sf["contentAttributes"]))
        if bits:
            print("  editor: " + "  ·  ".join(bits))
    elif surface()["blocks"]:
        print("  editor: NOT in the editor's registry - renders for visitors, "
              "unreadable in the editor")

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


def _sf(name):
    full = gblib.full_name(name)
    rec = surface()["blocks"].get(full)
    if rec is None:
        print(f"'{full}' is not in the EDITOR registry "
              f"(it may still be registered server-side - see `gb.py stats`)")
    return full, rec


def cmd_variations(s, a):
    """A variation is a block wearing a different face: same block name,
    different preset attributes. core/group IS Row, Stack and Grid; core/embed
    IS 33 providers. None of it is visible server-side."""
    if a.block:
        full, rec = _sf(a.block)
        if not rec:
            return
        for v in rec.get("variations") or []:
            flag = " (default)" if v["isDefault"] else ""
            scope = f"  scope:{','.join(v['scope'])}" if v.get("scope") else ""
            print(f"{v['name']:28} {v['title']}{flag}{scope}")
            if v.get("attributes"):
                print(f"    attributes: {j(v['attributes'])[:150]}")
            if v.get("innerBlocks"):
                print(f"    innerBlocks: {', '.join(x for x in v['innerBlocks'] if x)}")
        if not rec.get("variations"):
            print(f"{full}: no variations")
        return
    rows = [(n, len(b["variations"])) for n, b in surface()["blocks"].items() if b.get("variations")]
    for n, c in sorted(rows, key=lambda x: -x[1]):
        if a.grep and a.grep not in n:
            continue
        print(f"{c:4}  {n}")
    print(f"-- {sum(c for _, c in rows)} variations across {len(rows)} blocks")


def cmd_transforms(s, a):
    """What a block can be turned into, and what turns into it. Matters when
    writing markup because a transform is also how the editor may REWRITE a
    block the user touches."""
    full, rec = _sf(a.block)
    if not rec:
        return
    tr = rec.get("transforms")
    if not tr:
        print(f"{full}: no transforms")
        return
    for side in ("from", "to"):
        for t in tr[side]:
            target = ", ".join(t["blocks"] or []) or (t["tag"] or "?")
            extra = "  isMatch()" if t["isMatch"] else ""
            print(f"{side:5} {t['type']:10} {target}{extra}")


def cmd_deprecated(s, a):
    """Deprecations are why "the editor accepted it" is not the same as "it is
    stable". A block whose markup matches an OLD save() is accepted through its
    deprecation chain - and a deprecation with migrate() rewrites the
    attributes the next time the block is touched."""
    if a.block:
        full, rec = _sf(a.block)
        if not rec:
            return
        deps = rec.get("deprecated") or []
        if not deps:
            print(f"{full}: no deprecations - its save() is the only accepted form")
            return
        print(f"{full}: {len(deps)} deprecated form(s)")
        for d in deps:
            bits = []
            if d["hasMigrate"]:
                bits.append("migrate() REWRITES attributes")
            if d["hasIsEligible"]:
                bits.append("isEligible()")
            if d["changedAttributes"]:
                bits.append("attrs: " + ", ".join(d["changedAttributes"][:8]))
            if d["changedSupports"]:
                bits.append("supports: " + ", ".join(d["changedSupports"][:6]))
            print(f"  [{d['index']}] " + ("  ".join(bits) or "same attributes, different markup"))
        return
    rows = [(n, len(b["deprecated"]),
             sum(1 for d in b["deprecated"] if d["hasMigrate"]))
            for n, b in surface()["blocks"].items() if b.get("deprecated")]
    for n, c, m in sorted(rows, key=lambda x: -x[1]):
        if a.grep and a.grep not in n:
            continue
        print(f"{c:3} forms ({m} migrating)  {n}")
    print(f"-- {sum(c for _, c, _ in rows)} deprecated forms across {len(rows)} blocks")


def cmd_save(s, a):
    """The exact shape this block's save() writes: element order, the class
    list in ITS order, the inline CSS declaration order, and which element
    carries `className`.

    This is the canonical form. Markup that differs is not necessarily invalid
    - the validator compares class tokens as a set - but the editor's next save
    rewrites it, so a page built the wrong way is one manual edit from being
    reshuffled end to end."""
    full, rec = _sf(a.block)
    if not rec:
        return
    sv = rec.get("save") or {}
    if sv.get("dynamic"):
        print(f"{full}: DYNAMIC - save() writes nothing; the server renders it. "
              f"Serialize as a void comment.")
        return
    if sv.get("error") or not sv.get("elements"):
        print(f"{full}: save() could not be probed ({sv.get('error', 'no output')})")
        return
    for i, el in enumerate(sv["elements"]):
        where = "  <- className lands here" if i == sv.get("classNameOn") else ""
        print(f"[{i}] <{el['tag']}>{where}")
        if el["attrs"]:
            print("    attribute order: " + " ".join(el["attrs"]))
        if el["classes"]:
            print("    class order    : " + " ".join(el["classes"]))
        if el["css"]:
            print("    inline CSS     : " + " ".join(el["css"]))
    if rec.get("contentAttributes"):
        print("bindable (role:content): " + ", ".join(rec["contentAttributes"]))


def cmd_settings(s, a):
    """What the editor is configured to ALLOW on this site.

    None of it constrains the markup - a page can carry an inline line-height
    on a theme that switches the control off, and it renders. What it decides
    is whether a human can change the value afterwards, which is the difference
    between a page and a page someone can maintain."""
    es = s.get("editor_settings") or {}
    ts = s.get("theme_supports") or {}
    if not es and not ts:
        print("not in this schema - re-extract with the current extract-block-schema.php")
        return

    allowed = es.get("allowedBlockTypes")
    print("insertable  : " + ("every registered block" if allowed is True
                              else f"{len(allowed)} block types (restricted)" if isinstance(allowed, list)
                              else "unknown"))
    print(f"wide/full   : {'yes' if es.get('alignWide') else 'no'}"
          f"   layout styles: {'off' if es.get('disableLayoutStyles') else 'on'}")
    off = [k[len("disableCustom"):].lower() for k in
           ("disableCustomColors", "disableCustomFontSizes", "disableCustomGradients",
            "disableCustomSpacingSizes") if es.get(k)]
    print("custom values: " + (f"DISABLED for {', '.join(off)}" if off
                               else "allowed for colors, font sizes, gradients, spacing"))
    on = [k for k in ("enableCustomLineHeight", "enableCustomSpacing") if es.get(k)]
    units = es.get("enableCustomUnits")
    print(f"controls    : {', '.join(on) or 'line-height and spacing OFF'}"
          f"   units: {', '.join(units) if isinstance(units, list) else units}")
    if es.get("imageSizes"):
        print(f"image sizes : {', '.join(es['imageSizes'])}   default: {es.get('imageDefaultSize')}")
    print(f"editor CSS  : {'editable' if es.get('canEditCSS') else 'not editable'}"
          f"   bindings editable: {'yes' if es.get('canUpdateBlockBindings') else 'no'}")
    bindable = es.get("__experimentalBlockBindingsSupportedAttributes")
    if bindable:
        n = sum(len(v) for v in bindable.values()) if isinstance(bindable, dict) else len(bindable)
        print(f"bindable    : {n} attributes across "
              f"{len(bindable) if isinstance(bindable, dict) else '?'} blocks")

    print("\ntheme_supports (a CLASSIC theme declares its editor surface here,")
    print("not in theme.json - and the resolved settings above can still differ):")
    print("  on : " + ", ".join(k for k, v in ts.items() if v))
    print("  off: " + ", ".join(k for k, v in ts.items() if not v))

    bs = s.get("block_style_defaults") or {}
    if bs:
        print(f"\nblocks the theme already styles ({len(bs)}) - "
              f"you inherit these before writing anything:")
        for name, groups in sorted(bs.items()):
            print(f"    {name:28} {', '.join(groups)}")
    bset = s.get("block_settings") or {}
    if bset:
        print(f"\nblocks with their own settings ({len(bset)}):")
        for name, decl in sorted(bset.items()):
            print(f"    {name:28} {', '.join(sorted(decl))}")


def cmd_bindings(s, a):
    """Sources a `metadata.bindings` entry may name. core/pattern-overrides is
    what turns a synced pattern into a template with editable slots."""
    for b in s.get("binding_sources") or []:
        ctx = f"  uses_context: {', '.join(b['uses_context'])}" if b.get("uses_context") else ""
        print(f"{b['name']:26} {b['label']}{ctx}")
    if not s.get("binding_sources"):
        print("no binding sources registered on this site")


def cmd_templates(s, a):
    """The four different things called a "template", and which exist here."""
    t = s.get("templates") or {}
    block_theme = t.get("is_block_theme")
    print(f"theme            : {'BLOCK theme' if block_theme else 'CLASSIC theme'}")
    print(f"wp_template      : {t.get('wp_template', 0)}"
          + ("" if block_theme else "   (not available - classic themes have no Site Editor templates)"))
    print(f"wp_template_part : {t.get('wp_template_part', 0)}")
    print(f"synced patterns  : {t.get('synced_patterns', 0)}   (wp_block post type - edit once, changes everywhere)")
    print(f"registered patterns: {len(s.get('patterns', []))}   (inserted as a COPY, then independent)")
    pts = t.get("post_type_templates") or []
    print(f"post-type templates: {len(pts)}   (a starting block structure for new posts; works on any theme)")
    for p in pts:
        print(f"    {p['post_type']:16} lock:{p['template_lock'] or 'none'}  {', '.join(p['blocks'][:6])}")
    overrides = any(b["name"] == "core/pattern-overrides" for b in (s.get("binding_sources") or []))
    print(f"pattern overrides: {'available' if overrides else 'NOT registered'}"
          f"   (a synced pattern with per-instance editable slots, bound to attributes marked role:content)")


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

    # --- the editor-side surface (data/editor-surface.json) ---
    p = sub.add_parser("variations")
    p.add_argument("block", nargs="?")
    p.add_argument("--grep")
    p = sub.add_parser("transforms")
    p.add_argument("block")
    p = sub.add_parser("deprecated")
    p.add_argument("block", nargs="?")
    p.add_argument("--grep")
    p = sub.add_parser("save")
    p.add_argument("block")
    sub.add_parser("settings")
    sub.add_parser("bindings")
    sub.add_parser("templates")

    for _, sp in sub.choices.items():
        sp.add_argument("--json", action="store_true")

    a = ap.parse_args()
    s = gblib.load_schema(a.schema)
    globals()[f"cmd_{a.cmd}"](s, a)


if __name__ == "__main__":
    main()
