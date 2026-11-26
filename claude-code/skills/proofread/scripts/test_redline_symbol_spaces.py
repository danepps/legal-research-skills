"""Synthetic OOXML for the opt-in symbol-space writer; Python 3.9, stdlib only."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from xml.etree import ElementTree as ET

import test_redline_docx as fixtures

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / 'legal-research'))
import citeform

redline = fixtures.redline
W, DATE = fixtures.W, fixtures.DATE
run, paragraph, zotero, citation = fixtures.run, fixtures.paragraph, fixtures.zotero, fixtures.citation
NBSP = '\u00a0'


class SymbolSpaceTests(unittest.TestCase):
    draft = fixtures.RedlineTests.draft
    edit = fixtures.RedlineTests.edit
    xml = fixtures.RedlineTests.xml

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='redline-symbol-tests-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def generate(self, draft, edits=(), **options):
        index = len(list(self.root.glob('result-*')))
        output, result = self.root / ('output-%d.docx' % index), self.root / ('result-%d.json' % index)
        before = draft.read_bytes()
        answer = redline.generate(draft, list(edits), output, result, 'Dubitante test', DATE, **options)
        self.assertEqual(before, draft.read_bytes())
        self.assertEqual(answer, json.loads(result.read_text()))
        return output, answer

    def document(self, path):
        with zipfile.ZipFile(path) as archive:
            return redline.Document({n: archive.read(n) for n in archive.namelist()})

    def assert_views(self, draft, output, expected):
        before, after = self.document(draft), self.document(output)
        old_ids = {n.attrs.get(redline.w('id')) for r in before.roots.values() for n in r.walk()}
        new_ids = {n.attrs.get(redline.w('id')) for r in after.roots.values() for n in r.walk()} - old_ids
        for key, node in before.units.items():
            raw = ''.join(a.char for a in redline.text_view(node, before.numbers))
            changed = after.units[key]
            self.assertEqual(''.join(a.char for a in redline.text_view(changed, after.numbers, new_ids, False)), raw)
            accepted = ''.join(a.char for a in redline.text_view(changed, after.numbers, new_ids, True))
            self.assertEqual(accepted, expected.get(key, raw))

    def ordinary_hits(self, path):
        count = 0
        with zipfile.ZipFile(path) as archive:
            for part in redline.SYMBOL_PARTS:
                if part not in archive.namelist():
                    continue
                root = ET.fromstring(archive.read(part))
                state = citeform.symbol_space_state()
                if part == 'word/document.xml':
                    units = [[p] for p in root.iter('{%s}p' % W)]
                else:
                    units = [list(note.iter('{%s}p' % W)) for note in root]
                for paragraphs in units:
                    count += sum(not h['nonbreaking'] and not h['in_field']
                                 for h in citeform.symbol_space_hits(paragraphs, state))
        return count

    def assert_detector_delta(self, draft, output, answer):
        self.assertEqual(self.ordinary_hits(draft) - self.ordinary_hits(output), answer['symbol_spaces']['applied'])

    def test_body_footnote_endnote_and_no_comments(self):
        body = paragraph(run('§ 1983 and ¶ 2') + '<w:r><w:footnoteReference w:id="2"/><w:endnoteReference w:id="3"/></w:r>')
        notes = '<w:footnote w:id="2">' + paragraph(run('§ 1983')) + '</w:footnote>'
        ends = ('<w:endnotes xmlns:w="%s"><w:endnote w:id="3">%s</w:endnote></w:endnotes>' %
                (W, paragraph(run('§ 1983')))).encode()
        extras = {'word/endnotes.xml': ends}
        for name, tag in (('header1', 'hdr'), ('footer1', 'ftr')):
            extras['word/' + name + '.xml'] = ('<w:%s xmlns:w="%s">%s</w:%s>' % (tag, W, paragraph(run('§ 1983')), tag)).encode()
        draft = self.draft(body, notes, extras)
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=4, in_fields=0, skipped={}))
        self.assertEqual(answer['totals'], dict(applied=0, commented=0, commented_instead=0, unplaced=0, applied_in_zotero_fields=0))
        self.assertEqual(answer['edits'], [])
        original = self.document(draft)
        expected = {k: ''.join(a.char for a in redline.text_view(n, original.numbers)).replace('§ ', '§' + NBSP).replace('¶ ', '¶' + NBSP)
                    for k, n in original.units.items()}
        self.assert_views(draft, output, expected)
        self.assert_detector_delta(draft, output, answer)
        with zipfile.ZipFile(draft) as before, zipfile.ZipFile(output) as after:
            self.assertEqual(before.namelist(), after.namelist())
            self.assertNotIn('word/comments.xml', after.namelist())
            self.assertEqual(before.read('word/header1.xml'), after.read('word/header1.xml'))
            self.assertEqual(before.read('word/footer1.xml'), after.read('word/footer1.xml'))
            for part in redline.SYMBOL_PARTS:
                root = ET.fromstring(after.read(part))
                deleted = list(root.iter('{%s}delText' % W))
                self.assertTrue(deleted)
                self.assertTrue(all(t.text == ' ' for t in deleted))
                self.assertTrue(all(t.text == NBSP for ins in root.iter('{%s}ins' % W) for t in ins.iter('{%s}t' % W)))

    def test_split_runs_text_elements_and_italic_formatting(self):
        body = paragraph(run('§') + run(' 1983', '<w:rPr><w:i/></w:rPr>') +
                         '<w:r><w:t> and §§</w:t><w:t xml:space="preserve"> </w:t><w:t>1–2</w:t></w:r>')
        draft = self.draft(body)
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces']['applied'], 2)
        root = self.xml(output)
        for tag in ('ins', 'del'):
            revision = next(root.iter('{%s}%s' % (W, tag)))
            self.assertIsNotNone(revision.find('.//{%s}i' % W))
        self.assert_views(draft, output, {('word/document.xml', 'p', 0): '§' + NBSP + '1983 and §§' + NBSP + '1–2'})
        self.assert_detector_delta(draft, output, answer)

    def test_nonbreaking_double_mixed_tab_and_break_gaps(self):
        samples = ['§' + c + '1' for c in (NBSP, '\u202f', '\u2007', NBSP + '\u202f', '  ', ' ' + NBSP, '\t', '\n')]
        body = paragraph(run('; '.join(samples)) + run('; §') + '<w:r><w:tab/></w:r>' + run('1; ¶') +
                         '<w:r><w:br/></w:r>' + run('2; §') + '<w:r><w:cr/></w:r>' + run('3; § 4'))
        draft = self.draft(body)
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=0, skipped=dict(already_nonbreaking=4, non_single_space=7)))
        self.assert_detector_delta(draft, output, answer)

    def test_fields_and_instructions_are_byte_identical(self):
        field = zotero(citation('§ 2'), result_runs=run('§ 2', '<w:rPr><w:i/></w:rPr>'))
        simple = '<w:fldSimple w:instr="REF example">' + run('¶ 3') + '</w:fldSimple>'
        instruction = '<w:r><w:instrText xml:space="preserve"> REF § 9 </w:instrText></w:r>'
        draft = self.draft(paragraph(run('§ 1; ') + field + simple + instruction))
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=2, skipped=dict(field_instruction=3)))
        with zipfile.ZipFile(output) as archive:
            for xml in (field, simple, instruction):
                self.assertIn(xml.encode(), archive.read('word/document.xml'))
        self.assert_detector_delta(draft, output, answer)

    def test_complex_fields_across_paragraphs_and_nested_fields(self):
        begin = '<w:r><w:fldChar w:fldCharType="begin"/><w:instrText> TOC </w:instrText><w:fldChar w:fldCharType="separate"/></w:r>'
        end = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        body = paragraph(begin + run('§ 1')) + paragraph(run('¶ 2') +
               '<w:fldSimple w:instr="REF x">' + run('§ 3') + '</w:fldSimple>' + end + run(' § 4'))
        draft = self.draft(body)
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=3, skipped={}))
        old, new = self.document(draft), self.document(output)
        for before, after in zip(redline.field_inventory(old)['word/document.xml'], redline.field_inventory(new)['word/document.xml']):
            self.assertEqual(old.parts['word/document.xml'][before.start:before.end], new.parts['word/document.xml'][after.start:after.end])
        self.assert_detector_delta(draft, output, answer)

    def test_unclosed_field_protects_the_rest_of_the_part(self):
        body = paragraph('<w:r><w:fldChar w:fldCharType="begin"/><w:fldChar w:fldCharType="separate"/></w:r>' + run('§ 1')) + paragraph(run('¶ 2'))
        output, answer = self.generate(self.draft(body), symbol_spaces='fix')
        self.assertFalse(output.exists())
        self.assertEqual(answer['status'], 'no_edits')
        self.assertEqual(answer['symbol_spaces'], dict(applied=0, in_fields=2, skipped={}))

    def test_field_symbol_with_space_outside_and_shared_field_run(self):
        simple = '<w:fldSimple w:instr="REF x">' + run('§') + '</w:fldSimple>'
        shared = '<w:r><w:t>¶ 2</w:t><w:fldChar w:fldCharType="begin"/><w:instrText> DATE </w:instrText><w:fldChar w:fldCharType="separate"/><w:t>today</w:t><w:fldChar w:fldCharType="end"/></w:r>'
        draft = self.draft(paragraph(simple + run(' 1; ') + shared + run('; § 3')))
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=1, skipped=dict(field_run=1)))
        with zipfile.ZipFile(output) as archive:
            self.assertIn(shared.encode(), archive.read('word/document.xml'))
        self.assert_detector_delta(draft, output, answer)

    def test_instruction_sharing_a_run_and_instruction_phase_text(self):
        shared = '<w:r><w:instrText> REF x </w:instrText><w:t>§ 1</w:t></w:r>'
        field = '<w:r><w:fldChar w:fldCharType="begin"/></w:r>' + run('¶ 2') + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        draft = self.draft(paragraph(shared + field + run('; § 3')))
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=1, skipped=dict(field_run=1)))
        with zipfile.ZipFile(output) as archive:
            self.assertIn(shared.encode(), archive.read('word/document.xml'))
            self.assertIn(field.encode(), archive.read('word/document.xml'))

    def test_note_table_and_unreferenced_endnote(self):
        notes = '<w:footnote w:id="2"><w:tbl><w:tr><w:tc>' + paragraph(run('§ 1')) + '</w:tc></w:tr></w:tbl></w:footnote>'
        ends = ('<w:endnotes xmlns:w="%s"><w:endnote w:id="3">%s</w:endnote></w:endnotes>' %
                (W, paragraph(run('¶ 2')))).encode()
        draft = self.draft(paragraph(run('Body')), notes, {'word/endnotes.xml': ends})
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=2, in_fields=0, skipped={}))
        self.assert_detector_delta(draft, output, answer)
        self.assert_views(draft, output, {('word/footnotes.xml', 'p', 0): '§' + NBSP + '1',
            ('word/endnotes.xml', 'p', 0): '¶' + NBSP + '2', ('word/endnotes.xml', 'en', 0): '¶' + NBSP + '2'})

    def test_no_eligible_spaces_reports_counts_without_output(self):
        draft = self.draft(paragraph(run('§\u00a01; ¶  2; §3; ¶ ')))
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertFalse(output.exists())
        self.assertEqual(answer['status'], 'no_edits')
        self.assertEqual(answer['symbol_spaces'], dict(applied=0, in_fields=0,
                         skipped=dict(already_nonbreaking=1, non_single_space=1)))

    def test_findings_win_over_space_and_symbol_context(self):
        for replacement in ('section 1983', '§1983', '§\u00a01983', '§\t1983'):
            with self.subTest(replacement=replacement):
                draft = self.draft(paragraph(run('§ 1983 and ¶ 2')))
                edits = redline.edits_from_findings([dict(location='¶0', find='§ 1983', replacement=replacement,
                    problem='Synthetic change', fix='Use the replacement.', severity='error', category='text')])
                output, answer = self.generate(draft, edits, symbol_spaces='fix')
                self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=0, skipped=dict(other_edit=1)))
                self.assertEqual(answer['totals']['applied'], 1)
                self.assert_views(draft, output, {('word/document.xml', 'p', 0): replacement + ' and ¶' + NBSP + '2'})

    def test_other_edits_and_comments_in_same_run_preserve_strict_offsets(self):
        draft = self.draft(paragraph(run('eror § 1983 remove ¶ 2 tail')))
        edits = [self.edit('eror', 'error'), self.edit('remove', '', ident='two'),
                 self.edit('§ 1983', kind='comment', ident='three')]
        output, answer = self.generate(draft, edits, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces']['applied'], 2)
        self.assert_views(draft, output, {('word/document.xml', 'p', 0): 'error §' + NBSP + '1983  ¶' + NBSP + '2 tail'})
        self.assert_detector_delta(draft, output, answer)

    def test_existing_insertions_deletions_and_moves_are_untouched(self):
        protected = ('<w:ins w:id="10">' + run('§ 1') + '</w:ins>' +
                     '<w:del w:id="11"><w:r><w:delText>¶ 2</w:delText></w:r></w:del>' +
                     '<w:moveFrom w:id="12"><w:r><w:delText>§ 3</w:delText></w:r></w:moveFrom>' +
                     '<w:moveTo w:id="13">' + run('¶ 4') + '</w:moveTo>')
        draft = self.draft(paragraph(protected + run('; § 5')))
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=0, skipped=dict(tracked_revision=4)))
        with zipfile.ZipFile(output) as archive:
            self.assertIn(protected.encode(), archive.read('word/document.xml'))
        self.assert_detector_delta(draft, output, answer)

    def test_move_ranges_across_paragraphs_and_deleted_boundary(self):
        for kind in ('moveFrom', 'moveTo'):
            with self.subTest(kind=kind):
                body = paragraph('<w:%sRangeStart w:id="20"/>' % kind + run('§ 1'))
                body += paragraph(run('¶ 2') + '<w:%sRangeEnd w:id="20"/>' % kind + run('; § 3'))
                body += paragraph(run('§') + '<w:del w:id="21"><w:r><w:delText>x</w:delText></w:r></w:del>' + run(' 4'))
                draft = self.draft(body)
                output, answer = self.generate(draft, symbol_spaces='fix')
                self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=0, skipped=dict(tracked_revision=3)))
                self.assert_detector_delta(draft, output, answer)

    def test_note_marks_and_cross_paragraph_gap(self):
        body = paragraph(run('§ ') + '<w:r><w:footnoteReference w:id="2"/></w:r>' + run('text; § 1'))
        notes = '<w:footnote w:id="2">' + paragraph('<w:r><w:footnoteRef/><w:t>§ 2</w:t></w:r>') + paragraph(run('§')) + paragraph(run('3')) + '</w:footnote>'
        draft = self.draft(body, notes)
        output, answer = self.generate(draft, symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces'], dict(applied=1, in_fields=0, skipped=dict(note_mark=2, non_single_space=1)))
        self.assert_detector_delta(draft, output, answer)

    def test_append_period_and_symbol_fix_share_a_note(self):
        body = paragraph(run('Body') + '<w:r><w:footnoteReference w:id="2"/></w:r>')
        notes = '<w:footnote w:id="2">' + paragraph(run('See § 1983')) + '</w:footnote>'
        draft = self.draft(body, notes)
        edit = dict(id='period', kind='append-period', location='n.1', find='See § 1983', note='Add period')
        output, answer = self.generate(draft, [edit], symbol_spaces='fix')
        self.assertEqual(answer['symbol_spaces']['applied'], 1)
        self.assert_views(draft, output, {('word/footnotes.xml', 'p', 0): 'See §' + NBSP + '1983.', ('word/footnotes.xml', 'fn', 0): 'See §' + NBSP + '1983.'})
        self.assert_detector_delta(draft, output, answer)

    def test_off_is_identical_to_default_and_never_runs_pass(self):
        draft = self.draft(paragraph(run('eror § 1983')))
        edits = [self.edit('eror', 'error')]
        with mock.patch.object(redline.Writer, 'fix_symbol_spaces', side_effect=AssertionError('off ran the pass')):
            default, a = self.generate(draft, edits)
            explicit, b = self.generate(draft, edits, symbol_spaces='off')
            empty, c = self.generate(draft, symbol_spaces='off')
        self.assertEqual(default.read_bytes(), explicit.read_bytes())
        self.assertEqual(a, b)
        self.assertNotIn('symbol_spaces', a)
        self.assertNotIn('symbol_spaces', c)
        self.assertFalse(empty.exists())

    def test_cli_empty_findings_and_option_validation(self):
        draft = self.draft(paragraph(run('§ 1983')))
        findings = self.root / 'findings.json'; findings.write_text('[]')
        output, result = self.root / 'cli.docx', self.root / 'cli.json'
        args = [sys.executable, '-I', '-B', str(fixtures.TOOL), '--draft', str(draft), '--findings', str(findings),
                '--output', str(output), '--result', str(result), '--author', 'Test', '--date', DATE, '--symbol-spaces']
        completed = subprocess.run(args + ['fix'], capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(result.read_text())['symbol_spaces']['applied'], 1)
        self.assertEqual(subprocess.run(args + ['invalid'], capture_output=True).returncode, 2)
        with self.assertRaisesRegex(ValueError, 'symbol_spaces'):
            self.generate(draft, symbol_spaces='invalid')
        # The autonomous pass also runs without an edits/findings file at all.
        standalone = [sys.executable, '-I', '-B', str(fixtures.TOOL), '--draft', str(draft),
            '--output', str(self.root / 'standalone.docx'), '--result', str(self.root / 'standalone.json'),
            '--author', 'Test', '--date', DATE, '--symbol-spaces', 'fix']
        completed = subprocess.run(standalone, capture_output=True, text=True)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads((self.root / 'standalone.json').read_text())['symbol_spaces']['applied'], 1)

    def test_strict_verifier_rejects_space_narrow_space_and_extra_change(self):
        for wrong in (' ', '\u202f', '\u2007', '\u00a0\u00a0'):
            with self.subTest(wrong=repr(wrong)):
                def corrupt(parts):
                    parts['word/document.xml'] = parts['word/document.xml'].replace(NBSP.encode(), wrong.encode())
                    return parts
                draft = self.draft(paragraph(run('§ 1983')))
                index = len(list(self.root.glob('result-*')))
                with self.assertRaisesRegex(ValueError, 'strict symbol-space'):
                    self.generate(draft, symbol_spaces='fix', fault_hook=corrupt)
                self.assertFalse((self.root / ('output-%d.docx' % index)).exists())
                self.assertEqual(json.loads((self.root / ('result-%d.json' % index)).read_text())['status'], 'failed')

    def test_strict_ledger_does_not_trust_the_replacement_map(self):
        original = redline.Writer.edited_parts
        def corrupt_plan(writer):
            for node, changes in writer.replacements.items():
                writer.replacements[node] = [(a, b, ' ' if r == NBSP else r) for a, b, r in changes]
            return original(writer)
        with mock.patch.object(redline.Writer, 'edited_parts', corrupt_plan):
            with self.assertRaisesRegex(ValueError, 'strict symbol-space'):
                self.generate(self.draft(paragraph(run('§ 1983'))), symbol_spaces='fix')
        self.assertFalse((self.root / 'output-0.docx').exists())

    def test_rejected_view_catches_wrong_deleted_space(self):
        def corrupt(parts):
            parts['word/document.xml'] = parts['word/document.xml'].replace(b'> </dubitante:delText>', b'>\xc2\xa0</dubitante:delText>')
            return parts
        with self.assertRaisesRegex(ValueError, 'rejected view'):
            self.generate(self.draft(paragraph(run('§ 1983'))), symbol_spaces='fix', fault_hook=corrupt)
        self.assertFalse((self.root / 'output-0.docx').exists())

    def test_unedited_field_formatting_fault_fails_byte_check(self):
        field = '<w:fldSimple w:instr="REF example">' + run('§ 2', '<w:rPr><w:i/></w:rPr>') + '</w:fldSimple>'
        def corrupt(parts):
            parts['word/document.xml'] = parts['word/document.xml'].replace(b'<w:i/>', b'<w:b/>')
            return parts
        with self.assertRaisesRegex(ValueError, 'unedited field bytes'):
            self.generate(self.draft(paragraph(run('§ 1') + field)), symbol_spaces='fix', fault_hook=corrupt)
        self.assertFalse((self.root / 'output-0.docx').exists())


if __name__ == '__main__':
    unittest.main()
