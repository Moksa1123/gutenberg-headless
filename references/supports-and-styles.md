# Supports, presets, and the two serialization moments

A block's *supports* (color, typography, spacing, border...) inject shared
attributes - `backgroundColor`, `fontSize`, `style`, `className`, `align` -
and each of those serializes into the saved HTML **at save time, in the
client**. Headless, there is no client, so you write both halves yourself, and
`validate-post.py` refuses a tree in which they disagree.

## Save-time: classes you must write into the HTML

| comment attr | classes the saved HTML must carry |
|---|---|
| `"backgroundColor":"x"` | `has-x-background-color has-background` |
| `"textColor":"x"` | `has-x-color has-text-color` |
| `"gradient":"x"` | `has-x-gradient-background has-background` |
| `"fontSize":"x"` | `has-x-font-size` |
| `"fontFamily":"x"` | `has-x-font-family` |
| `"borderColor":"x"` | `has-border-color has-x-border-color` |
| `"align":"wide"/"full"` | `alignwide` / `alignfull` |
| `"style":{"typography":{"textAlign":"center"}}` | `has-text-align-center` - a CLASS, not inline CSS (measured against the editor's own resave) |
| `"className":"a b"` | `a b` appended verbatim |
| `"anchor":"x"` | `id="x"` |
| block style variation | `is-style-{name}` (`gb.py styles`) |
| `"dropCap":true` | `has-drop-cap` |

The slug in a preset attr must exist on the target site (`gb.py presets color`)
or the class lands in the HTML and **no stylesheet anywhere defines it** -
the page looks unstyled with zero errors. `E-PRESET`.

Some blocks put these classes on an inner element, not the wrapper:
`core/button` colors go on the `<a class="wp-block-button__link ...">`.
The validator checks the block's whole own HTML for this reason.

## Save-time: the style object → inline CSS

Custom (non-preset) values live in `"style":{...}` in the comment **and** as an
inline `style=""` in the HTML:

```
{"style":{"color":{"text":"#c0392b"},"typography":{"letterSpacing":"2px"}}}
  → <p class="has-text-color" style="color:#c0392b;letter-spacing:2px">
```

Preset references inside the style object use the `var:` shorthand and expand
to a CSS custom property in the HTML:

```
comment: "style":{"spacing":{"padding":{"top":"var:preset|spacing|60"}}}
HTML:    style="padding-top:var(--wp--preset--spacing--60)"
```

`gb.py var "var:preset|spacing|60"` prints the expansion and whether the slug
exists on the site. The style-key → CSS mapping is **data-driven**: extracted
from the live site's own `WP_Style_Engine::BLOCK_STYLE_DEFINITIONS_METADATA`
into `data/style-surface.json` (37 properties), consumed by
`gblib.style_expectations()`. Box values (`padding`, `margin`) take one string
or a per-side object; `border.radius` takes a string or per-corner object;
`border.top/right/bottom/left` take `{color,width,style}` objects; `shadow`
is a bare string under `style`. Two properties the PHP engine lacks but the
JS engine serializes inline (measured): `typography.textShadow` and the
`outline.*` group - `gblib.ENGINE_SUPPLEMENT`.

**The save-time / render-time split, measured property by property:**

| save-time (you write the inline CSS/class) | render-time (server/view script - write the attr ONLY) |
|---|---|
| color.text/background/gradient, all typography.* except textAlign(class), border.* incl. per-side/per-corner, shadow, dimensions.*, outline.*, spacing.padding/margin | background.* (bg image/size/position...), position (sticky/fixed → wp-container-* + is-position-*), spacing.blockGap (container CSS), elements.* (wp-elements-* + CSS, `:hover` etc. allowed on ANY block here), filter.duotone, css (has-custom-css is save-time, the hash class + stylesheet render-time), all `:state`/`@viewport` keys (wp-states-*), lightbox (Interactivity API expansion), fitText (directives) |

**Fluid typography rewrites your inline font-size.** With theme.json
`typography.fluid: true` (ON on this site), render replaces a custom inline
`font-size: 3rem` with `font-size: clamp(min, formula, 3rem)` - the authored
value survives as the clamp maximum. verify-live accepts that form; do not be
surprised when the delivered bytes differ from the saved bytes here.

## Render-time: classes the SERVER injects - do not write these

Three supports are applied by `render_block` filters when the page is served,
for static and dynamic blocks alike. They appear in the delivered page but
must **not** appear in the stored markup (the editor would flag it):

| comment attr | injected at render |
|---|---|
| `"layout":{"type":"constrained"/"flex"/"grid"}` | `wp-container-*` + `is-layout-*` classes + a generated stylesheet |
| `"style":{"elements":{...}}` (link/heading/button colors) | `wp-elements-*` class + generated CSS |
| duotone filter | `wp-duotone-*` class + an inline SVG |

This is the mirror image of the save-time rules: write `has-*` classes
yourself, never write `wp-container-*` yourself.

## Wrapper class

Every block's first element normally carries `wp-block-{name}` (`/` → `-`):
`wp-block-group`, `wp-block-media-text`, `wp-block-button` with the link inside
as `wp-block-button__link`. Exceptions that carry none: `paragraph`,
`list-item`, `html`, `more`, `nextpage`, `freeform`, `shortcode`. Theme CSS
targets these classes; missing one degrades styling silently (`W-WRAPPER`).

## theme.json presets on this site

Extraction merges every origin (`default` < `theme` < `custom`) exactly as WP
does. On booking.moksaweb.com (Blocksy 2.1.53, classic theme):

- colors: 12 default + 8 theme (`palette-color-1`...`palette-color-8`, which
  resolve to `var(--theme-palette-color-N, #hex)` - Blocksy chains its own vars)
- font sizes: `small medium large x-large xx-large`
- spacing: `20 30 40 50 60 70 80` (0.44rem-5.06rem)
- gradients: 56, shadows: 5, duotones: 8

Preset definitions are delivered as `--wp--preset--*` custom properties in the
`global-styles-inline-css` style tag; `verify-live.py` asserts every var your
tree references is defined in the CSS the visitor actually receives.

Layout sizes are theme vars, not lengths: `contentSize:
var(--theme-block-max-width)`, `wideSize: var(--theme-block-wide-max-width)`.
`alignwide`/`alignfull` only do something inside a `constrained` layout parent.
