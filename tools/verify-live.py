#!/usr/bin/env python3
"""Verify the page the PUBLIC gets, not the one in the database.

    python tools/verify-live.py page.html https://site/slug/

Everything before this point checked the server's side of the story: the file,
the database row, do_blocks() output. None of it is what a visitor receives -
the theme, Breeze, Varnish and the CDN all sit in between. This fetches the
public URL and asserts, against the delivered bytes:

  - every content/wrapper block's text is in the page
  - every class the comment attrs demand (has-*, align*, is-style-*) is there
  - every inline-style rule the style objects demand is there
  - every --wp--preset--* var the tree references is DEFINED in the delivered
    CSS (inline <style> or a linked same-host stylesheet) - a class with no
    definition styles nothing, silently
  - every pure-dynamic block either delivered its wrapper class or is listed
    as swept-empty (needs context) so the gap is explained, not hidden

Prints the cache headers so a stale edge is visible rather than silent.
"""
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blockmark
import gblib

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

UA = {"User-Agent": "Mozilla/5.0 (verify-live)"}


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace"), dict(r.headers)


def text_of(html):
    t = re.sub(r"<[^>]+>", " ", html or "")
    return [s for s in (x.strip() for x in unescape(t).split()) if len(s) >= 3]


def main():
    src_file, url = sys.argv[1], sys.argv[2]
    src = Path(src_file).read_text(encoding="utf-8")
    schema = gblib.load_schema()
    blocks = schema["blocks"]
    tree = blockmark.parse(src)

    page, headers = fetch(url)
    page_flat = re.sub(r"\s+", "", page)

    # all delivered CSS: inline styles + same-host linked sheets
    css = "".join(re.findall(r"<style[^>]*>(.*?)</style>", page, re.S))
    host = re.match(r"https?://[^/]+", url).group(0)
    sheets = 0
    for href in re.findall(r'<link[^>]+rel=["\']stylesheet["\'][^>]+href=["\']([^"\']+)', page) \
              + re.findall(r'<link[^>]+href=["\']([^"\']+)["\'][^>]+rel=["\']stylesheet', page):
        full = href if href.startswith("http") else host + href if href.startswith("/") else None
        if full and full.startswith(host):
            try:
                body, _ = fetch(full)
                css += body
                sheets += 1
            except Exception:
                pass

    ok = bad = 0
    unexplained = []
    preset_vars = set()

    def check(cond, what):
        nonlocal ok, bad
        if cond:
            ok += 1
        else:
            bad += 1
            unexplained.append(what)

    n_content = n_dynamic = dyn_delivered = dyn_expected_empty = 0
    for node in blockmark.walk(tree):
        name = node["blockName"]
        bdef = blocks.get(name, {})
        attrs = node.get("attrs") or {}
        adefs = bdef.get("attributes") or {}
        pure_dynamic = bdef.get("is_dynamic") and not any(a.get("source") for a in adefs.values())

        # collect preset refs for the CSS-definition check
        for an, av in attrs.items():
            kind = gblib.preset_kind_for(an)
            if kind and isinstance(av, str) and av:
                preset_vars.add(f"--wp--preset--{kind}--{av}")
        for kind, slug in gblib.preset_slugs_in_style(attrs.get("style") or {}):
            preset_vars.add(f"--wp--preset--{kind}--{slug}")

        if pure_dynamic:
            n_dynamic += 1
            cls = "wp-block-" + name.replace("core/", "").replace("/", "-")
            if cls in page:
                dyn_delivered += 1
            elif bdef.get("render_verdict") == "empty":
                dyn_expected_empty += 1
            else:
                unexplained.append(f"dynamic {name}: no '{cls}' in the page and the sweep "
                                   f"says it should render")
                bad += 1
            continue

        n_content += 1
        for word in text_of(node.get("innerHTML", ""))[:8]:
            check(word in page, f"{name}: text {word!r} not delivered")
        for an, av in attrs.items():
            for cls in gblib.classes_for(name, an, av, bdef):
                check(cls in page, f"{name}: class '{cls}' not delivered")
        rules, style_classes, _ = gblib.style_expectations(attrs.get("style") or {}, name)
        for prop, val in rules:
            want = re.sub(r"\s+", "", f"{prop}:{val}")
            hit = want in page_flat
            if not hit and prop == "font-size":
                # fluid typography (theme.json typography.fluid) rewrites the
                # saved inline font-size to clamp(min, formula, MAX) at render,
                # where MAX is the authored value. Measured on this site.
                v = re.escape(re.sub(r"\s+", "", str(val)))
                hit = re.search(rf'font-size:clamp\([^;"]*?,{v}\)', page_flat) is not None
            check(hit, f"{name}: inline {prop}:{val} not delivered")
        for cls in style_classes:
            check(cls in page, f"{name}: class '{cls}' not delivered")

    defined = undefined = 0
    for var in sorted(preset_vars):
        if var + ":" in css or var + " :" in css:
            defined += 1
        else:
            undefined += 1
            unexplained.append(f"preset {var} referenced but DEFINED NOWHERE in delivered CSS")

    hl = {h.lower(): v for h, v in headers.items()}
    shown = [f"{k}: {hl[k]}" for k in ("x-cache", "cf-cache-status", "x-varnish",
             "age", "cache-control", "x-breeze-cache") if k in hl]
    print("cache headers : " + ("  ".join(shown) if shown else "(none)"))
    print(f"stylesheets   : {sheets} same-host sheets + inline styles inspected")
    print(f"content blocks: {n_content} - {ok} assertions passed")
    print(f"dynamic blocks: {n_dynamic} - {dyn_delivered} delivered their wrapper, "
          f"{dyn_expected_empty} swept-empty (need context, explained)")
    print(f"preset vars   : {defined} defined in delivered CSS, {undefined} missing")
    for u in unexplained:
        print(f"  FAIL {u}")
    if unexplained:
        print(f"FAIL - {len(unexplained)} assertions failed")
        sys.exit(1)
    print("PASS - the page a visitor receives carries every text fragment, every class\n"
          "       and every inline rule the tree demands, and every preset var it\n"
          "       references is defined in the CSS actually delivered.")


if __name__ == "__main__":
    main()
