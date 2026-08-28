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
_SEQ = [0]


def design_rule(css_body: str) -> str:
    """Register a layout rule; returns the stable class to put on the element.

    The selector is doubled (`.x.x`) and every declaration marked important:
    themes routinely apply negative margins to the children of a constrained
    layout to cancel container padding (measured: Blocksy sets
    `margin-left:-22px` on them), which silently defeats a plain
    `margin-left:auto`. Layout the converted page depends on has to win."""
    _SEQ[0] += 1
    cls = f"el2b-{_SEQ[0]}"
    body = ";".join(f"{d.strip()} !important" for d in css_body.split(";") if d.strip())
    DESIGN_RULES.append(f".{cls}.{cls}{{{body}}}")
    return cls


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

    def layout_css(self, css_body):
        """Layout an optimiser must not be able to strip - goes to the design
        layer under a stable class, not to per-block style.css."""
        if css_body:
            self.extra_classes.append(design_rule(css_body))

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

    # Within spacing, the editor emits margin before padding - and within a box,
    # top/right/bottom/left. Both are insertion-order dependent in the output.
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
        return self.style, classes + self.extra_classes, ";".join(inline)


def auto_style(st: Style, widget: str, settings: dict, elmap, cssmap, *, prefix_filter=None):
    """Map every Elementor setting whose measured CSS the block engine can
    express. Anything with a known CSS property but no block path goes to
    style.css rather than being dropped."""
    for ctrl, val in settings.items():
        if prefix_filter and not ctrl.startswith(prefix_filter):
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
        v = scalar(val)
        if v is None:
            continue
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


def wrapper(tag, classes, inline, inner, *, extra=""):
    cls = " ".join(dict.fromkeys(c for c in classes if c))
    bits = [tag] + ([extra] if extra else []) + \
           ([f'class="{cls}"'] if cls else []) + ([f'style="{inline}"'] if inline else [])
    return f"<{' '.join(bits)}>{inner}</{tag}>"


def comment(name, attrs, inner=None):
    short = name[5:] if name.startswith("core/") else name
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
        style, classes, inline = st.resolve()
        attrs = {"style": style} if style else {}
        return comment("core/paragraph", attrs,
                       wrapper("p", classes, inline, s.get("title", "")))

    level = int(raw[1])
    st = Style()
    if ALIGN.get(s.get("align", "")):
        st.set(("typography", "textAlign"), ALIGN[s["align"]])
    auto_style(st, "heading", s, ctx["elmap"], ctx["cssmap"])
    style, classes, inline = st.resolve()
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
    style, classes, inline = st.resolve()
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
    auto_style(st, "button", s, ctx["elmap"], ctx["cssmap"])
    hover_bg, hover_fg = s.get("button_background_hover_color"), s.get("button_hover_text_color")
    if hover_bg or hover_fg:
        hv = {}
        if hover_bg:
            hv["background"] = hover_bg
        if hover_fg:
            hv["text"] = hover_fg
        st.style[":hover"] = {"color": hv}   # button IS in the pseudo allowlist
    style, classes, inline = st.resolve("core/button")
    attrs = {"style": style} if style else {}
    # Measured, and the OPPOSITE of core/heading: core/button's own save()
    # generates has-custom-font-size for a custom size (heading needs it as an
    # explicit className instead). Block-specific, so it lives at the call site.
    if (style.get("typography") or {}).get("fontSize"):
        classes = classes + ["has-custom-font-size"]
    link_cls = ["wp-block-button__link"] + [c for c in classes if c != "has-custom-css"] + ["wp-element-button"]
    a = wrapper("a", link_cls, inline, s.get("text", ""),
                extra=f'href="{html.escape(href)}"' if href else "")
    button = comment("core/button", attrs,
                     wrapper("div", ["wp-block-button"] + [c for c in classes if c == "has-custom-css"], "", a))
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
    style, classes, inline = st.resolve()
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
    c = e.get("settings", {}).get("color")
    attrs = {}
    classes = ["wp-block-separator", "has-alpha-channel-opacity"]
    if isinstance(c, str) and c:
        attrs["style"] = {"color": {"text": c}}
        classes.append("has-text-color")
    return comment("core/separator", attrs, f'<hr class="{" ".join(classes)}"/>')


def conv_spacer(e, ctx) -> str:
    h = size((e.get("settings") or {}).get("space"), "50px")
    return comment("core/spacer", {"height": h},
                   f'<div style="height:{h}" aria-hidden="true" class="wp-block-spacer"></div>')


def conv_icon_list(e, ctx) -> str:
    items = (e.get("settings") or {}).get("icon_list") or []
    lis = "".join(comment("core/list-item", {}, f"<li>{i.get('text','')}</li>") + "\n\n" for i in items)
    note("info", "icon-list", f"{len(items)} items -> core/list (icons dropped)")
    return comment("core/list", {}, f'<ul class="wp-block-list">{lis.rstrip()}</ul>')


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
        gap = size(s.get("flex_gap"))
        if gap:
            st.set(("spacing", "blockGap"), gap)          # keep it in the attrs
        st.layout_css(f"gap:{gap or '0px'};margin-block:0")

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
                st.layout_css(f"max-width:{wv};margin-left:auto;margin-right:auto")
        bw = size(s.get("boxed_width"))
        if bw:
            st.layout_css(f"max-width:{bw};margin-left:auto;margin-right:auto")

        is_row = s.get("flex_direction") in ("row", "row-reverse")
        layout = {"type": "flex"} if is_row else {"type": "constrained"}
        if is_row:
            just = {"center": "center", "flex-start": "left", "flex-end": "right",
                    "space-between": "space-between"}.get(s.get("flex_justify_content", ""))
            if just:
                layout["justifyContent"] = just
            if s.get("flex_wrap") == "wrap":
                layout["flexWrap"] = "wrap"
        full = s.get("content_width") == "full" or (s.get("width") or {}).get("size") == 100

        style, classes, inline = st.resolve()
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("file", help="_elementor_data JSON")
    ap.add_argument("--el-skill", type=Path,
                    default=Path(os.path.expanduser("~/.claude/skills/elementor-headless")),
                    help="path to the elementor-headless skill (its measured CSS map drives the mapping)")
    ap.add_argument("--report", action="store_true")
    a = ap.parse_args()

    elmap = load_el_css_map(a.el_skill if a.el_skill and a.el_skill.exists() else None)
    if not elmap:
        note("warn", "-", "elementor-headless not found - style mapping limited to the built-in cases")
    ctx = {"elmap": elmap, "cssmap": css_to_style_path()}

    tree = json.loads(Path(a.file).read_text(encoding="utf-8"))
    body = "\n\n".join(x for x in (convert_element(e, ctx) for e in tree) if x)
    # The design layer goes FIRST and carries the layout rules an optimiser
    # must not be able to strip (see DESIGN_RULES).
    if DESIGN_RULES:
        layer = ("<!-- wp:html -->\n<style>\n" + "\n".join(DESIGN_RULES) +
                 "\n</style>\n<!-- /wp:html -->")
        body = layer + "\n\n" + body
        note("info", "-", f"{len(DESIGN_RULES)} layout rules in a design-layer <style> "
                          f"(survives remove-unused-CSS plugins; per-block style.css does not)")
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
