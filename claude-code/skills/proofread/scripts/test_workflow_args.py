#!/usr/bin/env python3
"""Offline check that proofread.workflow.js refuses unusable arguments before any agent runs
(2026-11-23, 1.6.10).

The session retypes the workflow's arguments from the extractor's output. In a live run the
lead passed them as a JSON string with a fragment repeated, so the string did not parse; the
script fell back to no arguments at all, sent its agents to /fulltext.txt, and the run failed
after spending tokens. Runs the workflow under stubbed agents (no model, no network) and
asserts that:

  * a string that is not valid JSON, missing arguments, a missing outDir, an empty or
    malformed chunkFiles, and a list or object argument of the wrong shape each stop the
    script with a message that names the problem, with no agent started;
  * an object, and a string that does parse, both run as before.
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
WORKFLOW = HERE.parent / "proofread.workflow.js"

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.env.PR_WORKFLOW, 'utf8').replace(/^export const meta/m, 'const meta');
const AF = Object.getPrototypeOf(async function () {}).constructor;
const run = new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', src);
let agents = 0;
const proofModels = [];
let styleAsked = false;
async function agent(prompt, opts) {
  agents++;
  const L = opts.label || '';
  if (L.startsWith('proof:chunk-')) { proofModels.push(opts.model); if (/severity[^\n]*style|style suggestions/i.test(prompt) && /STYLE PASS IS ON|style:\s*true/i.test(prompt)) styleAsked = true; }
  if (L.startsWith('consistency')) return { findings: [], conventions: [] };
  if (L.startsWith('proof:chunk-')) return { findings: [] };
  if (L.startsWith('verify:batch-')) return { verdicts: [] };
  if (L === 'report') return '# Proofread';
  throw new Error('unstubbed ' + L);
}
const budget = { total: null, spent: () => 0, remaining: () => Infinity };
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)));
const spec = JSON.parse(process.env.PR_ARGS);
const args = spec.kind === 'undefined' ? undefined : spec.value;
run(args, budget, agent, parallel, () => {}, () => {}).then(
  (out) => console.log(JSON.stringify({ ok: true, agents, exitState: out.exitState, chunks: out.counts.chunks, proofModels, findingsKey: Array.isArray(out.findings) })),
  (err) => console.log(JSON.stringify({ ok: false, agents, message: String(err && err.message) })));
"""

GOOD = {"outDir": "/x", "draftName": "d", "chunkFiles": ["/x/c0.json"], "lintFindings": [],
        "counts": {"paragraphs": 300, "footnotes": 0, "words": 1000}, "headings": [],
        "noteParas": {"1": 1}, "formatting": {"available": False}}

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: proofread arguments test skipped")
    sys.exit(0)


def run(value=None, kind="value"):
    env = dict(os.environ, PR_WORKFLOW=str(WORKFLOW), PR_ARGS=json.dumps({"kind": kind, "value": value}))
    p = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("node failed")
    return json.loads(p.stdout.strip().splitlines()[-1])


def refused(r, needle):
    return (not r["ok"]) and r["agents"] == 0 and needle in r["message"] and "No agent was started" in r["message"]


print("usable arguments run as before")
r = run(GOOD)
check(r["ok"] and r["agents"] > 0 and r["chunks"] == 1, "an object runs (%s)" % r)
r = run(json.dumps(GOOD))
check(r["ok"] and r["agents"] > 0 and r["chunks"] == 1, "a string that parses is accepted and runs")
r = run({"outDir": "/x", "chunkFiles": ["/x/c0.json"]})
check(r["ok"], "only outDir and chunkFiles are required")

print("a switch passed as the string 'false' stays off")
r = run(dict(GOOD, fable="false", deep="false", style="false", replacements="false"))
check(r["ok"] and r["proofModels"] == ["opus"], "fable:'false' leaves the proofers on Opus (%s)" % r.get("proofModels"))
r = run(dict(GOOD, fable="true"))
check(r["ok"] and r["proofModels"] == ["fable"], "fable:'true' and fable:true still select it")
r = run(dict(GOOD, fable=True))
check(r["ok"] and r["proofModels"] == ["fable"], "fable:true selects it")

print("a string that is not valid JSON stops the script")
# The shape seen live: the tail of the formatting block repeated after its closing brace.
good = json.dumps(GOOD, separators=(",", ":"))
broken = good.replace('"available":false}', '"available":false}"available":false}', 1)
assert broken != good
r = run(broken)
check(refused(r, "not valid JSON"), "a repeated fragment is refused with no agent started (%s)" % r.get("message", r)[:90])
r = run("not json at all")
check(refused(r, "not valid JSON"), "free text is refused")

print("missing or misshapen arguments stop the script")
check(refused(run(kind="undefined"), "args is missing"), "no arguments")
check(refused(run({}), "outDir"), "an empty object: outDir named")
check(refused(run([GOOD]), "not an object"), "a list in place of the object")
check(refused(run("[1, 2]"), "not an object"), "a string that parses to a list")
check(refused(run(dict(GOOD, outDir="")), "outDir"), "an empty outDir")
check(refused(run({k: v for k, v in GOOD.items() if k != "chunkFiles"}), "chunkFiles"), "no chunkFiles")
check(refused(run(dict(GOOD, chunkFiles=[])), "chunkFiles"), "an empty chunkFiles")
check(refused(run(dict(GOOD, chunkFiles="/x/c0.json")), "chunkFiles"), "chunkFiles as one string")
check(refused(run(dict(GOOD, chunkFiles=["/x/c0.json", 3])), "chunkFiles"), "a chunk path that is not a string")
check(refused(run(dict(GOOD, lintFindings="[]")), "lintFindings must be a list"), "lintFindings as a string")
check(refused(run(dict(GOOD, headings={})), "headings must be a list"), "headings as an object")
check(refused(run(dict(GOOD, counts=[1])), "counts must be an object"), "counts as a list")
check(refused(run(dict(GOOD, formatting="x")), "formatting must be an object"), "formatting as a string")
r = run({"chunkFiles": [], "lintFindings": 3})
check(refused(r, "outDir") and "chunkFiles" in r["message"] and "lintFindings" in r["message"], "every problem is named at once")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
