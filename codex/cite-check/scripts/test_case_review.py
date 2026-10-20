#!/usr/bin/env python3
"""Offline end-to-end schema-v6 gates, including publication and legacy compatibility."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import findings_diff as f

HERE = Path(__file__).resolve().parent


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


class ReviewTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        draft = root / 'draft.md'; draft.write_text('A proposition.[^1]\n\n[^1]: Alpha v. Beta, 1 F.3d 2 (2000).\n')
        self.run = root / 'run'
        p = subprocess.run([sys.executable, str(HERE / 'init_run.py'), str(draft), '--run-dir', str(self.run)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        self.manifest = json.loads((self.run / 'run-manifest.json').read_text())
        self.assertEqual(self.manifest['schema_version'], 6)
        self.manifest.update(status='ready_for_validation', completion_target='complete')
        self.manifest['counts'].update(prepared_units=0, quote_checks=0, verified=1, partial=0, mismatch=0, unverified=0, existence_only=1)
        text = 'Alpha v. Beta, 1 F.3d 2 (2000).'
        write_rows(self.run / 'citation-units.jsonl', [{'unit_id': 'U1', 'source_id': 'S1', 'source_type': 'case', 'footnote_number': 1, 'full_footnote': text, 'draft_citation_text': text, 'resolved_source_label': text, 'draft_find_string': text, 'caption_in_draft': 'footnote'}])
        write_rows(self.run / 'source-ledger.jsonl', [{'source_id': 'S1', 'source_type': 'case', 'canonical_citation': text, 'status': 'metadata_only', 'verification_basis': 'metadata_only'}])
        write_rows(self.run / 'footnote-coverage.jsonl', [{'footnote_number': 1, 'status': 'reviewed', 'unit_ids': ['U1']}])
        write_rows(self.run / 'body-coverage.jsonl', [{'paragraph_number': 1, 'status': 'no_citations', 'unit_ids': [], 'reason': 'Citation is in note.'}])
        self.verdict = {'verdict_id': 'V1', 'unit_id': 'U1', 'status': 'verified', 'severity': 'info', 'category': 'verified_identity', 'verification_basis': 'metadata_only', 'evidence': 'Primary metadata', 'suggested_action': 'none', 'identity_confirmed': True, 'support_read': False}
        def check(names):
            return {'status': 'checked', 'routes': [{'route': n, 'status': 'checked', 'query': 'fixture query', 'checked_at': '2026-10-19', 'evidence': 'fixture result, no hits'} for n in names]}
        self.review = {'source_id': 'S1', 'history': check(['docket', 'later_opinions']), 'treatment': check(['graph', 'name']), 'findings': []}
        self.report = "# Cite Check\nCreated by: Codex\nModel: fixture\nGenerated: fixture\nElapsed: fixture\nTokens: unavailable\n\nExistence-only: 1 of 1 citation instances were confirmed to exist but not read for proposition support.\n\n## Needs your attention\nNone\n\n## Subsequent history & treatment\nCase review S1: history=checked; treatment=checked.\n\n## Couldn't check\nNone\n"

    def validate(self, *, refresh=True, mark=False):
        (self.run / 'run-manifest.json').write_text(json.dumps(self.manifest))
        write_rows(self.run / 'verdicts.jsonl', [self.verdict])
        write_rows(self.run / 'case-review.jsonl', [] if self.review is None else [self.review])
        (self.run / 'report.md').write_text(self.report)
        if refresh:
            (self.run / 'findings.json').write_text(json.dumps(f.snapshot(self.run)))
        return subprocess.run([sys.executable, str(HERE / 'validate_run.py'), str(self.run), '--require-ready', *(['--mark-complete'] if mark else [])], capture_output=True, text=True)

    def test_ready_and_postcompletion_findings_are_stable(self):
        result = self.validate(mark=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        manifest = json.loads((self.run / 'run-manifest.json').read_text())
        self.assertEqual(manifest['status'], 'complete')
        self.assertEqual(json.loads((self.run / 'findings.json').read_text()), f.snapshot(self.run))

    def test_missing_case_or_one_route_rejected(self):
        self.review['treatment']['routes'].pop()
        self.assertIn('lacks required routes', self.validate().stderr)
        self.review = None
        self.assertIn('exactly one row per cited case', self.validate().stderr)

    def test_skipped_pass_requires_limits_and_report_disclosure(self):
        self.review['history'] = {'status': 'skipped', 'reason': 'No docket access.', 'unlock_path': 'Obtain official docket.'}
        self.assertIn('complete_with_limits', self.validate().stderr)
        self.manifest['completion_target'] = 'complete_with_limits'
        self.report = self.report.replace('history=checked', 'history=skipped') + '\nNo docket access. Obtain official docket.\n'
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_false_not_applicable_and_truncated_coverage_rejected(self):
        self.review['history']['status'] = 'not_applicable'
        self.assertIn('only identified Supreme Court', self.validate().stderr)
        self.review['history']['status'] = 'checked'
        self.review['history']['routes'][0]['truncated'] = True
        self.assertIn('must remain partial', self.validate().stderr)

    def test_existence_only_count_and_actual_speaker(self):
        self.report = self.report.replace('1 of 1 citation', '0 of 1 citation')
        self.assertIn('accurate existence-only', self.validate().stderr)
        self.verdict['category'] = 'misattributed'
        self.assertIn('actual_speaker', self.validate().stderr)

    def test_stale_findings_and_unsupported_support_claim(self):
        self.assertEqual(self.validate().returncode, 0)
        (self.run / 'findings.json').write_text('{}')
        self.assertIn('stale', self.validate(refresh=False).stderr)
        self.verdict.update(support_read=True)
        self.assertIn('retrieved full-text', self.validate().stderr)

    def test_history_requires_draft_location_and_rule_basis(self):
        self.review['findings'] = [{'unit_id': 'U1', 'kind': 'history', 'verdict': 'omitted_required_history', 'find': 'invented string', 'label': 'Add disposition', 'evidence': 'Docket order'}]
        error = self.validate().stderr
        self.assertIn('find-string absent', error)
        self.assertIn('Rule 10.7 basis', error)

    def test_v5_remains_readable_without_new_records(self):
        self.manifest['schema_version'] = 5
        self.review = None
        self.verdict.pop('support_read'); self.verdict.pop('identity_confirmed')
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_rerun_requires_frozen_previous_and_opening_diff(self):
        self.assertEqual(self.validate().returncode, 0)
        old = self.run / 'previous-findings.json'
        old.write_bytes((self.run / 'findings.json').read_bytes())
        self.manifest['previous_findings_sha256'] = hashlib.sha256(old.read_bytes()).hexdigest()
        self.assertIn('open with the current findings diff', self.validate().stderr)
        previous = json.loads(old.read_text())
        current = f.snapshot(self.run)
        block = f.render(previous, current, f.diff(previous, current))
        self.report = self.report.replace('## Needs your attention', block + '\n## Needs your attention')
        result = self.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        old.write_text('{}')
        self.assertIn('hash differs', self.validate().stderr)


if __name__ == '__main__':
    unittest.main()
