---
name: "gutenberg-headless"
description: |
  Build and modify WordPress block-editor (Gutenberg) pages by writing the serialized block markup directly - no editor, no browser. Query the full block surface of the target site (302 block types, every attribute, support and preset) instead of guessing, with every block's bare-page render behaviour measured by an actual do_blocks() sweep, and validate that the comment JSON and the saved HTML - the two halves WordPress never checks against each other - actually agree.
license: "MIT"
author: "moksa (https://moksaweb.com)"
version: "1.0.0"
---

# Headless Gutenberg

Build block-editor pages by writing `post_content` directly. The editor is one
client of that format; it is not the format, and you do not need it.

**Scope: page construction.** Making a page of blocks exist, look right, and
survive both the front end and the editor. Not site health, not plugin audits,
not theme building.

## The one rule that overrides everything

**A block is two halves that WordPress never checks against each other.** The
comment JSON is what the *editor* reads; the saved HTML is what the *visitor*
gets. Write `"backgroundColor":"accent"` in the comment and skip the
`has-accent-background-color` class in the HTML, and the front end shows no
background, the editor shows one, and nobody shows an error. Every mistake in
this format is that mistake in some costume: value in the wrong half, class
missing from one half, slug that exists in neither.

So: **never write an attribute name, a preset slug, a wrapper class or a "this
block exists" claim from memory. Look it up, then validate both halves.**

Everything in `data/` was extracted from the live target site and then made to
prove itself:

```
PARSER    blockmark.py round-tripped against serialize_blocks() on the live
          site over real posts: byte-identical (one divergence is the server's
          own {}->[] normalization, documented)
RENDER    302/302 blocks swept through do_blocks() on a bare page, 0 errors:
          69 render, 205 render NOTHING (need context), 28 are content blocks
EDITOR    the shipped demo page: 21/21 blocks isValid in Gutenberg itself, and
          the editor's own resave is byte-identical to the file we wrote
LIVE      verify-live.py PASS on the public URL through Breeze/Varnish: every
          text fragment, class, inline rule and preset var asserted against
          the delivered bytes
```

## Not every block exists on every install

**The block surface is a property of the SITE.** This one registers 302 block
types: 116 `core/*`, 165 `woocommerce/*`, 13 `blocksy/*`, plus wpforms and
moksa plugins. A bare WordPress has ~116. Name a block the target site does not
register and the front end prints your raw HTML while the editor demands
recovery - no warning at write time (`E-BLOCK` at validate time).

```bash
python tools/gb.py blocks --namespace woocommerce --grep price
python tools/gb.py block woocommerce/product-price      # errors if absent, suggests close names
```

Re-extract to describe a different site (see extraction-traps.md §6).

## Three families, three writing modes

`is_dynamic` is misleading (272/302 carry a render callback - even
`core/heading`). What matters is where the content lives. `gb.py block <name>`
prints the family on line two:

| family | count | you write |
|---|---|---|
| CONTENT-IN-HTML (has sourced attrs) | 28 | comment + the full saved HTML; sourced attrs (`content`, `citation`, `url`...) live ONLY in the HTML - `E-SOURCED` if you put them in the comment |
| STATIC WRAPPER | 14 | comment + wrapper HTML (`group`, `columns`, `spacer`...) |
| PURE DYNAMIC | 260 | a void comment `<!-- wp:x {...} /-->`; attrs are everything |

And the killer number for the third family: **205 of 302 blocks render NOTHING
on a bare page** - they need a product, a post, a cart, a query loop. The sweep
verdict is printed by `gb.py block <name>` (`render-sweep: empty`) together
with `uses_context`, so you find out before writing, not after publishing an
invisible page.

## The two serialization moments

**Save-time is yours.** The classes and inline styles the editor would have
generated, you generate: preset attrs → `has-*` classes, style object → inline
CSS with `var:preset|kind|slug` expanded to `var(--wp--preset--kind--slug)`,
`className`/`anchor`/`align` into the markup. Tables in
supports-and-styles.md; `validate-post.py` enforces every one of them.

**Render-time is the server's.** `layout`, `style.elements`, duotone become
`wp-container-*`/`wp-elements-*`/`wp-duotone-*` classes injected while
serving. Write those into stored markup and the editor flags it. Rule of
thumb: `has-*` yourself, `wp-container-*` never.

A preset slug must exist on the target site or its class styles nothing,
silently (`E-PRESET`):

```bash
python tools/gb.py presets color          # palette-color-1..8 on this site (Blocksy)
python tools/gb.py var "var:preset|spacing|60"
```

## Look it up like this

```bash
python tools/gb.py stats                          # what site, what's in here
python tools/gb.py blocks --grep cart             # find a block
python tools/gb.py blocks --static --top-level    # what can stand alone as written HTML
python tools/gb.py block core/group               # one block: family, attrs, supports, sweep verdict
python tools/gb.py block heading --grep color     # filter its attrs
python tools/gb.py supports core/image            # the full flattened supports tree
python tools/gb.py presets                        # every preset slug on the site + CSS var
python tools/gb.py styles                         # is-style-* variations
python tools/gb.py patterns --grep hero           # registered patterns
python tools/gb.py var "var:preset|color|x"       # expand a preset ref, check it exists
python tools/gb.py skeleton                       # a minimal valid page
python tools/gb.py grammar                        # the serialization cheat sheet
```

