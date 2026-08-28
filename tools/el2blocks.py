#!/usr/bin/env python3
"""Convert an Elementor tree (_elementor_data) into serialized block markup —
driven by the elementor-headless schema, not by a hand-written widget table.

    wp post meta get 123 _elementor_data > page.json
    python tools/el2blocks.py page.json --el-skill ~/.claude/skills/elementor-headless > page.html
    python tools/validate-post.py page.html          # ALWAYS
    # then the editor byte-check (references/canonicalization.md)

    python tools/el2blocks.py page.json --report     # what mapped, what didn't

WHY IT READS THE OTHER SKILL
The sibling skill `elementor-headless` already measured, on live sites, which
CSS property every one of Elementor's 26,063 (control, selector) pairs actually
emits — `data/css-selectors.csv`. This converter reads that table and matches
it against THIS skill's `data/style-surface.json` (the block style engine's own
property→CSS map). 11,516 Elementor controls turn out to emit a property the
block style engine can express natively; the mapping between the two systems is
therefore *derived from two measured datasets*, not from someone's memory of
what `typography_font_size` is called this year.

Without --el-skill it still runs on a small built-in fallback map, and says so.

WHAT THIS IS, AND IS NOT
An honest structural translator, not a magic wand:
  - STRUCTURE and CONTENT convert faithfully (containers→groups with the right
    layout, headings keep level+alignment, text keeps its HTML, buttons keep
    link and label).
  - STYLE converts natively where the block engine has the property, and is
    escalated to per-block `style.css` where it does not.
  - Nothing is silently dropped: an unmappable widget becomes a visible
    core/html placeholder carrying its original settings, and --report lists
    every decision.
The output is a STARTING POINT. validate-post.py and the editor byte-check are
what make it correct.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gblib  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPORT: list[tuple[str, str, str]] = []

# Rules that must survive aggressive "remove unused CSS" optimisers. Per-block
# style.css compiles to a hash class injected at RENDER time, so a plugin that
# scans the raw HTML (Perfmatters RUCSS - measured on moksaweb.com) never sees
# the class and strips the rule. Layout the page cannot do without - content
# max-widths, column flex-basis - therefore goes into ONE design-layer <style>
# keyed by a stable class written into the markup itself.
DESIGN_RULES: list[str] = []
MEDIA_RULES: dict[str, list[str]] = {}
_SEQ = [0]

# Elementor's default responsive breakpoints, and the media query each control
# suffix compiles to. Every one of these is a MAX-width query except widescreen:
# Elementor is mobile-last, so `padding_mobile` means "at 767px and below".
#
# Missing this entirely was the single largest fidelity bug found: the converted
# page carried only DESKTOP values, so at 390px its h1 stayed 56px where the
# original dropped to 36px, and containers with an explicit desktop width stayed
# 1160px wide inside a 390px viewport - invisible only because the theme sets
# `body{overflow-x:hidden}`, which hides overflow instead of preventing it. A
# scrollbar check passes on that page; it is not a responsive check.
BREAKPOINTS = {
    "widescreen": "(min-width:2400px)",
    # Not a control suffix - only `hide_desktop` reaches it. The leading
    # underscore keeps it out of split_breakpoint's suffix matching.
    "_desktop": "(min-width:1025px)",
    "laptop": "(max-width:1366px)",
    "tablet_extra": "(max-width:1200px)",
    "tablet": "(max-width:1024px)",
    "mobile_extra": "(max-width:880px)",
    "mobile": "(max-width:767px)",
}
# Longest first: `_mobile_extra` must not be read as `_mobile` + "_extra".
BP_SUFFIXES = sorted(BREAKPOINTS, key=len, reverse=True)


def split_breakpoint(ctrl: str) -> tuple[str, str | None]:
    """`padding_mobile` -> ('padding', 'mobile'); `padding` -> ('padding', None)."""
    for bp in BP_SUFFIXES:
        if ctrl.endswith("_" + bp):
            return ctrl[: -len(bp) - 1], bp
    return ctrl, None


def design_rule(css_body: str, target: str = "") -> str:
    """Register a layout rule; returns the stable class to put on the element.

    The selector is doubled (`.x.x`) and every declaration marked important:
    themes routinely apply negative margins to the children of a constrained
    layout to cancel container padding (measured: Blocksy sets
    `margin-left:-22px` on them), which silently defeats a plain
    `margin-left:auto`. Layout the converted page depends on has to win."""
    cls = new_design_class()
    emit_design_rule(cls, css_body, target=target)
    return cls


def new_design_class() -> str:
    _SEQ[0] += 1
    return f"el2b-{_SEQ[0]}"


def emit_design_rule(cls: str, css_body: str, breakpoint: str | None = None,
                     pseudo: str | None = None, target: str = ""):
    """Write one rule for an already-allocated class, optionally inside a
    breakpoint's media query, for a pseudo-state, and/or aimed at a DESCENDANT
    of the element carrying the class.

    `target` exists because a block does not always let you put a class on the
    element you need to style. `core/button`'s `className` lands on the wrapper
    `<div class="wp-block-button">`, never on the `<a>` inside it - so a class
    written straight onto the `<a>` is markup the block's own save() would not
    produce, and the EDITOR rejects the block even though the server accepts it
    and the page looks right. Measured: four buttons showing "this block
    contains unexpected or invalid content"."""
    body = ";".join(f"{d.strip()} !important" for d in css_body.split(";") if d.strip())
    if not body:
        return
    rule = f".{cls}.{cls}{target}{pseudo or ''}{{{body}}}"
    if breakpoint:
        MEDIA_RULES.setdefault(breakpoint, []).append(rule)
    else:
        DESIGN_RULES.append(rule)


def note(level, widget, msg):
    REPORT.append((level, widget, msg))


# ---- the derived Elementor-control → block-style map ----------------------

# CSS property -> the block style path that produces it. Built from this
# skill's own style-surface.json (the engine's property_keys), so it stays
# correct across WordPress versions without editing this file.
def css_to_style_path() -> dict[str, tuple[str, ...]]:
    out = {}
    for key, spec in gblib._engine().items():
        prop = (spec.get("property_keys") or {}).get("default")
        if prop and "." in key:
            group, name = key.split(".", 1)
            out.setdefault(prop, (group, name))
    # the JS engine's extras, measured (gblib.ENGINE_SUPPLEMENT)
    for key, prop in gblib.ENGINE_SUPPLEMENT.items():
        group, name = key.split(".", 1)
        out.setdefault(prop, (group, name))
    # Elementor 4.x containers drive layout through CSS CUSTOM PROPERTIES
    # (--gap, --min-height, --justify-content...) rather than the property
    # itself, so the measured map reports the variable name. Fold each one back
    # onto the real property before looking it up.
    for var, real in {
        "--gap": "gap", "--row-gap": "row-gap", "--column-gap": "column-gap",
        "--min-height": "min-height", "--width": "width",
        "--justify-content": "justify-content", "--align-items": "align-items",
        "--flex-direction": "flex-direction", "--content-width": "max-width",
    }.items():
        if real in out:
            out.setdefault(var, out[real])
    # text-align: block-native, but as a CLASS not a declaration, so it is not
    # in the engine's property_keys - gblib.style_expectations emits the class.
    out.setdefault("text-align", ("typography", "textAlign"))
    out.setdefault("gap", ("spacing", "blockGap"))
    out.setdefault("--gap", ("spacing", "blockGap"))
    return out


def load_el_css_map(el_skill: Path | None) -> dict[tuple[str, str], list[str]]:
    """(widgetType, control) -> [css properties it emits], measured by the
    elementor-headless sweeps."""
    if not el_skill:
        return {}
    p = el_skill / "data" / "css-selectors.csv"
    if not p.exists():
        note("warn", "-", f"{p} not found - falling back to the built-in map")
        return {}
    out: dict[tuple[str, str], list[str]] = {}
    with open(p, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            # one control can drive several properties; the column separates
            # them by whitespace (and, for older rows, by "|").
            props = [x for x in re.split(r"[|\s]+", row.get("properties") or "") if x]
            if props:
                out[(row["owner"], row["control"])] = props
    return out


# Elementor value shapes -> CSS strings.
def size(v, default=None):
    if not isinstance(v, dict):
        return default
    s, u = v.get("size"), v.get("unit", "px")
    if s in (None, ""):
        return default
    return str(s) if u == "custom" else f"{s}{u}"


def box(v):
    if not isinstance(v, dict):
        return {}
    u = v.get("unit", "px")
    out = {}
    for side in ("top", "right", "bottom", "left"):
        val = v.get(side, "")
        if val not in ("", None):
            out[side] = str(val) if u == "custom" else f"{val}{u}"
    return out


def scalar(val):
    """Turn any Elementor control value into a CSS scalar, or None.

    `rgba(0,0,0,0)` is a DELIBERATE transparent - ghost buttons and overlay-free
    sections rely on it. Treating it as "no value" makes the block inherit a
    solid colour it was never meant to have."""
    if isinstance(val, dict):
        return size(val)
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str) and val.strip() and val not in ("default", "custom", "normal"):
        return val.strip()
    return None


ALIGN = {"left": "left", "center": "center", "right": "right"}
BOX_PROPS = {"padding": ("spacing", "padding"), "margin": ("spacing", "margin")}

