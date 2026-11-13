#!/usr/bin/env python3
"""Offline recovery, source grouping and publication regressions."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from cache_recovery import build_recovery, coverage_lines, source_state, validate_recovery
from source_resolution import resolution_errors, recovery_lines
from verify_quotes import file_sha256
from prepare_source_bundle import build_bundle
import test_case_review as fixtures

HERE = Path(__file__).resolve().parent


def write(run, name, data):
    (run / name).write_text(''.join(json.dumps(r) + '\n' for r in data))


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.run = Path(temp.name)
        (self.run / 'run-manifest.json').write_text(json.dumps({'cache_recovery_version': 1}))
        self.units = [
            {'unit_id': 'U1', 'source_id': 'S1', 'footnote_number': 1, 'draft_citation_text': 'A, First Work', 'resolved_source_label': 'A, First Work', 'prepared_unit_ids': ['P1']},
            {'unit_id': 'U2', 'source_id': 'S2', 'footnote_number': 1, 'draft_citation_text': 'B, Second Work', 'resolved_source_label': 'B, Second Work'},
            {'unit_id': 'U3', 'source_id': 'S3', 'footnote_number': 9, 'draft_citation_text': 'C, Third Work', 'resolved_source_label': 'C, Third Work'},
        ]
        self.sources = []
        for sid, text in [('S1', 'Different words in the assigned source.'), ('S2', 'The exact passage appears in this second source.'), ('S3', 'The exact passage appears here too.')]:
            path = self.run / (sid + '.txt'); path.write_text(text)
            self.sources.append({'source_id': sid, 'canonical_citation': sid + ' full work', 'source_path': path.name,
                                 'source_sha256': file_sha256(path), 'library_id': 'group:1', 'zotero_item_key': sid})
        self.prepared = [{'prepared_unit_id': 'P1', 'quote': 'The exact passage', 'footnote_number': 1}]
        self.verdicts = [{'unit_id': 'U1', 'status': 'unverified'}]
        self.save()

    def save(self):
        for name, data in [('citation-units.jsonl', self.units), ('source-ledger.jsonl', self.sources),
                           ('prepared-units.jsonl', self.prepared), ('verdicts.jsonl', self.verdicts)]:
            write(self.run, name, data)
        write(self.run, 'quote-checks.jsonl', [])

    def artifact(self):
        result = build_recovery(self.run)
        (self.run / 'cache-recovery.json').write_text(json.dumps(result))
        return result, '\n'.join(coverage_lines(result) + recovery_lines(self.units))

    def test_sibling_match_does_not_change_verdict_or_verify_pin(self):
        before = (self.run / 'verdicts.jsonl').read_bytes()
        result, report = self.artifact()
        attempts = result['results'][0]['attempts']
        self.assertEqual([a['source_id'] for a in attempts], ['S1', 'S2'])
        self.assertEqual(attempts[1]['match']['status'], 'verbatim')
        self.assertNotIn('page', attempts[1]['match'])
        self.assertEqual((self.run / 'verdicts.jsonl').read_bytes(), before)
        self.assertTrue(any('needs review' in e for e in validate_recovery(self.run, report)))
        write(self.run, 'cache-recovery-reviews.jsonl', [{'prepared_unit_id': 'P1', 'source_id': 'S2',
            'source_sha256': self.sources[1]['source_sha256'], 'disposition': 'attribution_issue',
            'evidence': 'Words occur in B; draft attribution still unresolved.'}])
        self.assertEqual(validate_recovery(self.run, report), [])

    def test_all_hits_retained_and_file_normalized_once(self):
        (self.run / 'S1.txt').write_text('The exact passage also appears in this source.')
        self.sources[0]['source_sha256'] = file_sha256(self.run / 'S1.txt')
        self.prepared.append(dict(self.prepared[0], prepared_unit_id='P2'))
        self.units[0]['prepared_unit_ids'].append('P2'); self.save()
        import cache_recovery
        with patch.object(cache_recovery, 'normalize', wraps=cache_recovery.normalize) as normalize:
            result = build_recovery(self.run)
            self.assertEqual(normalize.call_count, 6)  # Three views per file, not per quotation.
        self.assertEqual(len(result['results']), 2)
        self.assertTrue(all(a['match']['status'] == 'verbatim' for a in result['results'][0]['attempts']))

    def test_missing_worker_mapping_is_retained_without_pooling_unknown_locations(self):
        self.prepared.append({'prepared_unit_id': 'P2', 'quote': 'No returned unit or location'})
        self.save()
        result = build_recovery(self.run)['results'][1]
        self.assertIsNone(result['unit_id'])
        self.assertEqual(result['attempts'], [])

    def test_sibling_note_id_and_number_aliases_are_reconciled(self):
        self.units[0]['note_id'] = 'fn:1'
        self.units[1].pop('footnote_number'); self.units[1]['note_id'] = 'fn:1'
        self.save()
        self.assertEqual([a['source_id'] for a in build_recovery(self.run)['results'][0]['attempts']], ['S1', 'S2'])

    def test_antecedent_context_and_its_siblings_are_searched(self):
        antecedent = self.units.pop(0)
        self.units[0]['footnote_number'] = 5
        antecedent['footnote_number'] = 5
        antecedent.pop('prepared_unit_ids')
        self.units.append({'unit_id': 'U4', 'source_id': 'S1', 'footnote_number': 8,
                           'draft_citation_text': 'Id.', 'resolved_source_label': 'A, First Work',
                           'xref_status': 'resolved', 'antecedent_unit_id': 'U1', 'prepared_unit_ids': ['P1']})
        self.prepared[0]['footnote_number'] = 8
        self.save(); write(self.run, 'resolution-context.jsonl', [antecedent])
        result = build_recovery(self.run)
        self.assertEqual([a['source_id'] for a in result['results'][0]['attempts']], ['S1', 'S2'])

    def test_stale_ledger_and_source_hash_block(self):
        result, report = self.artifact()
        (self.run / 'S2.txt').write_text('Changed file')
        errors = validate_recovery(self.run, report)
        self.assertTrue(any('stale' in e for e in errors))
        self.assertTrue(any('changed cache hash' in e for e in errors))

    def test_report_omission_blocks(self):
        self.artifact()
        self.assertTrue(any('omits recovery coverage' in e for e in validate_recovery(self.run, '')))

    def test_skip_never_reads_zotero_cache(self):
        (self.run / 'run-manifest.json').write_text(json.dumps({'library_access': {'selection': {'status': 'skipped'}}}))
        result = build_recovery(self.run)
        self.assertTrue(all(a['status'] == 'skipped' and 'match' not in a for a in result['results'][0]['attempts']))

    def test_selected_library_does_not_silently_search_another_library(self):
        state = source_state(self.run, self.sources[0], {'status': 'selected', 'id': 'group:2'})
        self.assertEqual(state['status'], 'not_selected')

    def test_negative_quote_finding_still_gets_cache_recovery(self):
        self.verdicts[0].update(status='mismatch', category='not_found_in_sources_checked')
        self.save()
        self.assertEqual(len(build_recovery(self.run)['results']), 1)

    def test_recovered_source_still_needs_stale_reference_report_when_quote_verified(self):
        self.units[0].update(source_id='S2', draft_citation_text='B, supra note 99',
            xref_status='recovered', xref_recovery={'candidate_unit_id': 'U2',
                'identity_confirmed': True, 'evidence': 'Title/version match U2; note 99 points elsewhere.'})
        self.verdicts[0]['status'] = 'verified'; self.save()
        result, report = self.artifact()
        self.assertEqual(result['results'], [])
        self.assertEqual(validate_recovery(self.run, report), [])
        self.assertTrue(any('stale reference' in e for e in validate_recovery(self.run, '')))

    def test_library_status_is_not_inferred_from_missing_item(self):
        self.assertEqual(source_state(self.run, {'source_id': 'S'}, None)['status'], 'not_assessed')
        with self.assertRaisesRegex(ValueError, 'needs evidence'):
            source_state(self.run, {'source_id': 'S', 'library_lookup': {'status': 'not_found'}}, None)
        with self.assertRaisesRegex(ValueError, 'item key'):
            source_state(self.run, {'source_id': 'S', 'library_lookup': {'status': 'record_no_attachment', 'evidence': 'Checked attachments'}}, None)
        source = dict(self.sources[1], library_lookup={'status': 'record_no_attachment', 'evidence': 'Old result'})
        self.assertEqual(source_state(self.run, source, None)['status'], 'text_cached')

    def test_non_utf8_cache_is_unreadable_not_absent_quote(self):
        (self.run / 'S2.txt').write_bytes(b'\xff\xfe')
        self.sources[1]['source_sha256'] = file_sha256(self.run / 'S2.txt'); self.save()
        a = build_recovery(self.run)['results'][0]['attempts'][1]
        self.assertEqual(a['status'], 'cache_unreadable'); self.assertNotIn('match', a)

    def test_unresolved_id_sources_cannot_be_grouped_or_verified(self):
        for u in self.units[:2]:
            u.update(source_id='S1', resolved_source_label='Id.', draft_citation_text='Id.', xref_status='unresolved')
        errors = resolution_errors(self.units, self.sources, [{'unit_id': 'U1', 'status': 'verified'}])
        self.assertTrue(any('own source_id' in e for e in errors))
        self.assertTrue(any('cannot be verified' in e for e in errors))
        self.save()
        with self.assertRaisesRegex(ValueError, 'own source_id'):
            build_bundle(self.run, 'S1')

    def test_stale_supra_recovery_requires_identity_and_preserves_finding(self):
        self.units[1].update(source_id='S1', draft_citation_text='A, supra note 99', resolved_source_label='A, First Work',
                             xref_status='recovered', xref_recovery={'candidate_unit_id': 'U1'})
        self.assertTrue(any('confirmed identity' in e for e in resolution_errors(self.units, self.sources)))
        self.units[1]['xref_recovery'].update(identity_confirmed=True, evidence='Note 99 is wrong; title and cited version match U1.')
        self.assertEqual(resolution_errors(self.units, self.sources), [])
        self.assertIn('stale reference', recovery_lines(self.units)[0])

    def test_wrong_supra_note_cannot_masquerade_as_ordinary_resolution(self):
        self.units[1].update(source_id='S1', draft_citation_text='A, supra note 99',
            resolved_source_label='A, First Work', xref_status='resolved', antecedent_unit_id='U1')
        self.assertTrue(any('supra target' in e for e in resolution_errors(self.units, self.sources)))
        self.units[1]['draft_citation_text'] = 'A, supra note 1'
        self.assertEqual(resolution_errors(self.units, self.sources), [])

    def test_legacy_bundle_preserves_old_resolution_contract(self):
        (self.run / 'run-manifest.json').write_text('{}')
        self.units[2].update(draft_citation_text='Id.', resolved_source_label='C, Third Work')
        self.save()
        self.assertEqual(build_bundle(self.run, 'S1')['source_id'], 'S1')

    def test_chain_cycle_wrong_source_and_short_identity_rejected(self):
        self.units[0].update(xref_status='resolved', antecedent_unit_id='U2')
        self.assertTrue(any('assigned source' in e for e in resolution_errors(self.units, self.sources)))
        self.units[1].update(source_id='S1', xref_status='resolved', antecedent_unit_id='U1')
        self.assertTrue(any('cycle' in e for e in resolution_errors(self.units, self.sources)))
        self.units[0]['resolved_source_label'] = 'A, supra note 9'
        self.assertTrue(any('not a resolved' in e for e in resolution_errors(self.units, self.sources)))

    def test_cli_is_idempotent_and_does_not_touch_verdicts(self):
        before = (self.run / 'verdicts.jsonl').read_bytes()
        command = [sys.executable, str(HERE / 'cache_recovery.py'), str(self.run)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        artifact = (self.run / 'cache-recovery.json').read_bytes()
        self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
        self.assertEqual((self.run / 'cache-recovery.json').read_bytes(), artifact)
        self.assertEqual((self.run / 'verdicts.jsonl').read_bytes(), before)


class CompletionTests(unittest.TestCase):
    def test_initializer_enables_recovery_and_real_gate_requires_fresh_artifact(self):
        base = fixtures.ReviewTests(); base.setUp(); self.addCleanup(base.doCleanups)
        # The existing fixture explicitly tests legacy compatibility; restore the new policy.
        initial = json.loads((base.run / 'run-manifest.json').read_text())
        self.assertEqual(initial['cache_recovery_version'], 1)
        base.manifest['cache_recovery_version'] = 1
        self.assertIn('cache recovery:', base.validate().stderr)
        (base.run / 'cache-recovery.json').write_text(json.dumps(build_recovery(base.run)))
        result = base.validate(mark=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        base.verdict['evidence'] = 'Changed evidence'
        self.assertIn('stale or inconsistent', base.validate().stderr)


if __name__ == '__main__':
    unittest.main()
