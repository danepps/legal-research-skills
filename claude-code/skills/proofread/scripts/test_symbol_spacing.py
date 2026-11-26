"""Space after § and ¶: the shared detector in legal-research/citeform.py, and its way
into proof.json. Synthetic OOXML only; fixtures stay in the system temporary folder."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / 'legal-research'))
import citeform  # noqa: E402

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
NBSP, NARROW = ' ', ' '


def esc(text):
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def run(text):
    return '<w:r><w:t xml:space="preserve">' + esc(text) + '</w:t></w:r>'


def field(display, code=' ADDIN ZOTERO_ITEM CSL_CITATION {"citationID":"x"} '):
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText xml:space="preserve">' + esc(code) + '</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run(display) +
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def para(contents):
    return '<w:p>' + contents + '</w:p>'


def element(xml):
    return ET.fromstring('<w:body ' + NS + '>' + xml + '</w:body>')


def hits(xml):
    return citeform.symbol_space_hits(list(element(xml)))


class DetectorTests(unittest.TestCase):
    def test_ordinary_space_is_flagged_and_nonbreaking_is_not(self):
        got = hits(para(run('See 42 U.S.C. § 1983 and ¶' + NBSP + '12 and §§' + NARROW + '1–2.')))
        self.assertEqual([(h['symbol'], h['nonbreaking']) for h in got],
                         [('§', False), ('¶', True), ('§§', True)])
        self.assertEqual(got[0]['context'], 'See 42 U.S.C. § 1983')

    def test_symbol_and_number_in_different_runs(self):
        got = hits(para(run('under §') + run(' 1983') + run(' and §') + run(NBSP) + run('1985')))
        self.assertEqual([h['nonbreaking'] for h in got], [False, True])

    def test_a_gap_that_mixes_the_two_spaces_can_still_break(self):
        self.assertEqual([h['nonbreaking'] for h in hits(para(run('§' + NBSP + ' 1983')))], [False])

    def test_tab_or_line_break_after_the_symbol_is_not_nonbreaking(self):
        got = hits(para(run('§') + '<w:r><w:tab/></w:r>' + run('1') + run(' ¶') + '<w:r><w:br/></w:r>' + run('2')))
        self.assertEqual([h['nonbreaking'] for h in got], [False, False])

    def test_no_space_and_trailing_symbol_are_not_this_check(self):
        self.assertEqual(hits(para(run('§1983 is cited; so is ¶ '))), [])

    def test_field_results_are_marked(self):
        got = hits(para(run('Compare § 1 with ') + field('Example, § 2 (2020)') + run(' and ¶ 3.')))
        self.assertEqual([h['in_field'] for h in got], [False, True, False])

    def test_simple_fields_and_other_fields_count_as_fields(self):
        xml = para('<w:fldSimple w:instr=" REF x ">' + run('§ 4') + '</w:fldSimple>' + field('¶ 5', ' REF y '))
        self.assertEqual([h['in_field'] for h in hits(xml)], [True, True])

    def test_a_field_left_open_carries_into_the_next_paragraph(self):
        first = para('<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> TOC </w:instrText></w:r>'
                     '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run('I. § 1'))
        second = para(run('II. § 2') + '<w:r><w:fldChar w:fldCharType="end"/></w:r>' + run(' then § 3'))
        state = citeform.symbol_space_state()
        a, b = (citeform.symbol_space_hits([p], state) for p in element(first + second))
        self.assertEqual([h['in_field'] for h in a + b], [True, True, False])

    def test_tracked_deletions_are_not_read(self):
        xml = para('<w:del><w:r><w:delText>§ 9</w:delText></w:r></w:del><w:ins>' + run('§' + NBSP + '9') + '</w:ins>')
        self.assertEqual([h['nonbreaking'] for h in hits(xml)], [True])

    def test_context_stops_at_a_note_call(self):
        xml = para(run('Earlier sentence.') + '<w:r><w:footnoteReference w:id="2"/></w:r>' + run(' Then § 7(a) applies.'))
        self.assertEqual(hits(xml)[0]['context'], 'Then § 7(a)')


class ConventionTests(unittest.TestCase):
    HIT = dict(symbol='§', nonbreaking=False, in_field=False, context='42 U.S.C. § 1983')

    def test_nothing_to_report_when_every_gap_is_nonbreaking(self):
        summary, row = citeform.symbol_space_convention([('', dict(self.HIT, nonbreaking=True))])
        self.assertIsNone(row)
        self.assertEqual((summary['total'], summary['nonbreaking'], summary['ordinary']), (1, 1, 0))

    def test_row_counts_and_separates_fields(self):
        located = [('note 3', self.HIT), ('', dict(self.HIT, nonbreaking=True)),
                   ('note 4', dict(self.HIT, in_field=True, context='Example, § 2'))]
        summary, row = citeform.symbol_space_convention(located)
        self.assertEqual((summary['ordinary'], summary['ordinary_in_fields']), (1, 1))
        self.assertEqual(summary['examples'], [dict(location='note 3', find='42 U.S.C. § 1983')])
        self.assertEqual(row['dominant'], 'ordinary space (2 of 3)')
        self.assertIn('non-breaking space after 1;', row['minority'])
        self.assertIn('1 followed by an ordinary space', row['minority'])
        self.assertIn('1 more inside Zotero citations', row['minority'])
        self.assertIn('note 3 `42 U.S.C. § 1983`', row['minority'])
        self.assertIn('^s', row['recommendation'])
        self.assertIn('unlinked', row['recommendation'])

    def test_fields_only_still_gets_a_row_and_no_examples(self):
        summary, row = citeform.symbol_space_convention([('note 4', dict(self.HIT, in_field=True))])
        self.assertEqual(summary['examples'], [])
        self.assertIn('1 with an ordinary space, inside Zotero citations', row['minority'])

    def test_first_column_names_the_commoner_form(self):
        good = dict(self.HIT, nonbreaking=True)
        _, row = citeform.symbol_space_convention([('', good), ('', good), ('note 9', self.HIT)])
        self.assertEqual(row['dominant'], 'non-breaking space (2 of 3)')
        self.assertTrue(row['minority'].startswith('1 followed by an ordinary space'))

    def test_a_note_s_leading_period_is_not_in_the_excerpt(self):
        self.assertEqual(hits(para(run('. 6 U.S.C. § 345.')))[0]['context'], '6 U.S.C. § 345.')

    def test_the_example_list_is_capped_and_the_counts_are_not(self):
        summary, _ = citeform.symbol_space_convention([('', self.HIT)] * 50)
        self.assertEqual((summary['ordinary'], len(summary['examples'])), (50, 20))

    def test_without_fields_the_recommendation_says_nothing_about_zotero(self):
        _, row = citeform.symbol_space_convention([('', self.HIT)])
        self.assertNotIn('Zotero', row['recommendation'])


class ExtractorTests(unittest.TestCase):
    def extract(self, body, notes='', suffix='.docx'):
        root = Path(tempfile.mkdtemp(prefix='symbol-spacing-tests-'))
        draft, out = root / ('draft' + suffix), root / 'out'
        with zipfile.ZipFile(draft, 'w') as z:
            z.writestr('word/document.xml', '<w:document ' + NS + '><w:body>' + body + '</w:body></w:document>')
            z.writestr('word/footnotes.xml', '<w:footnotes ' + NS + '>' + notes + '</w:footnotes>')
            z.writestr('word/styles.xml', '<w:styles ' + NS + '/>')
        done = subprocess.run([sys.executable, str(HERE / 'extract_proof.py'), str(draft), str(out)],
                              capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.fulltext = (out / 'fulltext.txt').read_text(encoding='utf-8')
        return json.loads(done.stdout), json.loads((out / 'proof.json').read_text(encoding='utf-8'))

    def test_proof_json_carries_the_summary_and_one_convention_row(self):
        body = (para(run('The statute, 42 U.S.C. § 1983, reaches this.') + '<w:r><w:footnoteReference w:id="2"/></w:r>') +
                para(run('Section §' + NBSP + '1985 does not.') + '<w:r><w:footnoteReference w:id="3"/></w:r>'))
        notes = ('<w:footnote w:id="2">' + para(run('See id. ¶ 4.')) + '</w:footnote>'
                 '<w:footnote w:id="3">' + para(field('Example, Title § 2 (2020).')) + '</w:footnote>')
        printed, proof = self.extract(body, notes)
        spacing = proof['formatting']['symbol_spacing']
        self.assertEqual((spacing['total'], spacing['nonbreaking'], spacing['ordinary'], spacing['ordinary_in_fields']),
                         (4, 1, 2, 1))
        self.assertEqual(spacing['examples'], [dict(location='', find='The statute, 42 U.S.C. § 1983,'),
                                                dict(location='note 1', find='See id. ¶ 4.')])
        rows = [c for c in proof['formatting']['conventions'] if c['issue'] == 'space after § and ¶']
        self.assertEqual(len(rows), 1)
        self.assertEqual(printed['symbols_with_ordinary_space'], 2)
        self.assertEqual(printed['symbols_with_ordinary_space_in_fields'], 1)
        # A convention, never a finding per symbol: nothing joins the lint pool.
        self.assertFalse([f for f in proof['lint_findings'] if 'non-breaking' in f['problem']])
        # The plain text every agent reads is unchanged: the gap is still one ordinary space.
        self.assertIn('Section § 1985 does not.', self.fulltext)

    def test_a_clean_draft_gets_no_row(self):
        _, proof = self.extract(para(run('Under §' + NBSP + '1983 and ¶' + NBSP + '2.')))
        self.assertEqual(proof['formatting']['symbol_spacing']['ordinary'], 0)
        self.assertFalse([c for c in proof['formatting']['conventions'] if c['issue'] == 'space after § and ¶'])


if __name__ == '__main__':
    unittest.main()
