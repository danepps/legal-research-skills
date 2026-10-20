export const meta = {
  name: 'cite-check',
  description: 'Verify every citation and quotation in an article draft against real sources — resolve Id./supra chains, collapse to unique sources, verify verbatim, re-verify high-severity findings, and grade a footnote-by-footnote report',
  phases: [
    { title: 'Segment', detail: 'resolve each quote to the specific source it hangs on (Id./supra chains, syllabus routing)' },
    { title: 'Existence', detail: 'CourtListener existence + caption check for every case cite, plus existence/metadata check of every unique unquoted secondary source (web-escalate misses)' },
    { title: 'Verify', detail: 'one agent per unique source: fetch once, check every quote verbatim + pincites + metadata' },
    { title: 'Re-verify', detail: 'mandatory verify-the-verifier pass on every high-severity finding' },
    { title: 'Form', detail: 'Bluebook typeface + short forms, decided from the draft alone (no sources)' },
    { title: 'Report', detail: 'assemble the graded, footnote-by-footnote cite-check report' },
  ],
}

// ---- args (assembled by SKILL.md from the extraction scripts) ----------------
// args = {
//   skillsDir: '<plugin root>/skills' (where the helper scripts live),
//   extractPath, unitsPath, draftPath, draftName,
//   unitCount, footnoteCount, caseCites:[...], supraProblems:[...],
//   formChecks:<extract.json form_checks block>,
//   ledger:[...], secondaryCites:[...]   (citation_ledger.py --compact)
//   deep:boolean, footnotesOnly:[lo,hi]|null, zotero:boolean
// }
let A = args || {}
if (typeof A === 'string') { try { A = JSON.parse(A) } catch { A = {} } }
const EXTRACT_PATH = A.extractPath || ''
const DRAFT_NAME = A.draftName || 'draft'
const UNIT_COUNT = A.unitCount || 0
const FOOTNOTE_COUNT = A.footnoteCount || 0
const CASE_CITES = A.caseCites || []
const SUPRA_PROBLEMS = A.supraProblems || []
// Citation-instance LEDGER (citation_ledger.py --compact, added 2026-09-06): EVERY citation
// instance in every footnote — quoted or not, case or secondary — with Id./supra/short-form
// cross-references pre-resolved. Joined to agent results after re-verify so the report can say
// per instance what was verified, what merely exists, and what was NOT checked at all.
const LEDGER = Array.isArray(A.ledger) ? A.ledger : []
const SECONDARY_CITES = Array.isArray(A.secondaryCites) ? A.secondaryCites : []
const DEEP = !!A.deep
const ZOTERO_OK = A.zotero !== false // assume available unless SKILL.md says otherwise
const ZOTERO_SERVER = A.zoteroServer || 'zotero' // per-project; SKILL.md pre-flight resolves it (setup registers "zotero" for a personal library, "zotero-<name>" for a group)
// Partial pass (DESIGN.md: `--footnotes 45-80`): SKILL.md resolves a footnote
// range/list to explicit unit ids and passes them here. Empty => full draft.
const UNIT_IDS = Array.isArray(A.unitIds) && A.unitIds.length ? A.unitIds.slice() : null
// id -> footnote number for every quote unit (prepare_units.py prints `unit_notes`; SKILL.md
// passes it as unitNotes). Deterministic, so a report line never depends on an agent echoing
// the footnote. Accepts [[id, note], ...] or {id: note}.
const UNIT_NOTES = new Map()
if (Array.isArray(A.unitNotes)) for (const [i, n] of A.unitNotes) UNIT_NOTES.set(Number(i), n)
else if (A.unitNotes && typeof A.unitNotes === 'object') for (const [i, n] of Object.entries(A.unitNotes)) UNIT_NOTES.set(Number(i), n)
// Bluebook FORM checks (the author lifted the format-linter scope lock 2026-08-10 "insofar
// as it's stopping you from checking obvious stuff"). Deterministic findings come
// straight from the extractor via the shared `citeform` module — the SAME module
// /proofread uses, so the two skills cannot give contradictory advice. Only the
// case-name judgment call needs an agent.
const FORM = A.formChecks || {}
const FORM_FINDINGS = FORM.findings || []
const FORM_FMT_OK = !!FORM.available
const FORM_FMT_PATH = FORM.fulltext_fmt || ''
const FORM_CANDIDATES = FORM.case_name_candidates || []

// Bundled helper scripts. SKILL.md passes skillsDir = "${CLAUDE_PLUGIN_ROOT}/skills",
// which Claude Code expands to the plugin's install directory before the call. The
// fallback is the plain ~/.claude/skills layout; $HOME (not ~) because every use
// below lands inside shell double quotes in an agent prompt, where $HOME expands but ~ does not.
const SKILLS = A.skillsDir || '$HOME/.claude/skills'
const PREPARE = `${SKILLS}/cite-check/scripts/prepare_units.py`
const CHECK_CITE = `${SKILLS}/legal-research/check_cite.py`
const FETCH_PAGE = `${SKILLS}/legal-research/fetch_page.py`
const VERIFY_QUOTES = `${SKILLS}/cite-check/scripts/verify_quotes.py`

// ---- knobs -------------------------------------------------------------------
const SEGMENT_CHUNK = 28   // quote-units per resolver agent
const EXIST_BATCH = 30     // case cites per existence agent (CL paces 60/min)
const SECONDARY_BATCH = 12 // unique secondary sources per existence/metadata agent
const VERIFY_CHUNK = 8     // small/quoteless sources bundled per verify agent
const MIRROR_CAP = 3       // max fetch attempts per source before "unverifiable"

// Model map (house convention): mechanical/mid-volume work on Sonnet; the final
// report inherits the session model (its prose is the deliverable). No stage
// runs on Haiku — a weak read here becomes a false accusation against the draft.
const RESOLVE_MODEL = 'sonnet'
const VERIFY_MODEL = 'sonnet'
const REVERIFY_MODEL = 'sonnet'

// Budget: always-armed soft cap + graceful degradation (ported from
// legal-research). The practice run burned ~2.2M without unique-source
// bundling and Id./supra pre-resolution; with them the target is 400-700k.
const RESERVE_REPORT = 60_000
const RESERVE_REVERIFY = 40_000
let SOFT_CAP = DEEP ? 900_000 : 650_000  // +100k (2026-09-06) for the secondary-source existence pass
// budget.spent() is TURN-GLOBAL (main loop + every workflow this turn). Baseline
// it at workflow start so the soft cap governs THIS workflow's own output — else
// invoking the skill late in a busy session spuriously degrades from agent one.
// A user "+Nk" budget (budget.total) is a real hard ceiling, so honor it directly.
const SPENT0 = budget.spent()
const remaining = () => budget.total ? budget.remaining() : Math.max(0, SOFT_CAP - (budget.spent() - SPENT0))
const tight = (need) => remaining() < need
const degradation = []

const norm = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()

// Collapse a resolved citation to a unique-source key: drop the pincite and any
// parenthetical so a case cited 30 times at different pages fetches ONCE.
function sourceKey(citation, kind) {
  let s = (citation || '').toLowerCase()
  s = s.replace(/\([^)]*\)/g, ' ')            // parentheticals
  s = s.replace(/,?\s*at\s+[\d,\s–-]+/g, ' ') // ", at 512–13"
  s = s.replace(/\bslip op[^,;]*/g, ' ')
  // keep volume+reporter+firstpage for cases; collapse trailing pincites
  const m = s.match(/(\d+)\s+(u\.?\s?s\.?|s\.?\s?ct\.?|f\.?\s?(?:2d|3d|4th|supp\.?(?:\s?[23]d)?)?|[a-z.\s]+?)\s+(\d+)/)
  if (m) return norm(`${m[1]} ${m[2]} ${m[3]}`)
  return norm(s).split(' ').slice(0, 8).join(' ')
}

const SOURCES = `FREE / OPEN-WEB SOURCES ONLY (no Westlaw/Lexis):
- Cases: CourtListener (HTML opinion view), Cornell LII, Justia, Google Scholar case law.
  OFFICIAL reporter text with star pagination (best for verbatim quotes + pincites):
  * Harvard Caselaw Access Project static HTML — https://static.case.law/us/<vol>/html/<page>-01.html
    (pad first page to 4 digits, e.g. us/536/html/0181-01.html; other reporters by slug: /f-supp/, /f2d/).
  * Library of Congress U.S. Reports page scans — tile.loc.gov usrep PDFs (route through the capped
    fetcher script, NEVER raw WebFetch). Authoritative, and — CRITICAL — the ONLY free source that
    carries the SYLLABUS and front matter; CourtListener/CAP opinion text does NOT.
- Statutes/rules: uscode.house.gov, Cornell LII, official state legislature sites.
- Scholarship: the user's Zotero library FIRST (see per-agent instructions), then SSRN, Google
  Scholar, law-school digital-commons repositories, HeinOnline open content, journal sites, author
  faculty pages, Google Books / archive.org snippet search for book quotes.
- KNOWN FETCH BLOCKS: Justia and SSRN often return HTTP 403 to scripted fetches; bepress/
  digital-commons and some university repositories block too. Mirror chain that works: journal's own
  site → non-bepress repository → Wayback Machine → Google Books snippet. Cap attempts per source at
  ${MIRROR_CAP}; then mark the item unverifiable with the unlock path (Hein/JSTOR pull), do NOT burn
  retries.
- PDFs: never WebFetch a PDF and never \`open\`/GUI-view one. Run the capped fetcher via Bash
  (load Bash with ToolSearch "select:Bash" if needed): python3 "${FETCH_PAGE}" "<url>"
TOOLS: WebSearch and WebFetch. If not callable, first run ToolSearch query "select:WebSearch,WebFetch".`

