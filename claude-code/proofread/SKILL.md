---
name: proofread
description: Proofread an article draft's prose — typos, grammar, missing/doubled words, editing residue, and internal consistency (hyphenation, capitalization, defined terms, Part/TOC/note cross-references) — returning a location-ordered report with verbatim Cmd+F find-strings. Trigger when the user wants a draft proofread ("proofread this", "proofing pass on <file>", "check the draft for typos/consistency"). Input: .docx (canonical) or markdown. NOT a cite-checker (that's /cite-check), NOT a Bluebook linter, NOT a substantive editor.
---

# Proofread

An internal proofreading pass over an article draft — the prose itself, not the citations.
Deterministic scripts do extraction, chunking, and the mechanical lint (doubled words,
footnote-call-before-punctuation, unbalanced quotes/parens, supra/infra note-number
direction breaks, Part-label existence, heading-outline rules) for near-zero tokens; model
agents read every sentence chunk-by-chunk, two whole-document agents adjudicate consistency
(hyphenation, spelling, capitalization, terminology drift, TOC staleness, roadmap-vs-
structure), and a **mandatory skeptical re-verification of every candidate finding** keeps
false positives out of the report (the cite-check lesson: no finding ships unvetted).

**Scope of the citation side** (recalibrated 2026-07-14 after the Codex-memo comparisons):
the deterministic layer DOES check mechanical citation typography and internal citation
consistency — unfilled `_`/`__` placeholders, `Id..`, `§`-spacing, `U. S.`, signal commas,
mixed signals ("see also generally"), mid-cite `(citing Id.)` capitalization, missing
terminal punctuation, page-range dash style, pincites below a cite's own first page,
year-shaped pincites ("596 U.S. 845, 2017 (2022)"), full case cites missing their decision
year, U.S.-Reports volume↔year sanity (585 U.S. can't be 2013), the same case cited with
different volumes across footnotes (signal words stripped before keying — the Jardines
lesson), `Name, supra note N` targets that don't contain that name, and a ≥12-word passage
repeated nearly verbatim in a nearby paragraph (duplicated-quotation residue). None of that
needs an external source.

**SHORT FORMS** (added 2026-08-10 on reader feedback): a full citation repeated within
Bluebook R. 10.9's five-footnote window where the short form belongs; a case short form
stranded past that window, or with no full cite before it anywhere; a secondary source
cited in full twice when R. 4.2 calls for `Author, supra note N`. All decidable from the
draft alone — see `~/.claude/skills/legal-research/bluebook-typeface-and-short-forms.md`
for the rules as applied.

**TYPEFACE** (added 2026-08-10, `.docx` only): the extractor now resolves run properties
(`w:i`, `w:smallCaps`, `w:caps`) through character *and* paragraph styles, so italics and
small caps ARE checked — signals/`Id.`/`supra` left roman, the `note N` after an italicized
`supra` wrongly italicized, italics spilling onto the comma before a citation, small caps
broken mid-word, and case-name italicization against R. 2.1(a) (roman in a full cite
standing in a citation clause, italic in a textual sentence or short form). This also
fixes the reverse problem: an ALL-CAPS Part header is stored as ordinary text with the caps
coming from the style, so proofers used to argue about the capitalization of words the
reader never sees that way. Those paragraphs now carry a `display` flag and are off-limits
for capitalization findings.

**What it is NOT:** citation/quotation verification against real sources (that's
`/cite-check` — the two compose: proofread the prose, cite-check the authorities), a full
Bluebook linter (signal order, citation order, and full-cite composition stay out of
scope), or a substantive editor. Suspicious text INSIDE quotations is never asserted as a
draft error — it ships as an **author query** ("verify this quote against its source").
Indentation and block-quote layout remain invisible; on the markdown fallback path the
whole typeface layer is switched off rather than guessed at.

## How to run

### 1. Parse the request
- **draftPath** — the draft (required). `.docx` is canonical; `.md`/`.txt` with pandoc
  footnotes works.
- **deep** — TWO independent proof passes instead of one: extract twice (1800- and
  1200-word chunks — different boundaries, so different eyes on every passage) and pass the
  concatenated chunk lists as `chunkFiles`; fuzzy dedup + verify absorb the overlap.
  Calibration (2026-07-14, NOTES.md) showed single-pass proofreading is stochastic —
  ~75–80% overlap between two same-model passes, each catching real errors the other
  missed — so a second offset pass buys far more recall than smaller chunks alone. Also
  smaller verify batches and a higher soft cap. Turn on for a near-final draft.
- **style** — opt-in: also surface genuine style problems (confusing sentences, unintended
  repetition), clearly separated in the report. Default OFF — proofreading, not editing.
- **fable** — opt-in: run the per-chunk proofers on Fable instead of Opus ("call in
  fable", "use the big model", typically alongside deep for a final pre-submission read).

Model map: proofers **Opus** (Fable with the flag); consistency, verify, and report always
inherit the session model — verify is the false-positive gate and the report is the
deliverable, so those never run on a smaller model.

### 1b. Ask how deep to go (author's call, 2026-08-09)

**Unless the request already settles it, ASK before doing anything else** — one
`AskUserQuestion`, up front, so the choice is made before the snapshot rather than
surfaced as an offer after a standard run has already finished. Depth changes the
extraction (step 3 runs the extractor once or twice), so it cannot be changed later
without re-running.

**Skip the ask** when the user's wording already picks a tier — "deep", "thorough",
"near-final", "pre-submission", "call in fable", "use the big model", "quick pass",
"standard". Don't re-ask what they just told you. Also skip it on an explicit re-run of
a tier already chosen this session.

Ask ONE question, header `Depth`, three options in escalating order:

| Option | Args | What to say |
|---|---|---|
| **Standard — one pass** | `deep:false, fable:false` | One 1800-word-chunk pass, Opus proofers. Good for a working draft or a quick check. |
| **Deep — two offset passes** | `deep:true, fable:false` | Two independent passes (1800 + 1200 chunk boundaries). In one calibration run this surfaced roughly a quarter more confirmed findings at no wall-clock cost (the wider fan-out parallelizes) — one draft's numbers, not a guarantee. For a near-final draft. |
| **Deep + Fable** | `deep:true, fable:true` | Deep, plus the per-chunk proofers on Fable. The final pre-submission read. |

Give the real reason in the option descriptions, not just labels: single-pass
proofreading is stochastic (~75–80% overlap between two same-model passes — each misses
real errors the other catches), so **depth buys recall that a better per-pass model does
not**. Don't tag a default "(Recommended)" — the right tier depends on how near-final the
draft is, which the user knows and you don't. If they say, note it and move on.

`style` stays out of this question — it's a different axis (proofreading vs. editing) and
adding it taxes every run with a second decision. Honor it when the request asks for it.

### 2. Snapshot the draft (always)
Live OneDrive/Word co-authoring changes the file between reads — the smoke-test draft
gained/lost footnotes across three reads in one morning. Copy the draft to the session
scratchpad first and run everything off the snapshot; record the snapshot time for the
report header.

```
cp "<draftPath>" "<scratch>/snapshot.docx" && chmod a-w "<scratch>/snapshot.docx"
```
Record the snapshot time; the extractor computes the snapshot's SHA-256 (in `proof.json`)
— both go into the workflow args and appear in the report header as provenance.

**The draft is read-only to this skill — structurally, not just by convention.** The
original draft's path goes into the `cp` above and NOWHERE else: never into Workflow args,
never into an agent prompt. Everything downstream reads only the write-protected snapshot's
extraction artifacts, and every workflow agent runs as the read-only `Explore` type (no
Edit/Write tools). The ONLY file this skill ever creates outside the scratchpad is the
report (step 5) — a new `.md` next to the draft, written by you, never the `.docx` itself.

### 3. Extract + lint (deterministic — run yourself, near-zero tokens)
```
python3 ~/.claude/skills/proofread/scripts/extract_proof.py "<scratch>/snapshot.docx" "<scratch>/proof"
```
Default chunking is 1800 words — sized so each proofer reads carefully rather than skims.
For **deep**, run the extractor a SECOND time into a separate outdir with
`--chunk-words 1200` and concatenate both runs' `chunk_files` into the workflow's
`chunkFiles` (use the 1800 run's `proof.json`/`fulltext.txt` as `outDir`; the snapshot is
identical so paragraph ids line up). Prints a summary (paragraph/footnote/
word counts, chunk_count, lint_finding_count…). It writes `<scratch>/proof/proof.json`,
`fulltext.txt`, and `chunks/chunk-NN.json`.

- If the summary shows `tracked_insertions`/`tracked_deletions` true: the extractor reads
  the accepted text and skips tracked deletions — tell the user and ask whether to
  accept-all first if the draft is heavily marked.
- The summary also reports `formatting_available`, `typeface_findings`,
  `short_form_findings` and `all_caps_headings`. `formatting_available: false` means a
  markdown/plain-text draft — say so at deliver time, since the typeface section will be
  absent.
- Pull the workflow args from `proof.json` (compact, no indent):
  `python3 -c "import json;d=json.load(open('<scratch>/proof/proof.json'));print(json.dumps({'chunkFiles':d['chunk_files'],'lintFindings':d['lint_findings'],'headings':d['headings'],'noteParas':d['note_para'],'sha256':d['sha256'],'formatting':d['formatting'],'counts':{'paragraphs':d['paragraph_count'],'footnotes':d['footnote_count'],'words':d['word_count']}}))"`

### 4. Launch the workflow
```
Workflow({
  scriptPath: "~/.claude/skills/proofread/proofread.workflow.js",  // expand ~ to the absolute home dir when calling
  args: {
    outDir:      "<scratch>/proof",         // agents read fulltext.txt + proof.json here
    draftName:   "<draft filename without extension>",
    chunkFiles:  <proof.json chunk_files>,
    lintFindings:<proof.json lint_findings>,
    counts:      { paragraphs, footnotes, words },
    headings:    <proof.json headings>,     // [{para,label,text}] — report location paths
    noteParas:   <proof.json note_para>,    // note -> referencing ¶ (for paths on n.N)
    sha256:      <proof.json sha256>,
    formatting:  <proof.json formatting>,   // typeface layer; available:false on .md drafts
    snapshotTime:"<when the snapshot was taken>",
    deep:  false,
    style: false,
    fable: false                            // true => proofers on Fable instead of Opus
  }
})
```

**Pipeline:** the whole-document consistency agents launch first and run alongside the
per-chunk proof fan-out — usage, structure, and (on `.docx`) typeface, the one stage that
reads `fulltext_fmt.txt` and is allowed to reason about italics; every candidate finding
(proof + consistency + typeface + deterministic lint)
is deduped and then re-derived by a skeptical verify agent that Greps the flagged passage
out of `fulltext.txt` and re-reads it in context; only confirmed findings reach the report,
sorted into draft order. Spend-guarded (soft cap ~250k lean / ~400k deep); runs in the
background and notifies on completion. No web access needed — the whole run is local.

### 5. Deliver
The workflow returns `{ report, counts, exitState, degradation, rejectedFindings }`.
- Write **`report`** to `<draft's directory>/<draftName> — Proofread.md` (next to the draft).
- **Research memo header & production footer (required, per the author — global rule in
  ~/.claude/CLAUDE.md):** the report opens directly under the title (alongside the
  snapshot line) with the structured header block (`Topic:` / `Date:` / `By:`); the
  `Production details:` block goes at the **very end of the file** (after everything
  else, set off by a `---` rule) — never up top. `Date` is local time
  (`date "+%Y-%m-%d %H:%M %Z"` when writing the file); `By` is `Claude-<orchestrating
  session model>` (exact id); `Production details` names the skill, the workflow-agent
  model(s) actually used (read them off the run's per-agent progress entries — don't
  assume the model map), the wall-clock duration, and the token count — from the workflow
  completion notification's `<usage>` block (`duration_ms`, `subagent_tokens`,
  `agent_count`), labeled subagent output tokens (orchestrator overhead not included).
  Example header:
  ```
  Topic: Proofread of <draft name>
  Date: 2026-07-14 15:05 PDT
  By: Claude-fable-5
  ```
  Example footer (last lines of the file):
  ```
  ---
  Production details: Claude Code /proofread; 8m 25s; 664,041 subagent output
    tokens across 24 agents (workflow agents Claude Opus 4.8)
  ```
- TL;DR the counts: errors / judgment calls / conventions, and note how many candidates the
  verify pass rejected (false-positive control working, not something to hide).
- If the source draft's mtime changed since the snapshot, say so — findings cite the
  snapshot, and paragraph numbers may have drifted.
- Surface `exitState` and any `degradation` (e.g. likely-severity findings shipped
  unvetted under budget pressure) and offer a targeted re-run.
- Offer a **.docx** copy via
  `python3 ~/.claude/skills/legal-research/md2docx.py "<report>.md" "<report>.docx" "<Title>"`.
- Note once what was and wasn't covered: on a `.docx`, italics/small caps WERE checked
  against the document's real run formatting (block-quote layout and indentation were not);
  on a markdown draft, no formatting was visible at all. Citation *substance* is never
  checked here — `/cite-check` covers the authorities.

## Guardrails (never relax)
- **The draft is never edited.** Read-only by construction: the original path is used once
  (the snapshot `cp`) and never reaches the workflow; the snapshot is `chmod a-w`; all
  agents run as the tool-gated read-only `Explore` type. This skill reports findings — it
  never applies them. If the user wants fixes applied, that is a separate, explicit request
  outside this skill, made against the live draft with their eyes on it.
- **Quoted language is never a draft error.** Archaic spelling and odd grammar in quotes
  stand, no [sic] suggestions. Transcription-smell inside a quote (garbled grammar, stray
  characters, duplicated clauses) ships only as an **author query** — "verify against the
  source" — never as a fix-the-draft finding.
- **Citation SUBSTANCE is out of scope; citation FORM is deterministic-or-typeface only.**
  Footnote prose (parenthetical wording, textual sentences) is proofread; mechanical
  typography, internal cite consistency, and short-form placement come from the lint layer;
  italics/small caps come from the typeface stage; signal order, citation order, and
  whether a cite is correctly *composed* belong to the journal and /cite-check. Model
  proofers still skip citation strings except obvious typos.
- **Formatting claims come from the formatting layer or not at all.** Only the typeface
  stage and the verify agents adjudicating its findings may reason about italics or small
  caps, and only against `fulltext_fmt.txt`. Every other stage sees plain text and must not
  guess. Indentation and block-quote layout are invisible to all of them. If
  `formatting.available` is false (markdown draft), no typeface claim may ship at all.
- **All-caps headings are never a capitalization finding.** Word applies caps via the style,
  so the stored text of a Part header is unreliable — its casing is not what prints.
- **Every finding is re-verified before it ships.** A verify agent re-reads the full passage
  and rejects what a careful editor wouldn't mark; unverifiable findings ship only under an
  explicit "Unvetted" label, never silently.
- **Verbatim find-strings.** Every reported finding carries text copied character-for-
  character from the draft so the author can Cmd+F straight to it; if the string can't be
  found verbatim, the finding doesn't ship.
- **No internal ¶ numbers in the report (author, 2026-08-23).** The extractor's paragraph ids
  exist only for the agents (grep anchors, dedup, sort keys) — the author editing in Word
  cannot see them, so they locate nothing. Reader-facing locations are the containing
  Part/Section, an approximate percent-through-the-document, and visible footnote numbers
  ("note N"); the verbatim find-string is the primary locator. The workflow's `locLabel()`
  renders these — keep any future report changes on that convention.
- **Proofread, don't edit.** No style/wordiness/clarity opinions unless `style` was
  requested, and then clearly separated as optional.
