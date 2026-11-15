#!/usr/bin/env python3
"""Offline check of proofread.workflow.js's verify join (2026-11-15 review).

Runs the workflow under stubbed agents (no model, no network). Two proof chunks raise fourteen
findings, which the verify stage splits into two batches (12 + 2). Asserts:

  * baseline: every finding confirmed, the run ends complete;
  * a verifier that returns a verdict for a finding from the OTHER batch cannot overwrite that
    batch's verdict (verdicts used to be keyed by the echoed id across all batches, last one
    winning, so the second batch's stray "rejected" for finding 0 removed a confirmed finding);
    the stray verdict is dropped and disclosed;
  * a duplicate verdict for the same id does not replace the first.
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
const scenario = process.env.PR_SCENARIO;
const run = new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', src);
const labels = [];
async function agent(prompt, opts) {
  const L = opts.label || '';
  labels.push(L);
  if (L.startsWith('consistency')) return { findings: [], conventions: [] };
  if (L.startsWith('proof:chunk-')) {
    const c = Number(L.split('-')[1]);
    return { findings: Array.from({ length: 7 }, (_, i) => ({ location: `¶${c * 100 + i + 1}`, find: `chunk ${c} wrong phrase number ${i}`, problem: `problem ${c}-${i}`, fix: `fix ${c}-${i}`, severity: 'error', category: 'typo' })) };
  }
  if (L.startsWith('verify:batch-')) {
    const given = [...prompt.matchAll(/"id": (\d+)/g)].map((m) => Number(m[1]));
    const verdicts = given.map((id) => ({ id, verdict: 'confirmed', note: 're-read' }));
    if (scenario === 'foreign' && given.includes(12)) verdicts.push({ id: 0, verdict: 'rejected', note: 'a finding this verifier was never shown' });
    if (scenario === 'duplicate' && given.includes(0)) verdicts.push({ id: 0, verdict: 'rejected', note: 'second verdict for the same id' });
    return { verdicts };
  }
  if (L === 'report') return '# Proofread';
  throw new Error('unstubbed ' + L);
}
const budget = { total: null, spent: () => 0, remaining: () => Infinity };
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)));
run({ outDir: '/x', draftName: 'd', chunkFiles: ['/x/c0.json', '/x/c1.json'], lintFindings: [], counts: { paragraphs: 300, footnotes: 0, words: 1000 }, headings: [] },
    budget, agent, parallel, () => {}, () => {}).then((out) => {
  console.log(JSON.stringify({ counts: out.counts, exitState: out.exitState, degradation: out.degradation,
    rejected: out.rejectedFindings, batches: labels.filter((l) => l.startsWith('verify:batch-')).length }));
});
"""

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: proofread workflow test skipped")
    sys.exit(0)


def run(scenario):
    env = dict(os.environ, PR_WORKFLOW=str(WORKFLOW), PR_SCENARIO=scenario)
    p = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("node failed for scenario %s" % scenario)
    return json.loads(p.stdout.strip().splitlines()[-1])


print("baseline")
r = run("baseline")
check(r["batches"] == 2 and r["counts"]["candidates"] == 14, "fourteen findings in two verify batches (%d, %d)" % (r["counts"]["candidates"], r["batches"]))
check(r["counts"]["confirmed"] == 14 and r["counts"]["rejected"] == 0 and r["exitState"] == "complete", "all confirmed; the run is complete")

print("a verifier answers for a finding in the other batch")
r = run("foreign")
check(r["counts"]["confirmed"] == 14 and r["counts"]["rejected"] == 0, "finding 0 keeps its own batch's verdict (%s)" % {k: r["counts"][k] for k in ("confirmed", "rejected")})
check(any("1 verify verdict(s) dropped" in d for d in r["degradation"]) and r["exitState"] == "complete_with_limits", "the stray verdict is dropped and disclosed (%s)" % r["degradation"])

print("a verifier returns two verdicts for one finding")
r = run("duplicate")
check(r["counts"]["confirmed"] == 14 and r["counts"]["rejected"] == 0 and any("dropped" in d for d in r["degradation"]), "the first verdict stands; the duplicate is dropped and disclosed")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
