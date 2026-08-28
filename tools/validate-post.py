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
            rules, style_classes, _notes = gblib.style_expectations(style)
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
