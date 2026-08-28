# The fidelity experiment: hand-written HTML/CSS/JS/SVG vs blocks

A deliberately designed static page - gradient hero with an absolutely-
positioned SVG blob, hover-lifting card grid, black stats band, tabbed panel,
FAQ accordion, pill CTA with hover, responsive breakpoints - was written as
one hand-authored file (`examples/fidelity-target.html`, served at
`/fidelity-target.html` on the test site), then reproduced as a 48-block tree
(`examples/fidelity-blocks.html`, post 4404) that holds the full bar:
validator 0 errors, verify-live PASS (141 assertions), editor 48/48 isValid,
resave byte-identical. Side-by-side screenshots confirm visual parity.

## What mapped, and how

| design feature | mechanism | native? |
|---|---|---|
| full-bleed gradient hero | group `align:full` + custom `style.color.gradient` | native |
| absolutely-positioned SVG blob | core/html block + parent group `style.css` (`& .gb-blob{position:absolute;...}`) | custom CSS |
| responsive h1 (3rem → 1.8rem) | `style["@mobile"].typography.fontSize` (7.1 states) | native |
| pill CTA + hover color swap | button `border.radius:999px` + `style[":hover"]` (button is in the pseudo allowlist) | native |
| CTA hover shadow + transition | button `style.css` (states emit no `transition`) | custom CSS |
| responsive 3-col card grid | group `layout:{type:"grid",minimumColumnWidth:"20rem"}` (server generates the media-free auto-fill CSS) | native |
| card hover lift (translateY + shadow) | group `style.css` `&:hover{...}` - group is NOT in the pseudo allowlist, so states cannot do this | custom CSS |
| stats flex band + responsive gap | `layout:flex` + `blockGap` + `@mobile` blockGap override | native |
| tabs with active-tab styling | core/tabs family; active-state styling via parent `style.css` `& button[aria-selected=true]{...}` | native + custom CSS |
| FAQ accordion, first item open | core/accordion, `openByDefault` + `is-open` class | native |
| centered content widths on a blank canvas | `style.css` max-width (the theme's `--theme-block-max-width` var is absent on Elementor Canvas, so constrained layout has nothing to resolve) | custom CSS |
| SVG icons | core/html blocks (kses off via apply-post) | native-ish |

Theme chrome (header/footer/title) was removed with the page template
`elementor_canvas` (`_wp_page_template` meta) - blocks cannot do that part;
it is a template decision.

## What blocks cannot reproduce

- **Arbitrary JavaScript.** The target's tab/accordion JS mapped to core
  interactive blocks - that is the whole extent of it. Behaviour outside what
  a registered block ships (counters, custom listeners, scroll effects) has no
  authoring surface; the Interactivity API is developer infrastructure, not
  a content field. Escape hatch: none in core (a script in core/html is
  stripped for non-unfiltered_html editors and is off-model anyway).
- **Pseudo-states on arbitrary blocks** via the style attribute - allowlisted
  to button/navigation-link. `style.css` `&:hover` covers the gap and is what
  the card lift uses.
- **transition/transform/animation** have no style-attribute surface at all -
  always `style.css`.

## Verdict

Everything visual in a designed landing page reproduced 1:1; roughly a third
of the polish (positioning tricks, hover physics, width constraints on a bare
canvas) rides on per-block `style.css` rather than first-class attributes -
which still round-trips the editor cleanly and stays scoped to the block.
Interactive behaviour reproduces exactly when it matches a core interactive
block (tabs, accordion, details, lightbox, fitText) and not at all otherwise.
