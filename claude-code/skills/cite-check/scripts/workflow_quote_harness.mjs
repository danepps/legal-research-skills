// Offline harness for the QUOTE side of cite-check.workflow.js (2026-11-15 review): the verify
// join, the re-verify gate and join, the artifact rule and the ledger, under
// stubbed agents. test_workflow_quotes.py drives it. Nothing here touches the network or a model.
//
//   node workflow_quote_harness.mjs <workflow.js> <args.json> <scenario>
//
// Baseline: every quote verbatim. Scenarios (what the stubbed agents do differently):
//   corrected     verify calls quote 0 a mismatch; the second checker says the first verdict was
//                 wrong (upheld=false) and the real finding is a syllabus quote
//   withdrawn     verify calls quote 0 a mismatch; the second checker finds it verbatim
//   wrong-echo    verify calls quote 0 a mismatch; the second checker upholds it but echoes id 1
//   foreign-id    the agent for quote 0's source also returns a verdict for quote 1, which
//                 belongs to another source; quote 1's own agent reports a mismatch
//   all-high      every quote a high-severity mismatch, upheld (the test sets the cost model so
//                 the budget fits only some of the second derivations)
//   exist-flaky   the case-existence agent dies once, then answers
//   exist-dead    the case-existence agent dies twice
import fs from 'node:fs'
const [,, wfPath, argsPath, scenario = 'baseline'] = process.argv
const src = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const fn = new Function('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', `return (async () => { ${src} })()`)
const args = JSON.parse(fs.readFileSync(argsPath, 'utf8'))
const budget = { spent: () => 0, total: 0, remaining: () => 1e9 }
const labels = []
const prompts = []
const logs = []
let reportPrompt = ''
let existCalls = 0
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)))
const ids = (prompt, re) => [...prompt.matchAll(new RegExp(re.source, 'g'))].map((m) => Number(m[1]))
const mismatch = (id) => ({ id, verdict: 'mismatch', severity: 'high', sourceText: 'what the source says', basis: 'authoritative-reproduction' })
const verbatim = (id) => ({ id, verdict: 'verbatim', severity: 'low', basis: 'authoritative-reproduction' })
async function agent(prompt, opts) {
  const L = opts.label || ''
  labels.push(L || opts.phase)
  prompts.push({ label: L, prompt })
  if (L.startsWith('segment')) {
    const m = prompt.match(/--ids (\d+) (\d+)/)
    const units = Array.from({ length: +m[2] - +m[1] }, (_, i) => +m[1] + i)
    return { resolutions: units.map((id) => ({ id, footnote: id + 1, quote: `quote ${id}`, source: `Case${id} v. Other, ${100 + id} U.S. ${200 + id}, ${205 + id} (19${50 + id})`, kind: 'case', pincite: String(205 + id) })) }
  }
  if (L.startsWith('exist-secondary')) return { sources: [...prompt.matchAll(/- key (.+?) \| /g)].map((m) => ({ key: m[1], exists: true, basis: 'web' })) }
  if (L.startsWith('exist')) {
    existCalls++
    if (scenario === 'exist-dead' || (scenario === 'exist-flaky' && existCalls === 1)) return null
    // the cites are the quoted arguments on the check_cite.py command line
    const cmd = prompt.split('\n').find((l) => l.includes('check_cite.py')) || ''
    return { results: [...cmd.matchAll(/"(\d+ [A-Za-z. ]+ \d+)"/g)].map((m) => ({ citation: m[1], exists: true, basis: 'courtlistener-api' })) }
  }
  if (L.startsWith('verify')) {
    const key = prompt.match(/SOURCE-BUNDLE KEY \(echo it back exactly\): (.+)/)[1].trim()
    const qids = ids(prompt, /\[id (\d+)\]/)
    const verdicts = qids.flatMap((id) => {
      if (['corrected', 'withdrawn', 'wrong-echo'].includes(scenario) && id === 0) return [mismatch(id)]
      if (scenario === 'all-high') return [mismatch(id)]
      if (scenario === 'foreign-id' && id === 0) return [verbatim(0), { ...verbatim(1), note: 'returned by the agent for another source' }]
      if (scenario === 'foreign-id' && id === 1) return [{ id, verdict: 'mismatch', severity: 'medium', sourceText: 'a real difference', basis: 'authoritative-reproduction' }]
      return [verbatim(id)]
    })
    return { sourceKey: key, sourceIdentified: 'stub source', fetchBasis: 'authoritative-reproduction', verdicts }
  }
  if (L.startsWith('re-verify')) {
    const id = Number(L.split('#')[1])
    if (scenario === 'corrected') return { id, upheld: false, verdict: 'syllabus_quote', severity: 'high', sourceText: 'the syllabus text', reason: 'verbatim in the syllabus, not the opinion' }
    if (scenario === 'withdrawn') return { id, upheld: false, verdict: 'verbatim', sourceText: 'the same words', reason: 'truncation: the footnote names a second source' }
    if (scenario === 'wrong-echo') return { id: id + 1, upheld: true, verdict: 'mismatch', severity: 'high', sourceText: 'what the source says', reason: 'stands' }
    return { id, upheld: true, verdict: 'mismatch', severity: 'high', sourceText: 'what the source says', reason: 'stands' }
  }
  if (opts.phase === 'Form') return { findings: [], conventions: [] }
  if (opts.phase === 'Report') { reportPrompt = prompt; return { report: '# report' } }
  throw new Error('unstubbed agent ' + L)
}
const out = await fn(args, budget, agent, parallel, () => {}, (m) => logs.push(m), null)
const section = (from, to) => { const i = reportPrompt.indexOf(from); return i < 0 ? '' : reportPrompt.slice(i, reportPrompt.indexOf(to, i + 1)).trim() }
console.log(JSON.stringify({
  scenario,
  agents: labels,
  exitState: out.exitState,
  degradation: out.degradation,
  counts: {
    quotesChecked: out.counts.quotesChecked, verbatim: out.counts.verbatim, mismatch: out.counts.mismatch, syllabus: out.counts.syllabus,
    artifactsCaught: out.counts.artifactsCaught, singleChecker: out.counts.highSeveritySingleChecker,
    casesChecked: out.counts.casesChecked, ledgerInstances: out.counts.ledgerInstances,
  },
  artifactsCaught: out.artifactsCaught,
  items: out.findings.items.filter((i) => i.kind === 'quote').map((i) => [i.footnote, i.verdict]),
  ledger: Object.fromEntries(out.ledger.map((x) => [x.n, x.d])),
  spend: { projected: out.spend.projected, cap: out.spend.softCap },
  reportHigh: section('=== HIGH-SEVERITY FINDINGS', '=== MEDIUM/LOW'),
  reportMedium: section('=== MEDIUM/LOW FINDINGS', '=== CITATION-METADATA'),
  reportSecondaryHeader: section('=== SECONDARY-SOURCE EXISTENCE', 'NOT FOUND'),
  // the scratch-file prefix each source-reading agent was given (one per agent, never shared)
  scratchPrefixes: prompts.filter((p) => /^(verify|re-verify)/.test(p.label)).map((p) => (p.prompt.match(/--out (\/tmp\/cc-[A-Za-z0-9_-]+)-src-/) || [])[1] || ''),
  genericScratch: prompts.some((p) => /\/tmp\/(src|q|sup|resup)-/.test(p.prompt)),
  reverifyNamesId: prompts.filter((p) => p.label.startsWith('re-verify')).every((p) => p.prompt.includes(`THE UNIT ID IS ${p.label.split('#')[1]} `)),
}))
