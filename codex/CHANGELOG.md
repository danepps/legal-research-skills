# Codex plugin changes

## 1.7.6 — 2026-11-25

- `internal-proofread`: replace the filename-based header/footer scan with section
  relationship resolution and inheritance. Ignore unused parts and generated furniture;
  deduplicate prose while preserving every section, type, part, paragraph and segment.
  Header/footer insertions are included; deletions and move sources are excluded.
- Separate primary and recall chunks preserve body boundaries. Prose and local citation
  mechanics run on author notes, without footnote terminal-punctuation or note-direction
  rules. Packets, challenger mapping, validation, merging, exact replacements and reports
  retain header/footer locations; first-page stories sort before the body, other running
  stories after notes. No header/footer prose adds no empty extraction field. Markdown
  output is unchanged. Each plugin bundles its own helper; neither imports the other.
- Tested offline using standard-library Python and synthetic documents: extraction and
  compatibility fixtures, all six types, duplicate parts, fields, tracked text, primary
  and recall/audit packet context, challenger mapping, location validation and exact
  replacement survival through merge/report. Repository validation uses
  `python3 run_tests.py`. No real draft, live model proofreading, Word opening/rendering,
  Word accept/reject UI, Zotero refresh, live host or fresh installation was tested.
  Codex still has no bundled redline writer; its optional exact corrections retain the
  source location for a downstream writer.
- Checked by hand after the tests (2026-11-25), on the snapshot of the live Dubitante run that exposed the gap: both extractors now return the first-page footer's author note, with the run-together word that was missed; in the Claude Code extractor the draft's 16 existing chunks are byte-for-byte unchanged and a 17th carries the header and footer text; the redline writer placed a correction for that word as a tracked insertion inside the footer part and anchored a comment-type finding at the start of the body, beginning with its location. Inspected as XML, not in Word. One nit left: a footer's rule line of underscores is extracted as text.

## 1.7.5 — 2026-11-23

- `cite-check`: deterministically compare a draft's printed case caption and year
  with the reporter lookup's resolved caption/date. Add explicit per-unit JSONL
  input and comparison output; retain existing found/not-found, fallback-search
  and rate-limit behavior. Shared state, D.C., Puerto Rico or Guam names and
  their Bluebook abbreviations cannot clear a mismatch between other parties.
  Compare complete sovereign names when no other distinctive words remain;
  other generic-only captions stay indeterminate. Absent captions/years do not
  become errors.
- Accept prefix agreement when the shorter word has at least four letters and
  single-letter insertion/deletion/substitution when both words have at least
  five. Retain the compared words and rule in the screen; misspelled party names
  alone are not wrong-identity findings.
- Preserve screens in source bundles and a per-unit ledger. New runs require
  screen coverage or disclosed unavailable screening. Readiness rejects an
  unresolved mismatch, edited comparison, missing finding, or unsupported
  clearance; findings and dismissals require opened evidence and report
  disclosure. Existing metadata-record and independent-audit gates still apply.
- Update the skill and protocols; retain compatibility for older runs, while
  checking any screen ledger they contain. Bump only the Codex plugin.
- Tested offline on `/usr/bin/python3` 3.9.6: all 19 cite-check test programs
  passed (182 unittest tests plus four standalone assertion programs), including
  26 new tests. No live cite-check, network calls, credential use, Claude-side
  test run, or private-skill installation was performed.

## 1.7.4 — 2026-11-23

- `internal-proofread`: optional exact corrections, for a host program or a
  requested marked draft that needs text a program can apply. `init_run.py
  --replacements` (off by default, recorded in the run manifest) lets a worker
  add `replacement` to a finding: the excerpt with only the correction made.
- The field is carried through merging, the rejection and verifier audits, and
  the final `dispositions.jsonl`. It is withdrawn when a later stage revises the
  suggestion, excerpt, location or severity without supplying a new one, when
  it equals the excerpt, and on rejected, waived, quoted, formatting and
  judgment findings. `validate_run.py` rejects a malformed or stale one.
- With the option off, packets and the worker schema are what they were:
  workers now read a schema copy generated into the run folder, which leaves
  the new section out, and a `replacement` supplied anyway is ignored and never
  written out. A regression test compares off-mode packets with the earlier
  text.
- Tested offline only (23 new tests, 37 in the skill). No live run, and nothing
  yet applies these corrections to a Word file for the Codex skill.

## 1.7.3 — 2026-11-14

- Reconcile citation and proofreading audits with the final finding. Retractions
  cannot leave live findings, and revisions must apply their recorded outcome.
  Reject duplicate, unknown, and stale proofreading audit rows.
