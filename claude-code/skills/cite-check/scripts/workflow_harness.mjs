// Offline harness for cite-check.workflow.js: runs the workflow with STUBBED agents so the
// accounting that no Python test can see (verdict acceptance, the re-verify gate, ledger
// join, counts, the findings export) is covered by the offline suite. test_workflow_support.py
// drives it. Nothing here touches the network or a model.
//
//   node workflow_harness.mjs <workflow.js> <args.json> <scenario>
//
// Scenarios (what the stubbed agents do; everything else is the same deterministic baseline):
//   baseline          every support unit supported, with full evidence
//   adverse           units 0 and 1 not_supported/contradicted; reviewer upholds both with evidence
//   budget-tight      as "adverse", but the budget runs out before the support re-verify
//   lost-reviewer     as "adverse", but the reviewer returns nothing
//   bad-results       the verify agent returns a verdict under a wrong source key; a dedicated
//                     agent returns one without a passage, one with a citation-only basis, one
//                     for an out-of-scope id, and one with an invented claim
//   downgrade         unit 0 contradicted; the reviewer corrects it to supported_qualified
//   retracted         unit 0 contradicted; the reviewer retracts it (supported) with evidence
import fs from 'node:fs'
const [,, wfPath, argsPath, scenario = 'baseline'] = process.argv
const src = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', `return (async () => { ${src} })()`)
const args = JSON.parse(fs.readFileSync(argsPath, 'utf8'))
let spent = 0
let currentPhase = ''
const budget = {
  spent: () => spent,
  total: 0,
  remaining: () => 1e9,
}
if (scenario === 'budget-tight') {
  // a hard user ceiling that is exhausted once the Re-verify phase starts
  budget.total = 1
  budget.remaining = () => (currentPhase === 'Re-verify' ? 0 : 1e9)
}
const phases = []
const phase = (t) => { phases.push(t); currentPhase = t }
const logs = []
const log = (m) => logs.push(m)
const parallel = async (fns) => Promise.all(fns.map((f) => f()))
const ids = (prompt, re) => [...prompt.matchAll(new RegExp(re.source, 'g'))].map((m) => Number(m[1]))
const labels = []
const evidence = (extra = {}) => ({ posture: 'holding', locator: 'p. 436', sourceText: 'the power to tax involves the power to destroy', reason: 'stub', basis: 'authoritative-reproduction', claimBasis: 'anchor.sentence', ...extra })
const adverseFor = (id) => (id === 0 ? 'not_supported' : id === 1 ? 'contradicted' : 'supported')
const supportVerdict = (id) => {
  if (scenario === 'baseline') return { id, verdict: 'supported', ...evidence() }
  if (scenario === 'bad-results') {
    if (id === 0) return { id, verdict: 'supported', ...evidence({ sourceText: '' }) }          // no passage
    if (id === 1) return { id, verdict: 'supported', ...evidence({ basis: 'citation-only' }) }  // not full text
    if (id === 2) return { id, verdict: 'supported', ...evidence({ claim: 'An invented stronger claim.' }) }
    if (id === 3) return { id, verdict: 'not_supported', ...evidence() }                       // adverse, no search
    return { id, verdict: 'supported', ...evidence() }
  }
  const v = ['adverse', 'budget-tight', 'lost-reviewer'].includes(scenario) ? adverseFor(id) : (scenario === 'downgrade' || scenario === 'retracted') && id === 0 ? 'contradicted' : 'supported'
  return { id, verdict: v, ...evidence(v === 'supported' ? {} : { searched: 'searched "tax", "destroy": only the general rule appears' }) }
}
async function agent(prompt, opts) {
  spent += 3000
  labels.push(opts.label || opts.phase)
  const L = opts.label || ''
  if (L.startsWith('segment')) {
    const m = prompt.match(/--ids (\d+) (\d+)/)
    const units = m ? Array.from({ length: +m[2] - +m[1] }, (_, i) => +m[1] + i) : (prompt.match(/--pick ([\d ]+)/) || [, ''])[1].trim().split(/\s+/).filter(Boolean).map(Number)
    return { resolutions: units.map((id) => ({ id, footnote: 1, quote: 'q', source: 'McCulloch v. Maryland, 17 U.S. (4 Wheat.) 316, 431 (1819)', kind: 'case', pincite: '431' })) }
  }
  if (L.startsWith('exist-secondary')) return { sources: [...prompt.matchAll(/- key (\S+)/g)].map((m) => ({ key: m[1], exists: true, basis: 'web' })) }
  if (L.startsWith('exist')) return { results: [...prompt.matchAll(/"(\d+ [A-Za-z. ]+ \d+)"/g)].map((m) => ({ citation: m[1], exists: true, caseName: 'X v. Y', dateFiled: '1819-03-06', basis: 'courtlistener-api' })) }
  if (L.startsWith('history')) return { cases: [...prompt.matchAll(/- cite: ([^|]+?) \|/g)].map((m) => ({ cite: m[1].trim(), status: 'checked', historyBasis: 'none-found', confidence: 'moderate' })) }
  if (L.startsWith('verify-tail')) return { sources: [] }
  if (L.startsWith('verify')) {
    const key = prompt.match(/SOURCE-BUNDLE KEY \(echo it back exactly\): (.+)/)[1].trim()
    const qids = ids(prompt, /\[id (\d+)\]/)
    const sids = ids(prompt, /\[support id (\d+)\]/)
    return { sourceKey: key, sourceIdentified: 'CourtListener', fetchBasis: 'authoritative-reproduction',
      verdicts: qids.map((id) => ({ id, verdict: 'verbatim', severity: 'low', basis: 'authoritative-reproduction' })),
      supportVerdicts: sids.map((id) => ({ ...supportVerdict(id), sourceKey: scenario === 'bad-results' ? 'wrong-source' : key })) }
  }
  if (L.startsWith('support-tail') || L.startsWith('support')) {
    const keys = [...prompt.matchAll(/SOURCE-BUNDLE KEY \(echo exactly\): (.+)/g)].map((m) => m[1].trim())
    const sids = ids(prompt, /\[support id (\d+)\]/)
    const perKey = keys.map((k) => ({ sourceKey: k, supportVerdicts: [] }))
    // assign each id to the bundle whose block lists it
    const blocks = prompt.split(/SOURCE \(resolved/).slice(1)
    blocks.forEach((b, i) => { for (const id of ids(b, /\[support id (\d+)\]/)) perKey[i].supportVerdicts.push(supportVerdict(id)) })
    if (scenario === 'bad-results') perKey[0].supportVerdicts.push({ id: 999, verdict: 'supported', ...evidence() })
    if (!sids.length) return L.startsWith('support-tail') ? { sources: perKey } : perKey[0]
    return L.startsWith('support-tail') ? { sources: perKey } : perKey[0]
  }
  if (L.startsWith('re-verify-support')) {
    const id = Number(L.split('#')[1])
    if (scenario === 'lost-reviewer') return null
    if (scenario === 'downgrade') return { id, upheld: false, verdict: 'supported_qualified', posture: 'dissent', sourceText: 'the dissent says so', locator: 'p. 440', reason: 'posture' }
    if (scenario === 'retracted') return { id, upheld: false, verdict: 'supported', sourceText: 'the court held exactly this', locator: 'p. 431', reason: 'paraphrased-claim' }
    return { id, upheld: true, verdict: adverseFor(id), sourceText: 'reviewer passage', locator: 'p. 436', searched: 'reviewer searched "tax", "destroy"', reason: 'stands' }
  }
  if (L.startsWith('re-verify')) { const id = Number(L.split('#')[1]); return { id, upheld: true, verdict: 'mismatch', severity: 'high', reason: 'stands' } }
  if (opts.phase === 'Form') return { findings: [], conventions: [] }
  if (opts.phase === 'Report') { if (process.env.REPORT_PROMPT_OUT) fs.writeFileSync(process.env.REPORT_PROMPT_OUT, prompt); return { report: '# report' } }
  throw new Error('unstubbed agent ' + L)
}
const out = await fn(args, budget, agent, parallel, phase, log, null)
const result = {
  scenario,
  phases,
  agents: labels,
  exitState: out.exitState,
  degradation: out.degradation,
  support: out.counts.support,
  ledger: Object.fromEntries(out.ledger.map((x) => [`${x.n}:${x.i}`, x.d])),
  findings: out.support.map((f) => ({ id: f.id, verdict: f.verdict, first: f.firstVerdict, artifact: !!f.artifact, unaudited: !!f.unaudited, rejected: !!f.rejected, reverified: !!f.reverified, claim: f.claim, claimBasis: f.claimBasis, claimNote: f.claimNote || '' })),
  items: out.findings.items.filter((i) => i.kind.startsWith('support')).map((i) => [i.kind, i.verdict, i.footnote]),
  exported: out.findings.support,
}
console.log(JSON.stringify(result))
