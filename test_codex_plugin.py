#!/usr/bin/env python3
"""Offline packaging checks for the Codex-only research plugin."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PACKAGE = ROOT / "codex"
MANIFEST = PACKAGE / ".codex-plugin" / "plugin.json"
MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
EXPECTED_SKILLS = {
    "build-zotero-library", "cite-check", "deep-research", "find-cite",
    "internal-proofread", "legal-research-memo",
}


class CodexPluginTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.marketplace = json.loads(MARKETPLACE.read_text(encoding="utf-8"))

    def test_marketplace_resolves_only_the_codex_package(self) -> None:
        self.assertEqual(self.marketplace["name"], "danepps-legal-research-codex")
        self.assertEqual(len(self.marketplace["plugins"]), 1)
        entry = self.marketplace["plugins"][0]
        self.assertEqual(entry["name"], self.manifest["name"])
        self.assertEqual(entry["source"], {"source": "local", "path": "./codex"})
        self.assertEqual((ROOT / entry["source"]["path"]).resolve(), PACKAGE.resolve())
        self.assertEqual(entry["policy"], {
            "installation": "AVAILABLE", "authentication": "ON_USE",
        })
        self.assertEqual(entry["category"], "Productivity")

    def test_manifest_lists_every_skill_once(self) -> None:
        paths = self.manifest["skills"]
        self.assertIsInstance(paths, list)
        self.assertEqual(len(paths), len(set(paths)))
        self.assertEqual(set(paths), {f"./{name}" for name in EXPECTED_SKILLS})
        discovered = {p.parent.name for p in PACKAGE.glob("*/SKILL.md")}
        self.assertEqual(discovered, EXPECTED_SKILLS)
        for relative in paths:
            self.assertTrue(relative.startswith("./"))
            self.assertNotIn("..", Path(relative).parts)
            skill = PACKAGE / relative / "SKILL.md"
            self.assertTrue(skill.is_file(), relative)
            self.assertTrue(skill.resolve().is_relative_to(PACKAGE.resolve()))

    def test_manifest_identity_and_invocations(self) -> None:
        self.assertEqual(self.manifest["name"], "legal-research")
        self.assertRegex(self.manifest["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(self.manifest["author"]["name"], "Daniel Epps")
        self.assertEqual(self.manifest["license"], "MIT")
        self.assertEqual((PACKAGE / "LICENSE").read_bytes(), (ROOT / "LICENSE").read_bytes())
        interface = self.manifest["interface"]
        self.assertTrue(interface["displayName"])
        self.assertTrue(interface["shortDescription"])
        self.assertNotIn("mcpServers", self.manifest)
        self.assertNotIn("hooks", self.manifest)
        self.assertNotIn("apps", self.manifest)
        for prompt in interface["defaultPrompt"]:
            names = re.findall(r"\$legal-research:([a-z-]+)", prompt)
            self.assertTrue(names, prompt)
            self.assertTrue(set(names).issubset(EXPECTED_SKILLS), prompt)

    def test_package_survives_copy_without_repository_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "installed-plugin"
            shutil.copytree(PACKAGE, copied, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            manifest = json.loads((copied / ".codex-plugin/plugin.json").read_text())
            for relative in manifest["skills"]:
                folder = copied / relative
                self.assertTrue((folder / "SKILL.md").is_file())
                self.assertTrue((folder / "agents/openai.yaml").is_file())
                self.assertTrue(any((folder / "scripts").glob("*.py")))
                for path in folder.rglob("*"):
                    self.assertFalse(path.is_symlink(), str(path))
            self.assertFalse((copied / "claude-code").exists())
            self.assertFalse((copied / "build-zotero-library/assets/browser-companion").exists())


if __name__ == "__main__":
    unittest.main()
