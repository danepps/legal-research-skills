#!/usr/bin/env python3
"""Offline API and completion-gate regressions; no credentials or network."""
import contextlib
import hashlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import attach_pdf
import verify_items
import zotero_api

SCRIPTS = Path(__file__).resolve().parent

def write_json(path, value):
    path.write_text(json.dumps(value) + '\n')

def write_rows(path, values):
    path.write_text(''.join(json.dumps(row) + '\n' for row in values))

class GateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.run = Path(self.temp.name)
        self.item = {'itemType': 'book', 'title': 'Fixture Book', 'date': '2024', 'ISBN': '9780306406157', 'collections': ['TARGET12']}
        self.candidate = {'candidate_id': 'c001', 'decision': 'add', 'reason': 'offline fixture', 'item': self.item,
            'provenance': [{'url': 'https://publisher.example/book', 'source_type': 'publisher', 'accessed_at': '2026-10-19', 'fields': ['itemType', 'title', 'date', 'ISBN']}],
            'duplicate_check': {'scope': 'collection_and_library', 'queries': ['Fixture Book'], 'matches': [], 'decision': 'unique'}}
        self.verification = {'library': 'user:123', 'source': 'zotero', 'results': [{'key': 'ITEM1234', 'verdict': 'PASS', 'stored_item': {**self.item, 'key': 'ITEM1234'}}]}
        write_json(self.run / 'run.json', {'schema_version': 1, 'request': 'Add fixture', 'library': {'type': 'user', 'id': '123'}, 'collection': {'key': 'TARGET12'}})
        write_rows(self.run / 'candidates.jsonl', [self.candidate])
        write_json(self.run / 'planned-items.json', [{'candidate_id': 'c001', 'item': self.item}])
        write_json(self.run / 'write-result.json', {'operation': 'create-items', 'library': 'user:123', 'request_count': 1, 'candidate_ids': ['c001'],
            'request_sha256': hashlib.sha256(json.dumps([self.item], sort_keys=True, ensure_ascii=False).encode()).hexdigest(),
            'successful': {'0': {'key': 'ITEM1234'}}, 'unchanged': {}, 'failed': {}})
        write_json(self.run / 'verification.json', self.verification)
        write_rows(self.run / 'manual-verifications.jsonl', [])
        write_rows(self.run / 'reuse-results.jsonl', [])

    def gate(self):
        return subprocess.run([sys.executable, str(SCRIPTS / 'validate_run.py'), str(self.run), '--require-ready'], capture_output=True, text=True)

    def test_valid_readback_passes(self):
        result = self.gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_write_library_fails(self):
        path = self.run / 'write-result.json'
        result = json.loads(path.read_text()); result['library'] = 'user:999'; write_json(path, result)
        self.assertIn('write-result library', self.gate().stdout)
        self.assertNotEqual(self.gate().returncode, 0)

    def test_missing_and_changed_readback_fail(self):
        for replacement in (None, {**self.item, 'key': 'ITEM1234', 'collections': []}, {**self.item, 'key': 'ITEM1234', 'title': 'Another Book'}):
            with self.subTest(stored=replacement):
                self.verification['results'][0]['stored_item'] = replacement
                write_json(self.run / 'verification.json', self.verification)
                self.assertNotEqual(self.gate().returncode, 0)

    def test_precheck_cannot_replace_zotero_readback(self):
        self.verification['source'] = 'input'; self.verification['library'] = None
        write_json(self.run / 'verification.json', self.verification)
        self.assertNotEqual(self.gate().returncode, 0)

    def test_reuse_needs_correct_destination_and_verified_readback(self):
        self.candidate.update(decision='reuse', existing_item_key='ITEM1234', item={'collections': ['TARGET12']})
        self.candidate['duplicate_check']['decision'] = 'duplicate'
        write_rows(self.run / 'candidates.jsonl', [self.candidate]); write_json(self.run / 'planned-items.json', [])
        (self.run / 'write-result.json').unlink()
        reuse = {'candidate_id': 'c001', 'item_key': 'ITEM1234', 'collection_key': 'TARGET12', 'library': 'user:123', 'operation': 'add-to-collection', 'http_status': 204}
        write_rows(self.run / 'reuse-results.jsonl', [reuse])
        self.assertEqual(self.gate().returncode, 0)
        reuse['collection_key'] = 'WRONG123'; write_rows(self.run / 'reuse-results.jsonl', [reuse])
        self.assertNotEqual(self.gate().returncode, 0)
        reuse['collection_key'] = 'TARGET12'; write_rows(self.run / 'reuse-results.jsonl', [reuse])
        (self.run / 'verification.json').unlink()
        self.assertNotEqual(self.gate().returncode, 0)