# Controls whose effect the container logic already expresses through the block
# `layout` attribute (which the server compiles to wp-container-* CSS). Letting
# auto_style also write them into style.css would duplicate - and fight - it.
LAYOUT_HANDLED = {
    "flex_direction", "flex_justify_content", "flex_align_items", "flex_wrap",
    "content_width",
}
# Effects Elementor renders with machinery blocks have no equivalent for. They
# are reported once, not smuggled into style.css where they would not work.
UNSUPPORTED = {
    "background_overlay_background", "background_overlay_hover_background",
    "background_overlay_hover_opacity", "background_overlay_opacity",
    "background_hover_transition", "background_overlay_color",
}


class Style:
    def __init__(self):
        self.style: dict = {}
        self.extra_classes: list[str] = []
        self.responsive: dict[str, list[str]] = {}
        self._rwd_class: str | None = None
        # A descendant selector appended to every design rule this style emits;
        # see emit_design_rule. Set by a converter whose block cannot carry a
        # class on the element that needs styling.
        self.target: str = ""

    def at(self, breakpoint, css_body):
        """A declaration that applies only below (or above) a breakpoint.

        Blocks have a native per-block state for this in WP 7.1
        (`style["@mobile"]`), but it covers only ONE width and only the
        properties the style engine expresses. Elementor pages use up to six
        breakpoints and set things the engine has no path for, so every
        responsive value goes to the design layer, where all of them survive
        and RUCSS cannot strip them."""
        if css_body:
            self.responsive.setdefault(breakpoint, []).append(css_body)

    def at_default(self, breakpoint, css_body):
        """A breakpoint default that any explicit setting must be able to beat.
        Same specificity and same !important as everything else in the layer, so
        the only thing that decides is order: defaults go first."""
        if css_body:
            self.responsive.setdefault(breakpoint, []).insert(0, css_body)

    def layout_css_state(self, pseudo, css_body):
        """A declaration for a pseudo-state (`:hover`, `:focus`) that the
        block's own state object cannot express - it carries colours only, so
        a hover border, transform or shadow has nowhere else to go."""
        if css_body:
            cls = new_design_class()
            emit_design_rule(cls, css_body, pseudo=pseudo, target=self.target)
            self.extra_classes.append(cls)

    def layout_css(self, css_body):
        """Layout an optimiser must not be able to strip - goes to the design
        layer under a stable class, not to per-block style.css."""
        if css_body:
            self.extra_classes.append(design_rule(css_body, target=self.target))

    def set(self, path, value):
        if value in (None, "", {}):
            return
        node = self.style
        for p in path[:-1]:
            node = node.setdefault(p, {})
        node[path[-1]] = value

    def css(self, snippet):
        if snippet:
            prev = self.style.get("css", "")
            self.style["css"] = f"{prev} {snippet}".strip() if prev else snippet

    # The editor's inline CSS follows the style object's key order, and that
    # order is BLOCK-SPECIFIC (measured): a heading emits spacing before
    # typography; a button emits color first. Markup that gets it wrong is
    # valid but gets reordered on the next editor save.
    ORDER_DEFAULT = ["spacing", "color", "background", "border", "dimensions",
                     "typography", "shadow", "outline", "elements", "css"]
    ORDER_BY_BLOCK = {
        "core/button": ["color", "spacing", "border", "typography", "shadow",
                        "outline", "background", "dimensions", "elements", "css"],
    }

    # These order the STYLE OBJECT's keys - what goes in the comment JSON -
    # which is a different question from the order of the inline CSS the
    # object compiles to (that comes from the measurement, see css_order).
    # The editor reserializes the object exactly as it parsed it, so this only
    # has to be self-consistent, but the editor emits margin before padding and
    # top/right/bottom/left within a box, and matching it keeps a hand-edited
    # page and a generated one looking alike.
    SUB_ORDER = {"spacing": ["margin", "padding", "blockGap"],
                 "typography": ["fontSize", "fontFamily", "fontStyle", "fontWeight",
                                "letterSpacing", "lineHeight", "textAlign",
                                "textDecoration", "textTransform"],
                 "border": ["color", "radius", "style", "width"]}
    SIDES = ["top", "right", "bottom", "left"]

    def normalize(self, block=None):
        order = self.ORDER_BY_BLOCK.get(block or "", self.ORDER_DEFAULT)
        rank = {k: i for i, k in enumerate(order)}
        out = {}
        for group, val in sorted(self.style.items(),
                                 key=lambda kv: (rank.get(kv[0], len(order)), kv[0])):
            if isinstance(val, dict) and group in self.SUB_ORDER:
                sub = {k: i for i, k in enumerate(self.SUB_ORDER[group])}
                val = {k: v for k, v in sorted(val.items(),
                                               key=lambda kv: (sub.get(kv[0], 99), kv[0]))}
                for k, v in val.items():
                    if isinstance(v, dict) and set(v) <= set(self.SIDES):
                        val[k] = {s: v[s] for s in self.SIDES if s in v}
            out[group] = val
        self.style = out

    def resolve(self, block=None):
        self.normalize(block)
        rules, classes, _ = gblib.style_expectations(self.style, block)
        b = block or ""
        props = [p for p, _ in rules]
        rules = apply_order(rules, props,
                            canonical_constraints(b, "css", styled_element(b)))
        inline = []
        for p, v in rules:
            inline.append(f"{p}:{v}")
            if p == "font-size":
                # theme.json `typography.fluid` rewrites a plain inline
                # font-size into clamp(min, formula, MAX) at render: a 56px
                # heading resolves to 44.6px at 1440px, and the whole page
                # reads a type scale smaller than the Elementor original,
                # which emits fixed sizes. Restating the size in the design
                # layer (doubled selector, !important) pins it back.
                self.layout_css(f"font-size:{v}")
        extra = list(self.extra_classes)
        if self.responsive:
            # One class carries every breakpoint for this element, so the
            # markup gains a single class no matter how many widths are set.
            cls = new_design_class()
            for bp in BREAKPOINTS:            # widest query first, narrowest last
                if bp in self.responsive:
                    emit_design_rule(cls, ";".join(self.responsive[bp]), bp, target=self.target)
            extra.append(cls)
        return self.style, classes + extra, ";".join(inline)


def apply_element_width(st: Style, s: dict):
    """Elementor's Advanced tab lets ANY widget set its own width
    (`_element_custom_width`) - it is not a container setting, so the container
    pass never sees it. Measured on moksaweb.com: a 600px lead paragraph and 11
    other elements rendered full-bleed without this, which reflows the whole
    column."""
    if s.get("_element_width") not in (None, "", "initial", "inherit", "auto"):
        return
    w = size(s.get("_element_custom_width"))
    if w:
        # Elementor applies this to the widget WRAPPER, so the text element
        # itself still computes max-width:none and simply inherits the width.
        # Setting it on the text element instead makes the box narrower than
        # the original by its own padding - measured 534 vs 600.
        st.layout_css(f"max-width:{w};width:100%")


def gap_css(val) -> tuple[str, str]:
    """(css declarations, the single value to store as blockGap) for a gap.

    An Elementor gap is TWO values when `isLinked` is false - `size` then only
    holds the column figure. Reading `size` alone gave a 14px row gap where the
    original renders 18px, on every container that unlinks the two."""
    if not isinstance(val, dict):
        return "", ""
    col, row = val.get("column"), val.get("row")
    unit = val.get("unit", "px")
    one = size(val)
    if not val.get("isLinked", True) and col not in (None, "") and row not in (None, "") and col != row:
        c = str(col) if unit == "custom" else f"{col}{unit}"
        r = str(row) if unit == "custom" else f"{row}{unit}"
        return f"row-gap:{r};column-gap:{c}", r
    return (f"gap:{one}", one) if one else ("", "")


def apply_custom_css(st: "Style", s: dict, widget: str):
    """Elementor Pro's per-element Custom CSS, where `selector` stands for the
    element itself.

    Dropping it is invisible on a static screenshot and obvious in use: on the
    reference page four cards carry their entire hover behaviour here - a 10px
    translate and a border-colour change - and converted without it they are
    inert. The text is authored CSS, so it is emitted as written (no
    `!important` injection); only `selector` is rewritten, doubled so it keeps
    the specificity the rest of the design layer relies on."""
    css = s.get("custom_css")
    if not isinstance(css, str) or not css.strip():
        return
    cls = new_design_class()
    body = css.replace("selector", f".{cls}.{cls}").strip()

    # Every declaration the design layer writes is !important, including the
    # element's RESTING border colour. Authored CSS carries none, so a
    # `selector:hover{border-color:...}` lost to the resting rule and four
    # cards moved on hover without changing colour - the transform in the same
    # block worked, which is exactly what makes it easy to miss. Raise the
    # authored declarations to the same level rather than lowering the layer.
    def _important(m):
        decls = [d.strip() for d in m.group(1).split(";") if d.strip()]
        return "{" + ";".join(d if "!important" in d else f"{d} !important"
                              for d in decls) + "}"
    body = re.sub(r"\{([^{}]*)\}", _important, body)

    DESIGN_RULES.append(body)
    st.extra_classes.append(cls)
    note("info", widget, "custom_css -> design layer (`selector` rewritten to its class)")


