#!/usr/bin/env python3
"""Exercise completion gates with a two-authority offline draft."""

from __future__ import annotations

import copy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def write_rows(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def read_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def synchronize(run: Path, *, target: str = "complete") -> None:
    path = run / "run-manifest.json"
    manifest = json.loads(path.read_text())
    manifest.update(status="ready_for_validation", completion_target=target)
    verdicts = read_rows(run / "verdicts.jsonl")
    manifest["counts"].update({
        status: sum(row.get("status") == status for row in verdicts)
        for status in ("verified", "partial", "mismatch", "unverified")
    })
    manifest["counts"]["quote_checks"] = 0
    write_json(path, manifest)


def validate(run: Path, expected: str | None = None) -> None:
    process = subprocess.run(
        [sys.executable, str(HERE / "validate_run.py"), str(run), "--require-ready", "--mark-complete"],
        capture_output=True, text=True, check=False,
    )
    if expected:
        assert process.returncode == 1, process.stdout + process.stderr
        assert expected in process.stderr, process.stderr
        assert json.loads((run / "run-manifest.json").read_text())["status"] == "ready_for_validation"
    else:
        assert process.returncode == 0, process.stdout + process.stderr


def main() -> int:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        draft = root / "draft.md"
        draft.write_text(
            "First proposition.[^1]\n\nSecond proposition.[^2]\n\n"
            "[^1]: Authority One, 1 U.S. 1 (2000).\n"
            "[^2]: Authority Two, 2 U.S. 2 (2001).\n", encoding="utf-8",
        )
        baseline = root / "baseline"
        subprocess.run(
            [sys.executable, str(HERE / "init_run.py"), str(draft), "--run-dir", str(baseline)],
            capture_output=True, text=True, check=True,
        )
        assert all(row["status"] == "pending" for row in read_rows(baseline / "footnote-coverage.jsonl"))
        units, sources, verdicts, coverage = [], [], [], []
        for number, title in ((1, "One"), (2, "Two")):
            text = f"Authority {title}, {number} U.S. {number} ({1999 + number})."
            units.append({
                "unit_id": f"U{number}", "footnote_number": number,
                "source_id": f"S{number}", "source_type": "case",
                "draft_citation_text": text, "full_footnote": text,
                "resolved_source_label": f"Authority {title}",
                "draft_find_string": f"Authority {title}", "caption_in_draft": "footnote",
            })
            sources.append({
                "source_id": f"S{number}", "source_type": "case", "canonical_citation": text,
                "status": "retrieved", "verification_basis": "primary_full_text",
            })
            verdicts.append({
                "verdict_id": f"V{number}", "unit_id": f"U{number}", "status": "verified",
                "severity": "info", "category": "support_correct",
                "verification_basis": "primary_full_text", "evidence": "Offline fixture passage.",
                "suggested_action": "none",
            })
            coverage.append({"footnote_number": number, "status": "reviewed", "unit_ids": [f"U{number}"]})
        for name, rows in (
            ("citation-units", units), ("source-ledger", sources),
            ("verdicts", verdicts), ("footnote-coverage", coverage),
        ):
            write_rows(baseline / f"{name}.jsonl", rows)
        (baseline / "report.md").write_text(
            "# Cite Check\n\nCreated by: Codex\nModel: test-model\n"
            "Generated: 2026-10-19 12:00 CDT\nElapsed: 1 second\nTokens: unavailable\n\n"
            "## Needs your attention\n\nNone.\n\n## Couldn't check\n\nNone.\n",
            encoding="utf-8",
        )
        synchronize(baseline)
        validate(baseline)

        def variant(name: str) -> Path:
            destination = root / name
            shutil.copytree(baseline, destination)
            synchronize(destination)
            return destination

        omitted = variant("omitted")
        write_rows(omitted / "citation-units.jsonl", units[:1])
        write_rows(omitted / "source-ledger.jsonl", sources[:1])
        write_rows(omitted / "verdicts.jsonl", verdicts[:1])
        write_rows(omitted / "footnote-coverage.jsonl", coverage[:1])
        synchronize(omitted)
        validate(omitted, "footnote lacks coverage review: 2")

        pending = variant("pending")
        write_rows(pending / "footnote-coverage.jsonl", [coverage[0], {
            "footnote_number": 2, "status": "pending", "unit_ids": []
        }])
        validate(pending, "footnote has not been reviewed")

        for field, value in (("status", "verifed"), ("severity", "hgh")):
            invalid = variant(field)
            changed = copy.deepcopy(verdicts)
            changed[0][field] = value
            write_rows(invalid / "verdicts.jsonl", changed)
            synchronize(invalid)
            validate(invalid, f"invalid {field}")

        duplicate = variant("duplicate")
        write_rows(duplicate / "verdicts.jsonl", verdicts + [dict(verdicts[0], verdict_id="V3")])
        synchronize(duplicate)
        validate(duplicate, "exactly one verdict per citation unit")

        metadata = variant("metadata")
        changed = copy.deepcopy(verdicts)
        changed[0].update(status="mismatch", severity="medium", category="metadata_error",
                          draft_find_string="Authority One", suggested_action="Correct the year.")
        write_rows(metadata / "verdicts.jsonl", changed)
        synchronize(metadata)
        validate(metadata, "lacks metadata_record")
        changed[0]["metadata_record"] = {
            "opened": True, "exact_work_checked": True, "record_type": "search_snippet",
            "location": "https://example.test/search", "fields": ["year"],
        }
        write_rows(metadata / "verdicts.jsonl", changed)
        validate(metadata, "unsupported metadata record type")
        changed[0]["metadata_record"].update(record_type="official_case_record",
                                             location="https://example.test/official-opinion")
        write_rows(metadata / "verdicts.jsonl", changed)
        validate(metadata)

        synchronize(metadata)
        changed[0]["metadata_record"].update(record_type="library_catalog_record", fields=["author_order"])
        write_rows(metadata / "verdicts.jsonl", changed)
        validate(metadata, "author-order correction requires a title or landing page")
        changed[0]["metadata_record"]["record_type"] = "pdf_first_page"
        write_rows(metadata / "verdicts.jsonl", changed)
        validate(metadata)

        for label, delta in (("numeric", 1), ("string", "1"), ("missing", None)):
            corrected = variant(f"onepage-{label}")
            changed = copy.deepcopy(verdicts)
            changed[0].update(status="mismatch", severity="medium", category="pincite_error",
                              pagination_convention="printed_page", draft_find_string="Authority One")
            if delta is not None:
                changed[0]["page_delta"] = delta
            write_rows(corrected / "verdicts.jsonl", changed)
            synchronize(corrected)
            validate(corrected, "lacks required verifier audit")
            write_rows(corrected / "verifier-audit.jsonl", [{
                "verdict_id": "V1", "audit_status": "confirmed", "evidence": "Independent page inspection."
            }])
            validate(corrected)

        unavailable = variant("unavailable")
        changed = copy.deepcopy(verdicts)
        changed[1].update(status="unverified", severity="low", verification_basis="unavailable",
                          draft_find_string="Authority Two", evidence="Retrieval failed.")
        unavailable_sources = copy.deepcopy(sources)
        unavailable_sources[1].update(status="unavailable", verification_basis="unavailable")
        write_rows(unavailable / "verdicts.jsonl", changed)
        write_rows(unavailable / "source-ledger.jsonl", unavailable_sources)
        synchronize(unavailable)
        validate(unavailable, "complete_with_limits")
        synchronize(unavailable, target="complete_with_limits")
        validate(unavailable, "lacks unlock_path")
        changed[1]["unlock_path"] = None
        unavailable_sources[1].update(reason=None, unlock_path=None)
        write_rows(unavailable / "verdicts.jsonl", changed)
        write_rows(unavailable / "source-ledger.jsonl", unavailable_sources)
        validate(unavailable, "lacks unlock_path")
        changed[1]["unlock_path"] = "Supply the full opinion."
        unavailable_sources[1].update(reason="Retrieval failed.", unlock_path="Supply the full opinion.")
        write_rows(unavailable / "verdicts.jsonl", changed)
        write_rows(unavailable / "source-ledger.jsonl", unavailable_sources)
        validate(unavailable, "omits unchecked item")
        with (unavailable / "report.md").open("a") as output:
            output.write("\nU2; S2: Retrieval failed. Supply the full opinion.\n")
        validate(unavailable)
        assert json.loads((unavailable / "run-manifest.json").read_text())["status"] == "complete_with_limits"

        legacy = variant("legacy-v3")
        manifest = json.loads((legacy / "run-manifest.json").read_text())
        manifest["schema_version"] = 3
        write_json(legacy / "run-manifest.json", manifest)
        (legacy / "footnote-coverage.jsonl").unlink()
        validate(legacy)

        pair = variant("optional-docx")
        manifest = json.loads((pair / "run-manifest.json").read_text())
        manifest["publication_policy"] = "matched_pair"
        write_json(pair / "run-manifest.json", manifest)
        validate(pair)
        derivative = subprocess.run(
            [sys.executable, str(HERE / "validate_run.py"), str(pair), "--require-ready", "--require-docx"],
            capture_output=True, text=True, check=False,
        )
        assert derivative.returncode == 1 and "missing nonempty report.docx" in derivative.stderr
        assert json.loads((pair / "run-manifest.json").read_text())["status"] == "complete"

    print("cite-check readiness safety tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
