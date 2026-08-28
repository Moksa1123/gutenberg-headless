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

### Visual fidelity is a separate question from validity

The first pass scored 179 blocks / 0 invalid and **still did not look like the
original**. `isValid` says the editor accepts the markup; it says nothing about
whether the page renders like the page it came from. Comparing the two full-page
screenshots side by side is not optional, and it exposed three layout failures a
validator structurally cannot see:

| symptom | root cause | fix |
|---|---|---|
| content ran edge-to-edge, right column clipped | Elementor's `width: 1160px` was skipped as "layout-handled", but `layout.type:constrained` resolves against `--wp--style--global--content-size`, which a **classic theme never defines** | width/`boxed_width` now emit real `max-width` (px) or `flex-basis` (%) |
| those max-widths never reached the browser | per-block `style.css` compiles to a **hash class injected at render**; Perfmatters' remove-unused-CSS scans the raw HTML, never sees it, strips the rule | layout rules go into one design-layer `<style>` under a stable class the markup itself carries |
| content still hugged the left edge | Blocksy sets `margin-left:-22px` on children of a constrained layout to cancel container padding, which beats a plain `margin:auto` | design-layer selectors are doubled (`.x.x`) and marked `!important` |
| every ghost button rendered solid white | the CSS map reports the same property for `button_background_hover_color` as for the normal one, so an undiscriminating pass wrote the HOVER colour as the resting colour | `auto_style` skips any `*_hover_*` control; states are set explicitly per converter |

Also measured: `rgba(0,0,0,0)` is a **deliberate** transparent (ghost buttons
depend on it), not an absence — treating it as empty makes the block inherit a
solid colour it never had.

### Vertical rhythm: the theme fills every silence

After the layout fixes the page still ran **+23% taller** than the original, and
that gap is entirely spacing the converted markup never asked for. Measured on
the delivered page:

- the theme gives **every** `.wp-block-group` a `margin-bottom: 24px` when the
  block does not say otherwise — 10 of them on this page
- and a `row-gap: 24px` to any group whose block does not set `blockGap`
- `blockGap` is **render-time** CSS (`wp-container-*`), so a theme rule at equal
  or higher specificity simply outranks it

Elementor never has this problem: its own reset zeroes widget margins, so an
Elementor tree records only the spacing the designer *added*. Converted markup
inherits a theme's opinions in every gap the tree left silent.

The fix is to state the silence: every container now emits
`gap:<its own value or 0>; margin-block:0` into the design layer, where the
doubled `!important` selector wins. Stray section margins went to **zero** and
the height difference fell from +23% to **+12%** — the remainder is
per-element text rhythm (`p` 18px, `h2` 14px top margins the theme applies to
typography), which is a theme-styling decision rather than a conversion error.

### Two more, found only by measuring every text node

Eyeballing screenshots is necessary and still not sufficient. Fingerprinting
**every** rendered text node on both pages (font-size, line-height, weight,
colour, y-position) turned up two systematic faults that a screenshot glance
reads as "close enough":

- **The whole type scale was shrunk.** theme.json's `typography.fluid` rewrites
  a plain inline `font-size:56px` into `clamp(31.6px, …, 56px)`, which resolves
  to **44.6px** at a 1440px viewport. Every heading and every paragraph was a
  step small: 56→44.6, 16.5→15.3, 34→34.06 with fractional values that give it
  away. Elementor emits fixed sizes, so a faithful conversion must opt out —
  each font-size is now restated in the design layer, where the doubled
  `!important` selector pins it. After the fix all four checkpoints match
  exactly: 56/70, 40/48, 20/28, 16.5/32.175.
- **195px of dead space above the hero.** The theme's page wrapper
  (`.ct-container-full`) applies `padding-top:120px` to ordinary pages; the
  Elementor original avoided it by using the `elementor_header_footer` page
  template. Converting the tree does not convert the template — set
  `_wp_page_template` to whatever the original used, or the converted page
  starts with a band of nothing.

### The full element-by-element diff

Checkpoints are still cherry-picking. The honest method is to fingerprint
**every** text-bearing element on both pages — 25 computed properties each —
pair them by their own text, and diff every property. On this page that is 123
elements on each side, **paired 123, none missing, none extra**.

The first full run reported differences on 8 properties. Two were real and
large, and neither would have been noticed by looking:

- **icon-list carried none of its styling.** Elementor keeps a list's
  typography under an `icon_` prefix (`icon_typography_font_size`,
  `icon_typography_line_height`) plus `text_color`, `icon_color` and
  `space_between` — the converter only took the text. 25 list items rendered at
  the theme's 16px/26.4px in its link colour instead of 14.5px/1.65em in
  `#A6A6B2`: the single biggest visual difference on the page, and invisible in
  a thumbnail. Fixing it removed the `fontSize`, `color`, `lineHeight` and
  `borderTopColor` differences in one go.
- **`_element_custom_width` was ignored.** Elementor's Advanced tab lets *any*
  widget set its own width; it is not a container setting, so the container
  pass never saw it. A 600px lead paragraph ran the full column width.

Everything else the diff reported was an equivalence, and saying so precisely
matters as much as fixing the rest: `start`/`left` and `end`/`right` are the
same value; `minHeight:0px`/`auto` likewise; and 70 of the 123 pairs compare an
Elementor `<span>` against a block `<a>`/`<p>` because the two systems nest text
differently — those must be compared as boxes, not as text nodes, and when you
do, the buttons match exactly (15/34 padding, 8px radius, transparent ghost fill,
2.4px border, the orange CTA).

After the fixes: of 53 same-tag comparable pairs, **12 differences remain, all
of them width**, and all downstream of percentage columns resolving against a
slightly different parent width — the ratios are consistent (76% of 1160 = 882).

Method note: `getComputedStyle` over every element of both pages, paired and
diffed as data, is what found these. "Looks about right" would not have, and
neither would a checklist of properties someone thought to check.

After all of it the converted page matches the original's structure, widths,
type scale, colours, CTA styling and section rhythm.

Three earlier bugs, also fixed at the root:

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
