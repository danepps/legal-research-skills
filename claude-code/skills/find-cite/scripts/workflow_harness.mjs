// Offline harness for find-cite.workflow.js: runs the script with STUBBED agents and prints the
// result. test_workflow.py drives it. Nothing here touches the network or a model.
//
//   node workflow_harness.mjs <workflow.js> '<plan JSON>'
//
// The plan says what each stubbed agent does:
//   { "args": {...} | "<string>" | omitted for undefined,
//     "argsUndefined": true,                 (pass no args at all)
//     "scope": {authorityType, reason} | "die",
//     "search": { "cases": [candidate, ...] | "die", "scholarship": [...] | "die" },
//     "verify": { "<candidate citation>": <verification object> | "die" },
//                (a verification object with "dieOnce": true dies on the first call, answers on the retry),
//     "budgetTotal": number (optional; agent() throws once spent reaches it),
//     "perAgent": tokens charged per agent call (default 2000) }
// A verification agent is matched by the CANDIDATE line of its prompt; one with no entry in
// "verify" throws (an unstubbed call is a test bug).
import fs from 'node:fs'
const [,, wfPath, planJson = '{}'] = process.argv
const plan = JSON.parse(planJson)
const src = fs.readFileSync(wfPath, 'utf8').replace(/^export const meta/m, 'const meta')
const AF = Object.getPrototypeOf(async function () {}).constructor
const run = new AF('args', 'budget', 'agent', 'parallel', 'phase', 'log', 'pipeline', src)
let spent = 0
const per = plan.perAgent || 2000
const budget = {
  total: plan.budgetTotal || null,
  spent: () => spent,
  remaining: () => (plan.budgetTotal ? Math.max(0, plan.budgetTotal - spent) : Infinity),
}
const labels = []
const calls = {}
const opts = {}
const prompts = {}
const logs = []
const unstubbed = [] // the workflow catches agent() throws (as a spent budget), so record them here
async function agent(prompt, o) {
  const L = o.label || o.phase
  if (plan.budgetTotal && spent >= plan.budgetTotal) throw new Error('budget exhausted')
  labels.push(L)
  calls[L] = (calls[L] || 0) + 1
  opts[L] = { model: o.model, effort: o.effort, phase: o.phase }
  prompts[L] = prompt
  spent += per
  if (L === 'scope') {
    if (plan.scope === 'die' || plan.scope == null) return null
    return plan.scope
  }
  if (L.startsWith('search:')) {
    const lane = L.split(':')[1]
    const s = (plan.search || {})[lane]
    if (s === 'die' || s == null) return null
    return { candidates: s }
  }
  if (L.startsWith('verify:')) {
    const cand = (prompt.match(/^CANDIDATE: (.+)$/m) || [])[1]
    const v = (plan.verify || {})[cand]
    if (v === undefined) { unstubbed.push(L + ' ' + cand); throw new Error('unstubbed verification for ' + cand) }
    if (v === 'die') return null
    if (v && v.dieOnce && calls[L] === 1) return null
    if (v && v.dieOnce) { const { dieOnce, ...rest } = v; return rest }
    return v
  }
  unstubbed.push(L)
  throw new Error('unstubbed agent ' + L)
}
const parallel = async (fns) => Promise.all(fns.map((f) => f().catch(() => null)))
const args = plan.argsUndefined ? undefined : plan.args
try {
  const out = await run(args, budget, agent, parallel, () => {}, (m) => logs.push(m), null)
  console.log(JSON.stringify({ ok: true, out, labels, calls, opts, logs, unstubbed,
    verifyPrompt: Object.entries(prompts).filter(([k]) => k.startsWith('verify:')).map(([, v]) => v)[0] || '',
    searchPrompts: Object.fromEntries(Object.entries(prompts).filter(([k]) => k.startsWith('search:'))) }))
} catch (e) {
  console.log(JSON.stringify({ ok: false, message: String(e && e.message), agents: labels.length, labels }))
}
