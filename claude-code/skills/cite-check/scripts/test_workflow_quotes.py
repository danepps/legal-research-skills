#!/usr/bin/env python3
"""Offline test of cite-check.workflow.js's QUOTE accounting (2026-11-15 review).

Builds a markdown fixture with five quotations on five cases, runs the deterministic prep
scripts, then drives the workflow through scripts/workflow_quote_harness.mjs with stubbed agents
and checks the defects that review found:

  * a second checker that corrects a mismatch to a DIFFERENT finding (a syllabus quote) no
    longer makes the finding disappear as an "artifact": it is reported under the corrected
    verdict, counted, exported and recorded as a finding in the ledger;
  * a finding the second checker withdraws (verbatim after all) is an artifact, and its ledger
    instance is "verified", not "existence-only";
  * re-verify results are joined by job position, so a second checker that echoes the wrong
    unit id cannot rewrite another quote's verdict;
  * a verify agent's verdict for a quote it was not given is dropped and counted;
  * the re-verify pass is no longer all-or-nothing: under a tight budget it re-derives as many
    high-severity findings as fit (the reserve guarantees three) and flags the rest;
  * a dead case-existence batch is retried once, and cites still unanswered are disclosed;
  * every source-reading agent gets its own scratch-file prefix, and the re-verify prompt
    states the unit id to return;
  * the report prompt points secondary-source items at the sections that now hold them.

Needs node (the workflow is JavaScript). Skips, with exit 0, when node is absent.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(os.path.dirname(HERE), "cite-check.workflow.js")
HARNESS = os.path.join(HERE, "workflow_quote_harness.mjs")

QUOTES = [
    "the power to tax involves the power to destroy the thing taxed",
    "it is emphatically the province and duty of the judicial department to say what the law is",
    "the question is whether the words used are used in such circumstances as to create a danger",
    "separate educational facilities are inherently unequal under the settled rule",
    "the right of the people to be secure in their houses shall not be violated by officers",
]
BODY = " ".join('In case %d the Court said that "%s" and went on.[^%d]' % (i + 1, q, i + 1) for i, q in enumerate(QUOTES))
NOTES = "\n".join("[^%d]: Case%d v. Other, %d U.S. %d, %d (19%d)." % (i + 1, i, 100 + i, 200 + i, 205 + i, 50 + i) for i in range(len(QUOTES)))
DRAFT = BODY + "\n\n" + NOTES + "\n"

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: workflow quote harness test skipped")
    sys.exit(0)


def run_script(name, *argv):
    return subprocess.run([sys.executable, os.path.join(HERE, name), *argv], check=True,
                          capture_output=True, text=True).stdout


with tempfile.TemporaryDirectory() as td:
    md = os.path.join(td, "draft.md")
    ex = os.path.join(td, "extract.json")
    with open(md, "w", encoding="utf-8") as f:
        f.write(DRAFT)
    run_script("extract_cites.py", md, ex)
    units = json.loads(run_script("prepare_units.py", ex, os.path.join(td, "units.json")))
    ledger = json.loads(run_script("citation_ledger.py", ex, "--compact"))
    data = json.load(open(ex, encoding="utf-8"))
    args = {
        "skillsDir": os.path.dirname(os.path.dirname(HERE)), "extractPath": ex, "draftName": "d",
        "footnoteCount": data["footnote_count"], "unitCount": units["unit_count"], "unitNotes": units["unit_notes"],
        "caseCites": data["unique_case_cites"], "supraProblems": data["supra_problem_candidates"],
        "formChecks": data["form_checks"], "ledger": ledger["instances"], "secondaryCites": ledger["secondary"],
        "unitIds": None, "deep": False, "history": False, "zotero": False, "support": False,
    }
    ap = os.path.join(td, "args.json")
    json.dump(args, open(ap, "w"))

    def run(scenario, extra=None):
        path = ap
        if extra:
            path = os.path.join(td, "args-%s.json" % scenario)
            json.dump(dict(args, **extra), open(path, "w"))
        p = subprocess.run([node, HARNESS, WORKFLOW, path, scenario], capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stderr[-2000:])
            raise SystemExit("harness failed for scenario %s" % scenario)
        return json.loads(p.stdout.strip().splitlines()[-1])

    check(units["unit_count"] == 5 and len(data["unique_case_cites"]) == 5 and len(ledger["instances"]) == 5,
          "fixture: 5 quote units, 5 case cites, 5 ledger instances (got %d/%d/%d)" % (units["unit_count"], len(data["unique_case_cites"]), len(ledger["instances"])))

    print("baseline")
    r = run("baseline")
    c = r["counts"]
    check(c["quotesChecked"] == 5 and c["verbatim"] == 5 and r["items"] == [], "five quotes verbatim, no findings (%s)" % c)
    check(all(v == "verified" for v in r["ledger"].values()), "ledger: every instance verified (%s)" % r["ledger"])
    px = r["scratchPrefixes"]
    check(len(px) == 5 and all(px) and len(set(px)) == 5 and not r["genericScratch"],
          "each verify agent has its own scratch-file prefix and no prompt names a generic /tmp file (%s)" % px)
    check("sections E/I/J" in r["reportSecondaryHeader"] and "sections E/G" not in r["reportSecondaryHeader"],
          "report prompt: secondary-source items point at sections E/I/J, not at the history section")

    print("second checker corrects a mismatch to a different finding")
    r = run("corrected")
    c = r["counts"]
    check(c["syllabus"] == 1 and c["mismatch"] == 0 and c["artifactsCaught"] == 0 and r["artifactsCaught"] == [],
          "the corrected finding is counted as a syllabus quote, not as an artifact (%s)" % c)
    check(r["items"] == [[1, "syllabus_quote"]], "it is exported as a finding (%s)" % r["items"])
    check("syllabus_quote, HIGH" in r["reportHigh"] and "first checker said mismatch" in r["reportHigh"],
          "it reaches the report's high-severity block with the first verdict named")
    check(r["ledger"]["1"] == "finding", "ledger: the instance is a finding (%s)" % r["ledger"]["1"])
    check(r["reverifyNamesId"], "the re-verify prompt states the unit id to return")

    print("second checker withdraws the finding")
    r = run("withdrawn")
    c = r["counts"]
    check(c["artifactsCaught"] == 1 and c["mismatch"] == 0 and r["items"] == [] and "(none)" in r["reportHigh"],
          "a finding cleared on re-verification is an artifact and stays out of the report (%s)" % c)
    check(r["ledger"]["1"] == "verified", "ledger: the withdrawn finding's instance is verified, not existence-only (%s)" % r["ledger"]["1"])

    print("second checker echoes the wrong unit id")
    r = run("wrong-echo")
    c = r["counts"]
    check(r["items"] == [[1, "mismatch"]] and c["mismatch"] == 1 and c["verbatim"] == 4,
          "only the quote that was re-verified is a finding; the neighbouring quote stays verbatim (%s, %s)" % (r["items"], c))
    check(c["singleChecker"] == 0 and not any("no re-verify verdict" in d for d in r["degradation"]),
          "the result is credited to the finding the job was launched for")

    print("verify agent returns a verdict for another source's quote")
    r = run("foreign-id")
    c = r["counts"]
    check(c["quotesChecked"] == 5 and c["verbatim"] == 4 and c["mismatch"] == 1, "five quotes, five verdicts: the foreign one is not counted (%s)" % c)
    check(any("1 quote verdict(s) dropped" in d for d in r["degradation"]), "the dropped verdict is disclosed (%s)" % r["degradation"])
    check(r["items"] == [[2, "mismatch"]] and r["ledger"]["2"] == "finding", "the quote keeps the verdict of the agent that read its source")

    print("budget fits three of five second derivations")
    # 150k segment + 90k existence + 5 x 680k verify leaves 360k of the 4M cap: the reserve held
    # back for re-verify (3 x 100k) guarantees three, and two do not fit.
    r = run("all-high", {"costModel": {"verify": 680_000}})
    c = r["counts"]
    rv = [a for a in r["agents"] if a.startswith("re-verify")]
    check(len([a for a in r["agents"] if a.startswith("verify")]) == 5, "all five sources verified")
    check(len(rv) == 3 and c["singleChecker"] == 2, "three findings re-derived, two flagged single-checker (%d launched, %s)" % (len(rv), c))
    check(any("skipped for 2 of 5" in d for d in r["degradation"]), "degradation says two of five were skipped for budget (%s)" % r["degradation"])
    check(r["reportHigh"].count("SINGLE-CHECKER") == 2 and "Report" in r["agents"], "the report labels the two that were not re-derived")
    r = run("all-high")
    check(len([a for a in r["agents"] if a.startswith("re-verify")]) == 5 and r["counts"]["singleChecker"] == 0, "control: with room, all five are re-derived")

    print("case-existence batch dies")
    r = run("exist-flaky")
    check(r["agents"].count("exist:5") == 2 and r["counts"]["casesChecked"] == 5 and not any("existence result" in d for d in r["degradation"]),
          "a dead batch is retried once and the retry's results are used")
    r = run("exist-dead")
    check(r["agents"].count("exist:5") == 2 and any("5 case cite(s) got no existence result" in d for d in r["degradation"]) and r["exitState"] == "complete_with_limits",
          "a batch that dies twice is disclosed (%s)" % r["degradation"])

    print("temporary files: every agent that can save one is told where, and args.scratchDir moves them all")
    FILE_AGENTS = ("exist:", "verify:", "re-verify:")

    def temp_prefixes(r):
        return [(t["label"], t["prefix"]) for t in r["tempFiles"] if t["label"].startswith(FILE_AGENTS)]

    r = run("corrected", {"runTag": "t1"})
    px = temp_prefixes(r)
    check({k for k in FILE_AGENTS if any(l.startswith(k) for l, _ in px)} == set(FILE_AGENTS), "existence, verify and re-verify agents all ran (%s)" % [l for l, _ in px])
    check(all(re.fullmatch(r"/tmp/cc-t1-[A-Za-z0-9-]+-", p) for _, p in px) and len({p for _, p in px}) == len(px),
          "with no scratchDir each has its own /tmp/cc-<runTag>-<tag>- prefix (%s)" % [p for _, p in px][:3])
    check(r["tmpNamed"] > 0 and len(r["scratchPrefixes"]) >= 5 and all(r["scratchPrefixes"]), "the /tmp paths are named in the prompts, as before")
    DIR = "/Users/a b/Proj/.dubitante/runs/r1/work/.tmp"
    r = run("corrected", {"runTag": "t1", "scratchDir": DIR})
    px2 = temp_prefixes(r)
    check([p for _, p in px2] == ['"%s/%s"' % (DIR, p[len("/tmp/"):]) for _, p in px],
          "with scratchDir the same names sit in that folder, double-quoted because the path has a space")
    check(r["tmpNamed"] == 0, "and no prompt names a /tmp path of this workflow")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
