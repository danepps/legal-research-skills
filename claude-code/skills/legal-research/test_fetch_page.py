#!/usr/bin/env python3
"""Self-test for fetch_page.py's PDF coverage reporting — run: python3 test_fetch_page.py

No network: a five-page PDF is hand-built in a temp directory and fetched
through a file:// URL. The page caps are lowered on the imported module (the
shipped caps are untouched) to reproduce the memo's CLAUDE-06 case: a PDF
longer than the cap must be reported as PARTIAL in both modes, carry a
[TRUNCATED] marker, and never be called full text. Needs pdftotext; prints
"skipped" and exits 0 without it. Plain asserts, no pytest.
"""
import contextlib
import importlib.util
import io
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(HERE, "fetch_page.py")


def build_pdf(path, n=5):
    """Minimal valid PDF, one Helvetica text line per page."""
    objs = []

    def add(obj):
        objs.append(obj)
        return len(objs)
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    contents = []
    for i in range(n):
        stream = "BT /F1 24 Tf 72 700 Td (Page %d of %d text here) Tj ET" % (i + 1, n)
        contents.append(add("<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)))
    pages_id = len(objs) + n + 1
    page_ids = [add("<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] "
                    "/Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>"
                    % (pages_id, font, contents[i])) for i in range(n)]
    assert add("<< /Type /Pages /Kids [%s] /Count %d >>"
               % (" ".join("%d 0 R" % p for p in page_ids), n)) == pages_id
    catalog = add("<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = b"%PDF-1.4\n"
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += ("%d 0 obj\n%s\nendobj\n" % (i, o)).encode()
    xref = len(out)
    out += ("xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)).encode()
    for off in offsets:
        out += ("%010d 00000 n \n" % off).encode()
    out += ("trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n"
            % (len(objs) + 1, catalog, xref)).encode()
    with open(path, "wb") as f:
        f.write(out)


failures = 0


def check(name, cond):
    global failures
    print("  [%s] %s" % ("ok" if cond else "FAIL", name))
    if not cond:
        failures += 1


if not shutil.which("pdftotext"):
    print("  [skipped] pdftotext not installed — PDF coverage checks need poppler")
    sys.exit(0)

spec = importlib.util.spec_from_file_location("fetch_page_under_test", SCRIPT)
fp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fp)


def run(argv, hide_pdfinfo=False):
    real_which = shutil.which
    if hide_pdfinfo:
        fp.shutil.which = lambda name, _w=real_which: None if name == "pdfinfo" else _w(name)
    out, err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = fp.main(argv)
    finally:
        fp.shutil.which = real_which
    return rc, out.getvalue(), err.getvalue()


with tempfile.TemporaryDirectory() as td:
    pdf = os.path.join(td, "five.pdf")
    build_pdf(pdf, 5)
    url = "file://" + pdf
    outfile = os.path.join(td, "src.txt")

    print("complete extraction (caps above the page count)")
    rc, so, se = run([url, "--out", outfile])
    body = open(outfile, encoding="utf-8").read()
    check("--out: rc 0, 5 pages reported complete, 'Full text' claimed",
          rc == 0 and "5 page(s), complete (5 of 5)" in so and "Full text, not truncated" in so)
    check("--out: no [TRUNCATED] marker in a complete file", "[TRUNCATED" not in body
          and "Page 5 of 5" in body)
    rc, so, se = run([url])
    check("stdout: complete coverage stated on stderr, last page present",
          rc == 0 and "complete (5 of 5)" in se and "Page 5 of 5" in so and "[TRUNCATED" not in so)

    print("partial extraction (cap lowered to 2 pages on the imported module)")
    saved = fp.PDF_MAX_PAGES, fp.FILE_PDF_MAX_PAGES
    fp.PDF_MAX_PAGES = fp.FILE_PDF_MAX_PAGES = 2
    try:
        rc, so, se = run([url, "--out", outfile])
        body = open(outfile, encoding="utf-8").read()
        check("--out: summary says PARTIAL with the exact coverage, never 'Full text'",
              rc == 0 and "PARTIAL: 2 of 5 page(s) extracted" in so
              and "pages 3–5 NOT extracted" in so and "Full text" not in so
              and "INCOMPLETE SOURCE TEXT" in so)
        check("--out: file ends with a [TRUNCATED ...] marker naming the dropped pages",
              body.rstrip().endswith("]") and "[TRUNCATED by fetch_page.py" in body
              and "pages 3–5 NOT extracted" in body and "Page 3 of 5" not in body)
        rc, so, se = run([url])
        check("stdout: PARTIAL coverage on stderr and [TRUNCATED] marker in the text",
              rc == 0 and "PARTIAL: 2 of 5" in se and "[TRUNCATED by fetch_page.py" in so
              and "Page 2 of 5" in so and "Page 3 of 5" not in so)

        rc, so, se = run([url, "--out", outfile], hide_pdfinfo=True)
        check("without pdfinfo: cap reached + probe past it -> PARTIAL, total unknown",
              rc == 0 and "PARTIAL: first 2 page(s) extracted" in so
              and "total page count unknown" in so and "Full text" not in so)
    finally:
        fp.PDF_MAX_PAGES, fp.FILE_PDF_MAX_PAGES = saved

    print("probe-based total when pdfinfo is absent and the PDF fits the cap")
    rc, so, se = run([url, "--out", outfile], hide_pdfinfo=True)
    check("page-range error past the last page -> complete (5 of 5), 'Full text' allowed",
          rc == 0 and "complete (5 of 5)" in so and "Full text, not truncated" in so)

    print("non-PDF source unaffected")
    txt = os.path.join(td, "page.html")
    with open(txt, "w", encoding="utf-8") as f:
        f.write("<html><body><p>Plain page text here.</p></body></html>")
    rc, so, se = run(["file://" + txt, "--out", outfile])
    check("HTML --out still reports full text", rc == 0 and "Full text, not truncated" in so)

print()
if failures:
    print("%d FAILURES" % failures)
    sys.exit(1)
print("all tests passed")
