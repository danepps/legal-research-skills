#!/usr/bin/env python3
"""Tests for findings_diff.py: keys ignore footnote numbers, new/still/resolved sets, rendering."""
import importlib.util
import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("fd", os.path.join(HERE, "findings_diff.py"))
fd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fd)
fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fails += 1


q1 = {"kind": "quote", "footnote": 12, "quote": "the limitations period does not begin to run", "source": "Smith v. Jones, 123 F.3d 456", "verdict": "mismatch", "label": "n.12 mismatch"}
q1_renum = dict(q1, footnote=14, label="n.14 mismatch")
q1_typo = dict(q1, quote="The limitations period does not begin to run.")   # case/punctuation only
q2 = {"kind": "quote", "footnote": 30, "quote": "another passage", "source": "Doe v. Roe", "verdict": "pincite_off"}
f1 = {"kind": "form", "footnote": 5, "find": "See Knowlton v. Moore", "problem": "case name italic in citation clause"}
e1 = {"kind": "existence", "footnote": 7, "cite": "03 U.S. 95"}
h1 = {"kind": "history", "footnote": 9, "cite": "397 F. Supp. 3d 126"}

check("key ignores footnote number", fd.key_of(q1) == fd.key_of(q1_renum))
check("key ignores case and punctuation", fd.key_of(q1) == fd.key_of(q1_typo))
check("different verdict -> different key", fd.key_of(q1) != fd.key_of(dict(q1, verdict="verbatim")))
check("form key from find + problem", fd.key_of(f1) == fd.key_of(dict(f1, footnote=99)) and fd.key_of(f1) != fd.key_of(dict(f1, problem="other")))
check("existence and history keys differ by kind", fd.key_of(e1) != fd.key_of(dict(e1, kind="history")))
check("explicit key wins", fd.key_of({"kind": "quote", "key": "abc"}) == "abc")
s1 = {"kind": "support", "footnote": 12, "verdict": "not_supported", "source": "Doe, 110 Harv. L. Rev. 815", "claim": "Courts have uniformly held X."}
check("support key ignores footnote number", fd.key_of(s1) == fd.key_of(dict(s1, footnote=40)))
check("support key changes with the verdict", fd.key_of(s1) != fd.key_of(dict(s1, verdict="contradicted")))
check("support-confirm (overstated) is a different kind from support", fd.key_of(s1) != fd.key_of(dict(s1, kind="support-confirm", verdict="overstated")))

tmp = tempfile.mkdtemp()
prev = os.path.join(tmp, "prev.json")
cur = os.path.join(tmp, "cur.json")
json.dump({"snapshotSha256": "a" * 64, "date": "2026-10-01", "items": [q1, q2, f1, e1]}, open(prev, "w"))
json.dump({"snapshotSha256": "b" * 64, "date": "2026-10-19", "items": [q1_renum, f1, h1]}, open(cur, "w"))
pm, p = fd.load(prev)
cm, c = fd.load(cur)
d = fd.diff(p, c)
check("new = history item only", [i["kind"] for i in d["new"]] == ["history"])
check("still open = renumbered quote + form", sorted(i["kind"] for i in d["still_open"]) == ["form", "quote"])
check("resolved = q2 and existence", sorted(i["kind"] for i in d["resolved"]) == ["existence", "quote"])
check("renumbered detected", len(d["renumbered"]) == 1 and d["renumbered"][0][1]["footnote"] == 14)
md = fd.render(pm, cm, d)
check("render has the three sections", all(h in md for h in ("### New since last report", "### Still open", "### Resolved")))
check("render counts line", "1 new, 2 still open, 2 resolved" in md)
check("render uses the current footnote for a moved finding", "- n.14 [quote: mismatch]" in md)
check("empty section says none", "- none" in fd.render(pm, cm, {"new": [], "still_open": [], "resolved": [], "renumbered": []}))
print("support findings on re-runs (2026-10-25)")
sp = {"kind": "support", "footnote": 3, "verdict": "not_supported", "source": "Doe", "claim": "X", "label": "l"}
sc_ = {"kind": "support-confirm", "footnote": 4, "verdict": "overstated", "source": "Roe", "claim": "Y", "label": "m"}
P = {fd.key_of(i): dict(i, key=fd.key_of(i)) for i in (sp, sc_, q1)}
C = {fd.key_of(q1): dict(q1, key=fd.key_of(q1))}
d_off = fd.diff(P, C, {"support": {"ran": True, "scope": "pincited"}}, {"support": {"ran": False}})
check("support pass off this run -> support items not rechecked, not resolved", len(d_off["resolved"]) == 0 and len(d_off["not_rechecked"]) == 2)
d_on = fd.diff(P, C, {"support": {"ran": True, "scope": "pincited"}}, {"support": {"ran": True, "scope": "pincited"}})
check("support pass ran at the same scope -> absent support items resolved", len(d_on["resolved"]) == 2 and not d_on["not_rechecked"])
d_scope = fd.diff(P, C, {"support": {"ran": True, "scope": "all"}}, {"support": {"ran": True, "scope": "pincited"}})
check("scope narrowed -> not rechecked", len(d_scope["not_rechecked"]) == 2)
d_first = fd.diff(P, C, {}, {"support": {"ran": True, "scope": "pincited"}})
check("previous file without support meta -> resolved when this run ran the pass", len(d_first["resolved"]) == 2)
md2 = fd.render({"date": "a"}, {"date": "b"}, d_off)
check("render lists the not-rechecked section", "### Not rechecked" in md2 and "NOT rechecked" in md2)
check("quote item absent with pass off is still resolved", all(i["kind"] != "quote" for i in d_off["not_rechecked"]))

print("\n%d failure(s)" % fails)
sys.exit(1 if fails else 0)
