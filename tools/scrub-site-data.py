#!/usr/bin/env python3
"""
scrub-site-data.py - remove what the extraction site leaked into data/.

The extractors read a live install, so a few values are the site's, not
WordPress's: its host (site_url, the measured_on stamp, absolute URLs inside
pattern content), the admin e-mail a pattern fills in, and absolute server
paths of plugin/theme pattern files. Hosts are read from the data itself, so
this file names no domain. Runs from build-indexes.py; idempotent.

    python tools/scrub-site-data.py           # rewrite data/ in place
    python tools/scrub-site-data.py --check   # exit 1 if anything would change
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

NEUTRAL_HOST = "example.com"
NEUTRAL_EMAIL = "admin@example.com"

# Top-level keys the extractors fill from get_site_url().
URL_KEYS = ("site_url", "url")
HOST = re.compile(r"^(?:https?:)?(?://)?([^/\s]+)")
EMAIL = re.compile(r"\b[\w.+-]+@(?!example\.com\b)[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b")
# "/home/<account>/.../public_html/wp-content/..." -> "wp-content/..."; JSON may escape "/".
SERVER_PATH = re.compile(r'(?<=")(?:[A-Za-z]:)?\\?/(?!\\?/)[^"\s]*?\\?/(?=wp-content\\?/)')


def site_hosts(data: Path) -> set[str]:
    """Hosts of the extraction site, read from the dumps and the measured_on stamp."""
    hosts: set[str] = set()
    for p in data.glob("*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(d, dict):
            for k in URL_KEYS:
                v = d.get(k)
                if isinstance(v, str) and (m := HOST.match(v)):
                    hosts.add(m.group(1).lower())
    for p in data.glob("*.csv"):
        with p.open(encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            if "measured_on" not in (r.fieldnames or []):
                continue
            for row in r:
                tok = (row.get("measured_on") or "").split(" ", 1)[0]
                if "." in tok and "/" not in tok:
                    hosts.add(tok.lower())
    hosts.discard(NEUTRAL_HOST)
    return hosts


def scrub_text(s: str, hosts: set[str]) -> str:
    for h in sorted(hosts, key=len, reverse=True):
        s = re.sub(r"(?i)(?<![\w.-])" + re.escape(h) + r"(?![\w-])", NEUTRAL_HOST, s)
    s = EMAIL.sub(NEUTRAL_EMAIL, s)
    return SERVER_PATH.sub("", s)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if dirty")
    ap.add_argument("data", nargs="?", default=str(DATA), help="data directory (default: data/)")
    a = ap.parse_args()
    data = Path(a.data)
    hosts = site_hosts(data)
    dirty = []
    for p in sorted(data.iterdir()):
        if p.suffix not in (".json", ".csv"):
            continue
        raw = p.read_text(encoding="utf-8")
        new = scrub_text(raw, hosts)
        if new == raw:
            continue
        if p.suffix == ".json":
            json.loads(new)  # never write a broken dump
        dirty.append(p.name)
        if not a.check:
            p.write_text(new, encoding="utf-8", newline="")
    for n in dirty:
        print(("would scrub " if a.check else "scrubbed ") + n)
    if not dirty:
        print("data/ clean")
    return 1 if (a.check and dirty) else 0


def scrub_dir(data: Path) -> list[str]:
    """For build-indexes.py: scrub `data` in place, return the files changed."""
    hosts = site_hosts(data)
    done = []
    for p in sorted(data.iterdir()):
        if p.suffix in (".json", ".csv"):
            raw = p.read_text(encoding="utf-8")
            new = scrub_text(raw, hosts)
            if new != raw:
                p.write_text(new, encoding="utf-8", newline="")
                done.append(p.name)
    return done


if __name__ == "__main__":
    sys.exit(main())