// Deterministic quote check: the model proposes, the script proves. Shared by
// every prompt whose agent fetches source text (verify / tail / re-verify).
const DETERMINISTIC_CHECK = `DETERMINISTIC QUOTE CHECK (MANDATORY before judging any quote by eye):
save each fetched source's FULL text to a scratch file with --out (this bypasses the stdout
truncation caps — a plain "> file" redirect does NOT) and run the deterministic verifier over every
quote you were given, e.g.:
  python3 "${FETCH_PAGE}" "<url>" --out /tmp/src-<slug>.txt
  python3 "${VERIFY_QUOTES}" /tmp/src-<slug>.txt --json /tmp/q-<slug>.json
where <slug> is a short filename-safe tag for the source (letters, digits, dashes — no spaces) and
the JSON file holds [{"id":..,"quote":"..","pincite":".."}] with every quote copied EXACTLY. Always
use the --json route: passing quotes as shell arguments breaks on any quote that contains a double
quote, a dollar sign, a backtick or an apostrophe, and a quote mangled by the shell is reported
not_found through no fault of the draft.
(--out prints a one-line summary; NEVER cat the file into your context — it can be an entire
book-length source. Read at most targeted excerpts around the verifier's reported matches.)
The same check applies to source text you obtained ANY other way — Zotero fulltext (write the
tool's returned text to a scratch file VERBATIM, unedited), a saved page, a pasted excerpt: put
it in a file and run the verifier against it. Once source text is in hand, no quote gets a
verbatim/mismatch verdict by eye.
For pincite checking, add --first-page to the same command:
  python3 "${VERIFY_QUOTES}" /tmp/src-<slug>.txt --json /tmp/q-<slug>.json --first-page <printed page no. of the PDF's first page>
Per quote it reports a status — verbatim | normalized (typographic-only differences: curly vs
straight quotes, dashes, hyphenation, ligatures — identical as printed) | altered (matches with the
draft's MARKED ellipses/brackets honored) | not_found — plus the printed PAGE of the match when the
text carries page boundaries (form feeds from the fetcher + --first-page, star pagination *N as CAP
and CourtListener carry it, or <<pg. N>> markers), a match excerpt, and on not_found a HINT showing
the closest source passage. Rules:
- The script's status IS the verbatim-ness verdict: map verbatim/normalized -> "verbatim", altered ->
  "altered_marked" (unless the marked alterations misrepresent the source — that judgment is yours).
  Do NOT overrule it by re-comparing characters yourself; your judgment is for SUBSTANCE (framing
  fidelity, meaning, metadata, honesty of alterations), not character comparison.
- not_found with a close hint: read the word_diff before concluding anything. draft_only /
  source_only / changed words are SUBSTANTIVE — a dropped or altered word is the candidate finding;
  copy the exact source language from the hint into sourceText. Entries under "cosmetic" are
  punctuation/case-level differences inside otherwise-identical words: on an OCR'd scan (LOC bound
  volumes) that is usually scan noise, NOT a draft error — confirm against a cleaner text of the
  same source (CAP static HTML / CourtListener) before reporting any verbatim-ness finding, and if
  the cleaner text matches, the verdict is verbatim. You may adjust and re-run AT MOST TWICE; a
  quote still not_found (with no innocent explanation) stays a finding.
- Pincites: use the script's page numbers instead of reading footer/star page markers by eye — this
  removes the off-by-one marker-convention trap. If it reports no page boundaries ("marker": "none"),
  fall back to the marker-convention rules and say which convention you assumed.
- Scope honesty: the script proves PRESENCE in the file you fetched, nothing more. A match inside a
  truncated fetch is only as good as the fetch; quote/pincite only from text above any [TRUNCATED]
  marker.`

// Hard calibration rules, hardwired into every agent that renders a verdict.
// These encode the practice run's five false findings so they cannot recur.
const CALIBRATION = `VERDICT DISCIPLINE — READ BEFORE JUDGING ANY QUOTE (these rules exist because
each was violated once and produced a FALSE accusation against the draft):
- Absence of a match licenses "not found in the sources checked" — NEVER "fabricated." A
  fabrication verdict requires that you have the FULL footnote text in view AND have actually
  searched EVERY source it names (including every parenthetical and "see also"). The practice run
  called a verbatim Merrill quote "fabricated" because a truncated footnote hid the Merrill
  attribution and the agent searched only the case cites.
- A verbatim FRAGMENT of a source, wrapped in the draft's OWN framing verb ("has encouraged courts
  to '…'", "has lamented that '…'"), is legitimate practice — judge FRAMING FIDELITY against the
  quote's surrounding body sentence, not word-for-word sentence identity. The practice run flagged a
  "dropped not reversing meaning" that was a faithful fragment + accurate framing.
- Resolve the citation the quote ACTUALLY hangs on before judging it. A bare "Id." points at its
  antecedent (which may be a CASE two notes up), not at a "see also" cite in the same note; follow
  any "supra note N" redirect to the note it names. You are given the antecedent notes and supra
  targets — use them.
- A quote pinned to the FIRST PAGE of a U.S. Reports cite (e.g. "536 U.S. 181, 181") is quoting the
  SYLLABUS, which "constitutes no part of the opinion of the Court" (Detroit Timber). CourtListener
  carries no syllabus, so a "silent splice" against opinion text is a false diagnosis — check the
  bound-volume (LOC) syllabus. A verbatim syllabus quote is itself a finding: verdict
  "syllabus_quote" (accurate but should be replaced with the opinion's equivalent language), NOT a
  misquote.
- Honest alterations (bracketed changes, ellipses, capitalization) are matched against the source
  with the marked alteration masked: the question is whether the marked-up quote honestly maps to
  the source, verdict "altered_marked" — not a mismatch.
- Never judge from memory. If you could not fetch and read the source, the verdict is
  "unverifiable" with the unlock path — never assume, never "fabricated."`

// ---------------------------------------------------------------------------
// SCHEMAS
// ---------------------------------------------------------------------------
const SEGMENT_SCHEMA = {
  type: 'object',
  required: ['resolutions'],
  properties: {
    resolutions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'source', 'kind'],
        properties: {
          id: { type: 'integer', description: 'the unit id, echoed exactly' },
          footnote: { type: 'integer', description: 'the unit\'s footnote number, echoed exactly (for a body quote, the footnote that carries its citation)' },
          quote: { type: 'string', description: 'the quoted text, echoed (short)' },
          source: { type: 'string', description: 'the SPECIFIC citation this quote hangs on, fully resolved (Id. walked to its antecedent, supra redirects followed). Copy the citation as printed.' },
          kind: { type: 'string', enum: ['case', 'statute', 'article', 'book', 'internet', 'unknown'] },
          pincite: { type: 'string', description: 'the page/section the quote is pinned to, resolved through the chain (e.g. an "Id. at 522" inherits the antecedent work at p. 522)' },
          syllabus: { type: 'boolean', description: 'true if the pincite is the first page of a U.S. Reports cite or otherwise points at the syllabus/front matter rather than the opinion' },
          manuscript: { type: 'boolean', description: 'true if the source is a working paper / "forthcoming" / SSRN preprint / slip opinion — needs a version-drift check' },
          resolutionNote: { type: 'string', description: 'one line: how you resolved an Id./supra chain, if any (for the report). Empty if the cite was already explicit.' },
        },
      },
    },
  },
}

const EXIST_SCHEMA = {
  type: 'object',
  required: ['results'],
  properties: {
    results: {
      type: 'array',
      items: {
        type: 'object',
        required: ['citation', 'exists'],
        properties: {
          citation: { type: 'string' },
          exists: { type: 'boolean' },
          caseName: { type: 'string' },
          dateFiled: { type: 'string' },
          corrected: { type: 'string', description: 'corrected reporter citation if the cited one is a typo (e.g. "03 U.S. 95" -> "303 U.S. 95")' },
          basis: { type: 'string', enum: ['courtlistener-api', 'web', 'unconfirmed'] },
          note: { type: 'string' },
        },
      },
    },
  },
}

const SECONDARY_EXIST_SCHEMA = {
  type: 'object',
  required: ['sources'],
  properties: {
    sources: {
      type: 'array',
      items: {
        type: 'object',
        required: ['key', 'exists'],
        properties: {
          key: { type: 'string', description: 'the source key, echoed exactly' },
          exists: { type: 'boolean' },
          basis: { type: 'string', enum: ['zotero', 'web', 'unconfirmed'] },
          identified: { type: 'string', description: 'the source as located (URL / Zotero key / catalog record)' },
          metadataFindings: { type: 'array', items: { type: 'string' }, description: 'author/title/journal/volume/first-page/year/publisher/edition discrepancies between the draft cite and the located source — one line each with the fix; empty if clean' },
          note: { type: 'string' },
        },
      },
    },
  },
}

