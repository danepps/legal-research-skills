#!/usr/bin/env python3
"""Offline behavior tests for both independently installable identity helpers."""
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULES = []
for name in ('cite-check', 'legal-research-memo'):
    spec = importlib.util.spec_from_file_location(name, ROOT / name / 'scripts/check_cite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    MODULES.append(module)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('offline tests must not access network'))
        self.network.start(); self.addCleanup(self.network.stop)

    def test_name_queries_and_escaping(self):
        for m in MODULES:
            self.assertEqual(m.party_tokens('Students for Fair Admissions v. President and Fellows of Harvard College'), ['Students', 'Harvard'])
            self.assertEqual(m.party_tokens('United States v. Jones'), ['United States', 'Jones'])
            self.assertIn('caseName:"Harvard"', m.name_query('Students v Harvard'))
            self.assertEqual(m.phrase('x" OR *:*'), '"x\\" OR *:*"')

    def test_unmatched_looks_by_both_routes_without_promoting_identity(self):
        for m in MODULES:
            with patch.object(m, 'request_json', return_value=[{'citation': '397 F. Supp. 3d 126', 'status': 404}]), patch.object(m, 'search', return_value={'status': 'checked', 'count': 1, 'results': [{'cluster_id': 99, 'caseName': 'Later case'}]}) as search:
                row = m.screen('397 F. Supp. 3d 126', 'Students v. Harvard')[0]
                self.assertEqual(search.call_count, 2)
                self.assertEqual(row['routes_tried'], ['citation_lookup', 'caption', 'citation_text'])
                self.assertFalse(row['found'])
                self.assertIn('unconfirmed', row['identity_confirmation'])
                self.assertEqual(search.call_args.args[0], '"397 F. Supp. 3d 126"')

    def test_no_caption_and_lookup_failure_are_explicit(self):
        for m in MODULES:
            with patch.object(m, 'request_json', side_effect=OSError('HTTP 429')):
                row = m.screen('10 F.4th 20')[0]
            self.assertEqual(row['fallbacks']['caption']['status'], 'skipped')
            self.assertEqual(row['fallbacks']['citation_text']['status'], 'unavailable')
            self.assertIsNone(row['found'])
            self.assertIn('429', row['error'])

    def test_ambiguous_and_batch_name(self):
        for m in MODULES:
            self.assertEqual(m.lookup_state({'status': 200, 'clusters': [{}, {}]}), 'ambiguous')
            with patch.object(m, 'request_json', return_value=[{}, {}]):
                with self.assertRaises(ValueError):
                    m.screen('batch', 'One v. Two')

    def test_pagination_and_truncation(self):
        for m in MODULES:
            next_url = m.BASE + '/api/rest/v4/search/?page=2'
            with patch.object(m, 'request_json', side_effect=[{'count': 3, 'results': [{'id': 1}], 'next': next_url}, {'count': 3, 'results': [{'id': 2}, {'id': 3}], 'next': None}]):
                got = m.fetch_pages(m.BASE + '/api/rest/v4/search/', limit=2)
            self.assertTrue(got['truncated'])
            self.assertEqual([r['id'] for r in got['results']], [1, 2])
            with self.assertRaises(ValueError):
                m.request_json('https://example.org/steal-token')

    def test_cluster_dedup_retains_signals_and_unknowns(self):
        for m in MODULES:
            rows = [{'cluster_id': 1, 'routes': ['graph'], 'snippet': 'A', 'signals': []},
                    {'cluster_id': 1, 'routes': ['name'], 'snippet': 'B', 'signals': ['overruled']},
                    {'case_name': 'same'}, {'case_name': 'same'}]
            got = m.dedupe_decisions(rows)
            self.assertEqual(len(got), 3)
            self.assertEqual(got[0]['routes'], ['graph', 'name'])
            self.assertEqual(got[0]['signals'], ['overruled'])
            self.assertEqual(got[0]['additional_snippets'], ['B'])

    def test_slip_bound_duplicates_merge_but_namesakes_do_not(self):
        for m in MODULES:
            rows = [{'cluster_id': 1, 'court_id': 'scotus', 'date_filed': '2023-06-29', 'citations': ['600 U.S. 181']},
                    {'cluster_id': 2, 'court_id': 'scotus', 'date_filed': '2023-06-29', 'citations': ['600 U.S. 181', '143 S. Ct. 2141']},
                    {'cluster_id': 3, 'court_id': 'scotus', 'date_filed': '2023-06-29', 'citations': ['143 S. Ct. 2141']},
                    {'cluster_id': 4, 'court_id': 'other', 'date_filed': '2023-06-29', 'citations': ['600 U.S. 181']}]
            got = m.dedupe_decisions(rows)
            self.assertEqual(len(got), 2)
            self.assertEqual(got[0]['cluster_ids'], [1, 2, 3])


if __name__ == '__main__':
    unittest.main()