def normalize_value(prop: str, v: str) -> str:
    """Elementor stores a font as a bare family name and its own font loader
    appends the generic fallback at render (`"Noto Sans TC", sans-serif`).
    Copying the bare name across gives the block no fallback at all: measured on
    13 elements, correct while the webfont loads and wrong the moment it does
    not."""
    if prop == "font-family" and "," not in v:
        # Deliberately UNQUOTED. The value ends up inside `style="..."`, so a
        # double quote terminates the attribute: quoting it produced 189
        # validator errors where the inline style simply stopped at the font.
        # `Noto Sans TC, sans-serif` is valid CSS unquoted, and getComputedStyle
        # normalises it back to the quoted form anyway.
        return f"{v}, sans-serif"
    return v


def responsive_css(widget: str, base: str, val, elmap) -> str:
    """The CSS a breakpoint variant of `base` should emit, as a declaration
    string. Returns "" when the control has no measured CSS or no value.

    This writes REAL properties, never Elementor's custom properties: on the
    original page `--gap` works because Elementor's own stylesheet consumes it,
    and on ours nothing does."""
    if base in ("padding", "margin") or base.endswith(("_padding", "_margin")):
        prop = "padding" if "padding" in base else "margin"
        b = box(val)
        return ";".join(f"{prop}-{s}:{b[s]}" for s in ("top", "right", "bottom", "left") if s in b)

    if base == "border_width" or base.endswith("_border_width"):
        b = box(val)
        if not b:
            return ""
        return ";".join(f"border-{s}-width:{b.get(s, '0px')}"
                        for s in ("top", "right", "bottom", "left"))

    if base == "flex_gap":
        return gap_css(val)[0]

    v = scalar(val)
    if v is None:
        return ""

    # Container width is the most common responsive control on a real page (71
    # of the 78 on the reference page) and the one a naive `width:100%` fails
    # to fix: the desktop rule states `flex:0 0 58%;max-width:58%`, and a
    # max-width at equal specificity and equal !important still wins over a
    # plain width. Measured: the hero heading rendered 192px wide inside a
    # 346px column. The breakpoint has to restate all three.
    if base in ("width", "boxed_width", "content_width"):
        return f"flex:0 0 {v};max-width:{v};width:{v}"
    props = elmap.get((widget, base))
    if not props:
        # `_element_custom_width` and friends are Advanced-tab controls the
        # widget sweep never recorded against this widget; they still have a
        # single obvious property.
        # `flex_gap` never reaches the measured CSS map because the desktop path
        # handles it as a layout attribute, so its breakpoint variant found no
        # property and the container kept its desktop gap at mobile.
        fallback = {"_element_custom_width": "max-width", "content_width": "max-width",
                    "width": "width", "min_height": "min-height", "height": "min-height",
                    "flex_gap": "gap"}
        prop = fallback.get(base)
        if not prop:
            return ""
        props = [prop]
    out = []
    for p in props:
        p = p[2:] if p.startswith("--") else p
        if p in ("gap", "row-gap", "column-gap", "content-width"):
            p = "max-width" if p == "content-width" else p
        out.append(f"{p}:{v}")
    return ";".join(out[:1] if len(out) > 2 else out)


def auto_style(st: Style, widget: str, settings: dict, elmap, cssmap, *, prefix_filter=None):
    """Map every Elementor setting whose measured CSS the block engine can
    express. Anything with a known CSS property but no block path goes to
    style.css rather than being dropped."""
    for ctrl, val in settings.items():
        if prefix_filter and not ctrl.startswith(prefix_filter):
            continue

        # Responsive variants are handled first and never fall through: a
        # breakpoint value has to reach the design layer even when the desktop
        # control is one the block `layout` attribute covers, because `layout`
        # has no per-breakpoint form.
        base, bp = split_breakpoint(ctrl)
        # Elementor's Responsive tab hides an element per device
        # (`hide_mobile: "hidden"`). There is no CSS map entry for it, so it was
        # silently dropped and the element showed up on every width.
        # The value is the device-tagged string `hidden-mobile`, not a bare
        # "hidden" - guessing the shape cost a 198px decorative SVG that should
        # have been hidden at 390px and instead pushed the hero 218px taller.
        if ctrl.startswith("hide_") and isinstance(val, str) and val.startswith("hidden"):
            device = ctrl[5:]
            query = BREAKPOINTS.get(device) or ("(min-width:1025px)" if device == "desktop" else None)
            if query:
                st.at(device if device in BREAKPOINTS else "_desktop", "display:none")
            else:
                note("warn", widget, f"{ctrl}: unknown device, element left visible")
            continue
        if bp:
            if "hover" in ctrl or ctrl.endswith("_focus") or base in UNSUPPORTED:
                continue
            css = responsive_css(widget, base, val, elmap)
            if css:
                st.at(bp, css)
            continue

        if ctrl in LAYOUT_HANDLED:
            continue          # the block `layout` attribute already carries it
        if "hover" in ctrl or ctrl.endswith("_focus"):
            # Measured: the CSS map reports the same property for the hover
            # control as for the normal one, so an undiscriminating pass writes
            # the HOVER colour as the resting colour - four ghost buttons on the
            # test page came out solid white. States are handled explicitly by
            # each converter (style[":hover"]).
            continue
        if ctrl in UNSUPPORTED:
            if scalar(val) or isinstance(val, dict):
                note("warn", widget, f"{ctrl}: Elementor-only effect, dropped (no block equivalent)")
            continue
        props = elmap.get((widget, ctrl))
        if not props:
            continue
        # box-model controls come as dimension objects
        if ctrl in ("padding", "margin") or ctrl.endswith(("_padding", "_margin")):
            base = "padding" if "padding" in ctrl else "margin"
            b = box(val)
            if b:
                st.set(BOX_PROPS[base], b)
            continue

        # Border width is PER SIDE in Elementor and a single value in the block
        # style object. Measured on moksaweb.com: six containers use a 1px TOP
        # rule as a divider (`{top:1, right:0, bottom:0, left:0}`); collapsing
        # that to one value drew a 2.4px box around each of them - the most
        # visible error on the page. Uniform widths stay native; anything
        # per-side goes to the design layer where all four sides survive.
        # Border radius is a BOX in Elementor ({top,right,bottom,left}) and
        # `scalar()` returns None for it, so every radius on the page was
        # dropped and each element fell back to the theme's - measured 3px
        # against 8px on every button. The block takes either one value or a
        # per-corner object; Elementor's box maps corner-wise clockwise from
        # top-left.
        if ctrl == "border_radius" or ctrl.endswith("_border_radius"):
            b = box(val)
            if not b:
                continue
            vals = set(b.values())
            if len(vals) == 1:
                st.set(("border", "radius"), next(iter(vals)))
            else:
                st.set(("border", "radius"), {
                    "topLeft": b.get("top", "0px"), "topRight": b.get("right", "0px"),
                    "bottomRight": b.get("bottom", "0px"), "bottomLeft": b.get("left", "0px")})
            continue

        if ctrl in ("border_width",) or ctrl.endswith("_border_width"):
            b = box(val)
            if not b:
                continue
            vals = set(b.values())
            if len(vals) == 1 and len(b) == 4:
                st.set(("border", "width"), next(iter(vals)))
            else:
                sides = ";".join(f"border-{side}-width:{b.get(side, '0px')}"
                                 for side in ("top", "right", "bottom", "left"))
                st.layout_css(sides + ";border-style:solid")
                note("info", widget, f"per-side border {b} -> design layer (block border.width is one value)")
            continue

        v = scalar(val)
        if v is None:
            continue
        v = normalize_value(props[0], v)
        # A control can emit several properties (Elementor's --gap sets
        # row-gap and column-gap too). Take the first one the block engine can
        # express; only escalate to style.css if NONE of them map.
        for prop in props:
            path = cssmap.get(prop)
            if path:
                st.set(path, v)
                break
        else:
            # Elementor writes many properties as CSS custom properties
            # (--overflow, --align-items). Its own stylesheet consumes those;
            # ours does not, so emit the REAL property in style.css.
            prop = props[0]
            if prop.startswith("--"):
                prop = prop[2:]
            st.css(f"{prop}:{v}")
            note("info", widget, f"{ctrl} -> style.css ({prop}: no block-native path)")


_SURFACE = [None]
_ORDER_CACHE: dict = {}
PROBE_CLASS = "ZZPROBECLS"


def _surface():
    """data/editor-surface.json - what each block's save() actually writes.

    This file replaces four hand-written tables that used to live in this
    module. They were derived from FOUR blocks by reading the editor's output
    by hand, and they were wrong twice: once about where `className` sits in
    the class list, once about the inline-CSS order being an order over style
    GROUPS rather than over CSS properties. Reading the measurement instead
    means a different site, or the next WordPress release, moves the converter
    with it."""
    if _SURFACE[0] is None:
        p = Path(__file__).resolve().parent.parent / "data" / "editor-surface.json"
        try:
            _SURFACE[0] = json.loads(p.read_text(encoding="utf-8"))["blocks"]
        except Exception:
            note("warn", "-", "data/editor-surface.json missing - canonical ordering "
                              "falls back to input order; markup stays valid but the "
                              "editor's next save may reshuffle it")
            _SURFACE[0] = {}
    return _SURFACE[0]


