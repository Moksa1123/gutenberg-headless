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

Deterministic, computed by save() regardless of your stored order. Ask the
editor rather than guessing - `getSaveContent` on synthetic attributes that
set every class-producing support at once answers it exactly:

```js
const t = wp.blocks.getBlockType('core/group')
wp.blocks.getSaveContent(t, { ...wp.blocks.getBlockAttributes(t, ''),
  align: 'full', className: 'ZZ', fontFamily: 'ff', fontSize: 'large',
  style: { color:{background:'#111',text:'#222'}, border:{color:'#333',width:'1px'},
           css:'color:red' } }, [])
```

That returns, for group / heading / paragraph / list alike:

```
wp-block-{name}  align{full|wide}  has-text-align-*  {className}
has-border-color  has-custom-css  has-text-color  has-background
has-{slug}-font-family  has-{slug}-font-size
```

**`className` comes EARLY - right after the alignment classes**, not last. An
out-of-order list is still valid (the validator compares class tokens as a
set) but not byte-identical, so the editor's next save reshuffles it.

`core/button` is composed differently, and its two elements have two orders:

```
<div class="wp-block-button {className}">
  <a class="wp-block-button__link has-text-color has-background has-border-color
            has-{slug}-font-family has-{slug}-font-size has-custom-font-size
            wp-element-button">
```

Note `className` lands on the **wrapper**, never on the `<a>`. A design-layer
class written onto the link is markup save() would never produce: the server
stores it, the page renders right, and the editor marks the block invalid.
Style the link through a descendant selector instead
(`.cls.cls .wp-block-button__link`).

## Declare every custom class in `className`

The parser pulls any class it did not generate off the wrapper and into the
`className` attribute. So a class written only into the HTML leaves the block
valid but not round-trip stable - the editor's resave adds
`"className":"..."` to the comment. Write it yourself, and **merge** rather
than skip when the block already has one (a heading carrying
`has-custom-font-size` still needs its design classes appended).

Gate this on `supports.customClassName`, not `supports.className`: the latter
means "do not add the generated `wp-block-<name>` class" and core/paragraph
sets exactly that.

## Inline style declaration order

A flat CSS-property order, NOT an order over the style object's groups - read
from the same `getSaveContent` probe with every style group populated:

```
border-color  border-style  border-width  border-radius
color  background-color
aspect-ratio  height  min-height  width
margin-*  padding-*
font-family  font-size  font-style  font-weight  letter-spacing  line-height
text-decoration  text-transform
box-shadow
```

`core/button`'s link puts **box-shadow before typography** and keeps
`min-height` on the wrapper instead.

## HTML attribute order

`id` (from `anchor`) comes BEFORE `class`: `<div id="faq" class="wp-block-group">`.
Inline `style` comes after `class`.

Block-specific attributes sit BETWEEN them, not before: core/button emits
`<a class="..." href="..." style="...">`. Writing the href first is valid,
renders identically, and still makes the editor rewrite the tag on save.

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
