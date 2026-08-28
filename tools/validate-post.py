#!/usr/bin/env python3
"""Pre-flight a post_content file of serialized block markup BEFORE writing it.

    python tools/validate-post.py page.html
    python tools/validate-post.py page.html --schema data/block-schema.json

Catches what WordPress will not. WP stores whatever you give it; the front end
renders the HTML of a static block verbatim and never reads its comment attrs,
the editor regenerates HTML from attrs and never trusts yours. A mismatch
between the two halves is invisible until someone opens the page - in one
surface or the other it is silently wrong.

Errors (exit 1):
  E-PARSE     grammar/JSON error, mismatched or unclosed delimiter
  E-BLOCK     blockName not registered on the target site - the block VANISHES
              in the editor's inserter sense: front end keeps raw HTML, editor
              shows it only after a recovery prompt
  E-TYPE      value's JSON type contradicts the schema type
  E-ENUM      value not in the attribute's enum
  E-SOURCED   a sourced attribute written into the comment JSON - it lives in
              the HTML; the comment copy does nothing
  E-PRESET    preset slug that does not exist on this site - the class lands in
              the HTML but no CSS anywhere defines it, so it styles NOTHING
  E-CLASS     comment attr requires a has-*/align* class the saved HTML lacks
              (front end never adds it; editor will and the two disagree)
  E-STYLE     style object demands inline CSS the saved HTML does not carry
  E-PARENT    block whose schema requires a parent/ancestor placed elsewhere
  E-EMPTY     content block with no saved HTML - renders literally nothing

Warnings:
  W-ATTR      attribute the server registry does not know - a typo (the editor
              drops it silently) or a JS-registered attribute the server can't see
  W-DYNHTML   inner HTML on a core pure-dynamic block (the callback regenerates it)
  W-CLASSNAME className/anchor in comment but not in the HTML
  W-WRAPPER   first element lacks the wp-block-* class this block normally carries
  W-EDITOR    block the SERVER registers but the editor's registry does not -
              the page renders and the editor cannot read or place it
  W-DEPRECATED the wrapper tag matches an OLD save() of this block. WordPress
              accepts it - that is what a deprecation is for - and rewrites it
              the moment anyone edits the block, running migrate() if it has one
  W-ORDER     class or inline-CSS order differs from what this block's save()
              writes. Legal, and the editor accepts it; what it does not survive
              is the editor's own next save, which regenerates the page and
              reshuffles it (measured: 5,465 bytes of drift on a 180-block page)
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blockmark
import gblib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Blocks whose save output carries no default wp-block-* class.
NO_WRAPPER_CLASS = {
    "core/paragraph", "core/list-item", "core/html", "core/more", "core/nextpage",
    "core/freeform", "core/shortcode", "core/missing", "core/block",
}

JSON_TYPES = {"string": str, "boolean": bool, "object": dict, "array": list,
              "integer": int, "number": (int, float), "null": type(None),
              "rich-text": str}


def first_tag_classes(html):
    """Classes of the first tag (for the wrapper check) and of ALL tags (for
    attr checks - button puts its color classes on the inner <a>, not the div)."""
    tags = re.findall(r"<[a-zA-Z][^>]*>", html or "")
    if not tags:
        return None, "", set()
    first = re.search(r'class="([^"]*)"', tags[0])
    everywhere = set()
    for t in tags:
        m = re.search(r'class="([^"]*)"', t)
        if m:
            everywhere.update(m.group(1).split())
    return tags[0], (first.group(1) if first else ""), everywhere


def inline_style(html):
    """Every style attribute in the block's own HTML, concatenated."""
    return ";".join(re.findall(r'style="([^"]*)"', html or ""))


def first_style(html):
    """Only the FIRST element's style attribute - the one save() composes."""
    tags = re.findall(r"<[a-zA-Z][^>]*>", html or "")
    if not tags:
        return ""
    m = re.search(r'style="([^"]*)"', tags[0])
    return m.group(1) if m else ""


class Report:
    def __init__(self):
        self.errors, self.warnings = [], []

    def err(self, code, where, msg):
        self.errors.append(f"{code:10} {where:34} {msg}")

    def warn(self, code, where, msg):
        self.warnings.append(f"{code:10} {where:34} {msg}")