const VERIFY_SCHEMA = {
  type: 'object',
  required: ['sourceKey', 'verdicts'],
  properties: {
    sourceKey: { type: 'string', description: 'the source-bundle key, echoed' },
    sourceIdentified: { type: 'string', description: 'the source as you actually located and read it (with the URL/edition/version)' },
    fetchBasis: { type: 'string', enum: ['direct-full-text', 'authoritative-reproduction', 'secondary-corroboration', 'citation-only', 'not-fetched'] },
    captionOk: { type: 'boolean', description: 'cases: is the party caption spelled correctly as cited?' },
    yearCourtOk: { type: 'boolean', description: 'cases: are the year and court right?' },
    metadataFindings: {
      type: 'array',
      items: { type: 'string' },
      description: 'citation-metadata problems: reporter typo, wrong volume/page, wrong year/court, author/title/journal discrepancy, impossible pincite (page outside the work) — one line each with the fix',
    },
    versionDrift: { type: 'string', description: 'manuscripts only: if the quoted language is absent or moved in the CURRENT version, say so with the current revision date and the new location — flag "superseded-source"' },
    urlFinding: { type: 'string', description: 'internet sources: "live" / "dead — suggest archived URL <url>" / "bot-blocked but presumptively live"' },
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        required: ['id', 'verdict'],
        properties: {
          id: { type: 'integer', description: 'the unit id, echoed exactly' },
          verdict: {
            type: 'string',
            enum: ['verbatim', 'altered_marked', 'fragment_framing', 'mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source', 'pincite_off', 'unverifiable'],
          },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
          sourceText: { type: 'string', description: 'the ACTUAL source language at that location, verbatim, for a side-by-side (empty if not fetched)' },
          pinciteFinding: { type: 'string', description: 'e.g. "quote sits at 516–17, cited 503" / "pincite unverifiable — no star pagination" — never guess a page' },
          basis: { type: 'string', enum: ['direct-full-text', 'authoritative-reproduction', 'secondary-corroboration', 'citation-only'] },
          note: { type: 'string' },
        },
      },
    },
  },
}

// verify-the-verifier: re-derive one high-severity finding from full context.
const REVERIFY_SCHEMA = {
  type: 'object',
  required: ['id', 'upheld', 'verdict'],
  properties: {
    id: { type: 'integer' },
    upheld: { type: 'boolean', description: 'false if the original high-severity verdict was a checker artifact' },
    verdict: { type: 'string', enum: ['verbatim', 'altered_marked', 'fragment_framing', 'mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source', 'pincite_off', 'unverifiable'] },
    severity: { type: 'string', enum: ['high', 'medium', 'low'] },
    sourceText: { type: 'string' },
    reason: { type: 'string', description: 'why the original stands or was an artifact — name the artifact class if any (truncation / missing-framing / wrong-antecedent / syllabus)' },
  },
}

const REPORT_SCHEMA = {
  type: 'object',
  required: ['report'],
  properties: { report: { type: 'string', description: 'the final cite-check report in Markdown — nothing else' } },
}

// A dead critical agent must abort loudly, not surface as a TypeError later.
async function must(label, fn) {
  let r = await fn()
  if (!r) { log(`${label} agent died — retrying once`); r = await fn() }
  if (!r) throw new Error(`${label} agent failed twice — aborting run`)
  return r
}

// ===========================================================================
// Phase 1 — SEGMENT & RESOLVE (highest-care stage)
// ===========================================================================
phase('Segment')
// Chunk the work as contiguous id ranges (full draft) or explicit id picks
// (partial pass). Each chunk is [loadArg, ids] where loadArg is the exact
// prepare_units flags the agent runs.
const segChunks = []
if (UNIT_IDS) {
  for (let i = 0; i < UNIT_IDS.length; i += SEGMENT_CHUNK) {
    const ids = UNIT_IDS.slice(i, i + SEGMENT_CHUNK)
    segChunks.push({ load: `--pick ${ids.join(' ')}`, label: `pick-${i}`, count: ids.length })
  }
} else {
  for (let lo = 0; lo < UNIT_COUNT; lo += SEGMENT_CHUNK) {
    const hi = Math.min(lo + SEGMENT_CHUNK, UNIT_COUNT)
    segChunks.push({ load: `--ids ${lo} ${hi}`, label: `${lo}-${hi}`, count: hi - lo })
  }
}

const segPrompt = (ch) => `You are resolving quotations in a law-review draft to the SPECIFIC
source each one hangs on, before any verification. Precision here is everything: the practice run's
worst false findings all came from mis-resolving which source a quote belonged to.

STEP 1 — load your units. Run via the Bash tool (load it first with ToolSearch "select:Bash" if
needed):
  python3 "${PREPARE}" "${EXTRACT_PATH}" ${ch.load}
This prints a JSON array of quote-units. Each has: id, loc (body/footnote), quote, sentence (the
draft's surrounding body sentence), footnote number, home_note (the FULL footnote text), leading_id,
antecedents (the preceding footnotes' full text, for Id. chains), supra_targets (the full text of
any "supra note N" the note redirects through), syllabus_hint, and footnote_basis — how the
extractor paired a body quote with its footnote. "sentence-after" / "sentence-before" are solid;
"paragraph-after" / "paragraph-before" mean NO marker sat in the quote's own sentence, so the
pairing is a paragraph-level GUESS: check whether home_note actually cites a source for this
quote, look at the neighbouring notes in antecedents, and say in resolutionNote which note you
settled on and why. A null footnote means no marker anywhere in the paragraph.

STEP 2 — for EACH unit, determine the SPECIFIC source the quote is attributed to:
- If the home_note gives an explicit citation and the quote sits in a parenthetical of ONE cite in a
  string, attach it to THAT cite — never "the lead cite" by default.
- If the quote hangs on a bare "Id.", walk to the antecedent: the most recent PRECEDING citation in
  the antecedents (which may be a CASE two notes up). Do NOT attach it to a "see also" cite in the
  same note.
- If the chain runs through "supra note N", follow it: the real source is the one defined in
  supra_targets[N] (e.g. an "Id. at 522" whose antecedent says "Nelson, supra note 19" resolves to
  the work defined in note 19, at 522 — NOT to the nearest full cite of that author).
- Classify the source kind (case/statute/article/book/internet). Mark manuscript=true for any
  working paper / "forthcoming" / SSRN preprint / slip opinion. Set syllabus=true when the pincite
  is the first page of a U.S. Reports cite (syllabus_hint is a clue) or otherwise points at front
  matter.
- Record the resolved pincite (an Id. inherits its antecedent's page unless it gives its own).
- resolutionNote: one line ONLY when you resolved an Id./supra chain, so the report can show the work.

THE SOURCE FIELD IS VERBATIM DRAFT TEXT — NEVER RECONSTRUCTED. Copy the citation exactly as it
appears in home_note / antecedents / supra_targets. Hard rules (each violated in a real run, each
producing a false "fix your draft" finding):
- A citation with NO case name (e.g. "141 S. Ct. 1220, 1222 (2021) (Thomas, J., concurring)" or
  "600 U.S. 1 (2023)") is PROPER Bluebook form when the case is named in the accompanying body
  sentence — check the unit's sentence field. NEVER invent, infer, or "restore" a caption (a real
  run fabricated "Thompson v. Knight" for the nameless Biden v. Knight cite and the report told the
  author's draft misnamed the case). Copy the nameless cite as-is; if the sentence names the case,
  say so in resolutionNote ("caption in text: <name>"); if nothing names it, kind "unknown".
- NEVER emit placeholder text of your own ("[placeholder]", "TBD", a guessed author) — a real run
  emitted "Bartenwerfer... [placeholder]" for a Moore v. Harper Id.-chain and the report claimed the
  DRAFT contained a placeholder footnote. If you cannot resolve, the source field is still the
  verbatim unresolved draft text, kind "unknown", and resolutionNote says what's missing.

Echo each unit's id and footnote number EXACTLY and the quote (short). Do NOT verify anything yet, do NOT fetch sources,
do NOT judge accuracy — only resolve WHICH source and WHERE. Never invent a citation; if a unit's
source is genuinely unresolvable from the context given, set source to the verbatim draft text
and kind "unknown".`

const segAgent = (ch) => agent(segPrompt(ch), {
  label: `segment:${ch.label}`,
  phase: 'Segment',
  schema: SEGMENT_SCHEMA,
  model: RESOLVE_MODEL,
  effort: 'medium',
})
// A dead segment agent would silently drop a whole chunk of quotes: retry once, then account.
const segResults = await parallel(segChunks.map((ch) => async () => {
  let r = await segAgent(ch)
  if (!r) { log(`segment:${ch.label} died — retrying once`); r = await segAgent(ch) }
  return r
}))
const resolutions = []
for (const r of segResults.filter(Boolean)) for (const u of (r.resolutions || [])) {
  if (u.footnote == null && UNIT_NOTES.has(u.id)) u.footnote = UNIT_NOTES.get(u.id)
  resolutions.push(u)
}
const resById = new Map(resolutions.map((r) => [r.id, r]))
const segTarget = UNIT_IDS ? UNIT_IDS.length : UNIT_COUNT
// Units no resolution came back for (dead chunk, or an agent that skipped ids) — these can
// never be verified, so they are disclosed as unchecked rather than vanishing.
const allUnitIds = UNIT_IDS ? UNIT_IDS.slice() : Array.from({ length: UNIT_COUNT }, (_, i) => i)
const unresolvedIds = allUnitIds.filter((i) => !resById.has(i))
if (unresolvedIds.length) degradation.push(`${unresolvedIds.length} quote unit(s) got no resolution from the segment pass (agent failure or skipped ids) — listed as NOT CHECKED`)
log(`Resolved ${resolutions.length}/${segTarget} quotes to their specific source${unresolvedIds.length ? ` (${unresolvedIds.length} unresolved)` : ''}.`)

// ===========================================================================
// Phase 2 — CASE EXISTENCE (deterministic CourtListener + web escalation)
// ===========================================================================
phase('Existence')
const existBatches = []
for (let i = 0; i < CASE_CITES.length; i += EXIST_BATCH) existBatches.push(CASE_CITES.slice(i, i + EXIST_BATCH))

