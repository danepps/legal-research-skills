#!/usr/bin/env python3
"""Offline proposition-support extraction, pages, ledgers and completion gates."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile

from extract_cites import extract_document, footnote_anchors, W
from support_screen import signal_of, screen_clause, split_clauses, prose_clauses
from prepare_support_units import build_support_units
from support_validation import ARTIFACTS, DISPOSITIONS, support_counts, support_sentence, validate_support
from verify_quotes import read_pages
from findings_diff import key_of, diff
import test_case_review as fixtures

HERE = Path(__file__).resolve().parent


def rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def write(path, data):
    path.write_text(''.join(json.dumps(row)+'\n' for row in data))


class ExtractionTests(unittest.TestCase):
    def test_anchors(self):
        paragraphs = ['First sentence. Preceding sentence.',
                      'The rule applies.[[FN:1]] Next clause[[FN:2]] has an exception.',
                      'Another rule[[FN:3]] “quoted words here.”',
                      'Block text.[[FN:fn:9]]']
        a = footnote_anchors(paragraphs, {4})
        self.assertEqual(a['1']['sentence'], 'The rule applies.')
        self.assertEqual(a['1']['previous'], 'Preceding sentence.')
        self.assertEqual(a['1']['position'], 'sentence-end')
        self.assertFalse(a['1']['paragraph_end'])
        self.assertEqual(a['2']['clause'], 'Next clause')
        self.assertEqual(a['2']['previous'], 'The rule applies.')
        self.assertTrue(a['2']['paragraph_end'])
        self.assertEqual(a['3']['position'], 'mid-sentence')
        self.assertTrue(a['fn:9']['block_quote'])
        self.assertEqual(a['fn:9']['paragraph_number'], 4)

    def test_markdown_orphan(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'draft.md'
            path.write_text('Rule.[^1]\n\n[^1]: A source.\n[^2]: Orphan.\n')
            data = extract_document(path)
            self.assertIsNone(data['footnotes'][1]['anchor'])
            self.assertTrue(any('no body anchor' in w for w in data['warnings']))

    def test_ooxml_custom_and_indented(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'draft.docx'
            ns = W[1:-1]
            with zipfile.ZipFile(path, 'w') as z:
                z.writestr('word/document.xml', f'''<w:document xmlns:w="{ns}"><w:body>
                <w:p><w:r><w:t>Before.</w:t></w:r></w:p>
                <w:p><w:pPr><w:ind w:left="720"/></w:pPr><w:r><w:t>Quoted rule.</w:t></w:r><w:r><w:footnoteReference w:id="4" w:customMarkFollows="1"/><w:t>*</w:t></w:r></w:p>
                </w:body></w:document>''')
                z.writestr('word/footnotes.xml', f'''<w:footnotes xmlns:w="{ns}"><w:footnote w:id="4"><w:p><w:r><w:t>Author note.</w:t></w:r></w:p></w:footnote><w:footnote w:id="5"><w:p><w:r><w:t>Orphan.</w:t></w:r></w:p></w:footnote></w:footnotes>''')
            data = extract_document(path)
            note = data['footnotes'][0]
            self.assertIsNone(note['number'])
            self.assertTrue(note['anchor']['block_quote'])
            self.assertEqual(note['anchor']['previous'], 'Before.')
            self.assertIsNone(data['footnotes'][1]['anchor'])
            self.assertTrue(any('no body anchor' in w for w in data['warnings']))

    def test_signals(self):
        for printed, normalized in [('See, e.g.,', 'see, e.g.'), ('See e.g.,', 'see, e.g.'), ('See', 'see'),
            ('See also', 'see also'), ('See generally', 'see generally'), ('Cf.', 'cf.'), ('But see', 'but see'),
            ('But cf.', 'but cf.'), ('Compare', 'compare'), ('Accord', 'accord'), ('Contra', 'contra'), ('E.g.,', 'e.g.'), ('', '')]:
            with self.subTest(signal=printed):
                self.assertEqual(signal_of(printed+' 42 U.S.C. § 1983.'), normalized)
        self.assertEqual(len(split_clauses('See A (holding “one; two”). See, e.g., B; Cf. C.')), 3)
        self.assertEqual(len(split_clauses('A (noting “one. See two”); B “one. See two”.')), 2)

    def test_pins_and_parentheticals(self):
        examples = [
            ('See A v. B, 326 U.S. 310, 316 (66 S. Ct. 154) (1945).', 'case', '316'),
            ('Id. at 820–21.', 'id', '820–21'),
            ('Doe, Title, 110 Harv. L. Rev. 815, 820 (1997).', 'article', '820'),
            ('Doe, Finance 45 (2d ed. 2010).', 'book', '45'),
            ('Cf. 42 U.S.C. § 1983.', 'statute', '§ 1983'),
            ('Doe, supra note 1, ¶ 12.', 'supra', '¶ 12'),
            ('Doe, Finance (2010).', 'book', ''),
            ('Doe, supra note 1.', 'supra', ''),
        ]
        for text, kind, pin in examples:
            self.assertEqual(screen_clause(text, kind)['pincite'], pin, text)
        s = screen_clause('A, 1 U.S. 2, 3 (2000) (Thomas, J., concurring) (quoting X) (holding that the rule applies).', 'case')
        self.assertEqual(s['parenthetical'], 'holding that the rule applies')
        self.assertEqual(s['opinion_note'], 'Thomas, J., concurring')
        self.assertEqual(screen_clause('A, 1 U.S. 2 (2000) (quoting B, 2 U.S. 3, 4 (2000))', 'case')['pincite'], '')
        self.assertEqual(screen_clause('A, 326 U.S. 310 (66 S. Ct. 154) (1945).', 'case')['parenthetical'], '')
        self.assertEqual(prose_clauses('For the contrary view, see A, 1 U.S. 2 (2000).'), ['For the contrary view,'])


class PageTests(unittest.TestCase):
    def test_boundaries_and_ranges(self):
        text = '*431 First *432 Second *433 Third'
        self.assertIn('Second', read_pages(text, '431-32'))
        self.assertNotIn('Third', read_pages(text, '431-32'))
        self.assertIn('Second', read_pages('First\fSecond\fThird', '432', 431))
        self.assertIn('First', read_pages('First <<pg. 431>> Second <<pg. 432>>', '431', marker_follows=True))
        self.assertIn('First', read_pages('<<pg. 431>>First<<pg. 432>>Second', '431'))
        self.assertIn('TRUNCATED', read_pages('<<pg. 1>>'+'x'*13000, '1'))
        with self.assertRaisesRegex(ValueError, 'available page range: 431-433'):
            read_pages(text, '435')
        with self.assertRaisesRegex(ValueError, 'search the text'):
            read_pages('Unpaginated source', '1')

    def test_cli_errors(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td)/'source.txt'; path.write_text('*431 First *432 Second *433 Third')
            def call(page):
                return subprocess.run([sys.executable, str(HERE/'verify_quotes.py'), str(path), '--page', page], capture_output=True, text=True)
            self.assertEqual(call('431-32').returncode, 0)
            self.assertNotEqual(call('800').returncode, 0)
            self.assertIn('431-433', call('800').stderr)


def support_fixture():
    notes, units, verdicts, sources = [], [], [], []
    texts = ['See A, 1 U.S. 2, 3 (2000).', 'But see B, 2 U.S. 4, 5 (2001).', 'Id.',
             'Cf. C, 3 U.S. 6, 7 (2002).', 'Author, supra note 1.', 'Author, Book (2000).',
             'D, 4 U.S. 8, 9 (2003).', '(quoting E, 5 U.S. 10 (2004))', 'X, supra note 99.']
    for index, text in enumerate(texts, 1):
        anchor = footnote_anchors([f'The rule applies.[[FN:{index}]]'])[str(index)]
        notes.append({'number': index, 'text': text, 'anchor': anchor})
        u = {'unit_id': f'U{index}', 'source_id': f'S{index}', 'source_type': 'case', 'footnote_number': index,
             'draft_citation_text': text, 'resolved_source_label': text, **{k:v for k,v in screen_clause(text).items() if k in {'signal','pincite','parenthetical','opinion_note'}}}
        units.append(u)
        sources.append({'source_id': u['source_id'], 'status': 'retrieved', 'verification_basis': 'primary_full_text'})
        verdicts.append({'verdict_id': f'V{index}', 'unit_id': u['unit_id'], 'support_read': False})
    units[2].update(xref_status='resolved', antecedent_unit_id='U2', source_id='S2')
    units[4]['xref_status'] = 'resolved'
    units[5]['source_type'] = 'book'
    units[7]['nested'] = True
    units[8]['xref_status'] = 'unresolved'
    verdicts[8]['status'] = 'unverified'
    extraction = {'footnotes': notes}
    quote_checks = [{'unit_id': 'U7', 'prepared_unit_id': 'P1'}]
    rows_ = build_support_units(extraction, units, quote_checks)
    for index, result in enumerate(('supported', 'not_supported', 'overstated', 'supported_qualified')):
        v = verdicts[index]
        status, category, severity = DISPOSITIONS[result]
        v.update(status=status, category=category, severity=severity, support_read=True, verification_basis='primary_full_text',
                 support={'verdict': result, 'signal': units[index]['signal'], 'claim': 'The rule applies.', 'claim_basis': 'anchor.sentence',
                          'locator_read': 'p. '+rows_[index]['pincite'], 'source_passage': 'The rule applies on these facts.', 'posture': 'holding',
                          'reason': 'Test fixture reasoning.', 'source_search': {'terms': ['rule'], 'result': 'Read all hits.'}})
    audits = [{'verdict_id': 'V2', 'audit_status': 'confirmed', 'initial_support_verdict': 'not_supported', 'reviewer': 'independent reviewer',
               'independent_rederivation': True, 'page_reread': '5', 'evidence': {k: 'Checked against complete unit and source page.' for k in ARTIFACTS}}]
    manifest = {'schema_version': 7, 'support_pass': {'enabled': True, 'scope': 'pincited'}, 'counts': {}}
    manifest['counts']['support'] = support_counts(rows_, verdicts, audits)
    report = 'Existence-only: fixture\n'+support_sentence(manifest['counts']['support'])+'\n## Needs your attention\nNone\n## Proposition support\nConfirm possible overstatement.\n'
    return manifest, extraction, units, quote_checks, rows_, verdicts, audits, sources, report


class SupportTests(unittest.TestCase):
    def validate(self, args):
        errors = []; validate_support(*args, errors); return errors

    def test_units_and_all_scope(self):
        args = support_fixture(); support = args[4]
        self.assertEqual([r['unit_id'] for r in support], ['U1','U2','U3','U4','U5','U6'])
        self.assertEqual(support[2]['pincite'], '5')
        self.assertEqual(support[2]['pincite_basis'], 'inherited')
        self.assertEqual(support[4]['pincite'], '')
        self.assertEqual(support[4]['scope'], 'whole-work')
        self.assertEqual(sum(r.get('unread_reason') == 'out_of_scope' for r in support), 2)
        self.assertFalse(any(r.get('unread_reason') for r in build_support_units(args[1], args[2], args[3], 'all')))
        self.assertEqual(self.validate(args), [])

    def test_id_chain_own_pin_and_supra_stop(self):
        args = support_fixture(); units = args[2]
        units[3].update(draft_citation_text='Id.', pincite='', xref_status='resolved', antecedent_unit_id='U3', source_id='S2')
        self.assertEqual(build_support_units(args[1], units, args[3])[3]['pincite'], '5')
        units[2]['pincite'] = '10'
        self.assertEqual(build_support_units(args[1], units, args[3])[3]['pincite'], '10')
        units[3]['antecedent_unit_id'] = 'U5'
        self.assertEqual(build_support_units(args[1], units, args[3])[3]['pincite'], '')
        units[3]['source_type'] = 'statute'; units[3]['draft_citation_text'] = '42 U.S.C. § 1983'
        self.assertEqual(build_support_units(args[1], units, args[3])[3]['scope'], 'pincited')

    def test_gates(self):
        for mutation, message in [
            (lambda a: a[5][2].update(severity='medium'), 'invalid disposition'),
            (lambda a: a[6].clear(), 'independent verifier audit'),
            (lambda a: a[5][0].pop('support'), 'lacks support verdict'),
            (lambda a: a[4].pop(0), 'exactly one row'),
            (lambda a: a[5][0]['support'].update(claim='Invented proposition'), 'not verbatim'),
            (lambda a: a[5][0]['support'].update(signal='but see'), 'signal mismatch'),
            (lambda a: a[5][0]['support'].update(source_passage=''), 'source_passage'),
            (lambda a: a[0]['counts']['support'].update(read=999), 'does not reconcile'),
            (lambda a: a[6][0]['evidence'].pop('posture'), 'six artifact classes'),
        ]:
            a = support_fixture(); mutation(a)
            self.assertTrue(any(message in e for e in self.validate(a)), message)
        a = list(support_fixture()); a[-1] = a[-1].replace('Support pass:', 'Wrong:')
        self.assertTrue(any('accurate support summary' in e for e in self.validate(a)))
        a = list(support_fixture()); a[-1] = a[-1].replace('None\n', 'U3: The rule applies.\n')
        self.assertTrue(any('Needs your attention' in e for e in self.validate(a)))

    def test_unread_and_unverifiable(self):
        a = list(support_fixture()); a[4][0]['unread_reason'] = 'budget'; a[5][0].pop('support'); a[5][0]['support_read'] = False
        a[0]['completion_target'] = 'complete_with_limits'; a[0]['counts']['support'] = support_counts(a[4], a[5], a[6])
        a[-1] = 'Existence-only: fixture\n'+support_sentence(a[0]['counts']['support'])+'\n## Proposition support\nU1 budget\n'
        self.assertEqual(self.validate(a), [])
        a = list(support_fixture()); a[5][0].update(status='unverified', support_read=False, unlock_path='Supply source PDF.')
        a[5][0]['support'].update(verdict='unverifiable'); a[0]['counts']['support'] = support_counts(a[4], a[5], a[6])
        a[-1] = 'Existence-only: fixture\n'+support_sentence(a[0]['counts']['support'])+'\n## Proposition support\n'
        self.assertEqual(self.validate(a), [])
        self.assertEqual(a[0]['counts']['support']['read'], 3)

    def test_audit_retractions_and_revisions(self):
        for result, status in [('supported', 'retracted'), ('overstated', 'revised'), ('supported_qualified', 'revised')]:
            a = list(support_fixture())
            v = a[5][1]
            v['status'], v['category'], v['severity'] = DISPOSITIONS[result]
            v['support']['verdict'] = result
            a[6][0]['audit_status'] = status
            a[0]['counts']['support'] = support_counts(a[4], a[5], a[6])
            a[-1] = 'Existence-only: fixture\n'+support_sentence(a[0]['counts']['support'])+'\n## Proposition support\n'
            self.assertEqual(self.validate(a), [])
            self.assertEqual(a[0]['counts']['support']['audits_retracted'], int(status == 'retracted'))

    def test_diff(self):
        item = {'kind':'support', 'category':'support_overstated', 'resolved_source_label':'A source', 'claim':'A claim', 'verdict':'overstated', 'footnote':1}
        self.assertEqual(key_of(item), key_of(dict(item, footnote=99)))
        self.assertNotEqual(key_of(item), key_of(dict(item, category='support_mismatch')))
        self.assertNotEqual(key_of(item), key_of(dict(item, verdict='contradicted')))
        before = {'coverage_complete':True, 'items':[item], 'support_pass':{'enabled':True}}
        after = {'coverage_complete':True, 'items':[], 'support_pass':{'enabled':False}}
        self.assertEqual(len(diff(before, after)['not_rechecked']), 1)

    def test_initialization(self):
        with tempfile.TemporaryDirectory() as td:
            draft = Path(td)/'d.md'; draft.write_text('Rule.[^1]\n\n[^1]: See A, 1 U.S. 2, 3 (2000).\n')
            for enabled in (False, True):
                run = Path(td)/str(enabled)
                p = subprocess.run([sys.executable, str(HERE/'init_run.py'), str(draft), '--run-dir', str(run), *(['--support'] if enabled else [])], capture_output=True, text=True)
                self.assertEqual(p.returncode, 0, p.stderr)
                m = json.loads((run/'run-manifest.json').read_text())
                self.assertEqual(m['schema_version'], 7 if enabled else 6)
                self.assertEqual(m['support_pass']['enabled'], enabled)
                if enabled: self.assertEqual(rows(run/'citation-screening.jsonl')[0]['signal'], 'see')

    def test_synthetic_draft_end_to_end(self):
        # A fourth pincited cite is needed for four read verdicts: bare supra,
        # like a whole-work cite, is out of scope under the binding pin rule.
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); run = root/'run'; draft = root/'draft.md'
            fixture = support_fixture()
            units = fixture[2][:7]; verdicts = fixture[5][:7]; audits = fixture[6]
            quotation = 'The source supplies these eight words for quotation matching.'
            body = [f'The rule applies.[^{i}]' for i in range(1, 7)] + [f'“{quotation}”[^{7}]']
            draft.write_text('\n\n'.join(body + [f"[^{i}]: {u['draft_citation_text']}" for i,u in enumerate(units, 1)]))
            def command(script, *args):
                return subprocess.run([sys.executable, str(HERE/script), *map(str,args)], capture_output=True, text=True)
            result = command('init_run.py', draft, '--run-dir', run, '--support')
            self.assertEqual(result.returncode, 0, result.stderr)
            extraction = json.loads((run/'extraction.json').read_text())
            for index, u in enumerate(units):
                u.update(full_footnote=extraction['footnotes'][index]['text'], draft_find_string=u['draft_citation_text'], caption_in_draft='footnote')
                if index == 2: u['resolved_source_label'] = units[1]['resolved_source_label']
                v = verdicts[index]
                v.update(identity_confirmed=True, evidence='Cached source fixture reviewed.', suggested_action='Review the stated finding.', draft_find_string=u['draft_citation_text'])
                if index >= 4:
                    v.update(status='verified', category='verified_quote' if index == 6 else 'verified_identity', severity='info', verification_basis='primary_full_text')
                if u['pincite'] and index != 6:
                    v['pincite_verification'] = {'confirmed':True, 'pincite':u['pincite'], 'pagination_convention':'printed_page', 'evidence_location':'cached fixture', 'evidence':'Printed pin inspected.'}
            verdicts[0].pop('pincite_verification')
            verdicts[0]['support']['locator_read'] = 'p. 4 (cited 3); nearby passage supports the claim.'
            units[6]['prepared_unit_ids'] = ['P1']
            write(run/'citation-units.jsonl', units)
            source_map = {u['source_id']:{'source_id':u['source_id'], 'source_type':u['source_type'], 'canonical_citation':u['resolved_source_label'], 'status':'retrieved', 'verification_basis':'primary_full_text'} for u in units}
            write(run/'source-ledger.jsonl', list(source_map.values()))
            source = run/'cached.txt'; source.write_text('<<pg. 9>>'+quotation)
            quote_items = run/'quote-items.json'
            quote_items.write_text(json.dumps([{'unit_id':'U7','source_id':'S7','prepared_unit_id':'P1','quote':quotation,'pincite':'9'}]))
            result = command('verify_quotes.py', source, '--json', quote_items, '--output', run/'quote-checks.jsonl')
            self.assertEqual(result.returncode, 0, result.stderr)
            write(run/'verdicts.jsonl', verdicts); write(run/'verifier-audit.jsonl', audits)
            write(run/'footnote-coverage.jsonl', [{'footnote_number':i,'status':'reviewed','unit_ids':[u['unit_id']]} for i,u in enumerate(units,1)])
            write(run/'body-coverage.jsonl', [{'paragraph_number':i,'status':'no_citations','unit_ids':[],'reason':'Citations are in notes.'} for i in range(1,8)])
            reviews = []
            for source_id, source_row in source_map.items():
                if source_row['source_type'] != 'case': continue
                review = {'source_id':source_id,'findings':[]}
                for name, routes_ in [('history',['docket','later_opinions']),('treatment',['graph','name'])]:
                    review[name] = {'status':'checked','routes':[{'route':route,'status':'checked','query':'fixture query','checked_at':'2026-10-25','evidence':'No hits in fixture.'} for route in routes_]}
                reviews.append(review)
            write(run/'case-review.jsonl', reviews)
            manifest = json.loads((run/'run-manifest.json').read_text())
            manifest.update(status='ready_for_validation',completion_target='complete')
            manifest['counts'].update(quote_checks=1, verified=5, partial=1, mismatch=1, unverified=0, existence_only=3)
            (run/'run-manifest.json').write_text(json.dumps(manifest))
            result = command('prepare_support_units.py', run, '--refresh-counts')
            self.assertEqual(result.returncode, 0, result.stderr)
            support = rows(run/'support-units.jsonl')
            self.assertEqual(len(support), 6)
            self.assertEqual(sum(r.get('unread_reason') == 'out_of_scope' for r in support), 2)
            report = '# Cite Check\nCreated by: Codex\nModel: fixture\nGenerated: fixture\nElapsed: fixture\nTokens: unavailable\n\n'
            report += 'Existence-only: 3 of 7 citation instances were confirmed to exist but not read for proposition support.\n'+result.stdout.strip()+'\n'
            report += '## Needs your attention\nNone\n## Subsequent history & treatment\n'
            report += '\n'.join(f"Case review {r['source_id']}: history=checked; treatment=checked." for r in reviews)
            report += '\n## Proposition support\nNot supported (fix or re-cite): U2.\nConfirm: possible overstatement: U3.\nQualified support (posture): U4.\n## Couldn\'t check\nNone\n'
            (run/'report.md').write_text(report)
            def validate():
                result = command('findings_diff.py','--run-dir',run,'--output',run/'findings.json')
                self.assertEqual(result.returncode,0,result.stderr)
                return command('validate_run.py',run,'--require-ready')
            result = validate(); self.assertEqual(result.returncode,0,result.stderr)
            verdicts[2]['severity'] = 'medium'; write(run/'verdicts.jsonl',verdicts)
            self.assertIn('invalid disposition',validate().stderr)
            verdicts[2]['severity'] = 'low'; write(run/'verdicts.jsonl',verdicts)
            write(run/'verifier-audit.jsonl',[])
            self.assertIn('required verifier audit',validate().stderr)

    def test_real_completion_gate_and_v6_compatibility(self):
        base = fixtures.ReviewTests('test_ready_and_postcompletion_findings_are_stable'); base.setUp()
        self.addCleanup(base.doCleanups)
        self.assertEqual(base.validate().returncode, 0)
        units = rows(base.run/'citation-units.jsonl')
        units[0].update(signal='', pincite='', parenthetical='', opinion_note='')
        write(base.run/'citation-units.jsonl', units)
        extraction = json.loads((base.run/'extraction.json').read_text())
        support = build_support_units(extraction, units, [], 'all')
        write(base.run/'support-units.jsonl', support)
        source = rows(base.run/'source-ledger.jsonl')[0]
        source.update(status='retrieved', verification_basis='primary_full_text')
        write(base.run/'source-ledger.jsonl', [source])
        base.manifest.update(schema_version=7, support_pass={'enabled':True, 'scope':'all'})
        base.verdict.update(status='partial', severity='low', category='support_overstated', support_read=True, verification_basis='primary_full_text', draft_find_string=units[0]['draft_citation_text'], support={'verdict':'overstated', 'signal':'', 'claim':'A proposition.', 'claim_basis':'anchor.sentence', 'locator_read':'whole work', 'source_passage':'A narrower rule.', 'posture':'holding', 'reason':'Confirm the broader scope.'})
        base.manifest['counts'].update(verified=0, partial=1, existence_only=0)
        base.manifest['counts']['support'] = support_counts(support, [base.verdict], [])
        base.report = base.report.replace('Existence-only: 1', 'Existence-only: 0').replace('proposition support.\n', 'proposition support.\n'+support_sentence(base.manifest['counts']['support'])+'\n')+'\n## Proposition support\nConfirm: possible overstatement.\n'
        result = base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        base.verdict['severity'] = 'medium'
        self.assertIn('invalid disposition', base.validate().stderr)
        base.verdict.update(status='mismatch', category='support_mismatch', severity='medium')
        base.verdict['support'].update(verdict='not_supported', source_search={'terms':['rule'], 'result':'No support.'})
        self.assertIn('audit', base.validate().stderr)
        base.manifest['counts'].update(partial=0, mismatch=1)
        audit = {'verdict_id':'V1', 'audit_status':'confirmed', 'initial_support_verdict':'not_supported',
                 'reviewer':'independent reviewer', 'independent_rederivation':True, 'page_reread':'whole work',
                 'evidence':{k:'Checked complete draft context and reread source.' for k in ARTIFACTS}}
        write(base.run/'verifier-audit.jsonl', [audit])
        old_sentence = support_sentence(base.manifest['counts']['support'])
        base.manifest['counts']['support'] = support_counts(support, [base.verdict], [audit])
        base.report = base.report.replace(old_sentence, support_sentence(base.manifest['counts']['support']))
        result = base.validate()
        self.assertEqual(result.returncode, 0, result.stderr)
        write(base.run/'verifier-audit.jsonl', [])
        self.assertIn('required verifier audit', base.validate().stderr)


if __name__ == '__main__':
    unittest.main()
