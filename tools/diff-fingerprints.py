# -*- coding: utf-8 -*-
"""Pair two style fingerprints by text key and report every differing property.

    node collect.js  ->  orig-fp.json / conv-fp.json     (see docstring below)
    python tools/diff-fingerprints.py orig-fp.json conv-fp.json

COLLECT WITH THIS, in the page, on BOTH pages at the SAME viewport width:

    () => {
      const PROPS = ['fontSize','fontWeight','lineHeight','letterSpacing',
        'textAlign','color','backgroundColor','textTransform',
        'paddingTop','paddingRight','paddingBottom','paddingLeft',
        'marginTop','marginBottom',
        'borderTopWidth','borderRightWidth','borderBottomWidth','borderLeftWidth',
        'borderTopColor','borderRadius','display','justifyContent','alignItems',
        'rowGap','columnGap','maxWidth','minHeight','opacity'];
      const out = [], seen = new Map();
      for (const el of document.querySelectorAll('main *, .site-main *, article *, .elementor *')) {
        const r = el.getBoundingClientRect();
        if (r.width < 1 || r.height < 1) continue;
        const cs = getComputedStyle(el);
        if (cs.visibility === 'hidden' || cs.display === 'none') continue;
        const own = [...el.childNodes].filter(n => n.nodeType===3 && n.textContent.trim())
                                      .map(n => n.textContent.trim()).join(' ');
        // KEY BY TEXT where there is text, else by a box signature: a border
        // or background on a text-less container is invisible to a text-only
        // fingerprint, and that is exactly where a 1px divider turned into a
        // full box went unnoticed on moksaweb.com.
        const box = (parseFloat(cs.borderTopWidth)+parseFloat(cs.borderRightWidth)
                    +parseFloat(cs.borderBottomWidth)+parseFloat(cs.borderLeftWidth)) > 0
                    || (cs.backgroundColor && cs.backgroundColor !== 'rgba(0, 0, 0, 0)');
        const base = own ? own.slice(0,30) : (box ? 'BOX@' + Math.round(r.top+scrollY) + 'x' + Math.round(r.width) : null);
        if (!base) continue;
        const n = (seen.get(base)||0)+1; seen.set(base, n);
        const rec = {key: base + (n>1?'#'+n:''), tag: el.tagName,
                     w: Math.round(r.width), h: Math.round(r.height)};
        for (const p of PROPS) rec[p] = cs[p];
        out.push(rec);
      }
      return JSON.stringify(out);
    }

TWO TRAPS, both hit for real while building this:
  1. Set the viewport EXPLICITLY on both pages before collecting. A default
     window width can be narrow enough to trip the responsive breakpoint and
     you end up diffing a desktop layout against a mobile one.
  2. Elementor wraps text in <span>, blocks put it straight on <h2>/<p>. Most
     pairs will therefore differ in `tag` - compare those as BOXES (the button
     element, not its label), and treat start/left, end/right and
     minHeight 0px/auto as the equivalences they are.
"""
import json, sys, collections
sys.stdout.reconfigure(encoding='utf-8')

a = json.loads(open(sys.argv[1] if len(sys.argv)>1 else 'orig-fp.json', encoding='utf-8').read())
b = json.loads(open(sys.argv[2] if len(sys.argv)>2 else 'conv-fp.json', encoding='utf-8').read())
# the evaluate() result may be wrapped as a JSON string
if isinstance(a, str): a = json.loads(a)
if isinstance(b, str): b = json.loads(b)

A = {r['key']: r for r in a}
B = {r['key']: r for r in b}
common = [k for k in A if k in B]
print(f"orig elements: {len(A)}  conv elements: {len(B)}  paired: {len(common)}")
print(f"missing in conv: {len(set(A)-set(B))}   extra in conv: {len(set(B)-set(A))}")
missing = sorted(set(A) - set(B))[:8]
if missing:
    print("  e.g. missing:", ' | '.join(m[:18] for m in missing))
print()

PROPS = [p for p in A[common[0]] if p not in ('key', 'tag')]
diffs = collections.defaultdict(list)
for k in common:
    for p in PROPS:
        va, vb = str(A[k].get(p)), str(B[k].get(p))
        if p in ('w', 'h'):
            try:
                if abs(int(va) - int(vb)) <= 3: continue
            except Exception: pass
        if va != vb:
            diffs[p].append((k, va, vb))

print("PROPERTY DIFFERENCES (count, then up to 3 examples)")
print("=" * 92)
for p, rows in sorted(diffs.items(), key=lambda x: -len(x[1])):
    print(f"\n{p}: {len(rows)}/{len(common)}")
    for k, va, vb in rows[:3]:
        print(f"    {k[:26]:28} orig={va[:34]:36} conv={vb[:34]}")
