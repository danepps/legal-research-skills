#!/usr/bin/env python3
"""Synthetic, offline local-copy regressions. Fixtures remain in hidden scratch."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from local_lookup import compact, merge, run
from local_sources import digest, discover_folders, index_file
import zotero_lookup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
SCRATCH = ROOT / ".codex-memo" / "local-source-tests"
SCRATCH.mkdir(parents=True, exist_ok=True)
CITE = "Mina Vale, Copper Lanterns and Silent Rivers, 12 Imaginary L. Rev. 41, 42 (2024)."
SOURCE = {"key": "copper", "kind": "article", "cite": CITE}
QUOTE = "The copper lantern illuminates every silent river beneath the invented bridge."
TEXT = "Imaginary Law Review\nVolume 12 (2024)\nCopper Lanterns and Silent Rivers\nMina Vale\n41\fImaginary Law Review\n" + QUOTE + "\n42\f"


def synthetic_pdf(text=True):
    """Minimal self-authored PDF, with offsets computed from these literal bytes."""
    stream = ("BT /F1 12 Tf 50 750 Td (Copper Lanterns and Silent Rivers) Tj "
              "0 -20 Td (Mina Vale) Tj 0 -20 Td (" + QUOTE + ") Tj ET").encode() if text else b""
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"]
    data, offsets = b"%PDF-1.4\n", [0]
    for i, obj in enumerate(objs, 1):
        offsets.append(len(data)); data += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    start = len(data)
    data += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    data += b"".join(f"{off:010d} 00000 n \n".encode() for off in offsets[1:])
    return data + f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n".encode()


class LocalTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(dir=SCRATCH))
        config = patch("source_options.default_file", return_value=self.root / "unused-setting")
        config.start(); self.addCleanup(config.stop)
        self.folder = self.root / "Sources"; self.folder.mkdir()
        self.cache = self.root / "cache"

    def file(self, name="copy.txt", text=TEXT):
        path = self.folder / name; path.write_text(text, encoding="utf-8"); return path

    def lookup(self):
        return run([SOURCE], [self.folder], self.cache)

    def test_clean_match_and_verification(self):
        path = self.file(); before = path.read_bytes()
        result = self.lookup(); hit = result["sources"]["copper"]
        self.assertTrue(hit["matched"])
        self.assertEqual(hit["fileSha256"], digest(path))
        self.assertEqual(hit["textPages"], 2)
        self.assertEqual(hit["version"]["kind"], "published")
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(compact(result)["copper"]["file"], "copy.txt")
        import verify_quotes
        self.assertIn(QUOTE, Path(hit["textPath"]).read_text())

    def test_filename_cannot_establish_identity(self):
        self.file("Mina Vale Copper Lanterns and Silent Rivers 2024.txt", "Unrelated Desert Horses\nOscar Reed\nSome different text.")
        self.assertFalse(self.lookup()["sources"]["copper"]["matched"])

    def test_different_published_copies_are_ambiguous(self):
        self.file(); self.file("second.md", TEXT.replace(QUOTE, QUOTE + " Different text."))
        row = self.lookup()["sources"]["copper"]
        self.assertFalse(row["matched"]); self.assertEqual(len(row["candidates"]), 2)

    def test_weak_title_or_wrong_given_name_cannot_match(self):
        self.file(text=TEXT.replace("Mina Vale", "Oscar Vale"))
        self.assertFalse(self.lookup()["sources"]["copper"]["matched"])
        self.file(text=TEXT.replace("Copper Lanterns and Silent Rivers", "Copper Lanterns and Silent Rivers Reconsidered"))
        self.assertFalse(self.lookup()["sources"]["copper"]["matched"])

    def test_reference_entry_is_not_title_page(self):
        self.file(text="References\n" + CITE + "\nMina Vale\n")
        self.assertFalse(self.lookup()["sources"]["copper"]["matched"])

    def test_working_paper_preserves_version_and_pin_limit(self):
        self.file(text="Working paper, forthcoming 2025\nCopper Lanterns and Silent Rivers\nMina Vale\n" + QUOTE)
        row = self.lookup()["sources"]["copper"]
        self.assertTrue(row["matched"])
        self.assertEqual(row["version"]["kind"], "working_paper")
        self.assertFalse(row["version"]["pinciteEligible"])
        self.assertIn("not judged", row["version"]["pinciteReason"])

    def test_conflicting_publication_labels_are_disclosed(self):
        self.file(text=TEXT.replace("Volume 12 (2024)", "Volume 9 (2023)"))
        row = self.lookup()["sources"]["copper"]
        self.assertTrue(row["matched"])
        self.assertEqual(row["version"]["kind"], "unknown")
        self.assertFalse(row["version"]["pinciteEligible"])
        self.assertIn("2023", row["versionNote"])
        self.assertEqual(len(row["confirm"]), 2)

    def test_book_and_internet_and_out_of_scope(self):
        self.file(text="The Amber Observatory\nNora Moss\nWorking paper\n2025\nInvented prose.")
        cites = self.root / "cites.json"
        cites.write_text(json.dumps([
            {"key": "b", "kind": "book", "cite": "Nora Moss, The Amber Observatory 23 (2025)."},
            {"key": "i", "kind": "internet", "cite": "Nora Moss, The Amber Observatory (2025), https://example.invalid/paper"},
            {"key": "c", "kind": "case", "cite": CITE},
            {"key": "s", "kind": "statute", "cite": CITE}]))
        sources = zotero_lookup.load_sources({"cites": [str(cites)]})
        result = run(sources, [self.folder], self.cache)
        self.assertEqual(set(result["sources"]), {"b", "i"})
        self.assertTrue(all(r["matched"] for r in result["sources"].values()))

    def test_unreadable_and_missing_pdftotext(self):
        self.file("empty.txt", "")
        pdf = self.folder / "scan.pdf"; pdf.write_bytes(synthetic_pdf(False))
        with patch("local_sources.shutil.which", return_value=None):
            result = self.lookup()
        self.assertEqual(result["stats"]["unreadable"], ["empty.txt", "scan.pdf"])
        self.assertIn("pdftotext unavailable", result["files"][1]["reason"])

    @unittest.skipUnless(shutil.which("pdftotext"), "pdftotext not installed")
    def test_synthetic_pdf_and_image_only_pdf(self):
        pdf = self.folder / "article.pdf"; pdf.write_bytes(synthetic_pdf())
        scan = self.folder / "scan.pdf"; scan.write_bytes(synthetic_pdf(False))
        result = self.lookup()
        self.assertTrue(result["sources"]["copper"]["matched"])
        self.assertEqual(result["stats"]["unreadable"], ["scan.pdf"])
        with patch("local_sources.subprocess.Popen", side_effect=AssertionError("re-extracted")):
            again = self.lookup()
        self.assertEqual(again["stats"]["cacheReused"], 2)

    def test_cache_reuse_and_hash_invalidation(self):
        path = self.file(); first = self.lookup()["sources"]["copper"]
        cached = Path(first["textPath"]); before = cached.stat().st_mtime_ns
        result = self.lookup()
        self.assertEqual(result["stats"]["cacheReused"], 1)
        self.assertEqual(cached.stat().st_mtime_ns, before)
        path.write_text(TEXT + "new words")
        self.assertNotEqual(self.lookup()["sources"]["copper"]["fileSha256"], first["fileSha256"])

    def test_folder_discovery_precedence_no_loose_files(self):
        draft = self.root / "draft.md"; draft.write_text("synthetic")
        self.assertEqual(discover_folders(draft)[0], [self.folder])
        (self.root / "AGENTS.md").write_text("Source folder: explicit\n")
        self.assertEqual(discover_folders(draft)[0], [self.root / "explicit"])
        self.assertEqual(discover_folders(draft, folders=[str(self.folder)])[0], [self.folder])
        self.assertEqual(discover_folders(self.folder / "draft.md")[0], [])
        # Amendment 2 permits an excluded cache below the source folder.
        result = run([SOURCE], [self.folder], self.folder / "cache")
        self.assertEqual(result["stats"]["filesIndexed"], 0)

    def test_merge_retains_local_hit_and_candidates(self):
        self.file(); result = self.lookup()
        remote = {"sources": {"copper": {"matched": True, "title": "wrong"}}}
        self.assertEqual(merge(result, remote)["sources"]["copper"]["origin"], "local")
        with patch.object(zotero_lookup, "dump_library", side_effect=AssertionError("network")):
            self.assertEqual(zotero_lookup.run([], [{}], str(self.cache))["stats"]["sources"], 0)

    @unittest.skipUnless(shutil.which("node"), "node not installed")
    def test_workflow_with_local_hit_and_no_zotero(self):
        self.file(text="Working paper\nCopper Lanterns and Silent Rivers\nMina Vale\n" + QUOTE)
        draft = self.root / "draft.md"
        draft.write_text('The author writes "' + QUOTE + '".[^1] Again, "' + QUOTE + '".[^2]\n\n[^1]: ' + CITE + '\n[^2]: ' + CITE)
        extract = self.root / "extract.json"
        def script(name, *args):
            return subprocess.run([sys.executable, str(HERE / name), *map(str, args)],
                                  check=True, capture_output=True, text=True).stdout
        script("extract_cites.py", draft, extract)
        units = json.loads(script("prepare_units.py", extract, self.root / "units.json"))
        ledger = json.loads(script("citation_ledger.py", extract, "--compact"))
        ledger_path = self.root / "ledger.json"; ledger_path.write_text(json.dumps(ledger))
        report_path = self.root / "lookup.json"
        script("local_lookup.py", report_path, "--secondary", ledger_path, "--draft", draft,
               "--cache-dir", self.cache)
        report = json.loads(report_path.read_text())
        hit_map = json.loads(script("local_lookup.py", report_path, "--compact"))
        key = ledger["secondary"][0]["key"]
        self.assertTrue(json.loads(script("local_lookup.py", report_path, "--get", key))["matched"])
        data = json.loads(extract.read_text())
        args = {"skillsDir": str(HERE.parents[1]), "extractPath": str(extract), "draftName": "synthetic",
                "footnoteCount": data["footnote_count"], "unitCount": units["unit_count"], "unitNotes": units["unit_notes"],
                "caseCites": [], "supraProblems": data["supra_problem_candidates"], "formChecks": data["form_checks"],
                "ledger": ledger["instances"], "secondaryCites": ledger["secondary"],
                "deep": False, "history": False, "zotero": False, "support": False,
                "sourceHits": hit_map, "sourceLookupPath": str(report_path), "sourceLookupSummary": report["stats"],
                "testQuote": QUOTE, "python": sys.executable, "testId": 1, "unitIds": [1]}
        args_path = self.root / "args.json"; args_path.write_text(json.dumps(args))
        proc = subprocess.run([shutil.which("node"), str(HERE / "workflow_quote_harness.mjs"),
                               str(HERE.parent / "cite-check.workflow.js"), str(args_path), "local-only"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        result = json.loads(proc.stdout.splitlines()[-1])
        self.assertTrue(any(a.startswith("zotero-sweep") for a in result["agents"]))
        self.assertFalse(any(a.startswith("exist-secondary") for a in result["agents"]))
        self.assertEqual(result["counts"]["verbatim"], 1)
        self.assertEqual(result["sweepCommands"], [[str(HERE / "zotero_sweep.py"), str(extract), str(report_path), "--ids", "1"]])
        prompts = "\n".join(p["prompt"] for p in result["prompts"])
        self.assertIn("LOCAL COPY: copy.txt", prompts)
        self.assertIn("Working-paper/forthcoming/manuscript marker", prompts)
        self.assertNotIn("NOT in any", prompts)
        self.assertNotIn("Zotero undefined", prompts)
        self.assertIn("pincite not judged by the local/Zotero text sweep", prompts)


if __name__ == "__main__":
    unittest.main()