const existPrompt = (batch) => `You are confirming that case citations from a law-review draft are
real, and catching reporter typos. Do NOT read opinions here — this is existence + reporter only.

STEP 1 — run the deterministic CourtListener lookup on ALL of them at once, via Bash (load with
ToolSearch "select:Bash" if needed):
  python3 "${CHECK_CITE}" ${batch.map((c) => `"${c}"`).join(' ')}
It returns, per citation: found (bool), case_name, date_filed.

STEP 2 — for each citation:
- found + a sensible case name -> exists=true, basis "courtlistener-api", echo caseName/dateFiled.
- NOT found -> this is usually a CourtListener pagination gap for very recent U.S. Reports volumes,
  NOT a bad cite. Do ONE web search ("<volume> <reporter> <page>" or the case name if you can infer
  it) to confirm. If it resolves, exists=true, basis "web". If the citation looks malformed (e.g. a
  volume with a digit dropped, "03 U.S. 95"), propose the corrected citation.
- Recent F.4th / regional-reporter cites (decision plausibly <18 months old from the volume/year):
  free indexes often lack the reporter pagination entirely. Search the case NAME with the reporter
  cite, and for anything with a SCOTUS connection try the Court's QP/docket sheets ("DECISION BELOW"
  on supremecourt.gov prints the lower-court cite — this is how a real run's "unconfirmed"
  116 F.4th 959 was in fact confirmed as Wolford v. Lopez). If the case is real but the page can't
  be confirmed free, report exists=true with note "reporter page too recent for free indexes —
  spot-check on Westlaw", NOT "unconfirmed". Do NOT nominate a different case as "the" match on a
  partial web hit (a real run offered United States v. DeLeon for a cite that was correct as
  written).
- Only if genuinely nothing resolves: exists=false, basis "unconfirmed" — and say so plainly, never
  call it fabricated.
Pace yourself; if the script reports a 429 rate-limit, wait and retry once.
${SOURCES}`

// Secondary sources (articles / books / statutes / internet) cited WITHOUT a quotation never
// reach the verify stage, so this is the only pass that touches them: existence + metadata,
// no substance. One batch per SECONDARY_BATCH unique sources.
const secBatches = []
for (let i = 0; i < SECONDARY_CITES.length; i += SECONDARY_BATCH) secBatches.push(SECONDARY_CITES.slice(i, i + SECONDARY_BATCH))
const secPrompt = (batch) => `You are confirming that SECONDARY sources cited in a law-review draft exist and are
cited with the right metadata. Do NOT read them for substance, do NOT check any quotation, and do NOT
assess whether they support anything — existence + bibliographic metadata only.

SOURCES (echo each key exactly; the cite text is verbatim from the draft's footnote):
${batch.map((s) => `- key ${s.key} | ${s.kind} | ${s.cite}`).join('\n')}

For EACH source:
- article: locate it (${ZOTERO_OK ? `the "${ZOTERO_SERVER}" Zotero MCP tools first — search by author/title — then` : ''} Google
  Scholar, SSRN, HeinOnline citation page, the journal's site, a digital-commons repository) and confirm
  author, title, journal, volume, first page, year. basis "zotero" or "web".
- book: a catalog / publisher / Open Library / Google Books record confirming author, title, edition,
  publisher, year.
- statute / rule: the current official text (uscode.house.gov, LII, official state source) exists at
  that section.
- internet: the URL resolves (one fetch; a 403 bot-block is "presumptively live", a 404 is dead —
  try archive.org once and report the archived URL in note).
- other / unparsed: do your best from the cite text; if you cannot tell what it is, exists=false with
  basis "unconfirmed" and say why.
Cap effort at ${MIRROR_CAP} attempts per source. NEVER call a source fabricated: "not found in the
sources checked" (exists=false, basis "unconfirmed") is the strongest negative allowed. Put any
draft-vs-source discrepancy (wrong volume/year/author/title/edition) in metadataFindings, quoting the
draft's cite text verbatim.

METADATA CORRECTIONS — EVIDENCE RULE (the Bressman & Gluck lesson, 2026-10-19). A metadataFinding
that tells the author to CHANGE something (author name or order, volume, first page, year, title,
edition) must rest on the source's OWN record, actually opened with WebFetch / fetch_page / Zotero:
the journal's article or issue page, the PDF's first page, the publisher's or a library catalog
record, the HeinOnline or SSRN citation page. Search-result titles, snippets and URL slugs do NOT
count, and neither do third-party casebooks, syllabi, reading lists, CVs or other articles' footnotes
— they copy each other's mistakes (a real run "corrected" the author order of 66 Stan. L. Rev. 725
from an opencasebook.org URL slug; the Stanford Law Review's own page showed the draft was right).
- Every metadataFindings line ends with the evidence tag "[source: <URL or record you opened>]".
- If the only evidence is a snippet or a third-party listing, do NOT write a metadataFinding: put the
  possible discrepancy in the note field as "confirm: …" with what you saw, or open the source page first.
- Multi-part and companion articles ("Part I"/"Part II", symposium pairs, "Foreword"/"Afterword")
  routinely ROTATE author order and sit in different volumes; aggregators conflate the parts. Match
  the exact part the draft cites before reporting any author-order or volume discrepancy.
- Author ORDER specifically is never a finding without the source's own title page or landing page.
${SOURCES}`

const existGate = !tight(RESERVE_REPORT + RESERVE_REVERIFY + (existBatches.length + secBatches.length) * 4000)
const casePassRan = !CASE_CITES.length || existGate
const secondaryPassRan = !SECONDARY_CITES.length || existGate
if (!secondaryPassRan) degradation.push(`secondary-source existence pass skipped for ${SECONDARY_CITES.length} sources (budget) — they are UNCHECKED in the ledger`)
const existJobs = []
if (casePassRan) for (const b of existBatches) existJobs.push(() =>
  agent(existPrompt(b), { label: `exist:${b.length}`, phase: 'Existence', schema: EXIST_SCHEMA, model: VERIFY_MODEL, effort: 'low' }))
if (secondaryPassRan) for (const b of secBatches) existJobs.push(() =>
  agent(secPrompt(b), { label: `exist-secondary:${b.length}`, phase: 'Existence', schema: SECONDARY_EXIST_SCHEMA, model: VERIFY_MODEL, effort: 'low' })
    .then((o) => o && o.sources ? { _secondary: o.sources } : o))
const existRaw = existJobs.length ? await parallel(existJobs) : []
const existence = []
const secondaryExistence = []
for (const r of existRaw.filter(Boolean)) {
  if (r._secondary) secondaryExistence.push(...r._secondary)
  else for (const e of (r.results || [])) existence.push(e)
}
const secBad = secondaryExistence.filter((s) => s.exists === false && s.basis !== 'unconfirmed')
const secUnconfirmed = secondaryExistence.filter((s) => s.exists === false && s.basis === 'unconfirmed')
const secMetaAll = secondaryExistence.flatMap((s) => (s.metadataFindings || []).map((m) => `[${s.key}] ${m}`))
// Evidence gate (2026-10-19): a metadata CORRECTION is only an "Error (fix)" when the agent tagged
// the source record it actually opened ("[source: …]"). Untagged lines were derived from search
// snippets / third-party listings and go to the report as "confirm", never as a fix — the
// Bressman & Gluck author-order artifact came from an opencasebook.org URL slug.
// The tag must carry a record ("[source: ]" alone does not count).
const EVIDENCED = /\[source:\s*[^\]\s][^\]]*\]/i
const secMeta = secMetaAll.filter((m) => EVIDENCED.test(m))
// Tentative discrepancies the prompt told the agent to park in `note` as "confirm: …" would
// otherwise vanish for sources that exist (only exists=false notes reach the report).
const secConfirmNotes = secondaryExistence
  .filter((s) => s.exists !== false && s.note && /\bconfirm\b/i.test(s.note))
  .map((s) => `[${s.key}] ${s.note}`)
const secMetaSoft = [...secMetaAll.filter((m) => !EVIDENCED.test(m)), ...secConfirmNotes]
log(`Secondary-source existence: ${secondaryExistence.length}/${SECONDARY_CITES.length} checked, ${secBad.length} not found, ${secUnconfirmed.length} unconfirmed, ${secMeta.length} metadata findings.`)
const existBad = existence.filter((e) => e.exists === false)
const existFixed = existence.filter((e) => e.corrected)
log(`Case existence: ${existence.length} checked, ${existBad.length} unconfirmed, ${existFixed.length} reporter typos.`)

// ===========================================================================
// Collapse resolved quotes onto UNIQUE sources (lesson 1: fetch once)
// ===========================================================================
const bundles = new Map()
for (const r of resolutions) {
  const key = sourceKey(r.source, r.kind)
  if (!bundles.has(key)) bundles.set(key, { key, kind: r.kind, source: r.source, manuscript: false, syllabus: false, quotes: [] })
  const b = bundles.get(key)
  if (r.manuscript) b.manuscript = true
  if (r.syllabus) b.syllabus = true
  b.quotes.push({ id: r.id, quote: r.quote || '', pincite: r.pincite || '', syllabus: !!r.syllabus })
}
let bundleList = [...bundles.values()]
// Order: sources carrying the most quotes first (they're the load-bearing ones).
bundleList.sort((a, b) => b.quotes.length - a.quotes.length)
log(`Collapsed ${resolutions.length} quotes onto ${bundleList.length} unique sources.`)

// Budget degradation: if a full verify won't fit, verify multi-quote sources
// individually and batch the single-quote long tail; never drop a source silently.
const PER_SOURCE = 9_000
let verifyBundles = bundleList
if (bundleList.length && tight(RESERVE_REPORT + RESERVE_REVERIFY + bundleList.length * PER_SOURCE)) {
  const heavy = bundleList.filter((b) => b.quotes.length >= 2)
  const light = bundleList.filter((b) => b.quotes.length < 2)
  degradation.push(`verify degraded: ${light.length} single-quote sources batched, ${heavy.length} read individually (budget)`)
  log(`Budget tight — reading ${heavy.length} multi-quote sources individually; batching ${light.length} single-quote sources.`)
  verifyBundles = heavy
  // light sources get chunked existence/quote checks below via the tail batches
  verifyBundles._light = light
}

