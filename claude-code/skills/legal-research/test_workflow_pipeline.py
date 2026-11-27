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

And the 2026-11-16 change, Finalize as edits:

  * no agent retypes the memo: the result is the draft with the returned edits applied and the
    two appendix sections placed after it, and text no edit names is byte-for-byte the draft's;
  * the Finalize model is whatever args.finalizeModel says and the session model when it is not
    passed (nothing is hard-coded), and Scope and Draft never take the override;
  * with finalizeModel set, a load-bearing authority that failed verification, negative treatment
    of one, and a gap-fill authority each call in the session model for one revision pass before
    Finalize, which is then told not to redo that work; with nothing of the kind there is no
    call-in; args.escalate:false and a dead call-in both leave the items to Finalize;
  * an edit that misquotes the memo gets one repair round; one that still cannot be placed is
    disclosed in the memo, returned in finalize.unappliedEdits, and keeps the run from ending
    "complete"; whitespace and quote-style differences are tolerated; an ambiguous find text is
    refused unless all:true; an edit that would gut the memo is discarded;
  * the deep calibration pass returns edits too.
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


def run(scenario, spent="0", extra=None):
    p = subprocess.run([node, str(HARNESS), str(WORKFLOW), scenario, spent, json.dumps(extra or {})], capture_output=True, text=True)
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
# Second live run, 2026-11-16: four of eight read opinions lost the tag because the reader's
# citation carried a pincite, a parallel cite or a parenthetical that the draft's did not.
r = run("was-read+read-pin")
line = [l for l in r["citeCheck"].split("\n") if "Case v1-1" in l][0]
check("| authoritative-reproduction |" in line and "research read" in line,
      "a reader's pincite, parallel cite and parenthetical do not lose the read tag (%s)" % line[:70])
r = run("was-read+read-other")
line = [l for l in r["citeCheck"].split("\n") if "Case v1-1" in l][0]
check("| citation-only |" in line and "research read" not in line, "a different case in the same volume does not gain it (%s)" % line[:70])

OPUS = {"finalizeModel": "opus"}
CAVEAT = "reportedly controls, but that could not be independently confirmed."

print("finalize as edits: the memo is the draft plus edits plus the appendices")
r = run("baseline")
draft, memo = r["draft"], r["memo"]
check("is to the same effect (checked)." in memo and "is to the same effect." not in memo, "the returned edit is applied")
untouched = [l for l in draft.split("\n") if "same effect" not in l]
check(all(l in memo.split("\n") for l in untouched), "every line no edit names is the draft's own, unchanged")
check(memo.index("## Conclusion") < memo.index("## Table of Authorities") < memo.index("## Limits of this research") and memo.endswith("Open-web sources only.\n"),
      "the Table of Authorities and Limits sections follow the memo's last line, in that order")
check(r["finalHasEditRules"] and "Return the final memo" not in r["finalMemoSection"], "Finalize is told to return edits, not the memo")
check(r["counts"]["editsApplied"] == 1 and r["counts"]["editsUnapplied"] == 0 and r["exitState"] == "complete", "counted; a clean run is still complete")

print("finalize model")
check(r["optsByLabel"]["Finalize"].get("model") is None and r["finalize"]["model"] == "session model" and r["finalize"]["callIn"].startswith("not applicable"),
      "with no finalizeModel, Finalize inherits the session model and there is no call-in")
r = run("baseline", extra=OPUS)
check(r["optsByLabel"]["Finalize"].get("model") == "opus" and r["finalize"]["model"] == "opus", "finalizeModel reaches the Finalize call")
check(r["optsByLabel"]["Scope"].get("model") is None and r["optsByLabel"]["Draft"].get("model") is None, "Scope and Draft never take the override")
check(r["finalize"]["callIn"] == "not needed" and "finalize:revise" not in r["labels"], "nothing substantive in the cite-check results: no call-in")
r = run("baseline", extra={"finalizeModel": "sonnet"})
check(r["optsByLabel"]["Finalize"].get("model") == "sonnet", "the model is whatever the skill passes; none is hard-coded")

print("call-in: a load-bearing authority fails verification")
r = run("refuted", extra=OPUS)
check(r["labels"].count("finalize:revise") == 1 and r["optsByLabel"]["finalize:revise"].get("model") is None and r["finalize"]["callIn"] == "ran",
      "one revision call, on the session model (no override)")
