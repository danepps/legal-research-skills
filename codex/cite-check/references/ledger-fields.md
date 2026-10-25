# Ledger field reference

Read this when constructing or updating a run. JSONL files contain one object per
line. Field names below are literal. The initializer creates schema-v6 runs;
schema-v2/v3/v4/v5 runs remain readable with their existing coverage requirements.
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
`draft_find_string` on the verdict itself. `partial` and `unverified` (except a read v7 `support_overstated` confirm item) require an
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
its verdict. Verified nonquotation units with pins require that record, except v7 support
judgments, whose `support.locator_read` can disclose a nearby passage without
certifying the original pin:

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

## Schema-v6 case review, verification scope and findings

Each external citation verdict also requires boolean `identity_confirmed` and
`support_read`. The latter means the relevant source text was read to assess the
proposition; it does not imply the proposition passed. Metadata/snippets cannot
set it true. `verified_support` requires it true; every verified external verdict
requires confirmed identity. A `misattributed` verdict also names `actual_speaker`.

Count external citation instances (exclude internal `not_applicable` pointers),
not distinct authorities. Set manifest `counts.existence_only` to the count with
`identity_confirmed: true` and `support_read: false`. Include this exact sentence
with computed numbers in the report summary:

```text
Existence-only: X of Y citation instances were confirmed to exist but not read for proposition support.
```

`case-review.jsonl` has exactly one row per case `source_id`, with `history`,
`treatment`, and `findings` (an empty list if no advisory findings). Each check is
an object with `status: checked`, `partial`, `skipped`, `unavailable`, or
`not_applicable`. Only Supreme Court history may be not applicable, with
`court_id: scotus` and `court_identity_evidence` on the source's review row.
State-court history still needs official-record and later-opinion review; a
RECAP-only helper's not-applicable result cannot excuse the whole history pass.

A checked history check needs `routes` for `docket` and `later_opinions`; checked
treatment needs `graph` and `name`. Every checked route records `route`,
`status: checked`, `query` (or direct record action), `checked_at`, `evidence`
(locator and result) and `truncated` when applicable. The treatment route evidence
must cover both recent-citing and treatment-language searches. A failed route or
capped retrieval makes the overall check partial, with `reason` and `unlock_path`;
skipped/unavailable checks also require both. These states require
`complete_with_limits`, even if all ordinary citation verdicts are verified.

In the advisory section include the exact coverage line per case, substituting
its ID and actual statuses, plus every gap's reason and unlock path:

```text
Case review S1: history=partial; treatment=checked.
```

Each advisory finding records `unit_id`, `kind: history` or `treatment`, `verdict`
(e.g. `omitted_required_history`, `contradicted_history`, `treatment_flag`), `find`
(verbatim draft string), `label` (reader-facing action) and `evidence`. Required
history omissions also need `rule_basis` identifying the applicable Rule 10.7
requirement and exception analysis. High/critical adverse findings must also
appear in the ordinary verdict/audit ledgers. Keep treatment flags separate from
history corrections.

Generate `findings.json` using `scripts/findings_diff.py --run-dir RUN_DIR
--output RUN_DIR/findings.json` after finalizing the manifest and ledgers. The gate
reconciles it to those records. It preserves each occurrence while grouping
stable content keys for comparison. Keep previous findings in the hidden run as
`previous-findings.json`, with manifest `previous_findings_sha256`; insert the
helper's exact re-run block before **Needs your attention**. Completion with
limits or focused coverage cannot resolve an absent previous finding. Keep all
JSON artifacts hidden unless the user requests their publication.


## Opt-in support pass (schema v7)

`init_run.py --support [--support-scope pincited|all]` writes schema 7 and
`support_pass: {"enabled": true, "scope": "pincited"}` (or `all`). Without the
flag, the manifest remains schema 6 with `support_pass: {"enabled": false}`;
all old completion contracts are preserved. The extra workflow is opt-in, never
implied by `deep`.

