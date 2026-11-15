#!/usr/bin/env python3
"""
test_gutenberg.py - the skill's self-test. Offline, standard library only.

Covers: the CI release gates that can run locally (example pages validate,
installer smoke test), the validators as gates (non-zero on error), the
validator rules against WordPress's own patterns, the parser round-trip,
Chinese queries through data/terms-zh.csv, provenance columns on the main
tables, SKILL.md structure and its numbers (check_numbers.py), and the evals
file shape.

    python tools/test_gutenberg.py                 # offline
    python tools/test_gutenberg.py --live <url>    # also verify-live the demo page against <url>

Steps that need php / node skip (and say so) when the binary is missing.
"""

from __future__ import annotations

import csv
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
DATA = ROOT / "data"
SKILL_MD = ROOT / "SKILL.md"
EXAMPLES = sorted((ROOT / "examples").glob("*.html"))
LIVE_URL: str | None = None

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(HERE))
import blockmark  # noqa: E402

TRUST = {"measured", "documented", "inferred", "house-style"}


def run(*args: str, tool: str = "gb.py") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(HERE / tool), *args], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", cwd=ROOT)


def gb_json(*args: str):
    p = run(*args, "--json")
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def rows(name: str) -> list[dict]:
    with (DATA / name).open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def schema() -> dict:
    return json.loads((DATA / "block-schema.json").read_text(encoding="utf-8"))


