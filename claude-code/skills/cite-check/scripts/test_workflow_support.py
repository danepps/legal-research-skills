#!/usr/bin/env python3
"""Offline test of cite-check.workflow.js's proposition-support accounting (Codex review,
2026-10-25, items 1-4). Builds a markdown fixture, runs the deterministic prep scripts, then
drives the workflow through scripts/workflow_harness.mjs with stubbed agents under named
scenarios and checks what reaches the findings, the ledger, the counts and the export:

  * an adverse verdict the second checker did not re-derive (budget, dead reviewer) is never
    a finding: it is excluded from the items, counted as not re-derived, and the ledger
    records the instance as support-unverifiable;
  * an agent result without evidence (no passage, citation-only basis, wrong source key, an
    out-of-scope id, an invented claim) is never counted as a completed read;
  * a reviewer's downgrade to supported_qualified stays reported and counted as qualified;
    a retraction ends as supported in the ledger;
  * the findings export lists what was read, so a later diff can tell resolved from not
    rechecked per item;
  * (2026-10-27) the gates PROJECT cost (agents x per-kind cost in the completion
    notification's unit, returned as `spend`): a phase whose projection would pass the cap
    degrades before launching and discloses every unit it did not read; the Zotero pre-lookup
    (`zoteroHits`) settles matched sources without an agent and tells every agent, per source,
    whether its text is on disk or it is not in Zotero at all.

Needs node (the workflow is JavaScript). Skips, with exit 0, when node is absent.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW = os.path.join(os.path.dirname(HERE), "cite-check.workflow.js")
HARNESS = os.path.join(HERE, "workflow_harness.mjs")

DRAFT = """Courts have long held that "the power to tax involves the power to destroy" when applied to federal instrumentalities.[^1] The Court reaffirmed the principle two decades later.[^2] Scholars have disagreed[^3] about its scope, and some have gone further.[^4] Finally, a point with no page.[^5]