// ===========================================================================
// Phase 3 — VERIFY (one agent per unique source; path per kind)
// ===========================================================================
phase('Verify')
const zoteroHint = ZOTERO_OK
  ? `SCHOLARSHIP (article/book): try the user's Zotero library FIRST. This project's library is
  served by the "${ZOTERO_SERVER}" MCP server. Load with
  ToolSearch "select:mcp__${ZOTERO_SERVER}__zotero_search_items,mcp__${ZOTERO_SERVER}__zotero_item_metadata,mcp__${ZOTERO_SERVER}__zotero_item_fulltext"
  (if those tools are absent, fall back to the mcp__zotero__* personal-library equivalents, knowing
  a co-authored project's sources usually live in its group library). Search by author/title; if the item is there, use
  zotero_item_metadata for existence/volume/page and zotero_item_fulltext to check the quote and
  pincite verbatim. Item keys can also be read from the draft's own Word field codes (CSL_CITATION
  blobs contain zotero.org/groups/<id>/items/<KEY>). If the Zotero tools error or the item is
  absent, fall back to the web mirror chain. If the item exists in Zotero WITHOUT an attached PDF,
  verify existence/metadata there and the quote via the web.`
  : `SCHOLARSHIP: the Zotero library is unavailable this run — verify articles/books via the open-web
  mirror chain (repository copy over SSRN; Google Books / archive.org snippet search for book quotes).`

const verifyPrompt = (b) => `You are a cite-checker verifying ONE source that a law-review draft
relies on. Fetch it ONCE and check every quotation the draft pins to it. ${b.quotes.length} quote(s)
hang on this source, so a single fetch settles all of them.

SOURCE (as resolved from the draft's footnotes by an earlier pass — it may be paraphrased or wrong;
the draft's own footnote text, which you can fetch with the prepare command below, is the ONLY
authoritative record of what the draft says): ${b.source}
KIND: ${b.kind}${b.manuscript ? '  [MANUSCRIPT — run the version-drift check]' : ''}${b.syllabus ? '  [SYLLABUS pincite present — see syllabus rule]' : ''}
SOURCE-BUNDLE KEY (echo it back exactly): ${b.key}

QUOTES TO CHECK (echo each id exactly):
${b.quotes.map((q) => `  [id ${q.id}]${q.syllabus ? ' [syllabus pincite]' : ''} @ ${q.pincite || '(no pincite)'} — "${q.quote}"`).join('\n')}

HOW TO FETCH (stop after ${MIRROR_CAP} attempts; then mark remaining quotes "unverifiable" with the
unlock path — do NOT keep retrying):
- CASE: CourtListener HTML opinion, or CAP static HTML / LOC bound-volume PDF for official star
  pagination. For a SYLLABUS pincite (first page of a U.S. cite) you MUST use the LOC bound volume —
  CourtListener has no syllabus text. Check caption spelling, year, court; each quote verbatim; each
  pincite's plausibility (best-effort — if there is no star pagination, say "pincite unverifiable",
  never guess a page).
- STATUTE/RULE: uscode.house.gov / LII / official source; verify the operative text verbatim.
- ${zoteroHint.trim()}
- MANUSCRIPT (working paper / forthcoming / SSRN / slip op.): verify the quote against the CURRENT
  public version. If a quoted passage is ABSENT or MOVED in the current version, set the quote's
  verdict "superseded_source" and fill versionDrift with the current revision date and the new
  location/wording — this is distinct from a misquote and means "re-pull and re-pin every cite to
  this source." Slip op. that has since gained U.S. Reports pagination: note the conversion.
- INTERNET: the URL must actually resolve (a dead link is a hallucination-grade error) and the page
  must support the proposition. Dead link -> try archive.org and report the archived URL in
  urlFinding. SSRN/bepress 403s are bot-blocks, not dead — mark "bot-blocked but presumptively live".

${DETERMINISTIC_CHECK}

PER-QUOTE VERDICTS (see the discipline rules below — apply them strictly):
- verbatim: matches the source word-for-word.
- altered_marked: differs only by HONESTLY marked alterations (brackets/ellipses/capitalization) that
  map faithfully to the source.
- fragment_framing: a verbatim fragment carried by the draft's own framing verb — check framing
  fidelity against the quote's body sentence, NOT sentence identity. (You will be told the sentence
  if one exists; if you need it, run: python3 "${PREPARE}" "${EXTRACT_PATH}" --ids <id> <id+1>.)
- mismatch: the quoted language genuinely differs from the source in a way that changes meaning, AND
  you have read the actual source text (fill sourceText). HIGH severity.
- syllabus_quote: the quote is verbatim but taken from the SYLLABUS/front matter — accurate yet
  should be replaced with the opinion's own language (suggest it in note). HIGH severity.
- not_found_in_sources: you searched every source the footnote names and the quote is in none of
  them. This is NOT "fabricated." HIGH severity, but say exactly which sources you searched.
- pincite_off: quote is verbatim but sits on a different page than cited (give both). MEDIUM.
- unverifiable: could not fetch/read the source — give the unlock path. Never guess.
Set severity honestly; fill sourceText for every high-severity verdict; report basis per verdict.
Collect citation-metadata problems (reporter typo, wrong volume/page/year/court, author/title/journal
discrepancy, impossible pincite) in metadataFindings. EVIDENCE TAG (2026-10-19): end EVERY
metadataFindings line with "[source: <the URL, Zotero key or record you actually read>]" — the fetched
full text you verified the quotes against counts, and is usually the right tag. A line without a
non-empty tag is treated as unevidenced and reaches the report only as "confirm …", never as a fix.
Bibliographic corrections (author name or order, volume, first page, year, title, edition) rest on the
source's OWN record (its first page, the journal's page, a catalog record), never on search snippets,
URL slugs, casebooks, syllabi or other articles' footnotes; companion / multi-part articles rotate
author order and volume between parts, so match the exact part the draft cites.

METADATA-FINDING DISCIPLINE (violations of each caused false report findings in a real run):
- Before alleging a caption/name/metadata error IN THE DRAFT, fetch the draft's actual footnote via
  python3 "${PREPARE}" "${EXTRACT_PATH}" --ids <id> <id+1> and quote the offending draft language
  VERBATIM in the finding. If the alleged error does not appear in the footnote text, the error is in
  the resolved SOURCE line above, not the draft — report nothing. A citation with no case name is
  proper form when the case is named in the body text (the unit's sentence field shows it).
- Pincite checks: identify the source's page-marker convention BEFORE assigning pages. Star/embedded
  markers (*259, official reporter transcriptions) mean the page STARTS at the marker — text after
  *N is on page N. Journal PDFs number pages in the FOOTER — text ABOVE the number is on that page,
  so in linear extracted text everything AFTER footer "1190" is on 1191. (A real run applied star
  logic to a footer-numbered PDF and "corrected" two accurate pincites to one page too low.) State
  which convention you used. If you cannot tell, or your proposed correction is off-by-exactly-one,
  report it as "possible off-by-one — confirm marker convention", never as a confident correction.

${CALIBRATION}
${SOURCES}`

// Tail batch prompt for the degraded (single-quote long-tail) sources.
const tailPrompt = (chunk) => `You are a cite-checker doing a QUICK verbatim check on several
single-quote sources a law-review draft cites (budget mode — one fetch each, be efficient).
For EACH, fetch the source once (${MIRROR_CAP} attempts max), check the one quote, and return a
verdict per the schema. Echo each sourceKey and each quote id exactly.

SOURCES:
${chunk.map((b) => `- key ${b.key} | ${b.kind} | ${b.source}\n    [id ${b.quotes[0].id}] @ ${b.quotes[0].pincite || '(no pincite)'} — "${b.quotes[0].quote}"`).join('\n')}

${DETERMINISTIC_CHECK}

${CALIBRATION}
${SOURCES}`

const verifyAgent = (b) => agent(verifyPrompt(b), {
  label: `verify:${(b.source || b.key).slice(0, 44)}`,
  phase: 'Verify',
  schema: VERIFY_SCHEMA,
  model: VERIFY_MODEL,
  effort: DEEP ? 'medium' : 'low',
})
// A dead verify agent would silently leave every quote on that source unchecked: retry once.
const verifyJobs = verifyBundles.map((b) => async () => {
  let r = await verifyAgent(b)
  if (!r) { log(`verify:${b.key} died — retrying once`); r = await verifyAgent(b) }
  return r
})
// Degraded long-tail: chunk single-quote sources VERIFY_CHUNK at a time.
const light = verifyBundles._light || []
for (let i = 0; i < light.length; i += VERIFY_CHUNK) {
  const chunk = light.slice(i, i + VERIFY_CHUNK)
  verifyJobs.push(() => agent(tailPrompt(chunk), {
    label: `verify-tail:${i}`,
    phase: 'Verify',
    // the tail schema is the same shape but one object per source; ask for an array wrapper
    schema: { type: 'object', required: ['sources'], properties: { sources: { type: 'array', items: VERIFY_SCHEMA } } },
    model: VERIFY_MODEL,
    effort: 'low',
  }).then((o) => o && o.sources ? { _multi: o.sources } : o))
}

const verifyRaw = await parallel(verifyJobs)
// Flatten (tail batches return {_multi:[...]}).
const verifyResults = []
for (const v of verifyRaw.filter(Boolean)) {
  if (v._multi) verifyResults.push(...v._multi)
  else verifyResults.push(v)
}

