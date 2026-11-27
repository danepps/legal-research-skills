---
name: find-cite
description: Quick, verified citation-finding for a specific proposition — a footnote-filler, not a research memo. Returns a few Supreme Court cites and/or a few scholarly cites (top scholars in flagship journals preferred; student notes only as a last resort), each verified with a pincite and a parenthetical or quote. Trigger when the user asks "find me a cite for X", "what should I cite for this footnote", "I need authority for the proposition that…", or pastes a sentence with an empty footnote.
---

# Find Cite

A lightweight sibling of `legal-research` for filling out a footnote. The deliverable is a
short, ranked list of **2–4 verified authorities** for one proposition, not a memo. If the
request turns out to need real synthesis across many authorities or an answer to an open
question, say so and offer the full `legal-research` skill instead.

## Why this runs as a workflow

Until 1.6.11 this skill ran inline and told the session to fetch pages itself. In current
Claude Code the main session is not offered `WebFetch` (checked headless on 2026-11-23, with and
without `--restricted`), so the old flow lost its best sources: CourtListener and Justia did not
load, and the one cite it found came back without a confirmed pincite. Workflow agents can call
`WebSearch` and `WebFetch` directly. A workflow also returns **fields** (`cites`, `gaps`,
`counts`, `exitState`) in a file the runtime writes unchanged, so a host program can add each
result to a running citation document without parsing prose. The footnote-ready text (`entry`)
is rendered by the script from the verified fields; no model writes it.

## 1. Parse the request
- **proposition**: the exact sentence or claim needing support (required). If the user pasted
  draft text with a footnote call, the proposition is the sentence the footnote hangs on, not
  the whole paragraph.
