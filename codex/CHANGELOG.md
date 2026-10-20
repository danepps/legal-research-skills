# Codex plugin changes

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
