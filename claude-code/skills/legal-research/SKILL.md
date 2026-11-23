---
name: legal-research
description: Deep legal research that fans out multiple agents across free legal sources, verifies every authority, and returns a polished, well-cited memo. Use for case-law research, legal-scholarship / literature reviews, or both. Modes — caselaw | scholarship | both. Trigger when the user wants a thorough doctrinal memo, a survey of the academic debate, an answer grounded in cases/statutes, or a research deep-dive on a legal question.
---

# Legal Research

Approximates a deep-research run, specialized for law, and tuned to be **efficient by default**.
It runs a **retrieval pipeline** over **free / open-web legal sources only** (no Westlaw/Lexis);
the stage-by-stage shape, caps, and model map live in step 4, next to the invocation. The design
keeps token use down — the dominant cost in naive fan-out is a frontier model *reading every
fetched page* — while still preventing hallucinated citations. Add **`deep`** (e.g. "do a deep
pass") for high-stakes work where thoroughness beats speed.

## Sources (open web)
Case law: CourtListener, Justia, Google Scholar case law, Cornell LII, Caselaw Access Project,
official court sites. Scholarship: SSRN, Google Scholar, law-school digital-commons repositories,
HeinOnline open content, journal sites, faculty pages. Scholarship modes also search the user's
own Zotero library via the Zotero MCP server (skipped gracefully if unavailable).

## How to run

### 1. Parse the request
Extract from the user's prompt:
- **question** — the legal question (required).
- **mode** — `caselaw`, `scholarship`, or `both`. Default `both`. Infer from wording
  ("what do courts hold" → caselaw; "state of the literature / scholarly debate" → scholarship).
- **outputStyle** — `practitioner` (Question Presented / Brief Answer / IRAC) or `academic`
  (intro / landscape / analysis / footnotes). **Default: practitioner for caselaw, academic for
  scholarship and for both.** Honor an explicit override.
- **jurisdiction**, **asOfDate** (default today), and any **notes** (facts, posture, scope).

### 2. Clarify only if genuinely blocking
If the question is too vague to research well, ask **2–3** targeted questions before launching.
For caselaw, **jurisdiction** and **procedural posture** matter most; for scholarship, the
**specific thesis or sub-question** and any **time window**. Don't over-ask — pick sensible
defaults and note them.

**Enumeration questions are a different job (2026-11-16).** A question that asks for *every*
member of a set ("every opinion Justice X has written on Y", "all the cases citing Z", "each
circuit's rule") cannot be answered by this pipeline as asked: it triages to a fixed number of
full reads (8 lean, 16 deep) however many candidates the search finds, so the memo comes back
describing a sample. On the first live run of this kind the search found 42 candidates, 8 were
read, and the findings about frequency and trend were artifacts of the 8. Before launching, tell
the user so in a sentence or two and settle which of these they want:
- **List first, then read each (the real answer).** Build the list from a source that can
  enumerate (a CourtListener author or citation filter, a database or lead list the user
  already has), show the count, and read every item with one agent per item outside this
  workflow, giving a cost estimate before launching. Then tabulate.
- **A narrower doctrinal question** this pipeline can answer from leading cases ("how does he use
  the common-law canon"), with the memo titled and scoped as leading cases, not a survey.
If the user wants the pipeline run anyway, pass the lead list in `notes` and say in the delivery
message, first, how many of how many were read.

### 3. Pre-flight: ensure web tools are allowed (do this BEFORE launching)
The research subagents call **WebSearch** and **WebFetch** heavily. If those tools are not
pre-allowed, each call raises an interactive permission prompt — and an interrupted prompt can
**kill a research agent mid-run** (a real failure mode: a prior run lost 2 of 4 vectors this way).

Before calling Workflow, make the run self-contained:
1. Read `~/.claude/settings.json` and check `permissions.allow` for `"WebFetch"` and `"WebSearch"`.
2. If either is missing, add it (merge into the existing `allow` array — never replace it; create
   the `permissions.allow` path if absent). If both are already present, do nothing.
3. Don't prompt the user about this — it's routine setup for the skill. (If the file is managed/
   read-only and you can't edit it, tell the user they'll see per-fetch prompts and should accept
   them, or add the rule via `/permissions`.)
4. Optional but worth a glance: deterministic case-cite verification needs a CourtListener API
   token. **Test it, don't go looking for a file** — run
   `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/check_cite.py "347 U.S. 483"`; exit 0 with
   `"found": true` means the token is working and there is nothing to report.
   `check_cite.py` resolves the token from `COURTLISTENER_API_TOKEN`, then
   `COURTLISTENER_TOKEN`, then the file `~/.config/courtlistener/token` — **in that order**,
   and the env-var route (commonly set in the `env` block of `~/.claude/settings.json`) is the
   normal install, so the absence of the file proves nothing. If the probe actually fails,
   don't block the run — verify agents fall back to web checking — but mention it once in the
   deliver step (token page: https://www.courtlistener.com/profile/api-token/).

### 4. Launch the workflow
Call the **Workflow** tool with the bundled script and the parsed args:

```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/skills/legal-research/legal-research.workflow.js",
  args: {
    skillsDir: "${CLAUDE_PLUGIN_ROOT}/skills",      // where the bundled helper scripts live
    question: "<the legal question>",
    mode: "caselaw" | "scholarship" | "both",
    outputStyle: "practitioner" | "academic",
    jurisdiction: "<e.g. federal / 9th Cir. / Missouri / U.S. Supreme Court>",
    asOfDate: "<YYYY-MM-DD or 'today'>",
    notes: "<facts, posture, scope, anything the user emphasized>",
    deep: false,  // true only when the user asks for a deep/thorough/high-stakes pass
    finalizeModel: "opus",  // ONLY when this session's model ranks above Opus (Fable, Mythos); otherwise OMIT the line
    projectDir: "<the current working directory — enables the local-corpus survey vector;
                  omit only if the cwd is clearly unrelated to the question>"
  }
})
```

Pass `args` as a JSON object, exactly as shown, never as a JSON-encoded string. The workflow
checks its arguments before it starts any agent: if they arrive as a string that does not parse,
or `question` is missing, or `mode` or `outputStyle` is not one of the values above, it fails at
once with a message naming the problem and nothing has been spent. When that happens, fix the
call and launch the workflow once more; do not stop the task and do not research without the
workflow.

Lean by default: ~4 search-only survey vectors (plus a Zotero-library sweep in scholarship modes
and a local-corpus sweep of `projectDir` — prior memos and downloaded sources are maps and leads,
never citable authority). Scope also classifies the question (doctrinal vs. scholarly; historical
or not) — that selects an analytical-method brief injected into Draft (synthesis discipline,
holding/dicta hygiene, era-spanning taxonomy for doctrinal-history questions) and, for historical
questions, spreads the search vectors across time layers so coverage doesn't cluster on the
modern canon. **Direct-answer coverage cell (scholarship/both, added 2026-07-16 after a Codex
comparison run beat a 64-agent Claude run on the actual question):** Scope must dedicate at least
one vector to scholarship treating the question's NAMED PHENOMENON as its own object — built from
the specialist title terms an expert expects and including a citation-chase of the most on-point
piece — kept distinct from the adjacent literatures the phenomenon merely belongs to. Survey flags
such central candidates; triage promotes them to full reads ahead of broad adjacent surveys. The
failure this fixes: mapping five adjacent literatures (extrajudicial speech, recusal, celebrity)
while missing the handful of works squarely about the phenomenon (e.g. judicial-autobiography
studies, "justices' book deals" ethics sections), then mistaking that corpus gap for a finding that
"no direct scholarship exists." Absence/gap claims are now gated by a **central-source omission
audit** (in the scholarly method brief): no "no scholarship directly addresses X" unless a
phenomenon-targeted search AND a both-directions citation-chase actually ran — otherwise the claim
is scoped to "in the sources reviewed" and the un-run search is flagged. Fan-out is organized around
coverage cells, and the agent cap is a ceiling, not a quota — nonoverlapping lanes beat many
overlapping generalist searches. Pipeline: survey vectors → dedup → **≤8 unique full reads total** (not per-vector;
readers fall back to open-access mirrors — the journal's own site, author pages, CourtListener/LII —
before giving up, test every candidate URL in one deterministic call first (`probe_sources.py`:
HTTP status, known-host rules for SSRN/bepress/Hein/sign-in walls, Wayback snapshot), route PDFs
through a hard size-capped fetcher, `fetch_page.py`, and extract
posture/limitation/separate-opinions/significance alongside the proposition and quote) → one
session-model draft (guided by the method brief) → a bounded gap-fill (≤3
targeted retrievals plus one retry wave, only if the draft flags missing authorities) → chunked
cite-checks of just the cited authorities (8 per agent; case cites confirmed deterministically via
CourtListener's citation-lookup API, `check_cite.py`, plus a systematic citing-opinions treatment
scan via `cl_case_tools.py citing` — a relevance-ranked treatment-language probe over the case's
actual citing opinions by TWO routes, the citation graph and a full-text search for the case name,
deduplicated to distinct cases, with a liveness date; a cite that will not resolve goes through
`cl_case_tools.py find` (caption search + opinions citing the string) before it is called
unconfirmed; load-bearing lower-court cases also get `cl_case_tools.py history`, the RECAP docket
and later same-litigation opinions; sources a reader already opened this run skip existence
re-checks) → light finalize (returned as edits the script applies; see the Finalize model note
below), whose Table of Authorities carries a **Validation** column per
authority (3-voter refutation panel / checked by existence + treatment probe / not validated) and
one sentence naming which authorities got the panel, because a screened case and a verified case
look identical in prose. Unselected candidates
AND the authorities each read source itself relies on are carried into the draft as hedged
**unread leads**, so breadth stays wide while fetches stay few. Every run is spend-guarded: a
hardwired soft ceiling (~250k output tokens lean, ~1M deep — raised from 600k on 2026-07-15 after
a deep historical run bound mid-ladder and left 35 of 43 citations unchecked) arms the same
graceful-degradation ladder as an explicit `+500k` budget — trim reads → skip gap-fill → verify
only load-bearing cites — so a runaway run degrades instead of spiraling. Read, gap-fill, and
verify agents all carry an **access-discipline block** (added same date): hard attempt caps,
WebSearch/WebFetch only, and an explicit ban on browser automation, library proxies, and SSO/login
flows — a paywalled source is an honest `opened=false`, not a reason to grind. Models: **Haiku** only for the search-snippet
survey; **Sonnet** for triage, full reads, and verification; **Scope and Draft inherit the session model**
(Fable when Fable is on), and so does Finalize unless you pass `finalizeModel`.
**Finalize model (2026-11-16).** Nothing is hard-coded in the script: with no `finalizeModel` a
session on Sonnet or Opus runs every session-model stage on that model. Pass `finalizeModel: "opus"`
only when your own model ranks above Opus (Fable or Mythos, whose use is capped); never pass a
model that ranks above the one you are running on. This is safe because no stage after Draft
retypes the memo any more: the deep calibration pass, Finalize, and the call-in below each return
find-and-replace **edits** that the script applies, so text no edit names stays the Draft's own
words, and the Table of Authorities and Limits sections come back as separate fields. With
`finalizeModel` set, the changes that alter what the memo can claim are not left to the cheaper
model: a load-bearing authority that failed verification (or that no checker examined), negative
treatment of one, an authority verified over a minority objection, and every gap-fill authority
(woven in as a full member of the memo: a table row, updated counts and title, a footnote; one the
cite-check did not confirm is woven in with that stated, never described as unread) go to **one
call on the session model first** (the call-in, `finalize:revise`). It
runs only when the cite-check results contain such an item; `escalate: false` turns it off, and
if it fails or is squeezed out by the budget the Finalize pass applies those items itself. The
result's `finalize` block says which model ran Finalize, whether the call-in ran and for which
authorities, and lists any edit that could not be placed (`unappliedEdits`). Effort is pinned per
call in the script (low for search, reads and cite-checks; medium for Scope, the refutation
voters, the call-in and Finalize; high for Draft and calibration), so nothing inherits the
session's effort setting. `deep:true` (or a `+800k`-style token budget) widens
to up to 7 vectors, raises the read cap to 16, and gives each load-bearing citation (capped at 8)
a **3-vote adversarial refutation pass** (re-opens sources to confirm quotes verbatim; the three
voters lead with different routes — the record, the passage in context, the strongest adverse
reading — meant to reduce correlated omissions; all three still run on the same model, so this is
not independence, and a refutation the majority outvotes is carried into the memo as a disclosed
objection rather than erased). The
workflow runs in the background and notifies you on completion.

### 5. Deliver
The workflow returns `{ memo, exitState, degradation, counts, finalize, ... }`.
- **Check `exitState` BEFORE presenting.** `complete` → deliver. `complete_with_limits` → deliver,
  surfacing the documented gaps (listed in `degradation` and the memo's Limits section). Since
  2026-11-15 those gaps include agent failures that used to leave no trace: a search vector that
  did not run (`counts.surveyLanesFailed`; say which, and treat any absence claim that depended on
  it as untested), a selected source nobody read (`counts.readsFailed`), a citation correction
  only a minority of the panel proposed (`counts.panelDisputedCorrections`; not applied, listed in
  Limits), and panel voters who reported different treatment for the same case
  (`counts.panelTreatmentSplits`; every report is in the memo, and the case needs a citator check).
  `budget_exhausted` → the budget guard cut actual coverage (trimmed reads, skipped gap-fill,
  unchecked cites — see `degradation` for specifics); the memo is not yet the deliverable. The proven
  rescue pattern (July 2026 pre-1960 run): launch targeted read-and-verify Agent passes — one per
  uncovered area, each given the specific cases/quotes to fetch and confirm against official
  reporter text (CAP static.case.law / LOC usrep scans) — then write the final memo yourself from
  the workflow's verified core plus the fill passes. Do not hand the user a memo that says
  "Confidence: insufficient" for half its scope without either filling the gaps or asking.
  **Rescue agents need the same access discipline as workflow agents** (lesson from a July 2026
  scholarship run, where an uncapped rescue agent burned 30+ minutes and ~245k tokens escalating
  to browser automation against a paywalled 1962 article): write into every rescue prompt a hard
  attempt cap (~3 per source), WebSearch/WebFetch only, an explicit ban on browser automation /
  library proxies / SSO flows, and the instruction that "paywalled — here is the strongest basis I
  reached" is a fully acceptable answer. If a rescue agent grinds anyway, SendMessage it to wrap
  up and report rather than waiting it out.
- **Save the memo with the script; never retype it (2026-11-16).** The memo is the primary
  deliverable, and it is delivered as a file. The completion notification names an
  `<output-file>` holding the workflow's result; copy the memo out of it:
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/save_memo.py "<output-file>" "<working dir>/<Title>.md" --header "<Topic/Date/By block>" --footer "<Production details block>"`.
  The script writes the memo byte for byte, puts the header under the title and the footer at the
  very end after a `---` rule (see the header/footer rule below), refuses to overwrite an existing
  file, and prints a summary without the memo's text. If the draft wrote its own `By:` (or
  `Topic:` / `Date:`) line under the title, the header's line replaces it and the summary lists it
  under `replacedHeaderLines`; nothing else in the memo is touched. Do NOT paste the memo into chat and do NOT
  write it out with the Write tool: on a metered session model, retyping a finished memo is the
  largest avoidable cost of delivering it, and a retyped memo can drift from the one that was
  cite-checked. In chat, give the path, the bottom line in a few sentences, the verification
  counts and the limits. If the script exits 1 (no memo found in the output file), fall back to
  writing the memo from the notification's inline result. Later changes to the saved memo are
  made with Edit, never by rewriting the file.
- **Check the memo's quotations by script (2026-11-16).** In lean mode the cite-check confirms
  that each authority exists and is cited correctly; it does not re-open an opinion to confirm
  the words quoted from it or their page. After saving, run
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/check_memo_quotes.py "<saved memo>" --sources "<project dir>" --fetch --append`.
  No model reads anything: the script takes each quotation and the citation it hangs on out of
  the memo, finds a copy of the source (a local PDF or text file whose name carries the reporter
  cite, else a public copy: a URL in the memo's footnote, the Caselaw Access Project page for a
  U.S. Reports cite, CourtListener's API text), runs the cite-check skill's deterministic
  verifier, and writes an addendum table into the memo ahead of the Production details. Omit
  `--sources` when the project has no local copies and `--fetch` to stay offline. Then act on its
  JSON summary, with Edit, never by retyping the memo:
  - `pinDiffers`: the quotation is in the source on a different page from the memo's pin. Correct
    the pin and say in the footnote where the page comes from. A page 'counted' from a local PDF
    is right only if the PDF starts on the report's first page; CourtListener text of a recent
    opinion usually has no reporter pages at all, and then no page is reported.
  - `notFound`: a prompt to look, not proof of a misquotation. Read the `hint` (the closest
    passage in the source). OCR debris in the copy and a footnote falling inside the quoted
    sentence both defeat the match; a changed word is a real finding. Fix the quotation, or tag
    it as unconfirmed, and add a line under the addendum saying which it was.
  - `foundElsewhere`: the words are in a different source the memo cites. For a table cell with no
    footnote that is the expected result; for a footnoted quotation it means a quotation inside a
    quotation or a wrong footnote, and the sentence needs a look.
  - `noSource`: say in the delivery message which cases could not be checked.
  Paraphrases and their pins are not checked by this. Give the counts in the delivery message.
- **Apply any unapplied edits before delivering.** If the summary's `unappliedEdits` is not
  empty (`counts.editsUnapplied` > 0), the checking passes called for changes whose target text
  could not be located. Each entry has `find`, `replace`, `why` and the `reason` it failed. Open
  the saved file, make each change by hand with Edit, then remove the 'Changes not made
  automatically' note from the end of the Limits section. One of them may be the caveat on an
  authority that failed verification, so do not deliver with any outstanding.
- **Say how Finalize ran** in `Production details`: the Finalize model, and whether the
  session-model call-in ran, was not needed, or failed (`finalize.callIn`). If it reads `failed`
  or `skipped (budget)` while `finalize.callInAuthorities` is not empty, the cheaper model made
  the changes for those authorities: re-read the memo's treatment of each one yourself before
  delivering, and say so.
- **Hyperlinks (required, per the author, 2026-08-29):** every news story, blog post, or other web
  source in the memo must carry its working URL as a clickable link — never an outlet-name-only
  attribution like "(Politico)" or "(Roll Call, July 14, 2026)". The workflow's citation block
  enforces this in agent prompts; hold hand-written edits, rescue passes, and any ad-hoc
  (non-workflow) research memos to the same rule, and instruct any rescue/fill agents to return
  the URL for every source they cite (a claim with no URL is unverified).
- **Research memo header & production footer (required, per the author — global rule in
  ~/.claude/CLAUDE.md):** the memo opens directly under the title with the structured
  header block (`Topic:` / `Date:` / `By:`); the `Production details:` block goes at the
  **very end of the file** (after all appendices, incl. "Limits of this research", set
  off by a `---` rule) — never up top. `Date` is the local date/time the memo was
  delivered/written; `By` is `Claude-<orchestrating session model>` (exact id);
  `Production details` names the skill, the workflow-agent model(s) actually used (read
  from the run's per-agent progress entries — don't assume), the wall-clock duration, and
  the token count from the completion notification's `<usage>` block (labeled subagent
  output tokens; orchestrator overhead not included). If you add a billed total from the agent
  transcripts, count each response ONCE: a response is logged on one line per content block and
  every line repeats its usage, so group by `message.id` before summing (a per-line sum doubled
  the figures in the first memo that reported one, 2026-11-16). If rescue/fill passes ran after the
  workflow, add their agent counts and note the duration covers the workflow run only.
- Surface the **verification counts** ("N authorities verified, M unverified") so they know how
  much to trust it, and point to the memo's **"Limits of this research"** appendix (which now
  discloses each authority's verification basis: direct-full-text / authoritative-reproduction /
  secondary-corroboration / citation-only).
- The result also carries **`skeleton`** — the citation-tagged analytical outline the draft was
  written from (each load-bearing claim tagged to its finding, holes marked GAP). Don't present it
  by default; offer it if the user wants to audit the reasoning, and use it yourself when editing
  the memo by hand (a claim with no skeleton line needs an authority or a hedge before it grows).
- The Markdown file is always saved (step above). Offer the other formats: **Word** via the
  bundled converter —
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/md2docx.py memo.md memo.docx "<Title>"`; or Google
  Drive via the connector. If the user asked for .docx up front, just produce it.
- Offer a follow-up pass on any weak/unverified point, or an output-style switch.

## Claim calibration (v7)
Cite-verification and claim-calibration catch disjoint error classes: verification catches false
statements about sources; calibration catches true findings assembled into unsupported
generalizations. The pipeline now enforces both — the Draft prompt carries a claim-strength gate
(frequency/priority/finality words like "first", "only", "overwhelmingly", "erased" require a
search designed to support them, else sample-scoped language), readers tag each source's posture
(including arguendo and nonprecedential dispositions) and bearing (process-only / assumes the
premise / adjacent doctrine), historical runs get selection-bias, boundary-date, and
harm/exclusion checks, and deep runs add a dedicated adversarial calibration pass on the draft.
Two further rules ride in the same brief (added 2026-11-03): repetitions of the same underlying
evidence are not independent corroboration and a head count is not a confidence level (confidence
is assessed from authority, verification basis, independent contributions, contrary evidence and
coverage); and for each material contested issue the counter-position is stated at full strength,
as its proponent would put it, never as the conclusion re-hedged. Finalize then runs a
**consistency audit** across sections — Brief Answer, Discussion, Conclusion and Limits must tell
one story, and the summary sections are fixed to match the Discussion and the cite-check results,
never the reverse.
A third error class sits between them: a **central-source omission** — a true "we didn't find it"
mistaken for "it isn't there." The direct-answer coverage cell and the omission audit (above) guard
this: an absence claim about a FIELD requires a search designed to find the thing (specialist title
terms + both-directions citation-chase), not the observation that adjacent abstracts stayed silent.
When editing or extending a memo BY HAND, hold your own prose to the same gate — and before writing
"no scholarship directly addresses X," run the phenomenon-named search yourself.

## Guardrails
- **No hallucinated law.** Every authority the memo cites goes to a cite-check, and the Table of
  Authorities says what each one got. That is not the same as "every cite was independently
  confirmed": an authority a checker could not confirm stays only with an explicit caveat, one
  the budget left unchecked is tagged as such, and a source a reader opened this run is checked
  for citation form and treatment but its quote is not re-read (its basis is reported as a
  reproduction resting on the research read). In deep mode the load-bearing authorities also face
  the refutation panel. Preserve that discipline; never add cites from memory when relaying or
  editing.
- **Open-web only.** Coverage is narrower than Westlaw/Lexis and treatment flags
  (KeyCite/Shepard's) are approximated, not authoritative. Always convey this caveat.
- **Opinions, articles and dockets that postdate the model's training data are real.** A 2025 or
  2026 decision nobody recognizes is not a hallucination signal; the fetched record is.
- **Say which tier each authority got.** When editing a memo by hand, keep the Validation labels
  in the Table of Authorities and never let an unlabeled list read as "all verified".
- **Not legal advice.** This is research support; final cite-checking and Bluebooking remain the
  user's responsibility. Recommend a paid-database pass before anything is filed or published.
