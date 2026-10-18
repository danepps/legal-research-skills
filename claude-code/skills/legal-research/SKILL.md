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
    projectDir: "<the current working directory — enables the local-corpus survey vector;
                  omit only if the cwd is clearly unrelated to the question>"
  }
})
```

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
readers fall back to open-access mirrors — digital commons, author pages, CourtListener/LII —
before giving up, route PDFs through a hard size-capped fetcher, `fetch_page.py`, and extract
posture/limitation/separate-opinions/significance alongside the proposition and quote) → one
session-model draft (guided by the method brief) → a bounded gap-fill (≤3
targeted retrievals plus one retry wave, only if the draft flags missing authorities) → chunked
cite-checks of just the cited authorities (8 per agent; case cites confirmed deterministically via
CourtListener's citation-lookup API, `check_cite.py`, plus a systematic citing-opinions treatment
scan via `cl_case_tools.py citing` — a relevance-ranked treatment-language probe over the case's
actual citing opinions, with a liveness date, replacing the old one-search glance; sources a
reader already opened this run skip existence re-checks) → light finalize. Unselected candidates
AND the authorities each read source itself relies on are carried into the draft as hedged
**unread leads**, so breadth stays wide while fetches stay few. Every run is spend-guarded: a
hardwired soft ceiling (~250k output tokens lean, ~1M deep — raised from 600k on 2026-07-15 after
a deep historical run bound mid-ladder and left 35 of 43 citations unchecked) arms the same
graceful-degradation ladder as an explicit `+500k` budget — trim reads → skip gap-fill → verify
only load-bearing cites — so a runaway run degrades instead of spiraling. Read, gap-fill, and
verify agents all carry an **access-discipline block** (added same date): hard attempt caps,
WebSearch/WebFetch only, and an explicit ban on browser automation, library proxies, and SSO/login
flows — a paywalled source is an honest `opened=false`, not a reason to grind. Models: **Haiku** only for the search-snippet
survey; **Sonnet** for triage, full reads, and verification; **Scope, Draft, and Finalize inherit
the session model** (Fable when Fable is on). `deep:true` (or a `+800k`-style token budget) widens
to up to 7 vectors, raises the read cap to 16, and gives each load-bearing citation (capped at 8)
a **3-vote adversarial refutation pass** (re-opens sources to confirm quotes verbatim). The
workflow runs in the background and notifies you on completion.

### 5. Deliver
The workflow returns `{ memo, exitState, degradation, counts, ... }`.
- **Check `exitState` BEFORE presenting.** `complete` → deliver. `complete_with_limits` → deliver,
  surfacing the documented gaps (listed in `degradation` and the memo's Limits section).
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
- Present the **memo** to the user as the primary deliverable.
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
  output tokens; orchestrator overhead not included). If rescue/fill passes ran after the
  workflow, add their agent counts and note the duration covers the workflow run only.
- Surface the **verification counts** ("N authorities verified, M unverified") so they know how
  much to trust it, and point to the memo's **"Limits of this research"** appendix (which now
  discloses each authority's verification basis: direct-full-text / authoritative-reproduction /
  secondary-corroboration / citation-only).
- The result also carries **`skeleton`** — the citation-tagged analytical outline the draft was
  written from (each load-bearing claim tagged to its finding, holes marked GAP). Don't present it
  by default; offer it if the user wants to audit the reasoning, and use it yourself when editing
  the memo by hand (a claim with no skeleton line needs an authority or a hedge before it grows).
- Offer to save it: Markdown in the working dir; **Word** via the bundled converter —
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
A third error class sits between them: a **central-source omission** — a true "we didn't find it"
mistaken for "it isn't there." The direct-answer coverage cell and the omission audit (above) guard
this: an absence claim about a FIELD requires a search designed to find the thing (specialist title
terms + both-directions citation-chase), not the observation that adjacent abstracts stayed silent.
When editing or extending a memo BY HAND, hold your own prose to the same gate — and before writing
"no scholarship directly addresses X," run the phenomenon-named search yourself.

## Guardrails
- **No hallucinated law.** The workflow only lets the memo cite authorities that an independent
  agent confirmed (in deep mode, that survived adversarial refutation). Preserve that discipline;
  never add cites from memory when relaying or editing.
- **Open-web only.** Coverage is narrower than Westlaw/Lexis and treatment flags
  (KeyCite/Shepard's) are approximated, not authoritative. Always convey this caveat.
- **Not legal advice.** This is research support; final cite-checking and Bluebooking remain the
  user's responsibility. Recommend a paid-database pass before anything is filed or published.
