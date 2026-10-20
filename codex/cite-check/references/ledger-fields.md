# Ledger field reference

Read this when constructing or updating a run. JSONL files contain one object per
line. Field names below are literal. The initializer creates schema-v5 runs;
schema-v2/v3/v4 runs remain readable with their existing coverage requirements.
Completion checks inspect declared evidence and consistency; they cannot establish
that an agent actually opened or correctly interpreted a source.

## Citation units and coverage

Every `citation-units.jsonl` row requires `unit_id`, `source_id`, `source_type`,
`draft_citation_text`, `resolved_source_label`, `draft_find_string`, and
`caption_in_draft` (`footnote`, `body`, or `none`). Preserve a cited pin in `pincite`.

- Numbered footnote: `footnote_number` is the extracted integer and
  `full_footnote` equals its entire extracted text. `location` may be `footnote`
  or omitted. Preserve `note_id` when available.
- Custom-marked footnote: `footnote_number: null`, the extracted `note_id`, and
  its complete `full_footnote`. Use extraction's `custom_mark` in the report.
  Body markers use the stable ID (for example `[[FN:fn:1]]`), not an invented
  printed number.
- Body citation: `location: body`, a one-based `paragraph_number`, and
  `body_context` equal to the complete extracted paragraph. Omit `note_id` and
  `footnote_number` or set both to null. `draft_citation_text` must occur within
  that paragraph. A quotation in the body supported by a footnote can still map
  to the footnote citation unit.

For a block quotation in paragraph 2 with its citation in paragraph 3, retain
`paragraph_number: 2` on the prepared quotation and `paragraph_number: 3` on the
body citation unit. Link them through the quote-check row's `prepared_unit_id`
and `unit_id`; do not copy the quotation into the citation paragraph's context.

Each `footnote-coverage.jsonl` row identifies its extracted `footnote_number` and,
for a custom mark, `note_id`. Each `body-coverage.jsonl` row identifies its
`paragraph_number`. Both require `unit_ids` and `status: reviewed`; use
`status: no_citations`, `unit_ids: []`, and a nonempty `reason` only after inspection.
Body unit IDs refer to `location: body` units. Footnote-backed quotations remain
in the footnote inventory. Focused numbered-note scopes omit body coverage.

For an indented paragraph listed in `extraction.block_quote_candidates`, also
record `block_quote_review: quotation` or `not_quotation` and `block_quote_reason`.
A confirmed block needs a prepared quotation with its `paragraph_number` and
`block_quote: true`. Styled DOCX quotations and Markdown `>` blocks are prepared
automatically. Add overlooked quotations manually, retaining their full text and
location; update manifest `counts.prepared_units` accordingly.

Prepared rows use `prepared_unit_id`, `location`, `quote`, `footnote_number`,
`note_id`, `paragraph_number`, `full_footnote`, and `body_context` as applicable.
Resolve source identity yourself from the complete draft. If a prepared row has
`primary_inferred_from_paragraph: true`, the final citation unit must have
`attribution_reviewed: true` before it can be verified.

## Sources and verdicts

`source-ledger.jsonl` requires `source_id`, `source_type`, `canonical_citation`,
`status`, and `verification_basis`. Source statuses are `retrieved`,
`metadata_only`, `snippet_only`, `unavailable`, or `not_applicable`.
Record actual retrieval scope. An unavailable source requires `reason` or
`retrieval_notes`, plus a concrete `unlock_path`.

`verdicts.jsonl` requires `verdict_id`, `unit_id`, `status`, `severity`, `category`,
`verification_basis`, `evidence`, and `suggested_action` (use `none` if appropriate).
Use the protocol's status, severity, and basis values. Positive categories are
`verified_quote`, `verified_support`, `verified_identity`, and `verified_pincite`;
legacy category labels remain readable. Identity can be verified from an adequate
metadata record. Quotations, support, and pincites require a retrieved full-text
basis in both the source and verdict rows. A snippet cannot fully verify a unit.
Secondary reproductions cannot establish a metadata correction.

Statuses `mismatch`, `partial`, and `unverified` require a verbatim
`draft_find_string` on the verdict itself. `partial` and `unverified` require an
`unlock_path`. Unavailable evidence, including an unavailable assigned-source
quote check, requires `complete_with_limits`; list affected source/unit IDs and
their exact unlock paths under **Couldn't check**. An unavailable sibling-source
check does not invalidate an otherwise verified assigned-source quotation.

`not_applicable` is restricted to a standalone internal pointer such as
`See infra Part II.` It requires `unit_kind: internal_reference`, a verdict
`reason`, a source row with `status: not_applicable`, and an `internal_target`
object containing a target `paragraph_number` and its exact extracted `text`.
It cannot have linked quote checks. Use `metadata_only` as the basis for this
internal structural inspection. A body pointer cannot target its own paragraph.
Supra citations to external authorities, retrieval failures, and suspected
misquotations do not qualify.

For `metadata_error` corrections, follow the protocol's `metadata_record` rules.
Supply the record's direct location, not a search-results page.

## Quotations, pins, and audits

Generate `quote-checks.jsonl` with `verify_quotes.py`. Its required link fields
are `quote_check_id`, `prepared_unit_id`, `unit_id`, `source_id`, and the unchanged
prepared `quote`. Match statuses are `verbatim`, `normalized`, `altered`,
`not_found`, and `unavailable`. Retrieved checks retain `source_path` and
`source_sha256`. Unavailable checks instead need `reason` and `unlock_path`.
Every prepared quote maps to exactly one citation unit; sibling-source checks
may share that unit but do not verify its assigned source.

An `altered` match needs explicit `alteration_reviewed: true` after reviewing the
full excerpt, bracket substitutions, ellipsis gaps, and framing. No truncated
excerpt or fuzzy hint should replace the full source passage.

A verified quoted unit with a `pincite` needs a matching quote-check row with
that exact pin and `pincite_ok: true`, or a direct `pincite_verification` record on
its verdict. Verified nonquotation units with pins require that record:

```json
{
  "pincite_verification": {
    "pincite": "¶ 12",
    "confirmed": true,
    "pagination_convention": "paragraph_number",
    "evidence_location": "cached-sources/S1.txt, paragraph 12",
    "evidence": "The actual passage inspected at that locator."
  }
}
```

Use an identified convention from the protocol, excluding `unknown` and
`unpaginated`. This is a recorded direct inspection, not a workaround for an
unrecoverable pin. Keep those verdicts `partial` with an unlock path. Page
corrections still need integer `page_delta` and the prescribed audit.

`verifier-audit.jsonl` requires `verdict_id`, `audit_status` (`confirmed`, `revised`,
or `retracted`), and `evidence`. Add auditor identity/session and notes when
available. Use `audit_status`, not `status`.

Before validation, set manifest `status: ready_for_validation`,
`completion_target: complete` or `complete_with_limits`, and counts for
`prepared_units`, `quote_checks`, `verified`, `partial`, `mismatch`, and `unverified`.
Only the validator's `--mark-complete` flag changes the final status.
