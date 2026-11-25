"""Endnote regressions: synthetic OOXML only, with all artifacts in worktree scratch."""
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
CLAUDE = ROOT / 'claude-code/skills/proofread/scripts'
CODEX = ROOT / 'codex/internal-proofread/scripts'
W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def run(text, italic=False):
    return '<w:r>' + ('<w:rPr><w:i/></w:rPr>' if italic else '') + '<w:t xml:space="preserve">' + escape(text) + '</w:t></w:r>'


def p(text):
    return '<w:p>' + text + '</w:p>'


def ref(ident, kind='endnote', mark=None):
    return '<w:r><w:' + kind + 'Reference w:id="' + str(ident) + '"' + (' w:customMarkFollows="1"' if mark else '') + '/>' + ('<w:t>' + escape(mark) + '</w:t>' if mark else '') + '</w:r>'


def note(ident, text, kind='endnote', typ=None):
    return f'<w:{kind} w:id="{ident}"' + (f' w:type="{typ}"' if typ else '') + '>' + text + f'</w:{kind}>'


def settings(fmt=None, start=None, restart=None):
    return '<w:endnotePr>' + ''.join(f'<w:{k} w:val="{v}"/>' for k, v in [('numFmt', fmt), ('numStart', start), ('numRestart', restart)] if v is not None) + '</w:endnotePr>'


def field(shown='Synthetic citation', zotero=False):
    code = ' REF synthetic '
    if zotero:
        code = ' ADDIN ZOTERO_ITEM CSL_CITATION ' + json.dumps({'citationID': 'synthetic', 'properties': {'plainCitation': shown, 'formattedCitation': shown}, 'citationItems': [{'suffix': '(teh rule)', 'itemData': {'title': 'Synthetic'}}]})
    return '<w:r><w:fldChar w:fldCharType="begin"/></w:r><w:r><w:instrText>' + escape(code) + '</w:instrText></w:r><w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run(shown) + '<w:r><w:fldChar w:fldCharType="end"/></w:r>'


def draft(path, body=None, ends=None, feet=None, props='', extras=None):
    if body is None:
        body = p(run('Body text') + ref(9))
    if ends is None:
        ends = note(9, p(run('Endnote the the prose.')))
    parts = {'[Content_Types].xml': b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
             'word/document.xml': f'<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>'.encode(),
             'word/settings.xml': f'<w:settings xmlns:w="{W}">{props}</w:settings>'.encode(),
             'word/endnotes.xml': f'<w:endnotes xmlns:w="{W}">{ends}</w:endnotes>'.encode()}
    if feet is not None:
        parts['word/footnotes.xml'] = f'<w:footnotes xmlns:w="{W}">{feet}</w:footnotes>'.encode()
    parts.update(extras or {})
    with zipfile.ZipFile(path, 'x') as z:
        for name, data in parts.items():
            z.writestr(zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0)), data)
    return path


class EndnotesTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.codex-memo/endnotes'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch, prefix='tests-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0

    def call(self, script, *args):
        result = subprocess.run([sys.executable, '-B', str(script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def extract(self, tree, **kwargs):
        self.counter += 1
        source = draft(self.root / f'draft-{self.counter}.docx', **kwargs)
        out = self.root / f'out-{self.counter}'
        out.mkdir()
        if tree == 'claude':
            self.call(CLAUDE / 'extract_proof.py', source, out)
            data = json.loads((out / 'proof.json').read_text())
        else:
            self.call(CODEX / 'extract_draft.py', source, '--output', out / 'document.json')
            data = json.loads((out / 'document.json').read_text())
        return source, out, data

    def ends(self, tree, data):
        return data.get('endnotes', []) if tree == 'claude' else [n for n in data['notes'] if n['story'] == 'endnote']

    def lint(self, tree, out, data):
        if tree == 'claude':
            return data['lint_findings'], {}
        self.call(CODEX / 'lint_draft.py', out / 'document.json', '--findings', out / 'static-findings.jsonl', '--symbols', out / 'symbols.json')
        return self.rows(out / 'static-findings.jsonl'), json.loads((out / 'symbols.json').read_text())

    def rows(self, path):
        return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]

    def test_reference_order_default_roman_and_filtered_entries(self):
        ends = ''.join(note(i, p(run(t)), typ=typ) for i, t, typ in [(4, 'Second.', None), (0, 'Separator.', 'separator'), (-1, 'Continuation.', 'continuationSeparator'), (8, 'Orphan.', None), (9, 'First.', None)])
        body = p(run('One') + ref(9)) + p(run('Two') + ref(4) + ref(9))
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, out, data = self.extract(tree, body=body, ends=ends)
                records = self.ends(tree, data)
                self.assertEqual([r['text'] for r in records], ['First.', 'Second.'])
                self.assertEqual([r['number' if tree == 'claude' else 'display_number'] for r in records], ['i', 'ii'])
                blocks = data.get('blocks') or json.loads(Path(data['chunk_files'][0]).read_text())['paragraphs']
                self.assertIn('[EN#i]', blocks[0]['text'])
                self.assertIn('[EN#ii][EN#i]', blocks[1]['text'])
                if tree == 'claude':
                    self.assertIn('[en.i] First.', (out / 'fulltext.txt').read_text())
                    self.assertIn('===== ENDNOTES =====', (out / 'fulltext_fmt.txt').read_text())

    def test_formats_start_restart_custom_and_unknown(self):
        for tree in ('claude', 'codex'):
            for fmt, wanted in [(None, ['i', 'ii']), ('decimal', ['1', '2']), ('upperRoman', ['I', 'II']), ('lowerLetter', ['a', 'b']), ('unknownFormat', ['i', 'ii'])]:
                with self.subTest(tree=tree, fmt=fmt):
                    _, _, data = self.extract(tree, body=p(run('One') + ref(9) + ref(4)), ends=note(9, p(run('First.'))) + note(4, p(run('Second.'))), props=settings(fmt))
                    records = self.ends(tree, data)
                    self.assertEqual([r.get('number', r.get('display_number')) for r in records], wanted)
                    if fmt == 'unknownFormat':
                        self.assertTrue(any('lowerRoman' in s for s in data['limitations']))
            body = p(run('One') + ref(9)) + '<w:p><w:pPr><w:sectPr>' + settings('decimal', 3, 'eachSect') + '</w:sectPr></w:pPr></w:p>' + p(run('Two') + ref(4))
            _, _, data = self.extract(tree, body=body, ends=note(9, p(run('First.'))) + note(4, p(run('Second.'))), props=settings('decimal', 3, 'eachSect'))
            records = self.ends(tree, data)
            self.assertEqual([r.get('number', r.get('display_number')) for r in records], ['3', '3'])
            self.assertEqual(len({r['location_label'] for r in records}), 2)
            _, out, data = self.extract(tree, body=p(run('Title') + ref(9, mark='*') + ref(4)), ends=note(9, p(run('Custom.'))) + note(4, p(run('Normal.'))))
            self.assertEqual([r.get('number', r.get('display_number')) for r in self.ends(tree, data)], ['*', 'i'])

    def test_tracked_view_fields_and_formatting_offsets(self):
        body = p(run('Start ') + '<w:del>' + ref(4) + '</w:del><w:moveFrom>' + ref(5) + '</w:moveFrom><w:ins>' + ref(9) + '</w:ins>' + run(' Italic after.', True))
        text = run('Good ') + '<w:ins>' + run('new ') + '</w:ins><w:del>' + run('deleted ') + '</w:del><w:moveFrom>' + run('moved ') + '</w:moveFrom>' + field('shown') + run(' tail.', True)
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, out, data = self.extract(tree, body=body, ends=note(9, p(text)) + note(4, p(run('Deleted.'))) + note(5, p(run('Moved.'))))
                self.assertEqual([r['text'] for r in self.ends(tree, data)], ['Good new shown tail.'])
                if tree == 'claude':
                    marked = (out / 'fulltext_fmt.txt').read_text()
                    self.assertIn('[EN#i] <i>Italic after.</i>', marked)
                    self.assertIn('shown <i>tail.</i>', marked)
                    self.assertTrue(data['tracked_insertions'])
                    self.assertTrue(data['tracked_deletions'])

    def test_note_lints_seeded_by_class(self):
        cases = [
            ('Id..', 'cite-id-doubled-period', 'citation.id_double_period'),
            ('Unfinished note', 'cite-terminal-punct', 'endnote.missing_terminal_punctuation'),
            ('97 Harv. L. Rev. 1513, 517.', 'pincite-arithmetic', 'citation.pincite_arithmetic'),
            ('Alpha v. Beta, 585 U.S. 296 (2013).', 'us-volume-year', 'citation.us_volume_year'),
            ('Gamma v. Delta, 326 U.S. 490, 493.', 'cite-missing-year', 'citation.missing_year'),
            ('Smith, supra note 12.', 'note-cross-reference', 'xref.missing_note'),
            ('See Alpha v. Beta, 500 U.S. 100 (1991).', 'fmt-signal-roman', None),
        ]
        for tree in ('claude', 'codex'):
            for text, claude_rule, codex_rule in cases:
                if tree == 'codex' and codex_rule is None:
                    continue  # Codex explicitly does not resolve effective typeface.
                with self.subTest(tree=tree, defect=claude_rule):
                    _, out, data = self.extract(tree, ends=note(9, p(run(text))))
                    rows, _ = self.lint(tree, out, data)
                    key, wanted = ('rule', claude_rule) if tree == 'claude' else ('rule_id', codex_rule)
                    hits = [r for r in rows if r[key] == wanted]
                    self.assertTrue(hits, rows)
                    self.assertTrue(all(r['location'].get('where', r['location'].get('story')) == 'endnote' for r in hits))

    def test_caption_and_supra_names_are_within_series(self):
        ends = note(9, p(run('Alpha v. Beta, 500 U.S. 100 (1991); Smith, A Title.'))) + note(4, p(run('Alpha v. Beta, 501 U.S. 100 (1991); Jones, supra note 1.')))
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, out, data = self.extract(tree, body=p(run('Body') + ref(9) + ref(4)), ends=ends, props=settings('decimal'))
                rows, symbols = self.lint(tree, out, data)
                if tree == 'claude':
                    self.assertTrue({'case-cite-inconsistency', 'supra-target-name'} <= {r['rule'] for r in rows})
                else:
                    self.assertTrue(symbols['case_citation_variants'])
                    self.assertIn('xref.supra_target_name', {r['rule_id'] for r in rows})
                _, out, data = self.extract(tree, body=p(run('Body') + ref(9) + ref(9, 'footnote')), ends=note(9, p(run('Smith. Alpha v. Beta, 500 U.S. 100 (1991).'))), feet=note(9, p(run('Jones. Alpha v. Beta, 501 U.S. 100 (1991).')), 'footnote'))
                rows, symbols = self.lint(tree, out, data)
                if tree == 'claude':
                    self.assertNotIn('case-cite-inconsistency', {r['rule'] for r in rows})
                else:
                    self.assertEqual(symbols['case_citation_variants'], [])

    def test_mixed_series_xrefs_marker_and_chunk_ownership(self):
        body = p(run('Body supra note 99') + ref(9, 'footnote') + ref(9) + run('.')) + p(run('Next') + ref(4))
        feet = note(9, p(run('Smith, supra note 2.')), 'footnote')
        ends = note(4, p(run('Jones, supra note 1.'))) + note(9, p(run('Jones, infra note 2.')))
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, out, data = self.extract(tree, body=body, feet=feet, ends=ends, props=settings('decimal'))
                self.assertEqual(len(self.ends(tree, data)), 2)
                rows, symbols = self.lint(tree, out, data)
                if tree == 'claude':
                    xrefs = [r for r in rows if r['rule'] == 'note-cross-reference']
                    self.assertTrue(xrefs)
                    self.assertEqual({r['location']['where'] for r in xrefs}, {'footnote'})
                    self.assertTrue(any(r['rule'] == 'endnote-before-punctuation' for r in rows))
                    chunk = json.loads(Path(data['chunk_files'][0]).read_text())
                    self.assertEqual(len(chunk['footnotes']), 1)
                    self.assertEqual([r['number'] for r in chunk['endnotes']], ['1', '2'])
                else:
                    xrefs = [r for r in rows if r['rule_id'].startswith('xref.')]
                    self.assertEqual({r['location']['story'] for r in xrefs}, {'footnote'})
                    self.assertTrue(any(r['rule_id'] == 'endnote.before_punctuation' for r in rows))
                    self.assertEqual(symbols['display_endnote_to_block'], {'1': 'EN9', '2': 'EN4'})
                    self.call(CODEX / 'make_chunks.py', out / 'document.json', '--run-dir', out, '--findings', out / 'static-findings.jsonl', '--symbols', out / 'symbols.json', '--min-words', 1, '--target-words', 4, '--max-words', 8)
                    chunks = self.rows(out / 'chunks.jsonl')
                    self.assertEqual(chunks[0]['owned_note_ids'], ['FN9', 'EN9'])
                    self.assertEqual(chunks[1]['owned_note_ids'], ['EN4'])
                    packet = Path(chunks[0]['packet_path']).read_text()
                    self.assertIn('Owned endnotes', packet)
                    semantic = ''.join(f.read_text() for f in (out / 'lane-packets').glob('xref_semantic*'))
                    self.assertIn('EN4', semantic)
                    self.assertNotIn('FN9', semantic)

    def writer(self):
        sys.path.insert(0, str(CLAUDE))
        spec = importlib.util.spec_from_file_location('en_redline', CLAUDE / 'redline_docx.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module

    def redline(self, source, edits, fault=None):
        writer = self.writer()
        self.counter += 1
        output = self.root / f'redline-{self.counter}.docx'
        answer = writer.generate(source, edits, output, self.root / f'result-{self.counter}.json', 'Synthetic', '2026-11-25T12:00:00Z', fault)
        return writer, output, answer

    def test_redline_endnote_change_comment_period_and_views(self):
        for zotero in (False, True):
            with self.subTest(zotero=zotero):
                citation = field(zotero=zotero)
                source, _, _ = self.extract('claude', ends=note(9, p(run('A teh choice. ') + citation)))
                edits = [dict(id='fix', location='en.i', find='teh', replacement='the', kind='change', note='Typo.'),
                         dict(id='query', location='en.i', find='choice', kind='comment', note='Review.'),
                         dict(id='period', location='en.i', find='…Synthetic citation', kind='append-period', note='Final period.')]
                writer, output, answer = self.redline(source, edits)
                self.assertEqual([r['status'] for r in answer['edits']], ['applied', 'commented', 'applied'])
                with zipfile.ZipFile(output) as z:
                    self.assertIn(citation.encode(), z.read('word/endnotes.xml'))
                    self.assertNotIn(b'comment', z.read('word/endnotes.xml'))
                    self.assertIn(b'Endnote i', z.read('word/comments.xml'))
                    doc = writer.Document({n: z.read(n) for n in z.namelist()})
                    ids = {n.attrs[writer.w('id')] for n in doc.roots['word/endnotes.xml'].walk() if n.tag in (writer.w('ins'), writer.w('del'))}
                    for accept, wanted in [(False, 'A teh choice. Synthetic citation'), (True, 'A the choice. Synthetic citation.')]:
                        self.assertEqual(''.join(a.char for a in writer.text_view(doc.locations['en.i'][1], doc.numbers, ids, accept)), wanted)

    def test_redline_zotero_edit_and_unplaced_location_no_fallback(self):
        source, _, _ = self.extract('claude', body=p(run('Unique body typo') + ref(9)), ends=note(9, p(field('Author (teh rule)', True))))
        edits = [dict(id='field', location='en.i', find='teh', replacement='the', kind='change', note='Typo.'),
                 dict(id='wrong', location='en.99', find='Unique body typo', replacement='Changed', kind='change', note='Bad location.')]
        _, output, answer = self.redline(source, edits)
        self.assertEqual(answer['edits'][0]['field'], 'zotero')
        self.assertEqual(answer['edits'][1]['status'], 'unplaced')
        self.assertTrue(answer['edits'][1]['reason'])
        with zipfile.ZipFile(output) as z:
            root = ET.fromstring(z.read('word/endnotes.xml'))
            code = ''.join(n.text or '' for n in root.iter(f'{{{W}}}instrText'))
            self.assertEqual(json.loads(code[code.index('{'):])['citationItems'][0]['suffix'], '(the rule)')

    def test_redline_verifier_rejects_endnote_text_and_field_damage(self):
        source, _, _ = self.extract('claude', ends=note(9, p(run('bad ') + field(zotero=True))))
        edit = dict(id='fix', location='en.i', find='bad', replacement='good', kind='change', note='Typo.')
        for old, new in [(b'>goo<', b'>evil<'), (b'"citationID": "synthetic"', b'"citationID": "corrupt"')]:
            def corrupt(parts):
                self.assertIn(old, parts['word/endnotes.xml'])
                parts['word/endnotes.xml'] = parts['word/endnotes.xml'].replace(old, new)
                return parts
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'Verification failed'):
                self.redline(source, [edit], corrupt)

    def test_codex_replacement_merge_report_and_location_validation(self):
        _, out, data = self.extract('codex', ends=note(9, p(run('Endnote lawprofessor prose.'))))
        records = self.ends('codex', data)
        self.assertEqual(len(records), 1)
        block = records[0]
        location = dict(block['location'], story='endnote', block_id=block['block_id'], char_start=0, char_end=len(block['text']), heading_path=[])
        finding = dict(finding_id='FEN', location=location, excerpt=block['text'], replacement='Endnote law professor prose.', category='typo', severity='error', impact='low', message='Missing space.', suggestion='Separate words.')
        (out / 'run-manifest.json').write_text(json.dumps(dict(draft_sha256=data['input_sha256'], replacements=True, counts={}, limitations=data['limitations'])))
        (out / 'agent-results').mkdir()
        result = out / 'agent-results/C1.json'
        result.write_text(json.dumps(dict(source_sha256=data['input_sha256'], chunk_id='C1', findings=[finding])))
        self.lint('codex', out, data)
        self.call(CODEX / 'merge_findings.py', out)
        merged = self.rows(out / 'findings.jsonl')
        self.assertEqual(merged[0]['location'], location)
        self.assertEqual(merged[0]['replacement'], finding['replacement'])
        (out / 'dispositions.jsonl').write_text(json.dumps(dict(finding_id='FEN', status='confirmed')) + '\n')
        self.call(CODEX / 'build_report.py', out)
        self.assertIn('Endnote i', (out / 'report.md').read_text())
        self.assertEqual(self.rows(out / 'dispositions.jsonl')[0]['replacement'], finding['replacement'])
        finding['location']['story'] = 'footnote'
        result.write_text(json.dumps(dict(source_sha256=data['input_sha256'], chunk_id='C1', findings=[finding])))
        bad = subprocess.run([sys.executable, str(CODEX / 'merge_findings.py'), str(out)], capture_output=True, text=True)
        self.assertNotEqual(bad.returncode, 0)


    def test_ambiguous_restarted_xrefs_and_roman_xrefs(self):
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                body = p(run('One') + ref(9)) + '<w:p><w:pPr><w:sectPr/></w:pPr></w:p>' + p(run('Two') + ref(4))
                _, out, data = self.extract(tree, body=body, ends=note(9, p(run('Smith, A Title.'))) + note(4, p(run('Jones, supra note 1.'))), props=settings('decimal', 1, 'eachSect'))
                rows, _ = self.lint(tree, out, data)
                self.assertEqual(len(self.ends(tree, data)), 2)
                self.assertFalse(any(r.get('rule') in ('note-cross-reference', 'supra-target-name') or r.get('rule_id', '').startswith('xref.') for r in rows), rows)
                self.assertTrue(any('ambiguous' in x.lower() for x in data['limitations']))
                _, out, data = self.extract(tree, body=p(run('Body supra note iii') + ref(9) + ref(4)), ends=note(9, p(run('Smith, infra note ii.'))) + note(4, p(run('Smith, supra note i.'))))
                rows, _ = self.lint(tree, out, data)
                xrefs=[r for r in rows if r.get('rule') == 'note-cross-reference' or r.get('rule_id', '').startswith('xref.')]
                self.assertEqual(len(xrefs), 1, rows)
                self.assertEqual(xrefs[0]['location'].get('where', xrefs[0]['location'].get('story')), 'body')

    def test_redline_period_guards_and_mixed_identical_ids(self):
        for ending, wanted in [(run('Done.'), 'commented_instead'),
                               (run('Done') + '<w:del w:id="90"><w:r><w:delText>old</w:delText></w:r></w:del>', 'commented_instead'),
                               (field('Done').replace('<w:r><w:fldChar w:fldCharType="end"/></w:r>', ''), 'commented_instead')]:
            with self.subTest(ending=ending):
                source, _, _ = self.extract('claude', body=p(run('Body') + ref(9, 'footnote') + ref(9)), feet=note(9, p(run('Footnote choice.')), 'footnote'), ends=note(9, p(ending)))
                edits=[dict(id='fn', location='n.1', find='choice', kind='comment', note='Footnote.'),
                       dict(id='en', location='en.i', find='Done.' if 'Done.' in ending else 'Done', kind='append-period', note='Endnote.')]
                _, output, answer = self.redline(source, edits)
                self.assertEqual(answer['edits'][1]['status'], wanted)
                with zipfile.ZipFile(source) as before, zipfile.ZipFile(output) as after:
                    self.assertEqual(before.read('word/endnotes.xml'), after.read('word/endnotes.xml'))
                    comments = ET.fromstring(after.read('word/comments.xml'))
                    self.assertEqual(len(comments), 2)

    def test_workflow_endnote_sort_prompts_and_findings(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Existing workflow harness needs Node; no install attempted.')
        _, out, data = self.extract('claude', body=p(run('Body')+ref(9,'footnote')+ref(9)), feet=note(9,p(run('Footnote the the prose.')),'footnote'))
        script = r"""
const fs=require('fs');
const src=fs.readFileSync(process.argv[1],'utf8').replace(/^export const meta/m,'const meta');
const d=JSON.parse(fs.readFileSync(process.argv[2]+'/proof.json','utf8'));
const prompts=[];
async function agent(prompt,opts){
 prompts.push(prompt);
 if(opts.label.startsWith('consistency'))return {findings:[],conventions:[]};
 if(opts.label.startsWith('proof:'))return {findings:[]};
 if(opts.label.startsWith('verify:')){
  const start=prompt.lastIndexOf('FINDINGS (verify batch');
  const batch=JSON.parse(prompt.slice(prompt.indexOf('[',start),prompt.lastIndexOf(']')+1));
  return {verdicts:batch.map(f=>({id:f.id,verdict:'confirmed',note:'Synthetic.'}))};
 }
 if(opts.label==='report')return null;
 throw Error(opts.label);
}
const AF=Object.getPrototypeOf(async function(){}).constructor;
new AF('args','budget','agent','parallel','phase','log',src)(
 {outDir:process.argv[2],chunkFiles:d.chunk_files,lintFindings:d.lint_findings,endnotes:d.endnotes,counts:{endnotes:d.endnote_count}},
 {total:null,spent:()=>0},agent,async fs=>Promise.all(fs.map(f=>f())),()=>{},()=>{}
).then(result=>console.log(JSON.stringify({result,prompts})));
"""
        proc=subprocess.run([node,'-e',script,str(CLAUDE.parent/'proofread.workflow.js'),str(out)],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        value=json.loads(proc.stdout)
        self.assertEqual([f['location'] for f in value['result']['findings']],['n.1','en.i'])
        self.assertIn('endnote i',value['result']['report'])
        self.assertTrue(any('"endnotes"' in p for p in value['prompts']))
        self.assertTrue(any('[en.' in p for p in value['prompts']))

    def test_codex_primary_recall_and_challenger_endnote_coverage(self):
        source=draft(self.root/'lifecycle.docx',ends=note(9,p(run('A clean endnote sentence.'))))
        out=self.root/'lifecycle'
        self.call(CODEX/'init_run.py',source,'--run-dir',out)
        manifest=json.loads((out/'run-manifest.json').read_text())
        chunks=self.rows(out/'chunks.jsonl')
        self.assertEqual([n for c in chunks for n in c['owned_note_ids']],['EN9'])
        for chunk in chunks:
            result=dict(chunk_id=chunk['chunk_id'],source_sha256=manifest['draft_sha256'],status='complete',reviewed_block_ids=chunk['core_block_ids'],reviewed_note_ids=chunk['owned_note_ids'],findings=[])
            for suffix in ('','-audit'):
                (out/'agent-results'/f"{chunk['chunk_id']}{suffix}.json").write_text(json.dumps(result))
        for lane in manifest['required_lanes']:
            (out/'lane-results'/f'{lane}.json').write_text(json.dumps(dict(lane=lane,source_sha256=manifest['draft_sha256'],status='complete',findings=[])))
        self.call(CODEX/'merge_findings.py',out)
        self.call(CODEX/'make_recall_packets.py',out)
        packets=self.rows(out/'recall-packets.jsonl')
        self.assertEqual([n for c in packets for n in c['reviewed_note_ids']],['EN9'])
        for packet in packets:
            (out/'recall-results'/f"{packet['packet_id']}.json").write_text(json.dumps(dict(packet_id=packet['packet_id'],source_sha256=manifest['draft_sha256'],status='complete',reviewed_block_ids=packet['reviewed_block_ids'],reviewed_note_ids=packet['reviewed_note_ids'],findings=[])))
        self.call(CODEX/'merge_findings.py',out)
        self.call(CODEX/'build_report.py',out)
        self.call(CODEX/'validate_run.py',out,'--require-ready')
        report=self.root/'challenger.md'
        report.write_text('- **en.i** — `clean endnote sentence` — Review wording.\n')
        self.call(CODEX/'ingest_challenger.py',out,report)
        self.assertEqual(self.rows(out/'challenger-findings.jsonl')[0]['location']['block_id'],'EN9')
        bad=dict(packet_id=packets[-1]['packet_id'],source_sha256=manifest['draft_sha256'],status='complete',reviewed_block_ids=[],reviewed_note_ids=[],findings=[])
        (out/'recall-results'/f"{packets[-1]['packet_id']}.json").write_text(json.dumps(bad))
        proc=subprocess.run([sys.executable,str(CODEX/'validate_run.py'),str(out),'--require-ready'],capture_output=True,text=True)
        self.assertNotEqual(proc.returncode,0)
        self.assertIn('recall result note coverage mismatch',proc.stderr)

    def test_roman_supra_names_and_ranges_crossing_current_note(self):
        body = p(run('Body') + ref(9) + ref(4) + ref(7))
        ends = note(9, p(run('Smith, A Title.'))) + note(4, p(run('Jones, supra note I; supra notes I–III.'))) + note(7, p(run('Another note.')))
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, out, data = self.extract(tree, body=body, ends=ends, props=settings('upperRoman'))
                rows, _ = self.lint(tree, out, data)
                rules = {r['rule' if tree == 'claude' else 'rule_id'] for r in rows}
                self.assertIn('supra-target-name' if tree == 'claude' else 'xref.supra_target_name', rules)
                self.assertIn('note-cross-reference' if tree == 'claude' else 'xref.note_direction', rules)

    def test_wrapped_endnote_paragraphs_and_body_callsite(self):
        wrapped = '<w:sdt><w:sdtContent>' + p(run('Wrapped teh note.')) + '</w:sdtContent></w:sdt>'
        deleted = '<w:del w:id="91">' + p(run('Deleted paragraph.')) + '</w:del>'
        body = '<w:sdt><w:sdtContent>' + p(run('Wrapped callsite.') + ref(9)) + '</w:sdtContent></w:sdt>'
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                source, out, data = self.extract(tree, body=body, ends=note(9, wrapped + deleted))
                self.assertEqual(self.ends(tree, data)[0]['text'], 'Wrapped teh note.')
                if tree == 'claude':
                    _, _, answer = self.redline(source, [dict(id='fix', location='en.i', find='teh', replacement='the', kind='change', note='Typo.')])
                    self.assertEqual(answer['edits'][0]['status'], 'applied')
                else:
                    self.assertEqual(data['blocks'][0]['endnote_ids'], ['9'])
                    self.assertIn('[EN#i]', data['blocks'][0]['text'])

    def test_codex_endnote_marker_search_mapping_and_replacement_guard(self):
        sys.path.insert(0, str(CODEX))
        import build_report
        import ingest_challenger
        import replacements
        text = 'Before the call[EN#i] after the call.'
        block = dict(block_id='B000001', story='body', text=text)
        location = dict(block_id='B000001', char_start=7, char_end=10)
        anchor, _ = build_report.search_anchor(dict(location=location), {'B000001': block}, [text], {})
        self.assertTrue(anchor)
        self.assertNotIn('[EN#', anchor)
        self.assertIn(anchor, text)
        matches, reason = ingest_challenger.map_item(dict(report_excerpt='Before the call[EN#i] after the call.'), [block])
        self.assertEqual(len(matches), 1, reason)
        self.assertEqual(matches[0]['excerpt'], text)
        with self.assertRaisesRegex(ValueError, 'marker'):
            replacements.validate_replacement(dict(location=dict(location, char_start=0, char_end=len(text)), excerpt=text, replacement='Before the call after the call.', category='typo'), {'B000001': block})

    def normalized(self, source, out, data):
        substitutions = {str(source): '<SOURCE>', str(out): '<OUT>', hashlib.sha256(source.read_bytes()).hexdigest(): '<SHA>'}
        if 'extracted_at' in data:
            substitutions[data['extracted_at']] = '<TIME>'
        result = {}
        for f in sorted(out.rglob('*')):
            if f.is_file():
                text = f.read_text()
                for old, new in substitutions.items():
                    text = text.replace(old, new)
                result[str(f.relative_to(out))] = text
        return result

    def test_no_endnotes_matches_19c9937_bytes(self):
        golden = json.loads((CODEX / 'fixtures/endnotes-no-endnotes.json').read_text())
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                result = self.extract(tree, body=p(run('Body text.') + ref(9, 'footnote')),
                                      ends='', feet=note(9, p(run('Smith, A Title. Id..')), 'footnote'))
                self.assertEqual(self.normalized(*result), golden[tree])


if __name__ == '__main__':
    unittest.main()
