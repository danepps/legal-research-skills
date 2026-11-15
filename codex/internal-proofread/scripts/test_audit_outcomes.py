#!/usr/bin/env python3
"""Exercise final dispositions through report generation and readiness."""
import json
import unittest

import test_workflow_integrity as fixtures


class AuditOutcomeTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowIntegrityTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.initialize('The court found that that rule applies here.\n')
        self.run = self.fixture.run
        self.finding = fixtures.read_rows(self.run / 'findings.jsonl')[0]
        self.finding.update(impact='high', category='grammar')
        self.write('findings.jsonl', [self.finding])

    def write(self, name, rows):
        (self.run / name).write_text(''.join(json.dumps(row) + '\n' for row in rows))

    def validate(self, status, audit_status, **extra):
        disposition = {'finding_id': self.finding['finding_id'], 'status': status, 'rationale': 'Reviewed in context.'}
        disposition.update(extra.pop('disposition', {}))
        self.write('dispositions.jsonl', [disposition])
        audit = {'finding_id': self.finding['finding_id'], 'source_sha256': self.finding['source_sha256'],
                 'audit_status': audit_status, **extra}
        self.write('verifier-audit.jsonl', [audit])
        self.assertEqual(self.fixture.call('build_report.py', self.run).returncode, 0)
        return self.fixture.call('validate_run.py', self.run, '--require-ready')

    def test_retraction_is_enforced_for_every_disposition_and_impact(self):
        for impact in ('high', 'low'):
            self.finding['impact'] = impact
            self.write('findings.jsonl', [self.finding])
            for status in ('confirmed', 'likely', 'query', 'fixed', 'waived', 'style', 'prepublication'):
                with self.subTest(impact=impact, status=status):
                    result = self.validate(status, 'retracted')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('retracted audit', result.stderr)
            result = self.validate('rejected', 'retracted')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn(self.finding['finding_id'], (self.run / 'report.md').read_text())

    def test_revision_must_reach_the_visible_report(self):
        self.assertNotEqual(self.validate('confirmed', 'revised').returncode, 0)
        final = {'status': 'confirmed', 'suggestion': 'Remove the second occurrence of that.',
                 'rationale': 'The repeated determiner is accidental in this sentence.'}
        self.assertNotEqual(self.validate('confirmed', 'revised', final_disposition=final).returncode, 0)
        result = self.validate('confirmed', 'revised', final_disposition=final, disposition=final)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(final['suggestion'], (self.run / 'report.md').read_text())
        self.assertIn(final['rationale'], (self.run / 'report.md').read_text())

    def test_duplicate_unknown_and_stale_audits_are_rejected(self):
        self.assertEqual(self.validate('confirmed', 'confirmed').returncode, 0)
        audit = fixtures.read_rows(self.run / 'verifier-audit.jsonl')[0]
        for rows in ([audit, dict(audit, audit_status='retracted')],
                     [audit, dict(audit, finding_id='UNKNOWN')],
                     [dict(audit, source_sha256='stale')]):
            with self.subTest(rows=rows):
                self.write('verifier-audit.jsonl', rows)
                self.assertNotEqual(self.fixture.call('validate_run.py', self.run, '--require-ready').returncode, 0)


if __name__ == '__main__':
    unittest.main()