Extraction adds an `anchor` to every footnote, including custom-marked notes:
`paragraph_number` (one-based), `sentence`, `previous`, `position`
(`sentence-end` or `mid-sentence`), `clause` (empty except mid-sentence),
`paragraph_end`, `block_quote`. Missing anchors are null with a warning.
`citation-screening.jsonl` contains deterministic clause/signal/locator hints;
it is not a final segmentation ledger. Confirm `signal`, `pincite`,
`parenthetical`, and `opinion_note` as strings on every external citation unit.
Retain the exact extracted wording of parentheticals and notes. Split and assign
nested quoting citations separately with `nested: true`. Mark internal/prose
units with `unit_kind: internal_reference` / `prose`. For resolved Id./supra
units set `xref_status: resolved`; unresolved ones use `unresolved`. On each Id.
record the immediately preceding citation's `antecedent_unit_id`, not the final
source in a flattened chain. Preserve `prepared_unit_ids` for linked quotations
before quote checks exist; the eventual quote-check links also exclude those
units from support review. The lead confirms all short-form resolutions.

After segmentation and quote linking, run:

```bash
python3 <skill-dir>/scripts/prepare_support_units.py RUN_DIR
```

This writes one `support-units.jsonl` row per eligible unquoted external instance,
including whole works. Quoted/nested/internal/prose and unresolved cross-references
are excluded. Every row carries `support_unit_id`, `unit_id`, `source_id`,
location fields, `signal`, `draft_citation_text`, `resolved_source_label`,
`pincite`, `pincite_basis`, `parenthetical`, `opinion_note`, `scope`, `anchor`,
`full_footnote`, `note_prose` (ordered prose clauses), and `siblings`.

An own pin wins. Bare Id. inherits through its antecedent chain; bare supra and
full citations never inherit. A pin, proposition parenthetical, statute section,
or URL is `pincited`; otherwise it is `whole-work`. Default-scope whole works
remain in the ledger with `unread_reason: out_of_scope`. In-scope unread rows
must say `budget` or `agent_failure`, with `support_read: false` and no `support`
object on the verdict. They require `complete_with_limits` and report disclosure.

Read units retain one final verdict per citation unit, `support_read: true`, and
a full-text verification basis on both source and verdict. Add:

```json
{"support": {
  "verdict": "overstated", "signal": "see",
  "claim": "Courts have uniformly held that the clause reaches this far.",
  "claim_basis": "anchor.sentence",
  "locator_read": "p. 437 (cited 436)", "posture": "holding",
  "source_passage": "The rule applies on these facts.",
  "reason": "Confirm whether this fact-bound holding supports the broader claim."
}}
```

`claim_basis` is exactly one of `anchor.sentence`, `anchor.clause`,
`parenthetical`, `note_prose`; claim must be verbatim in that field. The source
passage is at most 400 characters. Dispositions, adverse-search evidence and
six-class independent audit records are specified in the verification protocol.
Unverifiable attempts use `support.verdict: unverifiable`, `status: unverified`,
`support_read: false`, and `unlock_path`; passage/locator are not required because
nothing was read. Do not mark unavailable evidence as full-text reading.

After final verdicts and audits, run preparation again with `--refresh-counts`.
It preserves budget/failure decisions, rebuilds immutable context and writes
`counts.support`: `units_total`, `in_scope`, `out_of_scope`, `read`, `supported`,
`qualified`, `overstated`, `not_supported`, `contradicted`, `unverifiable`,
`unread_budget`, `unread_failure`, `audits_retracted`. It prints the exact sentence
required immediately after the existing existence-only sentence:

```text
Support pass: X of Y in-scope unquoted instances were read; A supported, B qualified, C to confirm (possible overstatement), D not supported, E contradicted, F unverifiable; G whole-work cites were not read (out of scope).
```

The gate reconstructs expected support units and reconciles counts; omitting a
unit cannot improve coverage. Existence-only retains its v6 identity-confirmed,
not-read meaning. `support_overstated` is low/partial, never a medium-or-higher
error or a Needs your attention item. Its partial status alone is not an unchecked
source. Support diff keys use category, resolved source label, claim and verdict,
never footnote numbers. Disabled or limited reruns cannot resolve absent support
findings; retain them as not rechecked.
