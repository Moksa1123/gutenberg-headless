# Custom CSS and JS: what WordPress actually gives you

Short answer, measured on WP 7.1:

| you want | WordPress has | where |
|---|---|---|
| CSS scoped to ONE block | **yes** — `style.css` attribute (7.0+) | this page, §1 |
| CSS for the whole page | not natively — use one `core/html` design layer | §2 |
| JS scoped to one block | **no.** Core has no per-block custom JS, at all | §3 |
| JS for the whole page | not natively — use one `core/html` behaviour layer | §3 |
| interactivity without writing JS | core's interactive blocks | §4 |

## 1. Per-block custom CSS (native, WP 7.0+)

Every block supports it unless it opts out (`customCSS` support; the opt-outs
are freeform, html, more, nextpage, shortcode, missing, block).

```html
<!-- wp:paragraph {"style":{"css":"border-left:4px solid #ffd800; padding-left:1em; & a{color:#c0392b} &:hover{background:#fdf6e3}"}} -->
<p class="has-custom-css">text with <a href="#">a link</a></p>
<!-- /wp:paragraph -->
```

Rules, all measured:

- The saved HTML must carry **`has-custom-css`**; the hashed
  `wp-custom-css-{hash}` class and the stylesheet are added at render.
- **`&` nesting works**: bare declarations hit the block, `& sel` its
  descendants, `&:hover` its states. Compiled output:
  `:root :where(.wp-custom-css-2c55d9ec a){...}`
- `&` must be written **`&`** inside the attrs JSON.
- Identical CSS on several blocks shares one hash and is emitted once.
- CSS containing HTML markup (`<tag`) is rejected wholesale.
- **The specificity ceiling**: everything compiles under `:root :where(...)`,
  i.e. specificity (0,1,0) *by design*. It can never out-rank a plugin's
  `.wp-block-woocommerce-checkout .field{...!important}`. When you must win
  that fight, use the design layer (§2).
- **The strip trap**: a `content_save_pre` filter deletes every `style.css`
  when the acting user lacks `edit_css` — and WP-CLI has no user at all. It is
  separate from kses; `kses_remove_filters()` does not stop it.
  `apply-post.php` calls `wp_custom_css_remove_filters()` for exactly this.

## 2. Page-level CSS: the design layer

There is no native "page custom CSS" field for block pages. The working
pattern (used by `examples/onepage-woo.html`, editor-validated at 169 blocks):
**one `core/html` block, first on the page**, carrying `<link>` for web fonts
and a single `<style>`:

```html
<!-- wp:html -->
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+TC:wght@700&display=swap" rel="stylesheet">
<style>
h1.wp-block-heading,h2.wp-block-heading{font-family:'Noto Serif TC',serif}
.gb-reveal{opacity:0;transform:translateY(26px);transition:opacity .7s,transform .7s}
#checkout .wc-block-components-address-form__last_name{order:2 !important}
</style>
<!-- /wp:html -->
```

Use it for: display typography, animation keyframes/classes, and any override
that must beat a plugin (an id-based rule is specificity (1,2,0) and wins where
per-block css structurally cannot).

## 3. JavaScript: the behaviour layer

**Core has no per-block custom JS.** No block support, no attribute, nothing in
`wp-includes/block-supports/`. The Interactivity API's `data-wp-*` directives
are render-time plumbing tied to registered script modules — developer
infrastructure, not an authoring field.

The sanctioned form is **one `core/html` block, last on the page**, with plain
vanilla JS:

```html
<!-- wp:html -->
<script>
(function(){
  var io = new IntersectionObserver(function(es){
    es.forEach(function(e){ if(e.isIntersecting){ e.target.classList.add('gb-in'); io.unobserve(e.target); } });
  }, {threshold:.15});
  document.querySelectorAll('.wp-block-quote, .wp-block-table').forEach(function(el){
    el.classList.add('gb-reveal'); io.observe(el);
  });
})();
</script>
<!-- /wp:html -->
```

Measured constraints:

- It survives the editor untouched — a page with both layers held
  `isValid` on every block **and** a byte-identical resave.
- kses strips `<script>` for users without `unfiltered_html`. `apply-post.php`
  removes those filters for the write; a human editing in wp-admin needs the
  capability (administrator on single site).
- One block, not scattered — the editor shows it as a single HTML block and
  the reader can find all the page's behaviour in one place.
- Respect `prefers-reduced-motion` in the CSS half; the animation classes live
  in the design layer, the observer in the behaviour layer.

## 4. Interactivity without writing JS

Core ships interactive blocks whose behaviour needs no code from you:
`core/tabs`, `core/accordion` (7.1), `core/details`, `core/navigation`,
image lightbox (`"lightbox":{"enabled":true}`), and `fitText` on
paragraph/heading. `gb.py block <name>` tells you which context each needs.
Prefer these — they are accessible, translated, and survive theme changes;
the behaviour layer is for what they cannot do.

## 5. Where each one lands in the page

| layer | block | position | carries |
|---|---|---|---|
| design | `core/html` | first | `<link>` fonts, `<style>` typography/animation/high-specificity overrides |
| per-block | any block's `style.css` | in place | styling scoped to that one block |
| behaviour | `core/html` | last | one `<script>`, vanilla, no dependencies |

`validate-post.py` treats all three as first-class: `style.css` is checked for
its `has-custom-css` class, and `core/html` content passes through verbatim.
