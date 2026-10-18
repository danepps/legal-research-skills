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
QUOTE_PATTERN = re.compile(r"[\u201c\"](.+?)[\u201d\"]")
REPORTER = (
    r"U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.\s?2d|F\.\s?(?:2d|3d|4th)|"
    r"F\.\s?Supp\.\s?(?:2d|3d)?|A\.\s?(?:2d|3d)|N\.E\.\s?(?:2d|3d)|"
    r"N\.W\.\s?2d|P\.\s?(?:2d|3d)|S\.E\.\s?2d|S\.W\.\s?(?:2d|3d)|So\.\s?(?:2d|3d)"
)
CASE_CITE = re.compile(rf"\b\d{{1,4}}\s+(?:{REPORTER})\s+\d{{1,4}}\b")
SUPRA = re.compile(r"supra\s+note[s]?\s+(\d+)", re.IGNORECASE)
SUPRA_WITH_NAME = re.compile(
    r"([A-Z][A-Za-z'\u2019.-]+)(?:\s+(?:&|and)\s+[A-Z][A-Za-z'\u2019.-]+)?"
    r"\s*,?\s+supra\s+note[s]?\s+(\d+)",
    re.IGNORECASE,
)
LEADING_ID = re.compile(r"^\s*(?:See\s+)?(?:Id\.|Ibid\.)", re.IGNORECASE)


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
    named = {(int(match.group(2)), match.group(1)) for match in SUPRA_WITH_NAME.finditer(text)}
    for match in SUPRA.finditer(text):
        number = int(match.group(1))
        names = sorted(name for target, name in named if target == number)
        supra.append({"note": number, "name_hint": names[0] if names else None})
    return {
        "leading_id": bool(LEADING_ID.search(text)),
        "supra": supra,
        "case_cites": sorted(set(match.group(0) for match in CASE_CITE.finditer(text))),
    }


def element_text(element: ET.Element, include_deleted: bool = False) -> str:
    parts: list[str] = []

    def walk(node: ET.Element, in_deleted: bool = False) -> None:
        deleted = in_deleted or node.tag == W + "del"
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
        if node.tag == W + "footnoteRef":
            return
        for child in list(node):
            walk(child, deleted)

    walk(element)
    return "".join(parts)


def sentence_context(paragraph: str, start: int, end: int) -> str:
    boundary = re.compile(r"[.!?][\u201d\"']?(?:\[\[FN:[^\]]+\]\])*\s+")
    preceding = list(boundary.finditer(paragraph, 0, start))
    left = preceding[-1].end() if preceding else 0
    following = boundary.search(paragraph, max(start, end - 2))
    right = following.end() if following else len(paragraph)
    return normalize(paragraph[left:right])


def rendered_marker(text: str, id_to_number: dict[str, int]) -> str:
    def replace(match: re.Match[str]) -> str:
        xml_id = match.group(1)
        return f"[[FN:{id_to_number.get(xml_id, xml_id)}]]"

    return FN_MARKER.sub(replace, text)


