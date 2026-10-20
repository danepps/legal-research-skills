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

Search the connected project library before the web, including group libraries when the project uses one. Verify that an attached file actually matches its metadata. Then use journal, repository, SSRN, author, institutional, publisher, Google Books, or Internet Archive copies. Compare the cited and current versions of manuscripts. Metadata-only or snippet-only access cannot verify a quotation or pincite.

### Internet sources

Confirm the URL resolves and the page supports the proposition. Record access date. For dead or changed pages, inspect an archived copy and suggest the stable archived URL.

## 2. Draft-grounded resolution

Keep four layers distinct:

1. `draft_citation_text`: verbatim text copied from the draft;
2. `resolved_source_label`: normalized identity inferred from cross-references or retrieved metadata;
3. `source_evidence`: what the retrieved source actually says;
4. `verdict`: the comparison and recommended action.

Walk `Id.`/`ibid.` backward through `supra` redirects until reaching a full source. For `supra note N`, inspect note N and confirm it contains the claimed source. Do not assume the nearest full citation is the antecedent. Preserve uncertainty.

Attach a quotation to the citation syntax and placement make responsible. Preserve the full body sentence, full footnote, marked quote, resolved pin, and nearby framing verb. Before concluding that a quote is absent, search every source named in the same footnote. If the quote appears in a sibling source, classify `misattributed` and recommend moving the parenthetical or citation.

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

Use one unit status: `verified`, `partial`, `mismatch`, `unverified`, or `not_applicable`.

A `metadata_error` finding that tells the author to change an author name or order, volume, first page, year, title, or edition must rest on the source's own record, actually opened during the run: the journal's article or issue page, the PDF's first page, a publisher or library catalog record, or a HeinOnline or SSRN citation page. Name that record in the finding. Search-result titles, snippets, and URL slugs do not count, and neither do casebooks, syllabi, reading lists, CVs, or other articles' footnotes, which copy each other's mistakes. If the only evidence is a snippet or a third-party listing, report the discrepancy as something to confirm, not as an error. Companion and multi-part articles routinely rotate author order and sit in different volumes, so match the exact part the draft cites before reporting an author-order or volume discrepancy; author order is never an error without the source's own title page or landing page.

Use specific categories, including:

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

For extracted PDF text, a header/star marker normally governs text after it; a footer number governs text above it. Do not infer a hard correction until the convention is identified. Any exact-one-page correction requires visual or otherwise authoritative confirmation plus an independent audit. If that cannot be obtained, use `pincite_unverifiable` or explicitly request manual confirmation.

For working papers, forthcoming articles, slip opinions, and other mutable sources, record cited-copy and current-version dates. If language exists only in the cited copy, classify `superseded_source`; it is not a misquote. If a slip opinion has official pagination, recommend conversion.

## 5. Run artifacts

- `run-manifest.json`: schema, draft path/hash, scope, timing, status, counts, and publication policy.
- `extraction.json`: paragraphs, footnotes, quotes, contexts, candidate cross-references, and tracked-change inventory.
- `prepared-units.jsonl`: deterministic quote/context packets with antecedent and `supra` targets.
- `citation-units.jsonl`: one citation instance per row. Required core fields: `unit_id`, `footnote_number`, `source_id`, `source_type`, `draft_citation_text`, `resolved_source_label`, `draft_find_string`, `caption_in_draft`, and `full_footnote`.
- `source-ledger.jsonl`: one source per row with canonical citation, type, identifiers, status, verification basis, versions, and retrieval notes.
- `quote-checks.jsonl`: one or more deterministic source-file checks per prepared quotation, linked to its citation unit and source, with source path/hash, match status, page basis, and review flags.
- `verdicts.jsonl`: one row per unit with status, severity, category, basis, evidence, suggested action, and adverse-finding draft string.
- `verifier-audit.jsonl`: independent audit rows with status, evidence, notes, and auditor identity/session when available.
- `report.md`: canonical report; `report.docx` is an optional synchronized derivative.
- `docx-verification.json`: for a requested DOCX, Markdown and DOCX hashes, OOXML-part and XML-parse results, extracted-text counts, explicit no-office-app status, and the visual-layout limitation.

Use stable IDs. Keep evidence structured as strings or arrays. Never omit evidence from an adverse verdict.

## 6. Report and completion rules

Order the report: title and provenance; scope/method; counts; **Needs your attention**; other confirmed corrections; full footnote ledger; **Couldn’t check**; method limits.

“Needs your attention” contains findings only. Do not include checked-and-cleared issues, plausible alternatives reasoned away, or requests to add a case name when it already appears in the body.

A ready schema-v3 run requires every prepared quotation to have a linked quote-check record; every verified quotation to have a deterministic `verbatim`, `normalized`, or reviewed `altered` match; every unit to have a verdict; every source to disclose basis; every source/unit reference to resolve; every adverse draft find string to occur in the extraction; every critical/high adverse verdict, `not_found_in_sources_checked`, and exact-one-page correction to have an audit; no stale draft or cached-source hash; and complete provenance. When a DOCX is requested, it must be synchronized with the Markdown and have a passed structural `docx-verification.json` record that states visual layout was not rendered and no office application was launched. Keep status `ready_for_validation` until the validator atomically marks it complete. `complete_with_limits` is allowed only when all unavailable items and unlock paths are listed. Schema-v2 runs remain valid under their original rules.