def apply_order(items, tokens, before):
    """Order `items` by the constraints in `before`, keeping input order
    wherever save() does not decide.

    A total order cannot express this block surface. core/separator emits
    has-text-color before has-alpha-channel-opacity when a background is set
    and after when it is not - so any single list picks one and rewrites the
    other case. Sorting by stable constraints only leaves the undecided pairs
    exactly as the converter emitted them, which is what the editor does too."""
    remaining = list(range(len(items)))
    out = []
    while remaining:
        for pos, i in enumerate(remaining):
            if not any((tokens[k], tokens[i]) in before for k in remaining if k != i):
                out.append(items[i])
                remaining.pop(pos)
                break
        else:                                   # cycle - impossible, never hang
            out.extend(items[k] for k in remaining)
            break
    return out


def canonical_constraints(block: str, kind: str, element: int = 0) -> set:
    """Pairs (a, b) meaning save() always writes a before b."""
    key = (block, kind, element, "pairs")
    if key in _ORDER_CACHE:
        return _ORDER_CACHE[key]
    rec = (_surface().get(block) or {}).get("save") or {}
    if element == 0:
        lists = [v.get(kind) or [] for v in (rec.get("variants") or [])]
    else:
        els = rec.get("elements") or []
        lists = [els[element].get(kind) or []] if len(els) > element else []
    before, conflicting = set(), set()
    for lst in [x for x in lists if x]:
        idx = {t: i for i, t in enumerate(lst)}
        for a in lst:
            for b in lst:
                if a != b and idx[a] < idx[b]:
                    if (b, a) in before:
                        conflicting.add((a, b))
                        conflicting.add((b, a))
                    before.add((a, b))
    _ORDER_CACHE[key] = before - conflicting
    return _ORDER_CACHE[key]


def canonical_order(block: str, kind: str, element: int = 0) -> list[str]:
    """A total order for `kind` ('classes' or 'css') on one element of `block`.

    The probe records several attribute combinations, and a block's order is
    not always the same list across them (core/separator moves
    has-text-color relative to has-alpha-channel-opacity depending on whether a
    background is set). So the orderings that hold in EVERY probe are collected
    as pairwise constraints and topologically sorted; a pair that ever flips
    constrains nothing."""
    key = (block, kind, element)
    if key in _ORDER_CACHE:
        return _ORDER_CACHE[key]

    rec = (_surface().get(block) or {}).get("save") or {}
    if element == 0:
        lists = [v.get(kind) or [] for v in (rec.get("variants") or [])]
    else:
        els = rec.get("elements") or []
        lists = [els[element].get(kind) or []] if len(els) > element else []
    lists = [x for x in lists if x]

    before, conflicting = set(), set()
    seen: list[str] = []
    for lst in lists:
        for t in lst:
            if t not in seen:
                seen.append(t)
        idx = {t: i for i, t in enumerate(lst)}
        for a in lst:
            for b in lst:
                if a == b:
                    continue
                if idx[a] < idx[b]:
                    if (b, a) in before:
                        conflicting.add((a, b))
                        conflicting.add((b, a))
                    before.add((a, b))
    before -= conflicting

    # Stable topological sort: repeatedly take the first token nothing
    # unplaced must precede.
    order, remaining = [], list(seen)
    while remaining:
        for t in remaining:
            if not any((o, t) in before for o in remaining if o != t):
                order.append(t)
                remaining.remove(t)
                break
        else:                       # a cycle cannot happen, but never hang
            order.extend(remaining)
            break
    _ORDER_CACHE[key] = order
    return order


def attr_after_class(block: str, element: int, attr: str) -> bool:
    """Does save() write `attr` AFTER the class attribute on this element?

    Attribute order inside the tag is part of byte-identity: core/button emits
    `<a class="..." href="...">`, and writing the href first is valid, renders
    identically, and is rewritten on the editor's next save."""
    els = ((_surface().get(block) or {}).get("save") or {}).get("elements") or []
    if len(els) <= element:
        return False
    order = els[element].get("attrs") or []
    if attr not in order or "class" not in order:
        return False
    return order.index(attr) > order.index("class")


def styled_element(block: str) -> int:
    """Which element of this block carries the style attribute.

    core/button splits itself: the wrapper takes min-height, the <a> takes
    everything else. Picking the richest one from the measurement avoids
    naming the block here."""
    els = ((_surface().get(block) or {}).get("save") or {}).get("elements") or []
    best, best_n = 0, -1
    for i, el in enumerate(els):
        n = len(el.get("css") or [])
        if n > best_n:
            best, best_n = i, n
    return best


def css_order(block: str) -> list[str]:
    return canonical_order(block, "css", styled_element(block))


def token_fn(block: str, element: int = 0, declared: set | None = None):
    """Map a class in OUR markup to the token the probe recorded for it.

    `declared` is what went into the block's `className` attribute; those land
    wherever the probe's placeholder landed, whatever they are called. The same
    class can arrive two ways: core/button's save() GENERATES
    `has-custom-font-size` near the end of the link's list, while core/heading
    does not generate it at all and it reaches the markup only through
    className, early."""
    known = set(canonical_order(block, "classes", element))
    declared = declared or set()

    def token_of(c: str) -> str:
        if c in declared and c not in known:
            return PROBE_CLASS
        if c in known:
            return c
        if c.startswith("el2b-"):
            return PROBE_CLASS
        # A class from a family the probe sampled once - it recorded
        # has-text-align-LEFT and the page uses right - stands in for its sibling.
        if c.startswith("has-text-align-"):
            for k in known:
                if k.startswith("has-text-align-"):
                    return k
        for suffix, kin in (("-font-size", "has-large-font-size"),
                            ("-font-family", "has-pf-font-family"),
                            ("-background-color", "has-background"),
                            ("-color", "has-text-color")):
            if c.endswith(suffix) and kin in known:
                return kin
        return c          # unknown: constrained by nothing, keeps its place

    return token_of


def wrapper(tag, classes, inline, inner, *, extra="", extra_after=False):
    """`extra_after` puts the block-specific attributes AFTER class.

    Attribute order inside the tag is part of byte-identity too: core/button's
    save() emits `<a class="..." href="..." style="...">`, and writing the href
    first is valid, renders the same, and still makes the editor's resave
    rewrite the tag."""
    # Class ORDER is applied later, in comment(), where the block name is
    # known - see canonicalize_classes.
    cls = " ".join(dict.fromkeys(c for c in classes if c))
    head = ([f'class="{cls}"'] if cls else [])
    tail = ([f'style="{inline}"'] if inline else [])
    mid = [extra] if extra else []
    bits = [tag] + (head + mid if extra_after else mid + head) + tail
    return f"<{' '.join(bits)}>{inner}</{tag}>"


def canonicalize_classes(block: str, html: str, class_name: str = "") -> str:
    """Reorder the class attribute of this block's OWN elements to match save().

    Only the part of the markup before the first nested block. `inner` contains
    the whole subtree, so numbering every class attribute in it hands a child's
    classes the parent's element index - which is not a shape at all, and it
    sorted a paragraph's classes into the order of a group's third element."""
    if not (_surface().get(block) or {}).get("save"):
        return html
    cut = html.find("<!-- wp:")
    head, tail = (html[:cut], html[cut:]) if cut != -1 else (html, "")
    idx = [0]
    declared = set(class_name.split())

    def fix(m):
        i = idx[0]
        idx[0] += 1
        classes = list(dict.fromkeys(m.group(1).split()))
        tok = token_fn(block, i, declared)
        ordered = apply_order(classes, [tok(c) for c in classes],
                              canonical_constraints(block, "classes", i))
        return f'class="{" ".join(ordered)}"'

    return re.sub(r'class="([^"]*)"', fix, head) + tail


def _blockdef(name):
    try:
        return gblib.load_schema()["blocks"].get(name) or {}
    except Exception:
        return {}


