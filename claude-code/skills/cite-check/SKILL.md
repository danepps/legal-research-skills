---
name: cite-check
description: Verify every citation and quotation in an article draft against the real sources — cases via CourtListener + official reporters, scholarship via the user's Zotero library then the open web — and return a graded, footnote-by-footnote report with a "needs your attention" section first, an advisory subsequent-history and treatment section (Bluebook R. 10.7 history the draft omits; cases a later decision overruled or limited), a "since the last report" diff on re-runs, plus a citation-form section (short cites per Bluebook R. 10.9/4.2 and italics/small caps per R. 2.1(a)) decided from the draft alone, and an OPT-IN proposition-support pass that reads each unquoted cite at its pincite and says whether it supports the sentence it hangs on (overstatement is reported as a confirm item, never an error). Trigger when the user wants a draft cite-checked ("cite-check this", "check the citations/quotes in this draft", "run cite-check on <file>"). Input: a .docx with real Word footnotes (markdown/plain-text fallback). Not a full Bluebook linter — signal order, citation order and cite composition stay out.
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
marked (and spoken by whom the draft says — a court reciting a party's position is not the court
holding it), supra/id. cross-references are intact, URLs are live, and — advisory, in its own
section — whether a lower-court case carries the subsequent history Bluebook R. 10.7 requires
(aff'd / rev'd / vacated / cert. denied) and whether a later decision has overruled or limited a
cited case. History comes from the RECAP docket (everything filed after the decision) and later
same-litigation opinions on CourtListener; treatment from a two-route citing-opinion probe. Neither
is Shepard's/KeyCite and the report says so.

**Coverage ledger (added 2026-09-06) — and what is still NOT checked.** Quote-verification
units are built from *quotations*; on their own they left every unquoted secondary source
unaccounted for. Now `scripts/citation_ledger.py` inventories **every citation instance** in
every footnote (case or secondary, quoted or not, with `Id.`/`supra`/short-form chains
resolved), a secondary-source existence pass covers the unquoted articles/books/statutes/URLs,
and the report's section J gives each instance a disposition — `verified`, `finding`,
`existence-only`, `unverifiable`, `unchecked`, `xref`, `unresolved-xref`, plus the support
pass's `supported` / `support-confirm` / `support-finding` / `support-unverifiable` — and lists
the unchecked ones by footnote. Two limits remain and the report must say so: (1) **proposition
support** — whether an unquoted cite actually stands for the sentence it hangs on — is assessed
ONLY when the opt-in support pass runs (below); otherwise `existence-only` means exactly that;
(2) pincites are checked only where a quotation anchors them, or where the support pass read
the page. Treat `existence-only` as "real source, unread," never as "passed."

