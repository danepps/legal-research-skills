export const meta = {
  name: 'proofread',
  description: 'Proofread an article draft — chunked proofreading agents over the prose, whole-document consistency agents, a mandatory skeptical re-verification of every finding, and a location-ordered report',
  phases: [
    { title: 'Proof', detail: 'one agent per chunk: typos, grammar, missing/doubled words, editing residue' },
    { title: 'Consistency', detail: 'whole-document usage/terminology, structure/cross-reference, and typeface agents' },
    { title: 'Verify', detail: 'mandatory skeptical re-check of every candidate finding in full context' },
    { title: 'Report', detail: 'assemble the location-ordered proofread report' },
  ],
}

// ---- args (assembled by SKILL.md from extract_proof.py) -----------------------
// args = {
//   outDir, draftName, chunkFiles:[...paths], lintFindings:[...],
//   counts:{paragraphs, footnotes, words}, headings, noteParas, sha256,
//   snapshotTime, formatting:<proof.json formatting block>,
//   deep:boolean, style:boolean, fable:boolean
// }
let A = args || {}
if (typeof A === 'string') { try { A = JSON.parse(A) } catch { A = {} } }
const OUT_DIR = A.outDir || ''
const DRAFT_NAME = A.draftName || 'draft'
const CHUNK_FILES = A.chunkFiles || []
const LINT = A.lintFindings || []
const COUNTS = A.counts || {}
const HEADINGS = A.headings || []      // [{para, label, text}] from proof.json
const NOTE_PARAS = A.noteParas || {}   // {noteNumber: referencing paragraph id}
const SHA256 = A.sha256 || null
const SNAPTIME = A.snapshotTime || null
const DEEP = !!A.deep
const STYLE = !!A.style
// Proofers run on Opus by default; `fable:true` escalates them to Fable for a
// near-final read. Consistency, verify, and report always inherit the session
// model — verify is the false-positive gate and report is the deliverable.
const PROOF_MODEL = A.fable ? 'fable' : 'opus'
// HARD READ-ONLY GATE: every agent runs as the 'Explore' type, which has no
// Edit/Write/NotebookEdit tools — a proofing agent CANNOT modify the draft (or
// anything else) even if it goes off the rails. The draft itself is never
// referenced here anyway: agents only ever see the scratchpad snapshot's
// extraction artifacts (SKILL.md forbids passing draftPath into args).
const RO = { agentType: 'Explore' }
const FULLTEXT = OUT_DIR + '/fulltext.txt'
const FULLTEXT_FMT = OUT_DIR + '/fulltext_fmt.txt'
const PROOF_JSON = OUT_DIR + '/proof.json'
// Formatting layer (.docx only): run properties resolved through character AND
// paragraph styles, so typeface is checkable and all-caps headings stop drawing
// bogus capitalization findings. Absent on the markdown path.
const FMT = A.formatting || {}
const FMT_OK = !!FMT.available

// ---- budget (house convention: baseline turn-global spent(), soft cap) --------
const RESERVE_REPORT = 30_000
let SOFT_CAP = DEEP ? 400_000 : 250_000
const SPENT0 = budget.spent()
const remaining = () => budget.total ? budget.remaining() : Math.max(0, SOFT_CAP - (budget.spent() - SPENT0))
const tight = (need) => remaining() < need
const degradation = []

// ---- schemas -------------------------------------------------------------------
const SEVERITIES = ['error', 'likely', 'style', 'query']
const FINDING_ITEM = {
  type: 'object',
  required: ['location', 'find', 'problem', 'fix', 'severity', 'category'],
  properties: {
    location: { type: 'string', description: 'e.g. "¶123" (body paragraph) or "n.45" (footnote)' },
    find: { type: 'string', description: 'VERBATIM text copied from the draft, long enough to be unique for Cmd+F' },
    problem: { type: 'string' },
    fix: { type: 'string', description: 'the minimal correction' },
    severity: { enum: SEVERITIES },
    category: { type: 'string', description: 'typo | missing-word | doubled-word | agreement | tense | wrong-word | garbled | punctuation | capitalization | cross-reference | consistency | style' },
  },
}
const PROOF_SCHEMA = {
  type: 'object', required: ['findings'],
  properties: { findings: { type: 'array', items: FINDING_ITEM } },
}
const CONS_SCHEMA = {
  type: 'object', required: ['findings', 'conventions'],
  properties: {
    findings: { type: 'array', items: FINDING_ITEM },
    conventions: {
      type: 'array',
      items: {
        type: 'object', required: ['issue', 'recommendation'],
        properties: {
          issue: { type: 'string', description: 'e.g. "decisionmaking vs. decision-making"' },
          dominant: { type: 'string', description: 'the form the draft mostly uses, with count' },
          minority: { type: 'string', description: 'the deviating form, with count and locations' },
          recommendation: { type: 'string' },
        },
      },
    },
  },
}
const VERIFY_SCHEMA = {
  type: 'object', required: ['verdicts'],
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object', required: ['id', 'verdict', 'note'],
        properties: {
          id: { type: 'number' },
          verdict: { enum: ['confirmed', 'rejected', 'revised'] },
          note: { type: 'string', description: 'one sentence: why, quoting the actual draft text you re-read' },
          revised_problem: { type: 'string' },
          revised_fix: { type: 'string' },
        },
      },
    },
  },
}

