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
    rechecked per item.

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

    def run(scenario):
        p = subprocess.run([node, HARNESS, WORKFLOW, ap, scenario], capture_output=True, text=True)
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

    print("adverse, audited")
    r = run("adverse")
    s = r["support"]
    check(s["notSupported"] == 1 and s["contradicted"] == 1 and s["unauditedAdverse"] == 0, "two adverse verdicts, both re-derived (%s)" % {k: s[k] for k in ("notSupported", "contradicted", "unauditedAdverse")})
    check(sorted(i[1] for i in r["items"]) == ["contradicted", "not_supported"], "both reach the findings items")
    check(sorted(v for v in r["ledger"].values() if v.startswith("support-")) == ["support-finding", "support-finding"], "ledger: two support-finding instances")

    print("adverse, re-verify skipped for budget (Codex item 1)")
    r = run("budget-tight")
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

print("\n%s" % ("all tests passed" if not fails else "%d FAILED" % fails))
sys.exit(1 if fails else 0)
