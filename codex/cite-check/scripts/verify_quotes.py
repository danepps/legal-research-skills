#!/usr/bin/env python3
"""Match draft quotations against a retrieved source-text file.

The script answers a narrow, deterministic question: whether the supplied
quotation occurs in this particular file. It does not establish source
identity, proposition support, honest framing, or authoritative pagination.

Statuses:
  verbatim    exact modulo whitespace
  normalized  exact after typographic folding
  altered     matches after honoring marked ellipses/brackets; review required
  not_found   no match in this file; a closest-passage hint may be included

Use --json with rows containing prepared_unit_id, unit_id, source_id, quote,
and optional pincite. Use --output to write validator-ready JSONL evidence.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from bisect import bisect_right
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


FOLD: dict[str, str] = {}
for character in "‘’‚‛′‵“”„‟″‶'\"":
    FOLD[character] = "'"
for character in "‐‑‒–—―−":
    FOLD[character] = "-"
FOLD[" "] = " "
LIGATURES = {
    "ﬀ": "ff",
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}
PAGE_MARKER = re.compile(r"<<pg\.\s*(\d+)>>")
STAR_MARKER = re.compile(r"\*(\d{1,4})")
ELLIPSIS = re.compile(r"\.[ ]?\.[ ]?\.(?:[ ]?\.)?")
BRACKET = re.compile(r"\[([^\][]{0,80})\]")
PUNCTUATION = re.compile(r"[^0-9A-Za-z]+")
MAX_CHAIN_RESTARTS = 50
MAX_ELLIPSIS_GAP = 600


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def page_spans(raw: str) -> tuple[list[tuple[int, int, int | None]], str]:
    explicit = [
        (match.start(), match.end(), int(match.group(1)))
        for match in PAGE_MARKER.finditer(raw)
    ]
    if explicit:
        return explicit, "explicit_page_marker"
    form_feeds = [(match.start(), match.end(), None) for match in re.finditer("\f", raw)]
    if form_feeds:
        return form_feeds, "form_feed"
    stars = [
        (match.start(), match.end(), int(match.group(1)))
        for match in STAR_MARKER.finditer(raw)
    ]
    numbers = [row[2] for row in stars]
    if len(stars) >= 3 and all(
        isinstance(left, int)
        and isinstance(right, int)
        and 0 < right - left <= 5
        for left, right in zip(numbers, numbers[1:])
    ):
        return stars, "star_marker_sequence"
    return [], "none"


def normalize(
    raw: str,
    *,
    fold: bool,
    spans: list[tuple[int, int, int | None]] | None = None,
) -> tuple[str, list[int], list[tuple[int, int | None]]]:
    """Return normalized text, normalized-to-raw offsets, and page boundaries."""
    output: list[str] = []
    offsets: list[int] = []
    boundaries: list[tuple[int, int | None]] = []
    pending_space = False
    page_rows = spans or []
    page_index = 0

    def emit(character: str, source_index: int) -> None:
        nonlocal pending_space
        if pending_space and output:
            output.append(" ")
            offsets.append(source_index)
        pending_space = False
        output.append(character)
        offsets.append(source_index)

    index = 0
    while index < len(raw):
        if page_index < len(page_rows) and index == page_rows[page_index][0]:
            boundaries.append(
                (len(output) + (1 if pending_space and output else 0), page_rows[page_index][2])
            )
            index = page_rows[page_index][1]
            page_index += 1
            pending_space = True
            continue
        character = raw[index]
        if character.isspace():
            pending_space = True
            index += 1
            continue
        if fold:
            character = FOLD.get(character, character)
            if character == "­":
                index += 1
                continue
            if character in LIGATURES:
                for folded_character in LIGATURES[character]:
                    emit(folded_character, index)
                index += 1
                continue
            if ord(character) > 127:
                decomposed = unicodedata.normalize("NFKC", character)
                if decomposed != character and decomposed.isascii():
                    for folded_character in decomposed:
                        emit(folded_character, index)
                    index += 1
                    continue
            if character == "-":
                previous_is_letter = bool(output) and output[-1].isalpha() and not pending_space
                dash_count = 1
                cursor = index + 1
                while cursor < len(raw) and FOLD.get(raw[cursor], raw[cursor]) == "-":
                    dash_count += 1
                    cursor += 1
                whitespace_start = cursor
                crossed_line = False
                while cursor < len(raw) and raw[cursor].isspace():
                    crossed_line = crossed_line or raw[cursor] in "\n\r\f\v"
                    cursor += 1
                had_whitespace = cursor > whitespace_start
                if (
                    previous_is_letter
                    and cursor < len(raw)
                    and raw[cursor].isalpha()
                    and dash_count == 1
                    and (not had_whitespace or crossed_line)
                ):
                    index = cursor if had_whitespace else index + 1
                    continue
                pending_space = True
                index = cursor
                continue
        emit(character, index)
        index += 1
    return "".join(output), offsets, boundaries


def printed_page(
    boundaries: list[tuple[int, int | None]],
    marker: str,
    first_page: int | None,
    position: int,
) -> int | None:
    if not boundaries:
        return None
    boundary_index = bisect_right([row[0] for row in boundaries], position) - 1
    if boundary_index < 0:
        explicit = boundaries[0][1]
        if explicit is not None:
            return explicit - 1
        return first_page
    explicit = boundaries[boundary_index][1]
    if explicit is not None:
        return explicit
    if marker != "form_feed" or first_page is None:
        return None
    first_boundary_starts_after_text = boundaries[0][0] > 0
    return first_page + boundary_index + (1 if first_boundary_starts_after_text else 0)


def parse_pincite(value: object) -> tuple[int, int] | None:
    if value in (None, ""):
        return None
    text = str(value)
    numbers = re.findall(r"\d+", text.split("n.")[0] or text)
    if not numbers:
        return None
    start = int(numbers[0])
    end = start
    if len(numbers) > 1:
        endpoint = numbers[1]
        if int(endpoint) < start and len(endpoint) < len(numbers[0]):
            endpoint = numbers[0][: len(numbers[0]) - len(endpoint)] + endpoint
        end = max(start, int(endpoint))
    return start, end


def marked_segments(quote: str) -> list[str]:
    return [segment.strip() for segment in ELLIPSIS.split(quote) if segment.strip()]


def segment_pattern(segment: str) -> re.Pattern[str]:
    pieces: list[str] = []
    cursor = 0
    for match in BRACKET.finditer(segment):
        pieces.append(re.escape(segment[cursor : match.start()]))
        inner = match.group(1).strip()
        if inner.casefold() == "sic":
            pieces.append(r"\s?")
        elif len(inner) <= 2:
            pieces.append(r".{0,4}")
        else:
            pieces.append(r".{0,%d}?" % (len(inner) + 20))
        cursor = match.end()
    pieces.append(re.escape(segment[cursor:]))
    return re.compile("".join(pieces))


def match_marked(source: str, patterns: list[re.Pattern[str]]) -> tuple[int, int, list[int]] | None:
    anchor = 0
    for _ in range(MAX_CHAIN_RESTARTS):
        first = patterns[0].search(source, anchor)
        if first is None:
            return None
        cursor = first.end()
        gaps: list[int] = []
        final = first
        for pattern in patterns[1:]:
            following = pattern.search(source, cursor)
            if following is None:
                break
            gaps.append(following.start() - cursor)
            cursor = following.end()
            final = following
        else:
            return first.start(), final.end(), gaps
        anchor = first.start() + 1
    return None


def occurrence_count(source: str, needle: str) -> int:
    count = 0
    cursor = 0
    while count < 5:
        found = source.find(needle, cursor)
        if found < 0:
            break
        count += 1
        cursor = found + max(1, len(needle))
    return count


def closest_passage(
    source: str, offsets: list[int], raw: str, probe: str
) -> tuple[float, str, str]:
    if not source or not probe:
        return 0.0, "", ""
    length = len(probe)
    step = max(10, length // 4)
    matcher = SequenceMatcher(autojunk=False)
    matcher.set_seq2(probe)
    best_ratio = 0.0
    best_index = 0
    stop = max(1, len(source) - length + 1)
    for index in range(0, stop, step):
        matcher.set_seq1(source[index : index + length])
        if matcher.real_quick_ratio() <= best_ratio:
            continue
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = index
    lower = max(0, best_index - step)
    upper = min(max(0, len(source) - length), best_index + step)
    for index in range(lower, upper + 1, max(1, step // 8)):
        matcher.set_seq1(source[index : index + length])
        ratio = matcher.ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_index = index
    if best_ratio < 0.5:
        return best_ratio, "", ""
    start = max(0, best_index - 60)
    end = min(len(source), best_index + length + 60)
    while start > 0 and source[start - 1] != " ":
        start -= 1
    while end < len(source) and source[end] != " ":
        end += 1
    raw_start = offsets[start]
    raw_end = offsets[end - 1] + 1
    return best_ratio, raw[raw_start:raw_end].strip(), source[start:end]


def word_diff(quote: str, source_window: str) -> dict[str, Any]:
    draft_words = quote.split()
    source_words = source_window.split()
    draft_keys = [PUNCTUATION.sub("", word).casefold() for word in draft_words]
    source_keys = [PUNCTUATION.sub("", word).casefold() for word in source_words]
    matcher = SequenceMatcher(None, draft_keys, source_keys, autojunk=False)
    result: dict[str, Any] = {}
    for operation, i1, i2, j1, j2 in matcher.get_opcodes():
        if operation == "equal":
            cosmetic = [
                f"{left} ~ {right}"
                for left, right in zip(draft_words[i1:i2], source_words[j1:j2])
                if left != right
            ]
            if cosmetic:
                result.setdefault("cosmetic", []).extend(cosmetic)
        elif operation == "delete":
            result.setdefault("draft_only", []).extend(draft_words[i1:i2])
        elif operation == "insert":
            if j1 != 0 and j2 != len(source_words):
                result.setdefault("source_only", []).extend(source_words[j1:j2])
        else:
            result.setdefault("changed", []).append(
                {
                    "draft": " ".join(draft_words[i1:i2]),
                    "source": " ".join(source_words[j1:j2]),
                }
            )
    return result


def check_quote(
    raw: str,
    views: dict[bool, tuple[str, list[int], list[tuple[int, int | None]]]],
    marker: str,
    first_page: int | None,
    item: dict[str, Any],
) -> dict[str, Any]:
    quote = str(item.get("quote", ""))
    result: dict[str, Any] = {"quote": quote, "warnings": []}
    plain_quote = normalize(quote, fold=False)[0]
    folded_quote = normalize(quote, fold=True)[0]
    status: str | None = None
    span: tuple[int, int] | None = None

    plain_source = views[False][0]
    if plain_quote:
        found = plain_source.find(plain_quote)
        if found >= 0:
            status = "verbatim"
            span = (found, found + len(plain_quote))
            result["occurrences"] = occurrence_count(plain_source, plain_quote)

    folded_source, folded_offsets, _ = views[True]
    if status is None and folded_quote:
        found = folded_source.find(folded_quote)
        if found >= 0:
            status = "normalized"
            span = (found, found + len(folded_quote))
            result["occurrences"] = occurrence_count(folded_source, folded_quote)
            result["note"] = "matched after typographic folding"

    if status is None:
        segments = marked_segments(folded_quote)
        marked = len(segments) > 1 or BRACKET.search(folded_quote)
        if marked and segments:
            marked_match = match_marked(
                folded_source, [segment_pattern(segment) for segment in segments]
            )
            if marked_match:
                start, end, gaps = marked_match
                status = "altered"
                span = (start, end)
                result["alteration_reviewed"] = False
                result["requires_judgment"] = True
                result["note"] = "marked alteration matched; honesty and framing require review"
                if any(gap > MAX_ELLIPSIS_GAP for gap in gaps):
                    result["warnings"].append("large_gap_between_ellipsis_segments")

    if status is None:
        result["status"] = "not_found"
        result["requires_judgment"] = True
        probe = max(marked_segments(folded_quote) or [folded_quote], key=len)
        ratio, hint, window = closest_passage(folded_source, folded_offsets, raw, probe)
        result["best_ratio"] = round(ratio, 3)
        if hint:
            result["hint"] = hint
            differences = word_diff(probe, window)
            if differences:
                result["word_diff"] = differences
        result["reason"] = "no match in this retrieved source-text file"
        return result

    result["status"] = status
    view = views[status != "verbatim"]
    _, offsets, boundaries = view
    assert span is not None
    start, end = span
    raw_start = offsets[start]
    raw_end = offsets[end - 1] + 1
    result["match_excerpt"] = raw[raw_start:raw_end][:400]
    page = printed_page(boundaries, marker, first_page, start)
    if page is not None:
        result["page"] = page
        end_page = printed_page(boundaries, marker, first_page, end - 1)
        if end_page is not None and end_page != page:
            result["page_end"] = end_page
    if result.get("occurrences", 1) > 1:
        result["warnings"].append("multiple_matches")
        result["requires_judgment"] = True
    pincite = item.get("pincite")
    parsed_pin = parse_pincite(pincite)
    if parsed_pin:
        result["pincite"] = str(pincite)
        if page is None:
            result["pincite_ok"] = None
            result["warnings"].append("pincite_not_judged_without_page_mapping")
        else:
            low, high = parsed_pin
            page_end = int(result.get("page_end", page))
            result["pincite_ok"] = any(low <= value <= high for value in range(page, page_end + 1))
            if marker == "form_feed":
                result["warnings"].append("printed_page_depends_on_asserted_first_page")
    return result


def load_items(args: argparse.Namespace) -> list[dict[str, Any]]:
    items = [{"quote": quote} for quote in args.quotes]
    if args.json_path:
        loaded = json.loads(args.json_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, list) or any(not isinstance(row, dict) for row in loaded):
            raise ValueError("--json must contain an array of objects")
        items.extend(loaded)
    if not items:
        raise ValueError("provide quotation arguments or --json")
    if any(not str(item.get("quote", "")).strip() for item in items):
        raise ValueError("every quote item requires nonempty quote")
    return items


def artifact_rows(
    source: Path,
    source_hash: str,
    source_characters: int,
    marker: str,
    first_page: int | None,
    items: list[dict[str, Any]],
    results: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    checked_at = datetime.now(timezone.utc).isoformat()
    for item, result in zip(items, results):
        for field in ("prepared_unit_id", "unit_id", "source_id"):
            if not isinstance(item.get(field), str) or not item[field].strip():
                raise ValueError(f"--output requires {field} on every --json row")
        row = {
            "quote_check_id": item.get("quote_check_id")
            or f"QC:{item['prepared_unit_id']}:{item['source_id']}",
            "prepared_unit_id": item["prepared_unit_id"],
            "unit_id": item["unit_id"],
            "source_id": item["source_id"],
            "quote": item["quote"],
            "status": result["status"],
            "source_path": str(source.resolve()),
            "source_sha256": source_hash,
            "source_characters": source_characters,
            "pagination_basis": marker,
            "first_page_asserted": first_page,
            "checked_at": checked_at,
            "warnings": result.get("warnings", []),
        }
        for field in (
            "match_excerpt",
            "occurrences",
            "page",
            "page_end",
            "pincite",
            "pincite_ok",
            "best_ratio",
            "hint",
            "word_diff",
            "reason",
            "requires_judgment",
            "alteration_reviewed",
            "note",
        ):
            if field in result:
                row[field] = result[field]
        rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]], append: bool, replace: bool) -> None:
    existing_ids: set[str] = set()
    if path.exists() and path.stat().st_size:
        if not append and not replace:
            raise ValueError(f"{path} is nonempty; use --append or --replace")
        if append:
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    existing_ids.add(str(json.loads(line).get("quote_check_id", "")))
    new_ids = [str(row["quote_check_id"]) for row in rows]
    if len(new_ids) != len(set(new_ids)):
        raise ValueError("duplicate quote_check_id values in output rows")
    duplicates = sorted(set(new_ids) & existing_ids)
    if duplicates:
        raise ValueError(f"quote_check_id already exists: {', '.join(duplicates)}")
    mode = "a" if append and path.exists() else "w"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open(mode, encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("quotes", nargs="*")
    parser.add_argument("--json", dest="json_path", type=Path)
    parser.add_argument(
        "--first-page",
        type=int,
        help="asserted printed number of the first physical page for form-feed text",
    )
    parser.add_argument("--output", type=Path, help="write validator-ready quote-check JSONL")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--append", action="store_true")
    mode.add_argument("--replace", action="store_true")
    args = parser.parse_args()
    if not args.source.is_file():
        parser.error(f"source file not found: {args.source}")
    try:
        items = load_items(args)
        raw = args.source.read_text(encoding="utf-8", errors="replace")
        spans, marker = page_spans(raw)
        views = {
            fold: normalize(raw, fold=fold, spans=spans)
            for fold in (False, True)
        }
        results = [
            check_quote(raw, views, marker, args.first_page, item)
            for item in items
        ]
        source_hash = file_sha256(args.source)
        report = {
            "source_path": str(args.source.resolve()),
            "source_sha256": source_hash,
            "source_characters": len(raw),
            "pagination_basis": marker,
            "first_page_asserted": args.first_page,
            "results": results,
        }
        if args.output:
            if args.quotes:
                raise ValueError("--output requires identified rows supplied through --json")
            rows = artifact_rows(
                args.source,
                source_hash,
                len(raw),
                marker,
                args.first_page,
                items,
                results,
            )
            write_jsonl(args.output, rows, args.append, args.replace)
            print(json.dumps({"output": str(args.output), "rows": len(rows)}))
        else:
            print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"verify_quotes: {exc}", file=sys.stderr)
        return 2
    return 1 if any(result["status"] == "not_found" for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
