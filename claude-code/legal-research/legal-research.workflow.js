export const meta = {
  name: 'legal-research',
  description: 'Retrieval-pipeline legal research: broad cheap search, dedup, read-once, draft, gap-fill, verify cited authorities, finalize',
  phases: [
    { title: 'Scope', detail: 'frame issues, jurisdiction, search vectors' },
    { title: 'Survey', detail: 'broad search-only sweep (+ Zotero library); collect candidates, fetch nothing' },
    { title: 'Read', detail: 'dedup, triage, then fully read each chosen source once' },
    { title: 'Draft', detail: 'synthesize a memo from the findings' },
    { title: 'Verify', detail: 'confirm only the authorities actually cited' },
    { title: 'Finalize', detail: 'apply corrections, flag unverified, add appendices' },
  ],
}

// ---- args (passed from the skill) -------------------------------------------
// args = { question, mode: 'caselaw'|'scholarship'|'both', outputStyle: 'academic'|'practitioner',
//          jurisdiction, asOfDate, notes, deep:boolean, projectDir:string }
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
const remainingTokens = () =>
  budget.total ? budget.remaining() : Math.max(0, SOFT_CAP - budget.spent())
const tight = (need) => remainingTokens() < need

// Lever 3 — model map:
// - Scope, Draft, and Finalize carry NO model override: they inherit the session model (Fable when
//   Fable is on). These are three calls total; Scope's leverage-per-token is the highest in the
//   pipeline (its vectors steer everything downstream), Draft is the analytical synthesis, and
//   Finalize re-emits the memo — an override there would launder session-model prose through a
//   cheaper model.
// - Sonnet does the accuracy-critical mid-volume work: triage (decides what gets read), the full
//   reads (a misread here becomes a confident wrong proposition in the draft, and lean verify
//   won't re-open the source to catch it), and cite-verification.
// - Haiku is confined to the one stage where a weak read can't corrupt the memo: the search-only
//   survey, whose output is candidate lists that Sonnet triage re-judges anyway.
const SCOUT_MODEL = 'haiku'   // survey: search-snippet harvesting only
const READ_MODEL = 'sonnet'   // triage, full reads, gap-fill reads
const VERIFY_MODEL = 'sonnet' // cite-checking

const SOURCES = `FREE / OPEN-WEB LEGAL SOURCES ONLY (no Westlaw/Lexis):
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

// Bundled helper scripts (run via the Bash tool). $HOME (not ~) because every use
// below lands inside shell double quotes in an agent prompt, where $HOME expands but ~ does not.
const CHECK_CITE = '$HOME/.claude/skills/legal-research/check_cite.py'
const FETCH_PAGE = '$HOME/.claude/skills/legal-research/fetch_page.py'
const CL_TOOLS = '$HOME/.claude/skills/legal-research/cl_case_tools.py'
// Deterministic quote verifier (lives in the sibling cite-check skill; both must be installed).
const VERIFY_QUOTES = '$HOME/.claude/skills/cite-check/scripts/verify_quotes.py'

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
  prior memo already corrected or qualified without addressing that qualification.`

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
          currentTreatment: { type: 'string' },
          notes: { type: 'string' },
        },
      },
    },
  },
}

// Deep mode: one adversarial vote on one load-bearing authority.
const REFUTE_SCHEMA = {
  type: 'object',
  required: ['refuted'],
  properties: {
    refuted: { type: 'boolean' },
    reason: { type: 'string' },
    correctedCitation: { type: 'string' },
    quoteAccurate: { type: 'boolean' },
    currentTreatment: { type: 'string' },
  },
}

