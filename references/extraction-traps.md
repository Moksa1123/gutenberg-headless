# How this schema can lie to you, and what was done about it

The schema is extracted from the **server** registry
(`WP_Block_Type_Registry`). The block editor is a JS application; some truth
exists only in the browser. Every known gap is listed here with how the skill
compensates - the ethos is the same as the Elementor skill's: where metadata
and rendered reality disagree, **the rendered result wins**.

## 1. JS-injected attributes the server never sees

Client code can add attributes via `blocks.registerBlockType` filters. Measured
on real content from the live site:

- `textAlign` on heading/post-title - injected when the block declares
  `supports.typography.textAlign`. The validator knows this one explicitly and
  validates its class instead of flagging it.
- `__woocommerceNamespace` on `core/post-title` - WooCommerce's client filter.

An attribute the server registry lacks is therefore a **warning** (`W-ATTR`),
not an error: it is either a typo (the editor drops it silently on resave) or
a JS-registered attribute. Both deserve a human look; only one is a bug.

## 2. Deprecations and save() live only in JS

The server cannot re-run `save()`, so no server-side tool can prove your HTML
matches the editor's expectation. The skill compensates twice:

- `validate-post.py` enforces the *rules* of save output (classes, inline
  styles, wrapper class, sourced attrs in HTML) - the mechanical 95%.
- The gold check is the editor itself:
  `wp.blocks.serialize(wp.data.select('core/block-editor').getBlocks())`
  compared byte-for-byte with the stored content, plus `isValid` per block.
  The shipped demo passes both (21/21 valid, `identical:true`).

Write the **canonical current form**, not a deprecated one: the deprecated form
stays valid but the next editor save rewrites it (measured: top-level
`textAlign` → `style.typography.textAlign`, default `"level":2` dropped).

## 3. `core/embed` variations are empty server-side

The YouTube/Twitter/Vimeo embed variations are registered in JS. The schema
honestly reports 0 variations for `core/embed`; the block itself still works
(`{"providerNameSlug":"youtube",...}`).

## 4. `is_dynamic` does not mean what it sounds like

In WP 7.1, blocks you would call static (`core/heading`) carry render
callbacks (filter passes), so `is_dynamic()` is true for 272 of 302 blocks.
The meaningful classifier is *has sourced attributes* (28) / *static wrapper*
(14) / *pure dynamic* (260) - see data-model.md. `gb.py` uses that, not the
raw flag.

## 5. PHP normalizes `{}` to `[]`

`serialize_blocks(parse_blocks(x))` on the server rewrites empty JSON objects
to empty arrays (`"taxQuery":{}` → `[]`) because PHP assoc-decodes them
identically. The editor does not. Round-trip comparisons must treat this as
expected noise - `blockmark.py` preserves the original bytes, which is why its
round-trip of six real posts beat the server's own on one of them.

## 6. The registry is a property of the SITE

302 blocks here; a bare WP has ~116. `woocommerce/*` (165) exists because
WooCommerce is active; `blocksy/*` because of Blocksy Companion. Ship markup
naming a block the target site does not register and the front end prints the
raw HTML while the editor demands recovery (`E-BLOCK`). Re-extract per site:

```
wp eval-file tools/extract-block-schema.php > dump.json
python tools/build-indexes.py dump.json --out data/ \
    --render-verification data/render-verification.csv
```

Localized titles come with the extraction (this one is zh_TW) - grep
`data/blocks.csv` by name, not by title.

## 7. Schema drift outlives content

Blocks written under an old plugin version stay in the database in the old
shape. The current schema's `parent:` constraints then *disagree with content
that works* (the live cart page, written by an older WooCommerce). `E-PARENT`
on existing content is a drift report; on new content it is a bug in your tree.

## 8. What was measured, and where

| claim | evidence |
|---|---|
| parser fidelity | 6 real posts round-tripped vs `serialize_blocks` on the live site: 5 byte-identical, 1 differs only by trap #5 |
| render behaviour | all 302 blocks through `do_blocks()`: `data/render-verification.csv`, 0 errors |
| save-output rules | demo page: validator 0 errors → editor 21/21 `isValid`, resave byte-identical |
| delivery | `verify-live.py` PASS against the public URL through Breeze/Varnish: every text fragment, class, inline rule and preset var asserted in the delivered bytes |
