#!/usr/bin/env python3
"""Offline regression tests for optional exact corrections."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

import make_chunks
import make_recall_packets
import make_rejection_packets
import test_workflow_integrity as fixtures
from common import read_json, read_jsonl, write_json, write_jsonl
from replacements import bind, bind_audit, effective_finding, resolve, validate_replacement

SCRIPTS = Path(__file__).resolve().parent


def packet_texts(root, enabled=False):
    """Exercise every packet writer, including both sharded lane types."""
    block = {'block_id': 'B000001', 'story': 'body', 'kind': 'paragraph',
             'text': 'The court found that that rule applies.', 'heading_path': [],
             'footnote_ids': ['1'], 'word_count': 8}
    note = {'block_id': 'FN1', 'note_id': '1', 'story': 'footnote', 'kind': 'paragraph',
            'text': 'See supra note 1.', 'heading_path': []}
    chunk = {'chunk_id': 'C0001', 'core_block_ids': ['B000001']}
    finding = {'finding_id': 'F1', 'category': 'duplication', 'severity': 'warning',
               'impact': 'high', 'excerpt': 'that that', 'suggestion': 'Remove the second that.',
               'location': {'block_id': 'B000001', 'char_start': 16, 'char_end': 25}}
    symbols = {'notes': [dict(note, display_number=1)], 'display_note_to_block': {'1': 'FN1'},
               'cross_references': [{'kind': 'note', 'block_id': 'FN1', 'targets': ['FN1']}],
               'serial_comma_candidates': [{'block_id': 'B000001', 'excerpt': 'one, two and three'}]}
    options = {'replacements': True} if enabled else {}
    make_chunks.write_chunk_packet(root / 'chunk.md', chunk, [block], [], [], [note], [finding], 'HASH', **options)
    make_chunks.write_lane_packets(root, [chunk, chunk], [block], [note], symbols, 'HASH', **options)
    make_recall_packets.write_packet(root / 'recall.md', 'RB0001', 'body', [block], 'HASH',
                                    ['B000001'], [], [], Path('/RUN/recall-results/RB0001.json'), **options)
    rejection = make_rejection_packets.render_packet('RP0001', 'HASH', [(finding, {'block': block}, True)],
                                                     Path('/RUN/rejection-results/RP0001.jsonl'), {}, **options)
    texts = {str(path.relative_to(root)): path.read_text() for path in sorted(root.rglob('*.md'))}
    texts['rejection.md'] = rejection
    return texts


class PacketCompatibilityTests(unittest.TestCase):
    def test_default_packets_match_pre_feature_bytes(self):
        expected = json.loads((SCRIPTS / 'fixtures/replacements-off.json').read_text())
        with tempfile.TemporaryDirectory() as directory:
            actual = packet_texts(Path(directory))
        self.assertEqual(actual, expected['packets'])
        from replacements import finding_schema
        self.assertEqual(hashlib.sha256(finding_schema(False).encode()).hexdigest(), expected['schema_sha256'])

    def test_every_enabled_packet_has_the_optional_instruction(self):
        with tempfile.TemporaryDirectory() as directory:
            actual = packet_texts(Path(directory), True)
        self.assertEqual(len(actual), 10)
        for name, packet in actual.items():
            with self.subTest(packet=name):
                self.assertIn('optional string `replacement`', packet)
                self.assertIn('quoted material', packet)
                self.assertIn('revised_replacement', packet)

    def test_default_manifest_and_generated_schema(self):
        fixture = fixtures.WorkflowIntegrityTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.initialize('A clean paragraph for a default run.\n')
        manifest = read_json(fixture.run / 'run-manifest.json')
        self.assertIs(manifest['replacements'], False)
        schema = (fixture.run / 'references/finding-schema.md').read_bytes()
        expected = json.loads((SCRIPTS / 'fixtures/replacements-off.json').read_text())
        self.assertEqual(hashlib.sha256(schema).hexdigest(), expected['schema_sha256'])
        manifest.pop('replacements')
        write_json(fixture.run / 'run-manifest.json', manifest)
        self.assertEqual(fixture.call('validate_run.py', fixture.run, '--require-ready').returncode, 0)


class ReplacementLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowIntegrityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.initialize('The court consider this rule.\n', '--replacements')
        self.run = self.fixture.run
        self.manifest = read_json(self.run / 'run-manifest.json')
        self.document = read_json(self.run / 'document.json')
        self.block = self.document['blocks'][0]
        self.blocks = {self.block['block_id']: self.block}
        self.finding = {
            'finding_id': 'EXACT1', 'source_sha256': self.manifest['draft_sha256'],
            'category': 'grammar', 'severity': 'warning', 'impact': 'low',
            'location': {'block_id': self.block['block_id'], 'story': self.block['story'],
                         'char_start': 0, 'char_end': len(self.block['text']), 'heading_path': []},
            'excerpt': self.block['text'], 'suggestion': 'Change consider to considers.',
            'message': 'The singular subject needs a singular verb.',
            'replacement': self.block['text'].replace('consider', 'considers'),
        }
        self.chunk_path = next(path for path in (self.run / 'agent-results').glob('*.json') if '-audit' not in path.name)
        self.raise_findings([self.finding])

    def call(self, script, *args, ok=True):
        result = self.fixture.call(script, self.run, *args)
        if ok:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def raise_findings(self, rows, path=None):
        path = path or self.chunk_path
        result = read_json(path)
        result['findings'] = rows
        write_json(path, result)
        self.call('merge_findings.py')

    def disposition(self, **fields):
        row = dict(finding_id='EXACT1', status='confirmed', rationale='Reviewed in context.', **fields)
        write_jsonl(self.run / 'dispositions.jsonl', [row])
        return row

    def final(self):
        self.call('build_report.py')
        return read_jsonl(self.run / 'dispositions.jsonl')[0]

    def test_option_and_confirmed_final_record(self):
        self.assertIs(self.manifest['replacements'], True)
        self.assertIn('optional string `replacement`', (self.run / 'references/finding-schema.md').read_text())
        self.disposition()
        final = self.final()
        self.assertEqual(final['replacement'], self.finding['replacement'])
        effective = effective_finding(read_jsonl(self.run / 'findings.jsonl')[0], final)
        self.assertEqual(effective['excerpt'], self.finding['excerpt'])
        self.assertEqual(effective['location'], self.finding['location'])
        self.call('validate_run.py', '--require-ready')
        self.assertEqual(self.final(), final)  # Rebuilding does not change a correction.

    def test_every_worker_origin_and_challenger_carries_the_field(self):
        paths = [self.chunk_path, next((self.run / 'agent-results').glob('*-audit.json')),
                 next((self.run / 'lane-results').glob('*.json')),
                 next((self.run / 'recall-results').glob('*.json'))]
        for path in paths:
            with self.subTest(path=path.name):
                self.raise_findings([])
                self.raise_findings([self.finding], path)
                self.assertEqual(read_jsonl(self.run / 'findings.jsonl')[0]['replacement'], self.finding['replacement'])
                result = read_json(path)
                result['findings'] = []
                write_json(path, result)
        write_jsonl(self.run / 'challenger-findings.jsonl', [self.finding])
        self.call('merge_findings.py')
        self.assertEqual(read_jsonl(self.run / 'findings.jsonl')[0]['replacement'], self.finding['replacement'])

    def test_deduplication_transfers_only_compatible_corrections_and_drops_conflicts(self):
        first = dict(self.finding, finding_id='A')
        first.pop('replacement')
        second = dict(self.finding, finding_id='B')
        self.raise_findings([first, second])
        merged = read_jsonl(self.run / 'findings.jsonl')
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]['replacement'], second['replacement'])
        self.assertEqual(merged[0]['merged_finding_ids'], ['A', 'B'])
        self.raise_findings([first, dict(second, suggestion='A different correction.')])
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
        self.raise_findings([dict(first, quoted_material=True), second])
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
        self.raise_findings([dict(first, replacement=second['replacement']),
                             dict(second, replacement='A conflicting correction.'),
                             dict(second, finding_id='C')])
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])

    def test_later_merge_revision_cannot_reuse_the_old_replacement(self):
        self.raise_findings([dict(self.finding, suggestion='Make a different correction.')])
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
        self.call('merge_findings.py')
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
        self.disposition()
        self.assertNotIn('replacement', self.final())
        self.call('merge_findings.py')
        self.assertNotIn('replacement', self.final())

    def test_final_disposition_does_not_mask_later_candidate_changes(self):
        self.disposition()
        self.assertIn('replacement', self.final())
        finding = read_jsonl(self.run / 'findings.jsonl')[0]
        finding['severity'] = 'error'
        write_jsonl(self.run / 'findings.jsonl', [finding])
        self.assertNotIn('replacement', self.final())
        self.assertNotIn('replacement', self.final())

    def test_each_bound_field_revision_drops_inherited_replacement(self):
        finding = bind(self.finding, True, self.blocks)
        variants = {
            'suggestion': 'A different correction.',
            'excerpt': 'court consider',
            'location': dict(self.finding['location'], char_start=4, char_end=18),
            'severity': 'error',
        }
        for key, value in variants.items():
            with self.subTest(field=key):
                ledger, final = resolve(finding, {'status': 'confirmed', key: value}, [], self.blocks)
                self.assertNotIn('replacement', ledger)
                self.assertNotIn('replacement', final)
        _, final = resolve(finding, {'status': 'confirmed', 'rationale': 'Clearer diagnosis.'}, [], self.blocks)
        self.assertEqual(final['replacement'], finding['replacement'])

    def test_new_correction_after_each_kind_of_revision(self):
        finding = bind(self.finding, True, self.blocks)
        short = dict(excerpt='consider', location=dict(self.finding['location'], char_start=10, char_end=18), replacement='considers')
        for update in (dict(suggestion='A revised instruction.', replacement=finding['replacement']),
                       dict(severity='error', replacement=finding['replacement']), short):
            with self.subTest(update=update):
                _, final = resolve(finding, dict(status='confirmed', **update), [], self.blocks)
                self.assertEqual(final['replacement'], update['replacement'])

    def test_new_disposition_correction_and_later_manual_edit(self):
        self.disposition(suggestion='A revised instruction.', replacement=self.finding['replacement'])
        final = self.final()
        self.assertEqual(final['replacement'], self.finding['replacement'])
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
        final['severity'] = 'error'
        write_jsonl(self.run / 'dispositions.jsonl', [final])
        self.call('validate_run.py', '--require-ready', ok=False)
        self.assertNotIn('replacement', self.final())

    def test_new_replacement_can_correct_a_revised_span(self):
        self.disposition(excerpt='consider', location=dict(self.finding['location'], char_start=10, char_end=18),
                         replacement='considers')
        final = self.final()
        self.assertEqual(final['replacement'], 'considers')
        self.assertEqual(final['location']['char_start'], 10)
        self.call('validate_run.py', '--require-ready')

    def test_rejected_waived_queries_and_other_exclusions_never_carry_inherited_edits(self):
        for status in ('rejected', 'waived', 'query', 'style', 'prepublication'):
            with self.subTest(status=status):
                write_jsonl(self.run / 'findings.jsonl', [bind(self.finding, True, self.blocks)])
                write_jsonl(self.run / 'dispositions.jsonl', [{'finding_id': 'EXACT1', 'status': status, 'rationale': 'Review.'}])
                self.assertNotIn('replacement', self.final())
                self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
                self.call('validate_run.py', '--require-ready')
        for extra in ({'quoted_material': True}, {'requires_author_judgment': True},
                      {'excerpt_only': False}, {'category': 'formatting'}):
            _, final = resolve(bind(self.finding, True, self.blocks), {'status': 'confirmed', **extra}, [], self.blocks)
            self.assertNotIn('replacement', final)

    def test_invalid_types_and_ineligible_findings_fail_before_merge(self):
        for extra in ({'replacement': 12}, {'replacement': None}, {'replacement': []},
                      {'replacement': {}}, {'replacement': True}, {'category': 'formatting'},
                      {'severity': 'query'}, {'quoted_material': True}, {'requires_author_judgment': True},
                      {'excerpt_only': False}, {'status': 'rejected'}, {'status': 'waived'}):
            with self.subTest(extra=extra):
                result = read_json(self.chunk_path)
                result['findings'] = [dict(self.finding, **extra)]
                write_json(self.chunk_path, result)
                self.assertIn('replacement', self.call('validate_run.py', ok=False).stderr)
                self.call('merge_findings.py', ok=False)

    def test_invalid_replacement_in_every_ledger_or_audit_is_checked(self):
        for name in ('static-findings.jsonl', 'challenger-findings.jsonl', 'findings.jsonl'):
            original = read_jsonl(self.run / name)
            write_jsonl(self.run / name, [dict(self.finding, replacement=42)])
            self.assertIn('replacement must be a string', self.call('validate_run.py', ok=False).stderr)
            write_jsonl(self.run / name, original)
        self.disposition(replacement=42)
        self.call('validate_run.py', ok=False)
        self.disposition()
        for name, extra in (
            ('verifier-audit.jsonl', {'audit_status': 'revised', 'final_disposition': {'status': 'confirmed', 'replacement': 42}}),
            ('rejection-audit.jsonl', {'rejection_status': 'revised', 'revised_replacement': 42}),
        ):
            write_jsonl(self.run / name, [{'finding_id': 'EXACT1', **extra}])
            self.assertIn('replacement must be a string', self.call('validate_run.py', ok=False).stderr)
            write_jsonl(self.run / name, [])

    def test_exact_whitespace_unicode_and_source_span(self):
        row = deepcopy(self.finding)
        row['excerpt'] = 'The  court\tconsider this “rule”.'
        row['location']['char_end'] = len(row['excerpt'])
        row['replacement'] = row['excerpt'].replace('consider', 'considers')
        blocks = {self.block['block_id']: dict(self.block, text=row['excerpt'])}
        from merge_findings import normalize_agent_finding
        normalized = normalize_agent_finding(row, 'HASH', 'chunk_agent', 'C1', True)
        self.assertEqual(bind(normalized, True, blocks)['replacement'], row['replacement'])
        self.assertEqual(normalized['excerpt'], row['excerpt'])
        for excerpt in (row['excerpt'].replace('  ', ' '), '…' + row['excerpt']):
            with self.assertRaises(ValueError):
                validate_replacement(dict(row, excerpt=excerpt), blocks)
        with self.assertRaises(ValueError):
            validate_replacement(row, {self.block['block_id']: dict(blocks[self.block['block_id']], kind='blockquote')})

    def test_absent_empty_and_noop_fields_are_omitted(self):
        for value in ('', self.finding['excerpt'], None):
            row = dict(self.finding)
            if value is None:
                row.pop('replacement')
            else:
                row['replacement'] = value
            self.raise_findings([row])
            self.disposition()
            self.assertNotIn('replacement', self.final())
            self.call('validate_run.py', '--require-ready')

    def test_revised_verifier_outcome_reaches_final_record(self):
        for value in ('new', '', None):
            with self.subTest(value=value):
                write_jsonl(self.run / 'findings.jsonl', [bind(self.finding, True, self.blocks)])
                final = {
                    'status': 'confirmed', 'suggestion': 'A revised action.', 'rationale': 'A clearer diagnosis.'}
                if value is not None:
                    final['replacement'] = self.finding['replacement'] if value == 'new' else ''
                write_jsonl(self.run / 'dispositions.jsonl', [dict(final, finding_id='EXACT1')])
                write_jsonl(self.run / 'verifier-audit.jsonl', [{
                    'finding_id': 'EXACT1', 'source_sha256': self.manifest['draft_sha256'],
                    'audit_status': 'revised', 'final_disposition': final}])
                actual = self.final()
                if value == 'new':
                    self.assertEqual(actual['replacement'], self.finding['replacement'])
                else:
                    self.assertNotIn('replacement', actual)
                self.call('validate_run.py', '--require-ready')

    def test_verifier_correction_does_not_revive_after_location_changes(self):
        final = dict(status='confirmed', suggestion='Use the singular verb.', rationale='A clearer diagnosis.',
                     replacement=self.finding['replacement'])
        write_jsonl(self.run / 'verifier-audit.jsonl', [{'finding_id': 'EXACT1',
            'source_sha256': self.manifest['draft_sha256'], 'audit_status': 'revised', 'final_disposition': final}])
        write_jsonl(self.run / 'dispositions.jsonl', [dict(final, finding_id='EXACT1')])
        result = self.final()
        self.assertIn('replacement', result)
        result.update(excerpt='consider', location=dict(self.finding['location'], char_start=10, char_end=18))
        write_jsonl(self.run / 'dispositions.jsonl', [result])
        self.assertNotIn('replacement', self.final())
        self.assertNotIn('replacement', self.final())

    def test_audit_keeps_unchanged_or_diagnosis_only_corrections(self):
        finding = bind(self.finding, True, self.blocks)
        for audit, disposition in (
            ({'audit_status': 'confirmed'}, {'status': 'confirmed'}),
            ({'rejection_status': 'reopen'}, {'status': 'confirmed'}),
            ({'audit_status': 'revised', 'final_disposition': {'rationale': 'Clearer diagnosis.'}}, {'status': 'confirmed'}),
        ):
            _, final = resolve(finding, disposition, [audit], self.blocks)
            self.assertEqual(final['replacement'], finding['replacement'])
        for audit in ({'audit_status': 'retracted'}, {'rejection_status': 'confirmed_rejection'}):
            _, final = resolve(finding, {'status': 'rejected'}, [audit], self.blocks)
            self.assertNotIn('replacement', final)
        audit = bind_audit({'rejection_status': 'revised', 'revised_replacement': ''},
                           dict(finding, quoted_material=True), self.blocks)
        self.assertEqual(audit['revised_replacement'], '')

    def test_invalid_raw_lane_recall_and_clean_audit_are_not_hidden(self):
        paths = [next((self.run / 'lane-results').glob('*.json')),
                 next((self.run / 'recall-results').glob('*.json')),
                 next((self.run / 'agent-results').glob('*-audit.json'))]
        for path in paths:
            original = read_json(path)
            write_json(path, dict(original, findings=[dict(self.finding, replacement=42)]))
            self.assertIn('replacement must be a string', self.call('validate_run.py', ok=False).stderr)
            write_json(path, original)

    def test_rejection_audit_revision_withdrawal_and_reopen(self):
        row = dict(self.finding, impact='high', category='possible_omission')
        self.raise_findings([row])
        write_jsonl(self.run / 'dispositions.jsonl', [{'finding_id': 'EXACT1', 'status': 'rejected', 'rationale': 'Provisional.'}])
        self.call('make_rejection_packets.py')
        packet = (self.run / 'rejection-packets/RP0001.md').read_text()
        self.assertIn(self.finding['replacement'], packet)
        self.assertIn('revised_replacement', packet)
        write_jsonl(self.run / 'verifier-audit.jsonl', [{'finding_id': 'EXACT1',
            'source_sha256': self.manifest['draft_sha256'], 'audit_status': 'confirmed'}])
        for value in ('new', '', None):
            with self.subTest(value=value):
                self.raise_findings([row])
                audit = {'finding_id': 'EXACT1', 'source_sha256': self.manifest['draft_sha256'],
                         'rejection_status': 'revised', 'rationale': 'A defect is present.',
                         'revised_suggestion': 'Use the singular verb.'}
                if value is not None:
                    audit['revised_replacement'] = row['replacement'] if value == 'new' else ''
                write_jsonl(self.run / 'rejection-results/RP0001.jsonl', [audit])
                self.call('merge_rejection_audit.py')
                self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
                self.disposition(suggestion=audit['revised_suggestion'])
                final = self.final()
                if value == 'new':
                    self.assertEqual(final['replacement'], row['replacement'])
                else:
                    self.assertNotIn('replacement', final)
                self.call('validate_run.py', '--require-ready')

    def test_default_mode_ignores_even_malformed_fields_and_does_not_emit_them(self):
        self.manifest['replacements'] = False
        write_json(self.run / 'run-manifest.json', self.manifest)
        self.raise_findings([dict(self.finding, replacement={'invalid': True})])
        self.assertNotIn('replacement', read_jsonl(self.run / 'findings.jsonl')[0])
        self.disposition(replacement=42)
        self.call('validate_run.py')
        self.assertNotIn('replacement', self.final())
        self.call('validate_run.py', '--require-ready')
        # Rejection packet payloads and the canonical audit ignore nested extras too.
        finding = dict(self.finding, category='possible_omission', impact='high', replacement=42)
        write_jsonl(self.run / 'findings.jsonl', [finding])
        write_jsonl(self.run / 'dispositions.jsonl', [{'finding_id': 'EXACT1', 'status': 'rejected', 'rationale': 'False positive.'}])
        self.call('make_rejection_packets.py')
        self.assertNotIn('"replacement"', (self.run / 'rejection-packets/RP0001.md').read_text())
        write_jsonl(self.run / 'rejection-results/RP0001.jsonl', [{
            'finding_id': 'EXACT1', 'source_sha256': self.manifest['draft_sha256'],
            'rejection_status': 'confirmed_rejection', 'rationale': 'False positive.',
            'replacement': 42, 'revised_replacement': [], 'extra': {'replacement': False}}])
        self.call('merge_rejection_audit.py')
        self.assertNotIn('replacement', (self.run / 'rejection-audit.jsonl').read_text())
        self.assertNotIn('replacement', self.final())


if __name__ == '__main__':
    unittest.main()
