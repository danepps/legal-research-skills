#!/usr/bin/env python3
"""Fetch a bounded public source with explicit extraction limits and provenance.

Usage: fetch_source.py URL [--out RUN_DIR/sources/UNIQUE_SOURCE.txt]

Without --out, print at most 40,000 characters. With --out, create a new text
file and adjacent .json provenance record; refuse existing paths. Never infer
full PDF coverage when the total page count is unavailable or exceeds the cap.
Only public HTTP(S) retrieval is supported; authenticated sources use the
user's separately authorized connector or local copy.
"""
from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request


MAX_BYTES = 2_500_000
FILE_MAX_BYTES = 25_000_000
MAX_CHARS = 40_000
PAGE_LIMIT = 60
FILE_PAGE_LIMIT = 400
NETWORK_TIMEOUT = 45
EXTRACTION_TIMEOUT = 60


class TextExtractor(html.parser.HTMLParser):
    # Keep substantive headings, footnotes, and asides. Only non-text payloads
    # are removed; source-specific chrome can be ignored during focused reads.
    SKIP = {"script", "style", "noscript", "svg"}
    BLOCK = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BLOCK:
            self.chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.BLOCK:
            self.chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.chunks.append(data)


def extract(body: bytes, content_type: str, page_limit: int) -> tuple[str, dict[str, object]]:
    pdf = "pdf" in content_type.lower() or body.startswith(b"%PDF-")
    metadata: dict[str, object] = {"format": "pdf" if pdf else "html_or_text", "complete_text": True}
    if pdf:
        if not shutil.which("pdftotext"):
            raise ValueError("PDF extraction requires pdftotext; use an authorized HTML copy instead")
        with tempfile.NamedTemporaryFile(suffix=".pdf") as temporary:
            temporary.write(body)
            temporary.flush()
            total = None
            if shutil.which("pdfinfo"):
                info = subprocess.run(["pdfinfo", temporary.name], capture_output=True, text=True, timeout=EXTRACTION_TIMEOUT)
                match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, re.MULTILINE)
                if info.returncode == 0 and match:
                    total = int(match.group(1))
            result = subprocess.run(
                ["pdftotext", "-l", str(page_limit), temporary.name, "-"],
                capture_output=True, text=True, timeout=EXTRACTION_TIMEOUT,
            )
        if result.returncode:
            raise ValueError(f"PDF extraction failed: {result.stderr[:300]}")
        text = result.stdout
        metadata.update(total_pages=total, page_limit=page_limit, complete_text=total is not None and total <= page_limit)
        if total is None:
            metadata["limit_note"] = f"Total PDF page count unavailable; extraction covers at most {page_limit} pages."
        elif total > page_limit:
            metadata["limit_note"] = f"PDF truncated to the first {page_limit} of {total} pages."
    else:
        parser = TextExtractor()
        parser.feed(body.decode("utf-8", errors="replace"))
        text = "".join(parser.chunks)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t\r]*\n+", "\n\n", text).strip()
    if not text:
        raise ValueError("source contains no extractable text")
    metadata["text_pages"] = text.count("\f") + 1 if pdf else None
    return text, metadata


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--out", type=Path, help="unique source path inside the hidden run directory; existing paths are refused")
    args = parser.parse_args(argv)
    if urllib.parse.urlparse(args.url).scheme not in {"http", "https"}:
        parser.error("URL must use http or https; read supplied local sources directly")
    output = args.out
    record_path = Path(str(output) + ".json") if output else None
    if output and (output.exists() or record_path.exists()):
        print("FETCH REFUSED: output or provenance path exists; use a unique per-run, per-source path.", file=sys.stderr)
        return 1
    byte_limit = FILE_MAX_BYTES if output else MAX_BYTES
    try:
        request = urllib.request.Request(args.url, headers={"User-Agent": "Codex-legal-research/1.0", "Accept": "text/html,application/pdf,text/plain"})
        with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT) as response:
            content_type = response.headers.get("Content-Type", "")
            final_url = response.geturl()
            body = response.read(byte_limit + 1)
        if len(body) > byte_limit:
            raise ValueError(f"response exceeds the {byte_limit:,}-byte cap")
        text, metadata = extract(body, content_type, FILE_PAGE_LIMIT if output else PAGE_LIMIT)
        metadata.update(
            requested_url=args.url, final_url=final_url, source_sha256=hashlib.sha256(body).hexdigest(),
            source_bytes=len(body), text_sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(), text_chars=len(text),
        )
        if output:
            # Exclusive creation protects parallel lanes even if both passed
            # the early exists check before either wrote its result.
            with output.open("x", encoding="utf-8") as handle:
                handle.write(text)
            with record_path.open("x", encoding="utf-8") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            print(json.dumps({"text_path": str(output), "provenance_path": str(record_path), **metadata}, ensure_ascii=False))
        else:
            if len(text) > MAX_CHARS:
                metadata["complete_text"] = False
                metadata["character_limit"] = MAX_CHARS
                metadata["limit_note"] = (str(metadata.get("limit_note", "")) + f" Text truncated to {MAX_CHARS:,} characters.").strip()
            print(text[:MAX_CHARS])
            print("\n[Extraction provenance: " + json.dumps(metadata, ensure_ascii=False) + "]")
        return 0
    except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"FETCH FAILED: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
