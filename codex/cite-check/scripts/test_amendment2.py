"""Amendment 2 regressions: invented works, bounded offline fixtures only."""
import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import local_sources as ls
import source_options as so

ROOT = next(p for p in Path(__file__).resolve().parents if (p / 'run_tests.py').is_file())
SCRATCH = ROOT / '.codex-memo/amendment2-tests'
TITLE = 'Copper Lanterns and Silent Rivers'
FIELDS = dict(title=TITLE, authors='Mina Vale', lastNames=['Vale'], journal='Imaginary L. Rev.', volume='12', first='41', year='2024', pattern='article')
PUBLISHED = 'Imaginary Law Review\nVolume 12 (2024)\n'+TITLE+'\nMina Vale\nAbstract\nInvented body text.\n41\fImaginary Law Review\nInvented continuation.\n42\f'
LIBS = [dict(id='one', name='Copper Library', status='available'), dict(id='two', name='Amber Library', status='available')]

def entry(text):
    return dict(readable=True, firstPages=text.split('\f')[:3], fileSha256=__import__('hashlib').sha256(text.encode()).hexdigest(), fileName='copy.txt')

class Amendment2Tests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=SCRATCH))
        self.folder=self.root/'Sources'; self.folder.mkdir()
        self.cache=self.root/'run/cache'
        self.draft=self.root/'draft.md'; self.draft.write_text('Synthetic.')
        p=patch('source_options.default_file', return_value=self.root/'no-default'); p.start(); self.addCleanup(p.stop)
    def test_01_own_title_and_byline(self):
        bad = ['Book Review\n'+TITLE+'\nMina Vale\nReviewed by Nora Moss',
               'Response to\n'+TITLE+'\nMina Vale',
               'Reading list\n'+TITLE+'\nMina Vale',
               'Another Heading\nNora Moss\nReferences\n'+TITLE+'\nMina Vale\n12 Imaginary Law Review 41 (2024)',
               TITLE+'\nMina Vale argues that copper matters.',
               TITLE+'\nReconsidered\nMina Vale',
               'Other Work\nNora Moss\f'+TITLE+'\nMina Vale',
               TITLE+'\nMina Vale\nReviewed by Nora Moss']
        for text in bad:
            with self.subTest(text=text): self.assertFalse(ls.identity(FIELDS,entry(text))['strong'])
        self.assertTrue(ls.identity(FIELDS,entry(PUBLISHED))['strong'])
        self.assertTrue(ls.identity(FIELDS,entry('HeinOnline\nDownloaded from HeinOnline\f'+PUBLISHED))['strong'])
    def test_03_conflicting_book_edition_and_year(self):
        fields=dict(FIELDS, journal='', volume='', first='', pattern='book', edition='2')
        for label in ['Third edition\nCopyright 2024', 'Second edition\nCopyright 2023']:
            chosen, candidates=ls.match(fields,[entry(TITLE+'\nMina Vale\n'+label)])
            self.assertIsNone(chosen); self.assertTrue(candidates); self.assertTrue(candidates[0]['identity'].get('reasons'))
        v=ls.version_evidence(fields, entry(TITLE+'\nMina Vale\n1'))
        self.assertFalse(v['pinciteEligible'])
    def test_05_numbered_manuscript_is_not_published(self):
        for pattern in ['book','internet','other']:
            v=ls.version_evidence(dict(FIELDS,journal='',pattern=pattern),entry(TITLE+'\nMina Vale\nInvented body\n1'))
            self.assertFalse(v['pinciteEligible'])
    def test_06_manuscript_markers_and_citation_numbers(self):
        for marker in ['Accepted manuscript', 'To be published in Imaginary Law Review', "Author’s version", 'This is a post-peer-review, pre-copyedit version']:
            v=ls.version_evidence(FIELDS,entry(PUBLISHED.replace('Abstract',marker+'\nAbstract')))
            self.assertFalse(v['pinciteEligible'],marker)
        v=ls.version_evidence(FIELDS,entry(PUBLISHED.replace('\n41','\n12 Imaginary Law Review 41')))
        self.assertFalse(v['pinciteEligible'])
    def test_07_body_citation_and_title_are_not_version_statements(self):
        self.assertTrue(ls.version_evidence(FIELDS,entry(PUBLISHED.replace('Invented body text.', '1. See Nora Moss, Other Work (forthcoming).')))['pinciteEligible'])
        fields=dict(FIELDS,title='Draft Rules and Silent Rivers')
        self.assertTrue(ls.version_evidence(fields,entry(PUBLISHED.replace(TITLE,fields['title'])))['pinciteEligible'])
    def test_10_identical_bytes_are_one_copy(self):
        one=entry(PUBLISHED); two=dict(one,fileName='other.txt')
        chosen,candidates=ls.match(FIELDS,[one,two])
        self.assertIsNotNone(chosen); self.assertEqual(len(candidates),1)
    def test_11_unique_published_candidate_wins(self):
        draft=entry(PUBLISHED.replace('Abstract','Working paper\nAbstract'))
        published=entry(PUBLISHED)
        chosen,candidates=ls.match(FIELDS,[draft,published])
        self.assertIsNotNone(chosen); self.assertEqual(chosen['fileSha256'],published['fileSha256']); self.assertEqual(len(candidates),2)
        other=entry(PUBLISHED.replace('Invented continuation.','Different continuation.'))
        self.assertIsNone(ls.match(FIELDS,[published,other])[0])
    def test_15_preview_limits_full_extraction_and_memory_failure(self):
        path=self.folder/'copy.txt'; path.write_text(PUBLISHED+'\f'+'tail '*1000)
        with patch.object(ls,'MAX_FILE_BYTES',64,create=True):
            self.assertFalse(ls.index_file(path,self.cache)['readable'])
        with patch.object(ls,'digest',side_effect=MemoryError):
            self.assertFalse(ls.index_file(path,self.cache)['readable'])
        preview=ls.index_file(path,self.cache)
        self.assertTrue(preview['readable']); self.assertFalse(preview.get('fullText',True))
        self.assertNotIn('tail',Path(preview['textPath']).read_text())
        with patch.object(ls,'MAX_TEXT_BYTES',64,create=True):
            self.assertFalse(ls.index_file(path,self.root/'small-cache',full=True)['readable'])
        with patch.object(ls,'MAX_PAGES',1,create=True):
            self.assertFalse(ls.index_file(path,self.root/'page-cache',full=True)['readable'])
    def test_15_file_count_and_progress(self):
        for i in range(4): (self.folder/f'{i}.txt').write_text(PUBLISHED)
        stderr=io.StringIO()
        with patch.object(ls,'MAX_FILES',2,create=True),contextlib.redirect_stderr(stderr):
            rows,errors=ls.index_folders([self.folder],self.cache)
        self.assertEqual(len(rows),2); self.assertTrue(errors); self.assertIn('limit',str(errors)); self.assertTrue(stderr.getvalue())
    def test_16_hidden_run_and_cache_are_skipped(self):
        run=self.folder/'run'; run.mkdir(); (run/'wrong.txt').write_text(PUBLISHED)
        hidden=self.folder/'.hidden'; hidden.mkdir(); (hidden/'wrong.txt').write_text(PUBLISHED)
        (self.folder/'right.txt').write_text(PUBLISHED)
        rows,errors=ls.index_folders([self.folder],run/'cache',exclude=[run])
        self.assertEqual([r['fileName'] for r in rows],['right.txt'])
    def test_17_tilde_paths(self):
        with patch('pathlib.Path.home',return_value=self.root),patch.dict(os.environ,{'HOME':str(self.root)}):
            self.assertEqual(so.discover_folders('~/draft.md',project='~')[0],[self.folder])
            self.assertEqual(so.plan_sources('~/draft.md',project='~',libraries=[])['folder_paths'],[str(self.folder)])
    def test_18_settled_folder_still_asks_library(self):
        plan=so.plan_sources(self.draft,libraries=LIBS)
        self.assertIsNotNone(plan['question']); self.assertNotIn('folder',[o['value'] for o in plan['question']['options']])
        answered=so.plan_sources(self.draft,libraries=LIBS,choices=['library:two'])
        self.assertEqual(answered['folder_paths'],[str(self.folder)])
    def test_19_single_select_zero_one_library(self):
        draft=self.root/'new/draft.md'; draft.parent.mkdir(); draft.write_text('Synthetic')
        for libs in [[],LIBS[:1]]:
            q=so.plan_sources(draft,libraries=libs)['question']
            self.assertFalse(q['multiSelect']); self.assertLessEqual(len(q['options']),4)
            if libs: self.assertIn('both',[o['value'] for o in q['options']])
    def test_20_short_prompt_and_overflow_only(self):
        q=so.plan_sources(self.draft,libraries=LIBS)['question']
        self.assertLess(len(q['title']),110); self.assertLess(len(q['save_offer']),140)
        self.assertNotIn('library_list',q)
    def test_21_folder_only_preserves_saved_library(self):
        draft=self.root/'new/draft.md'; draft.parent.mkdir(); draft.write_text('Synthetic')
        project=draft.parent/so.PROJECT_FILE
        project.write_text('Zotero library: Amber Library → ID two\n')
        plan=so.plan_sources(draft,libraries=LIBS,choices=['folder'])
        self.assertEqual(plan['library_id'],'two'); self.assertFalse(plan['skip_zotero'])
        so.materialize(plan,remember=True)
        self.assertIn('Zotero library: Amber Library → ID two',project.read_text())

if __name__=='__main__': unittest.main()
