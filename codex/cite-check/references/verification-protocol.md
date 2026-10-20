# Verification protocol

## Contents

1. Source hierarchy and source-specific checks
2. Draft-grounded resolution
3. Verification basis and verdict taxonomy
4. Pincite and source-version controls
5. Run artifacts
6. Report and completion rules

## 1. Source hierarchy and source-specific checks

Prefer: user-supplied local source; official or primary source; authoritative reproduction with stable pagination; repository or author copy; connected library full text; reliable metadata or snippet; disclosed secondary reproduction. Never upgrade metadata or snippets to full-text verification.

### Cases

Treat citation lookup as identity screening. Retrieve the opinion for quotations, holdings, propositions, and pincites. Check caption only against a caption actually printed in the footnote or body; nameless reporter citations can be correct. For Supreme Court cases prefer official slip opinions or bound volumes. A first-page U.S. Reports pin may point to a syllabus; distinguish syllabus from opinion language. Describe negative-treatment review as approximate, not Shepard’s or KeyCite.

### Statutes, rules, and regulations

Use the official code, legislature, agency, rule publisher, or court. Verify section identity, version/effective date, quoted operative text, and the relevant historical version.

### Scholarship and books

Search the connected project library before the web, including group libraries when the project uses one. If none is connected, disclose that once and continue to authoritative web sources. Verify that an attached file actually matches its metadata. Then use journal, repository, SSRN, author, institutional, publisher, Google Books, or Internet Archive copies. Compare the cited and current versions of manuscripts. Metadata-only or snippet-only access cannot verify a quotation or pincite.

### Internet sources

Confirm the URL resolves and the page supports the proposition. Record access date. For dead or changed pages, inspect an archived copy and suggest the stable archived URL.

## 2. Draft-grounded resolution

Keep four layers distinct:

1. `draft_citation_text`: verbatim text copied from the draft;
2. `resolved_source_label`: normalized identity inferred from cross-references or retrieved metadata;
3. `source_evidence`: what the retrieved source actually says;
4. `verdict`: the comparison and recommended action.

Walk `Id.`/`ibid.` backward through `supra` redirects until reaching a full source. For `supra note N`, inspect note N and confirm it contains the claimed source. Do not assume the nearest full citation is the antecedent. Preserve uncertainty.

Attach each quotation or proposition to the citation that the footnote's syntax and placement make responsible for it. Preserve the full body sentence, full footnote, marked quote, resolved pin, and nearby framing verb. Before concluding that a quote is absent, search every source named in the same footnote. If the quote appears in a sibling source, classify `misattributed` and recommend moving the parenthetical or citation.

Every adverse verdict must have a short verbatim `draft_find_string` that occurs in the extracted draft. A proposed finding that cannot be found in the draft is an artifact and must be retracted.

For every prepared quotation, preserve the link from `prepared_unit_id` to one citation `unit_id`. Run the deterministic quotation matcher against the retrieved source-text file and retain the source hash. The matcher establishes only whether text appears in that file. A typographically normalized match remains textually identical; a bracket/ellipsis-assisted match requires separate alteration and framing review; a miss is not proof that the draft fabricated language. Multiple source checks may attach to one prepared unit when sibling attribution or source-version drift is at issue.

## 3. Verification basis and verdict taxonomy

Use one verification basis:

- `primary_full_text`
- `authoritative_reproduction`
- `repository_full_text`
- `local_library_full_text`
- `metadata_only`
- `snippet_only`
- `secondary_reproduction`
- `unavailable`

Use one unit status: `verified`, `partial`, `mismatch`, `unverified`, or `not_applicable`. Reserve `not_applicable` for a standalone internal structural pointer with no quotation, an inspected target paragraph, and a concrete reason; it never excuses failed source retrieval. See the [ledger field reference](ledger-fields.md) for its exact fields. Verified substantive support, quotations, and pincites require retrieved full text; adequate metadata can verify identity alone.