def comment(name, attrs, inner=None):
    short = name[5:] if name.startswith("core/") else name

    bd = _blockdef(name)
    sup = bd.get("supports") or {}

    # The editor's PARSER pulls any class it did not generate off the wrapper
    # and into the `className` attribute. So markup that carries a design-layer
    # class only in the HTML stays valid, but the editor's own resave writes
    # `"className":"el2b-65 el2b-66"` into the comment - 5,465 bytes of
    # difference on this page, i.e. the next manual save rewrites the post.
    # Declaring it ourselves is what the parser would have done.
    # Gate on `customClassName` ONLY. `supports.className: false` is a
    # different flag - it says "do not add the generated wp-block-<name>
    # class", not "no custom classes allowed", and core/paragraph sets exactly
    # that. Conflating the two silently skipped every paragraph on the page.
    if inner and attrs is not None and sup.get("customClassName") is not False:
        m = re.match(r"\s*<[a-z][a-z0-9]*\b[^>]*\bclass=\"([^\"]*)\"", inner)
        if m:
            mine = [c for c in m.group(1).split() if c.startswith("el2b-")]
            if mine:
                # MERGE, never skip: a heading already declares
                # `className:"has-custom-font-size"`, and bailing out there left
                # its design classes undeclared. The parser puts every custom
                # class in one attribute, design classes first.
                existing = [c for c in (attrs.get("className") or "").split() if c]
                attrs["className"] = " ".join(
                    dict.fromkeys(mine + existing))

    # Put every element's class list in the order this block's save() writes.
    # Doing it HERE, where the block name is known and the markup is already
    # built, keeps one choke point instead of threading an ordering through
    # every converter - and means each converter can emit classes in whatever
    # order reads best.
    if inner:
        inner = canonicalize_classes(name, inner, attrs.get("className", "") if attrs else "")

    # Attribute order in the comment JSON follows the block's REGISTERED
    # attribute order (the editor iterates blockType.attributes), not insertion
    # order. Getting it wrong is valid but not byte-identical, so the next save
    # reshuffles the whole page.
    order = list(bd.get("attributes") or {})
    if attrs and order:
        rank = {k: i for i, k in enumerate(order)}
        attrs = {k: attrs[k] for k in sorted(attrs, key=lambda k: (rank.get(k, len(order)), k))}

    a = ""
    if attrs:
        a = " " + json.dumps(attrs, ensure_ascii=False, separators=(",", ":")) \
            .replace("--", "\\u002d\\u002d").replace("<", "\\u003c") \
            .replace(">", "\\u003e").replace("&", "\\u0026")
    if inner is None:
        return f"<!-- wp:{short}{a} /-->"
    return f"<!-- wp:{short}{a} -->\n{inner}\n<!-- /wp:{short} -->"


# ---- widget converters (structure/content; style comes from auto_style) ----

def conv_heading(e, ctx) -> str:
    s = e.get("settings", {})
    raw = s.get("header_size", "h2")

    # Elementor's heading widget is routinely used as styled TEXT with
    # header_size div/span/p. Emitting h2 for those would invent a document
    # outline the original never had - 45 sibling h2s on one real page. Those
    # convert to a paragraph carrying the same styling; only real h1-h6 stay
    # headings.
    if not re.fullmatch(r"h[1-6]", raw or ""):
        note("info", "heading", f"header_size '{raw}' is styled text, not a heading -> core/paragraph")
        st = Style()
        if ALIGN.get(s.get("align", "")):
            st.set(("typography", "textAlign"), ALIGN[s["align"]])
        auto_style(st, "heading", s, ctx["elmap"], ctx["cssmap"])
        apply_element_width(st, s)
        st.layout_css("margin-block:0")
    
        style, classes, inline = st.resolve("core/paragraph")
        attrs = {"style": style} if style else {}
        return comment("core/paragraph", attrs,
                       wrapper("p", classes, inline, s.get("title", "")))

    level = int(raw[1])
    st = Style()
    if ALIGN.get(s.get("align", "")):
        st.set(("typography", "textAlign"), ALIGN[s["align"]])
    auto_style(st, "heading", s, ctx["elmap"], ctx["cssmap"])
    # Elementor resets widget margins; a theme does not. Without stating it,
    # every heading picks up the theme's own top margin (measured: 8-18px on
    # 7 elements, which then reflows their width).
    st.layout_css("margin-block:0")
    style, classes, inline = st.resolve("core/heading")
    attrs = {}
    if level != 2:
        attrs["level"] = level
    # Measured: on core/heading a custom font size travels as an explicit
    # className (the editor does not generate it) - without this the block is
    # valid but the editor's resave rewrites the markup.
    if (style.get("typography") or {}).get("fontSize"):
        attrs["className"] = "has-custom-font-size"
        classes = classes + ["has-custom-font-size"]
    if style:
        attrs["style"] = style
    return comment("core/heading", attrs,
                   wrapper(f"h{level}", ["wp-block-heading"] + classes, inline, s.get("title", "")))


def conv_text_editor(e, ctx) -> str:
    s = e.get("settings", {})
    raw = (s.get("editor") or "").strip()
    st = Style()
    if ALIGN.get(s.get("align", "")):
        st.set(("typography", "textAlign"), ALIGN[s["align"]])
    auto_style(st, "text-editor", s, ctx["elmap"], ctx["cssmap"])
    apply_element_width(st, s)
    st.layout_css("margin-block:0")
    
    style, classes, inline = st.resolve("core/paragraph")
    attrs = {"style": style} if style else {}
    m = re.fullmatch(r"<p>(.*?)</p>", raw, re.S)
    if m or (raw and not re.search(r"<(ul|ol|table|div|h[1-6])", raw, re.I)):
        text = m.group(1).strip() if m else re.sub(r"</?p>", "", raw).strip()
        return comment("core/paragraph", attrs, wrapper("p", classes, inline, text))
    note("info", "text-editor", "rich HTML kept verbatim in core/html")
    return comment("core/html", {}, raw)


def conv_button(e, ctx) -> str:
    s = e.get("settings", {})
    href = ((s.get("link") or {}).get("url")) or ""
    st = Style()
    # Everything this button sends to the design layer must be aimed at the
    # <a>, because the class itself can only live on the wrapper (see below).
    st.target = " .wp-block-button__link"
    auto_style(st, "button", s, ctx["elmap"], ctx["cssmap"])
    apply_element_width(st, s)
    apply_custom_css(st, s, "button")

    # A button icon is a Font Awesome glyph loaded from Elementor's own icon
    # font, which a block page does not ship. Reported rather than dropped: the
    # label still converts, and the choice of replacement (an inline SVG, a
    # text glyph, none) belongs to whoever is doing the migration.
    # Elementor's own stylesheet says `.elementor-button { line-height: 1 }`,
    # read off the rendered original. A converted button that stays silent
    # inherits the THEME's line-height instead - measured 26.4px against
    # 16px, which made every button 10px taller and was the whole of a
    # constant +21px page-height difference. A framework default is still a
    # value; it has to be stated, exactly like the container's 20px gap.
    if not size(s.get("typography_line_height")):
        st.set(("typography", "lineHeight"), "1")

    icon = ((s.get("selected_icon") or {}).get("value"))
    if icon:
        note("warn", "button", f"icon '{icon}' dropped - Font Awesome is not loaded on a block page; "
                               f"re-add as an inline SVG if it carries meaning")

    # Elementor names the button's hover TEXT colour `hover_color` - flatly,
    # with no `button_` prefix and no `_text_` in it, unlike its background and
    # border siblings. Reading only the symmetrical name found nothing, so
    # every button kept its resting text colour while the background inverted
    # underneath it: white on white on all three buttons of the page.
    hover_bg = s.get("button_background_hover_color")
    hover_fg = s.get("hover_color") or s.get("button_hover_text_color")
    if hover_bg or hover_fg:
        hv = {}
        if hover_bg:
            hv["background"] = hover_bg
        if hover_fg:
            hv["text"] = hover_fg
        st.style[":hover"] = {"color": hv}   # button IS in the pseudo allowlist

    # The block :hover state carries colours only. A hover BORDER colour, and
    # the transition that makes any of it a fade rather than a jump, go to the
    # design layer. Elementor's own stylesheet says
    # `.elementor-button { transition: all .3s }`; a converted button inherited
    # the theme's 0.12s, which reads as a different button.
    hover_border = s.get("button_hover_border_color")
    trans = "transition:all .3s"
    st.layout_css(trans)
    if hover_border:
        st.layout_css_state(":hover", f"border-color:{hover_border}")
    style, classes, inline = st.resolve("core/button")
    attrs = {"style": style} if style else {}
    # Measured, and the OPPOSITE of core/heading: core/button's own save()
    # generates has-custom-font-size for a custom size (heading needs it as an
    # explicit className instead). Block-specific, so it lives at the call site.
    if (style.get("typography") or {}).get("fontSize"):
        classes = classes + ["has-custom-font-size"]
    # core/button's save() puts the block's `className` on the WRAPPER div and
    # generates the <a>'s class list itself. A design-layer class written onto
    # the <a> is therefore markup save() would never produce: the server stores
    # it, the page renders correctly, and the EDITOR marks the block invalid -
    # "this block contains unexpected or invalid content" on all four buttons,
    # with an offer to restore that would have thrown the styling away. So the
    # el2b-* classes ride on the wrapper (declared in `className` so save()
    # reproduces them) and their rules reach the link through st.target.
    design_cls = [c for c in classes if c.startswith("el2b-")]
    link_cls = ["wp-block-button__link"] + \
               [c for c in classes if c != "has-custom-css" and not c.startswith("el2b-")] + \
               ["wp-element-button"]
    wrap_cls = ["wp-block-button"] + [c for c in classes if c == "has-custom-css"] + design_cls
    if design_cls:
        attrs["className"] = " ".join(design_cls)
    a = wrapper("a", link_cls, inline, s.get("text", ""),
                extra=f'href="{html.escape(href)}"' if href else "",
                extra_after=attr_after_class("core/button", 1, "href"))
    button = comment("core/button", attrs, wrapper("div", wrap_cls, "", a))
    layout = {}
    if s.get("align") in ALIGN:
        layout = {"layout": {"type": "flex", "justifyContent": s["align"]}}
    return comment("core/buttons", layout, f'<div class="wp-block-buttons">{button}</div>')


