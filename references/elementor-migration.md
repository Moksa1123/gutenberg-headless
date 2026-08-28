# Elementor → blocks

`tools/el2blocks.py` converts an Elementor tree (`_elementor_data`) into
serialized block markup. It is a structural translator with an honest report,
not a magic wand — and it is **driven by two measured datasets, not by a
hand-written widget table**.

```bash
wp post meta get 123 _elementor_data > page.json
python tools/el2blocks.py page.json --report            # decide before converting
python tools/el2blocks.py page.json > page.html
python tools/validate-post.py page.html                 # always
wp eval-file tools/apply-post.php new page.html "Title" page draft
# then the editor check (canonicalization.md): isValid on every block
```

## Where the mapping comes from

The sibling skill [elementor-headless](https://github.com/Moksa1123/elementor-headless)
already measured, on live sites, which CSS property each of Elementor's
(control, selector) pairs actually emits — `data/css-selectors.csv`, 25,357
usable rows. This converter reads that table and matches it against **this**
skill's `data/style-surface.json` (the block style engine's own property→CSS
map, 42 expressible properties). Every style decision is therefore derived
from two measured datasets. Nobody wrote down that `typography_font_size`
means `font-size`; the sweep did.

Point it at your copy with `--el-skill /path/to/elementor-headless` (it
defaults to `~/.claude/skills/elementor-headless`). Without it the converter
still runs, structure and content intact, and says the mapping is limited.

**Elementor 4.x drives containers through CSS custom properties** (`--gap`,
`--min-height`, `--justify-content`), so the measured map reports variable
names; the converter folds each back onto its real property before lookup.

## What converts, and how

| Elementor | block | notes |
|---|---|---|
| container / section / column | `core/group` | flex direction → `layout.type` (flex/constrained), justify → `layout.justifyContent`, `flex_gap` → `spacing.blockGap`, full width → `align:full` |
| heading | `core/heading` or `core/paragraph` | real h1-h6 stay headings; `div`/`span`/`p` are styled TEXT and become paragraphs (reported) |
| text-editor | `core/paragraph` or `core/html` | one `<p>` becomes a paragraph; richer HTML is kept verbatim |
| button | `core/buttons` > `core/button` | link, label, colors, radius, padding; **hover colors become native `style[":hover"]`** (button is in the pseudo-state allowlist) |
| image / image-box | `core/image` / group | |
| icon-list | `core/list` | icons dropped, reported |
| icon-box | group (heading + paragraph) | core has no icon-box |
| social-icons | `core/social-links` | service parsed from the icon value |
| divider / spacer / shortcode / html / video | separator / spacer / shortcode / html / embed | |
| anything else | `core/html` placeholder **carrying its original settings** | visible, greppable, never silently dropped |

Style that has no block-native property is escalated to per-block `style.css`
rather than lost. Effects blocks genuinely cannot do (background overlays,
Elementor's hover transitions) are **dropped and reported as warnings** — not
smuggled into `style.css` where they would not work anyway.

## Measured result on a real page

The test site's Elementor home page (63 KB of `_elementor_data`, 12 widget
types, 36 containers):

```
158 blocks emitted
  0 validate-post.py errors
  0 invalid blocks in the editor          <- the bar that matters
 25 report lines, every one actionable:
      10x container background image -> style.background (render-time)
       7x background overlay          -> dropped, no block equivalent
       4x icon-box                    -> icon dropped, title+text kept
       2x widgets (counter, icon)     -> visible placeholder with settings
```

Byte-identity with the editor's resave converges but is not guaranteed on a
converted page — the editor normalizes key order per block type
(canonicalization.md) and Elementor content brings its own entity encoding.
**`isValid` on every block is the shipping bar**; byte-identity is the polish
pass, reached by the same console loop as any hand-written page.

## Second real page: moksaweb.com, a different site entirely

The same converter, run against the author's main site (moksaweb.com — 176
registered blocks, no WooCommerce, Jetpack instead; **a completely different
block surface from the first test site's 302**) on a real published case
study, 84 KB of tree, 75 containers:

```
179 blocks emitted
  0 validator errors        (against moksaweb's OWN re-extracted schema)
  0 invalid blocks in the editor
1096 verify-live assertions passed on the delivered public page
```

Live result: <https://moksaweb.com/camping-case-blocks/> (converted) beside the
Elementor original. The exercise also proves the skill's own first rule — the
block surface is a property of the SITE: validating the converted page against
the *other* site's schema would have been meaningless, so moksaweb's schema was
re-extracted first (`extract-block-schema.php` + `sweep-render.php`, two
commands).

Three real bugs it surfaced, each now fixed at the root:

- **`header_size: div`** — Elementor's heading widget is routinely used as
  styled TEXT. 45 of the 55 headings on that page were `div`; emitting `h2` for
  all of them would have invented a document outline the original never had.
  They now convert to styled paragraphs, and only real `h1`-`h6` stay headings.
- **`core/separator`** carries its color in the style ATTRIBUTE only, never
  inline, and always ships `has-alpha-channel-opacity`. gblib now knows
  (`NO_INLINE_COLOR_BLOCKS`), so the validator agrees with the editor.
- **CSS custom properties leaking**: Elementor writes `--overflow: hidden`;
  its stylesheet consumes that, ours does not. Escalations to `style.css` now
  strip the `--` and emit the real property.

## Canonicalization rules this work surfaced

- A custom `style.typography.fontSize` marks the element `has-custom-font-size`
  — but **`core/button` generates it in save(), while `core/heading` needs it
  as an explicit `className`**. Block-specific, measured both ways.
- The inline CSS follows the style object's key order, and **that order is
  block-specific**: heading emits spacing before typography, button emits
  color first. Within `spacing`, margin precedes padding; within a box,
  top→right→bottom→left.
- `core/buttons` must contain a real nested `core/button` block. Assembling
  the wrapper HTML by string surgery produces markup that validates on the
  server and is invalid in the editor.

## What you should still do by hand

- **Layout intent**: Elementor's absolute positioning, sticky effects and
  z-index tricks have no block equivalent. Rebuild them with the design layer
  (custom-css-js.md).
- **Motion**: entrance animations are Elementor-only; the behaviour layer
  covers them in ~15 lines.
- **Forms, popups, loop templates**: these are Elementor Pro subsystems, not
  content. Convert the page, then replace them with a block form plugin or
  core query blocks.
- **Global colors**: Elementor kit colors become literal hex values here. Map
  them onto your theme.json palette slugs afterwards (`gb.py presets color`)
  so a palette change keeps working.
