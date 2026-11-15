---
name: "gutenberg-headless"
description: |
  Build and modify WordPress block-editor (Gutenberg) pages by writing the serialized block markup directly - no editor, no browser. Query the full block surface of the target site (302 block types, every attribute, support and preset) instead of guessing, with every block's bare-page render behaviour measured by an actual do_blocks() sweep, and validate that the comment JSON and the saved HTML - the two halves WordPress never checks against each other - actually agree. 中文觸發：區塊編輯器、古騰堡、Gutenberg 頁面、不開編輯器做頁面、post_content、區塊標記、按鈕、欄、群組、封面、商品格線、WooCommerce 區塊頁面、結帳頁、區塊無效／嘗試復原、區塊版面配置（pattern）、Elementor 轉區塊。
license: "MIT"
author: "moksa (https://moksaweb.com)"
version: "1.11.1"
user-invocable: true
---

# Headless Gutenberg

Build block-editor pages by writing `post_content` directly. The editor is one
client of that format; it is not the format, and you do not need it.

**A block is two halves that WordPress never checks against each other.** The
comment JSON is what the *editor* reads; the saved HTML is what the *visitor*
gets. Write `"backgroundColor":"accent"` in the comment and skip the
`has-accent-background-color` class in the HTML, and the front end shows no
background, the editor shows one, and nobody shows an error. Every mistake in
this format is that mistake in some costume: value in the wrong half, class
missing from one half, slug that exists in neither.

## Sources

