#!/usr/bin/env python3
"""Offline checks for the deep-mode refutation panel in legal-research.workflow.js (1.6.1).

Runs the workflow under stubbed agents (no model, no network) and asserts:
  * authorityType(): explicit whole-label kinds, statutory signatures before reporter cites,
    a caption or a bare section symbol alone is not a type, conflicting signals -> unknown;
  * each source type gets its own voter routes and the shared tool tip is order-neutral;
  * a refutation the majority outvotes reaches Finalize as a MINORITY OBJECTION, is counted in
    counts.panelObjections, labels the authority's tier, and ends the run complete_with_limits;
  * every voter's reason survives aggregation (the old slice(0, 2) dropped the third);
  * every voter sees the memo question; a historical run adds the research date, the notes and
    the rule that a change after the proposition's date is a disclosure, not a refutation.
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
const assert = require('assert/strict');
const src = fs.readFileSync(process.env.LR_WORKFLOW, 'utf8').replace(/^export const meta/m, 'const meta');
const AF = Object.getPrototypeOf(async function () {}).constructor;
new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', src); // parses as a workflow body

// ---- classifier -------------------------------------------------------------------------
const block = src.slice(src.indexOf('const REPORTER_CITE'), src.indexOf('const REFUTE_ROUTES_BY_TYPE'));
eval(block.replace(/const (REPORTER_CITE|KIND_CASE|KIND_STATUTE|KIND_SECONDARY|authorityType)/g, 'var $1'));
const fixtures = [
  [{kind: 'case', citation: 'Miller v. French, 530 U.S. 327 (2000) (interpreting 18 U.S.C. § 3626)'}, 'case'],
  [{kind: '', citation: 'Miller v. French, 530 U.S. 327 (2000) (interpreting 18 U.S.C. § 3626)'}, 'unknown'],
  [{kind: 'casebook', citation: 'Hart & Wechsler, The Federal Courts and the Federal System (7th ed. 2015)'}, 'secondary'],
  [{kind: 'constitutional treatise', citation: 'Laurence Tribe, American Constitutional Law (3d ed. 2000)'}, 'unknown'],
  [{kind: 'other', citation: 'William Van Alstyne, A Critical Guide to Marbury v. Madison, 1969 Duke L.J. 1'}, 'unknown'],
  [{kind: 'other', citation: 'The Paquete Habana, 175 U.S. 677 (1900)'}, 'case'],
  [{kind: '', citation: '*In re Gault*, 387 U.S. 1 (1967)'}, 'case'],
  [{kind: '', citation: 'Marbury v. Madison, 5 U.S. (1 Cranch) 137 (1803)'}, 'case'],
  [{kind: '', citation: 'Smith v. Jones, No. 20-1234 (9th Cir. 2021)'}, 'unknown'],
  [{kind: '', citation: '78 Stat. 241'}, 'statute'],
  [{kind: '', citation: '28 U.S.C. § 1332(a) (1982)'}, 'statute'],
  [{kind: '', citation: 'Fed. R. Crim. P. 11'}, 'statute'],
  [{kind: '', citation: 'Restatement (Second) of Torts § 402A (1965)'}, 'unknown'],
  [{kind: '', citation: 'Note, Interpreting 42 U.S.C. § 1983, 120 Harv. L. Rev. 100 (2006)'}, 'unknown'],
  [{kind: 'other', citation: 'Author, The Fourth Amendment Today, 30 Const. Comment. 1 (2015)'}, 'unknown'],
  [{kind: '', citation: 'U.S. Const. amend. IV'}, 'statute'],
  [{kind: 'article', citation: 'Daniel Epps, Harmless Errors and Substantial Rights, 131 Harv. L. Rev. 2117 (2018)'}, 'secondary'],
  [{kind: '', citation: 'Daniel Epps, Harmless Errors and Substantial Rights, 131 Harv. L. Rev. 2117 (2018)'}, 'unknown'],
];
for (const [c, want] of fixtures) assert.equal(authorityType(c), want, `authorityType(${c.citation}, kind=${JSON.stringify(c.kind)})`);

// ---- stubbed workflow runs ----------------------------------------------------------------
const memo = '# Brief Answer\nx\n\n# Discussion\nx\n\n# Conclusion\nx';
async function run({kind = 'case', citation, scenario = 'agree', historical = false, asOf = 'today', question = 'q', notes = ''} = {}) {
  const calls = [];
  const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', `return (async () => { ${src} })()`);
  const cited = [{citation: citation || 'Fixture v. Example, 100 U.S. 1 (2000)', kind, loadBearing: true,
    proposition: 'p', quote: 'q', pincite: '5', url: 'https://example.invalid/fixture'}];
  const vote = (k) => {
    if (scenario === 'short' && k === 3) return null;
    const refuted = scenario === 'third-refutes' && k === 3;
    return {refuted, basis: 'authoritative-reproduction', quoteAccurate: true,
      reason: refuted ? `Voter ${k} UNIQUE_ADVERSE: the passage excludes the fixture facts.` : `Voter ${k} REASON_${k}: no defect.`};
  };
  const agent = async (prompt, opts) => {
    const label = opts.label || '';
    calls.push({label, prompt, phase: opts.phase});
    if (opts.phase === 'Scope') return {jurisdiction: 'x', issues: ['a'], searchVectors: [], methodClass: 'doctrinal', historical};
    if (opts.phase === 'Survey') return {candidates: []};
    if (label === 'calibrate:thesis') return {memoDraft: memo};
    if (opts.phase === 'Draft') return {memoDraft: memo, citedAuthorities: cited, missingAuthorities: [], skeleton: 's'};
    if (label.startsWith('refute:')) return vote(Number(label.match(/#(\d+)$/)[1]));
    if (label.startsWith('verify:')) return {verdicts: cited.map((c, index) => ({index, citation: c.citation, verdict: 'verified', basis: 'authoritative-reproduction'}))};
    if (opts.phase === 'Finalize') return {memo};
    throw new Error('unexpected agent ' + JSON.stringify(opts));
  };
  const result = await fn({question, notes, mode: 'caselaw', deep: true, asOfDate: asOf, runTag: 't'},
    {total: 0, spent: () => 0, remaining: () => 1e9}, agent, async (jobs) => Promise.all(jobs.map((f) => f())), () => {}, () => {});
  const voters = calls.filter((c) => c.label.startsWith('refute:'));
  const finalPrompt = calls.find((c) => c.phase === 'Finalize').prompt;
  return {result, voters, finalPrompt, calls};
}
(async () => {
  // objection survives, is counted, labels the tier, limits the run
  const r = await run({scenario: 'third-refutes'});
  assert.equal(r.result.counts.verified, 1);
  assert.equal(r.result.counts.panelObjections, 1);
  assert.equal(r.result.exitState, 'complete_with_limits');
  assert.ok(r.finalPrompt.includes('MINORITY OBJECTION (voter #3, adverse reading)'));
  assert.ok(r.finalPrompt.includes('UNIQUE_ADVERSE'));
  assert.ok(r.finalPrompt.includes('1 objection unresolved'));
  // every reason survives when all agree
  const a = await run({scenario: 'agree'});
  for (const k of [1, 2, 3]) assert.ok(a.finalPrompt.includes(`REASON_${k}`), `reason ${k} reached Finalize`);
  assert.equal(a.result.exitState, 'complete');
  assert.equal(a.result.counts.panelObjections, 0);
  // short panel still disclosed
  const s = await run({scenario: 'short'});
  assert.equal(s.result.counts.shortRefutationPanel, 1);
  // routes per type; shared tip order-neutral; three distinct routes per authority
  const routeLine = (v) => v.prompt.match(/YOUR ROUTE[^\n]*/)[0];
  const caseRun = await run({kind: 'case'});
  assert.equal(new Set(caseRun.voters.map(routeLine)).size, 3);
  assert.ok(caseRun.voters.every((v) => !v.prompt.includes('this is a secondary source') && !v.prompt.includes('SOURCE TYPE UNKNOWN')));
  assert.ok(caseRun.voters.every((v) => !v.prompt.includes('settle existence and the reporter cite deterministically first')));
  const art = await run({kind: 'article', citation: 'Author, Title, 10 Example L. Rev. 1 (2000)'});
  assert.ok(art.voters.every((v) => routeLine(v).includes('secondary source')));
  const stat = await run({kind: 'statute', citation: '42 U.S.C. § 1983'});
  assert.ok(stat.voters.every((v) => routeLine(v).includes('statute, regulation, rule')));
  const unk = await run({kind: 'other', citation: 'Restatement (Second) of Torts § 402A (1965)'});
  assert.ok(unk.voters.every((v) => v.prompt.includes('SOURCE TYPE UNKNOWN')));
  // temporal context on a historical run
  const h = await run({kind: '', citation: '28 U.S.C. § 1332(a) (1982)', historical: true, asOf: '1985-01-01'});
  assert.ok(h.voters.every((v) => v.prompt.includes('RESEARCH AS OF: 1985-01-01') && v.prompt.includes('HISTORICAL QUESTION')));
  // the target date given only in the question or notes still reaches every voter
  const h2 = await run({kind: '', citation: '28 U.S.C. § 1332(a)', historical: true,
    question: 'What was the diversity amount-in-controversy threshold in 1982?', notes: 'period: 1980-1984'});
  assert.ok(h2.voters.every((v) => v.prompt.includes('MEMO QUESTION: What was the diversity amount-in-controversy threshold in 1982?')));
  assert.ok(h2.voters.every((v) => v.prompt.includes('QUESTION NOTES: period: 1980-1984')));
  assert.ok(h2.voters.every((v) => v.prompt.includes('RESEARCH AS OF: today')));
  const plain = await run({kind: 'case'});
  assert.ok(plain.voters.every((v) => !v.prompt.includes('HISTORICAL QUESTION')));
  console.log(JSON.stringify({ok: true, fixtures: fixtures.length, runs: 9}));
})().catch((e) => { console.error(e && e.stack || e); process.exit(1); });
"""


def main() -> int:
    node = shutil.which("node")
    if not node:
        print("skip: node not available")
        return 0
    env = dict(os.environ, LR_WORKFLOW=str(WORKFLOW))
    proc = subprocess.run([node, "-e", NODE_SCRIPT], capture_output=True, text=True, env=env)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        return 1
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    print(f"ok: refute routing — {out['fixtures']} classifier fixtures, {out['runs']} stubbed runs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