check("FAILED VERIFICATION" in r["revisePrompt"] and "Alpha v. Beta, 500 U.S. 1 (1991)" in r["revisePrompt"].split("=== ITEMS ===")[1].split("=== MEMO ===")[0]
      and "Gamma v. Delta" not in r["revisePrompt"].split("=== ITEMS ===")[1].split("=== MEMO ===")[0],
      "it is given the failed load-bearing authority and not the ordinary one")
check(CAVEAT in r["memo"] and CAVEAT in r["finalMemoSection"], "its edit is applied before Finalize, which reads the revised memo")
check(r["finalHasAlreadyRevised"] and r["labels"].index("finalize:revise") < r["labels"].index("Finalize"), "Finalize runs after it and is told not to redo that authority")
check(r["finalize"]["callInAuthorities"] == [{"citation": "Alpha v. Beta, 500 U.S. 1 (1991)", "reasons": ["load-bearing authority that FAILED VERIFICATION"]}], "the result names the authority and the reason")
r = run("refuted")
check("finalize:revise" not in r["labels"] and not r["finalHasAlreadyRevised"], "without finalizeModel the same run has no call-in: Finalize is already the session model")
r = run("refuted", extra={"finalizeModel": "opus", "escalate": False})
check("finalize:revise" not in r["labels"] and r["finalize"]["callIn"].startswith("off") and not r["finalHasAlreadyRevised"], "escalate:false leaves the item to Finalize")
r = run("refuted+revise-dead", extra=OPUS)
check(r["labels"].count("finalize:revise") == 2 and r["finalize"]["callIn"].startswith("failed") and not r["finalHasAlreadyRevised"] and CAVEAT not in r["memo"],
      "a call-in that dies twice is reported, and Finalize applies the items itself (%s)" % r["finalize"]["callIn"])

print("call-in: negative treatment, and its absence")
r = run("treatment", extra=OPUS)
check(r["finalize"]["callIn"] == "ran" and "NEGATIVE TREATMENT" in r["revisePrompt"], "one voter's overruling of a load-bearing authority calls in the session model")
r = run("correction-majority", extra=OPUS)
check(r["finalize"]["callIn"] == "not needed", "a corrected citation alone is clerical: no call-in")

print("call-in: gap-fill authorities")
r = run("gapfill", extra=OPUS)
check(r["finalize"]["callIn"] == "ran" and "POST-DRAFT ADDITION" in r["revisePrompt"] and "Needed v. Case, 502 U.S. 3 (1993)" in r["revisePrompt"],
      "an authority retrieved after drafting is woven in by the session model")
check(not r["finalHasPostDraftBullet"] and r["finalHasAlreadyRevised"], "Finalize is not asked to weave it in again")
r = run("gapfill")
check(r["finalHasPostDraftBullet"] and "finalize:revise" not in r["labels"], "without finalizeModel, Finalize weaves it in as before")
check(r["finalHasWeaveRule"], "... and is told to carry it through tables, counts and footnotes")
check("[read this run by a research agent | cite-check: verified]" in r["finalPostDraftSection"], "the addition is listed as a source the run read")

# First live run, 2026-11-16: two gap-fill opinions were added beside tables, counts and a title
# that still described the original eight, and a third, which the gap-fill agent had read in the
# official slip opinion, was called an unread candidate because the checker skipped it.
print("gap-fill: weaving rule, and an addition the cite-check did not confirm")
r = run("gapfill", extra=OPUS)
rp = r["revisePrompt"]
check("* TABLES:" in rp and "* COUNTS:" in rp and "* CITATION STYLE:" in rp and "* NOT CONFIRMED:" in rp, "the call-in is told to carry an addition through tables, counts and footnotes")
check("never describe one as unread" in rp and "Read this run: a research agent opened this source" in rp, "... and that the run read it")
check("The one exception is a" in rp, "... as the stated exception to the lightest-change rule")
r = run("gapfill+gapfill-unverified", extra=OPUS)
reasons = [x for a in r["finalize"]["callInAuthorities"] for x in a["reasons"]]
check(r["finalize"]["callIn"] == "ran" and "POST-DRAFT ADDITION that the cite-check did NOT confirm" in reasons, "an unconfirmed gap-fill authority still goes to the call-in")
check(r["counts"]["unverified"] == 1 and "checked — could not be confirmed (a research agent read the source this run)] Needed v. Case" in r["citeCheck"],
      "it stays unverified, and its label says the run read it")
