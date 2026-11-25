"""Synthetic Codex run checks for proposed identity and separate pin outcomes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from local_lookup import apply_lookup, build_lookup, disclosure_lines, validate_local_sources
from local_sources import digest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[2]
SCRATCH=ROOT/'.codex-memo/amendment2-tests'; SCRATCH.mkdir(parents=True,exist_ok=True)
CITE='Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41, 42 (2024).'
QUOTE='The copper lantern illuminates every silent river beneath the invented bridge.'

class RunTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(dir=SCRATCH));self.folder=self.root/'Sources';self.folder.mkdir()
        self.run=self.root/'run';self.run.mkdir()
        (self.folder/'copy.txt').write_text('Copper Lanterns and Silent Rivers\nMina Vale\nAccepted manuscript\n'+QUOTE+'\n1')
        self.sources=[dict(source_id='S1',source_type='article',canonical_citation=CITE)]
        self.manifest={}
        self.units=[dict(unit_id='U1',source_id='S1',pincite='42')]
        self.lookup=build_lookup(self.sources,[self.folder],self.run/'cached-sources/local')
        apply_lookup(self.run,self.manifest,self.sources,self.lookup)
        self.report='\n'.join(disclosure_lines(self.lookup))
    def test_02_identity_review_required_and_rejection_falls_through(self):
        v=[dict(unit_id='U1',status='partial',category='verified_quote')]
        self.assertTrue(any('identity' in e for e in validate_local_sources(self.run,self.manifest,self.sources,self.units,v,self.report)))
        result=subprocess.run([sys.executable,str(HERE/'local_lookup.py'),str(self.run),'--review-source','S1','--identity-status','rejected','--identity-locator','first content page','--identity-reason','Synthetic wrong edition'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        source=json.loads((self.run/'source-ledger.jsonl').read_text())
        self.assertEqual(source['local_identity_review']['status'],'rejected')
        self.assertEqual(source['status'],'unavailable');self.assertNotIn('source_path',source)
        self.assertEqual(validate_local_sources(self.run,self.manifest,[source],self.units,[],self.report),[])
    def test_09_verified_quote_with_explicit_pin_not_judged(self):
        self.sources[0]['local_identity_review']=dict(status='confirmed',locator='first content page',reason='Synthetic title and byline inspected.')
        verdict=dict(unit_id='U1',status='verified',category='verified_quote',pincite_verification=dict(status='not_judged',confirmed=False,reason='Manuscript pagination.'))
        self.assertEqual(validate_local_sources(self.run,self.manifest,self.sources,self.units,[verdict],self.report),[])
        for field,value in [('confirmed',True),('corrected_page','8'),('reason','')]:
            bad={**verdict,'pincite_verification':{**verdict['pincite_verification'],field:value}}
            self.assertTrue(validate_local_sources(self.run,self.manifest,self.sources,self.units,[bad],self.report))
    def test_14_candidate_and_missing_folder_disclosures_are_relative(self):
        for name in ['b.txt','c.txt']:
            (self.folder/name).write_text('Copper Lanterns and Silent Rivers Reconsidered\nMina Vale\n'+name)
        result=build_lookup(self.sources,[self.folder,self.root/'missing'],self.run/'cache')
        self.assertNotIn(str(self.root),'\n'.join(disclosure_lines(result)))
    def test_15_only_matched_copy_is_fully_extracted(self):
        (self.folder/'unrelated.txt').write_text('Other Work\nNora Moss\f'+('unrelated text '*100)+'\fEND')
        lookup=build_lookup(self.sources,[self.folder],self.run/'cache')
        self.assertEqual(len(list((self.run/'cache').glob('*-full.txt'))),1)
        self.assertTrue(all(not f['fullText'] for f in lookup['files']))
    def test_16_cli_source_folder_can_contain_run(self):
        draft=self.root/'draft.md';draft.write_text('Synthetic draft')
        self.manifest['draft_path']=str(draft)
        (self.run/'run-manifest.json').write_text(json.dumps(self.manifest))
        result=subprocess.run([sys.executable,str(HERE/'local_lookup.py'),str(self.run),'--folder',str(self.root),'--apply'],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        files=json.loads((self.run/'local-lookup.json').read_text())['files']
        self.assertEqual([f['fileName'] for f in files],['copy.txt'])

    def test_17_tilde_cli_preview_and_initializer(self):
        draft=self.root/'draft.md';draft.write_text('Synthetic.[^1]\n\n[^1]: '+CITE)
        env={**os.environ,'HOME':str(self.root)}
        preview=self.root/'options.json'
        p=subprocess.run([sys.executable,str(HERE/'prepare_run_options.py'),'~/draft.md','--project','~','--defaults','--output',str(preview)],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        p=subprocess.run([sys.executable,str(HERE/'init_run.py'),'~/draft.md','--run-dir',str(self.root/'tilde-run'),'--options',str(preview)],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    def test_09_full_validator_accepts_quote_without_certifying_pin(self):
        import findings_diff
        def command(name,*args):
            p=subprocess.run([sys.executable,str(HERE/name),*map(str,args)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stdout+p.stderr)
            return p
        draft=self.root/'quoted.md';draft.write_text('The author writes “'+QUOTE+'”[^1]\n\n[^1]: '+CITE)
        run=self.root/'ready';command('init_run.py',draft,'--run-dir',run)
        manifest=json.loads((run/'run-manifest.json').read_text())
        prepared=json.loads((run/'prepared-units.jsonl').read_text())
        sources=[dict(source_id='S1',source_type='article',canonical_citation=CITE)]
        lookup=build_lookup(sources,[self.folder],run/'cached-sources/local')
        apply_lookup(run,manifest,sources,lookup)
        command('local_lookup.py',run,'--review-source','S1','--identity-status','confirmed','--identity-locator','file page 1','--identity-reason','Synthetic work and edition inspected')
        def rows(name,items): (run/(name+'.jsonl')).write_text(''.join(json.dumps(x)+'\n' for x in items))
        unit=dict(unit_id='U1',source_id='S1',source_type='article',footnote_number=1,full_footnote=CITE,draft_citation_text=CITE,resolved_source_label=CITE,draft_find_string='Copper Lanterns',caption_in_draft='footnote',pincite='42')
        rows('citation-units',[unit]); rows('footnote-coverage',[dict(footnote_number=1,status='reviewed',unit_ids=['U1'])])
        rows('body-coverage',[dict(paragraph_number=1,status='no_citations',unit_ids=[],reason='Citation inventoried in note 1.')])
        verdict=dict(verdict_id='V1',unit_id='U1',status='verified',severity='info',category='verified_quote',verification_basis='local_library_full_text',evidence='Synthetic deterministic quotation match.',suggested_action='none',identity_confirmed=True,support_read=False,pincite_verification=dict(status='not_judged',confirmed=False,reason='Manuscript pagination.'))
        rows('verdicts',[verdict]); rows('case-identity-checks',[])
        items=run/'items.json';items.write_text(json.dumps([dict(prepared_unit_id=prepared['prepared_unit_id'],unit_id='U1',source_id='S1',quote=prepared['quote'])]))
        command('verify_quotes.py',sources[0]['source_path'],'--json',items,'--output',run/'quote-checks.jsonl')
        manifest.update(status='ready_for_validation',completion_target='complete_with_limits')
        manifest['counts'].update(quote_checks=1,verified=1,partial=0,mismatch=0,unverified=0,existence_only=1)
        (run/'run-manifest.json').write_text(json.dumps(manifest))
        command('cache_recovery.py',run)
        recovery=json.loads((run/'cache-recovery.json').read_text())
        report="# Cite Check\nCreated by: Codex\nModel: synthetic-test\nGenerated: fixture\nElapsed: fixture\nTokens: unavailable\n\nExistence-only: 1 of 1 citation instances were confirmed to exist but not read for proposition support.\n\n## Needs your attention\nNone.\n\n## Subsequent history & treatment\nNo cases.\n\n## Couldn't check\nU1: Pincite not judged: Manuscript pagination. Obtain the published copy for pins.\n"
        report+='\n'.join(disclosure_lines(lookup))+'\n'+(run/'cache-recovery.md').read_text()
        (run/'report.md').write_text(report)
        (run/'findings.json').write_text(json.dumps(findings_diff.snapshot(run)))
        command('validate_run.py',run,'--require-ready')
        verdict['pincite_verification']['confirmed']=True;rows('verdicts',[verdict])
        bad=subprocess.run([sys.executable,str(HERE/'validate_run.py'),str(run),'--require-ready'],capture_output=True,text=True)
        self.assertNotEqual(bad.returncode,0);self.assertIn('printed pincites',bad.stderr)

if __name__=='__main__':unittest.main()