// ---- shared ground rules (every finder stage) -----------------------------------
const GROUND_RULES = `GROUND RULES — read carefully; violations produce false accusations against the draft:
- READ-ONLY RUN: you must never create, modify, or delete any file. You have no write
  tools; do not attempt writes via shell commands either. Findings are REPORTED, never
  applied — the authors decide what to change.
- The text you are given is PLAIN: italics, small caps, underlining, indentation and
  block-quote structure are not shown to you. NEVER flag anything that depends on them —
  italicization of signals or case names, small caps in cites, block-quote layout. A
  separate typeface stage owns those, reading the marked-up copy of the same document.
- HEADINGS MAY PRINT IN ALL CAPS. Word applies caps as a style, so a header stored as
  "understanding temporalism" prints as "UNDERSTANDING TEMPORALISM". Any paragraph whose
  "display" field says ALL CAPS or SMALL CAPS renders that way regardless of the letters
  you see: never flag the capitalization of individual words in it, and never call two such
  headings inconsistent with each other because their stored casing differs. Their WORDING
  and spelling are still fair game.
- Text INSIDE quotation marks or an obvious block quotation is someone else's language and
  is NEVER flagged as a draft error: archaic spelling, odd grammar, and missing commas all
  stand; do not suggest [sic]. BUT if quoted text looks like a TRANSCRIPTION error — garbled
  grammar mid-quote, a stray character (e.g. "practice-and consent"), a clause duplicated as
  if pasted twice, a word that breaks the quote's own sentence — flag it with severity
  "query" and category "quote-integrity": the action is "verify this quotation against its
  source," never "fix the draft." Unbalanced quotation marks themselves are ordinary flags.
- In footnotes, IGNORE citation strings entirely — reporter abbreviations, signals, short
  forms, "supra"/"Id." mechanics, pincite format are ALL out of scope (a separate cite-check
  skill owns them, and a Bluebook linter this is not). DO proofread the PROSE inside
  footnotes: textual sentences and the words inside explanatory parentheticals like
  "(holding that the the statute applies)".
- [FN#n] markers are footnote-call positions, not text. [¶n] / [n.n] prefixes are location
  labels, not text.
- Legal terms of art, Latin phrases, party names, and the authors' defined shorthand are not
  errors. American legal-scholarship conventions apply (this is a US law review article).
- This is PROOFREADING, not editing${STYLE ? '' : `: do NOT flag style, wordiness, passive voice,
  clarity, or word choice you merely dislike. Only objective errors (severity "error") and
  probable errors a careful reader would mark (severity "likely")`}.
${STYLE ? '- Style mode is ON: you MAY additionally flag genuine style problems (severity "style") — confusing sentences, unintended repetition, tonal slips — sparingly, at most 3 per chunk.' : ''}
- Every finding needs a VERBATIM "find" string copied character-for-character from the draft
  (unique enough to locate with Cmd+F in Word — include a few surrounding words), the
  location label, what is wrong, and the minimal fix.
- If you are not sure something is an error, use severity "likely" or omit it. An empty
  findings list is a fine answer. Never pad.`

