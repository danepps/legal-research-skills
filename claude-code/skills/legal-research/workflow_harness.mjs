// Offline harness for legal-research.workflow.js (2026-11-15 review): runs the whole pipeline
// with STUBBED agents and prints what reached the Draft and Finalize prompts and the result.
// test_workflow_pipeline.py drives it. Nothing here touches the network or a model.
//
//   node workflow_harness.mjs <workflow.js> <scenario> [output tokens already spent this turn]
//
// Baseline: 4 survey vectors x 10 candidates, triage picks 8, every reader opens its source and
// reports two authorities it relies on, the draft cites one load-bearing and one ordinary case.
// Scenarios (what the stubbed agents do differently):
//   triage-null    the triage agent dies (agent() returns null)
//   triage-dupes   the triage agent returns repeated and out-of-range indices
//   dead-read      the reader for triage's first pick dies twice
//   flaky-read     that reader dies once, then answers
//   dead-survey    the first survey vector dies twice
//   refuted        (deep) all three panel voters refute the load-bearing authority
//   treatment      (deep) voters 1-2 report no negative treatment, voter 3 reports an overruling
//   correction     (deep) one voter proposes a different citation; two find it accurate
//   correction-majority  (deep) two voters propose the same corrected citation
//   foreign-index  ten cited authorities (two cite-check chunks); the first chunk's agent also returns
//                  "verified" under index 9, which the second chunk was given and could not confirm
//   was-read       the draft cites a source a reader opened; the checker reports citation-only
import fs from 'node:fs'
const [,, wfPath, scenario = 'baseline', spent0 = '0'] = process.argv
const src = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', `return (async () => { ${src} })()`)
const deep = ['refuted', 'treatment', 'correction', 'correction-majority'].includes(scenario)
const args = { question: 'Q', mode: 'caselaw', deep, asOfDate: '2026-11-15' }
let spent = Number(spent0)
const budget = { spent: () => spent, total: null, remaining: () => Infinity }
const labels = []
const logs = []
const calls = {}
let finalPrompt = ''
let draftPrompt = ''
let readPrompt = ''
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)))
const candidate = (v, i) => `Case ${v}-${i}, ${100 + i} U.S. ${v.slice(1)}${i} (1990)`
async function agent(prompt, opts) {
  const L = opts.label || opts.phase
  labels.push(L)
  calls[L] = (calls[L] || 0) + 1
  spent += 2000
  if (opts.phase === 'Scope') return { issues: ['i1', 'i2'], jurisdiction: 'federal', methodClass: 'doctrinal', historical: false,
    searchVectors: [1, 2, 3, 4].map((n) => ({ label: 'v' + n, kind: 'caselaw', goal: 'g', queries: ['q'] })) }
  if (L.startsWith('survey')) {
    const v = L.split(':')[1]
    if (scenario === 'dead-survey' && v === 'v1') return null
    return { candidates: Array.from({ length: 10 }, (_, i) => ({ kind: 'case', citation: candidate(v, i), url: 'https://example.org/' + v + i, why: 'w', authority: 'high' })) }
  }
  if (L === 'triage') {
    if (scenario === 'triage-null') return null
    if (scenario === 'triage-dupes') return { selected: [3, 3, 5, 5, 999, -1, 7] }
    return { selected: [0, 1, 2, 3, 4, 5, 6, 7] }
  }
  if (L.startsWith('read')) {
    readPrompt = prompt
    const cit = prompt.match(/SOURCE TO READ: (.+)/)[1]
    if (/Case v1-0,/.test(cit) && (scenario === 'dead-read' || (scenario === 'flaky-read' && calls[L] === 1))) return null
    return { kind: 'case', citation: cit, proposition: 'p', quote: 'q', pincite: '1', opened: true,
      keyCited: [`Harvested by ${cit.slice(5, 9)} A, 1 U.S. 1`, `Harvested by ${cit.slice(5, 9)} B, 2 U.S. 2`] }
  }
  if (opts.phase === 'Draft' && L === 'Draft') {
    draftPrompt = prompt
    const second = scenario === 'was-read' ? candidate('v1', 1) : 'Gamma v. Delta, 501 U.S. 2 (1992)'
    const citedAuthorities = [{ citation: 'Alpha v. Beta, 500 U.S. 1 (1991)', kind: 'case', proposition: 'p', quote: 'q', loadBearing: true }, { citation: second, kind: 'case', proposition: 'p', loadBearing: false }]
    // ten authorities make two cite-check chunks (8 + 2)
    if (scenario === 'foreign-index') for (let i = 2; i < 10; i++) citedAuthorities.push({ citation: `Filler${i} v. Other, ${510 + i} U.S. ${i} (1993)`, kind: 'case', proposition: 'p', loadBearing: false })
    return { memoDraft: 'MEMO '.repeat(50), skeleton: 's', missingAuthorities: [], citedAuthorities }
  }
  if (L === 'calibrate:thesis') return null
  if (L.startsWith('refute')) {
    const k = Number(L.split('#')[1])
    if (scenario === 'refuted') return { refuted: true, basis: 'direct-full-text', reason: 'the quote is not in the opinion' }
    if (scenario === 'treatment') return k === 3
      ? { refuted: false, basis: 'direct-full-text', reason: 'ok', currentTreatment: 'OVERRULED by Omega v. Psi, 600 U.S. 9 (2023)' }
      : { refuted: false, basis: 'authoritative-reproduction', reason: 'ok', currentTreatment: 'no negative treatment found in the citing probe' }
    if (scenario === 'correction') return k === 2
      ? { refuted: false, basis: 'citation-only', reason: 'ok', correctedCitation: 'Alpha v. Beta, 505 U.S. 100 (1992)' }
      : { refuted: false, basis: 'direct-full-text', reason: 'cite accurate as written' }
    if (scenario === 'correction-majority') return k === 1
      ? { refuted: false, basis: 'direct-full-text', reason: 'cite accurate as written' }
      : { refuted: false, basis: 'direct-full-text', reason: 'year is wrong', correctedCitation: k === 2 ? 'Alpha v. Beta, 500 U.S. 1 (1992)' : 'Alpha v. Beta, 500 U.S. 1 (1992).' }
  }
  if (L.startsWith('verify')) {
    const given = [...prompt.matchAll(/^\[(\d+)\]/gm)].map((m) => Number(m[1]))
    const verdicts = given.map((index) => ({ index, verdict: 'verified', basis: 'citation-only' }))
    if (scenario === 'foreign-index') {
      // the first chunk (0-7) also answers for index 9, which the second chunk was given and could not confirm
      if (given.includes(0)) verdicts.push({ index: 9, citation: 'Somebody Else v. Nobody', verdict: 'verified', basis: 'citation-only', notes: 'returned under an index this checker was not given' })
      if (given.includes(9)) verdicts.find((v) => v.index === 9).verdict = 'unverified'
    }
    return { verdicts }
  }
  if (opts.phase === 'Finalize') { finalPrompt = prompt; return { memo: 'FINAL' } }
  throw new Error('unstubbed ' + L)
}
try {
  const out = await fn(args, budget, agent, parallel, () => {}, (m) => logs.push(m), null)
  const cut = (a, b) => { const i = finalPrompt.indexOf(a); return i < 0 ? '' : finalPrompt.slice(i, finalPrompt.indexOf(b, i + 1)).trim() }
  console.log(JSON.stringify({
    scenario, exitState: out.exitState, degradation: out.degradation, counts: out.counts,
    readAgents: labels.filter((l) => l.startsWith('read')).length,
    distinctReads: new Set(labels.filter((l) => l.startsWith('read'))).size,
    surveyAgents: labels.filter((l) => l.startsWith('survey')).length,
    findingsInDraft: (draftPrompt.match(/^\[\d+\] /gm) || []).length,
    harvestedInDraft: (draftPrompt.match(/^\[\d+\] Harvested by/gm) || []).length,
    harvestSources: new Set((draftPrompt.match(/^\[\d+\] Harvested by \S+/gm) || []).map((x) => x.split(' ').pop())).size,
    firstPickInDraft: /Case v1-0,/.test(draftPrompt),
    firstPickLine: (draftPrompt.match(/^\[\d+\] Case v1-0,.*$/m) || [''])[0],
    readPromptProbes: /probe_sources\.py/.test(readPrompt),
    logs,
    citeCheck: cut('=== CITE-CHECK RESULTS ===', '=== DRAFT MEMO ==='),
    finalMentionsResearchGaps: /RESEARCH COVERAGE GAPS/.test(finalPrompt),
    researchGaps: cut('- RESEARCH COVERAGE GAPS', '- Append two sections'),
  }))
} catch (e) {
  console.log(JSON.stringify({ scenario, threw: String(e), agentsBeforeCrash: labels.length }))
}
