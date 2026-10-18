#!/usr/bin/env python3
"""Offline checks for legal-research-skills. No credentials or network needed.

Runs every test_*.py as its own process (some are unittest modules, some are
standalone assertion scripts), compiles every Python file, checks every
relative Markdown link, validates SKILL.md frontmatter and Codex UI
metadata, and checks the Claude Code plugin manifests. Exits non-zero if anything fails.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SKIP_DIRS = {".git", ".codex-memo", "__pycache__", ".pytest_cache", "testdata", "node_modules"}
LINK_RE = re.compile(r"\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


def walk(suffixes: tuple[str, ...]) -> list[Path]:
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(suffixes):
                out.append(Path(dirpath) / name)
    return sorted(out)


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT))


def run_test_programs() -> list[str]:
    failures: list[str] = []
    tests = [p for p in walk((".py",)) if p.name.startswith("test_")]
    for test in tests:
        proc = subprocess.run(
            [sys.executable, str(test)],
            cwd=test.parent,
            capture_output=True,
            text=True,
        )
        status = "ok" if proc.returncode == 0 else f"FAILED (exit {proc.returncode})"
        print(f"  {status:22s} {rel(test)}")
        if proc.returncode != 0:
            tail = (proc.stdout + proc.stderr).strip().splitlines()[-15:]
            failures.append(f"{rel(test)}:\n    " + "\n    ".join(tail))
    print(f"  {len(tests)} test programs, {len(tests) - len(failures)} passed")
    return failures


def compile_python() -> list[str]:
    failures: list[str] = []
    files = walk((".py",))
    for f in files:
        try:
            ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        except SyntaxError as exc:
            failures.append(f"{rel(f)}:{exc.lineno}: {exc.msg}")
    print(f"  {len(files)} Python files compiled, {len(failures)} failed")
    return failures


def check_markdown_links() -> list[str]:
    failures: list[str] = []
    checked = 0
    for md in walk((".md",)):
        text = md.read_text(encoding="utf-8", errors="replace")
        for target in LINK_RE.findall(text):
            if re.match(r"^(https?:|mailto:|#)", target):
                continue
            path = target.split("#", 1)[0]
            if not path:
                continue
            checked += 1
            if not (md.parent / path).exists():
                failures.append(f"{rel(md)}: broken link {target}")
    print(f"  {checked} relative Markdown links checked, {len(failures)} broken")
    return failures


def check_frontmatter() -> list[str]:
    failures: list[str] = []
    skills = sorted(p for p in walk(("SKILL.md",)) if p.name == "SKILL.md")
    for skill in skills:
        lines = skill.read_text(encoding="utf-8").splitlines()
        if not lines or lines[0].strip() != "---":
            failures.append(f"{rel(skill)}: missing frontmatter")
            continue
        try:
            end = lines.index("---", 1)
        except ValueError:
            failures.append(f"{rel(skill)}: unterminated frontmatter")
            continue
        fields: dict[str, str] = {}
        for line in lines[1:end]:
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                fields[k.strip()] = v.strip()
        folder = skill.parent.name
        if fields.get("name") != folder:
            failures.append(f"{rel(skill)}: name {fields.get('name')!r} != folder {folder!r}")
        if len(fields.get("description", "")) < 20:
            failures.append(f"{rel(skill)}: description missing or too short")
        if len(lines) <= end + 1 or not any(l.strip() for l in lines[end + 1:]):
            failures.append(f"{rel(skill)}: no body after frontmatter")
    print(f"  {len(skills)} SKILL.md files checked, {len(failures)} problems")
    return failures


def check_plugin_manifests() -> list[str]:
    """The Claude Code side is a plugin: marketplace.json at the root, plugin.json in
    claude-code/, skills under claude-code/skills/, CHANGELOG's top entry matching
    the plugin version, and no stale ~/.claude/skills paths in skill text."""
    failures: list[str] = []
    try:
        market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
        plugin = json.loads((ROOT / "claude-code" / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"plugin manifests: {exc}"]
    entries = {e.get("name"): e for e in market.get("plugins", [])}
    if plugin.get("name") not in entries:
        failures.append(f"marketplace.json lists {sorted(entries)} but plugin.json is {plugin.get('name')!r}")
    else:
        src = entries[plugin["name"]].get("source")
        if src != "./claude-code":
            failures.append(f"marketplace entry source is {src!r}, expected './claude-code'")
        if "version" in entries[plugin["name"]]:
            failures.append("set version in plugin.json only, not in the marketplace entry")
    for key in ("name", "version", "description", "author"):
        if not plugin.get(key):
            failures.append(f"plugin.json: missing {key}")
    skills_dir = ROOT / "claude-code" / "skills"
    skills = sorted(p.name for p in skills_dir.iterdir() if (p / "SKILL.md").exists()) if skills_dir.is_dir() else []
    if len(skills) < 6:
        failures.append(f"claude-code/skills has {len(skills)} skills, expected at least 6")
    changelog = ROOT / "CHANGELOG.md"
    if changelog.exists():
        m = re.search(r"^## \[?v?(\d[^\]\s]*)", changelog.read_text(encoding="utf-8"), re.M)
        if not m:
            failures.append("CHANGELOG.md: no '## <version>' heading")
        elif m.group(1) != plugin.get("version"):
            failures.append(f"CHANGELOG.md top entry {m.group(1)} != plugin.json version {plugin.get('version')}")
    else:
        failures.append("CHANGELOG.md missing")
    stale = 0
    for f in walk((".md", ".js")):
        if "claude-code" in f.parts and "~/.claude/skills/" in f.read_text(encoding="utf-8", errors="replace"):
            failures.append(f"{rel(f)}: hard-coded ~/.claude/skills/ path; use ${{CLAUDE_PLUGIN_ROOT}}/skills/")
            stale += 1
    print(f"  plugin {plugin.get('name')} v{plugin.get('version')}: {len(skills)} skills, {stale} stale paths, {len(failures)} problems")
    return failures


def check_codex_ui_metadata() -> list[str]:
    failures: list[str] = []
    files = sorted(ROOT.glob("codex/*/agents/openai.yaml"))
    for f in files:
        text = f.read_text(encoding="utf-8")
        if not re.search(r"^interface:\s*$", text, re.M):
            failures.append(f"{rel(f)}: missing top-level 'interface:' block")
        for key in ("display_name", "short_description", "default_prompt"):
            if not re.search(rf"^\s+{key}:\s*\S", text, re.M):
                failures.append(f"{rel(f)}: missing interface.{key}")
    print(f"  {len(files)} Codex UI metadata files checked, {len(failures)} problems")
    return failures


def main() -> int:
    print(f"legal-research-skills checks (Python {sys.version.split()[0]})")
    all_failures: list[str] = []
    for title, fn in (
        ("Test programs", run_test_programs),
        ("Python compile", compile_python),
        ("Markdown links", check_markdown_links),
        ("SKILL.md frontmatter", check_frontmatter),
        ("Codex UI metadata", check_codex_ui_metadata),
        ("Plugin manifests", check_plugin_manifests),
    ):
        print(f"\n{title}")
        all_failures.extend(fn())
    print()
    if all_failures:
        print(f"FAILED: {len(all_failures)} problem(s)")
        for item in all_failures:
            print(f"- {item}")
        return 1
    print("All checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