// ---- Phase: Consistency (launched first — independent of the proof fan-out) -----
phase('Consistency')
log('launching whole-document consistency agents')
const consUsageP = agent(
  `You are checking a law review article draft for INTERNAL CONSISTENCY of usage. Draft:
"${DRAFT_NAME}" (~${COUNTS.words || '?'} words, ${COUNTS.footnotes || '?'} footnotes).

Read ${FULLTEXT} (the whole draft, flattened; body paragraphs are prefixed [¶n], footnotes
[n.n], headings with #, table-of-contents lines with [TOC]). Also Read ${PROOF_JSON} and use
its "consistency" block — deterministic variant counts computed over the exact text
(hyphenation_variants, spelling_variants, defined_terms, stats).

${GROUND_RULES}

Your job — adjudicate, with the whole document in view:
1. HYPHENATION/COMPOUNDS: for each variant pair in the data (and any you notice), decide
   whether the variation is a real inconsistency or grammatically motivated (attributive
   "common-law rule" vs. predicate "at common law" is CORRECT variation; "decisionmaking" vs.
   "decision-making" in the same syntactic role is not). Skip variation inside quotations.
2. SPELLING variants (British/American, -ise/-ize): deviations outside quotations get a finding.
3. CAPITALIZATION conventions: "the Court" (SCOTUS) vs. "the court", "Constitution",
   "Part/Section" when cross-referring, "federal/Federal", "justice/Justice". Infer the
   draft's dominant convention, flag deviations with locations.
4. TERMINOLOGY DRIFT: key concepts the draft names inconsistently (e.g. "general law" vs.
   "general private law" vs. "the general-law approach" where the switch looks unintentional
   rather than meaningful); defined terms introduced then abandoned.
5. PUNCTUATION conventions from the stats block: serial comma, em-dash spacing,
   straight-vs-curly quote/apostrophe intrusions, double spaces. Report as conventions with
   counts; individual findings only when instances are few enough to list.
Findings = specific fixable deviations (severity "likely" for judgment calls, "error" only
when objectively wrong). Conventions = the global calls with your recommendation. Locations
in findings use the ¶n / n.n labels.`,
  { label: 'consistency:usage', phase: 'Consistency', schema: CONS_SCHEMA, ...RO })

const consStructP = agent(
  `You are checking the STRUCTURE and CROSS-REFERENCES of a law review article draft:
"${DRAFT_NAME}". Read ${PROOF_JSON} first — use "headings" (computed labels I / I.A / I.B.1…),
"toc_entries", and "part_refs" (every "supra/infra Part/Section X" with context). Then Read
${FULLTEXT} for the actual text (body paragraphs prefixed [¶n], footnotes [n.n], headings #).

${GROUND_RULES}

Your job:
1. PART/SECTION CROSS-REFERENCES: for every entry in part_refs, check the target exists AND
   that the description matches what that Part actually contains (e.g. "Part III considers
   objections" is wrong if Objections is Part II.D). Direction too: "infra" must point
   forward, "supra" backward.
2. TABLE OF CONTENTS STALENESS: compare toc_entries against the real headings — missing,
   renamed, or reordered entries (Word TOCs go stale; a mismatch means "refresh the TOC
   before submission" — one finding listing the mismatches, not one per line).
3. INTRODUCTION'S ROADMAP: find the roadmap paragraph ("Part I … Part II … Part III …") and
   check it against the actual structure — right count of Parts, right order, right one-line
   descriptions.
4. "TEXT ACCOMPANYING NOTES n–m" references: spot-check that the notes exist and the
   accompanying text plausibly discusses what is claimed.
5. DEFINED-TERM DISCIPLINE from proof.json defined_terms: a term defined but never used
   again, or defined twice.
Do NOT re-litigate note-number arithmetic bounds — a deterministic pass already checked
supra/infra note directions. Findings use severity "error" only for objectively broken
references; "likely" for judgment calls. Conventions may be empty.`,
  { label: 'consistency:structure', phase: 'Consistency', schema: CONS_SCHEMA, ...RO })

