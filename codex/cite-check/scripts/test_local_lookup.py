#!/usr/bin/env python3
"""Synthetic offline tests of folder lookup, provenance, and readiness controls."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from local_lookup import (apply_lookup, build_lookup, disclosure_lines, parse_citation,
                          validate_local_sources)
from local_sources import discover_folders, digest
from cache_recovery import source_state
from prepare_source_bundle import build_bundle

HERE = Path(__file__).resolve().parent
SCRATCH = HERE.parents[2] / ".codex-memo" / "codex-local-tests"
SCRATCH.mkdir(parents=True, exist_ok=True)
CITE = "Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41, 42 (2024)."
QUOTE = "The copper lantern illuminates every silent river beneath the invented bridge."
TEXT = "Imaginary Law Review\nVolume 12 (2024)\nCopper Lanterns and Silent Rivers\nMina Vale\n41\f" + QUOTE + "\n42\f"


def pdf_bytes(with_text=True):
    stream = b"BT /F1 12 Tf 50 750 Td (Copper Lanterns and Silent Rivers) Tj 0 -20 Td (Mina Vale) Tj ET" if with_text else b""
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    data, offsets = b"%PDF-1.4\n", []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += b"xref\n0 6\n0000000000 65535 f \n"
    data += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets)
    return data + f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=SCRATCH))
        config = patch("source_options.default_file", return_value=self.root / "unused-setting")
        config.start(); self.addCleanup(config.stop)
        self.folder = self.root / "sOuRcEs"; self.folder.mkdir()
        self.run = self.root / "run"; self.run.mkdir()
        self.draft = self.root / "draft.md"; self.draft.write_text("Synthetic draft")
        self.manifest = {"draft_path": str(self.draft), "original_draft_path": str(self.draft),
                         "library_access": {"selection": {"status": "skipped"}}}
        self.sources = [{"source_id": "S1", "source_type": "article", "canonical_citation": CITE,
                         "status": "unavailable", "verification_basis": "unavailable"}]
        self.units = [{"unit_id": "U1", "source_id": "S1", "pincite": "42", "footnote_number": 1,
                       "resolved_source_label": CITE, "draft_citation_text": CITE, "source_type": "article"}]

    def file(self, name="copy.md", text=TEXT):
        path = self.folder / name; path.write_text(text); return path

    def lookup(self):
        return build_lookup(self.sources, [self.folder], self.run / "cached-sources" / "local")

    def save(self):
        (self.run / "run-manifest.json").write_text(json.dumps(self.manifest))
        for name, rows in (("source-ledger.jsonl", self.sources), ("citation-units.jsonl", self.units)):
            (self.run / name).write_text("".join(json.dumps(r) + "\n" for r in rows))

    def apply(self, lookup):
        (self.run / "local-lookup.json").write_text(json.dumps(lookup))
        apply_lookup(self.run, self.manifest, self.sources, lookup)

    def test_clean_match_contract_and_skip_zotero(self):
        original = self.file(); before = digest(original)
        lookup = self.lookup(); self.apply(lookup)
        source = self.sources[0]
        self.assertEqual(source["source_origin"], "local_folder")
        self.assertEqual(source["local_copy"]["sha256"], before)
        self.assertEqual(source["source_sha256"], digest(source["source_path"]))
        self.assertEqual(source_state(self.run, source, {"status": "skipped"})["status"], "text_cached")
        self.assertEqual(source_state(self.run, source, {"status": "selected", "id": "group:9"})["status"], "text_cached")
        self.assertEqual(validate_local_sources(self.run, self.manifest, self.sources, self.units, [], "\n".join(disclosure_lines(lookup))), [])
        self.assertEqual(digest(original), before)

    def test_filename_and_wrong_author_and_weak_match(self):
        self.file("Mina Vale Copper Lanterns and Silent Rivers.txt", "A Different Work\nNora Moss")
        self.assertFalse(self.lookup()["sources"]["S1"]["matched"])
        self.file("Mina Vale Copper Lanterns and Silent Rivers.txt", TEXT.replace("Mina Vale", "Oscar Vale"))
        self.assertFalse(self.lookup()["sources"]["S1"]["matched"])
        self.file("Mina Vale Copper Lanterns and Silent Rivers.txt", TEXT.replace("Silent Rivers", "Silent Rivers Reconsidered"))
        self.assertFalse(self.lookup()["sources"]["S1"]["matched"])

    def test_different_published_copies_are_ambiguous(self):
        self.file(); self.file("another.txt", TEXT.replace(QUOTE, QUOTE + " Different text."))
        result = self.lookup()["sources"]["S1"]
        self.assertFalse(result["matched"]); self.assertEqual(len(result["candidates"]), 2)

    def test_reference_not_identity(self):
        self.file(text="References\n" + CITE + "\nMina Vale")
        self.assertFalse(self.lookup()["sources"]["S1"]["matched"])

    def test_working_paper_quote_can_match_but_pin_cannot_pass(self):
        self.file(text="Copper Lanterns and Silent Rivers\nMina Vale\nWorking paper\n" + QUOTE)
        lookup = self.lookup(); self.apply(lookup)
        report = "\n".join(disclosure_lines(lookup))
        self.assertEqual(self.sources[0]["local_copy"]["version"]["kind"], "working_paper")
        self.sources[0]["local_identity_review"] = {"status": "confirmed", "locator": "first content page", "reason": "Synthetic title and byline inspected."}
        verdicts = [{"unit_id": "U1", "status": "verified", "category": "verified_quote"}]
        self.assertTrue(any("printed pincites" in e for e in validate_local_sources(self.run, self.manifest, self.sources, self.units, verdicts, report)))
        verdicts[0]["status"] = "partial"
        self.assertEqual(validate_local_sources(self.run, self.manifest, self.sources, self.units, verdicts, report), [])
        items = self.run / "items.json"; items.write_text(json.dumps([{"prepared_unit_id": "P1", "unit_id": "U1", "source_id": "S1", "quote": QUOTE}]))
        out = self.run / "quotes.jsonl"
        proc = subprocess.run([sys.executable, str(HERE / "verify_quotes.py"), self.sources[0]["source_path"],
                               "--json", str(items), "--output", str(out)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        row = json.loads(out.read_text())
        self.assertEqual(row["status"], "verbatim")
        self.assertEqual(row["source_sha256"], self.sources[0]["source_sha256"])

    def test_conflicting_publication_labels_are_disclosed(self):
        self.file(text=TEXT.replace("Volume 12 (2024)", "Volume 9 (2023)"))
        result = self.lookup()["sources"]["S1"]
        self.assertTrue(result["matched"])
        version = result["local_copy"]["version"]
        self.assertEqual(version["kind"], "unknown")
        self.assertFalse(version["pinciteEligible"])
        self.assertIn("2023", version["note"])

    def test_unreadable_and_cache_reuse(self):
        self.file(); self.file("empty.txt", "")
        first = self.lookup(); hit = first["sources"]["S1"]
        path = Path(hit["source_path"]); before = path.stat().st_mtime_ns
        second = self.lookup()
        self.assertEqual(second["stats"]["unreadable"], ["empty.txt"])
        self.assertEqual(second["stats"]["cache_reused"], 2)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.file(text=TEXT + "changed")
        self.assertNotEqual(self.lookup()["sources"]["S1"]["local_copy"]["sha256"], hit["local_copy"]["sha256"])

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_synthetic_pdf_cache_and_scan(self):
        (self.folder / "article.pdf").write_bytes(pdf_bytes())
        (self.folder / "scan.pdf").write_bytes(pdf_bytes(False))
        lookup = self.lookup()
        self.assertTrue(lookup["sources"]["S1"]["matched"])
        self.assertEqual(lookup["stats"]["unreadable"], ["scan.pdf"])
        with patch("local_sources.subprocess.Popen", side_effect=AssertionError("re-extracted")):
            self.assertEqual(self.lookup()["stats"]["cache_reused"], 2)

    def test_no_pdftotext_and_readonly_folder(self):
        (self.folder / "article.pdf").write_bytes(pdf_bytes())
        with patch("local_sources.shutil.which", return_value=None):
            self.assertEqual(self.lookup()["stats"]["unreadable"], ["article.pdf"])
        result = build_lookup(self.sources, [self.folder], self.folder / "cache")
        self.assertEqual(result["stats"]["files_indexed"], 1)

    def test_books_internet_scope_and_discovery(self):
        self.file(text="The Amber Observatory\nNora Moss\nWorking paper 2025")
        self.sources = [{"source_id": str(i), "source_type": kind, "canonical_citation": "Nora Moss, The Amber Observatory 23 (2025)."}
                        for i, kind in enumerate(("book", "internet", "case", "statute"))]
        result = self.lookup()
        self.assertEqual(set(result["sources"]), {"0", "1"})
        self.assertTrue(all(r["matched"] for r in result["sources"].values()))
        self.assertEqual(discover_folders(self.draft)[0], [self.folder])
        (self.root / "CLAUDE.md").write_text("Source folder: somewhere\n")
        self.assertEqual(discover_folders(self.draft)[0], [self.root / "somewhere"])
        self.assertEqual(discover_folders(self.draft, folders=[str(self.folder)])[0], [self.folder])

    def test_readiness_rejects_changed_files_and_missing_disclosure(self):
        original = self.file(); lookup = self.lookup(); self.apply(lookup)
        self.assertTrue(validate_local_sources(self.run, self.manifest, self.sources, self.units, [], ""))
        original.write_text("changed")
        errors = validate_local_sources(self.run, self.manifest, self.sources, self.units, [], "\n".join(disclosure_lines(lookup)))
        self.assertTrue(any("original local copy changed" in e for e in errors))

    def test_readiness_rejects_reassigned_identity(self):
        self.file(); lookup = self.lookup(); self.apply(lookup)
        self.sources[0]["canonical_citation"] = "Nora Moss, The Amber Observatory (2025)."
        errors = validate_local_sources(self.run, self.manifest, self.sources, self.units, [], "\n".join(disclosure_lines(lookup)))
        self.assertTrue(any("lookup provenance" in e for e in errors))

    def test_cli_and_bundle_carry_local_copy(self):
        self.file(); self.manifest.pop("library_access"); self.save()
        proc = subprocess.run([sys.executable, str(HERE / "local_lookup.py"), str(self.run), "--apply"], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        bundle = build_bundle(self.run, "S1")
        self.assertEqual(bundle["sources"][0]["local_copy"]["filename"], "copy.md")
        self.assertIn('"matched": 1', proc.stdout)

    def test_apply_does_not_overwrite_other_retrieved_evidence(self):
        self.file(); lookup = self.lookup()
        self.sources[0]["source_path"] = "existing.txt"
        with self.assertRaises(ValueError):
            self.apply(lookup)


if __name__ == "__main__":
    unittest.main()
