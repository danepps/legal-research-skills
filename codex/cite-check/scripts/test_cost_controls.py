#!/usr/bin/env python3
"""Bounded packets and correct usage arithmetic, with no model/network calls."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from prepare_source_bundle import build_bundle
from usage_report import build_report, instant

HERE = Path(__file__).resolve().parent


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows), encoding='utf-8')


def event(timestamp, input_tokens, cached, output, reasoning=0):
    return {'type': 'event_msg', 'timestamp': timestamp, 'payload': {
        'type': 'token_count', 'info': {'total_token_usage': {
            'input_tokens': input_tokens, 'cached_input_tokens': cached,
            'output_tokens': output, 'reasoning_output_tokens': reasoning,
            'total_tokens': input_tokens + output}}}}


class UsageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def log(self, name='lead', events=None, identity=None):
        path = self.root / (name + '.jsonl')
        write_rows(path, [{'type': 'session_meta', 'payload': {'id': identity or name}}] + (events or []))
        return path

    def test_repeated_counters_and_subsets_are_not_added_twice(self):
        a = event('2026-10-27T10:00:00Z', 1000, 800, 100, 30)
        b = event('2026-10-27T10:01:00Z', 2000, 1700, 150, 40)
        path = self.log(events=[a, a, b, b])
        report = build_report([path, path])
        self.assertEqual(report['tokens']['total_tokens'], 2150)
        self.assertEqual(report['tokens']['cached_input_tokens'], 1700)
        self.assertEqual(report['sessions'][0]['generations'], 2)
        self.assertIsNone(report['tokens']['cache_write_input_tokens'])

    def test_window_subtracts_preexisting_usage_and_excludes_later_work(self):
        path = self.log(events=[event('2026-10-27T10:00:00Z', 1000, 800, 100),
                               event('2026-10-27T10:01:00Z', 3000, 2500, 300),
                               event('2026-10-27T10:02:00Z', 9000, 8000, 900)])
        report = build_report([path], instant('2026-10-27T05:00:30-05:00'), instant('2026-10-27T10:01:30Z'))
        self.assertEqual(report['tokens']['total_tokens'], 2200)
        self.assertEqual(report['tokens']['cached_input_tokens'], 1700)
        self.assertEqual(report['sessions'][0]['generations'], 1)

    def test_parent_and_worker_sum_but_copied_session_is_rejected(self):
        events = [event('2026-10-27T10:00:00Z', 1000, 800, 100)]
        lead, worker = self.log(events=events), self.log('worker', events)
        self.assertEqual(build_report([lead, worker])['tokens']['total_tokens'], 2200)
        duplicate = self.log('copy', events, identity='lead')
        with self.assertRaisesRegex(ValueError, 'duplicate session'):
            build_report([lead, duplicate])

    def test_unavailable_worker_cannot_silently_undercount(self):
        lead = self.log(events=[event('2026-10-27T10:00:00Z', 1000, 800, 100)])
        report = build_report([lead, self.log('missing')])
        self.assertEqual(report['status'], 'unavailable')
        self.assertIsNone(report['tokens']['total_tokens'])
        self.assertEqual(report['sessions'][0]['tokens']['total_tokens'], 1100)

    def test_fork_metadata_keeps_worker_identity_and_excludes_older_parent_events(self):
        path = self.root/'fork.jsonl'
        write_rows(path, [
            {'type': 'session_meta', 'payload': {'id': 'worker', 'forked_from_id': 'lead',
                                                'timestamp': '2026-10-27T10:01:00Z'}},
            {'type': 'session_meta', 'payload': {'id': 'lead'}},
            event('2026-10-27T10:00:00Z', 9000, 8000, 900),
            event('2026-10-27T10:02:00Z', 1000, 800, 100),
        ])
        report = build_report([path])
        self.assertEqual(report['sessions'][0]['session_id'], 'worker')
        self.assertEqual(report['tokens']['total_tokens'], 1100)

    def test_resets_and_unknown_counter_semantics_fail(self):
        path = self.log(events=[event('2026-10-27T10:00:00Z', 1000, 800, 100),
                               event('2026-10-27T10:01:00Z', 200, 100, 20)])
        with self.assertRaisesRegex(ValueError, 'counter reset'):
            build_report([path])
        broken = event('2026-10-27T10:00:00Z', 1000, 800, 100)
        broken['payload']['info']['total_token_usage']['total_tokens'] = 1900
        with self.assertRaisesRegex(ValueError, 'unsupported token schema'):
            build_report([self.log(events=[broken])])
        with self.assertRaisesRegex(ValueError, 'timezone'):
            instant('2026-10-27T10:00:00')

    def test_cli_reports_actual_window(self):
        path = self.log(events=[event('2026-10-27T10:00:00Z', 1000, 800, 100)])
        out = self.root / 'usage.json'
        proc = subprocess.run([sys.executable, str(HERE/'usage_report.py'), '--session', str(path),
                               '--output', str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(out.read_text())['tokens']['total_tokens'], 1100)

    def test_window_subsets_are_validated_after_subtraction(self):
        path = self.log(events=[event('2026-10-27T10:00:00Z', 1000, 0, 100),
                               event('2026-10-27T10:01:00Z', 1010, 900, 110)])
        with self.assertRaisesRegex(ValueError, 'cached_input_tokens exceeds'):
            build_report([path], instant('2026-10-27T10:00:30Z'))

    def test_missing_window_baseline_is_unavailable_unless_zero_is_established(self):
        row = event('2026-10-27T10:01:00Z', 3000, 2500, 300)
        path = self.log(events=[row])
        start = instant('2026-10-27T10:00:30Z')
        report = build_report([path], start)
        self.assertEqual(report['status'], 'unavailable')
        self.assertEqual(report['sessions'][0]['baseline_basis'], 'unavailable_pre_window_counter')
        row['payload']['info']['last_token_usage'] = row['payload']['info']['total_token_usage']
        self.assertEqual(build_report([self.log(events=[row])], start)['tokens']['total_tokens'], 3300)


class BundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.units = [
            {'unit_id': 'U1', 'source_id': 'S1', 'note_id': 'fn:1', 'footnote_number': 1,
             'draft_citation_text': 'First source', 'full_footnote': 'First source; second source.',
             'body_context': 'Complete claim with its qualifying clause.', 'prepared_unit_ids': ['P1']},
            {'unit_id': 'U2', 'source_id': 'S2', 'note_id': 'fn:1', 'draft_citation_text': 'Second source'},
            {'unit_id': 'U3', 'source_id': 'S3', 'note_id': 'fn:99', 'full_footnote': 'Unrelated secret text.'},
        ]
        write_rows(self.root/'citation-units.jsonl', self.units)
        write_rows(self.root/'source-ledger.jsonl', [
            {'source_id': s, 'source_path': 'cached-sources/' + s + '.txt', 'full_text': 'DO NOT PACK THIS'}
            for s in ('S1', 'S2', 'S3')])
        write_rows(self.root/'prepared-units.jsonl', [
            {'prepared_unit_id': 'P1', 'note_id': 'fn:1', 'quote': 'Exact complete quotation.'},
            {'prepared_unit_id': 'P2', 'note_id': 'fn:99', 'quote': 'Unrelated quotation.'}])
        write_rows(self.root/'support-units.jsonl', [{'unit_id': 'U1', 'anchor': {'sentence': 'Complete claim.'}}, {'unit_id': 'U3'}])

    def test_packet_keeps_complete_context_siblings_and_paths_without_full_corpus(self):
        bundle = build_bundle(self.root, 'S1')
        self.assertEqual(bundle['citation_units'], self.units[:1])
        self.assertEqual(bundle['prepared_quotes'][0]['quote'], 'Exact complete quotation.')
        self.assertEqual([u['unit_id'] for u in bundle['sibling_citations']], ['U2'])
        self.assertEqual([s['source_id'] for s in bundle['sources']], ['S1', 'S2'])
        self.assertEqual(len(bundle['support_units']), 1)
        text = json.dumps(bundle)
        for excluded in ('DO NOT PACK THIS', 'Unrelated secret', 'Unrelated quotation'):
            self.assertNotIn(excluded, text)

    def test_unlinked_quote_at_same_note_remains_context(self):
        del self.units[0]['prepared_unit_ids']
        write_rows(self.root/'citation-units.jsonl', self.units)
        bundle = build_bundle(self.root, 'S1')
        self.assertEqual(len(bundle['prepared_quotes']), 1)
        self.assertIn('not inferred attribution', bundle['quote_scope'])

    def test_dangling_quote_and_unknown_source_are_errors(self):
        with self.assertRaisesRegex(ValueError, 'resolved citation units'):
            build_bundle(self.root, 'unknown')
        (self.root/'prepared-units.jsonl').unlink()
        with self.assertRaisesRegex(ValueError, 'linked prepared quotation'):
            build_bundle(self.root, 'S1')

    def test_mixed_note_identifiers_retain_sibling_and_unlinked_quote(self):
        del self.units[0]['prepared_unit_ids']
        self.units[1].pop('note_id')
        self.units[1]['footnote_number'] = 1
        write_rows(self.root/'citation-units.jsonl', self.units)
        write_rows(self.root/'prepared-units.jsonl', [
            {'prepared_unit_id': 'P1', 'footnote_number': 1, 'quote': 'Complete quotation.'}])
        bundle = build_bundle(self.root, 'S1')
        self.assertEqual([u['unit_id'] for u in bundle['sibling_citations']], ['U2'])
        self.assertEqual([p['prepared_unit_id'] for p in bundle['prepared_quotes']], ['P1'])
        self.assertEqual([s['source_id'] for s in bundle['sources']], ['S1', 'S2'])

    def test_new_source_can_be_assigned_before_retrieval_without_fabricating_status(self):
        write_rows(self.root/'source-ledger.jsonl', [])
        bundle = build_bundle(self.root, 'S1')
        self.assertFalse(bundle['source_record_available'])
        self.assertEqual(bundle['sources'], [])
        self.assertEqual(bundle['citation_units'], self.units[:1])

    def test_cli_cannot_overwrite_ledger(self):
        ledger = self.root/'source-ledger.jsonl'
        before = ledger.read_bytes()
        proc = subprocess.run([sys.executable, str(HERE/'prepare_source_bundle.py'), str(self.root), 'S1',
                               '--output', str(ledger)], capture_output=True, text=True)
        self.assertNotEqual(proc.returncode, 0)
        self.assertEqual(ledger.read_bytes(), before)
        out = self.root/'source-bundles/S1.json'
        proc = subprocess.run([sys.executable, str(HERE/'prepare_source_bundle.py'), str(self.root), 'S1',
                               '--output', str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(out.read_text())['source_id'], 'S1')


if __name__ == '__main__':
    unittest.main()