[^1]: McCulloch v. Maryland, 17 U.S. (4 Wheat.) 316, 431 (1819).
[^2]: See id. at 436; see also Marbury v. Madison, 5 U.S. (1 Cranch) 137, 177 (1803) (holding that it is emphatically the province of the judiciary to say what the law is).
[^3]: Jane Doe, The Taxing Power Reconsidered, 110 Harv. L. Rev. 815, 820 (1997); but see John Roe, Federalism and Finance 45 (2d ed. 2010).
[^4]: Cf. 42 U.S.C. § 1983; see generally Doe, supra note 3, at 822.
[^5]: Roe, supra note 3.
"""

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: workflow harness test skipped")
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
    support = json.loads(run_script("prepare_support_units.py", ex, "--compact"))
    data = json.load(open(ex, encoding="utf-8"))
    args = {
        "skillsDir": os.path.dirname(os.path.dirname(HERE)), "extractPath": ex, "draftName": "d",
        "footnoteCount": data["footnote_count"], "unitCount": units["unit_count"], "unitNotes": units["unit_notes"],
        "caseCites": data["unique_case_cites"], "supraProblems": data["supra_problem_candidates"],
        "formChecks": data["form_checks"], "ledger": ledger["instances"], "secondaryCites": ledger["secondary"],
        "unitIds": None, "deep": False, "history": True, "zotero": False,
        "support": True, "supportUnits": support["units"], "supportScope": "pincited",
    }
    ap = os.path.join(td, "args.json")
    json.dump(args, open(ap, "w"))

    def run(scenario, extra=None):
        path = ap
        if extra:
            a2 = dict(args, **extra)
            path = os.path.join(td, "args-%s.json" % scenario)
            json.dump(a2, open(path, "w"))
        p = subprocess.run([node, HARNESS, WORKFLOW, path, scenario], capture_output=True, text=True)
        if p.returncode != 0:
            print(p.stderr[-2000:])
            raise SystemExit("harness failed for scenario %s" % scenario)
        return json.loads(p.stdout.strip().splitlines()[-1])

    in_scope = [u for u in support["units"] if u["scope"] == "pincited"]
    check(len(in_scope) == 6 and sum(u["scope"] == "whole-work" for u in support["units"]) == 1,
          "fixture: 6 pincited support units + 1 whole-work (got %d/%d)" % (len(in_scope), len(support["units"])))

    print("baseline")
    r = run("baseline")
    s = r["support"]
    check("Support" in r["phases"] and s["ran"] is True, "support phase ran")
    check(s["unitsChecked"] == 6 and s["supported"] == 6 and s["rejected"] == 0 and s["unauditedAdverse"] == 0, "all six in-scope units read and supported (%s)" % s)
    check(all(v == "supported" for k, v in r["ledger"].items() if k.split(":")[0] in ("2", "3", "4")) , "ledger: the unquoted instances in n.2-4 are 'supported' (%s)" % r["ledger"])
    check(len(r["exported"]["read"]) == 6 and r["exported"]["complete"] is True, "export lists the six read units and is complete")
    sp = r["spend"]
    check(sp["agents"] == len(r["agents"]) and sp["measured"] == 3000 * len(r["agents"]), "spend: agents and tokens measured for the run (%s)" % {k: sp[k] for k in ("agents", "measured", "perAgent")})
    check(sp["byPhase"].get("Support", {}).get("agents") == 2 and sp["byPhase"].get("Verify", {}).get("agents") == 1, "spend: per-phase agent counts (%s)" % {k: v["agents"] for k, v in sp["byPhase"].items()})
    check(sum(v["tokens"] for v in sp["byPhase"].values()) == sp["measured"], "spend: per-phase tokens sum to the run total")
    check(sp["softCap"] == 7_000_000 and sp["hardCeiling"] is False, "spend: soft cap 4M + 3M for support (input-equivalent tokens), no hard ceiling")
    cm = sp["costModel"]
    kind = lambda L: "segment" if L.startswith("segment") else "existWeb" if L.startswith("exist-secondary") else "exist" if L.startswith("exist") else "history" if L.startswith("history") else "verifyTail" if L.startswith("verify-tail") else "verify" if L.startswith("verify") else "supportTail" if L.startswith("support-tail") else "support" if L.startswith("support") else "reverify" if L.startswith("re-verify") else "form" if L == "Form" else "report" if L == "Report" else "verify"
    expected = sum(cm[kind(L)] for L in r["agents"])
    check(sp["projected"] == expected and sp["perAgent"] == round(expected / len(r["agents"])), "spend: projected cost = cost model summed over the agents launched (%s)" % {k: sp[k] for k in ("projected", "perAgent")})
    check(sum(v["projected"] for v in sp["byPhase"].values()) == sp["projected"], "spend: per-phase projections sum to the run total")
    check("input-equivalent tokens" in sp["unit"] and "peak context" in sp["unit"], "spend: the unit is named and the notification figure explained")

    print("adverse, audited")
    r = run("adverse")
    s = r["support"]
    check(s["notSupported"] == 1 and s["contradicted"] == 1 and s["unauditedAdverse"] == 0, "two adverse verdicts, both re-derived (%s)" % {k: s[k] for k in ("notSupported", "contradicted", "unauditedAdverse")})
    check(sorted(i[1] for i in r["items"]) == ["contradicted", "not_supported"], "both reach the findings items")
    check(sorted(v for v in r["ledger"].values() if v.startswith("support-")) == ["support-finding", "support-finding"], "ledger: two support-finding instances")

    print("adverse, re-verify skipped for budget (Codex item 1)")
    r = run("budget-tight", {"costModel": {"reverify": 5_000_000}})
    s = r["support"]
    check(any("re-verify skipped" in d for d in r["degradation"]), "degradation records the skipped audit")
    check(s["notSupported"] == 0 and s["contradicted"] == 0 and s["unauditedAdverse"] == 2, "unaudited adverse verdicts are NOT counted as findings (%s)" % {k: s[k] for k in ("notSupported", "contradicted", "unauditedAdverse")})
    check(r["items"] == [], "no support finding items exported")
    check(all(f["unaudited"] for f in r["findings"] if f["verdict"] in ("not_supported", "contradicted")), "the verdicts carry the unaudited flag")
    check("support-finding" not in r["ledger"].values() and list(r["ledger"].values()).count("support-unverifiable") == 2, "ledger: unaudited adverse instances are support-unverifiable, never support-finding (%s)" % r["ledger"])
    check(len(r["exported"]["read"]) == 4, "export: only the four audited/non-adverse reads count as read")

    print("adverse, reviewer returns nothing")
    r = run("lost-reviewer")
    s = r["support"]
    check(s["unauditedAdverse"] == 2 and s["notSupported"] == 0 and s["contradicted"] == 0 and r["items"] == [], "a lost reviewer leaves the adverse verdicts unaudited and out of the findings")

    print("agent results without evidence (Codex item 2)")
    r = run("bad-results")
    s = r["support"]
    by_id = {f["id"]: f for f in r["findings"]}
    check(s["rejected"] >= 4, "rejected results are counted (%d)" % s["rejected"])
    check(by_id[0]["rejected"] and by_id[0]["verdict"] == "unverifiable", "no passage -> rejected, unverifiable")
    check(by_id[1]["rejected"] and by_id[1]["verdict"] == "unverifiable", "citation-only basis -> rejected, unverifiable")
    check(by_id[3]["rejected"] and by_id[3]["verdict"] == "unverifiable", "adverse verdict without a search -> rejected, unverifiable")
    check(999 not in by_id, "an out-of-scope / unknown id never becomes a finding")
    check(not by_id[2]["rejected"] and by_id[2]["claimNote"] and "invented" not in by_id[2]["claim"], "an invented claim is replaced by the unit's own anchor and noted")
    rejected_ids = {f["id"] for f in r["findings"] if f["rejected"]}
    check(rejected_ids == {0, 1, 3}, "exactly the three evidence-less results are rejected (%s)" % sorted(rejected_ids))
    check(s["unitsChecked"] == 3 and all(f["verdict"] == "unverifiable" for f in r["findings"] if f["rejected"]),
          "rejected results are not counted as checked (checked=%d of 6)" % s["unitsChecked"])
    check(r["exported"]["complete"] is False, "export is not complete when results were rejected")

    print("reviewer downgrades contradicted to qualified (Codex item 3)")
    r = run("downgrade")
    s = r["support"]
    f0 = next(f for f in r["findings"] if f["id"] == 0)
    check(f0["verdict"] == "supported_qualified" and f0["first"] == "contradicted" and not f0["artifact"], "final verdict supported_qualified, first verdict kept, not an artifact")
    check(s["qualified"] == 1 and s["contradicted"] == 0 and s["artifactsCaught"] == 0, "counted as qualified, not as supported or artifact (%s)" % {k: s[k] for k in ("qualified", "contradicted", "artifactsCaught", "supported")})
    check(r["ledger"]["2:1"] == "supported", "ledger: the instance is 'supported' (qualified support)")
    check(r["items"] == [], "qualified support is advisory, not a finding item")

    print("reviewer retracts contradicted (supported)")
    r = run("retracted")
    s = r["support"]
    f0 = next(f for f in r["findings"] if f["id"] == 0)
    check(f0["artifact"] and f0["verdict"] == "supported", "retraction is an artifact with final verdict supported")
    check(s["artifactsCaught"] == 1 and s["supported"] == 6 and r["ledger"]["2:1"] == "supported", "retracted finding counted and recorded as supported in the ledger")
    check(any(e["claim"] == f0["claim"] for e in r["exported"]["read"]), "a retracted finding's unit still counts as read in the export")

    print("support projection exceeds the cap: the ladder degrades BEFORE launching (2026-10-27)")
    # Gates project by cost model (agents x per-kind cost in the completion notification's unit),
    # so a phase that passes its gate completes; one that would not fit degrades up front, with
    # every skipped unit disclosed. Here the dedicated support pass would cost 500k + 3 x 167k
    # against ~850k left, so the ladder drops the secondary sources and keeps the case.
    r = run("baseline", {"costModel": {"support": 4_000_000, "supportTail": 4_000_000}})
    s = r["support"]
    check(r["spend"]["byPhase"]["Support"]["agents"] == 1, "one support agent launched, for the case kept (%d)" % r["spend"]["byPhase"]["Support"]["agents"])
    check(any("secondary source(s) not read (budget)" in d for d in r["degradation"]), "degradation names the ladder step (%s)" % r["degradation"])
    check(s["unitsChecked"] == 2 and s["unread"] >= 4, "only the folded McCulloch unit and the Marbury unit are read; the rest unread, not checked (%s)" % {k: s[k] for k in ("unitsChecked", "unread", "supported")})
    check(r["exported"]["complete"] is False, "export is not complete when units were skipped for budget")
    check(r["exitState"] == "complete_with_limits", "exit state discloses the limit")
    check(not any("agent failure" in d for d in r["degradation"]), "budget skips are never reported as agent failures")
    check(r["spend"]["projected"] <= r["spend"]["softCap"], "the projection never exceeds the cap (%d of %d)" % (r["spend"]["projected"], r["spend"]["softCap"]))

    print("Zotero pre-lookup joined to the run (2026-10-27)")
    doe_txt = os.path.join(td, "zotero-DOE1.txt")
    open(doe_txt, "w").write("page 815\fpage 816\f")
    hits = {"110 harv l rev 815": {"lib": "zotero", "item": "DOE1", "title": "The Taxing Power Reconsidered", "au": ["Doe"], "year": "1997",
                                   "vol": "110", "pp": "815-870", "text": doe_txt, "pages": 2, "src": "pdf", "first": "815",
                                   "confirm": ["confirm: draft year 1997 vs Zotero record 1998"]}}
    r = run("baseline", {"zotero": True, "zoteroHits": hits, "zoteroLookupPath": os.path.join(td, "zotero_lookup.json")})
    labels = r["agents"]
    check("exist-secondary:2" in labels and "exist-secondary:3" not in labels, "the matched source never reaches an existence agent (batch of 2, not 3): %s" % [l for l in labels if l.startswith("exist")])
    doe = [e for e in r["secondaryExistence"] if e["key"] == "110 harv l rev 815"]
    check(len(doe) == 1 and doe[0]["exists"] is True and doe[0]["basis"] == "zotero" and "confirm: draft year 1997" in doe[0]["note"], "its existence is settled deterministically with the record as basis and the difference as a confirm note (%s)" % (doe[0] if doe else None))
    pr = {p["label"]: p for p in r["prompts"]}
    sup = [p for p in r["prompts"] if p["label"].startswith("support:")][0]
    check(sup["textOnDisk"] == doe_txt and not sup["hasCostOpt"] and sup["toolCap"] == 8, "the support agent for the matched source is told its text is on disk and gets the tighter tool cap; the cost kind never reaches agent() (%s)" % {k: sup[k] for k in ("textOnDisk", "hasCostOpt", "toolCap")})
    tail = [p for p in r["prompts"] if p["label"].startswith("support-tail")][0]
    check(tail["saysNotInZotero"], "unmatched sources are told they are not in Zotero")
    check(not any(p["mentionsZoteroTool"] for p in r["prompts"]), "no agent prompt names a Zotero MCP tool")
    check(r["spend"]["byPhase"]["Support"]["projected"] == r["spend"]["costModel"]["supportZotero"] + r["spend"]["costModel"]["supportTail"], "support projection uses the Zotero rate for the matched source (%s)" % r["spend"]["byPhase"]["Support"])
    check(r["support"]["unitsChecked"] == 6, "all six in-scope units still read")
    # the draft cites a short title; the record carries a subtitle and sits under a different key
    hits2 = {"orphan-key": dict(hits["110 harv l rev 815"], title="The Taxing Power Reconsidered: A Subtitle the Draft Omits")}
    r = run("baseline", {"zotero": True, "zoteroHits": hits2, "zoteroLookupPath": os.path.join(td, "zotero_lookup.json")})
    sup = [p for p in r["prompts"] if p["label"].startswith("support:")][0]
    check(sup["textOnDisk"] == doe_txt, "a record with a subtitle is joined by its main title + author when the keys differ")

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
