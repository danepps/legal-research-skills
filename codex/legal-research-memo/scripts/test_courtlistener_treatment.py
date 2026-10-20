#!/usr/bin/env python3
"""Offline treatment tests including independent route coverage and clustered hits."""
import unittest
from unittest.mock import patch
import courtlistener_treatment as t


class TreatmentTests(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
        guard.start(); self.addCleanup(guard.stop)

    def test_phrases_and_signals(self):
        self.assertEqual(t.target_party_tokens('Barnes v. Gorman'), ['Barnes', 'Gorman'])
        self.assertTrue(t.mentions_target('Barnes did not control.', 'Barnes v. Gorman'))
        self.assertIn('overruled', t.signal_names('Roe was overruled.'))
        variants = t.name_phrases('Students for Fair Admissions v. President and Fellows of Harvard College')
        self.assertEqual(variants[-1], 'Students v. Harvard')
        self.assertIn('President & Fellows', variants[1])

    def test_both_routes_keep_counts_dedup_and_date_filter(self):
        calls = []
        def search(query, **kwargs):
            calls.append((query, kwargs))
            ids = [2, 2] if query.startswith('cites:') else [2, 3]
            return {'status': 'checked', 'query': query, 'count': 30, 'truncated': True,
                    'results': [{'cluster_id': cid, 'caseName': 'Later', 'opinions': [{'id': cid * 10, 'snippet': 'Barnes was overruled'}]} for cid in ids]}
        with patch.object(t, 'resolve_cluster', return_value={'id': 1, 'case_name': 'Barnes v. Gorman', 'date_filed': '2002-06-17'}), patch.object(t, 'opinion_ids', return_value=[10, 11]), patch.object(t, 'search', side_effect=search):
            report = t.build_report('536 U.S. 181', 5)
        self.assertEqual(len(calls), 4)
        self.assertEqual(report['distinct_case_count'], 2)
        self.assertEqual(report['total_citing_results'], 30)
        self.assertEqual(report['name_rows_absent_from_retrieved_graph'][0]['cluster_id'], 3)
        self.assertTrue(all(k['filed_after'] == '2002-06-17' for q, k in calls if not q.startswith('cites:')))
        self.assertTrue(all('order_by' not in k for q, k in calls if 'overruled OR' in q))
        self.assertEqual(report['combined_citing_decisions'][0]['routes'], ['graph', 'name'])
        self.assertEqual({r['cluster_id'] for r in report['treatment_probe']}, {2})
        self.assertEqual({r['cluster_id'] for r in report['combined_treatment_decisions']}, {2, 3})

    def test_missing_date_discloses_name_skip(self):
        with patch.object(t, 'resolve_cluster', return_value={'id': 1, 'case_name': 'A v. B'}), patch.object(t, 'opinion_ids', return_value=[]):
            report = t.build_report('cluster:1', 5)
        self.assertEqual(report['routes']['name']['status'], 'skipped')
        self.assertEqual(report['distinct_case_count'], 0)

    def test_ambiguous_identity_not_first_candidate(self):
        with patch.object(t, 'request_json', return_value=[{'clusters': [{'id': 1}, {'id': 2}]}]):
            with self.assertRaises(ValueError):
                t.resolve_cluster('ambiguous')

    def test_failed_graph_metadata_still_runs_name_route(self):
        with patch.object(t, 'resolve_cluster', return_value={'id': 1, 'case_name': 'Barnes v. Gorman', 'date_filed': '2002-06-17'}), patch.object(t, 'opinion_ids', side_effect=OSError('rate limit')), patch.object(t, 'search', return_value={'status': 'checked', 'count': 0, 'results': [], 'truncated': False}) as search:
            report = t.build_report('cluster:1', 5)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(report['routes']['graph']['status'], 'unavailable')
        self.assertEqual(report['routes']['name']['status'], 'checked')


if __name__ == '__main__':
    unittest.main()
