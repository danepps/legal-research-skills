#!/usr/bin/env python3
"""Merge static, chunk-agent, and global-lane findings into one proof ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import normalize_space, read_json, read_jsonl, stable_id, validate_finding_location, write_jsonl


VALID_CATEGORIES = {
    "typo", "duplication", "possible_omission", "grammar", "punctuation", "delimiter",
    "xref", "heading", "numbering", "footnote", "defined_term", "consistency", "formatting", "other",
}


def load_result(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def normalize_agent_finding(raw: dict, source_hash: str, origin: str, source_id: str) -> dict:
    location = raw.get("location") if isinstance(raw.get("location"), dict) else {}
    block_id = location.get("block_id") or raw.get("block_id")
    start = int(location.get("char_start", raw.get("char_start", 0)) or 0)
    end = int(location.get("char_end", raw.get("char_end", start)) or start)
    category = str(raw.get("category", "other"))
    if category not in VALID_CATEGORIES:
        category = "other"
    excerpt = normalize_space(str(raw.get("excerpt") or raw.get("exact_text") or ""))
    suggestion = normalize_space(str(raw.get("suggestion") or raw.get("proposed_change") or ""))
    message = normalize_space(str(raw.get("message") or raw.get("reason") or "Agent-reported proofreading candidate."))
    impact = str(raw.get("impact", "medium")).lower()
    if impact not in {"low", "medium", "high"}:
        impact = "medium"
    confidence = float(raw.get("confidence", 0.75))
    finding_id = str(raw.get("finding_id") or stable_id(source_hash, origin, source_id, block_id, start, end, category, excerpt, prefix="A"))
    return {
        "finding_id": finding_id,
        "source_sha256": source_hash,
        "origin": origin,
        "source_id": source_id,
        "rule_id": str(raw.get("rule_id") or f"{origin}.{category}"),
        "category": category,
        "severity": str(raw.get("severity", "warning")),
        "impact": impact,
        "confidence": max(0.0, min(1.0, confidence)),
        "detection": str(raw.get("detection", "semantic")),
        "location": {
            "story": location.get("story"),
            "block_id": block_id,
            "char_start": start,
            "char_end": end,
            "heading_path": location.get("heading_path", []),
        },
        "excerpt": excerpt,
        "message": message,
        "suggestion": suggestion,
        "status": "candidate",
    }


def substantially_overlaps(left: dict, right: dict) -> bool:
    left_location = left.get("location", {})
    right_location = right.get("location", {})
    if left_location.get("block_id") != right_location.get("block_id") or left.get("category") != right.get("category"):
        return False
    left_start, left_end = int(left_location.get("char_start", 0)), int(left_location.get("char_end", 0))
    right_start, right_end = int(right_location.get("char_start", 0)), int(right_location.get("char_end", 0))
    overlap = max(0, min(left_end, right_end) - max(left_start, right_start))
    shorter = min(max(1, left_end - left_start), max(1, right_end - right_start))
    if overlap / shorter >= 0.5:
        return True
    # Excerpts include surrounding context and may be identical for distinct
    # errors in one paragraph. Coordinates, not excerpt containment, identify
    # an occurrence. Exact zero-width coordinates represent the same insertion.
    return left_start == left_end == right_start == right_end


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = read_json(run_dir / "run-manifest.json")
    source_hash = str(manifest.get("draft_sha256"))
    rows = read_jsonl(run_dir / "static-findings.jsonl") + read_jsonl(run_dir / "challenger-findings.jsonl")
    result_files = (
        sorted((run_dir / "agent-results").glob("*.json"))
        + sorted((run_dir / "lane-results").glob("*.json"))
        + sorted((run_dir / "recall-results").glob("*.json"))
    )
    for path in result_files:
        result = load_result(path)
        if result.get("source_sha256") != source_hash:
            raise ValueError(f"{path}: source hash differs from run manifest")
        if path.parent.name == "agent-results":
            origin = "chunk_agent"
        elif path.parent.name == "recall-results":
            origin = "recall"
        else:
            origin = "global_lane"
        source_id = str(result.get("chunk_id") or result.get("lane") or result.get("packet_id") or path.stem)
        findings = result.get("findings", [])
        if not isinstance(findings, list):
            raise ValueError(f"{path}: findings must be an array")
        for index, item in enumerate(findings):
            if not isinstance(item, dict):
                raise ValueError(f"{path}: finding {index + 1} must be an object")
            rows.append(normalize_agent_finding(item, source_hash, origin, source_id))

    document = read_json(run_dir / "document.json")
    blocks = {block.get("block_id"): block for block in document.get("blocks", []) + document.get("notes", [])}
    for row in rows:
        validate_finding_location(row, blocks)
    order = {block.get("block_id"): index for index, block in enumerate(document.get("blocks", []) + document.get("notes", []), 1)}
    rows.sort(key=lambda row: (
        order.get(row.get("location", {}).get("block_id"), 10**9),
        int(row.get("location", {}).get("char_start", 0)),
        int(row.get("location", {}).get("char_end", 0)),
        row.get("finding_id", ""),
    ))
    merged: list[dict] = []
    for row in rows:
        existing = next((item for item in reversed(merged) if substantially_overlaps(item, row)), None)
        if existing is None:
            copy = dict(row)
            copy["corroborated_by"] = [str(row.get("source_id") or row.get("origin"))]
            copy["merged_finding_ids"] = [str(row.get("finding_id"))]
            merged.append(copy)
            continue
        source = str(row.get("source_id") or row.get("origin"))
        if source not in existing["corroborated_by"]:
            existing["corroborated_by"].append(source)
        merged_id = str(row.get("finding_id"))
        if merged_id not in existing["merged_finding_ids"]:
            existing["merged_finding_ids"].append(merged_id)
        existing["confidence"] = max(float(existing.get("confidence", 0)), float(row.get("confidence", 0)))
        if row.get("impact") == "high":
            existing["impact"] = "high"

    output = sorted(merged, key=lambda row: (
        order.get(row.get("location", {}).get("block_id"), 10**9),
        int(row.get("location", {}).get("char_start", 0)), row.get("finding_id", ""),
    ))
    write_jsonl(run_dir / "findings.jsonl", output)
    print(f"merged {len(rows)} candidates into {len(output)} ledger findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
