#!/usr/bin/env python3
"""Offline publication regressions: accounting, readiness, and overwrite protection."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('publisher', Path(__file__).with_name('publish_report.py'))
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)

class PublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / '.run'
        self.run.mkdir()
        self.draft = self.root / 'Draft.md'
        self.draft.write_text('original draft')
        (self.run / 'report.md').write_text('# Proofread\n\nDraft: `snapshot.md`\n\nVerified finding.\n')
        (self.run / 'run-manifest.json').write_text(json.dumps({'original_draft_path': str(self.draft), 'created_at': '2026-01-01T00:00:00+00:00'}))

    def invoke(self, args, gate=0):
        with patch.object(sys, 'argv', ['publish', str(self.run), '--model', 'test-model', '--subagents', 'none', *args]), patch.object(publisher.subprocess, 'run', return_value=SimpleNamespace(returncode=gate)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return publisher.main()

    def test_unavailable_publishes_with_null_count_and_final_footer(self):
        self.assertEqual(self.invoke(['--tokens-unavailable']), 0)
        output = self.root / 'Draft — Proofread.md'
        text = output.read_text()
        self.assertIn('tokens unavailable (runtime did not expose exact usage)', text)
        self.assertLess(text.index('Verified finding.'), text.index('Topic:'))
        self.assertTrue(text.rstrip().endswith('subagents: none'))
        manifest = json.loads((self.run / 'run-manifest.json').read_text())
        self.assertIsNone(manifest['publication']['tokens'])
        self.assertEqual(self.draft.read_text(), 'original draft')

    def test_known_tokens_preserved(self):
        self.invoke(['--tokens', '12345'])
        self.assertEqual(json.loads((self.run / 'run-manifest.json').read_text())['publication']['tokens'], 12345)

    def test_failed_readiness_never_publishes(self):
        with self.assertRaises(SystemExit):
            self.invoke(['--tokens-unavailable'], gate=1)
        self.assertFalse((self.root / 'Draft — Proofread.md').exists())

    def test_foreign_report_is_preserved(self):
        foreign = self.root / 'Draft — Proofread.md'
        foreign.write_text('Another reviewer wrote this.')
        self.invoke(['--tokens-unavailable'])
        self.assertEqual(foreign.read_text(), 'Another reviewer wrote this.')
        self.assertTrue((self.root / 'Draft — Codex Proofread.md').is_file())

    def test_invalid_and_ambiguous_accounting_rejected(self):
        for args in (['--tokens', '-1'], ['--tokens', '1', '--tokens-unavailable'], []):
            with self.subTest(args=args), self.assertRaises(SystemExit):
                self.invoke(args)

if __name__ == '__main__':
    unittest.main()
