#!/usr/bin/env python3
"""Shared library: schema loading + the serialization rules the client editor
applies at save time (which headless writing must reproduce by hand).

Everything here mirrors what @wordpress/block-editor does in JS when it saves a
block - the part of the pipeline that does NOT run on the server for static
blocks. gb.py is the CLI over it; validate-post.py enforces it.
"""
import json
import re
from pathlib import Path

DATA = Path(__file__).resolve().parent.parent / "data"


def load_schema(path=None):
    p = Path(path) if path else DATA / "block-schema.json"
    return json.loads(p.read_text(encoding="utf-8"))


def full_name(name):
    return name if "/" in name else f"core/{name}"


# ---- preset refs -----------------------------------------------------------

PRESET_KINDS = {
    "color": "color", "gradient": "gradient", "font-size": "font-size",
    "font-family": "font-family", "spacing": "spacing", "shadow": "shadow",
    "duotone": "duotone",
}


def preset_ref_to_var(ref):
    """'var:preset|spacing|50' -> 'var(--wp--preset--spacing--50)'.
    Returns None if ref is not a preset reference."""
    m = re.fullmatch(r"var:preset\|([a-z-]+)\|([a-zA-Z0-9-]+)", ref or "")
    if not m:
        return None
    return f"var(--wp--preset--{m.group(1)}--{m.group(2)})"


def presets(schema):
    """{kind: {slug: value}} from the merged global settings, all origins.
    'custom' (user) origin wins over 'theme' wins over 'default', like WP."""
    gs = schema.get("global_settings", {})
    spec = {
        "color": (("color", "palette"), "color"),
        "gradient": (("color", "gradients"), "gradient"),
        "duotone": (("color", "duotone"), "colors"),
        "font-size": (("typography", "fontSizes"), "size"),
        "font-family": (("typography", "fontFamilies"), "fontFamily"),
        "spacing": (("spacing", "spacingSizes"), "size"),
        "shadow": (("shadow", "presets"), "shadow"),
    }
    out = {}
    for kind, (path, vkey) in spec.items():
        node = gs
        for p in path:
            node = node.get(p, {}) if isinstance(node, dict) else {}
        slugs = {}
        if isinstance(node, dict):
            for origin in ("default", "theme", "custom"):
                for item in node.get(origin) or []:
                    slugs[str(item.get("slug", ""))] = item.get(vkey, "")
        out[kind] = slugs
    return out


# ---- save-time class formulas ---------------------------------------------
# attribute -> (classes the saved HTML must carry, preset kind the slug must exist in)

SLUG_ATTR_CLASSES = {
    "backgroundColor": (["has-background", "has-{v}-background-color"], "color"),
    "textColor":       (["has-text-color", "has-{v}-color"], "color"),
    "gradient":        (["has-background", "has-{v}-gradient-background"], "gradient"),
    "fontSize":        (["has-{v}-font-size"], "font-size"),
    "fontFamily":      (["has-{v}-font-family"], "font-family"),
    "borderColor":     (["has-border-color", "has-{v}-border-color"], "color"),
}

TEXT_ALIGN_VALUES = {"left", "center", "right"}


def classes_for(block, attr, value, block_def=None):
    """The classes the saved HTML must carry for this comment attribute,
    or [] when the attribute does not serialize to a class. Slug attrs only -
    the style object is handled by style_expectations()."""
    if attr in SLUG_ATTR_CLASSES and isinstance(value, str) and value:
        tpl, _kind = SLUG_ATTR_CLASSES[attr]
        return [c.format(v=value) for c in tpl]
    if attr == "textAlign" and value in TEXT_ALIGN_VALUES:
        return [f"has-text-align-{value}"]
    if attr == "align" and isinstance(value, str) and value:
        if value in ("wide", "full"):
            return [f"align{value}"]
        if value in TEXT_ALIGN_VALUES:
            # text blocks serialize has-text-align-*; box blocks serialize align*.
            sup = (block_def or {}).get("supports", {})
            if isinstance(sup.get("typography"), dict) and sup["typography"].get("textAlign"):
                return [f"has-text-align-{value}"]
            return [f"align{value}"]
    if attr == "dropCap" and value is True:
        return ["has-drop-cap"]
    if attr == "fitText" and value is True:
        return ["has-fit-text"]
    if attr == "layout" and isinstance(value, dict):
        return []  # render-time: WP injects the container class when serving
    return []


def preset_kind_for(attr):
    return SLUG_ATTR_CLASSES.get(attr, (None, None))[1]


# ---- the style object ------------------------------------------------------
# Data-driven from data/style-surface.json - the live site's own
# WP_Style_Engine::BLOCK_STYLE_DEFINITIONS_METADATA - plus the measured
# save-time vs render-time split (see references/supports-and-styles.md).

_ENGINE = None


def _engine():
    global _ENGINE
    if _ENGINE is None:
        p = DATA / "style-surface.json"
        _ENGINE = json.loads(p.read_text(encoding="utf-8"))["style_engine"] if p.exists() else {}
    return _ENGINE


# Measured: these style keys produce NOTHING in the saved HTML - the server
# (or a view script) applies them at render. Writing their CSS into the saved
# markup would make the editor flag the block.
RENDER_TIME_GROUPS = {"background", "position", "elements", "filter"}
RENDER_TIME_PROPS = {("spacing", "blockGap")}
STATE_KEY = re.compile(r"^(:|@)")  # :hover / @mobile / @tablet / @desktop

