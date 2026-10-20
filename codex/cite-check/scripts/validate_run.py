#!/usr/bin/env python3
"""Validate cite-check run structure and enforce report-readiness gates."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path


REQUIRED_FILES = (
    "run-manifest.json",
    "extraction.json",
    "prepared-units.jsonl",
    "citation-units.jsonl",
    "source-ledger.jsonl",
    "verdicts.jsonl",
    "verifier-audit.jsonl",
)
HIGH_SEVERITY = {"critical", "high"}
AUDIT_STATUSES = {"confirmed", "revised", "retracted"}
CAPTION_LOCATIONS = {"footnote", "body", "none"}
PAGINATION_CONVENTIONS = {
    "printed_page",
    "star_or_header_precedes",
    "footer_follows",
    "paragraph_number",
    "section_number",
    "unpaginated",
    "unknown",
}
VERIFICATION_BASES = {
    "primary_full_text",
    "authoritative_reproduction",
    "repository_full_text",
    "local_library_full_text",
    "metadata_only",
    "snippet_only",
    "secondary_reproduction",
    "unavailable",
}
QUOTE_CHECK_STATUSES = {"verbatim", "normalized", "altered", "not_found", "unavailable"}
UNIT_STATUSES = {"verified", "partial", "mismatch", "unverified", "not_applicable"}
SEVERITIES = {"critical", "high", "medium", "low", "info"}
METADATA_RECORD_TYPES = {
    "journal_article_page", "journal_issue_page", "pdf_first_page",
    "publisher_record", "library_catalog_record", "heinonline_record",
    "ssrn_record", "official_case_record",
}
AUTHOR_ORDER_RECORD_TYPES = {"journal_article_page", "pdf_first_page", "publisher_record", "ssrn_record"}
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path, errors: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("top level is not an object")
        return value
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{path.name}: {exc}")
        return {}


def load_jsonl(path: Path, errors: list[str]) -> list[dict]:
    rows = []
    try:
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError("row is not an object")
            rows.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{path.name}:{number if 'number' in locals() else '?'}: {exc}")
    return rows


def require_fields(rows: list[dict], fields: set[str], label: str, errors: list[str]) -> None:
    for index, row in enumerate(rows, 1):
        missing = sorted(field for field in fields if row.get(field) in (None, "", []))
        if missing:
            errors.append(f"{label} row {index}: missing {', '.join(missing)}")


def occurs_in_draft(value: object, corpus: str) -> bool:
    text = str(value or "").strip()
    return bool(text) and text in corpus


def nonempty_string(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def page_delta(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value)
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--mark-complete", action="store_true")
    parser.add_argument(
        "--require-docx", action="store_true",
        help="separately check the optional DOCX after Markdown is ready; never required for Markdown publication",
    )
    args = parser.parse_args()
    if args.mark_complete and not args.require_ready:
        parser.error("--mark-complete requires --require-ready")
    if args.require_docx and not args.require_ready:
        parser.error("--require-docx requires --require-ready")
    errors: list[str] = []
    for name in REQUIRED_FILES:
        if not (args.run_dir / name).is_file():
            errors.append(f"missing {name}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    manifest = load_json(args.run_dir / "run-manifest.json", errors)
    extraction = load_json(args.run_dir / "extraction.json", errors)
    prepared = load_jsonl(args.run_dir / "prepared-units.jsonl", errors)
    units = load_jsonl(args.run_dir / "citation-units.jsonl", errors)
    sources = load_jsonl(args.run_dir / "source-ledger.jsonl", errors)
    verdicts = load_jsonl(args.run_dir / "verdicts.jsonl", errors)
    audits = load_jsonl(args.run_dir / "verifier-audit.jsonl", errors)
    schema_version = manifest.get("schema_version")
    if schema_version not in {2, 3, 4}:
        errors.append("run-manifest.json: unsupported schema_version")
        schema_version = 2
    quote_check_path = args.run_dir / "quote-checks.jsonl"
    quote_checks: list[dict] = []
    if schema_version >= 3:
        if not quote_check_path.is_file():
            errors.append("missing quote-checks.jsonl")
        else:
            quote_checks = load_jsonl(quote_check_path, errors)
    coverage: list[dict] = []
    if schema_version >= 4:
        coverage = load_jsonl(args.run_dir / "footnote-coverage.jsonl", errors)
    if extraction.get("schema_version") != 1:
        errors.append("extraction.json: unsupported schema_version")
    if manifest.get("draft_sha256") != extraction.get("input_sha256"):
        errors.append("manifest and extraction draft hashes differ")
    draft_path = Path(str(manifest.get("draft_path", "")))
    if not draft_path.is_file():
        errors.append("draft snapshot/source file is missing")
    elif file_sha256(draft_path) != manifest.get("draft_sha256"):
        errors.append("draft changed after extraction; re-extract before completion")

    corpus = "\n".join(
        [str(value) for value in extraction.get("paragraphs", [])]
        + [str(row.get("text", "")) for row in extraction.get("footnotes", [])]
    )

    if args.require_ready:
        if not units:
            errors.append("citation-units.jsonl is empty")
        if not sources:
            errors.append("source-ledger.jsonl is empty")
        if not verdicts:
            errors.append("verdicts.jsonl is empty")
        allowed_statuses = {"ready_for_validation", "complete", "complete_with_limits"}
        if manifest.get("status") not in allowed_statuses:
            errors.append(
                "run-manifest.json status must be ready_for_validation, complete, or complete_with_limits"
            )
        completion_target = manifest.get("completion_target")
        if manifest.get("status") == "ready_for_validation" and completion_target not in {
            "complete",
            "complete_with_limits",
        }:
            errors.append("ready_for_validation manifest lacks valid completion_target")
        final_status = (
            completion_target if manifest.get("status") == "ready_for_validation"
            else manifest.get("status")
        )
        expected_counts = {
            status: sum(1 for row in verdicts if row.get("status") == status)
            for status in ("verified", "partial", "mismatch", "unverified")
        }
        for status, expected in expected_counts.items():
            if manifest.get("counts", {}).get(status) != expected:
                errors.append(f"run-manifest.json count mismatch for {status}: expected {expected}")
        if manifest.get("counts", {}).get("prepared_units") != len(prepared):
            errors.append("run-manifest.json prepared_units count mismatch")
        if schema_version >= 3 and manifest.get("counts", {}).get("quote_checks") != len(quote_checks):
            errors.append("run-manifest.json quote_checks count mismatch")
        require_fields(
            units,
            {
                "unit_id",
                "footnote_number",
                "source_id",
                "source_type",
                "draft_citation_text",
                "resolved_source_label",
                "draft_find_string",
                "caption_in_draft",
                "full_footnote",
            },
            "citation-units.jsonl",
            errors,
        )
        require_fields(
            sources,
            {"source_id", "source_type", "canonical_citation", "status", "verification_basis"},
            "source-ledger.jsonl",
            errors,
        )
        require_fields(
            verdicts,
            {
                "verdict_id",
                "unit_id",
                "status",
                "severity",
                "category",
                "verification_basis",
                "evidence",
                "suggested_action",
            },
            "verdicts.jsonl",
            errors,
        )
        for index, source in enumerate(sources, 1):
            if source.get("verification_basis") not in VERIFICATION_BASES:
                errors.append(f"source-ledger.jsonl row {index}: invalid verification_basis")
        for index, unit in enumerate(units, 1):
            if unit.get("caption_in_draft") not in CAPTION_LOCATIONS:
                errors.append(f"citation-units.jsonl row {index}: invalid caption_in_draft")
            if not occurs_in_draft(unit.get("draft_find_string"), corpus):
                errors.append(f"citation-units.jsonl row {index}: draft_find_string not found in draft")
            if not occurs_in_draft(unit.get("draft_citation_text"), str(unit.get("full_footnote", ""))):
                errors.append(
                    f"citation-units.jsonl row {index}: draft_citation_text not found in full_footnote"
                )

        for index, verdict in enumerate(verdicts, 1):
            if verdict.get("status") not in UNIT_STATUSES:
                errors.append(f"verdicts.jsonl row {index}: invalid status")
            if verdict.get("severity") not in SEVERITIES:
                errors.append(f"verdicts.jsonl row {index}: invalid severity")
            if verdict.get("verification_basis") not in VERIFICATION_BASES:
                errors.append(f"verdicts.jsonl row {index}: invalid verification_basis")
            if verdict.get("category") == "fabricated":
                errors.append(f"verdicts.jsonl row {index}: use not_found_in_sources_checked")
            if verdict.get("category") == "metadata_error" and verdict.get("status") == "mismatch":
                if verdict.get("verification_basis") in {"snippet_only", "unavailable"}:
                    errors.append(f"verdicts.jsonl row {index}: metadata correction cannot rest on snippets or unavailable evidence")
                record = verdict.get("metadata_record")
                if not isinstance(record, dict):
                    errors.append(f"verdicts.jsonl row {index}: metadata_error lacks metadata_record")
                else:
                    if record.get("opened") is not True or record.get("exact_work_checked") is not True:
                        errors.append(f"verdicts.jsonl row {index}: metadata record must be opened and match the exact work/part")
                    if record.get("record_type") not in METADATA_RECORD_TYPES:
                        errors.append(f"verdicts.jsonl row {index}: unsupported metadata record type")
                    if not isinstance(record.get("location"), str) or not record["location"].strip():
                        errors.append(f"verdicts.jsonl row {index}: metadata record lacks location")
                    fields = record.get("fields")
                    if not isinstance(fields, list) or not fields or any(
                        not isinstance(field, str) or not field.strip() for field in fields
                    ):
                        errors.append(f"verdicts.jsonl row {index}: metadata record must identify corrected fields")
                    elif "author_order" in fields and record.get("record_type") not in AUTHOR_ORDER_RECORD_TYPES:
                        errors.append(f"verdicts.jsonl row {index}: author-order correction requires a title or landing page")
            adverse = verdict.get("status") in {"mismatch", "unverified", "partial"}
            if adverse and not occurs_in_draft(verdict.get("draft_find_string"), corpus):
                errors.append(f"verdicts.jsonl row {index}: adverse draft_find_string not found in draft")
            if verdict.get("category") == "pincite_error":
                if "page_delta" in verdict and page_delta(verdict["page_delta"]) is None:
                    errors.append(f"verdicts.jsonl row {index}: page_delta must be an integer")
                convention = verdict.get("pagination_convention")
                if convention not in PAGINATION_CONVENTIONS or convention == "unknown":
                    errors.append(
                        f"verdicts.jsonl row {index}: pincite_error lacks identified pagination_convention"
                    )
        unit_ids = {row.get("unit_id") for row in units}
        verdict_unit_ids = {row.get("unit_id") for row in verdicts}
        for unit_id in sorted(str(value) for value in unit_ids - verdict_unit_ids):
            errors.append(f"citation unit lacks verdict: {unit_id}")
        for unit_id in sorted(str(value) for value in verdict_unit_ids - unit_ids):
            errors.append(f"verdict references unknown citation unit: {unit_id}")
        source_ids = [row.get("source_id") for row in sources]
        if len(source_ids) != len(set(source_ids)):
            errors.append("source-ledger.jsonl contains duplicate source_id rows")
        unit_source_ids = {row.get("source_id") for row in units}
        for source_id in sorted(str(value) for value in unit_source_ids - set(source_ids)):
            errors.append(f"citation unit references unknown source: {source_id}")
        unit_id_list = [row.get("unit_id") for row in units]
        if len(unit_id_list) != len(set(unit_id_list)):
            errors.append("citation-units.jsonl contains duplicate unit_id rows")
        verdict_ids = [row.get("verdict_id") for row in verdicts]
        if len(verdict_ids) != len(set(verdict_ids)):
            errors.append("verdicts.jsonl contains duplicate verdict_id rows")
        verdict_units = [row.get("unit_id") for row in verdicts]
        if len(verdict_units) != len(set(verdict_units)):
            errors.append("verdicts.jsonl must contain exactly one verdict per citation unit")

        if schema_version >= 4:
            notes = {row.get("number"): row for row in extraction.get("footnotes", [])}
            selected = manifest.get("selected_footnotes")
            if selected is not None and (
                not isinstance(selected, list)
                or any(not isinstance(n, int) or isinstance(n, bool) or n not in notes for n in selected)
            ):
                errors.append("run-manifest.json selected_footnotes must name extracted footnotes")
                selected = []
            expected_notes = set(notes) if selected is None else set(selected)
            covered_notes: set[int] = set()
            for index, row in enumerate(coverage, 1):
                number = row.get("footnote_number")
                if not isinstance(number, int) or isinstance(number, bool) or number not in expected_notes:
                    errors.append(f"footnote-coverage.jsonl row {index}: unknown or out-of-scope footnote")
                    continue
                if number in covered_notes:
                    errors.append(f"footnote-coverage.jsonl: duplicate footnote {number}")
                covered_notes.add(number)
                ids = row.get("unit_ids")
                if not isinstance(ids, list) or any(not isinstance(value, str) for value in ids):
                    errors.append(f"footnote-coverage.jsonl row {index}: unit_ids must be a string list")
                    continue
                expected_ids = {unit.get("unit_id") for unit in units if unit.get("footnote_number") == number}
                if len(ids) != len(set(ids)) or set(ids) != expected_ids:
                    errors.append(f"footnote-coverage.jsonl row {index}: unit_ids do not reconcile with citation units")
                if row.get("status") == "reviewed":
                    if not ids:
                        errors.append(f"footnote-coverage.jsonl row {index}: reviewed footnote lacks citation units")
                elif row.get("status") == "no_citations":
                    if ids or not nonempty_string(row.get("reason")):
                        errors.append(f"footnote-coverage.jsonl row {index}: no_citations requires a reason and no units")
                else:
                    errors.append(f"footnote-coverage.jsonl row {index}: footnote has not been reviewed")
            for number in sorted(expected_notes - covered_notes):
                errors.append(f"footnote lacks coverage review: {number}")
            for index, unit in enumerate(units, 1):
                number = unit.get("footnote_number")
                if number not in expected_notes:
                    errors.append(f"citation-units.jsonl row {index}: unknown or out-of-scope footnote")
                elif unit.get("full_footnote") != notes[number].get("text"):
                    errors.append(f"citation-units.jsonl row {index}: full_footnote differs from extraction")

        unchecked_units = [
            row for row in verdicts
            if row.get("status") in {"unverified", "partial"}
            or row.get("verification_basis") == "unavailable"
        ]
        unavailable_sources = [
            row for row in sources
            if row.get("status") == "unavailable" or row.get("verification_basis") == "unavailable"
        ]
        if (unchecked_units or unavailable_sources) and final_status != "complete_with_limits":
            errors.append("unchecked items require completion_target/status complete_with_limits")
        for row in unchecked_units:
            if not nonempty_string(row.get("unlock_path")):
                errors.append(f"unchecked citation unit lacks unlock_path: {row.get('unit_id')}")
            if row.get("status") == "verified":
                errors.append(f"verified citation unit has unavailable evidence: {row.get('unit_id')}")
        for row in unavailable_sources:
            if not any(nonempty_string(row.get(field)) for field in ("reason", "retrieval_notes")):
                errors.append(f"unavailable source lacks reason or retrieval_notes: {row.get('source_id')}")
            if not nonempty_string(row.get("unlock_path")):
                errors.append(f"unavailable source lacks unlock_path: {row.get('source_id')}")
        if schema_version >= 3:
            prepared_by_id: dict[str, dict] = {}
            for index, row in enumerate(prepared, 1):
                prepared_id = row.get("prepared_unit_id")
                if not isinstance(prepared_id, str) or not prepared_id.strip():
                    errors.append(f"prepared-units.jsonl row {index}: missing prepared_unit_id")
                elif prepared_id in prepared_by_id:
                    errors.append(f"prepared-units.jsonl has duplicate prepared_unit_id: {prepared_id}")
                else:
                    prepared_by_id[prepared_id] = row

            unit_by_id = {
                str(row.get("unit_id")): row
                for row in units
                if isinstance(row.get("unit_id"), str) and row.get("unit_id")
            }
            source_id_set = {
                str(row.get("source_id"))
                for row in sources
                if isinstance(row.get("source_id"), str) and row.get("source_id")
            }
            verdict_by_unit = {
                str(row.get("unit_id")): row
                for row in verdicts
                if isinstance(row.get("unit_id"), str) and row.get("unit_id")
            }
            checks_by_prepared: dict[str, list[dict]] = {}
            quote_check_ids: set[str] = set()
            for index, check in enumerate(quote_checks, 1):
                check_id = check.get("quote_check_id")
                if not isinstance(check_id, str) or not check_id.strip():
                    errors.append(f"quote-checks.jsonl row {index}: missing quote_check_id")
                elif check_id in quote_check_ids:
                    errors.append(f"quote-checks.jsonl has duplicate quote_check_id: {check_id}")
                else:
                    quote_check_ids.add(check_id)
                prepared_id = check.get("prepared_unit_id")
                unit_id = check.get("unit_id")
                source_id = check.get("source_id")
                if not isinstance(prepared_id, str) or not prepared_id.strip():
                    errors.append(
                        f"quote-checks.jsonl row {index}: missing prepared_unit_id"
                    )
                elif prepared_id not in prepared_by_id:
                    errors.append(
                        f"quote-checks.jsonl row {index}: unknown prepared_unit_id {prepared_id!r}"
                    )
                else:
                    checks_by_prepared.setdefault(prepared_id, []).append(check)
                    if check.get("quote") != prepared_by_id[prepared_id].get("quote"):
                        errors.append(
                            f"quote-checks.jsonl row {index}: quote differs from prepared unit"
                        )
                if not isinstance(unit_id, str) or not unit_id.strip():
                    errors.append(f"quote-checks.jsonl row {index}: missing unit_id")
                elif unit_id not in unit_by_id:
                    errors.append(f"quote-checks.jsonl row {index}: unknown unit_id {unit_id!r}")
                if not isinstance(source_id, str) or not source_id.strip():
                    errors.append(f"quote-checks.jsonl row {index}: missing source_id")
                elif source_id not in source_id_set:
                    errors.append(f"quote-checks.jsonl row {index}: unknown source_id {source_id!r}")
                status = check.get("status")
                if status not in QUOTE_CHECK_STATUSES:
                    errors.append(f"quote-checks.jsonl row {index}: invalid status {status!r}")
                    continue
                if status == "unavailable":
                    if not nonempty_string(check.get("reason")):
                        errors.append(
                            f"quote-checks.jsonl row {index}: unavailable check lacks reason"
                        )
                    if not nonempty_string(check.get("unlock_path")):
                        errors.append(
                            f"quote-checks.jsonl row {index}: unavailable check lacks unlock_path"
                        )
                    continue
                source_path_value = check.get("source_path")
                source_hash = check.get("source_sha256")
                if not isinstance(source_path_value, str) or not source_path_value.strip():
                    errors.append(f"quote-checks.jsonl row {index}: missing source_path")
                    continue
                if not isinstance(source_hash, str) or not SHA256.fullmatch(source_hash):
                    errors.append(f"quote-checks.jsonl row {index}: invalid source_sha256")
                    continue
                source_text_path = Path(source_path_value).expanduser()
                if not source_text_path.is_absolute():
                    source_text_path = args.run_dir / source_text_path
                if not source_text_path.is_file():
                    errors.append(
                        f"quote-checks.jsonl row {index}: source text file does not exist"
                    )
                elif file_sha256(source_text_path) != source_hash:
                    errors.append(
                        f"quote-checks.jsonl row {index}: source text hash is stale"
                    )

            for prepared_id, prepared_row in prepared_by_id.items():
                checks = checks_by_prepared.get(prepared_id, [])
                if not checks:
                    errors.append(f"prepared quotation lacks quote check: {prepared_id}")
                    continue
                mapped_units = {
                    str(check.get("unit_id"))
                    for check in checks
                    if isinstance(check.get("unit_id"), str)
                }
                if len(mapped_units) != 1:
                    errors.append(
                        f"prepared quotation {prepared_id} must map to exactly one citation unit"
                    )
                    continue
                unit_id = next(iter(mapped_units))
                verdict = verdict_by_unit.get(unit_id)
                if verdict is None:
                    continue
                adequate_matches = [
                    check
                    for check in checks
                    if check.get("source_id") == unit_by_id.get(unit_id, {}).get("source_id")
                    and (
                        check.get("status") in {"verbatim", "normalized"}
                        or (
                            check.get("status") == "altered"
                            and check.get("alteration_reviewed") is True
                        )
                    )
                ]
                if verdict.get("status") == "verified" and not adequate_matches:
                    errors.append(
                        f"verified quotation unit {unit_id} lacks a deterministic match"
                    )
                unit_pin = unit_by_id.get(unit_id, {}).get("pincite")
                if unit_pin and verdict.get("status") == "verified":
                    pin_checks = [
                        check
                        for check in adequate_matches
                        if str(check.get("pincite", "")) == str(unit_pin)
                    ]
                    if not pin_checks:
                        errors.append(
                            f"verified quotation unit {unit_id} lacks a check for its pincite"
                        )
                    elif all(check.get("pincite_ok") is not True for check in pin_checks):
                        errors.append(
                            f"verified quotation unit {unit_id} lacks a confirmed pincite match"
                        )
        audit_by_verdict = {row.get("verdict_id"): row for row in audits}
        audit_ids = [row.get("verdict_id") for row in audits]
        if len(audit_ids) != len(set(audit_ids)):
            errors.append("verifier-audit.jsonl contains duplicate verdict_id rows")
        for index, audit in enumerate(audits, 1):
            if audit.get("verdict_id") not in set(verdict_ids):
                errors.append(f"verifier-audit.jsonl row {index}: unknown verdict_id")
            if audit.get("audit_status") not in AUDIT_STATUSES:
                errors.append(f"verifier-audit.jsonl row {index}: invalid audit_status")
            if audit.get("evidence") in (None, "", []):
                errors.append(f"verifier-audit.jsonl row {index}: missing evidence")
        for verdict in verdicts:
            adverse = verdict.get("status") in {"mismatch", "unverified", "partial"}
            exact_one_page = (
                verdict.get("category") == "pincite_error"
                and page_delta(verdict.get("page_delta")) in {-1, 1}
            )
            unknown_page_delta = (
                verdict.get("category") == "pincite_error"
                and verdict.get("pagination_convention") in {
                    "printed_page", "star_or_header_precedes", "footer_follows"
                }
                and page_delta(verdict.get("page_delta")) is None
            )
            needs_audit = (
                (adverse and verdict.get("severity") in HIGH_SEVERITY)
                or verdict.get("category") == "not_found_in_sources_checked"
                or exact_one_page
                or unknown_page_delta
            )
            if needs_audit:
                audit = audit_by_verdict.get(verdict.get("verdict_id"))
                if not audit or audit.get("audit_status") not in AUDIT_STATUSES:
                    errors.append(
                        f"verdict lacks required verifier audit: {verdict.get('verdict_id')}"
                    )
        report = args.run_dir / "report.md"
        if not report.is_file() or not report.read_text(encoding="utf-8").strip():
            errors.append("missing nonempty report.md")
        elif "Needs your attention" not in report.read_text(encoding="utf-8"):
            errors.append("report.md lacks Needs your attention section")
        elif not any(
            heading in report.read_text(encoding="utf-8")
            for heading in ("Couldn't check", "Couldn’t check")
        ):
            errors.append("report.md lacks Couldn't check section")
        else:
            report_text = report.read_text(encoding="utf-8")
            for field in ("Created by: Codex", "Model:", "Generated:", "Elapsed:", "Tokens:"):
                if field not in report_text:
                    errors.append(f"report.md lacks provenance field: {field}")
            model_lines = [line for line in report_text.splitlines() if line.startswith("Model:")]
            if model_lines and (not model_lines[0][len("Model:"):].strip() or "<" in model_lines[0]):
                errors.append("report.md Model field must contain the exact lead model label")
            # These are mechanical presence checks. The lead still must ensure
            # the limitation description accurately explains what was unchecked.
            limit_section = re.split(r"Couldn['’]t check", report_text, maxsplit=1)[-1]
            for row in unchecked_units + unavailable_sources:
                item_id = str(row.get("unit_id", row.get("source_id", "")))
                if item_id and not re.search(r"(?<![\w-])" + re.escape(item_id) + r"(?![\w-])", limit_section):
                    errors.append(f"report.md Couldn't check section omits unchecked item: {item_id}")
                unlock = str(row.get("unlock_path", "")).strip()
                if unlock and unlock not in limit_section:
                    errors.append(f"report.md Couldn't check section omits unlock_path for: {item_id}")

        publication_policy = manifest.get("publication_policy", "markdown_only")
        if publication_policy not in {"matched_pair", "markdown_only", "docx_only"}:
            errors.append("run-manifest.json has invalid publication_policy")
        # Derivative failure must not block the canonical Markdown gate, even
        # for older manifests that requested a matched pair or DOCX output.
        if args.require_docx:
            docx = args.run_dir / "report.docx"
            verification_record_path = args.run_dir / "docx-verification.json"
            if not docx.is_file() or docx.stat().st_size == 0:
                errors.append("missing nonempty report.docx")
            if not verification_record_path.is_file():
                errors.append("missing docx-verification.json")
            else:
                verification = load_json(verification_record_path, errors)
                if verification.get("status") != "passed":
                    errors.append("docx-verification.json status must be passed")
                if verification.get("verification_method") != "ooxml_structure_and_text_extraction":
                    errors.append("docx-verification.json has the wrong verification method")
                if verification.get("visual_verification") != "not_performed":
                    errors.append("docx-verification.json must disclose that visual verification was not performed")
                if verification.get("office_application_launched") is not False:
                    errors.append("docx-verification.json must show that no office application was launched")
                if not isinstance(verification.get("xml_parts_parsed"), int) or verification.get("xml_parts_parsed", 0) < 1:
                    errors.append("docx-verification.json xml_parts_parsed must be positive")
                if not isinstance(verification.get("extracted_text_characters"), int) or verification.get("extracted_text_characters", 0) < 1:
                    errors.append("docx-verification.json extracted_text_characters must be positive")
                if report.is_file() and verification.get("markdown_sha256") != file_sha256(report):
                    errors.append("docx-verification.json markdown hash does not match report.md")
                if docx.is_file() and verification.get("docx_sha256") != file_sha256(docx):
                    errors.append("docx-verification.json docx hash does not match report.docx")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    if args.mark_complete:
        if manifest.get("status") == "ready_for_validation":
            manifest["status"] = manifest["completion_target"]
            manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
            (args.run_dir / "run-manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
    print("cite-check run validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
