# Changelog

Releases of the `legal-research` plugin for Claude Code and the companion Codex skills. Claude Code users receive a release when the version below changes (`/plugin marketplace update danepps`, or automatically if auto-update is on for the `danepps` marketplace). Codex users re-run the installer.

## 1.6.22 (2026-11-27)

`cite-check`: two false positives from the live run that checked 1.6.21. No Codex skill changed;
the companion Codex version stays **1.7.9**.

- 1.6.20's guard for a cut-short treatment check read the word 'truncated' in an agent's notes.
  1.6.20's own prompt told the agent to use that word, and in the 1.6.21 run the agent wrote 'Full
  output read, not truncated' for all five cases; the run ended `complete_with_limits` with every
  case listed as treatment unchecked. The history schema now has a required `treatmentReadInFull`,
  and the guard follows it. The text test remains only for an answer without the field, and it
  skips 'not truncated'.
- A metadata line that only confirms the cite ('Citation 503 U.S. 540, 549 (1992) is correct for
  the passage. [source: …]') was exported as a finding. A line that says the cite is correct or
  matches the record and names no discrepancy (should, wrong, not, but, differs …) is now dropped
  with the other clean results.
- The 1.6.21 run otherwise behaved as intended: `treatmentFlag` set aside the rows about other
  cases (including *State v. Shirley* on *Russell*), and the one real flag (*People v. Brown* on
  *Mathews*) was kept.
- Tests: `scripts/test_workflow_case_metadata.py`.
- Not tested: a live run.

## 1.6.21 (2026-11-27)

`cite-check`: the history agent says yes or no to a treatment flag. No Codex skill changed (its
treatment findings already carry a verdict); the companion Codex version stays **1.7.9**.

- In the live run that checked 1.6.20 (2026-11-27), the agent wrote into `treatment` a row it had
  set aside: 'Scope unconfirmed: State v. Shirley … That row says Russell disapproved a different
  case, Bueno, so it is not adverse treatment of Russell.' The report then listed *United States v.
  Russell*, 411 U.S. 423 (1973), under 'Treatment flags' and in the same entry said it was not
  one. 1.6.19's clean-result filter does not catch this, because the text opens like a flag.
- The history schema has a required `treatmentFlag` (true only when a row says this case was
  overruled, abrogated, limited, declined to follow or superseded). When it is false, any
  `treatment` text moves to `note` as 'set aside: …' and is not a finding. The prompt says a row
  in which this case does the overruling or disapproving is not a flag. An answer without the
  field keeps 1.6.20's behaviour.
- Tests: `scripts/test_workflow_case_metadata.py` feeds the run's Shirley text with
  `treatmentFlag: false`.
- Not tested: a live run.

## 1.6.20 (2026-11-27)

`cite-check`: a treatment check whose output was cut short is listed as not checked. Also
`legal-research`'s `cl_case_tools.py citing`, which both skills use. No Codex skill changed (it
uses its own `courtlistener_treatment.py`); the companion Codex version stays **1.7.9**.

- The live run that checked 1.6.19 (2026-11-27, Dubitante, Sonnet) found none of the treatment
  flag every earlier run of the same draft had found (*People v. Brown*, 218 P.3d 733 (Colo. App.
  2009), on *Mathews*). Its history agent had run the five `citing` lookups in one command, each
  piped through `head -c 3500`. The tool printed the recent citing cases first and the treatment
  rows last, so the agent read no treatment row. It said so in each case's note ('first ~3.5KB of
  output only'), but the case was still counted as checked, the run ended `complete`, and the
  report said 'Treatment flags: none'.
- `cl_case_tools.py citing` now prints `treatment_probe` and `name_search_treatment_probe` before
  `recent_citing` and `name_search_only`. The keys and their contents are unchanged.
- The history agent's prompt tells it to run the lookup once per case, read the whole output, and
  write 'truncated' in coverage when it could not.
- A checked case whose note or coverage says its output was truncated (or 'first ~3.5KB', 'not
  read in full') keeps its history result but drops to low confidence, is listed in the report data
  under 'not checked' as 'treatment unchecked', and adds one run limit naming the cites, so the run
  ends `complete_with_limits`.
- Tests: `test_cl_case_tools.py` stubs the CourtListener calls and checks the order (a treatment
  row falls inside the first 3,500 bytes); `test_workflow_case_metadata.py` feeds the run's notes
  through the stubbed workflow. Both fail on 1.6.19.
- Not tested: a live run.

## 1.6.19 (2026-11-27)

`cite-check`: a clean result is no longer counted as a finding. No Codex skill changed (its
history and treatment findings are structured rows with a verdict); the companion Codex version
stays **1.7.9**.

- Five live runs on the same six-note draft (2026-11-27, Dubitante, Sonnet) agreed on every real
  finding, but their findings export held 7 to 11 items. The extra items were clean results that
  agents had written into finding fields instead of leaving them empty: treatment text such as
  'None naming this case as overruled or limited', metadata lines such as 'No metadata problems:
  … matches the fetched record', and, in two runs, history lines that only restated the case-name
  or year mismatch already reported for the same cite. On a re-run, such items would have shown in
  'Since the last report' as new or resolved findings when nothing had changed.
- The workflow now drops them before building the export, the counts and the report agent's
  data: a treatment, history or metadata line that opens with 'None', 'Nothing', 'No adverse …',
  'No metadata problems …' and the like; and a history line on a cite with a case-name or year
  mismatch that names no history outcome (affirmed, reversed, vacated, remanded, cert., overruled,
  and so on). A real treatment flag (one run's 'Limited or declined to follow in part by a state
  court. People v. Brown …') and a real history outcome on a mismatched cite are kept.
- Tests: `scripts/test_workflow_case_metadata.py` feeds the five runs' texts through the stubbed
  workflow; seven checks fail on 1.6.18. `scripts/workflow_case_harness.mjs` can now stub the
  verify agents' metadata lines and returns the report agent's history data.
- Not tested: a live run.

## 1.6.18 (2026-11-27)

`find-cite`: an entry starts with its cites. No Codex skill changed; the companion Codex version
stays **1.7.9**.

- The `entry` used to open with a `**Proposition:**` line and an `**Authority type:**` line that
  gave the classifier's reasoning. The proposition line is gone: a host prints the proposition as
  the entry's heading, and in a chat the user has just typed it. The authority type, with the same
  reasoning, is now an italic note at the end, just before the `*Checked:*` line. (Dan,
  2026-11-27, looking at an entry in the Dubitante app: keep this simple for people who are not
  technical.)
- The result's `proposition`, `authorityType` and `authorityTypeBasis` fields are unchanged.
- Tests: `scripts/test_workflow.py` checks the new order in every stubbed run.
- Not tested: a live run in the new layout.

## 1.6.17 (2026-11-27)

`proofread`: a report starts with its findings. The snapshot line and the header block no longer
sit between the title and the first finding. Companion Codex version **1.7.9**, which makes the
same change to `internal-proofread`.

- The workflow's `report` used to carry a block quotation under its title with the snapshot time
  and the draft's 64-character SHA-256, typed by the report agent from its prompt. The script now
  writes that line itself, as the report's last line, so the hash is exact; the agent is told to
  write no provenance line and is no longer shown the hash, and one it writes anyway is removed.
- The mechanical fallback report (used when the report agent fails twice) keeps its failure notice
  under the title and also ends with the snapshot line.
- `SKILL.md`, step 5: nothing is added between the title and the findings and no `Topic:` line is
  written. `Production details:`, then `Date:` and `By:`, are the last lines of the file.
- Nothing else about the report changes: the same sections in the same order, the same findings
  data, the same redline.
- Tests: `scripts/test_workflow_provenance.py` (stubbed agents) checks the three cases.
- Not tested: a live run. A host that publishes the report with a header of its own under the
  title (the Dubitante app did) has to stop doing so separately.

## 1.6.16 (2026-11-27)

`legal-research`, `cite-check` and `find-cite`: every agent that can save a file is told where its
temporary files go, and a new optional `scratchDir` argument moves them out of `/tmp`. No Codex skill
changed; the companion Codex version stays **1.7.8**.

- Why. A program that launches a run inside a file boundary (the Dubitante app, with its boundary
  on) lets the run write only its own folder. The workflows named `/tmp` paths for the cite-checkers
  and refutation voters, and gave the `legal-research` readers, scouts and gap-fill agents no path at
  all, so those agents made up their own (`/tmp/<case>.txt`). Two agents can collide on such a name,
  and a confined run refuses every one of them: on 2026-11-26 a confined research memo verified 11
  authorities where the same question unconfined verified 19.
- `scratchDir` (all three workflows): the absolute path of an existing folder. Left out, the folder
  is `/tmp` and every path the workflows already named is unchanged. A path with a space is written
  inside double quotes in the commands the agents are given. A relative path, or one with a double
  quote, backtick, dollar sign, backslash or line break, stops the workflow before any agent starts.
  The skills say to pass it only when the launching program supplies a folder.
- A `TEMPORARY FILES` rule in each prompt whose agent can run a command: any file it saves gets a
  name starting with a prefix unique to the run and to that agent, in the scratch folder, and it
  writes nowhere else and does not `cd` elsewhere. This is new for `legal-research`'s scope, survey,
  read and gap-fill agents and for `cite-check`'s existence and history agents; the agents that
  already had a named path keep it and get the rule for anything else. This rule is in every run,
  with or without `scratchDir`.
- Tests: the stubbed-agent tests of the three workflows check the default paths, a plain folder, a
  folder with a space, that no prompt names a `/tmp` path of the workflow once `scratchDir` is set,
  that no two file-saving agents share a prefix, and each refused form of the argument.
- Checked live on 2026-11-27 through the Dubitante app's opt-in tests with its boundary on, one run
  each. Research memo, the question of the 2026-11-26 trial: the agents saved their files in the
  run's folder under the given names and none in `/tmp`; 14 authorities verified and 5 unverified,
  then 16 and 3 once the app also worked around a Claude Code refusal that is separate from this
  change. Cite-check on a six-footnote fixture: complete, with the same counts as the unconfined run
  of 2026-11-26. One run each is not a measure of quality, and the memo counts vary from run to run.
- Not tested: `find-cite` live with `scratchDir`; a folder whose path has a space, live; any run
  outside the app with `scratchDir` set.

## 1.6.15 (2026-11-26)

`proofread` and `cite-check` check that every section symbol (§) and paragraph symbol (¶) in a Word
draft is followed by a non-breaking space, so a line never ends on the symbol, and the proofread
redline can fix it. Companion Codex version **1.7.8**.

- The check reads the Word file's own characters. Every text view the agents read collapses white
  space, which turns a non-breaking space into an ordinary one, so no agent could see the difference
  and none is asked to. A gap counts as non-breaking only if every character in it is U+00A0, U+202F
  or U+2007. The code is shared: `legal-research/citeform.py` (`symbol_space_hits`,
  `symbol_space_convention`), run by both extractors.
- It is reported as one row in the conventions table (proofread: document-wide conventions;
  cite-check: the Citation form section), never as a finding per symbol and not through the verify
  pass. The row gives the counts, up to three examples with a place the author can find, and the Word
  replacement that fixes them all: find the symbol and a space, replace with the symbol and `^s`. It
  is typography, not a Bluebook rule, and the report says so.
- Symbols inside a Word field's displayed text (a Zotero citation, a cross-reference, a table of
  contents) are counted separately. A typed fix inside a Zotero citation is wiped on refresh or
  flagged as a hand edit, so the row says to make the replacement after the fields are unlinked.
- Redline: `redline_docx.py --symbol-spaces fix` (the skill now always passes it) puts the
  non-breaking space in as tracked changes, with no comment, wherever a symbol is followed by exactly
  one ordinary space in the body, a footnote or an endnote. It leaves alone, and counts by reason in
  the result's new `symbol_spaces` object, a space inside a field's displayed text or instructions,
  a gap that is not one ordinary space, a space another edit already touches, and one inside or
  beside existing tracked changes or a note mark. These changes are not in the `applied` total. The
  writer's existing checks collapse white space and could not confirm this change, so the pass has
  its own strict check: the accepted text may differ from the expected text only at the recorded
  positions, each a U+0020 that is now U+00A0. Without the option the writer's output is unchanged.
- Limits: `.docx` only (a markdown or plain-text draft is not checked); headers and footers are not
  read for this.
- Tested with synthetic OOXML: the detector, both extractors, and the redline pass (22 tests,
  including fault injection against the strict check and byte-identical output with the option off).
  `run_tests.py` gains a check that the detector in `citeform.py` and the copy in each Codex skill
  stay the same. The two extraction baselines (`endnotes-no-endnotes.json`,
  `headers-footers-no-stories.json`) were regenerated; compared key by key with the old ones, the
  only differences are the new `formatting.symbol_spacing` entry (Claude Code) and the new
  `formatting` entry plus one appended limitation (Codex). Checked by hand on a real draft with 293
  footnotes (not in this repository): both extractors count 27 symbols, 25 of them followed by an
  ordinary space and none inside a field; the redline changed 25 of 25, and the detector run over
  the redlined copy found none left. Not tested: a live run of either skill with
  the check in it, a symbol inside a real Zotero field, and opening the redline in Word.

## 1.6.14 (2026-11-25)

`cite-check` can use the user's own copies of sources from a folder, with no Zotero library needed. Companion Codex version **1.7.7**. Public plugin only; the change is not in the author's private skills.

- Cite-check can use PDFs, TXT and MD from an explicit folder, a project Source
  folder line, Sources beside the draft, or a shared default saved by setup.
  Local copies precede selected Zotero and the web; no Zotero is required.
- Setup asks Zotero/folder/both/neither. The fourth run question resolves folder
  and Zotero choices independently and offers only unsettled halves. Zero/one
  library uses single selection; multiple libraries use a bounded multi-select.
  Prompts and save offers are short; overflow names appear only when needed.
  Folder selection needs no typed path and cannot erase an unoffered saved library.
- Identity uses the document's own head title and byline, rejecting review,
  response and reference layouts and conflicting book editions/years. Scripts
  propose; first-page model inspection and its recorded outcome precede reliance.
  Mismatches fall through to selected Zotero/web. Hits are checked against each
  unit's cited title; the wider pre-existing ledger-key collision issue remains.
- A database cover sheet that states the file's own citation identifies the copy: HeinOnline (three
  layouts), JSTOR, and a repository's recommended citation. A HeinOnline or JSTOR copy is the published
  version; a repository copy is not assumed to be. A cover that cites another work ends the search for
  that file; a cover year that differs from the draft's is reported, not fatal. On a journal's own first
  page the byline may sit above or below the title, run over several lines, and carry a middle initial
  or a footnote mark; an unlisted co-author or a different given name is still a miss.
