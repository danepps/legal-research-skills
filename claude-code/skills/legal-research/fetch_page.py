#!/usr/bin/env python3
"""Hard-capped page fetcher for legal-research read agents.

Enforces in CODE what the prompts can only ask for: a byte cap, a timeout, and
a character cap on extracted text — so one giant PDF or page can never blow up
an agent's context (the v2 spiral / built-in deep-research hang failure mode).

Usage:
    python3 fetch_page.py <url>              # capped text to stdout (context-safe)
    python3 fetch_page.py <url> --out FILE   # full text to FILE (for file-side
                                             # tools like cite-check's verify_quotes.py)

Behavior (stdout mode — the caps protect agent context):
  - Downloads at most MAX_BYTES; refuses (exit 1) anything larger.
  - HTML: strips script/style/nav chrome, prints plain text.
  - PDF: extracts text via `pdftotext` (first 60 pages) if installed;
    otherwise refuses with instructions to find an HTML version.
  - Output truncated to MAX_CHARS with an explicit [TRUNCATED] marker.

--out mode: the text goes to disk, never into context, so the limits are
generous instead (25 MB download, 400 PDF pages, no char truncation) and
stdout gets only a one-line summary (chars, page count, sha256). Do NOT cat
the file into context — read it with targeted tools.

Exit codes: 0 = text delivered; 1 = fetch refused/failed (treat as a failed
attempt and move to the next fallback); 2 = usage error.

Stdlib only (pdftotext optional). Part of the legal-research skill.
"""
import hashlib
import html.parser
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request

MAX_BYTES = 2_500_000
TIMEOUT = 45
MAX_CHARS = 40_000
PDF_MAX_PAGES = 60
# --out mode: text lands on disk for file-side tools, not in agent context.
FILE_MAX_BYTES = 25_000_000
FILE_PDF_MAX_PAGES = 400

class TextExtractor(html.parser.HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "header", "footer", "nav", "aside"}
    BLOCK = {"p", "div", "li", "tr", "br", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip_depth = 0
        self.chunks = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip_depth += 1
        elif tag in self.BLOCK:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif tag in self.BLOCK:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            self.chunks.append(data)


def main(argv):
    args = list(argv)
    out_path = None
    if "--out" in args:
        i = args.index("--out")
        if i + 1 >= len(args):
            print("usage: fetch_page.py <url> [--out FILE]", file=sys.stderr)
            return 2
        out_path = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1:
        print("usage: fetch_page.py <url> [--out FILE]", file=sys.stderr)
        return 2
    url = args[0]
    max_bytes = FILE_MAX_BYTES if out_path else MAX_BYTES
    pdf_pages = FILE_PDF_MAX_PAGES if out_path else PDF_MAX_PAGES

    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Macintosh) legal-research-skill/1.0",
            "Accept": "text/html,application/xhtml+xml,application/pdf,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            ctype = (resp.headers.get("Content-Type") or "").lower()
            body = resp.read(max_bytes + 1)
    except Exception as e:
        print(f"FETCH FAILED: {e}", file=sys.stderr)
        return 1

    if len(body) > max_bytes:
        print(
            f"FETCH REFUSED: response exceeds the {max_bytes:,}-byte cap — treat this "
            "attempt as failed and look for a smaller or HTML version of the source.",
            file=sys.stderr,
        )
        return 1

    is_pdf = "pdf" in ctype or body[:5] == b"%PDF-"
    if is_pdf:
        if not shutil.which("pdftotext"):
            print(
                "FETCH REFUSED: source is a PDF and pdftotext is not installed — "
                "find an HTML version (CourtListener/LII for cases, digital commons "
                "for articles) instead.",
                file=sys.stderr,
            )
            return 1
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(body)
            f.flush()
            try:
                proc = subprocess.run(
                    ["pdftotext", "-l", str(pdf_pages), f.name, "-"],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
            except subprocess.TimeoutExpired:
                print("PDF extraction timed out — treat as fetch failure.", file=sys.stderr)
                return 1
        if proc.returncode != 0:
            print(f"PDF extraction failed: {proc.stderr[:300]}", file=sys.stderr)
            return 1
        text = proc.stdout
    else:
        parser = TextExtractor()
        try:
            parser.feed(body.decode("utf-8", "replace"))
        except Exception:
            pass
        text = "".join(parser.chunks)

    text = re.sub(r"[ \t]+", " ", text)
    # Keep page boundaries (\f, as pdftotext emits) through the blank-line
    # collapse — cite-check's verify_quotes.py derives printed pages from them.
    text = text.replace("\f", "\n\ue000\n")
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    text = re.sub("\n?\ue000\n?", "\f", text).strip()
    if not text:
        print("FETCH REFUSED: no extractable text at this URL.", file=sys.stderr)
        return 1
    if out_path:
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            print(f"FETCH FAILED: cannot write --out file: {e}", file=sys.stderr)
            return 1
        pages = text.count("\f") + 1
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
        print(
            f"WROTE {out_path}: {len(text):,} chars, {pages} page(s), sha256 {digest}. "
            "Full text, not truncated — do not cat it into context; run file-side "
            "tools (e.g. verify_quotes.py) against it."
        )
        return 0
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS] + (
            f"\n\n[TRUNCATED at {MAX_CHARS:,} chars by fetch_page.py — quote and "
            "pincite only from the text above this marker]"
        )
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