- Prevent research memos from passing full readiness with unresolved issues or
  blockers, even when completion gates are marked passed. Add explicit blocker
  resolution and preserve delivery with disclosed limits.
- Add offline regressions for the inconsistent states and successful correction,
  retraction, recovery, and limited-delivery paths.

## 1.7.2 — 2026-11-14

- Treat a word split by a soft hyphen at a line end as one word in `cite-check`
  quotation matching. The whole-word quotation is now `normalized`; the split form
  no longer matches. Whitespace of any kind after the soft hyphen counts.
- Treat a bracketed star-page marker (`[*516]`, `[**12]`) as whitespace and as a
  page boundary, so a quotation may cross it and pincites are judged from it. A
  lone bare `*516` remains text.
- Reject a quotation that drops the first half of a word hyphenated across a line
  with a bracketed marker in the gap.

## 1.7.1 — 2026-11-14

- Require whole source tokens in `cite-check` quotation matching. A quotation that
  begins or ends inside a source word or number (“eligible” within “ineligible”;
  “$400,” within “$400,000”) is now `not_found` with a `partial_token_match` warning
  and field, in the plain, folded and dehyphenated views, occurrence counts, pincite
  selection and every ellipsis segment. An edge occupied by a bracket is exempt.
  A soft hyphen at a line end joins a word the same way a hyphen does.
- Accept, with a `match_abuts_digits` warning that requires judgment, a word followed
  directly by digits and a sentence-ending number followed by one to three digits;
  both are the shape of a flattened footnote call.
- Quotations that stop before a possessive or inside a hyphenated compound no longer
  match.

## 1.7.0 — 2026-11-12

- Recover unresolved quotations from reachable cached source texts before reporting
  access failures. New runs require a current recovery record and explicit review
  of remaining matches; matching words never clear attribution or pagination.
- Guard source grouping against unresolved Id./supra pooling, require evidence and
  disclosure for stale-note recovery, and preserve legacy-run compatibility.
- Clarify manuscript/chapter/version-aware Zotero matching and distinguish actual
  cache and library states in reports. Keep explicit skip and library selections.
- Run advisory history after requested core verification and required audits,
  using bounded screening, material-hit retrieval and measured pilot batches.

## 1.6.1 — 2026-11-03

- Strengthen memo counterarguments by identifying the attacked premise, supporting
  evidence, and conditions for success; carry accepted qualifications into the answer.
- Add record, context, and adverse-reading checks within the existing bounded
  refutation pass, with source-appropriate tools and an evidence-based disposition
  for every material objection. No additional agents or majority voting.
- Compare summaries, analysis, conclusions, and limits after substantive corrections;
  align them with verified claims and refresh affected claim anchors and audits.

## 1.6.0 — 2026-10-30

- Address Claude's dialog follow-ups: select Zotero libraries from public runtime
  metadata, preserve short digit-bearing descriptions such as `5A`, distinguish
  unavailable connections from absent/unassessed libraries, and carry the resolved
  choice through initialization, validation and source packets. Retain the
  size-based coverage/depth/support picker. Clarify that the Web API helper uses
  shell/Keychain credentials rather than parsing MCP config scopes, and that local
  PDFs are already supported without automatic folder matching. Remove the stale
  fixed support-cost multiplier from the Codex README.

## 1.5.0 — 2026-10-30

- Add a Codex cite-check picker for whole-draft or sample coverage, review depth,
  and separately opt-in proposition support. Preview actual draft counts before
  source work; use compatible reconciled inventories for cache/source counts,
  otherwise mark them unknown. Skip settled choices, bind resolved options to
  the draft snapshot, and preserve focused coverage when deep review is selected.

- Reduce cite-check context overhead: prepare bounded source packets with full
  relevant draft context and cache references, use fresh worker contexts, and
  share retrieval records across quote, support and audit work. Add a usage
  reporter for explicitly selected Codex sessions and time windows; subtract
  cumulative counters and keep cached input/reasoning as subsets. Replace the
  unsupported fixed support-cost multiplier with estimates of actual source work.

- Fix focused sample-run findings: preserve background meaning in `see also
  generally`, recognize dotted journal abbreviations without mistaking opening
  pages for pincites, and require reviewed claim scope for mid-sentence anchors.
  Authority-name prefixes can use the complete sentence after scope review;
  title confirmation alone cannot count as proposition support.

