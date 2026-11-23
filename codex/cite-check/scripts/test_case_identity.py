#!/usr/bin/env python3
"""Offline, synthetic end-to-end tests for mismatch preservation at readiness."""
import json
import unittest
from unittest.mock import patch

import check_cite
from identity_validation import disclosure
from prepare_source_bundle import build_bundle
import test_case_review as fixtures


class CaseIdentityGates(unittest.TestCase):
    def setUp(self):
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
        guard.start(); self.addCleanup(guard.stop)
        guard = patch.object(check_cite, 'token', side_effect=AssertionError('credentials forbidden'))
        guard.start(); self.addCleanup(guard.stop)
        self.base = fixtures.ReviewTests()
        self.base.setUp(); self.addCleanup(self.base.doCleanups)
        self.run = self.base.run
        self.base.manifest['case_identity_version'] = 1
        self.unit = json.loads((self.run / 'citation-units.jsonl').read_text())
        self.unit.update(lookup_citation='1 F.3d 2', draft_case_name='Alpha v. Beta', draft_year=2000)
        self.screen('Gamma v. Delta', '2000-01-01')

    def screen(self, name, date):
        fixtures.write_rows(self.run / 'citation-units.jsonl', [self.unit])
        response = [{'citation': '1 F.3d 2', 'status': 200, 'clusters': [{'case_name': name, 'date_filed': date}]}]
        with patch.object(check_cite, 'request_json', return_value=response):
            self.row = check_cite.screen_units([self.unit])[0]
        fixtures.write_rows(self.run / 'case-identity-checks.jsonl', [self.row])

    def resolve(self, dimension='caption', disposition='finding'):
        category = 'identity_error' if dimension == 'caption' else 'metadata_error'
        resolution = {'disposition': disposition, 'category': category,
                      'evidence_opened': True, 'evidence_location': 'cached fixture first page',
                      'evidence': 'Synthetic fixture record inspected.',
                      'reason': 'Synthetic fixture establishes the comparison outcome.'}
        self.base.verdict.setdefault('identity_resolutions', {})[dimension] = resolution
        if disposition == 'finding':
            self.base.verdict.update(status='mismatch', category=category, severity='medium',
                                     identity_confirmed=dimension != 'caption',
                                     draft_find_string=self.unit['draft_citation_text'],
                                     suggested_action='Inspect the name and reporter citation before correcting.')
            self.base.manifest['counts'].update(verified=0, mismatch=1, existence_only=int(dimension != 'caption'))
            if dimension == 'caption':
                self.base.report = self.base.report.replace('Existence-only: 1 of 1', 'Existence-only: 0 of 1')
            else:
                self.base.verdict['metadata_record'] = {'opened': True, 'exact_work_checked': True,
                    'record_type': 'official_case_record', 'location': 'cached fixture first page', 'fields': ['year']}
        self.base.report += '\n' + disclosure(self.row, dimension, disposition) + '\n' + resolution['reason'] + '\n'

    def test_mismatch_cannot_pass_verified_then_passes_as_finding(self):
        result = self.base.validate(mark=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('unresolved caption mismatch', result.stderr)
        self.assertEqual(json.loads((self.run / 'run-manifest.json').read_text())['status'], 'ready_for_validation')
        self.resolve()
        result = self.base.validate(mark=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        snapshot = json.loads((self.run / 'findings.json').read_text())
        self.assertEqual(snapshot['items'][0]['identity_resolutions']['caption']['disposition'], 'finding')

    def test_year_finding_obeys_existing_metadata_provenance_gate(self):
        self.screen('Alpha v. Beta', '1999-01-01')
        self.assertIn('unresolved year mismatch', self.base.validate().stderr)
        self.resolve('year')
        self.base.verdict.pop('metadata_record')
        self.assertIn('lacks metadata_record', self.base.validate().stderr)
        self.base.verdict['metadata_record'] = {'opened': True, 'exact_work_checked': True,
            'record_type': 'official_case_record', 'location': 'cached fixture first page', 'fields': ['year']}
        result = self.base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_explicit_dismissal_needs_opened_evidence_and_public_reason(self):
        self.resolve(disposition='not_error')
        result = self.base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        resolution = self.base.verdict['identity_resolutions']['caption']
        resolution['evidence_opened'] = False
        self.assertIn('needs opened evidence', self.base.validate().stderr)
        resolution['evidence_opened'] = True
        self.base.report = self.base.report.replace(resolution['reason'], '')
        self.assertIn('report omits reason', self.base.validate().stderr)

    def test_dropped_row_or_edited_result_cannot_clear_mismatch(self):
        self.row['identity_comparison']['caption']['result'] = 'match'
        fixtures.write_rows(self.run / 'case-identity-checks.jsonl', [self.row])
        error = self.base.validate().stderr
        self.assertIn('altered identity_comparison', error)
        self.assertIn('unresolved caption mismatch', error)
        fixtures.write_rows(self.run / 'case-identity-checks.jsonl', [])
        self.assertIn('exactly one screen row', self.base.validate().stderr)
        (self.run / 'case-identity-checks.jsonl').rename(self.run / 'preserved-screen.jsonl')
        self.assertIn('case-identity-checks.jsonl', self.base.validate().stderr)

    def test_finding_cannot_be_omitted_from_report_or_marked_verified(self):
        self.resolve()
        self.base.report = self.base.report.replace(disclosure(self.row, 'caption', 'finding'), '')
        self.assertIn('report omits caption mismatch', self.base.validate().stderr)
        self.base.verdict.update(status='verified', identity_confirmed=True)
        error = self.base.validate().stderr
        self.assertIn('finding needs an adverse', error)
        self.assertIn('cannot confirm draft identity', error)

    def test_caption_input_must_be_from_the_declared_draft_location(self):
        self.unit['draft_case_name'] = 'Gamma v. Delta'
        self.screen('Gamma v. Delta', '2000-01-01')
        self.assertIn('caption must occur', self.base.validate().stderr)
        self.unit['draft_case_name'] = None
        self.screen('Gamma v. Delta', '2000-01-01')
        self.assertIn('caption must occur', self.base.validate().stderr)

    def test_each_mismatch_requires_its_own_resolution(self):
        self.screen('Gamma v. Delta', '1999-01-01')
        self.resolve()
        self.assertIn('unresolved year mismatch', self.base.validate().stderr)
        self.resolve('year')
        self.base.verdict.update(category='identity_error', identity_confirmed=False)
        self.base.manifest['counts']['existence_only'] = 0
        result = self.base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_legacy_manifest_still_checks_any_present_screen_ledger(self):
        self.base.manifest.pop('case_identity_version')
        self.assertIn('unresolved caption mismatch', self.base.validate().stderr)

    def test_worker_bundle_keeps_the_screen_with_the_draft(self):
        bundle = build_bundle(self.run, 'S1')
        self.assertEqual(bundle['case_identity_checks'], [self.row])
        self.assertEqual(bundle['citation_units'][0]['draft_case_name'], 'Alpha v. Beta')

    def test_high_severity_finding_still_requires_independent_audit(self):
        self.resolve()
        self.base.verdict['severity'] = 'high'
        self.assertIn('lacks required verifier audit', self.base.validate().stderr)
        fixtures.write_rows(self.run / 'verifier-audit.jsonl', [
            {'verdict_id': 'V1', 'audit_status': 'confirmed', 'evidence': 'Independent synthetic fixture inspection.'}])
        result = self.base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_caption_elsewhere_does_not_ground_body_location(self):
        # The original fixture's caption is in the footnote. An unrelated body
        # location must not be accepted simply because the text occurs elsewhere.
        self.unit.update(caption_in_draft='body', body_context='A proposition.')
        self.screen('Alpha v. Beta', '2000-01-01')
        self.assertIn('caption must occur', self.base.validate().stderr)

    def test_unscreened_access_is_disclosed_and_verified_only_with_opened_record(self):
        row = {'unit_id': 'U1', 'source_id': 'S1', 'lookup_state': 'not_screened',
               'reason': 'API unavailable.', 'unlock_path': 'Inspect the official record.'}
        fixtures.write_rows(self.run / 'case-identity-checks.jsonl', [row])
        self.assertIn('unscreened verification needs', self.base.validate().stderr)
        self.base.verdict['identity_evidence'] = {'evidence_opened': True,
            'evidence_location': 'cached fixture first page', 'evidence': 'Synthetic identity inspected.',
            'reason': 'Direct inspection confirms caption, reporter and year.'}
        self.base.report += '\nCase identity U1: not_screened; API unavailable.; Inspect the official record.\n'
        result = self.base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