A `metadata_error` finding that tells the author to change an author name or order, volume, first page, year, title, or edition must rest on the source's own record, actually opened during the run: the journal's article or issue page, the PDF's first page, a publisher or library catalog record, or a HeinOnline or SSRN citation page. Name that record in the finding. Search-result titles, snippets, and URL slugs do not count, and neither do casebooks, syllabi, reading lists, CVs, or other articles' footnotes, which copy each other's mistakes. If the only evidence is a snippet or a third-party listing, report the discrepancy as something to confirm, not as an error. Companion and multi-part articles routinely rotate author order and sit in different volumes, so match the exact part the draft cites before reporting an author-order or volume discrepancy; author order is never an error without the source's own title page or landing page.

For a `metadata_error` with status `mismatch`, record a `metadata_record` object with `opened: true`, `exact_work_checked: true`, a direct URL or local page locator in `location`, and a nonempty `fields` array naming what is corrected (use `author_order` for that field). Its `record_type` must be `journal_article_page`, `journal_issue_page`, `pdf_first_page`, `publisher_record`, `library_catalog_record`, `heinonline_record`, `ssrn_record`, or `official_case_record`. Author-order corrections require a title/landing-page type: `journal_article_page`, `pdf_first_page`, `publisher_record`, or `ssrn_record`. The validator checks this declared provenance; it cannot substitute for opening and reading the record. A weaker metadata discrepancy remains `partial` with an unlock path and a request to confirm.

Use specific categories, including:

- `verified_quote`
- `verified_support`
- `verified_identity`
- `verified_pincite`
- `identity_error`
- `metadata_error`
- `quote_mismatch`
- `fragment_framing_review`
- `support_mismatch`
- `misattributed`
- `pincite_error`
- `pincite_unverifiable`
- `broken_cross_reference`
- `syllabus_quote`
- `superseded_source`
- `dead_url`
- `content_drift`
- `too_recent_for_free_index`
- `not_found_in_sources_checked`

Do not use `fabricated`. Severity is `critical`, `high`, `medium`, `low`, or `info`. Reserve critical/high for meaning changes, wrong-source attribution, nonexistent authority after adequate searching, or loss of central support.

## 4. Pincite and source-version controls

Record `pagination_convention` as one of `printed_page`, `star_or_header_precedes`, `footer_follows`, `paragraph_number`, `section_number`, `unpaginated`, or `unknown`.

The matcher reads `<<pg. N>>` as a marker before its page; use `--marker-follows` for numbered footer markers and calibrate one page against authoritative pagination. Form-feed `--first-page` applies to the first physical text segment, including covers. Paragraph and section locators require direct `pincite_verification`, not page-number matching. For extracted PDF text, a header/star marker normally governs text after it; a footer number governs text above it. Do not infer a hard correction until the convention is identified. Any exact-one-page correction requires visual or otherwise authoritative confirmation plus an independent audit. If that cannot be obtained, use `pincite_unverifiable` or explicitly request manual confirmation.

For working papers, forthcoming articles, slip opinions, and other mutable sources, record cited-copy and current-version dates. If language exists only in the cited copy, classify `superseded_source`; it is not a misquote. If a slip opinion has official pagination, recommend conversion.

## 5. Run artifacts

Read the [ledger field reference](ledger-fields.md) before writing rows; it lists exact required keys, source statuses, body/custom-note identities, positive categories, and pin/audit records.

