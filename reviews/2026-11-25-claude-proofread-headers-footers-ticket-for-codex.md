# Ticket for Codex: proofread reads headers and footers

Date: 2026-11-25
By: Claude (Fable 5.2), for Codex and Daniel Epps
Skill: none (ad hoc session)
Branch: `proofread-headers-footers` (a worktree cut from `120a8e2`, the unmerged Claude Code plugin 1.6.12; this change is 1.6.13 for Claude Code and 1.7.6 for Codex)

## What Dan saw

A live proofread of a law-review draft produced 134 findings and missed a plain error: two words run together with no space in the author note. The author note of that draft is not a footnote. It sits in a page footer (`word/footer2.xml`, the first-page footer), and Word itself had already marked the error there with a spelling flag.

The cause: `claude-code/skills/proofread/scripts/extract_proof.py` reads `word/document.xml` and `word/footnotes.xml` and nothing else. No finding can ever be made about text in a header or footer. The Codex skill's `codex/internal-proofread/scripts/extract_draft.py` is to be checked for the same gap.

Dan's decision (2026-11-25): proofread should cover headers and footers.

## What to build

### 1. Extraction (both plugins)

- Read the header and footer parts the document actually uses: those referenced by a section's `headerReference` / `footerReference` (through the document's relationships), with their type (default, first page, even pages) and section.
- **Skip page furniture.** A part whose only text is a page-number or similar field result, or that is empty, contributes nothing. Field result text is handled as it is elsewhere in the extractor; a field's instruction text is never proofread.
- **One copy of repeated text.** The same header or footer repeated across sections or types is proofread once, and its location names every place it appears.
- Apply the extractor's existing view of the text (tracked insertions included, deletions and move sources excluded, white space as elsewhere) so a find string is verbatim against what the author sees.
- **Locations.** Give header and footer paragraphs a location form of their own beside the existing body and footnote forms (for example where: header or footer, with the type, the section and the paragraph). Every consumer of `location` must accept it: the lint, the chunks, the full-text files, the workflow, the report's location-ordered listing and its find strings. Decide where they sort in the report (suggestion: first-page header and footer before the body, the rest after the footnotes) and say what you chose.
- **Which lints apply.** The general prose lints do (doubled words, typos, spacing, quotation marks). Footnote-only rules do not, with one question to settle and report: an author note in a footer is footnote-like prose and may carry citations; say whether the citation-mechanics lints should run on it and what you did.
- **Chunks.** Header and footer text must reach a proofreading agent, in an existing chunk or a small one of its own, without changing the size or order of the body chunks for a draft that has no such text. A draft with no header or footer text must produce byte-identical extraction output to today's, apart from any new empty field you add; if you add one, say so.
- Markdown input has no headers or footers; nothing changes there.

### 2. The redline writer (`claude-code/skills/proofread/scripts/redline_docx.py`)

- **Tracked changes** for a clear correction in a header or footer part, under the writer's existing rules and with its existing verification extended to those parts (rejecting the new revisions reproduces the original text of the part; accepting gives only the intended replacement; fields unchanged).
- **Comments are the open problem.** Claude's recollection, not verified in this session, is that Word does not allow comments in headers and footers. Do not put comment anchors in a header or footer part on the strength of the schema alone. Unless you can establish from Microsoft's own documentation that Word accepts them, anchor such a comment at the start of the document body and begin its text with the location (for example: First-page footer, then the quoted words), so the author still sees it in the margin. Say in the report which you did and on what evidence.
- A finding in a header or footer that cannot be placed stays `unplaced` with a reason, as today; it never fails the redline.
- The appended-period rule (1.6.12) is for footnotes only and does not extend to these parts.

### 3. Workflow, skill text and Codex

- `claude-code/skills/proofread/proofread.workflow.js` and `SKILL.md`: whatever the new location form and chunk require, and one or two plain sentences saying headers and footers are now read.
- **Codex `internal-proofread`:** the same coverage in `extract_draft.py`, the lint, chunks, packets, merging and report, under that tree's own conventions. The two trees are independent implementations; do not import across them. Its optional exact replacements (1.7.4) must carry a header or footer location through unchanged.

### 4. Say what else is unread

Report, without building it, what other text of a `.docx` the extractors still never read (endnotes, text boxes, comments, footnote separators, anything else you find), so Dan can decide on each.

## Tests (synthetic documents only)

- A first-page footer holding an author note with a run-together word across two runs: the finding is made, its location names the footer, and the redline places it.
- Default, first-page and even-page headers and footers; two sections sharing one part; two sections with identical text in different parts (one finding, both places named).
- A footer with only a page-number field (nothing extracted); a header with text plus a page-number field (the field result is not proofread as prose).
- A draft with no header or footer text: extraction output unchanged from the current release.
- Redline: a tracked change inside a footer verifies on reject and accept; a comment-type finding lands where section 2 says; a footer containing a field is not damaged.
- The Codex side: the same extraction cases, and a replacement on a footer location through merge and report.
- `python3 run_tests.py` passes.

## Docs and release

`CHANGELOG.md` (1.6.13) and `codex/CHANGELOG.md` (1.7.6), each stating what was and was not tested; both `plugin.json` versions; the README only if it describes what proofread reads.

## Constraints

Work only inside this worktree. Do not read or change the main checkout at `/Users/dan/ClaudeCode/legal-research-skills`, the private skills, or the Dubitante app. No git command that writes; Claude commits. No installs; standard-library Python only. Synthetic test documents only, never a real draft. Do not delete or overwrite any tracked or pre-existing file; the test suite's own cleanup of temporary fixtures it creates, and cleanup of temporary files your new tests create, is fine inside this worktree's scratch and temp locations. Do not weaken an existing test.

## Report back

What you built; every departure from this ticket and why; the answers to the questions in sections 1, 2 and 4; the commands you ran with their real output; what is untested (nothing here can be opened in Word; say so); every file added or changed.
