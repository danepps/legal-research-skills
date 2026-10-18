#!/usr/bin/env python3
"""Extract DOCX, Markdown, or text drafts into stable proofreading blocks."""

from __future__ import annotations

import argparse
import re
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from common import SCHEMA_VERSION, file_sha256, normalize_space, utc_now, word_count, write_json


W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"


def wtag(name: str) -> str:
    return W + name


def attr(element: ET.Element | None, name: str, default: str = "") -> str:
    if element is None:
        return default
    return element.attrib.get(wtag(name), default)


def visible_text(element: ET.Element) -> tuple[str, list[str], list[str], list[str]]:
    parts: list[str] = []
    note_ids: list[str] = []
    fields: list[str] = []
    bookmarks: list[str] = []

    def walk(node: ET.Element, deleted: bool = False) -> None:
        deleted = deleted or node.tag == wtag("del")
        if deleted:
            return
        if node.tag == wtag("t"):
            parts.append(node.text or "")
            return
        if node.tag == wtag("tab"):
            parts.append("\t")
            return
        if node.tag in {wtag("br"), wtag("cr")}:
            parts.append("\n")
            return
        if node.tag == wtag("footnoteReference"):
            note_id = attr(node, "id")
            if note_id:
                note_ids.append(note_id)
            return
        if node.tag == wtag("instrText"):
            instruction = normalize_space(node.text or "")
            if instruction:
                fields.append(instruction)
            return
        if node.tag == wtag("bookmarkStart"):
            name = attr(node, "name")
            if name and not name.startswith("_"):
                bookmarks.append(name)
        for child in node:
            walk(child, deleted)

    walk(element)
    return normalize_space("".join(parts)), note_ids, fields, bookmarks


def load_styles(archive: zipfile.ZipFile) -> dict[str, dict]:
    try:
        root = ET.fromstring(archive.read("word/styles.xml"))
    except KeyError:
        return {}
    styles: dict[str, dict] = {}
    for style in root.findall(f".//{wtag('style')}"):
        style_id = attr(style, "styleId")
        name = attr(style.find(wtag("name")), "val", style_id)
        outline = attr(style.find(f".//{wtag('outlineLvl')}"), "val")
        styles[style_id] = {"name": name, "outline_level": int(outline) + 1 if outline.isdigit() else None}
    return styles


def paragraph_metadata(paragraph: ET.Element, styles: dict[str, dict]) -> dict:
    ppr = paragraph.find(wtag("pPr"))
    style_id = attr(ppr.find(wtag("pStyle")) if ppr is not None else None, "val")
    style = styles.get(style_id, {"name": style_id, "outline_level": None})
    level = style.get("outline_level")
    if not level:
        match = re.search(r"heading\s*([1-9])", str(style.get("name", "")), re.I)
        if match:
            level = int(match.group(1))
    num_pr = ppr.find(wtag("numPr")) if ppr is not None else None
    return {
        "style_id": style_id or None,
        "style_name": style.get("name") or None,
        "heading_level": level,
        "num_id": attr(num_pr.find(wtag("numId")) if num_pr is not None else None, "val") or None,
        "list_level": attr(num_pr.find(wtag("ilvl")) if num_pr is not None else None, "val") or None,
    }


def make_block(
    block_id: str,
    story: str,
    kind: str,
    order: int,
    text: str,
    heading_path: list[str],
    source_locator: str,
    metadata: dict | None = None,
    note_ids: list[str] | None = None,
    fields: list[str] | None = None,
    bookmarks: list[str] | None = None,
) -> dict:
    return {
        "block_id": block_id,
        "story": story,
        "kind": kind,
        "order": order,
        "text": text,
        "word_count": word_count(text),
        "heading_path": list(heading_path),
        "source_locator": source_locator,
        "reviewable": bool(text.strip()) and kind != "code",
        "footnote_ids": note_ids or [],
        "field_codes": fields or [],
        "bookmarks": bookmarks or [],
        **(metadata or {}),
    }


