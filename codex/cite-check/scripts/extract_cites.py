#!/usr/bin/env python3
"""Extract paragraphs, footnotes, quotations, and context from DOCX/Markdown/text.

The output is structural evidence for the cite-check workflow. It deliberately
does not parse legal citations or decide which authority supports a quotation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
FN_MARKER = re.compile(r"\[\[FN:([^\]]+)\]\]")
# Nested typographic double quotes need a stack, not a non-greedy regex.
def quotation_spans(text: str):
    stack: list[str] = []
    start = 0
    for index, character in enumerate(text):
        if character not in '“”"':
            continue
        opens = character == '“' or (character == '"' and (
            not stack or (index > 0 and text[index - 1].isspace()
                          and index + 1 < len(text) and text[index + 1].isalnum())))
        if opens:
            if not stack:
                start = index
            stack.append(character)
        elif stack and ((character == '”' and stack[-1] == '“')
                        or (character == '"' and stack[-1] == '"')):
            stack.pop()
            if not stack:
                yield start, index + 1, text[start + 1:index]

REPORTER = (
    r"U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.\s?2d|F\.\s?(?:2d|3d|4th)|"
    r"F\.\s?Supp\.\s?(?:2d|3d)?|A\.\s?(?:2d|3d)|N\.E\.\s?(?:2d|3d)|"
    r"N\.W\.\s?(?:2d)?|P\.\s?(?:2d|3d)?|S\.E\.\s?(?:2d)?|S\.W\.\s?(?:2d|3d)?|So\.\s?(?:2d|3d)?|"
    r"N\.Y\.\s?(?:2d|3d)?|Cal\.\s?(?:2d|3d|4th|5th)?|Mass\.|Va\.|Tex\.|WL"
)
CASE_CITE = re.compile(rf"\b\d{{1,4}}\s+(?:{REPORTER})\s+(?:\([^)]*\)\s+)?\d{{1,10}}\b")
SUPRA = re.compile(r"supra\s+notes?\s+(\d+(?:\s*[-–]\s*\d+)?(?:\s*,\s*\d+(?:\s*[-–]\s*\d+)?)*)", re.IGNORECASE)
SUPRA_WITH_NAME = re.compile(r"([A-Z][A-Za-z'’.-]+)(?:\s+(?:&|and)\s+[A-Z][A-Za-z'’.-]+)?\s*,?\s+$")
SIGNAL_WORDS = {"see", "cf", "but", "compare", "accord", "also", "contra", "and"}
LEADING_ID = re.compile(r"^\s*(?:(?:but\s+)?(?:see(?:\s+also)?|cf\.|accord|contra)\s*[,;]?\s*)?(?:e\.g\.,?\s*)?(?:id\.|ibid\.)", re.IGNORECASE)
DELETED_TAGS = {W + "del", W + "moveFrom"}


def note_key(row: dict) -> int | str | None:
    """Use printed numbers for normal notes and stable IDs for custom marks."""
    number = row.get("number", row.get("footnote_number"))
    return number if number is not None else row.get("note_id")


def visible_nodes(root: ET.Element, include_deleted: bool = False):
    if not include_deleted and root.tag in DELETED_TAGS:
        return
    yield root
    for child in root:
        yield from visible_nodes(child, include_deleted)



def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def cross_reference_metadata(text: str) -> dict[str, object]:
    """Return candidate structure only; do not pretend to parse Bluebook syntax."""
    supra = []
    for match in SUPRA.finditer(text):
        named = SUPRA_WITH_NAME.search(text[:match.start()])
        hint = named.group(1) if named and named.group(1).lower().rstrip(".") not in SIGNAL_WORDS else None
        targets = match.group(1) if re.match(r"supra\s+notes\b", match.group(0), re.IGNORECASE) else re.match(r"\d+", match.group(1)).group(0)
        for part in targets.split(","):
            bounds = re.split(r"\s*[-–]\s*", part.strip())
            low, high = int(bounds[0]), int(bounds[-1])
            # Reject implausible expansions rather than allocating an unbounded range.
            numbers = range(low, high + 1) if low <= high <= low + 1000 else [low]
            for number in numbers:
                supra.append({"note": number, "name_hint": hint})
    return {
        "leading_id": bool(LEADING_ID.search(text)),
        "supra": supra,
        "case_cites": sorted(set(match.group(0) for match in CASE_CITE.finditer(text))),
    }


def element_text(element: ET.Element, include_deleted: bool = False) -> str:
    parts: list[str] = []

    def walk(node: ET.Element, in_deleted: bool = False) -> None:
        deleted = in_deleted or node.tag in DELETED_TAGS
        if deleted and not include_deleted:
            return
        if node.tag == W + "footnoteReference":
            parts.append(f"[[FN:{node.get(W + 'id', '')}]]")
            return
        if node.tag in (W + "t", W + "delText"):
            if include_deleted or not deleted:
                parts.append(node.text or "")
            return
        if node.tag in (W + "tab", W + "br", W + "cr"):
            parts.append(" ")
            return
        if node.tag == W + "noBreakHyphen":
            parts.append("-")
            return
        if node.tag == W + "footnoteRef":
            return
        for child in list(node):
            walk(child, deleted)

    walk(element)
    return "".join(parts)


def sentence_bounds(paragraph: str, start: int, end: int) -> tuple[int, int]:
    boundary = re.compile(r"[.!?](?:[”\"']|\[\[FN:[^\]]+\]\])*\s+")
    abbreviation = re.compile(r"(?:\b(?:v|vs|Id|Ibid|e\.g|i\.e|Co|Inc|Ct|Cir|No|Nos|art|sec|pp|p)\.|\b(?:[A-Z]\.)+)$", re.IGNORECASE)
    breaks = [m for m in boundary.finditer(paragraph)
              if not abbreviation.search(paragraph[:m.start() + 1])]
    left = max((m.end() for m in breaks if m.end() <= start), default=0)
    right = next((m.end() for m in breaks if m.end() >= end), len(paragraph))
    return left, right


def sentence_context(paragraph: str, start: int, end: int) -> str:
    left, right = sentence_bounds(paragraph, start, end)
    return normalize(paragraph[left:right])


def rendered_marker(text: str, id_to_number: dict) -> str:
    return FN_MARKER.sub(lambda m: f"[[FN:{id_to_number.get(m.group(1), m.group(1))}]]", text)


def quote_rows(paragraphs: list[str], id_to_number: dict, min_words: int,
               notes: list[dict] | None = None, blocks: set[int] | None = None) -> list[dict]:
    rows: list[dict] = []
    notes_by_key = {str(note_key(row)): row for row in notes or []}
    for paragraph_number, paragraph in enumerate(paragraphs, 1):
        spans = list(quotation_spans(paragraph))
        block = paragraph_number in (blocks or set())
        if block:
            spans = [(0, len(paragraph), paragraph.strip('“”"'))]
        for start, end, marked_quote in spans:
            quote = normalize(FN_MARKER.sub("", marked_quote))
            if len(quote.split()) < min_words:
                continue
            left, right = sentence_bounds(paragraph, start, end)
            if block:
                left, right = 0, len(paragraph)
            context = paragraph[left:right]
            contained = list(FN_MARKER.finditer(paragraph, start, end))
            after = FN_MARKER.search(paragraph, end, right)
            before = list(FN_MARKER.finditer(paragraph, left, start))
            primary = contained[-1] if contained else after or (before[-1] if before else None)
            inferred = False
            if primary is None:
                after = FN_MARKER.search(paragraph, end)
                before = list(FN_MARKER.finditer(paragraph, 0, start))
                primary = after or (before[-1] if before else None)
                inferred = primary is not None
            key = primary.group(1) if primary else None
            home = notes_by_key.get(key, {})
            references = [int(v) if v.isdigit() else v for v in FN_MARKER.findall(context)]
            rows.append({
                "quote_id": f"Q{len(rows) + 1}", "paragraph_number": paragraph_number,
                "quote": quote, "body_context": normalize(FN_MARKER.sub("", context)),
                "body_context_with_refs": context, "supporting_footnote_numbers": references,
                "primary_supporting_footnote": home.get("number", int(key) if key and key.isdigit() else None),
                "primary_supporting_note_id": home.get("note_id"),
                "primary_inferred_from_paragraph": inferred, "block_quote": block,
            })
    return rows


def paragraph_kind(paragraph: ET.Element, styles: dict[str, ET.Element]) -> tuple[bool, bool]:
    props = paragraph.find(W + "pPr")
    style = props.find(W + "pStyle") if props is not None else None
    style_id = style.get(W + "val", "") if style is not None else ""
    visited = set()
    candidates = [props] if props is not None else []
    is_quote = False
    while style_id and style_id not in visited:
        visited.add(style_id)
        row = styles.get(style_id)
        name = row.find(W + "name") if row is not None else None
        label = style_id + " " + (name.get(W + "val", "") if name is not None else "")
        is_quote |= bool(re.search(r"quote|quotation", label, re.IGNORECASE))
        if row is None:
            break
        candidates.extend(row.findall(W + "pPr"))
        parent = row.find(W + "basedOn")
        style_id = parent.get(W + "val", "") if parent is not None else ""
    indented = False
    for candidate in candidates:
        indent = candidate.find(W + "ind")
        if indent is not None:
            try:
                indented |= int(indent.get(W + "left", indent.get(W + "start", "0"))) > 0
            except ValueError:
                pass
    return is_quote, indented


def parse_docx(path: Path, include_deleted: bool) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        roots = {name: ET.fromstring(archive.read(name)) for name in (
            "word/document.xml", "word/footnotes.xml", "word/endnotes.xml",
            "word/comments.xml", "word/settings.xml", "word/styles.xml")
            if name in archive.namelist()}
    document_root = roots["word/document.xml"]
    footnotes_root = roots.get("word/footnotes.xml")
    visible = list(visible_nodes(document_root, include_deleted))
    issues: list[str] = []
    warnings: list[str] = []
    if any(node.tag == W + "endnoteReference" for node in visible):
        issues.append("Endnotes are not supported by this extractor. Convert them to footnotes in a separate draft copy and initialize a new run; do not publish this extraction as complete.")
    settings = roots.get("word/settings.xml")
    properties = list(document_root.iter(W + "footnotePr"))
    if settings is not None:
        properties = list(settings.iter(W + "footnotePr")) + properties
    start = 1
    for props in properties:
        num_start = props.find(W + "numStart")
        if num_start is not None:
            start = int(num_start.get(W + "val", "1"))
        for tag, allowed in (("numRestart", "continuous"), ("numFmt", "decimal")):
            item = props.find(W + tag)
            if item is not None and item.get(W + "val") != allowed:
                issues.append(f"Unsupported footnote numbering: {tag}={item.get(W + 'val')}; review a copy with continuous decimal numbering.")
    section_properties = list(document_root.iter(W + "footnotePr"))
    if len(section_properties) > 1 and any(row.find(W + "numStart") is not None for row in section_properties):
        issues.append("Section-specific footnote starts require manual normalization in a separate draft copy.")
    if start < 1:
        issues.append("Footnote numStart must be a positive integer.")

    ordered_ids: list[str] = []
    labels: dict[str, int | str] = {}
    marks: dict[str, str] = {}
    next_number = start
    for index, reference in enumerate(visible):
        if reference.tag != W + "footnoteReference":
            continue
        xml_id = reference.get(W + "id", "")
        if xml_id in labels:
            continue
        ordered_ids.append(xml_id)
        if reference.get(W + "customMarkFollows", "").lower() in {"1", "true", "on"}:
            labels[xml_id] = f"fn:{xml_id}"
            following = next((n for n in visible[index + 1:] if n.tag in {W + "t", W + "p", W + "footnoteReference"}), None)
            mark = (following.text or "").strip().split()[0] if following is not None and following.tag == W + "t" and (following.text or "").strip() else ""
            marks[xml_id] = mark or "custom mark"
        else:
            labels[xml_id] = next_number
            next_number += 1

    styles_root = roots.get("word/styles.xml")
    styles = {row.get(W + "styleId", ""): row for row in styles_root or []}
    paragraphs, blocks, block_candidates = [], [], []
    for paragraph in (n for n in visible if n.tag == W + "p"):
        text = normalize(element_text(paragraph, include_deleted=include_deleted))
        if text:
            paragraphs.append(rendered_marker(text, labels))
            is_quote, indented = paragraph_kind(paragraph, styles)
            if is_quote:
                blocks.append(len(paragraphs))
            elif indented:
                block_candidates.append(len(paragraphs))
    footnotes = []
    notes_by_id = {row.get(W + "id", ""): row for row in footnotes_root or [] if row.tag == W + "footnote"}
    for xml_id in ordered_ids:
        node = notes_by_id.get(xml_id)
        pieces = [normalize(element_text(n, include_deleted)) for n in visible_nodes(node, include_deleted) if n.tag == W + "p"] if node is not None else []
        text = normalize(" ".join(pieces))
        if not text:
            issues.append(f"Referenced footnote {labels[xml_id]} is missing or empty; inspect its content before re-extraction.")
        row = {"number": labels[xml_id] if xml_id not in marks else None,
               "note_id": f"fn:{xml_id}", "xml_id": xml_id, "text": text, **cross_reference_metadata(text)}
        if xml_id in marks:
            row["custom_mark"] = marks[xml_id]
        footnotes.append(row)
    tracked_roots = [root for name, root in roots.items() if name in {"word/document.xml", "word/footnotes.xml", "word/endnotes.xml"}]
    return {
        "paragraphs": paragraphs, "footnotes": footnotes,
        "block_quote_paragraphs": blocks, "block_quote_candidates": block_candidates,
        "blocking_issues": issues, "warnings": warnings,
        "tracked_changes": {
            "insertions_present": any(n.tag in {W + "ins", W + "moveTo"} for root in tracked_roots for n in root.iter()),
            "deletions_present": any(n.tag in DELETED_TAGS for root in tracked_roots for n in root.iter()),
            "deleted_text_included": include_deleted,
        },
        "comments_count": len(roots.get("word/comments.xml", [])),
        "id_to_rendered_number": labels,
    }


def parse_markdown_or_text(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    footnotes: list[dict[str, object]] = []
    body_lines: list[str] = []
    current: dict[str, object] | None = None
    definition = re.compile(r"^\[\^([^\]]+)\]:\s*(.*)$")
    for line in text.splitlines():
        match = definition.match(line)
        if match:
            current = {
                "number": int(match.group(1)) if match.group(1).isdigit() else len(footnotes) + 1,
                "xml_id": match.group(1),
                "text": match.group(2).strip(),
            }
            current.update(cross_reference_metadata(str(current["text"])))
            footnotes.append(current)
        elif current is not None and (line.startswith("    ") or line.startswith("\t")):
            current["text"] = normalize(str(current["text"]) + " " + line.strip())
            current.update(cross_reference_metadata(str(current["text"])))
        else:
            current = None
            body_lines.append(line)

    body = "\n".join(body_lines)
    id_to_number = {str(item["xml_id"]): int(item["number"]) for item in footnotes}
    for xml_id, number in id_to_number.items():
        body = body.replace(f"[^{xml_id}]", f"[[FN:{number}]]")
    paragraphs, blocks = [], []
    for chunk in re.split(r"\n\s*\n", body):
        if not normalize(chunk):
            continue
        is_block = all(line.lstrip().startswith(">") for line in chunk.splitlines() if line.strip())
        if is_block:
            chunk = re.sub(r"^\s*>\s?", "", chunk, flags=re.MULTILINE)
        paragraphs.append(normalize(chunk))
        if is_block:
            blocks.append(len(paragraphs))
    return {
        "paragraphs": paragraphs,
        "footnotes": footnotes,
        "tracked_changes": {
            "insertions_present": False,
            "deletions_present": False,
            "deleted_text_included": False,
        },
        "comments_count": 0,
        "id_to_rendered_number": id_to_number,
        "block_quote_paragraphs": blocks,
        "block_quote_candidates": [], "blocking_issues": [], "warnings": [],
    }


def extract_document(path: Path, min_quote_words: int = 8, include_deleted: bool = False) -> dict[str, object]:
    if path.suffix.lower() == ".docx":
        parsed = parse_docx(path, include_deleted)
        input_format = "docx"
    elif path.suffix.lower() in (".md", ".markdown", ".txt"):
        parsed = parse_markdown_or_text(path)
        input_format = path.suffix.lower().lstrip(".")
    else:
        raise ValueError("supported inputs are .docx, .md, .markdown, and .txt")

    paragraphs = list(parsed["paragraphs"])
    id_to_number = dict(parsed["id_to_rendered_number"])
    body_quotes = quote_rows(paragraphs, id_to_number, min_quote_words, parsed["footnotes"], set(parsed.get("block_quote_paragraphs", [])))
    footnote_quotes: list[dict[str, object]] = []
    for footnote in parsed["footnotes"]:
        for _, _, marked in quotation_spans(str(footnote["text"])):
            quote = normalize(marked)
            if len(quote.split()) >= min_quote_words:
                footnote_quotes.append(
                    {
                        "quote_id": f"FQ{len(footnote_quotes) + 1}",
                        "footnote_number": footnote["number"],
                        "note_id": footnote.get("note_id"),
                        "quote": quote,
                        "full_footnote": footnote["text"],
                    }
                )

    notes_by_number = {item["number"]: item for item in parsed["footnotes"] if isinstance(item["number"], int)}
    supra_problem_candidates = []
    for footnote in parsed["footnotes"]:
        for redirect in footnote.get("supra", []):
            target = notes_by_number.get(int(redirect["note"]))
            name_hint = redirect.get("name_hint")
            if target is None or (
                name_hint and name_hint.lower() not in str(target.get("text", "")).lower()
            ):
                supra_problem_candidates.append(
                    {
                        "footnote_number": footnote["number"],
                        "target_note": redirect["note"],
                        "name_hint": name_hint,
                        "reason": "missing_target" if target is None else "name_not_found_in_target",
                    }
                )
    unique_case_cites = sorted(
        {cite for footnote in parsed["footnotes"] for cite in footnote.get("case_cites", [])}
    )

    return {
        "schema_version": 1,
        "input_path": str(path.resolve()),
        "input_sha256": sha256(path),
        "input_format": input_format,
        "minimum_quote_words": min_quote_words,
        "paragraph_count": len(paragraphs),
        "footnote_count": len(parsed["footnotes"]),
        "body_quote_count": len(body_quotes),
        "footnote_quote_count": len(footnote_quotes),
        "unique_case_cite_count": len(unique_case_cites),
        "supra_problem_candidate_count": len(supra_problem_candidates),
        "tracked_changes": parsed["tracked_changes"],
        "comments_count": parsed["comments_count"],
        "blocking_issues": parsed.get("blocking_issues", []),
        "warnings": parsed.get("warnings", []),
        "block_quote_candidates": parsed.get("block_quote_candidates", []),
        "paragraphs": paragraphs,
        "footnotes": parsed["footnotes"],
        "body_quotes": body_quotes,
        "footnote_quotes": footnote_quotes,
        "unique_case_cites": unique_case_cites,
        "supra_problem_candidates": supra_problem_candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-quote-words", type=int, default=8)
    parser.add_argument("--include-deleted", action="store_true")
    args = parser.parse_args()
    if not args.input.is_file():
        parser.error(f"input file not found: {args.input}")
    if args.min_quote_words < 1:
        parser.error("--min-quote-words must be positive")
    try:
        data = extract_document(args.input, args.min_quote_words, args.include_deleted)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        print(f"extract_cites: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
        summary = {key: data[key] for key in (
            "footnote_count", "body_quote_count", "footnote_quote_count",
            "unique_case_cite_count", "supra_problem_candidate_count", "tracked_changes"
        )}
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
