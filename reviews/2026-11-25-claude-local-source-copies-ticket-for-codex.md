# Ticket for Codex: cite-check uses the user's own copies of sources from a folder

Date: 2026-11-25
By: Claude (Fable 5.2), for Codex and Daniel Epps
Skill: none (ad hoc session)
Branch: `local-source-copies` (cut from `d1a0edd`, Claude Code plugin 1.6.11 / Codex plugin 1.7.5)

## Why

A user with no Zotero library has no way to give cite-check a copy of a source it cannot reach.

- In the Claude Code skill, Zotero is the only route for a licensed copy of an article or book. After Zotero the agents go to the open web, and a paywalled source ends in the report's section I (Couldn't check).
- The README tells people who do not use Zotero to skip it. Those users lose every paywalled source.
- The Codex skill accepts one supplied file per source through `source_path`, but `codex/cite-check/references/run-picker.md` says folder-wide matching is not implemented.

Many users already have the PDFs: articles downloaded from HeinOnline or Westlaw, library scans, author copies. They sit in a folder. This ticket lets cite-check find them.

## Decisions already made (Dan, 2026-11-25)

- This goes in the public plugin, both the Claude Code skill and the Codex skill.
- It is not to be ported to the private skills. Do not touch `~/ClaudeCode/research-skills-private`. Claude records the divergence in `PUBLIC-VERSIONS.md` after review.

## Scope defaults (Claude's, not yet confirmed by Dan; build to these and flag disagreement)

1. **Secondary sources only.** The same kinds the Zotero pre-lookup covers (article, book, other, and an internet manuscript whose cite yields an author and a title). Cases and statutes stay with CourtListener and the public sources.
2. **No new question in the up-front dialog.** The folder is found, in this order:
   - a folder the user names in the request;
   - a `Source folder: <path>` line in the project folder's `CLAUDE.md` or `AGENTS.md` (the same convention as the existing `Zotero library:` line);
   - a subfolder named `Sources` (any capitalization) beside the draft.
   If none exists, the pass is skipped without a prompt. Loose PDFs beside the draft are not scanned.
3. **One release for both plugins:** Claude Code 1.6.12 and Codex 1.7.6.
4. **No OCR.** A PDF with no text layer is listed as unreadable. Never install software.

## Rules that must hold

- **A filename or PDF metadata match never establishes identity.** A file is matched to a citation from the text of its own first pages (title, author, and where present the journal, volume, first page, year). This is the rule the Codex skill already states in `run-picker.md`.
- **Ambiguity is a miss.** Two plausible files, or one weak match, means not matched; list the candidates for the report. Never pick one.
- **The copy may not be the published version.** An SSRN draft or author manuscript has different pagination. Record what the first pages show (journal running head and printed page numbers, or a working-paper or forthcoming marker, or neither). Pincites are judged only against a copy that carries the printed page numbers; otherwise the quotation can be confirmed and the pincite is reported as not judged, with the reason.
- **The report names the copy used:** the file's name, and the version note above. A quotation confirmed in the user's copy is never worded as confirmed in the published source unless the copy is the published version.
- **Local copies come first**, then Zotero, then the web. A source matched in the folder is not looked up again elsewhere.
- **Nothing leaves the machine at indexing time.** Indexing and matching are script work with no model call and no network.
- **The user's files are read-only.** Extracted text and the index go in the run's scratch or cache directory, keyed by content hash, so a re-run extracts nothing twice.

## Claude Code side (`claude-code/skills/cite-check/`)

The existing seam is the Zotero pre-lookup. `scripts/zotero_lookup.py` writes a report keyed by ledger source key (`matched`, `title`, `textPath`, `textPages`, `textSource`, `citedFirstPage`, `confirm`, `score`, `candidates`), its `--compact` map is the workflow's `zoteroHits`, and `scripts/zotero_sweep.py` runs `verify_quotes.py` against the text files it left on disk. A local-copies pass should produce records the workflow can join on the same key.

