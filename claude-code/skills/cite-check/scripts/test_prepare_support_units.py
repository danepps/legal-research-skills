#!/usr/bin/env python3
"""Synthetic-fixture test for prepare_support_units.py and the support-pass fields that
citation_ledger.py and extract_cites.py emit for it (added 2026-10-24). Locks in: every
unquoted instance becomes a unit; quoted, nested and unresolved instances do not; signals
are read per clause; a pincite is taken from the cite, or inherited down an Id. chain; the
proposition parenthetical and a separate-opinion note are captured; the anchor sentence /
clause is attached; scope is pincited vs whole-work; and the support dispositions never
promote a confirm item to a finding. No network, no credentials."""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import citation_ledger as cl  # noqa: E402
import prepare_support_units as psu  # noqa: E402

DRAFT = """Courts have long held that "the power to tax involves the power to destroy" when applied to federal instrumentalities.[^1] The Court reaffirmed the principle two decades later.[^2] Scholars have disagreed[^3] about its scope, and some have gone further.[^4] The literature is vast.[^5] A contrary view exists.[^6] Finally, a point with no page.[^7]

> A block quotation of some length that carries its own marker at the end and nothing else of note.[^8]

[^1]: McCulloch v. Maryland, 17 U.S. (4 Wheat.) 316, 431 (1819).
[^2]: See id. at 436; see also Marbury v. Madison, 5 U.S. (1 Cranch) 137, 177 (1803) (holding that it is emphatically the province of the judiciary to say what the law is) (quoting Hylton v. United States, 3 U.S. (3 Dall.) 171, 175 (1796)).
[^3]: Jane Doe, The Taxing Power Reconsidered, 110 Harv. L. Rev. 815, 820 (1997); but see John Roe, Federalism and Finance 45 (2d ed. 2010).
[^4]: Cf. 42 U.S.C. § 1983; see generally Doe, supra note 3, at 822.
[^5]: Id.; Smith, supra note 99, at 4.
[^6]: Scholars disagree. See Roe, supra note 3, at 50 (Thomas, J., concurring).
[^7]: Roe, supra note 3.
[^8]: Compare Doe, supra note 3, at 821, with Roe, supra note 3, at 52.
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
    units = psu.build_units(data)
    out = subprocess.run([sys.executable, os.path.join(HERE, "prepare_support_units.py"), ex, "--compact"],
                         check=True, capture_output=True, text=True)
    compact = json.loads(out.stdout)["units"]
    fnout = subprocess.run([sys.executable, os.path.join(HERE, "prepare_support_units.py"), ex, "--footnotes", "2-3"],
                           check=True, capture_output=True, text=True)
    picked = json.loads(fnout.stdout)["unit_ids"]

inst = L["instances"]
by_note = {}
for x in inst:
    by_note.setdefault(x["note"], []).append(x)
U = {}
for u in units:
    U.setdefault(u["note"], []).append(u)

print("anchors (extract_cites.py)")
a = {int(k): v["anchor"] for k, v in data["footnotes"].items()}
check(a[1]["position"] == "sentence-end" and a[1]["sentence"].startswith("Courts have long held"), "n.1 anchor is its sentence, marker at the end")
check(a[2]["previous"].startswith("Courts have long held"), "n.2 carries the preceding sentence")
check(a[3]["position"] == "mid-sentence" and a[3]["clause"] == "Scholars have disagreed", "n.3 mid-sentence marker -> clause before the marker (%r)" % a[3]["clause"])
check(a[4]["clause"] == "" and a[4]["sentence"].endswith("gone further."), "n.4 sentence-end marker -> whole sentence, no clause")
check(a[8]["block_quote"] is True and a[8]["previous"].startswith("Finally"), "block-quote anchor flagged, previous = last sentence of the prior paragraph")
check(data.get("warnings") == [] or not any("anchor" in w for w in data["warnings"]), "no anchor warning when every marker is in the body")

print("ledger fields (citation_ledger.py)")
check(by_note[1][0]["signal"] == "" and by_note[1][0]["pincite"] == "431", "full case cite: no signal, pincite 431")
check(by_note[2][0]["signal"] == "see" and by_note[2][0]["pincite"] == "436", "'See id. at 436' -> signal see, pincite 436")
check(by_note[2][1]["signal"] == "see also" and by_note[2][1]["pincite"] == "177", "'see also Marbury ... 137, 177' -> see also, pincite 177")
check(by_note[2][1]["parenthetical"].startswith("holding that"), "proposition parenthetical captured, not the (quoting ...) one (%r)" % by_note[2][1]["parenthetical"][:30])
check(by_note[2][2].get("nested") is True and by_note[2][2]["pincite"] == "", "nested Hylton is stored normalized (no pincite) — it is never a unit")
check(by_note[3][0]["pincite"] == "820", "article pincite after the first page (815, 820)")
check(by_note[3][1]["signal"] == "but see" and by_note[3][1]["pincite"] == "45", "'but see Roe ... 45 (2d ed. 2010)' -> but see, book page 45")
check(by_note[4][0]["signal"] == "cf." and by_note[4][0]["pincite"] == "§ 1983", "'Cf. 42 U.S.C. § 1983' -> cf., section locator")
check(by_note[4][1]["signal"] == "see generally" and by_note[4][1]["pincite"] == "822", "'see generally Doe, supra note 3, at 822' -> see generally, own pincite 822")
check([x["kind"] for x in by_note[6]] == ["text", "supra"], "n.6 splits into prose / Roe supra (%s)" % [x["kind"] for x in by_note[6]])
check(by_note[6][1]["opinion_note"] == "Thomas, J., concurring" and by_note[6][1]["pincite"] == "50", "separate-opinion note + page captured on the Roe supra")
check([x["signal"] for x in by_note[8]] == ["compare", "compare with"], "'Compare A, with B' splits into two instances with signals compare / compare with (%s)" % [x["signal"] for x in by_note[8]])
check(by_note[8][0]["pincite"] == "821" and by_note[8][1]["pincite"] == "52", "each side of the comparison keeps its own pincite")
check(by_note[8][1]["xref_status"] == "resolved" and inst[by_note[8][1]["xref_final"]]["text"].startswith("but see John Roe"), "'compare with Roe, supra note 3' resolves to the Roe book (signal words stripped from the name key)")
ck = cl.compact(L)[2]
check(ck["s"] == "see also" and ck["pin"] == "177" and ck["par"] is True, "compact form carries s / pin / par")

print("units (prepare_support_units.py)")
check(1 not in U, "quoted McCulloch (n.1, body quote) produces NO unit — the quote path covers it")
check([u["kind"] for u in U[2]] == ["case", "case"], "n.2: Id. and Marbury are units; nested Hylton is not (%s)" % [u["kind"] for u in U[2]])
check(U[2][0]["source"].startswith("McCulloch") and U[2][0]["resolved_from"] == "n.1" and U[2][0]["pincite"] == "436" and U[2][0]["pincite_basis"] == "own",
      "Id. at 436 resolves to McCulloch with its own pincite")
check(U[2][0]["anchor"]["sentence"] == "The Court reaffirmed the principle two decades later.", "unit carries the anchor sentence")
check(U[2][1]["parenthetical"].startswith("holding that") and U[2][1]["signal"] == "see also", "Marbury unit carries parenthetical + signal")
check([u["signal"] for u in U[3]] == ["", "but see"], "n.3 signals: direct, but see")
check(U[3][0]["anchor"]["clause"] == "Scholars have disagreed", "mid-sentence marker: unit carries the clause")
check(all(u["scope"] == "pincited" for u in U[3]), "pincited article and book are in default scope")
check(U[4][0]["kind"] == "statute" and U[4][0]["scope"] == "pincited", "a statute section is a locator -> pincited scope")
check(U[4][1]["kind"] == "article" and U[4][1]["resolved_from"] == "n.3" and U[4][1]["pincite"] == "822" and U[4][1]["pincite_basis"] == "own",
      "'see generally Doe, supra note 3, at 822' resolves to the Doe article with its own page")
n5u = U.get(5, [])
check(len(n5u) == 1, "n.5: the bare Id. is a unit; the broken 'Smith, supra note 99' is NOT (%d)" % len(n5u))
check(n5u[0]["kind"] == "article" and n5u[0]["pincite"] == "822" and n5u[0]["pincite_basis"] == "inherited",
      "bare 'Id.' after 'Doe, supra note 3, at 822' inherits page 822 (basis inherited)")
n6u = U.get(6, [])
check(len(n6u) == 1 and n6u[0]["opinion_note"] == "Thomas, J., concurring" and n6u[0]["pincite"] == "50", "Roe unit carries the concurrence note and page 50")
check(n6u[0]["note_prose"] == ["Scholars disagree."], "the footnote's own prose rides along as note_prose (%s)" % n6u[0]["note_prose"])
check(U[7][0]["scope"] == "whole-work" and U[7][0]["pincite"] == "" and U[7][0]["source"].startswith("but see John Roe"),
      "'Roe, supra note 3' with no page -> whole-work scope; never inherits note 3's page 45")
check(U[8][0]["anchor"]["block_quote"] is True, "block-quote anchor reaches the unit")
check(len(U[8]) == 2 and U[8][1]["signal"] == "compare with" and U[8][1]["source"].startswith("but see John Roe") and U[8][1]["pincite"] == "52",
      "both sides of 'Compare A, with B' are support units; the second is Roe at 52 with signal compare with")
check(all(u["note_text"] for u in units), "every unit carries the full footnote text")
check([u["id"] for u in units] == list(range(len(units))), "unit ids are dense from 0")
check(compact[0]["claim"] == "The Court reaffirmed the principle two decades later." and compact[0]["key"] == "17 u s 316",
      "compact form carries claim + source key")
check(sorted(picked) == [u["id"] for u in units if u["note"] in (2, 3)], "--footnotes 2-3 picks the right unit ids")

print("screener regressions (Codex review, 2026-10-25)")
sc = lambda c: (cl.classify(c)[0], cl.signal_of(c), cl.locate(c, cl.classify(c)[0]), cl.proposition_parenthetical(c), cl.opinion_note(c))
k, sig, pin, par, op = sc("See Smith v. Jones, No. 19-123 (S.D.N.Y. Mar. 3, 2020).")
check(pin == "" and par == "", "docket number is not a book page; court/date parenthetical is not a proposition (%r, %r)" % (pin, par))
k, sig, pin, par, op = sc("Smith v. Jones, No. 19-123, slip op. at 4 (S.D.N.Y. Mar. 3, 2020).")
check(pin == "4" and par == "", "'slip op. at 4' still a pincite; date parenthetical still ignored")
k, sig, pin, par, op = sc("Jack Balkin, Brown at 50: The Legacy, 90 Va. L. Rev. 1537 (2004).")
check(pin == "", "'Brown at 50' in a title is not a pincite (%r)" % pin)
check(cl.locate("Id. at 436", "id") == "436" and cl.locate("Doe, supra note 3, at 50", "supra") == "50" and cl.locate("McCulloch, 17 U.S. at 400", "case-short") == "400",
      "'at N' after a period or comma still locates")
k, sig, pin, par, op = sc("Doe v. Roe, 1 U.S. 2, 3 (2000) (rejecting the dissenting view that the rule is absolute).")
check(par.startswith("rejecting the dissenting") and op == "", "'rejecting the dissenting view' is a proposition, not a posture note (%r / %r)" % (par[:20], op))
for c, want in (("X, 1 U.S. 2 (2000) (Thomas, J., concurring).", "Thomas, J., concurring"),
                ("X, 1 U.S. 2 (2000) (Roberts, C.J., dissenting).", "Roberts, C.J., dissenting"),
                ("X, 1 U.S. 2 (2000) (Kagan & Sotomayor, JJ., dissenting).", "Kagan & Sotomayor, JJ., dissenting"),
                ("X, 1 U.S. 2 (2000) (opinion of Roberts, C.J.).", "opinion of Roberts, C.J."),
                ("X, 1 U.S. 2 (2000) (plurality opinion).", "plurality opinion"),
                ("X, 1 U.S. 2 (2000) (Breyer, J., concurring in part and dissenting in part).", "Breyer, J., concurring in part and dissenting in part")):
    check(cl.opinion_note(c) == want and cl.proposition_parenthetical(c) == "", "posture note %r captured, not a proposition" % want)
check(sc("For a contrary view, cf. Smith v. Jones, 100 F.3d 200, 205 (2d Cir. 1996).")[1] == "cf.", "signal after introductory prose is read (cf.)")
check(sc("*See* Smith v. Jones, 100 F.3d 200, 205 (2d Cir. 1996).")[1] == "see", "markdown-italicized signal is read")
check(sc("_But see_ Smith v. Jones, 100 F.3d 200 (2d Cir. 1996).")[1] == "but see", "underscore-italicized signal is read")
check(sc("Smith v. Jones, 100 F.3d 200, 205 (2d Cir. 1996) (see also the dissent).")[1] == "", "a signal word inside a parenthetical after a cite is not the clause's signal")
k, sig, pin, par, op = sc("Jane Doe, Title, 1 J. 5 (2020), https://example.org/x (last visited Jan. 5, 2020).")
check(par == "", "'last visited' parenthetical is not a proposition")
check(cl.proposition_parenthetical("Memo (on file with author).") == "", "'on file with author' is not a proposition")
check(cl.proposition_parenthetical("THE FEDERALIST NO. 10 (James Madison) (Jacob E. Cooke ed., 1961).") == "", "author and editor parentheticals are not propositions")
check(cl.proposition_parenthetical("X, 1 U.S. 2, 3 (2000) (holding that the clause applies to the states).") == "holding that the clause applies to the states", "'holding that' parenthetical still captured")
check(cl.proposition_parenthetical("X, 1 U.S. 2, 3 (2000) (the rule applies only to federal officers).") == "the rule applies only to federal officers", "a verbless proposition parenthetical of 3+ words still captured")

print("clause splitting after a citation (Codex review, 2026-10-25)")
cs = cl.split_clauses("See A v. B, 1 U.S. 2 (2000). For the contrary view, see C v. D, 2 U.S. 3 (2001).")
check(len(cs) == 2 and cl.classify(cs[1])[0] == "case" and cl.signal_of(cs[1]) == "see",
      "a sentence break after a cite starts a new clause; the prose-prefixed cite keeps its signal (%s)" % [c[:30] for c in cs])
cs = cl.split_clauses("Doe, supra note 3, at 50. For the contrary view, see Roe, supra note 3, at 52.")
check(len(cs) == 2 and cl.classify(cs[1])[0] == "supra", "same after a pincite: the second supra is its own instance")
cs = cl.split_clauses("Smith v. Jones, 1 U.S. 2 (2000). This case is important. Id. at 5.")
check([cl.classify(c)[0] for c in cs] == ["case", "text", "id"], "prose between cites becomes a text clause (%s)" % [cl.classify(c)[0] for c in cs])
check(len(cl.split_clauses("McCulloch v. Maryland, 17 U.S. (4 Wheat.) 316, 431 (1819).")) == 1, "a parallel-reporter parenthetical does not split")
check(len(cl.split_clauses("Smith v. Jones, 1 U.S. 2, 3 (2000) (holding that X. The court said so).")) == 1, "a sentence break inside a parenthetical does not split")
print("journal abbreviations with several periods (Codex smoke test, 2026-10-26)")
for c, pin in (("See generally Author, Title, 121 Yale L.J. 1286 (2012).", ""), ("Author, Title, 121 Yale L.J. 1286, 1290–92 (2012).", "1290–92"),
               ("Author, Title, 66 B.C. L. Rev. 1679 (2025).", ""), ("Author, Title, 91 N.Y.U. L. Rev. 762, 780 (2016).", "780"),
               ("Author, Title, 31 Fordham Urb. L.J. 1507, 1532 (2004).", "1532")):
    k = cl.classify(c)[0]
    check(k == "article" and cl.locate(c, k) == pin, "%r -> article, pin %r (got %s, %r)" % (c[:45], pin, k, cl.locate(c, k)))
check(cl.locate("Author, Title, 121 Yale L.J. 1286 (2012).", "book") == "", "a journal cite handed to the book rule does not take its first page as a pin")
check(cl.locate("RICHARD POSNER, ECONOMIC ANALYSIS OF LAW 45 (9th ed. 2014).", "book") == "45", "a real book page still locates")
check(cl.signal_of("See also generally Author, Title, 1 J. 5 (2020).") == "see generally", "'see also generally' keeps the background meaning")
check(cl.signal_of("*See also generally* Author, Title, 1 J. 5 (2020).") == "see generally", "italicized 'see also generally' too")
print("rule and code locators")
for c, want in (("Fed. R. Civ. P. 12(b)(6).", "12(b)(6)"), ("See Fed. R. Evid. 403.", "403"), ("Sup. Ct. R. 10(a).", "10(a)"), ("42 U.S.C. 1983.", "1983"), ("42 U.S.C. § 1983(a).", "§ 1983(a)")):
    k = cl.classify(c)[0]
    check(k == "statute" and cl.locate(c, k) == want, "%r -> statute at %r (got %s, %r)" % (c, want, k, cl.locate(c, k)))

print("support dispositions (reference implementation)")
L2 = json.loads(json.dumps(L))
case_ex = {"17 U.S. 316": {"exists": True}, "5 U.S. 137": {"exists": True}, "3 U.S. 171": {"exists": True}}
sec_ex = {x["key"]: {"exists": True} for x in inst if x["kind"] in ("article", "book", "statute")}
qv = {by_note[1][0]["i"]: ["verbatim"]}
sv = {by_note[2][0]["i"]: "supported", by_note[2][1]["i"]: "overstated", by_note[3][0]["i"]: "not_supported",
      by_note[3][1]["i"]: "contradicted", by_note[4][0]["i"]: "supported_qualified", by_note[4][1]["i"]: "unverifiable",
      by_note[7][0]["i"]: "unread"}
c = cl.assign_dispositions(L2, case_ex, sec_ex, qv, support_verdicts=sv)
d = {x["i"]: x["disposition"] for x in L2["instances"]}
check(d[by_note[1][0]["i"]] == "verified", "quoted cite stays verified")
check(d[by_note[2][0]["i"]] == "supported", "resolved Id. read for support -> supported (its own status, not xref)")
check(d[by_note[2][1]["i"]] == "support-confirm", "overstated -> support-confirm, never a finding")
check(d[by_note[3][0]["i"]] == "support-finding" and d[by_note[3][1]["i"]] == "support-finding", "not_supported / contradicted -> support-finding")
check(d[by_note[4][0]["i"]] == "supported", "supported_qualified -> supported")
check(d[by_note[4][1]["i"]] == "support-unverifiable", "unverifiable support read on a resolved supra -> support-unverifiable")
check(d[by_note[7][0]["i"]] == "xref", "an unread (out-of-scope) supra keeps its xref disposition")
check(d[by_note[2][2]["i"]] == "existence-only", "nested Hylton, never a unit, stays existence-only")
sec_ex2 = dict(sec_ex)
sec_ex2[by_note[3][0]["key"]] = {"exists": False}
L3 = json.loads(json.dumps(L))
cl.assign_dispositions(L3, case_ex, sec_ex2, qv, support_verdicts={by_note[3][0]["i"]: "supported"})
check({x["i"]: x["disposition"] for x in L3["instances"]}[by_note[3][0]["i"]] == "finding",
      "existence=false outranks a support verdict")
check(cl.support_disposition("unread") is None and cl.support_disposition("overstated") == "support-confirm",
      "support_disposition map: unread -> none, overstated -> confirm")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
