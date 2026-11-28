// Offline harness for the CASE-METADATA comparison and the EXIT STATE of cite-check.workflow.js
// (2026-11-23). test_workflow_case_metadata.py drives it. Nothing here touches the network or a
// model: every agent is a stub, steered by the `_stub` key of the args file (removed before the
// workflow sees the args):
//
//   node workflow_case_harness.mjs <workflow.js> <args.json>
//
//   _stub.existence   { "<reporter cite>": { exists, caseName, dateFiled, basis, note, corrected } }
//                     what the case-existence agent returns per cite (default: exists, courtlistener-api,
//                     no caption); a cite mapped to null is left out of the agent's answer
//   _stub.secondary   { "<source key>": { exists, basis } } (default: exists, web)
//   _stub.history     { "<reporter cite>": { status, note } } (default: checked)
//   _stub.quotes      { "<unit id>": "<verdict>" } (default: verbatim)
//   _stub.verifyMeta  [ "<metadataFindings line>", ... ] returned by every quote-verify agent (default: none)
// Segment agents resolve each quote unit to the first full case cite in its footnote (from the
// ledger), so the quote side is plain.
import fs from 'node:fs'
const [,, wfPath, argsPath] = process.argv
const src = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', `return (async () => { ${src} })()`)
const args = JSON.parse(fs.readFileSync(argsPath, 'utf8'))
const stub = args._stub || {}
delete args._stub
const budget = { spent: () => 0, total: 0, remaining: () => 1e9 }
const labels = []
const logs = []
let reportPrompt = ''
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)))
const ids = (prompt, re) => [...prompt.matchAll(new RegExp(re.source, 'g'))].map((m) => Number(m[1]))
const noteOf = new Map((args.unitNotes || []).map(([i, n]) => [Number(i), n]))
const fullCiteIn = (n) => ((args.ledger || []).find((x) => x.n === n && x.k === 'case') || {}).c || ''
async function agent(prompt, opts) {
  const L = opts.label || ''
  labels.push(L || opts.phase)
  if (L.startsWith('segment')) {
    const m = prompt.match(/--ids (\d+) (\d+)/)
    const units = Array.from({ length: +m[2] - +m[1] }, (_, i) => +m[1] + i)
    return { resolutions: units.map((id) => ({ id, footnote: noteOf.get(id), quote: `quote ${id}`, source: fullCiteIn(noteOf.get(id)), kind: 'case', pincite: '' })) }
  }
  if (L.startsWith('exist-secondary')) {
    return { sources: [...prompt.matchAll(/- key (.+?) \| /g)].map((m) => ({ key: m[1], exists: true, basis: 'web', ...((stub.secondary || {})[m[1]] || {}) })) }
  }
  if (L.startsWith('exist')) {
    const cmd = prompt.split('\n').find((l) => l.includes('check_cite.py')) || ''
    const cites = [...cmd.matchAll(/"(\d+ [A-Za-z0-9. ]+ \d+)"/g)].map((m) => m[1])
    const ex = stub.existence || {}
    return { results: cites.filter((c) => ex[c] !== null).map((c) => ({ citation: c, exists: true, basis: 'courtlistener-api', ...(ex[c] || {}) })) }
  }
  if (L.startsWith('history')) {
    const h = stub.history || {}
    return { cases: [...prompt.matchAll(/- cite: ([^|]+?) \|/g)].map((m) => m[1].trim()).map((c) => ({ cite: c, status: 'checked', historyBasis: 'none-found', confidence: 'moderate', ...(h[c] || {}) })) }
  }
  if (L.startsWith('verify')) {
    const key = prompt.match(/SOURCE-BUNDLE KEY \(echo it back exactly\): (.+)/)[1].trim()
    const q = stub.quotes || {}
    return { sourceKey: key, sourceIdentified: 'stub source', fetchBasis: 'authoritative-reproduction', metadataFindings: stub.verifyMeta || [],
      verdicts: ids(prompt, /\[id (\d+)\]/).map((id) => ({ id, verdict: q[id] || 'verbatim', severity: 'low', basis: 'authoritative-reproduction' })) }
  }
  if (L.startsWith('zotero-sweep')) return { results: [] }
  if (L.startsWith('re-verify')) { const id = Number(L.split('#')[1]); return { id, upheld: true, verdict: 'mismatch', severity: 'high', reason: 'stands' } }
  if (opts.phase === 'Form') return { findings: [], conventions: [] }
  if (opts.phase === 'Report') { reportPrompt = prompt; return { report: '# report' } }
  throw new Error('unstubbed agent ' + L)
}
const out = await fn(args, budget, agent, parallel, () => {}, (m) => logs.push(m), null)
const section = (from, to) => { const i = reportPrompt.indexOf(from); return i < 0 ? '' : reportPrompt.slice(i, to ? reportPrompt.indexOf(to, i + 1) : undefined).trim() }
console.log(JSON.stringify({
  agents: labels,
  exitState: out.exitState,
  degradation: out.degradation,
  counts: out.counts,
  ledger: out.ledger.map((x) => ({ i: x.i, n: x.n, k: x.k, d: x.d, why: x.why || '' })),
  items: out.findings.items,
  reportCaseBlock: section('=== CASE NAME / YEAR DOES NOT MATCH', '=== URL FINDINGS'),
  reportExistence: section('=== CASE EXISTENCE ===', '=== CASE NAME / YEAR'),
  reportLimits: section('=== RUN LIMITS', 'Return ONLY'),
  reportHistory: section('=== SUBSEQUENT HISTORY & TREATMENT', 'NOT CHECKED / NOT RESOLVED'),
  reportAsksForSection: /Case name or year does not match the reporter cite/.test(reportPrompt) && /never write that case cites were confirmed with no issues/.test(reportPrompt),
  logs,
}))