// Flatten to per-quote findings keyed by unit id, joined back to resolution + bundle.
const findings = []
const bundleByKey = new Map(bundleList.map((b) => [b.key, b]))
for (const v of verifyResults) {
  const b = bundleByKey.get(v.sourceKey)
  for (const q of (v.verdicts || [])) {
    const res = resById.get(q.id)
    findings.push({
      id: q.id,
      footnote: res ? res.footnote : undefined,
      source: (res && res.source) || (v.sourceIdentified) || (b && b.source) || '',
      sourceIdentified: v.sourceIdentified || '',
      verdict: q.verdict,
      severity: q.severity || (['mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source'].includes(q.verdict) ? 'high' : q.verdict === 'pincite_off' ? 'medium' : 'low'),
      sourceText: q.sourceText || '',
      pinciteFinding: q.pinciteFinding || '',
      basis: q.basis || v.fetchBasis || '',
      note: q.note || '',
      metadataFindings: v.metadataFindings || [],
      versionDrift: v.versionDrift || '',
      urlFinding: v.urlFinding || '',
    })
  }
}
// Attach footnote numbers via the resolution units (segment echoed ids).
// (footnote already set above where res was found.)
const highSev = findings.filter((f) => f.severity === 'high')
// Resolved quotes that no verify agent returned a verdict for (dead agent after retry, or a
// verdict list that skipped ids). Disclosed in the report as NOT CHECKED, never dropped.
const verdictIds = new Set(findings.map((f) => f.id))
const unverifiedUnits = resolutions.filter((r) => !verdictIds.has(r.id))
if (unverifiedUnits.length) degradation.push(`${unverifiedUnits.length} resolved quote(s) got no verdict from the verify pass (agent failure or skipped ids) — listed as NOT CHECKED`)
log(`Verified ${findings.length} quotes across ${verifyResults.length} sources; ${highSev.length} high-severity findings to re-verify${unverifiedUnits.length ? `; ${unverifiedUnits.length} quotes got no verdict` : ''}.`)

// ===========================================================================
// Phase 4 — VERIFY-THE-VERIFIER (mandatory; the anti-artifact gate)
// ===========================================================================
phase('Re-verify')
const reverifyPrompt = (f) => `You are the SECOND, independent check on a HIGH-SEVERITY cite-check
finding. Five of the six gravest findings in the practice run were checker ARTIFACTS, not draft
errors — your job is to catch that before it reaches the report. Re-derive the verdict from the FULL
context; do not defer to the first checker.

STEP 1 — load the full unit (home footnote, body sentence, Id.-chain antecedents, supra targets):
  python3 "${PREPARE}" "${EXTRACT_PATH}" --ids ${f.id} ${f.id + 1}

FIRST CHECKER SAID: verdict "${f.verdict}" — ${f.note || '(no note)'}
Source it read: ${f.sourceIdentified || f.source}
Source text it reported: ${f.sourceText ? `"${f.sourceText}"` : '(none reported)'}

STEP 2 — independently determine the truth, checking specifically for these artifact classes:
- TRUNCATION: does the FULL home_note name a source (in a parenthetical or "see also") that the first
  checker did NOT search? If the quote is verbatim in a source the note actually cites, the finding
  is an artifact — verdict is verbatim/altered_marked, upheld=false. "Fabricated/not-found" REQUIRES
  that every named source was searched.
- MISSING FRAMING: is this a verbatim FRAGMENT the draft carries with its own framing verb (see the
  body sentence)? Then it is fragment_framing (legitimate), upheld=false — not a meaning-reversal.
- WRONG ANTECEDENT: did the first checker attach a bare "Id." to a "see also" cite instead of the
  real antecedent? Re-resolve using the antecedents/supra_targets and re-check against the RIGHT
  source. If verbatim there, upheld=false.
- SYLLABUS: is the pincite the first page of a U.S. cite? Then a "silent splice" vs. opinion text is
  wrong — check the LOC bound-volume syllabus. If verbatim in the syllabus, verdict syllabus_quote
  (a real but different finding), and note the opinion's equivalent language if you can find it.
Open the source yourself (${MIRROR_CAP} attempts max) to confirm. If the original finding holds after
all this, upheld=true and restate it with the source text. Fill sourceText whenever you read it.

${DETERMINISTIC_CHECK}

${CALIBRATION}
${SOURCES}`

let reverified = new Map()
if (highSev.length && !tight(highSev.length * 6000)) {
  const outs = await parallel(highSev.map((f) => () =>
    agent(reverifyPrompt(f), {
      label: `re-verify:n.${f.footnote ?? '?'}#${f.id}`,
      phase: 'Re-verify',
      schema: REVERIFY_SCHEMA,
      model: REVERIFY_MODEL,
      effort: 'medium',
    })
  ))
  for (const o of outs.filter(Boolean)) reverified.set(o.id, o)
  const flipped = [...reverified.values()].filter((r) => r.upheld === false).length
  const lost = highSev.filter((f) => !reverified.has(f.id)).length
  if (lost) degradation.push(`${lost} high-severity finding(s) got no re-verify verdict (agent failure) — flagged as single-checker`)
  log(`Re-verify complete: ${reverified.size} high-severity findings re-derived, ${flipped} were checker artifacts (corrected)${lost ? `; ${lost} not re-verified` : ''}.`)
} else if (highSev.length) {
  degradation.push(`verify-the-verifier skipped for ${highSev.length} findings (budget) — flagged as single-checker`)
  log(`Budget tight — verify-the-verifier skipped; high-severity findings flagged single-checker.`)
}

// Apply re-verify results: replace verdict/severity, mark artifacts.
for (const f of findings) {
  const rv = reverified.get(f.id)
  if (!rv) continue
  f.reverified = true
  f.artifact = rv.upheld === false
  f.verdict = rv.verdict
  f.severity = rv.severity || f.severity
  if (rv.sourceText) f.sourceText = rv.sourceText
  f.reverifyReason = rv.reason || ''
}

// ===========================================================================
// Citation-instance LEDGER JOIN — mirror of citation_ledger.assign_dispositions()
// (the Python function is the reference implementation and is what the test covers;
// keep the two in step). Every instance ends with a disposition `d`:
//   verified | finding | existence-only | unverifiable | unchecked | xref | unresolved-xref | not-a-citation
// ===========================================================================
const XREF_KINDS = new Set(['id', 'supra', 'case-short'])
const VERIFIED_V = new Set(['verbatim', 'altered_marked', 'fragment_framing'])
const FINDING_V = new Set(['mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source', 'pincite_off'])
const caseExist = new Map(existence.map((e) => [norm(e.citation), e]))
const secExist = new Map(secondaryExistence.map((s) => [s.key, s]))
const ledgerByNote = new Map()
for (const x of LEDGER) { if (!ledgerByNote.has(x.n)) ledgerByNote.set(x.n, []); ledgerByNote.get(x.n).push(x) }
const substantive = (x) => !XREF_KINDS.has(x.k) && x.k !== 'text' && x.k !== 'internal'
// quote verdicts -> instances: (1) same source key, preferring the quote's own note, then the
// nearest earlier note (an Id.-chain quote resolves to its antecedent's instance); (2) the
// note's only substantive instance; (3) prefix match on the verbatim citation text.
const instVerdicts = new Map()
for (const f of findings) {
  if (f.artifact) continue
  const res = resById.get(f.id)
  const src = (res && res.source) || f.source || ''
  const k = sourceKey(src)
  const note = f.footnote
  let hit = null
  const byKey = LEDGER.filter((x) => substantive(x) && x.key === k)
  if (byKey.length) {
    hit = byKey.find((x) => x.n === note) ||
      byKey.filter((x) => note == null || x.n <= note).sort((a, b) => b.n - a.n)[0] || byKey[0]
  }
  if (!hit && note != null) {
    const subs = (ledgerByNote.get(note) || []).filter(substantive)
    if (subs.length === 1) hit = subs[0]
  }
  if (!hit && note != null) {
    const s40 = norm(src).slice(0, 40)
    hit = (ledgerByNote.get(note) || []).find((x) => s40 && norm(x.c).startsWith(s40)) || null
  }
  if (!hit) continue
  if (!instVerdicts.has(hit.i)) instVerdicts.set(hit.i, [])
  instVerdicts.get(hit.i).push(f.verdict)
}
for (const x of LEDGER) {
  const vs = instVerdicts.get(x.i) || []
  if (x.k === 'text') { x.d = 'not-a-citation'; continue }
  if (x.k === 'internal') { x.d = 'internal-ref'; continue }
  if (XREF_KINDS.has(x.k)) {
    x.d = x.xs === 'resolved' ? 'xref' : 'unresolved-xref'
    if (vs.some((v) => FINDING_V.has(v))) x.d = 'finding'
    continue
  }
  const ex = x.k === 'case' ? (x.case ? caseExist.get(norm(x.case)) : undefined) : secExist.get(x.key)
  const ran = x.k === 'case' ? casePassRan : secondaryPassRan
  let exists = null
  if (ex) exists = ex.exists === true ? true : (ex.exists === false && ex.basis !== 'unconfirmed' ? false : null)
  if (vs.some((v) => FINDING_V.has(v)) || exists === false) x.d = 'finding'
  else if (vs.some((v) => VERIFIED_V.has(v))) x.d = 'verified'
  else if (vs.length && vs.every((v) => v === 'unverifiable')) x.d = 'unverifiable'
  else if (exists === true) x.d = 'existence-only'
  else if (ex) x.d = 'unverifiable'
  else x.d = ran ? 'unchecked' : 'unchecked'
  if (x.d === 'unchecked') x.why = ran ? 'not reached by any pass' : 'existence pass skipped (budget)'
}
const ledgerCounts = {}
for (const x of LEDGER) ledgerCounts[x.d] = (ledgerCounts[x.d] || 0) + 1
const ledgerLine = (x) => `- n.${x.n} [${x.k}] ${x.c.slice(0, 140)}${x.why ? ` — ${x.why}` : ''}`
log(`Ledger: ${LEDGER.length} citation instances — ${JSON.stringify(ledgerCounts)}`)

