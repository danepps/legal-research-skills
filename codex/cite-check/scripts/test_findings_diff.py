#!/usr/bin/env python3
"""Offline content identity and conservative re-run comparison tests."""
import json
from pathlib import Path
import tempfile
import unittest
import findings_diff as f


class DiffTests(unittest.TestCase):
    def setUp(self):
        self.item = {'kind': 'quote', 'quote': 'A meaningful quoted sentence', 'source': 'Smith v. Jones', 'verdict': 'misattributed', 'footnote': 2, 'label': 'Fix speaker'}

    def test_renumbered_quote_retains_key_and_current_location(self):
        moved = dict(self.item, footnote=37, unit_id='new-id', label='Different explanatory prose')
        self.assertEqual(f.key_of(self.item), f.key_of(moved))
        before = {'coverage_complete': True, 'items': [self.item]}
        after = {'coverage_complete': True, 'items': [moved]}
        changes = f.diff(before, after)
        self.assertEqual(len(changes['still_open']), 1)
        self.assertEqual(len(changes['renumbered']), 1)
        self.assertIn('n.37', f.render(before, after, changes))

    def test_full_content_and_category_distinguish_different_findings(self):
        long = dict(self.item, quote='x' * 200 + ' first')
        other = dict(long, quote='x' * 200 + ' second', key=f.key_of(long))
        self.assertNotEqual(f.key_of(long), f.key_of(other))
        self.assertNotEqual(f.key_of(self.item), f.key_of(dict(self.item, verdict='pincite_error')))
        self.assertNotEqual(f.key_of(dict(self.item, quote='α')), f.key_of(dict(self.item, quote='β')))
        self.assertEqual(f.key_of(self.item), f.key_of(dict(self.item, quote='A meaningful quoted sentence.')))

    def test_supra_target_renumbering_is_not_identity(self):
        a = {'kind': 'citation', 'find': 'Smith, supra note 12', 'source': 'Smith, Book', 'verdict': 'broken_cross_reference'}
        self.assertEqual(f.key_of(a), f.key_of(dict(a, find='Smith, supra note 15')))

    def test_history_findings_do_not_collapse_different_outcomes(self):
        a = {'kind': 'history', 'cite': '1 F.3d 2', 'verdict': 'omitted_required_history'}
        self.assertNotEqual(f.key_of(a), f.key_of(dict(a, verdict='contradicted_history')))

    def test_duplicates_retain_occurrences(self):
        grouped = f.index_items([self.item, dict(self.item, footnote=4)])
        self.assertEqual(len(grouped), 1)
        self.assertEqual(len(next(iter(grouped.values()))['occurrences']), 2)

    def test_limited_or_legacy_comparison_cannot_resolve_absent_findings(self):
        for current in ({'coverage_complete': False, 'items': []}, {'items': []}):
            changes = f.diff({'coverage_complete': True, 'items': [self.item]}, current)
            self.assertEqual(changes['resolved'], [])
            self.assertEqual(len(changes['not_rechecked']), 1)
        self.assertEqual(len(f.diff({'coverage_complete': True, 'items': [self.item]}, {'coverage_complete': True, 'items': []})['resolved']), 1)

    def test_snapshot_preserves_all_quotes_independent_of_check_order(self):
        with tempfile.TemporaryDirectory() as temp:
            run = Path(temp)
            (run / 'run-manifest.json').write_text(json.dumps({'draft_sha256': 'abc', 'scope': 'standard', 'completion_target': 'complete'}))
            for name, rows in {
                'citation-units': [{'unit_id': 'U1', 'source_id': 'S1', 'footnote_number': 1}],
                'source-ledger': [{'source_id': 'S1', 'canonical_citation': 'Smith'}],
                'verdicts': [{'unit_id': 'U1', 'status': 'mismatch', 'category': 'quote_mismatch', 'suggested_action': 'Fix'}],
                'quote-checks': [{'unit_id': 'U1', 'quote': 'First quote'}, {'unit_id': 'U1', 'quote': 'Second quote'}],
            }.items():
                (run / (name + '.jsonl')).write_text(''.join(json.dumps(r) + '\n' for r in rows))
            first = f.snapshot(run)
            path = run / 'quote-checks.jsonl'
            path.write_text('\n'.join(reversed(path.read_text().splitlines())) + '\n')
            second = f.snapshot(run)
            self.assertEqual(first['items'][0]['key'], second['items'][0]['key'])
            self.assertIn('First quote', first['items'][0]['quote'])
            self.assertIn('Second quote', first['items'][0]['quote'])


if __name__ == '__main__':
    unittest.main()