- `run-manifest.json`: schema, draft path/hash, scope, timing, status, counts, and publication policy.
- `extraction.json`: paragraphs, footnotes, quotes, contexts, candidate cross-references, and tracked-change inventory.
- `prepared-units.jsonl`: deterministic quote/context packets with antecedent and `supra` targets.
- `footnote-coverage.jsonl` (schema v4/v5): one row per in-scope extracted footnote, with `footnote_number`, `status`, and `unit_ids`. Replace the initial `pending` status with `reviewed` and every citation unit ID for that note, or with `no_citations`, an empty list, and a concrete `reason`. The lead must inspect each footnote; reconciliation prevents silent omission of whole notes but does not prove that every citation within a note was segmented.
- `body-coverage.jsonl` (schema v5): one inspected paragraph per row outside focused numbered-footnote scopes, with `paragraph_number`, `status`, `unit_ids`, and a reason for `no_citations`; review indented block candidates explicitly.
- `citation-units.jsonl`: one citation instance per row with stable source/unit IDs and verbatim draft text. Use numbered/custom-footnote or body-paragraph location fields as specified in the ledger reference.
- `source-ledger.jsonl`: one source per row with canonical citation, type, identifiers, status, verification basis, versions, and retrieval notes.
- `quote-checks.jsonl`: one or more deterministic source-file checks per prepared quotation, linked to its citation unit and source, with source path/hash, match status, page basis, and review flags.
- `verdicts.jsonl`: one row per unit with status, severity, category, basis, evidence, suggested action, and adverse-finding draft string.
- `verifier-audit.jsonl`: independent audit rows with `verdict_id`, `audit_status`, evidence, notes, and auditor identity/session when available.
- `report.md`: canonical report; `report.docx` is an optional synchronized derivative.
- `docx-verification.json`: for a requested DOCX, Markdown and DOCX hashes, OOXML-part and XML-parse results, extracted-text counts, explicit no-office-app status, and the visual-layout limitation.

Use stable IDs and exactly one final verdict per citation unit. Keep evidence structured as strings or arrays. Never omit evidence from an adverse verdict. `partial` and `unverified` verdicts require `unlock_path`; unavailable source rows require `reason` or `retrieval_notes` plus `unlock_path`. List their unit/source IDs and exact unlock paths in the report's **Couldn't check** section. These items require `complete_with_limits`. Record page-correction `page_delta` as an integer (numeric strings are accepted for compatibility); an exact-one-page delta or an unspecified page delta requires an audit.

## 6. Report and completion rules

Order the report: title and provenance; scope/method; counts; **Needs your attention**; other confirmed corrections; full footnote ledger; **Couldn’t check**; method limits.

“Needs your attention” contains findings only. Do not include checked-and-cleared issues, plausible alternatives reasoned away, or requests to add a case name when it already appears in the body.

A ready schema-v3/v4/v5 run requires every prepared quotation to have a linked quote-check record; every verified quotation to have a deterministic `verbatim`, `normalized`, or reviewed `altered` match in the unit's assigned source; every unit to have exactly one verdict with a valid status and severity; every source to disclose basis; every source/unit reference to resolve; every adverse draft find string to occur in the extraction; every critical/high adverse verdict, `not_found_in_sources_checked`, and exact-one-page or unspecified-page-delta correction to have an audit; no stale draft or cached-source hash; and complete provenance. Schemas v4/v5 also require footnote coverage reconciliation and verbatim full-footnote linkage to extraction. A requested DOCX needs a synchronized, passed structural `docx-verification.json` record that states visual layout was not rendered and no office application was launched; check that derivative separately with `--require-ready --require-docx` after the Markdown gate. Missing or failed DOCX output never blocks audited Markdown, including for legacy `matched_pair` or `docx_only` manifests. Keep status `ready_for_validation` until the validator atomically marks it complete. `complete_with_limits` is required when any items are partially checked or unavailable, and their IDs and unlock paths must be listed. Schema v5 additionally requires body coverage and review of indented block candidates; custom marks retain stable note IDs, and extraction blockers prevent publication. Schema-v2/v3 runs remain readable without the footnote coverage file; they receive the stricter verdict, audit, and limitation checks but cannot claim schema-v4 coverage. Schema-v4 runs remain readable without body coverage. To obtain current coverage, initialize a schema-v5 run from the draft and review both coverage ledgers against its frozen extraction.