**Proposition support (OPT-IN, added 2026-10-24).** With `support:true`, every unquoted citation
instance the ledger inventories becomes a *support unit*: the body sentence its footnote marker
sits in (or, for a mid-sentence marker, the clause before it), the full footnote, its Bluebook
signal, its pincite (a bare `Id.` inherits its antecedent's page; a bare `Author, supra note N`
does not — it is the whole work), its proposition parenthetical and any separate-opinion note the
draft gives. `scripts/prepare_support_units.py` builds them deterministically. An agent fetches
each source once (a source a verify agent already fetched for a quote gets its support units
folded into that agent), reads the pincited page with `verify_quotes.py --page`, and judges the
claim **through its signal** (a `but see` cite claims contrary authority; `cf.` claims analogy;
`see generally` claims background). Verdicts: `supported`, `supported_qualified` (support from a
posture the draft does not disclose — dicta, a concurrence, a reported view; advisory),
`overstated` (**a confirm item by the author's decision — the source supports a narrower or
weaker claim; never called an error, never in "Needs your attention"**), `not_supported` (medium),
`contradicted` (high), `unverifiable`, `unread`. Every `not_supported` / `contradicted` verdict
goes through the same independent second derivation as a high-severity quote finding before it
reaches the report; the report shows the draft's claim and the source's passage side by side.
Default scope is **pincited** instances (a page, section, URL or parenthetical to read); bare
whole-work cites are listed as not read unless `supportScope:"all"`. Quoted instances are not
support units (the quote path, with its fragment-framing judgment, covers them). **Cost (measured,
2026-10-26, read off the agent transcripts 2026-10-27):** the first live run with the pass
reported 1,989,264 subagent tokens on footnotes 1–30 of a 293-note draft, 34 agents. Output tokens
were not the cost (278k for the run, in line with the budget gates, which were right not to
close); the cost was 486 agent turns, each re-reading 50–60k of context, and the turn-heavy agents
were the ones searching Zotero by hand (12 searches per existence batch, three libraries per
verify agent) and trying repository URLs one at a time. Since then the Zotero work is done once,
deterministically, before launch (step 3), every agent carries a tool-call budget, batches are
smaller, and the gates project cost per agent kind in a unit the transcripts measure afterwards
(`scripts/run_usage.py`) instead of reading output tokens. The soft cap rises by 3M when the pass is on.
Step 3a says how to state the expected cost before launching.

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
- **support** — optional, OFF by default. Turn on when the user asks whether the cites actually
  support their propositions ("check that the sources support what I cite them for", "check
  proposition support", "do the signal cites hold up", "support pass"). Never infer it from
  "deep" or "thorough" — deep buys care per quote, support buys a different check with a
  different cost (see above); when the user asks for support on a long draft, say in one
  sentence that it reads every pincited unquoted cite and give the step 3a estimate. `supportScope:"all"` additionally reads bare whole-work cites; only when the
  user asks for that explicitly.
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
| **Standard** | `deep:false` | Verify agents at low effort, soft cap 4M input-equivalent tokens (+3M with support). Good for a working draft. |
| **Deep** | `deep:true` | Verify agents at **medium** effort, soft cap 6M input-equivalent tokens (+3M with support). Closer reading of each quote against its source — for a near-final draft. |

**Do NOT reuse /proofread's rationale here — the two `deep`s are different mechanisms.**
Proofread's deep adds a second offset extraction pass (a recall play, backed by the ~75–80%
same-model overlap finding). Cite-check's deep does **not** add a pass or re-fetch anything: it
raises verify-agent effort from `low` to `medium` and lifts the soft cap. It buys
care per quote, not more quotes. Quote *coverage* is identical either way — every quote is checked in
both tiers — so don't imply Standard skips anything.

Timing matters less here than in proofread (deep doesn't change extraction, so a later re-run can
replay segment/existence from cache via `resumeFromRunId`), but verify is the bulk of the run — on
a real draft roughly three agents in four — so a tier change still means re-running the expensive
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
3. Resolve the project's Zotero library, if the user has one (Zotero is optional; without it
   scholarship is checked against the open web):
   a. Look for a `Zotero library:` line in the project folder's `CLAUDE.md` (or `AGENTS.md`). If
      present, use the MCP server it names and skip to (c).
   b. If absent and a Zotero MCP server is registered, ASK the user which Zotero library this
      project uses (personal library, or a named group library), then record the answer as a
      `Zotero library: <name> → MCP server <server>` line in the project folder's `CLAUDE.md` so
      future runs don't re-ask. If no Zotero server is registered at all, don't ask — pass
      `zotero:false` and move on.
   c. Confirm that MCP server actually exists (`/legal-research:setup` registers a personal
      library as `zotero` and a group library as `zotero-<name>`). If the project's library has
      no server yet, offer to add it through `/legal-research:setup`; it takes effect after a
      Claude Code restart, so agents fall back to the web this run.
   d. Pass the server name as `zoteroServer` (and `zotero:false` if no usable server this run).
   e. The deterministic pre-lookup in step 3 reads the same `mcpServers` entries (API key and
      library id) from `~/.claude.json`, so it needs nothing more. Pass it the project's server
      first and any other registered Zotero server the user's sources may live in (a personal
      library beside a group's); it searches them in that order.

### 2a. Look for the previous report (re-runs)
If `<draft's directory>/<draftName> — Cite Check (Claude) findings.json` exists, this is a re-run
after edits: keep that path for step 5, where the new report opens with what changed. Nothing
else to do now; the run itself is identical. (Runs before 2026-10-27 wrote
`<draftName> — Cite Check findings.json`, the name the Codex skill's report also uses; if only
that older file exists, use it as the previous run this once — step 5 writes the new name from
now on and leaves the old file alone.)

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

