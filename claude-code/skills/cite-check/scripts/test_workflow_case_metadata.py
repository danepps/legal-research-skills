#!/usr/bin/env python3
"""Offline test of two cite-check.workflow.js fixes from the 2026-11-23 live run (E0).

1. A full case citation whose reporter cite resolves to a DIFFERENT case, or to a different year,
   is a finding. The live run cited "Sherman v. United States, 356 U.S. 396 (1958)" (CourtListener
   resolves 356 U.S. 396 to Thomas v. Arizona) and "Sorrells v. United States, 287 U.S. 435
   (1934)" (lookup date 1932-12-19), and its report said every case cite was confirmed with no
   metadata issues. Checked here: the finding reaches counts, the findings export (and
   findings_diff.py), the ledger disposition, and the report agent's data; a table of name pairs
   that must NOT be flagged (Bluebook abbreviations, first names in captions, acronyms, In re,
   ex rel., et al., a one-letter spelling slip) and pairs that must; the year rules; no comparison
   on a web-only, name-search or corrected existence result.
2. exitState is complete_with_limits exactly when `degradation` is non-empty, and each limit is a
   plain sentence with its count and cause (the live run ended complete_with_limits with an empty
   list; the cause was a history lookup that got HTTP 429 twice), with no duplicate lines.
3. A clean result written into a finding field is not a finding (2026-11-27, five live runs of the
   same draft gave 7 to 11 findings): "None naming …" treatment text, "No metadata problems …"
   metadata lines, and a history line that only restates the case-name or year mismatch.

Drives the workflow through scripts/workflow_case_harness.mjs with stubbed agents (no model, no
network). Skips, with exit 0, when node is absent.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(os.path.dirname(HERE), "cite-check.workflow.js")
HARNESS = os.path.join(HERE, "workflow_case_harness.mjs")
sys.path.insert(0, HERE)
import findings_diff  # noqa: E402

# The E0 fixture (make_citecheck_fixture.py in the app repo), as markdown.
DRAFT = """The federal entrapment defense turns on a question a jury usually decides. The Supreme Court has said that the instruction does not depend on a confession: "We hold that even if the defendant denies one or more elements of the crime, he is entitled to an entrapment instruction whenever there is sufficient evidence from which a reasonable jury could find entrapment."[^1] Once the defense is properly raised, the burden sits with the government.[^2] The doctrine is older than either statement. The Court first recognized the defense in a Prohibition-era prosecution,[^3] and returned to it a generation later in a narcotics case.[^4]

The defense looks to the defendant's state of mind and not to the government's conduct alone.[^5] That focus has drawn criticism, but the Court has not moved from it.[^6]