- Measured on three disjoint samples of 150 journal articles from one real Zotero library (2026-11-25),
  the third never used for tuning: 129, 121 and 119 matched (82 percent overall), 93, 85 and 94 of them
  as the published version. The first version of this matcher found 12 of 150. No wrong match in 450
  shuffled citation-and-file pairs; the only same-surname matches were duplicate records of one article.
  The files are not in this repository; `test_local_layouts.py` reproduces the layouts with invented works.
- Two independent adversarial reviews of the matcher (2026-11-25) each found wrong documents and wrong
  versions it accepted; every case is now a test in `test_local_layouts.py` (classes Adversarial and
  SecondReview). What the matcher now requires: a cover page is recognised by the provider's page
  furniture, never by a provider's name or a quoted citation in ordinary text; a cover's volume, journal,
  page, year, title and authors come from one citation, the title comma-delimited directly before the
  volume; journal names agree word for word (abbreviations and acronyms allowed, initials alone not);
  names are compared person by person, each given name with its own surname, compound surnames and
  suffixes intact; only journal, date, production and banner lines may stand above a title, and a name
  the citation does not list after the byline refuses the match; the citation-line cover layout also
  needs the title and author at the head of the content page; a one-word or stock title needs the page
  to show the cited journal, volume and first page; a title or page that carries another script is never
  matched. For the version: notices of a draft, proof, reprint, early view or accepted manuscript are
  read on the cover, across the first forty lines of the first page and the head of later pages, and the
  work's own title is never taken for one; publication labels must agree on the article's own first
  page; a running citation line counts only beside a standalone page label; a database copy whose page
  labels run from another number, or that has no content page, is not treated as published.
- Known limits. A citation that gives only an initial matches any given name with that initial. A
  database copy that shows no page numbers in its text is still treated as the published scan (43 percent
  of the real HeinOnline and JSTOR copies measured show no first-page number), so the agent that judges
  a pincite must find the printed page itself. OCR spelling in a title is tolerated only on the
  citation-line cover layout, beside the author's surname. A script cannot settle identity for every
  layout, which is why its match is a proposal that the reading agent confirms from the first page.
- Identical bytes are one copy. Exactly one strong published candidate can win
  over drafts, with alternatives disclosed. Every source type needs affirmative
  publication evidence and standalone printed labels for pincites. Accepted and
  repository manuscripts remain unfit; body/footnote mentions are not version
  statements. Quotation results survive while page corrections are refused across
  quote/support report fields. Bibliographic confirm entries are retained.
- The local/Zotero sweep runs with Zotero disabled and returns every source
  containing a quotation, leaving multiple matches unattributed. It cannot decide
  which source the author intended; the wider attribution problem remains.
  Reports name copies and candidates without absolute paths and disclose limits.
- Index only first-page previews, then extract selected copies in full. Caps:
  500 files, 60 MiB/file, 256 KiB/preview, 16 MiB/full extraction, 400 pages.
  Skip hidden/run/cache folders, including runs inside source folders; expand
  tilde paths, report skipped/unreadable inputs, and print progress to stderr.
  Original files stay read-only; extraction is offline, content-hashed and reused.
- Synthetic regressions cover all Amendment 2 items, including generated PDFs,
  missing pdftotext, limits, edition conflicts, duplicate/version selection,
  dialog persistence, workflow report fields and a nonzero-id sweep whose harness
  executes the emitted command. Shared-helper divergence is a run_tests.py gate.
  Validation command: `python3 run_tests.py`; model responses are stubbed.
- Untested: live model/host dialogs, Zotero/web retrieval, installation/update,
  books and book chapters against real files (only journal articles were measured),
  realistic large-folder performance and irregular/scanned layouts. No OCR or installation; cases/statutes, private skills and the app are
  outside this change. Versions are 1.6.14 and 1.7.7.

## 1.6.13 (2026-11-25)

`proofread` now reads referenced DOCX headers, footers and endnotes, including first-page
author notes. It resolves section relationships and inheritance, excludes unused parts and
generated page furniture, and reviews repeated prose once with every occurrence named.
Separate prose segments prevent find strings from crossing omitted field results.
Additional chunks, both full-text views, prose/citation typography lint, verification
prompts and report locations carry the new coverage. Body chunks and extraction with
no added story prose retain their existing output; Markdown is unchanged.

- Endnotes follow reference order with separate display labels, locations and markers.
  Settings/section formats, starts, section restarts and text custom marks are read;
  unsupported formats and page restarts disclose their fallback. Repeated numbers stay
  distinct. Note-level lints and comparisons run within each series; ambiguous references
  are suppressed. Endnotes accompany their call sites in chunks and sort after footnotes.
  Endnote tracked changes, reference-anchored comments, appended periods, accept/reject
  verification and Zotero field handling use the existing footnote safeguards.
  Synthetic regressions cover these paths and no-endnote extraction bytes at `19c9937`.
- Remaining gaps include comment-body prose, image-only text, equation/embedded-object
  contents and imported `altChunk` content; text-box coverage and final layout are not
  guaranteed. Separators and unreferenced endnotes are intentionally excluded.

- First-page story findings sort before the body, other running stories after both note series.
  Citation typography applies to author notes; footnote terminal punctuation, note-order,
  short-form-distance and footnote typeface rules do not. Explicit first/even references
  are inspected even when their display switch is off; no pagination is inferred.
- The redline writer applies a clear correction to all physical copies, or none if any
  is unsafe. It verifies accepted/rejected text and exact header/footer field bytes.
  Comments share a body-start anchor and name all locations. This follows the conservative
  ticket fallback; support for Word anchors inside headers/footers was not established.
  Unplaceable findings remain reported with reasons. Appended periods apply to footnotes
  and endnotes under the same certainty checks.
- Tested with synthetic OOXML and standard-library Python, plus the existing local Node
  workflow-stub pattern: all six story types, shared/identical parts, inheritance, fields,
  tracked text, comments, rejection/acceptance, corruption failures, isolated CLI imports,
  report ordering and extraction compatibility. Repository validation uses
  `python3 run_tests.py`. No real draft, live model proofreading, Word opening/accept-reject
  UI, pagination, Zotero refresh, live Claude/Codex host or fresh installation was tested.
