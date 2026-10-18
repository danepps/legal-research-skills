#!/usr/bin/env python3
"""Create neutral audit packets for rejected high-impact proofreading findings."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from common import file_sha256, read_json, read_jsonl, write_jsonl


PACKET_SIZE = 8
AUDIT_CATEGORIES = {"possible_omission", "duplication", "xref", "numbering"}
BLOCK_ID_PATTERN = re.compile(r"\b(?:B\d{6}|FN\d+)\b")
CLAUSE_MARKER_PATTERN = re.compile(r"\b(?:whether|if)\b", flags=re.IGNORECASE)


def unique_by_id(rows: list[dict], path: Path, key: str) -> dict[str, dict]:
    indexed: dict[str, dict] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value:
            raise ValueError(f"{path}: every row requires a non-empty {key}")
        if value in indexed:
            raise ValueError(f"{path}: duplicate {key}: {value}")
        indexed[value] = row
    return indexed


def local_snapshot(run_dir: Path, manifest: dict) -> Path | None:
    candidates = sorted(run_dir.glob("source-snapshot.*"))
    if len(candidates) > 1:
        raise ValueError(f"{run_dir}: multiple source snapshots found")
    if candidates:
        return candidates[0]
    manifest_path = Path(str(manifest.get("draft_path", ""))).expanduser()
    return manifest_path if manifest_path.is_file() else None


def related_block_ids(finding: dict, primary_id: str) -> list[str]:
    searchable = " ".join(
        str(finding.get(name, ""))
        for name in ("excerpt", "message", "suggestion")
    )
    return list(dict.fromkeys(
        block_id for block_id in BLOCK_ID_PATTERN.findall(searchable)
        if block_id != primary_id
    ))


def source_context(
    finding: dict,
    block_by_id: dict[str, dict],
    story_items: dict[str, list[dict]],
) -> dict:
    location = finding.get("location")
    if not isinstance(location, dict):
        raise ValueError(f"finding {finding.get('finding_id')}: location must be an object")
    block_id = location.get("block_id")
    if not isinstance(block_id, str) or block_id not in block_by_id:
        raise ValueError(f"finding {finding.get('finding_id')}: unknown source block {block_id!r}")
    located = block_by_id[block_id]
    text = str(located.get("text", ""))
    start = int(location.get("char_start", 0) or 0)
    end = int(location.get("char_end", start) or start)
    offsets_within_extracted_text = 0 <= start <= end <= len(text)

    siblings = story_items.get(str(located.get("story")), [])
    sibling_index = next((index for index, item in enumerate(siblings) if item.get("block_id") == block_id), None)
    before = siblings[sibling_index - 1] if sibling_index is not None and sibling_index > 0 else None
    after = siblings[sibling_index + 1] if sibling_index is not None and sibling_index + 1 < len(siblings) else None
    mentioned = []
    for related_id in related_block_ids(finding, block_id):
        related = block_by_id.get(related_id)
        if related is not None:
            mentioned.append(related)

    return {
        "located_block": located,
        "exact_character_span": {
            "char_start": start,
            "char_end": end,
            "extracted_block_length": len(text),
            "offsets_within_extracted_text": offsets_within_extracted_text,
            "text": text[start:end] if offsets_within_extracted_text else None,
        },
        "previous_block_same_story": before,
        "next_block_same_story": after,
        "explicitly_referenced_blocks": mentioned,
    }


def requires_clause_analysis(finding: dict, context: dict) -> bool:
    if finding.get("category") != "possible_omission":
        return False
    located = context["located_block"]
    location = finding.get("location", {})
    text = str(located.get("text", ""))
    start = int(location.get("char_start", 0) or 0)
    end = int(location.get("char_end", start) or start)
    nearby = text[max(0, start - 300):min(len(text), end + 300)]
    evidence = " ".join((
        str(finding.get("excerpt", "")),
        str(finding.get("message", "")),
        nearby,
    ))
    return bool(CLAUSE_MARKER_PATTERN.search(evidence))


def structural_index(document: dict, symbols: dict | None) -> dict:
    heading_blocks = [
        block for block in document.get("blocks", [])
        if block.get("kind") == "heading"
    ]
    value = {"heading_blocks": heading_blocks}
    if symbols is not None:
        value.update({
            "indexed_headings": symbols.get("headings", []),
            "display_note_to_block": symbols.get("display_note_to_block", {}),
        })
    return value


def render_packet(
    packet_id: str,
    source_hash: str,
    packet_findings: list[tuple[dict, dict, bool]],
    result_path: Path,
    structure: dict | None,
) -> str:
    lines = [
        f"# Independent candidate audit {packet_id}",
        "",
        f"Source SHA-256: `{source_hash}`",
        "",
        "Independently assess each candidate from the frozen source context below. "
        "Do not infer that a candidate is correct or incorrect from its presence in this packet. "
        "No prior disposition or rationale is provided.",
        "",
        f"Write exactly one JSONL row per finding to `{result_path}`. Preserve any existing rows "
        "for other findings. Each row must have:",
        "",
        "- `finding_id`: the exact finding ID in this packet;",
        "- `source_sha256`: the exact source hash above;",
        "- `rejection_status`: `confirmed_rejection`, `reopen`, or `revised`;",
        "- `verifier`: the verifier name or identifier;",
        "- `rationale`: a specific, source-grounded explanation; and",
        "- optional `revised_suggestion`: a replacement suggestion when `rejection_status` is `revised`.",
        "",
        "Use `confirmed_rejection` when the candidate is not an internal textual defect; `reopen` "
        "when the candidate identifies a real defect substantially as stated; and `revised` when "
        "there is a real issue but the candidate or proposed correction needs material revision.",
        "",
        "The context objects contain the complete, untruncated extracted text and metadata for the "
        "located source block, its immediately adjacent blocks in the same story, and any block IDs "
        "explicitly named by the candidate. Treat those objects as frozen source evidence.",
        "",
    ]
    if structure is not None:
        lines.extend([
            "## Frozen structural index",
            "",
            "Use this extracted heading and displayed-note index only as supporting evidence. "
            "Automatic Word numbering or field behavior may require inspection of the frozen source snapshot.",
            "",
            "```json",
            json.dumps(structure, indent=2, ensure_ascii=False),
            "```",
            "",
        ])
    for number, (finding, context, clause_analysis) in enumerate(packet_findings, 1):
        lines.extend([
            f"## Candidate {number}: {finding['finding_id']}",
            "",
            "### Candidate record",
            "",
            "```json",
            json.dumps(finding, indent=2, ensure_ascii=False),
            "```",
            "",
            "### Full frozen source context",
            "",
            "```json",
            json.dumps(context, indent=2, ensure_ascii=False),
            "```",
            "",
        ])
        if clause_analysis:
            lines.extend([
                "### Required whether/if-clause analysis",
                "",
                "Before assigning a status, identify the grammatical subject and the finite predicate "
                "of the entire whether/if clause. State both in the rationale; if either is absent, "
                "say so explicitly. Do not treat an infinitive or a predicate inside a nested modifier "
                "as the finite predicate of the entire clause.",
                "",
            ])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()

    required = ("run-manifest.json", "document.json", "findings.jsonl", "dispositions.jsonl")
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        parser.error(f"run directory lacks required files: {', '.join(missing)}")

    try:
        manifest = read_json(run_dir / "run-manifest.json")
        document = read_json(run_dir / "document.json")
        findings = read_jsonl(run_dir / "findings.jsonl")
        dispositions = read_jsonl(run_dir / "dispositions.jsonl")
        finding_by_id = unique_by_id(findings, run_dir / "findings.jsonl", "finding_id")
        disposition_by_id = unique_by_id(dispositions, run_dir / "dispositions.jsonl", "finding_id")
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    source_hash = manifest.get("draft_sha256")
    if not isinstance(source_hash, str) or not source_hash:
        parser.error("run-manifest.json lacks draft_sha256")
    if document.get("input_sha256") != source_hash:
        parser.error("document source hash differs from run manifest")
    snapshot = local_snapshot(run_dir, manifest)
    if snapshot is not None and file_sha256(snapshot) != source_hash:
        parser.error(f"frozen source snapshot hash differs from run manifest: {snapshot}")

    blocks = document.get("blocks", []) + document.get("notes", [])
    block_by_id = {
        str(block.get("block_id")): block
        for block in blocks if isinstance(block, dict) and block.get("block_id")
    }
    if len(block_by_id) != len(blocks):
        parser.error("document contains a missing or duplicate block ID")
    story_items: dict[str, list[dict]] = {}
    for block in blocks:
        story_items.setdefault(str(block.get("story")), []).append(block)
    for values in story_items.values():
        values.sort(key=lambda item: (int(item.get("order", 0) or 0), str(item.get("block_id"))))

    selected = []
    for finding in findings:
        finding_id = finding["finding_id"]
        disposition = disposition_by_id.get(finding_id)
        if (
            finding.get("impact") == "high"
            and finding.get("category") in AUDIT_CATEGORIES
            and disposition is not None
            and disposition.get("status") == "rejected"
        ):
            if finding.get("source_sha256") != source_hash:
                parser.error(f"finding has stale source hash: {finding_id}")
            try:
                context = source_context(finding, block_by_id, story_items)
            except ValueError as exc:
                parser.error(str(exc))
            selected.append((finding, context, requires_clause_analysis(finding, context)))

    unknown_dispositions = sorted(set(disposition_by_id) - set(finding_by_id))
    if unknown_dispositions:
        parser.error(f"dispositions reference unknown findings: {', '.join(unknown_dispositions[:5])}")

    symbols_path = run_dir / "symbols.json"
    symbols = read_json(symbols_path) if symbols_path.is_file() else None
    if symbols is not None and symbols.get("source_sha256") != source_hash:
        parser.error("symbols source hash differs from run manifest")
    structure = structural_index(document, symbols)

    packet_dir = run_dir / "rejection-packets"
    result_dir = run_dir / "rejection-results"
    packet_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)
    audit_path = run_dir / "rejection-audit.jsonl"
    if audit_path.exists():
        try:
            read_jsonl(audit_path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            parser.error(str(exc))
    else:
        audit_path.write_text("", encoding="utf-8")

    manifest_rows = []
    for start in range(0, len(selected), PACKET_SIZE):
        packet_number = start // PACKET_SIZE + 1
        packet_id = f"RP{packet_number:04d}"
        packet_findings = selected[start:start + PACKET_SIZE]
        packet_path = packet_dir / f"{packet_id}.md"
        result_path = result_dir / f"{packet_id}.jsonl"
        if not result_path.exists():
            result_path.write_text("", encoding="utf-8")
        packet_structure = structure if any(
            finding.get("category") in {"xref", "numbering"}
            for finding, _context, _clause_analysis in packet_findings
        ) else None
        packet_path.write_text(
            render_packet(packet_id, source_hash, packet_findings, result_path, packet_structure),
            encoding="utf-8",
        )
        manifest_rows.append({
            "packet_id": packet_id,
            "source_sha256": source_hash,
            "finding_ids": [finding["finding_id"] for finding, _context, _clause in packet_findings],
            "finding_count": len(packet_findings),
            "packet_path": str(packet_path),
            "result_path": str(result_path),
            "whether_if_clause_analysis_ids": [
                finding["finding_id"]
                for finding, _context, clause in packet_findings if clause
            ],
        })

    write_jsonl(run_dir / "rejection-packets.jsonl", manifest_rows)
    print(json.dumps({
        "run_dir": str(run_dir),
        "selected_findings": len(selected),
        "packets": len(manifest_rows),
        "packet_size_limit": PACKET_SIZE,
        "manifest": str(run_dir / "rejection-packets.jsonl"),
        "audit": str(audit_path),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
