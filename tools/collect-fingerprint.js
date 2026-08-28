// Collect a style fingerprint of a rendered page, for tools/diff-fingerprints.py.
//
// Run the exported function in BOTH pages at the SAME viewport width, save the
// two results, then diff them. It is the only honest way to answer "does the
// converted page look like the original" - screenshots hide small systematic
// errors and checkpoints only find what you thought to check.
//
//   Playwright:  await page.setViewportSize({width:1440, height:900})
//                await page.evaluate(<this function>)   // both pages
//   then:        python tools/diff-fingerprints.py orig.json conv.json
//
// Two traps, both hit for real while building the Elementor converter:
//   1. Set the viewport EXPLICITLY on both pages. A default window can be
//      narrow enough to trip the responsive breakpoint and you end up diffing
//      a desktop layout against a mobile one.
//   2. Elementor wraps text in <span>; blocks put it on <h2>/<p> directly. Most
//      pairs will differ in `tag` - the diff tool compares those as boxes.
() => {
  const PROPS = [
    'fontSize','fontWeight','lineHeight','letterSpacing','fontFamily',
    'textAlign','color','backgroundColor','backgroundImage','textTransform',
    'paddingTop','paddingRight','paddingBottom','paddingLeft',
    'marginTop','marginRight','marginBottom','marginLeft',
    'borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth',
    'borderTopColor','borderRadius','boxShadow',
    'display','flexDirection','flexWrap','justifyContent','alignItems',
    'rowGap','columnGap','maxWidth','minHeight','opacity','position','overflow'
  ];
  const out = [], seen = new Map();
  const scope = document.querySelectorAll('main *, .site-main *, article *, .elementor *');
  for (const el of scope) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;

    const own = [...el.childNodes]
      .filter(n => n.nodeType === 3 && n.textContent.trim())
      .map(n => n.textContent.trim()).join(' ');

    // Key by text where there is text; otherwise by a BOX signature. A border
    // or background on a text-less container is invisible to a text-only
    // fingerprint - which is exactly how six 1px dividers rendered as full
    // 2.4px boxes and went unreported.
    const borderPx = parseFloat(cs.borderTopWidth) + parseFloat(cs.borderRightWidth)
                   + parseFloat(cs.borderBottomWidth) + parseFloat(cs.borderLeftWidth);
    const hasBox = borderPx > 0
                || (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)')
                || (cs.backgroundImage && cs.backgroundImage !== 'none')
                || cs.boxShadow !== 'none';
    const base = own ? own.slice(0, 30)
                     : (hasBox ? `BOX@${Math.round(r.top + scrollY)}x${Math.round(r.width)}` : null);
    if (!base) continue;

    const n = (seen.get(base) || 0) + 1;
    seen.set(base, n);
    const rec = { key: base + (n > 1 ? `#${n}` : ''), tag: el.tagName,
                  w: Math.round(r.width), h: Math.round(r.height),
                  x: Math.round(r.left), y: Math.round(r.top + scrollY) };
    for (const p of PROPS) rec[p] = cs[p];
    out.push(rec);
  }
  return JSON.stringify({
    viewport: window.innerWidth,
    pageHeight: document.documentElement.scrollHeight,
    elements: out
  });
}