// Typeface: only runs when the extractor produced a real formatting layer.
// Deliberately a separate agent from consistency:usage — it is the ONE stage
// allowed to reason about italics, and giving it its own prompt keeps the
// "you cannot see formatting" rule intact everywhere else.
const consTypeP = FMT_OK ? agent(
  `You are checking TYPEFACE conventions — italics and small caps — in the law review draft
"${DRAFT_NAME}". You are the only stage that can see formatting, so nothing here is guesswork.

Read ${FULLTEXT_FMT}: the whole draft with formatting marked up as <i>italic</i>,
<sc>small caps</sc>, and <caps>prints in all caps</caps>. Line structure is the same as the
plain text — body paragraphs prefixed [¶n], footnotes [n.n], headings with #. Also Read
${PROOF_JSON} and use its "formatting" block: "case_name_counts" (how the draft actually
sets case names in each position) and "case_name_candidates" (every case name whose
observed typeface departs from the Bluebook expectation for its position — the script's
positional guess is FALLIBLE, so re-read each one in its sentence before you accept it).

${GROUND_RULES}

THE RULES YOU ARE APPLYING (Bluebook R. 2.1(a) typeface for law review FOOTNOTES — not the
Bluepages/practitioner convention, which italicizes case names everywhere. The full
statement, including the worked examples, is in
~/.claude/skills/legal-research/bluebook-typeface-and-short-forms.md — Read it first.
State the rule in your findings so the authors can check your work):
1. ITALIC: introductory signals (See, See also, See generally, Cf., Compare … with …,
   But see, But cf., Accord, Contra, E.g.); "Id."; "supra"; "infra"; and
   subsequent-history phrases ("aff'd", "rev'd", "cert. denied", "overruled by").
   NOT italic (common mistake, imported from the practitioner Bluepages): the word
   "hereinafter" — "[hereinafter Hearings]" has only the short title italic — and
   "quoting"/"citing" in an explanatory parenthetical. Never flag those as roman errors.
2. ITALIC: case names in TEXTUAL sentences — in body text, and in textual sentences inside
   a footnote ("in the early case Hylton v. United States, the Justices …") — and case
   names in SHORT-FORM cites ("Hylton, 3 U.S. at 174").
3. ROMAN: case names in FULL citations that stand in a citation clause or citation sentence
   of a footnote ("See Knowlton v. Moore, 178 U.S. 41, 106 (1900)."). This is the one most
   drafts get backwards, and it is the distinction the script cannot reliably draw: a name
   after "See," "(quoting," or "; and" opens a citation clause (roman), while a name after
   ordinary prose words ("relied on", "the case of") is textual (italic).
4. ROMAN: everything adjacent to the italicized bit — the "note 3" after an italicized
   "supra", the "at" of a short form, and the comma or period separating a case name or
   article title from its citation.
5. LARGE AND SMALL CAPS: book authors and titles, institutional authors, and periodical
   names in law review footnotes. Judge these for CONSISTENCY across the draft (the same
   source set two different ways) rather than against the rule in the abstract.

Your job:
a. Adjudicate every entry in case_name_candidates: read its sentence in ${FULLTEXT_FMT},
   decide whether it is textual or a citation clause, and issue a finding ONLY where the
   typeface is actually wrong for the position it is in. Rejecting the script's guess is a
   fine and expected outcome — say so by simply not reporting it.
b. Sweep for typeface INCONSISTENCY the script does not model: the same source or signal
   set two ways in different footnotes, small caps applied to part of a name, italics
   running through a whole cite where only the case name belongs in italics, a stretch of
   body text left italic from an earlier edit.
c. Report document-wide patterns as conventions with counts, not as dozens of findings. If
   the draft is uniformly contrary to a rule, that is ONE convention entry (a single global
   fix), not one finding per instance.

CRITICAL — find strings: the markup tags are NOT in the author's document. Every "find"
string you report must be the text with all <i>/<sc>/<caps> tags REMOVED, so it can be
found with Cmd+F in Word. Say which words should change typeface in the "problem"/"fix"
instead. Location labels are the ¶n / n.n prefixes. Category: "typeface".`,
  { label: 'consistency:typeface', phase: 'Consistency', schema: CONS_SCHEMA, ...RO }) : null

