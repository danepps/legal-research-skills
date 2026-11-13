#!/usr/bin/env python3
"""Offline test for zotero_sweep.py (2026-11-12): a quote on a stale "supra" and one on an "Id."
after it reach the Zotero text through the citation ledger; a quote that is not in the text is
reported not found; a footnote whose source has no text on disk is tried against nothing."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


DRAFT = """One.[^1] Two.[^2] Three.[^3] Four.[^4] Five.[^5]

[^1]: Thomas W. Merrill, The Landscape of Constitutional Property, 86 Va. L. Rev. 885 (2000).
[^2]: Jane Gold, Something Else, 1 Yale L.J. 1 (1990).
[^3]: Merrill, Landscape, supra note 2, at 950 ("property is a creature of positive law and nothing more than that").
[^4]: Id. at 943 ("these are words that appear nowhere at all in the text").
[^5]: Gold, supra note 2, at 3 ("a quote from a source that has no text file on disk").
"""

with tempfile.TemporaryDirectory() as td:
    md, ex = os.path.join(td, "d.md"), os.path.join(td, "x.json")
    open(md, "w", encoding="utf-8").write(DRAFT)
    subprocess.run([sys.executable, os.path.join(HERE, "extract_cites.py"), md, ex], check=True, capture_output=True)
    txt = os.path.join(td, "merrill.txt")
    open(txt, "w", encoding="utf-8").write("Cover page\fIn this view property is a creature of positive law and nothing more than that, and so on.\fMore text.")
    lk = os.path.join(td, "lookup.json")
    json.dump({"sources": {"86 va l rev 885": {"matched": True, "textPath": txt, "itemKey": "M1", "library": "zotero-group",
                                               "title": "The Landscape of Constitutional Property"},
                           "1 yale l j 1": {"matched": True, "textPath": "", "itemKey": "G1"}}}, open(lk, "w"))
    sys.path.insert(0, HERE)
    import prepare_units as pu
    units = pu.build_units(json.load(open(ex, encoding="utf-8")))
    by_note = {u["footnote"]: u["id"] for u in units}
    out = subprocess.run([sys.executable, os.path.join(HERE, "zotero_sweep.py"), ex, lk, "--ids", str(by_note[3]), str(by_note[4]), str(by_note[5])],
                         capture_output=True, text=True)
    res = {r["footnote"]: r for r in json.loads(out.stdout)["results"]}
    check(res[3]["found"] and res[3]["status"] == "verbatim" and res[3]["item"] == "M1",
          "quote on a stale supra found in the Zotero text (%s)" % {k: res[3].get(k) for k in ("found", "status", "item")})
    check(res[3]["page_in_file"] == 2 and "creature of positive law" in res[3]["matched"], "page in file and excerpt reported")
    check(not res[4]["found"] and res[4]["tried"] == [txt], "Id. quote tried against the same text, not found")
    check(not res[5]["found"] and res[5]["tried"] == [], "source with no text on disk: nothing tried")
    bad = subprocess.run([sys.executable, os.path.join(HERE, "zotero_sweep.py"), ex], capture_output=True, text=True)
    check(bad.returncode == 2, "usage error exits 2")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
