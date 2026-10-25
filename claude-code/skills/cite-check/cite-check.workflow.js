export const meta = {
  name: 'cite-check',
  description: 'Verify every citation and quotation in an article draft against real sources — resolve Id./supra chains, collapse to unique sources, verify verbatim, optionally read unquoted cites for proposition support, re-verify high-severity findings, and grade a footnote-by-footnote report',
  phases: [
    { title: 'Segment', detail: 'resolve each quote to the specific source it hangs on (Id./supra chains, syllabus routing)' },
    { title: 'Existence', detail: 'CourtListener existence + caption check for every case cite (name-search fallback before any web escalation), plus existence/metadata check of every unique unquoted secondary source' },
    { title: 'History', detail: 'subsequent history (docket entries after the decision + later same-litigation opinions) for every lower-court case, and a two-route adverse-treatment probe for every case' },
    { title: 'Verify', detail: 'one agent per unique source: fetch once, check every quote verbatim + pincites + metadata' },
    { title: 'Support', detail: '(opt-in) read each unquoted cite at its pincite and judge whether it supports the sentence it hangs on, through its signal' },
    { title: 'Re-verify', detail: 'mandatory verify-the-verifier pass on every high-severity finding (quote and support)' },
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
//   deep:boolean, footnotesOnly:[lo,hi]|null, zotero:boolean,
//   history:boolean (default true) — the subsequent-history / treatment pass
//   support:boolean (default FALSE — opt-in), supportUnits:[...] (prepare_support_units.py
//   --compact), supportScope:'pincited'|'all' — the proposition-support pass (2026-10-24)
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
const HISTORY_ON = A.history !== false // subsequent-history + treatment pass (2026-10-19)
// Proposition-support pass (2026-10-24) — OPT-IN. Reads every unquoted citation instance in
// scope at its pincite and judges, through its Bluebook signal, whether the source supports
// the sentence it hangs on. Off by default because it changes the cost profile from "sources
// with quotes" to "every source"; "overstated" is a CONFIRM item by the author's decision.
const SUPPORT_ON = !!A.support
const SUPPORT_SCOPE = A.supportScope === 'all' ? 'all' : 'pincited' // whole-work cites only on 'all'
const SUPPORT_UNITS = SUPPORT_ON && Array.isArray(A.supportUnits) ? A.supportUnits : []
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
const PREPARE_SUPPORT = `${SKILLS}/cite-check/scripts/prepare_support_units.py`
const CL_TOOLS = `${SKILLS}/legal-research/cl_case_tools.py`

// ---- knobs -------------------------------------------------------------------
const SEGMENT_CHUNK = 28   // quote-units per resolver agent
const EXIST_BATCH = 30     // case cites per existence agent (CL paces 60/min)
const SECONDARY_BATCH = 12 // unique secondary sources per existence/metadata agent
const HISTORY_BATCH = 8    // case cites per subsequent-history / treatment agent
const VERIFY_CHUNK = 8     // small/quoteless sources bundled per verify agent
const SUPPORT_TAIL = 5     // single-unit support sources bundled per agent under budget pressure
const PER_SUPPORT_SOURCE = 10_000 // budget estimate per dedicated support agent
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
if (SUPPORT_ON) SOFT_CAP += 350_000       // the support pass reads sources the quote pass never fetched
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
  "unverifiable" with the unlock path — never assume, never "fabricated."
- Opinions, articles and dockets that POSTDATE your training data are real. A 2025 or 2026
  decision you do not recognize is not a hallucination signal; CourtListener and the open web
  are the record, your recall is not.`

// Proposition-support judgment rules (opt-in pass, 2026-10-24). Hardwired into the fold-in
// block, the dedicated support agents and the support re-verify agent, so the three cannot
// apply different tests. "Overstated" is a CONFIRM item by the author's decision.
const SUPPORT_RULES = `WHAT THE DRAFT CLAIMS. Each unit carries the body sentence its footnote marker sits in
(anchor.sentence); when the marker is MID-SENTENCE, anchor.clause (the text before the marker)
is the claim, not the whole sentence. If the footnote's OWN prose states the proposition ("For the
contrary view, see ..."; note_prose), that governs. A proposition parenthetical ("holding that
...") says precisely what the source is cited for — check that. An opinion_note the draft itself
supplies ("Thomas, J., concurring") is the posture the draft claims: judge against that opinion.
Judge the claim in the DRAFT'S words, with its own hedges ("arguably", "has suggested"); never
substitute a stronger paraphrase and then find it unsupported.

READ THE CLAIM THROUGH THE SIGNAL (Bluebook R. 1.2) — the verdict is relative to it:
- (no signal) / see / see, e.g. / accord — the source directly states or clearly implies the
  proposition. "e.g." means others do too; check only this one.
- see also — additional support; same test.
- cf. — the source supports a DIFFERENT proposition that is analogous; the question is whether
  the analogy is fair, never whether the source says the sentence.
- compare ... with — a comparison; each side is its own unit (signal "compare" for the first
  authority, "compare with" for the second); the question is whether that side says what the
  comparison implies about it, read with the other side in view (same footnote).
- see generally — background; supported if the source treats the topic at the level the draft
  suggests. NEVER not_supported merely because the page does not state the sentence.
- but see / but cf. / contra — cited as CONTRARY authority; the test is whether it actually
  contradicts (cf.: is contrary by analogy to) the proposition. A "but see" source that does NOT
  contradict the sentence is not_supported (the cite fails its job) — never "contradicted".

VERDICTS (one per unit):
- supported — at the pincite (or, for a whole-work cite, in the work's holding/argument) the
  source says what the draft cites it for, through the signal.
- supported_qualified — supports it, but from a POSTURE the draft does not disclose: dicta, a
  concurrence or dissent, a plurality, an arguendo assumption, the syllabus, a party's argument
  the court recites, an author REPORTING someone else's view. Name the posture. Advisory.
- overstated — the source supports a NARROWER or WEAKER version: one court cited for "courts have
  uniformly held"; "may" cited for "must"; a fact-bound holding cited for a general rule. This is a
  CONFIRM item for the author, never an error: give the source's actual scope in reason and the
  passage in sourceText, so the author can decide whether to soften the sentence.
- not_supported — the pincited page (and, after a search of the source for the proposition's key
  terms, nothing nearby) does not address the proposition. Say in reason what the page DOES say.
- contradicted — the source says the OPPOSITE of what the draft cites it for, through the signal.
  Requires the FULL footnote in view and the contradicting passage verbatim in sourceText.
- unverifiable — the source could not be fetched or read; give the unlock path in reason.
- unread — a unit you deliberately did not read (whole-work scope / budget); say so.
Per unit, always fill: claim (the proposition you judged, VERBATIM from the unit — never your
paraphrase) and claimBasis (anchor.sentence / anchor.clause / parenthetical / note_prose); posture;
locator (the page you actually read; if the pincited page does not exist or holds nothing relevant,
say so); sourceText (verbatim, <= 400 chars) for every verdict except unverifiable/unread; reason
(one line, claim vs source); basis; and for not_supported / contradicted, searched (the key terms
you searched the fetched source for, and what came back).

DISCIPLINE (each rule mirrors a false finding the quote pass once produced):
- A supporting passage a page or two off the pincite is a pincite NOTE inside a supported verdict
  ("passage at 437, cited 436" in locator), not not_supported.
- not_supported and contradicted need the pincited page read AND a search of the fetched source
  for the proposition's key terms. Name what you searched.
- Pages: use the verifier's --page output, not footer/star markers by eye; if the file has no
  page boundaries, say so in locator and read a targeted excerpt instead.
- Scholarship cited for "scholars argue X": a source that reports X is supported; cited for X
  itself, a source that only REPORTS X is supported_qualified (reported view).
- Never judge from memory. Sources that postdate your training data are real. A paywall or bot
  wall means unverifiable with the unlock path, not a guess.`

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
            enum: ['verbatim', 'altered_marked', 'fragment_framing', 'mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source', 'pincite_off', 'misattributed', 'unverifiable'],
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

// Proposition-support verdicts (opt-in pass, 2026-10-24). Shared by the fold-in on a verify
// agent (the source is already on disk) and the dedicated support agents.
const SUPPORT_VERDICTS = ['supported', 'supported_qualified', 'overstated', 'not_supported', 'contradicted', 'unverifiable', 'unread']
const SUPPORT_VERDICT_ITEM = {
  type: 'object',
  required: ['id', 'verdict'],
  properties: {
    id: { type: 'integer', description: 'the support-unit id, echoed exactly' },
    verdict: { type: 'string', enum: SUPPORT_VERDICTS },
    posture: { type: 'string', description: 'what the supporting passage IS: holding / dicta / concurrence / dissent / plurality / arguendo / syllabus / party argument recited / author\'s thesis / reported view / statutory text / other' },
    locator: { type: 'string', description: 'the page/section you actually read, and any offset from the pincite ("passage at 437, cited 436")' },
    sourceText: { type: 'string', description: 'the source passage, VERBATIM (<= 400 chars) — the evidence for the verdict; required for every verdict except unverifiable/unread' },
    reason: { type: 'string', description: 'one line: what the draft claims (through its signal) vs what the source says' },
    claim: { type: 'string', description: 'the proposition you actually judged, VERBATIM from the unit (anchor.clause, anchor.sentence, the parenthetical, or the footnote\'s own prose) — never a paraphrase' },
    claimBasis: { type: 'string', enum: ['anchor.sentence', 'anchor.clause', 'parenthetical', 'note_prose'], description: 'where the claim came from' },
    searched: { type: 'string', description: 'not_supported / contradicted only: the key terms you searched the fetched source for, and what came back' },
    basis: { type: 'string', enum: ['direct-full-text', 'authoritative-reproduction', 'secondary-corroboration', 'citation-only', 'not-fetched'] },
  },
}
const SUPPORT_SCHEMA = {
  type: 'object',
  required: ['sourceKey', 'supportVerdicts'],
  properties: {
    sourceKey: { type: 'string', description: 'the source-bundle key, echoed' },
    sourceIdentified: { type: 'string', description: 'the source as you actually located and read it (URL/edition/version)' },
    fetchBasis: { type: 'string', enum: ['direct-full-text', 'authoritative-reproduction', 'secondary-corroboration', 'citation-only', 'not-fetched'] },
    supportVerdicts: { type: 'array', items: SUPPORT_VERDICT_ITEM },
  },
}
VERIFY_SCHEMA.properties.supportVerdicts = {
  type: 'array', items: SUPPORT_VERDICT_ITEM,
  description: 'ONLY when the prompt lists SUPPORT UNITS for this source: one verdict per support-unit id',
}
const SUPPORT_REVERIFY_SCHEMA = {
  type: 'object',
  required: ['id', 'upheld', 'verdict'],
  properties: {
    id: { type: 'integer' },
    upheld: { type: 'boolean', description: 'false if the first support verdict was a checker artifact' },
    verdict: { type: 'string', enum: SUPPORT_VERDICTS },
    posture: { type: 'string' },
    locator: { type: 'string' },
    sourceText: { type: 'string' },
    searched: { type: 'string', description: 'the key terms you searched the source for, and what came back' },
    reason: { type: 'string', description: 'why the original stands or was an artifact — name the artifact class (paraphrased-claim / signal-misread / wrong-antecedent / wrong-page / clause-vs-sentence / footnote-prose / posture)' },
  },
}

// verify-the-verifier: re-derive one high-severity finding from full context.
const REVERIFY_SCHEMA = {
  type: 'object',
  required: ['id', 'upheld', 'verdict'],
  properties: {
    id: { type: 'integer' },
    upheld: { type: 'boolean', description: 'false if the original high-severity verdict was a checker artifact' },
    verdict: { type: 'string', enum: ['verbatim', 'altered_marked', 'fragment_framing', 'mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source', 'pincite_off', 'misattributed', 'unverifiable'] },
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
- NOT found -> a citation that will not resolve is a SEARCH problem, never evidence of a bad cite:
  CourtListener's citation metadata is uneven (a case can be present and full-text searchable with
  no reporter citation attached), and recent U.S. Reports volumes lag. BEFORE any web search, run
  the name-search fallback, one Bash call per unresolved cite (the case name comes from the
  draft's footnote; if you were given none, use the citation alone):
    python3 "${CL_TOOLS}" find "<case name as cited>" --cite "<citation>" --year <year if known>
  It returns (a) candidates — opinions whose caption matches, with their citations, court and
  date; a candidate whose court/date/parties match the draft's cite settles existence
  (exists=true, basis "courtlistener-api", note "resolved by name search; no reporter cite on
  the CourtListener record" and carry the candidate's own citation if it differs); and (b)
  citers_of_cite — opinions whose TEXT cites the citation string: a later opinion citing
  "397 F. Supp. 3d 126" by name proves the cite is real even when the opinion itself is not in
  the index (exists=true, basis "courtlistener-api", note which citing opinion confirmed it).
  Only if both come back empty, do ONE web search ("<volume> <reporter> <page>" or the case
  name) to confirm. If it resolves, exists=true, basis "web". If the citation looks malformed
  (e.g. a volume with a digit dropped, "03 U.S. 95"), propose the corrected citation.
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
  call it fabricated; in note, list the routes you tried (lookup / name search / citation-string
  search / web).
- Opinions that postdate your training data are real; do not downgrade a 2025–2026 cite because
  you do not recognize the case.
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
// Phase 2b — SUBSEQUENT HISTORY & TREATMENT (added 2026-10-19)
// Bluebook R. 10.7 wants the subsequent history in the citation, and a case cited for current
// law may have been reversed, vacated or overruled since. Direct history is what a citation
// graph cannot see: a judgment vacated on reconsideration or reversed by a mandate often leaves
// no published opinion for a citation search to find, so the DOCKET (RECAP, federal only) is
// read for everything filed after the decision, alongside later same-litigation opinions; a
// two-route citing probe (graph + name phrase) flags adverse treatment. Advisory: findings go in
// their own report section, never in "Needs your attention", and never enter the ledger.
// ===========================================================================
phase('History')
const HISTORY_RE = /\b(aff'd|affirmed|rev'd|reversed|vacated|cert\.?\s*(denied|granted|dismissed)|overruled|abrogated|superseded|modified|reh'g|rehearing|en banc|withdrawn|amended|substituted|remanded|appeal (dismissed|docketed|filed)|petition for cert)/i
const SCOTUS_RE = /\b\d+\s+(U\.?\s?S\.?|S\.?\s?Ct\.?|L\.?\s?Ed\.?(\s?2d)?)\s+\d+/i
const existByCite = new Map(existence.map((e) => [norm(e.citation), e]))
const draftTextsFor = (cite) => {
  const k = norm(cite)
  return LEDGER.filter((x) => x.k === 'case' && x.case && norm(x.case) === k).map((x) => x.c)
}
const historyCases = CASE_CITES.map((cite) => {
  const ex = existByCite.get(norm(cite)) || {}
  const texts = draftTextsFor(cite)
  return {
    cite,
    caseName: ex.caseName || '',
    dateFiled: ex.dateFiled || '',
    exists: ex.exists !== false,
    scotus: SCOTUS_RE.test(cite),
    draftHasHistory: texts.some((t) => HISTORY_RE.test(t)),
    draftTexts: texts.slice(0, 3).map((t) => t.slice(0, 220)),
    notes: [...new Set(LEDGER.filter((x) => x.k === 'case' && x.case && norm(x.case) === norm(cite)).map((x) => x.n))].slice(0, 8),
  }
})
const HISTORY_SCHEMA = {
  type: 'object',
  required: ['cases'],
  properties: {
    cases: {
      type: 'array',
      items: {
        type: 'object',
        required: ['cite', 'status'],
        properties: {
          cite: { type: 'string', description: 'the citation, echoed exactly' },
          status: { type: 'string', enum: ['checked', 'not-resolved', 'tool-error', 'skipped'] },
          subsequentHistory: { type: 'string', description: 'the subsequent history found, in Bluebook order with cites, e.g. "aff\'d, 980 F.3d 157 (1st Cir. 2020), rev\'d, 600 U.S. 181 (2023)"; empty if none was found' },
          historyBasis: { type: 'string', enum: ['docket+opinions', 'opinions-only', 'docket-only', 'none-found', 'not-checked'], description: 'what the history rests on' },
          historyFinding: { type: 'string', description: 'ONLY when the draft\'s citation omits history you found (or states history the record contradicts): one line, quoting the draft\'s cite text and giving the history to add. Empty otherwise.' },
          treatment: { type: 'string', description: 'adverse treatment that names THIS case (overruled / abrogated / limited / declined to follow / superseded by statute), with the treating case\'s name, cite and date and the scope as far as the snippet shows ("scope unconfirmed" otherwise). Empty if none.' },
          treatmentRoutes: { type: 'string', description: 'coverage line: graph N (M with treatment language) / name-search N (K not in graph) / D distinct cases; most recent citing date' },
          coverage: { type: 'string', description: 'what was and was not checked: docket read (N entries after decision, truncated?), docket skipped (state court / no RECAP record), same-litigation opinions found, name resolution route' },
          confidence: { type: 'string', enum: ['high', 'moderate', 'low'] },
          note: { type: 'string' },
        },
      },
    },
  },
}
const historyPrompt = (batch) => `You are checking the SUBSEQUENT HISTORY and current TREATMENT of case citations in a
law-review draft, with two deterministic CourtListener tools. Bluebook R. 10.7 requires the
subsequent history of a cited decision (aff'd / rev'd / vacated / cert. denied / overruled), and a
case cited for current law must not have been reversed or overruled since. You READ tool output
and report; you do not verify quotes here and you do not assess whether the draft's proposition
is supported.

CASES (echo each cite exactly as given):
${batch.map((c) => `- cite: ${c.cite}${c.caseName ? ` | name: ${c.caseName}` : ''}${c.dateFiled ? ` | decided: ${c.dateFiled}` : ''} | ${c.scotus ? 'SUPREME COURT (no docket pass; treatment only)' : 'lower court (history + treatment)'} | draft cite text already carries history words: ${c.draftHasHistory ? 'YES' : 'no'} | cited in notes ${c.notes.join(', ') || '?'}\n    draft cite(s): ${c.draftTexts.map((t) => JSON.stringify(t)).join(' || ') || '(none captured)'}`).join('\n')}

FOR EACH CASE, via Bash (load with ToolSearch "select:Bash" if needed):
1. Lower-court cases only — subsequent history:
     python3 "${CL_TOOLS}" history "<cite>" --name "<case name>" --year <decision year>
   Read origin (court, level, docket number), docket.flagged_entries (each entry's flags name
   what it is evidence of: notice_of_appeal, usca_judgment_or_opinion, mandate, cert_granted /
   cert_denied, amended_or_substituted_opinion, reconsideration, vacated, remanded ...),
   docket.note (why a docket pass was skipped or empty), and same_litigation_opinions (later
   opinions in the same case; court_can_review_origin=true marks a reviewing court — THAT
   opinion's citation is the history to report). Compose subsequentHistory from what the record
   shows, in Bluebook order, citing the reviewing opinion where the index has it and the docket
   entry (date, entry number, wording) where it does not. A notice of appeal alone is "appeal
   filed, <date>" — not an outcome. An "(Attachments: ... Amended Opinion ...)" parenthetical is
   a known, unretrieved amendment — report it as such.
2. Every case — treatment:
     python3 "${CL_TOOLS}" citing "<cite>" --name "<case name>" --limit 10
   Read treatment_probe.most_relevant (mentions_target=true rows first) and
   name_search_treatment_probe. A signal row whose snippet names THIS case's parties and says it
   was overruled / abrogated / limited / declined to follow / superseded is a treatment flag:
   name the treating case, cite, date, and the scope if the snippet shows it, else "scope
   unconfirmed — open <case>". Rows about other cases are noise. Copy routes.* counts and
   distinct_cases_returned into treatmentRoutes with most_recent_citing_date.
3. If the cite does not resolve, the tool says so: run
     python3 "${CL_TOOLS}" find "<case name>" --cite "<cite>" --year <year>
   and retry with cluster:<id> from the matching candidate. If nothing resolves, status
   "not-resolved" — that is a coverage gap, not evidence about the case.

WHAT COUNTS AS A FINDING (historyFinding) — only these:
- The draft's cite text carries NO history words, and the record shows an outcome that Bluebook
  R. 10.7 requires: a reviewing court's affirmance / reversal / vacatur / modification, cert.
  denied or granted, an amended or substituted opinion, a judgment vacated on reconsideration.
- The draft states history the record contradicts (says aff'd, record shows rev'd).
NOT a finding: a notice of appeal with no outcome (say so in coverage); history the draft already
gives (draftHasHistory YES and consistent); a denial of rehearing (R. 10.7.1 lets it be omitted
unless particularly relevant); a Supreme Court decision (no history to add).
Treatment is reported in its own field, never as a history finding: the draft may cite the case
for its history or as a foil, which you cannot tell from here.

HONESTY RULES: RECAP is crowd-sourced, incomplete and federal-only — an empty docket is "no RECAP
entries found", never "no appeal"; state-court origins get no docket pass, say so; docket text
is the clerk's language, not a holding — do not characterize scope from "VACATED and REMANDED"
alone; the opinion index and the docket are separate sources. Supreme Court dockets are not on
PACER, so cert. history rests on lower-court docket entries or a later same-litigation opinion
— say "cert. history unconfirmed" when neither shows it. No hits is not proof of good law
(this is not Shepard's/KeyCite). Cases decided after your training data are real. Cap
confidence at moderate when the docket could not be read or only one citing route returned;
low when the case did not resolve or a tool errored. Never report from memory.
Pace yourself; on a 429 rate-limit, wait and retry once.`
const historyBatches = []
const historyTargets = HISTORY_ON ? historyCases.filter((c) => c.exists) : []
for (let i = 0; i < historyTargets.length; i += HISTORY_BATCH) historyBatches.push(historyTargets.slice(i, i + HISTORY_BATCH))
let historyResults = []
let historyRan = false
if (historyBatches.length && !tight(RESERVE_REPORT + RESERVE_REVERIFY + historyBatches.length * 5000)) {
  historyRan = true
  const hAgent = (b, i) => agent(historyPrompt(b), { label: `history:${i * HISTORY_BATCH}-${i * HISTORY_BATCH + b.length}`, phase: 'History', schema: HISTORY_SCHEMA, model: VERIFY_MODEL, effort: DEEP ? 'medium' : 'low' })
  const outs = await parallel(historyBatches.map((b, i) => async () => {
    let r = await hAgent(b, i)
    if (!r) { log(`history batch ${i} died — retrying once`); r = await hAgent(b, i) }
    return r
  }))
  for (const o of outs.filter(Boolean)) historyResults.push(...(o.cases || []))
  const got = new Set(historyResults.map((h) => norm(h.cite)))
  const missed = historyTargets.filter((c) => !got.has(norm(c.cite)))
  for (const c of missed) historyResults.push({ cite: c.cite, status: 'skipped', coverage: 'no result returned (agent failure)', confidence: 'low' })
  if (missed.length) degradation.push(`${missed.length} case cite(s) got no subsequent-history result (agent failure) — listed as not checked`)
} else if (historyBatches.length) {
  degradation.push(`subsequent-history / treatment pass skipped for ${historyTargets.length} case cites (budget)`)
} else if (!HISTORY_ON && CASE_CITES.length) {
  degradation.push('subsequent-history / treatment pass turned off by the caller (history:false)')
}
const historyByCite = new Map(historyResults.map((h) => [norm(h.cite), h]))
const historyFindings = historyResults.filter((h) => h.status === 'checked' && h.historyFinding)
const treatmentFlags = historyResults.filter((h) => h.status === 'checked' && h.treatment)
const historyUnchecked = historyResults.filter((h) => h.status !== 'checked')
const histLine = (h) => {
  const c = historyCases.find((x) => norm(x.cite) === norm(h.cite)) || {}
  return `- ${h.cite}${c.notes && c.notes.length ? ` (n.${c.notes.join(', n.')})` : ''}` +
    (h.historyFinding ? `\n    history: ${h.historyFinding}` : '') +
    (h.subsequentHistory && !h.historyFinding ? `\n    record shows: ${h.subsequentHistory}` : '') +
    (h.treatment ? `\n    treatment: ${h.treatment}` : '') +
    `\n    basis: ${h.historyBasis || 'n/a'}; ${h.coverage || ''}; routes: ${h.treatmentRoutes || 'n/a'}; confidence ${h.confidence || '?'}` +
    (h.note ? `\n    note: ${h.note}` : '')
}
log(`History: ${historyResults.length}/${historyTargets.length} cases checked — ${historyFindings.length} missing-history findings, ${treatmentFlags.length} treatment flags, ${historyUnchecked.length} not checked.`)

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

// ---------------------------------------------------------------------------
// Proposition-support units (opt-in). Scope: `pincited` units always; `whole-work` units only
// when supportScope is 'all'. Units whose source a verify agent fetches anyway are FOLDED INTO
// that agent (the text is already on disk); the rest get dedicated support agents below.
// ---------------------------------------------------------------------------
const supportInScope = SUPPORT_UNITS.filter((u) => u.scope === 'pincited' || SUPPORT_SCOPE === 'all')
const supportOutOfScope = SUPPORT_UNITS.filter((u) => !(u.scope === 'pincited' || SUPPORT_SCOPE === 'all'))
const supportByKey = new Map()
for (const u of supportInScope) {
  if (!supportByKey.has(u.key)) supportByKey.set(u.key, [])
  supportByKey.get(u.key).push(u)
}
const supportUnitById = new Map(SUPPORT_UNITS.map((u) => [u.id, u]))
if (SUPPORT_ON) log(`Support pass ON (scope ${SUPPORT_SCOPE}): ${supportInScope.length} unquoted citation instances in scope across ${supportByKey.size} unique sources; ${supportOutOfScope.length} whole-work cites out of scope.`)
const supportUnitLine = (u) => `  [support id ${u.id}] n.${u.n} | signal: ${u.sig || '(none — direct support)'} | ${u.pin ? 'at ' + u.pin : 'WHOLE WORK (no pincite)'} | ${u.k}`
// The fold-in block appended to a verify agent's prompt when its source carries support units.
const supportFoldBlock = (b) => {
  const units = supportByKey.get(b.key)
  if (!units || !units.length) return ''
  return `
=== SUPPORT UNITS (opt-in proposition-support pass) — ${units.length} unquoted cite(s) to the SAME source ===
Besides the quotes, the draft cites this source WITHOUT a quotation in the places below. Since you
have the text on disk, read each cited page and judge whether it supports what the draft cites it
for. Load the units (proposition sentence, full footnote, signal, parenthetical) via Bash:
  python3 "${PREPARE_SUPPORT}" "${EXTRACT_PATH}" --pick ${units.map((u) => u.id).join(' ')}
${units.map(supportUnitLine).join('\n')}
Read a pincited page from your saved source file with:
  python3 "${VERIFY_QUOTES}" /tmp/src-<slug>.txt --page <pincite> [--first-page <printed no. of the PDF's first page>]
Return one entry per support id in supportVerdicts (separate from the quote verdicts).
${SUPPORT_RULES}
`
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
- misattributed: the words ARE in the source, but the source is quoting someone else — a party's
  brief or argument, a lower court, a dissent or concurrence, an earlier case, a witness — and
  the draft's framing attributes them to the court (or the author) itself. Read the sentence
  around the match and the draft's body sentence before using this; a court adopting a quoted
  formulation as its own is not misattribution. MEDIUM; name the actual speaker in note and
  quote the source's attribution in sourceText.
- unverifiable: could not fetch/read the source — give the unlock path. Never guess.
ATTRIBUTION CHECK (substance, after the deterministic check): for every verbatim/normalized/
altered match, look at who is speaking in the source at that spot — the court for itself, or the
court reciting a party's position, a dissent, or another case. If the draft says "the Court held/
explained/reasoned" and the matched words are a recital, that is the misattributed verdict above.
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
${supportFoldBlock(b)}
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

// Support verdicts the verify agents returned for folded-in units (the source was on disk).
const supportRaw = []
const foldedKeys = new Set(verifyBundles.filter((b) => supportByKey.has(b.key)).map((b) => b.key))
for (const v of verifyResults) {
  if (!foldedKeys.has(v.sourceKey)) continue
  for (const sv of (v.supportVerdicts || [])) supportRaw.push({ ...sv, sourceKey: v.sourceKey, sourceIdentified: v.sourceIdentified || '', basis: sv.basis || v.fetchBasis || '' })
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
      severity: q.severity || (['mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source'].includes(q.verdict) ? 'high' : ['pincite_off', 'misattributed'].includes(q.verdict) ? 'medium' : 'low'),
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
// Phase 3b — SUPPORT (opt-in; dedicated agents for sources no verify agent fetched)
// ===========================================================================
phase('Support')
const supportPrompt = (bundles) => `You are checking whether sources a law-review draft cites WITHOUT quoting them
actually SUPPORT the propositions they are cited for (the opt-in proposition-support pass). This is a
judgment call, so the discipline below matters more than speed. ${bundles.length === 1 ? 'ONE source; fetch it once.' : `${bundles.length} sources, one unit each; fetch each once.`}

${bundles.map((b) => `SOURCE (resolved from the draft's footnotes; the footnote text you load below is the authoritative record): ${b.source}
KIND: ${b.kind}   SOURCE-BUNDLE KEY (echo exactly): ${b.key}
UNITS:
${b.units.map(supportUnitLine).join('\n')}`).join('\n\n')}

STEP 1 — load the units (proposition sentence, preceding sentence, full footnote, signal,
parenthetical, opinion note), via Bash (load it with ToolSearch "select:Bash" if needed):
  python3 "${PREPARE_SUPPORT}" "${EXTRACT_PATH}" --pick ${bundles.flatMap((b) => b.units.map((u) => u.id)).join(' ')}

STEP 2 — fetch each source ONCE (stop after ${MIRROR_CAP} attempts; then every unit on it is
"unverifiable" with the unlock path). Save the FULL text with --out (never cat it into context):
  python3 "${FETCH_PAGE}" "<url>" --out /tmp/sup-<slug>.txt
${zoteroHint.trim()}
For a case, CourtListener's HTML opinion or CAP static HTML carries star pagination; for a journal
PDF, pass the printed number of its first page. Then read the PINCITED page of each unit:
  python3 "${VERIFY_QUOTES}" /tmp/sup-<slug>.txt --page <pincite> [--first-page <printed first page>]
(a range "512-514" works; if the file has no page boundaries the tool says so — then grep -n the
proposition's key terms and read a targeted excerpt with sed -n). For a WHOLE-WORK unit, read the
holding / abstract / introduction and the part that bears on the claim; cap your effort.

STEP 3 — one verdict per unit, per the rules below. Echo each support id and sourceKey exactly.

${SUPPORT_RULES}
${SOURCES}`

let supportDedicated = [...supportByKey.entries()]
  .filter(([key]) => !foldedKeys.has(key))
  .map(([key, units]) => ({ key, units, kind: units[0].k, source: units[0].src }))
let supportRan = false
const supportSkippedUnits = []
if (SUPPORT_ON && supportDedicated.length) {
  // Budget ladder: whole-work units first (if 'all'), then secondary sources, then skip.
  const need = () => RESERVE_REPORT + RESERVE_REVERIFY + supportDedicated.length * PER_SUPPORT_SOURCE
  if (tight(need()) && SUPPORT_SCOPE === 'all') {
    const dropped = supportDedicated.filter((b) => b.units.every((u) => u.scope === 'whole-work'))
    supportDedicated = supportDedicated.filter((b) => !b.units.every((u) => u.scope === 'whole-work'))
    supportSkippedUnits.push(...dropped.flatMap((b) => b.units))
    if (dropped.length) degradation.push(`support: ${dropped.length} whole-work source(s) not read (budget)`)
  }
  if (tight(need())) {
    const dropped = supportDedicated.filter((b) => b.kind !== 'case')
    supportDedicated = supportDedicated.filter((b) => b.kind === 'case')
    supportSkippedUnits.push(...dropped.flatMap((b) => b.units))
    if (dropped.length) degradation.push(`support: ${dropped.length} secondary source(s) not read (budget) — cases kept`)
  }
  if (tight(need())) {
    supportSkippedUnits.push(...supportDedicated.flatMap((b) => b.units))
    degradation.push(`support: dedicated support agents skipped for ${supportDedicated.length} source(s) (budget) — only units folded into verify agents were read`)
    supportDedicated = []
  }
}
if (SUPPORT_ON && (supportDedicated.length || foldedKeys.size)) {
  supportRan = true
  // Multi-unit sources get their own agent; single-unit sources ride SUPPORT_TAIL per agent.
  const heavy = supportDedicated.filter((b) => b.units.length >= 2)
  const light = supportDedicated.filter((b) => b.units.length < 2)
  const jobs = heavy.map((b) => () => agent(supportPrompt([b]), {
    label: `support:${(b.source || b.key).slice(0, 44)}`, phase: 'Support', schema: SUPPORT_SCHEMA,
    model: VERIFY_MODEL, effort: 'medium', // a judgment, not a string match: never low
  }))
  for (let i = 0; i < light.length; i += SUPPORT_TAIL) {
    const chunk = light.slice(i, i + SUPPORT_TAIL)
    jobs.push(() => agent(supportPrompt(chunk), {
      label: `support-tail:${i}`, phase: 'Support',
      schema: { type: 'object', required: ['sources'], properties: { sources: { type: 'array', items: SUPPORT_SCHEMA } } },
      model: VERIFY_MODEL, effort: 'medium',
    }).then((o) => o && o.sources ? { _multi: o.sources } : o))
  }
  const outs = jobs.length ? await parallel(jobs) : []
  for (const o of outs.filter(Boolean)) {
    const list = o._multi ? o._multi : [o]
    for (const v of list) for (const sv of (v.supportVerdicts || [])) supportRaw.push({ ...sv, sourceKey: v.sourceKey, sourceIdentified: v.sourceIdentified || '', basis: sv.basis || v.fetchBasis || '' })
  }
}
// Join verdicts to units; anything in scope with no verdict is disclosed as not checked.
const supportFindings = []
const seenSupport = new Set()
const supportSeverity = (v) => (v === 'contradicted' ? 'high' : v === 'not_supported' ? 'medium' : v === 'overstated' ? 'confirm' : 'low')
for (const sv of supportRaw) {
  const u = supportUnitById.get(sv.id)
  if (!u || seenSupport.has(sv.id)) continue
  seenSupport.add(sv.id)
  const verdict = SUPPORT_VERDICTS.includes(sv.verdict) ? sv.verdict : 'unverifiable'
  supportFindings.push({
    id: sv.id, i: u.i, footnote: u.n, kind: u.k, signal: u.sig, pincite: u.pin, scope: u.scope,
    source: u.src, claim: sv.claim || u.claim || '', claimBasis: sv.claimBasis || (u.claim ? 'anchor' : ''),
    searched: sv.searched || '', sourceIdentified: sv.sourceIdentified || '',
    verdict, posture: sv.posture || '', locator: sv.locator || '', sourceText: sv.sourceText || '',
    reason: sv.reason || '', basis: sv.basis || '', severity: supportSeverity(verdict),
  })
}
const supportNoVerdict = supportInScope.filter((u) => !seenSupport.has(u.id) && !supportSkippedUnits.some((s) => s.id === u.id))
if (supportRan && supportNoVerdict.length) degradation.push(`${supportNoVerdict.length} support unit(s) got no verdict (agent failure or skipped ids) — listed as NOT CHECKED`)
if (SUPPORT_ON) log(`Support: ${supportFindings.length} verdicts — ${supportFindings.filter((f) => f.verdict === 'contradicted').length} contradicted, ${supportFindings.filter((f) => f.verdict === 'not_supported').length} not supported, ${supportFindings.filter((f) => f.verdict === 'overstated').length} overstated (confirm), ${supportFindings.filter((f) => f.verdict === 'supported_qualified').length} qualified, ${supportFindings.filter((f) => f.verdict === 'supported').length} supported; ${supportNoVerdict.length} no verdict, ${supportSkippedUnits.length} skipped (budget), ${supportOutOfScope.length} out of scope.`)

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

// Support findings are the most judgment-laden verdicts in the run, so contradicted and
// not_supported get the same independent second derivation. Overstated is a confirm item and
// is not re-verified (the author decides); supported/qualified are not findings.
const supportReverifyPrompt = (f) => `You are the SECOND, independent check on a proposition-SUPPORT finding from a
cite-check run: the first checker said this cite does NOT support (or contradicts) the sentence it is
cited for. Support verdicts are judgment calls and the quote pass showed five of six grave findings
were checker artifacts; re-derive this one from the FULL context and do not defer to the first checker.

STEP 1 — load the unit (proposition sentence, preceding sentence, clause before a mid-sentence
marker, FULL footnote, footnote prose, signal, parenthetical, opinion note), via Bash:
  python3 "${PREPARE_SUPPORT}" "${EXTRACT_PATH}" --pick ${f.id}

FIRST CHECKER SAID: verdict "${f.verdict}" — ${f.reason || '(no reason)'}
Source it read: ${f.sourceIdentified || f.source}; locator: ${f.locator || '(none)'}; posture: ${f.posture || '(none)'}
Source text it reported: ${f.sourceText ? `"${f.sourceText}"` : '(none reported)'}

STEP 2 — open the source yourself (${MIRROR_CAP} attempts max; --out to /tmp/resup-${f.id}.txt, then
  python3 "${VERIFY_QUOTES}" /tmp/resup-${f.id}.txt --page <pincite> [--first-page N])
and check specifically for these artifact classes:
- PARAPHRASED CLAIM: did the first checker test a stronger claim than the draft's own words (its
  hedges, its framing verb)? Judge the draft's sentence as written.
- SIGNAL MISREAD: a cf. / see generally / but see / compare cite judged as if it were a bare "see".
- CLAUSE VS SENTENCE: a mid-sentence marker supports the clause before it (anchor.clause), not the
  whole sentence; a footnote whose own prose states the proposition is judged against THAT.
- WRONG ANTECEDENT / WRONG PAGE: an Id. resolved to the wrong source, or a page read under the wrong
  marker convention (footer-numbered PDF vs star pagination) — re-read the right page.
- NEARBY PASSAGE: the supporting passage a page or two off the pincite = supported, with a locator note.
- POSTURE: support from a concurrence/dissent/dicta/reported view is supported_qualified, not
  not_supported; a narrower-than-claimed holding is overstated (a CONFIRM item), not contradicted.
If the finding holds after all this, upheld=true and restate it with the passage verbatim in
sourceText. If it is an artifact, upheld=false with the corrected verdict.

${SUPPORT_RULES}
${SOURCES}`
const supportToReverify = supportFindings.filter((f) => f.verdict === 'contradicted' || f.verdict === 'not_supported')
const supportReverified = new Map()
if (supportToReverify.length && !tight(supportToReverify.length * 6000)) {
  const outs = await parallel(supportToReverify.map((f) => () =>
    agent(supportReverifyPrompt(f), { label: `re-verify-support:n.${f.footnote}#${f.id}`, phase: 'Re-verify', schema: SUPPORT_REVERIFY_SCHEMA, model: REVERIFY_MODEL, effort: 'medium' })))
  for (const o of outs.filter(Boolean)) supportReverified.set(o.id, o)
  const lost = supportToReverify.filter((f) => !supportReverified.has(f.id)).length
  if (lost) degradation.push(`${lost} support finding(s) got no re-verify verdict (agent failure) — flagged as single-checker`)
  log(`Support re-verify: ${supportReverified.size} findings re-derived, ${[...supportReverified.values()].filter((r) => r.upheld === false).length} were checker artifacts (corrected).`)
} else if (supportToReverify.length) {
  degradation.push(`support re-verify skipped for ${supportToReverify.length} findings (budget) — flagged as single-checker`)
}
for (const f of supportFindings) {
  const rv = supportReverified.get(f.id)
  if (!rv) continue
  f.reverified = true
  const corrected = SUPPORT_VERDICTS.includes(rv.verdict) ? rv.verdict : f.verdict
  // an "artifact" here means the finding dissolved (the cite supports the claim after all);
  // a downgrade to overstated/qualified is a corrected verdict, not an artifact, and stays reported
  f.artifact = rv.upheld === false && ['supported', 'supported_qualified'].includes(corrected)
  f.firstVerdict = f.verdict
  f.verdict = corrected
  f.severity = supportSeverity(f.verdict)
  if (rv.sourceText) f.sourceText = rv.sourceText
  if (rv.posture) f.posture = rv.posture
  if (rv.locator) f.locator = rv.locator
  if (rv.searched) f.searched = rv.searched
  f.reverifyReason = rv.reason || ''
}
const supportByInstance = new Map(supportFindings.filter((f) => !f.artifact).map((f) => [f.i, f.verdict]))

// ===========================================================================
// Citation-instance LEDGER JOIN — mirror of citation_ledger.assign_dispositions()
// (the Python function is the reference implementation and is what the test covers;
// keep the two in step). Every instance ends with a disposition `d`:
//   verified | finding | existence-only | unverifiable | unchecked | xref | unresolved-xref | not-a-citation
//   + (opt-in support pass) supported | support-confirm | support-finding | support-unverifiable
// ===========================================================================
const supportDisposition = (v) => (
  v === 'contradicted' || v === 'not_supported' ? 'support-finding'
    : v === 'overstated' ? 'support-confirm'
      : v === 'supported' || v === 'supported_qualified' ? 'supported'
        : v === 'unverifiable' ? 'support-unverifiable' : null)
const XREF_KINDS = new Set(['id', 'supra', 'case-short'])
const VERIFIED_V = new Set(['verbatim', 'altered_marked', 'fragment_framing'])
const FINDING_V = new Set(['mismatch', 'not_found_in_sources', 'syllabus_quote', 'superseded_source', 'pincite_off', 'misattributed'])
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
  const sd = supportDisposition(supportByInstance.get(x.i))
  if (x.k === 'text') { x.d = 'not-a-citation'; continue }
  if (x.k === 'internal') { x.d = 'internal-ref'; continue }
  if (XREF_KINDS.has(x.k)) {
    x.d = x.xs === 'resolved' ? 'xref' : 'unresolved-xref'
    if (vs.some((v) => FINDING_V.has(v))) x.d = 'finding'
    else if (sd && x.xs === 'resolved') x.d = sd
    continue
  }
  const ex = x.k === 'case' ? (x.case ? caseExist.get(norm(x.case)) : undefined) : secExist.get(x.key)
  const ran = x.k === 'case' ? casePassRan : secondaryPassRan
  let exists = null
  if (ex) exists = ex.exists === true ? true : (ex.exists === false && ex.basis !== 'unconfirmed' ? false : null)
  if (vs.some((v) => FINDING_V.has(v)) || exists === false) x.d = 'finding'
  else if (sd === 'support-finding' || sd === 'support-confirm') x.d = sd
  else if (vs.some((v) => VERIFIED_V.has(v))) x.d = 'verified'
  else if (sd === 'supported') x.d = 'supported'
  else if (vs.length && vs.every((v) => v === 'unverifiable')) x.d = 'unverifiable'
  else if (sd === 'support-unverifiable') x.d = 'support-unverifiable'
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
  misattributed: findings.filter((f) => f.verdict === 'misattributed' && !f.artifact).length,
  support: {
    on: SUPPORT_ON,
    ran: supportRan,
    scope: SUPPORT_SCOPE,
    unitsTotal: SUPPORT_UNITS.length,
    unitsInScope: supportInScope.length,
    unitsOutOfScope: supportOutOfScope.length,
    unitsChecked: supportFindings.filter((f) => !['unverifiable', 'unread'].includes(f.verdict)).length,
    supported: supportFindings.filter((f) => f.verdict === 'supported' || f.artifact).length,
    qualified: supportFindings.filter((f) => f.verdict === 'supported_qualified' && !f.artifact).length,
    overstated: supportFindings.filter((f) => f.verdict === 'overstated').length,
    notSupported: supportFindings.filter((f) => f.verdict === 'not_supported').length,
    contradicted: supportFindings.filter((f) => f.verdict === 'contradicted').length,
    unverifiable: supportFindings.filter((f) => f.verdict === 'unverifiable').length,
    unread: supportFindings.filter((f) => f.verdict === 'unread').length + supportSkippedUnits.length,
    notChecked: supportNoVerdict.length,
    artifactsCaught: supportFindings.filter((f) => f.artifact).length,
    singleChecker: supportFindings.filter((f) => ['contradicted', 'not_supported'].includes(f.verdict) && !f.reverified).length,
  },
  history: {
    ran: historyRan,
    casesTargeted: historyTargets.length,
    casesChecked: historyResults.filter((h) => h.status === 'checked').length,
    lowerCourtCases: historyTargets.filter((c) => !c.scotus).length,
    missingHistory: historyFindings.length,
    treatmentFlags: treatmentFlags.length,
    notChecked: historyUnchecked.length,
  },
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

const fmtSupport = (f) => `- n.${f.footnote} [${f.verdict}${f.severity === 'high' ? ', HIGH' : ''}${['contradicted', 'not_supported'].includes(f.verdict) && !f.reverified ? ', SINGLE-CHECKER — not re-verified' : ''}] ` +
  `${f.signal ? f.signal + ' ' : ''}${(f.source || '').slice(0, 120)}${f.pincite ? ' at ' + f.pincite : ''}` +
  `\n    cited for (draft${f.claimBasis ? ', ' + f.claimBasis : ''}): "${(f.claim || '').slice(0, 260)}"` +
  (f.sourceText ? `\n    source says: "${f.sourceText.slice(0, 400)}"` : '') +
  (f.searched ? `\n    searched: ${f.searched.slice(0, 200)}` : '') +
  (f.posture ? `\n    posture: ${f.posture}` : '') +
  (f.locator ? `\n    locator: ${f.locator}` : '') +
  (f.reason ? `\n    reason: ${f.reason}` : '') +
  (f.reverifyReason ? `\n    re-verify: ${f.reverifyReason}${f.firstVerdict && f.firstVerdict !== f.verdict ? ` (first checker said ${f.firstVerdict})` : ''}` : '') +
  `\n    basis: ${f.basis || 'unstated'}`
const supportSec = (pred) => supportFindings.filter((f) => !f.artifact && pred(f)).map(fmtSupport).join('\n') || '(none)'

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
  mismatch / unverifiable; case cites checked; broken supras; pincite/metadata issues; missing
  subsequent history and treatment flags). The TL;DR MUST also carry one plain sentence with the
  ledger figure for citations that were confirmed to exist but NOT read for whether they support
  the proposition ("N of M citation instances are existence-only"), so the reader sees the
  unchecked share before the findings.${SUPPORT_ON ? ` The support pass RAN this time (opt-in): add one
  sentence with its counts — units read, supported, qualified, overstated (confirm), not supported,
  contradicted, unverifiable, and how many unquoted cites were NOT read (out of scope or budget).` : ` The
  support pass did NOT run (it is opt-in: support:true); say so in that sentence.`} State the verification basis honestly (everything rests
  on a fetched source; nothing judged from memory).
- **A. Needs your attention first** — the HIGH-severity findings (mismatches, not-found, syllabus
  quotes, superseded-source${SUPPORT_ON ? ', and CONTRADICTED support findings' : ''}), each with draft text vs. source text and the fix. These are the ones
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
- **G. Subsequent history & treatment (advisory)** — from the HISTORY block below. Two lists:
  "Add subsequent history" (the draft's cite omits an outcome the record shows: give the draft's
  cite text and the history to add, with its basis — docket entry or reviewing opinion) and
  "Treatment flags" (a later case says this one was overruled / abrogated / limited: name it,
  give the scope as far as known, and say the author must confirm how the draft uses the case).
  Then one line each for cases not checked. Keep this section ADVISORY in tone: the docket is
  the clerk's language, RECAP is incomplete, and no hits is not proof of good law.
- **H. Proposition support (opt-in)** — ${SUPPORT_ON ? `from the SUPPORT block below. Four lists, in this
  order: "Not supported (fix or re-cite)" (medium: the pincited page does not address the claim —
  give the claim, what the page does say, and the locator); "Confirm: possible overstatement"
  (the source supports a narrower or weaker version — phrase EVERY item as something to confirm,
  give the source's actual scope and the passage, and NEVER call it an error or put it in A);
  "Qualified support (posture)" (advisory: dicta, concurrence, dissent, reported view — one line
  each); then one sentence each for not read (out of scope / budget) and unverifiable (with unlock
  paths). Contradicted items go in A, not here (cross-reference them in one line).` : `ONE sentence: the
  pass did not run (opt-in; \`support:true\` reads every unquoted cite at its pincite), so unquoted
  cites were existence-checked only.`}
- **I. Couldn't check (what would unlock each)** — unverifiable items, each with its unlock path
  (Hein/JSTOR pull, add PDF to Zotero, physical copy).
- **J. Citation coverage ledger** — REQUIRED, from the ledger block below: what every citation
  instance got, and above all what did NOT get checked.
- A short method note: deterministic extraction + supra/existence checks; quotes verified by agents
  against fetched sources; a mandatory verify-the-verifier pass on high-severity findings; free/
  open-web sources only, so a Westlaw/Lexis + manual Bluebook pass is still recommended. State
  the coverage limits plainly: every citation instance is inventoried in section J; quoted
  passages were verified against fetched text; case cites and unquoted secondary sources were
  existence/metadata-checked${SUPPORT_ON ? `, and the unquoted cites in scope (${SUPPORT_SCOPE === 'all' ? 'pincited and whole-work' : 'pincited or parenthetical cites; bare whole-work cites were not read'}) were read for proposition support through their signals — a judgment, re-derived by a second checker for every not-supported/contradicted verdict` : ` ONLY — whether an unquoted cite actually supports its proposition
  was NOT assessed (the opt-in support pass did not run)`}; subsequent history and treatment were checked against CourtListener's
  opinion index and the RECAP docket archive (federal, incomplete), not Shepard's/KeyCite.

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
  failed. They are not findings; list them in section I as "not checked this run — re-run", by
  footnote, so the author knows the gap.
- A "misattributed" finding means the words are in the source but spoken by someone the draft
  does not name (a party, a dissent, a lower court). Section B or D, medium: give the actual
  speaker from the finding's note and the source's attribution.
- SUPPORT findings are judgments. "overstated" is a CONFIRM item by the author's standing
  instruction: it never appears in A, is never called an error, and is phrased "confirm that <source>
  supports <claim>; it says <scope>". "supported_qualified" is advisory. Every support line keeps
  the claim (the draft's sentence or clause) and the source passage side by side; a support
  finding with no source passage is by construction unverified — move it to section I, do not
  present it as a finding.

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

=== SUBSEQUENT HISTORY & TREATMENT (section G — advisory) ===
${historyRan ? `${counts.history.casesChecked} of ${counts.history.casesTargeted} case cites checked (${counts.history.lowerCourtCases} lower-court cases got the docket/same-litigation pass; Supreme Court cites got the treatment probe only).` : `PASS DID NOT RUN (${degradation.find((d) => /history/.test(d)) || 'no case cites'}) — say so in section G in one sentence.`}
ADD SUBSEQUENT HISTORY (the draft's cite omits an outcome the record shows):
${historyFindings.map(histLine).join('\n') || '(none)'}
TREATMENT FLAGS (a later case says this one was overruled / abrogated / limited — the author must confirm how the draft uses it):
${treatmentFlags.filter((h) => !h.historyFinding).map(histLine).join('\n') || '(none)'}
NOT CHECKED / NOT RESOLVED:
${historyUnchecked.map((h) => `- ${h.cite} — ${h.status}: ${h.coverage || h.note || ''}`).join('\n') || '(none)'}

=== PROPOSITION SUPPORT (section H${SUPPORT_ON ? '; contradicted items ALSO go in A' : ''}) ===
${SUPPORT_ON ? `Pass ran: ${supportRan ? 'yes' : 'NO (' + (degradation.find((d) => /^support/.test(d)) || 'no units in scope') + ')'}; scope ${SUPPORT_SCOPE}; ${counts.support.unitsInScope} unquoted instances in scope (${counts.support.unitsOutOfScope} whole-work cites out of scope, not read); ${counts.support.unitsChecked} read; ${counts.support.artifactsCaught} first-checker findings re-derived as artifacts (EXCLUDED below).
CONTRADICTED (section A — the source says the opposite; each survived or awaits re-verify as labelled):
${supportSec((f) => f.verdict === 'contradicted')}
NOT SUPPORTED (section H first list; medium):
${supportSec((f) => f.verdict === 'not_supported')}
CONFIRM — POSSIBLE OVERSTATEMENT (section H second list; never an error):
${supportSec((f) => f.verdict === 'overstated')}
QUALIFIED SUPPORT — POSTURE (section H third list; advisory, one line each):
${supportSec((f) => f.verdict === 'supported_qualified')}
SUPPORTED: ${counts.support.supported} (counts only — never list them).
UNVERIFIABLE (section I, with unlock paths):
${supportSec((f) => f.verdict === 'unverifiable')}
NOT READ — out of scope (${supportOutOfScope.length} whole-work cites; one sentence) / budget (${supportSkippedUnits.length}) / agent failure (${supportNoVerdict.length}; list by footnote in section I):
${supportNoVerdict.map((u) => `- n.${u.n} support unit ${u.id} — no verdict: ${(u.src || '').slice(0, 100)}`).join('\n') || '(none)'}` : 'PASS DID NOT RUN (opt-in). One sentence in section H.'}

=== UNVERIFIABLE (section I) ===
${findings.filter((f) => f.verdict === 'unverifiable').map(fmtFinding).join('\n') || '(none)'}

=== QUOTES NOT CHECKED — agent failure, not a finding (section I; list by footnote) ===
${[...unresolvedIds.map((i) => `- n.${UNIT_NOTES.get(i) ?? '?'} unit ${i} — no source resolution`), ...unverifiedUnits.map((r) => `- n.${r.footnote ?? '?'} unit ${r.id} — no verdict: "${(r.quote || '').slice(0, 120)}"`)].join('\n') || '(none)'}

=== SECONDARY-SOURCE EXISTENCE (sections E/G) ===
${secondaryExistence.length}/${SECONDARY_CITES.length} unique unquoted secondary sources existence-checked${secondaryPassRan ? '' : ' — PASS SKIPPED (budget); list them as UNCHECKED in section H'}.
NOT FOUND (draft cites a source no catalog/site could locate — section E, phrase as "not found in the sources checked"):
${secBad.map((s) => `- key ${s.key}: ${s.note || ''}`).join('\n') || '(none)'}
UNCONFIRMED (section I, with what would unlock each):
${secUnconfirmed.map((s) => `- key ${s.key}: ${s.note || ''}`).join('\n') || '(none)'}
METADATA DISCREPANCIES — EVIDENCED (section E "Errors (fix)"; from the existence agents, each line names the source record the agent opened):
${secMeta.map((m) => `- ${m}`).join('\n') || '(none)'}
METADATA DISCREPANCIES — UNEVIDENCED (section E "Confirm" ONLY — untagged findings and "confirm: …" notes, derived from search snippets or third-party listings, never from the source's own page; phrase each as "confirm …", never as a correction, and never promote one to the TL;DR):
${secMetaSoft.map((m) => `- ${m}`).join('\n') || '(none)'}

=== CITATION COVERAGE LEDGER (section J — REQUIRED; place it AFTER section I and BEFORE Citation form) ===
${LEDGER.length} citation instances inventoried across ${FOOTNOTE_COUNT} footnotes. Dispositions: ${JSON.stringify(ledgerCounts)}.
Write section J as: (1) one sentence with the counts; (2) one plain sentence that "existence-only"
instances were confirmed to exist but were NOT read for whether they support the proposition they
are cited for${SUPPORT_ON ? ' (the support pass read the "supported" / "support-confirm" / "support-finding" / "support-unverifiable" ones)' : ''}, and that "xref" instances (Id./supra/short forms) inherit their antecedent's status;
(3) the three lists below, each item as "n.N — cite text", so the author can see exactly what was
not checked. An empty list is written as "none". Do not pad, do not summarize the lists away.
UNCHECKED (no pass reached them):
${LEDGER.filter((x) => x.d === 'unchecked').map(ledgerLine).join('\n') || '(none)'}
UNVERIFIABLE (existence could not be confirmed from free sources; quote-level unverifiables are already in section I):
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
  : (counts.unverifiable || existBad.length || ledgerCounts.unchecked || secUnconfirmed.length || historyUnchecked.length || counts.support.unverifiable || counts.support.notChecked ? 'complete_with_limits' : 'complete')

// Structured findings for `scripts/findings_diff.py` (2026-10-19): a re-run after edits leads
// with what is new / still open / resolved. Identity is by content, never by footnote number.
const findingItems = [
  ...findings.filter((f) => !f.artifact && FINDING_V.has(f.verdict) && f.verdict !== 'unverifiable').map((f) => {
    const q = resById.get(f.id)
    return { kind: 'quote', footnote: f.footnote, verdict: f.verdict, severity: f.severity, quote: (q && q.quote) || '', source: f.sourceIdentified || f.source, label: `${f.verdict}: "${((q && q.quote) || '').slice(0, 100)}" — ${(f.sourceIdentified || f.source || '').slice(0, 60)}` }
  }),
  ...metaFindingsEvidenced.map((m) => ({ kind: 'metadata', label: m.slice(0, 200) })),
  ...secMeta.map((m) => ({ kind: 'metadata', label: m.slice(0, 200) })),
  ...SUPRA_PROBLEMS.map((s) => ({ kind: 'supra', footnote: s.footnote, claims: s.claims, supraNote: s.supra_note, label: `"${s.claims}, supra note ${s.supra_note}" — target does not name ${s.claims}` })),
  ...existBad.map((e) => ({ kind: 'existence', cite: e.citation, label: `unconfirmed: ${e.citation}` })),
  ...secBad.map((s) => ({ kind: 'secondary', source: s.key, label: `not found: ${s.key} ${s.note || ''}`.slice(0, 200) })),
  ...formAll.map((f) => ({ kind: 'form', location: f.location, find: f.find, problem: f.problem, label: `${f.problem} — "${(f.find || '').slice(0, 80)}"` })),
  ...historyFindings.map((h) => ({ kind: 'history', cite: h.cite, label: h.historyFinding.slice(0, 200) })),
  ...supportFindings.filter((f) => !f.artifact && ['contradicted', 'not_supported', 'overstated'].includes(f.verdict)).map((f) => ({
    kind: f.verdict === 'overstated' ? 'support-confirm' : 'support', footnote: f.footnote, verdict: f.verdict, severity: f.severity,
    source: f.source, claim: f.claim, label: `${f.verdict}: ${(f.source || '').slice(0, 60)}${f.pincite ? ' at ' + f.pincite : ''} — "${(f.claim || '').slice(0, 100)}"`,
  })),
  ...treatmentFlags.map((h) => ({ kind: 'treatment', cite: h.cite, label: h.treatment.slice(0, 200) })),
]

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
  history: historyResults,        // per-case subsequent-history / treatment results (section G)
  support: supportFindings,       // per-unit proposition-support verdicts (section H; opt-in)
  findings: { items: findingItems, support: { on: SUPPORT_ON, ran: supportRan, scope: SUPPORT_SCOPE } }, // for scripts/findings_diff.py — SKILL.md adds snapshotSha256 + date and saves it next to the report; `support` lets a later diff tell "resolved" from "not rechecked"
  report: report.report,
}
