---
name: cite-check
description: Verify every citation and quotation in an article draft against the real sources — cases via CourtListener + official reporters, scholarship via the user's Zotero library then the open web — and return a graded, footnote-by-footnote report with a "needs your attention" section first, plus a citation-form section (short cites per Bluebook R. 10.9/4.2 and italics/small caps per R. 2.1(a)) decided from the draft alone. Trigger when the user wants a draft cite-checked ("cite-check this", "check the citations/quotes in this draft", "run cite-check on <file>"). Input: a .docx with real Word footnotes (markdown/plain-text fallback). Not a full Bluebook linter — signal order, citation order and cite composition stay out.
---

# Cite Check

A verification pass over a finished or in-progress article draft. Every authority is checked for
existence; every quotation is checked verbatim against the real source; every URL is confirmed to
resolve; pincites are sanity-checked where the source's pagination is recoverable. Deterministic
scripts do extraction and cross-reference resolution for near-zero tokens; model agents do the
quote/pincite verification in a unique-source fan-out, with a **mandatory second check on every
high-severity finding** so a checker artifact never reaches the report.

It reuses the **legal-research** skill's machinery (`check_cite.py`, `fetch_page.py`, the
CourtListener token, the budget-degradation ladder) and its house rules (open-web only, never verify
from memory, an unfetchable source is reported unverified — never assumed).

**What it checks:** that each cite resolves to the claimed source, captions/authors/titles are
spelled right, the reporter/volume/first-page/court/year are right, quotes are verbatim or honestly
marked, supra/id. cross-references are intact, and URLs are live.

**Coverage ledger (added 2026-09-06) — and what is still NOT checked.** Quote-verification
units are built from *quotations*; on their own they left every unquoted secondary source
unaccounted for. Now `scripts/citation_ledger.py` inventories **every citation instance** in
every footnote (case or secondary, quoted or not, with `Id.`/`supra`/short-form chains
resolved), a secondary-source existence pass covers the unquoted articles/books/statutes/URLs,
and the report's section H gives each instance a disposition — `verified`, `finding`,
`existence-only`, `unverifiable`, `unchecked`, `xref`, `unresolved-xref` — and lists the
unchecked ones by footnote. Two limits remain and the report must say so: (1) **proposition
support** — whether an unquoted cite actually stands for the sentence it hangs on — is never
assessed (that is what `existence-only` means); (2) pincites are checked only where a quotation
anchors them. Treat `existence-only` as "real source, unread," never as "passed."

