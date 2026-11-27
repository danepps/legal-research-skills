#!/usr/bin/env python3
"""Offline check that legal-research.workflow.js refuses unusable arguments before any agent
runs (2026-11-23, 1.6.11).

Until 1.6.11 the script replaced arguments it could not parse with none and ran the whole
pipeline on a placeholder question. Runs the script under a stub that counts agent calls and
stops at the first one, and asserts that:

  * a string that is not valid JSON, missing arguments, a missing or blank question, a mode or
    outputStyle outside the allowed values, and a non-string where a string belongs each stop
    the script with a message naming the problem, with no agent started;
  * an object, and a string that parses, both get past the check and reach the first agent.
  * the deep switch is on for true and the string 'true' only; the string 'false' used to turn
    it on.
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
WORKFLOW = HERE / "legal-research.workflow.js"

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.env.LR_WORKFLOW, 'utf8').replace(/^export const meta/m, 'const meta');
const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', `return (async () => { ${src} })()`);
let agents = 0;
const REACHED = 'reached the first agent';
const agent = async () => { agents++; throw new Error(REACHED); };
const parallel = async (fns) => Promise.all(fns.map((f) => f()));
const pipeline = async (items, ...stages) => { for (const it of items) { let v = it; for (const s of stages) v = await s(v, it, 0); } return []; };
const budget = { total: null, spent: () => 0, remaining: () => Infinity };
const spec = JSON.parse(process.env.LR_ARGS);
const args = spec.kind === 'undefined' ? undefined : spec.value;
fn(args, budget, agent, parallel, () => {}, () => {}, pipeline).then(
  () => console.log(JSON.stringify({ agents, message: 'returned' })),
  (err) => console.log(JSON.stringify({ agents, message: String(err && err.message) })));
"""

GOOD = {"skillsDir": "/s", "question": "Is entrapment a jury question?", "mode": "caselaw",
        "outputStyle": "practitioner", "jurisdiction": "federal", "asOfDate": "2026-11-23", "notes": "", "deep": False}

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: legal-research arguments test skipped")
    sys.exit(0)


def run(value=None, kind="value"):
    env = dict(os.environ, LR_WORKFLOW=str(WORKFLOW), LR_ARGS=json.dumps({"kind": kind, "value": value}))
    p = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("node failed")
    return json.loads(p.stdout.strip().splitlines()[-1])


def refused(r, needle):
    return r["agents"] == 0 and r["message"].startswith("legal-research workflow:") and needle in r["message"] and "No agent was started" in r["message"]


def passed(r):
    return r["agents"] >= 1 and not r["message"].startswith("legal-research workflow:")


print("usable arguments get past the check")
check(passed(run(GOOD)), "an object reaches the first agent")
check(passed(run(json.dumps(GOOD))), "a string that parses is accepted")
check(passed(run({"question": "Q"})), "only the question is required")
check(passed(run(dict(GOOD, mode="BOTH", outputStyle="Academic"))), "mode and outputStyle are matched without regard to case")

print("a string that is not valid JSON stops the script")
good = json.dumps(GOOD, separators=(",", ":"))
check(refused(run(good + '"deep":false}'), "not valid JSON"), "a repeated fragment is refused with no agent started")
check(refused(run("research this"), "not valid JSON"), "free text is refused")

print("missing or misshapen arguments stop the script")
check(refused(run(kind="undefined"), "args is missing"), "no arguments")
check(refused(run({}), "question"), "an empty object: question named")
check(refused(run([GOOD]), "not an object"), "a list in place of the object")
check(refused(run(dict(GOOD, question="   ")), "question"), "a blank question")
check(refused(run(dict(GOOD, question=["Q"])), "question"), "a question that is not a string")
check(refused(run(dict(GOOD, mode="everything")), "mode must be"), "an unknown mode")
check(refused(run(dict(GOOD, outputStyle="memo")), "outputStyle must be"), "an unknown outputStyle")
check(refused(run(dict(GOOD, notes={"a": 1})), "notes must be a string"), "notes as an object")
r = run({"mode": "x", "jurisdiction": 3})
check(refused(r, "question") and "mode must be" in r["message"] and "jurisdiction must be a string" in r["message"], "every problem is named at once")

print("the deep switch passed as a string")
HARNESS = HERE / "workflow_harness.mjs"


def harness_exit(deep):
    p = subprocess.run([node, str(HARNESS), str(WORKFLOW), "baseline", "0", json.dumps({"deep": deep})], capture_output=True, text=True)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("harness failed")
    return json.loads(p.stdout.strip().splitlines()[-1])["exitState"]


# The baseline stubs answer no deep-mode agent, so a deep run ends with limits and a lean run
# does not: the exit state shows which mode the script chose.
lean, deep_on = harness_exit(False), harness_exit(True)
check(lean != deep_on, "the stubbed run tells lean from deep (%s, %s)" % (lean, deep_on))
check(harness_exit("false") == lean, "deep:'false' is lean, not deep")
check(harness_exit("true") == deep_on, "deep:'true' is deep")

print("scratchDir (the folder for the agents' temporary files)")
check(passed(run(dict(GOOD, scratchDir="/runs/r 1/work/.tmp"))), "an absolute path, spaces included, is accepted")
for bad, why in (("runs/r1", "a relative path"), ("/", "the root alone"), ("/a/$HOME/b", "a dollar sign"), ('/a/"b', "a double quote"),
                 ("/a/`b`", "a backtick"), ("/a\\b", "a backslash"), ("/a\nb", "a line break"), (7, "a number")):
    check(refused(run(dict(GOOD, scratchDir=bad)), "scratchDir must be the absolute path of a folder"), "refused: " + why)

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
