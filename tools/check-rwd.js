// Assert a page is actually responsive at a given viewport width.
//
// Run this function in the page at EVERY breakpoint you support, on the
// original and the converted page both. It answers three questions a
// screenshot answers badly:
//
//   1. does anything render wider than the viewport?
//   2. does any text shrink below a readable size?
//   3. does any interactive target end up too small to hit?
//
//   Playwright:  await page.setViewportSize({width:390, height:844})
//                const r = await page.evaluate(<this function>)
//
// THE TRAP THIS EXISTS FOR
// `document.scrollingElement.scrollWidth > innerWidth` is the obvious overflow
// check and it is wrong on most real sites: themes set `body{overflow-x:hidden}`
// (measured on Blocksy), which CLIPS the overflow instead of preventing it. The
// scrollbar never appears, the check passes, and the content is still cut off -
// a container 1160px wide inside a 390px viewport reported clean. So this walks
// elements and compares each box against the viewport, and reports the clip
// separately from the verdict.
() => {
  const vw = window.innerWidth;
  const overflow = [], tiny = [], smallTargets = [];
  const MIN_FONT = 12;      // below this, body copy is unreadable on a phone
  const MIN_TARGET = 24;    // WCAG 2.2 2.5.8 Target Size (Minimum)

  for (const el of document.querySelectorAll('main *, article *, .elementor *')) {
    // Nodes INSIDE an <svg> live in the SVG's own coordinate space: a <g> with
    // a negative x is normal there and says nothing about page layout. The
    // <svg> element itself is still checked, which is the box that matters.
    if (el.ownerSVGElement) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;

    // An element is only overflowing if it is not itself inside something that
    // scrolls horizontally on purpose (a carousel, a wide table in a scroller).
    let scroller = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ov = getComputedStyle(p).overflowX;
      if (ov === 'auto' || ov === 'scroll') { scroller = true; break; }
    }
    if (!scroller && (r.right > vw + 1 || r.left < -1)) {
      overflow.push({ tag: el.tagName, cls: (el.getAttribute('class') || '').slice(0, 48),
                      width: Math.round(r.width), right: Math.round(r.right),
                      text: (el.textContent || '').trim().slice(0, 24) });
    }

    const ownText = [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim());
    if (ownText && parseFloat(cs.fontSize) < MIN_FONT) {
      tiny.push({ tag: el.tagName, fontSize: cs.fontSize,
                  text: (el.textContent || '').trim().slice(0, 24) });
    }
    if ((el.tagName === 'A' || el.tagName === 'BUTTON' ||
         (el.tagName === 'INPUT' && el.type !== 'hidden')) &&
        (r.height < MIN_TARGET || r.width < MIN_TARGET)) {
      smallTargets.push({ tag: el.tagName, w: Math.round(r.width), h: Math.round(r.height),
                          text: (el.textContent || '').trim().slice(0, 24) });
    }
  }

  const doc = document.scrollingElement;
  return {
    viewport: vw,
    pageHeight: doc.scrollHeight,
    // Reported for context, NOT used as the verdict - see the header.
    scrollbarOverflow: doc.scrollWidth - vw,
    clipsOverflow: getComputedStyle(document.body).overflowX === 'hidden',
    overflow: overflow.slice(0, 10),
    overflowCount: overflow.length,
    tinyText: tiny.slice(0, 6),
    tinyTextCount: tiny.length,
    smallTargets: smallTargets.slice(0, 6),
    smallTargetCount: smallTargets.length,
    // Only overflow fails the check. Small type and small targets are design
    // decisions - the reference page ships 11.5px section labels deliberately -
    // so folding them into the verdict makes every real page FAIL and the
    // signal worthless. They are reported for review, and the number to watch
    // is whether a CONVERSION adds any the original did not have.
    pass: overflow.length === 0
  };
}