- Checked by hand after the tests (2026-11-25), on the snapshot of the live Dubitante run that exposed the gap: both extractors now return the first-page footer's author note, with the run-together word that was missed; in the Claude Code extractor the draft's 16 existing chunks are byte-for-byte unchanged and a 17th carries the header and footer text; the redline writer placed a correction for that word as a tracked insertion inside the footer part and anchored a comment-type finding at the start of the body, beginning with its location. Inspected as XML, not in Word. One nit left: a footer's rule line of underscores is extracted as text.
- Endnotes, checked by hand after the tests (2026-11-25): the snapshot of the live run's draft was converted so that its 351 footnotes became decimal-numbered endnotes. The Claude Code extractor returns all 351 with their numbers, marks their references `[EN#n]`, and every deterministic lint rule fires exactly as often as on the footnote version (13 missing final periods among them); the redline writer applied the same 41 changes, 12 of them periods appended in the endnotes part, none opening inside a field. The unconverted draft extracts byte-for-byte as before. A converted file is not a document Word produced, and nothing was opened in Word.

## 1.6.12 (2026-11-25)

`proofread` redlines can append a missing final period for a `cite-terminal-punct` finding without a replacement, including a footnote ending in a Zotero citation. The period is a plain tracked insertion after every field; field instructions and results stay unchanged, and trailing whitespace outside the field stays after the period. The excerpt must match the extractor's footnote-end text, terminal punctuation must be absent, and existing deletions, move sources, uncertain field boundaries and conflicting edits prevent application. Two findings at one end produce one period; declined edits remain comments on the footnote's body reference.

- Policy stays in `edits_from_findings`. The validated `append-period` edit kind also works through `--edits` without a `replacement`; the result identifies the kind and counts the insertion in `applied`, never `applied_in_zotero_fields`.
- Accepted and rejected text verification still runs before publication. Unedited fields in an appended footnote are also checked across their full byte ranges, including their displayed results and formatting. Ordinary replacements and other lint categories retain their existing policy; the Codex `internal-proofread` skill is unchanged.
- The terminal-punctuation guard follows the existing lint exactly: it strips closing quotes, but not closing parentheses. This differs from the ticket's description of the lint; a note ending in `.)` therefore still receives a period after the parenthesis. The lint itself is unchanged.
- Tested with standard-library Python on synthetic OOXML: the ticket's eleven cases, nested and incomplete fields, malformed field markers, moved-from ranges, conflicting edits, extractor whitespace parity, direct CLI input, and verification failure on changed field formatting. Full repository checks are run with `python3 run_tests.py`. **Not tested:** opening any output in Microsoft Word, Word's accept/reject UI, Zotero refresh, or a live proofread/Dubitante session. No real draft was used by the tests.
- Checked by hand after the tests (2026-11-25): the writer was re-run on the snapshot and findings of a live Dubitante proofread of a Zotero-linked article draft (134 findings, 12 of them `cite-terminal-punct` without a replacement). All 12 became appended periods (applied 29 to 41, commented 100 to 88); six sit directly after a citation field's end marker and six after plain text; none opens inside a field and none carries character formatting; the writer's own accept/reject verification passed. The output was inspected as XML, not in Word.


## 1.6.11 (2026-11-23)

`cite-check` now reports a case citation that resolves to a different case, or a different year, than the draft gives. `find-cite` becomes a workflow. All three workflow scripts refuse unusable arguments. These came out of one headless run of each skill through a host program on 2026-11-23 (Sonnet lead; an invented six-footnote draft with four seeded defects for cite-check). After the fixes the same cite-check run reported all four seeded defects where 1.6.10 reported two, and the new find-cite returned its cite verified in full, with a pincite read from the source's page markers and a quotation confirmed by script, where the inline skill had returned it partly verified with no pincite. **Not tested:** a draft of real size; find-cite's scholarship lane, Zotero, or a second cite in a live run; a session relaunching a workflow after an argument error. Codex plugin 1.7.5, released the same day, closes the same case-identity gap in the Codex cite-check skill (see `codex/CHANGELOG.md`).

**cite-check: a hole that was always there.** The existence pass was given bare reporter strings and asked only whether each resolved. Nothing compared the resolved case name and date with the draft. In the live run the draft cited *Sherman v. United States* at 356 U.S. 396, which CourtListener's lookup resolves to Thomas v. Arizona, and gave *Sorrells v. United States*, 287 U.S. 435, the year 1934 where the lookup gives a 1932 decision date. The report said all five case cites were confirmed with no metadata issues. One agent noticed both in a per-case note that nothing read. This has been true of every released version. It affected unquoted case cites with the support pass off, which is the default.

- `cite-check.workflow.js`: after the existence pass, the script compares each full case citation's name and year with the caption and date its reporter cite resolved to, with no model. A name is flagged only when no distinctive party word of the draft's name is in the caption: Bluebook abbreviations, first names and long party lists in a caption, `In re` and `Ex parte`, acronyms, a one-letter spelling difference, and generic parties (United States, State, a state's own name as sovereign) do not cause a flag by themselves. A year is flagged when both years are present and differ. Comparison runs only when CourtListener's citation lookup itself resolved the cite. The comparison rests on the caption and date the existence agent copies from the lookup's output; the prompt now tells it to copy them exactly.
- A flagged citation is a finding everywhere: new counts (`caseCiteMismatches`, `caseNameMismatch`, `caseYearMismatch`), a `case-metadata` item in the findings export, a `finding` disposition in the ledger, its own section in the report, and a summary line that may no longer say the case cites were confirmed. The finding states what the draft says and what the lookup returned, and that either the name (or year) or the reporter cite may be the part that is wrong. `scripts/findings_diff.py` and `scripts/citation_ledger.py` know the new kind.
- **Limits are always listed.** The run above ended `complete_with_limits` with an empty `degradation` list, because the exit state was also set by counts (here one treatment lookup that got HTTP 429) that added no sentence. Every cause now adds one, including history entries an agent marked as a tool error, and the exit state is `complete_with_limits` exactly when the list is non-empty.

**find-cite is a workflow.** The skill ran in the lead session and told it to fetch pages. In Claude Code 2.1.330 the lead session is not offered `WebFetch` (checked headless, with and without `--restricted`; not checked in an interactive session), so the skill lost CourtListener and Justia. Workflow agents can fetch.

- New `find-cite.workflow.js`: a search-only sweep per lane (Haiku), one verifying agent per candidate (Sonnet), and assembly in code. At most 12 agent starts. It keeps the old skill's rules: the canonical cite first, the scholarship ranking with student notes last, fit over fame, a pincite only if it was seen, anything that fails verification dropped and counted.
- A quotation ships only on a receipt from the new `scripts/quote_receipt.py`, which runs cite-check's deterministic `verify_quotes.py` over the fetched text; otherwise the cite carries a paraphrase and says so. The receipt also prints the matched passage as plain source text, so the plugin's quotation hook finds each delivered quotation in a raw tool result. The hook is unchanged.
- A lane delivers its own kind of authority. The first live run, asked for cases only, also delivered a manual page it had not opened; a cases lane now ships cases only, and an unopened source of another kind is dropped.
- The workflow returns fields (`cites`, `gaps`, `counts`, `exitState`, `degradation`, `dropped`) and `entry`, the footnote-ready Markdown rendered by the script from those fields. A host program can append `entry` to a document and list `cites`. `SKILL.md` is rewritten for the new flow.
- A gap in the quotation hook, noticed and not changed: if the lead reads a workflow's output file into the conversation, that result counts as a source for its own quotations. `SKILL.md` tells the lead not to read it.

**Arguments.**

- `legal-research.workflow.js` and `cite-check.workflow.js` stop before any agent starts when their arguments are a string that does not parse, are missing, or lack what a run needs (`question`; `extractPath`, the counts, `caseCites`, `ledger`, `secondaryCites`), as proofread has since 1.6.10. Before, legal-research ran its whole pipeline on a placeholder question. Each `SKILL.md` says to pass `args` as an object and to launch once more on that error.
- In all three workflows a switch is on only for `true` or the string `'true'` (and `history` and `zotero` off only for `false` or `'false'`). The string `'false'` is truthy and used to turn a switch on: in proofread that selected Fable proofers or deep mode, in cite-check the support pass.

Tests: new `test_workflow_args.py` in legal-research and cite-check, `test_workflow_case_metadata.py` in cite-check (the live draft, a table of name pairs that must and must not be flagged, the year rules, the exit-state invariant), and `test_workflow.py` and `test_quote_receipt.py` in find-cite; additions to proofread's `test_workflow_args.py`, `test_citation_ledger.py` and `test_findings_diff.py`. The cite-check fixes and the find-cite workflow were written by Claude Opus agents and reviewed by Claude Fable, which also checked the name rules against a separate table of 27 pairs.

## 1.6.10 (2026-11-23)

`proofread`: the workflow checks its arguments before it starts any agent. Observed in a live run through a host program (Sonnet lead, invented 807-word draft): the session passed the workflow's arguments as a JSON string instead of an object, and the string did not parse because a fragment of the `formatting` block was repeated. The script caught the parse error and carried on with no arguments, so `outDir` was empty, the consistency agents were sent to `/fulltext.txt` and `/proof.json`, both reads were refused, and the session stopped the workflow. The run failed after 17 seconds and about USD 0.17. Checked offline with the new test below, by `run_tests.py`, and in one live run through the same host program on the same draft, which completed normally. **Not tested live:** a session actually relaunching the workflow after the new error; the error path is covered offline only. Codex plugin unchanged.

- `proofread.workflow.js`: arguments that arrive as a string that is not valid JSON now stop the script with an error that says so. So do missing arguments, a missing `outDir`, a `chunkFiles` that is absent, empty or not a list of paths, and a `lintFindings`, `headings`, `counts`, `noteParas` or `formatting` of the wrong shape. Every problem found is named in one message, and no agent is started. A string that does parse is still accepted. A run with usable arguments is unchanged.
- This is a check, not a cure. The session still retypes the extractor's output into the call, because a workflow script cannot read `proof.json` itself. A garbled value that still parses and still has the right shape is not caught here; the verify stage re-reads every finding against the snapshot, which is what catches an altered find string.
- `SKILL.md` step 4 now says to pass `args` as an object, never as a JSON-encoded string, and to launch the workflow once more if it reports unusable arguments.
- Tests: new `scripts/test_workflow_args.py` (19 checks, stubbed agents), including the shape of the string seen in the live run.

## 1.6.9 (2026-11-23)

`proofread` redline: a correction inside a Zotero citation now goes into the citation's stored data, not only onto the page. Run on a copy of a real article draft (224 Zotero citations): 97 synthetic pincite and parenthetical changes were applied in their fields; an independent comparison of every field before and after found exactly three values changed in each of those 97 (the pincite or parenthetical and the two stored copies of the displayed text) and the other 127 fields byte-for-byte identical. **Not tested:** opening the result in Word, and whether a Zotero refresh accepts the edited fields without flagging them. Those need Word and Zotero and have not been done.

- `scripts/redline_docx.py`: when the changed characters of a correction belong to one citation item's `locator` (pincite), `prefix` (signal) or `suffix` (parenthetical), the script patches that value and the field's `plainCitation` and `formattedCitation` in the field code, and tracks the visible change in the displayed text. The field code itself is not a tracked change, because Zotero cannot read one. The comment says so: rejecting the change in Word does not undo it, since a Zotero refresh will show the new text.
- It edits only when it is certain. The component must appear verbatim, once, in the displayed text (a pincite as a whole token), with no markup beside the changed characters; the same substitution must be possible in both stored copies of the displayed text, in `formattedCitation` as plain ASCII with no RTF escape inside it; and the citation must not be marked `dontUpdate`. Otherwise the correction stays a comment that gives the reason. Text from the library item or the citation style (author, title, volume, page, year) is never edited: the comment says to change it in Zotero.
- The field code is patched by byte range inside the affected JSON strings; the JSON is never re-serialized. Before saving, the script checks that every unedited Zotero field is byte-for-byte unchanged, that each edited field's JSON differs only in the intended values, and that its stored plain text equals the displayed text with the changes accepted.
- New option `--zotero-fields edit|comment` (default `edit`); `comment` restores 1.6.8's behavior. The result file marks such an edit `"field": "zotero"` and counts them in `applied_in_zotero_fields`.
- Fix: a find string padded with spaces is no longer treated as a lint excerpt when the replacement carries the same padding.
- A draft with a damaged citation field still gets its redline: that field is only commented on and is checked for unchanged bytes.
- Tests: `scripts/test_redline_docx.py` now has 49 tests. The field editing was written by Codex (gpt-6-astra) and reviewed and adjusted by Claude.

## 1.6.8 (2026-11-23)

`proofread`: an optional redline. Besides the report, the skill can save a marked-up copy of a `.docx` draft, with the clear corrections as tracked changes and everything else as comments. It is off unless chosen, and a run without it is unchanged: with the new argument left out, every agent prompt, every schema and the rest of the workflow's return were compared with 1.6.7's under stubbed agents and are identical. Exercised in one live run through a host program on an invented 807-word draft (5 tracked changes and 6 comments from 11 findings), and the writer was run with 227 synthetic edits on a copy of a real article draft (229 footnotes, 224 Zotero citations): all 317 paragraphs and footnotes read the same as the extractor reads them, and the 87 changes that fell inside Zotero citations became comments. Word opened an earlier build's output for both documents, listed the main-text changes and comments, and removed a footnote insertion when all changes were rejected, so tracked changes in footnotes are real revisions to Word. **Not confirmed in Word:** the final placement of footnote comments (next bullet), which was written after those checks. The skill's own dialog question and deliver step have not been run in a live session.

- New third question in the opening dialog, `Redline` (off by default, `.docx` only), and a deliver step that builds the copy and saves it beside the report. The draft itself is still never edited.
- New `scripts/redline_docx.py`, standard library only, which builds the copy from the workflow's findings without launching Word or any other program. A confirmed finding of severity `error` that carries a replacement becomes a tracked change with a comment; every other finding becomes a comment. A change that would touch a Word field (a Zotero citation is changed in Zotero, never in its displayed text), a footnote mark or an existing tracked deletion becomes a comment that states the proposal. Findings on the same words share one comment, and a correction takes the span ahead of a comment. It edits the document's XML by byte range, so every part it does not change is copied unchanged.
- A comment about a footnote hangs on the footnote's reference mark in the text, one comment per footnote, naming the words it is about. Word has no comments inside footnotes and silently drops any it finds there, which an earlier build of the script learned on the real draft (203 comments lost on opening).
- The script verifies the copy before saving it: with its tracked changes rejected the text must equal the draft's exactly, and with them accepted it must equal the draft's with only the intended replacements. If either check fails, no file is written.
- New `findings` array in the workflow's return: every confirmed finding, in draft order, with `location`, `find`, `problem`, `fix`, `severity` and `category`. Unvetted and rejected findings are not in it. The report is unchanged.
- New optional workflow argument `replacements` (default off), passed only when a redline was chosen. With it on, proofers and the consistency agents add `replacement`, the find string with only the correction made, when the fix is a pure text substitution. The verifier is shown it and asked to check that it changes nothing but the error; it can correct it (`revised_replacement`) or withdraw it. A replacement is dropped when the verifier revises the fix, the severity or the find string without supplying a new one, when a revised find string fails the snapshot check, when it equals the find string, and on author queries and typeface findings.
- Known limit: the deterministic lint's findings (a doubled word, a broken note number) carry no replacement, so they arrive as comments, not tracked changes.
- Tests: `scripts/test_workflow_findings.py` (22 checks, stubbed agents) and `scripts/test_redline_docx.py` (25 tests on synthetic documents). The writer was drafted by Codex (gpt-6-astra) and reviewed and extended by Claude.
- Codex plugin 1.7.4 (see `codex/CHANGELOG.md`), released the same day: the Codex `internal-proofread` skill gains the matching optional exact corrections in its findings. Nothing applies them to a Word file for that skill yet.

## 1.6.7 (2026-11-22)

Quotation-check hook fixes. Observed in a headless `/proofread` run: the session saved the report the proofread workflow returned, the plugin's own Stop hook blocked the saved report twice, the model stripped every quotation mark and blockquote marker from the file to get past it, and the hook then let the reply through as still unverified after two retries. The saved report no longer matched the workflow's. The fixes were checked by replaying that run's transcript through the new hook (the report is allowed, and with the workflow's result removed only genuine quotations are listed) and by the offline tests below. One live headless `/proofread` run followed with the fixed hook: it did not block, the session took five turns instead of seven, and the workflow's report was saved unchanged. The list-item pairing fix and the re-check of a file fixed after a block were not reached in that run, since nothing was blocked; they are tested offline only. Codex plugin unchanged.

