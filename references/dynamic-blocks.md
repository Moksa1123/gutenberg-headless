# Dynamic blocks

260 of the 302 blocks on the target site are **pure dynamic**: no sourced
attributes, a server render callback, serialized as a void comment:

```
<!-- wp:latest-posts {"postsToShow":3,"displayPostDate":true} /-->
<!-- wp:woocommerce/cart /-->
```

The comment attrs are the entire block. There is no HTML to get right - and
nothing to see until the page is served.

## The sweep: 205 of 302 render NOTHING on a bare page

Every registered block was rendered server-side through `do_blocks()` in its
void form, on a bare page with no post, no product, no cart
(`tools/sweep-render.php`; verdicts in `data/render-verification.csv`, merged
into the schema so `gb.py block <name>` prints them):

| verdict | count | meaning |
|---|---|---|
| `renders` | 69 | produced markup with zero context |
| `empty` | 205 | produced **nothing** - it needs context |
| `content-block` | 28 | content is the saved HTML; a void test is meaningless |
| errors | 0 | every callback ran clean |

`empty` is not broken. `woocommerce/add-to-cart-form` needs a product page;
`core/post-title` needs a post; the cart blocks need a cart. The point of the
sweep is that you **know before writing** whether a bare page will show the
block or silently show nothing: `gb.py block woocommerce/product-price` says
`render-sweep: empty` and you go find the context it needs (`uses_context` is
printed too).

## Context

Dynamic blocks receive context from ancestors (`uses_context` /
`provides_context` in the schema). A `core/post-title` inside a
`core/query` + `core/post-template` gets `postId` from the loop and renders;
the same block at the top level of an ordinary page renders the *current*
post's title - and on a bare context, nothing. Parent constraints
(`parent:`/`ancestor:`, enforced by `E-PARENT`) usually encode where the
context comes from.

## Saved HTML inside dynamic blocks

Two conventions exist side by side:

- **Core pure-dynamic blocks** regenerate output wholesale; saved inner HTML is
  dead weight. The validator warns (`W-DYNHTML`).
- **WooCommerce cart/checkout blocks** deliberately save a full skeleton of
  inner blocks and divs - it is the SSR/hydration fallback for their React
  frontend. Not dead weight; the validator stays quiet for non-core namespaces.

When WooCommerce restructures those trees between versions, existing pages keep
the old shape. The validator caught exactly this on the live site's cart page:
five `woocommerce/cart-order-summary-*` blocks whose current schema demands a
`cart-order-summary-totals-block` parent that the stored 2024-era markup does
not have. The page still renders (the callbacks tolerate it); the editor will
restructure it on next save. That is schema drift made visible, not a false
positive.

## Verifying a dynamic block

`verify-live.py` cannot assert content it does not control, so it asserts the
contract instead: each pure-dynamic block in the tree must either deliver its
`wp-block-*` wrapper in the public page, or be on record as `empty` in the
sweep - in which case the gap is *explained* and reported as such. A dynamic
block that the sweep says renders, but which is absent from the delivered page,
fails the run.

## "Renders nothing" is not a diagnosis

`sweep-render.php` says whether a block produces output on a bare page. For 205
of 302 blocks here the answer is no, and on its own that verdict is close to
useless: it cannot tell a broken block from one waiting for a post.

`tools/sweep-context.php` renders every block again inside contexts a real page
can supply - cheapest first - and records the FIRST one that yields output.
`gb.py context` accounts for all 302:

```
  101  needs a parent block - standalone is meaningless
   69  renders in: bare
   64  unexplained - needs a context this sweep does not build, or no such data
   23  content-in-HTML - the void form is empty by design
   17  renders in: singular          core/post-title, post-content, post-date, ...
   15  renders in: product           woocommerce/product-price, add-to-cart-form, ...
    9  static wrapper - you write the HTML
    2  renders in: term-archive      core/term-name, core/term-count
    2  renders in: logged-in         moksafopoi/balance, moksafopoi/tier
```

`gb.py block <name>` prints the same verdict per block, so "why is my page
blank" is answerable before publishing rather than after.

### The bug that made the first run worthless

The first version entered a context per block and left it again. It never
actually left: `wp_reset_postdata()` restores `$post` from `$wp_query->post`,
which is exactly the value the enter step had just written. From the first
block that needed a post onwards, every later block's "bare" test ran with a
post still in scope, and `core/post-content` reported 3,849 bytes of "bare"
output - the post's own content.

Contexts are now entered once per PASS, with the globals snapshotted and
written back wholesale. The corrected bare pass produces **69**, which is
exactly what the independent `sweep-render.php` reports - the cross-check that
says the fix is right.

### What "unexplained" mixes

Two different things, both measured rather than assumed:

- a context this sweep does not build - a cart with items, a checkout session,
  an archive with results, `core/tabs`'s own inner context;
- the site simply has no such data. `core/site-tagline` is empty here because
  `blogdescription` is an empty string, and `core/tag-cloud` because the site
  has 0 tags. Neither block is broken, and no context would help.

Re-run the sweep on the target site rather than trusting these numbers: like
everything else in this repo, the answer is a property of that site.
