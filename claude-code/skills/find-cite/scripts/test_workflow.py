#!/usr/bin/env python3
"""Offline checks of find-cite.workflow.js under stubbed agents (no model, no network).

Drives scripts/workflow_harness.mjs and asserts that:

  * unusable arguments stop the script with an error that begins "find-cite workflow:", names
    every problem and says no agent was started, and no agent starts;
  * authorityType "auto" is settled by the rule for clear propositions (no classifier agent) and
    by the stubbed classifier otherwise; a classifier that dies twice falls back to both, as a limit;
  * a candidate that fails verification is dropped, counted, and absent from the entry, and a
    top-up round verifies the next candidates when fewer than two survive;
  * a proposed quotation ships only on a valid receipt (hash of the exact text, verbatim or
    normalized status, contained in the matched passage); otherwise the paraphrase is used;
  * a pincite ships only when it was seen in an opened source, and a receipt's page fixes a wrong pin;
  * a student note is flagged and ranked last;
  * a dead agent is retried once, and a second death is recorded as a limit;
  * the agent cap (12 starts) holds, and what it cut is a limit; a budget cut is a limit;
  * the entry holds exactly the cites in `cites`, in order, and no other reporter citation;
  * exitState is complete_with_limits exactly when degradation is non-empty, in every run;
  * the Zotero instruction follows zoteroServer; models follow the legal-research constants.
Skipped without node.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKFLOW = HERE.parent / "find-cite.workflow.js"
HARNESS = HERE / "workflow_harness.mjs"
sys.dont_write_bytecode = True  # leave no __pycache__ beside these scripts or the hooks
sys.path.insert(0, str(HERE))
from quote_receipt import quote_hash  # noqa: E402

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: find-cite workflow test skipped")
    sys.exit(0)

SKILLS = "/plugin/skills"
CITE_RX = re.compile(r"\b\d{1,4} (?:U\.S\.|S\. Ct\.|F\.(?: ?\dd)?|[A-Z][A-Za-z.]{1,20} L\. ?(?:Rev|J)\.) \d{1,5}\b")
all_runs = []


def run(plan):
    p = subprocess.run([node, str(HARNESS), str(WORKFLOW), json.dumps(plan)], capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("harness failed")
    r = json.loads(p.stdout.strip().splitlines()[-1])
    if r.get("ok"):
        all_runs.append(r)
        if r["unstubbed"]:
            print("  unstubbed agent calls: %s" % r["unstubbed"])
    return r


def args(**kw):
    a = {"skillsDir": SKILLS, "proposition": "A defendant who denies the acts may still get an entrapment instruction.",
         "asOfDate": "2026-11-23"}
    a.update(kw)
    return a


def cand(citation, kind="case", **kw):
    c = {"kind": kind, "citation": citation, "url": "https://example.org/" + re.sub(r"\W+", "-", citation)[:40],
         "why": "on point", "fit": "direct", "role": "supporting", "supportingLanguage": "snippet text"}
    c.update(kw)
    return c


def receipt(quote, status="verbatim", excerpt=None, page=None, page_end=None, pincite_ok=None, h=None):
    q = quote.strip(" \t\r\n")
    return {"id": "x", "status": status, "quote_hash": h or quote_hash(q),
            "match_excerpt": q if excerpt is None else excerpt, "text_from": "file", "source": "https://example.org",
            "source_sha256": "0" * 64, "page": page, "page_end": page_end, "pincite_ok": pincite_ok}


def vcase(name, rep, year, pin="62", supports="squarely", opened=True, seen=True, quote="", rc=None, exists=True, **kw):
    v = {"exists": exists, "kind": "case", "caseName": name, "reporterCite": rep, "courtYear": year,
         "opened": opened, "url": "https://static.case.law/x", "pincite": pin, "pinciteSeen": seen,
         "opinionPart": "majority", "supports": supports, "paraphrase": "holding that the rule applies",
         "fit": "canonical cite", "basis": "opened at the pincite on CAP", "treatmentChecked": True,
         "treatment": "No negative treatment in the CourtListener citing probe.", "signal": "See"}
    if quote:
        v["quote"] = quote
    if rc is not None:
        v["quoteReceipt"] = rc
    v.update(kw)
    return v


def varticle(authors, title, vol, journal, first, year, pin="12", kind="article", supports="squarely", opened=True, seen=True, **kw):
    v = {"exists": True, "kind": kind, "authors": authors, "title": title, "volume": vol, "journal": journal,
         "firstPage": first, "year": year, "opened": opened, "url": "https://repo.example.edu/x", "pincite": pin,
         "pinciteSeen": seen, "opinionPart": "n/a", "supports": supports,
         "paraphrase": "arguing that the rule is incoherent", "fit": "leading article", "basis": "opened the repository PDF",
         "treatmentChecked": False, "studentNote": kind == "note", "venueTier": 1 if kind == "article" else 3, "signal": "See also"}
    v.update(kw)
    return v


A = ("Alpha v. Beta", "485 U.S. 58", "1988")
B = ("Gamma v. Delta", "500 U.S. 1", "1991")
C = ("Epsilon v. Zeta", "510 U.S. 7", "1994")
D = ("Eta v. Theta", "520 U.S. 9", "1997")
E = ("Iota v. Kappa", "530 U.S. 11", "2000")
cc = lambda t: "%s, %s (%s)" % t  # noqa: E731


def refused(r, *needles):
    m = r.get("message", "")
    return (not r["ok"]) and r["agents"] == 0 and m.startswith("find-cite workflow:") \
        and "No agent was started" in m and all(n in m for n in needles)


def entry_matches_cites(out):
    entry, cites = out["entry"], out["cites"]
    pos, ok = -1, True
    for c in cites:
        at = entry.find(c["citation"])
        if at <= pos:
            ok = False
        pos = at
    covered = " ".join(c["citation"] for c in cites)
    stray = [m for m in CITE_RX.findall(entry) if m not in covered]
    return ok and not stray, stray


# ---------------------------------------------------------------------------------------
print("arguments are checked before any agent starts")
check(refused(run({"args": "{not json"}), "not valid JSON"), "a string that is not JSON")
check(refused(run({"argsUndefined": True}), "args is missing"), "no arguments")
check(refused(run({"args": [1]}), "not an object"), "a list")
check(refused(run({"args": {}}), "skillsDir", "proposition"), "an empty object names both required arguments")
check(refused(run({"args": args(proposition="   ")}), "proposition is missing or empty"), "a blank proposition")
check(refused(run({"args": args(authorityType="cases-only")}), "authorityType must be one of"), "an unknown authority type")
check(refused(run({"args": args(zoteroServer="my server")}), "zoteroServer"), "a malformed Zotero server name")
check(refused(run({"args": args(constraints=["x"])}), "constraints must be a string"), "constraints as a list")
check(refused(run({"args": args(authority_type="cases")}), "unknown argument authority_type"), "a misspelled argument")
check(refused(run({"args": args(skillsDir='/a"b')}), "skillsDir contains"), "a skillsDir that would break a shell command")
r = run({"args": {"proposition": "", "authorityType": 3, "jurisdiction": 5}})
check(refused(r, "skillsDir", "proposition", "authorityType", "jurisdiction"), "every problem is named at once")
r = run({"args": json.dumps(args(authorityType="cases")), "search": {"cases": []}})
check(r["ok"] and r["out"]["authorityType"] == "cases", "a JSON string that parses is accepted")

# ---------------------------------------------------------------------------------------
print("baseline: cases only, all verified, one quotation confirmed")
QA = "even if the defendant denies one or more elements of the crime, he is entitled to an instruction"
plan = {"args": args(authorityType="cases"),
        "search": {"cases": [cand(cc(B)), cand(cc(A), role="canonical"), cand(cc(C), fit="close")]},
        "verify": {cc(A): vcase(*A, quote=QA, rc=receipt(QA, excerpt="even if the defendant denies one or more elements\nof the crime, he is entitled to an instruction")),
                   cc(B): vcase(*B, pin="5"), cc(C): vcase(*C, pin="9", supports="partially", shortfall="it concerns a different defense")}}
r = run(plan)
out = r["out"]
check(out["exitState"] == "complete" and out["degradation"] == [], "a clean run ends complete (%s)" % out["degradation"])
check("scope" not in r["labels"] and r["calls"].get("search:cases") == 1 and "search:scholarship" not in r["calls"], "no classifier; one sweep")
check(out["counts"]["agentStarts"] == 4 and out["counts"]["agentCap"] == 12, "1 sweep + 3 verifiers (%s)" % out["counts"]["agentStarts"])
check(r["opts"]["search:cases"]["model"] == "haiku" and all(r["opts"][k]["model"] == "sonnet" for k in r["opts"] if k.startswith("verify:")),
      "search on haiku, verification on sonnet")
check([c["citation"] for c in out["cites"]] == ["*Alpha v. Beta*, 485 U.S. 58, 62 (1988)", "*Gamma v. Delta*, 500 U.S. 1, 5 (1991)",
                                                "*Epsilon v. Zeta*, 510 U.S. 7, 9 (1994)"], "canonical first; partial support last (%s)" % [c["citation"] for c in out["cites"]])
check(out["cites"][0]["support"] == {"type": "quotation", "text": QA} and "(“%s”)" % QA in out["entry"], "the confirmed quotation ships in quotation marks")
check(out["cites"][1]["support"]["type"] == "paraphrase" and "(holding that the rule applies)." in out["entry"], "the others carry their paraphrase")
check(any("closest is *Epsilon v. Zeta* (no. 3)" in g for g in out["gaps"]) is False, "a lane with a square hit reports no gap")
ok, stray = entry_matches_cites(out)
check(ok, "the entry holds exactly the cites, in order (stray: %s)" % stray)
check("Treatment: No negative treatment" in out["entry"] and "Signal (tentative): *See*" in out["entry"], "treatment and tentative signal lines")
check(out["entry"].count('"') == 0 and out["entry"].count("“") == 1, "the only double quotation marks in the entry are the checked quotation's")
check("verify_quotes.py" in r["verifyPrompt"] and "quote_receipt.py" in r["verifyPrompt"] and "check_cite.py" in r["verifyPrompt"]
      and "cl_case_tools.py\" find" in r["verifyPrompt"] and "cl_case_tools.py\" citing" in r["verifyPrompt"]
      and r["verifyPrompt"].count(SKILLS + "/legal-research/") >= 4, "verifiers use the shared helper scripts through skillsDir")

# ---------------------------------------------------------------------------------------
print("auto: the rule settles clear propositions; the classifier settles the rest")
r = run({"args": args(proposition="Scholars have argued that the doctrine rests on a fiction."), "search": {"scholarship": []}})
check(r["out"]["authorityType"] == "scholarship" and "scope" not in r["labels"] and r["out"]["authorityTypeBasis"].startswith("rule:"), "literature claim -> scholarship by rule")
r = run({"args": args(proposition="The Supreme Court has held that entrapment is a jury question."), "search": {"cases": []}})
check(r["out"]["authorityType"] == "cases" and "scope" not in r["labels"], "doctrine -> cases by rule")
r = run({"args": args(proposition="The Court has grown skeptical of the doctrine."), "search": {"cases": [], "scholarship": []}})
check(r["out"]["authorityType"] == "both" and "scope" not in r["labels"], "characterization -> both by rule")
r = run({"args": args(), "scope": {"authorityType": "scholarship", "reason": "a framing claim about the \"field\""}, "search": {"scholarship": []}})
check(r["out"]["authorityType"] == "scholarship" and r["calls"].get("scope") == 1 and r["opts"]["scope"]["model"] == "haiku"
      and r["out"]["authorityTypeBasis"].startswith("classifier:") and '"' not in r["out"]["authorityTypeBasis"], "otherwise the stubbed classifier decides")
r = run({"args": args(), "scope": "die", "search": {"cases": [], "scholarship": []}})
check(r["out"]["authorityType"] == "both" and r["calls"].get("scope") == 2 and r["out"]["exitState"] == "complete_with_limits"
      and any("classifier failed twice" in d for d in r["out"]["degradation"]), "a classifier that dies twice: both, as a limit")
r = run({"args": args(authorityType="Scholarship"), "search": {"scholarship": []}})
check(r["out"]["authorityType"] == "scholarship" and r["out"]["authorityTypeBasis"] == "requested", "a requested type is used as given")

# ---------------------------------------------------------------------------------------
print("failed verification is dropped and counted; a top-up round follows")
F_ = ("Lambda v. Mu", "540 U.S. 13", "2003")
plan = {"args": args(authorityType="cases"),
        "search": {"cases": [cand(cc(A)), cand(cc(B)), cand(cc(C)), cand(cc(D)), cand(cc(E)), cand(cc(F_))]},
        "verify": {cc(A): vcase(*A), cc(B): vcase(*B, exists=False), cc(C): vcase(*C, supports="no"),
                   cc(D): vcase(*D, supports="no"), cc(E): vcase(*E, pin="12"), cc(F_): vcase(*F_, pin="14")}}
r = run(plan)
out = r["out"]
check(out["counts"]["dropped"] == 3 and len(out["dropped"]) == 3, "three dropped (%s)" % out["counts"])
check(all(x not in out["entry"] for x in ("500 U.S. 1", "510 U.S. 7", "520 U.S. 9", "Gamma", "Epsilon", "Eta v.")), "dropped cites are absent from the entry")
check(r["calls"].get("verify:c5") == 1 and r["calls"].get("verify:c6") == 1 and out["counts"]["delivered"] == 3, "the top-up verified the next two")
check(out["exitState"] == "complete", "drops alone are not a limit")
ok, stray = entry_matches_cites(out)
check(ok, "entry matches cites after a top-up")

# ---------------------------------------------------------------------------------------
print("a quotation without a valid receipt becomes a paraphrase")
Q = "the government may not originate a criminal design and implant it in an innocent mind"
plan = {"args": args(authorityType="cases"),
        "search": {"cases": [cand(cc(A)), cand(cc(B)), cand(cc(C)), cand(cc(D))]},
        "verify": {cc(A): vcase(*A, quote=Q, rc=receipt(Q, h="deadbeef")),
                   cc(B): vcase(*B, quote=Q, rc=receipt(Q, status="not_found", excerpt="")),
                   cc(C): vcase(*C, quote=Q, rc=receipt(Q, excerpt="an entirely different passage of the opinion")),
                   cc(D): vcase(*D, quote=Q)}}
r = run(plan)
out = r["out"]
check(all(c["support"]["type"] == "paraphrase" for c in out["cites"]) and Q not in out["entry"], "none of the four ships as a quotation")
why = [c["quotationCheck"] for c in out["cites"]]
check(any("different text" in w for w in why) and any("not_found" in w for w in why) and any("not inside" in w for w in why)
      and any("no receipt" in w for w in why), "each reason is recorded (%s)" % why)
check(out["entry"].count("could not be confirmed against the source text") == 4 and "“" not in out["entry"], "the entry says so, with no quotation marks")
QL = "x" * 260
r = run({"args": args(authorityType="cases"), "search": {"cases": [cand(cc(A))]}, "verify": {cc(A): vcase(*A, quote=QL, rc=receipt(QL))}})
check(r["out"]["cites"][0]["support"]["type"] == "paraphrase", "an over-long quotation is not shipped")
QU = "the § 1983 remedy isn’t limited to state actors in that narrow sense"
r = run({"args": args(authorityType="cases"), "search": {"cases": [cand(cc(A))]}, "verify": {cc(A): vcase(*A, quote=QU, rc=receipt(QU))}})
check(r["out"]["cites"][0]["support"]["type"] == "quotation", "the JS and Python hashes agree on non-ASCII text")

# ---------------------------------------------------------------------------------------
print("pincites ship only when seen")
plan = {"args": args(authorityType="cases"), "search": {"cases": [cand(cc(A)), cand(cc(B)), cand(cc(C))]},
        "verify": {cc(A): vcase(*A, opened=False), cc(B): vcase(*B, seen=False), cc(C): vcase(*C, pin="9", quote=Q, rc=receipt(Q, page=12, pincite_ok=False))}}
out = run(plan)["out"]
by = {c["citation"].split("*")[1]: c for c in out["cites"]}
check(by["Alpha v. Beta"]["citation"] == "*Alpha v. Beta*, 485 U.S. 58 (1988)" and by["Alpha v. Beta"]["verification"]["level"] == "partial", "an unopened source: partial, no pincite")
check(by["Gamma v. Delta"]["pincite"] == "" and by["Gamma v. Delta"]["verification"]["level"] == "partial", "a pin not seen is not given")
check(by["Epsilon v. Zeta"]["citation"] == "*Epsilon v. Zeta*, 510 U.S. 7, 12 (1994)", "the receipt's page replaces a wrong pin")
check(out["cites"][0]["citation"].startswith("*Epsilon"), "the fully verified cite ranks first")

# ---------------------------------------------------------------------------------------
print("student notes are flagged and ranked last")
NOTE = "Note, Entrapment Again, 101 Yale L.J. 5 (1990)"
S1 = "Jane Roe, Article One, 100 Harv. L. Rev. 1 (1987)"
plan = {"args": args(authorityType="both"),
        "search": {"cases": [cand(cc(A)), cand(cc(B))],
                   "scholarship": [cand(NOTE, kind="note", studentNote=True, venueTier=3), cand(S1, kind="article", venueTier=1)]},
        "verify": {cc(A): vcase(*A), cc(B): vcase(*B, pin="5"),
                   NOTE: varticle("", "Entrapment Again", "101", "Yale L.J.", "5", "1990", kind="note"),
                   S1: varticle("Jane Roe", "Article One", "100", "Harv. L. Rev.", "1", "1987", opened=False)}}
r = run(plan)
out = r["out"]
check(len(out["cites"]) == 4 and out["cites"][-1]["studentNote"] and not any(c["studentNote"] for c in out["cites"][:-1]), "the note is last, though verified in full")
check(out["cites"][-1]["citation"] == "Note, *Entrapment Again*, 101 Yale L.J. 5, 12 (1990)", "Bluebook note form (%s)" % out["cites"][-1]["citation"])
check("Student note: last resort" in out["entry"].split("4. ")[1] and any("student note" in g.lower() for g in out["gaps"]), "flagged in the entry and the gaps")
check(out["cites"][2]["citation"] == "Jane Roe, *Article One*, 100 Harv. L. Rev. 1 (1987)", "a partial article carries no pincite")
ok, stray = entry_matches_cites(out)
check(ok, "entry matches cites for a mixed result (stray: %s)" % stray)

# ---------------------------------------------------------------------------------------
print("dead agents: retried once, then a limit")
plan = {"args": args(authorityType="cases"), "search": {"cases": [cand(cc(A)), cand(cc(B)), cand(cc(C))]},
        "verify": {cc(A): vcase(*A), cc(B): "die", cc(C): dict(vcase(*C, pin="9"), dieOnce=True)}}
r = run(plan)
out = r["out"]
check(r["calls"]["verify:c2"] == 2 and r["calls"]["verify:c3"] == 2, "each dead verifier was retried once")
check(out["counts"]["notChecked"] == 1 and out["counts"]["delivered"] == 2 and "Gamma" not in out["entry"], "the twice-dead one is not delivered")
check(out["exitState"] == "complete_with_limits" and any("failed twice" in d for d in out["degradation"]) and "**Limits of this run:**" in out["entry"],
      "it is a limit, shown in the entry")
r = run({"args": args(authorityType="both"), "search": {"cases": "die", "scholarship": []}})
check(r["calls"]["search:cases"] == 2 and any("cases search did not run" in d for d in r["out"]["degradation"]), "a dead search lane is retried once, then a limit")
check(any("No case could be verified" in g for g in r["out"]["gaps"]), "and the gap is stated")

# ---------------------------------------------------------------------------------------
print("the agent cap and the budget")
many = [cand("Case%d v. Other, %d U.S. %d (1990)" % (i, 400 + i, i)) for i in range(6)]
arts = [cand("Author%d, Title %d, %d Harv. L. Rev. %d (1990)" % (i, i, 90 + i, i), kind="article") for i in range(3)]
plan = {"args": args(authorityType="both"), "search": {"cases": many, "scholarship": arts},
        "verify": {c["citation"]: "die" for c in many + arts}}
r = run(plan)
out = r["out"]
check(len(r["labels"]) == 12 and out["counts"]["agentStarts"] == 12, "no more than 12 agent starts (%d)" % len(r["labels"]))
check(any("agent cap" in d for d in out["degradation"]) and out["exitState"] == "complete_with_limits", "the cap's cut is a limit")
check(out["cites"] == [] and "No authority could be verified" in out["entry"], "nothing unverified ships")
plan = {"args": args(authorityType="cases"), "search": {"cases": [cand(cc(A)), cand(cc(B)), cand(cc(C))]},
        "verify": {cc(A): vcase(*A), cc(B): vcase(*B), cc(C): vcase(*C)}, "budgetTotal": 2000 + 40000}
r = run(plan)
check(r["calls"].get("verify:c3") is None and any("token budget stopped 1" in d for d in r["out"]["degradation"]), "a budget cut is a limit")

# ---------------------------------------------------------------------------------------
print("free text cannot smuggle in another authority or a double quotation mark")
plan = {"args": args(authorityType="cases"), "search": {"cases": [cand(cc(A)), cand(cc(B))]},
        "verify": {cc(A): vcase(*A, fit='Canonical cite. Followed in Omega v. Psi, 999 U.S. 1 (2020).', paraphrase='holding that "entrapment" is a defense'),
                   cc(B): vcase(*B)}}
out = run(plan)["out"]
check("999 U.S. 1" not in out["entry"] and "Canonical cite." in out["entry"], "a sentence citing another authority is removed")
check('"' not in out["entry"] and "‘entrapment’" not in out["entry"] and "'entrapment'" in out["entry"], "double quotation marks in a paraphrase become single")

# ---------------------------------------------------------------------------------------
print("Zotero follows zoteroServer")
r = run({"args": args(authorityType="scholarship", zoteroServer="zotero-fccl"), "search": {"scholarship": []}})
check("mcp__zotero-fccl__zotero_search_items" in r["searchPrompts"]["search:scholarship"], "named server: searched first")
r = run({"args": args(authorityType="scholarship"), "search": {"scholarship": []}})
check("Do not search Zotero" in r["searchPrompts"]["search:scholarship"] and "mcp__" not in r["searchPrompts"]["search:scholarship"], "no server: told not to search Zotero")

# ---------------------------------------------------------------------------------------
print("invariants over every run above")
bad = [x["out"]["exitState"] for x in all_runs if bool(x["out"]["degradation"]) != (x["out"]["exitState"] == "complete_with_limits")]
check(not bad and all(x["out"]["exitState"] in ("complete", "complete_with_limits") for x in all_runs), "exitState matches degradation in %d runs" % len(all_runs))
check(all(entry_matches_cites(x["out"])[0] for x in all_runs), "every entry holds exactly its cites, in order")
check(all(len(x["labels"]) <= 12 for x in all_runs), "no run exceeded the agent cap")
check(all(not x["unstubbed"] for x in all_runs), "no unstubbed agent call")
check(all(list(x["out"].keys())[:6] ==["proposition", "authorityType", "authorityTypeBasis", "exitState", "degradation", "entry"] for x in all_runs),
      "entry comes before the long fields in the result")
for x in all_runs:
    for c in x["out"]["cites"]:
        if c["verification"]["level"] != "verified" and re.search(r", \d+(?:[–-]\d+)? \(", c["citation"]):
            check(False, "a partial cite carries a pincite: %s" % c["citation"])

print("a lane delivers its own kind of authority (first live run, 2026-11-23)")
manual = "U.S. Dep't of Justice, Criminal Resource Manual 646"
r = run({"args": args(authorityType="cases"),
         "search": {"cases": [cand("Mathews v. United States, 485 U.S. 58 (1988)"), cand(manual, kind="other")]},
         "verify": {"Mathews v. United States, 485 U.S. 58 (1988)": vcase("Mathews v. United States", "485 U.S. 58", "1988"),
                    manual: {"exists": True, "kind": "other", "citationText": manual, "opened": False, "url": "https://www.justice.gov/x",
                             "supports": "partially", "paraphrase": "summarizing Mathews", "fit": "secondary guidance, not authority",
                             "basis": "Existence only from search results.", "opinionPart": "n/a"}}})
out = r["out"]
check(r["ok"] and [c["kind"] for c in out["cites"]] == ["case"], "a cases lane delivers only the case (%s)" % [c["kind"] for c in out["cites"]])
check(any("not a case" in d["reason"] for d in out["dropped"]) and "Criminal Resource Manual" not in out["entry"], "the manual page is dropped, counted, and absent from the entry")
check(out["counts"]["dropped"] == 1 and out["counts"]["delivered"] == 1, "counts follow")
case_in_schol = "Jacobson v. United States, 503 U.S. 540 (1992)"
r = run({"args": args(authorityType="scholarship"),
         "search": {"scholarship": [cand(case_in_schol)]},
         "verify": {case_in_schol: vcase("Jacobson v. United States", "503 U.S. 540", "1992")}})
check(r["ok"] and not r["out"]["cites"] and any("not scholarship" in d["reason"] for d in r["out"]["dropped"]), "a scholarship lane delivers no case")
paper = "Working Paper on Entrapment"
r = run({"args": args(authorityType="scholarship"),
         "search": {"scholarship": [cand(paper, kind="other")]},
         "verify": {paper: {"exists": True, "kind": "other", "citationText": paper, "opened": False, "url": "https://example.org/p",
                            "supports": "partially", "paraphrase": "arguing the point", "fit": "adjacent", "basis": "search result only", "opinionPart": "n/a"}}})
check(r["ok"] and not r["out"]["cites"] and any("search results only" in d["reason"] for d in r["out"]["dropped"]), "an unopened 'other' source is dropped, not partially verified")
r = run({"args": args(authorityType="cases"),
         "search": {"cases": [cand("Mathews v. United States, 485 U.S. 58 (1988)")]},
         "verify": {"Mathews v. United States, 485 U.S. 58 (1988)": vcase("Mathews v. United States", "485 U.S. 58", "1988", basis="Opened on CAP.")}})
check(r["ok"] and ".;" not in r["out"]["entry"] and ". ;" not in r["out"]["entry"], "a basis ending in a period does not leave stray punctuation in the entry")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
