"""Synthetic OOXML only. Fixtures are kept in the system temporary folder, never deleted."""
import importlib.util
import errno
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest import mock
import zipfile
from xml.etree import ElementTree as ET

TOOL = Path(__file__).with_name('redline_docx.py')
spec = importlib.util.spec_from_file_location('redline_docx', TOOL)
redline = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = redline
spec.loader.exec_module(redline)
W = redline.W
DATE = '2026-11-23T12:00:00Z'


def run(text, props=''):
    return '<w:r>' + props + '<w:t xml:space="preserve">' + redline.escape(text) + '</w:t></w:r>'


def paragraph(contents):
    return '<w:p>' + contents + '</w:p>'


class RedlineTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='redline-tests-'))

    def draft(self, body, notes=None, extras=None):
        data = {
            '[Content_Types].xml': ('<Types xmlns="%s"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>' % redline.CT).encode(),
            '_rels/.rels': ('<Relationships xmlns="%s"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>' % redline.REL).encode(),
            'word/document.xml': ('<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="%s" xmlns:custom="urn:keep" custom:keep="yes"><w:body><!-- keep this comment -->%s<w:sectPr/></w:body></w:document>' % (W, body)).encode(),
            'word/styles.xml': ('<w:styles xmlns:w="%s"><w:style w:styleId="Untouched"/></w:styles>' % W).encode(),
            'word/media/untouched.bin': b'synthetic binary part\x00\xff',
        }
        if notes is not None:
            data['word/footnotes.xml'] = ('<w:footnotes xmlns:w="%s">%s</w:footnotes>' % (W, notes)).encode()
        data.update(extras or {})
        path = self.root / ('draft-%d.docx' % len(list(self.root.glob('draft-*'))))
        with zipfile.ZipFile(path, 'x') as z:
            for name, content in data.items():
                z.writestr(name, content)
        return path

    def edit(self, find, replacement='', location='¶0', kind='change', ident='one'):
        return dict(id=ident, location=location, find=find, kind=kind, replacement=replacement, note='Problem. Proposed fix.')

    def generate(self, draft, edits, fault=None):
        number = len(list(self.root.glob('result-*')))
        output = self.root / ('output-%d.docx' % number)
        result = self.root / ('result-%d.json' % number)
        before = draft.read_bytes()
        answer = redline.generate(draft, edits, output, result, 'Dubitante test', DATE, fault)
        self.assertEqual(draft.read_bytes(), before)
        self.assertEqual(json.loads(result.read_text()), answer)
        if output.exists():
            with zipfile.ZipFile(draft) as original, zipfile.ZipFile(output) as changed:
                for name in original.namelist():
                    if name not in ('word/document.xml', 'word/footnotes.xml', 'word/comments.xml', 'word/_rels/document.xml.rels', '[Content_Types].xml'):
                        self.assertEqual(original.read(name), changed.read(name))
                self.assertIn(b'<!-- keep this comment -->', changed.read('word/document.xml'))
        return output, answer

    def xml(self, output, name='word/document.xml'):
        with zipfile.ZipFile(output) as z:
            return ET.fromstring(z.read(name))

    def test_single_run_trims_unchanged_context_and_is_deterministic(self):
        draft = self.draft(paragraph(run('The teh rule.')))
        output, answer = self.generate(draft, [self.edit('The teh rule.', 'The the rule.')])
        self.assertEqual(answer['totals']['applied'], 1)
        root = self.xml(output)
        self.assertEqual(''.join(n.text or '' for n in root.iter('{%s}delText' % W)), 'eh')
        self.assertEqual(''.join(n.text or '' for ins in root.iter('{%s}ins' % W) for n in ins.iter('{%s}t' % W)), 'he')
        other, _ = self.generate(draft, [self.edit('The teh rule.', 'The the rule.')])
        self.assertEqual(output.read_bytes(), other.read_bytes())

    def test_three_runs_keep_formatting(self):
        draft = self.draft(paragraph(run('abc', '<w:rPr><w:b/></w:rPr>') + run('def', '<w:rPr><w:i/></w:rPr>') + run('ghi', '<w:rPr><w:smallCaps/></w:rPr>')))
        output, answer = self.generate(draft, [self.edit('abcdefghi', 'ABCDEFGHI')])
        self.assertEqual(answer['edits'][0]['status'], 'applied')
        for tag in ('ins', 'del'):
            runs = [r for revision in self.xml(output).iter('{%s}%s' % (W, tag)) for r in revision.findall('{%s}r' % W)]
            self.assertEqual([list(r.find('{%s}rPr' % W))[0].tag for r in runs], ['{%s}%s' % (W, t) for t in ('b', 'i', 'smallCaps')])

    def test_footnote_number_is_reference_order_not_xml_id(self):
        draft = self.draft(paragraph(run('Body') + '<w:r><w:footnoteReference w:id="9"/></w:r>'),
                           '<w:footnote w:id="9">' + paragraph('<w:r><w:footnoteRef/></w:r>' + run('Footnote eror.')) + '</w:footnote>')
        output, answer = self.generate(draft, [self.edit('eror', 'error', 'n.1')])
        self.assertEqual(answer['totals']['applied'], 1)
        self.assertTrue(list(self.xml(output, 'word/footnotes.xml').iter('{%s}ins' % W)))

    def test_footnote_comments_hang_on_the_reference_mark_in_the_text(self):
        # Word drops comments placed inside a footnote, so none may be written there.
        body = paragraph(run('Body one') + '<w:r><w:footnoteReference w:id="9"/></w:r>' + run(' and two') + '<w:r><w:footnoteReference w:id="4"/></w:r>')
        notes = ('<w:footnote w:id="9">' + paragraph('<w:r><w:footnoteRef/></w:r>' + run('First eror and a choice.')) + '</w:footnote>'
                 '<w:footnote w:id="4">' + paragraph('<w:r><w:footnoteRef/></w:r>' + run('Second note is fine.')) + '</w:footnote>'
                 '<w:footnote w:id="5">' + paragraph('<w:r><w:footnoteRef/></w:r>' + run('Orphan eror note.')) + '</w:footnote>')
        draft = self.draft(body, notes)
        edits = [self.edit('eror', 'error', 'n.1'), self.edit('choice', location='n.1', kind='comment', ident='two'),
                 self.edit('fine', location='n.2', kind='comment', ident='three'),
                 self.edit('Orphan eror', 'Orphan error', location='nowhere', ident='four'),
                 self.edit('Orphan', location='nowhere', kind='comment', ident='five')]
        output, answer = self.generate(draft, edits)
        self.assertEqual([e['status'] for e in answer['edits']], ['applied', 'commented', 'commented', 'applied', 'unplaced'])
        self.assertIn('no reference mark', answer['edits'][4]['reason'])
        with zipfile.ZipFile(output) as z:
            footnotes, document = z.read('word/footnotes.xml'), z.read('word/document.xml')
        self.assertNotIn(b'comment', footnotes)
        self.assertEqual(footnotes.count(b':ins '), 2)
        self.assertEqual(len(list(ET.fromstring(document).iter('{%s}commentRangeStart' % W))), 2)
        comments = self.xml(output, 'word/comments.xml').findall('{%s}comment' % W)
        text = sorted(''.join(t.text for t in c.iter('{%s}t' % W)) for c in comments)
        self.assertEqual(len(comments), 2)
        self.assertTrue(text[0].startswith('Footnote 1, at \u201ceror\u201d') and 'Footnote 1, at \u201cchoice\u201d' in text[0])
        self.assertTrue(text[1].startswith('Footnote 2, at \u201cfine\u201d'))

    def test_custom_footnote_mark_stays_in_one_run_when_it_carries_a_comment(self):
        # An author note marked "*": the mark text sits in the same run as the reference,
        # and splitting that run would turn the mark into body text.
        body = paragraph(run('Title') + '<w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr><w:footnoteReference w:customMarkFollows="1" w:id="2"/><w:t>*</w:t></w:r>')
        notes = '<w:footnote w:id="2">' + paragraph('<w:r><w:t>*</w:t></w:r>' + run(' Professor of eror.')) + '</w:footnote>'
        draft = self.draft(body, notes)
        output, answer = self.generate(draft, [self.edit('eror', 'error', 'nowhere')])
        self.assertEqual(answer['edits'][0]['status'], 'applied')
        with zipfile.ZipFile(draft) as before, zipfile.ZipFile(output) as after:
            original_run = before.read('word/document.xml').split(b'<w:r><w:rPr><w:vertAlign')[1].split(b'</w:r>')[0]
            self.assertIn(original_run, after.read('word/document.xml'))
        self.assertEqual(len(self.xml(output, 'word/comments.xml').findall('{%s}comment' % W)), 1)

    def test_zotero_field_is_only_commented(self):
        field = '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText> ADDIN ZOTERO_ITEM synthetic </w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run('123 U.S. 456') + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        draft = self.draft(paragraph(field))
        output, answer = self.generate(draft, [self.edit('123 U.S. 456', '124 U.S. 456')])
        self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
        self.assertIn('Zotero', answer['edits'][0]['reason'])
        self.assertFalse(list(self.xml(output).iter('{%s}del' % W)))
        with zipfile.ZipFile(output) as z:
            self.assertIn(b'123 U.S. 456', z.read('word/document.xml'))
            self.assertIn(b'Proposed replacement: 124 U.S. 456', z.read('word/comments.xml'))

    def test_duplicate_find_is_resolved_by_zero_based_nonempty_location(self):
        draft = self.draft(paragraph('') + paragraph(run('same')) + paragraph(run('same')))
        _, answer = self.generate(draft, [self.edit('same', 'different', '¶1')])
        self.assertEqual(answer['totals']['applied'], 1)

    def test_ambiguous_absent_and_valid_global_fallback(self):
        draft = self.draft(paragraph(run('same')) + paragraph(run('same unique')))
        edits = [self.edit('same', 'x', '¶99'), self.edit('missing', 'x', ident='two'), self.edit('unique', 'special', 'bad-location', ident='three')]
        _, answer = self.generate(draft, edits)
        self.assertEqual([e['status'] for e in answer['edits']], ['unplaced', 'unplaced', 'applied'])

    def test_existing_comments_and_ids_preserved(self):
        comments = ('<w:comments xmlns:w="%s"><w:comment w:id="42" w:author="Original"><w:p><w:r><w:t>Keep me</w:t></w:r></w:p></w:comment></w:comments>' % W).encode()
        rels = ('<Relationships xmlns="%s"><Relationship Id="rOld" Type="%s" Target="comments.xml"/></Relationships>' % (redline.REL, redline.COMMENTS_REL)).encode()
        draft = self.draft(paragraph('<w:commentRangeStart w:id="42"/>' + run('old') + '<w:commentRangeEnd w:id="42"/><w:r><w:commentReference w:id="42"/></w:r>'), extras={'word/comments.xml': comments, 'word/_rels/document.xml.rels': rels})
        output, answer = self.generate(draft, [self.edit('old', 'new')])
        root = self.xml(output, 'word/comments.xml')
        ids = [n.get('{%s}id' % W) for n in root]
        self.assertEqual(len(set(ids)), 2); self.assertIn('42', ids)
        with zipfile.ZipFile(output) as z:
            self.assertEqual(z.read('word/_rels/document.xml.rels'), rels)
            self.assertIn(b'<w:comment w:id="42" w:author="Original">', z.read('word/comments.xml'))

    def test_existing_revisions_are_kept_and_deletion_crossing_is_commented(self):
        body = paragraph('<w:ins w:id="88" w:author="Old">' + run('eror') + '</w:ins>' + run(' left') + '<w:del w:id="89"><w:r><w:delText>deleted</w:delText></w:r></w:del>' + run(' right'))
        draft = self.draft(body)
        output, answer = self.generate(draft, [self.edit('eror', 'error'), self.edit('left right', 'both', ident='two')])
        self.assertEqual([e['status'] for e in answer['edits']], ['applied', 'commented_instead'])
        root = self.xml(output)
        self.assertTrue(any(n.get('{%s}id' % W) == '88' for n in root.iter('{%s}ins' % W)))
        self.assertTrue(any(n.get('{%s}id' % W) == '89' for n in root.iter('{%s}del' % W)))

    def test_special_unicode_and_comments_only(self):
        draft = self.draft(paragraph(run('“A & B < C” 😀 wrong.')))
        output, answer = self.generate(draft, [self.edit('😀 wrong', '🧑🏽 correct'), self.edit('A & B < C', location='¶0', kind='comment', ident='two')])
        self.assertEqual(answer['totals']['applied'], 1)
        self.assertEqual(answer['totals']['commented'], 1)
        self.assertTrue(output.exists())

    def test_insertion_and_deletion_only_changes(self):
        draft = self.draft(paragraph(run('word word eror')))
        _, answer = self.generate(draft, [self.edit('word word', 'word'), self.edit('eror', 'error', ident='two')])
        self.assertEqual(answer['totals']['applied'], 2)

    def test_simple_field_and_footnote_mark_are_comments(self):
        draft = self.draft(paragraph('<w:fldSimple w:instr="DATE">' + run('today') + '</w:fldSimple>' + run(' body') + '<w:r><w:footnoteReference w:id="4"/></w:r>'), '<w:footnote w:id="4">' + paragraph(run('note')) + '</w:footnote>')
        _, answer = self.generate(draft, [self.edit('today', 'tomorrow'), self.edit('body[FN#1]', 'body', ident='two')])
        self.assertEqual(answer['totals']['commented_instead'], 2)

    def test_whitespace_cleaning_and_custom_marks_match_extractor(self):
        draft = self.draft(paragraph(run('   One  eror\t here  ') + '<w:r><w:footnoteReference w:id="8" w:customMarkFollows="1"/><w:t>*</w:t></w:r>'), '<w:footnote w:id="8">' + paragraph(run('A')) + paragraph(run('B')) + '</w:footnote>')
        with zipfile.ZipFile(draft) as z:
            doc = redline.Document({n: z.read(n) for n in z.namelist()})
        self.assertEqual(redline.cleaned(redline.text_view(doc.locations['¶0'][1], doc.numbers))[0], 'One eror here [FN#?]')
        self.assertEqual(redline.cleaned(redline.text_view(doc.locations['n.1'][1], doc.numbers))[0], 'A B')
        _, answer = self.generate(draft, [self.edit('One eror here', 'One error here')])
        self.assertEqual(answer['totals']['applied'], 1)

    def test_lint_excerpt_with_ellipses_is_anchored_as_a_comment_only(self):
        draft = self.draft(paragraph(run('The argument concerns the the relationship between them.')))
        edits = [self.edit('\u2026concerns the the relationship\u2026', kind='comment'),
                 self.edit('\u2026The argument\u2026', 'An argument', ident='two'),
                 self.edit('\u2026', kind='comment', ident='three')]
        output, answer = self.generate(draft, edits)
        self.assertEqual([e['status'] for e in answer['edits']], ['commented', 'commented_instead', 'unplaced'])
        self.assertIn('excerpt', answer['edits'][1]['reason'])
        body = self.xml(output)
        self.assertEqual(len(body.findall('.//{%s}ins' % W)) + len(body.findall('.//{%s}del' % W)), 0)
        self.assertEqual(len(self.xml(output, 'word/comments.xml').findall('{%s}comment' % W)), 2)

    def test_findings_on_one_span_share_a_comment_and_a_change_wins_the_span(self):
        draft = self.draft(paragraph(run('The premise set out in supra note 9 is narrow.')))
        edits = [self.edit('set out in supra note 9', kind='comment'),
                 self.edit('supra note 9', 'supra note 1', ident='two'),
                 self.edit('premise set out', kind='comment', ident='three'),
                 self.edit('note 9 is', 'note 2 is', ident='four')]
        output, answer = self.generate(draft, edits)
        self.assertEqual([e['status'] for e in answer['edits']], ['commented', 'applied', 'commented', 'commented_instead'])
        self.assertEqual(answer['totals'], dict(applied=1, commented=2, commented_instead=1, unplaced=0))
        body = self.xml(output)
        self.assertEqual(''.join(t.text for t in body.findall('.//{%s}ins//{%s}t' % (W, W))), '1')
        comments = self.xml(output, 'word/comments.xml').findall('{%s}comment' % W)
        text = [''.join(t.text for t in c.iter('{%s}t' % W)) for c in comments]
        # The change holds the span; the overlapping comment and the second change join its
        # comment. The third comment overlaps nothing that was claimed before it.
        self.assertEqual(len(comments), 2)
        self.assertTrue(any('Also at this place' in x and 'Proposed replacement: note 2 is' in x for x in text))
        self.assertTrue(all(len(c.findall('{%s}p' % W)) >= 1 for c in comments))

    def test_verifier_rejects_wrong_application_before_final_output(self):
        draft = self.draft(paragraph(run('bad text')))
        output, result = self.root / 'failed.docx', self.root / 'failed.json'
        def corrupt(parts):
            before = parts['word/document.xml']
            parts['word/document.xml'] = before.replace(b'>goo<', b'>evil<')
            self.assertNotEqual(parts['word/document.xml'], before)
            return parts
        with self.assertRaisesRegex(ValueError, 'Verification failed'):
            redline.generate(draft, [self.edit('bad', 'good')], output, result, 'Test', DATE, corrupt)
        self.assertFalse(output.exists())
        self.assertEqual(json.loads(result.read_text())['status'], 'failed')

    def test_existing_output_is_never_replaced(self):
        draft = self.draft(paragraph(run('bad')))
        output = self.root / 'existing.docx'; output.write_bytes(b'keep')
        with self.assertRaises(FileExistsError):
            redline.generate(draft, [self.edit('bad', 'good')], output, self.root / 'result.json', 'Test', DATE)
        self.assertEqual(output.read_bytes(), b'keep')

    def test_no_edits_has_no_output(self):
        draft = self.draft(paragraph(run('unchanged')))
        output, answer = self.generate(draft, [])
        self.assertEqual(answer['status'], 'no_edits'); self.assertFalse(output.exists())

    def test_findings_policy_and_malformed_values(self):
        base = dict(location='¶0', find='eror', problem='Typo', fix='Use error.', severity='error', category='spelling', replacement='error')
        cases = [base, dict(base, severity='likely'), dict(base, severity='style'), dict(base, severity='query'),
                 dict(base, replacement=''), dict(base, replacement='eror'), {k: v for k, v in base.items() if k != 'replacement'}]
        edits = redline.edits_from_findings(cases)
        self.assertEqual([e['kind'] for e in edits], ['change'] + ['comment'] * 6)
        self.assertEqual([e['id'] for e in edits], [str(i) for i in range(1, 8)])
        self.assertEqual(edits[0]['note'], 'Typo\nUse error.')
        # An object is read as a workflow output file (see WorkflowOutputInput below).
        for malformed in (None, 'text', dict(findings={}), [dict(base, replacement=None)], [dict(base, severity='unknown')], [dict(base, find='')], [dict(base, category=4)]):
            with self.subTest(malformed=malformed), self.assertRaisesRegex(ValueError, 'Malformed findings'):
                redline.edits_from_findings(malformed)

    def test_findings_cli_and_exclusive_modes_with_staging_directory(self):
        draft = self.draft(paragraph(run('eror')))
        findings = self.root / 'findings.json'
        findings.write_text(json.dumps([dict(location='¶0', find='eror', problem='Typo', fix='Use error.', severity='error', category='spelling', replacement='error')]))
        stage = self.root / 'hidden'; stage.mkdir()
        output = self.root / 'redline.docx'; result = self.root / 'tool-result.json'
        args = [sys.executable, '-I', '-B', str(TOOL), '--draft', str(draft), '--output', str(output), '--result', str(result), '--author', 'Test', '--date', DATE]
        completed = subprocess.run(args + ['--findings', str(findings), '--staging-dir', str(stage)], capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(result.read_text())['totals']['applied'], 1)
        self.assertEqual(len(list(stage.glob('*.staging'))), 1)
        self.assertFalse(list(self.root.glob('*.staging')))
        self.assertEqual(subprocess.run(args, capture_output=True, timeout=10).returncode, 2)
        self.assertEqual(subprocess.run(args + ['--edits', str(findings), '--findings', str(findings)], capture_output=True, timeout=10).returncode, 2)

    def test_cross_volume_link_failure_keeps_output_absent(self):
        draft = self.draft(paragraph(run('bad')))
        output = self.root / 'redline.docx'; result = self.root / 'result.json'
        with mock.patch.object(redline.os, 'link', side_effect=OSError(errno.EXDEV, 'cross-device')):
            with self.assertRaisesRegex(ValueError, 'same volume'):
                redline.generate(draft, [self.edit('bad', 'good')], output, result, 'Test', DATE, staging_dir=self.root)
        self.assertFalse(output.exists())
        self.assertIn('same volume', json.loads(result.read_text())['reason'])

    def test_verification_parses_xml_parts_with_non_xml_extensions(self):
        types = ('<Types xmlns="%s"><Override PartName="/custom/data.custom" ContentType="application/xml"/></Types>' % redline.CT).encode()
        draft = self.draft(paragraph(run('bad')), extras={'[Content_Types].xml': types, 'custom/data.custom': b'<keep/>', 'word/drawing.vml': b'<drawing/>'})
        for index, part in enumerate(('custom/data.custom', 'word/drawing.vml')):
            def corrupt(parts):
                parts[part] = b'<not-closed>'
                return parts
            output = self.root / ('invalid-%d.docx' % index)
            with self.assertRaises(redline.expat.ExpatError):
                redline.generate(draft, [self.edit('bad', 'good')], output, self.root / ('invalid-%d.json' % index), 'Test', DATE, corrupt)
            self.assertFalse(output.exists())


class WorkflowOutputInput(unittest.TestCase):
    """--findings accepts the proofread workflow's whole output file."""

    FINDING = dict(location='¶0', find='eror', problem='p', fix='f', severity='error', category='typo', replacement='error')

    def test_output_file_and_bare_array_give_the_same_edits(self):
        bare = redline.edits_from_findings([self.FINDING])
        self.assertEqual(redline.edits_from_findings(dict(result=dict(report='# r', findings=[self.FINDING]))), bare)
        self.assertEqual(redline.edits_from_findings(dict(findings=[self.FINDING])), bare)
        self.assertEqual(bare[0]['kind'], 'change')

    def test_output_file_without_findings_is_a_clear_failure(self):
        with self.assertRaisesRegex(ValueError, 'No findings in the workflow output'):
            redline.edits_from_findings(dict(result=dict(report='# r')))


if __name__ == '__main__':
    unittest.main()
