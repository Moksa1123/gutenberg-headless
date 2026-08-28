# What WP 7.0 / 7.1 added to the block surface

Measured, not recalled: core `block.json` sets for 6.9 / 7.0 / 7.1 were diffed
file-by-file (6.9=106, 7.0=109, 7.1=115 blocks), every new behaviour was pushed
through `do_blocks()` on the live site, and the canonical serialization of each
new feature was taken from the editor's own `wp.blocks.serialize()`. The proof
page is `examples/wp71-features.html` - 19 blocks, editor 19/19 `isValid`,
resave byte-identical, live PASS.

## New blocks

| version | blocks |
|---|---|
| ≤6.9 | accordion family (4), math, icon-era experiments, term-count/term-name/term-template/terms-query |
| 7.0 | `core/breadcrumbs`, `core/icon`, `core/navigation-overlay-close` |
| 7.1 | `core/tabs`, `core/tab-list`, `core/tab-panels`, `core/tab-panel`, `core/playlist`, `core/playlist-track` |

Tabs and accordion are **dynamic-with-skeleton**: you write the full inner
markup (the callback only augments it with ids/aria/Interactivity directives),
so the validator does not warn about inner HTML on them. Canonical shapes are
in `examples/wp71-features.html`; the notable sourced attr is `core/tab-list`'s
`tabs` (source:query from the `<button role="tab">` elements - never put it in
the comment). `core/math` holds `latex` in the comment and sourced `mathML` in
the HTML; canonical MathML is the editor's LaTeX engine output
(`<semantics><mrow>...<annotation encoding="application/x-tex">`), and a
hand-written simpler `<math>` stays valid but gets rewritten on resave.
`core/playlist` has a rich adjustable surface: `waveformStyle`
(bars/mirror/line/blocks/dots/seekbar), `waveformColor`, show* toggles.

## The headline: per-block STATES (7.1)

`wp-includes/block-supports/states.php` (@since 7.1.0). The `style` attribute
now accepts **pseudo-state and viewport keys**, compiled at render time into a
scoped stylesheet + a generated `wp-states-{hash}` class on the block:

```
"style":{
  ":hover":  {"color":{"background":"var:preset|color|palette-color-3"}},
  "@mobile": {"typography":{"fontSize":"18px"},
              ":hover":{...}, "elements":{"link":{...}}}
}
```

Measured render output:

```
.wp-states-84c5c619{font-size:18px !important;}            (inside @media)
.wp-states-ecdf5de5 .wp-block-button__link:hover{
    background-color:var(--wp--preset--color--palette-color-3) !important;...}
```

Rules (all measured):
- **Viewport keys work on any block**: `@mobile` = `(width <= 689.98px)`,
  `@tablet` = `(689.98px < width <= 999.98px)`, `@desktop` = `(width > 999.98px)`.
  Breakpoints come from theme.json's new `settings.viewport` section.
- **Block-level pseudo-states are allowlisted**:
  `WP_Theme_JSON::VALID_BLOCK_PSEUDO_SELECTORS` = only `core/button` and
  `core/navigation-link` (`:hover :focus :focus-visible :active`). A `:hover`
  on a paragraph is silently ignored (measured: no class, no CSS).
- `style.elements.link/button` accept the full set incl. `:visited` inside
  states.
- Everything is render-time: the saved HTML carries **nothing** for states -
  no class, no inline style. Write the comment attr only.
- Preset refs (`var:preset|...`) work inside state styles and are emitted as
  `var(--wp--preset--...)` in the generated CSS, with `!important`.

## Per-block visibility (6.9, viewport form in 7.0)

`metadata.blockVisibility` (NOT `metadata.visibility`):

```
{"metadata":{"blockVisibility":false}}                          -> renders NOTHING
{"metadata":{"blockVisibility":{"viewport":{"mobile":false}}}}  -> class wp-block-hidden-mobile
                    + @media (width <= 689.98px){.wp-block-hidden-mobile{display:none !important}}
```

`false` hides on the front end even for blocks whose visibility support is off.
Support is default-ON; block.json only carries opt-outs (freeform, html, more,
nextpage, shortcode, pattern, missing, and the tabs/accordion structural
children).

## Per-block custom CSS (7.0)

