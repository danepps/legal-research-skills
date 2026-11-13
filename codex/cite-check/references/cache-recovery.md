# Resolve and recover before reporting access failures

Use this protocol during source resolution and again before the final report.
The scripts search supplied run files only; they do not query Zotero, download
sources, change verdicts, or establish attribution or printed pagination.

## Resolve before grouping

Keep draft wording intact. A resolved source label and canonical citation must
identify the full work, never a bare Id. or supra short form. Give an unresolved
reference its own source ID per citation unit; never pool unresolved Id. units.
Record `xref_status: unresolved` and an unverified verdict with an unlock path.

For resolved Id./ibid. and supra citations, record `xref_status: resolved` and
`antecedent_unit_id`. Id. points to its immediate antecedent; supra points to the
specific citation unit in the referenced note. The chain must terminate at an
identified source and retain the same source ID. Focused runs may use a minimal
`resolution-context.jsonl` containing out-of-scope antecedent units (same fields);
these are context only, never additional checked coverage or verdicts.

When a supra note number is stale, search earlier full citations using the named
author and title. Treat that as candidate discovery, not automatic resolution:
two works by the same author remain ambiguous. Inspect the full citation, title,
version, footnote context and source identity. A confirmed recovery records
`xref_status: recovered` and `xref_recovery` with `candidate_unit_id`, boolean
`identity_confirmed: true`, and `evidence` explaining the identification and the
stale target. Keep the original citation and report the broken reference even
if the quotation is accurate. The recovery helper produces its coverage line.

Reconcile every assigned unit ID against every returned worker ID. Retry a
missing result once in a smaller bounded assignment when it is an execution
failure. Unresolved identities get a retry only with a concrete new route.
After that, retain explicit unchecked rows and unlock paths; never silently
drop units or treat an empty result as success.

## Search the selected library accurately

Use the selected library and preserve both library ID and item key. Honor skip
and access limits. Search manuscripts with author/title metadata even when the
citation includes an SSRN URL or was classified as an internet source. For
chapter citations, match chapter title and chapter authors first, then container
title; distinguish volume editors from authors and allow an et al. citation
without inventing missing authors. Inspect chapter records before falling back
to the parent book. Check the cited manuscript version separately from a later
publication.

For duplicate records, first establish the same work and relevant version from
metadata. Only then prefer a readable attachment. A PDF must never outweigh
conflicting identity or edition evidence. Open the chosen attachment and confirm
it matches the record and cited work. Cache its extracted UTF-8 text with
`source_path` and `source_sha256` in the source ledger. Do not put generated
analysis or metadata in a source-text file.

Record `library_lookup` on a source when retrieval is incomplete: `status` is
`record_no_attachment`, `record_unreadable`, `not_found`, `unavailable`, or
`not_assessed`; `evidence` names the selected library, search terms/actions and
result. Record statuses require `library_id` and `zotero_item_key`. `not_found`
means only not found in that documented search. No item key by itself establishes
neither absence nor lack of attachments. Keep network, permission, extraction,
version and missing-attachment failures distinct in evidence and unlock paths.

## Run the cached-text sweep

After core verification and requested support, before reporting:

```bash
python3 <skill-dir>/scripts/cache_recovery.py RUN_DIR
```

The helper searches all reachable cached source texts for each unresolved or
unmapped prepared quotation: its assigned source, sibling citations in its note
or body paragraph, and recorded antecedent chains. It retains all hits, including
hits in different works. Files are loaded and normalized once per invocation.
Missing mappings, cache failures and unsurveyed libraries remain visible.

Inspect every hit in the actual file. Resolve attribution and source version,
review brackets/ellipses and surrounding qualifications, and verify pagination
separately. A match in a sibling work cannot clear the assigned source. If the
finding can be resolved, update the ordinary quote checks, verdict and audit
records through their existing gates. Otherwise record a row in
`cache-recovery-reviews.jsonl` with `prepared_unit_id`, `source_id`, the matched
`source_sha256`, substantive `evidence`, and `disposition` of `attribution_issue`,
`version_issue`, `alteration_issue`, `pagination_unresolved`, or `context_issue`.
Explain that remaining issue in Couldn't check; do not call readable cached text
unavailable or recommend attaching a file already present.

Regenerate after any ledger or cache change. Copy the current lines from hidden
`cache-recovery.md` into the report's Couldn't check section (stale-reference
lines may also appear with the cross-reference findings). `text_cached` means a
hash-checked file is available; `searched=...` records the deterministic search,
not a complete human/model reading. Report record/no-attachment, unreadable,
not-found, skipped, unavailable and not-assessed states as distinct limitations.

New runs carry `cache_recovery_version: 1`. Their readiness gate independently
recomputes the sweep, rejects stale/missing artifacts, changed hashes, unsafe
resolution, unreviewed matches and omitted report coverage. Legacy runs without
the field retain their prior contract; add the field explicitly to upgrade a
resumed run. Do not remove it from a new run to bypass recovery. All recovery
artifacts remain hidden; only the completed report is published.
