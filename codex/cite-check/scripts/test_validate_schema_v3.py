#!/usr/bin/env python3
"""Integration test for schema-v3 deterministic quote-check readiness."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
INITIALIZER = HERE / "init_run.py"
MATCHER = HERE / "verify_quotes.py"
VALIDATOR = HERE / "validate_run.py"


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        draft = root / "draft.md"
        draft.write_text(
            'The court stated that “the limitations period does not begin to run '
            'until the plaintiff knows of the injury.”[^1]\n\n'
            "[^1]: Test Authority, 1 U.S. 1, 2 (2000).\n",
            encoding="utf-8",
        )
        run = root / ".codex-memo" / "runs" / "cite-test"
        initialized = subprocess.run(
            [
                sys.executable,
                str(INITIALIZER),
                str(draft),
                "--run-dir",
                str(run),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert initialized.returncode == 0, initialized.stderr
        prepared = json.loads((run / "prepared-units.jsonl").read_text(encoding="utf-8"))
        footnote = "Test Authority, 1 U.S. 1, 2 (2000)."
        unit = {
            "unit_id": "U1",
            "footnote_number": 1,
            "source_id": "S1",
            "source_type": "case",
            "draft_citation_text": footnote,
            "resolved_source_label": "Test Authority",
            "draft_find_string": "Test Authority",
            "caption_in_draft": "footnote",
            "full_footnote": footnote,
            "body_context": prepared["body_context"],
            "pincite": "2",
        }
        source = {
            "source_id": "S1",
            "source_type": "case",
            "canonical_citation": "Test Authority, 1 U.S. 1 (2000)",
            "status": "retrieved",
            "verification_basis": "primary_full_text",
        }
        verdict = {
            "verdict_id": "V1",
            "unit_id": "U1",
            "status": "verified",
            "severity": "info",
            "category": "quote_correct",
            "verification_basis": "primary_full_text",
            "evidence": "Deterministic source-text match.",
            "suggested_action": "none",
        }
        write_jsonl(run / "citation-units.jsonl", [unit])
        write_jsonl(run / "footnote-coverage.jsonl", [
            {"footnote_number": 1, "status": "reviewed", "unit_ids": ["U1"]}
        ])
        write_jsonl(run / "body-coverage.jsonl", [{
            "paragraph_number": 1, "status": "no_citations", "unit_ids": [],
            "reason": "The quotation's citation is inventoried in footnote 1."
        }])
        write_jsonl(run / "source-ledger.jsonl", [source])
        write_jsonl(run / "verdicts.jsonl", [verdict])

        source_text = run / "cached-sources" / "S1.txt"
        source_text.parent.mkdir(parents=True)
        source_text.write_text(
            "<<pg. 2>> the limitations period does not begin to run until "
            "the plaintiff knows of the injury.",
            encoding="utf-8",
        )
        items = run / "S1-items.json"
        items.write_text(
            json.dumps(
                [
                    {
                        "prepared_unit_id": prepared["prepared_unit_id"],
                        "unit_id": "U1",
                        "source_id": "S1",
                        "quote": prepared["quote"],
                        "pincite": "2",
                    }
                ]
            ),
            encoding="utf-8",
        )
        matched = subprocess.run(
            [
                sys.executable,
                str(MATCHER),
                str(source_text),
                "--json",
                str(items),
                "--output",
                str(run / "quote-checks.jsonl"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert matched.returncode == 0, matched.stderr

        (run / "report.md").write_text(
            "# Cite Check\n\n"
            "Created by: Codex\nModel: test-model\nGenerated: 2026-07-22 12:00:00 CDT\n"
            "Elapsed: 1 second\nTokens: unavailable (runtime did not expose exact usage)\n\n"
            "## Needs your attention\n\nNone.\n\n## Couldn't check\n\nNone.\n",
            encoding="utf-8",
        )
        manifest_path = run / "run-manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["schema_version"] = 5  # Preserve pre-v6 fixture coverage.
        manifest["status"] = "ready_for_validation"
        manifest["completion_target"] = "complete"
        manifest["counts"].update(
            {
                "quote_checks": 1,
                "verified": 1,
                "partial": 0,
                "mismatch": 0,
                "unverified": 0,
            }
        )
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

        valid = subprocess.run(
            [
                sys.executable,
                str(VALIDATOR),
                str(run),
                "--require-ready",
                "--mark-complete",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert valid.returncode == 0, valid.stdout + valid.stderr

        # A sibling source's match is evidence of possible misattribution, not
        # a match in the authority that the citation unit actually names.
        check = json.loads((run / "quote-checks.jsonl").read_text(encoding="utf-8"))
        sibling = dict(source, source_id="S2", canonical_citation="Different Authority")
        write_jsonl(run / "source-ledger.jsonl", [source, sibling])
        write_jsonl(run / "quote-checks.jsonl", [dict(check, source_id="S2")])
        wrong_source = subprocess.run(
            [sys.executable, str(VALIDATOR), str(run), "--require-ready"],
            capture_output=True, text=True, check=False,
        )
        assert wrong_source.returncode == 1
        assert "lacks a deterministic match" in wrong_source.stderr
        write_jsonl(run / "source-ledger.jsonl", [source])
        write_jsonl(run / "quote-checks.jsonl", [check])

        (run / "quote-checks.jsonl").write_text("", encoding="utf-8")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["counts"]["quote_checks"] = 0
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        invalid = subprocess.run(
            [sys.executable, str(VALIDATOR), str(run), "--require-ready"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert invalid.returncode == 1
        assert "prepared quotation lacks quote check" in invalid.stderr

    print("schema-v3 quote-check tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
