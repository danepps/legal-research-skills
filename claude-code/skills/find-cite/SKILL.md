---
name: find-cite
description: Quick, verified citation-finding for a specific proposition — a footnote-filler, not a research memo. Returns a few Supreme Court cites and/or a few scholarly cites (top scholars in flagship journals preferred; student notes only as a last resort), each verified with a pincite and a parenthetical or quote. Trigger when the user asks "find me a cite for X", "what should I cite for this footnote", "I need authority for the proposition that…", or pastes a sentence with an empty footnote.
---

# Find Cite

A lightweight sibling of `legal-research` for filling out a footnote. The deliverable is a
short, ranked list of **2–4 verified authorities** for one proposition — not a memo. Run it
**inline** (no Workflow): a handful of searches, roughly ≤6 page fetches total, minutes not
tens of minutes. If the request turns out to need real synthesis across many authorities or
an answer to an open question, say so and offer the full `legal-research` skill instead.

## 1. Parse the request
- **proposition** — the exact sentence or claim needing support (required). If the user
  pasted draft text with a footnote call, the proposition is the sentence the footnote hangs
  on, not the whole paragraph.
- **authority type** — read it off the *kind of proposition*, not off a default. The ideal
  answer is a few of each **when the proposition genuinely supports both**; don't force a
  category that doesn't fit.
  - **Pure doctrine** ("the Court has held…", black-letter statements, vote lineups) →
    cases; add a scholarly cite only if a well-known article states the rule crisply or is
    the standard synthesis.
  - **Claims about the literature, theory, or empirics** ("scholars have argued…", "the
    conventional account is…") → scholarship; a case belongs only if it's the doctrinal
    anchor the literature is reacting to.
  - **Characterizations of doctrine or the Court** ("the Court has grown skeptical of…",
    "this doctrine is famously incoherent") → both: cases as the primary evidence, plus a
    scholar making the same observation.
  - **Framing/background claims** → both, lightly — one or two of each.
  If the user says which they want, that controls. When the mix is a judgment call, note in
  the answer why you leaned the way you did.
- **constraints** — era, "the canonical cite," "something recent," a particular justice or
  scholar, jurisdiction other than SCOTUS. Honor them.

Don't ask clarifying questions unless the proposition itself is ambiguous in a way that
changes what you'd search for. Sensible defaults, noted in the answer, beat a round-trip.

## 2. Search (lean)
**Cases.** Prefer the authority that controls in the proposition's jurisdiction and supports
it directly. For federal constitutional and SCOTUS-focused work that is usually the Supreme
Court; a state-law or circuit-specific proposition gets its own controlling authority first,
not a looser Supreme Court analogy. For well-worn propositions there is usually a
*canonical* cite (the case everyone cites); find that one first — WebSearch phrasing like
`"<proposition keywords>" Supreme Court held` or searching the proposition's signature quote
works well — then one or two reinforcing or more recent cites. Sources: CourtListener,
Google Scholar case law, Justia, Cornell LII, official slip opinions.

**Scholarship.** Search the **Zotero library first** (`mcp__zotero__zotero_search_items`) —
the user may already own the right article, and a library record gives reliable
bibliographic metadata. It is still only a candidate: open the text for any pincite or
quote. Then Google Scholar, SSRN, and law-school digital commons. Ranking:

1. Recognized scholars in **flagship general law reviews** (Harvard, Yale, Stanford,
   Columbia, Chicago, NYU, Michigan, Penn, Virginia, California, Georgetown, Duke,
   Northwestern, Cornell, Texas, Vanderbilt) and top peer-edited journals
   (*Supreme Court Review*, *Journal of Legal Studies*, *Journal of Legal Analysis*).
2. Well-cited work in strong secondary or specialty journals.
3. **Student notes — last resort only.** Cite one only when nothing better exists, and
   label it as a Note in the answer so the user can decide.

Fit comes first: a piece squarely on the proposition outranks a famous one that is merely
adjacent. Among sources that genuinely fit, prefer the more influential author and venue;
Google Scholar citation counts are a fine proxy when unsure.

**Parallelize when it helps.** For `both` mode, two concurrent `general-purpose` Agent
sweeps (one cases, one scholarship, each told to return candidates *with URLs and the
supporting language*) beat serial searching — but keep each agent lean and capped. For a
single-type request, just search inline.

## 3. Verify (non-negotiable)
An unverified cite never ships — that rule is identical to the full skill's.

- **Cases:** run every candidate through the deterministic lookup:
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/check_cite.py "<vol> U.S. <page>" …`
  (falls back to web verification if no CourtListener token). A cite that does not resolve is
  a search problem, not a bad cite: run
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/cl_case_tools.py find "<case name>" --cite "<cite>"`
  before concluding anything. For a case doing load-bearing work, glance at treatment with
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/cl_case_tools.py citing "<cite>" --limit 10`
  (two routes, deduplicated; a flagged row means open that case, not "treatment confirmed") and,
  for a lower-court case, subsequent history with `… cl_case_tools.py history "<cite>"` so the
  delivered cite carries its aff'd / rev'd / cert. denied line. Then **open the opinion** and
  confirm the passage actually supports the proposition, at the pincite, in the majority
  (not a dissent/concurrence unless flagged). Pincite to official U.S. Reports pagination
  where available (CourtListener, CAP `static.case.law`, LOC usrep scans).
- **Scholarship:** confirm the article exists and get the real journal/volume/first-page
  from the actual source (Zotero record, journal page, SSRN, digital commons, HeinOnline
  citation page). If quoting or giving a pincite, open the text and copy verbatim. If only
  the article's existence and general thesis can be confirmed — not the specific page —
  deliver it without a pincite and say so.
- Anything that fails verification is dropped or explicitly flagged, never smoothed over.

## 4. Deliver
Short and footnote-ready, best cite first:

- Full **Bluebook cite with pincite** for each authority.
- A **clickable URL** to the source consulted (CourtListener/CAP opinion, SSRN/repository,
  journal page) after each cite — per the author, sources cited without links are "not helpful".
- A **parenthetical or verbatim quote** (quotes only if actually copied from the source —
  paraphrases go unquoted).
- One line on **fit** (canonical cite / recent reaffirmation / leading article / *student
  note — only authority found*).
- **Verification basis** in a word or two, honest about how thin it is: *opened at the
  pincite* is full verification; *CourtListener + snippet* or *Zotero + journal page*
  confirms existence and metadata only — label such a cite partially verified and give it
  no pincite you did not see.

Then be honest about gaps: if no SCOTUS case squarely supports the proposition, say what
the closest authority is and how it falls short — a candid "the strong version of this
claim isn't citable" is a useful answer. Deliver the cites as paste-ready text; never edit
the user's draft unless they explicitly ask you to insert them.

## Guardrails
- All global authority rules apply: never invent a case, cite, quote, holding, or
  authorship; quotes are verbatim or marked as paraphrase; uncertainty is flagged plainly.
- Open-web coverage only (no Westlaw/Lexis); no authoritative KeyCite/Shepard's — for a
  case doing load-bearing work, glance for negative treatment and say if you didn't.
- Opinions and articles that postdate the model's training data are real; verify them like
  any other, never discount them for being unfamiliar.
- Suggest signals (*see*, *see, e.g.*, *cf.*) only tentatively — signal choice is the
  user's call.
