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
block six ways (full / colours / text-only / typography / border / spacing) and
ships all six; `validate-post.py` keeps only the pairs whose order never flips
and reports a violation of those as **W-ORDER**.

Treating a single probe as THE order produced four false positives on a page the
editor itself had confirmed byte-identical - which is worse than no check.

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