| | |
|---|---|
| Surface | Extracted from the live registry of booking.moksaweb.com: **WP 7.1, Blocksy 2.1.53, extracted 2026-08-28** (`extract-block-schema.php`). WooCommerce's version was not recorded by that extraction - `data/pending.csv` |
| Size | 302 block types (116 `core/*`, 165 `woocommerce/*`, 13 `blocksy/*`, plus wpforms and moksa plugins), 86 registered patterns. Current counts: `python tools/gb.py stats` - do not quote numbers from memory |
| Render proof | every block rendered through `do_blocks()` on a bare page, 0 errors: 69 render, 205 render NOTHING (need context), 28 are content blocks (`data/render-verification.csv`) |
| Editor surface | read IN the editor (`extract-editor-surface.js`): 280 block types, 173 variations, 168 transforms, 192 deprecated forms the PHP registry cannot see; 22 registered blocks are absent from the post editor |
| Parser proof | `blockmark.py` round-tripped over every block post on the site - 19 posts, 111 KB (`data/roundtrip-verification.csv`, re-measured 2026-11-15 on the site as it is now, whose versions the file records - newer than the extraction); every divergence is the documented escape class (W-ESCAPE) |
| Provenance | every row of the main CSVs carries `measured_on` + `trust`; `terms-zh.csv` carries `source` + `trust` |
| Trust levels | `measured` (實測: read off the live site or rendered) > `documented` (official source, e.g. WordPress / WooCommerce zh_TW on translate.wordpress.org) > `inferred` / `house-style` (never present these as WordPress's rules) |
| Last checked | 2026-11-15: self-test and SKILL.md number check pass; open gaps in `data/pending.csv` |

## Usage

**Use it for:** making a page of blocks exist, look right, and survive both the
front end and the editor; changing an existing block page; answering "does this
block exist here / what is the attribute called / what HTML does save() write /
why does it render nothing".

**Do not use it for:**

| Request | Go to |
|---|---|
| Elementor pages (`_elementor_data`) | `elementor-headless` |
| Mosaic Pro (Nextend) sites | `mosaic-headless` |
| Writing SEO articles / Rank Math scores (FAQ/HowTo blocks in an article) | `rankmath-seo-wp` |
| Publishing moksaweb.com articles | `moksa-wp-publish` |
| Packaging a plugin for wordpress.org | `wporg-plugin-submit` |
| Site health, plugin audits, theme building | out of scope - say so |

**The front door is `tools/gb.py`.** Every answer starts with a lookup there.
Add `--json` after the subcommand. **Never read `data/block-schema.json` or
`data/editor-surface.json` into context** - they are the database; `gb.py` is
the query. `data/*.csv` are for grep.

| User-run tools (stdlib only) | Does |
|---|---|
| `gb.py` | query the schema - **the front door** |
| `validate-post.py` | pre-flight both halves of every block; exit 1 on any error |
| `apply-post.php` | `wp eval-file`: write past kses/slashing, byte-verify the stored row, purge caches |
| `verify-live.py` | assert the page the PUBLIC receives, through every cache; exit 1 on FAIL |
| `blockmark.py` | parse/serialize block markup, round-trip-faithful (also a library) |
| `el2blocks.py` | Elementor tree → block markup, driven by elementor-headless's measured CSS table |
| `audit-contrast.js`, `check-rwd.js`, `rwd-scan.js`, `collect-states.js`, `collect-fingerprint.js` + `diff-fingerprints.py`, `audit-coverage.py` | in-page design checks: contrast, RWD overflow, hover/focus states, element-by-element diff against an original |
| `test_gutenberg.py` | self-test (offline) |

| Maintainer tools | Does | Extra dependency |
|---|---|---|
| `extract-block-schema.php`, `sweep-render.php`, `sweep-context.php`, `extract-patterns.php` | dump a live site's block surface, render sweep, contexts, patterns | WP-CLI on a test site |
| `extract-editor-surface.js` | variations, transforms, deprecations, save() shapes - run IN the editor | a logged-in editor |
| `build-indexes.py`, `provenance.py` | dump → `data/`, stamp `measured_on` / `trust` | - |
| `export-block-posts.php` + `roundtrip-check.py` | re-measure the parser over a site's stored posts | WP-CLI |
| `selftest-patterns.py` | validator rules vs markup WordPress itself wrote | - |
| `check_numbers.py` | every number in this file vs the data | - |
| `benchmark-tokens.py` | reproduce the token numbers | `tiktoken` |
| `install-skill.py`, `bin/install.mjs` | install into other agent platforms | Node for the `.mjs` |

Two dependency layers: the user path (query, validate, verify, test) is Python
standard library only. `tiktoken` is used by `benchmark-tokens.py` alone and is
listed in `requirements.txt`; the JS tools run inside a browser page.

## Routing

**Iron rule: look it up first, never answer from memory. Not in the data → say so, mark it 待補 (pending), record it in `data/pending.csv`, and do not guess.**
Never write an attribute name, a preset slug, a wrapper class or a "this block
exists" claim from memory. Look it up, then validate both halves.

Chinese and colloquial terms work directly: `data/terms-zh.csv` expands them to
the English names (`按鈕` → button, `邊框間距` / `內距` → padding, `商品格線` →
product-collection), and block titles are the site's own zh_TW strings. When a
Chinese query finds nothing, `gb.py` names the words it could not map.

| The user says | Data | Command |
|---|---|---|
| 「有沒有按鈕／封面／群組區塊」 | registered blocks | `gb.py blocks --grep 按鈕` |
| 「商品格線」「商品價格」「購物車／結帳區塊」 | WooCommerce blocks | `gb.py blocks --grep 商品格線` · `gb.py blocks --namespace woocommerce --grep price` |
| 「欄怎麼排」「多重欄位」 | one block: family, attrs, supports, sweep verdict | `gb.py block core/columns` |
| 「背景色／文字色彩要寫在哪」 | that block's attributes | `gb.py block core/group --grep 背景色` |
| 「這區塊能設內距／邊界嗎」 | flattened supports | `gb.py supports core/group` |
| 「色票／字級／間距有哪些」 | the site's presets | `gb.py presets color` · `gb.py presets font-size` · `gb.py presets spacing` |
| 「外框按鈕」「樣式變化」 | `is-style-*` | `gb.py styles core/button` |
| 「有現成的版型嗎」 | registered patterns | `gb.py patterns --grep hero` · `gb.py patterns --show <name>` |
| 「存檔後 HTML 長什麼樣」「為什麼編輯器說無效」 | the exact shape save() writes | `gb.py save core/button` · `gb.py deprecated core/image` |
| 「為什麼前台一片空白」「動態區塊要什麼才會顯示」 | render sweep + contexts | `gb.py block woocommerce/product-price` → `render-sweep:` · `gb.py context` |
| 「X 裡面可以放什麼」「子區塊」 | the `parent:` / `ancestor:` flag on every block | `gb.py blocks --grep tab` (children of `core/tabs` carry `parent:core/tabs`) |
| 「解析器可靠嗎」「存回去會不會變」 | recorded round-trip | `data/roundtrip-verification.csv` · [canonicalization.md](references/canonicalization.md) |
| 「手機版／平板斷點」 | every responsive mechanism, real widths | `gb.py rwd` · [responsive.md](references/responsive.md) |
| 「資料列／直行排列／格狀」 | editor variations | `gb.py variations core/group` |
| 「段落可以轉成什麼」 | transforms | `gb.py transforms core/paragraph` |
| 「綁定自訂欄位」 | block bindings sources | `gb.py bindings` |
| 「範本／範本組件／頁尾」 | Site Editor surface | `gb.py templates` |
| 「編輯器允許什麼」「主題已經設好的樣式」 | editor settings | `gb.py settings` |
| 「懸停效果」「自訂 CSS」「fitText」 | WP 7.0/7.1 surface | [wp71-new-surface.md](references/wp71-new-surface.md) · [custom-css-js.md](references/custom-css-js.md) |
| 「給我一個起手頁」「語法」 | skeleton / grammar | `gb.py skeleton` · `gb.py grammar` |
| 「這站跟資料一樣嗎」 | what site the data describes | `gb.py stats` |
| a word that matches nothing | - | retry in English; still nothing → `data/pending.csv` |

`--grep` is a plain substring match (not a regex), Chinese expanded. `gb.py context`
splits the same bare-page sweep by cause (needs a parent, renders in a product,
static wrapper...): a finer view of the render/empty/content verdicts, not a
different measurement.

## Tasks

| Task | Steps | Done when (evidence) |
|---|---|---|
| **Build a new page** | `gb.py skeleton > page.html` → look up every block, attr and slug as you write → `validate-post.py page.html` → `wp eval-file tools/apply-post.php new page.html "Title" page publish` → `verify-live.py page.html <url>` → editor check (below) | validate `0 errors`; apply-post logs `round-trip: stored content is byte-identical to the file`; verify-live `PASS`; editor: no invalid blocks and serialize === stored |
| **Change an existing page** | `wp post get <id> --field=post_content > page.html` → `validate-post.py` the untouched file first (pre-existing problems are not yours) → edit → validate → `apply-post.php <id> page.html` → verify-live | same evidence as a new page, on the same post id |
| **Start from a pattern** | `gb.py patterns --grep <word>` → `gb.py patterns --show <name> > part.html` (canonical markup WordPress wrote for THIS site) → adapt → validate | validate `0 errors` on the adapted markup |
| **WooCommerce page** | `gb.py blocks --namespace woocommerce --grep <x>` → `gb.py block <name>` for its render verdict and `uses_context` → `gb.py context` → [woo-onepage.md](references/woo-onepage.md) for the single-product family and the `is_checkout()` trap | verify-live `PASS`, the Woo blocks render non-empty on the page (they need a product/cart context), and for checkout a real Store-API order |
| **Elementor page → blocks** | `el2blocks.py page.json --el-skill <elementor-headless dir> > page.html` → validate → apply → `collect-fingerprint.js` on both pages → `diff-fingerprints.py` ([elementor-migration.md](references/elementor-migration.md)) | validate `0 errors`, editor check passes, the fingerprint diff lists no unexplained difference, side-by-side screenshots match |
| **Design / RWD check** | `gb.py rwd` before any breakpoint → `check-rwd.js` / `rwd-scan.js` across the width range → `audit-contrast.js` | no overflow band, no contrast failure, at every width the site really uses |
| **Answer a question** | the matching `gb.py` command from `## Routing` | the answer quotes the command output; nothing found → said so and recorded in `data/pending.csv` |

**The surface is a property of the SITE.** Name a block the target site does
not register and the front end prints your raw HTML while the editor demands
recovery - no warning at write time (`E-BLOCK` at validate time). A different
site needs its own extraction (`## Maintenance`).

**Three families, three writing modes.** `is_dynamic` is misleading (272/302
carry a render callback - even `core/heading`). `gb.py block <name>` prints the
family on line two:

| family | count | you write |
|---|---|---|
| CONTENT-IN-HTML (has sourced attrs) | 28 | comment + the full saved HTML; sourced attrs (`content`, `citation`, `url`...) live ONLY in the HTML - `E-SOURCED` if you put them in the comment |
| STATIC WRAPPER | 14 | comment + wrapper HTML (`group`, `columns`, `spacer`...) |
| PURE DYNAMIC | 260 | a void comment `<!-- wp:x {...} /-->`; attrs are everything |

205 of 302 blocks render NOTHING on a bare page - they need a product, a post,
a cart, a query loop. `gb.py block <name>` prints `render-sweep:` and
`uses_context`, so you find out before writing, not after publishing an
invisible page.

**Two serialization moments.** Save-time is yours: preset attrs → `has-*`
classes, style object → inline CSS with `var:preset|kind|slug` expanded to
`var(--wp--preset--kind--slug)`, `className`/`anchor`/`align` into the markup
([supports-and-styles.md](references/supports-and-styles.md)). Render-time is
the server's: `layout`, `style.elements`, duotone become `wp-container-*` /
`wp-elements-*` / `wp-duotone-*` classes while serving. Rule of thumb: `has-*`
yourself, `wp-container-*` never. A preset slug must exist on the target site or
its class styles nothing, silently (`E-PRESET`).

**Write the canonical current form.** A deprecated form stays valid while the
next manual save silently rewrites it (measured: `"textAlign":"center"` →
`"style":{"typography":{"textAlign":"center"}}`, defaults like `"level":2`
dropped). `examples/demo-page.html` (21 blocks) passes every check below - it is
the file to imitate ([canonicalization.md](references/canonicalization.md)).

| Reference | What's in it |
|---|---|
| [data-model.md](references/data-model.md) | the grammar, where each attr lives, editor validation/migration, kses+slash, `{}`→`[]`, caches |
| [supports-and-styles.md](references/supports-and-styles.md) | every save-time class formula, the style object, preset vars, render-time injections |
| [dynamic-blocks.md](references/dynamic-blocks.md) | the pure-dynamic blocks, the bare-page sweep, context, WooCommerce hydration skeletons |
| [editor-surface.md](references/editor-surface.md) | what only the editor knows: variations, transforms, deprecations, save() shapes |
| [extraction-traps.md](references/extraction-traps.md) | the ways the schema can lie and how each is compensated; describing another theme without switching |
| [wp71-new-surface.md](references/wp71-new-surface.md) | 7.0/7.1, measured: `:hover`/`@mobile` states, `blockVisibility`, `style.css`, `fitText`, tabs/accordion |
| [canonicalization.md](references/canonicalization.md) | byte-identical rules and the console loop that converges any page |
| [responsive.md](references/responsive.md) | every breakpoint mechanism and its real width |
| [custom-css-js.md](references/custom-css-js.md) | per-block CSS, the design/behaviour layer pattern |
| [fidelity.md](references/fidelity.md) | a designed HTML/CSS/JS/SVG page rebuilt as blocks to parity |
| [woo-onepage.md](references/woo-onepage.md) | one-page WooCommerce checkout that placed a real order |
| [elementor-migration.md](references/elementor-migration.md) | converting Elementor pages, and how to prove the result matches |

## Verify

Every output has a gate. Run it; do not report success without it.

| Output | Validator | Pass when |
|---|---|---|
| any block markup | `python tools/validate-post.py page.html` | `0 errors`, exit 0. Catches unregistered blocks, unknown/mistyped attrs, enum violations, sourced attrs in the comment, missing preset slugs, every class and inline rule the comment promises but the HTML lacks, parent/ancestor violations, empty content blocks |
| the stored row | `wp eval-file tools/apply-post.php <id\|new> page.html` | logs `round-trip: stored content is byte-identical to the file` (it warns otherwise) and purges the object cache + Breeze |
| the published page | `python tools/verify-live.py page.html https://<site>/<slug>/` | `PASS`, exit 0 - every text fragment, class, inline rule and preset var asserted against the delivered bytes |
| the editor | in wp-admin's console: `wp.data.select('core/block-editor').getBlocks().filter(b => !b.isValid)` | `[]`, and `wp.blocks.serialize(...getBlocks()) === wp.data.select('core/editor').getCurrentPost().content` is `true` |
| this skill | `python tools/test_gutenberg.py` | all pass (offline; `--live <url>` also verifies the demo page) |

## Maintenance

For maintainers.

- **Re-extract** for another site or after an upgrade:
  `wp eval-file tools/extract-block-schema.php > dump.json`,
  `wp eval-file tools/sweep-render.php > render-sweep.json`, then
  `python tools/build-indexes.py dump.json --out data/ --render-sweep render-sweep.json`
  (stamps `measured_on` / `trust` through `provenance.py`); re-run
  `extract-editor-surface.js` in the editor. Pass a theme slug to the extractor
  to describe an installed, inactive theme ([extraction-traps.md](references/extraction-traps.md)).
  `data/` is generated - never hand-edit it.
- **After any data change**: `python tools/check_numbers.py --fix`, then
  `python tools/check_numbers.py` (every number in this file is whitelisted and
  checked against the data), `python tools/test_gutenberg.py`,
  `python tools/selftest-patterns.py`, re-verify the demo page with
  `verify-live.py`, and re-run the evals (`evals/grade.py`, results in
  `evals/RESULTS.md`).
- **Parser**: `export-block-posts.php` + `roundtrip-check.py --out data/roundtrip-verification.csv`; exit 1 means a divergence outside the escape class.
- **Release** (`RELEASING.md`, `.github/workflows/publish.yml`): the example pages
  validate, the installer smoke test passes. The installer rebuilds this file's
  frontmatter from `assets/templates/platforms/*.json`; the self-test keeps
  them in step.
- **Pending gaps** live in `data/pending.csv`; close a row only with a measured
  or documented source.
