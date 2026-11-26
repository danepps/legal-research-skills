"""Offline raw-OOXML spacing, extraction and reporting regressions (Python 3.9)."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET

HERE = Path(__file__).resolve().parent
import symbol_spacing as citeform

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


EXTRACTOR = 'extract_draft.py'
SLOT = 'formatting'

class AdditionalDetectorTests(unittest.TestCase):
    def test_all_three_nonbreaking_characters_and_mixed_gaps(self):
        got = hits(para(run('§\u00a0\u202f\u20071 ¶\u20072 §\u202f\t3')))
        self.assertEqual([h['nonbreaking'] for h in got], [True, True, False])

    def test_deleted_and_moved_runs_and_field_markers_are_skipped(self):
        xml = para('<w:del>' + field('§ 1') + '</w:del><w:moveFrom>' +
                   field('¶ 2') + '</w:moveFrom><w:moveTo>' + run('§ 3') + '</w:moveTo>')
        self.assertEqual([(h['symbol'], h['in_field']) for h in hits(xml)], [('§', False)])

    def test_nested_fields_and_instruction_text(self):
        xml = para('<w:fldSimple w:instr="§ 99">' + field('§ 1', ' REF § 88 ') +
                   run(' ¶ 2') + '</w:fldSimple>' + run(' § 3'))
        self.assertEqual([h['in_field'] for h in hits(xml)], [True, True, False])

    def test_split_symbol_gap_field_boundary(self):
        xml = para(run('§') + field(' ') + run('12'))
        self.assertTrue(hits(xml)[0]['in_field'])

    def test_carriage_return_and_paragraph_gap_break(self):
        xml = para(run('§') + '<w:r><w:cr/></w:r>' + run('1 ¶')) + para(run('2'))
        self.assertEqual([h['nonbreaking'] for h in hits(xml)], [False, False])

    def test_empty_and_capped_report(self):
        summary, row = citeform.symbol_space_convention([])
        self.assertEqual(summary['total'], 0)
        self.assertIsNone(row)
        hit = dict(symbol='§', nonbreaking=False, in_field=False, context='§ 1')
        _, row = citeform.symbol_space_convention([('note %d' % i, hit) for i in range(1, 8)])
        self.assertIn('note 3', row['minority'])
        self.assertNotIn('note 4', row['minority'])


class ExtractorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='codex-symbol-spacing-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def call(self, script, *args):
        result = subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                                cwd=self.root, capture_output=True, text=True)
        return result

    def docx(self, body, notes='', extra=None):
        draft = self.root / 'draft.docx'
        with zipfile.ZipFile(draft, 'w') as archive:
            archive.writestr('word/document.xml', '<w:document ' + NS + '><w:body>' + body + '</w:body></w:document>')
            archive.writestr('word/footnotes.xml', '<w:footnotes ' + NS + '>' + notes + '</w:footnotes>')
            archive.writestr('word/styles.xml', '<w:styles ' + NS + '/>')
            for name, text in (extra or {}).items():
                archive.writestr(name, text)
        return draft

    def extract(self, draft):
        output = self.root / 'extracted.json'
        result = self.call(EXTRACTOR, draft, '--output', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(output.read_text())

    def test_counts_field_state_labels_and_unchanged_text(self):
        body = (para(run('See 42 U.S.C. § 1983 and ¶' + NBSP + '12.') +
                     '<w:r><w:footnoteReference w:id="22"/></w:r>') +
                '<w:del>' + para(run('§ 99')) + '</w:del>' +
                '<w:moveFrom>' + para(run('§ 98')) + '</w:moveFrom>' +
                para('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                     '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run('Entry § 1')) +
                para(run('Entry ¶ 2') + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'))
        notes = '<w:footnote w:id="22">' + para(run('See ¶ 3 and §§' + NBSP + '4–5.')) + '</w:footnote>'
        data = self.extract(self.docx(body, notes))
        form = data[SLOT]
        s = form['symbol_spacing']
        self.assertEqual(tuple(s[k] for k in ('total', 'nonbreaking', 'ordinary', 'ordinary_in_fields')), (6, 2, 2, 2))
        self.assertEqual([e['location'] for e in s['examples']], ['', 'note 1'])
        self.assertEqual(len(form['conventions']), 1)
        note = form['conventions'][0]['report_markdown']
        for text in ('not a Bluebook rule', 'Total symbol runs: 6', 'non-breaking: 2',
                     'ordinary outside fields: 2', 'ordinary inside fields: 2', '^s', 'unlinked'):
            self.assertIn(text, note)
        self.assertEqual(citeform.validate_symbol_spacing(form, note), [])
        self.assertTrue(citeform.validate_symbol_spacing(form, note + note))
        self.assertTrue(citeform.validate_symbol_spacing(form, 'omitted'))
        text = data['blocks'][0]['text'] if SLOT == 'formatting' else data['paragraphs'][0]
        self.assertIn('See 42 U.S.C. § 1983 and ¶ 12.', text)
        self.assertNotIn(NBSP, text)
        s['total'] += 1
        self.assertTrue(citeform.validate_symbol_spacing(form))

    def test_all_good_and_no_symbols_keep_counts_without_note(self):
        for text, total in (('Under §' + NBSP + '1983 and ¶\u20072.', 2), ('No symbols here.', 0)):
            with self.subTest(text=text):
                form = self.extract(self.docx(para(run(text))))[SLOT]
                self.assertEqual(form['symbol_spacing']['total'], total)
                self.assertEqual(form['symbol_spacing']['nonbreaking'], total)
                self.assertEqual(form['conventions'], [])
                self.assertEqual(citeform.symbol_spacing_report(form), '')
                self.assertEqual(citeform.validate_symbol_spacing(form, ''), [])

    def test_non_docx_is_skipped_with_a_limitation(self):
        for extension in ('.md', '.txt'):
            draft = self.root / ('draft' + extension)
            draft.write_text('Under § 1 and ¶' + NBSP + '2.')
            data = self.extract(draft)
            form = data[SLOT]
            self.assertEqual(form['symbol_spacing']['status'], 'not_applicable')
            self.assertEqual(form['conventions'], [])
            self.assertNotIn('total', form['symbol_spacing'])
            self.assertIn(citeform.TEXT_LIMITATION, data['limitations'])

    def test_note_field_state_carries_between_paragraphs_and_parts_reset(self):
        begin = '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        body = para(begin + run('§ 1') + '<w:r><w:footnoteReference w:id="2"/></w:r>')
        notes = '<w:footnote w:id="2">' + para(run('§ 2 ') + begin) + para(run('§ 3') + end) + '</w:footnote>'
        form = self.extract(self.docx(body, notes))[SLOT]
        self.assertEqual((form['symbol_spacing']['ordinary'], form['symbol_spacing']['ordinary_in_fields']), (1, 2))

    def test_note_labels_use_displayed_start_and_custom_mark(self):
        body = para(run('Text.') + '<w:r><w:footnoteReference w:id="44" custom="x"/></w:r>' +
                    '<w:r><w:footnoteReference w:id="55" w:customMarkFollows="1"/><w:t>*</w:t></w:r>')
        notes = ''.join('<w:footnote w:id="%s">%s</w:footnote>' % (i, para(run('Under § 1.'))) for i in ('44', '55'))
        settings = '<w:settings ' + NS + '><w:footnotePr><w:numStart w:val="12"/></w:footnotePr></w:settings>'
        form = self.extract(self.docx(body, notes, {'word/settings.xml': settings}))[SLOT]
        self.assertEqual([e['location'] for e in form['symbol_spacing']['examples']], ['note 12', 'note *'])

    def test_endnotes_have_reader_labels_and_separate_part_state(self):
        body = para(run('Text.') + '<w:r><w:endnoteReference w:id="9"/></w:r>')
        endnotes = '<w:endnotes ' + NS + '><w:endnote w:id="9">' + para(field('Under § 1.')) + '</w:endnote></w:endnotes>'
        form = self.extract(self.docx(body, extra={'word/endnotes.xml': endnotes}))[SLOT]
        self.assertEqual(form['symbol_spacing']['ordinary_in_fields'], 1)
        self.assertIn('endnote i', form['conventions'][0]['minority'])

    def test_report_and_readiness_bypass_finding_and_audit_pools(self):
        draft = self.docx(para(run('The rule in § 1 applies here.')))
        directory = self.root / 'run'
        result = self.call('init_run.py', draft, '--run-dir', directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        def read(name):
            return json.loads((directory / name).read_text())
        def rows(name):
            return [json.loads(line) for line in (directory / name).read_text().splitlines() if line.strip()]
        def write(name, data):
            (directory / name).write_text(json.dumps(data))
        def call(script):
            result = self.call(script, directory)
            self.assertEqual(result.returncode, 0, result.stderr)
        manifest = read('run-manifest.json')
        for chunk in rows('chunks.jsonl'):
            result = dict(chunk_id=chunk['chunk_id'], source_sha256=manifest['draft_sha256'], status='complete',
                          reviewed_block_ids=chunk['core_block_ids'], reviewed_note_ids=chunk['owned_note_ids'], findings=[])
            write('agent-results/' + chunk['chunk_id'] + '.json', result)
            write('agent-results/' + chunk['chunk_id'] + '-audit.json', result)
        for lane in manifest['required_lanes']:
            write('lane-results/' + lane + '.json', dict(lane=lane, source_sha256=manifest['draft_sha256'], status='complete', findings=[]))
        call('merge_findings.py')
        call('make_recall_packets.py')
        for packet in rows('recall-packets.jsonl'):
            write('recall-results/' + packet['packet_id'] + '.json', dict(packet_id=packet['packet_id'],
                  source_sha256=manifest['draft_sha256'], status='complete', findings=[],
                  reviewed_block_ids=packet['reviewed_block_ids'], reviewed_note_ids=packet['reviewed_note_ids']))
        call('merge_findings.py')
        call('build_report.py')
        for name in ('static-findings.jsonl', 'findings.jsonl', 'dispositions.jsonl', 'verifier-audit.jsonl', 'rejection-audit.jsonl'):
            self.assertEqual(rows(name), [], name)
        for path in list((directory / 'packets').glob('*.md')) + list((directory / 'lane-packets').glob('*.md')):
            self.assertNotIn('report_markdown', path.read_text())
        note = read('document.json')['formatting']['conventions'][0]['report_markdown']
        report = (directory / 'report.md').read_text()
        self.assertEqual(report.count(note), 1)
        result = self.call('validate_run.py', directory, '--require-ready')
        self.assertEqual(result.returncode, 0, result.stderr)
        for changed in (report.replace(note, ''), report + note):
            (directory / 'report.md').write_text(changed)
            result = self.call('validate_run.py', directory, '--require-ready')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('symbol_spacing', result.stderr)


if __name__ == '__main__':
    unittest.main()