// ---- Phase: Proof (chunk fan-out) ------------------------------------------------
phase('Proof')
log(`proofreading ${CHUNK_FILES.length} chunks`)
const proofResults = await parallel(CHUNK_FILES.map((cf, i) => () =>
  agent(
    `You are proofreading chunk ${i + 1}/${CHUNK_FILES.length} of a law review article draft
("${DRAFT_NAME}"). Read ${cf} — JSON with "paragraphs" (body text, [FN#n] marks footnote
calls; "heading" non-null means the line is a section heading) and "footnotes" (the notes
called in these paragraphs, keyed by their real numbers).

${GROUND_RULES}

Read every sentence slowly, the way a professional proofreader does — including footnote
prose. You are hunting:
- typos and misspellings (including real-word typos: "casual"/"causal", "trail"/"trial",
  "form"/"from", "public"/"pubic", "now"/"not");
- missing words ("the court held the statute" → "held THAT the statute") and doubled words;
- subject–verb and pronoun–antecedent agreement, singular/plural slips;
- tense and parallelism breaks within a sentence;
- EDITING RESIDUE — the highest-value catch: half-revised sentences that read as garbled,
  duplicated phrases from a botched cut-and-paste, orphaned sentence fragments, leftover
  author notes/brackets ("[cite]", "[shyam...]", "TK", "XXX", "[?]");
- punctuation errors in PROSE (comma splices only when flagrant, missing closing punctuation,
  a period where a question mark is required);
- MISSING commas the draft's own convention requires: after a multiword introductory phrase,
  before a conjunction joining two independent clauses, and after "that is" — flag these
  when the surrounding text shows the draft normally uses them (calibrate to the draft, not
  to your own comma taste);
- sentence FRAGMENTS: a "sentence" with no finite verb ("For example, legislative
  intervention fueled by donor interests." — no verb → fragment);
- unidiomatic constructions and wrong attributive number ("beholden to follow",
  "contracts principles" for "contract principles", "deferential of");
- DANGLING modifiers and mixed/blended constructions: a participial opener whose subject
  isn't the actor ("looking at the statute's impact, the statute appeared"), mixed
  correlatives ("whether X or if Y"), blended idioms ("an alternative around", "balancing
  in the need", "learn well from", "peace can sometimes break" for "break down");
- malformed noun phrases from half-revisions: stacked or inverted "of"-chains ("the
  existence of general law of the thin version we defend"), a modifier pointing at the
  wrong antecedent ("this obligation" where the referent was a right);
- DUPLICATED sentences or quotations in nearby paragraphs: a distinctive sentence or block
  quote appearing twice within a page is editing residue even when each copy reads
  cleanly — compare quotes across your whole chunk, not just within a paragraph;
- proper names the chunk itself contradicts: a case name or person in body text that
  doesn't match the accompanying footnote's caption or another nearby spelling ("Webb's
  Fabulous Pharmacy" beside a cite whose caption is "Webb's Fabulous Pharmacies") — flag
  as likely and let the verifier decide;
- body-text capitalization errors.
Location = the paragraph's "¶<id>" (use the "id" field) or "n.<number>" for footnote prose.
Report location + verbatim find + problem + minimal fix + severity + category.`,
    { label: `proof:chunk-${i}`, phase: 'Proof', schema: PROOF_SCHEMA, model: PROOF_MODEL, ...RO })
))

