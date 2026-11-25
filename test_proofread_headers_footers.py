"""Synthetic OOXML regressions for both independently shipped proofreaders."""
import hashlib
import importlib.util
import json
import os
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
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'


def run(text):
    return '<w:r><w:t xml:space="preserve">' + escape(text) + '</w:t></w:r>'


def p(contents):
    return '<w:p>' + contents + '</w:p>'


def field(code='PAGE', result='7', simple=False):
    if simple:
        return '<w:fldSimple w:instr="' + code + '">' + run(result) + '</w:fldSimple>'
    return ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
            '<w:r><w:instrText>' + code + '</w:instrText></w:r>'
            '<w:r><w:fldChar w:fldCharType="separate"/></w:r>' + run(result) +
            '<w:r><w:fldChar w:fldCharType="end"/></w:r>')


def docx(path, stories=(), sections=None, body=None):
    # stories: (kind, relationship id, OPC part name, paragraph XML)
    if sections is None:
        sections = [[(kind, 'first', rid) for kind, rid, _, _ in stories]]
    rels = ''.join(f'<Relationship Id="{rid}" Type="{R}/{kind}" Target="{part[5:]}"/>'
                   for kind, rid, part, _ in stories)
    def sect(refs):
        return '<w:sectPr>' + ''.join(
            f'<w:{kind}Reference w:type="{typ}" r:id="{rid}"/>' for kind, typ, rid in refs
        ) + '<w:titlePg/></w:sectPr>'
    content = body if body is not None else p(run('A clean body paragraph.'))
    for refs in sections[:-1]:
        content += '<w:p><w:pPr>' + sect(refs) + '</w:pPr></w:p>'
    content += sect(sections[-1])
    parts = {
        '[Content_Types].xml': b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/></Types>',
        'word/document.xml': (f'<w:document xmlns:w="{W}" xmlns:r="{R}"><w:body>{content}</w:body></w:document>').encode(),
        'word/footnotes.xml': f'<w:footnotes xmlns:w="{W}"/>'.encode(),
        'word/_rels/document.xml.rels': f'<Relationships xmlns="{REL}">{rels}</Relationships>'.encode(),
        'word/settings.xml': f'<w:settings xmlns:w="{W}"><w:evenAndOddHeaders/></w:settings>'.encode(),
    }
    for kind, _, part, contents in stories:
        tag = 'hdr' if kind == 'header' else 'ftr'
        parts[part] = f'<w:{tag} xmlns:w="{W}">{contents}</w:{tag}>'.encode()
    with zipfile.ZipFile(path, 'x') as z:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, (2020, 1, 1, 0, 0, 0))
            z.writestr(info, data)
    return path