def quote_rows(
    paragraphs: list[str], id_to_number: dict[str, int], min_words: int
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for paragraph_number, raw_paragraph in enumerate(paragraphs, 1):
        paragraph = rendered_marker(raw_paragraph, id_to_number)
        for match in QUOTE_PATTERN.finditer(paragraph):
            quote = normalize(FN_MARKER.sub("", match.group(1)))
            if len(quote.split()) < min_words:
                continue
            context_with_refs = sentence_context(paragraph, match.start(), match.end())
            references = [
                int(value) if value.isdigit() else value
                for value in FN_MARKER.findall(context_with_refs)
            ]
            after = FN_MARKER.search(paragraph, match.end())
            before = list(FN_MARKER.finditer(paragraph, 0, match.start()))
            primary = None
            if after:
                value = after.group(1)
                primary = int(value) if value.isdigit() else value
            elif before:
                value = before[-1].group(1)
                primary = int(value) if value.isdigit() else value
            rows.append(
                {
                    "quote_id": f"Q{len(rows) + 1}",
                    "paragraph_number": paragraph_number,
                    "quote": quote,
                    "body_context": normalize(FN_MARKER.sub("", context_with_refs)),
                    "body_context_with_refs": context_with_refs,
                    "supporting_footnote_numbers": references,
                    "primary_supporting_footnote": primary,
                }
            )
    return rows


def parse_docx(path: Path, include_deleted: bool) -> dict[str, object]:
    with zipfile.ZipFile(path) as archive:
        document_root = ET.fromstring(archive.read("word/document.xml"))
        footnotes_root = None
        if "word/footnotes.xml" in archive.namelist():
            footnotes_root = ET.fromstring(archive.read("word/footnotes.xml"))
        comments_count = 0
        if "word/comments.xml" in archive.namelist():
            comments_root = ET.fromstring(archive.read("word/comments.xml"))
            comments_count = len(comments_root.findall(W + "comment"))

    paragraphs: list[str] = []
    for paragraph in document_root.iter(W + "p"):
        text = normalize(element_text(paragraph, include_deleted=include_deleted))
        if text:
            paragraphs.append(text)

    ordered_ids: list[str] = []
    for reference in document_root.iter(W + "footnoteReference"):
        xml_id = reference.get(W + "id", "")
        if xml_id not in ordered_ids:
            ordered_ids.append(xml_id)
    id_to_number = {xml_id: index for index, xml_id in enumerate(ordered_ids, 1)}

    footnote_text: dict[str, str] = {}
    if footnotes_root is not None:
        for footnote in footnotes_root.findall(W + "footnote"):
            if footnote.get(W + "type") in ("separator", "continuationSeparator"):
                continue
            xml_id = footnote.get(W + "id", "")
            pieces = [
                normalize(element_text(paragraph, include_deleted=include_deleted))
                for paragraph in footnote.findall(W + "p")
            ]
            footnote_text[xml_id] = normalize(" ".join(piece for piece in pieces if piece))

    footnotes: list[dict[str, object]] = []
    seen = set()
    for xml_id in ordered_ids:
        if xml_id in seen or xml_id not in footnote_text:
            continue
        seen.add(xml_id)
        number = id_to_number.get(xml_id)
        text = footnote_text[xml_id]
        footnotes.append(
            {"number": number, "xml_id": xml_id, "text": text, **cross_reference_metadata(text)}
        )

    return {
        "paragraphs": [rendered_marker(text, id_to_number) for text in paragraphs],
        "footnotes": footnotes,
        "tracked_changes": {
            "insertions_present": document_root.find(".//" + W + "ins") is not None,
            "deletions_present": document_root.find(".//" + W + "del") is not None,
            "deleted_text_included": include_deleted,
        },
        "comments_count": comments_count,
        "id_to_rendered_number": id_to_number,
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
    paragraphs = [normalize(chunk) for chunk in re.split(r"\n\s*\n", body) if normalize(chunk)]
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
    id_to_number = {str(key): int(value) for key, value in dict(parsed["id_to_rendered_number"]).items()}
    body_quotes = quote_rows(paragraphs, id_to_number, min_quote_words)
    footnote_quotes: list[dict[str, object]] = []
    for footnote in parsed["footnotes"]:
        for match in QUOTE_PATTERN.finditer(str(footnote["text"])):
            quote = normalize(match.group(1))
            if len(quote.split()) >= min_quote_words:
                footnote_quotes.append(
                    {
                        "quote_id": f"FQ{len(footnote_quotes) + 1}",
                        "footnote_number": footnote["number"],
                        "quote": quote,
                        "full_footnote": footnote["text"],
                    }
                )

    notes_by_number = {int(item["number"]): item for item in parsed["footnotes"]}
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