With `support:true`, also build the support units (zero model tokens):

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/prepare_support_units.py "<scratch>/extract.json" "<scratch>/support_units.json"
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/prepare_support_units.py "<scratch>/extract.json" --compact > "<scratch>/support_args.json"
```

**Zotero pre-lookup (2026-10-27; whenever a Zotero server exists, support on or off).** One
deterministic pass matches every article/book the draft cites to the user's Zotero libraries,
compares the record's metadata to the cite, downloads each match's PDF attachment and extracts its
text to a file. It replaces every Zotero search an agent used to make, and the agents are told so
per source (text already on disk, or not in Zotero at all). Run it with the project's server first
and any other registered Zotero server the sources may live in:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/zotero_lookup.py "<scratch>/zotero_lookup.json" \
    --server <zoteroServer> [--server zotero ...] \
    --secondary "<scratch>/ledger_args.json" --support "<scratch>/support_args.json" \
    --cache-dir "<scratch>/zotero-cache"
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/zotero_lookup.py "<scratch>/zotero_lookup.json" --compact > "<scratch>/zotero_hits.json"
```

(`--support` only with `support:true`; without it the support units file does not exist.) It
prints `{sources, matched, withText, unmatched, downloads}`; the first run on a 1,453-item
library took about three and a half minutes, nearly all of it PDF downloads, and a re-run in the
same cache dir is seconds (library dumps and texts are reused). Say the match count at deliver
time; `unmatched` sources are checked on the web as before. The `--compact` file is the map the
workflow takes as `zoteroHits`; pass the report path as `zoteroLookupPath`. If no Zotero server
is registered, skip this and pass `zotero:false`; the agents are then told not to search Zotero.

The first prints `unit_count`, `in_scope_pincited`, `whole_work`, `by_kind`, `unique_sources`,
`units_without_anchor`. Glance at `whole_work`: those are bare cites to an entire work that the
default scope will NOT read — say the number at deliver time. `units_without_anchor` should be
0; a non-zero count means footnote markers the body parser could not place (the extractor
warns). The `--compact` file holds the `units` array the workflow takes as `supportUnits`.
For a partial pass, `--footnotes 45-80` prints the support unit ids for those notes (the
workflow still takes the whole `supportUnits` array; restrict with `unitIds` only for quotes —
support units outside the chosen footnotes are simply not in scope when you pass a filtered
`supportUnits` array, so filter the compact list to those ids yourself).

`citation_ledger.py` prints instance_count / by_kind / unique_secondary_cites / unresolved_xrefs.
Glance at `by_kind`: a large `other` or `text` count means the footnotes use a citation form the
splitter doesn't recognise — those instances still ship in the ledger (as `unchecked` /
`not-a-citation`), so the report stays honest, but say so at deliver time. The `--compact` file
holds the two arrays the workflow takes (`instances`, `secondary`).

`extract_cites.py` prints a summary (footnote_count, body/footnote quote counts, unique_case_cite_count,
supra_problem_candidates, plus `form_findings` / `form_short_form` / `form_typeface` /
`formatting_available` / `case_name_candidates` from the form layer). `prepare_units.py` prints
unit_count / case_cites / supra_problems / unit_notes (the id → footnote list the workflow takes as
`unitNotes`). Read `extract.json` to pull the arrays the workflow needs:
`unique_case_cites`, `supra_problem_candidates`, and the whole `form_checks` block.

`formatting_available: false` means a markdown/plain-text draft — short forms still run, typeface
does not; say so at deliver time. If `formatting_unaligned_footnotes` appears, that many footnotes
got no typeface analysis (their formatted text didn't match the validated parser's text, so the
layer declined rather than risk misaligned offsets) — mention it only if the count is non-trivial.
For a **partial pass**, resolve the footnote range to unit ids:

```
python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/prepare_units.py "<scratch>/extract.json" --footnotes 45-80
```

(prints `unit_ids` — pass them as `unitIds`). The report then titles itself "partial pass —
footnotes 45–80 of N" and its counts describe that range only; say the same in the deliver
message, and label the report file for the range if a whole-draft report already sits next to
the draft (a partial findings file would otherwise overwrite it and reset the re-run diff).

### 3a. Say what it will cost before launching (2026-10-27)