// ===========================================================================
// Phase 4b — FORM (Bluebook typeface + short forms; no external sources)
// ===========================================================================
// Cheap and self-contained: the deterministic findings are already computed, so
// this phase spends ONE agent, and only when there is a formatting layer and a
// case-name judgment to make. Everything else ships as-is. Runs after re-verify
// so it never competes with the verification stages for budget.
phase('Form')
const FORM_SCHEMA = {
  type: 'object',
  required: ['findings'],
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        required: ['location', 'find', 'problem', 'fix'],
        properties: {
          location: { type: 'string', description: 'n.45 or ¶123' },
          find: { type: 'string', description: 'VERBATIM draft text, NO <i>/<sc> tags' },
          problem: { type: 'string' },
          fix: { type: 'string' },
          rule: { type: 'string', description: 'the Bluebook rule, e.g. "R. 2.1(a)"' },
        },
      },
    },
    conventions: {
      type: 'array',
      items: {
        type: 'object',
        required: ['issue', 'recommendation'],
        properties: {
          issue: { type: 'string' }, dominant: { type: 'string' },
          minority: { type: 'string' }, recommendation: { type: 'string' },
        },
      },
    },
  },
}
let formAgentFindings = []
let formAgentConventions = []
if (FORM_FMT_OK && FORM_CANDIDATES.length && !tight(RESERVE_REPORT + 15_000)) {
  const fr = await agent(
    `You are settling CASE-NAME TYPEFACE questions in the law review draft "${DRAFT_NAME}".

Bluebook R. 2.1(a) for law review FOOTNOTES (not the Bluepages practitioner rule, which
italicizes case names everywhere):
- ROMAN: a case name in a FULL citation standing in a citation clause or citation sentence
  ("See Knowlton v. Moore, 178 U.S. 41, 106 (1900).").
- ITALIC: a case name in a TEXTUAL sentence — including a textual sentence inside a
  footnote ("Flint relied on Veazie Bank v. Fenno, 75 U.S. 533 (1869)") — and any
  SHORT-FORM case name ("Hylton, 3 U.S. at 174").
The full rule statement with worked examples:
${SKILLS}/legal-research/bluebook-typeface-and-short-forms.md — Read it first.

A deterministic pass flagged the case names below as departing from the expectation for the
position it THINKS they occupy. That positional guess is fallible — it mistakes textual
sentences for citation clauses. For each one, Grep its location label in ${FORM_FMT_PATH}
(same line structure as the draft: [¶n] body paragraphs, [n.n] footnotes, with <i>italic</i>
and <sc>small caps</sc> marked) and READ THE SENTENCE AROUND IT. Report a finding ONLY where
the typeface is genuinely wrong for the position the name actually occupies.

REJECTING CANDIDATES IS THE EXPECTED OUTCOME for some of them — simply omit those. Do not
pad the list, and do not report a name merely because the script nominated it.

While you are in the file, you MAY add typeface findings the script cannot model: the same
source set two ways in different footnotes, small caps covering only part of a name, or a
stretch of body text left italic from an earlier edit. Cap those at 8 and keep them concrete.

CRITICAL: the <i>/<sc> tags are NOT in the author's document. Every "find" string must be
the text with all tags REMOVED so it is Cmd+F-able in Word. Name the rule in each finding.

CANDIDATES:
${JSON.stringify(FORM_CANDIDATES, null, 1)}

DRAFT-WIDE COUNTS (how the draft actually sets case names in each position):
${JSON.stringify(FORM.case_name_counts || {}, null, 1)}`,
    { schema: FORM_SCHEMA, phase: 'Form', model: VERIFY_MODEL, effort: DEEP ? 'medium' : 'low' })
  formAgentFindings = fr?.findings || []
  formAgentConventions = fr?.conventions || []
} else if (FORM_FMT_OK && FORM_CANDIDATES.length) {
  degradation.push('budget: case-name typeface candidates shipped unadjudicated')
}
const formConventions = [...(FORM.conventions || []), ...formAgentConventions]
const formLoc = (l) => (l && l.where === 'footnote' ? `n.${l.note}` : `¶${l && l.para}`)
const formAll = [
  ...FORM_FINDINGS.map((f) => ({
    location: formLoc(f.location), find: f.find, problem: f.problem, fix: f.fix,
    kind: f.rule === 'cite-short-form' ? 'short-form' : 'typeface',
  })),
  ...formAgentFindings.map((f) => ({
    location: f.location, find: f.find, problem: f.problem, fix: f.fix,
    kind: 'typeface', rule: f.rule,
  })),
]
log(`form: ${formAll.length} findings (${formAll.filter((f) => f.kind === 'short-form').length} short-form, ${formAll.filter((f) => f.kind === 'typeface').length} typeface), ${formConventions.length} conventions`)

// ===========================================================================
// Phase 5 — REPORT (session model; assembles the graded report)
// ===========================================================================
phase('Report')
const bySeverity = (s) => findings.filter((f) => f.severity === s && !f.artifact)
const counts = {
  quotesChecked: findings.length,
  verbatim: findings.filter((f) => f.verdict === 'verbatim').length,
  alteredMarked: findings.filter((f) => f.verdict === 'altered_marked' || f.verdict === 'fragment_framing').length,
  mismatch: findings.filter((f) => ['mismatch', 'not_found_in_sources'].includes(f.verdict) && !f.artifact).length,
  syllabus: findings.filter((f) => f.verdict === 'syllabus_quote' && !f.artifact).length,
  superseded: findings.filter((f) => f.verdict === 'superseded_source' && !f.artifact).length,
  pinciteOff: findings.filter((f) => f.verdict === 'pincite_off').length,
  unverifiable: findings.filter((f) => f.verdict === 'unverifiable').length,
  artifactsCaught: findings.filter((f) => f.artifact).length,
  quotesNotChecked: unresolvedIds.length + unverifiedUnits.length,
  highSeveritySingleChecker: findings.filter((f) => f.severity === 'high' && !f.artifact && !f.reverified).length,
  casesChecked: existence.length,
  casesUnconfirmed: existBad.length,
  reporterTypos: existFixed.length,
  supraBreaks: SUPRA_PROBLEMS.length,
  formShortForm: formAll.filter((f) => f.kind === 'short-form').length,
  formTypeface: formAll.filter((f) => f.kind === 'typeface').length,
  ledgerInstances: LEDGER.length,
  ledger: ledgerCounts,
  secondaryChecked: secondaryExistence.length,
  secondaryNotFound: secBad.length,
}

const fmtFinding = (f) => {
  const q = resById.get(f.id)
  return `- n.${f.footnote ?? '?'} [${f.verdict}${f.severity === 'high' ? ', HIGH' : ''}${f.severity === 'high' && !f.reverified ? ', SINGLE-CHECKER — not re-verified' : ''}] ` +
    `source: ${f.sourceIdentified || f.source}` +
    (q ? `\n    draft quote: "${(q.quote || '').slice(0, 240)}"` : '') +
    (f.sourceText ? `\n    source text: "${f.sourceText.slice(0, 280)}"` : '') +
    (f.pinciteFinding ? `\n    pincite: ${f.pinciteFinding}` : '') +
    (f.versionDrift ? `\n    version-drift: ${f.versionDrift}` : '') +
    (f.note ? `\n    note: ${f.note}` : '') +
    (f.reverifyReason ? `\n    re-verify: ${f.reverifyReason}` : '') +
    `\n    basis: ${f.basis || 'unstated'}`
}

const metaFindingsFlat = [...new Set(verifyResults.flatMap((v) => v.metadataFindings || []))]
// Same evidence gate as the existence pass: a verify agent's metadata correction is a fix only
// when it names the record it read; untagged lines are "confirm" items.
const metaFindingsEvidenced = metaFindingsFlat.filter((m) => EVIDENCED.test(m))
const metaFindingsSoft = metaFindingsFlat.filter((m) => !EVIDENCED.test(m))
const urlFindings = verifyResults.map((v) => v.urlFinding).filter(Boolean)
const supraReport = SUPRA_PROBLEMS.map((s) => `- n.${s.footnote}: "${s.claims}, supra note ${s.supra_note}" — target note ${s.supra_note} does not name ${s.claims} (holds: "${(s.target_excerpt || '').slice(0, 90)}…")`).join('\n')