`customCSS` support, default-ON for every block (opt-outs only: freeform,
html, more, nextpage, shortcode, missing, block). Serializes as `style.css`
in the comment plus class `has-custom-css` in the saved HTML; at render the
server adds a hashed `wp-custom-css-{hash}` class and emits the compiled
stylesheet. **Nesting with `&` works** - measured output:

```
<!-- wp:paragraph {"style":{"css":"color:red; & a{color:blue} &:hover{background:#eee}"}} -->
<p class="has-custom-css">x <a href="#">y</a></p>

:root :where(.wp-custom-css-2c55d9ec){color:red;}
:root :where(.wp-custom-css-2c55d9ec a){color:blue}
:root :where(.wp-custom-css-2c55d9ec:hover){background:#eee}
```

Bare declarations scope to the block; `& <sel>` scopes descendants; `&:state`
scopes pseudo-classes. Everything lands under `:root :where(...)` so it stays
low-specificity. Identical CSS across instances shares one hashed class and is
emitted once. CSS containing HTML markup (`<tag`) is rejected wholesale.
Remember `&` must be written `\u0026` inside the attrs JSON
(serialize_block_attributes escaping - blockmark.serialize does it).

**The strip trap (measured):** when the acting user lacks `edit_css` - and
WP-CLI has NO user - a `content_save_pre` filter at priority 8
(`wp_strip_custom_css_from_blocks`) deletes every `style.css` on the way into
the database. It is separate from kses; `kses_remove_filters()` does not stop
it. `apply-post.php` calls `wp_custom_css_remove_filters()` for exactly this
reason, and its byte-compare would expose the loss if anything else strips.

There is **no per-block custom JS** in core (no block-support for it; the
interactive behaviour blocks ship with comes from the Interactivity API's
`data-wp-*` directives, which are render-time and tied to registered script
modules, not an editable field). Per-block custom HTML is the pre-existing
"edit as HTML" mode plus `core/html` - which is opted OUT of customCSS.

## fitText (paragraph + heading)

Client-injected top-level attr `"fitText":true` (gated on
`supports.typography.fitText`). Save output marks it with class
`has-fit-text`; at render the server adds Interactivity API directives
(`data-wp-init---core-fit-text` etc.) and enqueues the fit-text module, which
sizes the text to fill the container width. **Measured trap**: without
`has-fit-text` in the saved HTML the block stays valid but the editor's
deprecation path silently EATS the attribute on parse. `validate-post.py`
errors on that (`E-CLASS`). fitText supersedes other typography features on
the block.

## Attribute migrations on existing blocks (write the NEW form)

- `textAlign` finished moving into `style.typography.textAlign`:
  7.0 moved button + comment-*, 7.1 moved post-date/excerpt/title/
  navigation-link, query-title, site-tagline, site-title, term-name, pullquote.
  The class stays `has-text-align-*`.
- `core/button`: `width` attr (25/50/75/100) REPLACED by
  `style.dimensions.width` (any CSS width). Render injects
  `--wp--block-button--width` + `has-custom-width wp-block-button__width*`
  classes - do not write those.
- `core/group`: + `dimensions.minWidth` (7.1), `background.gradient` (7.1).
  `background.gradient` also landed on quote, pullquote, verse, post-content,
  accordion - it reuses the existing `gradient` preset attr / `style.color.gradient`.
- `core/image`: + `isDecorative` (alt="" semantics).
- `core/video`: + `width`/`height` attrs.
- `core/cover`: + `allowedVideoProviders` (youtube/vimeo/videopress/animoto/
  tiktok/wordpress-tv).
- `core/latest-posts`: `columns`/`postLayout` REMOVED in favour of the
  `layout` support; `core/search`: `isSearchFieldHidden` removed, `tagName`
  added; `core/page-list`: `isNested` removed.
- Paragraphs now get `wp-block-paragraph` injected at RENDER time (saved
  markup still carries no class - do not add one).

## New support keys, by version

- 7.0: `customCSS`, `listView`, `dimensions.width`, `typography.textAlign`,
  `typography.textColumns`, `typography.textIndent`, anchor on ~20 more blocks
- 7.1: `background.gradient`, `dimensions.minWidth`, `layout.allowOrientation`,
  `layout.allowWrap`, plus the `visibility` opt-outs on new structural blocks

theme.json gains `settings.viewport` (the breakpoints states and visibility
compile against): on this site `mobile: 689.98px`, `tablet: 999.98px`.