- The returned result of the proofread workflow now counts as a source. It counts only for a `Workflow` call whose `scriptPath` is this plugin's `skills/proofread/proofread.workflow.js`, with no inline script, and whose script file the session did not write or edit. The text is read from the `<task-notification>` that carries that call's id. The notification cuts a result at about 8,000 characters, so the hook then reads the full result from the output file the notification names, or from the run record beside the transcript. The trusted scripts are an explicit list (`TRUSTED_WORKFLOWS` in `quote_common.py`) holding only proofread. The legal-research and cite-check workflows are left out on purpose: their memos and reports quote cases and articles, and this hook is the check that those quotations match fetched sources. A saved research memo is checked against the same sources as in 1.6.6. A workflow's summary line, any other agent's report, `WebFetch` and `WebSearch` still do not count. **This is more permissive than before:** a sentence the proofread workflow's agents wrote, such as a proposed rewording, can now be repeated in quotation marks.
- Quotation marks pair in order within one paragraph, list item, heading, table cell or run of blockquote lines, never across them. The old pattern skipped pairs under ten characters, so the closing mark of a short quotation (`"the the"`) opened a phantom quotation that ran into the next list item. A straight mark now opens or closes by its neighbours, the rule the private quote-guard mod has used since 2026-11-10, so a stray inch mark no longer hides a later quotation. A quotation wrapped over several lines of one paragraph or list item is still checked as one.
- A file written this turn is checked as it is on disk when the hook runs. The hook used to re-check the text of the original `Write` call, so a file fixed after a block, with `Edit` or a shell command, was flagged again for text it no longer held. The `Write` text is used only if the file is gone. For a file only edited this turn, a quotation on disk is checked if one of this turn's edits added it.
- Tests: `claude-code/hooks/tests/test_quote_check.py` (43 new checks, 130 in all), including a regression built from a trimmed copy of that run's report. Transcript-only tests now name files under a directory that does not exist, since the hook now reads files from disk.

## 1.6.6 (2026-11-16)

`legal-research`: the memo is no longer retyped after it is drafted, and the Finalize stage can run on a cheaper model than the Draft. Exercised in one live run (lean, caselaw), in which all 19 edits were placed without a repair round; that run and a second one led to the fixes in the last bullets of this entry. The second run exercised the gap-fill weaving fix (30 call-in edits, all placed); the skipped-check flag, the header replacement and the read-tag fix are tested offline only.

