#!/usr/bin/env python3
"""Verify a DOCX as OOXML without launching an office application."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import unicodedata
import zipfile
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree


REQUIRED_PARTS = {"[Content_Types].xml", "_rels/.rels", "word/document.xml"}
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
TEXT_PARTS = ("word/document.xml", "word/footnotes.xml", "word/endnotes.xml")
VERIFICATION_METHOD = "ooxml_structure_text_extraction_and_sync"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_tokens(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", html.unescape(text)).casefold()
    return re.findall(r"[^\W_]+(?:['’][^\W_]+)?", normalized, flags=re.UNICODE)


def markdown_text(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    text = re.sub(r"\A---\s*\n.*?\n---\s*(?:\n|\Z)", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", " ", text, flags=re.DOTALL)
    text = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\[[^]]*\]", r"\1", text)
    text = re.sub(r"^\s*\[(?!\^)[^]]+\]:\s+\S+.*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*\[\^[^]]+\]:\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[\^[^]]+\]", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"^\s*[-:| ]{3,}\s*$", " ", text, flags=re.MULTILINE)
    text = re.sub(r"^\s{0,3}(?:#{1,6}|>|[-+*]|\d+[.)])\s+", "", text, flags=re.MULTILINE)
    return re.sub(r"[`*_~]", "", text)


def coverage(reference: list[str], candidate: list[str]) -> float:
    if not reference:
        return 1.0 if not candidate else 0.0
    overlap = Counter(reference) & Counter(candidate)
    return sum(overlap.values()) / len(reference)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-markdown-coverage", type=float, default=0.97)
    parser.add_argument("--min-docx-coverage", type=float, default=0.90)
    args = parser.parse_args()

    for threshold in (args.min_markdown_coverage, args.min_docx_coverage):
        if not 0 <= threshold <= 1:
            parser.error("coverage thresholds must be between 0 and 1")

    if not args.docx.is_file() or not zipfile.is_zipfile(args.docx):
        parser.error("DOCX is missing or is not a valid ZIP/OOXML package")
    if args.markdown is not None and not args.markdown.is_file():
        parser.error("Markdown source not found")

    with zipfile.ZipFile(args.docx) as archive:
        names = set(archive.namelist())
        missing = sorted(REQUIRED_PARTS - names)
        if missing:
            parser.error(f"DOCX lacks required OOXML parts: {', '.join(missing)}")
        xml_names = sorted(
            name for name in names if name.endswith((".xml", ".rels"))
        )
        roots = {}
        for name in xml_names:
            try:
                roots[name] = ElementTree.fromstring(archive.read(name))
            except ElementTree.ParseError as exc:
                parser.error(f"malformed XML part {name}: {exc}")
        used_text_parts = [name for name in TEXT_PARTS if name in roots]
        text = " ".join(
            node.text or ""
            for name in used_text_parts
            for node in roots[name].iter(f"{WORD_NS}t")
        ).strip()
        if not text:
            parser.error("word/document.xml contains no extractable text")

    docx_tokens = normalized_tokens(text)
    sync_record = None
    if args.markdown:
        markdown_tokens = normalized_tokens(markdown_text(args.markdown))
        markdown_coverage = coverage(markdown_tokens, docx_tokens)
        docx_coverage = coverage(docx_tokens, markdown_tokens)
        sync_record = {
            "status": "passed",
            "method": "normalized_token_multiset_coverage",
            "markdown_tokens": len(markdown_tokens),
            "docx_tokens": len(docx_tokens),
            "markdown_coverage": round(markdown_coverage, 6),
            "docx_coverage": round(docx_coverage, 6),
            "minimum_markdown_coverage": args.min_markdown_coverage,
            "minimum_docx_coverage": args.min_docx_coverage,
            "markdown_normalized_sha256": hashlib.sha256(
                " ".join(markdown_tokens).encode("utf-8")
            ).hexdigest(),
            "docx_normalized_sha256": hashlib.sha256(
                " ".join(docx_tokens).encode("utf-8")
            ).hexdigest(),
        }
        if markdown_coverage < args.min_markdown_coverage:
            parser.error(
                "DOCX is missing substantive Markdown text: "
                f"coverage {markdown_coverage:.3f} < {args.min_markdown_coverage:.3f}"
            )
        if docx_coverage < args.min_docx_coverage:
            parser.error(
                "DOCX contains substantial text absent from Markdown: "
                f"coverage {docx_coverage:.3f} < {args.min_docx_coverage:.3f}"
            )

    record = {
        "schema_version": 1,
        "status": "passed",
        "verification_method": VERIFICATION_METHOD,
        "visual_verification": "not_performed",
        "office_application_launched": False,
        "docx_sha256": sha256(args.docx),
        "markdown_sha256": sha256(args.markdown) if args.markdown else None,
        "required_parts_present": sorted(REQUIRED_PARTS),
        "xml_parts_parsed": len(xml_names),
        "text_parts_checked": used_text_parts,
        "extracted_text_characters": len(text),
        "extracted_text_words": len(text.split()),
        "substantive_sync": sync_record,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "notes": "OOXML structure checked. Token coverage is a screening check, not proof of semantic equivalence, word order, or correct footnote attachment; inspect substantive synchronization separately. Pagination and visual layout were not rendered.",
    }
    payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