def extract_docx(path: Path) -> tuple[list[dict], list[dict], list[dict], list[dict], list[str]]:
    blocks: list[dict] = []
    notes: list[dict] = []
    fields_index: list[dict] = []
    bookmarks_index: list[dict] = []
    limitations = [
        "Visible inserted text is included and deleted text is excluded.",
        "Final pagination and page-number references require the user to update fields in Microsoft Word; automated office rendering is not used.",
        "Text contained only in images is not extracted.",
    ]
    with zipfile.ZipFile(path) as archive:
        styles = load_styles(archive)
        heading_stack: list[str] = []
        counter = 0

        def add_paragraph(paragraph: ET.Element, story: str, kind_override: str | None, locator: str) -> None:
            nonlocal counter, heading_stack
            text, note_ids, fields, bookmarks = visible_text(paragraph)
            if not text and not fields and not bookmarks and not note_ids:
                return
            counter += 1
            meta = paragraph_metadata(paragraph, styles)
            kind = kind_override or ("heading" if meta.get("heading_level") else ("list_item" if meta.get("num_id") else "paragraph"))
            if kind == "heading" and text:
                level = int(meta.get("heading_level") or 1)
                heading_stack = heading_stack[: level - 1]
                heading_stack.append(text)
            block_id = f"B{counter:06d}"
            block = make_block(block_id, story, kind, counter, text, heading_stack, locator, meta, note_ids, fields, bookmarks)
            blocks.append(block)
            for instruction in fields:
                fields_index.append({"block_id": block_id, "instruction": instruction})
            for name in bookmarks:
                bookmarks_index.append({"block_id": block_id, "name": name})

        document = ET.fromstring(archive.read("word/document.xml"))
        body = document.find(wtag("body"))
        if body is not None:
            body_index = 0
            for child in body:
                if child.tag == wtag("p"):
                    body_index += 1
                    add_paragraph(child, "body", None, f"word/document.xml/body/p[{body_index}]")
                elif child.tag == wtag("tbl"):
                    for row_no, row in enumerate(child.findall(wtag("tr")), 1):
                        for cell_no, cell in enumerate(row.findall(wtag("tc")), 1):
                            for para_no, paragraph in enumerate(cell.findall(f".//{wtag('p')}"), 1):
                                add_paragraph(
                                    paragraph,
                                    "table",
                                    "table_cell",
                                    f"word/document.xml/table[{body_index + 1}]/row[{row_no}]/cell[{cell_no}]/p[{para_no}]",
                                )

        for member in sorted(name for name in archive.namelist() if re.fullmatch(r"word/(header|footer)\d+\.xml", name)):
            story = "header" if "header" in member else "footer"
            root = ET.fromstring(archive.read(member))
            for para_no, paragraph in enumerate(root.findall(f".//{wtag('p')}"), 1):
                add_paragraph(paragraph, story, story, f"{member}/p[{para_no}]")

        if "word/footnotes.xml" in archive.namelist():
            root = ET.fromstring(archive.read("word/footnotes.xml"))
            note_order = 0
            for footnote in root.findall(wtag("footnote")):
                note_id = attr(footnote, "id")
                note_type = attr(footnote, "type")
                if note_type in {"separator", "continuationSeparator"} or (note_id.lstrip("-").isdigit() and int(note_id) <= 0):
                    continue
                paragraph_texts: list[str] = []
                fields: list[str] = []
                bookmarks: list[str] = []
                for paragraph in footnote.findall(f".//{wtag('p')}"):
                    paragraph_text, _, paragraph_fields, paragraph_bookmarks = visible_text(paragraph)
                    if paragraph_text:
                        paragraph_texts.append(paragraph_text)
                    fields.extend(paragraph_fields)
                    bookmarks.extend(paragraph_bookmarks)
                text = "\n".join(paragraph_texts)
                note_order += 1
                notes.append(
                    make_block(
                        f"FN{note_id}",
                        "footnote",
                        "footnote",
                        note_order,
                        text,
                        [],
                        f"word/footnotes.xml/footnote[@w:id='{note_id}']",
                        {"note_id": note_id},
                        fields=fields,
                        bookmarks=bookmarks,
                    )
                )
    return blocks, notes, fields_index, bookmarks_index, limitations