Add `--json` to any of them. **Never read `data/block-schema.json` into
context** - it is the database; `gb.py` is the query. `data/*.csv` are there
for grep.

## Build a page

```bash
python tools/gb.py skeleton > page.html
# ...edit, looking every attribute and slug up as you go...

python tools/validate-post.py page.html                    # BEFORE writing anything
wp eval-file tools/apply-post.php new page.html "Title" page publish
wp eval-file tools/apply-post.php <post_id> page.html      # or update in place
python tools/verify-live.py page.html https://site/slug/   # what the PUBLIC gets
```

`validate-post.py` is not optional. It catches what WordPress will not:
unregistered blocks, unknown/mistyped attrs, enum violations, sourced attrs in
the comment, preset slugs that do not exist, every class and inline rule the
comment promises but the HTML lacks, parent/ancestor violations, content
blocks with no content.

`apply-post.php` exists because the write path itself lies: WP-CLI has no user
→ kses rewrites your markup; `wp_update_post` unslashes → your attr escapes
vanish. It removes kses for the write, slashes, **byte-compares the stored row
against your file**, and purges the caches (object cache + Breeze) between the
database and the visitor.

And the page must earn a pass in the one place no server-side tool can reach -
the editor's own JS validator. Cheap browser check, no clicking:

```js
// wp-admin editor console, or driven via browser automation
wp.data.select('core/block-editor').getBlocks().filter(b => !b.isValid)  // want: []
wp.blocks.serialize(wp.data.select('core/block-editor').getBlocks())
  === wp.data.select('core/editor').getCurrentPost().content             // want: true
```

Aim for the second line too: write the **canonical current form**, because a
deprecated form stays valid while the next manual save silently rewrites it
(measured: `"textAlign":"center"` → `"style":{"typography":{"textAlign":"center"}}`,
defaults like `"level":2` dropped). `examples/demo-page.html` passes both -
that is the file to imitate.

## Reference

| Doc | What's in it |
|---|---|
| [data-model.md](references/data-model.md) | the grammar, where each attr lives, editor validation/migration, kses+slash, `{}`→`[]`, caches |
| [supports-and-styles.md](references/supports-and-styles.md) | every save-time class formula, the style object, preset vars, render-time injections, this site's palette |
| [dynamic-blocks.md](references/dynamic-blocks.md) | the 260 pure-dynamic blocks, the 205-empty sweep, context, WooCommerce's hydration skeletons, drift |
| [extraction-traps.md](references/extraction-traps.md) | the eight ways the schema can lie (JS-only truth among them) and how each is compensated |
| [wp71-new-surface.md](references/wp71-new-surface.md) | what 7.0/7.1 added, measured: per-block `:hover`/`@mobile` states, `blockVisibility`, `style.css`, `fitText`, tabs/accordion/math/playlist, the textAlign/button-width migrations |
| [canonicalization.md](references/canonicalization.md) | byte-identical rules: attr key order, class order, id-before-class, LF, default omission, is-open - and the console loop that converges any page |
| [fidelity.md](references/fidelity.md) | a designed HTML/CSS/JS/SVG page rebuilt as 48 blocks to full parity: what is native, what rides on style.css, what is impossible |
| [woo-onepage.md](references/woo-onepage.md) | one-page WooCommerce checkout that placed a real order: single-product family shapes, the is_checkout() mu-plugin trap, Store-API E2E procedure, RWD verification checklist |

## Verify it rather than trusting it

The schema describes booking.moksaweb.com: WP 7.1, Blocksy 2.1.53,
WooCommerce 11. Yours differs. Make it prove itself:

```bash
wp eval-file tools/extract-block-schema.php > mine.json
wp eval-file tools/sweep-render.php > render-sweep.json    # re-measure, don't assume
python tools/build-indexes.py mine.json --out data/ \
    --render-verification data/render-verification.csv
```

## Tools

| Tool | Does |
|---|---|
| `gb.py` | query the schema - **the front door** |
| `blockmark.py` | parse/serialize block markup, round-trip-faithful (also a library) |
| `validate-post.py` | pre-flight both halves of every block before writing |
| `apply-post.php` | write content past kses/slashing, byte-verify the row, purge caches |
| `verify-live.py` | assert the page the PUBLIC receives, through every cache |
| `audit-contrast.js` | in-page WCAG contrast audit (gradients, cover dims, symbols) - design verification |
| `check-rwd.js` | per-breakpoint layout audit: real overflow (a theme's `overflow-x:hidden` hides it from the scrollbar), tiny type, small targets |
| `collect-fingerprint.js` + `diff-fingerprints.py` | 35 computed properties per element on two pages, paired and diffed - the only honest answer to "does it match the original" |
| `extract-block-schema.php` | dump a live site's full block surface + theme.json |
| `sweep-render.php` | render all blocks through do_blocks(), record who shows nothing |
| `build-indexes.py` | turn dump + sweep into the shipped data files |