def load_writer():
    sys.path.insert(0, str(CLAUDE))
    spec = importlib.util.spec_from_file_location('hf_redline', CLAUDE / 'redline_docx.py')
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class CoverageTests(unittest.TestCase):
    def setUp(self):
        scratch = ROOT / '.codex-memo/headers-footers'
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix='tests-', dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.counter = 0

    def call(self, script, *args):
        result = subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result

    def extract(self, tree, stories=(), sections=None, body=None, suffix='.docx'):
        self.counter += 1
        source = self.root / f'draft-{self.counter}{suffix}'
        if suffix == '.docx':
            docx(source, stories, sections, body)
        else:
            source.write_text('A clean body paragraph.\n')
        out = self.root / f'out-{self.counter}'
        out.mkdir()
        if tree == 'claude':
            self.call(CLAUDE / 'extract_proof.py', source, out)
            data = json.loads((out / 'proof.json').read_text())
            records = data.get('headers_footers', [])
        else:
            self.call(CODEX / 'extract_draft.py', source, '--output', out / 'document.json')
            data = json.loads((out / 'document.json').read_text())
            records = [b for b in data['blocks'] if b['story'] in ('header', 'footer')]
        return source, out, data, records

    def test_all_types_shared_parts_and_identical_parts(self):
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                stories = [(k, k + t, f'word/{k}-{t}.xml', p(run(f'{k} {t} the the text.')))
                           for k in ('header', 'footer') for t in ('default', 'first', 'even')]
                refs = [(k, t, k + t) for k in ('header', 'footer') for t in ('default', 'first', 'even')]
                _, _, _, records = self.extract(tree, stories, [refs, refs])
                self.assertEqual(len(records), 6)
                self.assertEqual({r['location']['where'] for r in records}, {'header', 'footer'})
                for record in records:
                    self.assertEqual([o['section'] for o in record['location']['occurrences']], [1, 2])
                twins = [('footer', 'a', 'word/footer1.xml', p(run('The the author note.'))),
                         ('footer', 'b', 'word/footer2.xml', p(run('The the author note.')))]
                _, out, data, records = self.extract(tree, twins, [[('footer', 'first', 'a')], [('footer', 'first', 'b')]])
                self.assertEqual(len(records), 1)
                self.assertEqual(len(records[0]['location']['occurrences']), 2)
                self.assertIn('section 1', records[0]['location_label'])
                self.assertIn('section 2', records[0]['location_label'])
                if tree == 'claude':
                    hits = [f for f in data['lint_findings'] if f['rule'] == 'doubled-word']
                else:
                    self.call(CODEX / 'lint_draft.py', out / 'document.json', '--findings', out / 'lint.jsonl', '--symbols', out / 'symbols.json')
                    hits = [json.loads(s) for s in (out / 'lint.jsonl').read_text().splitlines() if 'text.adjacent_duplicate' in s]
                self.assertEqual(len(hits), 1)
                self.assertEqual(hits[0]['location']['occurrences'], records[0]['location']['occurrences'])

    def test_inheritance_unreferenced_parts_and_empty_parts(self):
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                stories = [('footer', 'f', 'word/footer1.xml', p(run('Author prose.'))),
                           ('header', 'unused', 'word/header1.xml', p(run('Unused the the error.'))),
                           ('header', 'empty', 'word/header2.xml', p(''))]
                _, _, _, records = self.extract(tree, stories, [[('footer', 'default', 'f'), ('header', 'first', 'empty')], []])
                self.assertEqual(len(records), 1)
                self.assertEqual([o['section'] for o in records[0]['location']['occurrences']], [1, 2])

    def test_page_furniture_and_mixed_field_segments(self):
        for tree in ('claude', 'codex'):
            for simple in (False, True):
                with self.subTest(tree=tree, simple=simple):
                    stories = [('footer', 'f', 'word/footer1.xml', p(field(simple=simple))),
                               ('header', 'h', 'word/header1.xml', p(run('Title words ') + field(simple=simple) + run(' more prose.')))]
                    _, out, _, records = self.extract(tree, stories)
                    self.assertEqual([r['text'] for r in records], ['Title words', 'more prose.'])
                    self.assertTrue(all(r['location']['where'] == 'header' for r in records))
                    if tree == 'claude':
                        self.assertNotIn('7', (out / 'fulltext.txt').read_text())

    def test_tracked_text_and_field_instructions(self):
        visible = (run('  Good  ') + '<w:ins w:id="80">' + run('new ') + '</w:ins>' +
                   '<w:del w:id="81">' + run('deleted ') + '</w:del>' +
                   '<w:moveFrom w:id="82">' + run('moved ') + '</w:moveFrom>' +
                   run('text ') + field('REF unseen_instruction', 'shown'))
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, _, _, records = self.extract(tree, [('footer', 'f', 'word/footer1.xml', p(visible))])
                self.assertEqual([r['text'] for r in records], ['Good new text shown'])

    def test_footer_general_lint_and_citation_rules_without_terminal_period(self):
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                _, out, data, records = self.extract(tree, [('footer', 'f', 'word/footer1.xml', p(run('The the author cites Id.. and “unclosed')))])
                self.assertEqual(len(records), 1)
                if tree == 'claude':
                    rules = {r['rule'] for r in data['lint_findings']}
                    self.assertTrue({'doubled-word', 'cite-id-doubled-period', 'unbalanced-quotes'} <= rules)
                    self.assertNotIn('cite-terminal-punct', rules)
                else:
                    self.call(CODEX / 'lint_draft.py', out / 'document.json', '--findings', out / 'lint.jsonl', '--symbols', out / 'symbols.json')
                    rules = {json.loads(s)['rule_id'] for s in (out / 'lint.jsonl').read_text().splitlines()}
                    self.assertTrue({'text.adjacent_duplicate', 'citation.id_double_period', 'delimiter.unbalanced_curly_quote'} <= rules)
                    self.assertNotIn('footnote.missing_terminal_punctuation', rules)

    def normalized_outputs(self, tree, result):
        source, out, data, _ = result
        replacements = {str(source): '<SOURCE>', str(out): '<OUT>', hashlib.sha256(source.read_bytes()).hexdigest(): '<SHA>'}
        if tree == 'codex':
            replacements[data['extracted_at']] = '<TIME>'
        answer = {}
        for path in sorted(out.rglob('*')):
            if path.is_file():
                value = path.read_text()
                for old, new in replacements.items():
                    value = value.replace(old, new)
                answer[str(path.relative_to(out))] = value
        return answer

    def test_no_stories_matches_release_golden(self):
        expected = json.loads((CODEX / 'fixtures/headers-footers-no-stories.json').read_text())
        for tree in ('claude', 'codex'):
            for suffix in ('.docx', '.md'):
                with self.subTest(tree=tree, suffix=suffix):
                    self.assertEqual(self.normalized_outputs(tree, self.extract(tree, suffix=suffix)), expected[tree + suffix])

    def test_body_chunks_unchanged_and_footer_is_owned(self):
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                plain = self.extract(tree)
                rich = self.extract(tree, [('footer', 'f', 'word/footer1.xml', p(run('Author pro') + run('fessor note.')))])
                self.assertEqual(rich[3][0]['text'], 'Author professor note.')
                if tree == 'claude':
                    old = [json.loads(Path(f).read_text()) for f in plain[2]['chunk_files']]
                    new = [json.loads(Path(f).read_text()) for f in rich[2]['chunk_files']]
                    self.assertEqual(new[:-1], old)
                    self.assertEqual(new[-1]['headers_footers'][0]['text'], 'Author professor note.')
                else:
                    chunks = []
                    for _, out, _, _ in (plain, rich):
                        self.call(CODEX / 'lint_draft.py', out / 'document.json', '--findings', out / 'lint.jsonl', '--symbols', out / 'symbols.json')
                        self.call(CODEX / 'make_chunks.py', out / 'document.json', '--run-dir', out, '--findings', out / 'lint.jsonl', '--symbols', out / 'symbols.json')
                        chunks.append([json.loads(s) for s in (out / 'chunks.jsonl').read_text().splitlines()])
                    self.assertEqual(chunks[1][0]['core_block_ids'], chunks[0][0]['core_block_ids'])
                    self.assertEqual(len(chunks[1]), len(chunks[0]) + 1)
                    packet = Path(chunks[1][-1]['packet_path']).read_text()
                    self.assertIn('First-page footer', packet)
                    self.assertIn('Author professor note.', packet)

    def test_codex_replacement_location_survives_merge_report_and_packets(self):
        _, out, document, records = self.extract('codex', [('footer', 'f', 'word/footer1.xml', p(run('Author law') + run('professor note.')))])
        block = records[0]
        location = dict(block['location'], story='footer', block_id=block['block_id'], char_start=0,
                        char_end=len(block['text']), heading_path=[])
        finding = dict(finding_id='FHF', location=location, excerpt=block['text'], replacement='Author law professor note.',
                       category='typo', severity='error', impact='low', message='Missing space.', suggestion='Separate law professor.')
        (out / 'run-manifest.json').write_text(json.dumps(dict(draft_sha256=document['input_sha256'], replacements=True, counts={}, limitations=[])))
        (out / 'agent-results').mkdir()
        (out / 'agent-results/C1.json').write_text(json.dumps(dict(source_sha256=document['input_sha256'], chunk_id='C1', findings=[finding])))
        self.call(CODEX / 'lint_draft.py', out / 'document.json', '--findings', out / 'static-findings.jsonl', '--symbols', out / 'symbols.json')
        self.call(CODEX / 'merge_findings.py', out)
        merged = [json.loads(s) for s in (out / 'findings.jsonl').read_text().splitlines()]
        self.assertEqual(merged[0]['location'], location)
        self.assertEqual(merged[0]['replacement'], finding['replacement'])
        (out / 'dispositions.jsonl').write_text(json.dumps(dict(finding_id='FHF', status='confirmed')) + '\n')
        self.call(CODEX / 'build_report.py', out)
        report = (out / 'report.md').read_text()
        self.assertIn('First-page footer', report)
        self.assertIn('section 1', report)
        self.assertIn('Author lawprofessor note.', report)
        final = json.loads((out / 'dispositions.jsonl').read_text())
        self.assertEqual(final['replacement'], finding['replacement'])

    def redline(self, source, edits, fault=None):
        writer = load_writer()
        self.counter += 1
        output = self.root / f'redline-{self.counter}.docx'
        result = self.root / f'result-{self.counter}.json'
        answer = writer.generate(source, edits, output, result, 'Synthetic', '2026-11-25T12:00:00Z', fault)
        return writer, output, answer

    def test_footer_run_together_change_comment_accept_reject_and_field_bytes(self):
        page = field()
        source, _, _, records = self.extract('claude', [('footer', 'f', 'word/footer1.xml', p(run('Author law') + run('professor note. ') + page))])
        self.assertEqual(len(records), 1)
        edit = dict(id='one', location=records[0]['location_label'], find='lawprofessor', replacement='law professor', kind='change', note='Missing space.')
        writer, output, answer = self.redline(source, [edit])
        self.assertEqual(answer['totals']['applied'], 1)
        with zipfile.ZipFile(source) as z, zipfile.ZipFile(output) as changed:
            original = writer.Document({n: z.read(n) for n in z.namelist()})
            after = writer.Document({n: changed.read(n) for n in changed.namelist()})
            xml = changed.read('word/footer1.xml')
            self.assertIn(page.encode(), xml)
            self.assertNotIn(b'commentRange', xml)
            comments = ET.fromstring(changed.read('word/comments.xml'))
            text = ''.join(comments.itertext())
            self.assertTrue(text.startswith('First-page footer'))
            self.assertIn('lawprofessor', text)
            first = ET.fromstring(changed.read('word/document.xml')).find(f'.//{{{W}}}p')
            self.assertEqual(first[0].tag, f'{{{W}}}commentRangeStart')
            ids = {n.attrs[writer.w('id')] for n in after.roots['word/footer1.xml'].walk() if n.tag in (writer.w('ins'), writer.w('del'))}
            for accept, expected in ((False, 'Author lawprofessor note. 7'), (True, 'Author law professor note. 7')):
                actual = ''.join(a.char for a in writer.text_view(after.roots['word/footer1.xml'], after.numbers, ids, accept))
                self.assertEqual(actual, expected)

    def test_comment_only_unplaced_and_no_footer_period(self):
        source, _, _, records = self.extract('claude', [('footer', 'f', 'word/footer1.xml', p(run('Author fragment')))])
        self.assertEqual(len(records), 1)
        loc = records[0]['location_label']
        edits = [dict(id='comment', location=loc, find='fragment', kind='comment', note='Review wording.'),
                 dict(id='absent', location=loc, find='missing words', kind='comment', note='Cannot locate.'),
                 dict(id='period', location=loc, find='Author fragment', kind='append-period', note='Do not append.')]
        _, output, answer = self.redline(source, edits)
        self.assertEqual(answer['totals']['applied'], 0)
        self.assertEqual(answer['edits'][1]['status'], 'unplaced')
        with zipfile.ZipFile(source) as z, zipfile.ZipFile(output) as after:
            self.assertEqual(z.read('word/footer1.xml'), after.read('word/footer1.xml'))
            self.assertIn(b'First-page footer', after.read('word/comments.xml'))

    def test_duplicate_parts_all_corrected_and_bad_location_never_falls_into_body(self):
        twins = [('footer', 'a', 'word/footer1.xml', p(run('lawprofessor'))),
                 ('footer', 'b', 'word/footer2.xml', p(run('lawprofessor')))]
        source, _, _, records = self.extract('claude', twins, [[('footer', 'first', 'a')], [('footer', 'first', 'b')]], p(run('lawprofessor')))
        self.assertEqual(len(records), 1)
        edit = dict(id='one', location=records[0]['location_label'], find='lawprofessor', replacement='law professor', kind='change', note='Missing space.')
        _, output, answer = self.redline(source, [edit])
        self.assertEqual(answer['totals']['applied'], 1)
        with zipfile.ZipFile(output) as z:
            for name in ('word/footer1.xml', 'word/footer2.xml'):
                self.assertIn(b':ins ', z.read(name))
        _, _, answer = self.redline(source, [dict(edit, location='First-page footer, section 99, paragraph 1')])
        self.assertEqual(answer['totals']['unplaced'], 1)

    def test_verifier_rejects_footer_text_and_field_instruction_corruption(self):
        source, _, _, records = self.extract('claude', [('footer', 'f', 'word/footer1.xml', p(run('bad ') + field()))])
        self.assertEqual(len(records), 1)
        edit = dict(id='one', location=records[0]['location_label'], find='bad', replacement='good', kind='change', note='Fix.')
        for old, new in ((b'>goo<', b'>evil<'), (b'PAGE', b'DATE')):
            def corrupt(parts):
                self.assertIn(old, parts['word/footer1.xml'])
                parts['word/footer1.xml'] = parts['word/footer1.xml'].replace(old, new)
                return parts
            with self.subTest(old=old), self.assertRaisesRegex(ValueError, 'Verification failed'):
                self.redline(source, [edit], corrupt)

    def test_workflow_footer_finding_sort_and_replacement(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Existing workflow harness requires Node; no install attempted.')
        _, out, data, records = self.extract('claude', [
            ('footer', 'f', 'word/footer1.xml', p(run('Author law') + run('professor note.'))),
            ('header', 'h', 'word/header1.xml', p(run('The the running title.')))],
            [[('footer', 'first', 'f'), ('header', 'default', 'h')]], p(run('The the body text.')))
        script = r'''
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8').replace(/^export const meta/m, 'const meta');
const data = JSON.parse(fs.readFileSync(process.argv[2] + '/proof.json', 'utf8'));
const AF = Object.getPrototypeOf(async function(){}).constructor;
const prompts = [];
async function agent(prompt, opts) {
  prompts.push(prompt);
  if (opts.label.startsWith('consistency')) return {findings:[], conventions:[]};
  if (opts.label.startsWith('proof:chunk-')) {
    const index = +opts.label.split('-').pop();
    const chunk = JSON.parse(fs.readFileSync(data.chunk_files[index], 'utf8'));
    return {findings:(chunk.headers_footers || []).filter(r => r.text.includes('lawprofessor')).map(r => ({
      location:r.location_label, find:'lawprofessor', replacement:'law professor',
      problem:'Missing space.', fix:'Separate the words.', category:'typo', severity:'error'}))};
  }
  if (opts.label.startsWith('verify:')) {
    const at = prompt.lastIndexOf('FINDINGS (verify batch');
    const batch = JSON.parse(prompt.slice(prompt.indexOf('[', at), prompt.lastIndexOf(']')+1));
    return {verdicts:batch.map(f => ({id:f.id, verdict:'confirmed', note:'Synthetic verdict.'}))};
  }
  if (opts.label === 'report') return null;
  throw new Error(opts.label);
}
new AF('args','budget','agent','parallel','phase','log',src)(
  {outDir:process.argv[2], chunkFiles:data.chunk_files, lintFindings:data.lint_findings, replacements:true},
  {total:null, spent:()=>0}, agent, async fs=>Promise.all(fs.map(f=>f())), ()=>{}, ()=>{}
).then(result=>console.log(JSON.stringify({result,prompts})));
'''
        result = subprocess.run([node, '-e', script, str(CLAUDE.parent / 'proofread.workflow.js'), str(out)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        findings = payload['result']['findings']
        self.assertEqual(len(findings), 3)
        self.assertTrue(findings[0]['location'].startswith('First-page footer'))
        self.assertEqual(findings[0]['replacement'], 'law professor')
        self.assertEqual(findings[1]['location'], '¶0')
        self.assertTrue(findings[2]['location'].startswith('Default header'))
        self.assertNotIn('¶undefined', payload['result']['report'])
        self.assertTrue(any('headers_footers' in prompt for prompt in payload['prompts']))
        source = Path(data['source'])
        writer = load_writer()
        _, _, answer = self.redline(source, writer.edits_from_findings(findings))
        self.assertEqual(answer['totals']['applied'], 1)

    def test_field_only_output_matches_empty_story_extraction(self):
        for tree in ('claude', 'codex'):
            with self.subTest(tree=tree):
                baseline = self.normalized_outputs(tree, self.extract(tree))
                actual = self.normalized_outputs(tree, self.extract(tree, [('footer', 'f', 'word/footer1.xml', p(field()))]))
                self.assertEqual(actual, baseline)

    def test_unplaceable_duplicate_is_atomic(self):
        # Same visible prose, but one copy crosses a prior deletion.
        stories = [('footer', 'a', 'word/footer1.xml', p(run('lawprofessor'))),
                   ('footer', 'b', 'word/footer2.xml', p(run('law') +
                    '<w:del w:id="99"><w:r><w:delText>old</w:delText></w:r></w:del>' + run('professor')))]
        source, _, _, records = self.extract('claude', stories, [[('footer', 'first', 'a')], [('footer', 'first', 'b')]])
        edit = dict(id='one', location=records[0]['location_label'], find='lawprofessor', replacement='law professor', kind='change', note='Missing space.')
        _, output, answer = self.redline(source, [edit])
        self.assertEqual(answer['totals']['commented_instead'], 1)
        self.assertEqual(answer['totals']['applied'], 0)
        with zipfile.ZipFile(source) as before, zipfile.ZipFile(output) as after:
            for name in ('word/footer1.xml', 'word/footer2.xml'):
                self.assertEqual(before.read(name), after.read(name))

    def test_no_footnotes_part_and_each_header_footer_kind_can_be_redlined(self):
        for kind in ('header', 'footer'):
            for typ in ('default', 'first', 'even'):
                with self.subTest(kind=kind, typ=typ):
                    source = self.root / f'without-notes-{kind}-{typ}.docx'
                    original = docx(self.root / f'with-notes-{kind}-{typ}.docx',
                                    [(kind, 'r', f'word/{kind}.xml', p(run('A law') + run('professor.')))], [[(kind, typ, 'r')]])
                    with zipfile.ZipFile(original) as before, zipfile.ZipFile(source, 'x') as after:
                        for item in before.infolist():
                            if item.filename != 'word/footnotes.xml':
                                after.writestr(item, before.read(item))
                    out = self.root / f'extract-{kind}-{typ}'
                    self.call(CLAUDE / 'extract_proof.py', source, out)
                    data = json.loads((out / 'proof.json').read_text())
                    record = data['headers_footers'][0]
                    _, output, answer = self.redline(source, [dict(id='one', location=record['location_label'],
                        find='lawprofessor', replacement='law professor', kind='change', note='Missing space.')])
                    self.assertEqual(answer['totals']['applied'], 1)
                    with zipfile.ZipFile(output) as z:
                        self.assertIn(b':ins ', z.read(f'word/{kind}.xml'))

    def test_codex_report_sorts_first_page_body_notes_then_running_stories(self):
        _, out, data, records = self.extract('codex', [
            ('header', 'd', 'word/header1.xml', p(run('Running header phrase.'))),
            ('footer', 'f', 'word/footer1.xml', p(run('First-page author phrase.')))],
            [[('header', 'default', 'd'), ('footer', 'first', 'f')]])
        note = dict(block_id='FN9', story='footnote', text='Synthetic footnote phrase.', heading_path=[])
        data['notes'] = [note]
        (out / 'document.json').write_text(json.dumps(data))
        (out / 'run-manifest.json').write_text(json.dumps(dict(draft_sha256=data['input_sha256'], counts={}, limitations=[])))
        (out / 'symbols.json').write_text(json.dumps(dict(display_note_to_block={'1': 'FN9'})))
        rows = []
        dispositions = []
        for i, block in enumerate(data['blocks'] + data['notes']):
            rows.append(dict(finding_id=str(i), location=dict(block_id=block['block_id'], char_start=0, char_end=4),
                             excerpt=block['text'], category='typo', impact='low'))
            # A fixed first-page finding must precede a confirmed body finding.
            dispositions.append(dict(finding_id=str(i), status='fixed' if block['story'] == 'footer' else 'confirmed'))
        (out / 'findings.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        (out / 'dispositions.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in dispositions))
        self.call(CODEX / 'build_report.py', out)
        text = (out / 'report.md').read_text()
        positions = [text.index(s) for s in ('First-page footer', '**Body', '**Note 1', 'Default header')]
        self.assertEqual(positions, sorted(positions))

    def test_duplicate_parts_use_one_location_labelled_body_comment(self):
        twins = [('footer', 'a', 'word/footer1.xml', p(run('A lawprofessor.'))),
                 ('footer', 'b', 'word/footer2.xml', p(run('A lawprofessor.')))]
        source, _, _, records = self.extract('claude', twins, [[('footer', 'first', 'a')], [('footer', 'first', 'b')]])
        edit = dict(id='one', location=records[0]['location_label'], find='lawprofessor', replacement='law professor', kind='change', note='Missing space.')
        _, output, _ = self.redline(source, [edit])
        with zipfile.ZipFile(output) as z:
            comments = ET.fromstring(z.read('word/comments.xml'))
            self.assertEqual(len(comments), 1)
            text = ''.join(comments.itertext())
            self.assertIn('section 1', text)
            self.assertIn('section 2', text)

    def test_codex_challenger_honors_story_and_block_locations(self):
        _, _, data, records = self.extract('codex', [('footer', 'f', 'word/footer1.xml', p(run('Repeated passage.')))],
                                           body=p(run('Repeated passage.')))
        script = '''import json, sys
sys.path.insert(0, sys.argv[1])
from ingest_challenger import candidate_blocks
d = json.loads(sys.argv[2]); b = d['blocks'][-1]
for label in (b['location_label'], b['block_id']):
    selected, error = candidate_blocks(label, d['blocks'], [], {})
    assert error is None, error
    assert [r['block_id'] for r in selected] == [b['block_id']], selected
selected, error = candidate_blocks('First-page footer, section 99, paragraph 1, segment 1', d['blocks'], [], {})
assert not selected and error
print('Header/footer challenger locations resolved without body fallback.')
'''
        result = subprocess.run([sys.executable, '-c', script, str(CODEX), json.dumps(data)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_codex_secondary_packets_keep_story_context_and_reject_forged_location(self):
        _, _, data, records = self.extract('codex', [('footer', 'f', 'word/footer1.xml', p(run('Author lawprofessor note.')))])
        script = '''import json, sys
sys.path.insert(0, sys.argv[1])
from make_recall_packets import render_material
from make_rejection_packets import source_context, render_packet
from common import validate_finding_location
from pathlib import Path
d=json.loads(sys.argv[2]); b=d['blocks'][-1]
row={'finding_id':'HFTEST', 'location':{'block_id':b['block_id'], 'char_start':0, 'char_end':6}, 'excerpt':'Author', 'category':'typo'}
validate_finding_location(row, {b['block_id']:b})
assert row['location']['occurrences'] == b['location']['occurrences']
context=source_context(row,{b['block_id']:b},{'footer':[b]})
assert context['located_block']['location'] == b['location']
related=dict(b, block_id='HF999999')
row['message']='Compare HF999999.'
linked=source_context(row,{b['block_id']:b, 'HF999999':related},{'footer':[b]})
assert linked['explicitly_referenced_blocks'] == [related]
recall='\\n'.join(render_material('Story', [b]))
packet=render_packet('RP1','HASH',[(row,context,True)],Path('/RUN/result.jsonl'),{})
assert b['location_label'] in recall and b['location_label'] in packet
row['location']['occurrences']=[{'section':99}]
try:
    validate_finding_location(row, {b['block_id']:b})
except ValueError:
    print('Recall/rejection context retained; forged section rejected.')
else:
    raise AssertionError('forged header/footer location accepted')
'''
        result = subprocess.run([sys.executable, '-c', script, str(CODEX), json.dumps(data)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_other_page_fields_nested_and_cross_paragraph_fields(self):
        for tree in ('claude', 'codex'):
            for code in ('NUMPAGES', 'SECTIONPAGES', 'PAGEREF target', 'STYLEREF title', 'DATE'):
                with self.subTest(tree=tree, code=code):
                    _, _, _, records = self.extract(tree, [('footer', 'f', 'word/footer1.xml', p(field(code, 'the the')))])
                    self.assertEqual(records, [])
            complex_field = ('<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
                             '<w:r><w:instrText>PA</w:instrText></w:r><w:r><w:instrText>GE</w:instrText></w:r>'
                             '<w:r><w:fldChar w:fldCharType="separate"/></w:r>')
            contents = p(run('Before ') + complex_field + field('REF nested', 'ignored'))
            contents += p(run('also ignored') + '<w:r><w:fldChar w:fldCharType="end"/></w:r>' + run(' After'))
            _, _, _, records = self.extract(tree, [('footer', 'f', 'word/footer1.xml', contents)])
            self.assertEqual([r['text'] for r in records], ['Before', 'After'])

    def test_codex_story_chunks_respect_max_even_after_a_short_story(self):
        _, out, _, records = self.extract('codex', [
            ('header', 'h', 'word/header1.xml', p(run('Short title'))),
            ('footer', 'f', 'word/footer1.xml', p(run('A longer author note with more than ten words needs its own oversized block chunk.')))])
        self.call(CODEX / 'lint_draft.py', out / 'document.json', '--findings', out / 'lint.jsonl', '--symbols', out / 'symbols.json')
        self.call(CODEX / 'make_chunks.py', out / 'document.json', '--run-dir', out, '--findings', out / 'lint.jsonl',
                  '--symbols', out / 'symbols.json', '--min-words', 5, '--target-words', 8, '--max-words', 10)
        chunks = [json.loads(s) for s in (out / 'chunks.jsonl').read_text().splitlines()]
        for chunk in chunks:
            self.assertTrue(chunk['within_configured_max'] or chunk['size_exception'] == 'single_block_exceeds_max', chunk)

    def test_codex_full_synthetic_lifecycle_requires_story_primary_and_recall_coverage(self):
        source = docx(self.root / 'lifecycle.docx', [('footer', 'f', 'word/footer1.xml', p(run('An author note with clean prose.')))])
        out = self.root / 'lifecycle-run'
        self.call(CODEX / 'init_run.py', source, '--run-dir', out, '--replacements')
        manifest = json.loads((out / 'run-manifest.json').read_text())
        def rows(name):
            return [json.loads(s) for s in (out / name).read_text().splitlines()]
        for chunk in rows('chunks.jsonl'):
            result = dict(chunk_id=chunk['chunk_id'], source_sha256=manifest['draft_sha256'], status='complete',
                          reviewed_block_ids=chunk['core_block_ids'], reviewed_note_ids=chunk['owned_note_ids'], findings=[])
            for suffix in ('', '-audit'):
                (out / 'agent-results' / (chunk['chunk_id'] + suffix + '.json')).write_text(json.dumps(result))
        for lane in manifest['required_lanes']:
            (out / 'lane-results' / (lane + '.json')).write_text(json.dumps(dict(lane=lane, source_sha256=manifest['draft_sha256'], status='complete', findings=[])))
        self.call(CODEX / 'merge_findings.py', out)
        self.call(CODEX / 'make_recall_packets.py', out)
        packets = rows('recall-packets.jsonl')
        self.assertEqual(len(packets), 2)
        self.assertTrue(packets[-1]['reviewed_block_ids'][0].startswith('HF'))
        for packet in packets:
            (out / 'recall-results' / (packet['packet_id'] + '.json')).write_text(json.dumps(dict(
                packet_id=packet['packet_id'], source_sha256=manifest['draft_sha256'], status='complete',
                reviewed_block_ids=packet['reviewed_block_ids'], reviewed_note_ids=packet['reviewed_note_ids'], findings=[])))
        self.call(CODEX / 'merge_findings.py', out)
        self.call(CODEX / 'build_report.py', out)
        self.call(CODEX / 'validate_run.py', out, '--require-ready')
        path = out / 'recall-results' / (packets[-1]['packet_id'] + '.json')
        result = json.loads(path.read_text())
        result['reviewed_block_ids'] = []
        path.write_text(json.dumps(result))
        failure = subprocess.run([sys.executable, str(CODEX / 'validate_run.py'), str(out), '--require-ready'], capture_output=True, text=True)
        self.assertNotEqual(failure.returncode, 0)
        self.assertIn('recall result block coverage mismatch', failure.stderr)

    def test_claude_extractor_isolated_cli_uses_only_bundled_helpers(self):
        source = docx(self.root / 'isolated.docx', [('footer', 'f', 'word/footer1.xml', p(run('Author prose.')))])
        out = self.root / 'isolated-output'
        result = subprocess.run([sys.executable, '-I', '-B', str(CLAUDE / 'extract_proof.py'), str(source), str(out)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((out / 'proof.json').read_text())['headers_footers'][0]['text'], 'Author prose.')


if __name__ == '__main__':
    unittest.main()
