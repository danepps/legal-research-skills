# Ticket for Codex: proofread reads endnotes

Date: 2026-11-25
By: Claude (Fable 5.2), for Codex and Daniel Epps
Skill: none (ad hoc session)
Branch: `proofread-headers-footers` (this worktree, on top of `19c9937`). Endnotes ship in the same release as headers and footers: Claude Code 1.6.13 and Codex 1.7.6. Do not bump the versions again.

## Why

The headers-and-footers pass listed what the extractors still never read. Endnotes were first on the list. A draft that uses endnotes instead of footnotes gets none of its notes proofread: no citation lints, no typo findings, nothing in the redline. Dan's decision (2026-11-25): proofread must cover endnotes.

## What to build (both plugins)

### 1. Extraction

- Read `word/endnotes.xml`. Skip the separator and continuation-separator entries; only endnotes referenced from the text count, in the order of their references.
- **Rendered numbers.** Number endnotes as Word displays them: by reference order, in the document's endnote number format (`w:endnotePr` in the settings or a section; Word's default is lower-case roman), honouring a restart or a custom mark where the existing footnote code already does the same for footnotes. If the format cannot be determined, use the default and say so in the extraction's limitations.
- **Inline markers.** The body shows a footnote reference as `[FN#n]`. Give endnote references their own marker (suggestion: `[EN#n]`, with the rendered number) so a proofer can tell the two series apart, and make every consumer of the footnote marker accept it: the punctuation-before-marker lint, the chunks, the full-text files, the formatting layer.
- **A draft may have both series.** Keep them separate: separate numbering, separate locations (suggestion: where: endnote, note: n; a short form such as `en.5` beside the existing `n.5`), separate listing in the report after the footnotes.
- Endnotes travel in chunks with the paragraphs that reference them, exactly as footnotes do. A draft with no endnotes must extract byte-for-byte as it does at `19c9937`.
- Apply the extractor's existing view of the text (tracked insertions in, deletions and move sources out, fields as elsewhere).

### 2. Lints

In a draft whose notes are endnotes, the endnotes are where the citations live. So every note-level rule runs on endnotes as it runs on footnotes: citation mechanics, terminal punctuation, pincite arithmetic, caption consistency, the U.S. volume-year check, missing years, typeface, and the supra and note cross-reference rules.

- **Cross-references resolve within their own series.** A `supra note 12` inside an endnote refers to endnote 12 and is checked against the count and order of the endnotes; one inside a footnote refers to footnote 12. Where a draft has both series and a reference is ambiguous, do not guess: report nothing for that reference, or a query, and say which you chose.
- Rules that compare notes with each other (caption consistency, supra name spelling, missing years) work within a series, not across the two.

### 3. Redline writer (Claude Code)

- Tracked changes and comments for endnote findings, placed the way the writer places them for footnotes today, with the same verification extended to `word/endnotes.xml` (reject reproduces the original; accept gives only the intended text; fields unchanged, Zotero fields included, with the existing in-field editing rules).
- **The appended final period (1.6.12) applies to endnotes too,** under the same certainty checks, since an endnote that ends in a citation with no period is the same defect.
- An endnote finding that cannot be placed stays `unplaced` with a reason and never fails the redline.

### 4. Workflow, skill text, Codex

- `proofread.workflow.js` and `SKILL.md` for the Claude Code skill; the equivalent files in `codex/internal-proofread/` (extraction, lint, chunks, packets, merging, report, the optional exact replacements), under each tree's own conventions, with no imports across the trees.
- One or two plain sentences in each skill file saying endnotes are read.
- Update the 1.6.13 and 1.7.6 changelog entries so they describe headers, footers and endnotes together, and correct the list of what remains unread.

## Tests (synthetic documents only)

- An endnote-only draft: notes extracted in reference order with rendered numbers; the note lints fire on a seeded defect of each kind; the redline places a tracked change and a comment on an endnote and appends a missing final period after a citation field.
- A draft with both footnotes and endnotes: separate numbering and locations; a `supra note` in each series checked against its own series; the punctuation-before-marker lint on an endnote reference.
- Number formats: default lower-case roman, arabic, and a restart, to the extent the footnote code supports the same.
- Separators and unreferenced endnotes are not extracted.
- A draft with no endnotes: output identical to `19c9937`.
- The Codex side: the same extraction and lint cases, and a replacement on an endnote location through merge and report.
- `python3 run_tests.py` passes.

## Constraints

Work only inside this worktree. Do not read or change the main checkout at `/Users/dan/ClaudeCode/legal-research-skills`, the sibling worktree `lrs-redline`, the private skills, or the Dubitante app. No git command that writes; Claude commits. No installs; standard-library Python only. Synthetic test documents only, never a real draft. Do not delete or overwrite any tracked or pre-existing file, other than editing the files this change needs; the test suite's own cleanup of temporary fixtures, and cleanup of temporary files your new tests create, is fine inside this worktree's scratch and temp locations. Do not weaken an existing test. Where the ticket leaves a design fork open, take the conservative option, record it under departures, and keep going.

## Report back

What you built; every departure and why; how endnote numbers are rendered and what you could not determine; the commands you ran with their real output; what is untested (nothing here can be opened in Word; say so); every file added or changed.
