// Offline harness for legal-research.workflow.js (2026-11-15 review): runs the whole pipeline
// with STUBBED agents and prints what reached the Draft and Finalize prompts and the result.
// test_workflow_pipeline.py drives it. Nothing here touches the network or a model.
//
//   node workflow_harness.mjs <workflow.js> <scenario> [output tokens already spent this turn] [extra args as JSON]
//
// A scenario may join several of the names below with "+", e.g. "refuted+revise-dead". The extra
// args are merged into the workflow's args: {"finalizeModel":"opus"}, {"escalate":false}.
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
//   read-pin       (with was-read) the reader returns its citation with a pincite, a parallel cite and
//                  an opinion parenthetical, which the draft's citation does not carry
//   read-other     (with was-read) the reader returns a different case in the same volume
// Finalize as edits (2026-11-16). The stub draft is a short memo with real sentences, and the
// Finalize stub returns edits plus the two appendix sections instead of a retyped memo:
//   gapfill        the draft flags a missing authority and the gap-fill agent retrieves it
//   gapfill-unverified  (with gapfill) the cite-checker examines the gap-fill authority and cannot confirm it
//   gapfill-skipped     (with gapfill) the cite-checker runs no check on it and returns "unverified", examined=false
//   unread-skipped      the cite-checker runs no check on a cited authority the run did NOT read
//   calibrate      (deep) the calibration reviewer returns one edit
//   revise-dead    the session-model call-in dies twice
//   edit-miss      Finalize's edit misquotes the memo; the repair round restates it correctly
//   edit-unfixable ... and the repair round misquotes it again
//   edit-tolerant  the find text differs from the memo only in whitespace and quote style
//   edit-ambiguous the find text occurs twice; the repair round sets all:true
//   edit-shrink    the edit deletes most of the memo
//   no-limits      Finalize returns an empty Limits section, twice
import fs from 'node:fs'
const [,, wfPath, scenario = 'baseline', spent0 = '0', extra = '{}'] = process.argv
const has = (name) => scenario.split('+').includes(name)
const src = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', `return (async () => { ${src} })()`)
const deep = ['refuted', 'treatment', 'correction', 'correction-majority', 'calibrate'].some(has)
const args = { question: 'Q', mode: 'caselaw', deep, asOfDate: '2026-11-15', ...JSON.parse(extra) }
let spent = Number(spent0)
const budget = { spent: () => spent, total: null, remaining: () => Infinity }
const labels = []
const logs = []
const calls = {}
let finalPrompt = ''
let draftPrompt = ''
let readPrompt = ''
let revisePrompt = ''
let repairPrompt = ''
const optsByLabel = {}
const prompts = []
// A memo with real sentences, so edits have something to find. "The rule is settled." occurs twice.
const DRAFT = [
  '# Memo', '',
  '## Brief Answer', 'The rule is settled. Alpha v. Beta, 500 U.S. 1 (1991), controls.', '',
  '## Discussion',
  'Alpha v. Beta, 500 U.S. 1 (1991), held that \u201cthe rule applies.\u201d',
  'Gamma v. Delta, 501 U.S. 2 (1992), is to the same effect.',
  'The record is thin on remedies. [GAP: Needed v. Case]', '',
  '## Conclusion', 'The rule is settled.',
].join('\n')
const TOA = '## Table of Authorities\n| Authority | Validation |\n|---|---|\n| Alpha v. Beta | checked |'
const LIMITS = '## Limits of this research\nOpen-web sources only.'
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)))
const candidate = (v, i) => `Case ${v}-${i}, ${100 + i} U.S. ${v.slice(1)}${i} (1990)`
async function agent(prompt, opts) {
  const L = opts.label || opts.phase
  prompts.push({ label: L, prompt })
  labels.push(L)
  calls[L] = (calls[L] || 0) + 1
  optsByLabel[L] = { model: opts.model, effort: opts.effort }
  spent += 2000
  if (opts.phase === 'Scope') return { issues: ['i1', 'i2'], jurisdiction: 'federal', methodClass: 'doctrinal', historical: false,
    searchVectors: [1, 2, 3, 4].map((n) => ({ label: 'v' + n, kind: 'caselaw', goal: 'g', queries: ['q'] })) }
  if (L.startsWith('survey')) {
    const v = L.split(':')[1]
    if (has('dead-survey') && v === 'v1') return null
    return { candidates: Array.from({ length: 10 }, (_, i) => ({ kind: 'case', citation: candidate(v, i), url: 'https://example.org/' + v + i, why: 'w', authority: 'high' })) }
  }
  if (L === 'triage') {
    if (has('triage-null')) return null
    if (has('triage-dupes')) return { selected: [3, 3, 5, 5, 999, -1, 7] }
    return { selected: [0, 1, 2, 3, 4, 5, 6, 7] }
  }
  if (L.startsWith('read')) {
    readPrompt = prompt
    const cit = prompt.match(/SOURCE TO READ: (.+)/)[1]
    if (/Case v1-0,/.test(cit) && (has('dead-read') || (has('flaky-read') && calls[L] === 1))) return null
    let readCit = cit
    if (has('read-pin')) readCit = cit.replace(/ \((\d{4})\)$/, ', 15-16, 99 S. Ct. 1234 ($1) (Kavanaugh, J., concurring, id. at 15-20)')
    if (has('read-other')) readCit = cit.replace(/U\.S\. (\d+)/, (m, p) => 'U.S. ' + (Number(p) + 500))
    return { kind: 'case', citation: readCit, proposition: 'p', quote: 'q', pincite: '1', opened: true,
      keyCited: [`Harvested by ${cit.slice(5, 9)} A, 1 U.S. 1`, `Harvested by ${cit.slice(5, 9)} B, 2 U.S. 2`] }
  }
  if (opts.phase === 'Draft' && L === 'Draft') {
    draftPrompt = prompt
    const second = has('was-read') ? candidate('v1', 1) : 'Gamma v. Delta, 501 U.S. 2 (1992)'
    const citedAuthorities = [{ citation: 'Alpha v. Beta, 500 U.S. 1 (1991)', kind: 'case', proposition: 'p', quote: 'q', loadBearing: true }, { citation: second, kind: 'case', proposition: 'p', loadBearing: false }]
    // ten authorities make two cite-check chunks (8 + 2)
    if (has('foreign-index')) for (let i = 2; i < 10; i++) citedAuthorities.push({ citation: `Filler${i} v. Other, ${510 + i} U.S. ${i} (1993)`, kind: 'case', proposition: 'p', loadBearing: false })
    return { memoDraft: DRAFT, skeleton: 's', missingAuthorities: has('gapfill') ? ['Needed v. Case'] : [], citedAuthorities }
  }
  if (L === 'calibrate:thesis') return has('calibrate')
    ? { edits: [{ find: 'The rule is settled. Alpha', replace: 'The rule appears settled in the cases reviewed. Alpha', why: 'quantifier' }] }
    : null
  if (L.startsWith('gapfill')) return { kind: 'case', citation: 'Needed v. Case, 502 U.S. 3 (1993)', url: 'https://example.org/needed', proposition: 'the remedy is available', quote: 'q', pincite: '5', opened: true }
  if (L === 'finalize:revise') {
    revisePrompt = prompt
    if (has('revise-dead')) return null
    return { edits: [{ find: 'Alpha v. Beta, 500 U.S. 1 (1991), controls.', replace: 'Alpha v. Beta, 500 U.S. 1 (1991), reportedly controls, but that could not be independently confirmed.', why: 'caveat Alpha (session-model call-in)' }] }
  }
  if (L.startsWith('finalize:repair')) {
    repairPrompt = prompt
    if (has('edit-unfixable')) return { edits: [{ find: 'is to the same affect, again.', replace: 'X', why: 'caveat Gamma' }] }
    if (has('edit-ambiguous')) return { edits: [{ find: 'The rule is settled.', replace: 'The rule appears settled in the cases reviewed.', all: true, why: 'quantifier' }] }
    return { edits: [{ find: 'is to the same effect.', replace: 'is reportedly to the same effect.', why: 'caveat Gamma' }] }
  }
  if (L.startsWith('refute')) {
    const k = Number(L.split('#')[1])
    if (has('refuted')) return { refuted: true, basis: 'direct-full-text', reason: 'the quote is not in the opinion' }
    if (has('treatment')) return k === 3
      ? { refuted: false, basis: 'direct-full-text', reason: 'ok', currentTreatment: 'OVERRULED by Omega v. Psi, 600 U.S. 9 (2023)' }
      : { refuted: false, basis: 'authoritative-reproduction', reason: 'ok', currentTreatment: 'no negative treatment found in the citing probe' }
    if (has('correction')) return k === 2
      ? { refuted: false, basis: 'citation-only', reason: 'ok', correctedCitation: 'Alpha v. Beta, 505 U.S. 100 (1992)' }
      : { refuted: false, basis: 'direct-full-text', reason: 'cite accurate as written' }
    if (has('correction-majority')) return k === 1
      ? { refuted: false, basis: 'direct-full-text', reason: 'cite accurate as written' }
      : { refuted: false, basis: 'direct-full-text', reason: 'year is wrong', correctedCitation: k === 2 ? 'Alpha v. Beta, 500 U.S. 1 (1992)' : 'Alpha v. Beta, 500 U.S. 1 (1992).' }
  }
  if (L.startsWith('verify')) {
    const given = [...prompt.matchAll(/^\[(\d+)\]/gm)].map((m) => Number(m[1]))
    const verdicts = given.map((index) => ({ index, verdict: 'verified', basis: 'citation-only' }))
    if (has('foreign-index')) {
      // the first chunk (0-7) also answers for index 9, which the second chunk was given and could not confirm
      if (given.includes(0)) verdicts.push({ index: 9, citation: 'Somebody Else v. Nobody', verdict: 'verified', basis: 'citation-only', notes: 'returned under an index this checker was not given' })
      if (given.includes(9)) verdicts.find((v) => v.index === 9).verdict = 'unverified'
    }
    if (has('unread-skipped') && given.includes(1)) Object.assign(verdicts.find((x) => x.index === 1), { verdict: 'unverified', examined: false, notes: 'I did not check it.' })
    // the gap-fill authority, which the run read: not confirmed, or never examined
    const gapIdx = (prompt.match(/^\[(\d+)\] \[READ IN FULL THIS RUN\] Needed v\. Case/m) || [])[1]
    if (gapIdx !== undefined && (has('gapfill-unverified') || has('gapfill-skipped'))) {
      const v = verdicts.find((x) => x.index === Number(gapIdx))
      v.verdict = 'unverified'
      v.notes = has('gapfill-skipped') ? 'Marked read in full this run; I did not check it.' : 'the quoted sentence is not in the opinion'
      if (has('gapfill-skipped')) v.examined = false
    }
    return { verdicts }
  }
  if (opts.phase === 'Finalize') {
    finalPrompt = prompt
    let edits = [{ find: 'is to the same effect.', replace: 'is to the same effect (checked).', why: 'tag Gamma' }]
    if (has('edit-miss') || has('edit-unfixable')) edits = [{ find: 'is to the same affect.', replace: 'is reportedly to the same effect.', why: 'caveat Gamma' }]
    if (has('edit-tolerant')) edits = [{ find: 'held  that\n"the rule applies."', replace: 'held that the rule applies.', why: 'unquote' }]
    if (has('edit-ambiguous')) edits = [{ find: 'The rule is settled.', replace: 'The rule appears settled in the cases reviewed.', why: 'quantifier' }]
    if (has('edit-shrink')) edits = [{ find: DRAFT.slice(DRAFT.indexOf('## Discussion')), replace: '', why: 'oops' }]
    return { edits, tableOfAuthorities: TOA, limits: has('no-limits') ? '  ' : LIMITS }
  }
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
    memo: out.memo,
    draft: DRAFT,
    finalize: out.finalize,
    labels,
    optsByLabel,
    revisePrompt,
    repairPrompt,
    finalHasEditRules: /HOW TO RETURN CHANGES/.test(finalPrompt),
    finalHasAlreadyRevised: /- ALREADY REVISED/.test(finalPrompt),
    finalHasPostDraftBullet: /- POST-DRAFT ADDITIONS/.test(finalPrompt),
    finalHasWeaveRule: /\* TABLES:/.test(finalPrompt) && /\* COUNTS:/.test(finalPrompt) && /\* CITATION STYLE:/.test(finalPrompt),
    finalPostDraftSection: cut('=== POST-DRAFT ADDITIONS ===', '=== DRAFT MEMO ==='),
    // where each agent was told to put a file it saves: the prefix of the TEMPORARY FILES rule, and
    // how many prompts still name a /tmp path of this workflow (none when args.scratchDir is set)
    tempFiles: prompts.map((p) => ({ label: p.label, prefix: (p.prompt.match(/gets a name that starts with\n  (.+)\n/) || [])[1] || '' })),
    tmpNamed: prompts.filter((p) => /(^|[^.\w])\/tmp\/lr-/.test(p.prompt)).length,
    finalMemoSection: finalPrompt.slice(finalPrompt.indexOf('=== DRAFT MEMO ===')),
  }))
} catch (e) {
  console.log(JSON.stringify({ scenario, threw: String(e), agentsBeforeCrash: labels.length }))
}
