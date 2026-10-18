#!/usr/bin/env python3
"""Offline tests for Zotero attachment filename generation."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).with_name("attach_pdf.py")
SPEC = importlib.util.spec_from_file_location("attach_pdf", SCRIPT)
assert SPEC and SPEC.loader
ATTACH_PDF = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ATTACH_PDF)


class AttachmentFilenameTests(unittest.TestCase):
    def test_uses_author_year_and_title(self) -> None:
        item = {
            "itemType": "journalArticle",
            "title": "Rules/Standards: A “New” Account?",
            "date": "2024-05",
            "creators": [
                {"creatorType": "author", "firstName": "Jane", "lastName": "D’Onfro"},
                {"creatorType": "author", "firstName": "Daniel", "lastName": "Epps"},
            ],
        }
        self.assertEqual(
            ATTACH_PDF.attachment_filename(item, "opaque-download.pdf"),
            "D’Onfro & Epps - 2024 - Rules Standards A “New” Account.pdf",
        )

    def test_prefers_authors_over_other_contributors(self) -> None:
        item = {
            "title": "Example",
            "date": "Spring 1998",
            "creators": [
                {"creatorType": "author", "lastName": "Writer"},
                {"creatorType": "translator", "lastName": "Translator"},
                {"creatorType": "editor", "lastName": "Editor"},
            ],
        }
        self.assertEqual(
            ATTACH_PDF.attachment_filename(item, "download.pdf"),
            "Writer - 1998 - Example.pdf",
        )

    def test_uses_et_al_for_three_primary_creators(self) -> None:
        item = {
            "title": "Many Hands",
            "date": "2020",
            "creators": [
                {"creatorType": "author", "lastName": "Alpha"},
                {"creatorType": "author", "lastName": "Beta"},
                {"creatorType": "author", "lastName": "Gamma"},
            ],
        }
        self.assertEqual(
            ATTACH_PDF.attachment_filename(item, "download.pdf"),
            "Alpha et al. - 2020 - Many Hands.pdf",
        )

    def test_falls_back_and_sanitizes_explicit_filename(self) -> None:
        self.assertEqual(
            ATTACH_PDF.attachment_filename({}, "../captured:file.PDF"),
            "captured file.pdf",
        )
        self.assertEqual(
            ATTACH_PDF.normalize_pdf_filename('  A/B: "Title".PDF  '),
            "A B Title.pdf",
        )

    def test_limits_utf8_filename_size(self) -> None:
        filename = ATTACH_PDF.attachment_filename(
            {"title": "É" * 200, "date": "2026"},
            "download.pdf",
        )
        self.assertLessEqual(len(filename.encode("utf-8")), ATTACH_PDF.MAX_FILENAME_BYTES)
        self.assertTrue(filename.endswith(".pdf"))


if __name__ == "__main__":
    unittest.main()
