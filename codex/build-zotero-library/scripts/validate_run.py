#!/usr/bin/env python3
"""Validate a build-zotero-library run and enforce its completion gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ALLOWED_DECISIONS = {"add", "reuse", "skip_duplicate", "exclude"}
IGNORED_PROVENANCE_FIELDS = {
    "collections", "tags", "relations", "accessDate", "dateAdded", "dateModified",
    "key", "version", "parentItem",
}


def load_json(path: Path, issues: list[str], required: bool = True) -> Any:
    if not path.exists():
        if required:
            issues.append(f"missing {path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        issues.append(f"invalid {path.name}: {exc}")
        return None


def load_jsonl(path: Path, issues: list[str]) -> list[dict[str, Any]]:
    if not path.exists():
        issues.append(f"missing {path.name}")
        return []
    values = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            issues.append(f"invalid {path.name} line {line_number}: {exc}")
            continue
        if not isinstance(value, dict):
            issues.append(f"{path.name} line {line_number} must be an object")
            continue
        values.append(value)
    return values


def nonempty(value: Any) -> bool:
    return value not in (None, "", [], {}, False)


def material_fields(item: dict[str, Any]) -> set[str]:
    return {
        field for field, value in item.items()
        if field not in IGNORED_PROVENANCE_FIELDS and nonempty(value)
    }


def source_is_valid(source: Any) -> bool:
    if not isinstance(source, dict):
        return False
    url = str(source.get("url", ""))
    fields = source.get("fields")
    return (
        url.startswith("https://")
        and isinstance(fields, list)
        and bool(fields)
        and bool(source.get("source_type"))
        and bool(source.get("accessed_at"))
    )


def successful_key(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    if value.get("key"):
        return str(value["key"])
    data = value.get("data")
    if isinstance(data, dict) and data.get("key"):
        return str(data["key"])
    return ""


def unwrapped_items(planned: list[Any]) -> list[dict[str, Any]]:
    items = []
    for entry in planned:
        if isinstance(entry, dict) and isinstance(entry.get("item"), dict):
            items.append(entry["item"])
        elif isinstance(entry, dict):
            items.append(entry)
    return items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    issues: list[str] = []
    warnings: list[str] = []

    run = load_json(run_dir / "run.json", issues)
    candidates = load_jsonl(run_dir / "candidates.jsonl", issues)
    planned = load_json(run_dir / "planned-items.json", issues)
    write_result = load_json(run_dir / "write-result.json", issues, required=False)
    verification = load_json(run_dir / "verification.json", issues, required=False)
    manual = load_jsonl(run_dir / "manual-verifications.jsonl", issues)
    reuse_results = load_jsonl(run_dir / "reuse-results.jsonl", issues)
    attachment_path = run_dir / "attachment-results.jsonl"
    attachments = load_jsonl(attachment_path, issues) if attachment_path.exists() else []

    if not isinstance(run, dict) or run.get("schema_version") != 1:
        issues.append("run.json must use schema_version 1")
    elif not run.get("request"):
        issues.append("run.json request is empty")
    else:
        library = run.get("library")
        collection = run.get("collection")
        if not isinstance(library, dict) or library.get("type") not in {"user", "group"} or not library.get("id"):
            issues.append("run.json must identify the target library")
        if not isinstance(collection, dict) or not collection.get("key"):
            issues.append("run.json must identify the target collection key")

    candidate_by_id: dict[str, dict[str, Any]] = {}
    add_ids: list[str] = []
    reuse_ids: list[str] = []
    for index, candidate in enumerate(candidates):
        label = f"candidate {index + 1}"
        candidate_id = str(candidate.get("candidate_id", ""))
        if not candidate_id:
            issues.append(f"{label} has no candidate_id")
            continue
        if candidate_id in candidate_by_id:
            issues.append(f"duplicate candidate_id {candidate_id}")
            continue
        candidate_by_id[candidate_id] = candidate
        decision = candidate.get("decision")
        if decision not in ALLOWED_DECISIONS:
            issues.append(f"{candidate_id} has unresolved or invalid decision {decision!r}")
            continue
        if not candidate.get("reason"):
            issues.append(f"{candidate_id} has no decision reason")

        duplicate = candidate.get("duplicate_check")
        if decision in {"add", "reuse", "skip_duplicate"}:
            if not isinstance(duplicate, dict):
                issues.append(f"{candidate_id} lacks duplicate_check")
            else:
                if duplicate.get("scope") != "collection_and_library":
                    issues.append(f"{candidate_id} duplicate scope must be collection_and_library")
                if not duplicate.get("queries"):
                    issues.append(f"{candidate_id} has no duplicate queries")
        if decision == "add":
            add_ids.append(candidate_id)
            if not isinstance(duplicate, dict) or duplicate.get("decision") != "unique":
                issues.append(f"{candidate_id} cannot be added without a unique duplicate decision")
            item = candidate.get("item")
            if not isinstance(item, dict):
                issues.append(f"{candidate_id} has no item object")
                continue
            if not item.get("itemType") or not item.get("title"):
                issues.append(f"{candidate_id} item requires itemType and title")
            provenance = candidate.get("provenance")
            if not isinstance(provenance, list) or not provenance:
                issues.append(f"{candidate_id} has no provenance")
                continue
            covered: set[str] = set()
            for source in provenance:
                if not source_is_valid(source):
                    issues.append(f"{candidate_id} has malformed provenance")
                    continue
                covered.update(str(field) for field in source["fields"])
            missing = material_fields(item) - covered
            if missing:
                issues.append(f"{candidate_id} lacks provenance for: {', '.join(sorted(missing))}")
        elif decision == "reuse":
            reuse_ids.append(candidate_id)
            if not candidate.get("existing_item_key"):
                issues.append(f"{candidate_id} reuse lacks existing_item_key")
            if not isinstance(duplicate, dict) or duplicate.get("decision") != "duplicate":
                issues.append(f"{candidate_id} reuse requires duplicate decision")
        elif decision == "skip_duplicate":
            if not isinstance(duplicate, dict) or duplicate.get("decision") != "duplicate":
                issues.append(f"{candidate_id} skip_duplicate requires duplicate decision")

    if not isinstance(planned, list):
        issues.append("planned-items.json must be an array")
        planned = []
    planned_ids = [
        str(entry.get("candidate_id", "")) for entry in planned if isinstance(entry, dict)
    ]
    if planned_ids != add_ids:
        issues.append("planned-items.json candidate order does not match add candidates")
    for index, entry in enumerate(planned):
        if not isinstance(entry, dict) or not isinstance(entry.get("item"), dict):
            issues.append(f"planned item {index + 1} must contain candidate_id and item")
            continue
        candidate = candidate_by_id.get(str(entry.get("candidate_id", "")))
        if candidate and entry["item"] != candidate.get("item"):
            issues.append(f"planned item {entry.get('candidate_id')} differs from candidates.jsonl")

    reuse_by_candidate = {
        str(result.get("candidate_id", "")): result for result in reuse_results
    }
    for candidate_id in reuse_ids:
        result = reuse_by_candidate.get(candidate_id)
        candidate = candidate_by_id.get(candidate_id, {})
        if not result:
            issues.append(f"{candidate_id} has no reuse result")
            continue
        if result.get("operation") != "add-to-collection" or result.get("http_status") not in {200, 204}:
            issues.append(f"{candidate_id} reuse operation did not succeed")
        if str(result.get("item_key", "")) != str(candidate.get("existing_item_key", "")):
            issues.append(f"{candidate_id} reuse result item key mismatch")

    written_keys: list[str] = []
    written_candidate_by_key: dict[str, str] = {}
    if add_ids:
        if not isinstance(write_result, dict):
            issues.append("write-result.json is required when items are added")
        else:
            if write_result.get("operation") != "create-items":
                issues.append("write-result.json operation must be create-items")
            if write_result.get("request_count") != len(planned):
                issues.append("write-result request_count does not match planned items")
            if write_result.get("candidate_ids") != planned_ids:
                issues.append("write-result candidate_ids do not match planned items")
            expected_hash = hashlib.sha256(
                json.dumps(unwrapped_items(planned), sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
            if write_result.get("request_sha256") != expected_hash:
                issues.append("write-result request hash does not match planned items")
            failed = write_result.get("failed")
            if not isinstance(failed, dict):
                issues.append("write-result failed map is missing")
            elif failed:
                issues.append(f"write-result contains {len(failed)} failed item(s)")
            written_at_index: dict[int, str] = {}
            for mapping_name in ("successful", "unchanged"):
                mapping = write_result.get(mapping_name) or {}
                if not isinstance(mapping, dict):
                    issues.append(f"write-result {mapping_name} must be an object")
                    continue
                for raw_index, value in mapping.items():
                    key = successful_key(value)
                    if not key:
                        issues.append(f"write-result {mapping_name} entry lacks an item key")
                    else:
                        try:
                            index = int(raw_index)
                        except (TypeError, ValueError):
                            issues.append(f"write-result {mapping_name} has nonnumeric index {raw_index!r}")
                            continue
                        if index in written_at_index:
                            issues.append(f"write-result repeats item index {index}")
                        written_at_index[index] = key
            written_keys = [written_at_index[index] for index in range(len(planned)) if index in written_at_index]
            if set(written_at_index) != set(range(len(planned))):
                issues.append("write-result indexes do not cover every planned item exactly once")
            if len(set(written_keys)) != len(written_keys):
                issues.append("write-result maps multiple planned items to the same Zotero key")
            written_candidate_by_key = {
                written_at_index[index]: planned_ids[index]
                for index in range(len(planned)) if index in written_at_index
            }
            if len(written_keys) != len(planned):
                issues.append("number of written item keys does not match planned items")
    elif write_result:
        warnings.append("write-result.json exists but there are no add candidates")

    verification_by_key: dict[str, dict[str, Any]] = {}
    if written_keys:
        if not isinstance(verification, dict) or not isinstance(verification.get("results"), list):
            issues.append("verification.json is required for written items")
        else:
            for result in verification["results"]:
                if isinstance(result, dict) and result.get("key"):
                    result_key = str(result["key"])
                    if result_key in verification_by_key:
                        issues.append(f"verification repeats item key {result_key}")
                    verification_by_key[result_key] = result

    manual_by_key: dict[str, dict[str, Any]] = {}
    for entry in manual:
        key = str(entry.get("item_key", ""))
        if not key:
            issues.append("manual verification lacks item_key")
            continue
        if key in manual_by_key:
            issues.append(f"manual verification repeats item key {key}")
        if entry.get("verdict") != "MANUAL_PASS":
            issues.append(f"manual verification for {key} has invalid verdict")
        url = str(entry.get("source_url", ""))
        checked = entry.get("checked_fields")
        if not url.startswith("https://") or not entry.get("accessed_at") or not entry.get("source_type"):
            issues.append(f"manual verification for {key} lacks source metadata")
        if not isinstance(checked, list) or "title" not in checked or len(checked) < 2:
            issues.append(f"manual verification for {key} must check title and another field")
        if not entry.get("note"):
            issues.append(f"manual verification for {key} lacks a note")
        expected_candidate = written_candidate_by_key.get(key)
        if expected_candidate and str(entry.get("candidate_id", "")) != expected_candidate:
            issues.append(f"manual verification for {key} has the wrong candidate_id")
        manual_by_key[key] = entry

    for key in written_keys:
        machine = verification_by_key.get(key)
        if machine and machine.get("verdict") == "PASS":
            continue
        if machine and key in manual_by_key and machine.get("verdict") in {"NO_IDENTIFIER", "UNRESOLVED", "UNAVAILABLE"}:
            continue
        verdict = machine.get("verdict") if machine else "missing"
        issues.append(f"item {key} has no PASS or MANUAL_PASS (machine verdict: {verdict})")
    extra_verified = set(verification_by_key) - set(written_keys)
    if extra_verified:
        warnings.append("verification includes non-written keys: " + ", ".join(sorted(extra_verified)))

    attachment_by_parent: dict[str, dict[str, Any]] = {}
    for entry in attachments:
        parent = str(entry.get("parent_item_key", ""))
        if not parent:
            issues.append("attachment result lacks parent_item_key")
            continue
        if parent in attachment_by_parent:
            issues.append(f"attachment results repeat parent item {parent}")
        if entry.get("schema_version") != 1 or entry.get("status") != "VERIFIED":
            issues.append(f"attachment for {parent} is not VERIFIED schema version 1")
        if not re.fullmatch(r"[A-Z0-9]{8}", str(entry.get("attachment_item_key", ""))):
            issues.append(f"attachment for {parent} lacks a valid Zotero attachment key")
        if entry.get("content_type") != "application/pdf" or not str(entry.get("filename", "")).lower().endswith(".pdf"):
            issues.append(f"attachment for {parent} is not recorded as a PDF")
        if not isinstance(entry.get("size"), int) or entry.get("size", 0) <= 5:
            issues.append(f"attachment for {parent} has an invalid size")
        if not re.fullmatch(r"[a-f0-9]{32}", str(entry.get("md5", ""))):
            issues.append(f"attachment for {parent} has an invalid md5")
        if not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256", ""))):
            issues.append(f"attachment for {parent} has an invalid sha256")
        if entry.get("source_mode") not in {
            "url", "file", "existing"
        }:
            issues.append(f"attachment for {parent} has an invalid source_mode")
        if not entry.get("verified_at"):
            issues.append(f"attachment for {parent} lacks verified_at")
        attachment_by_parent[parent] = entry

    required_attachment_keys: set[str] = set()
    if isinstance(run, dict) and run.get("require_pdfs"):
        required_attachment_keys.update(written_keys)
        for candidate_id in reuse_ids:
            existing = str(candidate_by_id.get(candidate_id, {}).get("existing_item_key", ""))
            if existing:
                required_attachment_keys.add(existing)
        if not attachment_path.exists():
            issues.append("attachment-results.jsonl is required when require_pdfs is true")
        missing_attachments = required_attachment_keys - set(attachment_by_parent)
        if missing_attachments:
            issues.append("missing verified PDF attachments for: " + ", ".join(sorted(missing_attachments)))
    extra_attachments = set(attachment_by_parent) - (set(written_keys) | {
        str(candidate_by_id.get(candidate_id, {}).get("existing_item_key", ""))
        for candidate_id in reuse_ids
    })
    extra_attachments.discard("")
    if extra_attachments:
        warnings.append("attachment results include non-target parent keys: " + ", ".join(sorted(extra_attachments)))

    summary = {
        "candidates": len(candidates),
        "add": len(add_ids),
        "reuse": len(reuse_ids),
        "skip_duplicate": sum(1 for value in candidates if value.get("decision") == "skip_duplicate"),
        "exclude": sum(1 for value in candidates if value.get("decision") == "exclude"),
        "written": len(written_keys),
        "machine_pass": sum(
            1 for key in written_keys
            if verification_by_key.get(key, {}).get("verdict") == "PASS"
        ),
        "manual_pass": sum(
            1 for key in written_keys
            if key in manual_by_key
            and verification_by_key.get(key, {}).get("verdict") in {"NO_IDENTIFIER", "UNRESOLVED", "UNAVAILABLE"}
        ),
        "pdfs_required": len(required_attachment_keys),
        "pdfs_verified": sum(1 for key in required_attachment_keys if key in attachment_by_parent),
    }
    ready = not issues
    audit = {
        "schema_version": 1,
        "status": "READY" if ready else "NOT_READY",
        "audited_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "summary": summary,
        "issues": issues,
        "warnings": warnings,
    }
    (run_dir / "audit.json").write_text(
        json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(audit["status"])
    print(json.dumps(summary, sort_keys=True))
    for issue in issues:
        print(f"- {issue}")
    for warning in warnings:
        print(f"- warning: {warning}")

    if args.require_ready and not ready:
        return 1
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
