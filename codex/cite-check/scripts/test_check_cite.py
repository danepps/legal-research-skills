#!/usr/bin/env python3
"""Offline behavior tests for both independently installable identity helpers."""
import importlib.util
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
MODULES = []
for name in ('cite-check', 'legal-research-memo'):
    spec = importlib.util.spec_from_file_location(name, ROOT / name / 'scripts/check_cite.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    MODULES.append(module)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('urllib.request.urlopen', side_effect=AssertionError('offline tests must not access network'))
        self.network.start(); self.addCleanup(self.network.stop)

    def test_name_queries_and_escaping(self):
        for m in MODULES:
            self.assertEqual(m.party_tokens('Students for Fair Admissions v. President and Fellows of Harvard College'), ['Students', 'Harvard'])
            self.assertEqual(m.party_tokens('United States v. Jones'), ['United States', 'Jones'])
            self.assertIn('caseName:"Harvard"', m.name_query('Students v Harvard'))
            self.assertEqual(m.phrase('x" OR *:*'), '"x\\" OR *:*"')

    def test_unmatched_looks_by_both_routes_without_promoting_identity(self):
        for m in MODULES:
            with patch.object(m, 'request_json', return_value=[{'citation': '397 F. Supp. 3d 126', 'status': 404}]), patch.object(m, 'search', return_value={'status': 'checked', 'count': 1, 'results': [{'cluster_id': 99, 'caseName': 'Later case'}]}) as search:
                row = m.screen('397 F. Supp. 3d 126', 'Students v. Harvard')[0]
                self.assertEqual(search.call_count, 2)
                self.assertEqual(row['routes_tried'], ['citation_lookup', 'caption', 'citation_text'])
                self.assertFalse(row['found'])
                self.assertIn('unconfirmed', row['identity_confirmation'])
                self.assertEqual(search.call_args.args[0], '"397 F. Supp. 3d 126"')

    def test_no_caption_and_lookup_failure_are_explicit(self):
        for m in MODULES:
            with patch.object(m, 'request_json', side_effect=OSError('HTTP 429')):
                row = m.screen('10 F.4th 20')[0]
            self.assertEqual(row['fallbacks']['caption']['status'], 'skipped')
            self.assertEqual(row['fallbacks']['citation_text']['status'], 'unavailable')
            self.assertIsNone(row['found'])
            self.assertIn('429', row['error'])

    def test_ambiguous_and_batch_name(self):
        for m in MODULES:
            self.assertEqual(m.lookup_state({'status': 200, 'clusters': [{}, {}]}), 'ambiguous')
            with patch.object(m, 'request_json', return_value=[{}, {}]):
                with self.assertRaises(ValueError):
                    m.screen('batch', 'One v. Two')

    def test_pagination_and_truncation(self):
        for m in MODULES:
            next_url = m.BASE + '/api/rest/v4/search/?page=2'
            with patch.object(m, 'request_json', side_effect=[{'count': 3, 'results': [{'id': 1}], 'next': next_url}, {'count': 3, 'results': [{'id': 2}, {'id': 3}], 'next': None}]):
                got = m.fetch_pages(m.BASE + '/api/rest/v4/search/', limit=2)
            self.assertTrue(got['truncated'])
            self.assertEqual([r['id'] for r in got['results']], [1, 2])
            with self.assertRaises(ValueError):
                m.request_json('https://example.org/steal-token')

    def test_cluster_dedup_retains_signals_and_unknowns(self):
        for m in MODULES:
            rows = [{'cluster_id': 1, 'routes': ['graph'], 'snippet': 'A', 'signals': []},
                    {'cluster_id': 1, 'routes': ['name'], 'snippet': 'B', 'signals': ['overruled']},
                    {'case_name': 'same'}, {'case_name': 'same'}]
            got = m.dedupe_decisions(rows)
            self.assertEqual(len(got), 3)
            self.assertEqual(got[0]['routes'], ['graph', 'name'])
            self.assertEqual(got[0]['signals'], ['overruled'])
            self.assertEqual(got[0]['additional_snippets'], ['B'])

    def test_slip_bound_duplicates_merge_but_namesakes_do_not(self):
        for m in MODULES:
            rows = [{'cluster_id': 1, 'court_id': 'scotus', 'date_filed': '2023-06-29', 'citations': ['600 U.S. 181']},
                    {'cluster_id': 2, 'court_id': 'scotus', 'date_filed': '2023-06-29', 'citations': ['600 U.S. 181', '143 S. Ct. 2141']},
                    {'cluster_id': 3, 'court_id': 'scotus', 'date_filed': '2023-06-29', 'citations': ['143 S. Ct. 2141']},
                    {'cluster_id': 4, 'court_id': 'other', 'date_filed': '2023-06-29', 'citations': ['600 U.S. 181']}]
            got = m.dedupe_decisions(rows)
            self.assertEqual(len(got), 2)
            self.assertEqual(got[0]['cluster_ids'], [1, 2, 3])


class DraftComparisonTests(unittest.TestCase):
    def setUp(self):
        self.m = MODULES[0]  # The independently installed sibling is out of scope.
        guard = patch('urllib.request.urlopen', side_effect=AssertionError('network forbidden'))
        guard.start(); self.addCleanup(guard.stop)
        credential = patch.object(self.m, 'token', side_effect=AssertionError('credentials forbidden'))
        credential.start(); self.addCleanup(credential.stop)

    def result(self, draft, resolved):
        return self.m.compare_identity(draft, None, resolved, None)['caption']['result']

    def test_disjoint_distinctive_parties_are_mismatches(self):
        for draft, resolved in [
            ('Sherman v. United States', 'Thomas v. Arizona'),
            ('United States v. Sherman', 'United States v. Thomas'),
            ('United States v. Lopez', 'United States v. Morrison'),
            ('Roe v. Wade', 'Doe v. Bolton'),
            ('State v. Adams', 'State v. Jones'),
            ('People v. Smith', 'Commonwealth v. Brown'),
            ('City of Austin v. County of Travis', 'City of Dallas v. County of Denton'),
            ('In re Adams', 'Ex parte Jones'),
        ]:
            with self.subTest(draft=draft, resolved=resolved):
                self.assertEqual(self.result(draft, resolved), 'mismatch')

    def test_abbreviations_spelling_long_names_and_procedural_labels(self):
        pairs = [
            ('Bd. of Educ. v. Allen', 'Board of Education v. Allen'),
            ("Dep't of Revenue v. Davis", 'Department of Revenue v. Davis'),
            ("Ass'n of Builders v. Jones", 'Association of Builders v. Jones'),
            ("Comm'n v. Brown", 'Commission v. Brown'),
            ("Nat'l Bank v. Smith", 'National Bank v. Smith'),
            ("Int'l Union v. Brown", 'International Union v. Brown'),
            ('Univ. of Michigan v. Doe', 'University of Michigan v. Doe'),
            ('Acme Co. v. Doe', 'Acme Company v. Doe'),
            ('Acme Corp. v. Doe', 'Acme Corporation v. Doe'),
            ('Acme, Inc. v. Doe', 'Acme Incorporated v. Doe'),
            ('EPA v. Brown', 'Environmental Protection Agency v. Brown'),
            ('In re Gault', 'In the Matter of Gault'),
            ('Ex parte Young', 'Young'),
            ('United States ex rel. Smith v. Jones', 'United States on behalf of Smith v. Jones'),
            ('United States v. Mathews', 'United States v. Frederick Mathews'),
            ('Smith v. Jones', 'John Smith, Mary Smith, and James Doe v. Robert Jones et al.'),
            ('SMITH, ET AL. v. JONES', 'Smith v Jones'),
            ('O’Connor v. Jones', "O'Connor v. Jones"),
        ]
        # Each abbreviation also works without a matching opposing party.
        pairs += [(short + ' of Acme', long + ' of Acme') for short, long in
                  [('Bd.', 'Board'), ('Educ.', 'Education'), ("Dep’t", 'Department'),
                   ("Ass'n", 'Association'), ("Comm'n", 'Commission'), ("Nat'l", 'National'),
                   ("Int'l", 'International'), ('Univ.', 'University'), ('Co.', 'Company'),
                   ('Corp.', 'Corporation'), ('Inc.', 'Incorporated')]]
        for draft, resolved in pairs:
            with self.subTest(draft=draft):
                self.assertEqual(self.result(draft, resolved), 'match')

    def test_prefix_and_old_reporter_spelling_agreement(self):
        for draft, resolved, draft_word, resolved_word, rule in [
            ('McCulloch v. Maryland', 'M’Culloch v. State of Maryland',
             'mcculloch', 'mculloch', 'one_edit'),
            ('Commonwealth v. Mass. Elec. Co.', 'Commonwealth v. Massachusetts Electric Company',
             'elec', 'electric', 'prefix'),
        ]:
            with self.subTest(draft=draft):
                comparison = self.m.compare_identity(draft, None, resolved, None)['caption']
                self.assertEqual(comparison['result'], 'match')
                self.assertEqual(comparison['shared_words'], [])
                self.assertEqual(comparison['word_agreements'], [
                    {'draft': draft_word, 'resolved': resolved_word, 'rule': rule}])

    def test_prefix_and_one_edit_length_boundaries(self):
        for left, right, expected in [
            ('elec', 'electric', 'match'),             # Four-letter prefix.
            ('ele', 'electric', 'mismatch'),           # Three letters are too short.
            ('mfrs', 'manufacturers', 'mismatch'),     # Not a prefix.
            ('adams', 'xadams', 'match'),              # Insertion at the start.
            ('adams', 'adxams', 'match'),              # Insertion in the middle.
            ('adams', 'adamsx', 'match'),              # Insertion at the end (also a prefix).
            ('adams', 'bdams', 'match'),               # Substitution at the start.
            ('adams', 'adans', 'match'),               # Substitution in the middle.
            ('adams', 'adamx', 'match'),               # Substitution at the end.
            ('adams', 'admas', 'mismatch'),            # Transposition is two edits.
            ('adams', 'xxadams', 'mismatch'),          # Two insertions.
            ('adams', 'adxans', 'mismatch'),           # Insertion and substitution.
            ('adams', 'abans', 'mismatch'),            # Two substitutions.
            ('adams', 'adms', 'mismatch'),             # Shorter word has four letters.
            ('wade', 'wide', 'mismatch'),              # Both words have four letters.
            ('roe', 'doe', 'mismatch'),                # Short names must remain distinct.
        ]:
            for draft_word, resolved_word in ((left, right), (right, left)):
                with self.subTest(draft=draft_word, resolved=resolved_word):
                    self.assertEqual(self.result('In re ' + draft_word, 'In re ' + resolved_word), expected)

    def test_generic_only_captions_are_indeterminate(self):
        for draft, resolved in [('United States', 'State'), ('People', 'Commonwealth'),
                                ('City v. County', 'State v. People'),
                                ('United States', 'United States v. Mathews'),
                                ('State v. Smith', 'People')]:
            with self.subTest(draft=draft):
                self.assertEqual(self.result(draft, resolved), 'indeterminate')

    def test_shared_sovereigns_do_not_clear_distinct_parties(self):
        for draft, resolved in [
            ('Mapp v. Ohio', 'Terry v. Ohio'),
            ('Arizona v. Gant', 'Arizona v. Fulminante'),
            ('Miranda v. Arizona', 'Thomas v. Arizona'),
            ('Miranda v. Ariz.', 'Thomas v. Arizona'),
            ('Adams v. Cal.', 'Brown v. California'),
            ('Adams v. Mass.', 'Brown v. Massachusetts'),
            ('New York v. Quarles', 'New York Times Co. v. Sullivan'),
            ('N.Y. v. Quarles', 'New York Times Co. v. Sullivan'),
            ('West Virginia v. Adams', 'W. Va. v. Brown'),
            ('North Carolina v. Adams', 'N.C. v. Brown'),
            ('District of Columbia v. Adams', 'D.C. v. Brown'),
            ('Puerto Rico v. Adams', 'P.R. v. Brown'),
            ('Guam v. Adams', 'Guam v. Brown'),
            ('New v. Adams', 'New York v. Brown'),
            ('West v. Adams', 'West Virginia v. Brown'),
            ('North v. Adams', 'North Carolina v. Brown'),
        ]:
            with self.subTest(draft=draft, resolved=resolved):
                comparison = self.m.compare_identity(draft, None, resolved, None)['caption']
                self.assertEqual(comparison['result'], 'mismatch')
                self.assertEqual(comparison['shared_words'], [])

    def test_sovereign_only_captions_compare_complete_names(self):
        for draft, resolved, expected in [
            ('Arizona v. California', 'Arizona v. California', 'match'),
            ('Arizona v. California', 'Ariz. v. Cal.', 'match'),
            ('Arizona v. California', 'Texas v. New Mexico', 'mismatch'),
            ('Ariz. v. Cal.', 'Tex. v. N.M.', 'mismatch'),
            ('New York v. West Virginia', 'N.Y. v. W. Va.', 'match'),
            ('New York v. West Virginia', 'N. Y. v. W.Va.', 'match'),
            ('New York v. North Carolina', 'New Mexico v. North Dakota', 'mismatch'),
            ('West Virginia', 'Virginia', 'mismatch'),
            ('North Carolina', 'South Carolina', 'mismatch'),
            ('New York', 'New Jersey', 'mismatch'),
            ('District of Columbia', 'Puerto Rico', 'mismatch'),
            ('Guam', 'Guam', 'match'),
            ('New York Times Co. v. Sullivan', 'New York Times Co. v. Sullivan', 'match'),
            ('N.Y. Times Co. v. Sullivan', 'New York Times Company v. Sullivan', 'match'),
            ('New Yorker v. Adams', 'New Yorker v. Brown', 'match'),
        ]:
            with self.subTest(draft=draft, resolved=resolved):
                self.assertEqual(self.result(draft, resolved), expected)

    def test_sovereign_abbreviations_match_full_names_and_do_not_mask_errors(self):
        pairs = [
            ('Alabama', 'Ala.'), ('Alaska', 'Alaska'), ('Arizona', 'Ariz.'),
            ('Arkansas', 'Ark.'), ('California', 'Cal.'), ('Colorado', 'Colo.'),
            ('Connecticut', 'Conn.'), ('Delaware', 'Del.'), ('Florida', 'Fla.'),
            ('Georgia', 'Ga.'), ('Hawaii', 'Haw.'), ('Idaho', 'Idaho'),
            ('Illinois', 'Ill.'), ('Indiana', 'Ind.'), ('Iowa', 'Iowa'),
            ('Kansas', 'Kan.'), ('Kentucky', 'Ky.'), ('Louisiana', 'La.'),
            ('Maine', 'Me.'), ('Maryland', 'Md.'), ('Massachusetts', 'Mass.'),
            ('Michigan', 'Mich.'), ('Minnesota', 'Minn.'), ('Mississippi', 'Miss.'),
            ('Missouri', 'Mo.'), ('Montana', 'Mont.'), ('Nebraska', 'Neb.'),
            ('Nevada', 'Nev.'), ('New Hampshire', 'N.H.'), ('New Jersey', 'N.J.'),
            ('New Mexico', 'N.M.'), ('New York', 'N.Y.'), ('North Carolina', 'N.C.'),
            ('North Dakota', 'N.D.'), ('Ohio', 'Ohio'), ('Oklahoma', 'Okla.'),
            ('Oregon', 'Or.'), ('Pennsylvania', 'Pa.'), ('Rhode Island', 'R.I.'),
            ('South Carolina', 'S.C.'), ('South Dakota', 'S.D.'), ('Tennessee', 'Tenn.'),
            ('Texas', 'Tex.'), ('Utah', 'Utah'), ('Vermont', 'Vt.'), ('Virginia', 'Va.'),
            ('Washington', 'Wash.'), ('West Virginia', 'W. Va.'), ('Wisconsin', 'Wis.'),
            ('Wyoming', 'Wyo.'), ('District of Columbia', 'D.C.'), ('Puerto Rico', 'P.R.'),
            ('Guam', 'Guam'),
        ]
        for full, abbreviated in pairs:
            with self.subTest(sovereign=full):
                self.assertEqual(self.result(full, abbreviated), 'match')
                self.assertEqual(self.result(full + ' v. Adams', abbreviated + ' v. Brown'), 'mismatch')
                self.assertEqual(self.result(full + ' v. Adams', abbreviated + ' v. Frederick Adams'), 'match')

    def test_years_and_missing_metadata(self):
        for year, date, result in [(1934, '1932-12-19', 'mismatch'),
                                   ('1932', '1932-12-19', 'match'),
                                   (None, '1932-12-19', 'not_supplied'),
                                   (1932, None, 'resolved_unavailable'),
                                   ('1932', '', 'resolved_unavailable')]:
            with self.subTest(year=year, date=date):
                self.assertEqual(self.m.compare_identity(None, year, None, date)['year']['result'], result)
        for bad in [True, 32, '1932/1934', [], {}]:
            with self.assertRaises(ValueError):
                self.m.compare_identity(None, bad, None, None)

    def test_handoff_cases_keep_found_and_surface_mismatch(self):
        for cite, name, year, resolved, date, dimension in [
            ('356 U.S. 396', 'Sherman v. United States', 1958, 'Thomas v. Arizona', '1958-06-30', 'caption'),
            ('287 U.S. 435', 'Sorrells v. United States', 1934, 'Sorrells v. United States', '1932-12-19', 'year'),
        ]:
            response = [{'citation': cite, 'status': 200, 'clusters': [{'case_name': resolved, 'date_filed': date}]}]
            with patch.object(self.m, 'request_json', return_value=response), patch.object(self.m, 'fallback_searches') as fallback:
                row = self.m.screen(cite, name, year=year)[0]
            self.assertIs(row['found'], True)
            self.assertEqual(row['identity_comparison'][dimension]['result'], 'mismatch')
            self.assertEqual(row['identity_comparison']['caption']['draft'], name)
            fallback.assert_not_called()

    def test_nameless_reporter_and_ambiguous_lookup(self):
        response = [{'citation': '356 U.S. 396', 'status': 200,
                     'clusters': [{'case_name': 'Thomas v. Arizona', 'date_filed': '1958-06-30'}]}]
        with patch.object(self.m, 'request_json', return_value=response):
            row = self.m.screen('356 U.S. 396')[0]
        self.assertEqual(row['identity_comparison']['caption']['result'], 'not_supplied')
        response[0]['clusters'].append({'case_name': 'Sherman v. United States'})
        with patch.object(self.m, 'request_json', return_value=response), patch.object(self.m, 'fallback_searches', return_value={'caption': {'status': 'skipped'}, 'citation_text': {'status': 'skipped'}}):
            row = self.m.screen('356 U.S. 396', 'Sherman v. United States', year=1958)[0]
        self.assertEqual(row['identity_comparison']['caption']['result'], 'resolved_unavailable')
        self.assertEqual(row['identity_comparison']['year']['result'], 'resolved_unavailable')

    def test_batch_metadata_is_bound_to_each_unit_even_for_repeated_cite(self):
        units = [{'unit_id': 'U1', 'source_id': 'S1', 'source_type': 'case', 'lookup_citation': '356 U.S. 396',
                  'draft_case_name': 'Sherman v. United States', 'draft_year': 1958},
                 {'unit_id': 'U2', 'source_id': 'S1', 'source_type': 'case', 'lookup_citation': '356 U.S. 396',
                  'draft_case_name': 'Thomas v. Arizona', 'draft_year': 1957}]
        response = [{'citation': '356 U.S. 396', 'status': 200, 'clusters': [
            {'case_name': 'Thomas v. Arizona', 'date_filed': '1958-06-30'}]}]
        with patch.object(self.m, 'request_json', return_value=response) as request:
            rows = self.m.screen_units(units)
        self.assertEqual(request.call_count, 2)
        self.assertEqual([r['unit_id'] for r in rows], ['U1', 'U2'])
        self.assertEqual(rows[0]['identity_comparison']['caption']['result'], 'mismatch')
        self.assertEqual(rows[1]['identity_comparison']['caption']['result'], 'match')
        self.assertEqual(rows[1]['identity_comparison']['year']['result'], 'mismatch')
        with patch.object(self.m, 'request_json') as request:
            for bad in [units + units, [dict(units[0], draft_year=True)],
                        [dict(units[0], lookup_citation='')], [{'unit_id': 'U1', 'source_type': 'case'}]]:
                with self.assertRaises(ValueError):
                    self.m.screen_units(bad)
            request.assert_not_called()

    def test_cli_writes_linked_jsonl_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            units = root / 'units.jsonl'
            units.write_text(json.dumps({'unit_id': 'U1', 'source_id': 'S1', 'source_type': 'case',
                'lookup_citation': '287 U.S. 435', 'draft_case_name': 'Sorrells v. United States', 'draft_year': 1934}) + '\n')
            output = root / 'screens.jsonl'
            response = [{'citation': '287 U.S. 435', 'status': 200, 'clusters': [
                {'case_name': 'Sorrells v. United States', 'date_filed': '1932-12-19'}]}]
            args = ['check_cite.py', '--units-file', str(units), '--output', str(output)]
            # A boolean auth-presence stub, never a token; all API data is mocked.
            with patch.object(sys, 'argv', args), patch.object(self.m, 'token', return_value=True), \
                    patch.object(self.m, 'request_json', return_value=response), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(self.m.main(), 0)
            row = json.loads(output.read_text())
            self.assertEqual(row['unit_id'], 'U1')
            self.assertEqual(row['identity_comparison']['year']['result'], 'mismatch')
            before = output.read_bytes()
            with patch.object(sys, 'argv', args), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                self.m.main()
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(output.read_bytes(), before)

    def test_single_year_only_batch_guard_and_missing_credentials(self):
        with patch.object(self.m, 'request_json', return_value=[{}, {}]), self.assertRaises(ValueError):
            self.m.screen('batch', year=1934)
        with patch.object(sys, 'argv', ['check_cite.py', '287 U.S. 435', '--year', '1934']), \
                patch.object(self.m, 'token', return_value=None), patch.object(self.m, 'request_json') as request, \
                contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.m.main(), 1)
            request.assert_not_called()


if __name__ == '__main__':
    unittest.main()