**Plus the obvious FORM problems (scope lock lifted by the user, 2026-08-10 — "undo the lock insofar as
it's stopping you from checking obvious stuff").** A `Form` phase reports what is decidable from the
draft alone, no source consulted:
- **Short forms** — a full citation repeated inside Bluebook R. 10.9's five-footnote window where
  the short form belongs; a case short form stranded past that window or with no full cite before it
  anywhere; a secondary source cited in full twice when R. 4.2 calls for `Author, supra note N`.
- **Typeface** (`.docx` only) — signals / `Id.` / `supra` / `quoting` left roman, the `note N` after
  an italicized `supra` wrongly italicized, italics spilling onto the comma before a citation, small
  caps broken mid-word, and case-name italicization under R. 2.1(a) (roman in a full cite standing
  in a citation clause, italic in a textual sentence or short form — the one call that needs an
  agent, since a pattern cannot tell those apart).

These run off `${CLAUDE_PLUGIN_ROOT}/skills/legal-research/citeform.py`, the **same module `/proofread` uses**,
so the two skills cannot give contradictory advice. The rules as applied are written out in
`${CLAUDE_PLUGIN_ROOT}/skills/legal-research/bluebook-typeface-and-short-forms.md`. Form findings get their own
report section near the end and never enter "Needs your attention" — they are tidy-up, not substance.

**What it is still NOT:** a full Bluebook linter (signal order, citation order, and whether a cite is
correctly *composed* remain out of scope), a substantive editor, or a substitute for the journal's
cite-check. The division with `/proofread` is unchanged for everything else: **proofread reads the
prose, cite-check verifies the authorities** — they now happen to share the citation-form layer.

## How to run

### 1. Parse the request
- **draftPath** — path to the draft (required). `.docx` with real Word footnotes is canonical;
  `.md`/`.txt` with pandoc-style `[^n]` footnotes works as a fallback.
- **footnotes** — optional partial pass, e.g. "footnotes 45–80" or a list. Default: whole draft.
- **deep** — optional; heavier verification (medium-effort verify agents, higher soft cap). Turn on
  for a near-final draft or when the user says "deep"/"thorough".
- If the draft has tracked changes, say so and ask whether to accept-all before checking (the parser
  reads the current/accepted text and skips tracked deletions, but a heavily-marked draft is worth a
  heads-up).

### 1b. Ask how deep to go (author's call, 2026-08-09 — mirrors /proofread step 1b)

**Unless the request already settles it, ASK up front** — one `AskUserQuestion`, header `Depth`,
before pre-flight. Fold the tracked-changes heads-up (step 1) into the same call when it applies, so
the user answers everything in one interaction rather than being stopped twice.

**Skip the ask** when the wording already picks a tier ("deep", "thorough", "near-final",
"pre-submission", "quick", "standard"), on a partial re-run of a tier already chosen this session, or
when the user asked only for a narrow footnote range.

Two options — cite-check has no `fable` escalation, so the ladder is shorter than proofread's:

| Option | Args | What to say |
|---|---|---|
| **Standard** | `deep:false` | Verify agents at low effort, soft cap 650k. Good for a working draft. |
| **Deep** | `deep:true` | Verify agents at **medium** effort, soft cap 900k. Closer reading of each quote against its source — for a near-final draft. |

**Do NOT reuse /proofread's rationale here — the two `deep`s are different mechanisms.**
Proofread's deep adds a second offset extraction pass (a recall play, backed by the ~75–80%
same-model overlap finding). Cite-check's deep does **not** add a pass or re-fetch anything: it
raises verify-agent effort from `low` to `medium` (workflow line 557) and lifts the soft cap. It buys
care per quote, not more quotes. Quote *coverage* is identical either way — every quote is checked in
both tiers — so don't imply Standard skips anything.

Timing matters less here than in proofread (deep doesn't change extraction, so a later re-run can
replay segment/existence from cache via `resumeFromRunId`), but verify is the bulk of the run — 26 of
33 agents on the National Muffler draft — so a tier change still means re-running the expensive
stage. Ask first.

### 2. Pre-flight (do this BEFORE launching — a mid-run permission prompt can kill an agent)
1. Read `~/.claude/settings.json`; ensure `permissions.allow` contains `"WebFetch"` and
   `"WebSearch"` (merge in what's missing — never replace the array). Routine setup; don't prompt.
2. Confirm the CourtListener token works. **Test it, don't go looking for a file** — run
   `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/check_cite.py "347 U.S. 483"`; exit 0 with
   `"found": true` means it is working and there is nothing to report. `check_cite.py` resolves
   the token from `COURTLISTENER_API_TOKEN`, then `COURTLISTENER_TOKEN`, then the file
   `~/.config/courtlistener/token` — **in that order**, and the env-var route (commonly set in
   the `env` block of `~/.claude/settings.json`) is the normal install, so a missing
   `~/.config/courtlistener/` directory proves nothing. If the probe actually fails the run
   still works (case existence falls back to web), but mention it once at deliver time.
   Token page: https://www.courtlistener.com/profile/api-token/
3. Resolve the project's Zotero library (projects differ — some are co-authored group libraries,
   some solo personal-library work):
   a. Look for a `Zotero library:` line in the project folder's `CLAUDE.md` (or `AGENTS.md`). If
      present, use the MCP server it names and skip to (c).
   b. If absent, ASK the user which Zotero library this project uses (personal library, or a named
      group library), then record the answer as a `Zotero library: <name> → MCP server <server>`
      line in the project folder's `CLAUDE.md` so future runs don't re-ask.
   c. Confirm that MCP server actually exists (personal = `zotero`; group libraries get their own
      server, e.g. `zotero-group` for "5A general law", group ID in `~/.claude.json`). If the
      project's library has NO server yet, THIS is the moment to offer to add one: duplicate the
      `zotero` entry in `~/.claude.json` under `zotero-<slug>` with `ZOTERO_LIBRARY_TYPE=group` and
      the group's `ZOTERO_LIBRARY_ID` (find it via zotero.org group URL or the draft's field codes);
      note it needs a Claude Code restart, so agents fall back to the web this run.
   d. Pass the server name as `zoteroServer` (and `zotero:false` if no usable server this run).

