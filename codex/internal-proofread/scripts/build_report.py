#!/usr/bin/env python3
"""Build a document-ordered proofreading report from findings and dispositions."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import read_json, read_jsonl, utc_now, write_json


VISIBLE_STATUSES = {"confirmed", "likely", "query", "fixed", "waived", "style", "prepublication"}
ANCHOR_TARGET_WORDS = 14
ANCHOR_MAX_WORDS = 24


def normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def anchor_occurrences(anchor: str, searchable_texts: list[str]) -> int:
    needle = normalized(anchor).casefold()
    if not needle:
        return 0
    return sum(text.casefold().count(needle) for text in searchable_texts)


def search_anchor(
    row: dict,
    block_by_id: dict[str, dict],
    searchable_texts: list[str],
    note_parent_by_id: dict[str, dict],
    allow_note_fallback: bool = True,
) -> tuple[str, bool]:
    """Return an exact, bounded source span suitable for Ctrl-F in the draft."""
    location = row.get("location", {})
    block_id = str(location.get("block_id") or "")
    block = block_by_id.get(block_id)
    if not block:
        return normalized(row.get("excerpt", "")), False
    text = str(block.get("text", ""))
    words = list(re.finditer(r"\S+", text))
    if not words:
        return normalized(row.get("excerpt", "")), False
    start = max(0, min(len(text), int(location.get("char_start", 0) or 0)))
    end = max(start, min(len(text), int(location.get("char_end", start) or start)))
    overlapping = [
        index for index, match in enumerate(words)
        if match.end() > start and match.start() < max(end, start + 1)
    ]
    if overlapping:
        left, right = overlapping[0], overlapping[-1]
    else:
        center = min(range(len(words)), key=lambda index: abs(words[index].start() - start))
        left = right = center
    if right - left + 1 > ANCHOR_MAX_WORDS:
        midpoint = (start + end) // 2
        center = min(range(left, right + 1), key=lambda index: abs(words[index].start() - midpoint))
        left = max(0, center - ANCHOR_TARGET_WORDS // 2)
        right = min(len(words) - 1, left + ANCHOR_TARGET_WORDS - 1)
        left = max(0, right - ANCHOR_TARGET_WORDS + 1)

    expand_left = True
    while right - left + 1 < ANCHOR_TARGET_WORDS and (left > 0 or right + 1 < len(words)):
        if expand_left and left > 0:
            left -= 1
        elif right + 1 < len(words):
            right += 1
        elif left > 0:
            left -= 1
        expand_left = not expand_left

    def current() -> str:
        return normalized(text[words[left].start():words[right].end()])

    while (
        right - left + 1 < ANCHOR_MAX_WORDS
        and anchor_occurrences(current(), searchable_texts) != 1
        and (left > 0 or right + 1 < len(words))
    ):
        if left > 0:
            left -= 1
        if right - left + 1 < ANCHOR_MAX_WORDS and right + 1 < len(words):
            right += 1
    anchor = current()
    if (
        allow_note_fallback
        and block.get("story") == "footnote"
        and anchor_occurrences(anchor, searchable_texts) != 1
        and block_id in note_parent_by_id
    ):
        parent = note_parent_by_id[block_id]
        parent_row = {"location": {"block_id": parent.get("block_id"), "char_start": 0, "char_end": 0}}
        parent_anchor, _ = search_anchor(
            parent_row, block_by_id, searchable_texts, note_parent_by_id, allow_note_fallback=False
        )
        if parent_anchor:
            return parent_anchor, True
    return anchor, False


def item_text(
    row: dict,
    disposition: dict,
    raw_to_display: dict[str, str],
    block_by_id: dict[str, dict],
    searchable_texts: list[str],
    note_parent_by_id: dict[str, dict],
) -> str:
    location = row.get("location", {})
    block_id = location.get("block_id") or "global"
    block = block_by_id.get(block_id, {})
    body_ids = [key for key, value in block_by_id.items()
                if value.get("story") not in {"footnote", "endnote"}]
    location_label = str(block.get("story") or "Draft").replace("_", " ").title()
    if block_id in raw_to_display:
        location_label = f"Note {raw_to_display[block_id]}"
    elif block_id in body_ids:
        progress = round(100 * body_ids.index(block_id) / max(1, len(body_ids) - 1))
        location_label += f", about {progress}% through draft"
    heading = " > ".join(location.get("heading_path", []))
    where = f"{location_label}" + (f" ({heading})" if heading else "")
    suggestion = disposition.get("suggestion") or row.get("suggestion") or "Review manually."
    rationale = disposition.get("rationale") or row.get("message") or ""
    anchor, uses_note_call_site = search_anchor(row, block_by_id, searchable_texts, note_parent_by_id)
    anchor_suffix = " (note call site)" if uses_note_call_site else ""
    return (
        f"- **{where} — {row.get('category')}** (`{row.get('finding_id')}`, {row.get('impact')} impact)\n"
        f"  - Find in draft: “{anchor}”{anchor_suffix}\n"
        f"  - Draft: “{row.get('excerpt', '')}”\n"
        f"  - Suggested action: {suggestion}\n"
        f"  - Basis: {rationale}"
    )


def section(
    title: str,
    rows: list[tuple[dict, dict]],
    raw_to_display: dict[str, str],
    block_by_id: dict[str, dict],
    searchable_texts: list[str],
    note_parent_by_id: dict[str, dict],
) -> list[str]:
    lines = [f"## {title}", ""]
    if not rows:
        lines.extend(["None.", ""])
    else:
        for row, disposition in rows:
            lines.extend([
                item_text(row, disposition, raw_to_display, block_by_id, searchable_texts, note_parent_by_id),
                "",
            ])
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--status", choices=("complete", "complete_with_limits"))
    parser.add_argument("--include-rejected", action="store_true")
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    manifest = read_json(run_dir / "run-manifest.json")
    document = read_json(run_dir / "document.json")
    symbols = read_json(run_dir / "symbols.json")
    source_blocks = document.get("blocks", []) + document.get("notes", [])
    block_by_id = {
        str(block.get("block_id")): block
        for block in source_blocks if block.get("block_id")
    }
    note_parent_by_id: dict[str, dict] = {}
    for block in document.get("blocks", []):
        for note_id in block.get("footnote_ids", []):
            note_parent_by_id.setdefault(f"FN{note_id}", block)
    searchable_texts = [normalized(block.get("text", "")) for block in source_blocks]
    raw_to_display = {
        block_id: display
        for display, block_id in symbols.get("display_note_to_block", {}).items()
    }
    findings = read_jsonl(run_dir / "findings.jsonl")
    dispositions = {row.get("finding_id"): row for row in read_jsonl(run_dir / "dispositions.jsonl")}
    groups: dict[str, list[tuple[dict, dict]]] = {name: [] for name in ("confirmed", "likely", "query", "fixed", "waived", "style", "prepublication", "rejected", "pending")}
    for row in findings:
        disposition = dispositions.get(row.get("finding_id"), {})
        status = str(disposition.get("status", "pending"))
        groups.setdefault(status, []).append((row, disposition))
    status = args.status or ("complete_with_limits" if groups["query"] or groups["waived"] or groups["pending"] else "complete")
    lines = [
        "# Internal Proofread Report",
        "",
        f"Draft: `{manifest.get('draft_path')}`  ",
        f"Source SHA-256: `{manifest.get('draft_sha256')}`  ",
        f"Run status: **{status}**",
        "",
        "## Needs your attention",
        "",
        f"- Confirmed or fixed errors: {len(groups['confirmed']) + len(groups['fixed'])}",
        f"- Likely errors: {len(groups['likely'])}",
        f"- Author queries: {len(groups['query'])}",
        f"- Pre-publication checks: {len(groups['prepublication'])}",
        f"- Style-consistency suggestions: {len(groups['style'])}",
        f"- Unresolved candidates: {len(groups['pending'])}",
        "",
    ]
    lines += section("Confirmed errors", groups["confirmed"] + groups["fixed"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    lines += section("Likely errors", groups["likely"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    lines += section("Author queries", groups["query"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    lines += section("Pre-publication checks", groups["prepublication"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    lines += section("Style consistency (optional)", groups["style"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    lines += section("Couldn't check", groups["waived"] + groups["pending"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    if args.include_rejected:
        lines += section("Rejected candidates", groups["rejected"], raw_to_display, block_by_id, searchable_texts, note_parent_by_id)
    else:
        lines.extend([
            "## Rejected candidates",
            "",
            f"{len(groups['rejected'])} rejected candidates are retained in `findings.jsonl` and `dispositions.jsonl`; details are omitted from this human-facing report.",
            "",
        ])
    lines.extend(["## Extraction and workflow limitations", ""])
    for limitation in manifest.get("limitations", []):
        lines.append(f"- {limitation}")
    lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    manifest["status"] = status
    manifest["updated_at"] = utc_now()
    manifest["counts"].update({
        "findings": len(findings), "confirmed": len(groups["confirmed"]), "fixed": len(groups["fixed"]),
        "likely": len(groups["likely"]), "queries": len(groups["query"]), "rejected": len(groups["rejected"]),
        "style": len(groups["style"]), "prepublication": len(groups["prepublication"]), "pending": len(groups["pending"]),
    })
    write_json(run_dir / "run-manifest.json", manifest)
    print(f"wrote {run_dir / 'report.md'} with status {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
