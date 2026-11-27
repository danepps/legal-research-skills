#!/usr/bin/env python3
"""Offline check of where proofread.workflow.js puts the report's provenance line (no model, no network).

The line (snapshot time, SHA-256, 'plain-text pass') is the report's LAST line and is written by the
script, not by the report agent. It used to sit under the title, between the heading and the first
finding. This drives the workflow with stubbed agents and asserts that:

  * a report from the agent starts with its own heading and its own next line, and ends with the
    provenance line, exactly once, with the hash the script was given;
  * a provenance blockquote the agent wrote under the title anyway is removed from there;
  * the mechanical fallback (the report agent dies twice) keeps its failure notice at the top and
    also ends with the provenance line;
  * the prompt no longer asks the agent for a provenance line and no longer shows it the hash.
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
SHA = "5eb9a2984c47c71975768619655bc9fd05d34cd65488291a5b520848bd0c28b0"
LINE = "> snapshot 2026-11-25T14:18:08Z, SHA-256 %s; plain-text pass." % SHA

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.env.PR_WORKFLOW, 'utf8').replace(/^export const meta/m, 'const meta');
const AF = Object.getPrototypeOf(async function () {}).constructor;
const run = new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', src);
const mode = process.env.PR_MODE;
let reportPrompt = '';
let reportCalls = 0;
async function agent(prompt, opts) {
  const L = opts.label || '';
  if (L.startsWith('consistency')) return { findings: [], conventions: [] };
  if (L.startsWith('proof:chunk-')) return { findings: [] };
  if (L.startsWith('verify:batch-')) return { verdicts: [] };
  if (L === 'report') {
    reportPrompt = prompt; reportCalls++;
    if (mode === 'dead') return null;
    if (mode === 'echo') return '# Proofread — d\n\n> snapshot 2026-11-25T14:18:08Z, SHA-256 0000; plain-text pass.\n\n_TL;DR: nothing found._\n\n## Errors (fix these)\nNone.';
    return '# Proofread — d\n_TL;DR: nothing found._\n\n## Errors (fix these)\nNone.\n\n\n';
  }
  throw new Error('unstubbed ' + L);
}
const budget = { total: null, spent: () => 0, remaining: () => Infinity };
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)));
run({ outDir: '/x', draftName: 'd', chunkFiles: ['/x/c0.json'], lintFindings: [], counts: { paragraphs: 3, footnotes: 0, words: 100 },
      headings: [], sha256: process.env.PR_SHA, snapshotTime: '2026-11-25T14:18:08Z' },
    budget, agent, parallel, () => {}, () => {}).then(
  (out) => console.log(JSON.stringify({ report: out.report, exitState: out.exitState, degradation: out.degradation, reportPrompt, reportCalls })),
  (err) => console.log(JSON.stringify({ error: String(err && err.message) })));
"""

fails = 0


def check(cond, msg):
    global fails
    print(("  [ok] " if cond else "  [FAIL] ") + msg)
    if not cond:
        fails += 1


node = shutil.which("node")
if not node:
    print("node not found: proofread provenance test skipped")
    sys.exit(0)


def run(mode):
    env = dict(os.environ, PR_WORKFLOW=str(WORKFLOW), PR_MODE=mode, PR_SHA=SHA)
    p = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("node failed")
    return json.loads(p.stdout.strip().splitlines()[-1])


print("the agent's report: heading first, provenance last")
r = run("clean")
lines = r["report"].split("\n")
check(lines[0] == "# Proofread — d" and lines[1].startswith("_TL;DR"), "the report starts with its heading and then its own next line (%r)" % lines[:2])
check(r["report"].endswith("\n\n" + LINE + "\n") and r["report"].count("snapshot") == 1, "the provenance line is the last line, once, with the script's hash")
check("\n\n\n" + LINE not in r["report"], "trailing blank lines of the agent's report are not carried before it")
check(SHA not in r["reportPrompt"] and "PROVENANCE" not in r["reportPrompt"] and "Write no provenance line" in r["reportPrompt"]
      and "the provenance blockquote" not in r["reportPrompt"], "the prompt asks for no provenance line and does not show the hash")
check(r["exitState"] == "complete", "a clean run is still complete")

print("a provenance line the agent wrote under the title anyway")
r = run("echo")
check(r["report"].count("snapshot") == 1 and "SHA-256 0000" not in r["report"] and r["report"].endswith(LINE + "\n"),
      "is removed there, and the script's line stands at the end")
check(r["report"].split("\n")[0] == "# Proofread — d" and "_TL;DR: nothing found._" in r["report"], "the rest of the report is kept")

print("the mechanical fallback")
r = run("dead")
lines = r["report"].split("\n")
check(r["reportCalls"] == 2 and lines[0] == "# Proofread — d" and lines[1].startswith("> REPORT AGENT FAILED"), "keeps its failure notice under the title (%r)" % lines[1][:40])
check("snapshot" not in lines[1] and r["report"].endswith("\n\n" + LINE + "\n") and r["report"].count(SHA) == 1, "and ends with the provenance line")
check(r["exitState"] == "complete_with_limits", "and is not a complete run")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
