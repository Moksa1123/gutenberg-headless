# -*- coding: utf-8 -*-
"""Pair two style fingerprints by text key and report every differing property."""
import json, sys, collections
sys.stdout.reconfigure(encoding='utf-8')

a = json.loads(open(r'G:\Block Editor\orig-fp.json', encoding='utf-8').read())
b = json.loads(open(r'G:\Block Editor\conv-fp.json', encoding='utf-8').read())
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
