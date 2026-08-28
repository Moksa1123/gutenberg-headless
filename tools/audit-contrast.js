// Design verification: WCAG contrast audit for a delivered page.
// Run in the page context (Playwright evaluate / browser console):
//   const report = JSON.parse(auditContrast());
// Flags text whose contrast against its effective background fails WCAG AA
// (4.5:1 normal, 3:1 large text >=24px or bold >=18.66px). Gradients are
// checked against EVERY color stop - the worst stop is reported, because a
// heading can sit on any part of the gradient.
function auditContrast() {
  const parse = (str) => {
    const m = (str || '').match(/rgba?\(([\d.]+)[, ]+([\d.]+)[, ]+([\d.]+)(?:[,/ ]+([\d.]+))?\)/);
    return m ? { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] } : null;
  };
  const lum = (c) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const ratio = (a, b) => {
    const l1 = Math.max(lum(a), lum(b)), l2 = Math.min(lum(a), lum(b));
    return (l1 + 0.05) / (l2 + 0.05);
  };
  // effective background: walk up for solid color and/or gradient stops
  const bgsOf = (el) => {
    let node = el;
    while (node && node !== document.documentElement) {
      const cs = getComputedStyle(node);
      const bi = cs.backgroundImage;
      if (bi && bi.includes('gradient')) {
        const stops = [...bi.matchAll(/rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}/g)].map(m => {
          if (m[0][0] === '#') {
            const h = m[0].slice(1);
            const x = h.length < 6 ? h.split('').map(c => c + c).join('') : h;
            return { r: parseInt(x.slice(0, 2), 16), g: parseInt(x.slice(2, 4), 16), b: parseInt(x.slice(4, 6), 16), a: 1 };
          }
          return parse(m[0]);
        }).filter(Boolean).filter(c => c.a > 0.4);
        if (stops.length) return stops;
      }
      const bc = parse(cs.backgroundColor);
      if (bc && bc.a > 0.4) return [bc];
      if (bi && bi.includes('url(')) return null; // photo background: cannot judge statically
      node = node.parentElement;
    }
    return [{ r: 255, g: 255, b: 255, a: 1 }];
  };
  // cover blocks: the dim overlay is a SIBLING span, not an ancestor - blend it
  const coverBg = (el) => {
    const cover = el.closest('.wp-block-cover');
    if (!cover) return undefined;
    const dim = cover.querySelector('.wp-block-cover__background');
    if (!dim) return null;
    const m = (dim.className.match(/has-background-dim-(\d+)/) || [])[1];
    const a = m ? +m / 100 : 0.5;
    const oc = parse(getComputedStyle(dim).backgroundColor) || { r: 0, g: 0, b: 0, a: 1 };
    // worst case: overlay blended over a WHITE photo region
    const blend = (v) => Math.round(v * a + 255 * (1 - a));
    return [{ r: blend(oc.r), g: blend(oc.g), b: blend(oc.b), a: 1 }];
  };
  const fails = [];
  document.querySelectorAll('h1,h2,h3,h4,p,a,li,cite,summary,td,th,button,label').forEach((el) => {
    if (el.closest('.screen-reader-text, .skip-link')) return;
    const t = (el.childNodes.length && [...el.childNodes].some(n => n.nodeType === 3 && n.textContent.trim())) ? el.textContent.trim() : '';
    if (!t) return;
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || +cs.opacity === 0) return;
    const fg = parse(cs.color);
    if (!fg) return;
    const bgs = coverBg(el) !== undefined ? coverBg(el) : bgsOf(el);
    if (!bgs) return; // photo bg - handled by eyeballing screenshots
    const worst = Math.min(...bgs.map(bg => ratio(fg, bg)));
    const size = parseFloat(cs.fontSize);
    const bold = +cs.fontWeight >= 700;
    const symbolOnly = !/[\p{L}\p{N}]/u.test(t);   // pure symbols (stars, arrows): graphics contrast 3:1
    const needed = symbolOnly ? 3 : (size >= 24 || (bold && size >= 18.66)) ? 3 : 4.5;
    if (worst < needed) {
      fails.push({ tag: el.tagName, text: t.slice(0, 24), ratio: +worst.toFixed(2), needed, color: cs.color, cls: (el.className || '').toString().slice(0, 50) });
    }
  });
  return JSON.stringify({ checked: true, failures: fails.slice(0, 20), failCount: fails.length });
}