def frontmatter(text: str) -> dict:
    """The few keys this skill uses; values unquoted, `|` blocks joined."""
    fm, out, key = text.split("---", 2)[1], {}, None
    for line in fm.splitlines():
        m = re.match(r"^([\w-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            out[key] = "" if val == "|" else val.strip('"')
        elif key and line.startswith("  "):
            out[key] = (out[key] + " " + line.strip()).strip()
    return out


# ---------------------------------------------------------------------------
class ReleaseGates(unittest.TestCase):
    """The local half of .github/workflows/publish.yml, plus the offline proofs."""

    def test_php_tools_parse(self):
        php = shutil.which("php")
        if not php:
            self.skipTest("php not installed - lint them on the test site (php -l)")
        for f in sorted(HERE.glob("*.php")):
            p = subprocess.run([php, "-l", str(f)], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, f"{f.name}: {p.stdout}{p.stderr}")

    def test_stats_reports_the_site(self):
        p = run("stats")
        self.assertEqual(p.returncode, 0, p.stderr)
        s = schema()
        self.assertIn(f"WordPress   : {s['wp_version']}", p.stdout)
        self.assertIn(f"{len(s['blocks'])} registered", p.stdout)
        self.assertIn(f"render-swept: {len(s['blocks'])}/{len(s['blocks'])}", p.stdout)

    def test_examples_validate(self):
        self.assertGreaterEqual(len(EXAMPLES), 5)
        for f in EXAMPLES:
            p = run(str(f), tool="validate-post.py")
            self.assertEqual(p.returncode, 0, f"{f.name}: {p.stdout[-800:]}")
            self.assertIn("0 errors", p.stdout, f.name)

    def test_validator_is_a_gate(self):
        with tempfile.TemporaryDirectory() as t:
            bad = Path(t) / "bad.html"
            bad.write_text('<!-- wp:paragraph {"backgroundColor":"no-such-slug"} -->\n'
                           "<p>x</p>\n<!-- /wp:paragraph -->\n", encoding="utf-8")
            p = run(str(bad), tool="validate-post.py")
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertIn("E-PRESET", p.stdout)
            ghost = Path(t) / "ghost.html"
            ghost.write_text("<!-- wp:acme/no-such-block /-->\n", encoding="utf-8")
            p = run(str(ghost), tool="validate-post.py")
            self.assertEqual(p.returncode, 1, p.stdout)
            self.assertIn("E-BLOCK", p.stdout)

    def test_selftest_patterns(self):
        if not (DATA / "patterns.json").exists():
            self.skipTest("data/patterns.json not shipped")
        p = run(tool="selftest-patterns.py")
        self.assertEqual(p.returncode, 0, p.stdout[-800:] + p.stderr[-800:])

    def test_installer_smoke(self):
        node = shutil.which("node")
        if not node or not (ROOT / "bin" / "install.mjs").exists():
            self.skipTest("node or bin/install.mjs missing")
        with tempfile.TemporaryDirectory() as t:
            p = subprocess.run([node, str(ROOT / "bin" / "install.mjs"), "claude-code", "--to", t, "--force"],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=ROOT)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            dst = Path(t) / "skills" / "gutenberg-headless"
            self.assertTrue((dst / "data" / "block-schema.json").exists())
            self.assertEqual(frontmatter((dst / "SKILL.md").read_text(encoding="utf-8")),
                             frontmatter(SKILL_MD.read_text(encoding="utf-8")))

    @unittest.skipUnless(LIVE_URL or "--live" in sys.argv, "offline (pass --live <url>)")
    def test_verify_live_demo(self):
        p = run(str(ROOT / "examples" / "demo-page.html"), LIVE_URL, tool="verify-live.py")
        self.assertEqual(p.returncode, 0, p.stdout[-1500:])
        self.assertIn("PASS", p.stdout)


# ---------------------------------------------------------------------------
class Parser(unittest.TestCase):

    def test_examples_round_trip(self):
        for f in EXAMPLES:
            src = f.read_text(encoding="utf-8")
            self.assertEqual(blockmark.serialize(blockmark.parse(src)), src, f.name)

    def test_recorded_round_trip(self):
        rs = rows("roundtrip-verification.csv")
        self.assertTrue(rs)
        for r in rs:
            self.assertIn(r["trust"], TRUST, r)
            self.assertTrue(r["measured_on"], r)
            self.assertIn(r["divergence"], ("", "escape"), r)
            self.assertEqual(r["byte_identical"] == "yes", r["divergence"] == "", r)

    def test_roundtrip_check_classifies(self):
        cases = [
            ('<!-- wp:paragraph {"className":"a&b"} -->\n<p>x</p>\n<!-- /wp:paragraph -->', 0, "escape"),
            ('<!-- wp:paragraph -->\n<p>x</p>\n<!-- /wp:paragraph -->', 0, ""),
            ('<!-- wp:paragraph {"a":1,  "b":2} -->\n<p>x</p>\n<!-- /wp:paragraph -->', 1, "other"),
        ]
        for content, code, kind in cases:
            with tempfile.TemporaryDirectory() as t:
                exp = Path(t) / "e.json"
                out = Path(t) / "o.csv"
                exp.write_text(json.dumps({"site": "https://example.test", "wp": "0", "woocommerce": None,
                                           "exported_at": "2099-01-01",
                                           "posts": [{"id": 1, "type": "page", "content": content}]}),
                               encoding="utf-8")
                p = run(str(exp), "--out", str(out), tool="roundtrip-check.py")
                self.assertEqual(p.returncode, code, p.stdout + p.stderr)
                with out.open(encoding="utf-8", newline="") as f:
                    self.assertEqual(next(csv.DictReader(f))["divergence"], kind, content)


# ---------------------------------------------------------------------------
# (query, gb.py command, name that must be in the result)
ZH_BLOCKS = [
    ("按鈕", "core/button"),
    ("欄", "core/columns"),
    ("多重欄位", "core/columns"),
    ("群組", "core/group"),
    ("封面", "core/cover"),
    ("段落", "core/paragraph"),
    ("圖片", "core/image"),
    ("分隔線", "core/separator"),
    ("麵包屑", "core/breadcrumbs"),
    ("手風琴", "core/accordion"),
    ("商品格線", "woocommerce/product-collection"),
    ("商品價格", "woocommerce/product-price"),
    ("加入購物車", "woocommerce/product-button"),
    ("購物車", "woocommerce/cart"),
    ("結帳", "woocommerce/checkout"),
    ("迷你購物車", "woocommerce/mini-cart"),
]
ZH_ATTRS = [  # (block, query, attribute or support key that must be printed)
    ("core/group", "背景色", "backgroundColor"),
    ("core/heading", "文字色彩", "textColor"),
    ("core/paragraph", "字型大小", "fontSize"),
    ("core/group", "內距", "spacing.padding"),
    ("core/group", "邊界", "spacing.margin"),
    ("core/cover", "最小高度", "minHeight"),
    ("core/image", "外觀比例", "aspectRatio"),
]


class ChineseQueries(unittest.TestCase):

    def test_block_routes(self):
        bad = []
        for q, want in ZH_BLOCKS:
            names = gb_json("blocks", "--grep", q)
            if want not in names:
                bad.append((q, want, names[:8]))
        self.assertEqual(bad, [])

    def test_attribute_routes(self):
        bad = []
        for block, q, want in ZH_ATTRS:
            p = run("block", block, "--grep", q)
            if p.returncode or want not in p.stdout:
                bad.append((block, q, want))
        self.assertEqual(bad, [])

    def test_ascii_unchanged(self):
        s = schema()
        want = sorted(n for n, b in s["blocks"].items()
                      if "button" in f"{n} {b['title']} {' '.join(b.get('keywords') or [])}".lower())
        self.assertEqual(gb_json("blocks", "--grep", "button"), want)

    def test_unknown_term_points_to_pending(self):
        p = run("blocks", "--grep", "咖啡機")
        self.assertIn("-- 0 blocks", p.stdout)
        self.assertIn("pending.csv", p.stderr)
        self.assertIn("咖啡機", p.stderr)

    def test_terms_file(self):
        rs = rows("terms-zh.csv")
        self.assertGreaterEqual(len(rs), 50)
        for r in rs:
            self.assertIn(r["trust"], TRUST, r)
            self.assertTrue(r["en"].strip(), r)
            if r["trust"] == "documented":
                self.assertTrue(r["source"].startswith("https://translate.wordpress.org/"), r)
        self.assertEqual(len({r["zh"] for r in rs}), len(rs), "duplicate zh term")

    def test_routing_table_commands_run(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        section = text.split("## Routing", 1)[1].split("\n## ", 1)[0]
        ran = 0
        for c in re.findall(r"`gb\.py ([^`]+)`", section):
            if "<" in c:
                continue
            p = run(*shlex.split(c))
            self.assertEqual(p.returncode, 0, f"gb.py {c}: {p.stderr}")
            self.assertTrue(p.stdout.strip(), f"gb.py {c}: no output")
            ran += 1
        self.assertGreaterEqual(ran, 15)


# ---------------------------------------------------------------------------
class Provenance(unittest.TestCase):
    TABLES = ("blocks.csv", "attributes.csv", "supports.csv", "styles.csv",
              "block-categories.csv", "presets.csv", "patterns.csv", "render-verification.csv")

    def test_main_tables_stamped(self):
        s = schema()
        want = [f"WP {s['wp_version']}", f"{s['theme']['name']} {s['theme']['version']}",
                f"extracted {s['extracted_at'][:10]}"]
        for name in self.TABLES:
            rs = rows(name)
            self.assertTrue(rs, name)
            bad = [r for r in rs if r.get("trust") not in TRUST
                   or not all(w in (r.get("measured_on") or "") for w in want)]
            self.assertEqual(bad[:3], [], name)

    def test_tables_agree_with_schema(self):
        s = schema()
        self.assertEqual(len(rows("blocks.csv")), len(s["blocks"]))
        verdicts = {r["block"]: r["verdict"] for r in rows("render-verification.csv")}
        self.assertEqual({r["name"]: r["render_verdict"] for r in rows("blocks.csv")}, verdicts)
        self.assertEqual({n: b.get("render_verdict") for n, b in s["blocks"].items()}, verdicts)

    def test_pending_file(self):
        rs = rows("pending.csv")
        self.assertTrue(rs)
        for r in rs:
            for k in ("date", "question", "why_not_found", "asked_by", "status"):
                self.assertTrue(r.get(k), (k, r))

    def test_stamp_is_idempotent(self):
        from provenance import stamp
        with tempfile.TemporaryDirectory() as t:
            dst = Path(t) / "styles.csv"
            dst.write_bytes((DATA / "styles.csv").read_bytes())
            m = {"site_url": "https://x.test", "wp_version": "9.9", "extracted_at": "2099-01-01T00:00:00",
                 "theme": {"name": "T", "version": "1"}, "plugin_versions": {"woocommerce": "99.0"}}
            stamp(Path(t), m)
            once = dst.read_bytes()
            stamp(Path(t), m)
            self.assertEqual(once, dst.read_bytes())
            lines = once.decode("utf-8").splitlines()
            self.assertEqual(lines[0].split(",")[-2:], ["measured_on", "trust"])
            self.assertIn("WooCommerce 99.0", lines[1])


# ---------------------------------------------------------------------------
class SkillDoc(unittest.TestCase):

    def test_numbers(self):
        import check_numbers
        problems, n = check_numbers.check()
        self.assertEqual(problems, [])
        self.assertGreater(n, 20)

    def test_structure(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        self.assertLessEqual(len(text.encode("utf-8")), 20 * 1024)
        self.assertEqual(frontmatter(text).get("user-invocable"), "true")
        heads = re.findall(r"(?m)^## (\S+)", text)
        self.assertEqual(heads, ["Sources", "Usage", "Routing", "Tasks", "Verify", "Maintenance"])
        first = text.split("## Routing", 1)[1].strip().splitlines()[0]
        self.assertIn("never answer from memory", first)
        self.assertIn("pending.csv", first)

    def test_no_duplicate_lines(self):
        lines = [ln.strip() for ln in SKILL_MD.read_text(encoding="utf-8").splitlines()]
        seen, dup = set(), []
        for ln in lines:
            if not ln or set(ln) <= set("|-") or ln == "---":
                continue
            if ln in seen:
                dup.append(ln)
            seen.add(ln)
        self.assertEqual(dup, [])

    def test_frontmatter_matches_installer_templates(self):
        tpl_dir = ROOT / "assets" / "templates" / "platforms"
        if not tpl_dir.exists():
            self.skipTest("installer templates not shipped here")
        fm = frontmatter(SKILL_MD.read_text(encoding="utf-8"))
        pkg = ROOT / "package.json"
        if pkg.exists():
            self.assertEqual(fm["version"], json.loads(pkg.read_text(encoding="utf-8"))["version"])
        for name in ("claude-code", "claude-ai"):
            tpl = json.loads((tpl_dir / f"{name}.json").read_text(encoding="utf-8"))["frontmatter"]
            for k in ("name", "description", "version"):
                self.assertEqual(str(tpl[k]), fm[k], (name, k))
            self.assertIs(tpl.get("user-invocable"), True, name)

    def test_links_resolve(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", text):
            if not target.startswith("http"):
                self.assertTrue((ROOT / target).exists(), target)

    def test_tools_named_in_skill_exist(self):
        text = SKILL_MD.read_text(encoding="utf-8")
        for name in set(re.findall(r"`([\w-]+\.(?:py|php|js|mjs))`", text)):
            hits = list(ROOT.glob(f"tools/{name}")) + list(ROOT.glob(f"bin/{name}"))
            if name == "install.mjs" and not (ROOT / "bin").exists():
                continue
            self.assertTrue(hits, name)

    def test_user_path_is_stdlib(self):
        stdlib = set(sys.stdlib_module_names) | {"__future__"}
        local = {p.stem for p in HERE.glob("*.py")} | {"save"}
        for name in ("gb.py", "gblib.py", "blockmark.py", "validate-post.py", "verify-live.py",
                     "el2blocks.py", "check_numbers.py", "provenance.py", "roundtrip-check.py",
                     "selftest-patterns.py", "test_gutenberg.py"):
            src = (HERE / name).read_text(encoding="utf-8")
            mods = re.findall(r"(?m)^\s*(?:import|from)\s+([A-Za-z_]\w*)", src)
            bad = sorted({m for m in mods if m not in stdlib and m not in local})
            self.assertEqual(bad, [], name)

    def test_requirements_list_maintainer_deps(self):
        req = ROOT / "requirements.txt"
        if not req.exists():
            self.skipTest("requirements.txt is a repo file")
        self.assertRegex(req.read_text(encoding="utf-8"), r"(?m)^tiktoken\b")


class Evals(unittest.TestCase):

    def test_cases_shape(self):
        f = ROOT / "evals" / "cases.json"
        self.assertTrue(f.exists(), "evals/cases.json missing")
        cases = [c for c in json.loads(f.read_text(encoding="utf-8"))["cases"] if not c.get("retired")]
        self.assertGreaterEqual(len(cases), 10)
        self.assertEqual(len({c["id"] for c in cases}), len(cases))
        for c in cases:
            for k in ("id", "question", "must", "source", "trust"):
                self.assertIn(k, c, c.get("id"))
            for group in c["must"]:
                for pat in group:
                    re.compile(pat)
                    self.assertNotIn("\x08", pat, c["id"])

    def test_results_recorded(self):
        f = ROOT / "evals" / "RESULTS.md"
        self.assertTrue(f.exists(), "evals/RESULTS.md missing")
        self.assertRegex(f.read_text(encoding="utf-8"), r"20\d\d-\d\d-\d\d")


if __name__ == "__main__":
    if "--live" in sys.argv:
        i = sys.argv.index("--live")
        LIVE_URL = sys.argv[i + 1]
        del sys.argv[i:i + 2]
    unittest.main(verbosity=2)
