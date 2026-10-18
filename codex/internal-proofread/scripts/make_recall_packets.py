#!/usr/bin/env python3
"""Create an independent, fine-grained second-pass proofreading packet set."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_json, read_jsonl, word_count, write_jsonl


def require_first_pass_complete(run_dir: Path, manifest: dict, source_hash: str, findings_path: Path) -> None:
    """Refuse to create recall packets before the blind first pass is complete and merged."""
    chunks_path = run_dir / "chunks.jsonl"
    if not chunks_path.is_file():
        raise FileNotFoundError(f"{chunks_path} is missing")
    chunks = read_jsonl(chunks_path)
    if not chunks:
        raise ValueError("chunks.jsonl is empty")
    result_paths: list[Path] = []
    for chunk in chunks:
        chunk_id = str(chunk.get("chunk_id") or "")
        path = run_dir / "agent-results" / f"{chunk_id}.json"
        if not path.is_file():
            raise FileNotFoundError(f"first pass is incomplete; missing chunk result {chunk_id}")
        result = read_json(path)
        if result.get("chunk_id") != chunk_id or result.get("source_sha256") != source_hash:
            raise ValueError(f"first-pass chunk identity/hash mismatch: {chunk_id}")
        if result.get("status") != "complete":
            raise ValueError(f"first-pass chunk is not complete: {chunk_id}")
        if set(result.get("reviewed_block_ids", [])) != set(chunk.get("core_block_ids", [])):
            raise ValueError(f"first-pass block coverage mismatch: {chunk_id}")
        if set(result.get("reviewed_note_ids", [])) != set(chunk.get("owned_note_ids", [])):
            raise ValueError(f"first-pass note coverage mismatch: {chunk_id}")
        if not isinstance(result.get("findings", []), list):
            raise ValueError(f"first-pass findings must be an array: {chunk_id}")
        result_paths.append(path)
    for lane in manifest.get("required_lanes", []):
        path = run_dir / "lane-results" / f"{lane}.json"
        if not path.is_file():
            raise FileNotFoundError(f"first pass is incomplete; missing lane result {lane}")
        result = read_json(path)
        if result.get("lane") != lane or result.get("source_sha256") != source_hash:
            raise ValueError(f"first-pass lane identity/hash mismatch: {lane}")
        if result.get("status") != "complete":
            raise ValueError(f"first-pass lane is not complete: {lane}")
        if not isinstance(result.get("findings", []), list):
            raise ValueError(f"first-pass lane findings must be an array: {lane}")
        result_paths.append(path)
    if result_paths and findings_path.stat().st_mtime < max(path.stat().st_mtime for path in result_paths):
        raise ValueError("findings.jsonl is stale; run merge_findings.py after all first-pass results")


def item_words(item: dict) -> int:
    value = item.get("word_count")
    if isinstance(value, int) and value >= 0:
        return value
    return word_count(str(item.get("text", "")))


def bounded_body_packets(items: list[dict], minimum: int, target: int, maximum: int) -> list[list[dict]]:
    """Partition sequential blocks, using dynamic programming to honor word bounds."""
    if not items:
        return []
    prefix = [0]
    for item in items:
        prefix.append(prefix[-1] + item_words(item))

    count = len(items)
    costs: list[float] = [float("inf")] * (count + 1)
    previous: list[int | None] = [None] * (count + 1)
    costs[0] = 0
    for end in range(1, count + 1):
        for start in range(end - 1, -1, -1):
            words = prefix[end] - prefix[start]
            oversized_single = end - start == 1 and words > maximum
            whole_short_document = start == 0 and end == count and words < minimum
            if words > maximum and not oversized_single:
                break
            if words < minimum and not whole_short_document:
                continue
            if costs[start] == float("inf"):
                continue
            exception_penalty = 10**12 if oversized_single or whole_short_document else 0
            candidate = costs[start] + exception_penalty + (words - target) ** 2
            if candidate < costs[end]:
                costs[end] = candidate
                previous[end] = start

    if previous[count] is None:
        return greedy_body_fallback(items, minimum, maximum)

    packets: list[list[dict]] = []
    end = count
    while end:
        start = previous[end]
        if start is None:
            raise RuntimeError("internal packet partition failure")
        packets.append(items[start:end])
        end = start
    packets.reverse()
    return packets


def greedy_body_fallback(items: list[dict], minimum: int, maximum: int) -> list[list[dict]]:
    """Keep ownership total and sequential when block granularity makes the bounds impossible."""
    packets: list[list[dict]] = []
    current: list[dict] = []
    words = 0
    for item in items:
        count = item_words(item)
        if current and words + count > maximum:
            packets.append(current)
            current = []
            words = 0
        current.append(item)
        words += count
    if current:
        if packets and words < minimum:
            previous_words = sum(item_words(item) for item in packets[-1])
            if previous_words + words <= maximum:
                packets[-1].extend(current)
            else:
                packets.append(current)
        else:
            packets.append(current)
    return packets


def bounded_note_packets(items: list[dict], target: int, maximum: int, max_notes: int) -> list[list[dict]]:
    """Partition notes with both word and item-count ceilings."""
    packets: list[list[dict]] = []
    current: list[dict] = []
    words = 0
    for item in items:
        count = item_words(item)
        overflow = current and (words + count > maximum or len(current) >= max_notes)
        target_break = current and words >= target
        if overflow or target_break:
            packets.append(current)
            current = []
            words = 0
        current.append(item)
        words += count
    if current:
        packets.append(current)
    return packets


def validate_unique(items: list[dict], label: str) -> None:
    ids = [str(item.get("block_id")) for item in items]
    if any(value in {"", "None"} for value in ids):
        raise ValueError(f"reviewable {label} item lacks block_id")
    duplicates = sorted({value for value in ids if ids.count(value) > 1})
    if duplicates:
        raise ValueError(f"duplicate reviewable {label} block IDs: {', '.join(duplicates)}")


def finding_spans(findings: list[dict], owned_ids: set[str]) -> list[dict]:
    spans: list[dict] = []
    for finding in findings:
        location = finding.get("location")
        if not isinstance(location, dict):
            continue
        block_id = str(location.get("block_id") or "")
        if block_id not in owned_ids:
            continue
        spans.append({
            "finding_id": str(finding.get("finding_id") or ""),
            "block_id": block_id,
            "char_start": int(location.get("char_start", 0) or 0),
            "char_end": int(location.get("char_end", location.get("char_start", 0)) or 0),
            "category": str(finding.get("category") or "other"),
        })
    return sorted(spans, key=lambda row: (row["block_id"], row["char_start"], row["char_end"], row["finding_id"]))


def render_material(title: str, items: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    for item in items:
        heading = " > ".join(str(value) for value in item.get("heading_path", []))
        metadata = [str(item.get("block_id")), str(item.get("story")), str(item.get("kind"))]
        if heading:
            metadata.append(heading)
        lines.extend([f"[{' | '.join(metadata)}]", str(item.get("text", "")), ""])
    return lines


def write_packet(
    path: Path,
    packet_id: str,
    packet_kind: str,
    items: list[dict],
    source_hash: str,
    block_ids: list[str],
    note_ids: list[str],
    spans: list[dict],
    result_path: Path,
) -> None:
    schema = {
        "packet_id": packet_id,
        "source_sha256": source_hash,
        "status": "complete",
        "reviewed_block_ids": block_ids,
        "reviewed_note_ids": note_ids,
        "findings": [],
    }
    lines = [
        f"# Independent recall packet {packet_id}",
        "",
        f"Source SHA-256: `{source_hash}`",
        f"Packet kind: `{packet_kind}`",
        f"Write the result to: `{result_path}`",
        "",
        "This is an independent second pass. Review every owned item for NEW proofreading findings that the first pass missed. Focus on semantic editing residue, nonadjacent duplication, transposed defined terms, malformed noun phrases, internal consistency, and secondary defects distinguishable from already known defects.",
        "",
        "Do not propose style-only rewrites, improvements in elegance, new organization, substantive argument changes, citation/source research, or quotation verification. Do not infer a source error merely because a proposition seems doubtful.",
        "",
        "The do-not-repeat metadata below identifies spans already surfaced in findings.jsonl. Do not report a finding whose location overlaps a listed span. A distinct secondary defect in the same block is allowed only when its exact span is nonoverlapping and it independently warrants correction.",
        "",
        "Return exactly one JSON object with the keys shown in the result template. Copy packet_id, source_sha256, reviewed_block_ids, and reviewed_note_ids exactly. Use status `complete` and an empty findings array when the owned material is clean. Each finding must follow references/finding-schema.md and use an exact owned block coordinate.",
        "",
        "## Result template",
        "",
        "```json",
        json.dumps(schema, indent=2, ensure_ascii=False),
        "```",
        "",
        "## Do-not-repeat finding spans",
        "",
        "```json",
        json.dumps(spans, indent=2, ensure_ascii=False),
        "```",
        "",
    ]
    lines += render_material("Owned body blocks" if packet_kind == "body" else "Owned notes", items)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--body-min-words", type=int)
    parser.add_argument("--body-target-words", type=int)
    parser.add_argument("--body-max-words", type=int)
    parser.add_argument("--note-target-words", type=int)
    parser.add_argument("--note-max-words", type=int)
    parser.add_argument("--note-max-count", type=int)
    args = parser.parse_args()

    run_dir = args.run_dir.expanduser().resolve()
    manifest = read_json(run_dir / "run-manifest.json")
    depth = str(manifest.get("review_depth") or "exhaustive")
    defaults = {
        "standard": (900, 1050, 1200, 1000, 1200, 40),
        "exhaustive": (600, 750, 900, 700, 900, 30),
    }
    body_min, body_target, body_max, note_target, note_max, note_count = defaults.get(depth, defaults["exhaustive"])
    args.body_min_words = body_min if args.body_min_words is None else args.body_min_words
    args.body_target_words = body_target if args.body_target_words is None else args.body_target_words
    args.body_max_words = body_max if args.body_max_words is None else args.body_max_words
    args.note_target_words = note_target if args.note_target_words is None else args.note_target_words
    args.note_max_words = note_max if args.note_max_words is None else args.note_max_words
    args.note_max_count = note_count if args.note_max_count is None else args.note_max_count
    if not (0 < args.body_min_words <= args.body_target_words <= args.body_max_words):
        parser.error("require 0 < body-min-words <= body-target-words <= body-max-words")
    if not (0 < args.note_target_words <= args.note_max_words):
        parser.error("require 0 < note-target-words <= note-max-words")
    if args.note_max_count <= 0:
        parser.error("require note-max-count > 0")
    document = read_json(run_dir / "document.json")
    findings_path = run_dir / "findings.jsonl"
    if not findings_path.is_file():
        raise FileNotFoundError(f"{findings_path} is missing; run merge_findings.py first")
    findings = read_jsonl(findings_path)

    source_hash = str(manifest.get("draft_sha256") or "")
    document_hash = str(document.get("input_sha256") or "")
    if not source_hash:
        raise ValueError("run-manifest.json lacks draft_sha256")
    if document_hash != source_hash:
        raise ValueError("document source hash differs from run manifest")
    require_first_pass_complete(run_dir, manifest, source_hash, findings_path)
    for finding in findings:
        finding_hash = finding.get("source_sha256")
        if finding_hash and str(finding_hash) != source_hash:
            raise ValueError(f"finding {finding.get('finding_id')} has a different source hash")

    body = [item for item in document.get("blocks", []) if item.get("reviewable")]
    notes = [item for item in document.get("notes", []) if item.get("reviewable")]
    validate_unique(body, "body")
    validate_unique(notes, "note")
    body_packets = bounded_body_packets(body, args.body_min_words, args.body_target_words, args.body_max_words)
    note_packets = bounded_note_packets(notes, args.note_target_words, args.note_max_words, args.note_max_count)

    packets_dir = run_dir / "recall-packets"
    results_dir = run_dir / "recall-results"
    output_manifest = run_dir / "recall-packets.jsonl"
    existing = list(packets_dir.glob("*.md")) if packets_dir.exists() else []
    manifest_has_rows = output_manifest.exists() and bool(output_manifest.read_text(encoding="utf-8").strip())
    if manifest_has_rows or existing:
        raise FileExistsError("recall packet artifacts already exist; use a fresh run copy for a new independent pass")
    packets_dir.mkdir(parents=True, exist_ok=True)
    results_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    packet_specs = [
        (f"RB{index:04d}", "body", packet, [str(item["block_id"]) for item in packet], [])
        for index, packet in enumerate(body_packets, 1)
    ] + [
        (f"RN{index:04d}", "notes", packet, [], [str(item["block_id"]) for item in packet])
        for index, packet in enumerate(note_packets, 1)
    ]
    for packet_id, kind, items, block_ids, note_ids in packet_specs:
        packet_path = packets_dir / f"{packet_id}.md"
        result_path = results_dir / f"{packet_id}.json"
        owned_ids = set(block_ids + note_ids)
        spans = finding_spans(findings, owned_ids)
        owned_words = sum(item_words(item) for item in items)
        within_bounds = (
            args.body_min_words <= owned_words <= args.body_max_words
            if kind == "body"
            else owned_words <= args.note_max_words and len(items) <= args.note_max_count
        )
        row = {
            "packet_id": packet_id,
            "packet_kind": kind,
            "source_sha256": source_hash,
            "reviewed_block_ids": block_ids,
            "reviewed_note_ids": note_ids,
            "owned_word_count": owned_words,
            "owned_item_count": len(items),
            "within_configured_bounds": within_bounds,
            "do_not_repeat_spans": spans,
            "packet_path": str(packet_path.resolve()),
            "result_path": str(result_path.resolve()),
        }
        rows.append(row)
        write_packet(packet_path, packet_id, kind, items, source_hash, block_ids, note_ids, spans, result_path.resolve())

    expected_body = [str(item["block_id"]) for item in body]
    expected_notes = [str(item["block_id"]) for item in notes]
    actual_body = [value for row in rows for value in row["reviewed_block_ids"]]
    actual_notes = [value for row in rows for value in row["reviewed_note_ids"]]
    if actual_body != expected_body or actual_notes != expected_notes:
        raise RuntimeError("recall packet ownership is incomplete, duplicated, or out of order")
    write_jsonl(output_manifest, rows)
    exceptions = sum(not row["within_configured_bounds"] for row in rows)
    print(
        f"created {len(body_packets)} body packets and {len(note_packets)} note packets; "
        f"owned {len(expected_body)} body blocks and {len(expected_notes)} notes exactly once; "
        f"size exceptions: {exceptions}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
