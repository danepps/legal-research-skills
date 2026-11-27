export const meta = {
  name: 'find-cite',
  description: 'Fill one footnote: find two to four verified authorities (cases and/or scholarship) for a single proposition, verify each at the source, and return structured cites plus a footnote-ready Markdown entry',
  phases: [
    { title: 'Scope', detail: 'resolve the authority type (a rule, else one small classifier agent)' },
    { title: 'Search', detail: 'one search-only sweep per lane (cases, scholarship)' },
    { title: 'Verify', detail: 'one agent per chosen candidate: lookup, open the source, pincite, quotation receipt, treatment' },
    { title: 'Assemble', detail: 'rank, render the citations and the entry in code; no model writes the deliverable' },
  ],
}

// ---- Why this is a workflow (2026-11-23) -------------------------------------------------
// find-cite used to run inline in the lead session and told the lead to fetch pages. In Claude
// CLI 2.1.330 the lead is not offered WebFetch (E0 record, Find a cite); workflow agents are. A
// workflow also returns fields, not prose: the host appends `entry` to a running document and
// lists `cites`. Every string in `entry` is rendered here from the verified fields: no model
// writes it, and no authority appears in it that is not in `cites`.
//
// ---- args ------------------------------------------------------------------------------
// { skillsDir (required), proposition (required), authorityType: cases|scholarship|both|auto
//   (default auto), constraints, jurisdiction, asOfDate, zoteroServer, runTag, scratchDir }
// Unusable arguments throw before any agent starts.
let A = args
if (typeof A === 'string') {
  try { A = JSON.parse(A) } catch (e) {
    throw new Error(`find-cite workflow: the arguments arrived as a string that is not valid JSON (${e.message}). No agent was started. Launch the workflow again with args as a JSON object, not a string.`)
  }
}
const isObj = (v) => !!v && typeof v === 'object' && !Array.isArray(v)
const KNOWN_ARGS = ['skillsDir', 'proposition', 'authorityType', 'constraints', 'jurisdiction', 'asOfDate', 'zoteroServer', 'runTag', 'scratchDir']
const TYPES = ['cases', 'scholarship', 'both', 'auto']
const argProblems = []
if (!isObj(A)) argProblems.push('args is missing or is not an object')
else {
  if (typeof A.skillsDir !== 'string' || !A.skillsDir.trim()) argProblems.push('skillsDir (the plugin\'s skills folder) is missing')
  else if (/["`\n]|\$\(/.test(A.skillsDir)) argProblems.push('skillsDir contains a quote, backtick, line break or $( and cannot be used in a shell command')
  if (typeof A.proposition !== 'string' || !A.proposition.trim()) argProblems.push('proposition is missing or empty')
  else if (A.proposition.length > 3000) argProblems.push('proposition is longer than 3,000 characters; pass the one sentence the footnote hangs on')
  if (A.authorityType != null && !TYPES.includes(String(A.authorityType).trim().toLowerCase())) argProblems.push(`authorityType must be one of ${TYPES.join(', ')} (got ${JSON.stringify(A.authorityType)})`)
  for (const k of ['constraints', 'jurisdiction', 'asOfDate', 'runTag']) if (A[k] != null && typeof A[k] !== 'string') argProblems.push(`${k} must be a string`)
  if (A.zoteroServer != null && (typeof A.zoteroServer !== 'string' || !/^[A-Za-z0-9_.-]+$/.test(A.zoteroServer))) argProblems.push('zoteroServer must be an MCP server name (letters, digits, dot, dash, underscore)')
  if (A.scratchDir != null && (typeof A.scratchDir !== 'string' || !/^\/+[^/]/.test(A.scratchDir.trim()) || /["`$\\\n\r]/.test(A.scratchDir))) argProblems.push('scratchDir must be the absolute path of a folder, with no double quote, backtick, dollar sign, backslash or line break')
  const unknown = Object.keys(A).filter((k) => !KNOWN_ARGS.includes(k))
  if (unknown.length) argProblems.push(`unknown argument${unknown.length === 1 ? '' : 's'} ${unknown.join(', ')} (known: ${KNOWN_ARGS.join(', ')})`)
}
if (argProblems.length) throw new Error(`find-cite workflow: unusable arguments (${argProblems.join('; ')}). No agent was started. Launch the workflow again with args as a JSON object.`)

const SKILLS = A.skillsDir.trim().replace(/\/+$/, '')
const PROPOSITION = A.proposition.trim()
const REQUESTED_TYPE = String(A.authorityType || 'auto').trim().toLowerCase()
const CONSTRAINTS = (A.constraints || '').trim()
const JURISDICTION = (A.jurisdiction || '').trim()
const AS_OF = (A.asOfDate || '').trim() || 'today'
const ZOTERO = (A.zoteroServer || '').trim()

const CHECK_CITE = `${SKILLS}/legal-research/check_cite.py`
const CL_TOOLS = `${SKILLS}/legal-research/cl_case_tools.py`
const PROBE = `${SKILLS}/legal-research/probe_sources.py`
const FETCH_PAGE = `${SKILLS}/legal-research/fetch_page.py`
const VERIFY_QUOTES = `${SKILLS}/cite-check/scripts/verify_quotes.py`
const RECEIPT = `${SKILLS}/find-cite/scripts/quote_receipt.py`

// Scratch-file tag: deterministic (Date.now/Math.random are unavailable), unique per input.
const fnv = (s) => {
  let h = 0x811c9dc5
  for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0 }
  return h >>> 0
}
const RUN_TAG = String(A.runTag || '').replace(/[^A-Za-z0-9_-]/g, '').slice(0, 24) ||
  fnv(`${PROPOSITION}|${REQUESTED_TYPE}|${CONSTRAINTS}|${JURISDICTION}|${AS_OF}`).toString(36)
// Where the agents' temporary files go (1.6.16). /tmp unless args.scratchDir names another folder:
// a host that confines a run to its own folder (the Dubitante app) passes one inside it, because
// such a run cannot write /tmp. The folder must exist. A path with a space or another character
// the shell would split on is written inside double quotes, so the same text works in a command
// and in the Read tool's file_path once the quotes are dropped.
const SCRATCH_DIR = String(A.scratchDir || '').trim().replace(/\/+$/, '') || '/tmp'
const SCRATCH_Q = /^[A-Za-z0-9_.\/@%+=:,-]+$/.test(SCRATCH_DIR) ? '' : '"'
const scratch = (slot, suffix = '') => `${SCRATCH_Q}${SCRATCH_DIR}/fc-${RUN_TAG}-${slot}${suffix}${SCRATCH_Q}`
// Every agent that can save a file gets this. Agents given no path made one up (/tmp/<case>.txt),
// which two agents can collide on and which a confined run refuses (2026-11-26 trial).
const tempFiles = (slot) => `TEMPORARY FILES: every file you save (a page, a PDF, extracted text, a script's output, a
quotation) gets one of the paths named above or, for anything else, a name that starts with
  ${scratch(slot, '-')}
(for example ${scratch(slot, '-page.html')}). Write nowhere else: not another name in /tmp, not the
working directory, not the home folder. Other agents are running at the same time, and some hosts
refuse a write anywhere else. Do not cd to another folder.${SCRATCH_Q ? '\nThe folder\'s path has a space or another special character in it: keep the double quotes around it in every shell command.' : ''}`

// ---- models, caps, budget -------------------------------------------------------------
// Model constants follow legal-research.workflow.js: Haiku only where a weak read cannot
// corrupt the result (the search-only sweeps, whose candidates are re-judged by a verifier,
// and the no-tool authority-type classifier); Sonnet for every agent that reads a source and
// decides what ships. No stage inherits the session model.
const SCOUT_MODEL = 'haiku'
const VERIFY_MODEL = 'sonnet'
// Agent cap: at most 12 agent starts per run, retries included. A normal run uses at most
// 1 classifier + 2 sweeps + 5 verifiers + 2 top-up verifiers = 10; the rest is retry room.
const MAX_AGENT_STARTS = 12
const VERIFY_CAP = 5        // first verification round, all lanes together
const TOPUP_CAP = 2         // one top-up round when fewer than MIN_CITES survive
const MIN_CITES = 2
const MAX_DELIVER = 4
const CANDIDATES_PER_LANE = 6
const QUOTE_MAX = 250       // characters; a footnote quotation, and within the verifier's excerpt
const SOFT_CAP = 200_000    // output tokens for this run when the user set no budget
const PER_VERIFY = 20_000
const SPENT0 = budget.spent()
const remainingTokens = () => (budget.total ? budget.remaining() : Math.max(0, SOFT_CAP - (budget.spent() - SPENT0)))

const degradation = []      // plain sentences; non-empty exactly when exitState has limits
let starts = 0
const capCut = []           // labels the agent cap stopped
let budgetStopped = 0
// One agent start, counted against the cap. Returns {value, failure}: failure is null,
// 'died' (agent() returned null), 'cap' or 'budget' (agent() threw: the budget is spent).
async function spawn(label, prompt, opts) {
  if (starts >= MAX_AGENT_STARTS) { capCut.push(label); return { value: null, failure: 'cap' } }
  starts++
  try {
    const value = await agent(prompt, { label, ...opts })
    return { value: value || null, failure: value ? null : 'died' }
  } catch (e) {
    budgetStopped++
    return { value: null, failure: 'budget' }
  }
}
// A dead agent is retried once; a second death is returned for the caller to record.
async function retryOnce(label, prompt, opts) {
  let r = await spawn(label, prompt, opts)
  if (r.failure === 'died') { log(`${label} died — retrying once`); r = await spawn(label, prompt, opts) }
  return r
}

// ---- shared text ----------------------------------------------------------------------
const norm = (s) => String(s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
const CITE_TRIPLE = /\b(\d{1,4})\s+(U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?[23]d)?|F\.\s?App'?x|So\.(?:\s?[23]d)?|P\.(?:\s?[23]d)?|A\.(?:\s?[23]d)?|N\.[EW]\.(?:\s?[23]d)?|S\.[EW]\.(?:\s?[23]d)?|Cal\.\s?(?:App\.\s?)?[2-5]th|[A-Z][A-Za-z.]{1,20}\s?L\.\s?(?:Rev|J)\.)\s+(\d{1,5})\b/g
const citeKey = (s) => {
  const m = [...String(s || '').matchAll(CITE_TRIPLE)][0]
  return m ? `${m[1]} ${m[2].toLowerCase().replace(/[^a-z0-9]/g, '')} ${m[3]}` : norm(s).slice(0, 60)
}

const ACCESS = `ACCESS DISCIPLINE: at most 3 fetch attempts per source, through WebSearch, WebFetch and the
capped fetcher only. Never browser automation, library proxies, SSO or login flows. A paywalled or
bot-walled source is an honest opened=false; say which wall in notes. WebFetch returns a model's
summary, not the page: never copy a quotation or a page number out of a WebFetch result.`

const SOURCES = `FREE / OPEN-WEB SOURCES ONLY (no Westlaw or Lexis). Opinions and articles that postdate your
training data are real; verify them like any other and never discount them as unfamiliar.
- Cases: CourtListener, Caselaw Access Project static HTML (https://static.case.law/us/<vol>/html/<first
  page padded to 4 digits>-01.html carries official U.S. Reports star pagination; other reporters by slug,
  e.g. /f2d/), Library of Congress U.S. Reports scans (tile.loc.gov; PDFs only through the capped fetcher),
  supremecourt.gov slip opinions, Cornell LII, FindLaw, Google Scholar. Justia and some CourtListener
  pages refuse automated fetches.
- Scholarship: law-school digital-commons repositories, authors' faculty pages, journal websites, SSRN
  abstract pages, Google Scholar, HeinOnline citation pages (no login).
TOOLS: if WebSearch, WebFetch or Bash is not callable, first run ToolSearch with query
"select:WebSearch,WebFetch,Bash".`

const ZOTERO_SEARCH = ZOTERO
  ? `ZOTERO: search the user's Zotero library FIRST (server "${ZOTERO}"): run ToolSearch with query
"select:mcp__${ZOTERO}__zotero_search_items,mcp__${ZOTERO}__zotero_item_metadata", then run a few keyword
searches. A library item is a candidate with reliable metadata, nothing more: put its item key in
zoteroKey. If the tools are unavailable or error, go on with the web.`
  : 'ZOTERO: no Zotero library was named for this run. Do not search Zotero or call any Zotero tool.'

const CONTEXT = `PROPOSITION (the sentence the footnote hangs on): ${PROPOSITION}
${CONSTRAINTS ? `CONSTRAINTS FROM THE AUTHOR (honor them): ${CONSTRAINTS}\n` : ''}JURISDICTION: ${JURISDICTION || 'not stated — infer it from the proposition (federal constitutional and SCOTUS-focused work usually means the Supreme Court)'}
AS OF: ${AS_OF}`

// ---- schemas ---------------------------------------------------------------------------
const SCOPE_SCHEMA = {
  type: 'object', required: ['authorityType', 'reason'],
  properties: {
    authorityType: { type: 'string', enum: ['cases', 'scholarship', 'both'] },
    reason: { type: 'string', description: 'one sentence: which kind of proposition this is' },
  },
}
const CANDIDATES_SCHEMA = {
  type: 'object', required: ['candidates'],
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object', required: ['citation', 'why'],
        properties: {
          kind: { type: 'string', enum: ['case', 'article', 'note', 'book', 'other'] },
          citation: { type: 'string', description: 'best citation readable off the search result or library record' },
          url: { type: 'string' },
          zoteroKey: { type: 'string' },
          supportingLanguage: { type: 'string', description: 'the snippet or abstract language that suggests support (NOT a quotation)' },
          why: { type: 'string', description: 'one line on why it fits' },
          fit: { type: 'string', enum: ['direct', 'close', 'adjacent'] },
          role: { type: 'string', enum: ['canonical', 'reaffirmation', 'recent', 'leading', 'supporting'] },
          venueTier: { type: 'integer', description: 'scholarship: 1 flagship general law review or top peer-edited journal; 2 strong secondary or specialty; 3 other' },
          studentNote: { type: 'boolean' },
        },
      },
    },
  },
}
const SIGNALS = ['none', 'See', 'See, e.g.,', 'See also', 'Cf.', 'See generally', 'Accord']
const VERIFY_SCHEMA = {
  type: 'object',
  required: ['exists', 'kind', 'opened', 'supports', 'paraphrase', 'fit', 'basis'],
  properties: {
    exists: { type: 'boolean', description: 'the authority exists as cited (after any correction below)' },
    existenceBasis: { type: 'string' },
    kind: { type: 'string', enum: ['case', 'article', 'note', 'book', 'other'] },
    caseName: { type: 'string', description: 'case: Bluebook short-form-ready case name, e.g. Mathews v. United States' },
    reporterCite: { type: 'string', description: 'case: volume, reporter, first page, e.g. 485 U.S. 58' },
    courtYear: { type: 'string', description: 'case: the parenthetical contents, e.g. 1988 or 9th Cir. 2018' },
    subsequentHistory: { type: 'string', description: "case: e.g. aff'd, 500 U.S. 1 (1991); empty if none" },
    authors: { type: 'string' },
    title: { type: 'string' },
    volume: { type: 'string' },
    journal: { type: 'string', description: 'Bluebook abbreviation, e.g. Harv. L. Rev.' },
    firstPage: { type: 'string' },
    year: { type: 'string' },
    edition: { type: 'string', description: 'book: e.g. 3d ed.; empty if none' },
    citationText: { type: 'string', description: 'kind other: the full citation, without a pincite' },
    opened: { type: 'boolean', description: 'you read the text of the source itself' },
    url: { type: 'string', description: 'the URL you consulted (the text you read, else the record that confirmed existence)' },
    pincite: { type: 'string', description: 'page(s) where the supporting passage sits, e.g. 62 or 62-63' },
    pinciteSeen: { type: 'boolean', description: 'true ONLY if you saw that page number for the passage in the source text' },
    opinionPart: { type: 'string', enum: ['majority', 'per curiam', 'plurality', 'concurrence', 'dissent', 'n/a'] },
    opinionAuthor: { type: 'string', description: 'surname of the justice/judge for a plurality, concurrence or dissent' },
    supports: { type: 'string', enum: ['squarely', 'partially', 'no', 'unknown'] },
    paraphrase: { type: 'string', description: 'Bluebook explanatory parenthetical, starting with a participle (holding that ...); no quotation marks' },
    quote: { type: 'string', description: 'optional: the exact text you put in the quote file; empty when none' },
    quoteReceipt: {
      type: 'object',
      properties: {
        id: { type: 'string' }, status: { type: 'string' }, quote_hash: { type: 'string' },
        match_excerpt: { type: 'string' }, text_from: { type: 'string' }, source: { type: 'string' },
        // Copied as printed: an integer, a boolean or null. Left untyped so a null never fails
        // validation; the script checks the values itself (Number.isInteger, === false).
        source_sha256: { type: 'string' }, page: { description: 'integer or null' }, page_end: { description: 'integer or null' },
        pincite_ok: { description: 'true, false or null' },
      },
    },
    fit: { type: 'string', description: 'one line: canonical cite / recent reaffirmation / leading article / ...' },
    shortfall: { type: 'string', description: 'if support is partial: how it falls short of the proposition' },
    basis: { type: 'string', description: 'a few words on what you actually did, e.g. opened at the pincite on CAP' },
    treatmentChecked: { type: 'boolean' },
    treatment: { type: 'string' },
    studentNote: { type: 'boolean' },
    venueTier: { type: 'integer' },
    signal: { type: 'string', enum: SIGNALS },
    notes: { type: 'string' },
  },
}

// ---- 1. authority type -----------------------------------------------------------------
// The old skill's rule: read the type off the KIND of proposition. Clear signals are settled
// here in code; anything else goes to one small classifier agent.
const RX_SCHOLARSHIP = /\b(scholars?|commentators?|academics?|(?:the|this|a) literature|theorists?|(?:have|has been) argued|conventional (?:account|wisdom|view)|standard (?:account|view)|empirical(?:ly)?|studies (?:show|find|suggest)|critics)\b/i
const RX_DOCTRINE = /\b(?:the (?:supreme )?court (?:has )?(?:held|holds|ruled|recognized)|(?:is|are) (?:well[- ])?(?:settled|established) (?:law|that)|black[- ]letter)\b/i
const RX_CHARACTERIZATION = /\b(skeptic(?:al|ism)|incoheren(?:t|ce)|famously|has grown|increasingly|retreat(?:ed)?|erod(?:ed|ing)|in recent (?:years|decades))\b/i
function typeByRule(p) {
  const s = RX_SCHOLARSHIP.test(p), d = RX_DOCTRINE.test(p), c = RX_CHARACTERIZATION.test(p)
  if (c && !s) return { type: 'both', basis: 'rule: a characterization of doctrine or the Court; cases as the evidence, plus a scholar making the same observation' }
  if (s && !d && !c) return { type: 'scholarship', basis: 'rule: a claim about the literature or the scholarly debate' }
  if (d && !s && !c) return { type: 'cases', basis: 'rule: a statement of doctrine' }
  return null
}

let authorityType = REQUESTED_TYPE
let authorityTypeBasis = 'requested'
if (REQUESTED_TYPE === 'auto') {
  phase('Scope')
  const ruled = typeByRule(PROPOSITION)
  if (ruled) { authorityType = ruled.type; authorityTypeBasis = ruled.basis }
  else {
    const r = await retryOnce('scope', `Classify ONE proposition for a law-review footnote by the kind of authority it needs. Use no tools.

${CONTEXT}

Read the type off the KIND of proposition, not off a default:
- Pure doctrine ("the Court has held...", black-letter statements, vote lineups) -> cases.
- Claims about the literature, theory or empirics ("scholars have argued...", "the conventional account is...") -> scholarship.
- Characterizations of doctrine or the Court ("the Court has grown skeptical of...", "this doctrine is famously incoherent") -> both.
- Framing or background claims -> both.
If the constraints above say which they want, that controls. Return the type and one sentence on why.`, { phase: 'Scope', schema: SCOPE_SCHEMA, model: SCOUT_MODEL, effort: 'low' })
    if (r.value && ['cases', 'scholarship', 'both'].includes(r.value.authorityType)) {
      authorityType = r.value.authorityType
      authorityTypeBasis = `classifier: ${String(r.value.reason || '').replace(/["“”]/g, "'").trim()}`
    } else {
      authorityType = 'both'
      authorityTypeBasis = 'default: the classifier did not return, so both cases and scholarship were searched'
      degradation.push(r.failure === 'cap' ? 'The agent cap stopped the authority-type classifier; both cases and scholarship were searched.' : 'The authority-type classifier failed twice; both cases and scholarship were searched by default.')
    }
  }
}
const LANES = authorityType === 'both' ? ['cases', 'scholarship'] : [authorityType]
const LANE_WORD = { cases: 'case', scholarship: 'scholarly source' }
log(`Authority type: ${authorityType} (${authorityTypeBasis}).`)

// ---- 2. search (one sweep per lane) ----------------------------------------------------
const sweepPrompt = (lane) => lane === 'cases'
  ? `You are a fast case-law scout for ONE footnote. SEARCH ONLY: use WebSearch (and nothing that opens a page).

${CONTEXT}

- Prefer the authority that controls in the proposition's jurisdiction and supports it directly. A
  state-law or circuit-specific proposition gets its own controlling authority first, not a looser
  Supreme Court analogy.
- For a well-worn proposition there is usually a CANONICAL cite (the case everyone cites): find that one
  first (queries like "<proposition keywords>" Supreme Court held, or the proposition's signature
  phrase), then one or two reinforcing or more recent cases. Mark the canonical one role=canonical.
- Fit over fame: a case squarely on the proposition outranks a famous adjacent one.
- Report up to ${CANDIDATES_PER_LANE} candidates, best first, each with the best citation the result shows,
  its URL, the snippet language that suggests support (it is NOT a quotation), one line on fit.
- Never invent a citation, volume, page, holding or quotation. Stop when two searches in a row add nothing.
${SOURCES}`
  : `You are a fast scholarship scout for ONE footnote. SEARCH ONLY: search results, abstracts and library
records; open no full texts.

${CONTEXT}

${ZOTERO_SEARCH}
Then search the web (Google Scholar, SSRN, digital-commons repositories, journal sites). Ranking:
1. Recognized scholars in flagship general law reviews (Harvard, Yale, Stanford, Columbia, Chicago, NYU,
   Michigan, Penn, Virginia, California, Georgetown, Duke, Northwestern, Cornell, Texas, Vanderbilt) and top
   peer-edited journals (Supreme Court Review, Journal of Legal Studies, Journal of Legal Analysis): venueTier 1.
2. Well-cited work in strong secondary or specialty journals: venueTier 2. Anything else: venueTier 3.
3. Student notes and comments are a last resort: set studentNote=true; report one only if nothing better fits.
Fit comes first: a piece squarely on the proposition outranks a famous one that is merely adjacent. Among
pieces that genuinely fit, prefer the more influential author and venue (citation counts are a fair proxy).
Report up to ${CANDIDATES_PER_LANE} candidates, best first: citation (author, title, volume, journal, first
page, year as the record shows them), URL (prefer a repository or faculty-page copy over SSRN), the
abstract language that suggests support (NOT a quotation), one line on fit. Never invent anything.
${SOURCES}`

// Deterministic ranking of a lane's candidates: student notes last, then fit, role, venue, order.
const FIT_RANK = { direct: 0, close: 1, adjacent: 2 }
const ROLE_RANK = { canonical: 0, leading: 1, reaffirmation: 2, recent: 3, supporting: 4 }
const rankCandidates = (cands) => cands
  .map((c, i) => ({ c, i }))
  .sort((a, b) =>
    (a.c.studentNote ? 1 : 0) - (b.c.studentNote ? 1 : 0) ||
    (FIT_RANK[a.c.fit] ?? 1) - (FIT_RANK[b.c.fit] ?? 1) ||
    (ROLE_RANK[a.c.role] ?? 4) - (ROLE_RANK[b.c.role] ?? 4) ||
    (a.c.venueTier || 2) - (b.c.venueTier || 2) ||
    a.i - b.i)
  .map((x) => x.c)

const QUOTAS = LANES.length === 2 ? { cases: 3, scholarship: 2 } : { [LANES[0]]: 4 }

// ---- 3. verification -------------------------------------------------------------------
const quoteSteps = (slot) => `QUOTATION (optional; checked by script, never by you). If one continuous sentence or phrase of
at most 40 words, with no double quotation marks inside and no omissions, states the proposition well,
you may propose it. Copy it from the text you saved, never from memory or a WebFetch summary:
  cat > ${scratch(slot, '-q.txt')} <<'FC_QUOTE_END'
  <the quotation exactly as it appears in the text>
  FC_QUOTE_END
  python3 "${RECEIPT}" --id ${slot} --quote-file ${scratch(slot, '-q.txt')} --source ${scratch(slot, '-src.txt')} --url "<the URL the text came from>" [--pincite <page>] [--first-page <printed number of a PDF's first page>]
It prints the matched source passage and a final line RECEIPT {json}. Copy that JSON into quoteReceipt
field for field, and set quote to exactly the text in the quote file. If the status is not_found, fix
the copy from the text at most twice; if it still fails, leave quote empty and drop quoteReceipt: the
paraphrase will be used. The script's status is the answer; do not argue with it.`

const verifyPrompt = (lane, c, slot) => lane === 'cases'
  ? `You are verifying ONE candidate case for a law-review footnote. An unverified citation must never ship,
so report exactly what you confirmed and nothing more.

${CONTEXT}

CANDIDATE: ${c.citation}
URL FROM THE SEARCH: ${c.url || '(none)'}
SEARCH SNIPPET (not a quotation; never copy it as one): ${c.supportingLanguage || c.why || ''}

Use the Bash tool for the scripts below (ToolSearch "select:Bash" if it is not loaded).
1. EXISTENCE, deterministically: python3 "${CHECK_CITE}" "<volume> <reporter> <first page>"
   A found result whose case name matches settles existence and the reporter cite. A cite that does not
   resolve is a search problem, not a bad cite: run python3 "${CL_TOOLS}" find "<case name>" --cite "<cite>"
   before concluding anything. exists=false only if both fail and a web search for the name finds nothing.
   If the record shows a different case at that cite, or a different year, correct the fields from the
   record and say so in notes; never keep a citation the record contradicts.
2. OPEN THE OPINION and save its text: python3 "${FETCH_PAGE}" "<url>" --out ${scratch(slot, '-src.txt')}
   Prefer the Caselaw Access Project page (official U.S. Reports star pagination), then CourtListener, LII,
   FindLaw. With more than one candidate URL, test them all in one call first: python3 "${PROBE}" "<url1>" "<url2>".
   Never print the whole file: grep -n -i the saved file for the passage, read small excerpts, or print one
   printed page with python3 "${VERIFY_QUOTES}" ${scratch(slot, '-src.txt')} --page <N>.
   Confirm (a) whether the passage supports the proposition: squarely, partially, or not at all; (b) whether it
   is in the MAJORITY opinion (otherwise give opinionPart and opinionAuthor); (c) the printed page it sits on,
   in official U.S. Reports pagination where the text carries it. pinciteSeen=true only if you saw that page
   number for that passage in the text; a page you did not see is not given. If the opinion cannot be opened
   in 3 attempts, set opened=false: the cite can then only be partially verified, without a pincite.
3. ${quoteSteps(slot)}
4. TREATMENT: python3 "${CL_TOOLS}" citing "<reporter cite>" --limit 10. Read the rows with mentions_target=true.
   Negative treatment of THIS case (overruled, abrogated, limited) goes in treatment, naming the treating case
   by name and year only. No hits is not proof of good law; say what the probe covered. For a lower-court case
   also run python3 "${CL_TOOLS}" history "<reporter cite>" and put any aff'd / rev'd / cert. denied line in
   subsequentHistory. If a tool errors (rate limit), set treatmentChecked=false and say so.
5. Fill the fields. paraphrase: a Bluebook explanatory parenthetical starting with a participle (holding that ...,
   explaining that ...), no quotation marks. fit: one line (canonical cite / recent reaffirmation / ...). Do not
   cite any other authority with a reporter citation in paraphrase, fit, shortfall, treatment or notes.
   signal: a tentative suggestion only. basis: a few honest words (opened at the pincite on CAP; lookup only).
${tempFiles(slot)}
${ACCESS}
${SOURCES}`
  : `You are verifying ONE candidate piece of scholarship for a law-review footnote. An unverified citation must
never ship, so report exactly what you confirmed and nothing more.

${CONTEXT}

CANDIDATE: ${c.citation}
URL FROM THE SEARCH: ${c.url || '(none)'}${c.zoteroKey && ZOTERO ? `\nZOTERO ITEM: ${c.zoteroKey} in library server "${ZOTERO}" (ToolSearch "select:mcp__${ZOTERO}__zotero_item_metadata,mcp__${ZOTERO}__zotero_item_fulltext").` : ''}
ABSTRACT OR SNIPPET (not a quotation; never copy it as one): ${c.supportingLanguage || c.why || ''}
${ZOTERO ? '' : 'Do not call any Zotero tool: no library was named for this run.\n'}
1. EXISTENCE AND BIBLIOGRAPHIC DATA from the source itself (the Zotero record, the journal's page, SSRN, a
   digital-commons record, a HeinOnline citation page): authors, title, volume, journal (Bluebook abbreviation),
   first page, year. Correct the candidate's data from the record and say so in notes. Never fill a field from memory.
   Set studentNote=true for a student Note or Comment, and venueTier (1 flagship general law review or top
   peer-edited journal, 2 strong secondary or specialty, 3 other).
2. OPEN THE TEXT if you can and save it: python3 "${FETCH_PAGE}" "<url>" --out ${scratch(slot, '-src.txt')}
   (repository and faculty-page PDFs work; SSRN downloads and HeinOnline usually do not). With more than one
   candidate URL, test them all first: python3 "${PROBE}" "<url1>" "<url2>". Never print the whole file: grep
   it, read excerpts, or print one page with python3 "${VERIFY_QUOTES}" ${scratch(slot, '-src.txt')} --page <N> --first-page <first printed page>.
   Confirm whether the piece supports the proposition (squarely, partially, not at all) and the printed page of
   the supporting passage. pinciteSeen=true only if you saw that page in the text. If only the piece's
   existence and general thesis can be confirmed, set opened=false and give no pincite.
3. ${quoteSteps(slot)}
4. Fill the fields. paraphrase: a Bluebook explanatory parenthetical starting with a participle (arguing that ...,
   explaining that ...), no quotation marks. fit: one line (leading article / standard synthesis / student note,
   only authority found / ...). Do not cite any other authority in paraphrase, fit, shortfall or notes.
   treatmentChecked=false. signal: a tentative suggestion only. basis: a few honest words.
${tempFiles(slot)}
${ACCESS}
${SOURCES}`

const verifyOne = (lane, c, slot) => retryOnce(`verify:${slot}`, verifyPrompt(lane, c, slot),
  { phase: 'Verify', schema: VERIFY_SCHEMA, model: VERIFY_MODEL, effort: 'low' })

// Budget: how many verification agents the remaining tokens allow.
const verifySlotsLeft = () => Math.max(0, Math.floor(remainingTokens() / PER_VERIFY))

phase('Search')
const laneState = {}
const verifications = [] // {lane, cand, slot, result}
let budgetCutVerify = 0
let reservedVerify = 0 // verification agents already granted (the lanes run concurrently)
await parallel(LANES.map((lane) => async () => {
  const r = await retryOnce(`search:${lane}`, sweepPrompt(lane),
    { phase: 'Search', schema: CANDIDATES_SCHEMA, model: SCOUT_MODEL, effort: 'low' })
  const st = { lane, failure: r.failure, candidates: [], picked: 0 }
  laneState[lane] = st
  if (!r.value) return st
  const seen = new Set()
  const cands = rankCandidates((r.value.candidates || []).filter((c) => c && c.citation))
    .filter((c) => { const k = citeKey(c.citation); if (seen.has(k)) return false; seen.add(k); return true })
  st.candidates = cands
  let quota = Math.min(QUOTAS[lane] || 0, cands.length)
  const allowed = Math.max(0, verifySlotsLeft() - reservedVerify)
  if (quota > allowed) { budgetCutVerify += quota - allowed; quota = allowed }
  reservedVerify += quota
  const picks = cands.slice(0, quota)
  st.picked = picks.length
  await parallel(picks.map((c, i) => async () => {
    const slot = `${lane[0]}${i + 1}`
    const res = await verifyOne(lane, c, slot)
    verifications.push({ lane, cand: c, slot, order: i, res })
  }))
  return st
}))

for (const lane of LANES) {
  const st = laneState[lane]
  if (!st || st.failure === 'died') degradation.push(`The ${lane} search did not run (its agent failed twice), so no ${LANE_WORD[lane]} candidates were considered.`)
  else if (st.failure === 'cap') degradation.push(`The agent cap stopped the ${lane} search, so no ${LANE_WORD[lane]} candidates were considered.`)
  else if (st.failure === 'budget') degradation.push(`The token budget ran out before the ${lane} search, so no ${LANE_WORD[lane]} candidates were considered.`)
}

// ---- 4. judge each verification in code -------------------------------------------------
// Sentence split that does not break after a citation abbreviation ("v.", "U.S.", "L. Rev.").
const ABBR_END = /(?:\bv|U\.S|S\.\s?Ct|L|Rev|J|Ct|Cir|F|Supp|App|e\.g|i\.e|cf|Inc|Co|No|Nos|ed|eds|al|Jr|St|Dist|\b[A-Z])\.$/
const sentences = (t) => {
  const out = []
  let cur = ''
  for (const piece of t.split(/(?<=[.;])\s+/)) {
    cur = cur ? `${cur} ${piece}` : piece
    if (!ABBR_END.test(cur)) { out.push(cur); cur = '' }
  }
  if (cur) out.push(cur)
  return out
}
const scrub = (s) => {
  // Free text from an agent: no double quotation marks (only checked quotations carry them),
  // and no sentence that cites another authority with a reporter citation.
  let t = String(s || '').replace(/\s+/g, ' ').trim()
  t = t.replace(/“/g, '‘').replace(/”/g, '’').replace(/"/g, "'")
  return sentences(t).filter((p) => !new RegExp(CITE_TRIPLE.source).test(p)).join(' ').trim()
}
const fold = (s) => String(s || '')
  .normalize('NFKC')
  .replace(/\[\*{1,3}\d{1,4}\]/g, ' ')
  .replace(/(^|\s)\*{1,3}\d{1,4}(?=\s|$)/g, ' ')
  .replace(/­/g, '')
  .replace(/([A-Za-z])-\s*\n\s*([A-Za-z])/g, '$1$2')
  .replace(/[‘’‚‛′`]/g, "'")
  .replace(/[‐‑‒–—―−]/g, '-')
  .replace(/\s+/g, ' ')
  .trim()
  .toLowerCase()
const TRIM_RX = /^[ \t\r\n]+|[ \t\r\n]+$/g
const quoteHash = (s) => fnv(String(s).replace(TRIM_RX, '')).toString(16).padStart(8, '0')

// Returns {ok, why}. The script, not the agent, decides whether a quotation ships.
function checkQuote(q, rc) {
  const quote = String(q || '').replace(TRIM_RX, '')
  if (!quote) return { ok: false, why: '' }
  if (quote.length > QUOTE_MAX) return { ok: false, why: `longer than ${QUOTE_MAX} characters` }
  if (/[\n"“”]/.test(quote)) return { ok: false, why: 'contains a line break or a double quotation mark' }
  if (!rc || typeof rc !== 'object') return { ok: false, why: 'no receipt from the quotation check' }
  if (rc.quote_hash !== quoteHash(quote)) return { ok: false, why: 'the receipt is for different text than the quotation returned' }
  if (!['verbatim', 'normalized'].includes(rc.status)) return { ok: false, why: `the quotation check reported ${rc.status || 'no status'}` }
  if (!fold(rc.match_excerpt).includes(fold(quote))) return { ok: false, why: 'the quotation is not inside the matched source passage' }
  return { ok: true, why: `confirmed by verify_quotes.py (${rc.status})` }
}

const pageRange = (p, e) => {
  if (e == null || e === p) return String(p)
  const a = String(p), b = String(e)
  if (a.length === b.length && a.length > 2 && a.slice(0, -2) === b.slice(0, -2)) return `${a}–${b.slice(-2)}`
  return `${a}–${b}`
}
const firstPageOf = (v) => {
  const m = String(v.kind === 'case' ? v.reporterCite || '' : v.firstPage || '').match(/(\d+)\s*$/)
  return m ? Number(m[1]) : null
}

function renderCitation(v, pin) {
  const k = v.kind
  const pinPart = pin ? `, ${pin}` : ''
  if (k === 'case') {
    let s = `*${v.caseName.trim()}*, ${v.reporterCite.trim()}${pinPart} (${v.courtYear.trim()})`
    const part = v.opinionPart
    if (part === 'plurality') s += ' (plurality opinion)'
    else if ((part === 'concurrence' || part === 'dissent') && (v.opinionAuthor || '').trim())
      s += ` (${v.opinionAuthor.trim()}, J., ${part === 'dissent' ? 'dissenting' : 'concurring'})`
    if ((v.subsequentHistory || '').trim()) s += `, ${v.subsequentHistory.trim().replace(/[.,;]+$/, '')}`
    return s
  }
  if (k === 'article' || k === 'note') {
    const au = (v.authors || '').trim()
    const lead = k === 'note' && !/\bNote\b|\bComment\b/.test(au) ? `${au ? au + ', ' : ''}Note` : au
    return `${lead}, *${v.title.trim()}*, ${v.volume.trim()} ${v.journal.trim()} ${v.firstPage.trim()}${pinPart} (${v.year.trim()})`
  }
  if (k === 'book') return `${v.authors.trim()}, *${v.title.trim()}*${pin ? ' ' + pin : ''} (${(v.edition || '').trim() ? v.edition.trim() + ' ' : ''}${v.year.trim()})`
  return (v.citationText || '').trim()
}
const missingFields = (v) => {
  const need = v.kind === 'case' ? ['caseName', 'reporterCite', 'courtYear']
    : (v.kind === 'article' || v.kind === 'note') ? ['title', 'volume', 'journal', 'firstPage', 'year'].concat(v.kind === 'article' ? ['authors'] : [])
      : v.kind === 'book' ? ['authors', 'title', 'year'] : ['citationText']
  return need.filter((f) => !String(v[f] || '').trim())
}

const SUPPORT_RANK = { squarely: 0, partially: 1, unknown: 2 }
const judged = []   // delivered-eligible cites
const dropped = []  // {citation, lane, reason}
let notChecked = 0
function judge(x) {
  const { lane, cand, slot, res } = x
  if (!res.value) {
    notChecked++
    if (res.failure === 'died') degradation.push('One candidate could not be checked: its verification agent failed twice. It is not delivered.')
    else if (res.failure === 'cap') degradation.push(`The agent cap (${MAX_AGENT_STARTS} agent starts per run) stopped the verification of one candidate, or its retry. It is not delivered.`)
    else degradation.push('The token budget ran out before one candidate was verified. It is not delivered.')
    return
  }
  const v = { ...res.value }
  if (v.kind === 'note') v.studentNote = true
  if (v.studentNote && v.kind === 'article') v.kind = 'note'
  if (v.exists !== true) { dropped.push({ citation: cand.citation, lane, reason: 'existence could not be confirmed (lookup and name search)' }); return }
  if (v.supports === 'no') { dropped.push({ citation: cand.citation, lane, reason: 'the source does not support the proposition' }); return }
  // A lane delivers its own kind of authority (2026-11-23). The first live run, asked for cases
  // only, delivered a Department of Justice manual page it had not opened, with a fit line saying
  // it was not authority. A cases lane ships cases; a scholarship lane ships no cases; and an
  // 'other' source that was never opened rests on search results alone, which is not existence
  // confirmed from the source.
  if (lane === 'cases' && v.kind !== 'case') { dropped.push({ citation: cand.citation, lane, reason: 'not a case (this lane delivers cases only)' }); return }
  if (lane === 'scholarship' && v.kind === 'case') { dropped.push({ citation: cand.citation, lane, reason: 'a case, not scholarship (this lane delivers scholarship only)' }); return }
  if (v.kind === 'other' && v.opened !== true) { dropped.push({ citation: cand.citation, lane, reason: 'the source could not be opened, so its existence rests on search results only' }); return }
  const miss = missingFields(v)
  if (miss.length) { dropped.push({ citation: cand.citation, lane, reason: `the citation could not be assembled (missing ${miss.join(', ')})` }); return }

  // Quotation: shipped only on a valid receipt; otherwise the paraphrase.
  const qc = checkQuote(v.quote, v.quoteReceipt)
  let pin = String(v.pincite || '').trim()
  let pinSeen = v.pinciteSeen === true && !!pin
  let opened = v.opened === true
  let pinNote = ''
  if (qc.ok) {
    opened = true
    const rc = v.quoteReceipt
    const fp = firstPageOf(v)
    // The verifier reads printed pages off the text's own page markers. Use them when they fall
    // in the work's page range (a parallel reporter's star pages would not) and the agent's pin
    // is missing or outside them.
    if (Number.isInteger(rc.page) && fp != null && rc.page >= fp && rc.page < fp + 400 && (!pinSeen || rc.pincite_ok === false)) {
      pin = pageRange(rc.page, rc.page_end); pinSeen = true; pinNote = 'pincite read from the source text\'s page markers'
    }
  }
  const supportsOk = v.supports === 'squarely' || v.supports === 'partially'
  const full = v.kind !== 'other' && opened && supportsOk && pinSeen
  const level = full ? 'verified' : 'partial'
  const deliveredPin = full ? pin : ''
  const paraphrase = scrub(v.paraphrase)
  const support = qc.ok ? { type: 'quotation', text: String(v.quote).replace(TRIM_RX, '') } : { type: 'paraphrase', text: paraphrase }
  const quotationCheck = !String(v.quote || '').trim() ? 'no quotation proposed'
    : qc.ok ? qc.why : `proposed quotation not confirmed (${qc.why}); paraphrase given instead`
  const basisBits = [scrub(v.basis).replace(/[.;,\s]+$/, '') || (opened ? 'source opened' : 'existence confirmed only')]
  if (!full) basisBits.push(opened ? (supportsOk ? 'no pincite seen, so none is given' : 'support not established') : 'source not opened, so no pincite')
  if (pinNote && full) basisBits.push(pinNote)
  if (qc.ok) basisBits.push('quotation checked by script against the fetched text')
  const isCase = v.kind === 'case'
  const treatment = isCase
    ? (v.treatmentChecked === true && scrub(v.treatment) ? scrub(v.treatment) : 'Treatment not checked.')
    : 'Treatment not checked (scholarship).'
  let fit = scrub(v.fit)
  if (isCase && ['concurrence', 'dissent', 'plurality'].includes(v.opinionPart)) fit = `${fit ? fit + ' ' : ''}The supporting passage is in a ${v.opinionPart === 'plurality' ? 'plurality opinion' : v.opinionPart}, not the majority.`.trim()
  judged.push({
    lane, slot, order: x.order,
    kind: v.kind,
    citation: renderCitation(v, deliveredPin),
    shortName: isCase ? `*${v.caseName.trim()}*` : v.kind === 'other' ? (v.citationText || '').trim().slice(0, 60) : `*${v.title.trim()}*`,
    pincite: deliveredPin,
    url: String(v.url || cand.url || '').trim(),
    support,
    paraphrase,
    quotationCheck,
    fit,
    supports: supportsOk ? v.supports : 'unknown',
    shortfall: scrub(v.shortfall),
    verification: { level, basis: basisBits.filter(Boolean).join('; ') },
    treatment,
    treatmentChecked: isCase && v.treatmentChecked === true,
    studentNote: !!v.studentNote,
    venueTier: Number.isInteger(v.venueTier) ? v.venueTier : (Number.isInteger(cand.venueTier) ? cand.venueTier : 2),
    signal: SIGNALS.includes(v.signal) ? v.signal : '',
    opinionPart: v.opinionPart || (isCase ? 'majority' : 'n/a'),
    key: citeKey(renderCitation(v, '')),
  })
}

phase('Verify')
verifications.sort((a, b) => LANES.indexOf(a.lane) - LANES.indexOf(b.lane) || a.order - b.order)
for (const x of verifications) judge(x)

// One top-up round when drops leave fewer than MIN_CITES. Required lanes with nothing yet go first.
// Two candidates that turn out to be the same authority (a corrected cite, say) count once.
let duplicatesMerged = 0
const dedupe = () => {
  const seen = new Set()
  const out = []
  for (const j of judged) { if (seen.has(j.key)) { duplicatesMerged++; continue } seen.add(j.key); out.push(j) }
  judged.length = 0; judged.push(...out)
}
dedupe()
let leftovers = []
for (const lane of LANES) {
  const st = laneState[lane]
  if (st) leftovers.push(...st.candidates.slice(st.picked).map((c, i) => ({ lane, c, i: st.picked + i })))
}
if (judged.length < MIN_CITES && leftovers.length) {
  const hasLane = (l) => judged.some((j) => j.lane === l)
  leftovers.sort((a, b) => (hasLane(a.lane) ? 1 : 0) - (hasLane(b.lane) ? 1 : 0) || LANES.indexOf(a.lane) - LANES.indexOf(b.lane) || a.i - b.i)
  let n = Math.min(TOPUP_CAP, leftovers.length, MIN_CITES - judged.length + 1)
  const allowed = verifySlotsLeft()
  if (n > allowed) { budgetCutVerify += n - allowed; n = allowed }
  const picks = leftovers.slice(0, n)
  leftovers = leftovers.slice(n)
  log(`Only ${judged.length} candidate(s) survived verification; verifying ${picks.length} more.`)
  const before = verifications.length
  await parallel(picks.map((p) => async () => {
    const slot = `${p.lane[0]}${p.i + 1}`
    const res = await verifyOne(p.lane, p.c, slot)
    verifications.push({ lane: p.lane, cand: p.c, slot, order: p.i, res })
  }))
  const fresh = verifications.slice(before).sort((a, b) => LANES.indexOf(a.lane) - LANES.indexOf(b.lane) || a.order - b.order)
  for (const x of fresh) judge(x)
  dedupe()
}
if (judged.length < MIN_CITES && leftovers.length) {
  degradation.push(`Fewer than ${MIN_CITES} authorities survived verification, and ${leftovers.length} further candidate${leftovers.length === 1 ? ' was' : 's were'} not checked because of the verification cap (${VERIFY_CAP} plus ${TOPUP_CAP} in one top-up round).`)
}
if (budgetCutVerify) degradation.push(`The token budget stopped ${budgetCutVerify} planned verification${budgetCutVerify === 1 ? '' : 's'}.`)
// Each agent the cap stopped is reported where it was stopped (classifier, search, verification).
if (capCut.length) log(`Agent cap reached: ${capCut.join(', ')} did not start.`)

// ---- 5. assemble -------------------------------------------------------------------------
phase('Assemble')
const LANE_PRIORITY = (lane) => LANES.indexOf(lane)
const ranked = judged.slice().sort((a, b) =>
  (a.studentNote ? 1 : 0) - (b.studentNote ? 1 : 0) ||
  (a.verification.level === 'verified' ? 0 : 1) - (b.verification.level === 'verified' ? 0 : 1) ||
  SUPPORT_RANK[a.supports] - SUPPORT_RANK[b.supports] ||
  LANE_PRIORITY(a.lane) - LANE_PRIORITY(b.lane) ||
  (a.lane === 'scholarship' ? a.venueTier - b.venueTier : 0) ||
  a.order - b.order)
const delivered = ranked.slice(0, MAX_DELIVER)
const surplus = ranked.length - delivered.length

const cites = delivered.map((j, i) => ({
  rank: i + 1,
  kind: j.kind,
  lane: j.lane,
  citation: j.citation,
  pincite: j.pincite,
  url: j.url,
  support: j.support,
  paraphrase: j.paraphrase,
  quotationCheck: j.quotationCheck,
  fit: j.fit,
  supports: j.supports,
  verification: j.verification,
  treatment: j.treatment,
  studentNote: j.studentNote,
  signal: j.signal,
  opinionPart: j.opinionPart,
}))

// Gaps: honest statements built from the fields. They name only authorities in `cites`.
const gaps = []
for (const lane of LANES) {
  const mine = cites.filter((c) => c.lane === lane)
  const dropN = dropped.filter((d) => d.lane === lane).length
  if (!mine.length) {
    gaps.push(`No ${LANE_WORD[lane]} could be verified for this proposition${dropN ? ` (${dropN} candidate${dropN === 1 ? '' : 's'} failed verification)` : ''}.`)
  } else if (!mine.some((c) => c.supports === 'squarely')) {
    const closest = delivered.find((j) => j.lane === lane)
    const rank = cites.find((c) => c.lane === lane).rank
    gaps.push(`No ${LANE_WORD[lane]} found squarely supports the proposition as stated. The closest is ${closest.shortName} (no. ${rank})${closest.shortfall ? `: ${closest.shortfall.replace(/[.\s]+$/, '')}` : ''}.`)
  }
}
if (cites.length && !cites.some((c) => c.verification.level === 'verified')) gaps.push('None of the authorities below was confirmed at a pincite; each is partially verified and carries no pincite.')
if (cites.some((c) => c.studentNote)) gaps.push('A student note is included only because nothing better was found; it is marked below.')

const counts = {
  candidatesFound: LANES.reduce((n, l) => n + ((laneState[l] && laneState[l].candidates.length) || 0), 0),
  checked: verifications.length - notChecked,
  verifiedInFull: cites.filter((c) => c.verification.level === 'verified').length,
  partiallyVerified: cites.filter((c) => c.verification.level === 'partial').length,
  dropped: dropped.length,
  notChecked,
  delivered: cites.length,
  verifiedNotDelivered: surplus,
  duplicatesMerged,
  quotationsConfirmed: cites.filter((c) => c.support.type === 'quotation').length,
  agentStarts: starts,
  agentCap: MAX_AGENT_STARTS,
}

// The footnote-ready entry, rendered here from the fields above (no model writes it).
const TYPE_LABEL = { cases: 'cases', scholarship: 'scholarship', both: 'cases and scholarship' }
const entryLines = []
// The entry starts with the cites. The proposition is the heading (or the user's own message),
// and how the authority type was chosen is a note at the end, beside the checking counts.
if (cites.length) {
  for (const c of cites) {
    const paren = c.support.type === 'quotation' ? ` (“${c.support.text}”)` : (c.support.text ? ` (${c.support.text.replace(/[.\s]+$/, '')})` : '')
    entryLines.push(`${c.rank}. ${c.citation}${paren}.`)
    if (c.url) entryLines.push(`   - Source: <${c.url}>`)
    if (c.studentNote) entryLines.push('   - Student note: last resort; cited only because nothing better was found.')
    if (c.fit) entryLines.push(`   - Fit: ${c.fit}`)
    entryLines.push(`   - Verification: ${c.verification.level === 'verified' ? 'verified in full' : 'partially verified'}; ${c.verification.basis}.`)
    if (c.support.type === 'paraphrase' && c.quotationCheck.startsWith('proposed quotation not confirmed')) entryLines.push('   - The parenthetical is a paraphrase: a proposed quotation could not be confirmed against the source text.')
    entryLines.push(`   - Treatment: ${c.treatment}`)
    if (c.signal) entryLines.push(`   - Signal (tentative): ${c.signal === 'none' ? 'none (direct support)' : `*${c.signal}*`}`)
  }
  entryLines.push('')
} else {
  entryLines.push('No authority could be verified for this proposition.', '')
}
if (gaps.length) entryLines.push(`**Gaps:** ${gaps.join(' ')}`, '')
if (degradation.length) entryLines.push(`**Limits of this run:** ${degradation.join(' ')}`, '')
entryLines.push(`*Authority type: ${TYPE_LABEL[authorityType]} (${authorityTypeBasis.replace(/["“”*]/g, "'")}).*`, '')
entryLines.push(`*Checked: ${counts.candidatesFound} candidates found; ${counts.verifiedInFull} verified in full, ${counts.partiallyVerified} partially verified, ${counts.dropped} dropped${counts.notChecked ? `, ${counts.notChecked} not checked` : ''}. Open-web sources only; no Westlaw, Lexis, KeyCite or Shepard's.*`)
const entry = entryLines.join('\n') + '\n'

const exitState = degradation.length ? 'complete_with_limits' : 'complete'
log(`Done: ${cites.length} cite(s) delivered, ${dropped.length} dropped, exit ${exitState}.`)

// `entry` comes early so a completion notice that cuts a long result still carries it whole.
return {
  proposition: PROPOSITION,
  authorityType,
  authorityTypeBasis,
  exitState,
  degradation,
  entry,
  gaps,
  counts,
  cites,
  dropped,
}
