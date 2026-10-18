#!/usr/bin/env python3
"""Find quantifier-trigger occurrences and emit a reviewable JSONL audit template."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


TRIGGER_TERMS = (
    "first",
    "earliest",
    "only",
    "settled",
    "overwhelmingly",
    "most",
    "always",
    "never",
)
TRIGGER_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(term) for term in TRIGGER_TERMS) + r")\b",
    re.IGNORECASE,
)
WORD_NAMESPACE = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract_deliverable_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return path.read_text(encoding="utf-8")
    if suffix == ".docx":
        try:
            with zipfile.ZipFile(path) as archive:
                document = archive.read("word/document.xml")
            root = ET.fromstring(document)
        except (zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
            raise ValueError(f"could not extract DOCX text: {exc}") from exc
        paragraphs = []
        for paragraph in root.iter(WORD_NAMESPACE + "p"):
            text = "".join(
                node.text or "" for node in paragraph.iter(WORD_NAMESPACE + "t")
            )
            paragraphs.append(text)
        return "\n".join(paragraphs)
    if suffix == ".pdf":
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise ValueError("pdftotext is required to audit a PDF deliverable") from exc
        except subprocess.CalledProcessError as exc:
            detail = exc.stderr.strip() or "unknown pdftotext error"
            raise ValueError(f"could not extract PDF text: {detail}") from exc
        return result.stdout
    raise ValueError(f"unsupported deliverable format for quantifier audit: {suffix or '(none)'}")


def find_quantifier_hits(text: str) -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    lines = text.splitlines() or [text]
    hit_number = 0
    for line_number, line in enumerate(lines, 1):
        for match in TRIGGER_PATTERN.finditer(line):
            hit_number += 1
            excerpt = " ".join(line.strip().split())
            if len(excerpt) > 240:
                excerpt = excerpt[:237] + "..."
            hits.append(
                {
                    "hit_id": f"Q{hit_number}",
                    "term": match.group(0).lower(),
                    "line": line_number,
                    "excerpt": excerpt,
                }
            )
    return hits


def audit_template(path: Path) -> list[dict[str, object]]:
    rows = find_quantifier_hits(extract_deliverable_text(path))
    for row in rows:
        row["claim_id"] = ""
        row["waiver"] = ""
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("deliverable", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    deliverable = args.deliverable.expanduser().resolve()
    if not deliverable.is_file():
        parser.error(f"deliverable does not exist: {deliverable}")
    try:
        rows = audit_template(deliverable)
    except (OSError, ValueError, zipfile.BadZipFile, KeyError, ET.ParseError) as exc:
        parser.error(str(exc))
    content = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
    if args.output:
        output = args.output.expanduser().resolve()
        if output.exists() and output.stat().st_size and not args.replace:
            parser.error(f"refusing to overwrite nonempty audit without --replace: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(output)
    else:
        print(content, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
