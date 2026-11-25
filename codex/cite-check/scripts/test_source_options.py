#!/usr/bin/env python3
"""Synthetic source-choice, shared-setting, and project-persistence regressions."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from source_options import (PROJECT_FILE, discover_folders, materialize, plan_sources,
                            match_library, validate_plan)

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "run_tests.py").is_file())
SCRATCH = ROOT / ".codex-memo" / "amendment1-tests"
SCRATCH.mkdir(parents=True, exist_ok=True)
LIBRARIES = [{"id": "personal", "name": "Personal Library", "status": "available"},
             {"id": "group:2", "name": "Copper Lantern Project", "status": "available"},
             {"id": "group:3", "name": "5A Amber Project", "status": "available"}]


class SourceOptionsTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=SCRATCH))
        self.draft = self.root / "draft.md"; self.draft.write_text("Synthetic draft.\n")
        home = patch.dict(os.environ, {"HOME": str(self.root / "home")})
        home.start(); self.addCleanup(home.stop)
        self.config = Path.home() / ".config/legal-research/source-folder"
        self.project_file = self.root / PROJECT_FILE

    def folder(self, name):
        path = self.root / name; path.mkdir(exist_ok=True); return path

    def plan(self, **kw):
        return plan_sources(self.draft, **kw)

    def test_precedence_and_none_suppresses_every_fallback(self):
        default = self.folder("default")
        self.config.parent.mkdir(parents=True); self.config.write_text(str(default) + "\n")
        self.assertEqual(discover_folders(self.draft), ([default], "default"))
        beside = self.folder("sOuRcEs")
        self.assertEqual(discover_folders(self.draft), ([beside], "beside_draft"))
        project = self.folder("project-pdfs")
        self.project_file.write_text("Source folder: project-pdfs\n")
        self.assertEqual(discover_folders(self.draft), ([project], "project"))
        self.project_file.write_text("Source folder: none\n")
        self.assertEqual(discover_folders(self.draft), ([], "project_none"))
        explicit = self.folder("requested")
        self.assertEqual(discover_folders(self.draft, folders=[str(explicit)]), ([explicit], "request"))

    def test_native_project_file_precedes_other_runtime_file(self):
        other = self.root / ("CLAUDE.md" if PROJECT_FILE == "AGENTS.md" else "AGENTS.md")
        other.write_text("Source folder: shared\n")
        self.assertEqual(discover_folders(self.draft)[0], [self.root / "shared"])
        self.project_file.write_text("Source folder: native\n")
        self.assertEqual(discover_folders(self.draft)[0], [self.root / "native"])

    def test_no_library_still_discovers_folder_option_and_neither(self):
        plan = self.plan(libraries=[])
        self.assertEqual(plan["status"], "needs_choice")
        self.assertEqual([o["value"] for o in plan["question"]["options"]], ["folder", "web"])
        self.assertIn("remember", plan["question"]["save_offer"])
        self.assertIn("this run only", plan["question"]["save_offer"])
        self.assertFalse((self.root / "Sources").exists())

    def test_personal_library_does_not_hide_new_folder_choice(self):
        plan = self.plan(libraries=LIBRARIES[:1])
        self.assertEqual(plan["status"], "needs_choice")
        self.assertEqual(len(plan["question"]["options"]), 4)
        both = self.plan(libraries=LIBRARIES[:1], choices=["folder", "library:personal"])
        self.assertEqual(both["library_id"], "personal")
        self.assertEqual(both["folder_paths"], [str(self.root / "Sources")])

    def test_four_options_named_libraries_both_and_overflow_description(self):
        pending = self.plan(libraries=LIBRARIES)
        q = pending["question"]
        self.assertTrue(q["multiSelect"])
        self.assertEqual(len(q["options"]), 4)
        self.assertEqual([o["value"] for o in q["options"]], ["library:personal", "library:group:2", "folder", "web"])
        self.assertTrue(all(row["name"] in q["library_list"] for row in LIBRARIES))
        self.assertEqual(match_library("5A", LIBRARIES)["id"], "group:3")
        selected = self.plan(libraries=LIBRARIES, choices=["folder", "library:group:3"])
        self.assertEqual(selected["library_id"], "group:3")
        self.assertEqual(selected["status"], "ready")
        with self.assertRaises(ValueError):
            match_library("Project", LIBRARIES)

    def test_settled_folder_asks_only_unsettled_library(self):
        self.folder("Sources")
        plan = self.plan(libraries=LIBRARIES)
        self.assertIsNotNone(plan["question"])
        self.assertIsNone(plan["library_id"])
        self.assertEqual(plan["choice_scope"], ["library"])
        self.assertNotIn("folder", [o["value"] for o in plan["question"]["options"]])
        sole = self.plan(libraries=LIBRARIES[:1])
        self.assertEqual(sole["library_id"], "personal")

    def test_unavailable_saved_library_does_not_block_settled_folder(self):
        self.folder("Sources")
        self.project_file.write_text("Zotero library: missing-library\n")
        plan = self.plan(libraries=LIBRARIES)
        self.assertEqual(plan["status"], "needs_choice")
        self.assertEqual(plan["folder_origin"], "beside_draft")
        self.assertEqual(plan["choice_scope"], ["library"])
        self.assertIn("Saved Zotero library cannot be used", plan["warnings"][0])
        with self.assertRaises(ValueError):
            validate_plan(plan)
        with self.assertRaises(ValueError):
            self.plan(libraries=LIBRARIES, library="missing-library")

    def test_folder_answer_creates_only_on_apply_and_can_remember_both(self):
        self.project_file.write_text("# Project\nKeep this instruction verbatim.\n")
        plan = self.plan(libraries=LIBRARIES, choices=["folder", "library:group:2"])
        validate_plan(plan)
        self.assertFalse((self.root / "Sources").exists())
        materialize(plan, remember=True)
        self.assertTrue((self.root / "Sources").is_dir())
        saved = self.project_file.read_text()
        self.assertTrue(saved.startswith("# Project\nKeep this instruction verbatim.\n"))
        self.assertIn("Source folder: " + str(self.root / "Sources"), saved)
        again = self.plan(libraries=LIBRARIES)
        self.assertIsNone(again["question"])
        self.assertEqual(again["library_id"], "group:2")

    def test_neither_is_remembered_even_with_available_zotero(self):
        plan = self.plan(libraries=LIBRARIES, choices=["web"])
        materialize(plan, remember=True)
        self.assertEqual(self.project_file.read_text(), "Source folder: none\nZotero library: none\n")
        self.folder("Sources")
        again = self.plan(libraries=LIBRARIES)
        self.assertEqual(again["folder_paths"], [])
        self.assertTrue(again["skip_zotero"])
        self.assertIsNone(again["question"])

    def test_zotero_only_and_folder_only_persist_distinct_answers(self):
        only = self.plan(libraries=LIBRARIES, choices=["library:group:2"])
        materialize(only, remember=True)
        self.assertIn("Source folder: none", self.project_file.read_text())
        folder = self.plan(libraries=LIBRARIES, choices=["folder"])
        materialize(folder, remember=True)
        # Amendment 2: the later folder-only answer must preserve the saved library.
        self.assertIn("Zotero library: Copper Lantern Project", self.project_file.read_text())
        self.assertEqual(folder["library_id"], "group:2")
        self.assertEqual(self.project_file.read_text().count("Source folder:"), 1)

    def test_run_only_does_not_save_and_headless_does_not_create(self):
        plan = self.plan(libraries=[], choices=["folder"])
        materialize(plan)
        self.assertFalse(self.project_file.exists())
        elsewhere = self.folder("another-project") / "draft.md"; elsewhere.write_text("Synthetic")
        headless = plan_sources(elsewhere, libraries=LIBRARIES, headless=True)
        materialize(headless)
        self.assertEqual(headless["folder_origin"], "headless_skip")
        self.assertFalse((elsewhere.parent / "Sources").exists())
        self.assertIsNone(headless["question"])
        with self.assertRaises(ValueError):
            materialize(headless, remember=True)

    def test_pending_forged_or_contradictory_selections_are_rejected(self):
        pending = self.plan(libraries=[])
        with self.assertRaises(ValueError):
            materialize(pending)
        pending.update(status="ready", question=None)
        with self.assertRaises(ValueError):
            validate_plan(pending)
        for choices in (["web", "folder"], ["library:personal", "library:group:2"], [], ["folder", "folder"]):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                self.plan(libraries=LIBRARIES, choices=choices)
        with self.assertRaises(ValueError):
            self.plan(libraries=[dict(LIBRARIES[0], env={"secret": "synthetic"})])

    def test_no_zotero_hides_library_options_but_not_folder_question(self):
        plan = self.plan(libraries=LIBRARIES, no_zotero=True)
        self.assertEqual([o["value"] for o in plan["question"]["options"]], ["folder", "web"])

    def test_missing_default_is_settled_and_malformed_default_is_not_used(self):
        self.config.parent.mkdir(parents=True)
        missing = self.root / "moved-folder"
        self.config.write_text(str(missing) + "\n")
        plan = self.plan(libraries=[])
        self.assertIsNone(plan["question"])
        self.assertEqual(plan["folder_paths"], [str(missing)])
        self.config.write_text("relative-path\n")
        with self.assertRaises(ValueError):
            self.plan(libraries=[])

    def test_unavailable_library_and_string_headless_cannot_bypass_choice(self):
        libs = LIBRARIES + [{"id": "offline", "name": "Offline Library", "status": "unavailable", "reason": "Synthetic unavailable connector"}]
        self.assertNotIn("library:offline", [o["value"] for o in self.plan(libraries=libs)["question"]["options"]])
        with self.assertRaises(ValueError):
            self.plan(libraries=libs, choices=["library:offline"])
        with self.assertRaises(ValueError):
            self.plan(libraries=[], headless="false")

    def test_folder_choice_never_overwrites_a_file_called_sources(self):
        path = self.root / "Sources"; path.write_text("Preserve this synthetic file.")
        plan = self.plan(libraries=[], choices=["folder"])
        with self.assertRaises(OSError):
            materialize(plan, remember=True)
        self.assertEqual(path.read_text(), "Preserve this synthetic file.")
        self.assertFalse(self.project_file.exists())

    def test_shared_setup_saves_only_a_path_and_status_reports_it(self):
        folder = self.folder("central-pdfs")
        sentinel = folder / "unindexed.txt"; sentinel.write_text("Synthetic content, not a setting.")
        env = {k: v for k, v in os.environ.items() if k not in {"COURTLISTENER_API_TOKEN", "COURTLISTENER_TOKEN"}}
        setup = ROOT / "claude-code/skills/setup/setup.py"
        saved = subprocess.run([sys.executable, str(setup), "source-folder", str(folder)], env=env, capture_output=True, text=True)
        self.assertEqual(saved.returncode, 0, saved.stderr)
        self.assertEqual(self.config.read_text(), str(folder) + "\n")
        self.assertFalse((Path.home() / ".claude").exists())
        status = subprocess.run([sys.executable, str(setup), "status"], env=env, capture_output=True, text=True)
        self.assertEqual(status.returncode, 0, status.stderr)
        self.assertEqual(json.loads(status.stdout)["source_folder"]["path"], str(folder))
        self.assertEqual(self.plan(libraries=[])["folder_origin"], "default")
        self.assertEqual(sentinel.read_text(), "Synthetic content, not a setting.")

    def test_full_picker_has_four_questions_and_guards_pending_sources(self):
        from extract_cites import extract_document
        from prepare_run_options import prepare_options, resolved_selection
        self.draft.write_text(" ".join(f"Statement.[^{i}]" for i in range(1, 37)) + "\n\n" +
                              "\n".join(f"[^{i}]: Mina Vale, Copper Lanterns (2024)." for i in range(1, 37)))
        extraction = extract_document(self.draft)
        plan = prepare_options(extraction, libraries=LIBRARIES, source_plan=self.plan(libraries=LIBRARIES))
        self.assertEqual([q["id"] for q in plan["questions"]], ["coverage", "depth", "support", "sources"])
        self.assertTrue(all(len(q["options"]) <= 4 for q in plan["questions"]))
        plan["status"], plan["questions"] = "ready", []
        with self.assertRaises(ValueError):
            resolved_selection(plan, extraction["input_sha256"])

    def test_cli_preserves_public_descriptions_through_library_validation(self):
        libraries = self.root / "libraries.json"
        rows = copy.deepcopy(LIBRARIES)
        rows[2]["description"] = "Amber research with Avery"
        libraries.write_text(json.dumps(rows))
        preview = self.root / "preview.json"
        result = subprocess.run([sys.executable, str(HERE / "prepare_run_options.py"),
                    str(self.draft), "--libraries", str(libraries), "--library", "with Avery", "--source-choice", "web",
                    "--coverage", "all", "--depth", "standard", "--support", "off",
                    "--output", str(preview)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(preview.read_text())
        from prepare_run_options import resolved_selection
        resolved_selection(plan, plan["draft_sha256"])
        self.assertEqual(plan["library_access"]["selection"]["id"], "group:3")
        self.assertEqual(plan["source_access"]["library_id"], "group:3")

    def test_cli_handoff_creates_and_saves_then_freezes_folder(self):
        citation = "Mina Vale, Copper Lanterns and Silent Rivers (2024)."
        self.draft.write_text("Synthetic claim.[^1]\n\n[^1]: " + citation)
        preview, run = self.root / "preview.json", self.root / "run"
        def script(name, *args):
            return subprocess.run([sys.executable, str(HERE / name), *map(str, args)], capture_output=True, text=True)
        result = script("prepare_run_options.py", self.draft, "--output", preview, "--coverage", "all",
                        "--depth", "standard", "--support", "off", "--source-choice", "folder", "--remember-sources")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / "Sources").exists())
        result = script("init_run.py", self.draft, "--run-dir", run, "--options", preview)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.root / "Sources").is_dir())
        self.assertIn("Source folder:", self.project_file.read_text())
        (self.root / "Sources" / "copy.txt").write_text("Copper Lanterns and Silent Rivers\nMina Vale\nWorking paper (2024)\nInvented text.")
        (run / "source-ledger.jsonl").write_text(json.dumps({"source_id": "S1", "source_type": "book",
                "canonical_citation": citation, "status": "unavailable", "verification_basis": "unavailable"}) + "\n")
        self.project_file.write_text("Source folder: none\nZotero library: none\n")
        result = script("local_lookup.py", run, "--apply")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((run / "local-lookup.json").read_text())["stats"]["matched"], 1)
        manifest_path = run / "run-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["source_access"], json.loads(preview.read_text())["source_access"])
        manifest["source_access"]["folder_paths"] = []
        manifest_path.write_text(json.dumps(manifest))
        result = script("validate_run.py", run)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("resolved source-folder choice", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