def conv_image(e, ctx) -> str:
    s = e.get("settings", {})
    img = s.get("image") or {}
    url, iid = img.get("url", ""), img.get("id")
    if not url:
        note("warn", "image", "no url - skipped")
        return ""
    st = Style()
    auto_style(st, "image", s, ctx["elmap"], ctx["cssmap"], prefix_filter="image_")
    apply_element_width(st, s)
    style, classes, inline = st.resolve("core/image")
    attrs = {"id": iid} if iid else {}
    if style:
        attrs["style"] = style
    tag = (f'<img src="{html.escape(url)}" alt="{html.escape(s.get("alt","") or "")}"'
           + (f' class="wp-image-{iid}"' if iid else "")
           + (f' style="{inline}"' if inline else "") + "/>")
    return comment("core/image", attrs,
                   wrapper("figure", ["wp-block-image", "size-full"] + classes, "", tag))


def conv_divider(e, ctx) -> str:
    # Measured: core/separator's save() puts the color in the style ATTRIBUTE
    # only (never inline CSS on the <hr>), and always carries
    # has-alpha-channel-opacity for its default opacity attribute.
    s = e.get("settings", {})
    c = s.get("color")
    attrs = {}
    classes = ["wp-block-separator", "has-alpha-channel-opacity"]
    if isinstance(c, str) and c:
        attrs["style"] = {"color": {"text": c}}
        classes.append("has-text-color")

    # core/separator's DEFAULT style is a short centred rule - core ships
    # `max-width: 100px` on it. Elementor's divider is full width unless told
    # otherwise, so a converted `+ ----- +` section rule rendered as a 100px
    # stub between two correctly placed glyphs. Width and thickness are real
    # settings on the widget and both have to be carried across; `max-width`
    # must be reset explicitly or core's 100px still wins.
    decls = []
    w = size(s.get("width"))
    if w:
        decls.append(f"width:{w};max-width:none")
    weight = size(s.get("weight"))
    if weight:
        # `border-top-style` is not optional here. A theme that resets
        # `border-style: none` on the rule makes the COMPUTED border-width 0
        # no matter how loudly the width is declared - measured: the line was
        # 1120px wide, correctly placed, and 0px thick.
        # `height:0` because a theme gives <hr> an intrinsic height of its own
        # (measured: 2px), which stacks on top of the border and makes the rule
        # box taller than Elementor's - 10px against 9px, on every divider.
        decls.append(f"border-top-width:{weight};border-top-style:solid;"
                     f"border-bottom-width:0;height:0")
    if isinstance(c, str) and c:
        # The block's own colour attribute reaches the <hr> as `color`, which
        # a theme's explicit `border-color` outranks - the rule came out in
        # the theme's #E1E8ED instead of the 10%-white it was given.
        decls.append(f"border-top-color:{c}")
    gap = size(s.get("gap"))
    if gap:
        # Elementor's `gap` is the breathing room on each side of the rule.
        decls.append(f"margin-top:{gap};margin-bottom:{gap}")
    if decls:
        classes.append(design_rule(";".join(decls)))

    return comment("core/separator", attrs, f'<hr class="{" ".join(classes)}"/>')


def conv_spacer(e, ctx) -> str:
    h = size((e.get("settings") or {}).get("space"), "50px")
    return comment("core/spacer", {"height": h},
                   f'<div style="height:{h}" aria-hidden="true" class="wp-block-spacer"></div>')


def conv_icon_list(e, ctx) -> str:
    s = e.get("settings", {})
    items = s.get("icon_list") or []

    # An icon-list carries its OWN typography and colour under an `icon_`
    # prefix, plus item spacing and a marker colour. Converting only the text
    # leaves every item inheriting the theme - measured on moksaweb.com: 25
    # list items came out 16px/26.4px in the theme's link blue instead of
    # 14.5px/1.65em in #A6A6B2, the single biggest visual difference on the
    # page. The list is styled as a whole; markers keep Elementor's accent.
    st = Style()
    fs = size(s.get("icon_typography_font_size"))
    lh = size(s.get("icon_typography_line_height"))
    if lh and lh.endswith("em"):
        lh = lh[:-2]
    color_txt = s.get("text_color")
    gap = size(s.get("space_between"))
    marker = s.get("icon_color")
    family = s.get("icon_typography_font_family")

    decls = []
    if fs:
        decls.append(f"font-size:{fs}")
    if lh:
        decls.append(f"line-height:{lh}")
    if isinstance(family, str) and family:
        decls.append(f"font-family:{normalize_value('font-family', family)}")
    if isinstance(color_txt, str) and color_txt:
        decls.append(f"color:{color_txt}")
    if decls:
        st.layout_css(";".join(decls))
    if gap:
        # Elementor spaces items with a gap between rows, not a bottom margin.
        st.layout_css(f"display:flex;flex-direction:column;gap:{gap};padding-left:1.2em;margin-block:0")
    else:
        st.layout_css("margin-block:0;padding-left:1.2em")
    if isinstance(marker, str) and marker:
        note("info", "icon-list", f"icons -> list markers in {marker}")

    _s, classes, _inline = st.resolve("core/list")

    # Elementor draws a Font Awesome glyph; a block list draws a ::marker. A
    # `disc` for every icon is a visible downgrade - the reference page uses
    # `fas fa-check` 21 times and rendered as bullet points. CSS takes a STRING
    # list-style-type, so the common glyphs come across as themselves.
    FA_GLYPH = {
        "check": "✓", "check-circle": "✔", "times": "✕",
        "times-circle": "✖", "plus": "+", "minus": "−",
        "arrow-right": "→", "arrow-left": "←",
        "angle-right": "›", "chevron-right": "›",
        "circle": "●", "dot-circle": "●", "square": "■",
        "star": "★", "caret-right": "▸", "long-arrow-alt-right": "⟶",
    }
    names = {((i.get("selected_icon") or {}).get("value") or "").split("fa-")[-1].strip()
             for i in items}
    glyph = FA_GLYPH.get(next(iter(names))) if len(names) == 1 else None

    marker_decls = []
    if isinstance(marker, str) and marker:
        marker_decls.append(f"color:{marker}")
    isz = size(s.get("icon_size"))
    if isz:
        marker_decls.append(f"font-size:{isz}")
    if classes:
        if glyph:
            DESIGN_RULES.append(f'.{classes[-1]} li{{list-style-type:"{glyph}"}}')
            note("info", "icon-list", f"{next(iter(names))} -> list-style-type \"{glyph}\"")
        elif len(names) > 1:
            note("warn", "icon-list", f"mixed icons {sorted(names)} - markers left as the default bullet")
        if marker_decls:
            DESIGN_RULES.append(f".{classes[-1]} li::marker{{{';'.join(marker_decls)}}}")
        indent = size(s.get("text_indent"))
        if indent:
            # Elementor's text_indent is the space between the glyph and the
            # text, which for a real list is the li's own start padding.
            DESIGN_RULES.append(f".{classes[-1]} li{{padding-inline-start:{indent}}}")

    lis = "".join(comment("core/list-item", {}, f"<li>{i.get('text','')}</li>") + "\n\n" for i in items)
    note("info", "icon-list", f"{len(items)} items -> core/list (icon glyphs become list markers)")
    cls = " ".join(["wp-block-list"] + classes)
    return comment("core/list", {}, f'<ul class="{cls}">{lis.rstrip()}</ul>')


def _title_text_group(title, desc, img=None, label="group"):
    inner = []
    if img:
        inner.append(comment("core/image", {},
                             f'<figure class="wp-block-image size-full"><img src="{html.escape(img)}" alt=""/></figure>'))
    if title:
        inner.append(comment("core/heading", {"level": 3}, f'<h3 class="wp-block-heading">{title}</h3>'))
    if desc:
        inner.append(comment("core/paragraph", {}, f"<p>{desc}</p>"))
    return comment("core/group", {"layout": {"type": "constrained"}},
                   f'<div class="wp-block-group">{chr(10).join(inner)}</div>')


def conv_icon_box(e, ctx) -> str:
    s = e.get("settings", {})
    note("info", "icon-box", "icon dropped - core has no icon-box; title+text kept")
    return _title_text_group(s.get("title_text", ""), s.get("description_text", ""))


def conv_image_box(e, ctx) -> str:
    s = e.get("settings", {})
    return _title_text_group(s.get("title_text", ""), s.get("description_text", ""),
                             (s.get("image") or {}).get("url", ""))


def conv_social(e, ctx) -> str:
    items = (e.get("settings") or {}).get("social_icon_list") or []
    links = []
    for it in items:
        url = ((it.get("link") or {}).get("url")) or ""
        icon = ((it.get("social_icon") or {}).get("value")) or ""
        svc = icon.split("-")[-1] if icon else ""
        if url and svc:
            links.append(comment("core/social-link", {"url": url, "service": svc}))
    return comment("core/social-links", {},
                   f'<ul class="wp-block-social-links">{(chr(10)+chr(10)).join(links)}</ul>')


def conv_shortcode(e, ctx) -> str:
    note("info", "shortcode", "kept as core/shortcode - renders the same way")
    return comment("core/shortcode", {}, (e.get("settings") or {}).get("shortcode", ""))