### 2b. Snapshot the draft (always)
A live OneDrive/Word co-authored file can change between extraction and delivery, which would
make the report describe bytes that were never checked. Copy the draft once, write-protect the
copy, hash it, and run everything downstream off the snapshot. The original path is used here
and nowhere else — never in Workflow args or an agent prompt.

```
cp "<draftPath>" "<scratch>/snapshot.docx" && chmod a-w "<scratch>/snapshot.docx"
shasum -a 256 "<scratch>/snapshot.docx"     # record this; it goes in the report footer
```

### 3. Extract & prepare (deterministic scripts — run these yourself, near-zero tokens)
Put the intermediate JSON somewhere the workflow's agents can read it (the session scratchpad is
fine). Use the installed script paths so this works from any folder (`draftName` stays the
original filename, not "snapshot"):

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/extract_cites.py "<scratch>/snapshot.docx" "<scratch>/extract.json"
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/prepare_units.py "<scratch>/extract.json" "<scratch>/units.json"
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/citation_ledger.py "<scratch>/extract.json" "<scratch>/ledger.json"
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/citation_ledger.py "<scratch>/extract.json" --compact > "<scratch>/ledger_args.json"
```

`citation_ledger.py` prints instance_count / by_kind / unique_secondary_cites / unresolved_xrefs.
Glance at `by_kind`: a large `other` or `text` count means the footnotes use a citation form the
splitter doesn't recognise — those instances still ship in the ledger (as `unchecked` /
`not-a-citation`), so the report stays honest, but say so at deliver time. The `--compact` file
holds the two arrays the workflow takes (`instances`, `secondary`).

`extract_cites.py` prints a summary (footnote_count, body/footnote quote counts, unique_case_cite_count,
supra_problem_candidates, plus `form_findings` / `form_short_form` / `form_typeface` /
`formatting_available` / `case_name_candidates` from the form layer). `prepare_units.py` prints
unit_count / case_cites / supra_problems. Read `extract.json` to pull the arrays the workflow needs:
`unique_case_cites`, `supra_problem_candidates`, and the whole `form_checks` block.

`formatting_available: false` means a markdown/plain-text draft — short forms still run, typeface
does not; say so at deliver time. If `formatting_unaligned_footnotes` appears, that many footnotes
got no typeface analysis (their formatted text didn't match the validated parser's text, so the
layer declined rather than risk misaligned offsets) — mention it only if the count is non-trivial.
For a **partial pass**, resolve the footnote range to unit ids:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/prepare_units.py "<scratch>/extract.json" --footnotes 45-80
```

(prints `unit_ids` — pass them as `unitIds`).

### 4. Launch the workflow

```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/skills/cite-check/cite-check.workflow.js",
  args: {
    skillsDir: "${CLAUDE_PLUGIN_ROOT}/skills",      // where the bundled helper scripts live
    extractPath: "<scratch>/extract.json",      // agents read units + full context from here
    draftName:   "<draft filename without extension>",
    footnoteCount: <extract.footnote_count>,
    unitCount:     <prepare.unit_count>,
    caseCites:     <extract.unique_case_cites>,        // array
    supraProblems: <extract.supra_problem_candidates>, // array
    formChecks:    <extract.form_checks>,              // typeface + short forms (whole block)
    ledger:        <ledger_args.instances>,            // every citation instance (compact form)
    secondaryCites:<ledger_args.secondary>,            // unique unquoted secondary sources
    unitIds:       <null | [ids from --footnotes]>,    // partial pass only
    deep:          false,
    zotero:        true,                               // false if no usable Zotero server this run
    zoteroServer:  "<from pre-flight 2.3>"             // e.g. "zotero-group" (5A) or "zotero" (personal)
  }
})
```

