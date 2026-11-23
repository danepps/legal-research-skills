#!/usr/bin/env python3
"""Check one proposed quotation against fetched source text and print a receipt.

Used by the find-cite workflow's verification agents. The agent PROPOSES a quotation; this
script runs the cite-check skill's deterministic verifier (verify_quotes.py) over the source
text and prints two things:

  1. the matched passage, copied from the source text (whitespace collapsed, nothing else
     changed), so the quotation exists in raw tool output; and
  2. a final line "RECEIPT {json}" that the agent copies into its result. The workflow script
     accepts a quotation only if the receipt's quote_hash is the hash of the exact quotation
     the agent returned, the status is verbatim or normalized, and the quotation is contained
     in the receipt's match_excerpt. Anything else is delivered as a paraphrase.

Usage:
    quote_receipt.py --id ID --quote-file QFILE (--source FILE | --url URL)
                     [--url URL] [--pincite P] [--first-page N]

QFILE holds the quotation as plain text (an agent writes it with a quoted heredoc, so no shell
quoting can change it); leading and trailing spaces, tabs and line breaks are ignored.
--source is text the agent already saved (fetch_page.py --out); with only --url the page is
fetched here with fetch_page.py --out. --pincite and --first-page are passed to the verifier.

quote_hash is FNV-1a (32 bit) over the UTF-16 code units of the trimmed quotation, the same
function the workflow computes in JavaScript.

Exit codes: 0 = the check ran (read the status); 1 = the page could not be fetched;
2 = usage or read error. Stdlib only. Reuses ../../legal-research/fetch_page.py and
../../cite-check/scripts/verify_quotes.py; copies neither.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILLS = os.path.dirname(os.path.dirname(HERE))
FETCH_PAGE = os.path.join(SKILLS, "legal-research", "fetch_page.py")
VERIFY_QUOTES = os.path.join(SKILLS, "cite-check", "scripts", "verify_quotes.py")
TRIM = " \t\r\n"


def quote_hash(s: str) -> str:
    """FNV-1a over UTF-16 code units (matches quoteHash in find-cite.workflow.js)."""
    h = 0x811C9DC5
    b = s.encode("utf-16-le")
    for i in range(0, len(b), 2):
        h ^= b[i] | (b[i + 1] << 8)
        h = (h * 0x01000193) & 0xFFFFFFFF
    return "%08x" % h


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--id", required=True)
    ap.add_argument("--quote-file", required=True)
    ap.add_argument("--source")
    ap.add_argument("--url")
    ap.add_argument("--pincite")
    ap.add_argument("--first-page", type=int)
    a = ap.parse_args(argv)
    if not a.source and not a.url:
        print("give --source FILE or --url URL", file=sys.stderr)
        return 2
    try:
        with open(a.quote_file, encoding="utf-8") as fh:
            quote = fh.read().strip(TRIM)
    except OSError as e:
        print("cannot read quote file: %s" % e, file=sys.stderr)
        return 2
    if not quote:
        print("quote file is empty", file=sys.stderr)
        return 2

    work = tempfile.mkdtemp(prefix="fc-receipt-")
    if a.source:
        src, text_from = a.source, "file"
        if not os.path.isfile(src):
            print("source file not found: %s" % src, file=sys.stderr)
            return 2
    else:
        src, text_from = os.path.join(work, "source.txt"), "url"
        p = subprocess.run([sys.executable, FETCH_PAGE, a.url, "--out", src], capture_output=True, text=True)
        if p.returncode != 0 or not os.path.isfile(src):
            print("FETCH FAILED for %s: %s" % (a.url, (p.stdout + p.stderr).strip()[-400:]))
            return 1

    qjson = os.path.join(work, "quotes.json")
    item = {"id": a.id, "quote": quote}
    if a.pincite:
        item["pincite"] = a.pincite
    with open(qjson, "w", encoding="utf-8") as fh:
        json.dump([item], fh, ensure_ascii=False)
    cmd = [sys.executable, VERIFY_QUOTES, src, "--json", qjson]
    if a.first_page:
        cmd += ["--first-page", str(a.first_page)]
    p = subprocess.run(cmd, capture_output=True, text=True)
    try:
        report = json.loads(p.stdout)
        r = report["results"][0]
    except (ValueError, KeyError, IndexError):
        print("verifier failed: %s" % (p.stdout + p.stderr).strip()[-400:], file=sys.stderr)
        return 2

    status = r.get("status")
    excerpt = r.get("match_excerpt", "")
    receipt = {
        "id": a.id,
        "status": status,
        "quote_hash": quote_hash(quote),
        "match_excerpt": excerpt,
        "text_from": text_from,
        "source": a.url or src,
        "source_sha256": report.get("sha256", ""),
    }
    for k in ("page", "page_end", "pincite_ok"):
        if k in r:
            receipt[k] = r[k]
    if status == "not_found":
        receipt["reason"] = r.get("reason", "")
        print("NOT FOUND in the source text (%s). Closest-match ratio: %s." % (src, r.get("best_ratio")))
    else:
        where = (", page %s" % r["page"]) if "page" in r else ""
        print("SOURCE PASSAGE %s (%s%s), copied from %s:" % (a.id, status, where, a.url or src))
        print(re.sub(r"\s+", " ", excerpt).strip())
        for w in r.get("warnings") or []:
            print("warning: %s" % w)
    print("RECEIPT " + json.dumps(receipt, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
