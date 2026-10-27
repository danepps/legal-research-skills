#!/usr/bin/env python3
"""Picker scope, opt-in boundaries, source counts and initialization handoff."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from extract_cites import extract_document, sha256
from prepare_run_options import prepare_options, resolved_selection, parse_footnotes
from prepare_units import build_prepared_units
from support_screen import screen_extraction

HERE = Path(__file__).resolve().parent


def write_rows(path, rows):
    path.write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')


class OptionsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.draft = self.root/'draft.md'
        self.draft.write_text(' '.join(f'A claim.[^{i}]' for i in range(1, 37))+'\n\n'+
                              '\n'.join(f'[^{i}]: A v. B, 1 U.S. 2, 3 (1900).' for i in range(1, 37)))
        self.ex = extract_document(self.draft)

    def save(self, plan):
        path = self.root/'options.json'
        path.write_text(json.dumps(plan))
        return path

    def initialize(self, plan, *flags):
        path = self.save(plan)
        return subprocess.run([sys.executable,str(HERE/'init_run.py'),str(self.draft),'--run-dir',
                               str(self.root/'run'),'--options',str(path),*flags],capture_output=True,text=True)

    def test_long_draft_gets_one_group_of_only_unsettled_choices(self):
        plan = prepare_options(self.ex)
        self.assertEqual(plan['status'], 'needs_choice')
        self.assertEqual([q['id'] for q in plan['questions']], ['coverage','depth','support'])
        self.assertEqual(plan['selection']['support'], 'off')
        plan = prepare_options(self.ex, depth='deep', support='pincited')
        self.assertEqual([q['id'] for q in plan['questions']], ['coverage'])
        self.assertEqual(plan['selection']['support'], 'pincited')

    def test_explicit_choices_bypass_picker_and_deep_does_not_enable_support(self):
        plan = prepare_options(self.ex,coverage='all',depth='deep',support='off')
        self.assertEqual(plan['status'],'ready')
        self.assertEqual(plan['questions'],[])
        self.assertEqual(plan['selection']['support'],'off')
        fallback = prepare_options(self.ex,depth='deep',defaults=True)
        self.assertEqual(fallback['selection']['support'],'off')
        self.assertEqual(fallback['selection']['depth'],'deep')

    def test_defaults_and_short_draft_do_not_force_dialog(self):
        plan = prepare_options(self.ex,defaults=True)
        self.assertEqual(plan['status'],'ready')
        self.assertEqual(plan['selection'],{'coverage':'all','depth':'standard','support':'off','footnotes':None})
        short = copy.deepcopy(self.ex);short['footnotes'] = short['footnotes'][:3]
        self.assertEqual(prepare_options(short)['questions'],[])
        self.assertEqual([q['id'] for q in prepare_options(short,ask=True)['questions']],['depth','support'])

    def test_sample_deep_initializes_as_focused_with_exact_notes(self):
        plan = prepare_options(self.ex,coverage='sample',depth='deep',support='pincited')
        self.assertEqual(plan['selection']['footnotes'],list(range(1,11)))
        self.assertFalse(plan['counts']['includes_body_citations'])
        p=self.initialize(plan)
        self.assertEqual(p.returncode,0,p.stderr)
        m=json.loads((self.root/'run/run-manifest.json').read_text())
        self.assertEqual(m['scope'],'focused')
        self.assertEqual(m['review_depth'],'deep')
        self.assertEqual(m['selected_footnotes'],list(range(1,11)))
        self.assertEqual(m['support_pass'],{'enabled':True,'scope':'pincited'})
        self.assertTrue(m['run_options_sha256'])

    def test_custom_notes_and_invalid_ranges_never_expand_to_whole_draft(self):
        plan=prepare_options(self.ex,footnotes=['2-3','7'],depth='standard',support='off')
        self.assertEqual(plan['selection']['footnotes'],[2,3,7])
        for value in ([],['0'],['40'],['5-2'],['1-999999'],['a']):
            with self.subTest(value=value),self.assertRaises(ValueError):
                parse_footnotes(value,set(range(1,37)))
        with self.assertRaises(ValueError):
            prepare_options(self.ex,coverage='all',footnotes=['1'])

    def test_pending_choices_and_conflicting_overrides_cannot_initialize(self):
        p=self.initialize(prepare_options(self.ex))
        self.assertNotEqual(p.returncode,0)
        self.assertFalse((self.root/'run').exists())
        p=self.initialize(prepare_options(self.ex,defaults=True),'--support')
        self.assertNotEqual(p.returncode,0)
        self.assertFalse((self.root/'run').exists())

    def test_changed_draft_and_implicit_support_are_rejected(self):
        plan=prepare_options(self.ex,defaults=True)
        changed=copy.deepcopy(plan);changed['selection']['support']='all'
        with self.assertRaisesRegex(ValueError,'explicit choice'):
            resolved_selection(changed,self.ex['input_sha256'])
        self.draft.write_text(self.draft.read_text()+'\nChanged.\n')
        p=self.initialize(plan)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('draft changed',p.stderr)
        self.assertFalse((self.root/'run').exists())

    def test_manifest_cannot_disagree_with_saved_choices(self):
        p=self.initialize(prepare_options(self.ex,coverage='sample',depth='standard',support='off'))
        self.assertEqual(p.returncode,0,p.stderr)
        path=self.root/'run/run-manifest.json';m=json.loads(path.read_text())
        m['scope']='standard';path.write_text(json.dumps(m))
        p=subprocess.run([sys.executable,str(HERE/'validate_run.py'),str(self.root/'run')],capture_output=True,text=True)
        self.assertNotEqual(p.returncode,0)
        self.assertIn('resolved scope/depth/support',p.stdout+p.stderr)

    def test_blocked_extraction_does_not_offer_a_runnable_choice(self):
        ex=copy.deepcopy(self.ex);ex['blocking_issues']=['Unsupported note numbering.']
        plan=prepare_options(ex)
        self.assertEqual(plan['status'],'blocked')
        self.assertEqual(plan['questions'],[])
        with self.assertRaises(ValueError):resolved_selection(plan,ex['input_sha256'])

    def test_cli_preview_is_local_and_leaves_draft_unchanged(self):
        before=self.draft.read_bytes();out=self.root/'hidden/options.json'
        p=subprocess.run([sys.executable,str(HERE/'prepare_run_options.py'),str(self.draft),
                          '--output',str(out),'--coverage','sample','--depth','standard','--support','off'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(out.read_text())['selection']['footnotes'],list(range(1,11)))
        self.assertEqual(self.draft.read_bytes(),before)


class SourceCountTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.draft=self.root/'draft.md'
        self.draft.write_text('The court said “one two three four five six seven eight nine ten.”[^1] Another claim.[^2] Background.[^3]\n\n'
                              '[^1]: A v. B, 1 U.S. 2, 3 (1900).\n'
                              '[^2]: Doe, Article, 10 Yale L.J. 20, 22 (1900).\n'
                              '[^3]: See generally Roe, A Book (1900).\n')
        self.ex=extract_document(self.draft);self.inventory=self.root/'inventory';self.inventory.mkdir()
        write_rows(self.inventory/'prepared-units.jsonl',build_prepared_units(self.ex))
        units=[]
        for i,row in enumerate(screen_extraction(self.ex),1):
            note=self.ex['footnotes'][i-1]
            units.append(dict(row,unit_id=f'U{i}',source_id=f'S{i}',source_type=row['kind_hint'],
                              resolved_source_label=row['draft_citation_text'],full_footnote=note['text']))
        write_rows(self.inventory/'citation-units.jsonl',units)
        write_rows(self.inventory/'quote-checks.jsonl',[{'unit_id':'U1','source_id':'S1','prepared_unit_id':'P1'}])
        cache=self.inventory/'case.txt';cache.write_text('Cached full text.')
        write_rows(self.inventory/'source-ledger.jsonl',[
            {'source_id':'S1','status':'retrieved','verification_basis':'primary_full_text',
             'source_path':'case.txt','source_sha256':sha256(cache)},
            {'source_id':'S2','status':'metadata_only'}, {'source_id':'S3','status':'unavailable'}])
        self.manifest={'draft_sha256':self.ex['input_sha256'],'status':'complete_with_limits','selected_footnotes':None}
        self.save_manifest()

    def save_manifest(self):
        (self.inventory/'run-manifest.json').write_text(json.dumps(self.manifest))

    def counts(self,support='off',**kwargs):
        return prepare_options(self.ex,support=support,inventory=self.inventory,defaults=True,**kwargs)['sources']

    def test_quote_support_and_whole_work_costs_are_separate(self):
        self.assertEqual(self.counts()['full_text_sources'],2)
        self.assertEqual(self.counts()['uncached_sources'],1)
        self.assertEqual(self.counts('pincited')['uncached_sources'],1)
        self.assertEqual(self.counts('all')['uncached_sources'],2)
        self.assertEqual(self.counts('all',footnotes=['2'])['full_text_sources'],1)

    def test_cache_hash_is_checked_and_missing_inventory_is_unknown(self):
        (self.inventory/'case.txt').write_text('Changed cache.')
        self.assertEqual(self.counts()['uncached_sources'],2)
        estimate=prepare_options(self.ex)['sources']
        self.assertEqual(estimate['status'],'unknown')
        self.assertIsNone(estimate['uncached_sources'])

    def test_stale_partial_and_unresolved_inventories_do_not_claim_zero_cost(self):
        for update in ({'draft_sha256':'wrong'}, {'selected_footnotes':[1]}, {'status':'initialized'}):
            with self.subTest(update=update):
                original=self.manifest.copy();self.manifest.update(update);self.save_manifest()
                self.assertEqual(self.counts()['status'],'unknown')
                self.manifest=original;self.save_manifest()

    def test_focused_inventory_with_a_higher_quote_threshold_is_not_complete_coverage(self):
        self.manifest['selected_footnotes']=[1];self.save_manifest()
        old_extraction=extract_document(self.draft, min_quote_words=12)
        write_rows(self.inventory/'prepared-units.jsonl',build_prepared_units(old_extraction,{1}))
        write_rows(self.inventory/'quote-checks.jsonl',[])
        self.assertEqual(self.counts(footnotes=['1'])['status'],'unknown')

    def test_quote_ids_can_change_without_invalidating_matching_content(self):
        rows=build_prepared_units(self.ex);rows[0]['prepared_unit_id']='P9'
        write_rows(self.inventory/'prepared-units.jsonl',rows)
        write_rows(self.inventory/'quote-checks.jsonl',[{'unit_id':'U1','source_id':'S1','prepared_unit_id':'P9'}])
        counts=self.counts(footnotes=['1'])
        self.assertEqual(counts['status'],'resolved_inventory')
        self.assertEqual(counts['cached_sources'],1)
        self.assertEqual(counts['inventory_path'],str(self.inventory.resolve()))


if __name__=='__main__':unittest.main()