// ---- collect + dedup candidates ---------------------------------------------------
// Fuzzy dedup: two agents flagging the same error phrase their find-strings
// differently, so exact keys leak duplicates into the report (first-run
// lesson: the ¶90 stray-"a" shipped twice). Same location + token overlap
// of the find-strings = same finding.
const toks = (s) => new Set((s || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim().split(' ').filter(Boolean))
function sameFinding(a, b) {
  if (a.location !== b.location) return false
  const ta = toks(a.find), tb = toks(b.find)
  let inter = 0
  for (const x of ta) if (tb.has(x)) inter++
  return inter / Math.max(1, ta.size + tb.size - inter) >= 0.4
}
const pool = []
function addCandidate(f, source) {
  if (!f || !f.find || !f.problem) return
  if (f.severity === 'style' && !STYLE) return
  if (pool.some(p => sameFinding(p, f))) return
  pool.push({ id: pool.length, source, ...f })
}
// deterministic lint findings join the pool (verify kills e.g. legit "had had")
for (const l of LINT) {
  const loc = l.location?.where === 'footnote' ? `n.${l.location.note}` : `¶${l.location?.para}`
  addCandidate({
    location: loc, find: l.find, problem: l.problem, fix: l.fix,
    severity: l.severity === 'error' ? 'error' : 'likely',
    category: l.rule,
  }, 'lint')
}
for (const r of proofResults.filter(Boolean)) r.findings.forEach(f => addCandidate(f, 'proof'))

const consUsage = await consUsageP
const consStruct = await consStructP
const consType = consTypeP ? await consTypeP : null
const conventions = [
  ...(consUsage?.conventions || []),
  ...(consStruct?.conventions || []),
  ...(consType?.conventions || []),
  ...(FMT.conventions || []),   // deterministic uniform-practice calls
]
for (const r of [consUsage, consStruct].filter(Boolean)) r.findings.forEach(f => addCandidate(f, 'consistency'))
// Typeface findings keep their own category so the verify stage knows to check
// them against the MARKED text and the report can group them.
for (const f of (consType?.findings || [])) addCandidate({ ...f, category: 'typeface' }, 'typeface')
log(`${pool.length} candidate findings (proof + consistency + lint), ${conventions.length} conventions`)

// ---- Phase: Verify (mandatory — no finding reaches the report unverified) ---------
phase('Verify')
let toVerify = pool
let unvetted = []
if (tight(RESERVE_REPORT + 40_000)) {
  // degrade: verify only "error"-severity; ship the rest labeled unvetted
  toVerify = pool.filter(f => f.severity === 'error')
  unvetted = pool.filter(f => f.severity !== 'error')
  degradation.push(`budget: verified only error-severity findings (${unvetted.length} likely/style findings shipped unvetted)`)
}
const BATCH = DEEP ? 8 : 12
const batches = []
for (let i = 0; i < toVerify.length; i += BATCH) batches.push(toVerify.slice(i, i + BATCH))
log(`verifying ${toVerify.length} findings in ${batches.length} batches`)

const verdictById = new Map()
const verifyResults = await parallel(batches.map((batch, bi) => () =>
  agent(
    `You are the SKEPTICAL second reader on a proofread of the law review draft
"${DRAFT_NAME}". Earlier agents flagged the findings below. Your job is to RE-DERIVE each
one from the actual draft text and kill the false positives. Findings you confirm go
straight into a report the authors will act on — a wrong confirmation wastes their time and
a wrong rejection hides a real error, so actually re-read the text; never rule from the
finding alone.

METHOD: the full draft is at ${FULLTEXT}. Each body paragraph is one line prefixed "[¶n]",
each footnote one line prefixed "[n.n]". For each finding, Grep that file for its location
label (e.g. pattern "^\\[¶123\\]" or "^\\[n\\.45\\]") to pull the full passage, then re-read the
ENTIRE passage around the flagged text.

Reject when: the flagged text is actually correct as written (grammatical "had had",
subjunctive, legal term of art, intentional usage); the finding depends on formatting that
is not visible to the stage that raised it; the find string does not appear in the passage;
or the "fix" would change meaning the authors plainly intended.
Revise when the problem is real but the diagnosis or fix is wrong. Confirm only what a
careful law-review editor would actually mark — but do not reject a genuine error merely
because it is small.
CATEGORY-SPECIFIC RULES:
${FMT_OK ? `- TYPEFACE findings (category "typeface", or a category starting "fmt-") are about italics
  and small caps, and they are IN SCOPE — the general "you cannot see formatting" rule does
  not apply to them, because this draft has a real formatting layer. Verify them against
  ${FULLTEXT_FMT}, NOT fulltext.txt: same [¶n] / [n.n] line structure, with <i>italic</i>,
  <sc>small caps</sc> and <caps>prints all caps</caps> marked. Grep the location label
  there and read the tags. Reject a typeface finding when the tags show the text is already
  correct, or when the flagged case name sits in a textual sentence (italic is right there)
  rather than in a citation clause. The find string must contain NO markup tags — if a
  confirmed finding's find string has tags in it, revise it to the tag-free text.
- Findings about the capitalization of a heading that "displays ALL CAPS" are automatically
  REJECTED: the reader never sees the stored casing.
` : ''}- Findings whose category starts with "cite-", "pincite", "case-cite", or "supra-" are
  DETERMINISTIC citation-mechanics candidates and ARE in scope even though they sit inside
  citation strings — do not reject them as "citation mechanics out of scope"; adjudicate
  them on the text (e.g., is the "U. S." spacing inside a quotation from an old reporter?
  is the pincite arithmetic actually impossible? does the terminal period really belong?).
- Findings with severity "query" (or sitting inside quotation marks) are AUTHOR QUERIES:
  confirm them only as "verify this quotation against its source" items — genuine
  transcription-smell (garbled grammar mid-quote, stray characters, duplicated clauses).
  Reject if the quoted text is merely archaic or stylistically odd. Never convert a query
  into a draft-error verdict. When you confirm a prose finding that sits inside a
  quotation, revise it INTO a query.

${GROUND_RULES}

FINDINGS (verify batch ${bi + 1}/${batches.length}):
${JSON.stringify(batch.map(({ id, location, find, problem, fix, severity, category }) =>
      ({ id, location, find, problem, fix, severity, category })), null, 1)}

Return a verdict for EVERY id.`,
    { label: `verify:batch-${bi}`, phase: 'Verify', schema: VERIFY_SCHEMA, ...RO })
))
for (const r of verifyResults.filter(Boolean)) {
  for (const v of (r.verdicts || [])) verdictById.set(v.id, v)
}

const confirmed = []
const rejected = []
for (const f of toVerify) {
  const v = verdictById.get(f.id)
  if (!v) { unvetted.push(f); continue } // verify agent died — ship labeled, never silently drop
  if (v.verdict === 'rejected') { rejected.push({ ...f, why: v.note }); continue }
  confirmed.push({
    ...f,
    problem: v.verdict === 'revised' && v.revised_problem ? v.revised_problem : f.problem,
    fix: v.verdict === 'revised' && v.revised_fix ? v.revised_fix : f.fix,
    verifierNote: v.note,
  })
}
log(`verify: ${confirmed.length} confirmed, ${rejected.length} rejected, ${unvetted.length} unvetted`)

// sort by location: body ¶ ascending, then footnotes ascending
const locKey = (f) => {
  const m = /^¶(\d+)/.exec(f.location) ; if (m) return [0, +m[1]]
  const n = /^n\.(\d+)/.exec(f.location); if (n) return [1, +n[1]]
  return [2, 0]
}
confirmed.sort((a, b) => { const [x, y] = locKey(a), [p, q] = locKey(b); return x - p || y - q })
unvetted.sort((a, b) => { const [x, y] = locKey(a), [p, q] = locKey(b); return x - p || y - q })

// Reader-facing location labels (author, 2026-08-23): internal ¶ ids mean nothing to an
// author editing in Word — there are no visible paragraph numbers — so the report locates
// body findings by containing Part/Section plus approximate position through the document,
// and footnotes by their visible number. The verbatim find string is the primary locator;
// ¶ ids stay internal (grep anchors, dedup, sort keys) and never reach the report.
function locLabel(loc) {
  const n = /^n\.(\d+)/.exec(loc)
  if (n) return `note ${n[1]}`
  const m = /^¶(\d+)/.exec(loc)
  if (!m) return loc
  const para = +m[1]
  const pct = COUNTS.paragraphs ? Math.min(99, Math.round(100 * para / COUNTS.paragraphs)) : null
  let best = null
  for (const h of HEADINGS) { if (h.para <= para) best = h; else break }
  let name = null
  if (best) {
    const t = (best.text || '').slice(0, 40).trim()
    name = (best.label && !t.startsWith(best.label) ? `${best.label} ${t}` : t) || null
  }
  if (name && pct != null) return `${name}, ≈${pct}% in`
  if (name) return name
  if (pct != null) return `≈${pct}% in`
  return loc
}
for (const f of [...confirmed, ...unvetted]) f.locationPath = locLabel(f.location)
const TYPEFACE = (f) => /^(fmt-|typeface)/.test(f.category || '')
const CITE_MECH = (f) => !TYPEFACE(f) && /^(cite-|pincite|case-cite|supra-)/.test(f.category || '')

// ---- Phase: Report ------------------------------------------------------------------
phase('Report')
const report = await agent(
  `Write the final PROOFREAD REPORT for the law review draft "${DRAFT_NAME}"
(~${COUNTS.words || '?'} words, ${COUNTS.paragraphs || '?'} body paragraphs,
${COUNTS.footnotes || '?'} footnotes). Audience: the authors (law professors) — direct,
no filler, no praise padding. Your ENTIRE final message must be the report markdown, nothing else.

PROVENANCE (put this under the title as a one-line blockquote):
snapshot ${SNAPTIME || 'time unknown'}${SHA256 ? `, SHA-256 ${SHA256}` : ''}; plain-text pass.

CONFIRMED PROSE FINDINGS (every one re-verified in context; already sorted into draft
order; "location" is the reader-facing label — containing Part/Section and/or approximate
position through the document, or "note N" for footnotes. Use these labels exactly as
given. NEVER refer to findings by paragraph numbers (¶n) anywhere in the report, including
the TL;DR — the authors edit in Word and cannot see paragraph numbers; the verbatim find
string is their locator):
${JSON.stringify(confirmed.filter(f => !CITE_MECH(f) && !TYPEFACE(f) && f.severity !== 'query').map(({ locationPath, location, find, problem, fix, severity, category, verifierNote }) =>
    ({ location: locationPath || location, find, problem, fix, severity, category, verifierNote })), null, 1)}

${FMT_OK ? `CONFIRMED TYPEFACE FINDINGS (italics and small caps — the one thing checked against the
formatted document rather than plain text; own "## Typeface" section):
${JSON.stringify(confirmed.filter(TYPEFACE).map(({ locationPath, location, find, problem, fix, category }) =>
      ({ location: locationPath || location, find, problem, fix, category })), null, 1)}` : ''}

CONFIRMED CITATION-MECHANICS FINDINGS (deterministic typography inside citations —
doubled periods, § spacing, placeholders, impossible pincites, supra-target breaks;
group these under their own "## Citation mechanics" section, one line each):
${JSON.stringify(confirmed.filter(CITE_MECH).map(({ locationPath, location, find, problem, fix, severity, category }) =>
    ({ location: locationPath || location, find, problem, fix, category })), null, 1)}

AUTHOR QUERIES (suspected transcription errors INSIDE quotations — the action is
"verify the quote against its source," never "fix the draft"; own section):
${JSON.stringify(confirmed.filter(f => f.severity === 'query').map(({ locationPath, location, find, problem, verifierNote }) =>
    ({ location: locationPath || location, find, problem, verifierNote })), null, 1)}

${unvetted.length ? `UNVETTED FINDINGS (flagged but NOT independently re-verified — label them as such):
${JSON.stringify(unvetted.map(({ locationPath, location, find, problem, fix, severity }) =>
      ({ location: locationPath || location, find, problem, fix, severity })), null, 1)}` : ''}

DOCUMENT-WIDE CONVENTIONS (from the consistency pass):
${JSON.stringify(conventions, null, 1)}

STRUCTURE:
# Proofread — ${DRAFT_NAME}
the provenance blockquote
_A one-line TL;DR: counts by severity, and the single most important catch._
## Errors (fix these)
prose severity "error", in draft order. For each: **location** — \`verbatim find string\` —
the problem — the fix. Keep the find string EXACTLY verbatim — it is the authors' Cmd+F
handle and their ONLY way to find the passage (the draft shows no paragraph numbers). Use
the location labels exactly as given ("note N" = footnote N; body labels name the
Part/Section and approximate position); never write ¶ numbers.
## Judgment calls (probably fix)
prose severity "likely", same format, one line each where possible.
## Citation mechanics
the citation-mechanics findings, one line each, grouped by kind (placeholders first, then
impossible pincites / inconsistent cites / supra breaks, then SHORT FORMS — category
"cite-short-form" — then typography). For the short-form items, state the governing rule
once at the top of that group so the authors can check it: a case may be short-cited if it
was cited in full in the same footnote or one of the preceding FIVE footnotes (R. 10.9),
and a secondary source takes "Author, supra note N" from its second appearance onward with
no distance limit (R. 4.2). Note once that these are mechanical checks, not a Bluebook review.
${FMT_OK ? `## Typeface
the typeface findings — italics and small caps — one line each, grouped by kind (signals
and "supra"/"Id." first, then case names, then small caps). Say once that this is the only
section based on the document's actual formatting, and name the rule being applied
(Bluebook R. 2.1(a)) so the authors can check the call.
` : ''}
## Author queries (verify quotes against sources)
the author-query items — suspected transcription errors inside quotations; make clear the
action is checking the source (or running /cite-check), not editing the draft.
${STYLE ? '## Style suggestions\nseverity "style" findings, clearly optional.\n' : ''}## Document-wide conventions
the conventions table: issue | draft's dominant form | deviations | recommendation.
Where the source data cites deviations by ¶ number, translate: give a few verbatim
example snippets (Cmd+F-able) and a count, never raw ¶ numbers.
${unvetted.length ? '## Unvetted\nthe unvetted list, clearly labeled as not re-verified.\n' : ''}## Coverage notes
- what this pass does NOT check: citation accuracy/quotes against real sources (the
  cite-check skill), and substantive Bluebook form beyond what is listed above (signal
  order, citation order, and full-cite composition were not reviewed).
- ${FMT_OK
    ? 'italics and small caps WERE checked, against the document\'s own run formatting; indentation and block-quote layout were not.'
    : 'formatting was NOT checked — this draft came in as plain text, so italics, small caps and layout were invisible to every stage.'}
- ${rejected.length} candidate findings were rejected on re-verification (false-positive control).
${degradation.length ? `- degradation this run: ${degradation.join('; ')}` : ''}

Do not invent findings, merge findings, or drop any confirmed finding. Plain sentences, not
arrow-chains.`,
  { label: 'report', phase: 'Report', ...RO })

return {
  report,
  counts: {
    candidates: pool.length,
    confirmed: confirmed.length,
    rejected: rejected.length,
    unvetted: unvetted.length,
    errors: confirmed.filter(f => f.severity === 'error' && !CITE_MECH(f) && !TYPEFACE(f)).length,
    likely: confirmed.filter(f => f.severity === 'likely' && !CITE_MECH(f) && !TYPEFACE(f)).length,
    citeMechanics: confirmed.filter(CITE_MECH).length,
    shortForms: confirmed.filter(f => f.category === 'cite-short-form').length,
    typeface: confirmed.filter(TYPEFACE).length,
    queries: confirmed.filter(f => f.severity === 'query').length,
    conventions: conventions.length,
  },
  exitState: degradation.length ? 'complete_with_limits' : 'complete',
  degradation,
  rejectedFindings: rejected.map(({ location, find, why }) => ({ location, find, why })),
}
