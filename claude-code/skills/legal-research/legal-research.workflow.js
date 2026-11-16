export const meta = {
  name: 'legal-research',
  description: 'Retrieval-pipeline legal research: broad cheap search, dedup, read-once, draft, gap-fill, verify cited authorities, finalize',
  phases: [
    { title: 'Scope', detail: 'frame issues, jurisdiction, search vectors' },
    { title: 'Survey', detail: 'broad search-only sweep (+ Zotero library); collect candidates, fetch nothing' },
    { title: 'Read', detail: 'dedup, triage, then fully read each chosen source once' },
    { title: 'Draft', detail: 'synthesize a memo from the findings' },
    { title: 'Verify', detail: 'confirm only the authorities actually cited' },
    { title: 'Finalize', detail: 'apply corrections as edits, flag unverified, add appendices' },
  ],
}

// ---- args (passed from the skill) -------------------------------------------
// args = { skillsDir: '<plugin root>/skills', question, mode: 'caselaw'|'scholarship'|'both', outputStyle: 'academic'|'practitioner',
//          jurisdiction, asOfDate, notes, deep:boolean, projectDir:string,
//          finalizeModel:string (optional; unset = the session model), escalate:boolean (default true) }
let A = args || {}
if (typeof A === 'string') { try { A = JSON.parse(A) } catch { A = {} } }
const QUESTION = A.question || 'No question provided.'
const MODE = (A.mode || 'both').toLowerCase()
const OUTPUT = (A.outputStyle || (MODE === 'caselaw' ? 'practitioner' : 'academic')).toLowerCase()
const JURISDICTION = A.jurisdiction || 'not specified — infer the most relevant U.S. jurisdiction(s)'
const AS_OF = A.asOfDate || 'today'
const NOTES = A.notes || ''
const DEEP = !!A.deep // opt-in heavier mode: more vectors, more reads, adversarial verify
const PROJECT_DIR = A.projectDir || '' // the user's working directory — enables the local-corpus sweep
// Run tag for scratch filenames (CLAUDE-07): cite-check chunks and refutation voters run
// concurrently and share /tmp, so every source dump needs a path unique to this run AND to the
// authority/voter writing it. Date.now()/Math.random() are unavailable in workflow scripts (they
// break resume), so the tag is a deterministic hash of the run's inputs; args.runTag overrides.
const RUN_TAG = (() => {
  const given = String(A.runTag || '').replace(/[^A-Za-z0-9_-]/g, '')
  if (given) return given.slice(0, 24)
  let h = 5381
  const s = `${QUESTION}|${MODE}|${AS_OF}|${NOTES}`
  for (let i = 0; i < s.length; i++) h = ((h * 33) ^ s.charCodeAt(i)) >>> 0
  return h.toString(36)
})()

const DO_CASES = MODE === 'caselaw' || MODE === 'both'
const DO_SCHOLARSHIP = MODE === 'scholarship' || MODE === 'both'

// Lean by default; widens only if the user opts into deep mode or sets a token budget.
const VECTOR_CAP = budget.total
  ? Math.min(7, Math.max(4, Math.floor(budget.total / 250_000)))
  : DEEP ? 6 : 4
// Lever 1+2: total number of UNIQUE sources fully fetched across the WHOLE run (not per vector).
// This is the dominant cost knob — every full read is model-reading of raw source text.
const READ_CAP = budget.total
  ? Math.min(24, Math.max(8, Math.floor(budget.total / 120_000)))
  : DEEP ? 16 : 8
const CANDIDATES_PER_VECTOR = 10 // hits per survey agent — search-only is near-free, keep recall wide in lean mode too
const LEADS_CAP = READ_CAP * 2 // unread search-extract leads carried into the draft for breadth
const GAPFILL_CAP = 3 // targeted post-draft retrievals if the draft flags missing authorities
const VERIFY_CHUNK = 8 // authorities per cite-check agent — small chunks keep attention fresh
const REFUTE_CAP = 8 // deep mode: max load-bearing authorities that get the 3-vote refutation pass

// Graceful degradation, ALWAYS armed. Two ceilings can bind: a user "+500k"-style budget (the
// harness makes agent() THROW once that pool is dry, which would kill the run mid-pipeline with
// the spend sunk) and, when no user budget is set, a hardwired SOFT_CAP so a runaway run degrades
// instead of spiraling (the v2 failure mode). Check remaining tokens at each phase boundary and
// drop luxuries in order — trim reads, skip gap-fill, shrink verify to load-bearing cites —
// always reserving enough for Draft + Finalize so a tight run still returns a complete (just
// more-flagged) memo.
const RESERVE_DRAFT = 60_000
const RESERVE_FINALIZE = 40_000
const PER_READ = 12_000 // rough output-token cost of one full read
// let, not const: historical multi-era questions get a bump after Scope classifies them — the
// July 2026 pre-1960 run showed the lean cap starving 3 of 5 declared eras of any full read.
// Deep cap raised 600k -> 1M (2026-07-15): a deep historical run bound mid-ladder and left 35 of
// 43 citations unchecked, forcing manual rescue passes. Cite-check is the stage that must finish.
let SOFT_CAP = DEEP ? 1_000_000 : 250_000 // output tokens; governs only when no user budget is set
// budget.spent() is turn-global (the main loop and every workflow this turn), so the soft cap is
// measured from where THIS run started. Without the baseline, tokens spent earlier in the turn
// (pre-flight, an earlier attempt, another workflow) came out of this run's cap: with 200k already
// spent, a lean run trimmed its reads from 8 to 3 (2026-11-15 review). The proofread and
// cite-check workflows already baselined.
const SPENT0 = budget.spent()
const remainingTokens = () =>
  budget.total ? budget.remaining() : Math.max(0, SOFT_CAP - (budget.spent() - SPENT0))
const tight = (need) => remainingTokens() < need

// Lever 3 — model map:
// - Scope and Draft (and the deep calibration pass) carry NO model override: they inherit the
//   session model (Fable when Fable is on). Scope's leverage-per-token is the highest in the
//   pipeline (its vectors steer everything downstream) and Draft is the analytical synthesis.
// - Finalize inherits the session model too UNLESS the skill passes args.finalizeModel. Nothing
//   is hard-coded here, so a session run entirely on Sonnet or Opus stays on that model; the
//   skill passes a cheaper model only when the session model sits above it (2026-11-16: 'opus'
//   on a Fable session, where Fable use is capped). That became safe when Finalize stopped
//   re-emitting the memo: every post-Draft pass now returns find-and-replace edits and this
//   script applies them, so a cheaper model can no longer launder the Draft's prose (see
//   applyEdits below).
// - With finalizeModel set, the changes that alter what the memo can CLAIM are not left to the
//   cheaper model: a load-bearing authority that failed verification or drew negative treatment,
//   a minority objection, and the weaving-in of gap-fill authorities go to one call on the
//   session model first (the "call-in", label finalize:revise), which also returns edits. It
//   runs only when the cite-check results contain such an item; args.escalate:false turns it off.
// - Sonnet does the accuracy-critical mid-volume work: triage (decides what gets read), the full
//   reads (a misread here becomes a confident wrong proposition in the draft, and lean verify
//   won't re-open the source to catch it), and cite-verification.
// - Haiku is confined to the one stage where a weak read can't corrupt the memo: the search-only
//   survey, whose output is candidate lists that Sonnet triage re-judges anyway.
const SCOUT_MODEL = 'haiku'   // survey: search-snippet harvesting only
const READ_MODEL = 'sonnet'   // triage, full reads, gap-fill reads
const VERIFY_MODEL = 'sonnet' // cite-checking
// Finalize's clerical pass and the edit-repair round. '' = no override (the session model).
const FINALIZE_MODEL = String(A.finalizeModel || '').trim().replace(/[^A-Za-z0-9._-]/g, '')
const withFinalizeModel = (opts) => (FINALIZE_MODEL ? { ...opts, model: FINALIZE_MODEL } : opts)
const ESCALATE = A.escalate !== false && A.escalate !== 'false'

const SOURCES = `Opinions, articles and dockets that POSTDATE your training data are real — a 2025 or 2026
decision you do not recognize is not a hallucination signal; the fetched record is, your recall is not.
FREE / OPEN-WEB LEGAL SOURCES ONLY (no Westlaw/Lexis):
- Case law: CourtListener, Justia, Google Scholar case law, Cornell LII, Caselaw Access Project,
  official court sites (supremecourt.gov, the U.S. Courts of Appeals, state high courts).
- Scholarship: SSRN, Google Scholar, law-school digital-commons repositories, HeinOnline open
  content, journal websites, authors' faculty pages.
- Prefer HTML versions over raw PDFs (CourtListener's HTML opinion view, LII, SSRN abstract
  pages) — PDFs are slow to fetch and bloat context.
- KNOWN FETCH BLOCKS + OFFICIAL-TEXT MIRRORS (field-tested): Justia returns HTTP 403 to WebFetch,
  and CourtListener opinion pages sometimes do too. For OFFICIAL reporter text with star
  pagination, go straight to:
  * Harvard Caselaw Access Project static HTML — https://static.case.law/us/<vol>/html/<first-page>-01.html
    (pad first page to 4 digits, e.g. us/3/html/0386-01.html; other reporters by slug, e.g. /ny/,
    /f2d/). Best single source for verbatim quotes and pincites.
  * Library of Congress U.S. Reports page scans — tile.loc.gov usrep PDFs (route through the
    capped fetcher script, never raw WebFetch). Authoritative for reading pincites off the page.
  * FindLaw (caselaw.findlaw.com/us-supreme-court/<vol>/<page>.html) and Cornell LII as HTML
    fallbacks (their star-pagination markers are occasionally off — prefer CAP/LOC for pincites).
- SSRN download pages and journal sites are often paywalled or fetch-blocked. Law-review articles
  usually also live on a school's digital-commons repository or the author's faculty page — prefer
  those copies.
TOOLS: use WebSearch and WebFetch. If not already callable, first run
ToolSearch with query "select:WebSearch,WebFetch", then use them.`

// Bundled helper scripts (run via the Bash tool). SKILL.md passes
// skillsDir = "${CLAUDE_PLUGIN_ROOT}/skills", which Claude Code expands to the plugin's
// install directory before the call. The fallback is the plain ~/.claude/skills layout;
// $HOME (not ~) because every use below lands inside shell double quotes in an agent
// prompt, where $HOME expands but ~ does not.
const SKILLS = A.skillsDir || '$HOME/.claude/skills'
const CHECK_CITE = `${SKILLS}/legal-research/check_cite.py`
const FETCH_PAGE = `${SKILLS}/legal-research/fetch_page.py`
const CL_TOOLS = `${SKILLS}/legal-research/cl_case_tools.py`
const PROBE = `${SKILLS}/legal-research/probe_sources.py`
// Deterministic quote verifier (lives in the sibling cite-check skill, shipped in the same plugin).
const VERIFY_QUOTES = `${SKILLS}/cite-check/scripts/verify_quotes.py`

const BLUEBOOK = `CITATION FORMAT (Bluebook, lightweight):
- Cases: *Brown v. Bd. of Educ.*, 347 U.S. 483, 495 (1954); add the deciding court for
  non-SCOTUS cases, e.g. (9th Cir. 2018), (S.D.N.Y. 2020).
- Articles: Author, *Title*, Vol. Journal Abbrev. FirstPage, Pincite (Year).
- Always give a pinpoint cite for any specific proposition or quotation.
- HYPERLINKS (required, per the author): every news story, blog post, report, or other web source
  MUST carry its working URL as a markdown hyperlink — [Outlet, *Title* (Date)](https://…) —
  or the bare URL appended to the cite. Never cite a web source by outlet name alone
  ("(Politico)", "(CNBC, May 2022)"). Use the URL already captured in the findings; a
  paywalled story still gets its story-page URL. For cases and scholarship, append the
  best public URL too (CourtListener/LII, SSRN/repository) when one is in the findings.`

// ---- v6: analytical-method modules injected into Draft ---------------------------------------
// Condensed from a strong external methods handbook. Scope classifies the question; Draft gets
// only the relevant module(s) (~1-2k input tokens on a call that already inherits the session
// model — the cheapest depth lever in the pipeline).
const METHODS_DOCTRINAL = `ANALYTICAL METHOD (doctrinal):
- For each issue: short answer → governing rule with best authority → leading applications →
  adverse or limiting authority → application → calibrated confidence + what could change it.
- Introduce a case by why it matters; give only the facts and reasoning the proposition needs.
- Do not infer a broad rule from factual resemblance. Check the disposition, the issue actually
  decided, and whether the language was necessary to the judgment.
- When authorities conflict, explain the conflict (hierarchy, jurisdiction, date, posture, facts)
  instead of averaging the rules together.
- Do not convert contextual considerations into universal elements unless the court did so.
  Distinguish the COURT'S stated test from the MEMO'S synthesis of the cases — label your own
  synthesis as such ("the better reading", "this memo's synthesis").
- When the doctrine has multiple stages, elements, or alternative routes, map them separately
  before synthesizing; never use authority on one stage to establish another.
- Authority from an adjacent doctrine, clause, jurisdiction, or era is ANALOGICAL: label it, state
  the exact proposition transferred, and name the difference that limits the analogy.
- If the memo turns on several authorities or a split, include an authority table:
  | Authority | Court/date | What it actually establishes | Force | Limitation or adverse point |`

const METHODS_HISTORY = `ANALYTICAL METHOD (doctrinal history / general law) — the question asks how
doctrine developed or what a legal concept has meant over time:
- Combine chronology with CONCEPTUAL organization. First map the distinct models or conceptions
  the courts have used (a taxonomy table: conception → core inquiry → representative decisions →
  present significance), THEN give the chronological account. The taxonomy is the memo's spine.
- Cover the FULL arc, including the pre-modern ancestry in the findings: earlier cases often use
  different vocabulary for the same problem. Do not start the story at the modern canon.
- Never assume an older court used a modern-sounding word in its modern doctrinal sense. Quote the
  language and identify the legal problem that court was actually solving.
- For each era distinguish: the rule as stated; the reasons given; accepted exceptions; later
  restatement or displacement; the modern court's use of that history; and what inference the
  record can and cannot support.
- Treat absences carefully: a source's silence may mean assumed, irrelevant, not litigated, or not
  reported — say which inference the record supports, and never convert a search failure into a
  historical rule.
- SELECTION-BIAS CHECK (mandatory before any comparative or frequency claim about an era): the
  research sample is drawn from cases where classification was CONTESTED — routine cases applied
  the category silently and never generated definitional language, so the sample structurally
  oversamples explicit reasoning. Say so, and scope frequency claims to "the leading contested
  cases reviewed," never to the era as a whole. Famous cases are not representative cases.
- BOUNDARY-DATE POLICY: if the question declares a period, state whether each boundary is
  inclusive or exclusive, and label any boundary-adjacent source as an epilogue or boundary
  marker rather than counting it as in-period evidence.
- HARM/EXCLUSION CHECK: ask whether the inherited legal categories were used to entrench
  subordination or exclude disfavored groups (e.g., Dred Scott in any history of constitutional
  property). A historical narrative that celebrates a method without confronting its worst uses
  is incomplete and will be attacked; include the confrontation.
- End historical sections with an explicit confidence level: strong and broad / strong but limited
  to a period or tradition / mixed or contested / sparse but suggestive / insufficient.
- Close the memo with a synthesis section ("how the strands fit together") and, where the findings
  support it, a one-paragraph synthesized formulation of the doctrine — expressly labeled as this
  memo's synthesis rather than a test the court has announced.`

