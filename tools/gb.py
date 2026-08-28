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
              + (f"  ({len(only_server)} absent from THIS editor - measured in the post "
                 f"editor; several of them exist in the SITE editor instead)" if only_server else ""))
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
    ctx = render_context()
    if ctx:
        print(f"  needs        : {classify(name, b, ctx)}")
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
    if a.show:
        # The content is canonical markup written by core, WooCommerce or the
        # theme, for THIS site - the best available starting point for a layout,
        # and the corpus tools/selftest-patterns.py checks the validator against.
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "data" / "patterns.json"
        if not p.exists():
            sys.exit("data/patterns.json not shipped - extract it with tools/extract-patterns.php")
        for pat in json.loads(p.read_text(encoding="utf-8"))["patterns"]:
            if pat["name"] == a.show or a.show in pat["name"]:
                print(f"<!-- {pat['name']} - {pat['title']} -->")
                print(pat["content"])
                return
        sys.exit(f"no pattern matching {a.show!r} - list them with `gb.py patterns`")
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


_CTX = [None]


def render_context():
    """Which context each block needs before it renders anything.

    `sweep-render.php` says a block renders nothing on a bare page - true for
    205 of 302 here, and nearly useless alone, because it does not distinguish
    "broken" from "waiting for a post". This is the same sweep run again inside
    contexts a real page can supply. tools/sweep-context.php."""
    if _CTX[0] is None:
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "data" / "render-context.json"
        _CTX[0] = json.loads(p.read_text(encoding="utf-8"))["blocks"] if p.exists() else {}
    return _CTX[0]


def classify(name, b, ctx):
    """Why this block renders nothing, in the site's own terms."""
    v = (ctx.get(name) or {}).get("context")
    if v and v != "needs-more":
        return f"renders in: {v}"
    if b.get("parent") or b.get("ancestor"):
        return "needs a parent block - standalone is meaningless"
    if any(x.get("source") for x in (b.get("attributes") or {}).values()):
        return "content-in-HTML - the void form is empty by design"
    if not b.get("is_dynamic"):
        return "static wrapper - you write the HTML"
    return "unexplained - needs a context this sweep does not build, or the site has no such data"


def cmd_context(s, a):
    """Account for every block: what does it need before it renders?"""
    ctx = render_context()
    if not ctx:
        print("data/render-context.json not shipped - run tools/sweep-context.php")
        return
    import collections
    groups = collections.defaultdict(list)
    for name, b in s["blocks"].items():
        groups[classify(name, b, ctx)].append(name)
    for k in sorted(groups, key=lambda x: -len(groups[x])):
        print(f"{len(groups[k]):5}  {k}")
    print(f"{sum(len(v) for v in groups.values()):5}  TOTAL")
    if a.show:
        for k in sorted(groups, key=lambda x: -len(groups[x])):
            if a.show not in k:
                continue
            print(f"\n{k}:")
            for n in sorted(groups[k]):
                print("   ", n)
    else:
        print("\n`--show <word>` lists the blocks in a group, e.g. --show singular")
    print("\nNote: 'unexplained' mixes two things measured separately - a context this "
          "sweep\ndoes not build (a cart with items, a checkout session), and a site that "
          "has no such\ndata at all. core/site-tagline is empty here because blogdescription "
          "is empty;\ncore/tag-cloud because the site has 0 tags. Neither is broken.")