def conv_html(e, ctx) -> str:
    return comment("core/html", {}, (e.get("settings") or {}).get("html", ""))


def conv_video(e, ctx) -> str:
    s = e.get("settings", {})
    url = s.get("youtube_url") or s.get("vimeo_url") or (s.get("hosted_url") or {}).get("url", "")
    if not url:
        note("warn", "video", "no url - skipped")
        return ""
    provider = "youtube" if "youtu" in url else ("vimeo" if "vimeo" in url else "")
    attrs = {"url": url, "type": "video"}
    if provider:
        attrs["providerNameSlug"] = provider
    note("info", "video", f"-> core/embed ({provider or 'generic'})")
    return comment("core/embed", attrs,
                   f'<figure class="wp-block-embed"><div class="wp-block-embed__wrapper">\n{url}\n</div></figure>')


WIDGETS = {
    "heading": conv_heading, "text-editor": conv_text_editor, "button": conv_button,
    "image": conv_image, "divider": conv_divider, "spacer": conv_spacer,
    "icon-list": conv_icon_list, "icon-box": conv_icon_box, "image-box": conv_image_box,
    "social-icons": conv_social, "shortcode": conv_shortcode, "html": conv_html,
    "video": conv_video,
}


# ---- containers ------------------------------------------------------------

def convert_element(e, ctx) -> str:
    et = e.get("elType")
    s = e.get("settings", {})

    if et in ("container", "section", "column"):
        children = [c for c in (convert_element(x, ctx) for x in e.get("elements", [])) if c]
        st = Style()
        auto_style(st, "container", s, ctx["elmap"], ctx["cssmap"])
        apply_element_width(st, s)
        apply_custom_css(st, s, "container")
        if s.get("background_background") == "gradient":
            a = s.get("background_color") or "#000"
            b = s.get("background_color_b") or "#fff"
            ang = (s.get("background_gradient_angle") or {}).get("size", 180)
            st.set(("color", "gradient"), f"linear-gradient({ang}deg,{a} 0%,{b} 100%)")
        elif isinstance(s.get("background_color"), str) and s["background_color"]:
            st.set(("color", "background"), s["background_color"])
        if (s.get("background_image") or {}).get("url"):
            st.set(("background", "backgroundImage"),
                   {"url": s["background_image"]["url"], "source": "file"})
            st.set(("background", "backgroundSize"), s.get("background_size") or "cover")
            note("info", "container", "background image -> style.background (render-time)")
        # Vertical rhythm is the difference between "converted" and "looks
        # converted". Measured on moksaweb.com: the theme gives every group a
        # 24px bottom margin and a 24px row-gap when the block does not say
        # otherwise, and blockGap is RENDER-time CSS that the theme's own rules
        # outrank - the page came out 23% taller than the Elementor original
        # from stacked default spacing alone. So every container states its
        # gap AND its margin explicitly, in the design layer, where it wins.
        # Elementor's own DEFAULT container gap is 20px, not zero: a container
        # that declares no flex_gap still renders 20px apart. Emitting 0 for
        # silence (the first attempt here) collapses every undeclared section -
        # measured: the hero lost its 20px rhythm and the page came out 7%
        # SHORT. State the default explicitly, the same as any other value.
        ELEMENTOR_DEFAULT_GAP = "20px"
        gap_decl, gap = gap_css(s.get("flex_gap"))
        if not gap:
            gap_decl, gap = f"gap:{ELEMENTOR_DEFAULT_GAP}", ELEMENTOR_DEFAULT_GAP
        st.set(("spacing", "blockGap"), gap)              # keep it in the attrs
        # Every Elementor container is position:relative (measured on 13 of
        # them). A block group is static, so any absolutely-positioned
        # decoration inside one resolves against the page instead of its
        # section - it does not move until the page scrolls past it, which a
        # screenshot of the top of the page never shows.
        # `margin-block:0` cancels the theme's default 24px block margin, but it
        # must not cancel a margin the ORIGINAL sets: it carries !important, so
        # a container with margin_top 40px came out at 0. Only neutralise the
        # sides the source leaves silent.
        m = (st.style.get("spacing") or {}).get("margin") or {}
        neutral = ";".join(f"margin-{side}:0" for side in ("top", "bottom") if side not in m)
        st.layout_css(";".join(x for x in (gap_decl, neutral, "position:relative") if x))

        # Elementor's OWN stylesheet, read off the rendered original rather than
        # assumed:
        #     @media (max-width:767px) .e-con.e-flex {
        #         --width: 100%; --flex-wrap: var(--flex-wrap-mobile) }
        # Every flex container goes full width and starts wrapping at mobile,
        # whether or not the page sets anything. Without this a container with a
        # 58% desktop width stays 58% at 390px and its neighbours are squeezed
        # into whatever is left - seven containers on the reference page, and
        # the reason the hero heading rendered 192px wide in a 346px column.
        # ...and the exemption is narrow: only an explicit `width_mobile`
        # survives, because Elementor re-declares `--width` for that container
        # inside the SAME mobile block. A desktop width does not - measured on
        # both pages at 390px: a container 58% wide on desktop renders 331px
        # (full) in the original, while a 22% stat cell that also sets
        # width_mobile:46% keeps its 2x2 grid. Exempting desktop widths too
        # left the hero heading in a 192px column; exempting nothing stacked
        # the stat grid four rows deep. Only width_mobile.
        # Only the WIDTH is defaulted. `flex-wrap` is NOT forced at mobile:
        # measured on the original at 390px, the `+ ---- +` rule row computes
        # `nowrap` there, because the element's own `--flex-wrap` survives
        # Elementor's mobile rule. Forcing wrap put each divider on its own
        # line and added 215px to the page. A breakpoint's wrap comes from
        # `flex_wrap_mobile` alone, through the normal responsive path.
        mobile_default = []
        if not size(s.get("width_mobile")):
            mobile_default.append("width:100%;max-width:100%;flex-basis:100%")
        if not s.get("flex_wrap") and not s.get("flex_wrap_mobile"):
            # `--flex-wrap` is only DEFINED on a container that sets it, so
            # Elementor's mobile rule (`--flex-wrap: var(--flex-wrap-mobile)`,
            # which defaults to wrap) reaches exactly the containers that stay
            # silent. Measured at 390px on the original: seven silent
            # containers wrap, and the `+ ---- +` rule row - which declares
            # nowrap - does not.
            mobile_default.append("flex-wrap:wrap")
        if mobile_default:
            st.at_default("mobile", ";".join(mobile_default))

        # Width is layout INTENT, and the block `layout` attribute cannot carry
        # it on a classic theme: layout.type "constrained" resolves against
        # --wp--style--global--content-size, which a classic theme never
        # defines - the content then fills the viewport. Measured on
        # moksaweb.com (Blocksy): the converted page ran edge-to-edge and
        # clipped its own right column until this was handled.
        #   px  -> a centred max-width (the section's content well)
        #   %   -> a flex-basis (a column inside a row)
        w = s.get("width")
        wv = size(w)
        if wv:
            unit = (w or {}).get("unit", "px")
            if unit == "%":
                if wv != "100%":
                    st.layout_css(f"flex:0 0 {wv};max-width:{wv}")
            else:
                # NO auto margins. In flexbox an auto margin OUTRANKS the
                # parent's align-items, and when free space is negative it
                # resolves to 0 - so on a viewport narrower than the well, the
                # rule meant to centre it pinned it to the left instead and
                # defeated the centring the parent was already doing.
                #
                # Measured at a 1040px viewport on a 1160px well: with the auto
                # margins the box sat at left:22 and overflowed 142px to one
                # side; without them it sits at left:-68 and overflows 52px each
                # way, which is exactly what the Elementor original does. Every
                # container this converter emits is a flex container, so the
                # parent's alignment is always there to do the work.
                st.layout_css(f"max-width:{wv}")
        bw = size(s.get("boxed_width"))
        if bw:
            # Same reasoning as `width` above: no auto margins in a flex parent.
            st.layout_css(f"max-width:{bw}")

        # How this container behaves as a flex ITEM inside its parent - a
        # different axis from the layout controls above, which say how it
        # arranges its own children. The widget sweep only ever recorded the
        # latter, so NONE of these appear in the measured CSS map and every one
        # of them was dropped in silence.
        #
        # Measured cost of dropping `flex_grow` alone: the decorative rule that
        # opens each section is `+ [divider] +` in a nowrap row, where the
        # middle container grows to fill. Without it the container collapses to
        # zero, the divider inside it (width:100% of zero) disappears, and both
        # `+` glyphs bunch together at the left - four times on the page.
        # Emitted AFTER the width block above, because `flex:0 0 X` there is a
        # shorthand that resets flex-grow.
        for ctrl, prop in (("flex_grow", "flex-grow"), ("flex_shrink", "flex-shrink"),
                           ("flex_order", "order"), ("flex_align_self", "align-self")):
            v = scalar(s.get(ctrl))
            if v is not None:
                st.layout_css(f"{prop}:{v}")

        # EVERY Elementor container is a flex container. Treating a
        # `flex_direction: column` one as `layout:{type:"constrained"}` throws
        # away its alignment and its gap, because constrained is a *flow*
        # layout - children stack, but align-items and justify-content mean
        # nothing. Measured on moksaweb.com: whole sections collapsed sideways
        # and lost their vertical rhythm. Both directions are now emitted as
        # real flex, with alignment restated in the design layer where the
        # theme cannot outrank it.
        direction = s.get("flex_direction") or "column"
        is_row = direction in ("row", "row-reverse")
        layout = {"type": "flex", "orientation": "horizontal" if is_row else "vertical"}
        # The block flex layout WRAPS by default, in BOTH orientations; an
        # Elementor container does not. Silence means nowrap, and emitting
        # nothing lets a row - or a column - reflow that never reflowed in the
        # original. Setting it once here covers both branches; putting it only
        # in the row branch (the first attempt) left 17 columns wrapping.
        layout["flexWrap"] = "wrap" if s.get("flex_wrap") == "wrap" else "nowrap"
        if is_row:
            just = {"center": "center", "flex-start": "left", "flex-end": "right",
                    "space-between": "space-between"}.get(s.get("flex_justify_content", ""))
            if just:
                layout["justifyContent"] = just
            pass
        else:
            just = {"center": "center", "flex-start": "top", "flex-end": "bottom",
                    "space-between": "space-between"}.get(s.get("flex_justify_content", ""))
            if just:
                layout["justifyContent"] = just

        # align-items has no block-layout equivalent in either direction.
        align = s.get("flex_align_items")
        if align in ("center", "flex-start", "flex-end", "stretch"):
            st.layout_css(f"align-items:{align}")
        if direction == "row-reverse" or direction == "column-reverse":
            st.layout_css(f"flex-direction:{direction}")

        full = s.get("content_width") == "full" or (s.get("width") or {}).get("size") == 100


        style, classes, inline = st.resolve("core/group")
        attrs = {}
        if full:
            attrs["align"] = "full"
        if style:
            attrs["style"] = style
        attrs["layout"] = layout
        cls = ["wp-block-group"] + (["alignfull"] if full else []) + classes
        return comment("core/group", attrs, wrapper("div", cls, inline, "\n\n".join(children)))

    if et == "widget":
        wt = e.get("widgetType", "")
        fn = WIDGETS.get(wt)
        if fn:
            return fn(e, ctx)
        note("warn", wt, "no block equivalent - visible core/html placeholder with its settings")
        return comment("core/html", {},
                       f'<!-- Elementor widget "{wt}" had no block equivalent. Settings: '
                       f'{html.escape(json.dumps(s, ensure_ascii=False)[:400])} -->')

    note("warn", et or "?", "unknown elType - skipped")
    return ""