// v7: claim-strength calibration — injected into every Draft (and enforced again at Finalize).
// Ported from the cross-model post-mortem of the pre-1960 property memos: page-verified quotes
// under unsupported thesis-level quantifiers were the failure mode cite-checking cannot catch.
const CLAIM_CALIBRATION = `CLAIM-STRENGTH CALIBRATION (applies to every thesis-level sentence):
- Match the strength of your language to the strength of the search design. A purposive sample of
  canonical or contested cases supports "characteristically", "repeatedly in the leading cases
  reviewed", "the clearest statements found" — it does NOT support "overwhelmingly", "dominant",
  "almost never", "rare", or any implied denominator.
- Trigger-word gate: before using "first", "last", "only", "never", "always", "settled",
  "overwhelmingly", "uniformly", "erased", "dead", or an equivalent frequency/priority/finality
  word, ask what search could support it. A priority claim ("first case to...") requires a search
  DESIGNED to find earlier instances; if none was run, write "the earliest clean statement in the
  materials reviewed" instead.
- Distinguish what an authority HELD from what it conceded arguendo, assumed, or said in dictum —
  and never let a nonprecedential disposition (equally divided affirmance, cert. denial, plurality)
  carry weight as a holding. Say "left standing without creating precedent", not "affirmed".
- Do not let a source that resolved only PROCESS (or an adjacent clause or doctrine) silently carry
  a claim about a DEFINITIONAL or substantive threshold — use each finding's bearing/posture fields
  to police this.
- When prior local research memos appear in the findings: reconcile, don't duplicate. Note where
  this memo's conclusions agree with, extend, or contradict theirs, and do not re-assert a claim a
  prior memo already corrected or qualified without addressing that qualification.
- Trace each proposition to its origin. Repetitions of the same underlying evidence (a treatise's
  summary repeated down a chain of citations; several sources that all rest on one case) are not
  independent corroboration, and a head count of agreeing sources is not a confidence level.
  Assess confidence from the authority's weight, its verification basis, genuinely independent
  contributions (a distinct court applying the rule is one), contrary evidence, and coverage.
- Counter-position at full strength: for each material contested issue, in the Discussion, state
  the strongest contrary reading as its proponent would — the premise it attacks, the authority or
  evidence it rests on, and the facts or interpretation under which it wins — not the memo's
  conclusion restated with hedges. A valid point the answer needs belongs in the answer itself.
  Summary sections carry the material qualifications that result, without repeating the
  argument.`

const METHODS_SCHOLARLY = `ANALYTICAL METHOD (scholarly):
- Frame a research problem, not just a question: the received account, the live disagreement, the
  evidence that complicates it, and the claim the sources can responsibly support.
- Map the literature by argument, method, and debate — not author-by-author ("A says, B says") —
  unless the sequence itself demonstrates the field changing.
- Separate primary sources from secondary interpretation, and what the sources establish from what
  the memo infers ("the evidence is consistent with…", "this cannot establish…").
- Give rival interpretations substantive treatment; test the thesis against inconvenient sources,
  minority views, and work using different vocabulary.
- State the contribution no more broadly than the evidence supports, and say what further research
  would test it.
- DIRECT vs. ADJACENT (central-source discipline): the question names a PHENOMENON (e.g. "justices
  writing books"). Scholarship that puts THAT phenomenon at the center of its analysis is direct;
  scholarship on a broader category the phenomenon merely belongs to (extrajudicial speech,
  outside-income ethics, judicial celebrity) is adjacent. A large adjacent literature does NOT
  substitute for the direct one, and volume of adjacent hits is not evidence about the direct field.
- CENTRAL-SOURCE OMISSION AUDIT (gate on every absence/gap claim): before writing that no (or only
  thin) scholarship directly treats the named phenomenon, confirm the record contains (a) a search
  aimed squarely at the phenomenon as its own object — including the obvious title terms a
  specialist would use (here e.g. "judicial autobiography", "Supreme Court memoir", "justices' book
  deals") — and (b) a citation-chase of the most on-point source found, in both directions
  (its references and works citing it). If either is missing, do NOT assert the gap: scope the
  statement to "in the sources reviewed" and flag the un-run search as a limitation. An absence
  claim is a finding about the FIELD and needs a search designed to find the thing, not merely the
  observation that adjacent abstracts failed to mention it.`

// A dead critical agent (agent() → null after retries) must not surface as a TypeError deep in the
// pipeline: retry once, then abort with a real error.
async function must(label, fn) {
  let r = await fn()
  if (!r) { log(`${label} agent died — retrying once`); r = await fn() }
  if (!r) throw new Error(`${label} agent failed twice — aborting run`)
  return r
}

// A dead non-critical agent (survey vector, reader) is retried once; a second death returns null
// and the caller records the hole. It never surfaces as a clean, empty result.
async function retryOnce(label, fn) {
  let r = await fn()
  if (!r) { log(`${label} died — retrying once`); r = await fn() }
  return r || null
}

const norm = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

// ---------------------------------------------------------------------------
const PLAN_SCHEMA = {
  type: 'object',
  required: ['issues', 'jurisdiction', 'searchVectors'],
  properties: {
    restatedQuestion: { type: 'string' },
    jurisdiction: { type: 'string' },
    methodClass: {
      type: 'string',
      enum: ['doctrinal', 'scholarly'],
      description: 'doctrinal = what the law is / how courts decide; scholarly = literature mapping, theory, intellectual history',
    },
    historical: {
      type: 'boolean',
      description: 'true if the question asks how doctrine DEVELOPED, what a term meant historically, or about general/common-law background — not just the current rule',
    },
    issues: { type: 'array', items: { type: 'string' } },
    doctrines: { type: 'array', items: { type: 'string' } },
    keyAuthorities: { type: 'array', items: { type: 'string' } },
    searchVectors: {
      type: 'array',
      items: {
        type: 'object',
        required: ['label', 'goal', 'queries'],
        properties: {
          label: { type: 'string' },
          kind: { type: 'string', enum: ['caselaw', 'scholarship'] },
          goal: { type: 'string' },
          queries: { type: 'array', items: { type: 'string' } },
        },
      },
    },
  },
}

// Survey returns lightweight candidates from SEARCH EXTRACTS ONLY — no page was opened.
const CANDIDATES_SCHEMA = {
  type: 'object',
  required: ['candidates'],
  properties: {
    candidates: {
      type: 'array',
      items: {
        type: 'object',
        required: ['citation', 'why'],
        properties: {
          kind: { type: 'string', enum: ['case', 'statute', 'article', 'other'] },
          citation: { type: 'string' },
          url: { type: 'string' },
          zoteroKey: { type: 'string', description: "Zotero item key — ONLY for items found in the user's Zotero library" },
          court: { type: 'string' },
          year: { type: 'string' },
          why: { type: 'string', description: 'one line on why this is on-point, from the search snippet/abstract' },
          authority: { type: 'string', enum: ['high', 'medium', 'low'], description: 'apparent authoritativeness from the snippet' },
        },
      },
    },
  },
}

// Triage picks which deduped candidates are worth a full read.
const TRIAGE_SCHEMA = {
  type: 'object',
  required: ['selected'],
  properties: {
    selected: { type: 'array', items: { type: 'integer' }, description: 'indices of candidates to fully read, best first' },
    notes: { type: 'string' },
  },
}

// One fully-read source.
const READ_SCHEMA = {
  type: 'object',
  required: ['citation', 'proposition', 'opened'],
  properties: {
    kind: { type: 'string', enum: ['case', 'statute', 'article', 'other'] },
    citation: { type: 'string' },
    url: { type: 'string' },
    court: { type: 'string' },
    year: { type: 'string' },
    proposition: { type: 'string', description: 'what this authority establishes, in your words' },
    holding: { type: 'string' },
    quote: { type: 'string', description: 'short verbatim quote, only if you actually read the source text' },
    pincite: { type: 'string' },
    posture: {
      type: 'string',
      description: 'is the proposition a HOLDING, dicta, alternative reasoning, an arguendo concession or assumption, a concurrence, a dissent, a NONPRECEDENTIAL disposition (equally divided affirmance, cert. denial, plurality), or (for articles) the author\'s thesis vs. a reported view? one phrase',
    },
    bearing: {
      type: 'string',
      description: 'how the source bears on the QUESTION itself: "direct answer" / "assumes the premise" / "process-only" (resolves procedure, not the threshold/definitional issue) / "adjacent doctrine or clause" (analogy only) / "background" — one label, so the draft cannot let a process-only or adjacent source carry a threshold claim',
    },
    limitation: {
      type: 'string',
      description: 'the strongest limitation, qualification, adverse reading, or later negative treatment visible in the source — one line',
    },
    separateOpinions: {
      type: 'string',
      description: 'cases only: notable concurrences/dissents and their point, one line each — only what you actually read',
    },
    significance: {
      type: 'string',
      description: 'what this source ADDS to the doctrine/debate (new test, narrowing, era shift, key rival account) — one line',
    },
    keyCited: {
      type: 'array',
      items: { type: 'string' },
      description: 'up to 5 authorities THIS source itself most relies on, citations copied as printed — only if you actually read it',
    },
    opened: { type: 'boolean', description: 'true ONLY if you fetched and read the real source' },
    fetchNote: { type: 'string', description: 'if the fetch failed or the page was not the source, say so here' },
  },
}

const DRAFT_SCHEMA = {
  type: 'object',
  required: ['memoDraft', 'citedAuthorities'],
  properties: {
    skeleton: { type: 'string', description: 'the citation-tagged analytical skeleton the memo was written FROM (compact bullets; every load-bearing line tagged to a finding index + citation; holes marked GAP)' },
    memoDraft: { type: 'string', description: 'the full memo in Markdown' },
    citedAuthorities: {
      type: 'array',
      description: 'every authority the draft actually cites',
      items: {
        type: 'object',
        required: ['citation'],
        properties: {
          citation: { type: 'string' },
          url: { type: 'string' },
          proposition: { type: 'string' },
          quote: { type: 'string' },
          pincite: { type: 'string' },
          kind: { type: 'string' },
          loadBearing: { type: 'boolean', description: 'true if the core analysis genuinely rests on this authority' },
        },
      },
    },
    missingAuthorities: {
      type: 'array',
      items: { type: 'string' },
      description: 'authorities the memo NEEDS but the findings lacked — each specific enough to retrieve (a case name, an article, a statute); most important first',
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['index', 'verdict'],
        properties: {
          index: { type: 'integer' },
          citation: { type: 'string' },
          verdict: { type: 'string', enum: ['verified', 'needs-correction', 'unverified'] },
          basis: {
            type: 'string',
            enum: ['direct-full-text', 'authoritative-reproduction', 'secondary-corroboration', 'citation-only'],
            description: 'strongest check actually performed: read the passage in the full source / in a reliable reproduction (LII, Justia, CourtListener) / confirmed only via secondary material / confirmed only that the citation exists (e.g. the CourtListener API hit)',
          },
          correctedCitation: { type: 'string' },
          quoteAccurate: { type: 'boolean' },
          examined: { type: 'boolean', description: 'false ONLY if you ran no check of your own on this authority (no lookup, no citator, nothing opened); otherwise true or omitted' },
          currentTreatment: { type: 'string' },
          notes: { type: 'string' },
        },
      },
    },
  },
}

// Deep mode: one adversarial vote on one load-bearing authority. `basis` is REQUIRED: the
// aggregate verdict's evidence level is read off the votes that actually came back, never
// assumed from the instruction to open the source (a paywalled voter reports what it reached).
const BASIS_LEVELS = ['direct-full-text', 'authoritative-reproduction', 'secondary-corroboration', 'citation-only']
const REFUTE_SCHEMA = {
  type: 'object',
  required: ['refuted', 'basis'],
  properties: {
    refuted: { type: 'boolean' },
    basis: {
      type: 'string',
      enum: BASIS_LEVELS,
      description: 'strongest source access you ACTUALLY achieved: read the passage in the full source / in a reliable reproduction (CourtListener, LII, Justia) / confirmed only through secondary material / confirmed only that the citation exists (e.g. the CourtListener API hit). A paywall or bot wall means you did NOT reach full text — report the level you reached.',
    },
    reason: { type: 'string' },
    correctedCitation: { type: 'string' },
    quoteAccurate: { type: 'boolean' },
    currentTreatment: { type: 'string' },
  },
}

// ---- Edits, not re-emission (2026-11-16) -----------------------------------------------------
// Every pass that changes the memo after Draft (deep calibration, the substantive call-in,
// Finalize) returns find-and-replace edits and this script applies them. Three reasons: the
// memo's prose cannot drift, because text no edit names is never retyped; the output is the
// edits alone instead of the whole memo a second and third time, which is most of what those
// passes used to cost; and it lets Finalize run on a cheaper model than the Draft.
const EDIT_ITEM = {
  type: 'object',
  required: ['find', 'replace'],
  properties: {
    find: { type: 'string', description: 'text copied CHARACTER FOR CHARACTER from the memo, long enough to occur exactly once (include neighbouring words); at most about 1,500 characters' },
    replace: { type: 'string', description: 'the full text that takes its place (an empty string deletes it). To INSERT, repeat the find text here with the addition beside it' },
    all: { type: 'boolean', description: 'true ONLY to replace every occurrence of a short recurring string, such as a citation being corrected' },
    why: { type: 'string', description: 'one short line: which instruction this edit carries out, and for which authority' },
  },
}
const EDITS_SCHEMA = {
  type: 'object',
  required: ['edits'],
  properties: { edits: { type: 'array', items: EDIT_ITEM, description: 'the changes to make; an empty array if nothing needs changing' } },
}
const FINAL_SCHEMA = {
  type: 'object',
  required: ['edits', 'tableOfAuthorities', 'limits'],
  properties: {
    edits: { type: 'array', items: EDIT_ITEM, description: 'the changes to the memo text; an empty array if none are needed' },
    tableOfAuthorities: { type: 'string', description: 'the complete Table of Authorities section in Markdown, starting with its heading' },
    limits: { type: 'string', description: 'the complete Limits of this research section in Markdown, starting with its heading' },
  },
}
const EDIT_RULES = `HOW TO RETURN CHANGES — you do NOT return the memo. You return a list of edits, and a script applies
each one to the memo exactly as you wrote it. Text that no edit names stays as it is, so there is
nothing to preserve by retyping it.
- find: copy the passage CHARACTER FOR CHARACTER from the memo below (same punctuation, same
  Markdown marks), and quote enough of the sentence that it occurs exactly ONCE. Keep it short:
  the clause or sentence you are changing, not the paragraph around it, and never more than about
  1,500 characters. An edit whose find text is not in the memo, or is in it more than once, is
  not applied.
- replace: the full text that takes its place. To insert a sentence, quote the sentence it follows
  as find and give that sentence plus the new one as replace. To delete, give an empty replace.
- all: set true only for a short string that must change everywhere it appears (a citation being
  corrected). Otherwise leave it out.
- why: one short line naming the instruction and the authority.
- Edits are applied in the order given, each to the result of the one before, so do not write two
  edits whose find texts overlap. Make the fewest edits that do the job; return an empty list if
  nothing needs changing.`