# Object-valued properties that expand to per-side / per-corner CSS.
_CORNERS = {"topLeft": "top-left", "topRight": "top-right",
            "bottomLeft": "bottom-left", "bottomRight": "bottom-right"}
_SIDES = ("top", "right", "bottom", "left")

BOX_GROUPS = {("spacing", "padding"): "padding", ("spacing", "margin"): "margin"}

# The JS style engine is ahead of the PHP one: these serialize inline at save
# (measured via the editor's own getSaveContent) but are absent from
# BLOCK_STYLE_DEFINITIONS_METADATA on the server.
ENGINE_SUPPLEMENT = {
    "typography.textShadow": "text-shadow",
    "outline.color": "outline-color",
    "outline.width": "outline-width",
    "outline.style": "outline-style",
    "outline.offset": "outline-offset",
}


def _css_value(v):
    return preset_ref_to_var(v) or v


# Blocks whose save() does NOT write the style object's colors inline - the
# attribute alone drives them (the theme/render pipeline reads it). Measured:
# core/separator carries has-text-color but an empty style attribute.
NO_INLINE_COLOR_BLOCKS = {"core/separator"}


def style_expectations(style, block=None):
    """What the saved HTML must carry for a style attribute object.

    Returns (rules, classes, notes):
      rules   [(css_property, css_value)] expected in the inline style
      classes [class names] expected in the class attribute
      notes   style keys that are render-time or unknown (asserted by
              verify-live against the delivered page, not against saved HTML)

    `block` lets a block opt out of rules that are block-specific (see
    NO_INLINE_COLOR_BLOCKS) - measured behaviour, not a guess.
    """
    rules, classes, notes = [], [], []
    if not isinstance(style, dict):
        return rules, classes, notes

    # per-block custom CSS (7.0): string under style.css -> has-custom-css
    if isinstance(style.get("css"), str) and style["css"].strip():
        classes.append("has-custom-css")

    engine = _engine()
    skip_color = block in NO_INLINE_COLOR_BLOCKS
    for group, props in style.items():
        if group == "css":
            continue
        if skip_color and group == "color":
            # attribute-only: still emit the classes, never the inline CSS
            if isinstance(props, dict):
                if props.get("text"):
                    classes.append("has-text-color")
                if props.get("background"):
                    classes.append("has-background")
            continue
        if STATE_KEY.match(group):
            notes.append(f"style.{group} (state - render-time wp-states-* CSS)")
            continue
        if group in RENDER_TIME_GROUPS:
            if group == "elements":
                classes.append("has-link-color") if isinstance(props, dict) and "link" in props else None
            notes.append(f"style.{group} (render-time)")
            continue
        if not isinstance(props, dict):
            # shadow is a bare string: style.shadow -> box-shadow
            if group == "shadow" and isinstance(props, str):
                rules.append(("box-shadow", _css_value(props)))
            continue
        for prop, val in props.items():
            key = (group, prop)
            if key in RENDER_TIME_PROPS:
                notes.append(f"style.{group}.{prop} (render-time)")
                continue
            if key == ("typography", "textAlign"):
                if val in TEXT_ALIGN_VALUES:
                    classes.append(f"has-text-align-{val}")
                continue
            # NOTE: a custom style.typography.fontSize does NOT automatically emit
            # has-custom-font-size. Measured: core/button's save adds it,
            # core/heading's does not - on heading the editor carries it as an
            # explicit `className`. So it is never generated here; where a
            # block needs it, the caller writes className (see el2blocks.py).
            if key in BOX_GROUPS:
                base = BOX_GROUPS[key]
                if isinstance(val, dict):
                    for side, sv in val.items():
                        if isinstance(sv, str):
                            rules.append((f"{base}-{side}", _css_value(sv)))
                elif isinstance(val, str):
                    rules.append((base, _css_value(val)))
                continue
            if key == ("border", "radius") and isinstance(val, dict):
                for corner, cv in val.items():
                    if corner in _CORNERS and isinstance(cv, str):
                        rules.append((f"border-{_CORNERS[corner]}-radius", _css_value(cv)))
                continue
            if group == "border" and prop in _SIDES and isinstance(val, dict):
                for sub, sv in val.items():
                    if isinstance(sv, str):
                        rules.append((f"border-{prop}-{sub}", _css_value(sv)))
                continue
            edef = engine.get(f"{group}.{prop}")
            if edef and edef.get("property_keys") and isinstance(val, (str, int, float)):
                css_prop = edef["property_keys"].get("default")
                if css_prop:
                    rules.append((css_prop, _css_value(str(val)) if isinstance(val, str) else str(val)))
                    cn = edef.get("classnames") or {}
                    for cls, flag in cn.items():
                        if flag is True and "$slug" not in cls:
                            classes.append(cls)
                    continue
            supp = ENGINE_SUPPLEMENT.get(f"{group}.{prop}")
            if supp and isinstance(val, (str, int, float)):
                rules.append((supp, _css_value(str(val)) if isinstance(val, str) else str(val)))
                continue
            notes.append(f"style.{group}.{prop}")
    return rules, classes, notes


def preset_slugs_in_style(style):
    """Every 'var:preset|kind|slug' reference inside a style object."""
    found = []

    def rec(v):
        if isinstance(v, str):
            m = re.fullmatch(r"var:preset\|([a-z-]+)\|([a-zA-Z0-9-]+)", v)
            if m:
                found.append((m.group(1), m.group(2)))
        elif isinstance(v, dict):
            for x in v.values():
                rec(x)
        elif isinstance(v, list):
            for x in v:
                rec(x)

    rec(style)
    return found