**Pipeline** (all model stages Sonnet except the report, which inherits the session model):
1. **Segment/resolve** — chunked; each quote is paired with the SPECIFIC source it hangs on, walking
   `Id.` chains to their real antecedent (which may be a case two notes up) and following
   `supra note N` redirects, using the antecedent/supra context the prep script assembles. First-page
   U.S. Reports pincites are flagged as *probable* syllabus and routed to the LOC bound volume,
   where the verify agent confirms which section the passage actually sits in.
2. **Existence** — `check_cite.py` over the unique reporter cites (CourtListener paces at
   60/min); "not found" is web-escalated (usually a CL pagination gap for recent U.S. Reports
   volumes, not a bad cite), reporter typos proposed. In the same fan-out, **secondary-source
   existence**: every unique unquoted article/book/statute/URL from the ledger is located
   (Zotero, then web) and its bibliographic metadata compared to the draft's cite — 12 per
   agent, low effort, no substance read. Under budget pressure this pass is skipped and the
   affected instances ship as `unchecked` (never silently).
3. **Verify** — quotes are collapsed onto their **unique source** (a case cited 30 times is fetched
   once) and one agent per source fetches it and checks every quote verbatim, every pincite, and the
   caption/author/title/reporter/year metadata. Verbatim-ness is settled by the **deterministic
   in-file checker** (`scripts/verify_quotes.py`): the agent proposes, the script proves the quote's
   presence in the fetched text (typographic folding, marked ellipses/brackets honored) and reports
   the printed page of the match — agent judgment is reserved for substance. Manuscripts get a **version-drift** check (quote
   present in the cited draft but gone/moved in the current SSRN version → `superseded-source`).
4. **Verify-the-verifier** — a MANDATORY independent re-derivation of every high-severity finding
   (mismatch / not-found / syllabus / superseded) from the full footnote + body sentence, to catch
   the checker artifacts that context-deprivation produces (the practice run had five). Confirmed
   artifacts are dropped; genuine findings are restated with source text.
4a. **Ledger join** — every quote verdict and existence result is joined back onto the citation
   instances (same rules as `citation_ledger.assign_dispositions`, the tested reference). Each
   instance ends with a disposition; `unchecked` is a first-class outcome, not an absence.