const EDIT_MAX_FIND = 4000
const QUOTES_SINGLE = "'‘’‚′"
const QUOTES_DOUBLE = '"“”„″'
const DASHES = '-‐‑‒–—'
// The find text is matched exactly first. If that fails, runs of whitespace and the straight/curly
// quote and hyphen/dash variants are treated as equal: those are the characters a model changes
// without noticing when it copies a passage, and tolerating them only LOCATES the passage (the
// replacement is still whatever the model wrote).
const tolerantPattern = (find) => {
  const body = find.trim().split(/\s+/).map((tok) => [...tok].map((ch) => {
    if (QUOTES_SINGLE.includes(ch)) return `[${QUOTES_SINGLE}]`
    if (QUOTES_DOUBLE.includes(ch)) return `[${QUOTES_DOUBLE}]`
    if (DASHES.includes(ch)) return `[${DASHES}]`
    return ch.replace(/[.*+?^${}()|[\]\\\/]/g, '\\$&')
  }).join('')).join('\\s+')
  return (/^\s/.test(find) ? '\\s+' : '') + body + (/\s$/.test(find) ? '\\s+' : '')
}
// Apply edits in order. Returns the new text, how many applied, and every edit that did not
// (with the reason, which goes back to the repair round and, failing that, into the result).
function applyEdits(text, edits) {
  let out = String(text || '')
  const failed = []
  let applied = 0
  for (const raw of Array.isArray(edits) ? edits : []) {
    const e = raw || {}
    const find = typeof e.find === 'string' ? e.find : ''
    const replace = typeof e.replace === 'string' ? e.replace : ''
    const fail = (reason) => failed.push({ find, replace, all: !!e.all, why: String(e.why || ''), reason })
    if (!find.trim()) { fail('the find text was empty'); continue }
    if (find === replace) continue
    if (find.length > EDIT_MAX_FIND) {
      fail(`the find text is ${find.length} characters long (limit ${EDIT_MAX_FIND}): quote only the sentence being changed, and split a long change into several edits`)
      continue
    }
    let spans = []
    for (let i = out.indexOf(find); i >= 0; i = out.indexOf(find, i + find.length)) spans.push([i, i + find.length])
    if (!spans.length) {
      try {
        for (const m of out.matchAll(new RegExp(tolerantPattern(find), 'g'))) if (m[0].length) spans.push([m.index, m.index + m[0].length])
      } catch { spans = [] }
    }
    if (!spans.length) { fail('the find text does not occur in the memo (it must be copied character for character)'); continue }
    if (spans.length > 1 && !e.all) { fail(`the find text occurs ${spans.length} times in the memo: quote more of the sentence so it is unique, or set all:true if every occurrence should change`); continue }
    for (let k = spans.length - 1; k >= 0; k--) out = out.slice(0, spans[k][0]) + replace + out.slice(spans[k][1])
    applied++
  }
  return { text: out, applied, failed }
}
// Apply a pass's edits, with ONE repair round for those whose find text did not match. Restating
// a find string is clerical, so the repair runs on the Finalize model whatever model wrote the
// edits. Edits still unapplied after it are returned, never dropped: the caller discloses them.
async function applyWithRepair(memo, edits, what, phaseName) {
  const before = String(memo || '')
  const first = applyEdits(before, edits)
  let { text, applied, failed } = first
  if (failed.length && !tight(RESERVE_FINALIZE)) {
    log(`${what}: ${failed.length} of ${(edits || []).length} edits did not match the memo text — one repair round.`)
    const fix = await agent(
      `A script tried to apply edits to the legal memo below, and ${failed.length} of them did not match its
text. Restate each one so that it applies. Do NOT change what an edit does: keep its replace text,
changing it only where it must change to fit a corrected find text. For each failed edit, locate
the passage in the memo that it meant, and return the edit with find copied CHARACTER FOR CHARACTER
from the memo as it stands now. Return the edits in the same order, one per failed edit. If the
memo already reads the way an edit intended, return that edit with find and replace both set to
the passage as it stands.

${EDIT_RULES}

=== FAILED EDITS ===
${failed.map((f, i) => `[${i + 1}] why: ${f.why || '(not stated)'}
    it failed because: ${f.reason}
    find: <<<${f.find}>>>
    replace: <<<${f.replace}>>>${f.all ? '\n    all: true' : ''}`).join('\n')}

=== MEMO ===
${text}`,
      withFinalizeModel({ schema: EDITS_SCHEMA, label: `finalize:repair (${what})`, phase: phaseName, effort: 'low' })
    ).catch(() => null)
    if (fix && Array.isArray(fix.edits)) {
      const second = applyEdits(text, fix.edits)
      text = second.text
      applied += second.applied
      // An edit the repair round did not return is still unapplied.
      failed = [...second.failed, ...failed.slice(fix.edits.length)]
    }
  }
  // A pass that cut the memo by more than 40% did something other than edit it.
  if (text.length < before.length * 0.6) {
    log(`${what}: the edits would have cut the memo from ${before.length} to ${text.length} characters — discarded.`)
    return { text: before, applied: 0, failed: [], rejected: true }
  }
  return { text, applied, failed, rejected: false }
}
// Does a cite-checker's currentTreatment text report NEGATIVE treatment? It is free text that
// usually says there is none ("no negative treatment found", "citator: no Negative/Caution
// treatment"), so a signal word counts only if no negation precedes it in the same sentence.
// Errs toward yes: a false yes costs one call on the session model, a false no leaves a
// treatment note to the clerical pass.
const NEGATIVE_SIGNAL = /overrul|abrogat|supersed|revers|vacat|disapprov|repudiat|no longer good law|called into (?:doubt|question)|limited (?:by|to|in)|narrowed|questioned|criticiz|declined to follow|negative|caution/gi
const NEGATOR = /\b(?:no|not|none|never|without|nor|neither)\b|n't/i
const hasNegativeTreatment = (treatment) => {
  const s = String(treatment || '')
  for (const m of s.matchAll(NEGATIVE_SIGNAL)) {
    if (/^no longer/i.test(m[0])) return true
    const sentenceStart = Math.max(s.lastIndexOf('.', m.index), s.lastIndexOf(';', m.index), s.lastIndexOf('|', m.index), s.lastIndexOf('\n', m.index), s.lastIndexOf('—', m.index))
    const lead = s.slice(Math.max(sentenceStart + 1, m.index - 60), m.index)
    if (!NEGATOR.test(lead)) return true
  }
  return false
}