const FINAL_SCHEMA = {
  type: 'object',
  required: ['memo'],
  properties: { memo: { type: 'string', description: 'the final memo in Markdown — nothing else' } },
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
const surveyJobs = vectors.map((v) => () =>
  agent(surveyPrompt(v), {
    label: `survey:${v.label}`.slice(0, 60),
    phase: 'Survey',
    schema: CANDIDATES_SCHEMA,
    model: SCOUT_MODEL,
    effort: 'low',
  })
)
if (DO_SCHOLARSHIP) {
  surveyJobs.push(() =>
    agent(zoteroSurveyPrompt, {
      label: 'survey:zotero-library',
      phase: 'Survey',
      schema: CANDIDATES_SCHEMA,
      model: SCOUT_MODEL,
      effort: 'low',
    })
  )
}
if (PROJECT_DIR) {
  surveyJobs.push(() =>
    agent(localSurveyPrompt, {
      label: 'survey:local-corpus',
      phase: 'Survey',
      schema: CANDIDATES_SCHEMA,
      model: SCOUT_MODEL,
      effort: 'low',
    })
  )
}
const surveys = await parallel(surveyJobs)

// Lever 1: dedup the candidate pool in PLAIN CODE before any page is fetched, so the same source
// is never read twice across overlapping vectors.
const poolMap = new Map()
for (const s of surveys.filter(Boolean)) {
  for (const c of s.candidates || []) {
    const k = norm(c.citation) || norm(c.url)
    if (!k) continue
    if (!poolMap.has(k)) poolMap.set(k, c)
    else {
      // keep the richer record; prefer the higher apparent authority
      const cur = poolMap.get(k)
      const rank = { high: 3, medium: 2, low: 1 }
      if ((rank[c.authority] || 0) > (rank[cur.authority] || 0)) poolMap.set(k, { ...cur, ...c })
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
  ).catch(() => ({ selected: [] }))
  selectedIdx = (triage.selected || []).filter((i) => i >= 0 && i < pool.length).slice(0, READ_CAP)
}
if (!selectedIdx.length) selectedIdx = pool.slice(0, READ_CAP).map((_, i) => i)
// Budget check: trim the read list (worst-ranked first) rather than die before Draft. The floor
// scales with declared issues on historical questions so trimming can't zero out whole eras.
// Degradation events are collected so the run can return an honest exit state (ported from the
// Codex deep-research-cli exit-state contract).
const degradation = []
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
const readResults = await parallel(
  toRead.map((c) => () =>
    agent(readPrompt(c), {
      label: `read:${(c.citation || c.url || '').slice(0, 50)}`,
      phase: 'Read',
      schema: READ_SCHEMA,
      model: READ_MODEL,
      effort: 'low',
    })
  )
)

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
const leads = [...poolLeads, ...citedWithin].slice(0, LEADS_CAP)
const findings = [...readFindings, ...leads]
const openedCount = readFindings.filter((f) => f.opened).length
log(`Read ${openedCount} sources in full; carrying ${leads.length} unread leads (${citedWithin.length} harvested from within read sources).`)

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
// rules already injected into the Draft prompt plus the Finalize audit.
if (DEEP && !tight(RESERVE_FINALIZE + 35_000)) {
  const cal = await agent(
    `You are an adversarial calibration reviewer for a legal research memo. Do NOT re-research, add,
or remove authorities. Your only job is to make the memo's CLAIMS match its EVIDENCE. Audit the
draft below and return a revised draft (same structure, lightest touch) fixing:
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

QUESTION: ${QUESTION}

=== DRAFT ===
${draft.memoDraft || ''}`,
    { schema: { type: 'object', required: ['memoDraft'], properties: { memoDraft: { type: 'string' } } },
      label: 'calibrate:thesis', phase: 'Draft', effort: 'high' }
  ).catch(() => null)
  if (cal && cal.memoDraft && cal.memoDraft.length > (draft.memoDraft || '').length * 0.6) {
    draft.memoDraft = cal.memoDraft
    log('Deep calibration pass applied to the draft.')
  } else if (cal) {
    log('Deep calibration returned a suspiciously short draft — keeping the original.')
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
const readKeys = new Set(readFindings.filter((f) => f.opened).map((f) => norm(f.citation)))
const toVerify = [
  ...cited,
  ...gapFindings.map((f) => ({
    citation: f.citation, url: f.url, proposition: f.proposition,
    quote: f.quote, pincite: f.pincite, kind: f.kind, gapFill: true,
  })),
].map((c, i) => ({ ...c, gi: i, wasRead: !!c.gapFill || readKeys.has(norm(c.citation)) }))

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
Read treatment_probe.most_relevant, prioritizing rows with mentions_target=true (the snippet
actually names this case's parties). A signal row about THIS case (e.g. "overruled by <X>") goes
in currentTreatment — name the treating case and, if the snippet shows it, the scope (full
overruling / partial abrogation / narrowing); if scope isn't visible, report the signal with
"scope unconfirmed". Rows about OTHER cases are noise — ignore them; the tool's caveats explain.
Also glance at most_recent_citing_date: if nothing has cited the case in ~5+ years, note
"dormant — most recent citing case <date>" in currentTreatment. If the script errors, fall back
to the quick web search ("<case name> overruled" / "abrogated"). No hits is NOT proof of good
law — this approximates, not replaces, Shepard's/KeyCite.
Authorities tagged [READ IN FULL THIS RUN] were already opened and quoted by a research agent this
run — skip existence re-confirmation for those; check only citation format and negative treatment.
${DEEP
    ? `Be adversarial — try to disprove each; open the source to confirm quotes. When you open a
source to check a quote, settle verbatim-ness deterministically: python3 "${FETCH_PAGE}" "<url>"
--out /tmp/src.txt, then python3 "${VERIFY_QUOTES}" /tmp/src.txt "<quote>" — its
verbatim/normalized/altered/not_found status (and word_diff on misses) is the answer; save your
judgment for whether the passage supports the proposition.`
    : 'Be efficient — a reliable search/catalog/API hit confirming the case name, reporter, and year is enough for existence; only open the source if something looks off. You are confirming, not re-researching (but if you DO open a source to check a quote, run it through the deterministic verifier: python3 "' + FETCH_PAGE + '" "<url>" --out /tmp/src.txt && python3 "' + VERIFY_QUOTES + '" /tmp/src.txt "<quote>").'}
ACCESS DISCIPLINE: at most 2 access attempts per authority, via WebSearch/WebFetch only — never
browser automation, library proxies, or SSO/login flows. If a source sits behind a paywall or bot
wall, stop and report the strongest basis you actually reached (secondary-corroboration or
citation-only are honest answers); do not grind on access.
Return one verdict per authority: "verified", "needs-correction" (give correctedCitation), or
"unverified" (could not confirm). Echo each authority's index EXACTLY as given in [brackets].
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

const chunkJob = (ch) => () =>
  agent(chunkPrompt(ch), {
    label: `verify:${ch[0].gi}-${ch[ch.length - 1].gi} (${ch.length})`,
    phase: 'Verify',
    schema: VERDICT_SCHEMA,
    model: VERIFY_MODEL,
    effort: 'low',
  }).then((o) => (o && o.verdicts) || [])

// Deep mode: each load-bearing authority gets 3 independent refutation votes; ≥2 refutes kill it.
const refutePrompt = (c, k) => `You are independent cite-checker #${k} of 3. Your job is to try to
REFUTE a load-bearing authority in a legal memo. Check adversarially:
(1) does this authority actually exist; (2) is the citation (reporter, volume, page, year, court)
accurate; (3) OPEN the source — does the quote appear VERBATIM, and does it support the stated
proposition at the given pincite; (4) for cases: overruled, abrogated, or superseded?
For (3), settle verbatim-ness DETERMINISTICALLY, not by eye: save the source text to a file and
run the quote verifier —
  python3 "${FETCH_PAGE}" "<url>" --out /tmp/refute-src.txt
  python3 "${VERIFY_QUOTES}" /tmp/refute-src.txt "<the quote>"
(text obtained any other way — Zotero fulltext, a saved page — goes into a scratch file the same
way). Its status is the verbatim-ness answer: verbatim/normalized -> the quote is good;
altered -> check the marked alterations are honest; not_found -> read the word_diff — draft_only/
source_only/changed words are substantive (grounds to refute), "cosmetic" entries on an OCR'd
scan are scan noise, not a refutation. It also reports the printed page of the match — use that
for the pincite instead of eyeballing page markers. Your own judgment goes to SUBSTANCE: does the
passage actually support the proposition.
If you cannot confirm a claimed quote or pincite, or you are genuinely uncertain the authority is
real, set refuted=true and say why. A wrong-but-fixable citation is NOT a refutation — set
refuted=false and give correctedCitation.
Tip: for CASES, settle existence and the reporter cite deterministically first — via the Bash tool
(load with ToolSearch "select:Bash" if needed): python3 "${CHECK_CITE}" "<cite>" — and check
treatment systematically with: python3 "${CL_TOOLS}" citing "<cite>" --limit 15 (read
treatment_probe.most_relevant, mentions_target=true rows first; a signal about THIS case →
currentTreatment with the treating case named; rows about other cases are noise). Then spend your
adversarial effort on the quote and the pincite.
ACCESS DISCIPLINE: at most 3 access attempts, via WebSearch/WebFetch only — never browser
automation, library proxies, or SSO/login flows. "I could not open the source" is NOT a refutation
by itself: if the source is paywalled, judge on what you could reach and say so in your reasoning.

AUTHORITY: ${c.citation}
URL: ${c.url || '(locate it yourself)'}
Proposition: ${c.proposition || ''}
Quote: ${c.quote || '(none)'} ${c.pincite ? '@ ' + c.pincite : ''}
${SOURCES}`

const refuteJob = (c) => () =>
  parallel(
    [1, 2, 3].map((k) => () =>
      agent(refutePrompt(c, k), {
        label: `refute:${(c.citation || '').slice(0, 40)}#${k}`,
        phase: 'Verify',
        schema: REFUTE_SCHEMA,
        model: VERIFY_MODEL,
        effort: 'medium',
      })
    )
  ).then((votes) => {
    const vs = votes.filter(Boolean)
    const refutes = vs.filter((v) => v.refuted).length
    const corrected = vs.find((v) => v.correctedCitation)?.correctedCitation
    const treatment = vs.find((v) => v.currentTreatment)?.currentTreatment
    return [{
      index: c.gi,
      citation: c.citation,
      verdict: refutes >= 2 ? 'unverified' : corrected ? 'needs-correction' : 'verified',
      basis: 'direct-full-text', // refutation voters are required to open the source
      correctedCitation: corrected,
      currentTreatment: treatment,
      notes: vs.map((v) => v.reason).filter(Boolean).slice(0, 2).join(' | ') || `${refutes}/3 refute votes`,
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

let verdicts = []
if (verifyList.length) {
  const jobs = []
  const chunkable = []
  // Deep refutes cost 3 medium-effort agents EACH, and the draft decides how many cites are
  // load-bearing — cap the refute set so a generous draft can't fan out unboundedly.
  const loadBearing = DEEP ? verifyList.filter((c) => c.loadBearing) : []
  const refuteSet = new Set(loadBearing.slice(0, REFUTE_CAP).map((c) => c.gi))
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
const vFor = (c) => {
  if (skippedSet.has(c.gi)) return { verdict: 'unchecked', notes: 'cite-check skipped — token budget' }
  const v =
    vmap.get(c.gi) ||
    verdicts.find((v) => v.citation && norm(v.citation) === norm(c.citation)) ||
    { verdict: 'unverified', notes: 'no verdict returned' }
  // A source a research agent opened and quoted this run is direct-full-text even if the
  // cite-checker (told to skip existence re-checks for it) reported a weaker basis.
  if (c.wasRead && v.verdict === 'verified') v.basis = 'direct-full-text'
  return v
}
const tagged = toVerify.map((c) => ({ ...c, v: vFor(c) }))
const okCount = tagged.filter((t) => t.v.verdict === 'verified').length
const fixCount = tagged.filter((t) => t.v.verdict === 'needs-correction').length
const badCount = tagged.filter((t) => t.v.verdict === 'unverified').length
const skipCount = tagged.filter((t) => t.v.verdict === 'unchecked').length
log(`Authorities checked: ${okCount} verified, ${fixCount} need correction, ${badCount} unverified${skipCount ? `, ${skipCount} unchecked (budget)` : ''}.`)

// ---- Phase 6: finalize -----------------------------------------------------
phase('Finalize')
const verifyReport = tagged
  .map(
    (t) =>
      `- [${t.v.verdict}${t.v.basis ? ` | ${t.v.basis}` : ''}] ${t.citation}${t.v.correctedCitation ? ` -> ${t.v.correctedCitation}` : ''}${
        t.v.currentTreatment ? ` (${t.v.currentTreatment})` : ''
      }${t.v.notes ? ` — ${t.v.notes}` : ''}`
  )
  .join('\n')

const gapReport = tagged
  .filter((t) => t.gapFill)
  .map(
    (t) =>
      `- ${t.citation} [cite-check: ${t.v.verdict}]\n  Proposition: ${t.proposition || ''}\n  Quote: ${t.quote || '(none)'} ${t.pincite ? '@ ' + t.pincite : ''}\n  URL: ${t.url || ''}`
  )
  .join('\n')

const final = await must('Finalize', () => agent(
  `You are finalizing a legal research memo. Apply the cite-check results to the draft with the
LIGHTEST touch needed — preserve the draft's prose verbatim except where an edit below requires a
change. Do not rewrite, restyle, or compress.

Apply these edits:
- Replace any "needs-correction" citation with its corrected form.
- Where a currentTreatment notes negative treatment, reflect it in the text (e.g. "overruled by…").
- For any "unverified" authority: either remove the sentence's reliance on it or downgrade it to an
  explicit caveat ("reportedly / could not be independently confirmed"). Never present an unverified
  authority as settled law.
- QUANTIFIER AUDIT (one scan, edit in place): find any "first / only / never / always / settled /
  overwhelmingly / dominant / rare / erased / dead" or equivalent frequency/priority/finality claim
  that the memo's own disclosed research design cannot support, and downgrade it to sample-scoped
  language ("in the leading cases reviewed", "the earliest clean statement found in this
  research"). Cite-checks confirm sources; they do not license generalizations.
${skipCount ? `- Authorities marked "unchecked" were NOT cite-checked (the token budget ran out) —
  this is different from unverified. KEEP them as cited, but tag each one's first citation with
  "[not independently cite-checked]" and list them separately in the Limits section.` : ''}
${gapReport ? `- POST-DRAFT ADDITIONS: the authorities below were retrieved after drafting to fill
  gaps the draft itself flagged. Weave each into the memo where the draft noted the gap, with its
  cite — subject to its cite-check verdict above. Remove the corresponding gap notes.` : ''}
- Append two sections:
  * **Table of Authorities** (only verified/corrected authorities, grouped by type).
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
${draft.memoDraft || '(empty draft)'}

Return the final memo in Markdown via the memo field.`,
  { schema: FINAL_SCHEMA, phase: 'Finalize', effort: 'medium' }
))

// Exit state (ported from the Codex deep-research-cli contract): make degradation machine-visible
// so the orchestrator's deliver step can react deterministically instead of parsing logs.
// - budget_exhausted: the budget guard cut coverage (trimmed reads, skipped gap-fill, unchecked
//   cites) — the memo is honest but the RESEARCH is incomplete; consider targeted fill passes.
// - complete_with_limits: full budget ran, but the record has documented gaps (failed fetches,
//   unverified or unrecovered authorities) — disclosed in the memo's Limits section.
// - complete: planned coverage met and every cited authority checked.
const failedOpens = readFindings.filter((f) => !f.opened).length
const unrecoveredGaps = Math.max(0, (draft.missingAuthorities || []).length - gapFindings.length)
const exitState = degradation.length
  ? 'budget_exhausted'
  : (badCount || failedOpens || unrecoveredGaps) ? 'complete_with_limits' : 'complete'
if (failedOpens) degradation.push(`${failedOpens} selected sources could not be opened`)
if (unrecoveredGaps) degradation.push(`${unrecoveredGaps} draft-flagged authorities never retrieved`)

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
  },
  memo: final.memo,
}