4b. **Form** — Bluebook typeface + short forms, decided from the draft alone. The deterministic
   findings arrive precomputed from the extractor, so this phase spends **at most one agent**, and
   only when there is a formatting layer AND case-name candidates to adjudicate (that agent's job is
   to reject the script's positional guesses as much as to confirm them). Runs after re-verify so it
   never competes with verification for budget; under pressure the candidates ship unadjudicated and
   the run records a degradation note.
5. **Report** — a graded, footnote-numbered report in the "needs your attention first" style, with
   a **citation coverage ledger** (section H: counts by disposition + the unchecked / unverifiable /
   unresolved-cross-reference instances listed by footnote) and citation form in their own sections
   near the end.

The run is spend-guarded (soft cap ~650k lean / ~900k deep output tokens) with the legal-research
degradation ladder armed; it runs in the background and notifies on completion.

### 5. Deliver
The workflow returns `{ report, counts, exitState, degradation, artifactsCaught, ledger, … }`.
- Write **`report`** to `<draft's directory>/<draftName> — Cite Check.md` (next to the draft).
- Write the **companion ledger** next to it: save the result's `ledger` array to
  `<scratch>/ledger_final.json`, then
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/citation_ledger.py --render "<scratch>/ledger_final.json" > "<draft's directory>/<draftName> — Citation Ledger.md"`
  — one row per citation instance (note, kind, disposition, cite text). This is the audit trail
  behind section H; `counts.ledger` has the totals for the TL;DR.
- **Research memo header & production footer (required, per the author — global rule in
  ~/.claude/CLAUDE.md):** the report opens directly under the title with the structured
  header block (`Topic:` / `Date:` / `By:`); the `Production details:` block goes at the
  **very end of the file** (after everything else, set off by a `---` rule) — never up
  top. `Date` is local time (`date "+%Y-%m-%d %H:%M %Z"` when writing the file); `By` is
  `Claude-<orchestrating session model>` (exact id); `Production details` names the
  skill, the workflow-agent model(s) actually used (read them off the run's per-agent
  progress entries — don't assume the model map), the wall-clock duration, and the token
  count — from the workflow completion notification's `<usage>` block (`duration_ms`,
  `subagent_tokens`, `agent_count`), labeled subagent output tokens (orchestrator
  overhead not included) — **plus the snapshot's SHA-256** (recorded in step 2b), which
  ties the report to the exact bytes checked. At deliver time also hash the live draft;
  if it no longer matches the snapshot, say so in the deliver message and in the footer
  ("draft edited since snapshot") — the report covers the snapshot, not the new text.
  Example header:
  ```
  Topic: Cite-check of <draft name>
  Date: 2026-07-14 15:05 PDT
  By: Claude-fable-5
  ```
  Example footer (last lines of the file):
  ```
  ---
  Production details: Claude Code /cite-check; 21m 7s; 2,397,252 subagent output
    tokens across 53 agents (workflow agents Claude Sonnet 5 + Claude Opus 4.8 report).
    Draft checked: test draft.docx, SHA-256 3f2a…e91b (report is stale if the hash no
    longer matches the draft).
  ```
- Present the TL;DR counts and point to the "Needs your attention" section.
- If `artifactsCaught` is non-empty, mention it — those are findings the second check disproved, and
  it's a sign the guardrail is working (not something to hide).
- Surface `exitState`: `complete` → deliver; `complete_with_limits` → deliver, noting the
  unverifiable items and any degradation; if the budget guard degraded coverage, say which sources
  were batched/skipped and offer a targeted re-run.
- Offer a **.docx** copy via the bundled converter:
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/md2docx.py "<report>.md" "<report>.docx" "<Title>"`.
- Note once, in the deliver message: free/open-web sources only, so a Westlaw/Lexis pass and a
  manual Bluebook check remain the user's responsibility before publication. Citation *form* now
  gets its own section (short cites + typeface), but signal order, citation order, and cite
  composition are still unchecked.
- `formFindings` / `formConventions` come back alongside the report if you want the raw list.

## Guardrails (inherited house rules — never relax)
- **Never invent authority.** Absence of a match is "not found in the sources checked," never
  "fabricated"; a fabrication/meaning-reversal claim requires the full footnote in view and every
  named source actually searched.
- **Quotes are verbatim or marked.** Honest bracket/ellipsis alterations are matched with the
  alteration masked — that is `altered_marked`, not a mismatch.
- **Never verify from memory.** An unfetchable source is reported unverifiable with its unlock path.
- **Metadata corrections come from the source's own record, never from search snippets or third-party
  listings (the Bressman & Gluck lesson, 2026-10-19).** The existence and verify agents may report a
  "fix" to an author, author order, volume, first page, year or title only after opening the journal's
  page, the PDF's first page, a publisher/catalog record, or a Hein/SSRN citation page, and each such
  line carries a non-empty `[source: …]` tag; untagged discrepancies, and the "confirm: …" notes an
  existence agent leaves on a source it could not pin down, reach the report only under "Confirm". A
  real run told the author to swap the authors of Part II of *Statutory Interpretation from the Inside*
  (66 Stan. L. Rev. 725) on the strength of an opencasebook.org URL slug — the Stanford Law Review page
  shows Bressman & Gluck, and the draft was right. Companion / multi-part articles rotate author order
  and volume between parts; match the exact part cited.
- **Never `open`/GUI-view a PDF; never install software without asking.** PDFs go through
  `fetch_page.py` (hard size cap).
- **Syllabus is not the law.** A pincite equal to the first page of a U.S. Reports cite is
  almost always the syllabus — but that is a flag, not a finding. Confirm against the bound
  volume (LOC scan) which section the passage actually sits in (syllabus, opinion, separate
  opinion) before reporting `syllabus_quote`; then flag it for replacement with the opinion's
  own language even when it is verbatim.
- Case treatment is an approximate negative-treatment glance, not Shepard's/KeyCite — say so.
- **Form findings never outrank substance.** Short-form and typeface items go in their own section
  near the end, never in "Needs your attention": a misquote and an un-italicized signal are not the
  same kind of problem, and mixing them buries the one that matters.
- **No typeface claim without the formatting layer.** On a markdown draft, or for a footnote whose
  formatted text didn't align with the validated parser's text, the answer is silence — not a guess.