check(r["finalHasAlreadyRevised"] and not r["finalHasPostDraftBullet"], "Finalize is told it was already handled")
r = run("gapfill+gapfill-unverified")
check("finalize:revise" not in r["labels"] and r["finalHasWeaveRule"] and "[read this run by a research agent | cite-check: unverified]" in r["finalPostDraftSection"],
      "without finalizeModel, Finalize gets the same rule and the same facts")
r = run("gapfill+gapfill-skipped", extra=OPUS)
reasons = [x for a in r["finalize"]["callInAuthorities"] for x in a["reasons"]]
line = next((l for l in r["citeCheck"].splitlines() if "Needed v. Case" in l), "")
check(r["counts"]["unverified"] == 0 and line.startswith("- [verified | authoritative-reproduction |"), "a check the checker skipped is not recorded as a check that failed")
check("the cite-checker reported running no check of its own" in line and "basis rests on this run's research read" in line, "... and the note says whose read the basis rests on")
check("POST-DRAFT ADDITION to weave in" in reasons, "... so it is woven in like any other addition")
r = run("unread-skipped")
line = next((l for l in r["citeCheck"].splitlines() if "Gamma v. Delta" in l), "")
check(r["counts"]["unverified"] == 1 and line.startswith("- [unverified |"), "examined=false does not rescue an authority the run never read")

print("edits that do not match")
r = run("edit-miss")
check(any(l.startswith("finalize:repair") for l in r["labels"]) and "is reportedly to the same effect." in r["memo"] and r["counts"]["editsUnapplied"] == 0 and r["exitState"] == "complete",
      "a misquoted find text gets one repair round and is then applied")
check("it failed because: the find text does not occur in the memo" in r["repairPrompt"], "the repair round is told why the edit failed")
r = run("edit-miss", extra=OPUS)
check([v.get("model") for k, v in r["optsByLabel"].items() if k.startswith("finalize:repair")] == ["opus"], "the repair round runs on the Finalize model")
r = run("edit-unfixable")
check(r["counts"]["editsUnapplied"] == 1 and r["exitState"] == "complete_with_limits" and any("could not be placed" in d for d in r["degradation"]),
      "an edit that still cannot be placed keeps the run from ending complete (%s)" % r["exitState"])
check("**Changes not made automatically.**" in r["memo"] and "- caveat Gamma" in r["memo"] and r["memo"].index("## Limits of this research") < r["memo"].index("Changes not made automatically"),
      "it is disclosed at the end of the memo's Limits section")
check(len(r["finalize"]["unappliedEdits"]) == 1 and r["finalize"]["unappliedEdits"][0]["pass"] == "finalize" and "is to the same effect." in r["memo"],
      "and returned in finalize.unappliedEdits; the sentence it targeted is unchanged")
r = run("edit-tolerant")
check("held that the rule applies." in r["memo"] and not any(l.startswith("finalize:repair") for l in r["labels"]),
      "a find text that differs only in whitespace and quote style is located without a repair round")
r = run("edit-ambiguous")
check("the find text occurs 2 times" in r["repairPrompt"], "a find text that occurs twice is refused")
check(r["memo"].count("The rule appears settled in the cases reviewed.") == 2 and "The rule is settled." not in r["memo"], "all:true replaces every occurrence")
r = run("edit-shrink")
check(r["memo"].startswith(r["draft"]) and r["exitState"] == "complete_with_limits" and any("discarded" in d for d in r["degradation"]),
      "an edit that would cut the memo by more than 40% is discarded and disclosed")
r = run("no-limits")
check("Finalize agent failed twice" in r.get("threw", ""), "a Finalize result with no Limits section is not accepted")

print("deep: calibration returns edits")
r = run("calibrate")
check("The rule appears settled in the cases reviewed. Alpha v. Beta" in r["finalMemoSection"] and r["optsByLabel"]["calibrate:thesis"].get("model") is None,
      "the calibration edit is applied to the draft before Finalize reads it, on the session model")