class ApiTests(unittest.TestCase):
    def test_inventory_keeps_identifiers_without_claiming_children_are_pdfs(self):
        payload = [{'key': 'ITEM1234', 'data': {'key': 'ITEM1234', 'itemType': 'book', 'title': 'Fixture', 'ISBN': '9780306406157'}, 'meta': {'numChildren': 1}}]
        with patch.object(zotero_api, 'credentials', return_value=('FAKE', 'user', '123')), patch.object(zotero_api, 'request_paginated', return_value=payload), patch.object(sys, 'argv', ['zotero_api', 'inventory', '--library', 'user:123']), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(zotero_api.main(), 0)
        row = json.loads(output.getvalue())[0]
        self.assertEqual(row['ISBN'], '9780306406157')
        self.assertEqual(row['child_count'], 1)
        self.assertNotIn('has_pdf', row)

    def test_pagination_reads_next_page(self):
        responses = [(200, [{'key': 'FIRST123'}], {'Total-Results': '2', 'Link': '<https://api.zotero.org/users/123/collections?start=1>; rel="next"'}),
                     (200, [{'key': 'SECOND12'}], {'Total-Results': '2'})]
        with patch.object(zotero_api, 'request', side_effect=responses) as request:
            self.assertEqual(len(zotero_api.request_paginated('/users/123/collections', 'FAKE')), 2)
            self.assertEqual(request.call_count, 2)

    def test_foreign_and_incomplete_pagination_fail(self):
        for headers in ({'Total-Results': '2'}, {'Link': '<https://foreign.example/page>; rel="next"'}):
            with self.subTest(headers=headers), patch.object(zotero_api, 'request', return_value=(200, [{'key': 'FIRST123'}], headers)), self.assertRaises(RuntimeError):
                zotero_api.request_paginated('/users/123/collections', 'FAKE')

    def test_unreturned_requested_key_fails(self):
        with patch.object(verify_items, 'credentials', return_value=('FAKE', 'user', '123')), patch.object(verify_items, 'zotero_request', return_value=(200, [], {})), self.assertRaisesRegex(RuntimeError, 'every requested item'):
            verify_items.fetch_zotero_items('user:123', 'ITEM1234', None)

    def test_creator_match_uses_names_not_substrings(self):
        item = {'title': 'Book', 'creators': [{'creatorType': 'author', 'lastName': 'Smith'}]}
        self.assertFalse(verify_items.compare(item, verify_items.record('fixture', 'Book', ['Jane Smithson'], None))[0])
        self.assertTrue(verify_items.compare(item, verify_items.record('fixture', 'Book', ['Jane Smith'], None))[0])

    def test_malformed_resolver_continues_to_valid_fallback(self):
        def malformed(_):
            raise AttributeError('invalid remote JSON shape')
        def good(_):
            return verify_items.Fetch('ok', [verify_items.record('fixture', 'Book', [], None)])
        with patch.object(verify_items.time, 'sleep'):
            result = verify_items.verify_identifier({'title': 'Book'}, 'ISBN', '9780306406157', [malformed, good])
        self.assertEqual(result['verdict'], 'PASS')
        self.assertEqual(result['attempts'][0]['status'], 'error')

    def test_missing_title_and_network_error_fail_closed(self):
        self.assertFalse(verify_items.compare({}, verify_items.record('fixture', 'Book', [], None))[0])
        def unavailable(_):
            return verify_items.Fetch('error', detail='HTTP 503')
        with patch.object(verify_items.time, 'sleep'):
            self.assertEqual(verify_items.verify_identifier({'title': 'Book'}, 'ISBN', '9780306406157', [unavailable])['verdict'], 'UNAVAILABLE')

class PdfTests(unittest.TestCase):
    def test_truncated_pdf_cannot_be_verified(self):
        with self.assertRaisesRegex(RuntimeError, 'structural verification'):
            attach_pdf.validate_pdf(b'%PDF-1.7\ntruncated, no objects or trailer\n')

    def test_real_pdf_parses_and_mock_existing_attachment_verifies(self):
        try:
            from pypdf import PdfWriter
        except ImportError:
            try:
                from PyPDF2 import PdfWriter
            except ImportError:
                self.skipTest('PDF parser is unavailable')
        stream = io.BytesIO(); writer = PdfWriter(); writer.add_blank_page(width=72, height=72); writer.write(stream); body = stream.getvalue()
        self.assertEqual(attach_pdf.validate_pdf(body)['page_count'], 1)
        child = {'key': 'PDF12345', 'data': {'itemType': 'attachment', 'contentType': 'application/pdf', 'filename': 'example.pdf', 'parentItem': 'ITEM1234', 'md5': hashlib.md5(body).hexdigest()}}
        with patch.object(attach_pdf, 'credentials', return_value=('FAKE', 'user', '123')), patch.object(attach_pdf, 'api_request', return_value=(200, [child], {})), patch.object(attach_pdf, 'fetch_stored_file', return_value=body), patch.object(sys, 'argv', ['attach', '--item', 'ITEM1234', '--verify-existing']), contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(attach_pdf.main(), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['status'], 'VERIFIED')
        self.assertEqual(result['pdf_validation']['page_count'], 1)

if __name__ == '__main__':
    unittest.main()
