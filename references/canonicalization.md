# Canonicalization: writing markup the editor would have written

The stability bar for every page this skill ships:
`wp.blocks.serialize(getBlocks()) === stored content`, byte for byte. Anything
less means the next manual save rewrites your markup - and whatever the editor
did not recognize gets silently dropped on the way. Three pages on the test
site hold this bar (posts 4398, 4400, 4404 - the last one 48 blocks deep).
Every rule below was found by iterating a real page to `identical:true`, not
by reading source.

## Comment JSON key order

The serializer walks the block's attributes object. For a parsed block that
object *starts* in your stored order, but any block whose edit component
normalizes attributes rebuilds it in **client-registry order** - the order the
attributes appear in `wp.blocks.getBlockType(name).attributes`. Different
blocks disagree:

- group / paragraph / heading: `style` comes BEFORE `backgroundColor`/`textColor`
  (`align` earlier still: `{"align":"full","style":...,"backgroundColor":...,"layout":...,"anchor":...}`)
- button: `backgroundColor`/`textColor` come BEFORE `style`

When in doubt, build the block with `wp.blocks.createBlock` in the console and
read the order back. Getting it wrong is not invalid - it just breaks
byte-identity.

## Class order in saved HTML

Deterministic, computed by save() regardless of your stored order:

```
wp-block-{name}  align{full|wide}  has-text-align-*  has-border-color
has-custom-css  has-{slug}-color  has-{slug}-background-color
has-text-color  has-background  is-style-*  {className}
```

Measured anchors: `wp-block-group alignfull has-custom-css has-background`,
`wp-block-group has-border-color has-custom-css has-palette-color-6-background-color has-background`,
`wp-block-button has-custom-css` (button colors live on the inner `<a>`:
`wp-block-button__link has-{slug}-color has-{slug}-background-color
has-text-color has-background wp-element-button`).

## HTML attribute order

`id` (from `anchor`) comes BEFORE `class`: `<div id="faq" class="wp-block-group">`.
Inline `style` comes after `class`.

## Other byte-identity rules (all hit in practice)

- **LF only.** The editor emits `\n`; a file written with CRLF differs at the
  first line break. (Write files with `newline='\n'`.)
- **Default values are omitted**: `"level":2` on a heading disappears on
  resave; `"activeTabIndex":0` never serializes. Write attrs only when
  non-default.
- **Deprecated forms are rewritten**: legacy `"textAlign":"x"` becomes
  `style.typography.textAlign`. Write the current form (wp71-new-surface.md).
- **State classes are part of save output**: accordion-item with
  `"openByDefault":true` must carry `is-open` on its wrapper.
- **Derived content is engine output**: core/math's MathML is the editor's
  LaTeX renderer's exact tree (`<semantics><mrow>...<annotation
  encoding="application/x-tex">`); a hand-simplified `<math>` stays valid but
  rewrites on resave.
- **`--`, `<`, `>`, `&`** in attrs JSON
  (serialize_block_attributes) - blockmark.serialize handles it.

## Rules added by the Woo one-pager (all measured)

- **alignfull flips attribute order**: a group with `align` set emits
  `<div class="..." id="..." style="...">`; without align, `id` comes first.
- `core/button` `typography.fontWeight` → inline `font-weight` on the inner
  `<a>`, appended last in its style attribute (wrapper carries nothing).
- `woocommerce/single-product` wrapper: `wp-block-woocommerce-single-product
  align* woocommerce`.
- product-image inside single-product is normalized to `"showSaleBadge":false`
  no matter what you write.
- Verbatim-copied WC checkout/cart skeletons stay byte-identical (dynamic -
  the editor does not re-render them).

## The loop that gets you there

```js
// wp-admin editor console (or browser automation), after every apply:
const flat=[]; const walk=b=>b.forEach(x=>{flat.push(x);walk(x.innerBlocks)});
walk(wp.data.select('core/block-editor').getBlocks());
flat.filter(b=>!b.isValid)                       // must be []
const stored = wp.data.select('core/editor').getCurrentPost().content;
const resaved = wp.blocks.serialize(wp.data.select('core/block-editor').getBlocks());
stored === resaved                               // must be true
// if false: find the first differing byte and ask the editor for the
// canonical form of that block via createBlock + serialize. Fix. Repeat.
```

Each iteration converges: 48-block page needed four passes (class order,
is-open, attr key order, id/class order). The editor is the oracle; never
argue with it, query it.
