#!/usr/bin/env python3
"""Offline check that cite-check.workflow.js refuses unusable arguments before any agent runs
(2026-11-23).

The lead session retypes the workflow's arguments from the extraction scripts' output. The
script used to begin `let A = args || {}` and replace a string that did not parse with {}, so a
garbled call ran with no extract, no ledger and no case cites (the proofread workflow failed live
that way and was fixed in 1.6.10). Runs the workflow under stubbed agents (no model, no network)
and asserts that:

  * a string that is not valid JSON, missing arguments, a missing extractPath, a missing count,
    and a list or object argument of the wrong shape each stop the script with a message that
    begins "cite-check workflow:", names every problem, and says no agent was started;
  * an object, and a string that does parse, both run;
  * a switch passed as the string 'false' stays off (deep, support) or turns off (history).
Skipped without node.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKFLOW = HERE.parent / "cite-check.workflow.js"

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.env.CC_WORKFLOW, 'utf8').replace(/^export const meta/m, 'const meta');
const AF = Object.getPrototypeOf(async function () {}).constructor;
const run = new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', src);
let agents = 0;
const labels = [];
async function agent(prompt, opts) {
  agents++;
  const L = opts.label || opts.phase || '';
  labels.push(L);
  if (L.startsWith('exist')) return { results: [] };
  if (L.startsWith('history')) return { cases: [] };
  if (opts.phase === 'Form') return { findings: [], conventions: [] };
  if (opts.phase === 'Report') return { report: '# Cite check' };
  throw new Error('unstubbed ' + L);
}
const budget = { total: 0, spent: () => 0, remaining: () => 1e9 };
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)));
const spec = JSON.parse(process.env.CC_ARGS);
const args = spec.kind === 'undefined' ? undefined : spec.value;
run(args, budget, agent, parallel, () => {}, () => {}).then(
  (out) => console.log(JSON.stringify({ ok: true, agents, labels, exitState: out.exitState, support: out.counts.support.on, historyRan: out.counts.history.ran, softCap: out.spend.softCap })),
  (err) => console.log(JSON.stringify({ ok: false, agents, message: String(err && err.message) })));
"""

# The smallest usable call: a draft with no quotes and no citations still needs every
# required key (SKILL.md step 4), each with its empty value.
GOOD = {"skillsDir": "/x/skills", "extractPath": "/x/extract.json", "draftName": "d",
        "footnoteCount": 0, "unitCount": 0, "caseCites": [], "ledger": [], "secondaryCites": [],
        "supraProblems": [], "formChecks": {}, "unitNotes": [], "unitIds": None,
        "deep": False, "history": True, "support": False, "zotero": False}

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: cite-check arguments test skipped")
    sys.exit(0)


def run(value=None, kind="value"):
    env = dict(os.environ, CC_WORKFLOW=str(WORKFLOW), CC_ARGS=json.dumps({"kind": kind, "value": value}))
    p = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("node failed")
    return json.loads(p.stdout.strip().splitlines()[-1])


def refused(r, needle):
    m = r.get("message", "")
    return (not r["ok"]) and r["agents"] == 0 and m.startswith("cite-check workflow:") and needle in m and "No agent was started" in m


def without(*keys):
    return {k: v for k, v in GOOD.items() if k not in keys}


print("usable arguments run")
r = run(GOOD)
check(r["ok"] and r["agents"] >= 1 and r["exitState"] == "complete", "an object runs (%s)" % r)
r = run(json.dumps(GOOD))
check(r["ok"] and r["agents"] >= 1, "a string that parses is accepted and runs")
r = run(dict(GOOD, footnoteCount="6", unitCount="0"))
check(r["ok"], "counts given as digit strings are accepted")
r = run(without("skillsDir", "draftName", "supraProblems", "formChecks", "unitNotes", "unitIds", "deep", "history", "support", "zotero"))
check(r["ok"], "only extractPath, footnoteCount, unitCount, caseCites, ledger and secondaryCites are required")

