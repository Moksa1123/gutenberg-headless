# The half the server does not know

`WP_Block_Type_Registry` is the whole truth for attributes and supports, and
almost nothing about everything else. Measured on booking.moksaweb.com (WP 7.1,
302 registered blocks):

| | PHP registry | the editor |
|---|---|---|
| block types | 302 | **280** |
| variations | 3 | **173** |
| transforms | 0 | **168** |
| deprecations | 0 | **192** |

Every number on the right comes from `tools/extract-editor-surface.js`, run in
the block editor of the target site; the result ships as
`data/editor-surface.json` and is queried through `gb.py`, never read whole.

```bash
python tools/gb.py variations                 # which blocks have faces, and how many
python tools/gb.py variations core/group      # Row / Stack / Grid, with their attributes
python tools/gb.py transforms core/paragraph  # what it becomes, what becomes it
python tools/gb.py deprecated                 # the whole list, worst first
python tools/gb.py deprecated core/image      # and what each old form differed in
python tools/gb.py save core/button           # the exact shape save() writes
python tools/gb.py bindings                   # what metadata.bindings may name
python tools/gb.py templates                  # the four things called "template"
python tools/gb.py settings                   # what the editor ALLOWS here
```

## 22 blocks the editor cannot read

The two registries are not the same set. 302 blocks are registered server-side;
280 exist in the editor. The 22 that are not - `woocommerce/breadcrumbs`,
`woocommerce/catalog-sorting`, `core/post-comments` and friends - render
perfectly on the front end and appear in the editor as unrecognised content.
Write one into a page and you have made something that works for visitors and
cannot be edited. `validate-post.py` reports it as **W-EDITOR**.

(The count is a property of the SCREEN, not just the site: on a freshly opened
post editor the registry starts at ~109 and finishes at 280 as the editor
scripts load. Probe after the editor has settled.)

## Deprecations: why "the editor accepted it" is not "it is stable"

192 deprecated forms across 75 blocks. A deprecation is how WordPress accepts
markup that an OLDER version of `save()` would have written - which is exactly
what makes a wrong-but-plausible page look fine right up until someone edits
it. `deprecated core/image` prints what each old form differed in, and flags
the dangerous kind:

```
core/image: 12 deprecated form(s)
  [0] migrate() REWRITES attributes  attrs: id, url, alt, caption
```

`migrate()` means the block does not merely accept the old markup, it rewrites
the attributes on the way in.

## Variations are blocks wearing a different face

Same `blockName`, different preset attributes - and none of it visible
server-side. `core/group` IS Row, Stack and Grid; `core/embed` IS 33 providers;
`core/social-link` IS 48 services. When you write markup you are choosing a
variation whether you know it or not, and `gb.py variations <block>` prints the
attributes that make each one what it is.

## What save() writes, per block

This is the canonical form, and it decides byte-identity:

```
$ python tools/gb.py save core/button
[0] <div>  <- className lands here
    attribute order: class style
    class order    : wp-block-button ZZPROBECLS
    inline CSS     : min-height
[1] <a>
    attribute order: class href title style target rel
    class order    : wp-block-button__link has-text-color has-background ...
    inline CSS     : border-color border-style border-width border-radius color ...
bindable (role:content): url, title, text, linkTarget, rel
```

Three things that cost real time to learn the hard way are in that output:

- **`className` lands on element 0**, the wrapper. A design-layer class written
  onto the `<a>` is markup `save()` would never produce - the server stores it,
  the page renders correctly, and the editor marks the block invalid.
- **Attribute order inside the tag counts.** `class` before `href`. Writing the
  href first is valid, renders identically, and still gets rewritten.
- **The inline CSS order is a flat property order**, not an order over the
  style object's groups.

### The order is not always a fixed list

`core/separator` emits `has-text-color has-alpha-channel-opacity` when a
background is set and the reverse when it is not. So the extractor probes each
block nine ways (full / colours / text-only / typography / border / spacing /
dimensions / presets / alignment) and ships all of them; `validate-post.py` keeps only the pairs whose order never flips
and reports a violation of those as **W-ORDER**.

Treating a single probe as THE order produced four false positives on a page the
editor itself had confirmed byte-identical - which is worse than no check.

## The converter reads this file instead of a table

`el2blocks.py` used to carry four hand-written ordering tables, derived by
reading the editor's output for FOUR blocks. They were wrong twice - about
where `className` sits in the class list, and about the inline CSS order being
an order over style *groups* rather than over CSS properties. Both cost a
round of "the page looks right and the editor rewrites it".

It now derives all of it from `data/editor-surface.json`:

| what | from |
|---|---|
| inline CSS declaration order | the probes' `css` lists |
| class order | the probes' `classes` lists |
| where `className` goes | the position of the probe's placeholder class |
| which element carries the style | the element with the most declarations |
| `class` before `href` in the tag | the element's recorded attribute order |

Two things make that work on real markup rather than only on the probe's:

- **Only stable pairs reorder anything.** The probes are intersected into
  pairwise constraints; a pair whose order ever flips constrains nothing and
  the converter's own order survives. Without this, every separator on a page
  with a coloured-but-not-backgrounded rule was rewritten.
- **A class the probe never produced stands in for its family.** The probe
  records `has-text-align-left`; a page uses `right`. Same slot.

The acceptance test is the strongest one available: the data-driven converter
produces output **byte-identical** to the hand-tabled version on a 180-block
page, and that page's round-trip through the editor is byte-identical too.

One table stays hand-written on purpose: the order of the keys **inside the
style object** in the comment JSON. The editor reserializes that object exactly
as it parsed it, so any self-consistent order round-trips - which the identical
round-trip on that page demonstrates. It is not measurable from `save()`,
because it never reaches the saved HTML.