def load_elementor(path: Path, want: str | None = None):
    """Read whatever Elementor actually hands you, and say which it was.

    Returns (label, tree, extras). Four shapes, all confirmed against
    Elementor's own source rather than assumed:

      _elementor_data     a bare array - what the postmeta holds
      the same, encoded   postmeta stores it as a JSON *string*, so a dump of
                          the meta value is a JSON document containing a string
      template export     `elementor-<id>-<date>.json` from Export Template:
                          {"content": [...], "page_settings": {...},
                           "version", "title", "type"} and, on newer versions,
                          "global_classes" / "global_variables"
                          (local.php::prepare_template_export)
      kit .zip            Export Kit: templates at content/<post_type>/<ID>.json,
                          each one a template export, beside manifest.json and
                          site-settings.json
                          (import-export/runners/export/elementor-content.php)
    """
    def unwrap(doc, label):
        if isinstance(doc, str):                       # postmeta is a string
            doc = json.loads(doc)
        if isinstance(doc, list):
            return label, doc, {}
        if isinstance(doc, dict) and isinstance(doc.get("content"), list):
            extras = {k: doc[k] for k in
                      ("page_settings", "global_classes", "global_variables", "type", "version")
                      if doc.get(k)}
            return doc.get("title") or label, doc["content"], extras
        raise ValueError(f"{label}: not Elementor data - expected an element array, "
                         f"or an export with a 'content' array")

    if path.suffix.lower() == ".zip":
        import zipfile
        with zipfile.ZipFile(path) as z:
            members = sorted(n for n in z.namelist()
                             if n.startswith("content/") and n.endswith(".json"))
            if not members:
                raise ValueError(f"{path}: no content/*/*.json inside - not an Elementor kit")
            if want:
                members = [m for m in members if want in m] or members[:0]
                if not members:
                    raise ValueError(f"no template matching {want!r} in the kit")
            elif len(members) > 1:
                note("warn", "-", f"kit holds {len(members)} templates; converting the first. "
                                  f"Use --template to pick: "
                                  f"{', '.join(Path(m).stem for m in members[:6])}")
            m = members[0]
            return unwrap(json.loads(z.read(m).decode("utf-8")), Path(m).stem)

    return unwrap(json.loads(path.read_text(encoding="utf-8")), path.stem)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="_elementor_data JSON, an Elementor template export, "
                                 "or an exported kit .zip")
    ap.add_argument("--template", help="which template to take out of a kit .zip")
    ap.add_argument("--el-skill", type=Path,
                    default=Path(os.path.expanduser("~/.claude/skills/elementor-headless")),
                    help="path to the elementor-headless skill (its measured CSS map drives the mapping)")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    elmap = load_el_css_map(a.el_skill if a.el_skill and a.el_skill.exists() else None)
    if not elmap:
        note("warn", "-", "elementor-headless not found - style mapping limited to the built-in cases")
    ctx = {"elmap": elmap, "cssmap": css_to_style_path()}

    label, tree, extras = load_elementor(Path(a.file), a.template)
    if extras.get("type"):
        note("info", "-", f"{label}: Elementor template export, type={extras['type']}"
                          + (f" (v{extras['version']})" if extras.get("version") else ""))

    # An export carries more than the element tree, and dropping it silently is
    # how a converted page loses its page background or its global classes.
    ps = extras.get("page_settings") or {}
    if ps:
        interesting = {k: v for k, v in ps.items()
                       if v not in (None, "", [], {}) and not k.startswith("_")}
        if interesting:
            note("warn", "page_settings",
                 f"the export sets {len(interesting)} PAGE-level settings that belong to the "
                 f"document, not to any element, so no block carries them: "
                 f"{', '.join(sorted(interesting)[:8])}"
                 + (" ..." if len(interesting) > 8 else "")
                 + " - re-apply them on the destination page or wrap the result in a group")
    for key, what in (("global_classes", "global CSS classes"),
                      ("global_variables", "global variables")):
        if extras.get(key):
            n = len(extras[key]) if hasattr(extras[key], "__len__") else "?"
            note("warn", key,
                 f"the export carries {n} {what}. Elements referencing them resolve through "
                 f"Elementor's own stylesheet, which a block page does not load - the values "
                 f"they resolve to are not in this file")

    body = "\n\n".join(x for x in (convert_element(e, ctx) for e in tree) if x)
    # The design layer goes FIRST and carries the layout rules an optimiser
    # must not be able to strip (see DESIGN_RULES).
    if DESIGN_RULES or MEDIA_RULES:
        css = list(DESIGN_RULES)
        # Media queries come after every base rule and in breakpoint order,
        # widest query first: they carry the same specificity and the same
        # !important, so the narrowest matching query must be the last one able
        # to win.
        n_media = 0
        for bp, query in BREAKPOINTS.items():
            rules = MEDIA_RULES.get(bp)
            if rules:
                css.append(f"@media {query}{{{''.join(rules)}}}")
                n_media += len(rules)
        layer = ("<!-- wp:html -->\n<style>\n" + "\n".join(css) +
                 "\n</style>\n<!-- /wp:html -->")
        body = layer + "\n\n" + body
        note("info", "-", f"{len(DESIGN_RULES)} layout rules in a design-layer <style> "
                          f"(survives remove-unused-CSS plugins; per-block style.css does not)")
        if n_media:
            note("info", "-", f"{n_media} responsive rules across "
                              f"{len([b for b in MEDIA_RULES if MEDIA_RULES[b]])} breakpoints "
                              f"(Elementor _tablet/_mobile variants)")
    markup = body + "\n"

    if a.report:
        agg = {}
        for row in REPORT:
            agg[row] = agg.get(row, 0) + 1
        print(f"blocks emitted    : {markup.count('<!-- wp:')}", file=sys.stderr)
        print(f"elementor CSS map : {len(elmap):,} (control, css) pairs from elementor-headless",
              file=sys.stderr)
        print(f"block style paths : {len(ctx['cssmap'])} CSS properties the block engine can express",
              file=sys.stderr)
        for (lvl, w, msg), n in sorted(agg.items(), key=lambda x: (-x[1], x[0])):
            print(f"  {lvl:5} {w:16} x{n:<4} {msg}", file=sys.stderr)
        print("\nNEXT: validate-post.py, then the editor byte-check.", file=sys.stderr)
        return

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(newline="\n")   # LF - byte-identity depends on it
    sys.stdout.write(markup)
    warns = sum(1 for lvl, _, _ in REPORT if lvl == "warn")
    print(f"\n<!-- from Elementor via elementor-headless CSS map: "
          f"{markup.count('<!-- wp:')} blocks, {warns} fallbacks. --report for detail. -->",
          file=sys.stderr)


if __name__ == "__main__":
    main()