- Every stage after Draft (the deep-mode calibration pass and Finalize) now returns find-and-replace edits, and the workflow script applies them. Text that no edit names stays exactly as the Draft wrote it. Finalize returns the Table of Authorities and the Limits section as separate fields, which the script places after the memo. Before this, calibration and Finalize each returned the whole memo again, which cost a full memo of output per pass and let a pass shorten or restyle prose it was told to leave alone.
- An edit whose find text is not in the memo gets one repair round. One that still cannot be placed is listed at the end of the memo's Limits section, returned in `finalize.unappliedEdits`, counted in `counts.editsUnapplied`, and keeps the run from ending `complete`; `SKILL.md` has the orchestrating session apply it by hand. A find text that occurs more than once is refused unless the edit says `all: true`. A pass whose edits would cut the memo by more than 40% is discarded.
- New optional argument `finalizeModel`. Left out, Finalize inherits the session model as before, so a session run entirely on Sonnet or Opus is unchanged. `SKILL.md` passes `"opus"` only when the session model ranks above Opus. No model is hard-coded in the script.
- With `finalizeModel` set, the changes that alter what the memo can claim go to one call on the session model before Finalize: a load-bearing authority that failed verification or that no checker examined, negative treatment of a load-bearing authority, an authority verified over a minority objection, and every gap-fill authority. The script decides this from the cite-check verdicts. `escalate: false` turns it off. `finalize.callIn` in the result says whether it ran.
- New `save_memo.py` copies the finished memo out of the run's output file into the `.md`, with the header under the title and the production details at the end, and never overwrites a file. `SKILL.md` now delivers the memo as that file plus a short summary in chat, not as a retyped copy.
- Fix from the live run: an authority retrieved after drafting is now woven in as a full member of the memo. The call-in (or Finalize, when no `finalizeModel` is set) must add a row to any table of the authorities read, update every count and the title, and cite it in a footnote where the memo uses footnotes. Told only to make the lightest change, the call-in had left the title, tables and counts describing the original set and cited the additions inline.
- Fix from the live run: a gap-fill authority that the run read is no longer reported as unread. The cite-check verdict has a new `examined` field; `unverified` with `examined: false` on a source the run read is treated like every other source the checker did not re-open (verified on the run's own read, with a note that the checker ran nothing). A gap-fill authority the checker examined and could not confirm now goes to the call-in too, under its own reason, and is woven in with a statement of what the check did and did not confirm.
- Fix from the live run: `save_memo.py --header` replaces a `By:`, `Topic:` or `Date:` line the draft wrote under the title instead of adding a second, and lists the replaced line in its summary.
- `SKILL.md`: a question that asks for every member of a set (every opinion by a judge, all cases citing a decision) is flagged before launch, because the pipeline reads a fixed number of sources; the instruction is to list first and read each item outside this workflow, or to narrow the question. A billed-token total taken from the agent transcripts must count each response once (group by `message.id`); a per-line sum doubles it.
- Fix from a second live run: a source a reader opened keeps its "read this run" tag when the reader's citation carries a pincite, a parallel cite or an opinion parenthetical that the draft's citation does not. The two were matched as whole strings, so four of eight opinions read on that run were reported as load-bearing authorities checked at citation level only. They are now matched on the reporter cite.
- New `check_memo_quotes.py`, run in the deliver step after the memo is saved: it checks every quotation in the memo against a copy of the source its footnote cites, with no model reading anything. Sources are local PDF or text files named by reporter cite, then (with `--fetch`) a URL in the memo's footnote, the Caselaw Access Project page for a U.S. Reports cite, and CourtListener's API text. Matching and page-finding are done by cite-check's `verify_quotes.py`. It appends an addendum table to the memo and prints the pins that differ, the quotations not found, and the cases with no source. It does not check paraphrases, and it reports no page for text that carries no reporter pagination.
- Tests: `test_workflow_pipeline.py` (62 new checks), `test_save_memo.py` and `test_check_memo_quotes.py`.

## 1.6.5 (2026-11-15)

Fixes from a code review of the three workflow scripts. Each defect was reproduced by running the script under stubbed agents and has a regression test; none was observed in a live run. The review, organized by kind of mistake, is in `reviews/2026-11-15-claude-workflow-review-for-codex.md`. Codex plugin unchanged (1.7.2).

`cite-check`:

- A high-severity finding that the second checker corrected to a different finding (a mismatch that is really a syllabus quotation or a wrong pincite) was dropped from the report as a "checker artifact" and counted as verbatim. It is now reported under the corrected verdict, with the first verdict named. Only a correction that clears the quotation withdraws the finding, and a cleared finding's ledger entry is `verified`, not `existence-only`.
- Re-verification results were matched to findings by the id the agent echoed, and the prompt showed the id only inside a command. An agent echoing the neighbouring id turned a clean quotation into a re-verified high-severity finding. Results are matched by job position, and the prompt states the id. Verify agents' verdicts are likewise kept only for the quotations the agent was given.
- Re-verification was all-or-nothing under budget pressure, and the reserve held back for it (40k) was less than one re-verify agent (100k), so a budget-bound run with two or more high-severity findings skipped the pass. The reserve is now three quote and two support re-verifications (capped at a tenth and a twentieth of the cap), and the pass re-derives as many findings as fit. **This changes budget-bound runs:** up to two fewer sources are verified so that findings can be re-derived; sources not reached are listed as not checked, as before.
- A case-existence batch whose agent died is retried once, and cites nobody answered for are listed in `degradation`. Verify tail batches retry once.
- Each agent writes its scratch files under a path unique to the run and to itself. Agents used to share `/tmp/src-<slug>.txt` and `/tmp/q-<slug>.json`.
- The report prompt sent secondary-source items to sections G and H (history and support); they go to E, I and J. `SKILL.md` quoted the history batch at 110k against the script's 350k.

`legal-research`:

- Deep mode, refutation panel: negative treatment reported by one voter was dropped when an earlier voter had written "none found". Every distinct report now reaches the memo, attributed. A citation correction proposed by one voter of three replaced a citation the other two found accurate; a correction now needs a strict majority, and a minority proposal is disclosed in the memo's Limits section.
- A refuted authority was labelled "verified (3-voter refutation panel)". Validation labels now follow the verdict, and statutes and secondary sources no longer claim a citing-opinion probe.
- A dead survey vector or reader left no trace, and the run could end `complete` with its top-ranked source missing from the draft. Both retry once; a second failure is a named coverage gap (`counts.surveyLanesFailed`, `counts.readsFailed`), passed to the memo's Limits section, and the unread source stays visible as an unread lead. A dead triage agent no longer crashes the run.
- Authorities harvested from the read sources never reached the draft, because the search leftovers filled the lead cap first. A third of the lead slots are kept for them.
- The soft cap is measured from the start of the run, not the start of the turn.
- A source a reader opened this run is no longer stamped `direct-full-text`; its basis is at least `authoritative-reproduction`, with a note that the cite-checker did not re-open it.
- Readers are told to probe candidate URLs with `probe_sources.py` in one call, as `SKILL.md` has said since 1.6.0. The "no hallucinated law" guardrail in `SKILL.md` now describes what the cite-check does and does not confirm.

`proofread`:

- A verifier's verdict for a finding outside its batch could overwrite that batch's verdict. Verdicts count only for the findings the verifier was given.
- The read-only guarantee is described accurately: the agent type has no file-editing tools but does have a shell, so the guarantee rests on the draft's path never reaching an agent and on the write-protected snapshot.

Tests: `cite-check/scripts/test_workflow_quotes.py`, `legal-research/test_workflow_pipeline.py`, `proofread/scripts/test_workflow_verify.py` (new, each with a stubbed-agent harness); `cite-check/scripts/test_workflow_support.py` updated for partial re-verification.

## 1.6.4 (2026-11-14)

The two reports from issue #2 that 1.6.3 left open. Both were correct quotations wrongly rejected.

- Claude Code `cite-check`, `scripts/verify_quotes.py`, soft hyphens: a word split by a soft hyphen at a line end ("un", U+00AD, line break, "necessary"; common in `pdftotext` output) read as two words, so the whole-word quotation was `not_found` while the split form "un necessary" matched. The halves are now one word at every tier: the whole-word quotation is `verbatim` and the split form is `not_found`. Any whitespace after the soft hyphen counts, since re-flowed or pasted text turns the line break into a space; a soft hyphen in the middle of a line is still just dropped.
- Bracketed star-page markers: "[*516]" stayed in the text as brackets, so a quotation crossing a page was `not_found`. A bracketed marker ("[*516]", also "[**12]" and "[***3]") is now treated as whitespace wherever it appears, and counts for star pagination the same way a bare "*516" does. A lone bare "*516" is still text, since it may be a footnote asterisk.
- This also closes a partial-match hole: a word hyphenated across a line with a bracketed marker in the gap ("in-", line break, "[*516]", line break, "eligible") used to match the quotation "eligible ...". It is rejected, and the whole word matches as `normalized`.
- Quotation Stop hook (`claude-code/hooks/scripts/quote_check.py`): the same two changes.
- Tests: regression cases in `test_verify_quotes.py` and `claude-code/hooks/tests/test_quote_check.py`, including pagination and pincites from bracketed markers.
- Codex plugin 1.7.2 (see `codex/CHANGELOG.md`): the same two changes in the Codex `cite-check` verifier.

## 1.6.3 (2026-11-14)

Quotation matching now requires whole source words and numbers. Reported in issue #2: the matchers located a quotation with a plain substring search, so a quotation that began or ended inside a source word or number passed as verbatim.

- Claude Code `cite-check`, `scripts/verify_quotes.py`: "eligible for copyright protection" came back `verbatim` against a source that says "ineligible for copyright protection", and "pay more than $400," against "$400,000". A match must now start and end on a source-token boundary. A cut is inside a token between two letters, two digits, or a digit and a following letter ("10b"); next to an apostrophe with a letter on each side ("can't"); at a thousands comma or decimal point inside a number; and next to a single hyphen joining two word halves, closed up ("non-binding") or broken across a line or page (a soft hyphen at a line end included). The rule covers the verbatim and normalized tiers, occurrence counting, pincite-based occurrence selection and both edges of every ellipsis segment; an edge occupied by a bracketed alteration is exempt ("[T]he" for "the"), and when a bracket's first expansion ends inside a word its other expansions are tried ("The [official] may" matches "The old mayor may issue" through "old mayor"). A quotation that includes a joining hyphen but not the other half ("The work is non-" against "non-binding") is a partial match too. A partial hit is `not_found` with a new `partial_token_match` field showing the source's own words, and the workflow prompt tells the verifying agent to report it as a finding. A later whole-token occurrence in the same source is still found.
- Accepted on purpose, with a new `match_abuts_digits` warning, because flattened footnote calls look like this: a word followed directly by digits ("protection12"), and a number, a period, then one to three digits before a new sentence ("in 1871.45 The Court"). The cost: "§ 1614" quoted from "§ 1614.105 The" passes with the warning.
- Stricter than before: a quotation that stops before a possessive or inside a hyphenated compound ("the court" from "the court's", "decision" from "decision-making") is now `not_found`.
- Quotation Stop hook (`claude-code/hooks/scripts/quote_check.py`): the same rule replaces its substring test. Letters outside a-z now count as letters (they used to become spaces). Replayed against 5,272 random whole-word spans of Markdown prose, the new check rejected none that the old one accepted.
- Also fixed, older than this release: a bracket-only quotation against an empty source raised `IndexError`.
- From issue #2, fixed: the dropped-prefix examples, the statute cite cut one digit short ("47:1A-1" against "47:1A-11"), the amount cut at its comma, and the prefix-less quotation that matched across a soft hyphen at a line end. Not addressed, both false rejections and not partial matches: a correct whole-word quotation of a word split by a soft hyphen at a line end, and a quotation that crosses a bracketed star-page marker (`[*516]`), are still `not_found`.
- Tests: regression cases added to `test_verify_quotes.py` and `claude-code/hooks/tests/test_quote_check.py` (dropped prefixes, truncated amounts and identifiers, apostrophes, hyphens, Unicode letters, combining marks, a whole-token occurrence after a partial one, repeated occurrences on different pages, folded typography, marked alterations).
- Codex plugin 1.7.1 (see `codex/CHANGELOG.md`): the same rule in the Codex `cite-check` verifier.

## 1.6.2 (2026-11-12)

Claude Code `cite-check`, fixes from a full-draft run that left 65 quotations unverifiable or unchecked although, for most of them, the Zotero pre-lookup had already put the source's text on disk.

- Short forms and `Id.` as quote sources: the segment stage could hand back a `supra` short form or a bare `Id.` as a quote's source. The short form never matched its Zotero record, and every `Id.` quote, from many different works, was pooled into one bundle sized for one source. The ledger now matches a `supra` whose note number is stale (the note it names does not cite that author, the usual renumbering break) to the earlier full cite by author name and any short-title word, accepted only when one source fits; the stale number is still reported, and the support pass uses the match. The workflow completes any `Id.`/`supra` source from the ledger and groups quotes by ledger key, the key the Zotero pre-lookup uses; anything still unresolved is re-asked once, then keyed by its own footnote, never pooled.
- Segment retry: units missing from a segment agent's answer (one returned 2 of its 28) are re-asked once in chunks of 7 instead of being listed as not checked.
- History pass: a hard tool-call cap, a recalibrated cost (it measured about seven times its model), and it now runs after the quote, support and re-verify passes, launching only the batches that fit what is left; the rest are listed as not checked.
- Zotero pre-lookup: forthcoming articles cited with an SSRN URL were never looked up; they are now, as is any secondary cite with an author and a title. A chapter cite (`Author, Title, in Book`) now takes the chapter's own record instead of the parent book's, editors are no longer counted as authors when a record has authors, `et al.` is no longer read as a surname, and a record with a PDF wins a near-tie.
- New pre-report Zotero sweep (`scripts/zotero_sweep.py`, deterministic): every quote still unverifiable, unchecked or unresolved is checked with `verify_quotes.py` against every Zotero text its footnote's citations reach; a match replaces the verdict (pincite not judged), and a match in a different work than the one resolved is flagged for an attribution check.
- Report: each unverifiable quote in section I carries its Zotero state (text read from Zotero; record without a PDF; not in Zotero), so the report no longer tells the author to attach a PDF that is already attached. The report no longer crashes on a ledger entry without citation text.
- Tests: new `test_zotero_sweep.py`; regression checks in the ledger and Zotero-lookup tests; six new harness scenarios (segment retry, ledger `Id.` resolution, unresolved `Id.` keying, history order and cap, the sweep, the sweep skipped for budget).

## 1.6.1 (2026-11-03)

Changes to the Claude Code `legal-research` memo workflow, taken from a read of the wise-men-flash decision skill (github.com/Ali-expandings/wise-men-flash, MIT; ideas only, no text copied), then reviewed by Codex (gpt-6-astra, 2026-11-03, with stubbed-agent reproductions) and revised on its findings. No new agent calls and no new phases. Prompt overhead is a fixed addition to the Draft and Finalize prompts plus per-voter text on each panel authority in deep mode (measured with Codex's stubbed-agent harness against 1.6.0 after the review fixes: about 260 added prompt words on a lean run with one cited authority, about 870 on a deep run with one panel authority, and about 5,200 on a deep run with eight, with the agent-call sequence identical; retries add more; tool and response costs were not measured).

- Claude Code `legal-research`, deep-mode refutation panel: the three voters on each load-bearing authority used to receive one identical prompt, so a shared blind spot could carry the vote. Each voter now leads with a different route — voter 1 the record (existence and citation accuracy settled deterministically before any reading), voter 2 the passage in context (the surrounding paragraphs and whose opinion it is, judged against the proposition as stated), voter 3 the strongest adverse reading (treatment and history first, then a narrower holding, an omitted limiting fact, a competing line the source itself acknowledges). The routes are source-aware: a statute, regulation, rule or constitutional provision gets the official text at the cited section in the version in force, with amendment, repeal, invalidation and a narrowing definition as the adverse reading; an article or book gets catalog and front-matter checks, with a later edition or published reply as the adverse reading; neither calls CourtListener. The type comes from the Draft's `kind` where it is explicit; otherwise from an explicit statutory signature (U.S.C., C.F.R., Stat., Pub. L., Fed. R., Const.) or a reporter cite with no journal marker (markup stripped); a caption alone, a bare section symbol (Restatements, treatises) or a title that names a case does not decide the type, and anything undecided keeps the case route under an instruction to establish its type first, so a harvested cite stamped `other` never loses its case tools. Every voter prompt now carries the memo question and the research date and, on a historical run, the question notes and the rule that an amendment or later treatment after the date the proposition concerns is a disclosure, not a refutation (a target date that appears only in the question would otherwise never reach a voter). The shared tool guidance is order-neutral so a route's own sequence governs (all from Codex's reviews of the drafts of this change). All four checks remain mandatory for every voter and the majority rule is unchanged, but the aggregation no longer discards reasons: every voter's reason is kept with its seat and route (the old code kept the first two, which after differentiation was always the adverse-reading voter's that vanished, a pre-existing defect Codex reproduced), and a refutation the majority outvotes becomes a **minority objection** — quoted in the cite-check results, shown in the authority's Validation label ("verified (3-voter refutation panel, 1 objection unresolved)"), counted in `counts.panelObjections`, disclosed as a coverage limit so the run ends `complete_with_limits`, and handed to Finalize with the instruction to qualify the memo's use of the authority where the objection names a narrower holding, an omitted limiting fact or a mischaracterized posture, or else to list the authority under "Verified over an objection" in Limits. A majority does not resolve an objection. The routes are intended to reduce correlated omissions; all three voters still run on the same model, so no independence or accuracy gain is claimed without evaluation.
- Claude Code `legal-research`, Draft brief (claim calibration): two rules added. Trace each proposition to its origin; repetitions of the same underlying evidence are not independent corroboration and a head count is not a confidence level, so confidence is assessed from authority, verification basis, genuinely independent contributions, contrary evidence and coverage (wording adopted from the Codex review, which found the first draft's best-authority-only rule would discourage counting a distinct court's application as evidence). For each material contested issue, the Discussion states the counter-position at full strength, as its proponent would put it (the premise it attacks, the authority it rests on, the facts or interpretation under which it wins), never as the memo's conclusion restated with hedges; summary sections carry the resulting qualifications without repeating the argument.
- Claude Code `legal-research`, Finalize: a consistency audit across sections, next to the existing quantifier audit. Brief Answer or Introduction, Discussion, Conclusion and Limits must tell one story; the summary sections are edited to match the Discussion and the cite-check results, never the reverse (a confidence up top the weakest load-bearing authority cannot support, a bottom line stated as settled over unresolved contrary authority, a qualification the Conclusion drops, an absolute a later section undercuts, a number that differs between sections).
- Not adopted from wise-men-flash: its "second model" check on the memo (wise-men-flash's own checker runs on Haiku, the same model family as its members; this plugin's models are unchanged — Haiku for the search survey, Sonnet for reads and verification, the session model for Scope, Draft and Finalize — and the Codex review path already supplies a genuinely different model), offline members answering from training data (contrary to this plugin's source-grounding rule), and a separate consistency-checking agent (an extra call per run; the audit rides in the Finalize call instead).
- Tests: `claude-code/skills/legal-research/test_refute_routing.py` (skipped without node) runs the workflow under stubbed agents and checks the authority-type classifier on 18 citations, the per-type voter routes and the order-neutral tool tip, that an outvoted refutation reaches Finalize as a quoted objection with its count, tier label and `complete_with_limits` state, that every voter's reason survives aggregation, and that a historical run passes the research date and the historical rule to every voter; the offline suite grows to 47 test programs.
- `run_tests.py`: the Markdown link check now skips the gitignored `AI Memos/` folder, as it already skipped `.codex-memo/`; a review memo there with absolute file links had turned the suite red.
- Codex plugin 1.6.1 (see `codex/CHANGELOG.md`): on its review of this change, Codex adapted three of the ideas into its own `legal-research-memo` skill without agents or voting — the full-strength counterargument per contested issue, record / context / adverse-reading lenses inside its existing bounded refutation pass with source-appropriate tools and an evidence-based disposition for every material objection, and a post-correction consistency comparison of summary, analysis, conclusion and limits against the verified claim record.

## 1.6.0 (2026-10-30)

- Claude Code `cite-check`, new **opt-in proposition-support pass** (`support:true`; off by default because it changes the cost profile from "sources with quotes" to "every source"). Every unquoted citation instance in the ledger becomes a support unit: the body sentence its footnote marker sits in (or the clause before a mid-sentence marker), the full footnote and its own prose, the Bluebook signal, the pincite (a bare `Id.` inherits its antecedent's page; a bare `Author, supra note N` does not), the proposition parenthetical and any separate-opinion note the draft gives. One agent per unique source reads the pincited page and judges the claim through its signal (a `but see` cite claims contrary authority, `cf.` analogy, `see generally` background); sources a verify agent already fetched get their support units folded into that agent. Verdicts: supported, supported with an undisclosed posture (advisory), **overstated (a confirm item by the author's decision, never an error)**, not supported (medium), contradicted (high), unverifiable, unread. Every not-supported or contradicted verdict goes through the same independent second derivation as a high-severity quote finding. Default scope is pincited or parenthetical cites; bare whole-work cites are listed as not read unless `supportScope:"all"`. New report section H (couldn't-check moves to I, the coverage ledger to J); new ledger dispositions `supported`, `support-confirm`, `support-finding`, `support-unverifiable`; support items join the re-run diff keyed by claim, source and verdict.
- Claude Code `cite-check`, extraction: every numbered footnote now carries its body **anchor** (the sentence containing the marker, the preceding sentence, the clause before a mid-sentence marker, and whether the marker ends a sentence or a block quotation); the ledger records each instance's introductory signal, pincite or locator, proposition parenthetical and separate-opinion note; the companion Citation Ledger gains a Signal column and, with `--extract`, the body sentence each note hangs on, so an existence-only row can be audited by eye without running the pass. New `scripts/prepare_support_units.py` (deterministic, zero model tokens) and `verify_quotes.py --page N` (print one printed page of a saved source by the same page-boundary detection the quote check uses).
- Tests: `test_prepare_support_units.py` (anchors, signals, pincite inheritance, scope, support dispositions), plus new checks in the extractor, verifier and diff tests; the offline suite grows to 27 test programs.
- Claude Code `cite-check`, fixes from the review of the Codex port (`reviews/2026-10-25-codex-cite-check-support-pass.md`): a court/date, access-date, editor or file parenthetical is no longer read as the proposition parenthetical; "at N" inside a title and a docket number before a court/date parenthetical are no longer pincites; a posture note is recognized only in its own shape ("Thomas, J., concurring", "opinion of Roberts, C.J."), so "(rejecting the dissenting view ...)" is a proposition; a signal after introductory prose or italicized in a markdown draft is read; a sentence break after a citation starts a new clause, so a second cite introduced by prose ("For the contrary view, see B") is its own instance; rules and unsectioned code cites carry a locator; a support verdict records the claim it judged, where the claim came from, and (for not-supported and contradicted) the terms searched; and a re-run without the support pass lists prior support findings as not rechecked instead of resolved. From the Codex review of the Claude side (`reviews/2026-10-25-claude-cite-check-support-pass.md`, with the response at its end): an adverse support verdict that the second checker did not re-derive is never a finding (section I, ledger `support-unverifiable`), and audit capacity is reserved before dedicated support agents spend; every agent result is validated before acceptance (in-scope id, matching source key, full-text basis, passage, locator, and the search behind an adverse verdict), with rejections counted and disclosed and a non-verbatim claim replaced by the unit's own anchor; a reviewer's downgrade to qualified support or overstatement stays reported in its own list and count, and a retraction is recorded as supported; the findings file carries what the pass actually read, so a re-run resolves a prior support finding only when it reread that unit. The workflow's accounting is now covered offline by `scripts/workflow_harness.mjs` and `test_workflow_support.py` (stubbed agents; skipped without `node`).
- Claude Code `cite-check`, from Codex's focused smoke test on a real draft (2026-10-26): a journal abbreviation with several periods ("Yale L.J.", "B.C. L. Rev.", "N.Y.U. L. Rev.") now classifies as an article instead of falling through to the book rule, which had taken the article's first page as a pincite; "see also generally" keeps the background meaning of "generally"; and the support rules tell the agent that a mid-sentence clause consisting only of an authority's name or a framing phrase attributes the whole sentence, that an unclear share of a joined sentence is unverifiable rather than a shortened claim, and that confirming a source's existence or title is not proposition support.
- Claude Code `cite-check`, more from the first live run of the support pass on this side (2026-10-26, footnotes 1–30 of a 293-note article, Zotero personal library, 34 agents; the same journal-abbreviation fix landed independently from both runs): an unabbreviated journal after a title comma (`61 Parliamentary Affairs 681 (2008)`) is an article and a bare article cite is the whole work, so no first page reaches the support pass as a pincite (43 of the draft's 264 support units had been classed as books, six of them "pincited" at their first page); the extractor's abbreviation guard protected substrings, so a sentence ending in "-ed." or "-ch." never split and the next sentence rode along in the anchor (15 anchors on the sample draft) — abbreviations are now protected only as whole tokens; a short comma-bearing clause with no digit and no citation token (footnote prose such as "Levinson treats 'exit' as a distinct third mechanism, separate from rights or votes.") is `text`, not an `other` citation to be existence-checked and reported unverifiable; and a partial pass (`unitIds`) is named as such in the report's title and TL;DR instead of "N footnotes swept". Regression checks in the ledger, extractor and support-unit tests. The run itself behaved: two adverse verdicts (a mismatched URL at n.19, a Federalist No. 37 cite that does not carry its sentence at n.25) were each re-derived with the search shown, zero checker artifacts, and every unreadable source listed with an unlock path.
- Claude Code `build-library`, `attach_pdf.py`: an explicit `--library` is applied before the resolver decides whether a configuration file is needed, so an API key plus a destination resolves without `ZOTERO_LIBRARY_ID` or a config file. This is the root cause of the attach_pdf readback failures that kept the offline suite red on `main` since 1.3.0 (traced by the Codex review); regression check added.
- Claude Code `cite-check`, **cost** (from the same live run, which spent 1,989,264 subagent tokens on 30 footnotes — about 58k per agent against the 9–10k per source the budget ladder assumed, so no gate ever closed and the run finished at twice the soft cap with "0 dropped for budget"; the report's own couldn't-check section showed the tokens going to agents trying repository URLs one at a time on sources that ended unverifiable). Three changes. (1) New shared toolbox script `legal-research/probe_sources.py`: an agent gathers every candidate URL for a source and tests them all in one deterministic call, which returns per URL whether it is fetchable, the HTTP status, the known behaviour of the host (HeinOnline, JSTOR, Westlaw and Lexis are subscription-only and are marked without a request; SSRN, Justia and bepress Digital Commons repositories return 403 to scripts; openYLS is a sign-in page) and a Wayback Machine snapshot for anything unreachable; the agent prompts now fetch only what the probe marks fetchable, count each probed failure as an attempt, and never retry a blocked host with URL variants. (2) The workflow measures itself: every agent runs through one counter, spend per phase is logged at each phase boundary and returned as `spend` (SKILL.md puts it in the report footer beside the completion notification's figure so the two can be reconciled), and the per-agent estimates behind every budget gate are floors that this run's measured mean replaces as soon as agents report. (3) The verify and support fan-outs launch in budget-sized waves instead of all at once (`gatedFanout`; `maxWave` arg, default 12), so a phase whose agents cost more than its gate assumed stops launching and discloses, by source, what it never fetched as NOT CHECKED (budget), with the `+Nk` budget that lifts the cap. SKILL.md gains a pre-launch cost estimate step (3c). Offline: `test_probe_sources.py` (host rules, status mapping, sign-in detection, Wayback parsing, the per-call cap) and a `budget-wave` scenario in the workflow harness test.
- `reviews/2026-10-27-claude-cite-check-cost-note-for-codex.md`: the cost findings and the review of the sample report, written up for the Codex side.
- Claude Code `cite-check` and `proofread`, **up-front dialog** (`claude-code/skills/DESIGN-upfront-dialog.md`, built 2026-10-27): the single `AskUserQuestion` that asked only Depth now carries the other opt-in choices a user would otherwise never discover. Cite-check asks Depth, proposition support (off / pincited cites / all cites, with the cost stated in the option text) and, when the project has no recorded library and there is a choice to make, which Zotero library — the registered libraries listed by their real names through new `legal-research/zotero_servers.py` (one API request per group, server name as fallback), a typed description resolved against group name, description and server name, and the answer written to the project's `CLAUDE.md` so it never recurs; with only a personal library registered the choice is made silently and said in one line. Proofread asks Depth and Style. A question the request settles is dropped from the call, not asked with a default; a `+Nk` budget does not settle Support; headless runs use the defaults and say so. Offline test `test_zotero_servers.py`.
- Claude Code `cite-check`, output names: the report, findings file and companion ledger are now `<draft> — Cite Check (Claude).md`, `<draft> — Cite Check (Claude) findings.json` and `<draft> — Citation Ledger (Claude).md`, because the Codex skill publishes its report as `<draft> — Cite Check.md` in the same folder and the two were overwriting each other. A re-run still reads an older findings file under the previous name once.
- Claude Code `cite-check`, **cost, corrected** (2026-10-27, from the agent transcripts of the same run; `reviews/2026-10-27-claude-eval-of-30438ba-budget-fix.md`). Output tokens were never the cost (278k for the run, in line with the gates) — the cost was 486 agent turns re-reading 50–60k of context each, and the turn-heavy agents were the ones searching Zotero by hand. New `scripts/zotero_lookup.py` (stdlib; reads the same `mcpServers` entries the Zotero MCP tools use): one deterministic pass before launch matches every article/book the draft cites to the user's Zotero libraries, compares record metadata to the cite as confirm notes, downloads each match's PDF and extracts its text to a file; the workflow (`zoteroHits`, `zoteroLookupPath` args) settles matched secondary sources without an agent and tells every verify and support agent, per source, that its text is on disk or that it is not in Zotero — no agent calls a Zotero tool any more. The budget gates now project cost per agent kind (`costModel` arg overrides) instead of reading output tokens, in input-equivalent tokens (uncached input + cache writes + cache reads ÷ 10 + output × 5), and new `scripts/run_usage.py` measures the same unit from the run's agent transcripts afterwards, per phase and per kind, for the report footer and for recalibrating the model; the completion notification's `subagent_tokens` turned out to be the sum of the agents' peak contexts, not a cost. Caps are 4M standard / 6M deep, +3M with support. A phase that would not fit degrades before launching. Batches shrink (secondary existence 5, verify tail 4, support tail 3) and every fetching agent carries a tool-call budget in its prompt. Offline: `test_zotero_lookup.py` (parsing, the real matching cases, credentials, a fake API end to end), `test_run_usage.py`, and new harness scenarios (ladder before launch; the Zotero join, including a record whose subtitle the draft omits). Live re-run on the same 30 footnotes with the support pass completing: 40 agents, 310 turns, 5.28M input-equivalent tokens measured against 5.08M projected, 18 of 21 quotes settled; the day before, 34 agents, 486 turns, 7.4M and 11 of 21.
- Claude Code `cite-check`, up-front dialog follow-ups (2026-10-30, from a dry run of the dialog against three registered libraries): a **Coverage** question (whole draft / footnotes 1–10 as a sample / specific footnotes typed in the Other box), the same choices as the Codex picker, dropped when the request names the range or when the tracked-changes question needs the fourth slot; `zotero_servers.py` and `zotero_lookup.py` read Zotero servers from all three Claude Code scopes (user, the project's `.mcp.json`, local) via `--project`, so a project-only library is offered and resolves; a Zotero server with no Web API key and library id (typically the desktop app's local API) is listed as NOT USABLE and the run says so in one line instead of silently going web-only; a short group-name token with a digit ("5A") now matches a typed description; the No Zotero option has description text. Regression checks in `test_zotero_servers.py` and `test_zotero_lookup.py`.

## 1.5.0 (2026-10-19)

Ideas taken from a second look at the DingDuff public skills (no code copied), adapted to law-review work on open sources.

- Claude Code `cite-check`, new **History** phase: every lower-court case cite gets a subsequent-history check — the RECAP docket's entries after the decision date with the dispositive ones flagged (notice of appeal, USCA judgment or opinion, mandate, cert. granted or denied, amended or substituted opinion, reconsideration, vacatur) plus later same-litigation opinions from the index — and every case gets a two-route adverse-treatment probe. A draft cite that omits an outcome Bluebook R. 10.7 requires is reported in a new advisory section G ("Subsequent history & treatment"); treatment flags are listed separately, since the draft may cite a case as history or as a foil. Couldn't-check moves to H and the coverage ledger to I. `history:false` skips the pass; under budget pressure it is skipped and disclosed.
- Claude Code `cite-check`, re-runs: the workflow returns a structured `findings` object; `scripts/findings_diff.py` compares it with the previous run's file (saved next to the report) and the report opens with what is new, still open, and resolved, keyed by content (quote, source, verdict, find-string, cite) so a renumbered draft does not reset the count.
- Claude Code `cite-check`, existence: a reporter cite that does not resolve is treated as a search problem, never as a fabrication signal — the agent runs the new `cl_case_tools.py find` (caption search, plus opinions whose text cites the citation string, which proves a cite real even when the opinion is not indexed) before any web escalation, and "unconfirmed" lists the routes tried. A real probe showed CourtListener returning 404 for the 2019 *Students for Fair Admissions* district-court cite while four later opinions cite it by number.
- Claude Code `cite-check`, verify: new `misattributed` verdict (medium) for words that are in the source but spoken by a party, a dissent, a lower court or another case where the draft attributes them to the court; the TL;DR must now state the existence-only share of citation instances in one sentence.
- Claude Code `legal-research` toolbox, `cl_case_tools.py citing`: citing opinions now come by two routes — the citation graph and a full-text search for the case name filed after the decision — deduplicated to distinct cases (the index is one row per opinion), with per-route counts in the output; the memo workflow's cite-check and refutation prompts read both routes and report distinct-case counts. New `history` and `find` subcommands as above; `--name` lets every subcommand resolve a case the cite will not. 34 offline checks in `test_cl_case_tools.py`.
- Claude Code `legal-research` memo: the Table of Authorities carries a **Validation** column per authority (3-voter refutation panel / checked by existence + treatment probe / not validated), with one sentence naming which authorities got the panel, because a screened case and a verified case look identical in prose; refutation voters run the history tool on load-bearing lower-court cases.
- Claude Code `cite-check`, `legal-research`, `find-cite`: a standing rule that opinions, articles and dockets postdating the model's training data are real, so an unfamiliar 2025–2026 decision is never treated as a hallucination signal.
- README: a paragraph for users whose organization manages Claude, with a ready-to-send administrator request to allow the marketplace.
- Codex plugin 1.4.0 (see `codex/CHANGELOG.md`): the same eight ideas implemented independently by Codex for the Codex skills — an advisory subsequent-history and treatment pass with a bounded RECAP helper, content-keyed re-run findings, two-route treatment triage, caption and citation-text identity fallbacks, the wrong-speaker misattribution rule, post-cutoff guidance, validation tiers in memo authority tables, and the existence-only count; reviewed by Claude, with one live-verified fix to the RECAP docket search (the court goes in a request parameter, not the query).
- Deferred: a proposition-support check for unquoted signal cites (it would mean reading every source; the existence-only disposition stays, now stated in the TL;DR), and an interactive side-by-side review page (a large build for little gain in a Word-and-Cmd+F workflow).

## 1.4.0 (2026-10-19)

- Claude Code `setup`: a new optional step offers automatic updates of the plugin. Claude Code updates a plugin on its own only when its marketplace has auto-update on, which is off for a third-party marketplace such as `danepps`; the setup helper's new `auto-update on|off|status` subcommand sets the documented `autoUpdate` field on the marketplace's `extraKnownMarketplaces` entry in `~/.claude/settings.json` (the same field the Enable auto-update choice under `/plugin` writes, and the one Claude Code consults first), reads the effective state back following the documented precedence, and reports the `DISABLE_UPDATES`, `DISABLE_AUTOUPDATER`, and `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` variables that switch the whole update pass off. The skill reports only what the helper read back, never the user's answer; skipping changes nothing; a marketplace already enabled through `/plugin` is recognized and never toggled off; a plugin that was not installed from the marketplace is reported as not updatable this way instead of failing setup. `status` now carries an `auto_update` block. Twenty-two regression checks cover these cases. No scheduler, startup hook, or self-modifying cache logic is added on the Claude Code side; this follows Codex's proposal of the same date except that the switch is written as a setting rather than left to the `/plugin` screen, because Claude Code's reference documents that field.

## 1.3.0 (2026-10-19)

A review release. Two independent reviews of the Claude Code skills (one by Codex, one by Claude with probe-verified fixtures) found defects that could produce false findings, silently incomplete runs, or wrong footnote numbers. Every item below was reproduced before it was fixed and carries a regression test; the offline suite grew from 14 to 26 test programs.

- Claude Code `cite-check`, extraction: a custom-marked author footnote (the starred note that opens many drafts) no longer shifts every footnote number by one; a footnote reference inside a tracked deletion is no longer numbered; moved text is no longer duplicated; manual line breaks and non-breaking hyphens no longer glue words together; block quotations (by paragraph style or indent) and single-curly-quote quotations are now extracted; a quotation's sentence now ends at its own footnote marker; a quote pairs with the marker after its own end within its sentence, with a paragraph-level fallback flagged as a guess for the resolver; endnotes, empty footnotes and unreferenced footnotes are warned about; common reporters that were silently skipped (S.E., S.W., state official reporters, Westlaw, nominative U.S. reporters) now reach the existence check; a footnote wrapped in a content control is no longer read as empty.
- Claude Code `cite-check`, verification: a quote with a leading or trailing ellipsis can now match; a closed-up em dash in the source matches a spaced dash in the draft; zero-width characters and decomposed accents no longer defeat matching; a meaningful hyphen (re-signed versus resigned) is no longer treated as typographic; a passage that appears on several pages is matched to the occurrence inside the cited pincite; Id. chains longer than three notes keep their antecedent; signal-prefixed Id. and Id. after an internal cross-reference resolve correctly; a supra whose named author is absent from the target note is reported as a probable renumbering break instead of marked resolved; stored excerpts are no longer truncated before agents see them.
- Claude Code `cite-check`, workflow: findings are labelled by footnote from a deterministic id-to-note map; a dead segment or verify agent is retried and whatever still fails is listed as not checked; high-severity findings that skipped the second check are labelled single-checker; agents pass quotes to the verifier through a JSON file, never as shell arguments; the default Zotero server is `zotero`; the pre-flight points at `/legal-research:setup`.
- Claude Code `legal-research` workflow: three dead refutation voters no longer produce a verified authority with a full-text basis; voters report their evidence basis and a short or empty panel is disclosed; per-chunk and per-voter source files replace shared `/tmp` names; the dormancy inference from citing-opinion dates is replaced by a plain statement of the date and the index's limits; `fetch_page.py` reports partial coverage and marks truncated output when a PDF exceeds the page cap instead of calling the text full.
- Claude Code `proofread` workflow: every dead worker is retried once and remaining gaps (chunks, consistency lanes, unvetted findings) are disclosed in the report and the exit state; the verifier can revise a finding's severity, category and find string, with a revised find string checked against the draft; deduplication no longer merges two distinct defects in one paragraph.
- Claude Code quotation hook: a subagent's summary, a workflow's returned result, a task notification, a peer message and the parent prompt inside a subagent transcript no longer count as sources; raw tool output inside subagent transcripts still does.
- Claude Code `setup`: credential files keep private permissions through the atomic rewrite; saving a CourtListener token now reports when an environment variable still overrides it, and where that variable likely lives.
- Claude Code `build-library`: the attachment helper resolves the library at run time, supports group libraries, and reads the attachment back before reporting success; collection checks follow pagination and reconcile the declared total; a requested key that does not come back is an error; the inventory's PDF flag means a real PDF attachment; author matching is whole-token; a catalog that could not be searched yields `UNAVAILABLE`, distinct from a completed search with no match.
- Codex plugin 1.1.0 (see `codex/CHANGELOG.md`): Codex's own review pass, with stricter evidence, coverage and completion validators, a paginated Zotero inventory, a bounded source fetcher, and an installer that fails instead of claiming success.
- Known open items on the Codex side, from Claude's review of the Codex cite-check skill (the review memos are kept outside the repository): custom-mark footnote numbering, deleted footnote references, a DOCX gate whose two method strings never match, an unguarded not-applicable status, body quotes attributed to the wrong footnote, block quotes, endnotes, and page-marker conventions.

## 1.2.1 (2026-10-19)

- Claude Code `cite-check`: a metadata correction (author name or order, volume, first page, year, title, edition) now has to be evidenced against the source's own record, opened during the run: the journal's page, the PDF's first page, a publisher or library catalog record, or a HeinOnline or SSRN citation page. Search snippets, URL slugs, casebooks, syllabi, and other articles' footnotes no longer count. The existence and verify agents tag each finding with the record they opened (an empty tag does not count), tentative notes an existence agent leaves on a source it could not pin down are carried into the report instead of dropped, and the report's section E splits into "Errors (fix)" for tagged findings and "Confirm" for everything else, which is phrased as something to check rather than something wrong. Author-order claims never reach "Errors (fix)" without a tag, since companion and multi-part articles rotate author order between parts. Prompted by a run that told the author to swap the authors of a Stanford Law Review article on the strength of an opencasebook.org URL slug; the journal's own page showed the draft was right.
- Codex `cite-check`: the verification protocol states the same evidence rule for `metadata_error` findings.

## 1.2.0 (2026-10-19)

- Claude Code: a seventh skill, `/legal-research:setup`, does the configuration in conversation so nobody has to edit a file. It checks Python, asks for the free CourtListener token and saves it to `~/.config/courtlistener/token` after testing it against a live lookup (the Codex scripts read the same file), pre-allows `WebFetch` and `WebSearch`, sets `enableWorkflows` (the Dynamic workflows switch a Pro plan needs), and can register a Zotero MCP server. Its script backs up every file it rewrites and never removes a setting it did not add.
- README: the Getting started section is now four steps done entirely inside the Claude desktop app or Claude Code, with the Terminal, installer-script, and Codex routes moved under "Other ways to install." The prerequisites table says where each credential goes in plain English. Prompted by a reader who found the old instructions assumed too much.

## 1.1.0 (2026-10-19)

- Claude Code: the plugin now carries a quotation check (`claude-code/hooks/`). While one of its skills is in use, every quotation of five or more words in the reply, or in a Markdown or text file written that turn, must match raw tool output from the session verbatim, including text fetched inside Agent and Workflow subagents; WebFetch and WebSearch summaries and the model's own written files do not count. An unmatched quotation blocks the reply until the model fetches the source, drops the quotation marks, or tags the line `[unverified]`. Inactive in sessions that do not use the plugin's skills; `LEGAL_RESEARCH_QUOTE_CHECK=off` disables it. See the README's "Quotation check (hook)" section.

## 1.0.1 (2026-10-18)

- Claude Code: the plugin is now named `legal-research`, the same name as the Codex plugin, so the install command is `/plugin install legal-research --marketplace danepps/legal-research-skills` and skills load as `/legal-research:<skill>`. Anyone who installed `law` earlier today should uninstall it (`/plugin uninstall law@danepps`) and install `legal-research`.

## 1.0.0 (2026-10-18)

First public release.

- Claude Code: `law` plugin (renamed `legal-research` in 1.0.1) with six skills (legal-research, cite-check, proofread, find-cite, build-library, case-prep), installable from the `danepps` marketplace in this repository.
- Codex: six skills (legal-research-memo, cite-check, internal-proofread, find-cite, build-zotero-library, deep-research), installed by the one-line installer.
