#!/usr/bin/env python3
"""Offline check of the `findings` array proofread.workflow.js returns (2026-11-23).

A host can turn the confirmed findings into a redline, so each finding may carry a
`replacement`: the find string with only the correction made. Runs the workflow under stubbed
agents (no model, no network) and asserts that a replacement reaches the return only while
everything it was written against still stands:

  * confirmed as raised: kept;
  * the verifier supplies revised_replacement: that one is used; an empty string withdraws it;
  * the verifier revises the fix, the severity or the find string without a new replacement:
    dropped;
  * the verifier's revised find string fails the snapshot check: the original find string is
    kept and the replacement, written against the revised one, is dropped;
  * author queries, typeface findings, and a replacement equal to the find string: never
    returned;
  * rejected findings are not in `findings`; a finding raised without one has no key at all;
  * the verifier is shown the replacement it is asked to check;
  * with the `replacements` argument off (the default), no prompt or schema mentions a
    replacement and none is returned.
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

# name -> (severity, category, replacement or None, verdict fields)
CASES = {
    "kept": ("error", "typo", "apple banana corrected", {"verdict": "confirmed"}),
    "verifierfix": ("error", "typo", "cherry dates wrong", {"verdict": "revised", "revised_replacement": "cherry dates right"}),
    "withdrawn": ("error", "typo", "elder figs corrected", {"verdict": "revised", "revised_replacement": ""}),
    "fixchanged": ("error", "typo", "grape hazel corrected", {"verdict": "revised", "revised_fix": "a different fix"}),
    "sevchanged": ("error", "typo", "indigo juniper corrected", {"verdict": "revised", "revised_severity": "likely"}),
    "findrevised": ("error", "typo", "kiwi lemon corrected", {"verdict": "revised", "revised_find": "kiwi lemon longer anchor"}),
    "findrefused": ("error", "typo", "mango nectar corrected", {"verdict": "revised", "revised_find": "mango nectar absent anchor", "revised_replacement": "mango nectar absent fixed"}),
    "query": ("query", "quote-integrity", "olive papaya corrected", {"verdict": "confirmed"}),
    "same": ("error", "typo", None, {"verdict": "confirmed"}),  # replacement == find, set below
    "rejected": ("error", "typo", "quince raisin corrected", {"verdict": "rejected"}),
    "none": ("error", "typo", None, {"verdict": "confirmed"}),
    "typeface": ("error", "typeface", "sorrel tomato corrected", {"verdict": "confirmed"}),
    "problemonly": ("error", "typo", "ugli vanilla corrected", {"verdict": "revised", "revised_problem": "a sharper diagnosis"}),
}
FINDS = {
    "kept": "apple banana mistake", "verifierfix": "cherry dates mistake", "withdrawn": "elder figs mistake",
    "fixchanged": "grape hazel mistake", "sevchanged": "indigo juniper mistake", "findrevised": "kiwi lemon mistake",
    "findrefused": "mango nectar mistake", "query": "olive papaya mistake", "same": "walnut xigua mistake",
    "rejected": "quince raisin mistake", "none": "yam zucchini mistake", "typeface": "sorrel tomato mistake",
    "problemonly": "ugli vanilla mistake",
}

findings = []
verdicts = {}
for i, (name, (sev, cat, repl, verdict)) in enumerate(CASES.items()):
    item = {"location": "¶%d" % (i + 1), "find": FINDS[name], "problem": "problem " + name,
            "fix": "fix " + name, "severity": sev, "category": cat}
    if name == "same":
        item["replacement"] = FINDS[name]
    elif repl is not None:
        item["replacement"] = repl
    findings.append(item)
    verdicts[FINDS[name]] = dict(verdict, note="re-read " + name)

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.env.PR_WORKFLOW, 'utf8').replace(/^export const meta/m, 'const meta');
const AF = Object.getPrototypeOf(async function () {}).constructor;
const FINDINGS = JSON.parse(process.env.PR_FINDINGS);
const VERDICTS = JSON.parse(process.env.PR_VERDICTS);
const run = new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', src);
const shown = [];
async function agent(prompt, opts) {
  const L = opts.label || '';
  if (L.startsWith('consistency')) return { findings: [], conventions: [] };
  if (L.startsWith('proof:chunk-')) return { findings: FINDINGS };
  if (L.startsWith('verify:batch-')) {
    const start = prompt.lastIndexOf('FINDINGS (verify batch');
    const json = prompt.slice(prompt.indexOf('[', start), prompt.lastIndexOf(']') + 1);
    const batch = JSON.parse(json);
    shown.push(...batch);
    return { verdicts: batch.map((f) => ({ id: f.id, ...VERDICTS[f.find] })) };
  }
  if (L === 'revised-find-check') {
    const items = JSON.parse(prompt.slice(prompt.indexOf('[', prompt.lastIndexOf('ITEMS:')), prompt.lastIndexOf(']') + 1));
    return { results: items.map((it) => ({ id: it.id, present: !it.find.includes('absent') })) };
  }
  if (L === 'report') return '# Proofread';
  throw new Error('unstubbed ' + L);
}
const budget = { total: null, spent: () => 0, remaining: () => Infinity };
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)));
const prompts = [];
const schemas = [];
const agentRecording = async (prompt, opts) => { prompts.push(prompt); schemas.push(JSON.stringify(opts.schema || null)); return agent(prompt, opts); };
run({ outDir: '/x', draftName: 'd', chunkFiles: ['/x/c0.json'], lintFindings: [], counts: { paragraphs: 300, footnotes: 0, words: 1000 }, headings: [],
      replacements: process.env.PR_REPLACEMENTS === '1' },
    budget, agentRecording, parallel, () => {}, () => {}).then((out) => {
  console.log(JSON.stringify({ findings: out.findings, counts: out.counts, exitState: out.exitState, shown,
    mentions: prompts.concat(schemas).filter((p) => /"replacement"|revised_replacement/.test(p)).length }));
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
    print("node not found: proofread findings test skipped")
    sys.exit(0)



def run(replacements, raised):
    env = dict(os.environ, PR_WORKFLOW=str(WORKFLOW), PR_FINDINGS=json.dumps(raised), PR_VERDICTS=json.dumps(verdicts),
               PR_REPLACEMENTS="1" if replacements else "0")
    p = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(p.stderr[-2000:])
        raise SystemExit("node failed")
    return json.loads(p.stdout.strip().splitlines()[-1])


print("replacements off (the default): nothing about a run changes")
# Agents are not asked for a replacement; one that supplies it anyway is ignored.
off = run(False, findings)
check(off["mentions"] == 0, "no prompt or schema mentions a replacement (%d do)" % off["mentions"])
check(len(off["findings"]) == 12 and all("replacement" not in f for f in off["findings"]), "findings are returned, none with a replacement")
check(all("replacement" not in f for f in off["shown"]), "the verifier is not shown one")

r = run(True, findings)
out = r["findings"]
by_problem = {f["problem"]: f for f in out}


def got(name):
    # revised_problem replaces the problem text for "problemonly"
    return by_problem.get("problem " + name) or by_problem.get("a sharper diagnosis" if name == "problemonly" else "")


print("the return carries the confirmed findings as data")
check(isinstance(out, list) and len(out) == r["counts"]["confirmed"] == 12, "twelve confirmed findings returned, matching counts.confirmed (%d, %d)" % (len(out), r["counts"]["confirmed"]))
check(got("rejected") is None, "a rejected finding is not returned")
check([f["location"] for f in out] == sorted((f["location"] for f in out), key=lambda s: int(s[1:])), "findings are in draft order")
check(all(set(f) <= {"location", "find", "problem", "fix", "severity", "category", "replacement"} for f in out), "each finding has only the documented fields")
check(all(k in f for f in out for k in ("location", "find", "problem", "fix", "severity", "category")), "each finding has every required field")

print("a replacement survives only while what it was written against stands")
check(got("kept").get("replacement") == "apple banana corrected", "confirmed as raised: kept")
check(got("verifierfix").get("replacement") == "cherry dates right", "the verifier's revised_replacement is used")
check("replacement" not in got("withdrawn"), "an empty revised_replacement withdraws it")
check("replacement" not in got("fixchanged") and got("fixchanged")["fix"] == "a different fix", "a revised fix without a new replacement drops it")
check("replacement" not in got("sevchanged") and got("sevchanged")["severity"] == "likely", "a revised severity drops it")
check("replacement" not in got("findrevised") and got("findrevised")["find"] == "kiwi lemon longer anchor", "a revised find string without a new replacement drops it")
check("replacement" not in got("findrefused") and got("findrefused")["find"] == FINDS["findrefused"], "a refused revised find string keeps the original find and drops the replacement written for the revised one")
check(got("problemonly").get("replacement") == "ugli vanilla corrected", "a revision to the diagnosis alone keeps it")

print("replacements that could not be applied mechanically never reach the return")
check("replacement" not in got("query"), "an author query has none")
check("replacement" not in got("typeface"), "a typeface finding has none")
check("replacement" not in got("same"), "a replacement equal to the find string is dropped")
check("replacement" not in got("none"), "a finding raised without one has no key")

print("the verifier sees what it is asked to check")
shown = {f["find"]: f for f in r["shown"]}
check(shown[FINDS["kept"]].get("replacement") == "apple banana corrected", "the verify prompt carries the replacement")
check("replacement" not in shown[FINDS["none"]], "and omits the key when there is none")

print("\n%d FAILED" % fails if fails else "\nall passed")
sys.exit(1 if fails else 0)