print("negative-treatment detector (decides the call-in)")
NEG_JS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const block = src.slice(src.indexOf('const NEGATIVE_SIGNAL'), src.indexOf('// ---- Phase 1: scope'));
eval(block.replace(/const (NEGATIVE_SIGNAL|NEGATOR|hasNegativeTreatment)/g, 'var $1'));
console.log(JSON.stringify(JSON.parse(process.argv[2]).map((t) => hasNegativeTreatment(t))));
"""
FIXTURES = [
    ("OVERRULED by Omega v. Psi, 600 U.S. 9 (2023)", True),
    ("abrogated in part by Smith v. Jones, 599 U.S. 1 (2023); scope unconfirmed", True),
    ("citator: Caution — Doe v. Roe, 12 F.4th 3 (9th Cir. 2021) — distinguished", True),
    ("VOTERS REPORT DIFFERENT TREATMENT: voter 1: no negative treatment found | voter 3: overruled by Omega v. Psi", True),
    ("no negative treatment found. Overruled by Omega v. Psi, 600 U.S. 9 (2023).", True),
    ("overruled in part by Omega v. Psi, which did not reach the second holding", True),
    ("no longer good law after Omega v. Psi", True),
    ("no negative treatment found in the citing probe", False),
    ("citator: no Negative/Caution treatment", False),
    ("has not been overruled or questioned; most recent citing opinion in the CourtListener index: 2024-03-01", False),
    ("most recent citing opinion in the CourtListener index: 2019-06-12", False),
    ("", False),
]
p = subprocess.run([node, "-e", NEG_JS, str(WORKFLOW), json.dumps([f[0] for f in FIXTURES])], capture_output=True, text=True)
got = json.loads(p.stdout) if p.returncode == 0 else []
if p.returncode != 0:
    print(p.stderr[-800:])
for (text, want), g in zip(FIXTURES, got or [None] * len(FIXTURES)):
    check(g == want, "%s: %r" % ("negative" if want else "not negative", text[:70]))

print("temporary files: every agent that can save one is told where, and args.scratchDir moves them all")
FILE_AGENTS = ("Scope", "survey:", "read:", "gapfill", "verify:", "refute:")


def temp_prefixes(r):
    return {t["label"]: t["prefix"] for t in r["tempFiles"] if t["label"].startswith(FILE_AGENTS)}


r = run("gapfill+refuted", extra={"runTag": "t1"})
px = temp_prefixes(r)
kinds = {k for k in FILE_AGENTS if any(l.startswith(k) for l in px)}
check(kinds == set(FILE_AGENTS), "scope, survey, read, gap-fill, verify and refute agents all ran (%s)" % sorted(kinds))
check(all(re.fullmatch(r"/tmp/lr-t1-[A-Za-z0-9-]+-", p) for p in px.values()),
      "with no scratchDir each one's prefix is /tmp/lr-<runTag>-<its own slot>- (%s)" % sorted(set(px.values()))[:3])
readers = [p for l, p in px.items() if l.startswith("read:")]
check(len(readers) == 8 and len(set(readers)) == 8, "the eight readers have eight different prefixes")
check(len(set(px.values())) == len(px), "no two of these agents share a prefix")
check(r["tmpNamed"] > 0, "the /tmp paths are named in the prompts, as before")
DIR = "/Users/a b/Proj/.dubitante/runs/r1/work/.tmp"
r = run("gapfill+refuted", extra={"runTag": "t1", "scratchDir": DIR + "/"})
px2 = temp_prefixes(r)
check(set(px2) == set(px) and all(p == '"%s/%s"' % (DIR, q[len("/tmp/"):]) for (l, p), (l2, q) in zip(sorted(px2.items()), sorted(px.items()))),
      "with scratchDir the same names sit in that folder, double-quoted because the path has a space")
check(r["tmpNamed"] == 0, "and no prompt names a /tmp path of this workflow")
r = run("gapfill+refuted", extra={"runTag": "t1", "scratchDir": "/runs/r1/work/.tmp"})
check(all(p.startswith("/runs/r1/work/.tmp/lr-t1-") for p in temp_prefixes(r).values()) and r["tmpNamed"] == 0, "a plain path is not quoted")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
