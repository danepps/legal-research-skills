#!/usr/bin/env python3
"""Offline checks of quote_receipt.py, the quotation check find-cite's verifiers run.

  * a verbatim quotation (even one the source wraps across a line) gets status verbatim, the
    receipt's hash of the trimmed quotation, and the matched passage printed as plain text;
  * typographic differences only (curly apostrophe, em dash) give normalized;
  * a changed word gives not_found and no passage;
  * the printed output satisfies the plugin's Stop-hook quotation check for the quotation as the
    find-cite entry prints it, while the RECEIPT line alone (JSON-escaped) would not when the
    source wraps the passage: the plain passage is what lets a correct entry through.
No network: the source is a local file (--source).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "quote_receipt.py"
HOOKS = HERE.parents[2] / "hooks" / "scripts"
sys.dont_write_bytecode = True  # leave no __pycache__ beside these scripts or the hooks
sys.path.insert(0, str(HERE))
from quote_receipt import quote_hash  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


SOURCE = ("Opinion of the Court.\n\nWe hold that even if the defendant denies one or more elements\n"
          "of the crime, he is entitled to an entrapment instruction whenever there is sufficient "
          "evidence. The Government’s position — that inconsistent defenses are barred — "
          "is rejected.\n")


def run(tmp, quote, slot):
    src = os.path.join(tmp, "src.txt")
    with open(src, "w", encoding="utf-8") as fh:
        fh.write(SOURCE)
    q = os.path.join(tmp, slot + "-q.txt")
    with open(q, "w", encoding="utf-8") as fh:
        fh.write(quote + "\n")
    p = subprocess.run([sys.executable, str(SCRIPT), "--id", slot, "--quote-file", q, "--source", src, "--url", "https://example.org/op"],
                       capture_output=True, text=True)
    line = [l for l in p.stdout.splitlines() if l.startswith("RECEIPT ")]
    return p.returncode, p.stdout, (json.loads(line[-1][8:]) if line else None)


with tempfile.TemporaryDirectory() as tmp:
    Q1 = "even if the defendant denies one or more elements of the crime, he is entitled to an entrapment instruction"
    code, out, rc = run(tmp, Q1, "c1")
    check(code == 0 and rc and rc["status"] == "verbatim", "a wrapped verbatim quotation is verbatim (%s)" % (rc or {}).get("status"))
    check(rc["quote_hash"] == quote_hash(Q1) and rc["id"] == "c1" and rc["text_from"] == "file" and rc["source"] == "https://example.org/op",
          "the receipt carries the hash of the trimmed quotation and its provenance")
    check(("SOURCE PASSAGE c1 (verbatim)" in out) and (Q1 in out), "the matched passage is printed as plain text")

    Q2 = "The Government's position - that inconsistent defenses are barred - is rejected"
    code, out, rc = run(tmp, Q2, "c2")
    check(rc and rc["status"] == "normalized", "curly apostrophe and dash differences are normalized (%s)" % (rc or {}).get("status"))

    Q3 = "even if the defendant admits one or more elements of the crime"
    code, out, rc = run(tmp, Q3, "c3")
    check(rc and rc["status"] == "not_found" and "SOURCE PASSAGE" not in out, "a changed word is not_found, with no passage printed")

    print("the Stop hook accepts the entry's quotation against the receipt output")
    if HOOKS.is_dir():
        sys.path.insert(0, str(HOOKS))
        try:
            import quote_check as qc
        except Exception as e:  # pragma: no cover
            qc = None
            check(False, "could not import the hook: %s" % e)
        if qc:
            code, out, rc = run(tmp, Q1, "c4")
            entry = "1. *Alpha v. Beta*, 485 U.S. 58, 62 (1988) (“%s”).\n" % Q1
            corpus = qc.norm_source(out)
            check(qc.unmatched_quotes(entry, corpus, set()) == [], "the full receipt output lets the quotation through")
            only_json = qc.norm_source([l for l in out.splitlines() if l.startswith("RECEIPT ")][0])
            check(qc.unmatched_quotes(entry, only_json, set()) != [], "the JSON receipt alone would not (escaped line break)")
            bad = "1. *Alpha v. Beta*, 485 U.S. 58, 62 (1988) (“%s”).\n" % Q3
            check(qc.unmatched_quotes(bad, corpus, set()) != [], "an unconfirmed quotation is still blocked")
    else:
        print("  hooks folder not found: hook check skipped")

    print("usage errors")
    p = subprocess.run([sys.executable, str(SCRIPT), "--id", "x", "--quote-file", os.path.join(tmp, "missing.txt"), "--source", os.path.join(tmp, "src.txt")],
                       capture_output=True, text=True)
    check(p.returncode == 2, "a missing quote file exits 2")
    empty = os.path.join(tmp, "empty.txt")
    open(empty, "w").close()
    p = subprocess.run([sys.executable, str(SCRIPT), "--id", "x", "--quote-file", empty, "--source", os.path.join(tmp, "src.txt")],
                       capture_output=True, text=True)
    check(p.returncode == 2, "an empty quote file exits 2")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