print("a switch passed as the string 'false'")
r = run(dict(GOOD, deep="false", support="false", history="false"))
check(r["ok"] and r["support"] is False and r["softCap"] == 4_000_000, "deep:'false' and support:'false' stay off (%s)" % r)
r = run(dict(GOOD, caseCites=["1 U.S. 1"], history="false"))
check(r["ok"] and r["historyRan"] is False and not any(l.startswith("history") for l in r["labels"]), "history:'false' turns the history pass off")
r = run(dict(GOOD, support="true", supportUnits=[]))
check(r["ok"] and r["support"] is True and r["softCap"] == 7_000_000, "support:'true' turns it on")

print("a string that is not valid JSON stops the script")
good = json.dumps(GOOD, separators=(",", ":"))
broken = good.replace('"ledger":[]', '"ledger":[]"ledger":[]', 1)  # a repeated fragment, the shape seen live in proofread
assert broken != good
check(refused(run(broken), "not valid JSON"), "a repeated fragment is refused with no agent started")
check(refused(run("not json at all"), "not valid JSON"), "free text is refused")

print("missing or misshapen arguments stop the script")
check(refused(run(kind="undefined"), "args is missing"), "no arguments")
check(refused(run(None), "args is missing"), "null arguments")
r = run({})
check(refused(r, "extractPath") and all(k in r["message"] for k in ("footnoteCount", "unitCount", "caseCites", "ledger", "secondaryCites")),
      "an empty object: every required argument named")
check(refused(run([GOOD]), "not an object"), "a list in place of the object")
check(refused(run("[1, 2]"), "not an object"), "a string that parses to a list")
check(refused(run(without("extractPath")), "extractPath"), "no extractPath")
check(refused(run(dict(GOOD, extractPath="  ")), "extractPath"), "a blank extractPath")
check(refused(run(without("unitCount")), "unitCount"), "no unitCount (no quote would be checked)")
check(refused(run(dict(GOOD, unitCount=-1)), "unitCount"), "a negative unitCount")
check(refused(run(dict(GOOD, footnoteCount="six")), "footnoteCount"), "a footnoteCount that is not a number")
check(refused(run(without("caseCites")), "caseCites"), "no caseCites (no case would be checked)")
check(refused(run(dict(GOOD, caseCites="287 U.S. 435")), "caseCites"), "caseCites as one string")
check(refused(run(dict(GOOD, caseCites=["287 U.S. 435", 3])), "caseCites"), "a case cite that is not a string")
check(refused(run(without("ledger")), "ledger"), "no ledger (section J would be empty)")
check(refused(run(dict(GOOD, ledger={"instances": []})), "ledger"), "the ledger_args object in place of its instances list")
check(refused(run(dict(GOOD, ledger=["n.1"])), "ledger"), "a ledger entry that is not an object")
check(refused(run(without("secondaryCites")), "secondaryCites"), "no secondaryCites")
check(refused(run(dict(GOOD, support=True)), "supportUnits"), "support on with no supportUnits")
check(refused(run(dict(GOOD, support=True, supportUnits="[]")), "supportUnits"), "supportUnits as a string")
check(refused(run(dict(GOOD, supraProblems={})), "supraProblems"), "supraProblems as an object")
check(refused(run(dict(GOOD, unitIds="1-5")), "unitIds"), "unitIds as a string")
check(refused(run(dict(GOOD, unitNotes=[[0, 1, 2]])), "unitNotes"), "a unitNotes entry that is not a pair")
check(refused(run(dict(GOOD, formChecks=[])), "formChecks must be an object"), "formChecks as a list")
check(refused(run(dict(GOOD, zoteroHits="{}")), "zoteroHits must be an object"), "zoteroHits as a string")
check(refused(run(dict(GOOD, costModel=[1])), "costModel must be an object"), "costModel as a list")
r = run({"extractPath": "/x/e.json", "caseCites": "x", "ledger": 3})
check(refused(r, "caseCites") and "ledger" in r["message"] and "unitCount" in r["message"] and "secondaryCites" in r["message"],
      "every problem is named at once")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
