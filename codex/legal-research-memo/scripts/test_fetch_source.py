#!/usr/bin/env python3
"""Offline tests for the bounded source fetcher; no network or credentials."""
from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import fetch_source


class Response(io.BytesIO):
    headers = {"Content-Type": "text/html"}

    def geturl(self) -> str:
        return "https://example.test/canonical"


class FetchSourceTests(unittest.TestCase):
    def test_html_retains_substantive_asides_and_output_is_exclusive(self) -> None:
        body = b"<h1>Authority</h1><p>Rule.</p><aside>Footnote limitation.</aside><script>ignore()</script>"
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "S1.txt"
            stdout = io.StringIO()
            with patch.object(fetch_source.urllib.request, "urlopen", return_value=Response(body)), redirect_stdout(stdout):
                self.assertEqual(fetch_source.main(["https://example.test/source", "--out", str(output)]), 0)
            record = json.loads(stdout.getvalue())
            self.assertTrue(record["complete_text"])
            self.assertEqual(record["final_url"], "https://example.test/canonical")
            self.assertEqual(len(record["source_sha256"]), 64)
            self.assertIn("Footnote limitation.", output.read_text())
            self.assertNotIn("ignore()", output.read_text())
            self.assertEqual(json.loads(Path(str(output) + ".json").read_text())["text_chars"], len(output.read_text()))
            before = output.read_bytes()
            with patch.object(fetch_source.urllib.request, "urlopen") as network, redirect_stderr(io.StringIO()):
                self.assertEqual(fetch_source.main(["https://example.test/source", "--out", str(output)]), 1)
                network.assert_not_called()
            self.assertEqual(output.read_bytes(), before)

    def test_download_cap_and_character_truncation_are_explicit(self) -> None:
        with patch.object(fetch_source.urllib.request, "urlopen", return_value=Response(b"x" * (fetch_source.MAX_BYTES + 1))), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(fetch_source.main(["https://example.test/source"]), 1)
            self.assertIn("byte cap", errors.getvalue())
        with patch.object(fetch_source.urllib.request, "urlopen", return_value=Response(b"x" * (fetch_source.MAX_CHARS + 1))), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(fetch_source.main(["https://example.test/source"]), 0)
            self.assertIn('"complete_text": false', output.getvalue())
            self.assertIn("Text truncated to 40,000 characters", output.getvalue())

    def test_pdf_page_cap_is_reported_even_for_short_text(self) -> None:
        responses = [
            subprocess.CompletedProcess([], 0, "Pages: 401\n", ""),
            subprocess.CompletedProcess([], 0, "A short excerpt.\fSecond page.\f", ""),
        ]
        with patch.object(fetch_source.shutil, "which", return_value="available"), patch.object(fetch_source.subprocess, "run", side_effect=responses):
            text, record = fetch_source.extract(b"%PDF-test", "application/pdf", 400)
        self.assertIn("\f", text)
        self.assertFalse(record["complete_text"])
        self.assertEqual(record["total_pages"], 401)
        self.assertIn("first 400 of 401 pages", record["limit_note"])

    def test_unknown_pdf_page_count_never_claims_full_text(self) -> None:
        with patch.object(fetch_source.shutil, "which", side_effect=lambda name: name if name == "pdftotext" else None), patch.object(fetch_source.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "Excerpt.", "")):
            _, record = fetch_source.extract(b"%PDF-test", "application/pdf", 60)
        self.assertFalse(record["complete_text"])
        self.assertIsNone(record["total_pages"])
        self.assertIn("at most 60 pages", record["limit_note"])

    def test_fully_extracted_pdf_is_identified_and_timeout_fails_cleanly(self) -> None:
        responses = [subprocess.CompletedProcess([], 0, "Pages: 1\n", ""), subprocess.CompletedProcess([], 0, "Rule.\f", "")]
        with patch.object(fetch_source.shutil, "which", return_value="available"), patch.object(fetch_source.subprocess, "run", side_effect=responses):
            _, record = fetch_source.extract(b"%PDF-test", "application/pdf", 60)
        self.assertTrue(record["complete_text"])
        with patch.object(fetch_source.urllib.request, "urlopen", side_effect=TimeoutError("timed out")), redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(fetch_source.main(["https://example.test/source"]), 1)
            self.assertNotIn("Traceback", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
