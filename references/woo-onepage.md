# One-page WooCommerce checkout, blocks only — the working recipe

Proven end-to-end on the test site: a marketing one-pager (post 4413, 119
blocks, `elementor_canvas` template) with hero → proof strip → benefit grid →
itinerary → testimonials → urgency band → **product section → same-page
checkout** → trust footer. A real order was placed through it from the public
page (order #4414: COD, NT$1,490, billing complete, district synced to city).
Validator 0 errors, verify-live PASS (356 assertions, 32 dynamic wrappers
delivered), editor 119/119 `isValid`, resave byte-identical. RWD verified at
390/820/1366 (no horizontal overflow, grid 1→2→4 columns, `@mobile` type
scale, decorative SVG hidden on mobile via `blockVisibility`).

## The product section (canonical shapes, all editor-verified)

```
<!-- wp:woocommerce/single-product {"productId":ID,"align":"wide"} -->
<div class="wp-block-woocommerce-single-product alignwide woocommerce">   ← note the extra `woocommerce` class
  ...columns...
  <!-- wp:woocommerce/product-image {"showProductLink":false,"showSaleBadge":false,"productId":ID,"isDescendentOfSingleProductBlock":true,...} /-->
  <!-- wp:woocommerce/product-price {"productId":ID,"isDescendentOfSingleProductBlock":true,"fontSize":"x-large"} /-->
  <!-- wp:woocommerce/add-to-cart-form {"quantitySelectorStyle":"stepper"} /-->
</div>
<!-- /wp:woocommerce/single-product -->
```

- Inner product blocks take `productId` + `isDescendentOfSingleProductBlock:true`
  explicitly - the wrapper's context does the rendering, the attrs keep the
  editor canonical.
- The editor **forces `showSaleBadge:false`** on product-image inside
  single-product (writing `true` gets normalized back - measured). Sale price
  strikethrough still renders from product-price.
- add-to-cart-form renders the classic PHP form: submitting reloads the page
  with the cart populated - which is exactly what makes the same-page checkout
  work with zero JS of ours.

## The checkout section

Copy the `wp:woocommerce/checkout` skeleton **verbatim from the site's own
checkout page** (post 8 here, 48 inner blocks) - never hand-compose it. With
an empty cart it renders a browse-store prompt; once the visitor adds the
product it renders the full form on the same URL.

**The `is_checkout()` trap (measured, cost a failed order):** plugins register
conditional checkout machinery only where `is_checkout()` is true, and a page
carrying the checkout block does NOT count - WP/WC do not map block presence
to that conditional. Here, moksa-for-woocommerce's TW district field
(`moksafowo/district`, an additional-checkout-fields dropdown of 369
townships) never rendered on the one-pager while its Store-API-side
enforcement still rejected the order (「宅配訂單請選擇鄉鎮市區」). Fix shipped as a
mu-plugin (`wp-content/mu-plugins/onepage-checkout-context.php`):

```php
add_filter( 'woocommerce_is_checkout', function ( $is ) {
    if ( $is || ! is_singular() ) return $is;
    $post = get_post();
    return $post && has_block( 'woocommerce/checkout', $post );
} );
```

Required for ANY one-page checkout on this site; harmless elsewhere.

## E2E checkout test procedure (browser)

1. Public page → click 加入購物車 (page reloads, cart filled).
2. Scroll to checkout - React form is live. Fill via native setters +
   `input`/`change` events (plain `.value=` does not reach the React store).
3. Fields that exist only in data, not DOM, can be set through the store:
   `wp.data.dispatch('wc/store/cart').updateCustomerData({...})` - but
   server-side locale rules may discard them (TW city is hidden AND cleared;
   only the district field feeds it, via the plugin's sync).
4. Pay with an offline gateway (`cod`/`bacs`) - a checkout test needs no
   payment credentials.
5. Assert server-side, not screen-side: `wp wc shop_order list` - status,
   total, gateway, billing fields, and (here) district→city sync.

## Styling WC blocks on a bare canvas

On `elementor_canvas` some WC component styles don't fully land; the classic
add-to-cart stepper collapsed. Per-block custom CSS on the surrounding group
fixes it, but WC's own rules win specificity against `:root :where(...)` -
use `!important` inside `style.css` for the contested properties (flex layout,
`position:static`, widths on `.wc-block-components-quantity-selector`). Same
for the empty-cart browse button. Custom CSS scoped to the section cannot leak.

## The design layer and the behaviour layer (measured pattern)

With kses removed at write time (apply-post.php), a `core/html` block may carry
`<link>`, `<style>` and `<script>` - and it round-trips the editor untouched
(122/122 valid, byte-identical WITH both layers in). That unlocks what block
attributes cannot do:

- **Design layer** (first block): Google Fonts `<link>` + one `<style>` tag -
  display typography (`Noto Serif TC` on headings, `Manrope` tabular numerals),
  `::selection`, `scroll-behavior`, keyframes/transition classes for reveal
  animations, and any **high-specificity overrides**. This is the escape hatch
  for the custom-css ceiling: per-block `style.css` always compiles to
  `:root :where(...)` = specificity (0,1,0), so it can NEVER out-rank a
  plugin's `.wp-block-woocommerce-checkout .field{...!important}` - an id-based
  rule in the design layer ((1,2,0) + !important) can. Measured on the TW
  address reorder: custom css lost to moksa's rules, the design layer won.
- **Behaviour layer** (last block): one vanilla `<script>` - IntersectionObserver
  reveal-on-scroll (progressive delays, `prefers-reduced-motion` respected),
  live countdown to next Sunday 23:59, count-up numerals. No dependencies, no
  build. This is the sanctioned form of "custom JS per page" - one html block,
  not scattered scripts.

## Taiwan-style checkout field order (measured)

`showFormStepNumbers:true` on the checkout block gives numbered steps. Field
order inside the address step is plugin/locale-controlled; reorder it with
design-layer CSS (`#checkout .wc-block-components-address-form__X{order:N
!important}` + flex column on the form). Verified visual order on the live
form: 姓氏 → 名字 → 電話 → 郵遞區號 → 縣市 → 鄉鎮市區 → 地址 (email stays in
step 1 聯絡資訊). The district wrapper matches `[class*=moksafowo-district]`.

## Canonicalization rules this page added (also in canonicalization.md)

- alignfull group with anchor: `class` comes BEFORE `id` (without align, id first).
- `core/button` `typography.fontWeight` serializes as inline `font-weight` on
  the inner `<a>` (last in the style attr) - not on the wrapper.
- single-product wrapper carries `woocommerce` alongside its block class.
- WC checkout/cart inner skeletons round-trip byte-identically when copied
  verbatim - they are dynamic and the editor does not regenerate them.

## Design verification: the contrast audit (do this every page)

`tools/audit-contrast.js` runs in the page (Playwright evaluate or console)
and flags every text element whose WCAG contrast fails against its EFFECTIVE
background - walking ancestors for solid colors, checking every stop of a
gradient, blending cover-block dim overlays (worst-case white photo), treating
pure-symbol text (stars) as graphics (3:1), and skipping screen-reader-only
elements. Found on this page's first run, all real: theme-black headings
inherited onto a dark hero (the theme's `h1{color}` beats color INHERITANCE -
always set an explicit `textColor` on headings over dark backgrounds), gold
eyebrow text at 2.7:1, star glyphs at 2.1:1, and the theme's yellow link color
inside the checkout on white. Fix, re-run, require zero failures.

## RWD verification (do this every page - Playwright)

For each of 390×844 / 820×1180 / 1366×900:

1. `scrollWidth - innerWidth <= 0` on the scrolling element (no horizontal overflow).
2. Grid columns collapse as designed (`getComputedStyle(grid).gridTemplateColumns`).
3. `@mobile` state styles actually apply (computed font-size at 390 equals the
   override; at ≥690 the fluid clamp value).
4. `blockVisibility` viewport rules: hidden elements report `display:none`
   inside `.wp-block-hidden-mobile`.
5. Interactive controls keep their geometry (stepper width/height, buttons not
   wrapping vertically).
6. Screenshot each breakpoint at hero + buy + checkout; look at them.

Breakpoints come from theme.json `settings.viewport` (here 689.98/999.98px) -
assert against those, not against your habits.
