#!/usr/bin/env python3
"""Behavioral regressions from the October 2026 review; no network or office app."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from xml.sax.saxutils import escape
import zipfile

import extract_cites as extract
import prepare_units as prepare
import verify_quotes as matcher
from check_cite import lookup_state

HERE = Path(__file__).resolve().parent
NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
QUOTE = "the limitations period does not begin until the plaintiff discovers the injury"


def run(script, *args):
    return subprocess.run([sys.executable, str(HERE / script), *map(str, args)],
                          capture_output=True, text=True, timeout=30)


def rows(path, values):
    path.write_text("".join(json.dumps(row) + "\n" for row in values))


def read_rows(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def create_docx(path, body, notes="", extra=None):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", f'<w:document xmlns:w="{NS}"><w:body>{body}</w:body></w:document>')
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>')
        if notes:
            archive.writestr("word/footnotes.xml", f'<w:footnotes xmlns:w="{NS}">{notes}</w:footnotes>')
        for name, text in (extra or {}).items():
            archive.writestr(name, text)
    return path


def note(number, text):
    return f'<w:footnote w:id="{number}"><w:p><w:r><w:t>{escape(text)}</w:t></w:r></w:p></w:footnote>'


def ref(number, custom=False):
    attr = 'w:customMarkFollows="1"' if custom else ""
    return f'<w:r><w:footnoteReference w:id="{number}" {attr}/></w:r>'


def match(raw, quote, pin=None, footer=False):
    spans, kind = matcher.page_spans(raw, footer)
    views = {fold: matcher.normalize(raw, fold=fold, spans=spans) for fold in (False, True)}
    views["dehyphenated"] = matcher.normalize(raw, fold=True, spans=spans, dehyphenate_line_breaks=True)
    return matcher.check_quote(raw, views, kind, None, {"quote": quote, "pincite": pin})


class ExtractionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def extract(self, body, notes="", extra=None):
        return extract.extract_document(create_docx(self.root / "draft.docx", body, notes, extra))

    def test_custom_marks_do_not_shift_numbers_or_supra(self):
        data = self.extract('<w:p>' + ref(1, True) + '<w:r><w:t>*</w:t></w:r>' + ref(2) + ref(3) + '</w:p>',
                            note(1, '“' + QUOTE + '” Author source.') + note(2, "Smith, Book.") + note(3, "Smith, supra note 1."))
        self.assertEqual([n["number"] for n in data["footnotes"]], [None, 1, 2])
        self.assertEqual(data["footnotes"][0]["custom_mark"], "*")
        self.assertEqual(data["supra_problem_candidates"], [])
        packet = prepare.build_prepared_units(data)[0]
        self.assertIsNone(packet["footnote_number"])
        self.assertEqual(packet["note_id"], "fn:1")
        self.assertIn("Author source", packet["full_footnote"])

    def test_deleted_references_and_moves_are_excluded(self):
        for tag in ("del", "moveFrom"):
            with self.subTest(tag=tag):
                data = self.extract('<w:p><w:' + tag + '>' + ref(1) + '</w:' + tag + '>' + ref(2) + '</w:p>',
                                    note(1, "Deleted authority.") + note(2, "Live authority."))
                self.assertEqual(data["paragraphs"], ["[[FN:1]]"])
                self.assertEqual([(n["number"], n["text"]) for n in data["footnotes"]], [(1, "Live authority.")])
        data = self.extract('<w:moveFrom><w:p><w:r><w:t>Moved.</w:t></w:r></w:p></w:moveFrom><w:moveTo><w:p><w:r><w:t>Moved.</w:t></w:r></w:p></w:moveTo>')
        self.assertEqual(data["paragraphs"], ["Moved."])
        self.assertTrue(data["tracked_changes"]["insertions_present"])
        self.assertTrue(data["tracked_changes"]["deletions_present"])

    def test_note_revisions_content_controls_and_characters(self):
        data = self.extract('<w:p>' + ref(1) + '</w:p>',
            '<w:footnote w:id="1"><w:sdt><w:sdtContent><w:p><w:ins><w:r><w:t>well</w:t><w:noBreakHyphen/><w:t>settled</w:t><w:br/><w:t>rule</w:t><w:cr/><w:t>applies</w:t></w:r></w:ins><w:del><w:r><w:delText>removed</w:delText></w:r></w:del></w:p></w:sdtContent></w:sdt></w:footnote>')
        self.assertEqual(data["footnotes"][0]["text"], "well-settled rule applies")
        self.assertTrue(data["tracked_changes"]["insertions_present"])
        self.assertTrue(data["tracked_changes"]["deletions_present"])

    def test_numbering_start_and_unsupported_structures(self):
        data = self.extract('<w:p>' + ref(2) + '</w:p><w:sectPr><w:footnotePr><w:numStart w:val="7"/></w:footnotePr></w:sectPr>', note(2, "Authority."))
        self.assertEqual(data["footnotes"][0]["number"], 7)
        data = self.extract('<w:p>' + ref(2) + '</w:p>', note(2, "Authority."),
                            {"word/settings.xml": f'<w:settings xmlns:w="{NS}"><w:footnotePr><w:numStart w:val="9"/></w:footnotePr></w:settings>'})
        self.assertEqual(data["footnotes"][0]["number"], 9)
        for body in ('<w:p><w:r><w:endnoteReference w:id="1"/></w:r></w:p>', '<w:p>' + ref(9) + '</w:p>',
                     '<w:sectPr><w:footnotePr><w:numRestart w:val="eachSect"/></w:footnotePr></w:sectPr>'):
            data = self.extract(body)
            self.assertTrue(data["blocking_issues"])
            result = run("init_run.py", self.root / "draft.docx", "--run-dir", self.root / f"blocked-{len(list(self.root.iterdir()))}")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("BLOCKED:", result.stderr)

    def test_sentence_and_attribution_context(self):
        for marker in ('”[[FN:1]]', '[[FN:1]]”'):
            text = 'Brown v. Board held that “' + QUOTE + '.' + marker + ' Another sentence.[[FN:2]]'
            row = extract.quote_rows([text], {}, 8)[0]
            self.assertEqual(row["primary_supporting_footnote"], 1)
            self.assertFalse(row["primary_inferred_from_paragraph"])
            self.assertTrue(row["body_context"].startswith("Brown v. Board"))
            self.assertNotIn("Another sentence", row["body_context"])
        row = extract.quote_rows(['“' + QUOTE + '.” Another sentence.[[FN:2]]'], {}, 8)[0]
        self.assertTrue(row["primary_inferred_from_paragraph"])
        row = extract.quote_rows(['Earlier sentence.[[FN:1]] Then “' + QUOTE + '.”[[FN:2]]'], {}, 8)[0]
        self.assertNotIn("Earlier", row["body_context"])

    def test_nested_and_block_quotes(self):
        for text in ('“Enough words precede the inner “quoted phrase” and enough words follow.”',
                     '“Enough words precede the inner ‘quoted phrase’ and enough words follow.”',
                     '"Enough words precede the inner "quoted phrase" and enough words follow."'):
            self.assertEqual(extract.quote_rows([text], {}, 8)[0]["quote"], text[1:-1])
        data = self.extract('<w:p><w:pPr><w:pStyle w:val="BlockQuote"/></w:pPr><w:r><w:t>' + QUOTE + '</w:t></w:r></w:p>')
        self.assertTrue(data["body_quotes"][0]["block_quote"])
        data = self.extract('<w:p><w:pPr><w:ind w:left="720"/></w:pPr><w:r><w:t>' + QUOTE + '</w:t></w:r></w:p>')
        self.assertEqual(data["block_quote_candidates"], [1])
        path = self.root / 'draft.md'; path.write_text('> ' + QUOTE)
        self.assertTrue(extract.extract_document(path)["body_quotes"][0]["block_quote"])

    def test_cross_reference_candidates_and_long_context(self):
        redirects = extract.cross_reference_metadata("See supra notes 1–3; Smith, supra note 4.")["supra"]
        self.assertEqual([r["note"] for r in redirects], [1, 2, 3, 4])
        self.assertIsNone(redirects[0]["name_hint"])
        self.assertEqual(redirects[-1]["name_hint"], "Smith")
        self.assertEqual([r["note"] for r in extract.cross_reference_metadata("Smith, supra note 4, 123.")["supra"]], [4])
        for text in ("See, e.g., id.", "Cf. id.", "But see id."):
            self.assertTrue(extract.cross_reference_metadata(text)["leading_id"])
        notes = {n: {"text": "Full authority." if n == 1 else "See infra Part II." if n == 3 else "Id. at 2."} for n in range(1, 8)}
        self.assertIn("1", prepare.preceding_notes(notes, 8))
        for cite in ("123 S.W.2d 456", "123 S.E. 456", "123 N.Y. 456", "2024 WL 123456", "5 U.S. (1 Cranch) 137"):
            self.assertEqual(extract.cross_reference_metadata(cite)["case_cites"], [cite])


class MatcherTests(unittest.TestCase):
    def test_typographic_variants(self):
        for source, quote in (("knows—or reasonably should know", "knows — or reasonably should know"),
                              ("knows—or reasonably should know", "knows--or reasonably should know"),
                              ("a cafe\u0301 opened", "a café opened"),
                              ("a café opened", "a cafe\u0301 opened"),
                              ("the plain\u200btiff knows", "the plaintiff knows")):
            with self.subTest(source=source):
                self.assertEqual(match(source, quote)["status"], "normalized")
        self.assertEqual(match("re-signed", "resigned")["status"], "not_found")

    def test_marked_alterations_require_review(self):
        for quote in ("... " + QUOTE, QUOTE + " ...", "… " + QUOTE, QUOTE + " …"):
            result = match(QUOTE, quote)
            self.assertEqual(result["status"], "altered")
            self.assertFalse(result["alteration_reviewed"])
        result = match("the plaintiff did file the claim", "the plaintiff [did not] file the claim")
        self.assertEqual(result["bracket_map"], [{"draft": "[did not]", "source_normalized": "did"}])
        self.assertTrue(result["requires_judgment"])

    def test_pagination(self):
        result = match("Alpha. <<pg. 10>> Bravo. <<pg. 11>>", "Bravo.", "11", footer=True)
        self.assertEqual(result["page"], 11)
        self.assertTrue(result["pincite_ok"])
        result = match("*1 Alpha. **1201 Beta. *2 Gamma. **1202 Delta. *3 Epsilon.", "Gamma.", "2")
        self.assertEqual(result["page"], 2)
        result = match("*1 Alpha **1201 Beta. *2 Gamma. **1202 Delta. *3 Epsilon.", "Alpha Beta.", "1")
        self.assertEqual(result["status"], "verbatim")
        for pin in ("¶ 12", "para. 12", "§ 12", "section 12"):
            result = match("<<pg. 2>> Some text.", "Some text.", pin)
            self.assertIsNone(result["pincite_ok"])
            self.assertIn("non_page_pincite_requires_separate_verification", result["warnings"])

    def test_complete_excerpts_and_raw_offsets(self):
        source = " ".join(f"word{n}" for n in range(150))
        result = match(source, source)
        self.assertEqual(result["match_excerpt"], source)
        raw = "prefix cafe\u0301 suffix"
        result = match(raw, "café")
        self.assertEqual(result["match_excerpt"], "cafe\u0301")
        self.assertEqual(raw[result["match_start"]:result["match_end"]], result["match_excerpt"])

    def test_lookup_outcomes(self):
        self.assertEqual(lookup_state({"status": 429}), "rate_limited")
        self.assertEqual(lookup_state({"status": 300}), "ambiguous")
        self.assertEqual(lookup_state({"status": 200, "clusters": [{}, {}]}), "ambiguous")
        self.assertEqual(lookup_state({"status": 200, "clusters": [{}]}), "matched")


class CompletionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.addCleanup(self.temp.cleanup)

    def ready(self, body_only=False, custom=False, internal=False):
        draft = self.root / ("draft.docx" if custom else "draft.md")
        if custom:
            create_docx(draft, '<w:p><w:r><w:t>Part II. Internal discussion.</w:t></w:r>' + ref(1, True) + '<w:r><w:t>*</w:t></w:r>' + ref(2) + '</w:p>',
                        note(1, "See infra Part II." if internal else "Author Authority.") + note(2, "Main Authority."))
        else:
            draft.write_text(('“' + QUOTE + '.” (Authority One, at 2).' if body_only else '“' + QUOTE + '.”[^1]\n\n[^1]: Authority One, 1 U.S. 1, 2 (2000).'))
        directory = self.root / 'run'
        result = run("init_run.py", draft, "--run-dir", directory)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads((directory / 'extraction.json').read_text())
        units, sources, verdicts, coverage = [], [], [], []
        locations = data['footnotes'] if not body_only else [{'number': None, 'text': data['paragraphs'][0]}]
        for index, location in enumerate(locations, 1):
            unit = {'unit_id': f'U{index}', 'footnote_number': location['number'], 'note_id': location.get('note_id'),
                    'source_id': f'S{index}', 'source_type': 'case', 'draft_citation_text': location['text'],
                    'resolved_source_label': 'Fixture Authority', 'draft_find_string': location['text'],
                    'caption_in_draft': 'body' if body_only else 'footnote'}
            if body_only:
                unit.update(location='body', paragraph_number=1, body_context=data['paragraphs'][0])
            else:
                unit['full_footnote'] = location['text']
                coverage.append({'footnote_number': location['number'], 'note_id': location.get('note_id'), 'status': 'reviewed', 'unit_ids': [unit['unit_id']]})
            units.append(unit)
            sources.append({'source_id': unit['source_id'], 'source_type': 'case', 'canonical_citation': 'Fixture Authority', 'status': 'retrieved', 'verification_basis': 'primary_full_text'})
            verdicts.append({'verdict_id': f'V{index}', 'unit_id': unit['unit_id'], 'status': 'verified', 'severity': 'info', 'category': 'verified_support',
                             'verification_basis': 'primary_full_text', 'evidence': 'Synthetic full text.', 'suggested_action': 'none'})
        rows(directory / 'citation-units.jsonl', units); rows(directory / 'source-ledger.jsonl', sources)
        rows(directory / 'verdicts.jsonl', verdicts); rows(directory / 'footnote-coverage.jsonl', coverage)
        rows(directory / 'body-coverage.jsonl', [{'paragraph_number': 1, 'status': 'reviewed' if body_only else 'no_citations',
             'unit_ids': ['U1'] if body_only else [], 'reason': 'Only footnote citations.'}])
        if not custom:
            prepared = read_rows(directory / 'prepared-units.jsonl')[0]
            source = directory / 'source.txt'; source.write_text('<<pg. 2>> ' + QUOTE + '.')
            items = directory / 'items.json'; items.write_text(json.dumps([{'prepared_unit_id': prepared['prepared_unit_id'], 'unit_id': 'U1', 'source_id': 'S1', 'quote': prepared['quote']}]))
            result = run('verify_quotes.py', source, '--json', items, '--output', directory / 'quote-checks.jsonl')
            self.assertEqual(result.returncode, 0, result.stderr)
        (directory / 'report.md').write_text('# Cite Check\nCreated by: Codex\nModel: test-model\nGenerated: fixture\nElapsed: fixture\nTokens: unavailable\n\n## Needs your attention\nNone.\n\n## Couldn\'t check\nNone.\n')
        self.assert_valid(directory)
        return directory

    def validate(self, directory, *args):
        path = directory / 'run-manifest.json'; manifest = json.loads(path.read_text())
        manifest.update(status='ready_for_validation', completion_target='complete')
        verdicts = read_rows(directory / 'verdicts.jsonl')
        manifest['counts'].update({status: sum(row['status'] == status for row in verdicts) for status in ('verified', 'partial', 'mismatch', 'unverified')})
        manifest['counts']['quote_checks'] = len(read_rows(directory / 'quote-checks.jsonl'))
        path.write_text(json.dumps(manifest))
        return run('validate_run.py', directory, '--require-ready', *args)

    def assert_valid(self, directory, *args):
        result = self.validate(directory, *args)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_custom_notes_and_body_citations_complete(self):
        self.ready(custom=True)

    def test_body_only_complete_and_coverage_required(self):
        directory = self.ready(body_only=True)
        rows(directory / 'body-coverage.jsonl', [])
        self.assertIn('body paragraph lacks coverage', self.validate(directory).stderr)

    def test_blockers_and_indented_candidates_cannot_be_ignored(self):
        directory = self.ready()
        path = directory / 'extraction.json'; data = json.loads(path.read_text())
        data['blocking_issues'] = ['Referenced endnotes require a normalized copy.']
        path.write_text(json.dumps(data))
        self.assertIn('extraction is blocked', self.validate(directory).stderr)
        data['blocking_issues'] = []; data['block_quote_candidates'] = [1]
        path.write_text(json.dumps(data))
        self.assertIn('indented block needs', self.validate(directory).stderr)
        coverage = read_rows(directory / 'body-coverage.jsonl')
        coverage[0].update(block_quote_review='quotation', block_quote_reason='Confirmed against the draft.')
        rows(directory / 'body-coverage.jsonl', coverage)
        self.assertIn('lacks a prepared block unit', self.validate(directory).stderr)
        prepared = read_rows(directory / 'prepared-units.jsonl'); prepared[0]['block_quote'] = True
        rows(directory / 'prepared-units.jsonl', prepared)
        self.assert_valid(directory)

    def test_not_applicable_cannot_hide_unavailable_quote(self):
        directory = self.ready()
        verdicts = read_rows(directory / 'verdicts.jsonl'); verdicts[0].update(status='not_applicable', verification_basis='metadata_only')
        sources = read_rows(directory / 'source-ledger.jsonl'); sources[0].update(status='metadata_only', verification_basis='metadata_only')
        rows(directory / 'verdicts.jsonl', verdicts); rows(directory / 'source-ledger.jsonl', sources)
        checks = read_rows(directory / 'quote-checks.jsonl'); checks[0].update(status='unavailable', reason='No full text.', unlock_path='Supply full text.')
        rows(directory / 'quote-checks.jsonl', checks)
        error = self.validate(directory).stderr
        self.assertIn('not_applicable is restricted', error)
        self.assertIn('complete_with_limits', error)

    def test_internal_reference_can_be_not_applicable_without_retrieval(self):
        directory = self.ready(custom=True, internal=True)
        paragraph = json.loads((directory / 'extraction.json').read_text())['paragraphs'][0]
        units = read_rows(directory / 'citation-units.jsonl'); units[0].update(unit_kind='internal_reference', internal_target={'paragraph_number': 1, 'text': paragraph})
        verdicts = read_rows(directory / 'verdicts.jsonl'); verdicts[0].update(status='not_applicable', reason='An internal pointer, not an external authority.')
        sources = read_rows(directory / 'source-ledger.jsonl'); sources[0].update(status='not_applicable', verification_basis='metadata_only')
        rows(directory / 'citation-units.jsonl', units); rows(directory / 'verdicts.jsonl', verdicts); rows(directory / 'source-ledger.jsonl', sources)
        self.assert_valid(directory)
        units[0]['internal_target']['text'] = 'Invented target'
        rows(directory / 'citation-units.jsonl', units)
        self.assertIn('not_applicable is restricted', self.validate(directory).stderr)

    def test_weak_quote_evidence_and_false_metadata_records_rejected(self):
        directory = self.ready()
        verdicts = read_rows(directory / 'verdicts.jsonl'); verdicts[0]['verification_basis'] = 'snippet_only'
        rows(directory / 'verdicts.jsonl', verdicts)
        self.assertIn('requires retrieved full text', self.validate(directory).stderr)
        verdicts[0].update(status='mismatch', category='metadata_error', severity='medium', verification_basis='secondary_reproduction', draft_find_string='Authority One',
                           metadata_record={'opened': True, 'exact_work_checked': True, 'record_type': 'official_case_record', 'location': 'https://www.google.com/search?q=Authority', 'fields': ['year']})
        rows(directory / 'verdicts.jsonl', verdicts)
        error = self.validate(directory).stderr
        self.assertIn('secondary reproductions', error)
        self.assertIn('not search results', error)

    def test_nonpage_pin_can_use_explicit_authoritative_confirmation(self):
        directory = self.ready()
        units = read_rows(directory / 'citation-units.jsonl'); units[0]['pincite'] = '¶ 12'; rows(directory / 'citation-units.jsonl', units)
        self.assertIn('lacks a check for its pincite', self.validate(directory).stderr)
        verdicts = read_rows(directory / 'verdicts.jsonl')
        verdicts[0]['pincite_verification'] = {'pincite': '¶ 12', 'confirmed': True, 'pagination_convention': 'paragraph_number', 'evidence_location': 'source.txt, paragraph 12', 'evidence': QUOTE}
        rows(directory / 'verdicts.jsonl', verdicts)
        self.assert_valid(directory)

    def test_ooxml_verifier_and_optional_gate_agree(self):
        directory = self.ready()
        report = directory / 'report.md'; docx = directory / 'report.docx'
        create_docx(docx, '<w:p><w:r><w:t>' + escape(report.read_text()) + '</w:t></w:r></w:p>')
        result = run('verify_docx_ooxml.py', docx, '--markdown', report, '--output', directory / 'docx-verification.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assert_valid(directory, '--require-docx')
        docx.unlink()
        self.assert_valid(directory)
        self.assertIn('missing nonempty report.docx', self.validate(directory, '--require-docx').stderr)


if __name__ == '__main__':
    unittest.main()
