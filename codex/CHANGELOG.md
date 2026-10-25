# Codex plugin changes

## 1.5.0 — 2026-10-25

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

