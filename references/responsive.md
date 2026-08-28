# Responsive, in the block editor

`python tools/gb.py rwd` prints all of this for the target site. Read that
before writing a breakpoint, because the numbers disagree and nothing in the
editor says so.

## Four different widths all called "mobile"

Measured on booking.moksaweb.com (WP 7.1, Blocksy):

| mechanism | where the number comes from | this site |
|---|---|---|
| `style["@mobile"]` (WP 7.1 block state) | theme.json `settings.viewport` | `width <= 689.98px` |
| `core/columns` `isStackedOnMobile` | hardcoded in the block's own CSS | `max-width: 781px` |
| `core/media-text` `isStackedOnMobile` | hardcoded in the block's own CSS | `max-width: 600px` |
| what `el2blocks.py` emits | Elementor's breakpoints | `max-width: 767px` |

Two core blocks share an attribute *name* and stack **181px apart**. A page
that uses `isStackedOnMobile` on both, and a `@mobile` state as well, has three
reflow points between 600px and 782px.

Nine core blocks ship their own media query; `gb.py rwd` lists them.
theme.json decides nothing about any of them.

## `@tablet` is a RANGE

Read from `WP_Theme_JSON::get_viewport_media_queries()`:

```
@mobile  -> @media (width <= 689.98px)
@tablet  -> @media (689.98px < width <= 999.98px)
@desktop -> @media (width > 999.98px)
```

`@tablet` is bounded at BOTH ends. A value set there does not cascade down to
phones the way a `max-width` query would - which is the opposite of how
Elementor's `_tablet` suffix behaves, and the reason the converter does not map
one onto the other.

## Why the converter emits its own media queries

`el2blocks.py` compiles Elementor's `_tablet` / `_mobile` control variants into
media queries in the design layer rather than into `style["@mobile"]`. Three
measured reasons:

1. **The widths differ.** `@mobile` here is 689.98px; Elementor's is 767px.
   Mapping one to the other moves every responsive value by 77px.
2. **`@tablet` is a range**, Elementor's `_tablet` is a max-width.
3. **A block state carries only what the style engine can express**, and
   Elementor pages set things it has no path for. The design layer takes all of
   them, and RUCSS cannot strip it.

## Fluid typography rewrites what you wrote

`settings.typography.fluid` is `true` here. Every `font-size` in a style object
is rewritten at render into `clamp(min, formula, max)`. Measured: a 56px
heading resolves to **44.6px** at 1440px - a 20% shrink across the whole type
scale, with the stored markup still saying 56px.

`verify-live.py` matches `font-size:clamp\(...\)` for this reason, and the
converter restates every font-size in the design layer to pin it back.

## `layout: constrained` may constrain nothing

`wp_get_global_settings()['layout']` here says:

```json
{"contentSize": "var(--theme-block-max-width)", "wideSize": "var(--theme-block-wide-max-width)"}
```

Both are CSS variables, and **neither is defined on the front end** - checked
with `getComputedStyle(document.documentElement)` on a live page:
`--wp--style--global--content-size` and `--theme-block-max-width` both come back
empty. So a `layout:{"type":"constrained"}` group has nothing to resolve
against and fills its parent.

That is why the converter writes an explicit `max-width` into the design layer
instead of relying on `constrained`. The earlier note in this repo said a
classic theme "never defines" contentSize; the truer version is that this one
declares it and points at a variable nobody emits.

## What actually reflows, per block

`gb.py rwd` section 3 lists every block with a responsive attribute - on this
site six of them, of which only `core/columns`, `core/media-text`,
`core/navigation` (`overlayMenu`) and `core/embed` (`responsive`) are core.

Everything else reflows through `layout` (35 blocks support it): a flex layout
with `flexWrap: "wrap"`, or a grid with `minimumColumnWidth`, which reflows
continuously and needs no breakpoint at all. That is usually the better answer
than a breakpoint - a grid whose columns are `minmax(16rem, 1fr)` has no
"mobile" to disagree about.

## Verifying it

`tools/check-rwd.js` audits a rendered page at any width. The trap it exists
for: `body { overflow-x: hidden }` clips overflow instead of preventing it, so
`scrollWidth > innerWidth` reports clean while content is cut off. It compares
each element's box against the viewport and reports the clip separately from
the verdict.

Run it at every width you claim to support, on the original and the new page
both - see references/elementor-migration.md for what that found.

## Sampling widths is not testing responsiveness

`check-rwd.js` audits one width thoroughly. Seven of them - 390, 430, 768, 820,
1024, 1366, 1440 - all reported PASS on the converted page.

A continuous sweep of 320-1600px then found an overflow band at **1040-1152px**
that none of those seven touches. Sampling cannot find what it does not sample,
and a layout that passes at 1024 and 1366 says nothing about 1100.

`tools/rwd-scan.js` returns a cheap per-width signature; the driver sweeps the
range, notices where the signature changes, and binary-searches each change to
the pixel. On the reference page that gives 25 reflow points, two of which are
the declared breakpoints:

```
   768px   height 5593 -> 5468      Elementor's mobile breakpoint
  1025px   height 5277 -> 4123      Elementor's tablet breakpoint
```

The rest are text rewrapping. A reflow at a width nobody declared is worth a
look; a reflow at a declared one is the design working.

### The signature has to ignore mere resizing

The first version hashed rounded box geometry and reported a reflow at **80 of
81 samples** - correctly, in a sense: a fluid layout's geometry changes
continuously. It was useless.

What separates a reflow from a resize is that elements change their
ARRANGEMENT. The signature now records, per container, the layout mode
(`display`, `flex-direction`, `flex-wrap`, grid column count) and **how many
rows its children occupy**. Both are invariant while a layout merely shrinks,
and both change the moment something wraps.

### Content and chrome are different problems

Overflow is counted per region, because mixing them makes a conversion audit
useless. On the reference site the widest offender between 1040 and 1296px is
the theme-builder HEADER: a nowrap flex row with a hardcoded `width: 1300px`,
overflowing by exactly `(1300 - viewport) / 2` on **every page of the site**,
converted or not. Attributing that to the page under test would have been
wrong, and "fixing" it in the converter would have been worse.

## An auto margin outranks the parent's alignment - and then gives up

The sweep found a real conversion defect the seven-width audit could not: in the
1040-1168px band the converted page overflowed **142px to one side** where the
original overflowed **52px to each**.

The cause is a CSS rule worth knowing. The converter centred a fixed-width
content well with `margin-left:auto; margin-right:auto`. In flexbox an auto
margin **outranks `align-items`**, and it only distributes POSITIVE free space -
so on a viewport narrower than the well it resolves to 0 and pins the box to the
start, while also suppressing the centring the parent was already doing.

Measured at 1040px on a 1160px well:

| | left | overflow |
|---|---|---|
| with auto margins | 22 | +142px, one side |
| without | -68 | +52px, each side |
| the Elementor original | -68 | +52px, each side |

Every container this converter emits is a flex container, so the parent's
`align-items` is always there to do the centring. The auto margins are gone.
