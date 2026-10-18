#!/usr/bin/env python3
"""Offline regression test for the require-pdfs completion gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("validate_run.py")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


class AttachmentGateTests(unittest.TestCase):
    def test_pdf_requirement_fails_closed_then_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary)
            item = {
                "itemType": "journalArticle",
                "title": "Example Article",
                "DOI": "10.1234/example",
                "collections": ["COLL1234"],
            }
            candidate = {
                "candidate_id": "c001",
                "decision": "add",
                "reason": "verified fixture",
                "item": item,
                "provenance": [{
                    "url": "https://example.test/article",
                    "source_type": "journal",
                    "accessed_at": "2026-07-16T10:00:00-07:00",
                    "fields": ["itemType", "title", "DOI"],
                }],
                "duplicate_check": {
                    "scope": "collection_and_library",
                    "queries": ["Example Article", "10.1234/example"],
                    "matches": [],
                    "decision": "unique",
                },
            }
            write_json(run_dir / "run.json", {
                "schema_version": 1,
                "request": "add article and PDF",
                "library": {"type": "user", "id": "123"},
                "collection": {"key": "COLL1234", "name": "Test"},
                "require_pdfs": True,
            })
            (run_dir / "candidates.jsonl").write_text(json.dumps(candidate) + "\n", encoding="utf-8")
            write_json(run_dir / "planned-items.json", [{"candidate_id": "c001", "item": item}])
            write_json(run_dir / "write-result.json", {
                "operation": "create-items",
                "request_count": 1,
                "candidate_ids": ["c001"],
                "request_sha256": hashlib.sha256(
                    json.dumps([item], sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest(),
                "successful": {"0": {"key": "ABCD2345"}},
                "unchanged": {},
                "failed": {},
            })
            write_json(run_dir / "verification.json", {
                "results": [{"key": "ABCD2345", "verdict": "PASS"}]
            })
            for name in ("manual-verifications.jsonl", "reuse-results.jsonl", "attachment-results.jsonl"):
                (run_dir / name).write_text("", encoding="utf-8")

            failed = subprocess.run(
                [sys.executable, str(SCRIPT), str(run_dir), "--require-ready"],
                capture_output=True, text=True,
            )
            self.assertNotEqual(failed.returncode, 0)
            self.assertIn("missing verified PDF attachments", failed.stdout)

            attachment = {
                "schema_version": 1,
                "status": "VERIFIED",
                "parent_item_key": "ABCD2345",
                "attachment_item_key": "WXYZ6789",
                "filename": "example.pdf",
                "content_type": "application/pdf",
                "size": 100,
                "md5": "a" * 32,
                "sha256": "b" * 64,
                "source_url": "https://heinonline.org/HOL/Page?handle=example",
                "source_mode": "file",
                "verified_at": "2026-07-16T10:01:00-07:00",
            }
            (run_dir / "attachment-results.jsonl").write_text(
                json.dumps(attachment) + "\n", encoding="utf-8"
            )
            passed = subprocess.run(
                [sys.executable, str(SCRIPT), str(run_dir), "--require-ready"],
                capture_output=True, text=True,
            )
            self.assertEqual(passed.returncode, 0, passed.stdout + passed.stderr)
            self.assertIn("READY", passed.stdout)


if __name__ == "__main__":
    unittest.main()