- **authorityType**: `cases`, `scholarship` or `both` if the user says which they want (that
  controls); otherwise `auto`. With `auto` the workflow reads the type off the *kind of
  proposition*: pure doctrine ("the Court has held…", black-letter statements, vote lineups) →
  cases; claims about the literature, theory or empirics ("scholars have argued…", "the
  conventional account is…") → scholarship; characterizations of doctrine or the Court ("the
  Court has grown skeptical of…", "this doctrine is famously incoherent") and framing or
  background claims → both. Clear cases are settled by a rule in the script, the rest by one
  small classifier agent, and the result says which and why.
- **constraints**: era, "the canonical cite", "something recent", a particular justice or
  scholar. Pass them as one plain sentence.
- **jurisdiction**: only when it is not the Supreme Court or federal constitutional law (a
  state-law or circuit-specific proposition gets its own controlling authority first).
- **asOfDate**: today's date (YYYY-MM-DD).

Don't ask clarifying questions unless the proposition itself is ambiguous in a way that
changes what would be searched for. Sensible defaults beat a round-trip.

## 2. Zotero (scholarship only, no question asked)
Pass `zoteroServer` only when one library is clearly the right one: the project folder's
`CLAUDE.md` (or `AGENTS.md`) has a `Zotero library:` line naming a server, or
`python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/zotero_servers.py --text --project "<project folder>"`
lists exactly one usable server. Otherwise leave it out: the agents are then told not to touch
Zotero, and you say in the delivery that the library was not searched.

## 3. Launch the workflow
```
Workflow({
  scriptPath: "${CLAUDE_PLUGIN_ROOT}/skills/find-cite/find-cite.workflow.js",
  args: {
    skillsDir: "${CLAUDE_PLUGIN_ROOT}/skills",   // where the shared helper scripts live
    proposition: "<the sentence>",
    authorityType: "auto",                      // or cases | scholarship | both
    constraints: "<optional>",
    jurisdiction: "<optional>",
    asOfDate: "<YYYY-MM-DD>",
    zoteroServer: "<optional MCP server name>"
  }
})
```
`scratchDir` (optional, not shown above) is the folder where the workflow's agents keep their
temporary files; left out, it is `/tmp`. Leave it out unless the program that launched this
session gives you a folder to pass, as one that confines a run to its own folder does.

Pass `args` as a JSON object, never as a JSON-encoded string, and leave out any optional field
you have no value for. The workflow checks its arguments before any agent starts: a missing
`skillsDir` or `proposition`, an unknown `authorityType`, a misspelled argument name, or a
string that does not parse stops it at once with an error that begins `find-cite workflow:` and
names every problem; nothing has been spent. Fix the call and launch once more. Do not fall back
to searching or fetching yourself.

**What it does** (minutes, not tens of minutes):
1. **Scope**: resolve `auto` (rule, else one Haiku classifier with no tools).
2. **Search**: one search-only sweep per lane (Haiku), returning ranked candidates with URLs and
   the snippet language that suggests support. Cases: the controlling authority for the
   jurisdiction, the *canonical* cite first, then one or two reinforcing or recent ones. Scholarship:
   the Zotero library first when named, then the open web, ranked (1) recognized scholars in
   flagship general law reviews and top peer-edited journals, (2) well-cited work in strong
   secondary or specialty journals, (3) **student notes as a last resort only**. Fit comes first: a
   piece squarely on the proposition outranks a famous adjacent one.
3. **Verify** (the heart of it; Sonnet, one agent per candidate: the best 4 for a single lane, or 3 cases and 2 scholarly pieces for
   both, plus
   one top-up round of up to 2 if drops leave fewer than 2):
   - *Cases*: the deterministic lookup (`check_cite.py`); the name search
     (`cl_case_tools.py find`) before anything is called unconfirmed; the opinion opened and the
     passage confirmed to support the proposition, at the pincite, in the majority (a separate
     opinion is labelled); official U.S. Reports pagination where available (Caselaw Access
     Project, CourtListener, LOC scans); treatment glanced at with `cl_case_tools.py citing`, and
     subsequent history for a lower-court case.
   - *Scholarship*: existence and real bibliographic data from the source itself (Zotero record,
     journal page, SSRN, repository, HeinOnline citation page); a pincite or quotation only if
     the text was opened.
   - *Quotations*: an agent may propose one, but the script ships it only on a receipt from
     `scripts/quote_receipt.py`, which runs the cite-check skill's deterministic verifier
     (`verify_quotes.py`) over the fetched text. A quotation without a matching receipt is
     delivered as a paraphrase in the parenthetical, and the entry says so.
   - A pincite ships only if it was seen in the opened source. A source that could not be
     opened is **partially verified** and carries no pincite.
   - A lane delivers its own kind of authority: a request for cases delivers cases only, and
     a source of some other kind that could not be opened is dropped, not listed as partly verified.
   - Anything that fails verification is **dropped and counted**, never smoothed over.
4. **Assemble** in code: rank (verified in full before partial, square support before partial,
   student notes last), render Bluebook citations from the verified fields, state the gaps, and
   build `entry`.

**Caps.** At most **12 agent starts per run**, retries included (a normal run uses at most 10).
A dead agent is retried once; a second death, or anything the cap or the token budget cut, is
recorded in `degradation` and makes the run `complete_with_limits`.

## 4. Deliver
The workflow returns `{ proposition, authorityType, authorityTypeBasis, exitState, degradation,
entry, gaps, counts, cites, dropped }`. `entry` is the whole footnote-ready answer: the
proposition, the ranked cites (each with its source URL, fit, verification level and basis,
treatment, tentative signal, and a student-note flag), the gaps, any limits of the run, and the
counts. It comes early in the result, so the completion notice carries it whole.

- **Print `entry` exactly as returned**, as ordinary Markdown in your reply (not in a code
  block). Do not add, remove or reword authorities, quotations, pincites or parentheticals, and
  do not add authorities of your own from memory. `gaps` is already inside `entry`.
- After it, at most two sentences of your own: that the Zotero library was not searched (when
  no `zoteroServer` was passed), and, when `exitState` is `complete_with_limits`, a pointer to
  the entry's 'Limits of this run' paragraph. If the request looked like it needs a memo, offer
  `legal-research`.
- **Take `entry` from the completion notice, not from the output file.** The plugin's
  quotation check (a Stop hook) does not count a workflow's returned result as a source; it
  finds each quotation in the source passage that `quote_receipt.py` printed inside the
  verifying agent's run. Reading the output file into the conversation would let the result
  vouch for its own quotations, so don't. If the notice somehow cuts `entry` off, say so and
  give the user the output file's path (the result's `entry` field) instead of reading it.
- **If the quotation check blocks your reply** over a quotation from the entry, do not hunt for
  the text yourself: replace that cite's quoted parenthetical with its `paraphrase` from `cites`
  (no quotation marks), and add one sentence saying the quotation was withheld because the
  check could not match it.
- The cites are paste-ready text. Never edit the user's draft unless they explicitly ask you
  to insert them.

A host program reads the same result from the workflow's output file: `entry` to append under
its own heading, and `cites` (ordered best first; each with `kind`, `citation`, `pincite`,
`url`, `support` {`type`: quotation | paraphrase, `text`}, `paraphrase`, `quotationCheck`, `fit`,
`supports`, `verification` {`level`: verified | partial, `basis`}, `treatment`, `studentNote`,
`signal`, `opinionPart`) to show as a list.

## Guardrails
- All global authority rules apply: never invent a case, cite, quote, holding, or
  authorship; quotes are verbatim or marked as paraphrase; uncertainty is flagged plainly.
- Open-web coverage only (no Westlaw/Lexis); no authoritative KeyCite/Shepard's. Treatment is
  a glance at CourtListener's citing opinions, and the entry says when it was not checked.
- Opinions and articles that postdate the model's training data are real; verify them like
  any other, never discount them for being unfamiliar.
- Signals (*see*, *see, e.g.*, *cf.*) are suggested only tentatively; signal choice is the
  user's call.
- Be honest about gaps: if no case squarely supports the proposition, the entry says what the
  closest authority is and how it falls short. A candid 'the strong version of this claim
  isn't citable' is a useful answer.