1. **New `scripts/local_lookup.py`** (standard library only; `pdftotext` for PDFs, as in `zotero_lookup.py`; `.txt` and `.md` files read directly).
   - Inputs: the same `--secondary`, `--support` and `--cites` files `zotero_lookup.py` takes; `--folder DIR` (repeatable); `--cache-dir DIR`.
   - Per file: content hash, page count, extracted text with form feeds between pages (the format `verify_quotes.py` already reads), and the identifying text of the first pages.
   - Matching: reuse `zotero_lookup.py`'s cite parsing and scoring by import where it fits, not by copying it.
   - Per source, the same fields as a Zotero record where they apply, plus the file's path and hash and the version note. Mark the origin so the workflow can tell a local copy from a Zotero item.
   - A summary line like the Zotero one: files indexed, sources matched, unmatched, unreadable files (by name).
   - `--compact` and `--get KEY`, as `zotero_lookup.py` has, or one merged report that serves both origins. Your choice; the workflow must end up with one map and one way to fetch a full record.
2. **`cite-check.workflow.js`.**
   - A source with a local copy gets a per-source line that says so and gives the text path, in place of the `ZOTERO:` line. The policy text must not tell an agent that a source is absent from Zotero when Zotero was never searched.
   - The pre-report sweep runs when a local lookup exists, with or without a Zotero lookup. Today it is gated on the Zotero pre-lookup alone.
   - Notes and findings name the copy (file name), not Zotero.
   - The pass works with `zotero:false`.
   - Section I (Couldn't check) says, for a source that could not be reached, that a copy placed in the source folder will be used on a re-run of those footnotes.
3. **`SKILL.md`.** A step beside the Zotero pre-lookup: how the folder is found, the command, what to say at deliver time (matched count, unreadable files), and the rules above. Say plainly that passages from the user's copies are read by the model like any other source.
4. **Tests.** `scripts/test_local_lookup.py` with synthetic fixtures only (made-up articles; no real drafts or real PDFs from anyone's library): a clean match, a filename that matches but text that does not, two candidate files, a working-paper copy, an unreadable file, a re-run that reuses the cache. A workflow-harness scenario with a local hit and no Zotero. Tests that need `pdftotext` skip cleanly without it.

## Codex side (`codex/cite-check/`)

Implement the folder matching that `references/run-picker.md` lists as not implemented, on the existing `source_path` and `source_sha256` contract, under the same rules. The two trees are independent implementations, so follow the Codex tree's own conventions (run directory, ledger fields, validator) instead of importing from `claude-code/`. Update `run-picker.md`, `references/verification-protocol.md` if its source order needs a word, and the two README sentences about supplied PDFs.

## Docs and release

- `README.md`: where it tells people without Zotero to skip, add that a folder of their own PDFs works instead, in one or two plain sentences. This audience is not technical.
- `TECHNICAL.md`: a row in the capability table.
- `CHANGELOG.md`: entries for 1.6.12 and Codex 1.7.6, stating what was and was not tested.
- Both `plugin.json` versions.
- `python3 run_tests.py` passes.

## Out of scope

- find-cite and legal-research (the memo quote checker's filename-based `--sources` lookup stays as it is).
- Cases and statutes.
- OCR.
- Any change to the Dubitante app or the private skills.
- Git: Claude commits after review. Do not commit, push or open a pull request.

## Report back

In your final message: what you built, every place you departed from this ticket and why, what you ran and its output, and what is untested. No separate handoff file.

## Amendment 1 (Dan, 2026-11-25): ask about the folder, in setup and in the dialog

This is a second pass, to be done after the first pass above is finished and reported. It replaces scope default 2 (no new question). Dan's reason: a user who has never heard of the folder convention would otherwise learn of it only from the Couldn't check section. It applies to both the Claude Code skill and the Codex skill.

### Setup (once per computer)

- **Claude Code `setup` skill:** step 5 (Zotero, optional) becomes a step about the user's own copies of sources. Ask whether they keep sources in Zotero, in a folder of PDFs, both, or neither. The Zotero branch is unchanged. For a folder: if they keep everything in one place, save it as their default folder; if their PDFs live with each project, say that cite-check will ask per project. Neither is a normal answer and never a problem.
- **Where the default is saved:** one small file under `~/.config/`, written by `setup.py` and read by both plugins, the way the CourtListener token file is shared. `setup.py status` reports it. It holds a path only, never file contents.
- **Codex:** the Codex setup helper does not configure sources, so put the same step in `INSTALL.md`'s Codex section, using the shared `setup.py` subcommand.
- Both `local_lookup.py` scripts read the default folder after the project-level sources in the order below.

### The cite-check dialog (per project)

- The dialog is at the tool's limit of four questions, so do not add a fifth. Widen the fourth question (Zotero library) into one about where the user's copies are: their Zotero library, a folder of PDFs, both, or neither (web only).
- **Ask only when it is unsettled.** It is settled when the request names a folder, the project file has a `Source folder:` line, a `Sources` subfolder exists beside the draft, or a default folder is saved. Then use it and say so in one line, as the skill already does when only a personal Zotero library is registered.
- **Remember the answer for the project,** including neither, by offering to add a `Source folder: <path>` or `Source folder: none` line to the project's `CLAUDE.md` (Codex: `AGENTS.md`), the same way the Zotero choice is saved today. A user with no Zotero and no folder then sees the question once per project.
- **No path typing required.** A person who chooses a folder and has not named one gets a `Sources` folder beside the draft (created if absent) and is told to put the PDFs there; they may name a different folder in their own words. Do not depend on the dialog's free-text field to return a path; the 2026-10-27 design note records that a free-text value did not come back.
- **Keep what works.** The existing behaviour for several Zotero libraries (listing by name, matching a typed description) must survive, the dialog must stay one interaction, and each question may offer at most four options. Where these pull against each other, choose a design, say in the report which one and why, and cover it with a test.
- **Order of sources for the lookup** is now: a folder named in the request; the project's `Source folder:` line; a `Sources` subfolder beside the draft; the saved default folder. A `Source folder: none` line turns the pass off for that project.
- **Headless runs** (no dialog available) use whatever is settled and otherwise skip the pass, as now.

### Docs

Update `claude-code/skills/DESIGN-upfront-dialog.md` with a dated note, the README's setup and Zotero sentences, the Codex `run-picker.md` (its fourth question and the sentence saying there is no new picker choice), and the two CHANGELOG entries. Report back as above, listing departures.

## Amendment 2 (2026-11-25): fixes from the two adversarial reviews

Third pass. Two reviews of the uncommitted change (a fresh read-only Codex thread on `claude-code/`; Claude on `codex/`) found the defects below. Dan has approved a fix pass. `local_sources.py` and `source_options.py` are the same file in both trees apart from `PROJECT_FILE`; fix both trees in the same pass and keep them identical, and add a check to `run_tests.py` that fails if they diverge.

### A. Identity: the wrong file can match

1. **The title and byline must be the document's own.** Today an exact title on adjacent lines plus any nearby line with the author's name matches anywhere in the first three pages. Probes matched a book review of the cited book (title, the book's author, then a reviewed-by line), a piece headed as a response to the cited title, an article that merely lists the title and citation, and a reading list. Require the title at the head of the document's first content page (allowing one recognized database cover sheet before it), reject a title that is part of a longer heading or sits under a review, response, reply or comment marker, and require a byline that is a byline and not a sentence that names the author.
2. **The script only proposes.** However good the heuristic, the agent that relies on a local copy must confirm from the first page that it is the cited work and edition, and treat a mismatch as no local copy, falling through to Zotero and the web. Put that instruction in the per-source line of the Claude workflow and in the Codex skill, and make the outcome a recorded field.
3. **Books: compare edition and year.** A third edition matched a cite to the second. A stated edition or year that conflicts with the cite is not a match (a candidate, with the reason). Where the copy states neither, it may match but is not fit for pincites.
4. **Ledger-key collisions (pre-existing, now reachable).** Two books whose titles share the first several words collapse to one ledger key in the Claude ledger builder; a local hit for one is then applied to the other and suppresses its Zotero lookup. A hit must be compared with the unit's own cited title before it is used; on a mismatch treat the source as having no hit. Do this for local hits; do it for Zotero hits too if the same guard covers them. Report the wider key-collision problem separately and do not rework the ledger keys in this pass.

### B. Version and pincites

5. **Fit for pincites only when the published version is affirmatively established, for every source type.** Today a book or manuscript with no parsed journal is fit whenever any number appears in a header.
6. **An accepted manuscript was classified as published.** Add the missing markers (accepted manuscript, to be published in, author's version, and the usual repository cover lines). A page number inside a citation line is not a printed page label; count only standalone header or footer labels.
7. **False working-paper markers.** A published article whose first-page footnote cites a forthcoming piece, or whose title contains the word draft, is marked a working paper. Look for markers only where a version statement appears (the head of the first page, headers and footers, a cover sheet), not in body text or footnotes.
8. **Enforce pin-not-judged across every report field (Claude workflow).** For an unfit copy, a verifier's pincite-error note survived after the verdict was changed, and a support result carried a page correction and a published-source label through unchanged. Keep the quotation result, mark the pincite not judged with the reason, and strip or refuse page corrections drawn from an unfit copy, in quote and support output alike.
9. **Codex validator.** It appears to reject any verified verdict on a pincited unit whose local copy is unfit for pincites, which would block the intended outcome (quotation confirmed, pincite not judged). Confirm, and make that outcome representable and valid.

### C. The right file is missed

10. **Duplicates by content.** Two paths with identical bytes are one copy, not two candidates.
11. **Draft and published version both present.** If exactly one strong candidate is established as the published version, use it and name the other in the report. Otherwise it stays ambiguous.

### D. Reporting

12. **Local bibliographic discrepancies are dropped (Claude workflow).** The local branch replaces `confirm` entries with a generic note and empties the metadata findings; the Zotero branch keeps them. Carry them through.
13. **The sweep takes the first of several matching sources (pre-existing, now applies to local copies).** When a quotation is found in more than one source the footnote cites, return all of them and leave the attribution unresolved.
14. **No absolute paths in reports.** Candidate and copy lines give the file name, or the path relative to the source folder, never the user's home directory.

### E. Operation and safety

15. **Bound the work.** Every file in the folder is fully extracted before matching, a saved default folder may hold thousands of PDFs, and there is no size limit; a very large text file is read into memory and a `MemoryError` escapes the per-file handler. Extract only the first pages for identity and the full text only for files that match; cap file size, extracted size and page count (the Zotero lookup's limits are a guide); cap the number of files indexed in one run; report anything skipped by name or count; print progress to stderr.
16. **Skip hidden folders and the run's own folders instead of refusing.** The Codex lookup exits with a usage error when the source folder contains the run directory, which is the case for a user whose PDFs sit beside the draft. Skip dot-directories, the run directory and the cache while indexing.
17. **Tilde in the draft or project path** is treated as a literal directory. Expand it, as the folder argument already does.

### F. The dialog

18. **Folder and Zotero settle separately.** Today a settled folder (a `Sources` folder or a saved default) suppresses the question, and a user with several Zotero libraries and none saved loses Zotero silently. This came from the wording of Amendment 1 and is corrected here: ask whenever either half is unsettled, offering only the unsettled half. A user with several libraries and a settled folder gets the library question as before this change.
19. **Plain single choice where possible.** With no library or one library, offer a single-select of at most four options (the library, a folder of PDFs, both, neither). Use multi-select only when two or more libraries must be offered.
20. **Shorter prompt.** One sentence for the question; the save offer in one short sentence; the full library list only when it does not fit in the options.
21. **Choosing a folder must not erase a saved Zotero library** unless the user was offered Zotero in the same question and declined it.

### G. Tests

22. A regression test for each numbered item above, with synthetic fixtures: multi-line reference layouts, a numbered-page manuscript, a review, a response, two editions, identical duplicates, draft plus published.
23. **The local-sweep harness test** runs the helper itself with a hard-coded id instead of checking the command the workflow emitted. Assert the emitted arguments, with a nonzero id or a multi-chunk case.

Constraints are unchanged from the first pass. Update both CHANGELOG entries to describe the shipped behaviour (the versions stay 1.6.12 and 1.7.6; nothing has been released). Report back as before: what changed per item, any item you did not fix and why, test output, what is untested.