const report = await must('Report', () => agent(
  `You are assembling the final cite-check report for a law professor's article draft ("${DRAFT_NAME}",
${FOOTNOTE_COUNT} footnotes). Write it in Markdown, in the professor's own report style: a decisive
TL;DR line with counts, then findings ordered by how much they would hurt IN PRINT, each with the
draft's text and the source's actual text side by side, keyed to footnote numbers. Be direct and
substantive; this reader is sophisticated. Do NOT invent anything — use only the findings below.

REPORT STRUCTURE (adapt section letters as the findings warrant; omit empty sections):
- Title + TL;DR: "${FOOTNOTE_COUNT} footnotes swept" and the counts (verbatim / marked-alteration /
  mismatch / unverifiable; case cites checked; broken supras; pincite/metadata issues). State the
  verification basis honestly (everything rests on a fetched source; nothing judged from memory).
- **A. Needs your attention first** — the HIGH-severity findings (mismatches, not-found, syllabus
  quotes, superseded-source), each with draft text vs. source text and the fix. These are the ones
  that would embarrass in print.
- **B. Verbatim slips (smaller)** — real but minor (a dropped word, a spelling, an unmarked comma).
- **C. Broken supra references** — from the deterministic supra check below (a renumbering artifact).
- **D. Wrong pincites & citation typos** — reporter typos, impossible pincites, off-by-some pincites.
- **E. Article/book metadata discrepancies** — wrong volume/year/journal/author/title. Two
  sub-lists: "Errors (fix)" holds ONLY discrepancies an agent (existence or verify) evidenced
  against the source's own record — the lines listed below as EVIDENCED, each tagged "[source: …]";
  every line listed below as UNEVIDENCED goes under "Confirm" and is phrased as something to check,
  not something wrong. Author-order claims never go in "Errors (fix)" without that tag (companion/
  multi-part articles rotate author order between parts).
- **F. URLs** — dead links (with archived replacements) and bot-blocked-but-live notes.
- **G. Couldn't check (what would unlock each)** — unverifiable items, each with its unlock path
  (Hein/JSTOR pull, add PDF to Zotero, physical copy).
- **H. Citation coverage ledger** — REQUIRED, from the ledger block below: what every citation
  instance got, and above all what did NOT get checked.
- A short method note: deterministic extraction + supra/existence checks; quotes verified by agents
  against fetched sources; a mandatory verify-the-verifier pass on high-severity findings; free/
  open-web sources only, so a Westlaw/Lexis + manual Bluebook pass is still recommended. State
  the coverage limits plainly: every citation instance is inventoried in section H; quoted
  passages were verified against fetched text; case cites and unquoted secondary sources were
  existence/metadata-checked ONLY — whether an unquoted cite actually supports its proposition
  was NOT assessed.

CRITICAL — do not resurrect checker artifacts: ${counts.artifactsCaught} high-severity findings were
re-derived and found to be CHECKER ARTIFACTS (verbatim after all). They are EXCLUDED from the
findings below. Do not mention them as problems.

REPORT DISCIPLINE (each rule below is standing feedback from the professor on a real report):
- FINDINGS ONLY. Never include items you checked and cleared ("Confirmed clean, for the record:
  …"), near-findings you talked yourself out of ("plausible abbreviation, not an error"), or any
  other visible deliberation. If it needs no action, it does not appear. The TL;DR counts already
  convey how much was checked and passed.
- Every finding must carry a verbatim Cmd+F-able find-string copied from the DRAFT (the draft
  quote / footnote text in the findings data). If you cannot key a finding to language actually in
  the draft, that finding is by construction a checker artifact — drop it, don't paper over it.
- A footnote citation with no case name is NOT a finding when the case is named in the accompanying
  text (proper Bluebook form). Do not tell the author to "supply the case name" for these.
- For unconfirmed case cites that are merely too recent for free indexes (see their notes), say
  "likely correct — reporter page too recent for free sources; spot-check on Westlaw", not language
  implying the cite is suspect.
- A high-severity finding marked SINGLE-CHECKER was not re-derived by the second check (budget or
  agent failure). Keep it in section A but say in its line that it rests on one checker and should
  be confirmed against the source before acting.
- QUOTES NOT CHECKED (listed below, if any) are quotes the run never verified because an agent
  failed. They are not findings; list them in section G as "not checked this run — re-run", by
  footnote, so the author knows the gap.

COUNTS: ${JSON.stringify(counts)}

=== HIGH-SEVERITY FINDINGS (section A) ===
${bySeverity('high').map(fmtFinding).join('\n') || '(none)'}

=== MEDIUM/LOW FINDINGS (sections B/D — verbatim slips, pincites) ===
${findings.filter((f) => f.severity !== 'high' && !f.artifact && !['verbatim', 'altered_marked', 'fragment_framing'].includes(f.verdict)).map(fmtFinding).join('\n') || '(none)'}

=== CITATION-METADATA FINDINGS — EVIDENCED (sections D/E; from the verify agents, each tagged with the record read) ===
${metaFindingsEvidenced.map((m) => `- ${m}`).join('\n') || '(none)'}
=== CITATION-METADATA FINDINGS — UNEVIDENCED (sections D/E "Confirm" ONLY — no record tagged; phrase each as "confirm …", never as a correction) ===
${metaFindingsSoft.map((m) => `- ${m}`).join('\n') || '(none)'}

=== BROKEN SUPRA REFERENCES (section C) — deterministic, high-confidence ===
${supraReport || '(none)'}

=== CASE EXISTENCE ===
- ${counts.casesChecked} case cites checked; ${counts.casesUnconfirmed} unconfirmed; reporter typos: ${existFixed.map((e) => `${e.citation} -> ${e.corrected}`).join('; ') || 'none'}.
${existBad.map((e) => `- UNCONFIRMED: ${e.citation} — ${e.note || ''}`).join('\n')}

=== URL FINDINGS (section F) ===
${urlFindings.map((u) => `- ${u}`).join('\n') || '(none)'}

=== UNVERIFIABLE (section G) ===
${findings.filter((f) => f.verdict === 'unverifiable').map(fmtFinding).join('\n') || '(none)'}

=== QUOTES NOT CHECKED — agent failure, not a finding (section G; list by footnote) ===
${[...unresolvedIds.map((i) => `- n.${UNIT_NOTES.get(i) ?? '?'} unit ${i} — no source resolution`), ...unverifiedUnits.map((r) => `- n.${r.footnote ?? '?'} unit ${r.id} — no verdict: "${(r.quote || '').slice(0, 120)}"`)].join('\n') || '(none)'}

=== SECONDARY-SOURCE EXISTENCE (sections E/G) ===
${secondaryExistence.length}/${SECONDARY_CITES.length} unique unquoted secondary sources existence-checked${secondaryPassRan ? '' : ' — PASS SKIPPED (budget); list them as UNCHECKED in section H'}.
NOT FOUND (draft cites a source no catalog/site could locate — section E, phrase as "not found in the sources checked"):
${secBad.map((s) => `- key ${s.key}: ${s.note || ''}`).join('\n') || '(none)'}
UNCONFIRMED (section G, with what would unlock each):
${secUnconfirmed.map((s) => `- key ${s.key}: ${s.note || ''}`).join('\n') || '(none)'}
METADATA DISCREPANCIES — EVIDENCED (section E "Errors (fix)"; from the existence agents, each line names the source record the agent opened):
${secMeta.map((m) => `- ${m}`).join('\n') || '(none)'}
METADATA DISCREPANCIES — UNEVIDENCED (section E "Confirm" ONLY — untagged findings and "confirm: …" notes, derived from search snippets or third-party listings, never from the source's own page; phrase each as "confirm …", never as a correction, and never promote one to the TL;DR):
${secMetaSoft.map((m) => `- ${m}`).join('\n') || '(none)'}

=== CITATION COVERAGE LEDGER (section H — REQUIRED; place it AFTER section G and BEFORE Citation form) ===
${LEDGER.length} citation instances inventoried across ${FOOTNOTE_COUNT} footnotes. Dispositions: ${JSON.stringify(ledgerCounts)}.
Write section H as: (1) one sentence with the counts; (2) one plain sentence that "existence-only"
instances were confirmed to exist but were NOT read for whether they support the proposition they
are cited for, and that "xref" instances (Id./supra/short forms) inherit their antecedent's status;
(3) the three lists below, each item as "n.N — cite text", so the author can see exactly what was
not checked. An empty list is written as "none". Do not pad, do not summarize the lists away.
UNCHECKED (no pass reached them):
${LEDGER.filter((x) => x.d === 'unchecked').map(ledgerLine).join('\n') || '(none)'}
UNVERIFIABLE (existence could not be confirmed from free sources; quote-level unverifiables are already in section G):
${LEDGER.filter((x) => x.d === 'unverifiable').map(ledgerLine).join('\n') || '(none)'}
UNRESOLVED CROSS-REFERENCES (Id./supra/short form with no findable antecedent — usually a renumbering break; overlaps section C where the deterministic supra check also fired):
${LEDGER.filter((x) => x.d === 'unresolved-xref').map(ledgerLine).join('\n') || '(none)'}

=== CITATION FORM (own section, AFTER the substance sections) ===
These are Bluebook FORM problems decided from the draft alone — no source was consulted and
none was needed. Give them their own "Citation form" section near the END of the report,
split into "Short forms" and "Typeface", one line each: location — \`verbatim find string\` —
problem — fix. Open the section with one sentence stating the governing rules so the authors
can check the calls: a case may be short-cited if it was cited in full in the same footnote
or one of the preceding FIVE footnotes (R. 10.9); a secondary source takes "Author, supra
note N" from its second appearance onward, with no distance limit (R. 4.2); and in law
review footnotes case names are ROMAN in full citations standing in a citation clause but
ITALIC in textual sentences and short forms (R. 2.1(a)). Do NOT promote these into "Needs
your attention" — they are tidy-up, not substance${FORM_FMT_OK ? '' : '. NOTE: no formatting layer was available for this draft (plain-text input), so typeface was NOT checked — say so in one clause'}.
${JSON.stringify(formAll, null, 1)}

=== CITATION-FORM CONVENTIONS (document-wide; a short table in the same section) ===
${JSON.stringify(formConventions, null, 1)}

Return ONLY the finished report in Markdown via the report field.`,
  { schema: REPORT_SCHEMA, phase: 'Report', effort: 'high' }
))

const exitState = degradation.length
  ? 'complete_with_limits'
  : (counts.unverifiable || existBad.length || ledgerCounts.unchecked || secUnconfirmed.length ? 'complete_with_limits' : 'complete')

return {
  draftName: DRAFT_NAME,
  exitState,
  degradation,
  counts,
  artifactsCaught: findings.filter((f) => f.artifact).map((f) => ({ id: f.id, footnote: f.footnote, reason: f.reverifyReason })),
  formFindings: formAll,
  formConventions,
  ledger: LEDGER,                 // every instance with its disposition `d` — render with citation_ledger.py --render
  secondaryExistence,
  report: report.report,
}
