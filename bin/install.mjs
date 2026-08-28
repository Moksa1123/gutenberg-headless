#!/usr/bin/env node
/**
 * Install the gutenberg-headless skill into any of 8 supported AI platforms.
 *
 *   npx gutenberg-headless --list
 *   npx gutenberg-headless claude-code --global
 *   npx gutenberg-headless cursor --to /path/to/project
 *   npx gutenberg-headless --dry-run claude-code
 *
 * Pure Node port of tools/install-skill.py (same platform configs, same
 * strategies, same stale-file pruning). Python is NOT needed to install -
 * only to run the skill's query/validation tools afterwards.
 *
 * Install types:
 *   full                - SKILL.md + references/ + tools/ + data/ + examples/
 *   rule                - single .md/.mdc rule file with embedded references
 *   instructions-append - fenced section appended to copilot-instructions.md
 *   zip-upload          - zip bundle for manual upload (Claude.ai)
 *
 * Exit codes: 0 = installed, 1 = failed, 2 = invocation error
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const PLATFORMS = path.join(ROOT, "assets", "templates", "platforms");

const die = (msg, code = 1) => { console.error(msg); process.exit(code); };
const expand = (p) => (p && p.startsWith("~") ? path.join(os.homedir(), p.slice(1)) : p);

function listPlatforms() {
  return fs.readdirSync(PLATFORMS).filter((f) => f.endsWith(".json")).sort()
    .map((f) => JSON.parse(fs.readFileSync(path.join(PLATFORMS, f), "utf8")));
}

function loadPlatform(name) {
  const p = path.join(PLATFORMS, `${name}.json`);
  if (!fs.existsSync(p)) die(`Unknown platform: ${name}\nRun --list to see options.`, 2);
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function buildFrontmatter(fm) {
  if (!fm) return "";
  const lines = ["---"];
  for (const [k, v] of Object.entries(fm)) {
    if (v === null || v === undefined) continue;
    if (Array.isArray(v)) lines.push(`${k}: [${v.map((x) => JSON.stringify(x)).join(", ")}]`);
    else if (typeof v === "boolean") lines.push(`${k}: ${v}`);
    else if (typeof v === "string" && (v.includes("\n") || v.length > 100)) {
      lines.push(`${k}: |`);
      for (const sub of v.split("\n")) lines.push(`  ${sub}`);
    } else lines.push(`${k}: ${JSON.stringify(v)}`);
  }
  lines.push("---");
  return lines.join("\n") + "\n\n";
}

function readSkillBody() {
  let raw = fs.readFileSync(path.join(ROOT, "SKILL.md"), "utf8");
  if (raw.startsWith("---")) {
    const end = raw.indexOf("\n---", 3);
    if (end !== -1) raw = raw.slice(end + 4).replace(/^\n+/, "");
  }
  return raw;
}

function embedReferences(names) {
  // A missing file is a hard error, not a skip - silently shipping a rule file
  // short one document is the silent-failure class this skill exists to kill.
  const parts = [];
  for (const n of names) {
    const p = path.join(ROOT, "references", n);
    if (!fs.existsSync(p)) {
      const avail = fs.readdirSync(path.join(ROOT, "references")).filter((q) => q.endsWith(".md")).join(", ");
      die(`Platform config asks to embed references/${n}, which does not exist.\nAvailable: ${avail}`);
    }
    parts.push(`\n\n---\n\n## Reference: ${n}\n\n${fs.readFileSync(p, "utf8")}\n`);
  }
  return parts.join("");
}

function walkFiles(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.name === "__pycache__") continue;
    if (e.isDirectory()) out.push(...walkFiles(p));
    else out.push(p);
  }
  return out;
}

function copySection(sec, dstRoot, force) {
  // Upgrades MUST delete what the previous version left behind: a stale, wrong
  // dataset sitting next to the right one is worse than no installer.
  const srcPath = path.join(ROOT, sec);
  if (!fs.existsSync(srcPath)) return [0, 0];
  let copied = 0;
  const keep = new Set();
  for (const f of walkFiles(srcPath)) {
    const rel = path.relative(srcPath, f);
    const target = path.join(dstRoot, sec, rel);
    keep.add(path.resolve(target));
    fs.mkdirSync(path.dirname(target), { recursive: true });
    if (fs.existsSync(target) && !force) continue;
    fs.copyFileSync(f, target);
    copied++;
  }
  let pruned = 0;
  const secDir = path.join(dstRoot, sec);
  if (fs.existsSync(secDir)) {
    for (const f of walkFiles(secDir)) {
      if (!keep.has(path.resolve(f))) { fs.unlinkSync(f); pruned++; }
    }
  }
  return [copied, pruned];
}

// ---------- strategies -----------------------------------------------------

function installFull(cfg, root, force, dry) {
  const fsr = cfg.folderStructure;
  const dir = path.join(root, fsr.skillPath);
  const file = path.join(dir, fsr.filename);
  const content = buildFrontmatter(cfg.frontmatter) + readSkillBody();
  const plan = { file, size: content.length, sections: [] };
  if (dry) {
    for (const s of ["references", "tools", "data", "examples"]) if (cfg.sections?.[s]) plan.sections.push(s);
    return plan;
  }
  fs.mkdirSync(dir, { recursive: true });
  if (fs.existsSync(file) && !force) die(`Refusing to overwrite ${file} - pass --force.`);
  fs.writeFileSync(file, content);
  for (const s of ["references", "tools", "data", "examples"]) {
    if (!cfg.sections?.[s]) continue;
    const [n, pruned] = copySection(s, dir, force);
    plan.sections.push(`${s} (${n} files${pruned ? `, ${pruned} stale removed` : ""})`);
  }
  return plan;
}

function installRule(cfg, root, force, dry) {
  const fsr = cfg.folderStructure;
  const file = path.join(root, fsr.skillPath, fsr.filename);
  let body = readSkillBody();
  if (cfg.embedReferences) body += embedReferences(cfg.embedReferences);
  const content = buildFrontmatter(cfg.frontmatter) + body;
  const plan = { file, size: content.length, embedded: cfg.embedReferences || [] };
  if (dry) return plan;
  fs.mkdirSync(path.dirname(file), { recursive: true });
  if (fs.existsSync(file) && !force) die(`Refusing to overwrite ${file} - pass --force.`);
  fs.writeFileSync(file, content);
  return plan;
}

function installAppend(cfg, root, force, dry) {
  const fsr = cfg.folderStructure;
  const target = path.join(root, fsr.projectRoot, fsr.filename);
  const { appendMarker: begin, appendMarkerEnd: end } = cfg;
  let body = readSkillBody();
  if (cfg.embedReferences) body += embedReferences(cfg.embedReferences);
  const section = `\n\n${begin}\n## Headless Gutenberg Skill\n\n${body}\n${end}\n`;
  const existing = fs.existsSync(target) ? fs.readFileSync(target, "utf8") : "";
  let content;
  if (existing.includes(begin) && existing.includes(end)) {
    const before = existing.split(begin)[0].replace(/\s+$/, "");
    const after = existing.split(end).slice(1).join(end).replace(/^\s+/, "");
    content = (before + "\n" + after).trim() + section;
  } else {
    content = (existing.replace(/\s+$/, "") + section).replace(/^\n+/, "");
  }
  const plan = { file: target, size: content.length, appended: true };
  if (dry) return plan;
  fs.mkdirSync(path.dirname(target), { recursive: true });
  fs.writeFileSync(target, content);
  return plan;
}

function installZip(cfg, root, force, dry) {
  // Node has no built-in zip. Stage the folder, then use whatever archiver the
  // OS has; if none, the staged folder + instructions are the result.
  const fsr = cfg.folderStructure;
  const outZip = path.join(root, fsr.skillPath);
  const stage = path.join(root, "gutenberg-headless-stage", "gutenberg-headless");
  const plan = { file: outZip, size: 0, entries: [] };
  if (dry) { plan.entries.push("SKILL.md + sections (staged, then zipped)"); return plan; }
  fs.rmSync(path.dirname(stage), { recursive: true, force: true });
  fs.mkdirSync(stage, { recursive: true });
  fs.writeFileSync(path.join(stage, "SKILL.md"), buildFrontmatter(cfg.frontmatter) + readSkillBody());
  for (const s of ["references", "data", "examples"]) {
    if (cfg.sections?.[s]) copySection(s, stage, true);
  }
  if (fs.existsSync(outZip) && !force) die(`Refusing to overwrite ${outZip} - pass --force.`);
  fs.mkdirSync(path.dirname(outZip), { recursive: true });
  try {
    if (process.platform === "win32") {
      execFileSync("powershell", ["-NoProfile", "-Command",
        `Compress-Archive -Path '${stage}' -DestinationPath '${outZip}' -Force`]);
    } else {
      execFileSync("zip", ["-qr", outZip, "gutenberg-headless"], { cwd: path.dirname(stage) });
    }
    fs.rmSync(path.dirname(stage), { recursive: true, force: true });
    plan.size = fs.statSync(outZip).size;
  } catch {
    plan.file = path.dirname(stage);
    plan.note = `no zip tool found - folder staged at ${path.dirname(stage)}; zip it manually`;
  }
  return plan;
}

const STRATEGIES = {
  full: installFull, rule: installRule,
  "instructions-append": installAppend, "zip-upload": installZip,
};

// ---------- CLI ------------------------------------------------------------

function cmdList() {
  const rows = listPlatforms();
  console.log(`${"platform".padEnd(14)} ${"install type".padEnd(22)} verified  as-of        display name`);
  console.log("-".repeat(90));
  for (const c of rows) {
    console.log(`${c.platform.padEnd(14)} ${c.installType.padEnd(22)} ${(c.verified ? "yes" : "no ").padEnd(8)}  ${(c.verifiedAsOf || "?").padEnd(12)} ${c.displayName}`);
  }
}

function cmdInfo(name) {
  const c = loadPlatform(name);
  const f = c.folderStructure;
  console.log(`Platform: ${c.platform}  (${c.displayName})`);
  console.log(`Install type: ${c.installType}`);
  console.log(`Project path: ${[f.projectRoot, f.skillPath, f.filename].filter(Boolean).join("/")}`);
  if (f.globalRoot) console.log(`Global path:  ${[f.globalRoot, f.skillPath, f.filename].filter(Boolean).join("/")}`);
  console.log(`Verified: ${!!c.verified} (as of ${c.verifiedAsOf || "unknown"})`);
  console.log(`\n${c.loaderBehaviour}`);
}

function main() {
  const argv = process.argv.slice(2);
  const flags = new Set(argv.filter((a) => a.startsWith("--") || a === "-f"));
  const pos = argv.filter((a) => !a.startsWith("-") && argv[argv.indexOf(a) - 1] !== "--to" && argv[argv.indexOf(a) - 1] !== "--info");
  const getOpt = (name) => { const i = argv.indexOf(name); return i !== -1 ? argv[i + 1] : null; };

  if (flags.has("--list")) return cmdList();
  if (getOpt("--info")) return cmdInfo(getOpt("--info"));
  const name = pos[0];
  if (!name) { cmdList(); console.log("\nUsage: npx gutenberg-headless <platform> [--global] [--to DIR] [--force] [--dry-run]"); return; }

  const cfg = loadPlatform(name);
  const fsr = cfg.folderStructure;
  const dry = flags.has("--dry-run");
  const force = flags.has("--force") || flags.has("-f");
  let root = getOpt("--to") ? path.resolve(expand(getOpt("--to"))) : null;
  if (!root) {
    if (flags.has("--global") && fsr.globalRoot) root = expand(fsr.globalRoot);
    else if (cfg.installType === "instructions-append") root = process.cwd();
    else root = path.join(process.cwd(), fsr.projectRoot || "");
  }

  console.log(`Installing gutenberg-headless -> ${cfg.displayName}${dry ? " (DRY RUN)" : ""}`);
  console.log(`Target root: ${root}`);
  const plan = STRATEGIES[cfg.installType](cfg, root, force, dry);
  console.log(`  file: ${plan.file}`);
  console.log(`  size: ${plan.size.toLocaleString()} bytes`);
  if (plan.sections?.length) console.log(`  sections: ${plan.sections.join(", ")}`);
  if (plan.embedded?.length) console.log(`  embedded refs: ${plan.embedded.join(", ")}`);
  if (plan.note) console.log(`  NOTE: ${plan.note}`);
  console.log(`\n${cfg.loaderBehaviour}`);
  if (dry) console.log("\n(dry run; nothing written.)");
}

main();
