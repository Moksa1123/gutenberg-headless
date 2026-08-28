# The data model

A block-editor page is **one string**: `post_content`. There are no meta keys to
set, no compiled CSS to rebuild, no edit mode to flag - everything Elementor
spreads across four meta keys, Gutenberg keeps in the content itself. That makes
writing simpler and verifying harder: both halves of a block (the comment and
the HTML) live in the same string, and nothing checks they agree.

## The grammar

```
static:   <!-- wp:namespace/name {"attr":value} -->SAVED HTML<!-- /wp:namespace/name -->
void:     <!-- wp:namespace/name {"attr":value} /-->
freeform: any HTML not inside a block comment (becomes a blockName:null node)
```

- The `core/` namespace is **omitted** in serialized form: `wp:paragraph`, never
  `wp:core/paragraph`. Every other namespace is written in full
  (`wp:woocommerce/cart`, `wp:blocksy/breadcrumbs`).
- Block names match `[a-z][a-z0-9_-]*` on both sides of the `/`.
- Nesting is by containment: a child block's comments sit inside the parent's
  HTML. The parent's own markup is split around the children.
- `tools/blockmark.py` is a Python port of `WP_Block_Parser`, verified by
  round-tripping real posts against `serialize_blocks(parse_blocks(...))` on the
  live site: 5 of 6 byte-identical, the sixth differing only by the `{}`→`[]`
  normalization below.

## Attrs JSON escaping

`serialize_block_attributes()` escapes sequences that would break the HTML
comment or trip kses: `--` → `\u002d\u002d`, `<` → `\u003c`, `>` → `\u003e`,
`&` → `\u0026`. Write a literal `--` inside an attribute value and the comment
terminates early; the parser reads garbage. `blockmark.serialize()` does this
for you.

## Where an attribute lives - the one distinction that matters

Every attribute is registered with or without a `source`:

| | stored in | writing it in the other place |
|---|---|---|
| no `source` | the comment JSON | - |
| `source: rich-text / html / attribute / query` | **the saved HTML**, at the registered `selector` | does nothing, silently |

`core/paragraph`'s `content` has `source: rich-text, selector: p`. Put
`"content":"hello"` in the comment and the paragraph renders **empty** - the
front end shows the HTML (there is none), the editor reads the HTML (there is
none). `gb.py block <name>` labels every sourced attribute `IN-HTML`;
`validate-post.py` errors with `E-SOURCED` if one appears in the comment.

## Three families of block (measured on the target site)

| family | count | serialized as | the content is |
|---|---|---|---|
| content-in-HTML (has sourced attrs) | 28 | comment + HTML | the saved HTML |
| static wrapper (no source, no callback) | 14 | comment + HTML | the saved HTML |
| pure dynamic (render_callback, no source) | 260 | void `/-->` | the comment attrs; server renders at view time |

For the first two families **the front end never reads the comment attrs** - it
delivers the saved HTML through `the_content` filters. For the third the saved
HTML is at most a hydration skeleton (WooCommerce uses it as one; core
pure-dynamic blocks regenerate wholesale).

`is_dynamic` alone does not tell you which family a block is in: in WP 7.1 even
`core/heading` has a render callback (a filter pass), but its content is still
the saved HTML. The classifier is **sourced attrs first, callback second** -
`gb.py block <name>` prints the family on the second line.

## What the editor does to your markup (validation and migration)

On open, the editor re-runs each block's `save()` against your saved HTML.
Three outcomes:

1. **identical** - valid, silent.
2. **matches a registered deprecation** - the block is *valid* and the editor
   holds the **migrated** attributes in memory. Nothing warns you. The next
   manual save rewrites your markup to the canonical form. Measured here: a
   heading written with the legacy top-level `"textAlign":"center"` stayed
   valid, and resave rewrote it to `"style":{"typography":{"textAlign":"center"}}`
   and dropped `"level":2` (default values are omitted).
3. **matches nothing** - "This block contains unexpected or invalid content",
   and the user must click through a recovery dialog.

The demo page in `examples/demo-page.html` was tuned until
`wp.blocks.serialize(getBlocks())` equalled the stored content **byte for
byte** (21 blocks, `identical:true`). That is the standard to aim for: markup
the editor would have written itself.

## Writing it: kses and slashing

Two things silently rewrite your content on the way into the database:

- **kses.** WP-CLI runs with no user; no user means no `unfiltered_html`
  capability, and the kses filters are hooked. Tags and attributes outside the
  allowlist are stripped, unicode escapes can be mangled - no error.
- **slashing.** `wp_update_post()` runs `wp_unslash()` on its input. Content
  containing backslashes (every `\u002d\u002d` escape) loses them unless you
  `wp_slash()` first.

`tools/apply-post.php` handles both (`kses_remove_filters()` + `wp_slash()`),
then **reads the row back and byte-compares it to your file**, so a rewrite is
an error message instead of a corrupted page. It refuses to write a file in
which `parse_blocks()` finds zero blocks.

## The PHP empty-object trap

`json_decode($attrs, true)` cannot tell `{}` from `[]`, so any server-side
resave (`serialize_blocks`, some plugins' filters) rewrites `"taxQuery":{}` to
`"taxQuery":[]`. Measured on this site's WooCommerce cart page. The JS editor
preserves `{}`. If an attribute's consumer distinguishes empty-object from
empty-array, avoid storing either empty form; omit the attribute instead.

## Caches between the database and the visitor

The row can be right and the visitor still get the old page: object cache
(Redis via Object Cache Pro here), page cache (Breeze), Varnish (Cloudways),
then the CDN. `apply-post.php` flushes the object cache and purges Breeze;
`verify-live.py` prints the response's cache headers (`x-cache`, `age`) so a
stale edge is visible rather than silent.
