// Measure a page's layout at one viewport width, compactly enough to sweep
// hundreds of widths and compare the results.
//
// WHY THIS AND NOT check-rwd.js
// check-rwd.js audits ONE width thoroughly: overflow, tiny type, small targets.
// That answers "is 390px broken". It cannot answer the question that actually
// matters for a responsive page - "at which widths does this layout CHANGE, and
// are those the widths anyone intended?" A page can pass at 390 and 768 and be
// broken at 500, and sampling seven points will never see it.
//
// So this returns a cheap SIGNATURE per width. The driver sweeps a range,
// notices where the signature changes, and binary-searches each change down to
// the pixel. What comes out is the list of widths at which the page really
// reflows, which can then be compared against the breakpoints the site
// declares (`gb.py rwd`). A reflow at a width nobody declared is a finding.
//
//   const sig = await page.evaluate(<this function>)
//
// The signature has to be stable at a given width and sensitive to reflow.
// Document height alone is neither: two different layouts can share a height,
// and a lazy image can change it without any reflow at all. So it also carries
// a hash of the box geometry of the elements that carry layout.
() => {
  const doc = document.scrollingElement;
  const vw = window.innerWidth;

  // Elements that decide layout - containers and media, not every text node.
  const nodes = document.querySelectorAll(
    'main div, main section, main figure, main img, main ul, main table,' +
    ' article div, article section, article figure, article img,' +
    ' .elementor div, .elementor section, .elementor figure, .elementor img'
  );

  // Overflow is counted per REGION. Page content and site chrome are different
  // problems with different owners, and mixing them makes a conversion audit
  // useless: on the reference site the widest offender between 1040px and
  // 1296px is the theme-builder HEADER, which carries a hardcoded
  // `width: 1300px` on a nowrap flex row. It overflows by exactly
  // (1300 - viewport) / 2 on EVERY page, converted or not.
  const region = (el) => (el.closest('main, article') ? 'content' : 'chrome');
  const overflowBy = { content: 0, chrome: 0 };
  const worstBy = { content: 0, chrome: 0 };
  let overflow = 0;
  let widest = 0;
  let h = 0;

  // THE SIGNATURE MUST NOT CHANGE WHEN THE PAGE MERELY GETS NARROWER.
  // The first version hashed rounded box geometry, and reported a "reflow" at
  // every single sample - correctly, in a sense, because a fluid layout's
  // geometry changes continuously. It was useless: 80 reflow points across 81
  // samples.
  //
  // What separates a reflow from a resize is that elements change their
  // ARRANGEMENT: a flex row wraps, a container stacks, something appears or
  // disappears. So the signature records, per container, how its children are
  // arranged - the number of distinct rows they occupy - plus the layout mode
  // itself. Both are invariant while a layout merely shrinks.
  let hash = 0x811c9dc5;
  const mix = (s) => {
    for (let i = 0; i < s.length; i++) {
      hash ^= s.charCodeAt(i);
      hash = Math.imul(hash, 0x01000193);
    }
  };

  for (const el of nodes) {
    // Nodes inside an <svg> live in the SVG's own coordinate space; a negative
    // x is normal there and says nothing about page layout.
    if (el.ownerSVGElement) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;

    // An element inside something that scrolls sideways on purpose is not
    // overflowing the page.
    let scroller = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ov = getComputedStyle(p).overflowX;
      if (ov === 'auto' || ov === 'scroll') { scroller = true; break; }
    }
    if (!scroller && (r.right > vw + 1 || r.left < -1)) {
      overflow++;
      widest = Math.max(widest, Math.round(r.right - vw));
      const reg = region(el);
      overflowBy[reg]++;
      worstBy[reg] = Math.max(worstBy[reg], Math.round(r.right - vw));
    }
    h++;

    // layout mode
    mix(cs.display);
    if (cs.display.includes('flex')) mix(cs.flexDirection + '|' + cs.flexWrap);
    if (cs.display.includes('grid')) mix(cs.gridTemplateColumns.split(' ').length + 'col');

    // how many ROWS the children occupy - the thing wrapping actually changes
    if (el.children.length > 1) {
      const rows = new Set();
      for (const c of el.children) {
        const cr = c.getBoundingClientRect();
        if (cr.width < 1 || cr.height < 1) continue;
        rows.add(Math.round(cr.top / 4));       // 4px tolerance for baselines
      }
      mix(el.children.length + ':' + rows.size);
    }
  }

  return {
    vw,
    height: doc.scrollHeight,
    boxes: h,
    overflow,
    worstOverflowPx: widest,
    contentOverflow: overflowBy.content,
    contentWorstPx: worstBy.content,
    chromeOverflow: overflowBy.chrome,
    chromeWorstPx: worstBy.chrome,
    // The theme may clip overflow rather than prevent it; report it, never
    // treat its absence as a pass.
    clips: getComputedStyle(document.body).overflowX === 'hidden',
    sig: (hash >>> 0).toString(36)
  };
}
