#!/usr/bin/env python3
"""Regressions from the focused DOCX smoke test; no private draft required."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extract_cites import footnote_anchors
from prepare_support_units import build_support_units
from support_screen import screen_clause, signal_of
from support_validation import support_counts, support_sentence, validate_support
from test_support import support_fixture

HERE = Path(__file__).resolve().parent


def rebuild(args):
    args[4] = build_support_units(args[1], args[2], args[3], args[0]['support_pass']['scope'])
    args[0]['counts']['support'] = support_counts(args[4], args[5], args[6])
    args[-1] = ('Existence-only: fixture\n' + support_sentence(args[0]['counts']['support'])
                + '\n## Needs your attention\nNone\n## Proposition support\n')


def errors(args):
    result = []
    validate_support(*args, result)
    return result


class JournalScreeningTests(unittest.TestCase):
    def test_journal_opening_pages_and_real_pins(self):
        for reporter, volume, first, pin in [
            ('Yale L.J.', '121', '1286', '1290–92'),
            ('Fordham Urb. L.J.', '31', '1507', '1532'),
            ('B.C. L. Rev.', '66', '1679', '1723'),
            ('N.Y.U. L. Rev.', '91', '762', '780'),
            ('Parliamentary Affairs', '61', '681', '688'),
        ]:
            for cited_pin in ('', pin):
                with self.subTest(reporter=reporter, pin=cited_pin):
                    citation = (f'See generally Author, Article Title, {volume} {reporter} '
                                f'{first}' + (f', {cited_pin}' if cited_pin else '') + ' (2020).')
                    screened = screen_clause(citation)
                    self.assertEqual(screened['kind_hint'], 'article')
                    self.assertEqual(screened['pincite'], cited_pin)
                    # A stale book hint must not turn the opening page into a pin.
                    self.assertEqual(screen_clause(citation, 'book')['pincite'], cited_pin)
                    unit = dict(screened, unit_id='U1', source_id='S1', source_type='article',
                                footnote_number=1, resolved_source_label=citation)
                    row = build_support_units({'footnotes': [{'number': 1, 'text': citation}]}, [unit])[0]
                    self.assertEqual(row['scope'], 'pincited' if cited_pin else 'whole-work')
                    self.assertEqual(row.get('unread_reason'), None if cited_pin else 'out_of_scope')
        self.assertEqual(screen_clause('Author, Book Title 45 (2020).')['pincite'], '45')
        self.assertEqual(screen_clause('Author, Book Title (2020).')['pincite'], '')

    def test_combined_background_signal_and_gate(self):
        for prefix in ('See also generally', '*See also generally*',
                       'For background, see also generally', 'SEE ALSO GENERALLY'):
            self.assertEqual(signal_of(prefix + ' Author, 121 Yale L.J. 1286 (2012).'), 'see generally')
        args = list(support_fixture())
        citation = 'See also generally Author, 121 Yale L.J. 1286 (2012) (describing the rule).'
        args[1]['footnotes'][0]['text'] = citation
        args[2][0].update(screen_clause(citation), source_type='article')
        args[5][0]['support']['signal'] = 'see generally'
        rebuild(args)
        self.assertEqual(args[4][0]['scope'], 'pincited')
        self.assertEqual(args[4][0]['pincite'], '')
        self.assertEqual(errors(args), [])
        # Rebuilding stale lead-confirmed fields must not silently restore direct support.
        args[2][0]['signal'] = args[5][0]['support']['signal'] = 'see also'
        rebuild(args)
        self.assertTrue(any('background meaning' in e for e in errors(args)))

    def test_initializer_to_support_units(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); draft = root/'draft.md'; run = root/'run'
            draft.write_text('Background.[^1] More background.[^2]\n\n'
                             '[^1]: See generally Author, 121 Yale L.J. 1286 (2012).\n'
                             '[^2]: See also generally Author, 66 B.C. L. Rev. 1679 (2025) '
                             '(describing the rule).\n')
            result = subprocess.run([sys.executable, str(HERE/'init_run.py'), str(draft),
                                     '--run-dir', str(run), '--support'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            screened = [json.loads(l) for l in (run/'citation-screening.jsonl').read_text().splitlines()]
            units = [dict(row, unit_id=f'U{i}', source_id=f'S{i}', source_type=row['kind_hint'],
                          resolved_source_label=row['draft_citation_text'])
                     for i, row in enumerate(screened, 1)]
            (run/'citation-units.jsonl').write_text(''.join(json.dumps(u)+'\n' for u in units))
            result = subprocess.run([sys.executable, str(HERE/'prepare_support_units.py'), str(run)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = [json.loads(l) for l in (run/'support-units.jsonl').read_text().splitlines()]
            self.assertEqual([u['source_type'] for u in units], ['article', 'article'])
            self.assertEqual([r['pincite'] for r in rows], ['', ''])
            self.assertEqual([r['signal'] for r in rows], ['see generally', 'see generally'])
            self.assertEqual([r['scope'] for r in rows], ['whole-work', 'pincited'])


class MidSentenceScopeTests(unittest.TestCase):
    def fixture(self, text='The Example Act[[FN:1]] requires an annual report.'):
        args = list(support_fixture())
        args[1]['footnotes'][0]['anchor'] = footnote_anchors([text])['1']
        rebuild(args)
        support = args[5][0]['support']
        support.update(claim=args[4][0]['anchor']['clause'], claim_basis='anchor.clause')
        return args

    def test_name_only_cannot_pass_without_scope_review(self):
        args = self.fixture()
        self.assertEqual(args[5][0]['support']['claim'], 'The Example Act')
        self.assertTrue(any('claim_scope_review' in e for e in errors(args)))
        for review in (None, {}, {'prefix_is_proposition': 'false', 'reason': 'Reviewed.'},
                       {'prefix_is_proposition': False, 'reason': ' '}):
            args[5][0]['support']['claim_scope_review'] = review
            self.assertTrue(any('claim_scope_review' in e for e in errors(args)))

    def test_reviewed_whole_sentence_fallback(self):
        args = self.fixture(); support = args[5][0]['support']
        support['claim_scope_review'] = {
            'prefix_is_proposition': False,
            'reason': 'The marker follows the statute name; its cited section governs the entire reporting requirement.'}
        self.assertTrue(any('conflicts with reviewed prefix scope' in e for e in errors(args)))
        support.update(claim=args[4][0]['anchor']['sentence'], claim_basis='anchor.sentence')
        self.assertEqual(errors(args), [])
        support['claim'] = 'The Example Act always requires annual reports.'
        self.assertTrue(any('claim not verbatim' in e for e in errors(args)))

    def test_assertive_prefix_stays_with_its_clause(self):
        args = self.fixture('The Act requires a report[[FN:1]], but the Rule grants an extension.')
        support = args[5][0]['support']
        support['claim_scope_review'] = {
            'prefix_is_proposition': True,
            'reason': 'The statute citation supports the first clause; the later exception belongs to a different authority.'}
        self.assertEqual(errors(args), [])
        support.update(claim=args[4][0]['anchor']['sentence'], claim_basis='anchor.sentence')
        self.assertTrue(any('conflicts with reviewed prefix scope' in e for e in errors(args)))

    def test_parenthetical_and_unverifiable_preserve_their_scope(self):
        args = self.fixture()
        citation = 'See A, 1 U.S. 2, 3 (2000) (requiring an annual report).'
        args[1]['footnotes'][0]['text'] = citation
        args[2][0].update(screen_clause(citation))
        args[5][0]['support'].update(claim='requiring an annual report', claim_basis='parenthetical')
        rebuild(args)
        self.assertEqual(errors(args), [])
        args = self.fixture()
        args[5][0].update(status='unverified', category='source_unavailable', support_read=False,
                         unlock_path='Clarify which claim this citation is responsible for.')
        args[5][0]['support']['verdict'] = 'unverifiable'
        rebuild(args)
        self.assertEqual(errors(args), [])
        self.assertEqual(args[0]['counts']['support']['read'], 3)


if __name__ == '__main__':
    unittest.main()
