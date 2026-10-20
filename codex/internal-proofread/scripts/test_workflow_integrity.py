#!/usr/bin/env python3
"""Offline lifecycle tests for proofreading occurrence and completion integrity."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent

def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

def write_json(path, value):
    path.write_text(json.dumps(value) + '\n')

class WorkflowIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / '.run'

    def call(self, script, *args):
        return subprocess.run([sys.executable, str(SCRIPTS / script), *map(str, args)], capture_output=True, text=True)

    def initialize(self, text, *init_args):
        draft = self.root / 'Draft.md'
        draft.write_text(text)
        result = self.call('init_run.py', draft, '--run-dir', self.run, *init_args)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.run / 'run-manifest.json').read_text())
        for chunk in read_rows(self.run / 'chunks.jsonl'):
            result = {
                'chunk_id': chunk['chunk_id'], 'source_sha256': manifest['draft_sha256'], 'status': 'complete',
                'reviewed_block_ids': chunk['core_block_ids'], 'reviewed_note_ids': chunk['owned_note_ids'], 'findings': [],
            }
            write_json(self.run / 'agent-results' / f"{chunk['chunk_id']}.json", result)
            write_json(self.run / 'agent-results' / f"{chunk['chunk_id']}-audit.json", result)
        for lane in manifest['required_lanes']:
            write_json(self.run / 'lane-results' / f'{lane}.json', {
                'lane': lane, 'source_sha256': manifest['draft_sha256'], 'status': 'complete', 'findings': [],
            })
        self.assertEqual(self.call('merge_findings.py', self.run).returncode, 0)
        self.assertEqual(self.call('make_recall_packets.py', self.run).returncode, 0)
        for packet in read_rows(self.run / 'recall-packets.jsonl'):
            write_json(self.run / 'recall-results' / f"{packet['packet_id']}.json", {
                'packet_id': packet['packet_id'], 'source_sha256': manifest['draft_sha256'], 'status': 'complete',
                'reviewed_block_ids': packet['reviewed_block_ids'], 'reviewed_note_ids': packet['reviewed_note_ids'], 'findings': [],
            })
        self.assertEqual(self.call('merge_findings.py', self.run).returncode, 0)
        self.assertEqual(self.call('build_report.py', self.run).returncode, 0)

    def test_distinct_repeated_errors_remain_distinct(self):
        self.initialize('The court found that that rule applies here, and the court later confirmed that that conclusion governs another claim.\n')
        self.assertEqual(len(read_rows(self.run / 'static-findings.jsonl')), 2)
        findings = read_rows(self.run / 'findings.jsonl')
        self.assertEqual(len(findings), 2)
        self.assertEqual([row['location']['char_start'] for row in findings], [16, 75])
        report = (self.run / 'report.md').read_text()
        self.assertNotIn('B000001', report)
        self.assertIn('through draft', report)

    def test_missing_snapshot_blocks_readiness(self):
        self.initialize('This clean paragraph contains a complete sentence for a controlled offline review.\n')
        self.assertEqual(self.call('validate_run.py', self.run, '--require-ready').returncode, 0)
        self.assertEqual((self.run / 'source-snapshot.md').stat().st_mode & 0o222, 0)
        self.assertNotEqual((self.root / 'Draft.md').stat().st_mode & 0o222, 0)
        (self.run / 'source-snapshot.md').unlink()
        result = self.call('validate_run.py', self.run, '--require-ready')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('snapshot is missing', result.stderr)

    def test_malformed_findings_fail_merge_and_readiness(self):
        self.initialize('This clean paragraph contains a complete sentence for a controlled offline review.\n')
        chunk = read_rows(self.run / 'chunks.jsonl')[0]
        path = self.run / 'agent-results' / f"{chunk['chunk_id']}.json"
        result = json.loads(path.read_text())
        for malformed in ('The draft has an error.', {}, {'location': {'block_id': 'MISSING', 'char_start': 0, 'char_end': 1}, 'excerpt': 'invented'}):
            with self.subTest(finding=malformed):
                result['findings'] = [malformed]
                write_json(path, result)
                self.assertNotEqual(self.call('merge_findings.py', self.run).returncode, 0)
                self.assertNotEqual(self.call('validate_run.py', self.run, '--require-ready').returncode, 0)

    def test_same_occurrence_is_merged(self):
        self.initialize('The court found that that rule applies here.\n')
        original = read_rows(self.run / 'static-findings.jsonl')[0]
        chunk = read_rows(self.run / 'chunks.jsonl')[0]
        path = self.run / 'agent-results' / f"{chunk['chunk_id']}.json"
        result = json.loads(path.read_text())
        result['findings'] = [original]
        write_json(path, result)
        self.assertEqual(self.call('merge_findings.py', self.run).returncode, 0)
        self.assertEqual(len(read_rows(self.run / 'findings.jsonl')), 1)

    def test_missing_or_incomplete_clean_audit_blocks_readiness(self):
        self.initialize('This clean paragraph contains a complete sentence for a controlled offline review.\n')
        path = next((self.run / 'agent-results').glob('*-audit.json'))
        audit = json.loads(path.read_text())
        audit['reviewed_block_ids'] = []
        write_json(path, audit)
        result = self.call('validate_run.py', self.run, '--require-ready')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('clean-chunk audit coverage', result.stderr)
        path.unlink()
        result = self.call('validate_run.py', self.run, '--require-ready')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('clean-chunk audit requires', result.stderr)

    def test_high_impact_clean_audit_miss_requires_full_expansion(self):
        self.initialize('The court found that that rule applies here.\n\nAnother complete paragraph follows with no reported errors.\n\nA final complete paragraph closes this controlled review.\n', '--min-words', 1, '--target-words', 5, '--max-words', 10)
        chunks = read_rows(self.run / 'chunks.jsonl')
        self.assertEqual(len(chunks), 3)
        first_path = self.run / 'agent-results' / f"{chunks[0]['chunk_id']}-audit.json"
        result = json.loads(first_path.read_text())
        finding = read_rows(self.run / 'static-findings.jsonl')[0]
        finding['impact'] = 'high'
        result['findings'] = [finding]
        write_json(first_path, result)
        for chunk in chunks[1:]:
            (self.run / 'agent-results' / f"{chunk['chunk_id']}-audit.json").unlink()
        self.assertEqual(self.call('merge_findings.py', self.run).returncode, 0)
        finding = read_rows(self.run / 'findings.jsonl')[0]
        (self.run / 'dispositions.jsonl').write_text(json.dumps({'finding_id': finding['finding_id'], 'status': 'confirmed'}) + '\n')
        (self.run / 'verifier-audit.jsonl').write_text(json.dumps({'finding_id': finding['finding_id'], 'source_sha256': finding['source_sha256'], 'audit_status': 'confirmed'}) + '\n')
        self.call('build_report.py', self.run)
        result = self.call('validate_run.py', self.run, '--require-ready')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('review of every clean chunk', result.stderr)

if __name__ == '__main__':
    unittest.main()
