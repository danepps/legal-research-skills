"""Synthetic OOXML only. Fixtures are kept in the system temporary folder, never deleted."""
import ast
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


def citation(display, items=None, formatted=None):
    """Invented data; the real-draft samples are never test fixtures."""
    return dict(citationID='synthetic', properties=dict(plainCitation=display,
                formattedCitation=display if formatted is None else formatted, noteIndex=7),
                citationItems=items if items is not None else [dict(id=1, itemData=dict(
                    title='A Synthetic Title', author=[dict(family='Example')], note='Leçon — café 😀'))])


def zotero(value, display=None, code=None, splits=(), entities=False, result_runs=None):
    if code is None:
        code = ' ADDIN ZOTERO_ITEM CSL_CITATION ' + json.dumps(value, ensure_ascii=False, separators=(',', ':')) + ' '
    if display is None:
        display = value['properties']['plainCitation']
    chunks = [code[a:b] for a, b in zip((0,) + tuple(splits), tuple(splits) + (len(code),))]
    def xml(text):
        escaped = redline.escape(text)
        return escaped.replace('"', '&quot;').replace("'", '&#x27;') if entities else escaped
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>' +
            ''.join('<w:r><w:instrText xml:space="preserve">' + xml(s) + '</w:instrText></w:r>' for s in chunks) +
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' +
            (run(display) if result_runs is None else result_runs) +
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


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

    def generate(self, draft, edits, fault=None, **options):
        number = len(list(self.root.glob('result-*')))
        output = self.root / ('output-%d.docx' % number)
        result = self.root / ('result-%d.json' % number)
        before = draft.read_bytes()
        answer = redline.generate(draft, edits, output, result, 'Dubitante test', DATE, fault, **options)
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
        # A real JSON object is now required by the output verifier. The volume
        # still comes from the item/style and the original assertions still hold.
        field = zotero(citation('123 U.S. 456'))
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
        self.assertEqual(answer['totals'], dict(applied=1, commented=2, commented_instead=1, unplaced=0, applied_in_zotero_fields=0))
        body = self.xml(output)
        self.assertEqual(''.join(t.text for t in body.findall('.//{%s}ins//{%s}t' % (W, W))), '1')
        comments = self.xml(output, 'word/comments.xml').findall('{%s}comment' % W)
        text = [''.join(t.text for t in c.iter('{%s}t' % W)) for c in comments]
        # The change holds the span; the overlapping comment and the second change join its
        # comment. The third comment overlaps nothing that was claimed before it.
        self.assertEqual(len(comments), 2)
        self.assertTrue(any('Also at this place' in x and 'Proposed replacement: note 2 is' in x for x in text))
        self.assertTrue(all(len(c.findall('{%s}p' % W)) >= 1 for c in comments))

    def test_find_padded_with_spaces_is_exact_when_the_replacement_keeps_the_padding(self):
        draft = self.draft(paragraph(run('See the eror here and the othr one.')))
        edits = [self.edit(' eror ', ' error '), self.edit(' othr ', 'other', ident='two')]
        output, answer = self.generate(draft, edits)
        self.assertEqual([e['status'] for e in answer['edits']], ['applied', 'commented_instead'])
        self.assertEqual(''.join(t.text for t in self.xml(output).findall('.//{%s}ins//{%s}t' % (W, W))), 'r')

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

    def field_code(self, output, part='word/document.xml'):
        return ''.join(n.text or '' for n in self.xml(output, part).iter('{%s}instrText' % W))

    def field_json(self, output, part='word/document.xml'):
        code = self.field_code(output, part)
        return json.loads(code[code.index('{'):])

    def assert_field_edit(self, output, answer, original, component, expected, item=0, part='word/document.xml'):
        self.assertEqual(answer['edits'][0], dict(id='one', status='applied', field='zotero'))
        self.assertEqual(answer['totals']['applied_in_zotero_fields'], 1)
        self.assertEqual(sum(answer['totals'][k] for k in ('applied', 'commented', 'commented_instead', 'unplaced')), len(answer['edits']))
        changed = self.field_json(output, part)
        self.assertEqual(changed['citationItems'][item][component], expected)
        for index, entry in enumerate(original['citationItems']):
            self.assertEqual(changed['citationItems'][index].get('itemData'), entry.get('itemData'))
        self.assertTrue(list(self.xml(output, part).iter('{%s}ins' % W)))
        comments = self.xml(output, 'word/comments.xml')
        paragraphs = [''.join(t.text or '' for t in p.iter('{%s}t' % W)) for p in comments.iter('{%s}p' % W)]
        self.assertIn(redline.ZOTERO_NOTICE, paragraphs)
        self.assertTrue(any('Problem. Proposed fix.' in p for p in paragraphs))
        # No field code is placed in a revision wrapper.
        for revision in list(self.xml(output, part).iter('{%s}ins' % W)) + list(self.xml(output, part).iter('{%s}del' % W)):
            self.assertFalse(list(revision.iter('{%s}instrText' % W)))

    def test_zotero_suffix_and_two_items(self):
        for items in ([dict(suffix='(discussing teh rule)', itemData=dict(title='Keep me'))],
                      [dict(itemData=dict(title='First')), dict(suffix='(discussing teh rule)', itemData=dict(title='Second'))]):
            with self.subTest(items=len(items)):
                shown = 'Alpha, First; Beta, Second (discussing teh rule)'
                value = citation(shown, items, r'{\scaps Alpha}, First; {\i{}Beta}, Second (discussing teh rule)')
                draft = self.draft(paragraph(zotero(value)))
                output, answer = self.generate(draft, [self.edit(shown, shown.replace('teh', 'the'))])
                self.assert_field_edit(output, answer, value, 'suffix', '(discussing the rule)', len(items)-1)
                self.assertEqual(self.field_json(output)['properties']['plainCitation'], shown.replace('teh', 'the'))

    def test_zotero_prefix_signal(self):
        value = citation('Seee Author, Title', [dict(prefix='Seee ', itemData=dict(title='Title'))], r'{\i{}Seee }Author, Title')
        output, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit('Seee Author', 'See Author')])
        # This correction is a deletion, so inspect the deleted run separately.
        self.assertEqual(answer['edits'][0].get('field'), 'zotero')
        self.assertEqual(self.field_json(output)['citationItems'][0]['prefix'], 'See ')
        self.assertEqual(self.field_json(output)['properties']['formattedCitation'], r'{\i{}See }Author, Title')
        self.assertTrue(list(self.xml(output).iter('{%s}del' % W)))

    def test_zotero_locator_whole_token_and_boundary_insertion(self):
        for replacement in ('47', '461'):
            value = citation('Author, 145 Reporter 46', [dict(locator='46', label='page')], r'{\scaps Author}, 145 Reporter 46')
            output, answer = self.generate(self.draft(paragraph(zotero(value) + run(' outside'))),
                                           [self.edit('Reporter 46', 'Reporter ' + replacement)])
            self.assert_field_edit(output, answer, value, 'locator', replacement)

    def test_zotero_locator_substring_is_not_a_whole_token(self):
        for shown in ('Author 146', 'Author 146 Reporter 46'):
            value = citation(shown, [dict(locator='46')])
            _, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit(shown, shown[:-1] + '7')])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            # In the first case nothing matches as a whole token. In the second,
            # the plain view is unambiguous but the formatted string has two
            # literal occurrences, so its stricter check declines the edit.
            self.assertIn('whole-token' if shown == 'Author 146' else 'formattedCitation', answer['edits'][0]['reason'])

    def test_zotero_library_author_title_and_style_are_comments(self):
        value = citation('Author, Title, 5 Reporter 46 (2000)', [dict(locator='46', itemData=dict(title='Title', author=[dict(family='Author')]))])
        for find, replacement in (('Author', 'Writer'), ('Title', 'Book'), ('5 Reporter', '6 Reporter'), ('(2000)', '(2001)'), ('Title,', 'Title;')):
            output, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit(find, replacement)])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            self.assertIn(redline.LIBRARY_REASON, answer['edits'][0]['reason'])
            self.assertEqual(self.field_json(output), value)

    def test_zotero_duplicate_locator_and_multiple_components_are_comments(self):
        cases = [('46 Reporter 46', [dict(locator='46')], 'Reporter 46', 'Reporter 47'),
                 ('Author 46', [dict(locator='46'), dict(locator='46')], '46', '47'),
                 ('Author (teh)', [dict(suffix='(teh)'), dict(suffix='(teh)')], 'teh', 'the')]
        for shown, items, find, replacement in cases:
            value = citation(shown, items)
            output, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit(find, replacement)])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            self.assertIn('exactly one', answer['edits'][0]['reason'])
            self.assertEqual(self.field_json(output), value)

    def test_zotero_markup_transformed_quotes_and_rtf_escapes_are_comments(self):
        cases = [('<i>teh</i>', 'teh', 'the', 'markup'),
                 ('{teh}', 'teh', 'the', 'markup'),
                 ('(“teh”)', 'teh', 'the', 'ASCII'),
                 ('(teh)', 'teh', 'the', 'RTF')]
        for suffix, find, replacement, reason in cases:
            shown = 'Author ' + suffix
            formatted = shown.replace('teh', r't\uc0\u101{}h') if reason == 'RTF' else shown
            value = citation(shown, [dict(suffix=suffix)], formatted)
            output, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit(find, replacement)])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            self.assertIn(reason, answer['edits'][0]['reason'])
            self.assertEqual(self.field_json(output), value)
        # CSL renders stored HTML and quotes differently; do not infer a mapping.
        for stored, shown in (('<i>teh</i>', 'teh'), ('("teh")', '(“teh”)')):
            value = citation('Author ' + shown, [dict(suffix=stored)])
            _, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit('teh', 'the')])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')

    def test_zotero_rtf_control_digits_are_not_locator_text(self):
        value = citation('Author 46', [dict(locator='46')], r'Author \u46{}')
        _, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit('46', '47')])
        self.assertIn('RTF control', answer['edits'][0]['reason'])

    def test_zotero_split_instructions_and_unicode_bytes_are_preserved(self):
        value = citation('Author (teh rule) — café 😀', [dict(suffix='(teh rule)', itemData=dict(title='Leçon — café 😀', note='unchanged'))])
        code = ' ADDIN ZOTERO_ITEM CSL_CITATION ' + json.dumps(value, ensure_ascii=False, indent=2) + ' '
        for split in (code.index('ZOTERO') + 3, code.index('teh') + 2, code.rindex('teh') + 2):
            draft = self.draft(paragraph(zotero(value, code=code, splits=(split,))))
            output, answer = self.generate(draft, [self.edit('teh', 'the')])
            self.assert_field_edit(output, answer, value, 'suffix', '(the rule)')
            self.assertEqual(self.field_code(output).encode(), code.replace('teh', 'the').encode())
            self.assertEqual(len(list(self.xml(output).iter('{%s}instrText' % W))), 2)

    def test_zotero_json_and_xml_escaping_preserve_original_spellings(self):
        value = citation('Author (a & b "teh" / rule)', [dict(suffix='(a & b "teh" / rule)', itemData=dict(title='Café 😀'))])
        code = ' ADDIN ZOTERO_ITEM CSL_CITATION ' + json.dumps(value, ensure_ascii=True, indent=1).replace('/', r'\/').replace('teh', r't\u0065h')
        draft = self.draft(paragraph(zotero(value, code=code, entities=True)))
        output, answer = self.generate(draft, [self.edit('teh', 'the & "right" /')])
        self.assert_field_edit(output, answer, value, 'suffix', '(a & b "the & "right" /" / rule)')
        with zipfile.ZipFile(output) as z:
            data = z.read('word/document.xml')
        self.assertIn(b'Caf\\u00e9 \\ud83d\\ude00', data)
        self.assertIn(b'&amp; \\&quot;right\\&quot; \\/', data)
        # The untouched slash escape, indentation and XML quote entities survive.
        self.assertIn(b'\\/ rule)&quot;', data)

    def test_zotero_split_json_escapes_and_styled_result_runs(self):
        value = citation('Café 😀 (teh)', [dict(suffix='(teh)')])
        code = ' ADDIN ZOTERO_ITEM CSL_CITATION ' + json.dumps(value, ensure_ascii=True).replace('teh', r't\u0065h')
        splits = [m + 3 for m in redline.occurrences(code, r'\u0065')] + [code.index(r'\ud83d') + 8]
        result_runs = run('Café 😀 (t') + run('e', '<w:rPr><w:i/></w:rPr>') + run('h)', '<w:rPr><w:b/></w:rPr>')
        for split in splits:
            draft = self.draft(paragraph(zotero(value, code=code, splits=(split,), result_runs=result_runs, entities=True)))
            output, answer = self.generate(draft, [self.edit('teh', 'the')])
            self.assert_field_edit(output, answer, value, 'suffix', '(the)')
            self.assertEqual(self.field_code(output), code.replace(r't\u0065h', 'the'))
            insertions = list(self.xml(output).iter('{%s}ins' % W))
            self.assertEqual([next(n.iter('{%s}t' % W)).text for n in insertions], ['h', 'e'])
            self.assertIsNotNone(insertions[0].find('.//{%s}i' % W))
            self.assertIsNotNone(insertions[1].find('.//{%s}b' % W))

    def test_zotero_later_safety_check_cancels_the_stored_patch(self):
        value = citation('Author (teh)', [dict(suffix='(teh)')])
        result_runs = run('Author (te') + '<w:del w:id="91"><w:r><w:delText>old</w:delText></w:r></w:del>' + run('h)')
        draft = self.draft(paragraph(zotero(value, result_runs=result_runs)))
        output, answer = self.generate(draft, [self.edit('teh', 'the')])
        self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
        self.assertIn('existing tracked deletion', answer['edits'][0]['reason'])
        self.assertEqual(self.field_code(output), self.field_code(draft))
        self.assertEqual(answer['totals']['applied_in_zotero_fields'], 0)

    def test_zotero_cdata_instruction_is_conservatively_commented(self):
        value = citation('Author (teh)', [dict(suffix='(teh)')])
        field = zotero(value).replace('<w:instrText xml:space="preserve">', '<w:instrText xml:space="preserve"><![CDATA[').replace('</w:instrText>', ']]></w:instrText>')
        draft = self.draft(paragraph(field))
        output, answer = self.generate(draft, [self.edit('teh', 'the')])
        self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
        self.assertIn('XML markup', answer['edits'][0]['reason'])
        self.assertEqual(self.field_code(output), self.field_code(draft))

    def test_zotero_dont_update_plain_mismatch_and_unsafe_replacement(self):
        for case in ('frozen', 'plain', 'new_unicode', 'new_markup', 'formatted_duplicate'):
            value = citation('Author (teh)', [dict(suffix='(teh)')])
            replacement = 'the'
            if case == 'frozen':
                value['properties']['dontUpdate'] = True
            elif case == 'plain':
                value['properties']['plainCitation'] = 'Other (teh)'
            elif case == 'new_unicode':
                replacement = 'thé'
            elif case == 'new_markup':
                replacement = '{the}'
            else:
                value['properties']['formattedCitation'] += ' (teh)'
            output, answer = self.generate(self.draft(paragraph(zotero(value, display='Author (teh)'))), [self.edit('teh', replacement)])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            self.assertEqual(self.field_json(output), value)

    def test_zotero_multiple_nonoverlapping_edits_in_one_field(self):
        value = citation('Seee Author (teh rule) at 46', [dict(prefix='Seee ', suffix='(teh rule)', locator='46')])
        edits = [self.edit('Seee', 'See'), self.edit('teh', 'the', ident='two'), self.edit('46', '47', ident='three')]
        output, answer = self.generate(self.draft(paragraph(zotero(value))), edits)
        self.assertEqual(answer['totals']['applied'], 3)
        self.assertEqual(answer['totals']['applied_in_zotero_fields'], 3)
        self.assertEqual(self.field_json(output)['properties']['plainCitation'], 'See Author (the rule) at 47')

    def test_zotero_adjacent_edits_in_the_same_component(self):
        value = citation('Author (abcd)', [dict(suffix='(abcd)')])
        output, answer = self.generate(self.draft(paragraph(zotero(value))), [self.edit('ab', 'AB'), self.edit('cd', 'CD', ident='two')])
        self.assertEqual(answer['totals']['applied_in_zotero_fields'], 2)
        changed = self.field_json(output)
        self.assertEqual(changed['citationItems'][0]['suffix'], '(ABCD)')
        self.assertEqual(changed['properties']['plainCitation'], 'Author (ABCD)')

    def test_zotero_comment_option_preserves_legacy_reason_and_code(self):
        value = citation('Author (teh)', [dict(suffix='(teh)')])
        draft = self.draft(paragraph(zotero(value)))
        output, answer = self.generate(draft, [self.edit('teh', 'the')], zotero_fields='comment')
        self.assertEqual(answer['edits'][0], dict(id='one', status='commented_instead', reason='The citation is generated by Zotero and must be changed there.'))
        self.assertEqual(self.field_code(output), self.field_code(draft))
        self.assertFalse(list(self.xml(output).iter('{%s}ins' % W)))
        edits = self.root / 'cli-edits.json'
        with edits.open('x') as f:
            json.dump([self.edit('teh', 'the')], f)
        result, cli_output = self.root / 'cli-result.json', self.root / 'cli-output.docx'
        args = [sys.executable, '-I', '-B', str(TOOL), '--draft', str(draft), '--edits', str(edits),
                '--output', str(cli_output), '--result', str(result), '--author', 'Test', '--date', DATE, '--zotero-fields', 'comment']
        completed = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(result.read_text())['edits'], answer['edits'])
        self.assertEqual(self.field_code(cli_output), self.field_code(draft))

    def test_zotero_unedited_field_bytes_unchanged(self):
        value = citation('Author (teh)', [dict(suffix='(teh)')])
        untouched = zotero(citation('Unedited — café'), entities=True, splits=(20,))
        draft = self.draft(paragraph(zotero(value) + run('; ') + untouched))
        output, answer = self.generate(draft, [self.edit('teh', 'the')])
        self.assertEqual(answer['totals']['applied'], 1)
        with zipfile.ZipFile(output) as z:
            self.assertIn(untouched.encode(), z.read('word/document.xml'))

    def test_zotero_field_footnote_comment_is_on_body_reference(self):
        value = citation('Author (teh)', [dict(suffix='(teh)')])
        body = paragraph(run('Body') + '<w:r><w:footnoteReference w:id="9"/></w:r>')
        notes = '<w:footnote w:id="9">' + paragraph('<w:r><w:footnoteRef/></w:r>' + zotero(value)) + '</w:footnote>'
        output, answer = self.generate(self.draft(body, notes), [self.edit('teh', 'the', 'n.1')])
        self.assert_field_edit(output, answer, value, 'suffix', '(the)', part='word/footnotes.xml')
        with zipfile.ZipFile(output) as z:
            self.assertNotIn(b'comment', z.read('word/footnotes.xml'))
        p = self.xml(output).find('.//{%s}p' % W)
        tags = [n.tag for n in p]
        anchor = tags.index('{%s}commentRangeStart' % W)
        self.assertIsNotNone(p[anchor+1].find('{%s}footnoteReference' % W))
        self.assertEqual(tags[anchor+2], '{%s}commentRangeEnd' % W)

    def test_zotero_orphan_footnote_cannot_omit_the_stored_data_warning(self):
        value = citation('Orphan (teh)', [dict(suffix='(teh)')])
        notes = '<w:footnote w:id="9">' + paragraph(zotero(value)) + '</w:footnote>'
        draft = self.draft(paragraph(run('Body')), notes)
        output, answer = self.generate(draft, [self.edit('teh', 'the', 'nowhere')])
        self.assertEqual(answer['edits'][0]['status'], 'unplaced')
        self.assertIn('no reference mark', answer['edits'][0]['reason'])
        self.assertEqual(self.field_code(output, 'word/footnotes.xml'), self.field_code(draft, 'word/footnotes.xml'))

    def test_zotero_verifier_rejects_wrong_patch_and_unedited_bytes(self):
        value = citation('Author (teh)', [dict(suffix='(teh)', itemData=dict(title='Original'))])
        mutations = [(b'"suffix":"(the)"', b'"suffix":"(bad)"'),
                     (b'"title":"Original"', b'"title":"Corrupted"'),
                     (b'"noteIndex":7', b'"noteIndex":true'),
                     (b'"citationID":"synthetic"', b'"citationID" : "synthetic"'),
                     (b'"suffix":"(the)"', b'"suffix":BROKEN')]
        for i, (old, new) in enumerate(mutations):
            draft = self.draft(paragraph(zotero(value)))
            def corrupt(parts):
                self.assertIn(old, parts['word/document.xml'])
                parts['word/document.xml'] = parts['word/document.xml'].replace(old, new)
                return parts
            output, result = self.root / ('bad-%d.docx' % i), self.root / ('bad-%d.json' % i)
            with self.assertRaisesRegex(ValueError, 'Verification failed:.*Zotero'):
                redline.generate(draft, [self.edit('teh', 'the')], output, result, 'Test', DATE, corrupt)
            self.assertFalse(output.exists())
            self.assertEqual(json.loads(result.read_text())['status'], 'failed')
        draft = self.draft(paragraph(run('bad ') + zotero(value)))
        def corrupt_untouched(parts):
            parts['word/document.xml'] = parts['word/document.xml'].replace(b'"noteIndex":7', b'"noteIndex": 7')
            return parts
        with self.assertRaisesRegex(ValueError, 'unedited Zotero instruction bytes'):
            self.generate(draft, [self.edit('bad', 'good')], corrupt_untouched)

    def test_zotero_invalid_json_is_commented_and_the_redline_is_still_made(self):
        for code in (' ADDIN ZOTERO_ITEM CSL_CITATION {broken}',
                     ' ADDIN ZOTERO_ITEM CSL_CITATION {"x":1,"x":2}'):
            draft = self.draft(paragraph(zotero({}, display='bad', code=code)))
            with zipfile.ZipFile(draft) as z:
                doc = redline.Document({n: z.read(n) for n in z.namelist()})
            decision = redline.Writer(doc, 'Test', DATE).place(self.edit('bad', 'good'))
            self.assertEqual(decision['status'], 'commented_instead')
            self.assertIn('JSON', decision['reason'])
            # A damaged field is left exactly as it was; it does not cost the author the redline.
            output, answer = self.generate(draft, [self.edit('bad', 'good')])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            with zipfile.ZipFile(draft) as before, zipfile.ZipFile(output) as after:
                self.assertIn(redline.escape(code).encode(), after.read('word/document.xml'))
            self.assertFalse(list(self.xml(output).iter('{%s}ins' % W)))

    def test_zotero_bibliography_crossing_and_simple_fields_are_comments(self):
        value = citation('Author (teh)', [dict(suffix='(teh)')])
        bibliography = zotero({}, display='Bibliography teh', code=' ADDIN ZOTERO_BIBL {"uncited":[],"omitted":[],"custom":[]} CSL_BIBLIOGRAPHY ')
        simple_code = redline.escape(' ADDIN ZOTERO_ITEM CSL_CITATION ' + json.dumps(value), {'"': '&quot;'})
        cases = [(bibliography, 'teh', 'the', 'bibliography'),
                 (run('before ') + zotero(value), 'before Author (teh)', 'before Author (the)', 'wholly inside'),
                 (zotero(value) + zotero(citation('Other')), '(teh)Other', '(the)Other', 'exactly one'),
                 (zotero(value).replace('<w:r><w:fldChar w:fldCharType="end"/></w:r>', ''), 'teh', 'the', 'complete'),
                 (zotero(value, result_runs='<w:fldSimple w:instr="DATE">' + run('Author (teh)') + '</w:fldSimple>'), 'teh', 'the', 'exactly one'),
                 ('<w:fldSimple w:instr="' + simple_code + '">' + run('Author (teh)') + '</w:fldSimple>', 'teh', 'the', 'complete')]
        for field, find, replacement, reason in cases:
            _, answer = self.generate(self.draft(paragraph(field)), [self.edit(find, replacement)])
            self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
            self.assertIn(reason, answer['edits'][0]['reason'])

    def period_edit(self, find='…Synthetic citation', **changes):
        finding = dict(location='n.1', find=find, problem='Missing terminal punctuation',
                       fix='add the final period', severity='likely', category='cite-terminal-punct')
        finding.update(changes)
        edit = redline.edits_from_findings([finding])[0]
        self.assertEqual(edit['kind'], 'append-period')
        return edit

    def period_draft(self, contents, tail=''):
        return self.draft(paragraph(run('Body') + '<w:r><w:footnoteReference w:id="9"/></w:r>'),
                          '<w:footnote w:id="9">' + paragraph('<w:r><w:footnoteRef/></w:r>' + contents) + tail + '</w:footnote>')

    def document(self, path):
        with zipfile.ZipFile(path) as z:
            return redline.Document({n: z.read(n) for n in z.namelist()})

    def assert_period_views(self, draft, output, expected):
        before, after = self.document(draft), self.document(output)
        old_ids = {n.attrs.get(redline.w('id')) for n in before.notes.walk() if n.tag == redline.w('ins')}
        inserted = [n for n in after.notes.walk() if n.tag == redline.w('ins') and n.attrs.get(redline.w('id')) not in old_ids]
        self.assertEqual(len(inserted), 1)
        ins = inserted[0]
        self.assertEqual(''.join(n.text for n in ins.walk() if n.tag == redline.w('t')), '.')
        self.assertFalse(any(n.tag == redline.w('rPr') for n in ins.walk()))
        self.assertEqual(ins.attrs[redline.w('author')], 'Dubitante test')
        self.assertEqual(ins.attrs[redline.w('date')], DATE)
        new_ids = {ins.attrs[redline.w('id')]}
        original = ''.join(a.char for a in redline.text_view(before.locations['n.1'][1], before.numbers))
        for accept, wanted in ((False, original), (True, expected)):
            actual = ''.join(a.char for a in redline.text_view(after.locations['n.1'][1], after.numbers, new_ids, accept))
            self.assertEqual(actual, wanted)
        for field in redline.field_inventory(after)['word/footnotes.xml']:
            self.assertFalse(field.start < ins.start < field.end)
        with zipfile.ZipFile(output) as z:
            self.assertNotIn(b'comment', z.read('word/footnotes.xml'))

    def assert_period_applied(self, contents, text, find='…Synthetic citation', **options):
        draft = self.period_draft(contents)
        output, answer = self.generate(draft, [self.period_edit(find)], **options)
        self.assertEqual(answer['edits'][0], dict(id='1', status='applied', kind='append-period'))
        self.assertEqual(answer['totals']['applied'], 1)
        self.assertEqual(answer['totals']['applied_in_zotero_fields'], 0)
        self.assert_period_views(draft, output, text)
        return draft, output

    def assert_period_comment(self, contents, find='…Synthetic citation', reason=None, tail=''):
        draft = self.period_draft(contents, tail)
        output, answer = self.generate(draft, [self.period_edit(find)])
        self.assertEqual(answer['edits'][0]['status'], 'commented_instead')
        self.assertEqual(answer['totals']['applied'], 0)
        if reason:
            self.assertIn(reason, answer['edits'][0]['reason'])
        with zipfile.ZipFile(draft) as before, zipfile.ZipFile(output) as after:
            self.assertEqual(before.read('word/footnotes.xml'), after.read('word/footnotes.xml'))
        self.assertEqual(len(self.xml(output, 'word/comments.xml').findall('{%s}comment' % W)), 1)

    def test_period_zotero_terminal_field_is_byte_identical(self):
        field = zotero(citation('Synthetic citation'), entities=True, splits=(20,))
        for mode in ('edit', 'comment'):
            with self.subTest(mode=mode):
                _, output = self.assert_period_applied(field, 'Synthetic citation.', zotero_fields=mode)
                with zipfile.ZipFile(output) as z:
                    self.assertIn(field.encode(), z.read('word/footnotes.xml'))

    def test_period_plain_text(self):
        self.assert_period_applied(run('Synthetic citation'), 'Synthetic citation.')

    def test_period_after_closing_quote_and_parenthesis(self):
        text = 'Synthetic citation (“quoted words”)'
        self.assert_period_applied(run(text), text + '.', '…' + text)

    def test_period_does_not_inherit_italic_or_other_run_formatting(self):
        for props in ('<w:i/>', '<w:smallCaps/><w:b/>', '<w:rStyle w:val="Emphasis"/>'):
            with self.subTest(props=props):
                styled = run('Synthetic citation', '<w:rPr>' + props + '</w:rPr>')
                _, output = self.assert_period_applied(styled, 'Synthetic citation.')
                with zipfile.ZipFile(output) as z:
                    self.assertIn(styled.encode(), z.read('word/footnotes.xml'))

    def test_period_trailing_whitespace_stays_after_period(self):
        cases = [run('Synthetic citation  \t'), run('Synthetic citation') + run('  \t'),
                 run('Synthetic citation') + '<w:r><w:tab/><w:br/></w:r>',
                 zotero(citation('Synthetic citation')) + run('  \t')]
        for contents, suffix in zip(cases, ('  \t', '  \t', '  ', '  \t')):
            with self.subTest(contents=contents):
                self.assert_period_applied(contents, 'Synthetic citation.' + suffix)

    def test_period_non_zotero_complex_and_simple_fields(self):
        fields = [zotero({}, display='Synthetic citation', code=' REF synthetic '),
                  '<w:fldSimple w:instr="REF synthetic">' + run('Synthetic citation') + '</w:fldSimple>']
        for field in fields:
            with self.subTest(field=field):
                _, output = self.assert_period_applied(field, 'Synthetic citation.')
                with zipfile.ZipFile(output) as z:
                    self.assertIn(field.encode(), z.read('word/footnotes.xml'))

    def test_period_existing_terminal_punctuation_is_commented(self):
        for suffix in ('.', '?', '!', '.”', '?"', "!’", ". ' ”"):
            text = 'Synthetic citation' + suffix
            with self.subTest(suffix=suffix):
                self.assert_period_comment(run(text), '…' + text, 'terminal punctuation')

    def test_period_parenthesis_follows_the_actual_lint(self):
        # Execute the actual standalone lint function, without importing the
        # extractor's installed-skill search paths or duplicating its rule.
        tree = ast.parse(TOOL.with_name('extract_proof.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'terminal_punct_finding')
        namespace = {}
        exec(compile(ast.Module(body=[function], type_ignores=[]), 'extract_proof.py', 'exec'), namespace)
        for suffix in ('.)', '.”)', '?)', '!")'):
            text = 'Synthetic citation' + suffix
            with self.subTest(suffix=suffix):
                findings = namespace['terminal_punct_finding'](text, {'where': 'footnote', 'note': 1})
                self.assertEqual(len(findings), 1)
                self.assert_period_applied(run(text), text + '.', findings[0]['find'])

    def test_period_existing_tracked_insertion_is_preserved(self):
        old = '<w:ins w:id="88" w:author="Old">' + run('Synthetic citation') + '</w:ins>'
        _, output = self.assert_period_applied(old, 'Synthetic citation.')
        with zipfile.ZipFile(output) as z:
            self.assertIn(old.encode(), z.read('word/footnotes.xml'))
        self.assertEqual(len(self.xml(output, 'word/footnotes.xml').findall('.//{%s}p/{%s}ins' % (W, W))), 2)

    def test_period_existing_tracked_deletion_at_end_is_commented(self):
        deleted = '<w:del w:id="89"><w:r><w:delText>deleted ending</w:delText></w:r></w:del>'
        self.assert_period_comment(run('Synthetic citation') + deleted, reason='deletion')
        self.assert_period_comment(deleted, '…deleted ending', 'end')

    def test_period_duplicate_findings_add_only_one_period(self):
        draft = self.period_draft(run('Synthetic citation'))
        edit = self.period_edit()
        output, answer = self.generate(draft, [edit, dict(edit, id='2')])
        self.assertEqual([e['status'] for e in answer['edits']], ['applied', 'commented_instead'])
        self.assertEqual(answer['totals']['applied'], 1)
        self.assert_period_views(draft, output, 'Synthetic citation.')

    def test_period_excerpt_must_match_the_end(self):
        self.assert_period_comment(run('Synthetic citation followed by other words'), reason='end')
        self.assert_period_comment(run('Different text entirely'), reason='end')

    def test_period_move_source_and_open_move_range_are_commented(self):
        moved = '<w:moveFrom w:id="90">' + run('old ending') + '</w:moveFrom>'
        self.assert_period_comment(run('Synthetic citation') + moved, reason='move')
        start, end = '<w:moveFromRangeStart w:id="90" w:name="m"/>', '<w:moveFromRangeEnd w:id="90"/>'
        for contents in (start + run('Synthetic citation') + end, start + run('Synthetic citation')):
            self.assert_period_comment(contents, reason='move')

    def test_period_other_edit_touching_the_end_wins_regardless_of_input_order(self):
        draft = self.period_draft(run('Synthetic citation'))
        period = self.period_edit()
        change = self.edit('citation', 'citation.', 'n.1', ident='replacement')
        for edits in ([period, change], [change, period]):
            _, answer = self.generate(draft, edits)
            by_id = {e['id']: e for e in answer['edits']}
            self.assertEqual(by_id['replacement']['status'], 'applied')
            self.assertEqual(by_id['1']['status'], 'commented_instead')
            self.assertIn('edit', by_id['1']['reason'])
            self.assertEqual(answer['totals']['applied'], 1)

    def test_period_earlier_edit_and_repeated_excerpt_do_not_block_end(self):
        draft = self.period_draft(run('Typoo citation; Synthetic citation'))
        edits = [self.period_edit('…citation'), self.edit('Typoo', 'Typo', 'n.1', ident='typo')]
        output, answer = self.generate(draft, edits)
        self.assertEqual(answer['totals']['applied'], 2)
        doc = self.document(output)
        self.assertEqual(redline.cleaned(redline.text_view(doc.locations['n.1'][1], doc.numbers))[0],
                         'Typo citation; Synthetic citation.')

    def test_period_whitespace_in_field_is_unchanged(self):
        field = zotero(citation('Synthetic citation  '))
        _, output = self.assert_period_applied(field + run(' \t'), 'Synthetic citation  . \t')
        with zipfile.ZipFile(output) as z:
            self.assertIn(field.encode(), z.read('word/footnotes.xml'))

    def test_period_nested_fields_are_unchanged(self):
        inner = '<w:fldSimple w:instr="REF inner">' + run('Synthetic citation') + '</w:fldSimple>'
        outer = zotero(citation('Synthetic citation'), result_runs=inner)
        _, output = self.assert_period_applied(outer, 'Synthetic citation.')
        with zipfile.ZipFile(output) as z:
            self.assertIn(outer.encode(), z.read('word/footnotes.xml'))

    def test_period_incomplete_field_is_commented(self):
        field = zotero(citation('Synthetic citation')).replace('<w:r><w:fldChar w:fldCharType="end"/></w:r>', '')
        self.assert_period_comment(field, reason='field')

    def test_period_malformed_field_boundaries_are_commented(self):
        field = zotero(citation('Synthetic citation'))
        separate = '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        finish = '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
        for contents in (field.replace(separate, separate * 2), field + finish):
            with self.subTest(contents=contents):
                self.assert_period_comment(contents, reason='field')

    def test_period_normalized_excerpt_matches_extractor_across_paragraphs(self):
        # Load the shared reader explicitly from this checkout, never an installed skill.
        spec = importlib.util.spec_from_file_location('period_citeform', TOOL.parents[2] / 'legal-research/citeform.py')
        citeform = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(citeform)
        draft = self.period_draft(run('  Earlier  text '),
                                  paragraph(run(' Synthetic\t citation \u00a0')) + paragraph(''))
        root = self.xml(draft, 'word/footnotes.xml').find('{%s}footnote' % W)
        spans = []
        for i, p in enumerate(root.findall('{%s}p' % W)):
            if i:
                spans.append((' ', frozenset()))
            spans.extend(citeform.runs_spans(p, {}, None))
        clean = citeform.clean_spans(spans)[0]
        self.assertEqual(clean, 'Earlier text Synthetic citation')
        doc = self.document(draft)
        self.assertEqual(redline.cleaned(redline.text_view(doc.locations['n.1'][1], doc.numbers))[0], clean)
        output, answer = self.generate(draft, [self.period_edit('…' + clean)])
        self.assertEqual(answer['totals']['applied'], 1)
        self.assert_period_views(draft, output, '  Earlier  text   Synthetic\t citation. \u00a0 ')

    def test_period_body_and_unknown_location_never_append(self):
        draft = self.period_draft(run('Synthetic citation'))
        for location, find in (('¶0', '…Body[FN#1]'), ('n.99', '…Synthetic citation'), ('unknown', '…Synthetic citation')):
            _, answer = self.generate(draft, [self.period_edit(find, location=location)])
            self.assertEqual(answer['totals']['applied'], 0)

    def test_period_policy_and_direct_edit_validation(self):
        edit = self.period_edit()
        redline.validate_edits([edit])
        for replacement in ('.', '', None):
            with self.assertRaisesRegex(ValueError, 'replacement'):
                redline.validate_edits([dict(edit, replacement=replacement)])
        finding = dict(location='n.1', find='…Synthetic citation', problem='p', fix='f',
                       category='cite-terminal-punct', severity='likely')
        cases = [finding, dict(finding, replacement=''), dict(finding, category='other'),
                 dict(finding, replacement='Synthetic citation.'), dict(finding, severity='error')]
        self.assertEqual([e['kind'] for e in redline.edits_from_findings(cases)],
                         ['append-period', 'append-period', 'comment', 'comment', 'append-period'])

    def test_period_direct_edits_cli(self):
        draft = self.period_draft(zotero(citation('Synthetic citation')))
        edits = self.root / 'append-edits.json'
        edits.write_text(json.dumps([self.period_edit()]))
        output, result = self.root / 'append-cli.docx', self.root / 'append-cli.json'
        args = [sys.executable, '-I', '-B', str(TOOL), '--draft', str(draft), '--edits', str(edits),
                '--output', str(output), '--result', str(result), '--author', 'Dubitante test', '--date', DATE]
        completed = subprocess.run(args, capture_output=True, text=True, timeout=10)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(result.read_text())['edits'][0]['kind'], 'append-period')
        self.assert_period_views(draft, output, 'Synthetic citation.')

    def test_period_verifier_rejects_changed_field_formatting(self):
        field = zotero(citation('Synthetic citation'), result_runs=run('Synthetic citation', '<w:rPr><w:i/></w:rPr>'))
        draft = self.period_draft(field)
        def corrupt(parts):
            parts['word/footnotes.xml'] = parts['word/footnotes.xml'].replace(b'<w:i/>', b'<w:b/>')
            return parts
        with self.assertRaisesRegex(ValueError, 'Verification failed:.*field'):
            self.generate(draft, [self.period_edit()], corrupt)

    def test_period_verifier_also_protects_fields_before_plain_ending(self):
        field = zotero(citation('Synthetic citation'), result_runs=run('Synthetic citation', '<w:rPr><w:i/></w:rPr>'))
        draft = self.period_draft(field + run(' (parenthetical)'))
        def corrupt(parts):
            parts['word/footnotes.xml'] = parts['word/footnotes.xml'].replace(b'<w:i/>', b'<w:b/>')
            return parts
        with self.assertRaisesRegex(ValueError, 'Verification failed:.*field'):
            self.generate(draft, [self.period_edit('…(parenthetical)')], corrupt)


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
