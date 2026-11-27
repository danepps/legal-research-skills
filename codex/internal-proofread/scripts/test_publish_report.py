#!/usr/bin/env python3
"""Offline publication regressions: accounting, readiness, and overwrite protection."""
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
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
        self.root = Path(self.temp.name).resolve()
        self.run = self.root / '.run'
        self.run.mkdir()
        self.draft = self.root / 'Draft.md'
        self.draft.write_text('original draft')
        self.source_hash = 'a' * 64
        self.body = '# Proofread\n\nVerified finding.\n\n## Details\n\n' + 'Finding context.\n' * 30
        self.canonical = self.body + f'\n---\n\nDraft: `snapshot.md`  \nSource SHA-256: `{self.source_hash}`  \n'
        (self.run / 'report.md').write_text(self.canonical)
        (self.run / 'run-manifest.json').write_text(json.dumps({'original_draft_path': str(self.draft), 'draft_path': 'snapshot.md', 'draft_sha256': self.source_hash, 'created_at': '2026-01-01T00:00:00+00:00'}))

    def invoke(self, args, gate=0):
        with patch.object(sys, 'argv', ['publish', str(self.run), '--model', 'test-model', '--subagents', 'none', *args]), patch.object(publisher.subprocess, 'run', return_value=SimpleNamespace(returncode=gate)), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return publisher.main()

    def test_unavailable_publishes_with_null_count_and_final_footer(self):
        self.assertEqual(self.invoke(['--tokens-unavailable']), 0)
        output = self.root / 'Draft — Proofread.md'
        text = output.read_text()
        self.assertIn('tokens unavailable (runtime did not expose exact usage)', text)
        self.assertLess(text.index('Verified finding.'), text.index('> Created by:'))
        self.assertNotIn('Topic:', text)
        self.assertTrue(text.rstrip().endswith('subagents: none'))
        manifest = json.loads((self.run / 'run-manifest.json').read_text())
        self.assertIsNone(manifest['publication']['tokens'])
        self.assertEqual(self.draft.read_text(), 'original draft')

    def test_known_tokens_preserved(self):
        self.invoke(['--tokens', '12345'])
        self.assertEqual(json.loads((self.run / 'run-manifest.json').read_text())['publication']['tokens'], 12345)

    def test_body_starts_immediately_and_all_provenance_is_in_one_final_block(self):
        generated = datetime(2026, 1, 1, 1, 2, 3, tzinfo=timezone.utc).astimezone()
        for accounting, token_text in ((['--tokens', '12345'], '12,345 tokens'),
                                       (['--tokens-unavailable'], 'tokens unavailable (runtime did not expose exact usage)')):
            with self.subTest(accounting=accounting), patch.object(publisher, 'datetime') as clock:
                clock.now.return_value = generated
                clock.fromisoformat.side_effect = datetime.fromisoformat
                self.invoke(accounting)
            text = (self.root / 'Draft — Proofread.md').read_text()
            self.assertEqual([line for line in text.splitlines() if line.strip()][1], 'Verified finding.')
            body, rule, footer = text.rpartition('\n---\n')
            self.assertEqual(body.rstrip(), self.body.rstrip())
            self.assertTrue(rule)
            expected = [
                '> Created by: **Codex**  ',
                '> Model: `test-model`  ',
                f"> Generated: {generated.strftime('%Y-%m-%d %H:%M:%S %Z')}  ",
                '> Elapsed: 1h 2m 3s  ',
                f'> Tokens: {token_text}',
                f'Draft: `{self.draft}`  ',
                f'Source SHA-256: `{self.source_hash}`  ',
                f"Date: {generated.strftime('%Y-%m-%d')}",
                'By: Codex-test-model',
                f'Production details: {token_text}; elapsed through audit: 1h 2m 3s; subagents: none',
            ]
            self.assertEqual([line for line in footer.splitlines() if line], expected)
            for line in expected:
                self.assertEqual(text.splitlines().count(line), 1, line)
            self.assertIn(f'\nSource SHA-256: `{self.source_hash}`  \n', text)
            self.assertEqual((self.run / 'report.md').read_text(), self.canonical)

    def test_ownership_accepts_both_layouts_only_for_this_codex_draft(self):
        path = self.root / 'existing.md'
        for layout in ('legacy', 'footer'):
            for author, draft, accepted in (('Codex', self.draft, True), ('Claude', self.draft, False),
                                             ('Codex', self.root / 'Other.md', False)):
                with self.subTest(layout=layout, author=author, draft=draft):
                    metadata = f'> Created by: **{author}**  \n\nDraft: `{draft}`  \n'
                    text = '# Proofread\n\n' + metadata + '\nVerified finding.\n' if layout == 'legacy' else self.body + '\n---\n\n' + metadata
                    path.write_text(text)
                    self.assertEqual(publisher.codex_report_for(path, self.draft), accepted)

    def test_body_mentions_and_inexact_draft_lines_do_not_establish_ownership(self):
        path = self.root / 'existing.md'
        marker = '> Created by: **Codex**  \n'
        for text in (
            self.body + marker + f'Draft: `{self.draft}`  \n\nMore report body.\n',
            '# Proofread\n\n' + marker + f'Mentioned Draft: `{self.draft}`\n',
            '# Proofread\n\n' + marker + f'Draft: `{self.draft}`.backup\n',
            self.body + '\n---\n\n' + marker + f'Draft: `{self.draft}`  \nDraft: `other.md`  \n',
        ):
            with self.subTest(text=text):
                path.write_text(text)
                self.assertFalse(publisher.codex_report_for(path, self.draft))

    def test_republishing_replaces_either_layout_without_fallback(self):
        output = self.root / 'Draft — Proofread.md'
        output.write_text(f'# Old report\n\n> Created by: **Codex**  \n\nDraft: `{self.draft}`  \n\nOld finding.\n')
        for _ in range(2):
            self.invoke(['--tokens', '12345'])
            self.assertIn('Verified finding.', output.read_text())
            self.assertEqual(output.read_text().count('> Created by:'), 1)
            self.assertFalse((self.root / 'Draft — Codex Proofread.md').exists())

    def test_explicit_foreign_output_is_never_replaced(self):
        output = self.root / 'existing.md'
        for text in ('Another reviewer wrote this.', f'# Proofread\n\n> Created by: **Codex**  \n\nDraft: `{self.root / "Other.md"}`  \n'):
            with self.subTest(text=text):
                output.write_text(text)
                with self.assertRaises(SystemExit):
                    self.invoke(['--tokens-unavailable', '--output', str(output)])
                self.assertEqual(output.read_text(), text)

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