## Deprecated forms are detectable

Each deprecation's `save()` is probed too, so the shape it wrote is on record.
Eight of the 192 change the wrapper TAG, and each is a real trap for
hand-written markup:

| block | old | current |
|---|---|---|
| core/button | `<a>` | `<div>` wrapping one |
| core/pullquote | `<blockquote>` | `<figure>` |
| core/cover | `<section>` | `<div>` |
| core/gallery | `<ul>` / `<div>` | `<figure>` |
| core/math | `<math>` | `<div>` |

`validate-post.py` reports **W-DEPRECATED** when the wrapper tag matches an old
form instead of the current one. The check is deliberately limited to the tag,
which is unambiguous - a class list is not, and a false positive here would be
worse than no check.

```
W-DEPRECATED core/button  <a> is deprecated form #8 of this block; the current
             save() writes <div>. WordPress accepts it and migrate() REWRITES
             the attributes - the next edit rewrites the block
```

## What the site allows: `gb.py settings`

```
insertable  : every registered block
custom values: allowed for colors, font sizes, gradients, spacing
controls    : enableCustomLineHeight, enableCustomSpacing   units: px, em, rem, %, vh, vw
```

None of this constrains the MARKUP - a page can carry an inline line-height on
a theme that switches the control off, and it renders. What it decides is
whether a human can change the value afterwards.

Note the two layers disagree on purpose: `theme_supports('custom-line-height')`
is **off** on this site while the resolved `enableCustomLineHeight` is **on**,
because global settings can enable what the theme never declared. The resolved
editor settings are the answer; theme_supports is one of its inputs, and the
only one a classic theme writes.

`gb.py settings` also lists what the theme already styles per block - 11 of
them here - which is why a block can look styled before you write anything, and
why a value you did write can look ignored.

## Templates: four different things

```
$ python tools/gb.py templates
theme            : CLASSIC theme
wp_template      : 0   (not available - classic themes have no Site Editor templates)
synced patterns  : 0   (wp_block post type - edit once, changes everywhere)
registered patterns: 86   (inserted as a COPY, then independent)
post-type templates: 0   (a starting block structure for new posts; works on any theme)
pattern overrides: available
```

- **Pattern** - inserted as a copy; edits are local. The reusable *layout*.
- **Synced pattern** (`wp_block`) - one source of truth; edits propagate.
- **Pattern overrides** - a synced pattern with per-instance editable slots,
  bound through `metadata.bindings` to attributes marked `role: content`
  (`gb.py save <block>` prints which those are).
- **`wp_template` / template parts** - the Site Editor's whole-page templates.
  **Block themes only.** On a classic theme they do not exist, and the page
  frame stays the theme's PHP.

Independent of all four: a post type's own `template` argument plus
`template_lock` (`all` / `insert` / `contentOnly`) gives every new post of that
type a starting block structure, on any theme.

## Re-extracting

```bash
# server side
wp eval-file tools/extract-block-schema.php > data/block-schema.json
python tools/build-indexes.py data/block-schema.json --out data/

# editor side - run in the block editor of the same site, as an admin
#   tools/extract-editor-surface.js  ->  data/editor-surface.json
```

Both must come from the SAME site: the two files are joined by block name, and
mixing sites silently produces a schema that describes neither.

## Checking the model against WordPress itself

Every other check here asks whether a page agrees with the model.
`tools/selftest-patterns.py` asks the opposite: whether the MODEL agrees with
WordPress. The 86 registered patterns are serialized block markup written by
core, WooCommerce and the theme, which makes them the largest corpus of
canonical markup the target site has.

It is run in `--pattern` mode, and that distinction is itself a measured fact:
a pattern is parsed and re-serialized before it becomes page content, so its
HTML is only a parsing vehicle. A group whose comment declares padding and
whose HTML has no style attribute parses as **valid** and reserializes **with**
`style="padding-top:100px"`. The same markup stored as post_content is a real
defect - the front end renders the stored HTML verbatim, and nobody sees the
padding until someone opens and saves the post.

**Two validator bugs it found**, both fixed:

- `"dimensions":{"minHeight":""}` - an explicitly empty value means "not set"
  and the editor emits nothing for it. The validator was demanding
  `min-height:` with no value.
- A sourced attribute duplicated in the comment was reported as an ERROR.
  Core's own patterns do it 22 times: `core/button`'s `url` alongside the
  `<a href>`. When the HTML carries the same value it is redundant, not
  broken - now W-SOURCED, and an error only when the value is absent from the
  markup and therefore genuinely lost.

**Four things that are simply true of core's own content** (57 of 86 patterns
are completely clean; these are the rest):

- **30 preset slugs that do not exist here.** Patterns ship assuming their own
  theme's palette - `fontFamily:'inter'`, `fontSize:'extra-small'` - and on a
  classic-theme site those classes style nothing. Patterns are site-dependent
  exactly like everything else in this repo.
- **29 attributes belonging to a DEPRECATED form.** `core/query`'s
  `displayLayout` is declared by deprecations #1-#4 and by no current
  attribute; `core/separator`'s `customColor` by deprecation #0. WordPress
  ships patterns written against old block forms.
- **22 redundant sourced copies.**
- **5 duplicate anchors** inside a single pattern - two elements with `#300`.

The clearest single example of the central trap is core's own spacer pattern.
It writes `{"height":200}` where the current attribute is a string. Parsing it
in the editor gives `"200px"`, not `200` and not `"200"` - because the markup
matches `core/spacer`'s one deprecation, whose `migrate()` rewrote the value on
read. `wp.blocks.serialize` then emits `{"height":"200px"}`. Accepted today,
rewritten on the next save, with nothing anywhere reporting it.
