#!/usr/bin/env python3
"""Offline history tests: RECAP twins, pagination, state gaps, ambiguous identity."""
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse
import case_history as h


class HistoryTests(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
        guard.start(); self.addCleanup(guard.stop)
        self.cluster = {'id': 1, 'docket_id': 10, 'case_name': 'Alpha v. Beta', 'date_filed': '2020-01-01'}

    def test_flags_are_only_leads_and_include_attachments(self):
        self.assertEqual(h.flags('NOTICE OF APPEAL'), ['notice_of_appeal'])
        self.assertIn('amended_or_substituted_opinion', h.flags('ORDER (Attachments: #1 Amended Opinion)'))
        self.assertIn('reconsideration', h.flags('Motion for relief under Rule 60(b)'))
        self.assertIn('cert_granted', h.flags('The petition for certiorari is granted.'))
        self.assertIn('appellate_judgment_or_opinion', h.flags('OPINION of USCA as to 674 Notice of Appeal'))
        self.assertEqual(h.flags('NOTICE OF APPEARANCE'), [])
        self.assertEqual(h.docket_core('1:14-cv-14176-ADB'), '14-cv-14176')
        self.assertEqual(h.docket_core('04cv2688'), '04-cv-2688')
        self.assertIsNone(h.docket_core('19-2005P'))

    def api(self, url, data=None):
        if '/dockets/' in url:
            return {'id': 10, 'court_id': 'mad', 'docket_number': '1:14-cv-14176-ADB'}
        return {'jurisdiction': 'FD'}

    def test_empty_scraper_twin_recovers_recap_and_later_candidates(self):
        def searching(query, **filters):
            if filters.get('type') == 'd':
                self.assertEqual(query, 'docketNumber:"14-cv-14176"')
                self.assertEqual(filters['court'], 'mad')
                return {'status': 'checked', 'truncated': False, 'results': [{'court_id': 'mad', 'docketNumber': '14-cv-14176', 'docket_id': 20}]}
            self.assertEqual(filters['filed_after'], '2020-01-01')
            return {'status': 'checked', 'results': [{'cluster_id': 2, 'dateFiled': '2021-01-01', 'court_id': 'ca1'}]}
        empty = {'results': [], 'truncated': False, 'count': 0}
        found = {'results': [{'id': 5, 'history_flags': ['mandate']}], 'truncated': False, 'count': 1}
        with patch.object(h, 'resolve', return_value=self.cluster), patch.object(h, 'request_json', side_effect=self.api), patch.object(h, 'entries', side_effect=[empty, found]) as entries, patch.object(h, 'search', side_effect=searching):
            packet = h.build_history('cluster:1')
        self.assertEqual(packet['docket']['docket_id'], '20')
        self.assertEqual(entries.call_args.args[0], '20')
        self.assertEqual(packet['later_opinions']['results'][0]['reviewing_jurisdiction'], 'requires_manual_verification')

    def test_recap_search_request_uses_court_parameter(self):
        def response(url, data=None):
            params = parse_qs(urlparse(url).query)
            if params.get('type') == ['d']:
                self.assertEqual(params['q'], ['docketNumber:"14-cv-14176"'])
                self.assertEqual(params['court'], ['mad'])
                return {'count': 1, 'next': None, 'results': [
                    {'court_id': 'mad', 'docketNumber': '14-cv-14176', 'docket_id': 4275760}]}
            return {'count': 0, 'next': None, 'results': []}
        empty = {'results': [], 'truncated': False, 'count': 0}
        found = {'results': [{'id': 5, 'history_flags': ['mandate']}], 'truncated': False, 'count': 1}
        with patch.object(h, 'resolve', return_value=self.cluster), patch.object(h, 'request_json', side_effect=self.api), patch.object(h, 'entries', side_effect=[empty, found]), patch('check_cite.request_json', side_effect=response) as request:
            packet = h.build_history('cluster:1')
        self.assertEqual(request.call_count, 2)
        self.assertEqual(packet['docket']['docket_id'], '4275760')
        self.assertEqual(packet['docket']['recap_search']['filters']['court'], 'mad')

    def test_ambiguous_twins_are_not_silently_selected(self):
        candidates = {'status': 'checked', 'truncated': False, 'results': [
            {'court_id': 'mad', 'docketNumber': '14-cv-14176', 'docket_id': n} for n in (20, 30)]}
        with patch.object(h, 'resolve', return_value=self.cluster), patch.object(h, 'request_json', side_effect=self.api), patch.object(h, 'entries', return_value={'results': [], 'truncated': False}), patch.object(h, 'search', side_effect=[candidates, {'results': []}]):
            self.assertEqual(h.build_history('cluster:1')['docket']['status'], 'partial')

    def test_state_or_missing_date_never_claims_docket_coverage(self):
        with patch.object(h, 'resolve', return_value=self.cluster), patch.object(h, 'request_json', side_effect=[{'court_id': 'ind'}, {'jurisdiction': 'S'}]), patch.object(h, 'entries') as entries, patch.object(h, 'search', return_value={'results': []}):
            result = h.build_history('cluster:1')
            entries.assert_not_called()
            self.assertEqual(result['docket']['status'], 'not_applicable')
        with patch.object(h, 'resolve', return_value={**self.cluster, 'date_filed': None}):
            result = h.build_history('cluster:1')
            self.assertEqual(result['docket']['status'], 'unavailable')
            self.assertEqual(result['later_opinions']['status'], 'skipped')

    def test_entry_query_inclusive_and_bounded(self):
        with patch.object(h, 'fetch_pages', return_value={'results': [{'description': 'VACATED and REMANDED'}], 'truncated': False}) as fetch:
            result = h.entries(10, '2020-01-01', 2)
        params = parse_qs(urlparse(fetch.call_args.args[0]).query)
        self.assertEqual(params['date_filed__gte'], ['2020-01-01'])
        self.assertEqual(params['order_by'], ['date_filed'])
        self.assertEqual(fetch.call_args.args[1], 2)
        self.assertEqual(fetch.call_count, 1)
        self.assertFalse(result['read_both_ends'])
        self.assertEqual(set(result['results'][0]['history_flags']), {'vacatur', 'remand'})

    def test_capped_entries_read_newest_and_preserve_flags_and_gaps(self):
        head = {'count': 567, 'results': [{'id': 1, 'entry_number': 121, 'date_filed': '2017-06-02', 'description': 'ORDER'}],
                'pages_read': 1, 'truncated': True}
        tail = {'count': 567, 'results': [
            {'id': 4, 'entry_number': 687, 'date_filed': '2022-01-24', 'description': 'Certiorari is granted'},
            {'id': 3, 'entry_number': 684, 'date_filed': '2020-12-01', 'description': 'USCA judgment and mandate'},
            {'id': 2, 'entry_number': 674, 'date_filed': '2019-10-01', 'description': 'NOTICE OF APPEAL'}],
            'pages_read': 1, 'truncated': True}
        with patch.object(h, 'fetch_pages', side_effect=[head, tail]) as fetch:
            result = h.entries(4275760, '2017-06-02', 100)
        calls = fetch.call_args_list
        self.assertEqual([call.args[1] for call in calls], [100, 50])
        for call, order in zip(calls, ['date_filed', '-date_filed']):
            params = parse_qs(urlparse(call.args[0]).query)
            self.assertEqual(params, {'docket': ['4275760'], 'date_filed__gte': ['2017-06-02'], 'order_by': [order]})
        self.assertEqual(result['count'], 567)
        self.assertEqual(result['retrieved_count'], 4)
        self.assertEqual(result['pages_read'], 2)
        self.assertTrue(result['read_both_ends'])
        self.assertTrue(result['truncated'])
        self.assertEqual([r['entry_number'] for r in result['results']], [121, 674, 684, 687])
        self.assertIn('notice_of_appeal', result['results'][1]['history_flags'])
        self.assertIn('mandate', result['results'][2]['history_flags'])
        self.assertIn('appellate_judgment_or_opinion', result['results'][2]['history_flags'])
        self.assertIn('cert_granted', result['results'][3]['history_flags'])
        with patch.object(h, 'resolve', return_value=self.cluster), patch.object(h, 'request_json', side_effect=self.api), patch.object(h, 'entries', return_value=result), patch.object(h, 'search', return_value={'results': []}):
            docket = h.build_history('cluster:1')['docket']
        self.assertEqual(docket['status'], 'partial')
        self.assertIn('intervening', docket['reason'])
        self.assertEqual(len(docket['flagged_entries']), 3)

    def test_overlapping_pages_deduplicated_and_complete_union_clears_gap(self):
        rows = [{'id': n, 'entry_number': n, 'date_filed': '2020-01-01', 'description': 'Mandate'} for n in (9, 10, 11)]
        first_url = h.BASE + '/api/rest/v4/docket-entries/?page=2'
        def response(url, data=None):
            params = parse_qs(urlparse(url).query)
            if params.get('page') == ['2']:
                return {'count': 3, 'next': None, 'results': rows[1:]}
            if params['order_by'] == ['-date_filed']:
                return {'count': 3, 'next': None, 'results': list(reversed(rows))}
            return {'count': 3, 'next': first_url, 'results': rows[:1]}
        with patch('check_cite.request_json', side_effect=response) as request:
            result = h.entries(10, '2020-01-01', 2)
        self.assertEqual(request.call_count, 3)
        self.assertEqual(result['pages_read'], 3)
        self.assertEqual([r['id'] for r in result['results']], [9, 10, 11])
        self.assertEqual(result['retrieved_count'], 3)
        self.assertTrue(result['read_both_ends'])
        self.assertFalse(result['truncated'])

    def test_failed_newest_read_keeps_head_and_discloses_gap(self):
        head = {'count': 30, 'results': [{'id': 1, 'description': 'Notice of appeal'}], 'truncated': True}
        with patch.object(h, 'fetch_pages', side_effect=[head, OSError('offline fixture failure')]):
            result = h.entries(10, '2020-01-01', 1)
        self.assertEqual(result['results'][0]['history_flags'], ['notice_of_appeal'])
        self.assertEqual(result['newest_entries']['status'], 'unavailable')
        self.assertTrue(result['truncated'])
        self.assertFalse(result['read_both_ends'])
        with patch.object(h, 'resolve', return_value=self.cluster), patch.object(h, 'request_json', side_effect=self.api), patch.object(h, 'entries', return_value=result), patch.object(h, 'search', return_value={'results': []}):
            docket = h.build_history('cluster:1')['docket']
        self.assertEqual(docket['status'], 'partial')
        self.assertIn('newest-entry read unavailable', docket['reason'])

    def test_ambiguous_lookup_rejected(self):
        with patch.object(h, 'request_json', return_value=[{'clusters': [{'id': 1}, {'id': 2}]}]):
            with self.assertRaises(ValueError):
                h.resolve('1 F.3d 2')


if __name__ == '__main__':
    unittest.main()
