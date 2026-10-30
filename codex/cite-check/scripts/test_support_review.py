#!/usr/bin/env python3
"""Regressions for Claude's fourteen findings on the Codex support pass."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

import test_support as fixtures
from extract_cites import extract_document, W
from prepare_support_units import build_support_units, claim_bases
from support_screen import split_clauses, screen_clause, prose_clauses, signal_of
from support_validation import attention_section, validate_support, support_counts, support_sentence, read_overstatement
from findings_diff import diff, support_coverage
from verify_quotes import read_pages, printed_page, normalize, page_spans

HERE = Path(__file__).resolve().parent


def errors(args):
    result = []
    validate_support(*args, result)
    return result


def rebuild(args):
    args[4] = build_support_units(args[1], args[2], args[3], args[0]['support_pass']['scope'])
    args[0]['counts']['support'] = support_counts(args[4], args[5], args[6])
    args[-1] = 'Existence-only: fixture\n'+support_sentence(args[0]['counts']['support'])+'\n## Needs your attention\nNone\n## Proposition support\n'


class ScreeningReviewTests(unittest.TestCase):
    def test_2_compare_preserves_both_verbatim_clauses(self):
        text = 'Compare Roe v. Wade, 410 U.S. 113, 153 (1973), with Doe v. Bolton, 410 U.S. 179, 190 (1973).'
        clauses = split_clauses(text)
        self.assertEqual(len(clauses), 2)
        self.assertTrue(all(c in text for c in clauses))
        screened = [screen_clause(c) for c in clauses]
        self.assertEqual([s['signal'] for s in screened], ['compare', 'compare with'])
        self.assertEqual([s['pincite'] for s in screened], ['153', '190'])
        self.assertEqual(len(split_clauses('Compare A, 1 U.S. 2 (2000) (agreeing with B).')), 1)
        self.assertEqual(len(split_clauses('Compare A, 1 U.S. 2 (2000) “agreeing with B”.')), 1)
        a = list(fixtures.support_fixture())
        a[2][0]['signal'] = a[4][0]['signal'] = a[5][0]['support']['signal'] = 'compare with'
        self.assertEqual(errors(a), [])

    def test_3_nonproposition_parentheticals(self):
        for parenthesis in ['S.D.N.Y. Mar. 3, 2020', 'Jan. 5, 2020', 'last visited Jan. 5, 2020',
                            'Jane Doe & John Roe eds., 2010', 'on file with author', 'Jacob E. Cooke ed., 1961']:
            with self.subTest(parenthesis=parenthesis):
                self.assertEqual(screen_clause('A, 1 U.S. 2 ('+parenthesis+').')['parenthetical'], '')
        self.assertEqual(screen_clause('A, 1 U.S. 2 (holding that the rule changed in 2000).')['parenthetical'], 'holding that the rule changed in 2000')
        self.assertEqual(screen_clause('A, 1 U.S. 2 (the rule applies to everyone).')['parenthetical'], 'the rule applies to everyone')

    def test_4_titles_and_dockets_are_not_pins(self):
        title = 'Jack Balkin, Brown at 50: The Legacy, 90 Va. L. Rev. 1537 (2004).'
        docket = 'See Smith v. Jones, No. 19-123 (S.D.N.Y. Mar. 3, 2020).'
        self.assertEqual(screen_clause(title)['pincite'], '')
        self.assertEqual(screen_clause(docket)['pincite'], '')
        self.assertEqual(screen_clause(docket)['kind_hint'], 'case')
        for text in ['Id. at 50.', 'Doe, supra note 3, at 50.', 'A, 17 U.S. at 50.', 'A, No. 19-123, slip op. at 50 (2020).']:
            self.assertEqual(screen_clause(text)['pincite'], '50', text)
        self.assertEqual(screen_clause('Doe, Book Vol. 3 (1990).')['pincite'], '')

    def test_5_posture_is_an_anchored_shape(self):
        text = 'A, 1 U.S. 2 (rejecting the dissenting view that the rule is absolute).'
        self.assertEqual(screen_clause(text)['opinion_note'], '')
        self.assertEqual(screen_clause(text)['parenthetical'], 'rejecting the dissenting view that the rule is absolute')
        for note in ['Thomas, J., concurring', 'Roberts, C.J., dissenting', 'Kagan & Sotomayor, JJ., dissenting',
                     'opinion of Roberts, C.J.', 'plurality opinion', 'per curiam']:
            s = screen_clause('A, 1 U.S. 2 ('+note+').')
            self.assertEqual(s['opinion_note'], note)
            self.assertEqual(s['parenthetical'], '')

    def test_6_prose_and_markdown_signals(self):
        for text, expected in [('For a contrary view, cf. A, 1 U.S. 2.', 'cf.'), ('*See* A, 1 U.S. 2.', 'see'),
                               ('_But see_ A, 1 U.S. 2.', 'but see'), ('A, 1 U.S. 2 (see also the dissent).', '')]:
            self.assertEqual(signal_of(text), expected)

    def test_7_rules_and_codes_are_located(self):
        for text, pin in [('See Fed. R. Civ. P. 12(b)(6).', '12(b)(6)'), ('Fed. R. Evid. 403.', '403'),
                          ('Sup. Ct. R. 10(a).', '10(a)'), ('42 U.S.C. 1983.', '1983')]:
            s = screen_clause(text)
            self.assertEqual(s['kind_hint'], 'statute')
            self.assertEqual(s['pincite'], pin)
            self.assertEqual(prose_clauses(text), [])
            u = dict(s, unit_id='U1', source_id='S1', source_type='rule', resolved_source_label=text, footnote_number=1)
            row = build_support_units({'footnotes':[{'number':1, 'text':text}]}, [u])[0]
            self.assertEqual(row['scope'], 'pincited')
            self.assertNotIn('unread_reason', row)

    def test_12_prose_after_citation(self):
        text = 'Scholars disagree. See A, 1 U.S. 2 (2000). For the contrary view, see B, 2 U.S. 3 (2001).'
        self.assertEqual(len(split_clauses(text)), 3)
        self.assertEqual(prose_clauses(text), ['Scholars disagree.', 'For the contrary view,'])
        self.assertEqual(len(split_clauses('A, 1 U.S. 2 (2000) (holding that X. See also Y).')), 1)
        self.assertEqual(len(split_clauses('A, 1 U.S. 2 (2000) “text 12. More text”.')), 1)


class GatesAndContextReviewTests(unittest.TestCase):
    def test_1_category_alone_never_exempts_partial(self):
        a = list(fixtures.support_fixture())
        quoted = a[5][6]
        quoted.update(category='support_overstated', status='partial', severity='low', support_read=True, verification_basis='primary_full_text')
        self.assertFalse(read_overstatement(quoted, {'U1','U2','U3','U4'}))
        self.assertTrue(any('support category requires' in e for e in errors(a)))
        self.assertTrue(read_overstatement(a[5][2], {'U3'}))
        for field in ('support', 'support_read'):
            v = dict(a[5][2]); v.pop(field)
            self.assertFalse(read_overstatement(v, {'U3'}))

    def test_8_body_citation_previous_sentence(self):
        a = list(fixtures.support_fixture())
        citation = a[2][0]['draft_citation_text']
        a[1]['paragraphs'] = ['The rule applies to everyone. '+citation+' Next sentence.']
        a[2][0].update(location='body', paragraph_number=1, footnote_number=None, body_context=a[1]['paragraphs'][0])
        a[5][0]['support'].update(claim='The rule applies to everyone.', claim_basis='anchor.previous')
        rebuild(a)
        self.assertTrue(a[4][0]['body_citation_sentence'])
        self.assertEqual(a[4][0]['anchor']['position'], 'citation-sentence')
        self.assertEqual(errors(a), [])
        # Across paragraphs, and inline use must not acquire that permission.
        a[1]['paragraphs'] = ['The rule applies to everyone.', citation]
        a[2][0].update(paragraph_number=2, body_context=citation)
        rebuild(a); self.assertEqual(errors(a), [])
        a[1]['paragraphs'] = ['Another proposition.', 'The rule applies '+citation+' only sometimes.']
        a[2][0]['body_context'] = a[1]['paragraphs'][1]
        rebuild(a)
        self.assertFalse(a[4][0]['body_citation_sentence'])
        self.assertNotIn('anchor.previous', claim_bases(a[4][0]))
        self.assertTrue(any('claim not verbatim' in e for e in errors(a)))

    def test_9_page_before_first_marker(self):
        for text in ['Intro text *431 First *432 Second *433 Third', 'Intro text <<pg. 431>> First <<pg. 432>> Second']:
            spans, kind = page_spans(text)
            _, _, boundaries = normalize(text, fold=False, spans=spans)
            self.assertEqual(printed_page(boundaries, kind, None, 0), 430)
            self.assertIn('Intro text', read_pages(text, '430'))
            self.assertIn('First', read_pages(text, '430-31'))
        with self.assertRaisesRegex(ValueError, 'unavailable'):
            read_pages('<<pg. 431>>First', '430')

    def test_11_orphan_docx_does_not_enter_v6_inventory(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'d.docx'; ns = W[1:-1]
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', f'<w:document xmlns:w="{ns}"><w:body><w:p><w:r><w:t>Rule.</w:t><w:footnoteReference w:id="1"/></w:r></w:p></w:body></w:document>')
                z.writestr('word/footnotes.xml', f'<w:footnotes xmlns:w="{ns}"><w:footnote w:id="1"><w:p><w:r><w:t>Live.</w:t></w:r></w:p></w:footnote><w:footnote w:id="2"><w:p><w:r><w:t>Orphan, supra note 99.</w:t></w:r></w:p></w:footnote></w:footnotes>')
            run = Path(td)/'run'
            p = subprocess.run([sys.executable,str(HERE/'init_run.py'),str(path),'--run-dir',str(run)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            data = json.loads((run/'extraction.json').read_text())
            self.assertEqual(data['footnote_count'], 1)
            self.assertEqual(len(fixtures.rows(run/'footnote-coverage.jsonl')),1)
            self.assertEqual(data['supra_problem_candidates'], [])
            self.assertTrue(data['unreferenced_footnotes'][0]['unreferenced'])
            self.assertIsNone(data['unreferenced_footnotes'][0]['anchor'])
            self.assertTrue(data['warnings'])
            self.assertEqual(json.loads((run/'run-manifest.json').read_text())['schema_version'],6)

    def test_13_attention_heading_forms_and_boundaries(self):
        for heading in ['## Needs your attention','**Needs your attention**','Needs your attention']:
            report = heading+'\nU3: confirm this.\n### Proposition support\nU4: elsewhere.\n'
            self.assertIn('U3', attention_section(report))
            self.assertNotIn('U4', attention_section(report))
            a = list(fixtures.support_fixture()); a[-1] += '\n'+report
            self.assertTrue(any('overstatement cannot appear' in e for e in errors(a)))
        a = list(fixtures.support_fixture())
        a[-1] = a[-1].replace('## Proposition support', '### Proposition support')+'\nU3: Confirm the scope.\n'
        self.assertEqual(errors(a), [])

    def test_14_unread_reason_must_name_the_same_unit(self):
        a = list(fixtures.support_fixture())
        a[4][0]['unread_reason']='budget'
        a[5][0].pop('support'); a[5][0].update(support_read=False,category='verified_identity')
        a[0]['completion_target']='complete_with_limits'
        a[0]['counts']['support']=support_counts(a[4],a[5],a[6])
        a[-1]='Existence-only: fixture\n'+support_sentence(a[0]['counts']['support'])+'\n## Needs your attention\nNone\n## Proposition support\nU1: not read.\nU10: budget\n'
        self.assertTrue(any('disclose unread support unit U1' in e for e in errors(a)))
        a[-1]+='U1: budget\n'
        self.assertEqual(errors(a), [])

    def test_14_claim_and_confirmed_audit(self):
        a=list(fixtures.support_fixture()); a[5][0]['support']['claim']='rule'
        self.assertTrue(any('complete declared extraction field' in e for e in errors(a)))
        a=list(fixtures.support_fixture()); a[6][0]['initial_support_verdict']='contradicted'
        self.assertTrue(any('confirmed audit must preserve' in e for e in errors(a)))

    def test_14_body_siblings_are_per_paragraph(self):
        a=list(fixtures.support_fixture())
        a[1]['paragraphs']=[a[2][0]['draft_citation_text'],a[2][1]['draft_citation_text']]
        for i in range(2):
            a[2][i].update(location='body',footnote_number=None,paragraph_number=i+1,body_context=a[1]['paragraphs'][i])
        prepared=build_support_units(a[1],a[2],a[3])
        self.assertEqual([r['siblings'] for r in prepared[:2]], [1,1])


class RerunReviewTests(unittest.TestCase):
    def test_10_per_claim_coverage_despite_unrelated_whole_work(self):
        a=fixtures.support_fixture()
        old={'kind':'support','category':'support_overstated','verdict':'overstated','resolved_source_label':a[2][0]['resolved_source_label'],'claim':'The rule applies.','signal':'see','footnote':1}
        before={'items':[old],'coverage_complete':True}
        with tempfile.TemporaryDirectory() as td:
            run=Path(td); fixtures.write(run/'support-units.jsonl',a[4])
            current={'items':[],'coverage_complete':True,'support_pass':{'enabled':True,'scope':'pincited'},'support_coverage':support_coverage(run,a[5])}
            self.assertEqual(len(diff(before,current)['resolved']),1)
            current['support_coverage'][0]['read']=False
            self.assertEqual(len(diff(before,current)['not_rechecked']),1)
            current['support_coverage'][0]['read']=True
            duplicate=dict(current['support_coverage'][0],read=False)
            current['support_coverage'].append(duplicate)
            self.assertEqual(len(diff(before,current)['not_rechecked']),1)
            current['support_coverage'].pop()
            current['coverage_complete']=False
            self.assertEqual(len(diff(before,current)['not_rechecked']),1)
            current['coverage_complete']=True
            current['support_pass']['enabled']=False
            self.assertEqual(len(diff(before,current)['not_rechecked']),1)
            current['support_pass']['enabled']=True
            current['support_coverage'][0]['checked_claim']='A different claim.'
            self.assertEqual(len(diff(before,current)['not_rechecked']),1)


if __name__=='__main__':
    unittest.main()