def markdown_blocks(path: Path) -> tuple[list[dict], list[dict], list[dict], list[dict], list[str]]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    blocks: list[dict] = []
    notes: list[dict] = []
    heading_stack: list[str] = []
    paragraph: list[str] = []
    paragraph_start = 1
    in_fence = False
    counter = 0

    def flush(end_line: int, kind: str = "paragraph") -> None:
        nonlocal paragraph, paragraph_start, counter
        text = normalize_space(" ".join(paragraph))
        if text:
            counter += 1
            blocks.append(make_block(f"B{counter:06d}", "body", kind, counter, text, heading_stack, f"line:{paragraph_start}-{end_line}"))
        paragraph = []

    for line_no, line in enumerate(lines, 1):
        if line.startswith("```") or line.startswith("~~~"):
            flush(line_no - 1)
            in_fence = not in_fence
            paragraph = [line]
            paragraph_start = line_no
            if not in_fence:
                flush(line_no, "code")
            continue
        if in_fence:
            paragraph.append(line)
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*#*\s*$", line)
        footnote = re.match(r"^\[\^([^\]]+)\]:\s*(.*)$", line)
        if heading:
            flush(line_no - 1)
            level = len(heading.group(1))
            text = normalize_space(heading.group(2))
            heading_stack = heading_stack[: level - 1]
            heading_stack.append(text)
            counter += 1
            blocks.append(make_block(f"B{counter:06d}", "body", "heading", counter, text, heading_stack, f"line:{line_no}", {"heading_level": level}))
        elif footnote:
            flush(line_no - 1)
            note_id, text = footnote.groups()
            notes.append(make_block(f"FN{note_id}", "footnote", "footnote", len(notes) + 1, text, [], f"line:{line_no}", {"note_id": note_id}))
        elif not line.strip():
            flush(line_no - 1)
            paragraph_start = line_no + 1
        else:
            if not paragraph:
                paragraph_start = line_no
            paragraph.append(line)
    flush(len(lines))
    return blocks, notes, [], [], ["Markdown parsing preserves headings and footnote definitions but does not fully interpret every extension."]


def text_blocks(path: Path) -> tuple[list[dict], list[dict], list[dict], list[dict], list[str]]:
    text = path.read_text(encoding="utf-8-sig")
    blocks: list[dict] = []
    heading_stack: list[str] = []
    for index, match in enumerate(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, flags=re.S), 1):
        value = normalize_space(match.group(0))
        kind = "heading" if len(value.split()) <= 14 and not re.search(r"[.!?]$", value) else "paragraph"
        if kind == "heading":
            heading_stack = [value]
        blocks.append(make_block(f"B{index:06d}", "body", kind, index, value, heading_stack, f"char:{match.start()}-{match.end()}"))
    return blocks, [], [], [], ["Plain-text extraction cannot recover Word styles, fields, bookmarks, or real footnotes."]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("draft", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    path = args.draft.expanduser().resolve()
    if not path.is_file():
        parser.error(f"draft does not exist: {path}")
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            blocks, notes, fields, bookmarks, limitations = extract_docx(path)
            input_format = "docx"
        elif suffix in {".md", ".markdown"}:
            blocks, notes, fields, bookmarks, limitations = markdown_blocks(path)
            input_format = "markdown"
        elif suffix in {".txt", ".text"}:
            blocks, notes, fields, bookmarks, limitations = text_blocks(path)
            input_format = "text"
        else:
            parser.error("supported inputs are .docx, .md, .markdown, .txt, and .text")
    except (OSError, zipfile.BadZipFile, ET.ParseError, UnicodeDecodeError) as exc:
        print(f"ERROR: extraction failed: {exc}", file=sys.stderr)
        return 1
    output = {
        "schema_version": SCHEMA_VERSION,
        "input_path": str(path),
        "input_sha256": file_sha256(path),
        "input_format": input_format,
        "tracked_change_view": "insertions_visible_deletions_excluded" if input_format == "docx" else None,
        "extracted_at": utc_now(),
        "blocks": blocks,
        "notes": notes,
        "fields": fields,
        "bookmarks": bookmarks,
        "statistics": {
            "block_count": len(blocks),
            "note_count": len(notes),
            "reviewable_block_count": sum(1 for block in blocks if block.get("reviewable")),
            "body_word_count": sum(int(block.get("word_count", 0)) for block in blocks),
            "note_word_count": sum(int(note.get("word_count", 0)) for note in notes),
        },
        "limitations": limitations,
    }
    write_json(args.output, output)
    print(f"extracted {len(blocks)} blocks and {len(notes)} notes to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