The workflow's gates **project** the run's cost from a per-agent-kind model. The unit is
**input-equivalent tokens**: uncached input + cache writes + cache reads ÷ 10 + output × 5, the
Sonnet price ratios, so 1M is about three dollars at Sonnet rates; `scripts/run_usage.py` measures
it from the run's transcripts afterwards (step 5). (Neither figure the runtime offers is a cost:
`budget.spent()` is output tokens, a few percent of this unit, and the completion notification's
`subagent_tokens` is the sum of each agent's peak context — checked on two runs — which grows
with agent count, not with work.) The model, overridable per kind through the `costModel` arg,
from the 2026-10-26 and 2026-10-27 runs (the second measured 5.28M against 5.08M projected): a
verify agent 150k from the web or 80k when Zotero put the text on disk; a dedicated support
agent 200k web / 100k Zotero; a verify tail batch (4 single-quote web sources) 130k and a
support tail batch (3 single-unit web sources) 210k; a secondary-existence batch of 5 web
sources 130k (sources matched in Zotero cost no agent); a case-existence batch of 30 cites 90k;
a history batch of 8 cases 110k; segmentation 150k per chunk; re-verification 100k per finding;
form 130k; the report 250k. Before step 4, add it up
from the counts the scripts printed (`unit_count` quotes, whose unique sources are fewer, often
by half; `unique_secondary_cites` less the Zotero `matched`; `unique_case_cite_count`; with
`support:true` the support `unique_sources` less those with Zotero text) and tell the user in
one sentence roughly how many agents and tokens to expect against the soft cap (4M standard /
6M deep, +3M with support; a 30-footnote run with support fits, a full draft usually does not).
If the projection exceeds the cap, say so plainly: the run degrades *before* launching the
phase that would not fit (the ladder in DESIGN.md — whole-work units, then secondary sources,
then the pass), lists every unit it did not read, and a `+Nk` budget written in the user's
request (for example `+20000k`) raises the cap to N in the same unit. Do not launch a run you
expect to degrade without having said so; do not pad the estimate either — the footer shows the
measured figure beside the projection, and a re-run on a cached `resumeFromRunId` replays the
cheap phases.

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
    unitNotes:     <prepare.unit_notes>,               // [[id, footnote], …] — labels findings by note
    caseCites:     <extract.unique_case_cites>,        // array
    supraProblems: <extract.supra_problem_candidates>, // array
    formChecks:    <extract.form_checks>,              // typeface + short forms (whole block)
    ledger:        <ledger_args.instances>,            // every citation instance (compact form)
    secondaryCites:<ledger_args.secondary>,            // unique unquoted secondary sources
    unitIds:       <null | [ids from --footnotes]>,    // partial pass only
    deep:          false,
    history:       true,                               // false only if the user asks to skip subsequent history / treatment
    support:       false,                              // OPT-IN: true only when the user asks for proposition support
    supportUnits:  <support_args.units>,               // with support:true — prepare_support_units.py --compact
    supportScope:  "pincited",                         // "all" also reads bare whole-work cites (explicit request only)
    zotero:        true,                               // false if no usable Zotero server this run
    zoteroServer:  "<from pre-flight 2.3>",            // e.g. "zotero-group" (5A) or "zotero" (personal)
    zoteroHits:    <zotero_hits.json>,                 // the --compact map from the pre-lookup (step 3); {} if none
    zoteroLookupPath: "<scratch>/zotero_lookup.json",  // agents read the full record of a matched source from it
    costModel:     undefined,                          // optional per-kind overrides, e.g. { verify: 60000 } (step 3a)
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
   60/min). A cite that does not resolve is a search problem, never evidence of a bad cite:
   CourtListener's citation metadata is uneven and a case can be present with no reporter cite
   attached, so the agent runs `cl_case_tools.py find` (caption search, plus a search for later
   opinions whose text cites the citation string, which proves the cite real even when the
   opinion itself is not indexed) BEFORE any web escalation; reporter typos proposed. In the same
   fan-out, **secondary-source existence**: every unique unquoted article/book/statute/URL from
   the ledger that the Zotero pre-lookup did not match is located on the web and its
   bibliographic metadata compared to the draft's cite — 5 per agent, low effort, no substance
   read; a source the pre-lookup matched is settled without an agent, its record as the basis and
   any draft-vs-record difference as a "confirm" note. Under budget pressure this pass is
   skipped and the affected instances ship as `unchecked` (never silently).
