#!/usr/bin/env python3
"""Offline checks of legal-research.workflow.js's pipeline accounting (2026-11-15 review).

Runs the whole workflow under stubbed agents (workflow_harness.mjs; no model, no network) and
asserts what that review found and fixed:

  * a dead triage agent no longer crashes the run with a TypeError; repeated and out-of-range
    triage indices do not read a source twice;
  * a dead reader or survey vector is retried once, and a second death is a named coverage gap:
    the run ends complete_with_limits, Finalize is told, and a selected source nobody read stays
    in the draft's findings as an unread lead;
  * authorities harvested from the read sources reach the draft (they used to be cut by the
    lead cap every time the search leftovers filled it), spread across the read sources;
  * the soft cap is measured from the start of this run, not from the start of the turn;
  * deep mode: a refuted authority is labelled refuted, not "verified (3-voter panel)"; one
    voter's negative treatment is not hidden by another's "none found"; a citation correction
    proposed by one voter of three is disclosed, not applied, while one proposed by two is;
  * a cite-check verdict returned under an index the checker was not given cannot overwrite the
    verdict of the checker that was;
  * a source read this run is not stamped direct-full-text on the reader's say-so;
  * readers are told to probe candidate URLs in one call (SKILL.md has said so since 1.6.0).
Skipped without node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKFLOW = HERE / "legal-research.workflow.js"
HARNESS = HERE / "workflow_harness.mjs"

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: legal-research pipeline test skipped")
    sys.exit(0)


def run(scenario, spent="0"):
    p = subprocess.run([node, str(HARNESS), str(WORKFLOW), scenario, spent], capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("harness failed for scenario %s" % scenario)
    return json.loads(p.stdout.strip().splitlines()[-1])


print("baseline")
r = run("baseline")
check(r.get("exitState") == "complete" and r["degradation"] == [], "a clean run ends complete with nothing to disclose")
check(r["readAgents"] == 8 and r["counts"]["read"] == 8 and r["counts"]["leads"] == 16, "8 reads, 16 unread leads (%s)" % r["counts"])
check(r["harvestedInDraft"] == 6 and r["harvestSources"] == 6,
      "6 of the 16 lead slots carry authorities harvested from the read sources, one per source (%d from %d sources)" % (r["harvestedInDraft"], r["harvestSources"]))
check(any("6 of 16 harvested" in l for l in r["logs"]), "the log reports the harvested leads actually carried")
check(r["readPromptProbes"], "the read prompt tells readers to probe candidate URLs with probe_sources.py")
check(not r["finalMentionsResearchGaps"], "no research-gap block in Finalize when nothing failed")

print("soft cap is baselined")
r = run("baseline", "200000")
check(r["exitState"] == "complete" and r["counts"]["read"] == 8,
      "200k of output tokens spent earlier in the turn does not trim this run's reads (%s, %s)" % (r["exitState"], r["degradation"]))

print("triage")
r = run("triage-null")
check("threw" not in r and r["exitState"] == "complete" and r["readAgents"] == 8, "a dead triage agent falls back to survey order instead of crashing (%s)" % r.get("threw"))
r = run("triage-dupes")
check(r["readAgents"] == 3 and r["distinctReads"] == 3, "repeated and out-of-range indices are dropped: three distinct reads (%d/%d)" % (r["readAgents"], r["distinctReads"]))

print("dead reader")
r = run("flaky-read")
check(r["readAgents"] == 9 and r["counts"]["read"] == 8 and r["exitState"] == "complete", "a reader that dies once is retried and its source is read")
r = run("dead-read")
check(r["exitState"] == "complete_with_limits" and any("never read" in d for d in r["degradation"]) and r["counts"]["readsFailed"] == 1,
      "a reader that dies twice is a coverage gap (%s)" % r["degradation"])
check(r["firstPickInDraft"] and "UNREAD" in r["firstPickLine"], "the source stays in the draft's findings as an unread lead (%s)" % r["firstPickLine"])
check(r["finalMentionsResearchGaps"] and "never read" in r["researchGaps"], "Finalize is told, for the Limits section")

print("dead survey vector")
r = run("dead-survey")
check(r["surveyAgents"] == 5 and r["exitState"] == "complete_with_limits" and r["counts"]["surveyLanesFailed"] == 1,
      "a vector that dies twice (one retry) is a coverage gap (%s)" % r["degradation"])
check('search vector "v1" did not run' in r["researchGaps"], "Finalize is told which vector did not run")

print("deep: refuted authority")
r = run("refuted")
check("[unverified | direct-full-text | tier: refuted (3-voter refutation panel)]" in r["citeCheck"] and "tier: verified" not in r["citeCheck"].split("\n")[1],
      "a refuted authority is labelled refuted, not verified")

print("deep: voters differ on treatment")
r = run("treatment")
check("OVERRULED by Omega v. Psi" in r["citeCheck"] and "VOTERS REPORT DIFFERENT TREATMENT" in r["citeCheck"],
      "the adverse-reading voter's overruling reaches Finalize beside the other voter's 'none found'")
check(r["exitState"] == "complete_with_limits" and r["counts"]["panelTreatmentSplits"] == 1, "the split is counted and the run is not plain complete")

print("deep: citation correction")
r = run("correction")
check("[verified |" in r["citeCheck"].split("\n")[1] and "-> Alpha v. Beta, 505" not in r["citeCheck"] and "PROPOSED CORRECTION NOT ADOPTED (voter #2 of 3): Alpha v. Beta, 505 U.S. 100 (1992)" in r["citeCheck"],
      "one voter's correction is disclosed, not applied")
check(r["counts"]["corrected"] == 0 and r["counts"]["panelDisputedCorrections"] == 1 and r["exitState"] == "complete_with_limits", "counted as a disputed correction")
r = run("correction-majority")
check("[needs-correction | direct-full-text | tier: corrected (3-voter refutation panel)]" in r["citeCheck"] and "-> Alpha v. Beta, 500 U.S. 1 (1992)" in r["citeCheck"] and r["counts"]["corrected"] == 1,
      "two voters proposing the same correction (punctuation aside) carry it")

print("cite-check verdict under a foreign index")
r = run("foreign-index")
line9 = [l for l in r["citeCheck"].split("\n") if "Filler9 v. Other" in l]
check(len(line9) == 1 and line9[0].startswith("- [unverified"), "authority 9 keeps the verdict of the checker it was given to (%s)" % (line9[0][:60] if line9 else "missing"))
check(r["counts"]["unverified"] == 1 and r["counts"]["verified"] == 9, "counts follow (%s)" % {k: r["counts"][k] for k in ("verified", "unverified")})

print("source read this run")
r = run("was-read")
line = [l for l in r["citeCheck"].split("\n") if "Case v1-1" in l][0]
check("| authoritative-reproduction |" in line and "direct-full-text" not in line and "research read" in line,
      "basis is the reproduction floor with a note, not direct-full-text (%s)" % line[:70])

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
