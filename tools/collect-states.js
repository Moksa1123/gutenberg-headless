// Collect the INTERACTIVE state of every interactive element on a page.
//
// A resting-state fingerprint (collect-fingerprint.js) cannot see any of this.
// It reads computed styles once, with nothing hovered and nothing focused, so
// a converted page can match it exactly and still have every button change
// colour the wrong way, or not at all. Measured: an Elementor page whose
// buttons invert on hover converted to blocks that did nothing, and the
// resting diff was clean.
//
// Use with a driver that hovers/focuses each element (tools/README or the
// migration reference has the Playwright loop):
//
//   const list = await page.evaluate(<this function>)      // 1. enumerate
//   for (const el of list) {                               // 2. drive
//     await page.hover(`[data-state-probe="${el.probe}"]`)
//     states[el.probe] = await page.evaluate(readProbe, el.probe)
//   }
//
// The function tags each element with `data-state-probe` so the driver can
// address it, and returns everything measurable WITHOUT interaction:
// transition, cursor, and the declared :hover/:focus rules found in the
// stylesheets - which is the only way to catch a hover that is declared but
// unreachable, and a hover the original never had.
() => {
  const STATE_PROPS = [
    'color', 'backgroundColor', 'backgroundImage', 'borderTopColor',
    'borderTopWidth', 'borderRadius', 'boxShadow', 'opacity', 'transform',
    'textDecorationLine', 'letterSpacing', 'filter'
  ];

  const isInteractive = (el) => {
    const tag = el.tagName;
    if (tag === 'A' || tag === 'BUTTON' || tag === 'SUMMARY') return true;
    if (tag === 'INPUT' || tag === 'SELECT' || tag === 'TEXTAREA') return true;
    const cs = getComputedStyle(el);
    // A card that lifts on hover is interactive even though it is a <div>.
    if (cs.cursor === 'pointer') return true;
    return cs.transitionDuration !== '0s' && cs.transitionProperty !== 'none';
  };

  // Which :hover / :focus declarations in the page's own stylesheets apply to
  // this element. Reading the RULES (not just the computed result) catches a
  // hover that exists but is outranked, which is invisible either way until
  // someone actually points at it.
  const declaredStates = (el) => {
    const out = [];
    for (const sheet of document.styleSheets) {
      let rules;
      try { rules = sheet.cssRules; } catch (e) { continue; }   // cross-origin
      const scan = (list) => {
        for (const r of list) {
          if (r.cssRules && r.conditionText !== undefined) { scan(r.cssRules); continue; }
          const sel = r.selectorText;
          if (!sel || !/:hover|:focus|:active/.test(sel)) continue;
          const base = sel.replace(/:(hover|focus|focus-visible|active)/g, '');
          let matches = false;
          try { matches = el.matches(base); } catch (e) { continue; }
          if (!matches) continue;
          const decls = {};
          for (const p of r.style) decls[p] = r.style.getPropertyValue(p);
          out.push({ selector: sel.slice(0, 80), decls });
        }
      };
      scan(rules);
    }
    return out;
  };

  const out = [];
  let n = 0;
  for (const el of document.querySelectorAll('main *, article *, .elementor *')) {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1) continue;
    if (!isInteractive(el)) continue;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;

    // Elementor wraps a button's words in <span class="elementor-button-text">
    // inside the <a>; a block button puts them on the <a> itself. Both are
    // "interactive", and pairing the two pages by label then compares a LABEL
    // against a BUTTON - which reports the button's border, radius and
    // background as differences on every single one of them. Keep only the
    // OUTERMOST interactive element carrying a given text.
    // Elementor nests a button three deep - a widget <div> that carries the
    // transition, the <a> that IS the control, and a <span> holding the words -
    // and all three qualify as "interactive". Pairing two pages by label then
    // compares whichever happens to be found first, which is how the same
    // button reported once as a label with no border and once as a wrapper
    // with no colour. Keep the real CONTROL where there is one, and only fall
    // back to the outermost element for a control-less hover target (a card).
    // `textContent` includes the text of any <style>/<script> inside the
    // element, so a group carrying a design-layer stylesheet was keyed by CSS
    // source; and the two pages indent differently, so the same card produced
    // two different keys. Both make the pairing wrong rather than noisy.
    const textOf = (n) => {
      let s = '';
      for (const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT); w.nextNode();) {
        const p = w.currentNode.parentElement;
        if (p && (p.tagName === 'STYLE' || p.tagName === 'SCRIPT')) continue;
        s += w.currentNode.textContent;
      }
      return s.replace(/\s+/g, ' ').trim();
    };
    const label = textOf(el);
    const CONTROL = /^(A|BUTTON|INPUT|SELECT|TEXTAREA|SUMMARY)$/;
    const sameLabel = (n) => textOf(n) === label;
    const isControl = CONTROL.test(el.tagName);

    let shadowed = false;
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      if (!sameLabel(p)) continue;
      if (CONTROL.test(p.tagName)) { shadowed = true; break; }        // a control outranks us
      if (!isControl && isInteractive(p)) { shadowed = true; break; } // prefer the outer box
    }
    if (!shadowed && !isControl) {
      // A wrapper around the real control loses to it.
      for (const d of el.querySelectorAll('a,button,input,select,textarea,summary')) {
        if (sameLabel(d)) { shadowed = true; break; }
      }
    }
    if (shadowed) continue;

    const probe = `p${n++}`;
    el.setAttribute('data-state-probe', probe);

    const rest = {};
    for (const p of STATE_PROPS) rest[p] = cs[p];

    out.push({
      probe,
      tag: el.tagName,
      // The label is the pairing key across the two pages - the same button
      // has the same words on both, whatever markup it is made of.
      label: label.slice(0, 40),
      w: Math.round(r.width), h: Math.round(r.height),
      cursor: cs.cursor,
      transition: cs.transition,
      transitionProperty: cs.transitionProperty,
      transitionDuration: cs.transitionDuration,
      rest,
      declared: declaredStates(el)
    });
  }
  return JSON.stringify({ viewport: innerWidth, elements: out });
}
