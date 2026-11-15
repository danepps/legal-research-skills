#!/usr/bin/env python3
"""Offline regression tests for audited findings and their final ledger state."""
import unittest

import findings_diff
import test_case_review as fixtures


class AuditOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.assertEqual(self.fixture.validate().returncode, 0)

    def adverse(self):
        f = self.fixture
        f.verdict.update(status='mismatch', severity='high', category='quote_mismatch',
                         draft_find_string='Alpha v. Beta', suggested_action='Correct the quotation.')
        f.manifest['counts'].update(verified=0, mismatch=1)

    def audit(self, status, **fields):
        fixtures.write_rows(self.fixture.run / 'verifier-audit.jsonl', [{
            'verdict_id': 'V1', 'audit_status': status,
            'evidence': 'Independent inspection of the source passage.', **fields,
        }])

    def test_retraction_cannot_leave_a_live_finding(self):
        self.adverse()
        self.audit('retracted')
        result = self.fixture.validate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('retracted audit', result.stderr)
        self.fixture.verdict.update(status='verified', category='verified_identity', severity='info')
        self.fixture.manifest['counts'].update(verified=1, mismatch=0)
        self.assertEqual(self.fixture.validate().returncode, 0)
        self.assertEqual(findings_diff.snapshot(self.fixture.run)['items'], [])

    def test_revision_requires_applied_outcome_and_keeps_corrected_finding(self):
        self.adverse()
        self.audit('revised')
        self.assertNotEqual(self.fixture.validate().returncode, 0)
        fields = ('status', 'category', 'severity', 'suggested_action')
        initial = {k: self.fixture.verdict[k] for k in fields}
        final = dict(initial, category='pincite_error', severity='medium', suggested_action='Use paragraph 4.')
        self.audit('revised', initial_verdict=initial, final_verdict=final)
        self.assertNotEqual(self.fixture.validate().returncode, 0)
        self.fixture.verdict.update(final, pagination_convention='paragraph_number')
        result = self.fixture.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        items = findings_diff.snapshot(self.fixture.run)['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['verdict'], 'pincite_error')
        self.audit('revised', initial_verdict=final, final_verdict=final)
        self.assertNotEqual(self.fixture.validate().returncode, 0)

    def test_confirmed_legacy_audit_remains_valid(self):
        self.adverse()
        self.audit('confirmed')
        self.assertEqual(self.fixture.validate().returncode, 0)


if __name__ == '__main__':
    unittest.main()