def cmd_rwd(s, a):
    """Every responsive mechanism the block editor gives you HERE, with the
    width each one actually uses.

    The reason this is a command and not a paragraph: the numbers disagree, and
    nothing in the editor tells you so. On this site four different widths all
    call themselves "mobile"."""
    gs = s.get("global_settings") or {}
    vp = gs.get("viewport") or {}
    print("1. per-block breakpoint STATES  (WP 7.1)   style[\"@mobile\"] / style[\"@tablet\"]")
    if vp:
        mob, tab = vp.get("mobile"), vp.get("tablet")
        print(f"     from theme.json settings.viewport: mobile={mob}  tablet={tab}")
        if mob:
            print(f"     @mobile  -> @media (width <= {mob})")
        if mob and tab:
            # A RANGE, not a max-width - a value set at @tablet does not apply
            # below the mobile breakpoint.
            print(f"     @tablet  -> @media ({mob} < width <= {tab})   <- a RANGE, not max-width")
        elif tab:
            print(f"     @tablet  -> @media (width <= {tab})")
    else:
        print("     settings.viewport not set - the defaults in WP_Theme_JSON apply")

    bp = s.get("block_breakpoints") or {}
    print(f"\n2. breakpoints blocks HARDCODE in their own stylesheet ({len(bp)} blocks)")
    print("     theme.json decides nothing about these.")
    for name, qs in sorted(bp.items()):
        if a.grep and a.grep not in name:
            continue
        print(f"     {name:24} {', '.join(qs)}")

    resp_attrs = []
    for name, b in s["blocks"].items():
        hits = [x for x in (b.get("attributes") or {})
                if any(k in x.lower() for k in ("stackedonmobile", "responsive", "overlaymenu",
                                                "mobilecolumns", "tabletcolumns"))]
        if hits:
            resp_attrs.append((name, hits))
    print(f"\n3. blocks with a responsive ATTRIBUTE ({len(resp_attrs)})")
    for name, hits in sorted(resp_attrs):
        print(f"     {name:24} {', '.join(hits)}")

    lay = gs.get("layout") or {}
    print("\n4. layout")
    print(f"     contentSize: {lay.get('contentSize')}   wideSize: {lay.get('wideSize')}")
    print(f"     useRootPaddingAwareAlignments: {gs.get('useRootPaddingAwareAlignments')}")
    fluid = (gs.get("typography") or {}).get("fluid")
    print(f"\n5. fluid typography: {j(fluid)}"
          + ("   <- every font-size you write is rewritten to clamp()" if fluid else ""))
    ts = s.get("theme_supports") or {}
    print(f"6. responsive-embeds theme support: {'yes' if ts.get('responsive-embeds') else 'no'}")


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
    # These count DATABASE records, which exist only where a user edited a
    # template; the files the theme ships are counted under Site Editor below.
    # Printing one number without the other reads as a contradiction.
    print(f"wp_template      : {t.get('wp_template', 0)} in the database (user-edited only)"
          + ("" if block_theme else "   - classic theme, so none are possible"))
    print(f"wp_template_part : {t.get('wp_template_part', 0)} in the database")
    print(f"synced patterns  : {t.get('synced_patterns', 0)}   (wp_block post type - edit once, changes everywhere)")
    print(f"registered patterns: {len(s.get('patterns', []))}   (inserted as a COPY, then independent)")
    pts = t.get("post_type_templates") or []
    print(f"post-type templates: {len(pts)}   (a starting block structure for new posts; works on any theme)")
    for p in pts:
        print(f"    {p['post_type']:16} lock:{p['template_lock'] or 'none'}  {', '.join(p['blocks'][:6])}")
    overrides = any(b["name"] == "core/pattern-overrides" for b in (s.get("binding_sources") or []))
    print(f"pattern overrides: {'available' if overrides else 'NOT registered'}"
          f"   (a synced pattern with per-instance editable slots, bound to attributes marked role:content)")

    pre = s.get("pretending")
    if pre:
        print(f"\n[ describing the site AS IF '{pre['theme']}' were active - nothing was changed ]")
        print(f"  faithful for: {pre['faithful_for']}")
        print(f"  STALE for   : {pre['stale_for']}")
        if pre.get("measured"):
            print(f"  measured    : {pre['measured']}")

    # --- the Site Editor ---
    res = t.get("resolved") or {}
    tpl, parts = res.get("wp_template") or [], res.get("wp_template_part") or []
    tj = t.get("theme_json") or {}
    print(f"\nSite Editor")
    if not block_theme and not tpl:
        print("  not available - a classic theme has no wp_template, and the page frame")
        print("  stays the theme's PHP. Everything below is what a BLOCK theme would add.")
    print(f"  templates      : {len(tpl)}" +
          (f"   ({', '.join(x['slug'] for x in tpl[:8])})" if tpl else ""))
    if tpl:
        # `theme` = still the file; `custom` = someone edited it and the database
        # copy now wins. That distinction is the whole of "why does the site not
        # look like the theme any more".
        cust = [x["slug"] for x in tpl if x.get("source") == "custom"]
        print(f"    of which user-edited (source=custom): {len(cust)}"
              + (f" - {', '.join(cust)}" if cust else ""))
    print(f"  template parts : {len(parts)}" +
          (f"   ({', '.join(x['slug'] for x in parts[:8])})" if parts else ""))
    print(f"  part areas     : {', '.join(t.get('template_part_areas') or [])}")
    print(f"  template types core knows: {len(t.get('default_template_types') or [])}")
    if tj.get("templateParts"):
        print(f"  theme.json templateParts: "
              + ", ".join(f"{x.get('name')}({x.get('area')})" for x in tj["templateParts"][:8]))
    if tj.get("customTemplates"):
        print(f"  customTemplates: "
              + ", ".join(f"{x.get('name')} -> {','.join(x.get('postTypes') or [])}"
                          for x in tj["customTemplates"]))
    sv = tj.get("style_variations") or []
    print(f"  style variations: {len(sv)}" + (f"   {', '.join(sv[:8])}" if sv else ""))
    uo = tj.get("user_overrides")
    if uo is not None:
        print(f"  user global-styles overrides: "
              + (", ".join(uo) if uo else "none (the wp_global_styles post is an empty shell)"))


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
    p.add_argument("--show", help="print a pattern\'s markup - canonical, site-specific reference")
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
    p = sub.add_parser("context")
    p.add_argument("--show")
    p = sub.add_parser("rwd")
    p.add_argument("--grep")
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