[^1]: Mathews v. United States, 485 U.S. 58, 62 (1988).
[^2]: Jacobson v. United States, 503 U.S. 540, 549 (1992) ("the prosecution must prove beyond reasonable doubt that the defendant was predisposed to commit the criminal act before being approached by Government agents").
[^3]: Sorrells v. United States, 287 U.S. 435 (1934).
[^4]: Sherman v. United States, 356 U.S. 396 (1958).
[^5]: United States v. Russell, 411 U.S. 423, 433 (1973); see also Mathews, 485 U.S. at 63.
[^6]: See Sherman, supra note 9; Jacobson, 503 U.S. at 548.
"""
# What the live run's existence agent returned for the three cites its stream shows in full
# (2026-11-23). For Mathews and Jacobson the stream was truncated; their stubs carry the draft's
# own name and year, which is all this test needs from them.
LIVE_EXISTENCE = {
    "287 U.S. 435": {"caseName": "Sorrells v. United States", "dateFiled": "1932-12-19"},
    "356 U.S. 396": {"caseName": "Thomas v. Arizona", "dateFiled": "1958-06-30"},
    "411 U.S. 423": {"caseName": "United States v. Russell", "dateFiled": "1973-04-24"},
    "485 U.S. 58": {"caseName": "Mathews v. United States", "dateFiled": "1988"},
    "503 U.S. 540": {"caseName": "Jacobson v. United States", "dateFiled": "1992"},
}
# The live run's history entry for Mathews (result.history, 2026-11-23).
LIVE_HISTORY_429 = {"485 U.S. 58": {"status": "tool-error", "confidence": "low", "historyBasis": "not-checked",
                                    "note": "The citing call returned HTTP 429 twice (initial run and one retry). Treatment is unchecked. Rerun later."}}

# (draft case name, caption the lookup returned): must NOT be flagged
SAME = [
    ("United States v. Mathews", "United States v. Frederick Mathews"),
    ("Brown v. Bd. of Educ.", "Brown v. Board of Education of Topeka"),
    ("Nat'l Fed'n of Indep. Bus. v. Sebelius", "National Federation of Independent Business v. Sebelius"),
    ("FCC v. Fox Television Stations, Inc.", "Federal Communications Commission v. Fox Television Stations, Inc."),
    ("In re Gault", "In Re Gault"),
    ("Ex parte Milligan", "Ex Parte Milligan"),
    ("United States ex rel. Toth v. Quarles", "Toth v. Quarles"),
    ("United States v. Russell", "United States v. Russell"),
    ("Int'l Shoe Co. v. Washington", "International Shoe Co. v. Washington, Office of Unemployment Compensation and Placement"),
    ("United States v. AT&T", "United States v. American Telephone & Telegraph Co."),
    ("Nat'l Labor Relations Bd. v. United States", "NLRB v. United States"),
    ("Comm'r v. Glenshaw Glass Co.", "Commissioner v. Glenshaw Glass Co."),
    ("Smith et al. v. Jones", "Smith v. Jones"),
    ("Texas v. New Mexico", "Texas v. New Mexico"),
    ("People v. Defore", "People of the State of New York v. John Defore"),
    ("United States v. Matthews", "United States v. Mathews"),  # a spelling slip is not this finding
    ("Ass'n for Molecular Pathology v. Myriad Genetics, Inc.", "Association for Molecular Pathology v. Myriad Genetics, Inc."),
    ("Dep't of Commerce v. New York", "Department of Commerce v. New York"),
    ("Phila. Newspapers, Inc. v. Hepps", "Philadelphia Newspapers, Inc. v. Hepps"),
    ("NAACP v. Alabama ex rel. Patterson", "National Association for the Advancement of Colored People v. Alabama ex rel. Patterson"),
    ("Bd. of Regents of State Colls. v. Roth", "Board of Regents of State Colleges v. Roth"),
    ("Pa. v. Mimms", "Pennsylvania v. Mimms"),
    ("United States v. United States", "Thomas v. Arizona"),  # no distinctive or state token: not compared
    ("The Prize Cases", "The Brig Amy Warwick"),  # a popular name for grouped decisions: not compared
]
# must be flagged
DIFFERENT = [
    ("Sherman v. United States", "Thomas v. Arizona"),
    ("Arizona v. Gant", "Arizona v. Fulminante"),  # a state is generic: the distinctive party is Gant
    ("Texas v. New Mexico", "Kansas v. Colorado"),  # state-only names compared by their states
    ("In re Gault", "In re Winship"),
    ("Brown v. Bd. of Educ.", "Plessy v. Ferguson"),
    ("Commonwealth v. Smith", "Commonwealth v. Jones"),
    ("People v. Defore", "People v. Smith"),
]

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: workflow case-metadata test skipped")
    sys.exit(0)


def run_script(name, *argv):
    return subprocess.run([sys.executable, os.path.join(HERE, name), *argv], check=True,
                          capture_output=True, text=True).stdout


def inst(i, text, cite, kind="case", key=None):
    return {"i": i, "n": i + 1, "k": kind, "c": text, "key": key or cite.lower().replace(".", " ").replace("  ", " "),
            "case": cite if kind == "case" else None, "x": None, "xn": None, "xs": None, "q": False,
            "s": "", "pin": "", "par": False}


with tempfile.TemporaryDirectory() as td:
    def run(args, stub):
        path = os.path.join(td, "args-%d.json" % len(os.listdir(td)))
        json.dump(dict(args, _stub=stub), open(path, "w"))
        p = subprocess.run([node, HARNESS, WORKFLOW, path], capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stderr[-2000:])
            raise SystemExit("harness failed")
        return json.loads(p.stdout.strip().splitlines()[-1])

    def invariant(r, label):
        d = r["degradation"]
        check((r["exitState"] == "complete_with_limits") == bool(d) and r["exitState"] in ("complete", "complete_with_limits"),
              "%s: exit state %s with %d degradation line(s)" % (label, r["exitState"], len(d)))
        check(len(d) == len(set(d)), "%s: no duplicate degradation lines" % label)

    # ---- the live run's draft ------------------------------------------------------------
    md = os.path.join(td, "draft.md")
    ex = os.path.join(td, "extract.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(DRAFT)
    run_script("extract_cites.py", md, ex)
    units = json.loads(run_script("prepare_units.py", ex, os.path.join(td, "units.json")))
    ledger = json.loads(run_script("citation_ledger.py", ex, "--compact"))
    data = json.load(open(ex, encoding="utf-8"))
    live = {
        "skillsDir": os.path.dirname(os.path.dirname(HERE)), "extractPath": ex, "draftName": "Entrapment note",
        "footnoteCount": data["footnote_count"], "unitCount": units["unit_count"], "unitNotes": units["unit_notes"],
        "caseCites": data["unique_case_cites"], "supraProblems": data["supra_problem_candidates"],
        "formChecks": data["form_checks"], "ledger": ledger["instances"], "secondaryCites": ledger["secondary"],
        "unitIds": None, "deep": False, "history": True, "zotero": False, "support": False,
    }
    check(sorted(data["unique_case_cites"]) == sorted(LIVE_EXISTENCE), "fixture: the five case cites of the live run (%s)" % data["unique_case_cites"])

    print("the live run: Sherman at 356 U.S. 396 and Sorrells dated 1934")
    r = run(live, {"existence": LIVE_EXISTENCE, "history": LIVE_HISTORY_429})
    c = r["counts"]
    check(c["caseCiteMismatches"] == 2 and c["caseNameMismatch"] == 1 and c["caseYearMismatch"] == 1,
          "counts: 2 citations, 1 name and 1 year (%s)" % {k: c[k] for k in ("caseCiteMismatches", "caseNameMismatch", "caseYearMismatch")})
    cm = [i for i in r["items"] if i["kind"] == "case-metadata"]
    check(sorted((i["footnote"], i["field"]) for i in cm) == [(3, "year"), (4, "name")], "findings export: n.3 year, n.4 name (%s)" % [(i["footnote"], i["field"]) for i in cm])
    sher = next((i for i in cm if i["field"] == "name"), {})
    check(sher.get("draft") == "Sherman v. United States" and sher.get("resolved") == "Thomas v. Arizona" and sher.get("resolvedDate") == "1958-06-30"
          and sher.get("cite") == "356 U.S. 396" and sher.get("find") == "Sherman v. United States, 356 U.S. 396 (1958)."
          and sher.get("source") == "CourtListener's citation lookup", "Sherman item: what the draft says, what the lookup gave, and the source (%s)" % sher)
    sor = next((i for i in cm if i["field"] == "year"), {})
    check(sor.get("draft") == "1934" and sor.get("resolvedDate") == "1932-12-19" and sor.get("resolved") == "Sorrells v. United States",
          "Sorrells item: 1934 in the draft against 1932-12-19 (%s)" % sor)
    led = {x["n"]: x for x in r["ledger"] if x["k"] == "case"}
    check(led[3]["d"] == "finding" and "1934" in led[3]["why"] and "1932-12-19" in led[3]["why"], "ledger n.3 (Sorrells) is a finding, with why (%s)" % led[3])
    check(led[4]["d"] == "finding" and "Thomas v. Arizona" in led[4]["why"], "ledger n.4 (Sherman) is a finding, with why (%s)" % led[4])
    check(led[5]["d"] == "existence-only" and led[1]["d"] == "verified", "ledger: Russell stays existence-only, Mathews verified")
    check(c["ledger"].get("finding") == 2 and c["ledger"].get("existence-only") == 1, "counts.ledger moves the two out of existence-only (%s)" % c["ledger"])
    blk = r["reportCaseBlock"]
    check("Sherman v. United States, 356 U.S. 396 (1958)." in blk and "resolves 356 U.S. 396 to Thomas v. Arizona (decided 1958-06-30)" in blk
          and "Either the case name or the reporter cite is wrong" in blk, "report data: the Sherman line names both sides and does not say which is wrong")
    check("the draft gives 1934; CourtListener's citation lookup gives a decision date of 1932-12-19 for 287 U.S. 435" in blk
          and "Either the year or the reporter cite is wrong" in blk, "report data: the Sorrells line")
    check("2 full citation(s) whose case name or year does not match" in r["reportExistence"], "report data: the existence summary counts them")
    check(r["reportAsksForSection"], "report prompt: own section, and never 'confirmed with no issues' while the count is non-zero")
    check(not any(i["kind"] == "case-metadata" and i["footnote"] in (1, 2, 5) for i in r["items"]), "no case-metadata item for Mathews, Jacobson or Russell")
    # exit state: the live run's limit, now explained
    invariant(r, "live run")
    d = [x for x in r["degradation"] if "485 U.S. 58" in x]
    check(r["exitState"] == "complete_with_limits" and len(d) == 1 and "CourtListener tool returned an error" in d[0] and "HTTP 429" in d[0],
          "degradation names the history tool error, its cite and cause (%s)" % r["degradation"])
    check("485 U.S. 58" in r["reportLimits"], "the report agent gets the run limits for its method note")

    print("findings_diff.py with the new kind")
    prev = {"items": r["items"]}
    fixed = {"items": [i for i in r["items"] if not (i["kind"] == "case-metadata" and i["field"] == "name")]}
    ki = [findings_diff.key_of(i) for i in cm]
    check(len(set(ki)) == 2, "the name item and the year item have different keys")
    pa, pb = os.path.join(td, "prev.json"), os.path.join(td, "cur.json")
    json.dump(prev, open(pa, "w"))
    json.dump(fixed, open(pb, "w"))
    out = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "findings_diff.py"), pa, pb, "--json"], check=True, capture_output=True, text=True).stdout)
    check(out["counts"]["resolved"] == 1 and out["resolved"][0]["field"] == "name" and out["counts"]["new"] == 0,
          "fixing the Sherman cite resolves the name item only (%s)" % out["counts"])
    moved = [dict(i, footnote=(i.get("footnote") or 0) + 1) for i in r["items"]]
    json.dump({"items": moved}, open(pb, "w"))
    out = json.loads(subprocess.run([sys.executable, os.path.join(HERE, "findings_diff.py"), pa, pb, "--json"], check=True, capture_output=True, text=True).stdout)
    check(out["counts"]["new"] == 0 and out["counts"]["resolved"] == 0, "a renumbered draft keeps the items still open (%s)" % out["counts"])
    md_out = subprocess.run([sys.executable, os.path.join(HERE, "findings_diff.py"), pa, pa], check=True, capture_output=True, text=True).stdout
    check("[case-metadata: name-mismatch]" in md_out and "[case-metadata: year-mismatch]" in md_out, "the Markdown diff labels the kind and field")

    # ---- the name table and the year rules ------------------------------------------------
    print("name pairs and year rules")
    rows = []  # (draft text, cite, existence stub, expect name flag, expect year flag, label)
    for k, (dn, cap) in enumerate(SAME):
        rows.append(("%s, %d U.S. %d (1990)." % (dn, 100 + k, 10 + k), {"caseName": cap, "dateFiled": "1990-06-01"}, False, False, "same: %s / %s" % (dn, cap)))
    for k, (dn, cap) in enumerate(DIFFERENT):
        rows.append(("%s, %d U.S. %d (1990)." % (dn, 200 + k, 10 + k), {"caseName": cap, "dateFiled": "1990-06-01"}, True, False, "different: %s / %s" % (dn, cap)))
    years = [
        ("Sorrells v. United States, %s (1934).", {"caseName": "Sorrells v. United States", "dateFiled": "1932-12-19"}, False, True, "year differs"),
        ("Sorrells v. United States, %s.", {"caseName": "Sorrells v. United States", "dateFiled": "1932-12-19"}, False, False, "draft gives no year"),
        ("Sorrells v. United States, %s (1934).", {"caseName": "Sorrells v. United States"}, False, False, "lookup gives no date"),
        ("Doe v. Roe, %s (2d Cir. 1990).", {"caseName": "Doe v. Roe", "dateFiled": "1990-02-01"}, False, False, "court-and-year parenthetical, same year"),
        ("Doe v. Roe, %s (2d Cir. 1990).", {"caseName": "Doe v. Roe", "dateFiled": "1991-02-01"}, False, True, "court-and-year parenthetical, other year"),
        ("Doe v. Roe, %s, 512 (1990) (citing a 1999 statute).", {"caseName": "Doe v. Roe", "dateFiled": "1990-02-01"}, False, False, "explanatory parenthetical's year is not read"),
        ("%s (2023).", {"caseName": "Thomas v. Arizona", "dateFiled": "2023-06-01"}, False, False, "nameless cite (named in the text): no name check"),
        ("%s (2023).", {"caseName": "Thomas v. Arizona", "dateFiled": "2022-06-01"}, False, True, "nameless cite: the year is still checked"),
        ("Sherman v. United States, %s (1934).", {"caseName": "Thomas v. Arizona", "dateFiled": "1958-06-30", "basis": "web"}, False, False, "web-only basis: no comparison"),
        ("Sherman v. United States, %s (1934).", {"caseName": "Thomas v. Arizona", "dateFiled": "1958-06-30", "note": "resolved by name search; no reporter cite on the CourtListener record"}, False, False, "name-search route: no comparison"),
        ("Sherman v. United States, %s (1934).", {"caseName": "Thomas v. Arizona", "dateFiled": "1958-06-30", "corrected": "356 U.S. 369"}, False, False, "a proposed reporter-typo correction: no comparison"),
        ("The Court so held in Sherman v. United States, %s (1958).", {"caseName": "Thomas v. Arizona", "dateFiled": "1958-06-30"}, True, False, "textual sentence: the name starts at the party"),
        ("See, e.g., Sherman v. United States, %s, 372 (1958).", {"caseName": "Sherman v. United States", "dateFiled": "1958-05-19"}, False, False, "signal and pincite"),
        ("Roe v. Wade, %s, 93 S. Ct. 705 (1973).", {"caseName": "Roe v. Wade", "dateFiled": "1973-01-22"}, False, False, "parallel cite before the year"),
        ("Roe v. Wade, %s, 93 S. Ct. 705 (1974).", {"caseName": "Roe v. Wade", "dateFiled": "1973-01-22"}, False, True, "parallel cite, other year"),
    ]
    for k, (fmt, stub, en, ey, label) in enumerate(years):
        rows.append((fmt % ("%d U.S. %d" % (300 + k, 10 + k)), stub, en, ey, label))
    instances, caseCites, stubs = [], [], {}
    import re
    for i, (text, stub, en, ey, label) in enumerate(rows):
        cite = re.search(r"\d+ U\.S\. \d+", text).group(0)
        instances.append(inst(i, text, cite))
        caseCites.append(cite)
        stubs[cite] = stub
    table = {
        "skillsDir": os.path.dirname(os.path.dirname(HERE)), "extractPath": os.path.join(td, "unused-extract.json"), "draftName": "table",
        "footnoteCount": len(instances), "unitCount": 0, "caseCites": caseCites, "ledger": instances, "secondaryCites": [],
        "history": True, "zotero": False, "support": False,
    }
    r = run(table, {"existence": stubs})
    by_i = {x["i"]: x for x in r["ledger"]}
    items = {}
    for it in r["items"]:
        if it["kind"] == "case-metadata":
            items.setdefault(it["footnote"] - 1, set()).add(it["field"])
    for i, (text, stub, en, ey, label) in enumerate(rows):
        got = items.get(i, set())
        ok = (("name" in got) == en) and (("year" in got) == ey) and ((by_i[i]["d"] == "finding") == (en or ey))
        check(ok, "%s -> %s%s" % (label, ",".join(sorted(got)) or "not flagged", "" if ok else "  [%s; ledger %s]" % (text, by_i[i]["d"])))
    check(r["counts"]["caseNameMismatch"] == sum(1 for row in rows if row[2]) and r["counts"]["caseYearMismatch"] == sum(1 for row in rows if row[3]),
          "counts match the table")
    invariant(r, "table run")
    check(r["exitState"] == "complete" and r["degradation"] == [], "findings alone are not limits: the table run is complete")

    # ---- exit state across limit causes ----------------------------------------------------
    print("exit state and degradation across limit causes")
    base = dict(table, caseCites=caseCites[:3], ledger=instances[:3], footnoteCount=3)
    ok3 = {c: stubs[c] for c in caseCites[:3]}
    r = run(base, {"existence": ok3})
    invariant(r, "clean")
    check(r["exitState"] == "complete", "a clean run is complete")

    r = run(dict(base, history=True), {"existence": ok3, "history": {caseCites[0]: {"status": "tool-error", "note": "HTTP 429 twice"}}})
    invariant(r, "history tool error")
    check(any("CourtListener tool returned an error" in d and caseCites[0] in d for d in r["degradation"]), "history tool error named with its cite")

    r = run(dict(base, history=True), {"existence": ok3, "history": {caseCites[1]: {"status": "not-resolved"}}})
    invariant(r, "history not resolved")
    check(any("could not resolve the cite" in d and caseCites[1] in d for d in r["degradation"]), "history not-resolved named")

    r = run(base, {"existence": dict(ok3, **{caseCites[2]: {"exists": False, "basis": "unconfirmed", "note": "lookup, name search, web: nothing"}})})
    invariant(r, "case unconfirmed")
    check(any("could not be confirmed to exist" in d and caseCites[2] in d for d in r["degradation"]), "unconfirmed case cite named")

    r = run(base, {"existence": dict(ok3, **{caseCites[2]: None})})
    invariant(r, "case with no existence result")
    check(sum("got no existence result" in d for d in r["degradation"]) == 1 and not any("not reached by any pass" in d for d in r["degradation"]),
          "a missing existence result is said once, not again as an unreached ledger instance (%s)" % r["degradation"])

    orphan = dict(base, ledger=base["ledger"] + [dict(inst(3, "Doe v. Roe, slip op. at 4 (2026).", "x"), case=None)], footnoteCount=4)
    r = run(orphan, {"existence": ok3})
    invariant(r, "ledger instance no pass reached")
    check(any("not reached by any pass" in d for d in r["degradation"]), "an unreached ledger instance is said")

    sec = {"key": "jane doe the taxing power", "kind": "article", "cite": "Jane Doe, The Taxing Power, 110 Harv. L. Rev. 815 (1997)"}
    withsec = dict(base, secondaryCites=[sec], ledger=base["ledger"] + [dict(inst(3, sec["cite"], "x", kind="article", key=sec["key"]))], footnoteCount=4)
    r = run(withsec, {"existence": ok3, "secondary": {sec["key"]: {"exists": False, "basis": "unconfirmed"}}})
    invariant(r, "secondary unconfirmed")
    check(any("secondary source(s) could not be located" in d for d in r["degradation"]), "an unconfirmed secondary source is said")

    r = run(live, {"existence": LIVE_EXISTENCE, "quotes": {"1": "unverifiable"}})
    invariant(r, "quote unverifiable")
    check(any("quotation(s) could not be verified" in d for d in r["degradation"]), "an unverifiable quotation is said")

    r = run(dict(base, history=False), {"existence": ok3})
    invariant(r, "history turned off")
    check(r["degradation"] == ["subsequent-history / treatment pass turned off by the caller (history:false)"], "history:false is its own single line (%s)" % r["degradation"])

    # ---- clean results are not findings (2026-11-27) -----------------------------------
    # Texts as the five live runs of 2026-11-27 returned them (abridged).
    print("clean results in finding fields: the 2026-11-27 runs")
    clean_history = {
        "287 U.S. 435": {"historyFinding": 'Draft cite says "(1934)"; CourtListener shows decided 1932-12-19. Year error, not a history item.',
                         "treatment": "None naming this case. Signal rows (Spradley, Black, Webb, Jimenez Recio) concern other cases."},
        "356 U.S. 396": {"historyFinding": 'Draft cite "Sherman v. United States, 356 U.S. 396 (1958)" does not match: 356 U.S. 396 resolves to Thomas v. Arizona.',
                         "treatment": "None naming Thomas v. Arizona (356 U.S. 390). Signal rows are routine overruled objections."},
        "411 U.S. 423": {"treatment": "None found naming Russell as overruled or limited."},
        "485 U.S. 58": {"treatment": "Limited or declined to follow in part by a state court. People v. Brown, 218 P.3d 733 (Colo. App. 2009), says 'other divisions of this court have declined to follow Mathews with respect to the affirmative defense'."},
        "503 U.S. 540": {"treatment": "No adverse treatment found naming Jacobson."},
    }
    clean_meta = ["No metadata problems: Jacobson v. United States, 503 U.S. 540 (1992) matches the fetched record [source: https://static.case.law/us/503/html/0540-01.html]",
                  "No metadata problems found: Jacobson v. United States, 503 U.S. 540 (1992). [source: https://static.case.law/us/503/html/0540-01.html]",
                  "year: the draft gives 1991 for a synthetic source; the record gives 1992 [source: https://example.org/synthetic-record]"]
    r = run(live, {"existence": LIVE_EXISTENCE, "history": clean_history, "verifyMeta": clean_meta})
    kinds = [i["kind"] for i in r["items"]]
    tr = [i for i in r["items"] if i["kind"] == "treatment"]
    check(len(tr) == 1 and tr[0]["cite"] == "485 U.S. 58" and "People v. Brown" in tr[0]["label"],
          "treatment: only the Mathews flag; four 'None …' texts dropped (%s)" % [i["label"][:40] for i in tr])
    check("history" not in kinds, "history: the two restated name/year mismatches are not history findings (%s)" % [i["label"][:50] for i in r["items"] if i["kind"] == "history"])
    md_items = [i["label"] for i in r["items"] if i["kind"] == "metadata"]
    check(md_items == [clean_meta[2]], "metadata: the two 'No metadata problems' lines dropped, the real one kept (%s)" % md_items)
    check(kinds.count("case-metadata") == 2, "the case-metadata items still stand (%d)" % kinds.count("case-metadata"))
    check(r["counts"]["history"]["treatmentFlags"] == 1 and r["counts"]["history"]["missingHistory"] == 0,
          "counts: 1 treatment flag, 0 missing history (%s)" % r["counts"]["history"])
    hist = r["reportHistory"]
    add = hist.split("ADD SUBSEQUENT HISTORY", 1)[1].split("TREATMENT FLAGS", 1)[0]
    check("(none)" in add and "Year error" not in hist, "report data: nothing to add under subsequent history")
    check("People v. Brown" in hist and "None naming" not in hist and "None found" not in hist, "report data: the Mathews flag, no 'None …' text")

    print("a history outcome on a mismatched cite is still a finding")
    real = dict(clean_history)
    real["356 U.S. 396"] = {"historyFinding": "The draft omits that the judgment was vacated and remanded (synthetic outcome for this test)."}
    r = run(live, {"existence": LIVE_EXISTENCE, "history": real})
    hi = [i for i in r["items"] if i["kind"] == "history"]
    check(len(hi) == 1 and hi[0]["cite"] == "356 U.S. 396" and "vacated" in hi[0]["label"], "history: the vacated-and-remanded line stays (%s)" % [i["label"][:50] for i in hi])

    # ---- a treatment probe not read in full is not a check (2026-11-27) -------------------
    # The live run's history agent piped each citing output through `head -c 3500` and said so in
    # its notes; the report then said "Treatment flags: none" with no limit.
    print("treatment output cut short: the 2026-11-27 run")
    cut = {
        "287 U.S. 435": {"note": "Supreme Court; no history to add. Treatment output was truncated; no treatment flag read for this case.",
                         "coverage": "Supreme Court, no docket pass. Citing tool read, first ~3.5KB of output only (recent citing rows, all with empty signals)."},
        "356 U.S. 396": {"coverage": "Supreme Court, no docket pass. First ~3.5KB of output only."},
        "411 U.S. 423": {"note": "Supreme Court; no history to add. Output truncated; no treatment flag read in the portion seen."},
        "485 U.S. 58": {"note": "Supreme Court; no history to add.", "coverage": "Supreme Court, no docket pass. Both routes read in full."},
        "503 U.S. 540": {"note": "Supreme Court; no history to add.", "coverage": "Supreme Court, no docket pass."},
    }
    r = run(live, {"existence": LIVE_EXISTENCE, "history": cut})
    invariant(r, "truncated treatment output")
    d = [x for x in r["degradation"] if "not read in full" in x]
    check(len(d) == 1 and "3 case cite(s)" in d[0] and all(c in d[0] for c in ("287 U.S. 435", "356 U.S. 396", "411 U.S. 423"))
          and "485 U.S. 58" not in d[0] and "503 U.S. 540" not in d[0], "one limit line naming the three cut cites, not the two read in full (%s)" % d)
    check(r["exitState"] == "complete_with_limits", "exit state complete_with_limits")
    nc = r["reportHistory"].split("NOT CHECKED / NOT RESOLVED", 1)[1] if "NOT CHECKED / NOT RESOLVED" in r["reportHistory"] else r["reportNotChecked"]
    check(nc.count("treatment unchecked") == 3, "report data: the three cut cites under not checked (%d)" % nc.count("treatment unchecked"))
    r = run(live, {"existence": LIVE_EXISTENCE, "history": {}})
    check(not any("not read in full" in x for x in r["degradation"]), "no limit when every output was read")

    # ---- treatmentFlag false is not a flag (2026-11-27, the run that checked 1.6.20) -------
    print("treatmentFlag: a row set aside is not a flag")
    flagged = {
        "411 U.S. 423": {"treatmentFlag": False, "treatment": "Scope unconfirmed: State v. Shirley (N.M. Ct. App., 2007-08-23) has a row with the 'disapproved' signal. That row says Russell disapproved a different case, Bueno, so it is not adverse treatment of Russell."},
        "485 U.S. 58": {"treatmentFlag": True, "treatment": "Declined to follow, scope unconfirmed: People v. Brown (Colo. Ct. App., 2009-06-25) says 'other divisions of this court have declined to follow Mathews with respect to the affirmative defense'."},
        "503 U.S. 540": {"treatment": "Limited by a synthetic later case (no treatmentFlag field: an older agent answer)."},
    }
    r = run(live, {"existence": LIVE_EXISTENCE, "history": flagged})
    tr = sorted(i["cite"] for i in r["items"] if i["kind"] == "treatment")
    check(tr == ["485 U.S. 58", "503 U.S. 540"], "treatment items: Mathews (flag true) and the answer without the field; not Russell (%s)" % tr)
    hist = r["reportHistory"]
    flags = hist.split("TREATMENT FLAGS", 1)[1]
    check("Shirley" not in flags.split("NOT CHECKED")[0], "report data: Shirley is not listed as a treatment flag")

    # ---- 'not truncated' is not a cut; read-in-full is the agent's answer (the 1.6.21 run) ----
    print("treatmentReadInFull, and 'not truncated' in text")
    full = {c: {"coverage": "Full output read, not truncated. No docket pass (SCOTUS)."} for c in LIVE_EXISTENCE}
    r = run(live, {"existence": LIVE_EXISTENCE, "history": full})
    check(not any("not read in full" in x for x in r["degradation"]), "'not truncated' without the field: no limit (%s)" % r["degradation"])
    mixed = {"287 U.S. 435": {"treatmentReadInFull": True, "coverage": "first ~3.5KB of output only"},
             "356 U.S. 396": {"treatmentReadInFull": False, "coverage": "Full output read."}}
    r = run(live, {"existence": LIVE_EXISTENCE, "history": mixed})
    d = [x for x in r["degradation"] if "not read in full" in x]
    check(len(d) == 1 and "356 U.S. 396" in d[0] and "287 U.S. 435" not in d[0], "the field decides when present (%s)" % d)

    print("a metadata line that only confirms the cite")
    meta = ["Citation 503 U.S. 540, 549 (1992) is correct for the passage. [source: https://static.case.law/us/503/html/0540-01.html]",
            "The volume is correct but the first page should be 540 [source: https://example.org/synthetic-a]",
            "year: the draft gives 1991; the record gives 1992 [source: https://example.org/synthetic-b]"]
    r = run(live, {"existence": LIVE_EXISTENCE, "verifyMeta": meta})
    md_items = [i["label"] for i in r["items"] if i["kind"] == "metadata"]
    check(md_items == meta[1:], "the 'is correct' line dropped, the two with a discrepancy kept (%s)" % md_items)

    # ---- the treating court's rank does not matter (the 1.6.22 run set aside People v. Brown) --
    r = run(live, {"existence": LIVE_EXISTENCE})
    check("treating court's rank does" in r["historyPrompt"] and "state or lower court that declines to follow" in r["historyPrompt"],
          "history prompt: a state or lower court declining to follow is a flag")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
