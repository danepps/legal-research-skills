"""Synthetic workflow, lookup-join and multi-source sweep regressions."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import citation_ledger as cl
import prepare_units as pu
import zotero_sweep
import zotero_lookup
from local_lookup import run, summary

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]
SCRATCH=ROOT/'.codex-memo/amendment2-tests'
SCRATCH.mkdir(parents=True, exist_ok=True)   # a fresh checkout has no scratch folder
TITLE='Copper Lanterns and Silent Rivers'
CITE='Mina Vale, '+TITLE+', 12 Imaginary L. Rev. 41, 42 (2024).'
QUOTE='The copper lantern illuminates every silent river beneath the invented bridge.'

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(dir=SCRATCH))
    def test_04_key_collision_does_not_suppress_lookup(self):
        sources=[dict(key='collision',kind='book',cite='Mina Vale, Copper Lanterns in Northern Towns (2024).')]
        local={'sources':{'collision':dict(matched=True,origin='local',title='Copper Lanterns in Southern Towns')}}
        self.assertEqual(zotero_lookup.without_local_hits(sources,local),sources)
    def test_13_sweep_returns_all_sources(self):
        a=self.root/'a.txt';a.write_text(QUOTE)
        b=self.root/'b.txt';b.write_text(QUOTE)
        inst=[dict(note=1,kind='article',key='a',text=CITE),dict(note=1,kind='article',key='b',text=CITE.replace(TITLE,'The Amber Observatory'))]
        lookup={'sources':{'a':dict(matched=True,textPath=str(a),title=TITLE), 'b':dict(matched=True,textPath=str(b),title='The Amber Observatory')}}
        with patch.object(cl,'build_ledger',return_value={'instances':inst}),patch.object(pu,'build_units',return_value=[dict(id=7,footnote=1,quote=QUOTE)]):
            row=zotero_sweep.sweep({},lookup,[7])['results'][0]
        self.assertTrue(row['found']);self.assertTrue(row['attributionUnresolved'])
        self.assertEqual({h['key'] for h in row['matches']},{'a','b'});self.assertNotIn('key',row)
    def test_14_summary_has_no_absolute_candidate_paths(self):
        folder=self.root/'Sources';folder.mkdir()
        for n in ['a.txt','b.txt']:
            (folder/n).write_text(TITLE+' Reconsidered\nMina Vale\n'+n)
        result=summary(run([dict(key='s',kind='article',cite=CITE)],[folder],self.root/'cache'))
        self.assertNotIn(str(self.root),json.dumps(result));self.assertTrue(result['candidates'])

    @unittest.skipUnless(shutil.which('node'),'node not installed')
    def test_02_04_08_12_workflow_guards(self):
        h=dict(origin='local',title=TITLE,cite=CITE,au=['Mina Vale'],file='copy.txt',text='synthetic.txt',pages=1,
               versionNote='Accepted manuscript',version={'pinciteEligible':False,'kind':'working_paper','pinciteReason':'Pincite not judged: manuscript.'},confirm=['confirm: draft volume 12 vs local volume 9'])
        args=dict(skillsDir=str(HERE.parents[1]),extractPath='synthetic-extract.json',draftName='synthetic',footnoteCount=1,unitCount=1,unitNotes=[[0,1]],caseCites=[],supraProblems=[],formChecks={},ledger=[],secondaryCites=[dict(key='s',kind='article',cite=CITE)],deep=False,history=False,zotero=False,support=True,supportUnits=[dict(id=2,i=0,n=1,k='article',src=CITE,key='s',pin='42',scope='pincited',claim='Invented proposition.')],sourceHits={'s':h},sourceLookupPath='lookup.json',testQuote=QUOTE,testResolutions=[dict(id=0,footnote=1,quote=QUOTE,source=CITE,ledgerKey='s',kind='article',pincite='42')])
        def harness(scenario,changes=None):
            path=self.root/(scenario+'.json');path.write_text(json.dumps({**args,**(changes or {})}))
            p=subprocess.run([shutil.which('node'),str(HERE/'workflow_quote_harness.mjs'),str(HERE.parent/'cite-check.workflow.js'),str(path),scenario],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            return json.loads(p.stdout.splitlines()[-1])
        out=harness('local-pin')
        self.assertEqual(out['localIdentityChecks'][0]['status'],'confirmed')
        self.assertIn('confirm: draft volume',json.dumps(out['secondaryExistence']))
        self.assertEqual(out['counts']['verbatim'],1)
        report=out['reportPrompt']
        self.assertNotIn('WRONG_PAGE_CORRECTION',report)
        self.assertNotIn('PUBLISHED_SOURCE_LABEL',report)
        self.assertIn('not judged',report);self.assertIn('copy.txt',report)
        self.assertEqual(out['support'][0]['locator'],'Pincite not judged: manuscript.')
        mismatch=harness('local-rejected')
        self.assertEqual(mismatch['localIdentityChecks'][0]['status'],'rejected')
        self.assertTrue(any(l.startswith('exist-secondary') for l in mismatch['agents']))
        self.assertIn('selected Zotero',json.dumps(mismatch['prompts']))
        wrong=dict(h,title='Copper Lanterns and Different Rivers')
        for hit in [wrong,dict(wrong,origin='zotero',lib='test',item='one')]:
            out=harness('local-collision',{'sourceHits':{'s':hit},'zoteroLookupPath':'remote.json','zotero':True})
            self.assertTrue(any(l.startswith('exist-secondary') for l in out['agents']))
            self.assertNotIn('LOCAL COPY: copy.txt',json.dumps(out['prompts']))

if __name__=='__main__':unittest.main()