2b. **History** (added 2026-10-19) — for every case cite that exists: lower-court cases get
   `cl_case_tools.py history` (the RECAP docket's entries after the decision date, with the
   dispositive ones flagged — notice of appeal, USCA judgment, mandate, cert. granted/denied,
   amended or substituted opinion, reconsideration, vacatur — plus later same-litigation
   opinions, i.e. the reviewing court's decision), and every case gets the two-route
   `cl_case_tools.py citing` treatment probe. A **finding** is a draft cite with no history
   words whose record shows an outcome R. 10.7 requires, or stated history the record
   contradicts; **treatment flags** (a later case says this one was overruled / abrogated /
   limited) are reported separately because the draft may cite the case as history or as a
   foil. Eight cases per agent, low effort; `history:false` skips it; under budget pressure it
   is skipped and the report says so. Advisory throughout: RECAP is crowd-sourced, incomplete
   and federal-only; docket text is the clerk's language; Supreme Court dockets are not on
   PACER; no hits is not proof of good law.
3. **Verify** — quotes are collapsed onto their **unique source** (a case cited 30 times is fetched
   once) and one agent per source fetches it and checks every quote verbatim, every pincite, the
   caption/author/title/reporter/year metadata, and **attribution** (the words are in the source,
   but is the source quoting a party, a dissent or another case where the draft says "the Court
   held"? — verdict `misattributed`, medium). Verbatim-ness is settled by the **deterministic
   in-file checker** (`scripts/verify_quotes.py`): the agent proposes, the script proves the quote's
   presence in the fetched text (typographic folding, marked ellipses/brackets honored) and reports
   the printed page of the match — agent judgment is reserved for substance. Manuscripts get a **version-drift** check (quote
   present in the cited draft but gone/moved in the current SSRN version → `superseded-source`).
3b. **Support** (opt-in, 2026-10-24) — the support units whose source a verify agent fetched
   anyway were already judged inside that agent; the rest are bundled by unique source (one
   agent per multi-unit source, three single-unit sources per agent) and read at the pincite
   with `verify_quotes.py --page`, medium effort (a judgment, never low) — straight from the
   file the Zotero pre-lookup extracted when it matched the source, from the web otherwise. Under budget pressure
   it degrades in order — whole-work units (if `all`), then secondary sources, then the whole
   dedicated pass — and every skipped unit is disclosed as not read.
4. **Verify-the-verifier** — a MANDATORY independent re-derivation of every high-severity finding
   (mismatch / not-found / syllabus / superseded) from the full footnote + body sentence, to catch
   the checker artifacts that context-deprivation produces (the practice run had five). Confirmed
   artifacts are dropped; genuine findings are restated with source text. With the support pass
   on, every `not_supported` / `contradicted` verdict gets the same second derivation, checking
   the support-specific artifact classes (a paraphrased claim, a misread signal, the clause vs the
   sentence, the wrong antecedent or page, undisclosed posture).
4a. **Ledger join** — every quote verdict and existence result is joined back onto the citation
   instances (same rules as `citation_ledger.assign_dispositions`, the tested reference). Each
   instance ends with a disposition; `unchecked` is a first-class outcome, not an absence.
4b. **Form** — Bluebook typeface + short forms, decided from the draft alone. The deterministic
   findings arrive precomputed from the extractor, so this phase spends **at most one agent**, and
   only when there is a formatting layer AND case-name candidates to adjudicate (that agent's job is
   to reject the script's positional guesses as much as to confirm them). Runs after re-verify so it
   never competes with verification for budget; under pressure the candidates ship unadjudicated and
   the run records a degradation note.
5. **Report** — a graded, footnote-numbered report in the "needs your attention first" style: a
   TL;DR that states the existence-only share in one sentence (and the support counts when the
   pass ran), the findings sections A–F, a **subsequent history & treatment** section (G,
   advisory), **proposition support** (H: not supported / confirm: possible overstatement /
   qualified support, or one sentence that the opt-in pass did not run; contradicted items go
   in A), couldn't-check (I), a **citation coverage ledger** (section J: counts by disposition +
   the unchecked / unverifiable / unresolved-cross-reference instances listed by footnote) and
   citation form in their own sections near the end.

The run is spend-guarded (soft cap 4M standard / 6M deep, +3M with support, input-equivalent
tokens projected per agent kind — step 3a) with the legal-research degradation ladder armed; it
runs in the background and notifies on completion.

### 5. Deliver
The workflow returns `{ report, counts, exitState, degradation, artifactsCaught, ledger, history,
support, findings, spend, … }`.
- **Re-run diff first (when step 2a found a previous findings file).** Save the result's
  `findings` object to `<scratch>/findings_new.json` with two fields added at the top level:
  `"snapshotSha256"` (from step 2b) and `"date"` (local date). Then
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/findings_diff.py "<previous findings.json>" "<scratch>/findings_new.json"`
  prints a "Since the last report" block (new / still open / resolved, keyed by content so a
  renumbered draft does not reset the count; support findings from a previous run are listed as
  "not rechecked", never resolved, when this run's support pass did not run or ran at a
  different scope). Insert that block into the report immediately after the TL;DR, before
  section A. Lead the deliver message with its three counts.
- Write **`report`** to `<draft's directory>/<draftName> — Cite Check (Claude).md` (next to the
  draft). The "(Claude)" tag is deliberate and never dropped: the Codex cite-check skill publishes
  its report as `<Draft name> — Cite Check.md` in the same folder, and the two must never
  overwrite each other (author's rule, 2026-10-27).
- Write the findings file for next time: `<draft's directory>/<draftName> — Cite Check (Claude) findings.json`
  (the same object, with `snapshotSha256` and `date`; overwrite the previous one — the diff has
  already been taken).
- Write the **companion ledger** next to it: save the result's `ledger` array to
  `<scratch>/ledger_final.json`, then
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/citation_ledger.py --render "<scratch>/ledger_final.json" --extract "<scratch>/extract.json" > "<draft's directory>/<draftName> — Citation Ledger (Claude).md"`
  — one row per citation instance (note, kind, signal, disposition, cite text, and — from
  `--extract` — the body sentence the note hangs on, so an `existence-only` row can be checked by
  eye). This is the audit trail behind section J; `counts.ledger` has the totals for the TL;DR.
- **Research memo header & production footer (required):** the report opens directly under the title with the structured
  header block (`Topic:` / `Date:` / `By:`); the `Production details:` block goes at the
  **very end of the file** (after everything else, set off by a `---` rule) — never up
  top. `Date` is local time (`date "+%Y-%m-%d %H:%M %Z"` when writing the file); `By` is
  `Claude-<orchestrating session model>` (exact id); `Production details` names the
  skill, the workflow-agent model(s) actually used (read them off the run's per-agent
  progress entries — don't assume the model map), the wall-clock duration, and the token
  count — from the workflow completion notification's `<usage>` block (`duration_ms`,
  `subagent_tokens`, `agent_count`) — and **the measured cost**: run
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/cite-check/scripts/run_usage.py "<transcript dir>" --projected <spend.projected>`
  on the transcript directory the Workflow launch result named (it reads the agents'
  own usage records: turns, input, cache writes and reads, output) and put its
  `measured` line, the measured ÷ projected ratio, and the per-phase table's top lines in
  the footer beside `spend.projected`. Label the notification's `subagent_tokens` for
  what it is, the sum of the agents' peak contexts. When measured ÷ projected is off by
  more than half in either direction, say so in the deliver message with the per-kind
  figures the script prints, so `COST` in the workflow (or a `costModel` override) gets
  corrected.
  **Plus the snapshot's SHA-256** (recorded in step 2b), which
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
  Production details: Claude Code /cite-check; 21m 7s; 53 agents (workflow agents
    Claude Sonnet 5 + Claude Opus 4.8 report); measured 6,420,000 input-equivalent tokens
    (run_usage.py: 53 agents, 410 turns; Verify 3,100k / Support 2,200k / other 1,120k)
    against 5,900,000 projected, of a 7,000,000 soft cap; the completion notification's
    subagent_tokens 2,397,252 (sum of the agents' peak contexts); Zotero pre-lookup
    matched 41 of 146 sources, 30 with text.
    Draft checked: test draft.docx, SHA-256 3f2a…e91b (report is stale if the hash no
    longer matches the draft).
  ```
- With `support:true`, lead with `counts.support` in one sentence: units read, not supported,
  contradicted, overstated (say "to confirm", never "errors"), qualified, and how many were not
  read (`unitsOutOfScope` whole-work cites, `unread` budget skips, `notChecked` agent failures).
  If `counts.support.ran` is false, say the support pass did not run and why (`degradation`).
  If `counts.support.artifactsCaught` is non-zero, mention it as the guardrail working. If
  `unauditedAdverse` is non-zero, those are adverse verdicts the second check could not re-derive
  (budget or a failed reviewer): they are listed in section I as not checked, never as findings —
  say so and offer a targeted re-run. If `rejected` is non-zero, an agent returned a verdict
  without the evidence the schema requires (passage, locator, full-text basis, search); those
  units are unverifiable this run and listed in section I with the reason.
- Present the TL;DR counts and point to the "Needs your attention" section. Mention section G in
  one sentence when `counts.history.missingHistory` or `counts.history.treatmentFlags` is non-zero
  (advisory: confirm on supremecourt.gov / Westlaw before changing a cite); if
  `counts.history.ran` is false, say the history pass did not run and why.
- If `artifactsCaught` is non-empty, mention it — those are findings the second check disproved, and
  it's a sign the guardrail is working (not something to hide).
- Surface `exitState`: `complete` → deliver; `complete_with_limits` → deliver, noting the
  unverifiable items and any degradation; if the budget guard degraded coverage, say which sources
  were batched/skipped and offer a targeted re-run. A degradation line saying the budget "ran out
  mid-phase" means the wave gate stopped launching agents: the sources it never fetched are named
  in section I as NOT CHECKED (budget), and the offer is a re-run with a `+Nk` budget and
  `resumeFromRunId`, which replays everything already done from cache. If `counts.quotesNotChecked` is non-zero, an
  agent failed mid-run and those quotes were never verified — say so and offer a targeted re-run
  of their footnotes; if `counts.highSeveritySingleChecker` is non-zero, say those findings rest on
  one checker.
- Offer a **.docx** copy via the bundled converter:
  `python3 ${CLAUDE_PLUGIN_ROOT}/skills/legal-research/md2docx.py "<report>.md" "<report>.docx" "<Title>"`.
- Note once, in the deliver message: free/open-web sources only, so a Westlaw/Lexis pass and a
  manual Bluebook check remain the user's responsibility before publication. Citation *form* now
  gets its own section (short cites + typeface), but signal order, citation order, and cite
  composition are still unchecked. Without `support:true`, say that unquoted cites were
  existence-checked only and that the support pass is available on request.
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
- Case treatment and subsequent history are approximations — CourtListener's opinion index, a
  two-route citing probe, and the RECAP docket archive (federal, crowd-sourced, incomplete; no
  Supreme Court dockets) — not Shepard's/KeyCite. Section G is advisory and says so; no hits is
  not proof of good law, and an empty docket is not proof that no appeal was taken.
- **Opinions, articles and dockets that postdate the model's training data are real.** A 2025 or
  2026 decision nobody recognizes is not a hallucination signal; the fetched record is.
- **A citation that will not resolve is a search problem, not a fabrication signal.** Name search
  and the citation-string search run before any web escalation, and "not found in the sources
  checked" lists the routes tried.
- **Form findings never outrank substance.** Short-form and typeface items go in their own section
  near the end, never in "Needs your attention": a misquote and an un-italicized signal are not the
  same kind of problem, and mixing them buries the one that matters.
- **No typeface claim without the formatting layer.** On a markdown draft, or for a footnote whose
  formatted text didn't align with the validated parser's text, the answer is silence — not a guess.
- **Overstatement is a confirm item, never an error (the author's decision, 2026-10-24).** A
  source that supports a narrower or weaker claim than the sentence makes is reported under
  "Confirm: possible overstatement" with the source's actual scope and passage, phrased as
  something to check. It never enters "Needs your attention" and the deliver message never calls
  it an error.
- **A support verdict is a judgment, judged through the signal.** `not_supported` and
  `contradicted` reach the report ONLY after the independent second derivation; one that got none
  (budget, a failed or evidence-less reviewer) is listed in section I as not checked, never as a
  finding. A verdict an agent returns without a full-text basis, a source passage and a locator
  (or an adverse one without the search it rests on) is not accepted: the unit is unverifiable
  this run. A `but see` or `cf.` cite is judged for the claim its signal makes. The pass is opt-in
  and the report says in one sentence when it did not run.