def check_type(val, spec):
    t = spec.get("type")
    if t is None:
        return True
    types = t if isinstance(t, list) else [t]
    return any(isinstance(val, JSON_TYPES[x]) for x in types if x in JSON_TYPES) or not types


_SURFACE = [None]


def editor_surface():
    """Per-block save() shape, measured in the editor (data/editor-surface.json).

    Everything below it checks is legal markup - the editor accepts it. What it
    does NOT survive is the editor's own next save, which regenerates the page
    from save() and reshuffles anything written in a different order. Measured
    on a 180-block page: 5,465 bytes of drift from class order, declaration
    order and one undeclared className."""
    if _SURFACE[0] is None:
        p = Path(__file__).resolve().parent.parent / "data" / "editor-surface.json"
        try:
            _SURFACE[0] = json.loads(p.read_text(encoding="utf-8"))["blocks"]
        except Exception:
            _SURFACE[0] = {}
    return _SURFACE[0]


def _constraints(variants, key):
    """Orderings that hold in EVERY probe of this block.

    A block's class order is not a fixed list. core/separator emits
    `has-text-color has-alpha-channel-opacity` when a background is also set
    and the reverse when it is not - so treating one probe's output as THE
    order reports canonical markup as wrong (measured: four false positives on
    a page the editor itself confirmed byte-identical). Only a pair whose order
    never flips across the probes is a rule."""
    lists = [v.get(key) or [] for v in variants]
    lists = [[x for x in l if not x.startswith("ZZPROBE")] for l in lists if l]
    if not lists:
        return set()
    before, conflicting = set(), set()
    for lst in lists:
        idx = {x: i for i, x in enumerate(lst)}
        for a in lst:
            for b in lst:
                if a == b:
                    continue
                if idx[a] < idx[b]:
                    if (b, a) in before:
                        conflicting.add((a, b))
                        conflicting.add((b, a))
                    before.add((a, b))
    return before - conflicting


def _violation(before, actual):
    """The first pair the markup writes against a stable constraint."""
    for i in range(len(actual)):
        for k in range(i + 1, len(actual)):
            if (actual[k], actual[i]) in before:
                return actual[i], actual[k]
    return None


def deprecated_form(rep, where, srec, tag_str):
    """Is this markup an OLD form of the block rather than the current one?

    WordPress accepts it - that is what a deprecation is for - and then rewrites
    it the moment anyone edits the block, silently, with whatever `migrate()`
    decides. The check is deliberately narrow: only the wrapper TAG, which is
    unambiguous. Eight deprecations on this site change it, and each is a real
    trap for hand-written markup: core/button's pre-6.x form is a bare <a>
    where the current one is a <div> wrapping one, core/pullquote was a
    <blockquote> and is now a <figure>, core/cover was a <section>."""
    save = srec.get("save") or {}
    els = save.get("elements") or []
    if not els or not tag_str:
        return
    current = els[0].get("tag")
    m = re.match(r"<([a-zA-Z][a-zA-Z0-9]*)", tag_str)
    if not current or not m:
        return
    actual = m.group(1).lower()
    if actual == current:
        return
    for d in srec.get("deprecated") or []:
        sh = d.get("shape") or {}
        if sh.get("tag") == actual:
            how = " and migrate() REWRITES the attributes" if d.get("hasMigrate") else ""
            rep.warn("W-DEPRECATED", where,
                     f"<{actual}> is deprecated form #{d['index']} of this block; the current "
                     f"save() writes <{current}>. WordPress accepts it{how} - "
                     f"the next edit rewrites the block")
            return


def canon_order(rep, where, srec, classes, first_style):
    save = srec.get("save") or {}
    variants = save.get("variants") or []
    if not variants:
        return

    tokens = classes.split()
    if tokens:
        bad = _violation(_constraints(variants, "classes"), tokens)
        if bad:
            rep.warn("W-ORDER", where,
                     f"class order: '{bad[0]}' is written before '{bad[1]}', "
                     f"save() always puts them the other way - valid, but the "
                     f"editor's next save rewrites it")

    # Only the FIRST element's own style attribute. The concatenation of every
    # style in the block is right for asking "does the block carry this
    # declaration" and meaningless for asking about ORDER - it reported a
    # heading's line-height as preceding a background-color that belongs to a
    # different element.
    if first_style:
        props = [d.split(":")[0].strip() for d in first_style.split(";") if ":" in d]
        bad = _violation(_constraints(variants, "css"), props)
        if bad:
            rep.warn("W-ORDER", where,
                     f"inline CSS order: '{bad[0]}' is written before '{bad[1]}', "
                     f"save() always puts them the other way")


