# Ticket for Codex: the proofread redline adds a missing final period after a citation

Date: 2026-11-25
By: Claude (Fable 5.2), for Codex and Daniel Epps
Skill: none (ad hoc session)
Branch: `redline-terminal-period` (a worktree cut from `d1a0edd`, Claude Code plugin 1.6.11)

## What Dan saw

A live proofread through the Dubitante app (plugin 1.6.11, redline on) produced 134 findings: 29 tracked changes, 100 comments, and none applied inside a Zotero field. Twelve of the comments were the deterministic lint `cite-terminal-punct`: a footnote whose text ends without terminal punctuation, usually because it ends with a Zotero citation. Each became a comment whose fix reads: add the final period.

Dan's decision (2026-11-25): for this finding the redline should add the period itself, as plain text after the citation.

## Why it is a comment today

- The lint finding has no `replacement`, and its `find` is an excerpt that starts with an ellipsis (the tail of the footnote). `redline_docx.py` never applies an excerpt as a change.
- `edits_from_findings` makes a tracked change only for severity `error` with an exact replacement. This lint is `likely`.

## What to build (`claude-code/skills/proofread/scripts/redline_docx.py`)

1. **A tracked insertion of one period at the end of the footnote.** For a finding in category `cite-terminal-punct` with no replacement, insert `.` as a `w:ins` run at the end of the footnote's text.
2. **Outside every field.** When the footnote's last text sits in a field result (a Zotero citation or any other field), the new run goes after that field's end marker, as an ordinary run. Never inside a field result or a field code. Every Zotero field stays byte-for-byte unchanged; nothing is counted in `applied_in_zotero_fields`.
3. **Plain formatting.** The new run must not inherit italics, small caps or other character formatting from the last run of the citation. Use the footnote's ordinary text formatting, following whatever the writer already does for inserted text.
4. **Only when it is certain; otherwise the comment as today.** Apply the insertion only if all of these hold, checked on the same text view the extractor uses:
   - the location is a footnote, and the footnote's text ends, ignoring trailing white space, with the verbatim words of the excerpt (the `find` without its ellipsis);
   - that text does not already end with terminal punctuation (`.`, `?`, `!`, or one of those followed by a closing quotation mark or parenthesis, matching the lint's own test in `extract_proof.py`);
   - the end of the footnote is not inside a tracked deletion or a moved-from range, and no other applied edit touches the same end;
   - trailing white space, if any, stays after the period where it lies outside the field.
5. **Policy lives in `edits_from_findings`,** as the existing rule does. This category is the one exception to the rule that only severity `error` with an exact replacement is applied. Give the edit a distinct kind so `--edits` input can request the same thing, and validate it in `validate_edits`.
6. **Result file.** The edit is `applied` and is counted in `totals.applied`; mark it so a reader of `redline-result.json` can tell an appended period from a replacement.
7. **Verification holds.** The writer's existing guarantees must still pass: rejecting the new revisions reproduces the draft exactly; accepting them gives the draft plus exactly the intended periods; unedited fields are unchanged.

## Tests (`scripts/test_redline_docx.py`, synthetic documents only)

A footnote ending in a Zotero citation field; ending in plain text; ending with a closing quotation mark and parenthesis; ending in italic text (the period is not italic); with trailing white space; ending in a non-Zotero field; already ending with a period (no change); ending inside an existing tracked insertion; ending inside a tracked deletion (comment, not a change); two findings on the same footnote end (one period); the excerpt not matching the footnote's end (comment). `python3 run_tests.py` passes.

## Docs and release

- `claude-code/skills/proofread/SKILL.md`: one or two sentences where the redline is described.
- `CHANGELOG.md`: an entry for 1.6.12, stating what was and was not tested (nothing here has been opened in Word).
- `claude-code/.claude-plugin/plugin.json`: 1.6.12.
- The Codex `internal-proofread` skill has no redline writer; leave it alone unless its findings need a change to carry this category, and say so in the report.

## Out of scope

Body paragraphs; any other lint category; the Dubitante app; the private skills (Claude ports the change after review). No git command that writes; Claude commits.

## Report back

What you built, every departure from this ticket and why, the commands you ran with their real output, what is untested, and the files added or changed.
