#!/usr/bin/env python3
"""Map an external Markdown proofread report into a frozen proofread run.

The importer is deliberately optional: it writes a separate challenger ledger
and never edits the canonical findings ledger or the frozen source snapshot.
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

from common import file_sha256, normalize_space, read_json, read_jsonl, stable_id, write_json, write_jsonl


ITEM_RE = re.compile(
    r"^\s*(?:[-*+]\s+)?"
    r"(?:"
    r"(?:\*\*(?P<bold_location>[^*\n]+)\*\*|"
    r"(?P<plain_location>(?:¶\s*\d+|n\.\s*\d+|note\s+\d+|B\d{6}|FN\S+)))"
    r"\s*(?:—|–|:|-)\s*"
    r")?"
    r"`(?P<excerpt>(?:\\`|[^`])+)`"
    r"\s*(?:—|–|:|-)\s*(?P<tail>.+?)\s*$",
    flags=re.IGNORECASE,
)
PLACEHOLDER_RE = re.compile(r"\[FN#\d+\]", flags=re.IGNORECASE)
SEPARATOR_RE = re.compile(r"\s+[—–]\s+")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")

TYPOGRAPHY = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        "…": "...",
        "\u00a0": " ",
    }
)

VALID_CATEGORIES = {
    "typo", "duplication", "possible_omission", "grammar", "punctuation", "delimiter",
    "xref", "heading", "numbering", "footnote", "defined_term", "consistency", "formatting", "other",
}


def normalize_with_map(text: str, *, strip_placeholders: bool = False) -> tuple[str, list[int]]:
    """Return comparison text plus a normalized-index to source-index map."""
    ignored: set[int] = set()
    if strip_placeholders:
        for match in PLACEHOLDER_RE.finditer(text):
            ignored.update(range(match.start(), match.end()))

    output: list[str] = []
    source_indexes: list[int] = []
    pending_space: int | None = None
    for index, character in enumerate(text):
        if index in ignored:
            continue
        converted = unicodedata.normalize("NFKC", character).translate(TYPOGRAPHY)
        for normalized_character in converted:
            if normalized_character.isspace():
                if output and pending_space is None:
                    pending_space = index
                continue
            if pending_space is not None:
                output.append(" ")
                source_indexes.append(pending_space)
                pending_space = None
            output.append(normalized_character)
            source_indexes.append(index)
    return "".join(output), source_indexes


def find_occurrences(haystack: str, needle: str) -> list[tuple[int, int]]:
    matches: list[tuple[int, int]] = []
    start = 0
    while needle and (found := haystack.find(needle, start)) >= 0:
        matches.append((found, found + len(needle)))
        start = found + 1
    return matches


def parse_report(path: Path) -> list[dict]:
    rows: list[dict] = []
    section = ""
    for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        heading = HEADING_RE.match(line)
        if heading:
            section = normalize_space(heading.group(1))
            continue
        match = ITEM_RE.match(line)
        if not match:
            continue
        tail_parts = SEPARATOR_RE.split(match.group("tail"), maxsplit=1)
        message = normalize_space(tail_parts[0])
        suggestion = normalize_space(tail_parts[1]) if len(tail_parts) == 2 else "Review manually."
        rows.append(
            {
                "report_line": line_number,
                "report_section": section,
                "report_location": normalize_space(match.group("bold_location") or match.group("plain_location") or ""),
                "report_excerpt": match.group("excerpt").replace(r"\`", "`"),
                "message": message,
                "suggestion": suggestion,
            }
        )
    return rows


def infer_category(message: str, suggestion: str) -> str:
    text = f"{message} {suggestion}".lower()
    rules = (
        ("xref", ("cross-reference", "cross reference", "supra note", "infra section", "does not exist")),
        ("numbering", ("numbering", "numbered subsection", "section numbers")),
        ("possible_omission", ("missing", "omitted", "dropped", "incomplete", "fragment", "no predicate", "no verb")),
        ("duplication", ("duplicate", "doubled", "repeated", "leftover")),
        ("delimiter", ("unbalanced", "unpaired", "mismatched", "quotation mark", "parenthes")),
        ("punctuation", ("punctuation", "comma", "apostrophe", "hyphen", "terminal period")),
        ("heading", ("heading", "title-cased", "title case")),
        ("defined_term", ("defined term",)),
        ("consistency", ("inconsistent", "standardize", "dominant", "deviates", "variant")),
        ("typo", ("typo", "misspell", "capitalized", "capitalization")),
        ("grammar", ("grammar", "ungrammatical", "agreement", "parallel", "article", "preposition", "possessive")),
        ("footnote", ("footnote", "author note", "citation")),
        ("formatting", ("formatting", "italics", "small caps")),
    )
    for category, needles in rules:
        if any(needle in text for needle in needles):
            return category
    return "other"


def infer_impact(section: str, category: str, message: str) -> str:
    text = f"{section} {message}".lower()
    if category in {"xref", "numbering"} or any(
        phrase in text
        for phrase in ("missing", "omitted", "opposite", "alter meaning", "inversion", "no predicate", "no verb")
    ):
        return "high"
    if category in {"punctuation", "formatting"} and not any(
        phrase in text for phrase in ("unbalanced", "unpaired", "mismatched")
    ):
        return "low"
    return "medium"


def candidate_blocks(location: str, blocks: list[dict], notes: list[dict], symbols: dict) -> tuple[list[dict], str | None]:
    label = normalize_space(location)
    direct = re.fullmatch(r"(B\d{6}|FN\S+)", label, flags=re.IGNORECASE)
    if direct:
        block_id = direct.group(1).upper()
        selected = [row for row in blocks + notes if str(row.get("block_id", "")).upper() == block_id]
        return selected, None if selected else f"reported block {block_id} is absent from document.json"

    note = re.fullmatch(r"(?:n\.|note)\s*(\d+)", label, flags=re.IGNORECASE)
    if note:
        display = note.group(1)
        block_id = symbols.get("display_note_to_block", {}).get(display)
        if block_id:
            selected = [row for row in notes if row.get("block_id") == block_id]
            return selected, None if selected else f"displayed note {display} maps to absent block {block_id}"
        # Older or plain-text runs may not expose displayed-note mappings.
        return notes, None

    if re.fullmatch(r"¶\s*\d+", label):
        return blocks, None
    return blocks + notes, None


def map_item(item: dict, pool: list[dict]) -> tuple[list[dict], str]:
    needle, _ = normalize_with_map(item["report_excerpt"], strip_placeholders=True)
    if not needle:
        return [], "excerpt is empty after placeholder and whitespace normalization"
    matches: list[dict] = []
    for block in pool:
        text = str(block.get("text", ""))
        normalized_text, index_map = normalize_with_map(text)
        for start, end in find_occurrences(normalized_text, needle):
            if not index_map:
                continue
            char_start = index_map[start]
            char_end = index_map[end - 1] + 1
            matches.append(
                {
                    "block": block,
                    "char_start": char_start,
                    "char_end": char_end,
                    "excerpt": text[char_start:char_end],
                    "normalized_excerpt": needle,
                }
            )
    if not matches:
        return [], "normalized excerpt was not found in the eligible frozen blocks or notes"
    if len(matches) > 1:
        return matches, f"normalized excerpt has {len(matches)} eligible occurrences and is not unique"
    return matches, ""


def validate_frozen_source(run_dir: Path, manifest: dict, document: dict) -> str:
    source_hash = str(manifest.get("draft_sha256") or "")
    if not source_hash:
        raise ValueError("run manifest lacks draft_sha256")
    if document.get("input_sha256") != source_hash:
        raise ValueError("source hashes differ between run-manifest.json and document.json")
    snapshot_value = manifest.get("draft_path") or manifest.get("source_snapshot", {}).get("path")
    snapshot = Path(str(snapshot_value)).expanduser()
    if not snapshot.is_absolute():
        snapshot = run_dir / snapshot
    if not snapshot.is_file():
        raise ValueError(f"frozen source snapshot is missing: {snapshot}")
    if file_sha256(snapshot) != source_hash:
        raise ValueError("frozen source snapshot hash differs from run manifest")
    return source_hash


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    run_dir = args.run_dir.expanduser().resolve()
    report = args.report.expanduser().resolve()
    if not run_dir.is_dir():
        parser.error(f"run directory does not exist: {run_dir}")
    if not report.is_file():
        parser.error(f"report does not exist: {report}")

    try:
        manifest = read_json(run_dir / "run-manifest.json")
        document = read_json(run_dir / "document.json")
        symbols_path = run_dir / "symbols.json"
        symbols = read_json(symbols_path) if symbols_path.is_file() else {}
        source_hash = validate_frozen_source(run_dir, manifest, document)
        parsed = parse_report(report)
        report_hash = file_sha256(report)
        blocks = [row for row in document.get("blocks", []) if isinstance(row, dict)]
        notes = [row for row in document.get("notes", []) if isinstance(row, dict)]
        mapped: list[dict] = []
        unmatched: list[dict] = []

        for item in parsed:
            pool, location_error = candidate_blocks(item["report_location"], blocks, notes, symbols)
            matches, match_error = map_item(item, pool) if not location_error else ([], location_error)
            identity = (
                source_hash, report_hash, item["report_line"], item["report_location"],
                item["report_excerpt"], item["message"],
            )
            if len(matches) != 1:
                unmatched.append(
                    {
                        "unmatched_id": stable_id(*identity, prefix="CHU"),
                        "source_sha256": source_hash,
                        "report_path": str(report),
                        "report_sha256": report_hash,
                        **item,
                        "normalized_excerpt": normalize_with_map(item["report_excerpt"], strip_placeholders=True)[0],
                        "status": "pending",
                        "reason": match_error,
                        "match_count": len(matches),
                        "candidate_locations": [
                            {
                                "block_id": match["block"].get("block_id"),
                                "char_start": match["char_start"],
                                "char_end": match["char_end"],
                            }
                            for match in matches
                        ],
                    }
                )
                continue

            match = matches[0]
            block = match["block"]
            category = infer_category(item["message"], item["suggestion"])
            if category not in VALID_CATEGORIES:
                category = "other"
            impact = infer_impact(item["report_section"], category, item["message"])
            finding_id = stable_id(
                *identity, block.get("block_id"), match["char_start"], match["char_end"], prefix="CH"
            )
            mapped.append(
                {
                    "finding_id": finding_id,
                    "source_sha256": source_hash,
                    "origin": "challenger",
                    "source_id": f"{report.name}:{item['report_line']}",
                    "rule_id": f"challenger.{category}",
                    "category": category,
                    "severity": "warning",
                    "impact": impact,
                    "confidence": 0.75,
                    "detection": "semantic",
                    "location": {
                        "story": block.get("story"),
                        "block_id": block.get("block_id"),
                        "char_start": match["char_start"],
                        "char_end": match["char_end"],
                        "heading_path": block.get("heading_path", []),
                    },
                    "excerpt": match["excerpt"],
                    "message": item["message"] or "Challenger-reported proofreading candidate.",
                    "suggestion": item["suggestion"],
                    "status": "candidate",
                    "report_path": str(report),
                    "report_sha256": report_hash,
                    "report_line": item["report_line"],
                    "report_section": item["report_section"],
                    "report_location": item["report_location"],
                    "report_excerpt": item["report_excerpt"],
                }
            )

        findings_path = run_dir / "challenger-findings.jsonl"
        unmatched_path = run_dir / "challenger-unmatched.jsonl"
        existing_mapped = read_jsonl(findings_path)
        existing_unmatched = read_jsonl(unmatched_path)
        preserved_unmatched = {row.get("unmatched_id"): row for row in existing_unmatched if row.get("report_sha256") == report_hash}
        for row in unmatched:
            prior = preserved_unmatched.get(row.get("unmatched_id"))
            if prior and prior.get("status") in {"resolved", "waived"}:
                row["status"] = prior["status"]
                row["resolution"] = prior.get("resolution")
        all_mapped = [row for row in existing_mapped if row.get("report_sha256") != report_hash] + mapped
        all_unmatched = [row for row in existing_unmatched if row.get("report_sha256") != report_hash] + unmatched
        unmatched_counts = {
            status: sum(1 for row in unmatched if row.get("status") == status)
            for status in ("pending", "resolved", "waived")
        }
        write_jsonl(findings_path, all_mapped)
        write_jsonl(unmatched_path, all_unmatched)
        ingest_record = {
            "report_path": str(report),
            "report_sha256": report_hash,
            "source_sha256": source_hash,
            "counts": {
                "parsed": len(parsed),
                "mapped": len(mapped),
                "unmatched": len(unmatched),
                **unmatched_counts,
            },
            "outputs": {
                "findings": "challenger-findings.jsonl",
                "unmatched": "challenger-unmatched.jsonl",
            },
        }
        manifest["challenger_ingest"] = ingest_record
        reports = [row for row in manifest.get("challenger_reports", []) if row.get("report_sha256") != report_hash]
        reports.append(ingest_record)
        manifest["challenger_reports"] = sorted(reports, key=lambda row: (row.get("report_path", ""), row.get("report_sha256", "")))
        write_json(run_dir / "run-manifest.json", manifest)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(
        f"parsed {len(parsed)} challenger items; mapped {len(mapped)} uniquely; "
        f"unmatched={len(unmatched)} "
        f"(pending={unmatched_counts['pending']}, resolved={unmatched_counts['resolved']}, waived={unmatched_counts['waived']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
