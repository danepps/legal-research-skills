#!/usr/bin/env python3
"""Validate internal-proofread run structure and enforce completion gates."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from common import file_sha256, read_json, read_jsonl, validate_finding_location


REQUIRED = (
    "run-manifest.json", "document.json", "symbols.json", "static-findings.jsonl", "chunks.jsonl",
    "findings.jsonl", "dispositions.jsonl", "verifier-audit.jsonl", "rejection-audit.jsonl",
    "rejection-packets.jsonl", "recall-packets.jsonl", "challenger-findings.jsonl",
    "challenger-unmatched.jsonl", "report.md",
)
DISPOSITIONS = {"confirmed", "likely", "query", "rejected", "fixed", "waived", "style", "prepublication"}
REPORT_VISIBLE_STATUSES = {"confirmed", "likely", "query", "fixed", "waived", "style", "prepublication"}
AUDIT_STATUSES = {"confirmed", "revised", "retracted"}
REJECTION_STATUSES = {"confirmed_rejection", "reopen", "revised"}
REJECTION_CATEGORIES = {"possible_omission", "duplication", "xref", "numbering"}


def load_result(path: Path, errors: list[str], blocks: dict[str, dict] | None = None) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("top level is not an object")
        findings = value.get("findings")
        if not isinstance(findings, list) or any(not isinstance(row, dict) for row in findings):
            errors.append(f"{path.name}: findings must be an array of objects")
        elif blocks is not None:
            for row in findings:
                try:
                    validate_finding_location(row, blocks)
                except ValueError as exc:
                    errors.append(f"{path.name}: {exc}")
        return value
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        errors.append(f"{path.name}: {exc}")
        return {}


def substantially_overlaps(left: dict, right: dict) -> bool:
    left_location = left.get("location", {})
    right_location = right.get("location", {})
    if left_location.get("block_id") != right_location.get("block_id") or left.get("category") != right.get("category"):
        return False
    left_start, left_end = int(left_location.get("char_start", 0)), int(left_location.get("char_end", 0))
    right_start, right_end = int(right_location.get("char_start", 0)), int(right_location.get("char_end", 0))
    overlap = max(0, min(left_end, right_end) - max(left_start, right_start))
    shorter = min(max(1, left_end - left_start), max(1, right_end - right_start))
    return overlap / shorter >= 0.5


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    errors: list[str] = []
    for name in REQUIRED:
        if not (run_dir / name).is_file():
            errors.append(f"missing {name}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    try:
        manifest = read_json(run_dir / "run-manifest.json")
        document = read_json(run_dir / "document.json")
        symbols = read_json(run_dir / "symbols.json")
        static = read_jsonl(run_dir / "static-findings.jsonl")
        challenger = read_jsonl(run_dir / "challenger-findings.jsonl")
        challenger_unmatched = read_jsonl(run_dir / "challenger-unmatched.jsonl")
        chunks = read_jsonl(run_dir / "chunks.jsonl")
        recall_packets = read_jsonl(run_dir / "recall-packets.jsonl")
        rejection_packets = read_jsonl(run_dir / "rejection-packets.jsonl")
        findings = read_jsonl(run_dir / "findings.jsonl")
        dispositions = read_jsonl(run_dir / "dispositions.jsonl")
        audits = read_jsonl(run_dir / "verifier-audit.jsonl")
        rejection_audits = read_jsonl(run_dir / "rejection-audit.jsonl")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    if manifest.get("schema_version") != 1 or document.get("schema_version") != 1 or symbols.get("schema_version") != 1:
        errors.append("unsupported schema version")
    source_hash = manifest.get("draft_sha256")
    if source_hash != document.get("input_sha256") or source_hash != symbols.get("source_sha256"):
        errors.append("source hashes differ across manifest, document, and symbols")
    draft = Path(str(manifest.get("draft_path", "")))
    if not draft.is_file():
        errors.append("frozen source snapshot is missing")
    elif file_sha256(draft) != source_hash:
        errors.append("draft changed after extraction; start a fresh run")
    block_ids = [block.get("block_id") for block in document.get("blocks", []) + document.get("notes", [])]
    source_blocks = {block.get("block_id"): block for block in document.get("blocks", []) + document.get("notes", [])}
    if len(block_ids) != len(set(block_ids)):
        errors.append("document contains duplicate block IDs")
    for row in static + challenger + findings:
        if row.get("source_sha256") != source_hash:
            errors.append(f"finding has stale source hash: {row.get('finding_id')}")
        try:
            validate_finding_location(row, source_blocks)
        except ValueError as exc:
            errors.append(f"invalid finding {row.get('finding_id')}: {exc}")

    if args.require_ready:
        if not chunks:
            errors.append("no chunks were created")
        reviewable = {block.get("block_id") for block in document.get("blocks", []) if block.get("reviewable")}
        reviewable_notes = {note.get("block_id") for note in document.get("notes", []) if note.get("reviewable")}
        core_counts = Counter(block_id for chunk in chunks for block_id in chunk.get("core_block_ids", []))
        note_counts = Counter(note_id for chunk in chunks for note_id in chunk.get("owned_note_ids", []))
        configured_max = int(manifest.get("chunk_policy", {}).get("max_words", 0) or 0)
        for chunk in chunks:
            core_words = int(chunk.get("core_word_count", 0) or 0)
            if configured_max and core_words > configured_max and chunk.get("size_exception") != "single_block_exceeds_max":
                errors.append(
                    f"chunk exceeds configured maximum without a single-block exception: "
                    f"{chunk.get('chunk_id')} ({core_words} > {configured_max})"
                )
        for missing in sorted(reviewable - set(core_counts)):
            errors.append(f"reviewable block lacks an owner: {missing}")
        for duplicate, count in sorted(core_counts.items()):
            if count != 1:
                errors.append(f"core block has {count} owners: {duplicate}")
        for missing in sorted(reviewable_notes - set(note_counts)):
            errors.append(f"reviewable note lacks an owner: {missing}")
        for duplicate, count in sorted(note_counts.items()):
            if count != 1:
                errors.append(f"owned note has {count} owners: {duplicate}")

        latest_result_mtime = max(
            (run_dir / "static-findings.jsonl").stat().st_mtime,
            (run_dir / "challenger-findings.jsonl").stat().st_mtime,
        )
        clean_chunks: list[dict] = []
        for chunk in chunks:
            chunk_id = str(chunk.get("chunk_id"))
            path = run_dir / "agent-results" / f"{chunk_id}.json"
            if not path.is_file():
                errors.append(f"missing chunk result: {chunk_id}")
                continue
            latest_result_mtime = max(latest_result_mtime, path.stat().st_mtime)
            result = load_result(path, errors, source_blocks)
            if result.get("chunk_id") != chunk_id or result.get("source_sha256") != source_hash:
                errors.append(f"chunk result identity/hash mismatch: {chunk_id}")
            if result.get("status") != "complete":
                errors.append(f"chunk result is not complete: {chunk_id}")
            if set(result.get("reviewed_block_ids", [])) != set(chunk.get("core_block_ids", [])):
                errors.append(f"chunk result block coverage mismatch: {chunk_id}")
            if set(result.get("reviewed_note_ids", [])) != set(chunk.get("owned_note_ids", [])):
                errors.append(f"chunk result note coverage mismatch: {chunk_id}")
            if not isinstance(result.get("findings", []), list):
                errors.append(f"chunk result findings must be an array: {chunk_id}")
            elif result.get("findings") == []:
                clean_chunks.append(chunk)

        audited_clean_chunks: list[dict] = []
        for chunk in clean_chunks:
            chunk_id = str(chunk.get("chunk_id"))
            path = run_dir / "agent-results" / f"{chunk_id}-audit.json"
            if not path.is_file():
                continue
            audited_clean_chunks.append(chunk)
            latest_result_mtime = max(latest_result_mtime, path.stat().st_mtime)
            result = load_result(path, errors, source_blocks)
            if result.get("chunk_id") != chunk_id or result.get("source_sha256") != source_hash:
                errors.append(f"clean-chunk audit identity/hash mismatch: {chunk_id}")
            if result.get("status") != "complete":
                errors.append(f"clean-chunk audit is not complete: {chunk_id}")
            if (set(result.get("reviewed_block_ids", [])) != set(chunk.get("core_block_ids", []))
                    or set(result.get("reviewed_note_ids", [])) != set(chunk.get("owned_note_ids", []))):
                errors.append(f"clean-chunk audit coverage mismatch: {chunk_id}")
        minimum_clean_audits = (len(clean_chunks) + 9) // 10
        if len(audited_clean_chunks) < minimum_clean_audits:
            errors.append(f"clean-chunk audit requires at least {minimum_clean_audits} completed sample(s)")

        if manifest.get("recall_required", False):
            if not recall_packets:
                errors.append("required independent recall packets were not created")
            recall_block_counts = Counter(
                block_id for packet in recall_packets for block_id in packet.get("reviewed_block_ids", [])
            )
            recall_note_counts = Counter(
                note_id for packet in recall_packets for note_id in packet.get("reviewed_note_ids", [])
            )
            for missing in sorted(reviewable - set(recall_block_counts)):
                errors.append(f"reviewable block lacks a recall owner: {missing}")
            for duplicate, count in sorted(recall_block_counts.items()):
                if count != 1:
                    errors.append(f"recall block has {count} owners: {duplicate}")
            for missing in sorted(reviewable_notes - set(recall_note_counts)):
                errors.append(f"reviewable note lacks a recall owner: {missing}")
            for duplicate, count in sorted(recall_note_counts.items()):
                if count != 1:
                    errors.append(f"recall note has {count} owners: {duplicate}")
            for packet in recall_packets:
                packet_id = str(packet.get("packet_id"))
                path = run_dir / "recall-results" / f"{packet_id}.json"
                if not path.is_file():
                    errors.append(f"missing recall result: {packet_id}")
                    continue
                latest_result_mtime = max(latest_result_mtime, path.stat().st_mtime)
                result = load_result(path, errors, source_blocks)
                if result.get("packet_id") != packet_id or result.get("source_sha256") != source_hash:
                    errors.append(f"recall result identity/hash mismatch: {packet_id}")
                if result.get("status") != "complete":
                    errors.append(f"recall result is not complete: {packet_id}")
                if set(result.get("reviewed_block_ids", [])) != set(packet.get("reviewed_block_ids", [])):
                    errors.append(f"recall result block coverage mismatch: {packet_id}")
                if set(result.get("reviewed_note_ids", [])) != set(packet.get("reviewed_note_ids", [])):
                    errors.append(f"recall result note coverage mismatch: {packet_id}")
                if not isinstance(result.get("findings", []), list):
                    errors.append(f"recall result findings must be an array: {packet_id}")

        for lane in manifest.get("required_lanes", []):
            path = run_dir / "lane-results" / f"{lane}.json"
            if not path.is_file():
                errors.append(f"missing global lane result: {lane}")
                continue
            latest_result_mtime = max(latest_result_mtime, path.stat().st_mtime)
            result = load_result(path, errors, source_blocks)
            if result.get("lane") != lane or result.get("source_sha256") != source_hash:
                errors.append(f"lane result identity/hash mismatch: {lane}")
            if result.get("status") != "complete":
                errors.append(f"global lane is not complete: {lane}")
            if not isinstance(result.get("findings", []), list):
                errors.append(f"lane result findings must be an array: {lane}")

        if (run_dir / "findings.jsonl").stat().st_mtime < latest_result_mtime:
            errors.append("findings.jsonl is stale; rerun merge_findings.py")
        finding_ids = [row.get("finding_id") for row in findings]
        if len(finding_ids) != len(set(finding_ids)):
            errors.append("findings.jsonl contains duplicate finding IDs")
        for index, row in enumerate(findings):
            for other in findings[index + 1:]:
                if substantially_overlaps(row, other):
                    errors.append(
                        f"overlapping duplicate findings were not merged: {row.get('finding_id')} and {other.get('finding_id')}"
                    )
        merged_ids = {
            merged_id
            for row in findings
            for merged_id in row.get("merged_finding_ids", [row.get("finding_id")])
        }
        for row in challenger:
            if row.get("finding_id") not in merged_ids:
                errors.append(f"challenger finding was not merged: {row.get('finding_id')}")
        for row in challenger_unmatched:
            status = row.get("status")
            if status not in {"pending", "resolved", "waived"}:
                errors.append(f"invalid challenger-unmatched status: {row.get('unmatched_id')}")
            elif status == "pending":
                errors.append(f"challenger item remains unmatched: {row.get('unmatched_id')}")
            elif not str(row.get("resolution", "")).strip():
                errors.append(f"resolved challenger item lacks a resolution: {row.get('unmatched_id')}")
        disposition_by_id = {row.get("finding_id"): row for row in dispositions}
        if len(disposition_by_id) != len(dispositions):
            errors.append("dispositions.jsonl contains duplicate finding IDs")
        audit_ids = {str(chunk.get("chunk_id")) for chunk in audited_clean_chunks}
        audit_misses = [row for row in findings
                       if disposition_by_id.get(row.get("finding_id"), {}).get("status") in {"confirmed", "fixed"}
                       and audit_ids.intersection(row.get("corroborated_by", []))]
        audit_words = sum(int(chunk.get("core_word_count", 0)) for chunk in audited_clean_chunks)
        audit_words += sum(int(source_blocks.get(note_id, {}).get("word_count", 0))
                           for chunk in audited_clean_chunks for note_id in chunk.get("owned_note_ids", []))
        high_miss = any(row.get("impact") == "high" for row in audit_misses)
        lower_misses = sum(row.get("impact") != "high" for row in audit_misses)
        expand_audit = high_miss or lower_misses > 2 * max(1, (audit_words + 4999) // 5000)
        if expand_audit and len(audited_clean_chunks) != len(clean_chunks):
            errors.append("clean-chunk audit miss threshold requires independent review of every clean chunk")
        for finding_id in sorted(str(value) for value in set(finding_ids) - set(disposition_by_id)):
            errors.append(f"finding lacks disposition: {finding_id}")
        for finding_id in sorted(str(value) for value in set(disposition_by_id) - set(finding_ids)):
            errors.append(f"disposition references unknown finding: {finding_id}")
        expected_rejection_ids = {
            row.get("finding_id") for row in findings
            if row.get("impact") == "high"
            and row.get("category") in REJECTION_CATEGORIES
            and disposition_by_id.get(row.get("finding_id"), {}).get("status") == "rejected"
        }
        packet_rejection_ids = [
            finding_id for packet in rejection_packets for finding_id in packet.get("finding_ids", [])
        ]
        if manifest.get("rejection_audit_required", False):
            rejection_audit_status = {row.get("finding_id"): row.get("rejection_status") for row in rejection_audits}
            missing = sorted(expected_rejection_ids - set(packet_rejection_ids))
            extra = sorted(
                finding_id for finding_id in set(packet_rejection_ids) - expected_rejection_ids
                if rejection_audit_status.get(finding_id) not in {"reopen", "revised"}
            )
            if missing or extra:
                errors.append(f"rejection packet coverage mismatch: missing={missing[:5]}, unexplained_extra={extra[:5]}")
            if len(packet_rejection_ids) != len(set(packet_rejection_ids)):
                errors.append("rejection packets contain duplicate finding IDs")
            for packet in rejection_packets:
                packet_id = str(packet.get("packet_id"))
                path = run_dir / "rejection-results" / f"{packet_id}.jsonl"
                if not path.is_file():
                    errors.append(f"missing rejection-audit result: {packet_id}")
                    continue
                try:
                    result_rows = read_jsonl(path)
                except (OSError, json.JSONDecodeError, ValueError) as exc:
                    errors.append(f"{path.name}: {exc}")
                    continue
                result_ids = [row.get("finding_id") for row in result_rows]
                if set(result_ids) != set(packet.get("finding_ids", [])) or len(result_ids) != len(set(result_ids)):
                    errors.append(f"rejection-audit result coverage mismatch: {packet_id}")
                for audit in result_rows:
                    if audit.get("source_sha256") != source_hash or audit.get("rejection_status") not in REJECTION_STATUSES:
                        errors.append(f"invalid rejection-audit result row: {audit.get('finding_id')}")
        audit_by_id = {row.get("finding_id"): row for row in audits}
        rejection_audit_by_id = {row.get("finding_id"): row for row in rejection_audits}
        if len(rejection_audit_by_id) != len(rejection_audits):
            errors.append("rejection-audit.jsonl contains duplicate finding IDs")
        for finding_id in sorted(set(packet_rejection_ids) - set(rejection_audit_by_id)):
            errors.append(f"rejection packet finding lacks canonical audit row: {finding_id}")
        for row in findings:
            disposition = disposition_by_id.get(row.get("finding_id"), {})
            status = disposition.get("status")
            if status not in DISPOSITIONS:
                errors.append(f"invalid or missing disposition status: {row.get('finding_id')}")
                continue
            if status in {"rejected", "waived", "query"} and not disposition.get("rationale"):
                errors.append(f"disposition requires rationale: {row.get('finding_id')}")
            if row.get("impact") == "high" and status in {"confirmed", "likely", "query", "fixed"}:
                audit = audit_by_id.get(row.get("finding_id"))
                if not audit or audit.get("audit_status") not in AUDIT_STATUSES:
                    errors.append(f"high-impact finding lacks verifier audit: {row.get('finding_id')}")
                elif audit.get("source_sha256") != source_hash:
                    errors.append(f"verifier audit has stale source hash: {row.get('finding_id')}")
                elif audit.get("audit_status") == "retracted" and status != "rejected":
                    errors.append(f"retracted audit conflicts with disposition: {row.get('finding_id')}")
            if (
                manifest.get("rejection_audit_required", False)
                and row.get("impact") == "high"
                and row.get("category") in REJECTION_CATEGORIES
                and status == "rejected"
            ):
                audit = rejection_audit_by_id.get(row.get("finding_id"))
                if not audit or audit.get("rejection_status") not in REJECTION_STATUSES:
                    errors.append(f"high-impact rejection lacks independent audit: {row.get('finding_id')}")
                elif audit.get("source_sha256") != source_hash:
                    errors.append(f"rejection audit has stale source hash: {row.get('finding_id')}")
                elif audit.get("rejection_status") != "confirmed_rejection":
                    errors.append(f"reopened rejection still has rejected disposition: {row.get('finding_id')}")

        for finding_id, audit in rejection_audit_by_id.items():
            disposition = disposition_by_id.get(finding_id, {})
            if audit.get("rejection_status") in {"reopen", "revised"} and disposition.get("status") == "rejected":
                errors.append(f"rejection audit requires a reopened disposition: {finding_id}")

        report = run_dir / "report.md"
        report_text = report.read_text(encoding="utf-8")
        if not report_text.strip():
            errors.append("report.md is empty")
        for heading in ("Needs your attention", "Confirmed errors", "Author queries", "Pre-publication checks", "Style consistency (optional)", "Couldn't check"):
            if heading not in report_text:
                errors.append(f"report.md lacks {heading} section")
        expected_anchors = sum(
            1 for row in dispositions if row.get("status") in REPORT_VISIBLE_STATUSES
        )
        anchor_count = report_text.count("  - Find in draft: ")
        if anchor_count < expected_anchors:
            errors.append(
                f"report.md lacks Ctrl-F context anchors: found {anchor_count}, expected at least {expected_anchors}"
            )
        if "  - Find in draft: “”" in report_text:
            errors.append("report.md contains an empty Ctrl-F context anchor")
        evidence_mtime = max((run_dir / "findings.jsonl").stat().st_mtime, (run_dir / "dispositions.jsonl").stat().st_mtime)
        if report.stat().st_mtime < evidence_mtime:
            errors.append("report.md is stale; rerun build_report.py")
        if manifest.get("status") not in {"complete", "complete_with_limits"}:
            errors.append("manifest status must be complete or complete_with_limits")
        if manifest.get("counts", {}).get("findings") != len(findings):
            errors.append("manifest finding count is stale; rerun build_report.py")

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("internal-proofread run validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
