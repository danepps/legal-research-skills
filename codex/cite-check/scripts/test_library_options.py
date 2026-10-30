#!/usr/bin/env python3
"""Offline library selection, disclosure, and run-handoff regressions."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extract_cites import extract_document
from library_options import library_options, validate_library_access, match_library
from prepare_run_options import prepare_options, resolved_selection
from prepare_source_bundle import build_bundle

HERE = Path(__file__).resolve().parent
LIBRARIES = [
    {"id": "user:1", "name": "Personal Library", "status": "available"},
    {"id": "group:2", "name": "Federal Criminal Common Law", "status": "available"},
    {"id": "group:3", "name": "5A General Law", "status": "available"},
    {"id": "offline", "name": "Offline Library", "status": "unavailable",
     "reason": "The connection is disabled; reconnect it or supply PDFs."},
]


class LibraryTests(unittest.TestCase):
    def test_real_names_and_short_digit_tokens_resolve_all_listed_libraries(self):
        for query, expected in (("5A", "group:3"), ("5A library", "group:3"),
                                ("criminal law", "group:2"), ("Personal Library", "user:1"),
                                ("group:2", "group:2")):
            with self.subTest(query=query):
                self.assertEqual(match_library(query, LIBRARIES)["id"], expected)
        access, question = library_options(LIBRARIES)
        self.assertEqual(access["selection"]["status"], "needs_choice")
        self.assertEqual(len(question["options"]), 3)
        self.assertIn("5A General Law [group:3]", question["title"])
        self.assertNotIn("Offline Library", question["title"])
        self.assertIn("Offline Library", access["warnings"][0])
        self.assertEqual(question["options"][-1]["label"], "No Zotero this run")

    def test_ambiguity_and_unavailable_requests_do_not_select_another_library(self):
        for query in ("law", "xy", "unknown", "Offline Library"):
            with self.subTest(query=query), self.assertRaises(ValueError):
                library_options(LIBRARIES, library=query, defaults=True)
        duplicates = [dict(row, name="Shared Name") for row in LIBRARIES[:2]]
        with self.assertRaises(ValueError):
            match_library("Shared Name", duplicates)
        self.assertEqual(match_library("user:1", duplicates)["id"], "user:1")

    def test_unknown_absent_unavailable_and_explicit_skip_are_distinct(self):
        for inventory, expected in ((None, "not_assessed"), ([], "none_available"),
                                    (LIBRARIES[-1:], "none_available")):
            access, question = library_options(inventory)
            self.assertEqual(access["selection"]["status"], expected)
            self.assertIsNone(question)
            validate_library_access(access)
        self.assertTrue(library_options(LIBRARIES[-1:])[0]["warnings"])
        skipped, question = library_options(LIBRARIES, no_zotero=True)
        self.assertEqual(skipped["selection"]["status"], "skipped")
        self.assertIsNone(question)
        self.assertTrue(skipped["warnings"])
        validate_library_access(skipped)

    def test_defaults_do_not_guess_among_multiple_libraries(self):
        access, question = library_options(LIBRARIES, defaults=True)
        self.assertEqual(access["selection"]["status"], "skipped")
        self.assertIsNone(question)
        self.assertIn("none selected", access["warnings"][-1])
        selected, _ = library_options(LIBRARIES, library="5A", defaults=True)
        self.assertEqual(selected["selection"]["id"], "group:3")
        validate_library_access(selected)
        # A tested desktop route needs no Web API credentials in this inventory.
        sole, _ = library_options([LIBRARIES[0], LIBRARIES[-1]])
        self.assertEqual(sole["selection"]["id"], "user:1")
        validate_library_access(sole)

    def test_bad_or_credential_bearing_inventory_is_rejected(self):
        for rows in ({}, [None], [dict(LIBRARIES[0], env={"ZOTERO_API_KEY": "secret"})],
                     [LIBRARIES[0], LIBRARIES[0]], [dict(LIBRARIES[0], status="unknown")],
                     [dict(LIBRARIES[-1], reason="")]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                library_options(rows)
        with self.assertRaises(ValueError):
            library_options(LIBRARIES, library="5A", no_zotero=True)

    def test_saved_pending_or_changed_selection_is_rejected(self):
        pending, _ = library_options(LIBRARIES)
        with self.assertRaises(ValueError):
            validate_library_access(pending)
        selected, _ = library_options(LIBRARIES, library="5A")
        selected["selection"]["id"] = "user:1"
        with self.assertRaises(ValueError):
            validate_library_access(selected)


class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.draft = self.root / "draft.md"
        self.draft.write_text("A claim.[^1]\n\n[^1]: Doe, Article (1900).\n")
        self.extraction = extract_document(self.draft)

    def test_short_run_still_resolves_library_and_forged_ready_cannot_bypass_it(self):
        plan = prepare_options(self.extraction, libraries=LIBRARIES)
        self.assertEqual([q["id"] for q in plan["questions"]], ["library"])
        self.assertEqual(plan["status"], "needs_choice")
        plan["status"], plan["questions"] = "ready", []
        with self.assertRaises(ValueError):
            resolved_selection(plan, self.extraction["input_sha256"])

    def test_scope_questions_and_library_question_fit_option_limits(self):
        ex = copy.deepcopy(self.extraction)
        ex["footnotes"] = [dict(ex["footnotes"][0], number=i) for i in range(1, 37)]
        plan = prepare_options(ex, libraries=LIBRARIES)
        self.assertEqual([q["id"] for q in plan["questions"]], ["coverage", "depth", "support", "library"])
        self.assertTrue(all(len(q["options"]) <= 3 for q in plan["questions"]))

    def test_cli_cannot_overwrite_its_library_inventory(self):
        path = self.root / "libraries.json"
        path.write_text(json.dumps(LIBRARIES))
        original = path.read_bytes()
        proc = subprocess.run([sys.executable, str(HERE / "prepare_run_options.py"), str(self.draft),
                               "--output", str(path), "--libraries", str(path), "--library", "5A"],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(path.read_bytes(), original)

    def test_cli_initialization_validation_and_packet_preserve_chosen_library(self):
        inventory = self.root / "libraries.json"
        inventory.write_text(json.dumps(LIBRARIES))
        preview = self.root / "preview.json"
        run = self.root / "run"
        proc = subprocess.run([sys.executable, str(HERE / "prepare_run_options.py"), str(self.draft),
                               "--output", str(preview), "--libraries", str(inventory), "--library", "5A"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        plan = json.loads(preview.read_text())
        self.assertEqual(plan["status"], "ready")
        proc = subprocess.run([sys.executable, str(HERE / "init_run.py"), str(self.draft),
                               "--run-dir", str(run), "--options", str(preview)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest_path = run / "run-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        self.assertEqual(manifest["library_access"], plan["library_access"])
        (run / "citation-units.jsonl").write_text(json.dumps({"unit_id": "U1", "source_id": "S1",
                                                            "footnote_number": 1}) + "\n")
        packet = build_bundle(run, "S1")
        self.assertEqual(packet["library_selection"]["id"], "group:3")
        self.assertNotIn("libraries", packet)
        manifest["library_access"], _ = library_options(LIBRARIES, library="user:1")
        manifest_path.write_text(json.dumps(manifest))
        proc = subprocess.run([sys.executable, str(HERE / "validate_run.py"), str(run)],
                              capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("resolved library choice", proc.stdout + proc.stderr)


if __name__ == "__main__":
    unittest.main()