def validate(tree, schema, rep):
    blocks = schema["blocks"]
    presets = gblib.presets(schema)
    seen_anchors = {}

    def visit(node, parents):
        name = node["blockName"]
        if name is None:
            return
        where = name + (f"#{node['attrs'].get('anchor')}" if node["attrs"].get("anchor") else "")
        bdef = blocks.get(name)
        if bdef is None:
            rep.err("E-BLOCK", name, "not registered on the target site - check gb.py blocks --grep")
            return

        attrs = node.get("attrs") or {}
        adefs = bdef.get("attributes") or {}
        has_sourced = any(x.get("source") for x in adefs.values())
        pure_dynamic = bdef["is_dynamic"] and not has_sourced
        html = node.get("innerHTML", "")
        _tag, wrapper_classes, class_set = first_tag_classes(html)
        style_str = inline_style(html)

        srec = editor_surface().get(name)
        if srec is None and editor_surface():
            rep.warn("W-EDITOR", where,
                     "registered on the SERVER but not in the editor's block registry - "
                     "the page renders, and the editor cannot read or place this block")
        elif srec:
            canon_order(rep, where, srec, wrapper_classes, first_style(html))
            deprecated_form(rep, where, srec, _tag)

        # parent / ancestor
        if bdef.get("parent"):
            direct = parents[-1] if parents else None
            if direct not in bdef["parent"]:
                rep.err("E-PARENT", where,
                        f"needs direct parent {bdef['parent']}, got {direct or 'top level'}")
        if bdef.get("ancestor"):
            if not any(p in bdef["ancestor"] for p in parents):
                rep.err("E-PARENT", where, f"needs ancestor {bdef['ancestor']}, none above it")

        # attributes
        sup = bdef.get("supports") or {}
        typo_sup = sup.get("typography") if isinstance(sup.get("typography"), dict) else {}
        for an, av in attrs.items():
            adef = adefs.get(an)
            if adef is None:
                # the server registry cannot see JS-injected attributes.
                # textAlign is the known one: injected client-side when the block
                # declares supports.typography.textAlign.
                if an == "textAlign" and typo_sup.get("textAlign"):
                    if not pure_dynamic and av in gblib.TEXT_ALIGN_VALUES:
                        cls = f"has-text-align-{av}"
                        if cls not in class_set:
                            rep.err("E-CLASS", where,
                                    f"textAlign={av!r} requires class '{cls}' in the saved HTML")
                    continue
                # fitText: client-injected when supports.typography.fitText.
                # save() marks it with has-fit-text; the server adds the
                # Interactivity directives at render. Without the class the
                # editor's deprecation path silently EATS the attribute.
                if an == "fitText" and typo_sup.get("fitText"):
                    if av is True and not pure_dynamic and "has-fit-text" not in class_set:
                        rep.err("E-CLASS", where,
                                "fitText=true requires class 'has-fit-text' in the saved HTML "
                                "- without it the editor migrates the attribute away")
                    continue
                rep.warn("W-ATTR", where,
                         f"{an!r} not in the server registry - a typo (dropped silently) "
                         f"or a JS-registered attribute the server cannot see")
                continue
            if adef.get("source"):
                rep.err("E-SOURCED", where,
                        f"{an!r} is sourced from HTML (source:{adef['source']}) - "
                        f"the comment copy does nothing; put it in the markup")
                continue
            if not check_type(av, adef):
                rep.err("E-TYPE", where, f"{an}={json.dumps(av, ensure_ascii=False)[:40]} "
                        f"but schema says type:{adef.get('type')}")
            if "enum" in adef and av not in adef["enum"]:
                rep.err("E-ENUM", where, f"{an}={av!r} not in {adef['enum']}")

            kind = gblib.preset_kind_for(an)
            if kind and isinstance(av, str) and av:
                if av not in presets.get(kind, {}):
                    rep.err("E-PRESET", where,
                            f"{an}={av!r}: no {kind} preset with that slug on this site "
                            f"- gb.py presets {kind}")

            if not pure_dynamic:
                for cls in gblib.classes_for(name, an, av, bdef):
                    if cls not in class_set:
                        rep.err("E-CLASS", where, f"{an}={av!r} requires class '{cls}' "
                                f"in the saved HTML - it is not there")
                if an == "className" and isinstance(av, str):
                    missing = [c for c in av.split() if c not in class_set]
                    if missing:
                        rep.warn("W-CLASSNAME", where, f"className {missing} not in the HTML class attr")
                if an == "anchor" and isinstance(av, str):
                    if f'id="{av}"' not in html:
                        rep.warn("W-CLASSNAME", where, f'anchor "{av}" but no id="{av}" in the HTML')
                    if av in seen_anchors:
                        rep.warn("W-CLASSNAME", where, f"duplicate anchor #{av} (also {seen_anchors[av]})")
                    seen_anchors[av] = name

        # the style object
        style = attrs.get("style")
        if style and not pure_dynamic:
            for skind, slug in gblib.preset_slugs_in_style(style):
                if slug not in presets.get(skind, {}):
                    rep.err("E-PRESET", where,
                            f"style references var:preset|{skind}|{slug} - no such preset here")
            rules, style_classes, _notes = gblib.style_expectations(style, name)
            norm = re.sub(r"\s+", "", style_str)
            for prop, val in rules:
                want = re.sub(r"\s+", "", f"{prop}:{val}")
                if want not in norm:
                    rep.err("E-STYLE", where,
                            f"style attr promises {prop}:{val} - saved HTML inline style "
                            f"says {style_str[:60]!r}")
            for cls in style_classes:
                if cls not in class_set:
                    rep.err("E-CLASS", where,
                            f"style object requires class '{cls}' in the saved HTML")

        # emptiness / dead HTML. Many dynamic blocks keep saved HTML as their
        # skeleton by design (woocommerce/*, and 7.1's tabs/accordion, whose
        # callbacks only augment it). Warn only when the sweep MEASURED that the
        # callback produces markup from attrs alone - then yours competes with it.
        if (pure_dynamic and html.strip() and name.startswith("core/")
                and bdef.get("render_verdict") == "renders"):
            rep.warn("W-DYNHTML", where,
                     "inner HTML on a dynamic block whose callback renders from attrs alone")
        if not pure_dynamic and has_sourced and not html.strip() and not node["innerBlocks"]:
            rep.err("E-EMPTY", where, "content block with no saved HTML - renders nothing")
        if (not pure_dynamic and html.strip() and name not in NO_WRAPPER_CLASS):
            expect = "wp-block-" + name.replace("core/", "").replace("/", "-")
            if expect not in set(wrapper_classes.split()):
                rep.warn("W-WRAPPER", where, f"first element lacks '{expect}'"
                         " (theme CSS that targets it will miss)")

        for child in node.get("innerBlocks", []):
            visit(child, parents + [name])

    for n in tree:
        visit(n, [])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file")
    ap.add_argument("--schema")
    args = ap.parse_args()

    src = Path(args.file).read_text(encoding="utf-8")
    schema = gblib.load_schema(args.schema)
    rep = Report()
    try:
        tree = blockmark.parse(src)
    except ValueError as e:
        print(f"E-PARSE    {e}")
        sys.exit(1)

    validate(tree, schema, rep)
    n_blocks = sum(1 for _ in blockmark.walk(tree))
    for w in rep.warnings:
        print(w)
    for e in rep.errors:
        print(e)
    if rep.errors:
        print(f"FAIL  {len(rep.errors)} errors, {len(rep.warnings)} warnings in {n_blocks} blocks")
        sys.exit(1)
    print(f"OK  {n_blocks} blocks, {len(rep.warnings)} warnings, 0 errors "
          f"(schema: {schema['site_url']}, WP {schema['wp_version']})")


if __name__ == "__main__":
    main()
