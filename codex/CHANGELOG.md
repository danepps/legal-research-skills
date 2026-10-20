# Codex plugin changes

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
