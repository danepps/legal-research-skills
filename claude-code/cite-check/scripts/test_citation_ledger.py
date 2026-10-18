#!/usr/bin/env python3
"""Synthetic-fixture test for citation_ledger.py (the acceptance case from the
2026-09-06 review): a draft with one quoted case cite, one unquoted case
proposition, one unquoted scholarly cite, an Id./supra/short-form chain, and a
broken supra must account for EVERY instance, and dispositions must never call an
unchecked instance verified. No network, no credentials, no real draft."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import citation_ledger as cl  # noqa: E402

DRAFT = """Courts have long held that "the power to tax involves the power to destroy" when applied to federal instrumentalities.[^1] The Court reaffirmed the principle two decades later.[^2] Scholars have disagreed about its scope.[^3] The Court's later cases narrowed it considerably.[^4] As one commentator notes, "the doctrine has proven remarkably durable over two centuries."[^5] A final footnote points nowhere.[^6]

[^1]: McCulloch v. Maryland, 17 U.S. (4 Wheat.) 316, 431 (1819).
[^2]: Id. at 436; see also Marbury v. Madison, 5 U.S. (1 Cranch) 137 (1803) (quoting Hylton v. United States, 3 U.S. (3 Dall.) 171, 175 (1796)).
[^3]: Jane Doe, The Taxing Power Reconsidered, 110 Harv. L. Rev. 815 (1997).
[^4]: Doe, supra note 3, at 820; McCulloch, 17 U.S. at 400.
[^5]: John Roe, Federalism and Finance 45 (2d ed. 2010).
[^6]: Smith, supra note 9, at 12; see infra Section II.B; infra _.
"""

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


with tempfile.TemporaryDirectory() as td:
    md = os.path.join(td, "draft.md")
    ex = os.path.join(td, "extract.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(DRAFT)
    subprocess.run([sys.executable, os.path.join(HERE, "extract_cites.py"), md, ex],
                   check=True, capture_output=True)
    data = json.load(open(ex, encoding="utf-8"))
    L = cl.build_ledger(data)
    inst = L["instances"]
    by_note = {}
    for x in inst:
        by_note.setdefault(x["note"], []).append(x)

print("inventory")
check(L["instance_count"] == 11, "11 instances found (got %d)" % L["instance_count"])
check([x["kind"] for x in by_note[1]] == ["case"], "n.1: one full case cite")
check([x["kind"] for x in by_note[2]] == ["id", "case", "case"],
      "n.2: Id., full case, nested (quoting) case -> %s" % [x["kind"] for x in by_note[2]])
check(by_note[2][2].get("nested") is True and by_note[2][2]["case_cite"] == "3 U.S. 171",
      "n.2 nested Hylton cite captured as its own instance")
check([x["kind"] for x in by_note[3]] == ["article"], "n.3: unquoted scholarly cite is an ARTICLE instance")
check([x["kind"] for x in by_note[4]] == ["supra", "case-short"], "n.4: supra + short-form case")
check([x["kind"] for x in by_note[5]] == ["book"], "n.5: book")
check([x["kind"] for x in by_note[6]] == ["supra", "internal", "internal"],
      "n.6: broken supra + infra-Section ref + placeholder -> %s" % [x["kind"] for x in by_note[6]])

print("cross-references")
check(by_note[2][0]["xref_target"] == by_note[1][0]["i"], "Id. in n.2 resolves to McCulloch in n.1")
check(by_note[4][0]["xref_target"] == by_note[3][0]["i"], "Doe, supra note 3 resolves to the Doe article")
check(by_note[4][1]["xref_target"] == by_note[1][0]["i"], "McCulloch, 17 U.S. at 400 resolves to the full cite")
check(by_note[6][0]["xref_status"] == "unresolved", "supra note 9 (nonexistent) is unresolved")
check(L["unresolved_xrefs"] == [by_note[6][0]["i"]], "unresolved list carries exactly the broken supra")

print("quotes + keys")
check(by_note[1][0]["quoted"] is True, "body quote pinned to n.1 marks McCulloch quoted")
check(by_note[5][0]["quoted"] is True, "body quote pinned to n.5 marks the book quoted")
check(by_note[3][0]["quoted"] is False, "article is unquoted")
check(by_note[1][0]["key"] == "17 u s 316", "McCulloch source key mirrors workflow sourceKey (%s)" % by_note[1][0]["key"])
check(cl.source_key("Id. at 522 (emphasis added)") == "id", "sourceKey of an Id. collapses to 'id'")
keys = {s["key"] for s in L["secondary_cites"]}
check(len(L["secondary_cites"]) == 2, "2 unique secondary cites (article, book)")

print("dispositions — nothing ran")
c0 = cl.assign_dispositions(json.loads(json.dumps(L)), secondary_pass_ran=False, case_pass_ran=False)
check(c0.get("unchecked", 0) == 5, "5 substantive instances unchecked when no pass ran (%s)" % c0)
check(c0.get("verified", 0) == 0 and c0.get("existence-only", 0) == 0, "no instance called verified/existence-only")
check(c0.get("unresolved-xref") == 1 and c0.get("xref") == 3, "xrefs: 3 resolved, 1 unresolved")
check(c0.get("internal-ref") == 2, "internal cross-refs are inventoried but never 'unchecked' (%s)" % c0)

print("dispositions — full run")
L2 = json.loads(json.dumps(L))
case_ex = {"17 U.S. 316": {"exists": True}, "5 U.S. 137": {"exists": True}, "3 U.S. 171": {"exists": True}}
sec_ex = {by_note[3][0]["key"]: {"exists": False}, by_note[5][0]["key"]: {"exists": True}}
qv = {by_note[1][0]["i"]: ["verbatim"], by_note[5][0]["i"]: ["verbatim"]}
c = cl.assign_dispositions(L2, case_ex, sec_ex, qv)
d = {x["i"]: x["disposition"] for x in L2["instances"]}
check(d[by_note[1][0]["i"]] == "verified", "quoted case cite -> verified")
check(d[by_note[2][1]["i"]] == "existence-only", "unquoted Marbury -> existence-only (support not assessed)")
check(d[by_note[2][2]["i"]] == "existence-only", "nested Hylton -> existence-only")
check(d[by_note[3][0]["i"]] == "finding", "secondary source that does not exist -> finding")
check(d[by_note[5][0]["i"]] == "verified", "quoted book -> verified")
check(d[by_note[6][0]["i"]] == "unresolved-xref", "broken supra stays a finding-grade unresolved xref")
check("unchecked" not in c, "no instance left unchecked in a full run (%s)" % c)

print("dispositions — partial run")
L3 = json.loads(json.dumps(L))
c3 = cl.assign_dispositions(L3, case_ex, {}, qv, secondary_pass_ran=False)
d3 = {x["i"]: x["disposition"] for x in L3["instances"]}
check(d3[by_note[3][0]["i"]] == "unchecked", "secondary pass skipped -> article is UNCHECKED, not passed")
check(d3[by_note[5][0]["i"]] == "verified", "quoted book still verified by its quote")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