- Address Claude's fourteen review findings: close the support-only partial gate,
  preserve comparison clauses and signals, reject nonproposition parentheticals
  and false pins, locate rules, and retain prose after citations. Add standalone
  body-cite claim context and prefix-page reading. Keep orphan DOCX notes out of
  v6 coverage. Reconcile reruns per source/claim occurrence, recognize supported
  report heading forms, require item-specific unread reasons and complete claims,
  validate confirmed audit transitions, and count body siblings per paragraph.

- Add an opt-in proposition-support pass to cite-check, with schema-v7 support
  ledgers, deterministic footnote anchors and citation screening, inherited Id.
  pins, bounded cached-page reading, and exact reconciled coverage counts.
- Judge each unquoted citation through its signal and disclosed opinion posture.
  Overstatement is a low-severity confirm item, never an error. Independently
  re-derive every not-supported and contradicted finding before reporting.
- Keep default runs on schema v6, including deep runs. Whole-work reading requires
  explicit scope `all`; unread and unavailable instances remain disclosed.
- Key support rerun findings by category/source/claim/verdict, preserving absent
  findings as not rechecked when the pass is disabled or limited.
- Add offline extraction, screening, page-reader, support-ledger and gate tests.

## 1.4.0 — 2026-10-19

- Add cite-check subsequent-history and treatment advisories, a bounded RECAP
  history helper with empty-docket twin search, and schema-v6 case coverage.
  Skipped, unavailable and capped passes require explicit limits. Older run
  schemas retain their contracts.
- Save content-keyed findings and compare re-runs without depending on footnote
  numbering. Preserve repeated occurrences; incomplete/focused reviews cannot
  automatically resolve findings absent from their scope.
- Extend treatment triage to graph and caption-phrase routes, with per-route
  totals, bounded pagination, and decision deduplication including duplicate
  reporter versions. Never present sample-only graph gaps as missing edges.
- Add caption and citation-text identity fallbacks to both citation helpers;
  retain ambiguity and treat citing passages as corroboration, not proof.
- Extend the existing misattribution verdict to wrong-speaker attribution and
  require the actual speaker in new runs. Add post-training-cutoff guidance.
- Add reader-facing authority validation tiers to research memos and exact
  existence-only instance counts to cite-check summaries.
- Add offline helper and completion tests. No Claude-side changes, new hooks,
  schedulers or account configuration.

## 1.3.0 — 2026-10-19

- Add a setup skill for optional daily automatic updates through the native
  Codex plugin manager, using per-user launchd, systemd, or Task Scheduler jobs.
- Keep the updater outside the replaceable plugin cache; provide status,
  immediate checks, and disable commands with installed-version readback.
- Skip missing or disabled plugins, reject local/forked/pinned marketplace
  sources, bound failed checks, and prevent overlapping updater operations.
- Keep automatic updates off until the user opts in. Manual installs and
  Claude-owned implementation/configuration are unchanged.

## 1.2.0 — 2026-10-19

- Preserve custom-marked author notes without shifting printed footnote numbers;
  exclude deleted references and move origins, and disclose revisions in notes.
- Support body citation units with schema-v5 paragraph coverage. Block completion
  on unsupported endnotes, numbering restarts, and missing referenced note text.
- Improve quotation attribution, nested/styled block extraction, supra candidates,
  long Id. context packets, typography matching, and page-marker handling.
- Restrict not-applicable verdicts to documented internal pointers, require full
  text for substantive verification, and reject weak metadata-correction evidence.
- Retain complete match excerpts and bracket comparisons, support explicit
  paragraph/section pinpoint verification, and repair the optional DOCX gate.
- Document exact ledger fields and add offline extraction, matching, and
  completion regression tests. Claude-owned resources remain unchanged.

## 1.1.0 — 2026-10-19

- Strengthen evidence, coverage, source-identity, and completion checks across
  citation checking, citation finding, research, proofreading, and Zotero runs.
- Fix DOCX displayed-note mapping, meaningful quotation hyphens, repeated-passage
  pincite selection, and distinct proofreading occurrences in the same paragraph.
- Keep Markdown publication independent of optional DOCX generation.
- Add bounded source retrieval with provenance, explicit partial-text reporting,
  and unique outputs; add a paginated Zotero inventory before candidate discovery.
- Verify Zotero destinations, reused-item readbacks, requested-key coverage, and
  PDF structure before reporting success.
- Make failed Codex installer updates return failure instead of reporting that
  the current release was installed.
- Add offline regression coverage. No Claude implementation or configuration is
  changed by this release.

## 1.0.0 — 2026-10-18

- Package the six maintained Codex skills as a native marketplace plugin while
  preserving the manual installation paths.