// ---- Phase 1: scope --------------------------------------------------------
phase('Scope')
const plan = await must('Scope', () => agent(
  `You are a senior legal-research librarian. Build a tight research plan.

QUESTION: ${QUESTION}
MODE: ${MODE}  (caselaw = judicial authority; scholarship = secondary/academic; both)
JURISDICTION: ${JURISDICTION}
RESEARCH AS OF: ${AS_OF}
EXTRA CONTEXT: ${NOTES || '(none)'}

Decompose into discrete legal issues; identify controlling jurisdiction(s), key doctrines, and
the authorities most likely central. Produce up to ${VECTOR_CAP} NON-OVERLAPPING search vectors. ${
    MODE === 'both'
      ? 'Cover BOTH case law and scholarship; tag each vector kind.'
      : `All vectors kind="${MODE === 'caselaw' ? 'caselaw' : 'scholarship'}".`
  }
Give each vector concrete queries tuned for free legal sources.
${DO_SCHOLARSHIP ? `DIRECT-ANSWER LANE (required for scholarship/both): the question names a specific
PHENOMENON. Dedicate at least ONE vector to scholarship that treats THAT phenomenon as its own
object of study — not the broader categories it belongs to. Build its queries from the specialist
title terms an expert would expect (e.g. for justices' books: "judicial autobiography", "Supreme
Court memoir", "justices' book deals", "judge as author"), and include a citation-chase step
(references and citing-works of the single most on-point piece). Keep the adjacent-literature
vectors too, but do not let them crowd out this direct lane — a run that maps five adjacent
literatures and misses the on-point one has failed the assignment. Tag this vector's goal with
"[DIRECT-ANSWER]".` : ''}

Also CLASSIFY the question (methodClass + historical):
- methodClass: "doctrinal" (what the law is / how courts decide) or "scholarly" (literature
  mapping, theory, intellectual history). A doctrinal question researched for an academic audience
  is still "doctrinal".
- historical: true if the question asks how doctrine DEVELOPED, what a term meant in an earlier
  era, or about common-law / general-law background — not merely the current rule.
If historical=true, allocate vectors ACROSS TIME LAYERS, not just across sub-issues: at least one
vector for the doctrine's origins / pre-modern ancestry (older cases often use DIFFERENT
terminology — include period vocabulary and predecessor doctrines in those queries), the canonical
era, and the most recent developments. A question-worded search alone will cluster on the modern
canon and miss the early material.
${SOURCES}`,
  { schema: PLAN_SCHEMA, phase: 'Scope', effort: 'medium' }
))
const vectors = (plan.searchVectors || []).slice(0, VECTOR_CAP)
// Assemble the analytical-method brief for Draft/Finalize from Scope's classification.
const METHOD_BRIEF = [
  plan.methodClass !== 'scholarly' || DO_CASES ? METHODS_DOCTRINAL : '',
  plan.methodClass === 'scholarly' || DO_SCHOLARSHIP ? METHODS_SCHOLARLY : '',
  plan.historical ? METHODS_HISTORY : '',
  CLAIM_CALIBRATION,
].filter(Boolean).join('\n\n')
// Historical multi-era questions need coverage, not just depth: raise the soft cap modestly and
// floor the read count near one-read-per-declared-issue so budget trimming degrades depth before
// it silently zeroes out whole eras.
if (plan.historical && !budget.total) SOFT_CAP += 100_000
const READ_FLOOR = plan.historical
  ? Math.min(6, Math.max(3, (plan.issues || []).length))
  : 3
log(`Scoped ${vectors.length} vectors across ${plan.issues?.length || 0} issues (${plan.methodClass || 'doctrinal'}${plan.historical ? ', historical' : ''}).`)

// ---- Phase 2: SURVEY — broad search-only sweep (Lever 2/3: no fetches, cheap model) ----
// Each vector runs WebSearch only and reports candidate authorities from the result snippets.
// Nothing is opened here, so this stays cheap while casting a wide recall net.
const surveyPrompt = (v) => `You are a fast legal research scout pursuing ONE search vector.

OVERALL QUESTION: ${QUESTION}
JURISDICTION: ${plan.jurisdiction || JURISDICTION}
YOUR VECTOR: ${v.label} — ${v.goal}
SUGGESTED QUERIES: ${(v.queries || []).join(' | ')}
KIND: ${v.kind || (DO_CASES && !DO_SCHOLARSHIP ? 'caselaw' : 'scholarship')}

HARD RULES — this is a SEARCH-ONLY sweep:
- Use ONLY WebSearch. Do NOT WebFetch. Do NOT open or read full pages. Work from titles,
  result snippets, and abstracts.
- Run several focused searches; cast a WIDE net for the most relevant, authoritative sources.
- NO-PROGRESS RULE: if two consecutive searches surface nothing new (same hits, equivalent
  queries), stop and report what you have — diminishing returns is a valid stopping reason.
- Report up to ${CANDIDATES_PER_VECTOR} distinct candidate authorities. For each: the best
  citation you can read off the snippet, the URL, and ONE line on why it's on-point.
- Capture a citation only if the snippet actually supports it. NEVER invent a citation, a quote,
  a holding, a volume/page, or a pin cite. No quotes at all in this phase (you haven't read them).
- Judge apparent authoritativeness (high/medium/low) from the source and snippet.
- CENTRALITY FLAG: if a candidate's title/snippet shows it treats the QUESTION'S NAMED PHENOMENON
  as its own object (not just a broader category it belongs to), say so in its one-line why and
  lead with those — they are the ones the triage step should promote to a full read. A title that
  names the phenomenon directly (e.g. an article whose subject IS judicial memoirs / justices' book
  deals) outranks a broad survey that would only mention it in passing.
- Prefer candidates whose FULL TEXT looks fetchable (CourtListener/LII/Justia for cases;
  digital-commons repositories or author pages for articles). If results show both an SSRN page
  and a repository copy of the same paper, report the repository URL.

Quality over quantity — prefer foundational/landmark and directly on-point sources over noise.
${SOURCES}`

// Scholarship modes also sweep the user's own Zotero library (via the Zotero MCP server).
const zoteroSurveyPrompt = `You are searching the USER'S OWN Zotero library for sources relevant
to a legal research question. This is a metadata sweep — do not read full texts here.

QUESTION: ${QUESTION}
ISSUES: ${(plan.issues || []).join(' | ')}

INSTRUCTIONS:
- First load the Zotero tools: run ToolSearch with query
  "select:mcp__zotero__zotero_search_items,mcp__zotero__zotero_item_metadata".
- If the Zotero tools are unavailable or a call errors, return {"candidates": []} immediately.
  Do NOT fall back to web search — other agents cover the web.
- Run a few keyword searches against the library (vary terms across the issues above).
- Report up to ${CANDIDATES_PER_VECTOR} relevant items. For each: the best citation you can build
  from the item's metadata, set zoteroKey to the Zotero item key, and ONE line on relevance.
  Leave url empty unless the metadata has one. No quotes; you haven't read the texts.`

// v6: sweep the user's own project directory — prior memos, downloaded opinions, notes. Nearly
// free and compounds across runs (the Codex-side comparison memo drew real depth from this).
const localSurveyPrompt = `You are sweeping the USER'S LOCAL PROJECT FILES for material relevant to
a legal research question. Metadata/skim sweep only — do not read files end-to-end here.

QUESTION: ${QUESTION}
ISSUES: ${(plan.issues || []).join(' | ')}
PROJECT DIRECTORY: ${PROJECT_DIR}

INSTRUCTIONS:
- Use Glob/Grep/Read (load via ToolSearch "select:Glob,Grep,Read" if needed). Stay INSIDE the
  project directory. Look for research memos, downloaded opinions/articles (.md, .txt, .docx,
  .pdf), and notes; Grep for the key doctrines and case names from the issues above.
- Skim headers/openings only (Read with a small limit) to judge relevance — no full reads.
- Report up to ${CANDIDATES_PER_VECTOR} relevant items as candidates. For each: put the ABSOLUTE
  FILE PATH in url, a short descriptive title in citation (e.g. "Local memo: <title/filename>"),
  kind "other" (or "case"/"article" if the file IS one), and ONE line on why it's relevant.
- These are the user's own files: they may contain prior AI research memos. Those are valuable
  MAPS (what was already found) but are NOT citable authority — say so in the why line.
- If the directory is empty of relevant material, return {"candidates": []}. Never invent files.`

phase('Survey')
// Each survey job is retried once if its agent dies; a vector that still returns nothing is a
// coverage gap, named in the result and in the memo's Limits (2026-11-15 review: a dead vector,
// the direct-answer lane included, used to drop out with no trace and the run could end "complete").
const surveyOpts = (label) => ({ label, phase: 'Survey', schema: CANDIDATES_SCHEMA, model: SCOUT_MODEL, effort: 'low' })
const surveyPlan = vectors.map((v) => ({ label: `survey:${v.label}`.slice(0, 60), what: `search vector "${v.label}"${/\[DIRECT-ANSWER\]/.test(v.goal || '') ? ' (the DIRECT-ANSWER lane)' : ''}`, prompt: surveyPrompt(v) }))
if (DO_SCHOLARSHIP) surveyPlan.push({ label: 'survey:zotero-library', what: "the sweep of the user's Zotero library", prompt: zoteroSurveyPrompt })
if (PROJECT_DIR) surveyPlan.push({ label: 'survey:local-corpus', what: 'the sweep of the local project files', prompt: localSurveyPrompt })
const surveys = await parallel(surveyPlan.map((j) => () => retryOnce(j.label, () => agent(j.prompt, surveyOpts(j.label)))))
const deadSurveys = surveyPlan.filter((_, i) => !surveys[i])

// Lever 1: dedup the candidate pool in PLAIN CODE before any page is fetched, so the same source
// is never read twice across overlapping vectors.
const poolMap = new Map()
for (const s of surveys.filter(Boolean)) {
  for (const c of s.candidates || []) {
    const k = norm(c.citation) || norm(c.url)
    if (!k) continue
    if (!poolMap.has(k)) poolMap.set(k, c)
    else {
      // keep the richer record; prefer the higher apparent authority. Either way the merged
      // record keeps a URL and a Zotero key if EITHER copy had one (the Zotero copy of a source
      // the web survey also found used to lose its key, and with it the full-text route).
      const cur = poolMap.get(k)
      const rank = { high: 3, medium: 2, low: 1 }
      const [win, lose] = (rank[c.authority] || 0) > (rank[cur.authority] || 0) ? [c, cur] : [cur, c]
      poolMap.set(k, { ...lose, ...win, url: win.url || lose.url, zoteroKey: win.zoteroKey || lose.zoteroKey })
    }
  }
}
const pool = [...poolMap.values()]
log(`Survey collected ${pool.length} distinct candidates (search-only, nothing fetched yet).`)

// ---- Phase 3: READ — triage, then fully read each chosen source ONCE -------
// Triage (no tools): pick the READ_CAP candidates most worth a full read. What gets read is the
// memo's evidentiary base, so this judgment call runs on Sonnet, not the scout model.
let selectedIdx = []
if (pool.length > READ_CAP) {
  const triage = await agent(
    `You are triaging search results for a ${OUTPUT} legal memo. From the candidate list, choose the
${READ_CAP} sources MOST worth reading in full. Optimize for: directly on-point to the question,
authoritativeness (landmark cases / leading scholarship), and COVERAGE across the distinct issues —
avoid picking five sources that all make the same point. CENTRALITY FIRST: any candidate that
treats the question's NAMED PHENOMENON as its own object (flagged as central/direct-answer in the
survey, or whose title names the phenomenon) MUST be promoted to a full read before broad adjacent
surveys — those direct sources are the ones the memo most needs to read rather than cite from an
abstract; do not leave a plainly on-point title unread while spending reads on adjacent background.
Break ties toward sources whose full text is likely fetchable (SSRN/journal-only links are often
paywalled and fail to open). Return their
indices, best first — and ORDER BY INTERLEAVED COVERAGE: first the single best source for each
distinct issue/era, then each issue's second-best, and so on. If the budget later trims the list
from the end, this ordering loses depth instead of silently zeroing out whole issues or eras.

QUESTION: ${QUESTION}
ISSUES: ${(plan.issues || []).join(' | ')}

CANDIDATES:
${pool.map((c, i) => `[${i}] (${c.authority || '?'}) ${c.citation} — ${c.why || ''}`).join('\n')}`,
    { schema: TRIAGE_SCHEMA, label: 'triage', phase: 'Read', model: READ_MODEL, effort: 'low' }
  ).catch(() => null)
  // agent() returns null when the agent dies (it rejects only when the budget is spent), so the
  // .catch alone left `triage.selected` to throw a TypeError after the surveys were paid for.
  // Indices are de-duplicated: a repeated index read the same source twice.
  selectedIdx = [...new Set((triage?.selected || []).filter((i) => Number.isInteger(i) && i >= 0 && i < pool.length))].slice(0, READ_CAP)
  if (!triage) log('Triage agent returned nothing — falling back to survey order for the read list.')
}
if (!selectedIdx.length) selectedIdx = pool.slice(0, READ_CAP).map((_, i) => i)
// Budget check: trim the read list (worst-ranked first) rather than die before Draft. The floor
// scales with declared issues on historical questions so trimming can't zero out whole eras.
// Degradation events are collected so the run can return an honest exit state (ported from the
// Codex deep-research-cli exit-state contract). `degradation` holds BUDGET cuts (→
// budget_exhausted); `coverageGaps` holds non-budget holes in the record — dead agents, failed
// opens, unrecovered authorities (→ complete_with_limits). Both are returned under `degradation`.
const degradation = []
const coverageGaps = []
const plannedReads = selectedIdx.length
while (selectedIdx.length > READ_FLOOR && tight(RESERVE_DRAFT + RESERVE_FINALIZE + selectedIdx.length * PER_READ)) selectedIdx.pop()
if (selectedIdx.length < plannedReads) {
  degradation.push(`reads trimmed ${plannedReads} → ${selectedIdx.length} (budget)`)
  log(`Budget tight — trimmed full reads ${plannedReads} → ${selectedIdx.length} (floor ${READ_FLOOR}).`)
}
const selectedSet = new Set(selectedIdx)
const toRead = selectedIdx.map((i) => pool[i])
log(`Triaged to ${toRead.length} sources for full reads (of ${pool.length} candidates).`)

// Read each selected source exactly once (Lever 1: fetch-once).
const readPrompt = (c) => `You are extracting from ONE legal source. Fetch and read it, then report.

OVERALL QUESTION: ${QUESTION}
SOURCE TO READ: ${c.citation}
URL: ${c.url || '(none — find it via a single WebSearch, then fetch)'}
${c.zoteroKey ? `ZOTERO KEY: ${c.zoteroKey} — this source is in the user's Zotero library. Load the
Zotero tools (ToolSearch query "select:mcp__zotero__zotero_item_fulltext") and read the full text
from there instead of the web. If that fails, fall back to the web instructions below.` : ''}
INSTRUCTIONS:
- Fetch and read this ONE source. Try the given URL first (or one WebSearch to locate it). If that
  fetch fails, is paywalled, or isn't actually the source, try up to TWO fallbacks, then stop:
  * cases — CourtListener's HTML opinion view, Cornell LII, or Justia;
  * articles — a digital-commons repository copy or the author's faculty page (one WebSearch like
    "<title>" digitalcommons OR site:.edu to locate a mirror).
  HARD CAP: 3 fetch attempts total. Do not browse beyond locating this one source.
- PROBE FIRST when you hold more than one candidate URL (the given one plus a mirror or two):
  test them ALL in ONE Bash call before fetching any —
    python3 "${PROBE}" "<url1>" "<url2>" ...
  It returns, per URL, fetchable true/false, the HTTP status, the host rule that applies (SSRN,
  bepress, HeinOnline and sign-in walls are known blocks) and a Wayback snapshot URL when one
  exists. Fetch only what it marks fetchable (or the snapshot). A URL it marks not fetchable
  counts as one of your attempts without a fetch; do not try variants of it.
- ACCESS DISCIPLINE: use only WebSearch, WebFetch, and the capped fetcher below. NEVER use
  browser-automation tools, library proxies, SSO/login flows, or PDF-download acrobatics to get
  past a paywall or bot wall (HeinOnline, WAF-protected repositories, publisher sites) —
  a paywalled source is a legitimate opened=false with the paywall named in fetchNote.
- PDF URLs: do NOT WebFetch them. Run the capped fetcher instead, via the Bash tool (if Bash isn't
  loaded, first run ToolSearch with query "select:Bash"):
    python3 "${FETCH_PAGE}" "<url>"
  It enforces a hard size cap and extracts the text; if it refuses (too big / unextractable),
  count that as a failed attempt and move to a fallback.
- LOCAL FILES: if the URL is an absolute file path (starts with "/"), do not use the web at all —
  read it with the Read tool (load via ToolSearch "select:Read" if needed) and set opened=true.
  A local AI-research memo is a MAP, not authority: extract which authorities it identifies as
  central (into keyCited) and, into proposition, a RECONCILIATION SUMMARY — its thesis in one
  sentence, any strong frequency/priority/universal claims it makes ("first", "overwhelmingly",
  "never"), and any corrections or caveats it has already established (into limitation). Say in
  fetchNote that this is a local research memo, not citable authority. This lets the draft build
  on prior work instead of silently re-asserting claims it already qualified.
- Extract: the precise citation, the key proposition it establishes, ONE short verbatim quote that
  supports it, and a pinpoint cite. Set opened=true.
- Also extract (one line each, ONLY from text you actually read — leave empty otherwise):
  * posture — is the proposition a holding, dicta, alternative reasoning, an ARGUENDO concession
    or assumption ("conceding that..."), a concurrence, a dissent, or a NONPRECEDENTIAL
    disposition (equally divided affirmance, plurality)? Misattributing a dissent's language to
    the court, or an arguendo concession to a holding, is a classic error — check whose opinion
    the passage sits in before quoting.
  * bearing — how the source bears on the question itself: direct answer / assumes the premise /
    process-only / adjacent doctrine or clause / background.
  * limitation — the strongest limitation, qualification, or adverse reading visible in the source.
  * separateOpinions — for cases: notable concurrences/dissents and their point.
  * significance — what this source ADDS to the doctrine or debate (new test, narrowing, era
    shift, key rival account).
- Also report in keyCited up to 5 authorities THIS source itself most relies on — copy their
  citations as printed in the text; skip any you can't read directly off the page.
- If every attempt fails, set opened=false and explain in fetchNote — carry over the citation and
  one-line relevance from the search snippet ONLY. Do NOT supply a proposition, holding, quote, or
  pin cite from memory; leave them empty.
- Never invent anything. Verbatim means verbatim.
${BLUEBOOK}
${SOURCES}`

phase('Read')
const readAgent = (c) => agent(readPrompt(c), {
  label: `read:${(c.citation || c.url || '').slice(0, 50)}`,
  phase: 'Read',
  schema: READ_SCHEMA,
  model: READ_MODEL,
  effort: 'low',
})
const readResults = await parallel(
  toRead.map((c) => () => retryOnce(`read:${(c.citation || c.url || '').slice(0, 50)}`, () => readAgent(c)))
)
// Selected sources whose reader died twice. They used to vanish: dropped from the read results
// and, being "selected", excluded from the unread leads too, so triage's top pick could be
// missing from the draft's findings with the run still "complete" (2026-11-15 review). They are
// carried as unread leads and counted as a coverage gap.
const deadReads = toRead.filter((_, i) => !readResults[i])

// Findings = the fully-read sources, PLUS the un-selected candidates carried as unread leads
// (Lever 2: breadth without paying to fetch them — the draft may mention, but must hedge, these).
const readFindings = readResults.filter(Boolean)
// Citation-network harvest: authorities the fully-read sources themselves rely on. Nearly free —
// the reader already had the text in context — and approximates Westlaw's cited-reference
// expansion. These join the unread-leads pool (hedged in the draft, cite-checked if cited).
const citedWithin = []
for (const f of readFindings.filter((r) => r.opened)) {
  for (const kc of (f.keyCited || []).slice(0, 5)) {
    const k = norm(kc)
    if (!k || poolMap.has(k) || citedWithin.some((c) => norm(c.citation) === k)) continue
    citedWithin.push({
      kind: 'other',
      citation: kc,
      why: `relied on by ${f.citation}`,
      proposition: `relied on by ${f.citation} (not independently read)`,
      opened: false,
    })
  }
}
const poolLeads = pool
  .filter((_, i) => !selectedSet.has(i))
  .map((c) => ({ ...c, proposition: c.why || '', opened: false }))
const deadReadLeads = deadReads.map((c) => ({ ...c, proposition: c.why || '', opened: false, fetchNote: 'selected for a full read, but the reading agent failed twice — unread' }))
// The harvest gets its own share of the lead slots. It used to be appended after the pool's
// leftovers and then cut at LEADS_CAP, and the leftovers alone usually filled the cap (40
// candidates less 8 reads is 32 against a cap of 16), so the harvested authorities never reached
// the draft while the log said they were carried (2026-11-15 review). A third of the slots are
// kept for them, taken round-robin across the read sources so one source cannot fill the share.
const harvestBySource = new Map()
for (const h of citedWithin) { if (!harvestBySource.has(h.why)) harvestBySource.set(h.why, []); harvestBySource.get(h.why).push(h) }
const harvestOrdered = []
for (let r = 0; harvestOrdered.length < citedWithin.length; r++) for (const list of harvestBySource.values()) if (list[r]) harvestOrdered.push(list[r])
const HARVEST_SLOTS = Math.min(harvestOrdered.length, Math.ceil(LEADS_CAP / 3))
const harvestLeads = harvestOrdered.slice(0, HARVEST_SLOTS)
const leads = [...deadReadLeads, ...poolLeads.slice(0, Math.max(0, LEADS_CAP - HARVEST_SLOTS - deadReadLeads.length)), ...harvestLeads]
const findings = [...readFindings, ...leads]
const openedCount = readFindings.filter((f) => f.opened).length
log(`Read ${openedCount} sources in full; carrying ${leads.length} unread leads (${harvestLeads.length} of ${citedWithin.length} harvested from within read sources${deadReads.length ? `; ${deadReads.length} selected source(s) unread after a reader failure` : ''}).`)

// ---- Phase 4: draft the memo from findings --------------------------------
const memoFormat =
  OUTPUT === 'practitioner'
    ? `PRACTITIONER structure:
1. **Question Presented**  2. **Brief Answer** (bottom line + confidence)
3. **Facts / Assumptions**  4. **Discussion** (by issue; IRAC: rule from controlling authority,
   application, candid treatment of counterarguments and contrary authority)  5. **Conclusion**`
    : `ACADEMIC structure:
1. **Introduction & Question**  2. **Background / Doctrinal Landscape**
3. **Analysis** (synthesize the authorities and scholarly debate; who argues what; tensions and
   open questions; strongest positions on each side)  4. **Assessment**
5. **Conclusion & Avenues for Further Work** — use footnote-style numbered citations.`

const bundle = findings
  .map(
    (f, i) =>
      `[${i}] ${f.citation} ${f.opened ? '(read in full)' : '(from search extract — UNREAD)'}\n  URL: ${f.url || ''}\n  Kind: ${f.kind || '?'} ${f.court || ''} ${f.year || ''}\n  Proposition: ${f.proposition}\n  Holding: ${f.holding || '(n/a)'}\n  Quote: ${f.quote || '(none)'} ${f.pincite ? '@ ' + f.pincite : ''}${
        f.posture ? `\n  Posture: ${f.posture}` : ''
      }${f.bearing ? `\n  Bearing on the question: ${f.bearing}` : ''}${f.limitation ? `\n  Limitation/adverse: ${f.limitation}` : ''}${
        f.separateOpinions ? `\n  Separate opinions: ${f.separateOpinions}` : ''
      }${f.significance ? `\n  Adds: ${f.significance}` : ''}`
  )
  .join('\n\n')

phase('Draft')
const draft = await must('Draft', () => agent(
  `You are a meticulous legal writer drafting a research memo for a law professor.

QUESTION: ${QUESTION}
JURISDICTION: ${plan.jurisdiction || JURISDICTION}
RESEARCH AS OF: ${AS_OF}

RULES:
- Build the memo ONLY from the findings below. Do NOT add any case, statute, quote, or article
  from memory.
- Lean on the authorities marked "(read in full)". You MAY cite an "(UNREAD)" search-extract source
  for breadth, but hedge it ("reportedly" / "per its abstract") and NEVER attribute a verbatim quote
  or a pin cite to an unread source.
- Distinguish holdings from dicta; note binding vs. persuasive authority. Findings carry Posture /
  Bearing / Limitation / Separate-opinions / Adds fields where the reader captured them — USE
  them: they are what lets the memo label dicta as dicta, qualify a rule, and weigh rival strands.
  In particular, a finding whose bearing is "process-only", "assumes the premise", or "adjacent
  doctrine or clause" must not carry a threshold or definitional claim, and a posture of
  "arguendo" or "nonprecedential disposition" must be presented as exactly that.
- A finding whose fetchNote marks it a LOCAL RESEARCH MEMO is a map, not authority: you may use it
  to structure coverage, but cite the underlying authorities, never the memo itself.
- Candid about contrary authority and weaknesses; thoughtful analysis over advocacy.

SKELETON BEFORE PROSE (do this FIRST; return it via the skeleton field):
Before writing any prose, build the analytical skeleton — for each issue: the conclusion, the
governing rule/synthesis, the support (which finding [indices] establish it), the application,
and the counter-authority — every load-bearing line tagged to the specific finding index +
citation it rests on, with "(UNREAD)" hedges carried onto the tag. Where a line has NO finding
to rest on, mark it "GAP: <what would support it>" — those become missingAuthorities and a
noted gap in the memo, never smoothed-over prose. Fluent prose is where unsupported analysis
hides; the skeleton forces every claim to name its authority BEFORE the writing starts. Then
write the memo FROM the skeleton: if a conclusion you're writing has no skeleton line, stop —
add the line (with its authority) or hedge the claim as unsupported. Return the skeleton as
compact bullets (not prose) in the skeleton field.
Calibrate depth like a budget: explanation in proportion to a skeptical reader's doubt on THAT
point. Spend it on the few outcome-determinative or contested points; compress the easy and
undisputed ones to a sentence. Equal depth on every point is mis-calibrated by definition.

${METHOD_BRIEF}

${memoFormat}
${BLUEBOOK}

After the memo:
- List EVERY authority you actually cited (citedAuthorities). Mark loadBearing=true on the
  authorities the core analysis genuinely rests on — those get the heaviest cite-check.
- If an authority the memo NEEDS is missing from the findings, do NOT invent or cite it — name it
  in missingAuthorities (at most ${GAPFILL_CAP}, most important first, each specific enough for one
  targeted retrieval: a case name, an article, a statute). Note the gap in the memo text itself.

=== FINDINGS ===
${bundle || '(none)'}

Return the memo draft (Markdown), the cited authorities, and any missing authorities.`,
  { schema: DRAFT_SCHEMA, phase: 'Draft', effort: 'high' }
))

const cited = (draft.citedAuthorities || []).filter((c) => c && c.citation)

// ---- Phase 4.25 (deep only): adversarial thesis calibration ----------------------------------
// Cite-checking catches false statements about sources; it cannot catch true findings assembled
// into unsupported generalizations. Deep runs get one bounded calibration pass on the draft —
// quantifiers, selection effects, source roles, boundary dates, rival readings — working from the
// draft alone (compact input; no re-reading of the corpus). Lean runs rely on the calibration
// rules already injected into the Draft prompt plus the Finalize audit. The reviewer returns
// edits (2026-11-16), not a second copy of the draft: same model as before, a fraction of the
// output, and no chance of the draft coming back shortened.
const calibrationUnapplied = []
if (DEEP && !tight(RESERVE_FINALIZE + 35_000)) {
  const cal = await agent(
    `You are an adversarial calibration reviewer for a legal research memo. Do NOT re-research, add,
or remove authorities. Your only job is to make the memo's CLAIMS match its EVIDENCE. Audit the
draft below and return edits (same structure, lightest touch) fixing:
1. QUANTIFIERS: every "first/last/only/never/always/settled/overwhelmingly/dominant/rare/erased/
   dead" — was the research designed to support that? If not, downgrade to sample-scoped language
   ("in the leading cases reviewed", "the earliest clean statement found in this research").
2. SELECTION EFFECTS: does any era-level or frequency claim rest on a sample of contested/famous
   cases? Add the caveat or narrow the claim.
3. SOURCE ROLES: is any process-only, arguendo, assumed, adjacent-doctrine, concurrence/dissent,
   or nonprecedential authority silently carrying a holding-weight or threshold claim? Fix the
   characterization in place.
4. BOUNDARY DATES: is out-of-period material counted as in-period evidence? Label it epilogue.
5. RIVAL READINGS: for the memo's central thesis, is there a plausible rival synthesis of the SAME
   findings the memo doesn't address? If so, add a short acknowledgment — do not rewrite the thesis.
Preserve every citation, quote, and pincite exactly as written. If nothing needs fixing in a
section, leave it untouched.

${EDIT_RULES}

QUESTION: ${QUESTION}

=== DRAFT ===
${draft.memoDraft || ''}`,
    { schema: EDITS_SCHEMA, label: 'calibrate:thesis', phase: 'Draft', effort: 'high' }
  ).catch(() => null)
  if (cal && Array.isArray(cal.edits) && cal.edits.length) {
    const r = await applyWithRepair(draft.memoDraft, cal.edits, 'calibration', 'Draft')
    draft.memoDraft = r.text
    if (r.failed.length) calibrationUnapplied.push(...r.failed)
    log(r.rejected
      ? 'Deep calibration edits discarded — keeping the draft as written.'
      : `Deep calibration: ${r.applied} edit${r.applied === 1 ? '' : 's'} applied to the draft${r.failed.length ? `, ${r.failed.length} could not be located` : ''}.`)
  } else if (cal) {
    log('Deep calibration found nothing to change.')
  }
}

// ---- Phase 4.5: bounded gap-fill — only when the draft itself says the record is thin ---------
let missing = (draft.missingAuthorities || []).filter(Boolean).slice(0, GAPFILL_CAP)
if (missing.length && tight(RESERVE_FINALIZE + missing.length * PER_READ)) {
  degradation.push(`gap-fill skipped for ${missing.length} flagged authorities (budget)`)
  log(`Budget tight — skipping gap-fill for ${missing.length} flagged authorities (draft already notes the gaps).`)
  missing = []
}
let gapFindings = []
if (missing.length) {
  log(`Draft flagged ${missing.length} missing authorities — one targeted retrieval each.`)
  const gapPrompt = (m, retry) => `A legal memo draft needs an authority the research did not capture:

NEEDED: ${m}
OVERALL QUESTION: ${QUESTION}

- ${retry
    ? `A first retrieval attempt FAILED. Try harder but stay bounded: up to THREE WebSearches with
  varied phrasings (author name, title fragment, reporter/docket guess), checking digital-commons
  repositories and author faculty pages for article mirrors. Then fetch the best hit ONCE`
    : 'ONE WebSearch to locate it, then WebFetch it ONCE'} and extract per the schema (precise
  citation, key proposition, one short verbatim quote, pinpoint cite; opened=true).
- If you cannot find or confirm it, set opened=false and say so in fetchNote. NEVER invent a
  citation, quote, or pin cite — an honest miss is fine; the draft already notes the gap.
${BLUEBOOK}
${SOURCES}`
  const gapJob = (m, retry) => () =>
    agent(gapPrompt(m, retry), {
      label: `gapfill${retry ? '-retry' : ''}:${m.slice(0, 40)}`,
      phase: 'Read',
      schema: READ_SCHEMA,
      model: READ_MODEL,
      effort: 'low',
    })
  const round1 = await parallel(missing.map((m) => gapJob(m, false)))
  const misses = []
  round1.forEach((f, i) => {
    if (f && f.opened && f.citation) gapFindings.push(f)
    else misses.push(missing[i])
  })
  // One bounded retry wave for the misses — wider search strategy, same per-agent caps.
  if (misses.length && !tight(RESERVE_FINALIZE + misses.length * PER_READ)) {
    log(`Gap-fill round 1 recovered ${gapFindings.length}/${missing.length}; retrying ${misses.length} with a wider search.`)
    const round2 = await parallel(misses.map((m) => gapJob(m, true)))
    gapFindings.push(...round2.filter((f) => f && f.opened && f.citation))
  }
  log(`Gap-fill recovered ${gapFindings.length} of ${missing.length}.`)
}

// ---- Phase 5: verify ONLY the cited authorities (+ gap-fill finds) ---------
phase('Verify')
// gi = stable global index used to join verdicts back to authorities. wasRead marks authorities a
// research agent already opened and quoted THIS run — cite-checkers skip existence re-confirmation
// for those and spend their effort on citation format + negative treatment.
// Matched on the reporter cite, not the whole string (second live run, 2026-11-16): a reader
// returns its citation with pincites, a parallel cite or an opinion parenthetical
// ("364 U.S. 587, 596-97", "595 U.S. 360 (2022) (Kavanaugh, J., concurring…)"), the Draft cites
// the bare case, and on whole-string equality four of eight read opinions lost the tag and were
// reported as load-bearing authorities checked at citation level only. A citation with no
// reporter cite (an article, a statute) still matches on the normalized string.
const CITE_TRIPLE = /\b(\d{1,3})\s+(U\.\s?S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?[23]d)?|F\.\s?App'?x|B\.R\.|So\.(?:\s?[23]d)?|P\.(?:\s?[23]d)?|A\.(?:\s?[23]d)?|N\.[EW]\.(?:\s?[23]d)?|S\.[EW]\.(?:\s?[23]d)?|N\.Y\.S\.(?:\s?[23]d)?|Cal\.\s?(?:App\.\s?)?[2-5]th)\s+(?:\([^)]{1,20}\)\s+)?(\d{1,5})\b/g
const citeKeys = (s) => [...String(s || '').matchAll(CITE_TRIPLE)].map((m) => `${m[1]} ${m[2].toLowerCase().replace(/[^a-z0-9]/g, '')} ${m[3]}`)
const readKeys = new Set()
for (const f of readFindings.filter((f) => f.opened)) {
  readKeys.add(norm(f.citation))
  for (const k of citeKeys(f.citation)) readKeys.add(k)
}
const wasReadThisRun = (citation) => readKeys.has(norm(citation)) || citeKeys(citation).some((k) => readKeys.has(k))
const toVerify = [
  ...cited,
  ...gapFindings.map((f) => ({
    citation: f.citation, url: f.url, proposition: f.proposition,
    quote: f.quote, pincite: f.pincite, kind: f.kind, gapFill: true,
  })),
].map((c, i) => ({ ...c, gi: i, wasRead: !!c.gapFill || wasReadThisRun(c.citation) }))

// Per-run, per-chunk, per-authority scratch path for source dumps (CLAUDE-07). `idx` is the
// authority's global index, or the literal "<index>" placeholder the agent substitutes.
const srcFile = (ch, idx) => `/tmp/lr-${RUN_TAG}-c${ch[0].gi}-src-${idx}.txt`
const refuteFile = (c, k) => `/tmp/lr-${RUN_TAG}-refute-${c.gi}-v${k}.txt`

const chunkPrompt = (ch) => `You are a cite-checker confirming authorities a legal memo relies on.

STEP 0 — deterministic case lookup, FIRST, for all the CASE citations below in one shot. Run via
the Bash tool (if Bash isn't loaded, first run ToolSearch with query "select:Bash"):
  python3 "${CHECK_CITE}" "<case cite 1>" "<case cite 2>" ...
It queries CourtListener's free citation-lookup API. A found result whose case name matches the
cited caption settles existence and the reporter cite — no web search needed for those checks. If
the script errors (offline / rate-limited), fall back to web checking.

Then, for EACH authority below, do a QUICK confirmation on the free legal web:
(1) does it genuinely exist; (2) is the citation accurate; (3) if a quote/proposition is given,
does it match the source; (4) for CASES, a systematic treatment check via the citing-opinions tool
(one Bash call per case):
  python3 "${CL_TOOLS}" citing "<reporter cite>" --limit 15
Read treatment_probe.most_relevant AND name_search_treatment_probe, prioritizing rows with
mentions_target=true (the snippet actually names this case's parties). The tool runs TWO routes —
the citation graph and a full-text search for the case name filed after the decision — because
they miss different cases; routes says what each returned and distinct_cases_returned is the
deduplicated count (the index is one row per opinion, so a case with a dissent is two rows —
never report row counts as case counts). A signal row about THIS case (e.g. "overruled by <X>")
goes in currentTreatment — name the treating case and, if the snippet shows it, the scope (full
overruling / partial abrogation / narrowing); if scope isn't visible, report the signal with
"scope unconfirmed". Rows about OTHER cases are noise — ignore them; the tool's caveats explain.
If the cite will not resolve, run python3 "${CL_TOOLS}" find "<case name>" --cite "<cite>" first:
an unresolved citation is a search problem, never evidence of fabrication, and opinions whose
text cite the string confirm it is real. Opinions that postdate your training data are real.
Also report most_recent_citing_date as a plain fact in currentTreatment — "most recent citing
opinion in the CourtListener index: <date>" — and, if that date is old, add that the index covers
only the opinions CourtListener holds and the probe read only the top rows. That field shows
recency WITHIN THE RETRIEVED INDEX, nothing more: do NOT describe the case as "dormant", "in
disuse", "moribund", or the like on that basis alone — such a characterization needs separate
support (a treatise, a court saying so, a citing-opinion count across a complete citator), and
without it you report only the date and the limitation. If the script errors, fall back
to the quick web search ("<case name> overruled" / "abrogated"). No hits is NOT proof of good
law — this approximates, not replaces, Shepard's/KeyCite.
Authorities tagged [READ IN FULL THIS RUN] were already opened and quoted by a research agent this
run — skip existence re-confirmation for those; check only citation format and negative treatment.
${DEEP
    ? `Be adversarial — try to disprove each; open the source to confirm quotes. When you open a
source to check a quote, settle verbatim-ness deterministically: python3 "${FETCH_PAGE}" "<url>"
--out ${srcFile(ch, '<index>')}, then python3 "${VERIFY_QUOTES}" ${srcFile(ch, '<index>')} "<quote>" — its
verbatim/normalized/altered/not_found status (and word_diff on misses) is the answer; save your
judgment for whether the passage supports the proposition.`
    : 'Be efficient — a reliable search/catalog/API hit confirming the case name, reporter, and year is enough for existence; only open the source if something looks off. You are confirming, not re-researching (but if you DO open a source to check a quote, run it through the deterministic verifier: python3 "' + FETCH_PAGE + '" "<url>" --out ' + srcFile(ch, '<index>') + ' && python3 "' + VERIFY_QUOTES + '" ' + srcFile(ch, '<index>') + ' "<quote>").'}
SCRATCH FILES: other cite-check agents are running at the same time and share /tmp, so write
source dumps ONLY to the path pattern above, substituting the authority's [bracketed] index for
<index> (one file per authority); never reuse a file for a different authority and never write to
a generic name like /tmp/src.txt.
ACCESS DISCIPLINE: at most 2 access attempts per authority, via WebSearch/WebFetch only — never
browser automation, library proxies, or SSO/login flows. If a source sits behind a paywall or bot
wall, stop and report the strongest basis you actually reached (secondary-corroboration or
citation-only are honest answers); do not grind on access.
Return one verdict per authority: "verified", "needs-correction" (give correctedCitation), or
"unverified" (could not confirm). Echo each authority's index EXACTLY as given in [brackets].
"unverified" is a FINDING: you looked and could not confirm it, or found evidence against it. If
you ran no check of your own on an authority (no lookup, no citator call, nothing opened), set
examined=false and say so in notes; do not let a check you skipped read as a check that failed.
For each verdict also report basis — the STRONGEST check you actually performed, honestly:
"direct-full-text" (read the passage in the full source), "authoritative-reproduction" (read it in
a reliable reproduction such as CourtListener/LII/Justia), "secondary-corroboration" (confirmed
only through secondary material), or "citation-only" (confirmed the cite exists — e.g. the
CourtListener API hit — without checking the proposition). Do not report a stronger basis than the
check you ran.

AUTHORITIES:
${ch
  .map((c) => `[${c.gi}]${c.wasRead ? ' [READ IN FULL THIS RUN]' : ''} ${c.citation}\n    URL: ${c.url || ''}\n    Proposition: ${c.proposition || ''}\n    Quote: ${c.quote || '(none)'}`)
  .join('\n')}
${SOURCES}`

const chunkAgent = (ch) => agent(chunkPrompt(ch), {
  label: `verify:${ch[0].gi}-${ch[ch.length - 1].gi} (${ch.length})`,
  phase: 'Verify',
  schema: VERDICT_SCHEMA,
  model: VERIFY_MODEL,
  effort: 'low',
})
// A dead chunk agent would leave up to VERIFY_CHUNK authorities with no verdict (and Finalize
// would then caveat every one of them in the memo): retry once, then account below.
const chunkJob = (ch) => async () => {
  let o = await chunkAgent(ch)
  if (!o) { log(`verify:${ch[0].gi}-${ch[ch.length - 1].gi} died — retrying once`); o = await chunkAgent(ch) }
  // Verdicts are joined to authorities by the echoed index. An index that is not in THIS chunk
  // would stamp this checker's verdict on an authority another checker was given (first one
  // wins), the same harm as the positional fallback removed in v4. Such a verdict loses its
  // index and can only be joined by its citation (2026-11-15 review).
  const mine = new Set(ch.map((c) => c.gi))
  return ((o && o.verdicts) || []).map((v) => (mine.has(v.index) ? v : { ...v, index: undefined }))
}

// Deep mode: each load-bearing authority gets 3 independent refutation votes; ≥2 refutes kill it.
// Three voters given one identical prompt make three correlated reads of the same source, so a
// 3-vote panel is weaker than it looks. Each voter LEADS with a different route — the record, the
// passage in context, or the strongest adverse reading — so their errors decorrelate; all four
// checks stay mandatory for every voter. (Idea from the wise-men-flash skill's per-member
// reasoning procedures, 2026-11-03; no text copied. Prompt-only: no extra calls.)
// The routes are source-aware: the refute set in a scholarship or mixed run holds articles,
// books and statutes too, and the CourtListener tools resolve opinions only. `kind` is a free
// string from the Draft; "other" (what citedWithin stamps on every harvested cite) and an empty
// kind are UNKNOWN, not non-case: they fall back to the caption (markup stripped) and then to a
// reporter-cite pattern, and an authority that matches neither gets the unknown route, which keeps
// the case tools and tells the voter to establish the type first (Codex reviews, 2026-11-03).
const REPORTER_CITE = /\b\d+\s+(?:U\.S\.|S\.\s?Ct\.|L\.\s?Ed\.(?:\s?2d)?|F\.(?:\s?(?:2d|3d|4th))?|F\.\s?Supp\.(?:\s?[23]d)?|F\.\s?App'?x|B\.R\.|So\.(?:\s?[23]d)?|P\.(?:\s?[23]d)?|A\.(?:\s?[23]d)?|N\.[EW]\.(?:\s?[23]d)?|S\.[EW]\.(?:\s?[23]d)?|N\.Y\.S\.(?:\s?[23]d)?|Cal\.\s?(?:App\.\s?)?[2-5]th|(?!Stat\.|Reg\.|Cong\.)[A-Z][a-z]+\.(?:\s?[23]d)?|WL|U\.S\.\s?LEXIS)(?:\s?\([^)]{1,20}\))?\s+\d+/
const KIND_CASE = /^(case|cases|caselaw|case law|opinion|judicial opinion|decision|judgment)$/
const KIND_STATUTE = /^(statute|statutes|statutory|regulation|regulations|rule|rules|constitution|constitutional provision|code|ordinance|treaty|legislation)$/
const KIND_SECONDARY = /^(article|articles|book|books|treatise|note|student note|essay|chapter|book chapter|report|secondary|secondary source|scholarship|law review article|casebook|monograph)$/
const authorityType = (c) => {
  // Explicit kinds count only as whole labels: "casebook" or "case note" is not a case and
  // "constitutional treatise" is not a statute (Codex review, 2026-11-03). Anything else is read
  // off the citation, and conflicting signals (a reporter cite plus a statutory signature in an
  // explanatory parenthetical) go to the unknown route instead of a guess.
  const kind = (c.kind || '').trim().toLowerCase().replace(/[_-]+/g, ' ')
  if (KIND_CASE.test(kind)) return 'case'
  if (KIND_STATUTE.test(kind)) return 'statute'
  if (KIND_SECONDARY.test(kind)) return 'secondary'
  const cite = (c.citation || '').replace(/[*_`]/g, '').trim()
  const statuteSig = /\b(U\.S\.C\.(?:A\.|S\.)?|C\.F\.R\.|Stat\.|Pub\. L\.|Fed\. R\. (?:Civ|Crim|App|Evid)\. P\.|Fed\. R\.|Const\.|Reg\.)\s/.test(cite)
  const captionSig = /\bv\.\s|^(In re|Ex parte|Matter of)\b/.test(cite)
  // Journal markers block BOTH the statute and the case branch: a note titled "Interpreting 42
  // U.S.C. § 1983" in a law review is neither (Codex review, 2026-11-03).
  const journalSig = /\b(L\. ?Rev\.|L\.J\.|J\. ?L\.|L\. ?Q\.|Rev\.\s|J\.\s|Const\. Comment\.|Comment\.\s|Stud\.\s|Pol'y\s)/.test(cite)
  const reporterRaw = REPORTER_CITE.test(cite)
  const reporterSig = reporterRaw && !journalSig
  if (statuteSig && !journalSig && !captionSig && !reporterRaw) return 'statute'
  // A caption alone ("v.", "In re") is not enough: article titles name cases ("A Critical Guide to
  // Marbury v. Madison, 1969 Duke L.J. 1"). Only a reporter cite with no journal marker and no
  // statutory signature is a case; everything else keeps the case tools behind a type check.
  if (reporterSig && !statuteSig) return 'case'
  return 'unknown'
}
const REFUTE_ROUTES_BY_TYPE = {
  case: {
    1: `YOUR ROUTE (voter #1 — the record first): settle (1) and (2) deterministically before anything
else — the CourtListener lookup, then the quote verifier on the saved source — and only then read
for substance. Your adversarial effort goes to the mechanics: a wrong volume, page, year, court or
pincite; a quote that is not verbatim; a parenthetical or bracket that changes the words.`,
    2: `YOUR ROUTE (voter #2 — the passage first): open the source and read the quoted passage IN
CONTEXT — the paragraph before and after it, and whose opinion it sits in — before running any
tool. Your adversarial effort goes to substance: does the passage, read fairly, support the
proposition AS STATED at the pincite, or only a narrower one; is it a holding, a dictum, an arguendo
assumption, a party's argument as recited by the court, a dissent or a concurrence. Then run the
deterministic quote check, and the case tools last.`,
    3: `YOUR ROUTE (voter #3 — the strongest adverse reading first): start from what would make this
citation wrong and look for it — negative or limiting treatment (the citing-opinions probe and, for
a lower court, the history tool, before anything else), a later same-litigation disposition, a
holding narrower than the proposition, a limiting fact the memo omits, a competing line of
authority the source itself acknowledges. Then confirm existence, the cite and the quote.`,
  },
  statute: {
    1: `YOUR ROUTE (voter #1 — the record first): this is a statute, regulation, rule or constitutional
provision, so the case tools do not apply. Settle (1) and (2) against the OFFICIAL text before
anything else — the code or register (uscode.house.gov, govinfo, eCFR, the state legislature's
site, or LII as a reproduction) at the cited title, section and subsection, in the version in force
on the date the memo's use requires (see RESEARCH AS OF below and the proposition's own date) —
then run the quote verifier on the saved text. Your
adversarial effort goes to the mechanics: a wrong section or subsection, a quote that is not
verbatim, words quoted from a different version.`,
    2: `YOUR ROUTE (voter #2 — the text first): this is a statute, regulation, rule or constitutional
provision, so the case tools do not apply. Read the cited provision IN CONTEXT — the definitions
section, the neighbouring subsections, any exception or savings clause — before running any check.
Your adversarial effort goes to substance: does the text, read with its definitions, support the
proposition AS STATED, or only a narrower one; is the memo quoting operative text or a heading,
note or preamble. Then run the deterministic quote check.`,
    3: `YOUR ROUTE (voter #3 — the strongest adverse reading first): this is a statute, regulation, rule
or constitutional provision, so the citing-opinions probe does not apply. Start from what would
make this citation wrong and look for it — an amendment, repeal or renumbering between the version
quoted and the date the memo's use requires (see RESEARCH AS OF below; a change after that date is
a disclosure for currentTreatment, not a refutation), a sunset or effective-date clause, a
provision held unconstitutional or preempted, a definition elsewhere in the title that narrows the
quoted words, a controlling construction by the courts that the memo's reading ignores. Then
confirm the section, the version and the quote.`,
  },
  secondary: {
    1: `YOUR ROUTE (voter #1 — the record first): this is a secondary source, so the case tools do not
apply. Settle (1) and (2) against the catalog record or the source's own front matter before
anything else — author, title, journal or publisher, volume, first page, year, edition — then run
the quote verifier on the saved text, and only then read for substance. Your adversarial effort
goes to the mechanics: a wrong volume, page or year; a quote that is not verbatim; a parenthetical
or bracket that changes the words.`,
    2: `YOUR ROUTE (voter #2 — the passage first): this is a secondary source, so the case tools do not
apply. Open it and read the quoted passage IN CONTEXT — the paragraph before and after it — before
running any check. Your adversarial effort goes to substance: is the author asserting this, or
reporting another's view, or describing a position in order to reject it; does the passage support
the proposition AS STATED at the pincite, or only a narrower claim. Then run the deterministic
quote check.`,
    3: `YOUR ROUTE (voter #3 — the strongest adverse reading first): this is a secondary source, so the
case tools do not apply. Start from what would make this citation wrong and look for it — a later
edition or version that changed the passage, a published reply, correction or retraction, the
author qualifying the claim elsewhere in the same piece, the passage being a description of an
opponent's view, a claim narrower than the proposition. Then confirm existence, the cite and the
quote.`,
  },
}
const UNKNOWN_PREFACE = `SOURCE TYPE UNKNOWN: the citation does not show whether this is a judicial opinion. Establish
that first from the citation and the source itself. If it is an opinion, the route below applies as
written, case tools included. If it is a statute, regulation or constitutional provision, apply the
same route to the OFFICIAL text at the cited section in the version in force, and skip the case
tools. If it is an article, book or other secondary source, apply the same route to the catalog
record and the text, and skip the case tools.
`
const refuteRoute = (k, type) => {
  const routes = REFUTE_ROUTES_BY_TYPE[type] || REFUTE_ROUTES_BY_TYPE.case
  return (type === 'unknown' ? UNKNOWN_PREFACE : '') + (routes[k] || '')
}
const refutePrompt = (c, k) => `You are independent cite-checker #${k} of 3. Your job is to try to
REFUTE a load-bearing authority in a legal memo. Check adversarially:
(1) does this authority actually exist; (2) is the citation (reporter, volume, page, year, court)
accurate; (3) OPEN the source — does the quote appear VERBATIM, and does it support the stated
proposition at the given pincite; (4) for cases: overruled, abrogated, or superseded; for a
statute, regulation or rule: amended, repealed, renumbered, held invalid or preempted; for a
secondary source: a later edition, reply, correction or retraction that changes the passage?
${refuteRoute(k, authorityType(c))}
You do not see the other voters and they do not see you: vote on what you found, not on what a
cautious checker usually concludes.
For (3), settle verbatim-ness DETERMINISTICALLY, not by eye: save the source text to a file and
run the quote verifier —
  python3 "${FETCH_PAGE}" "<url>" --out ${refuteFile(c, k)}
  python3 "${VERIFY_QUOTES}" ${refuteFile(c, k)} "<the quote>"
(text obtained any other way — Zotero fulltext, a saved page — goes into that same scratch file).
Use EXACTLY that path — other voters and cite-checkers are running concurrently in the same /tmp,
and a shared filename would let you verify the quote against someone else's source.
Its status is the verbatim-ness answer: verbatim/normalized -> the quote is good;
altered -> check the marked alterations are honest; not_found -> read the word_diff — draft_only/
source_only/changed words are substantive (grounds to refute), "cosmetic" entries on an OCR'd
scan are scan noise, not a refutation. It also reports the printed page of the match — use that
for the pincite instead of eyeballing page markers. Your own judgment goes to SUBSTANCE: does the
passage actually support the proposition.
If you cannot confirm a claimed quote or pincite, or you are genuinely uncertain the authority is
real, set refuted=true and say why. A wrong-but-fixable citation is NOT a refutation — set
refuted=false and give correctedCitation.
CASE TOOLS (cases only; run them at the point YOUR ROUTE puts them, not before): existence and
the reporter cite settle deterministically via the Bash tool (load with ToolSearch "select:Bash"
if needed): python3 "${CHECK_CITE}" "<cite>"; treatment is checked systematically with: python3 "${CL_TOOLS}" citing "<cite>" --limit 15 (read
treatment_probe.most_relevant and name_search_treatment_probe, mentions_target=true rows first; a
signal about THIS case → currentTreatment with the treating case named; rows about other cases
are noise; distinct_cases_returned, not row counts, is the number of citing cases). A cite that
will not resolve is a search problem (python3 "${CL_TOOLS}" find "<name>" --cite "<cite>"), not a
refutation. For a LOWER-COURT case cited for current law, also run python3 "${CL_TOOLS}" history
"<cite>" and report in currentTreatment any reversal, vacatur or cert. disposition the docket or a
later same-litigation opinion shows. Opinions that postdate your training data are real. For a
STATUTE, REGULATION, RULE or CONSTITUTION, none of these tools apply: existence and text are the
official code or register (uscode.house.gov, govinfo, eCFR, the state legislature's site; LII as a
reproduction) at the version in force on the relevant date. For an ARTICLE or BOOK, none apply
either: existence is the catalog record (Zotero, the journal's site, a repository, WorldCat), and
the quote is settled by the verifier above.
ACCESS DISCIPLINE: at most 3 access attempts, via WebSearch/WebFetch only — never browser
automation, library proxies, or SSO/login flows. "I could not open the source" is NOT a refutation
by itself: if the source is paywalled, judge on what you could reach and say so in your reasoning.
BASIS (required): report the strongest source access you ACTUALLY achieved — "direct-full-text"
only if you read the passage in the full source; "authoritative-reproduction" if you read it in
CourtListener/LII/Justia or a comparable reproduction; "secondary-corroboration" if you confirmed
it only through secondary material; "citation-only" if you confirmed no more than that the cite
exists (e.g. the CourtListener API hit). Being INSTRUCTED to open the source does not make your
basis full-text — a paywall or bot wall means you report the level you reached.

MEMO QUESTION: ${QUESTION}
RESEARCH AS OF: ${AS_OF}${plan.historical ? `${NOTES ? `
QUESTION NOTES: ${NOTES}` : ''}
HISTORICAL QUESTION: the memo asks how the law stood at an earlier time, so the version that matters
is the one in force on the date the proposition concerns (read the proposition, the memo question
and its notes above for that date), not today's. An amendment, repeal, overruling or later treatment AFTER
that date is reported in currentTreatment as a disclosure — it is a refutation only if the memo
presents the earlier text or holding as current law.` : ''}
AUTHORITY: ${c.citation}
URL: ${c.url || '(locate it yourself)'}
Proposition: ${c.proposition || ''}
Quote: ${c.quote || '(none)'} ${c.pincite ? '@ ' + c.pincite : ''}
${SOURCES}`

const refuteVoter = (c, k) => agent(refutePrompt(c, k), {
  label: `refute:${(c.citation || '').slice(0, 40)}#${k}`,
  phase: 'Verify',
  schema: REFUTE_SCHEMA,
  model: VERIFY_MODEL,
  effort: 'medium',
})
// Strongest evidence level any RETURNED vote actually reported. Never assumed: a panel whose
// voters all hit a paywall reports citation-only even though each was told to open the source.
const strongestBasis = (vs) => {
  let best
  for (const v of vs) {
    const i = BASIS_LEVELS.indexOf(v.basis)
    if (i >= 0 && (best == null || i < best)) best = i
  }
  return best == null ? undefined : BASIS_LEVELS[best]
}
// Authorities whose refutation panel came back short (CLAUDE-01): {gi, citation, votes}.
const refuteGaps = []
// Authorities the panel verified over a minority refutation: {gi, citation, objections[]}.
const panelObjections = []
// Authorities where a minority of voters proposed a citation correction: {gi, citation, disputed[]}.
const panelDisputes = []
// Authorities whose voters reported different current treatment: {gi, citation}.
const panelTreatmentSplits = []
const REFUTE_ROUTE_NAMES = { 1: 'record', 2: 'passage in context', 3: 'adverse reading' }
const refuteJob = (c) => () =>
  parallel(
    [1, 2, 3].map((k) => async () => {
      // A dead voter is NOT a non-refuting vote: retry once, then count only what came back.
      let v = await refuteVoter(c, k)
      if (!v) { log(`refute:${(c.citation || '').slice(0, 40)}#${k} died — retrying once`); v = await refuteVoter(c, k) }
      return v
    })
  ).then((votes) => {
    // Keep each vote's seat (k) so a reason can be attributed to its route. Every reason is kept:
    // the old slice(0, 2) silently dropped the third voter's, and after the routes were
    // differentiated that was the adverse-reading voter's (Codex review, 2026-11-03).
    const vs = votes.map((v, i) => (v ? { ...v, k: i + 1 } : null)).filter(Boolean)
    const refutes = vs.filter((v) => v.refuted).length
    // Majority of the votes that actually came back: 3 votes → 2 refutes kill; 2 votes → 1;
    // 1 vote → that vote decides and is flagged single-voter. A short panel never verifies more
    // easily than a full one.
    const killAt = Math.ceil(vs.length / 2)
    // CORRECTIONS (2026-11-15 review). The first voter to offer a correctedCitation used to win:
    // one voter's proposal (on a citation-only basis, in the test) replaced a citation the other
    // two had found accurate, and Finalize was told to apply it. A correction is adopted only
    // when a majority of the returned voters propose the same one; otherwise it is carried as a
    // disputed proposal for Finalize to disclose, and the citation stands.
    const proposals = new Map()
    for (const v of vs) {
      const cc = (v.correctedCitation || '').trim()
      if (!cc || norm(cc) === norm(c.citation)) continue
      const key = norm(cc)
      if (!proposals.has(key)) proposals.set(key, { text: cc, voters: [] })
      proposals.get(key).voters.push(v.k)
    }
    const adopted = [...proposals.values()].find((p) => p.voters.length > vs.length / 2) // a strict majority: 2 of 3, 2 of 2, 1 of 1
    const corrected = adopted ? adopted.text : undefined
    const disputed = [...proposals.values()].filter((p) => p !== adopted)
      .map((p) => `PROPOSED CORRECTION NOT ADOPTED (voter${p.voters.length === 1 ? '' : 's'} #${p.voters.join(', #')} of ${vs.length}): ${p.text}`)
    // TREATMENT (2026-11-15 review). The first non-empty currentTreatment used to win, so voter
    // #1's "no negative treatment found" hid voter #3's "overruled by ..." (the voter whose route
    // leads with adverse treatment). Every distinct report is kept, attributed to its voter.
    const treatments = []
    for (const v of vs) {
      const t = (v.currentTreatment || '').trim()
      if (t && !treatments.some((x) => norm(x.t) === norm(t))) treatments.push({ k: v.k, t })
    }
    const treatment = treatments.length <= 1
      ? treatments[0]?.t
      : `VOTERS REPORT DIFFERENT TREATMENT — ${treatments.map((x) => `voter #${x.k} (${REFUTE_ROUTE_NAMES[x.k] || 'route'}): ${x.t}`).join(' || ')}`
    const basis = strongestBasis(vs)
    const reasons = vs
      .filter((v) => v.reason)
      .map((v) => `#${v.k} ${REFUTE_ROUTE_NAMES[v.k] || ''}${v.refuted ? ' REFUTES' : ''}: ${v.reason}`)
      .join(' | ')
    if (vs.length < 3) refuteGaps.push({ gi: c.gi, citation: c.citation, votes: vs.length })
    if (!vs.length) {
      // Nothing was checked. "Verified" here would be the absence of evidence dressed as evidence.
      return [{
        index: c.gi,
        citation: c.citation,
        verdict: 'unverified',
        notes: 'NOT CHECKED — all 3 refutation voters failed (after one retry each); no evidence either way',
      }]
    }
    const verdict = refutes >= killAt ? 'unverified' : corrected ? 'needs-correction' : 'verified'
    const panelNote = vs.length < 3 ? `${vs.length === 1 ? 'SINGLE-VOTER' : 'SHORT PANEL'} — ${3 - vs.length} of 3 refutation voters returned nothing` : ''
    // A refutation the majority outvoted is not resolved by the majority: it is carried to
    // Finalize as an objection (with its evidence) and disclosed, and the authority's tier label
    // says so. Finalize qualifies the memo's use of the authority or lists it in Limits.
    const objections = refutes && refutes < killAt
      ? vs.filter((v) => v.refuted).map((v) => `MINORITY OBJECTION (voter #${v.k}, ${REFUTE_ROUTE_NAMES[v.k] || 'route'}): ${v.reason || '(no reason given)'}`)
      : []
    if (objections.length) panelObjections.push({ gi: c.gi, citation: c.citation, objections })
    if (disputed.length) panelDisputes.push({ gi: c.gi, citation: c.citation, disputed })
    if (treatments.length > 1) panelTreatmentSplits.push({ gi: c.gi, citation: c.citation })
    return [{
      index: c.gi,
      citation: c.citation,
      verdict,
      basis, // what the voters reported; undefined if none reported one
      correctedCitation: corrected,
      currentTreatment: treatment,
      objections,
      notes: [...objections, ...disputed, panelNote, basis ? '' : 'basis not reported by any voter', reasons || `${refutes}/${vs.length} refute votes`].filter(Boolean).join(' | '),
    }]
  })

// Budget check: if a full cite-check won't fit, verify only the load-bearing and gap-fill
// authorities; the rest are marked "unchecked" (kept in the memo, flagged, never removed).
const PER_CHECK = DEEP ? 9_000 : 2_500
let verifyList = toVerify
let skippedSet = new Set()
if (toVerify.length && tight(RESERVE_FINALIZE + toVerify.length * PER_CHECK)) {
  verifyList = toVerify.filter((c) => c.loadBearing || c.gapFill)
  skippedSet = new Set(toVerify.filter((c) => !(c.loadBearing || c.gapFill)).map((c) => c.gi))
  degradation.push(`${skippedSet.size} citations left unchecked (budget)`)
  log(`Budget tight — cite-checking only ${verifyList.length} load-bearing/gap-fill authorities; ${skippedSet.size} left unchecked.`)
}

// Which authorities got the 3-voter adversarial panel (deep mode): the memo must label each
// authority's validation tier, since a screened case and a panel-verified case look identical
// on the page (2026-10-19).
const panelSet = new Set()
let verdicts = []
if (verifyList.length) {
  const jobs = []
  const chunkable = []
  // Deep refutes cost 3 medium-effort agents EACH, and the draft decides how many cites are
  // load-bearing — cap the refute set so a generous draft can't fan out unboundedly.
  const loadBearing = DEEP ? verifyList.filter((c) => c.loadBearing) : []
  const refuteSet = new Set(loadBearing.slice(0, REFUTE_CAP).map((c) => c.gi))
  for (const gi of refuteSet) panelSet.add(gi)
  if (loadBearing.length > REFUTE_CAP)
    log(`Deep refutation capped at ${REFUTE_CAP} of ${loadBearing.length} load-bearing authorities; the rest get the standard chunk check.`)
  for (const c of verifyList) {
    if (refuteSet.has(c.gi)) jobs.push(refuteJob(c))
    else chunkable.push(c)
  }
  for (let i = 0; i < chunkable.length; i += VERIFY_CHUNK) jobs.push(chunkJob(chunkable.slice(i, i + VERIFY_CHUNK)))
  const outs = await parallel(jobs)
  verdicts = outs.filter(Boolean).flat()
}

// Join verdicts to authorities by echoed index; fall back to citation match, NEVER to position —
// a positional fallback can stamp "verified" on the wrong authority.
const vmap = new Map()
for (const v of verdicts) if (Number.isInteger(v.index) && !vmap.has(v.index)) vmap.set(v.index, v)
// Authorities no checker returned anything for (dead chunk agent after retry, or an agent that
// skipped an index). They are "unverified" in the memo and disclosed as NOT CHECKED — distinct
// from an authority a checker examined and could not confirm.
const noVerdict = []
const vFor = (c) => {
  if (skippedSet.has(c.gi)) return { verdict: 'unchecked', notes: 'cite-check skipped — token budget' }
  let v = vmap.get(c.gi) || verdicts.find((v) => v.citation && norm(v.citation) === norm(c.citation))
  if (!v) {
    noVerdict.push({ gi: c.gi, citation: c.citation })
    v = { verdict: 'unverified', notes: 'NOT CHECKED — no verdict returned (cite-check agent failed after one retry, or skipped this index)' }
  }
  // A source the run read, which the checker says it did not examine at all: "unverified" would
  // record a failed check that never happened. On the first live run (2026-11-16) a gap-fill agent
  // read a concurrence in the official slip opinion, the checker skipped it and returned
  // "unverified", and the memo called the opinion unread. It is treated like every other source
  // the run read and the checker did not re-open: verified on the strength of the run's own read,
  // and the note says the checker ran nothing.
  if (c.wasRead && v.verdict === 'unverified' && v.examined === false) {
    v = {
      ...v,
      verdict: 'verified',
      basis: undefined,
      notes: [v.notes, 'the cite-checker reported running no check of its own on this authority'].filter(Boolean).join(' — '),
    }
  }
  // A source a research agent opened and quoted this run was read, so the cite-checker (told to
  // skip existence re-checks for it) may have reported a weaker basis than the run achieved.
  // It used to be stamped "direct-full-text" outright. But readers are told to prefer
  // CourtListener / LII HTML, which this vocabulary calls a reproduction, and the checker did not
  // re-open the source: the floor is "authoritative-reproduction", a checker's own stronger
  // report stands, and the note says whose read the basis rests on (2026-11-15 review).
  if (c.wasRead && v.verdict === 'verified') {
    const lvl = BASIS_LEVELS.indexOf(v.basis)
    const floor = BASIS_LEVELS.indexOf('authoritative-reproduction')
    v = {
      ...v,
      basis: lvl >= 0 && lvl <= floor ? v.basis : 'authoritative-reproduction',
      notes: [v.notes, "basis rests on this run's research read of the source; the cite-checker did not re-open it"].filter(Boolean).join(' — '),
    }
  }
  return v
}
const checkKind = (c, v) => {
  if (v.verdict === 'unchecked') return 'not validated (budget)'
  if (/NOT CHECKED/.test(v.notes || '')) return 'not validated (checker failure)'
  // The label follows the verdict (2026-11-15 review): an authority the panel REFUTED used to be
  // labelled "verified (3-voter refutation panel)" beside an "unverified" verdict.
  if (panelSet.has(c.gi)) {
    const short = /SHORT PANEL|SINGLE-VOTER/.test(v.notes || '')
    const obj = (v.objections || []).length
    const panel = `${short ? 'short' : '3-voter'} refutation panel`
    if (v.verdict === 'unverified') return `refuted (${panel})`
    return `${v.verdict === 'needs-correction' ? 'corrected' : 'verified'} (${panel}${obj ? `, ${obj} objection${obj === 1 ? '' : 's'} unresolved` : ''})`
  }
  if (v.verdict === 'unverified') return c.wasRead ? 'checked — could not be confirmed (a research agent read the source this run)' : 'checked — could not be confirmed'
  // The citing-opinion probe resolves judicial opinions only; a statute or an article got the
  // existence and citation check and nothing else.
  const t = authorityType(c)
  return t === 'statute' || t === 'secondary' ? 'checked (existence + citation; no treatment probe for this source type)' : 'checked (existence + citing-opinion treatment probe)'
}
const tagged = toVerify.map((c) => { const v = vFor(c); return { ...c, v, check: checkKind(c, v) } })
const okCount = tagged.filter((t) => t.v.verdict === 'verified').length
const fixCount = tagged.filter((t) => t.v.verdict === 'needs-correction').length
const badCount = tagged.filter((t) => t.v.verdict === 'unverified').length
const skipCount = tagged.filter((t) => t.v.verdict === 'unchecked').length
// Coverage gaps from dead checkers (CLAUDE-01): disclosed, counted, and they keep the run from
// ending "complete" — a cite nobody checked is not a verified cite.
const refuteNoVotes = refuteGaps.filter((g) => g.votes === 0)
const refuteShort = refuteGaps.filter((g) => g.votes > 0)
if (refuteNoVotes.length) coverageGaps.push(`${refuteNoVotes.length} load-bearing authorit${refuteNoVotes.length === 1 ? 'y' : 'ies'} got NO refutation votes (all 3 voters failed after one retry each) — marked unverified / NOT CHECKED`)
if (refuteShort.length) coverageGaps.push(`${refuteShort.length} load-bearing authorit${refuteShort.length === 1 ? 'y' : 'ies'} decided on a short refutation panel (1–2 of 3 voters returned) — flagged in the cite-check results`)
if (panelDisputes.length) coverageGaps.push(`${panelDisputes.length} load-bearing authorit${panelDisputes.length === 1 ? 'y has' : 'ies have'} a citation correction proposed by a minority of the panel — not applied; listed in Limits for the author to confirm`)
if (panelTreatmentSplits.length) coverageGaps.push(`${panelTreatmentSplits.length} load-bearing authorit${panelTreatmentSplits.length === 1 ? 'y' : 'ies'} drew different treatment reports from the panel's voters — every report is carried into the memo`)
if (panelObjections.length) coverageGaps.push(`${panelObjections.length} load-bearing authorit${panelObjections.length === 1 ? 'y' : 'ies'} verified over a minority refutation — the objection is carried into the memo's text or its Limits section, not resolved by the majority`)
if (noVerdict.length) coverageGaps.push(`${noVerdict.length} cited authorit${noVerdict.length === 1 ? 'y' : 'ies'} got no cite-check verdict at all (agent failure after one retry, or skipped index) — marked unverified / NOT CHECKED`)
const checkGapReport = [
  ...refuteNoVotes.map((g) => `- ${g.citation} — no refutation votes returned (0/3 voters)`),
  ...refuteShort.map((g) => `- ${g.citation} — short refutation panel (${g.votes}/3 voters returned)`),
  ...noVerdict.map((g) => `- ${g.citation} — no cite-check verdict returned`),
].join('\n')
log(`Authorities checked: ${okCount} verified, ${fixCount} need correction, ${badCount} unverified${skipCount ? `, ${skipCount} unchecked (budget)` : ''}${refuteGaps.length || noVerdict.length ? `; ${refuteNoVotes.length + noVerdict.length} NOT CHECKED (dead checkers), ${refuteShort.length} on a short panel` : ''}.`)

// ---- Phase 6: finalize -----------------------------------------------------
phase('Finalize')
// How a post-draft addition is woven in; shared by the call-in and the Finalize pass. Written
// after the first live run (2026-11-16): told only to make the lightest change, the call-in added
// two gap-fill opinions beside tables, counts and a title that still described the original set,
// and cited them inline in a footnoted memo.
const GAP_WEAVE = `Weave each one into the memo where the draft noted the gap, with its cite, subject to its
  cite-check verdict, and remove the corresponding gap note. A research agent opened and read each
  one this run, so it is part of what the memo read: never describe one as unread, as a candidate,
  or as something the memo only heard about. Carry it all the way through, so that the memo reads
  as if the authority had been in it from the start:
  * TABLES: where the memo has a table listing or classifying the authorities it read, add a row.
  * COUNTS: where the memo counts or tallies its sources (the title, a scope note, the Brief
    Answer or short answers, a table, the Assessment, the Conclusion), update every count, so
    that each number means one thing throughout. Never leave an old count standing beside a note
    that the addition is outside it.
  * CITATION STYLE: cite it the way the memo cites its other authorities. In a memo that uses
    footnotes, give it a footnote: a new marker with the next unused number, and its definition
    added directly after the memo's last existing footnote definition. No inline citation there.
  * NOT CONFIRMED: an addition whose cite-check verdict is "unverified" is still woven in as a
    source this run read, with a plain statement of what the cite-check did and did not confirm
    in place of the generic "reportedly" caveat. No conclusion may rest on it alone.`
const verifyReport = tagged
  .map(
    (t) =>
      `- [${t.v.verdict}${t.v.basis ? ` | ${t.v.basis}` : ''} | tier: ${t.check}] ${t.citation}${t.v.correctedCitation ? ` -> ${t.v.correctedCitation}` : ''}${
        t.v.currentTreatment ? ` (${t.v.currentTreatment})` : ''
      }${t.v.notes ? ` — ${t.v.notes}` : ''}`
  )
  .join('\n')

const gapReport = tagged
  .filter((t) => t.gapFill)
  .map(
    (t) =>
      `- ${t.citation} [read this run by a research agent | cite-check: ${t.v.verdict}]\n  Proposition: ${t.proposition || ''}\n  Quote: ${t.quote || '(none)'} ${t.pincite ? '@ ' + t.pincite : ''}\n  URL: ${t.url || ''}`
  )
  .join('\n')

const researchGapReport = [
  ...deadSurveys.map((j) => `- ${j.what} did not run (the search agent failed twice)`),
  ...deadReads.map((c) => `- ${c.citation || c.url} — selected for a full read, never read (the reading agent failed twice); it appears in the findings only as an unread lead`),
].join('\n')

// The memo from here on is the draft plus applied edits; no agent retypes it (see applyEdits).
let memo = draft.memoDraft || ''
let editsApplied = 0
const unapplied = calibrationUnapplied.map((f) => ({ ...f, pass: 'calibration' }))

// Which cite-check results change what the memo can CLAIM, as opposed to how it cites? Decided
// here from the verdicts, not by a model: a load-bearing authority that failed verification (or
// that no checker examined), negative treatment of a load-bearing authority, an authority the
// panel verified over a minority objection, and every gap-fill authority to be woven in. That
// includes a gap-fill authority the cite-check could not confirm: left to the clerical pass, the
// first live run's memo described one as an unread candidate although the run had read it.
const substantiveByGi = new Map()
const addSubstantive = (t, reason) => {
  const e = substantiveByGi.get(t.gi) || { t, reasons: [] }
  if (!e.reasons.includes(reason)) e.reasons.push(reason)
  substantiveByGi.set(t.gi, e)
}
for (const t of tagged) {
  if (t.gapFill) {
    addSubstantive(t, t.v.verdict === 'unverified' ? 'POST-DRAFT ADDITION that the cite-check did NOT confirm' : 'POST-DRAFT ADDITION to weave in')
    continue
  }
  if (!t.loadBearing) continue
  if (t.v.verdict === 'unverified') addSubstantive(t, /NOT CHECKED/.test(t.v.notes || '') ? 'load-bearing authority that NO CHECKER EXAMINED' : 'load-bearing authority that FAILED VERIFICATION')
  else if (hasNegativeTreatment(t.v.currentTreatment)) addSubstantive(t, 'NEGATIVE TREATMENT of a load-bearing authority')
}
for (const p of panelObjections) {
  const t = tagged.find((x) => x.gi === p.gi)
  if (t) addSubstantive(t, 'VERIFIED OVER A MINORITY OBJECTION')
}
const substantive = [...substantiveByGi.values()]

// The call-in: with Finalize on a cheaper model, those items go to ONE call on the session model
// first (no model override), which returns edits like every other pass. If it is switched off,
// squeezed out by the budget, or dies twice, the Finalize pass applies the items itself, as it
// always did, and the result says so.
let callIn = !FINALIZE_MODEL ? 'not applicable (Finalize ran on the session model)'
  : !substantive.length ? 'not needed'
    : !ESCALATE ? 'off (args.escalate:false)'
      : tight(RESERVE_FINALIZE) ? 'skipped (budget)' : 'wanted'
let handled = []
if (callIn === 'wanted') {
  log(`Cite-check results change what the memo can claim for ${substantive.length} authorit${substantive.length === 1 ? 'y' : 'ies'} — calling in the session model for those before the ${FINALIZE_MODEL} Finalize pass.`)
  const itemBlock = ({ t, reasons }) =>
    `- ${t.citation}\n  Why it is here: ${reasons.join('; ')}\n  Cite-check: [${t.v.verdict}${t.v.basis ? ` | ${t.v.basis}` : ''} | tier: ${t.check}]${t.v.correctedCitation ? ` -> ${t.v.correctedCitation}` : ''}${t.v.currentTreatment ? ` (${t.v.currentTreatment})` : ''}${t.v.notes ? ` — ${t.v.notes}` : ''}${
      t.gapFill ? `\n  Read this run: a research agent opened this source and reported what follows.\n  Proposition: ${t.proposition || ''}\n  Quote: ${t.quote || '(none)'} ${t.pincite ? '@ ' + t.pincite : ''}\n  URL: ${t.url || ''}` : ''}`
  const revise = await retryOnce('finalize:revise', () => agent(
    `You are revising a legal research memo after its citations were checked. A separate clerical pass
runs after you: it corrects citation forms, tags unchecked authorities, runs the quantifier and
consistency scans, and writes the Table of Authorities and the Limits section. Leave all of that
to it. Your job is ONLY the authorities listed under ITEMS, because each one changes what the memo
can claim. Make the LIGHTEST change that leaves the memo saying no more than its checked
authorities support. Do not rewrite, restyle, or compress anything else. The one exception is a
POST-DRAFT ADDITION, which is carried all the way through the memo as described under it.

What each kind of item calls for:
- A load-bearing authority that FAILED VERIFICATION, or that NO CHECKER EXAMINED: the analysis
  rests on it. Remove the memo's reliance on it, or downgrade it to an explicit caveat
  ("reportedly / could not be independently confirmed"; for one nobody examined, say that it was
  not independently checked), and narrow any conclusion that depended on it to what the remaining
  authorities support. Never present it as settled law.
- NEGATIVE TREATMENT of a load-bearing authority: reflect it in the text where the memo relies on
  the authority (e.g. "overruled by…") and narrow the reliance to what survives. A treatment that
  begins "VOTERS REPORT DIFFERENT TREATMENT" lists what each checker found: if ANY of them reports
  negative treatment, reflect that one and say that the checkers differed. One checker's "no
  negative treatment found" does not cancel another's overruling.
- VERIFIED OVER A MINORITY OBJECTION (quoted in the item as "MINORITY OBJECTION"): a majority does
  not resolve an objection. Where it names a narrower holding, an omitted limiting fact, a
  mischaracterized posture (dictum, dissent, arguendo) or a narrower claim than the proposition,
  qualify the memo's use of that authority in the sentence that cites it. Never present such an
  authority as settled support.
- POST-DRAFT ADDITION (one to weave in, or one the cite-check did NOT confirm): an authority
  retrieved after drafting to fill a gap the draft itself flagged.
  ${GAP_WEAVE}
- FOLLOW-THROUGH: if a change above leaves the title, the Brief Answer, the Introduction or the
  Conclusion saying more or less than the Discussion now supports, edit those lines too.

${EDIT_RULES}
${substantive.some((s) => s.t.gapFill) ? BLUEBOOK : ''}

QUESTION: ${QUESTION}

=== ITEMS ===
${substantive.map(itemBlock).join('\n')}

=== MEMO ===
${memo || '(empty draft)'}`,
    { schema: EDITS_SCHEMA, label: 'finalize:revise', phase: 'Finalize', effort: 'medium' }
  ))
  if (revise && Array.isArray(revise.edits)) {
    const r = await applyWithRepair(memo, revise.edits, 'revision call-in', 'Finalize')
    if (r.rejected) {
      callIn = 'failed (its edits were discarded)'
    } else {
      memo = r.text
      editsApplied += r.applied
      unapplied.push(...r.failed.map((f) => ({ ...f, pass: 'revision call-in' })))
      handled = substantive
      callIn = 'ran'
      log(`Revision call-in: ${r.applied} edit${r.applied === 1 ? '' : 's'} applied${r.failed.length ? `, ${r.failed.length} could not be located` : ''}.`)
    }
  } else {
    callIn = 'failed (the agent died twice)'
  }
  if (callIn !== 'ran') log(`Revision call-in ${callIn} — the ${FINALIZE_MODEL} Finalize pass applies those items itself.`)
}
const gapHandled = handled.some((h) => h.t.gapFill)

const finalizePrompt = `You are finalizing a legal research memo. Apply the cite-check results to the draft with the
LIGHTEST touch needed. Do not rewrite, restyle, or compress.

${EDIT_RULES}

Make these changes:
- Replace any "needs-correction" citation with its corrected form.
- Where a currentTreatment notes negative treatment, reflect it in the text (e.g. "overruled by…").
  A treatment that begins "VOTERS REPORT DIFFERENT TREATMENT" lists what each checker found: if
  ANY of them reports negative treatment, reflect that one in the text, say that the checkers
  differed, and name the authority in Limits as needing a citator check. One checker's "no
  negative treatment found" does not cancel another's overruling.
- A note reading "PROPOSED CORRECTION NOT ADOPTED" is one checker's proposed citation that the
  other checkers did not share. Do NOT apply it. Keep the citation as written and list it in
  Limits under "Citation corrections proposed but not confirmed", with the proposal quoted.
- For any "unverified" authority: either remove the sentence's reliance on it or downgrade it to an
  explicit caveat ("reportedly / could not be independently confirmed"). Never present an unverified
  authority as settled law.
- QUANTIFIER AUDIT (one scan, edit in place): find any "first / only / never / always / settled /
  overwhelmingly / dominant / rare / erased / dead" or equivalent frequency/priority/finality claim
  that the memo's own disclosed research design cannot support, and downgrade it to sample-scoped
  language ("in the leading cases reviewed", "the earliest clean statement found in this
  research"). Cite-checks confirm sources; they do not license generalizations.
- CONSISTENCY AUDIT (one scan, edit in place — read the memo as a whole, not section by section):
  the Brief Answer or Introduction, the Discussion, the Conclusion and the Limits section must tell
  one story. Fix the summary sections to match the Discussion and the cite-check results, never the
  reverse: a confidence stated up top that the weakest load-bearing authority's verification basis
  or the Limits section cannot support; a bottom line stated as settled while the Discussion names
  contrary or limiting authority it does not resolve; a qualification the Discussion adds that the
  Conclusion drops; an absolute ("no court has", "uniformly") that a later section undercuts; a
  date, count or number that differs between sections.
${skipCount ? `- Authorities marked "unchecked" were NOT cite-checked (the token budget ran out) —
  this is different from unverified. KEEP them as cited, but tag each one's first citation with
  "[not independently cite-checked]" and list them separately in the Limits section.` : ''}
${checkGapReport ? `- CITE-CHECK COVERAGE GAPS: the checking agents for the authorities below FAILED (not
  "could not confirm" — nothing was checked). Those marked "no ... returned" carry an
  "unverified" verdict above because no evidence came back; treat them like unverified in the
  text, but in the Limits section list them under their own heading, "Not independently
  checked (checker failure)", distinct from authorities a checker examined and rejected. A
  "short refutation panel" authority was decided by fewer than 3 adversarial voters — keep it as
  cited, but name it in the Limits section as single- or two-checker verified.
${checkGapReport}` : ''}
${panelObjections.length ? `- MINORITY OBJECTIONS: the authorities below were verified by their refutation panel over
  one voter's evidenced objection (quoted in their cite-check results as "MINORITY OBJECTION").
  A majority does not resolve an objection. Where it names a narrower holding, an omitted
  limiting fact, a mischaracterized posture (dictum, dissent, arguendo) or a narrower claim than
  the proposition, qualify the memo's use of that authority in the sentence that cites it. Where
  the memo's own record cannot resolve it, keep the cite, state the qualification, and list the
  authority under its own heading in Limits, "Verified over an objection", with the objection
  quoted. Never present such an authority as settled support.
${panelObjections.map((p) => `  - ${p.citation}: ${p.objections.join(' | ')}`).join('\n')}` : ''}
${researchGapReport ? `- RESEARCH COVERAGE GAPS: the parts of the research below did NOT run or did not return (agent
  failures, not judgments about the sources). State each in the Limits section in plain words. If
  a search vector did not run, do not let the memo make an absence claim ("no court has", "the
  literature does not address") that depends on what that vector would have searched.
${researchGapReport}` : ''}
${gapReport && !gapHandled ? `- POST-DRAFT ADDITIONS: the authorities below were retrieved after drafting to fill
  gaps the draft itself flagged.
  ${GAP_WEAVE}` : ''}
${handled.length ? `- ALREADY REVISED: an earlier pass has changed the memo's text for the authorities below (a
  failed verification, negative treatment, a minority objection, or a post-draft addition woven
  in). For these authorities this overrides the text instructions above: do NOT edit the memo's
  reliance on them again. Correct a citation's form if the results call for it, and report them
  in the Table of Authorities and the Limits section exactly as their verdicts require.
${handled.map((h) => `  - ${h.t.citation} (${h.reasons.join('; ')})`).join('\n')}` : ''}
- Append two sections. Return each one complete, heading included, in its own field
  (tableOfAuthorities, limits), NOT as edits: the script places them after the memo's last line.
  * **Table of Authorities** (only verified/corrected authorities, grouped by type), with a
    **Validation** column copied from each authority's "tier:" label in the cite-check results:
    "verified (3-voter refutation panel)" / "verified (short refutation panel)" / "corrected
    (... refutation panel)" / "checked (existence + citing-opinion treatment probe)" / "checked
    (existence + citation; no treatment probe for this source type)" / "not validated (...)". An
    authority labelled "refuted (...)" or "checked — could not be confirmed" is unverified and
    does not belong in the table. A checked case and a
    panel-verified case look identical in prose, so the label is the only place the reader can
    tell them apart. Under the table, ONE sentence naming which authorities got the refutation
    panel and why (load-bearing), and which were only checked; if NO authority got the panel
    (lean mode), say so in as many words — never let an unlabeled table read as "all verified".
  * **Limits of this research** — what could not be verified, gaps, that ONLY free/open-web sources
    were used, and that a Westlaw/Lexis pass plus a manual Bluebook check is recommended before
    publication or filing. Disclose the VERIFICATION BASIS mix using the labels in the cite-check
    results (direct-full-text / authoritative-reproduction / secondary-corroboration /
    citation-only): say how many authorities sit at each level and name any LOAD-BEARING authority
    verified only at "secondary-corroboration" or "citation-only". A global claim like "all
    authorities verified" must match the WEAKEST material authority — if the levels are mixed,
    say they are mixed.
${BLUEBOOK}

=== CITE-CHECK RESULTS ===
${verifyReport || '(none)'}
${gapReport ? `\n=== POST-DRAFT ADDITIONS ===\n${gapReport}\n` : ''}
=== DRAFT MEMO ===
${memo || '(empty draft)'}

Return the edits, the Table of Authorities section and the Limits section.`
// A result with no Limits section is treated as a dead agent: the section is not optional.
const final = await must('Finalize', async () => {
  const r = await agent(finalizePrompt, withFinalizeModel({ schema: FINAL_SCHEMA, phase: 'Finalize', effort: 'medium' }))
  return r && String(r.limits || '').trim() ? r : null
})
const finalPass = await applyWithRepair(memo, final.edits, 'finalize', 'Finalize')
memo = finalPass.text
editsApplied += finalPass.applied
unapplied.push(...finalPass.failed.map((f) => ({ ...f, pass: 'finalize' })))
log(`Finalize: ${finalPass.applied} edit${finalPass.applied === 1 ? '' : 's'} applied${finalPass.failed.length ? `, ${finalPass.failed.length} could not be located` : ''}.`)
if (finalPass.rejected) coverageGaps.push('the Finalize edits were discarded (they would have cut the memo by more than 40%) — the cite-check results were NOT applied to the memo text; rely on the Table of Authorities and the Limits section, and apply the corrections by hand')
// An edit nobody could place is disclosed in the memo and returned for the skill to apply by
// hand. It is never dropped: it may be the caveat on an authority that failed verification.
const oneLine = (s, n) => { const t = String(s || '').replace(/\s+/g, ' ').trim(); return t.length > n ? t.slice(0, n) + '…' : t }
const unappliedNotice = unapplied.length
  ? `**Changes not made automatically.** ${unapplied.length} change${unapplied.length === 1 ? '' : 's'} that the checking passes called for could not be placed in the memo text and ${unapplied.length === 1 ? 'was' : 'were'} NOT made:\n${unapplied.map((u) => `- ${oneLine(u.why, 200) || 'change to the passage beginning: ' + oneLine(u.find, 80)}`).join('\n')}`
  : ''
if (unapplied.length) coverageGaps.push(`${unapplied.length} edit${unapplied.length === 1 ? '' : 's'} could not be placed in the memo text — listed at the end of its Limits section and returned in finalize.unappliedEdits to be applied by hand`)
memo = [memo.replace(/\s+$/, ''), String(final.tableOfAuthorities || '').trim(), String(final.limits || '').trim(), unappliedNotice]
  .filter(Boolean).join('\n\n') + '\n'

// Exit state (ported from the Codex deep-research-cli contract): make degradation machine-visible
// so the orchestrator's deliver step can react deterministically instead of parsing logs.
// - budget_exhausted: the budget guard cut coverage (trimmed reads, skipped gap-fill, unchecked
//   cites) — the memo is honest but the RESEARCH is incomplete; consider targeted fill passes.
// - complete_with_limits: full budget ran, but the record has documented gaps (failed fetches,
//   unverified or unrecovered authorities) — disclosed in the memo's Limits section.
// - complete: planned coverage met and every cited authority checked.
const failedOpens = readFindings.filter((f) => !f.opened).length
const unrecoveredGaps = Math.max(0, (draft.missingAuthorities || []).length - gapFindings.length)
if (failedOpens) coverageGaps.push(`${failedOpens} selected sources could not be opened`)
if (deadReads.length) coverageGaps.push(`${deadReads.length} selected source${deadReads.length === 1 ? '' : 's'} never read — the reading agent failed twice (carried as unread leads)`)
if (deadSurveys.length) coverageGaps.push(`${deadSurveys.length} survey lane${deadSurveys.length === 1 ? '' : 's'} did not run (agent failure after one retry): ${deadSurveys.map((j) => j.what).join('; ')}`)
if (unrecoveredGaps) coverageGaps.push(`${unrecoveredGaps} draft-flagged authorities never retrieved`)
// Dead-checker gaps (refuteGaps / noVerdict) are already in coverageGaps, so a run in which every
// voter died can never end "complete".
const exitState = degradation.length
  ? 'budget_exhausted'
  : (badCount || coverageGaps.length) ? 'complete_with_limits' : 'complete'
degradation.push(...coverageGaps)

return {
  question: QUESTION,
  mode: MODE,
  outputStyle: OUTPUT,
  deep: DEEP,
  skeleton: draft.skeleton || '',
  exitState,
  degradation,
  counts: {
    candidates: pool.length,
    read: openedCount,
    leads: leads.length,
    cited: cited.length,
    gapFilled: gapFindings.length,
    verified: okCount,
    corrected: fixCount,
    unverified: badCount,
    uncheckedForBudget: skipCount,
    notCheckedAgentFailure: refuteNoVotes.length + noVerdict.length, // counted inside `unverified`
    shortRefutationPanel: refuteShort.length,
    panelObjections: panelObjections.length,
    panelDisputedCorrections: panelDisputes.length,
    panelTreatmentSplits: panelTreatmentSplits.length,
    surveyLanesFailed: deadSurveys.length,
    readsFailed: deadReads.length,
    editsApplied,
    editsUnapplied: unapplied.length,
  },
  // How the memo was finalized: which model ran the Finalize pass, whether the session model was
  // called in for the changes that alter the memo's claims (and for which authorities), and any
  // edit that could not be placed — the skill applies those by hand before delivering.
  finalize: {
    model: FINALIZE_MODEL || 'session model',
    callIn,
    callInAuthorities: substantive.map((s) => ({ citation: s.t.citation, reasons: s.reasons })),
    unappliedEdits: unapplied,
  },
  memo,
}
