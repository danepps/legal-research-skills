#!/usr/bin/env python3
"""Create owned-core proofreading chunks and whole-document lane packets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from common import read_json, read_jsonl, write_jsonl


def choose_chunks(blocks: list[dict], minimum: int, target: int, maximum: int) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    current: list[dict] = []
    words = 0
    for block in blocks:
        count = int(block.get("word_count", 0))
        heading_break = block.get("kind") == "heading" and words >= minimum
        overflow = current and words >= minimum and words + count > maximum
        target_break = current and words >= target and block.get("kind") in {"heading", "paragraph"}
        if heading_break or overflow or target_break:
            chunks.append(current)
            current = []
            words = 0
        current.append(block)
        words += count
    if current:
        previous_words = sum(int(block.get("word_count", 0)) for block in chunks[-1]) if chunks else 0
        if chunks and words < max(200, minimum // 2) and previous_words + words <= maximum:
            chunks[-1].extend(current)
        else:
            chunks.append(current)
    return chunks


def context(blocks: list[dict], start: int, direction: int, word_limit: int) -> list[dict]:
    selected: list[dict] = []
    words = 0
    index = start
    while 0 <= index < len(blocks) and words < word_limit:
        block = blocks[index]
        selected.append(block)
        words += int(block.get("word_count", 0))
        index += direction
    if direction < 0:
        selected.reverse()
    return selected


def render_blocks(title: str, blocks: list[dict]) -> list[str]:
    lines = [f"## {title}", ""]
    if not blocks:
        lines.append("(none)")
        lines.append("")
        return lines
    for block in blocks:
        heading = " > ".join(block.get("heading_path", []))
        meta = f"[{block.get('block_id')} | {block.get('story')} | {block.get('kind')}"
        if heading:
            meta += f" | {heading}"
        meta += "]"
        lines.extend([meta, str(block.get("text", "")), ""])
    return lines


def compact_notes(rows: list[dict]) -> list[dict]:
    """Keep only note identity fields needed by xref and structure reviewers."""
    keys = ("block_id", "raw_note_id", "display_number", "order", "story")
    return [{key: row.get(key) for key in keys if row.get(key) is not None} for row in rows]


def bounded_excerpt(value: object, limit: int = 120) -> str:
    excerpt = str(value or "")
    return excerpt if len(excerpt) <= limit else excerpt[: limit - 1].rstrip() + "…"


def compact_cross_references(rows: list[dict]) -> list[dict]:
    """Retain every reference and resolution while shortening repeated prose context."""
    compact: list[dict] = []
    for row in rows:
        copy = dict(row)
        copy["excerpt"] = bounded_excerpt(copy.get("excerpt"))
        compact.append(copy)
    return compact


def compact_variant_rows(rows: list[dict]) -> list[dict]:
    """Retain every indexed variant pair with one locating example per variant."""
    compact: list[dict] = []
    for row in rows:
        copy = {key: value for key, value in row.items() if key != "occurrences"}
        seen: set[str] = set()
        occurrences: list[dict] = []
        for occurrence in row.get("occurrences", []):
            variant = str(occurrence.get("variant", ""))
            if variant.casefold() in seen:
                continue
            seen.add(variant.casefold())
            occurrences.append({
                key: bounded_excerpt(occurrence.get(key)) if key == "excerpt" else occurrence.get(key)
                for key in ("variant", "block_id", "char_start", "char_end", "excerpt")
                if occurrence.get(key) is not None
            })
        copy["occurrences"] = occurrences
        compact.append(copy)
    return compact


def compact_residue(rows: list[dict]) -> list[dict]:
    """Retain all residue candidates while bounding repeated context text."""
    compact: list[dict] = []
    for row in rows:
        copy = dict(row)
        copy["excerpt"] = bounded_excerpt(copy.get("excerpt"))
        compact.append(copy)
    return compact


def semantic_note_references(blocks: list[dict], notes: list[dict], symbols: dict) -> list[dict]:
    """Attach the prose needed to test note cross-references semantically."""
    all_by_id = {str(row.get("block_id")): row for row in blocks + notes}
    note_by_block = {str(row.get("block_id")): row for row in notes}
    raw_by_block = {str(row.get("block_id")): str(row.get("note_id")) for row in notes}
    note_order = [str(row.get("block_id")) for row in notes]
    note_index = {block_id: index for index, block_id in enumerate(note_order)}
    call_sites: dict[str, list[dict]] = {}
    for block in blocks:
        for raw_id in map(str, block.get("footnote_ids", [])):
            call_sites.setdefault(raw_id, []).append({
                "block_id": block.get("block_id"),
                "heading_path": block.get("heading_path", []),
                "text": bounded_excerpt(block.get("text", ""), 1200),
            })

    display_by_block = {
        str(row.get("block_id")): row.get("display_number")
        for row in symbols.get("notes", [])
    }
    enriched: list[dict] = []
    for row in symbols.get("cross_references", []):
        if row.get("kind") != "note" or len(row.get("targets", [])) != 1:
            continue
        source_id = str(row.get("block_id"))
        target_id = str(row["targets"][0])
        source = all_by_id.get(source_id)
        target = note_by_block.get(target_id)
        if not source or not target:
            continue
        target_position = note_index.get(target_id, -1)
        neighborhood = []
        if target_position >= 0:
            for neighbor_id in note_order[max(0, target_position - 2): target_position + 3]:
                neighbor = note_by_block[neighbor_id]
                neighborhood.append({
                    "block_id": neighbor_id,
                    "display_number": display_by_block.get(neighbor_id),
                    "text": bounded_excerpt(neighbor.get("text", ""), 700),
                })
        source_raw = raw_by_block.get(source_id)
        target_raw = raw_by_block.get(target_id)
        enriched.append({
            "source_block_id": source_id,
            "source_display_number": display_by_block.get(source_id),
            "source_text": bounded_excerpt(source.get("text", ""), 900),
            "source_call_sites": call_sites.get(source_raw, []) if source_raw else [],
            "reference": {
                key: row.get(key)
                for key in ("direction", "label", "char_start", "char_end", "excerpt")
            },
            "target_block_id": target_id,
            "target_display_number": display_by_block.get(target_id),
            "target_text": bounded_excerpt(target.get("text", ""), 900),
            "target_call_sites": call_sites.get(target_raw, []) if target_raw else [],
            "target_neighborhood": neighborhood,
        })
    return enriched


def write_chunk_packet(path: Path, chunk: dict, core: list[dict], before: list[dict], after: list[dict],
                       owned_notes: list[dict], static_findings: list[dict], source_hash: str) -> None:
    lines = [
        f"# Proofreading packet {chunk['chunk_id']}",
        "",
        f"Source SHA-256: `{source_hash}`",
        "",
        "Review every CORE block and owned footnote. Use context blocks only to understand continuity; do not report defects located only in context.",
        "Find typos, missing or duplicated words, malformed sentences, punctuation problems, and obvious internal inconsistencies. Do not rewrite for elegance, change substantive claims, or silently correct quotations.",
        'Do not treat every `.”).` or `.").` ending as duplicated punctuation. Distinguish a parenthetical consisting entirely of a full-sentence quotation from a quotation grammatically integrated after language such as `explaining that`; report only the form that is wrong in context.',
        "Footnote block IDs such as FN24 are raw OOXML IDs and may not equal Word's displayed note number. Do not propose a supra/infra-number correction from the raw ID; leave cross-reference resolution to the global xref lane.",
        "Return one JSON object to `agent-results/<chunk_id>.json` with `chunk_id`, `source_sha256`, `status`, `reviewed_block_ids`, `reviewed_note_ids`, and `findings`. Each finding must follow `references/finding-schema.md`.",
        "",
    ]
    lines += render_blocks("Context before (not owned)", before)
    lines += render_blocks("CORE blocks (owned)", core)
    lines += render_blocks("Owned footnotes", owned_notes)
    if static_findings:
        lines.extend(["## Static candidates to confirm, reject, or refine", "", "```json"])
        lines.extend(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in static_findings)
        lines.extend(["```", ""])
    lines += render_blocks("Context after (not owned)", after)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_lane_packets(run_dir: Path, chunks: list[dict], blocks: list[dict], notes: list[dict],
                       symbols: dict, source_hash: str) -> list[str]:
    lanes = run_dir / "lane-packets"
    lanes.mkdir(parents=True, exist_ok=True)
    block_by_id = {str(block.get("block_id")): block for block in blocks}
    boundary = [
        "# Boundary and continuity lane",
        "",
        f"Source SHA-256: `{source_hash}`",
        "",
        "Review each seam for duplicated or missing text, broken sentences, abrupt edit artifacts, and transition errors. Return `lane-results/boundary.json` using the lane-result schema.",
        "",
    ]
    for left, right in zip(chunks, chunks[1:]):
        left_blocks = [block_by_id[item] for item in left["core_block_ids"][-2:]]
        right_blocks = [block_by_id[item] for item in right["core_block_ids"][:2]]
        boundary.extend([f"## {left['chunk_id']} → {right['chunk_id']}", ""])
        boundary += render_blocks("Left side", left_blocks)
        boundary += render_blocks("Right side", right_blocks)
    (lanes / "boundary.md").write_text("\n".join(boundary), encoding="utf-8")

    note_index_rows = compact_notes(symbols.get("notes", []))
    packets = {
        "xref": ("Resolve every indexed internal reference against the listed targets. Distinguish internal references from statutes and rules. Use display_note_to_block and each note's display_number; never treat a raw FN block ID as a displayed note number.",
                 {"headings": symbols.get("headings", []), "captions": symbols.get("captions", []), "notes": note_index_rows,
                  "display_note_to_block": symbols.get("display_note_to_block", {}),
                  "cross_references": compact_cross_references(symbols.get("cross_references", [])), "bookmarks": symbols.get("bookmarks", []), "fields": symbols.get("fields", [])}),
        "terminology": ("Review defined terms, names, capitalization, singular/plural forms, acronyms, and hyphenation variants. Report likely inconsistencies, not mere stylistic alternatives.",
                        {"defined_terms": symbols.get("defined_terms", []), "defined_term_variants": symbols.get("defined_term_variants", []),
                         "hyphenation_variants": compact_variant_rows(symbols.get("hyphenation_variants", [])),
                         "open_hyphen_variants": compact_variant_rows(symbols.get("open_hyphen_variants", [])),
                         "lexical_variants": compact_variant_rows(symbols.get("lexical_variants", [])),
                         "term_permutations": compact_variant_rows(symbols.get("term_permutations", [])),
                         "name_order_variants": compact_variant_rows(symbols.get("name_order_variants", []))}),
        "consistency": ("Review semantic editing residue and internal consistency across body text and linked footnotes. Flag transposed defined terms, nonadjacent duplicated concepts, malformed noun phrases, authorial capitalization errors, and conflicting names, dates, or numbers. Treat an unresolved body/footnote conflict as an author query; do not research or silently resolve it. Route accepted spelling and house-style alternatives to the style appendix.",
                        {"semantic_residue_candidates": compact_residue(symbols.get("semantic_residue_candidates", [])),
                         "body_note_numeric_links": symbols.get("body_note_numeric_links", []),
                         "century_note_links": symbols.get("century_note_links", []),
                         "case_citation_variants": symbols.get("case_citation_variants", []),
                         "long_duplicate_spans": symbols.get("long_duplicate_spans", []),
                         "term_permutations": compact_variant_rows(symbols.get("term_permutations", []))}),
        "structure": ("Review heading hierarchy, TOC-derived labels, duplicate or skipped numbering, note sequence, captions, bookmarks, and field-code integrity. Treat toc_entries as the authoritative displayed hierarchy when body heading text omits automatic numbering.",
                      {"headings": symbols.get("headings", []), "captions": symbols.get("captions", []), "notes": note_index_rows,
                       "toc_entries": symbols.get("toc_entries", []),
                       "bookmarks": symbols.get("bookmarks", []), "fields": symbols.get("fields", [])}),
    }
    for name, (instruction, payload) in packets.items():
        text = [f"# {name.title()} lane", "", f"Source SHA-256: `{source_hash}`", "", instruction,
                f"Return `lane-results/{name}.json` using the lane-result schema.", "", "```json", json.dumps(payload, indent=2, ensure_ascii=False), "```", ""]
        (lanes / f"{name}.md").write_text("\n".join(text), encoding="utf-8")

    semantic_refs = semantic_note_references(blocks, notes, symbols)
    semantic_lane_names: list[str] = []
    batch_size = 10
    for index in range(0, len(semantic_refs), batch_size):
        name = f"xref_semantic_{index // batch_size + 1:03d}"
        semantic_lane_names.append(name)
        payload = semantic_refs[index:index + batch_size]
        instruction = (
            "Review every note cross-reference semantically, not merely numerically. Compare the source claim and "
            "source note with the target note and its accompanying body text. Follow short Id. chains using the "
            "included target neighborhood. Report a high-impact xref finding when the target exists but does not "
            "support the source call site; turn genuine ambiguity into an author query."
        )
        text = [
            f"# Semantic xref lane {index // batch_size + 1}", "", f"Source SHA-256: `{source_hash}`", "",
            instruction, f"Return `lane-results/{name}.json` with lane `{name}` using the lane-result schema.",
            "", "```json", json.dumps(payload, indent=2, ensure_ascii=False), "```", "",
        ]
        (lanes / f"{name}.md").write_text("\n".join(text), encoding="utf-8")

    serial_lane_names: list[str] = []
    serial_candidates = list(symbols.get("serial_comma_candidates", []))
    serial_batch_size = 80
    for index in range(0, len(serial_candidates), serial_batch_size):
        name = f"serial_comma_{index // serial_batch_size + 1:03d}"
        serial_lane_names.append(name)
        payload = serial_candidates[index:index + serial_batch_size]
        instruction = (
            "Review every deterministic candidate in context. Decide whether it is a true series of three or more "
            "parallel items in authorial prose that lacks the draft's serial comma, or instead a clause, paired "
            "construction, quotation, or other non-list. Report only true omissions. An empty findings array "
            "certifies that this entire candidate shard was reviewed and clear."
        )
        text = [
            f"# Serial-comma lane {index // serial_batch_size + 1}", "", f"Source SHA-256: `{source_hash}`", "",
            instruction, f"Return `lane-results/{name}.json` with lane `{name}` using the lane-result schema.",
            "", "```json", json.dumps(payload, indent=2, ensure_ascii=False), "```", "",
        ]
        (lanes / f"{name}.md").write_text("\n".join(text), encoding="utf-8")
    return ["boundary", *packets.keys(), *semantic_lane_names, *serial_lane_names]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("document", type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--findings", required=True, type=Path)
    parser.add_argument("--symbols", required=True, type=Path)
    parser.add_argument("--min-words", type=int, default=800)
    parser.add_argument("--target-words", type=int, default=1000)
    parser.add_argument("--max-words", type=int, default=1200)
    parser.add_argument("--context-words", type=int, default=120)
    args = parser.parse_args()
    if not (0 < args.min_words <= args.target_words <= args.max_words):
        parser.error("require 0 < min-words <= target-words <= max-words")
    document = read_json(args.document)
    static = read_jsonl(args.findings)
    symbols = read_json(args.symbols)
    source_hash = str(document.get("input_sha256"))
    blocks = [block for block in document.get("blocks", []) if block.get("reviewable")]
    notes = [note for note in document.get("notes", []) if note.get("reviewable")]
    raw_chunks = choose_chunks(blocks, args.min_words, args.target_words, args.max_words)
    block_index = {block["block_id"]: index for index, block in enumerate(blocks)}
    note_by_id = {str(note.get("note_id")): note for note in notes}
    note_owner: dict[str, int] = {}
    for chunk_no, core in enumerate(raw_chunks):
        for block in core:
            for note_id in block.get("footnote_ids", []):
                if str(note_id) in note_by_id:
                    note_owner.setdefault(str(note_id), chunk_no)
    if raw_chunks:
        for note_id in note_by_id:
            note_owner.setdefault(note_id, len(raw_chunks) - 1)

    chunks: list[dict] = []
    packets = args.run_dir / "packets"
    packets.mkdir(parents=True, exist_ok=True)
    (args.run_dir / "agent-results").mkdir(parents=True, exist_ok=True)
    (args.run_dir / "lane-results").mkdir(parents=True, exist_ok=True)
    for chunk_no, core in enumerate(raw_chunks):
        chunk_id = f"C{chunk_no + 1:04d}"
        start = block_index[core[0]["block_id"]]
        end = block_index[core[-1]["block_id"]]
        before = context(blocks, start - 1, -1, args.context_words)
        after = context(blocks, end + 1, 1, args.context_words)
        owned_note_ids = sorted(
            (note_id for note_id, owner in note_owner.items() if owner == chunk_no),
            key=lambda value: (0, int(value)) if value.isdigit() else (1, value),
        )
        owned_notes = [note_by_id[note_id] for note_id in owned_note_ids]
        core_ids = [block["block_id"] for block in core]
        core_word_count = sum(int(block.get("word_count", 0)) for block in core)
        size_exception = "single_block_exceeds_max" if core_word_count > args.max_words and len(core) == 1 else None
        row = {
            "chunk_id": chunk_id,
            "source_sha256": source_hash,
            "core_block_ids": core_ids,
            "context_before_ids": [block["block_id"] for block in before],
            "context_after_ids": [block["block_id"] for block in after],
            "owned_note_ids": [note["block_id"] for note in owned_notes],
            "core_word_count": core_word_count,
            "within_configured_max": core_word_count <= args.max_words,
            "size_exception": size_exception,
            "packet_path": str((packets / f"{chunk_id}.md").resolve()),
        }
        chunks.append(row)
        candidate_rows = [item for item in static if item.get("location", {}).get("block_id") in set(core_ids + row["owned_note_ids"])]
        write_chunk_packet(packets / f"{chunk_id}.md", row, core, before, after, owned_notes, candidate_rows, source_hash)

    write_jsonl(args.run_dir / "chunks.jsonl", chunks)
    lane_names = write_lane_packets(args.run_dir, chunks, blocks, notes, symbols, source_hash)
    print(f"created {len(chunks)} owned chunks and {len(lane_names)} global lane packets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
