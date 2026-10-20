---
name: cite-check
description: Verify legal citations, quotations, pincites, proposition support, cross-references, source versions, and URLs in draft scholarship or legal writing. Use when Codex is asked to cite-check, source-check, quote-check, validate footnotes, audit authorities, find broken Id. or supra chains, check a legal article before submission, or produce a footnote-by-footnote verification report from a .docx, Markdown, or text draft. This is an evidence-verification workflow with basic citation sanity checks, not a comprehensive Bluebook-format linter.
---

# Cite Check

Verify a draft against retrieved sources without modifying it. Use deterministic extraction and machine-checked ledgers for structure. Keep draft text, inferred source identity, retrieved evidence, and final judgment in separate fields so a model inference cannot silently become a claim about what the draft says.

## Non-negotiable rules

- Opinions, articles and dockets may postdate the model’s training data; an unfamiliar 2025–2026 decision is not a hallucination signal.
- Never verify from memory. Record the exact source and verification basis for every verdict.
- Preserve the input draft. Keep all working artifacts in a hidden run directory.
- Resolve `Id.`, `ibid.`, `supra`, and other cross-references before source grouping or verification.
- Group by unique source. Fetch once, then check every quotation, proposition, and pin tied to it.
- Run `scripts/verify_quotes.py` against the retrieved source text for every extracted quotation. Treat its result as evidence of a match in that file, not as proof of source identity, proposition support, honest framing, or authoritative pagination.
- Preserve verbatim `draft_citation_text`, `full_footnote`, `body_context`, and a Cmd+F-able `draft_find_string`. Never replace draft text with a reconstructed caption or citation.
- Treat inferred identity as `resolved_source_label`, never as text printed in the draft. A nameless reporter cite may be correct when the case name appears in the body.
- Report absence as `not_found_in_sources_checked`, not “fabricated.” Search every source named in the footnote before using that category.
- Independently recheck every critical/high adverse finding and every exact-one-page pincite correction.
- Treat CourtListener lookup as identity screening only. A miss is unresolved, not proof of an error.
- Treat bot walls, paywalls, OCR failures, missing attachments, and unavailable pagination as limits, not negative evidence.
- Never open PDFs in a GUI or install software without approval.

## Scope and depth

Check source identity and metadata, quotation fidelity, honest alterations, proposition support, recoverable pincites, `Id.`/`supra` integrity, live URLs, source-version drift, syllabus use, and obvious citation-data errors.

Do not comprehensively lint signals, typefaces, citation ordering, short-form style, or parenthetical form unless separately requested.

- **Focused:** specified footnotes, sources, or quotations.
- **Standard:** the full draft; default.
- **Deep:** Standard plus independent review of load-bearing support and all adverse findings.

## Run the workflow

### 1. Inspect project rules and initialize

Read applicable `AGENTS.md` files before choosing paths or publication formats. Identify the draft, scope, local source folders, connected scholarly libraries, and any requested output constraints.

Default the run directory to `<project>/.codex-memo/runs/<run-id>/` and initialize it:

```bash
python3 <skill-dir>/scripts/init_run.py <draft> --run-dir <hidden-run-dir> --scope standard
```

For a focused pass, add `--scope focused --footnotes 45-80` (or explicit numbers). The run directory itself must not already exist; create its parent, then pass a new run-id child. The initializer freezes a source snapshot inside the run and writes the manifest, extraction, scope-filtered prepared quote units, and empty ledgers. Review only that snapshot; report its hash and disclose later changes to the live draft without invalidating the snapshot review. If tracked changes exist, disclose that extraction includes visible insertions/move destinations and excludes deletions/move origins, including changes inside footnotes; do not silently accept or reject changes.

Inspect `blocking_issues` before continuing. Referenced endnotes, missing note text, and unsupported numbering/restarts block completion. A separately normalized copy can be used only when its text and note mapping to the supplied draft are verified; disclose the transformation and initialize a new run. Otherwise disclose that the requested review could not be completed. Never alter the supplied draft. Custom-marked author notes have `number: null`, a stable `note_id`, and a `custom_mark` display label; preserve those IDs instead of assigning a footnote number.

### 2. Read the protocol

Read [references/verification-protocol.md](references/verification-protocol.md) completely before creating citation units or verdicts.

### 3. Segment with draft-grounded fields

Use `prepared-units.jsonl` as context scaffolding. Convert every citation instance—not only every quotation—into `citation-units.jsonl`.

For new schema-v6 runs, reconcile every in-scope footnote in `footnote-coverage.jsonl` and every body paragraph in `body-coverage.jsonl`. Set `status: reviewed` and list the corresponding citation `unit_ids`, or use `no_citations`, an empty list, and a concrete `reason`. Body coverage inventories citations located in the body; citations appearing in footnotes remain in footnote coverage. A focused numbered-footnote run excludes body coverage and custom-marked notes. The initializer leaves coverage rows `pending`; the gate rejects omitted locations. This is a lead-reviewed inventory, not a claim that the extractor parses every citation or finds every quotation.

Review styled block quotations and every indented `block_quote_candidates` paragraph. Record `block_quote_review` and `block_quote_reason` in body coverage. For a confirmed indentation candidate, add a prepared unit with the full quotation, `paragraph_number`, and `block_quote: true`; do the same for any other missed block or short quotation. Inspect nested quotes and source attribution. `primary_inferred_from_paragraph: true` is only a suggestion; confirm the source relationship and set the citation unit's `attribution_reviewed: true` before verifying it.

For each unit:

- copy `draft_citation_text` verbatim from its extracted footnote or body paragraph;
- preserve `full_footnote` and relevant `body_context`;
- choose a short `draft_find_string` that occurs verbatim in the extracted draft;
- resolve cross-references into a separate `resolved_source_label` and record the resolution path;
- use `caption_in_draft: footnote`, `body`, or `none`; never synthesize a caption;
- attach each quotation or proposition to the citation that the footnote's syntax and placement make responsible for it, and preserve its `prepared_unit_id`;
- assign a stable `source_id` and collapse repeated authorities only after resolution.

If resolution remains uncertain, preserve the uncertainty. Do not use placeholders or best-guess captions.

Use the exact keys in the protocol's [ledger field reference](references/ledger-fields.md). Body-only citations use `location: body`, `paragraph_number`, and the complete extracted paragraph as `body_context`, with no footnote identity. Keep every cited pincite in `pincite`; unavailable pagination requires a partial verdict, not omission of the pin. Reporter extraction and leading-Id flags are screening aids, not an exhaustive citation inventory or an automatic resolver.

### 4. Retrieve and verify by source bundle

Prefer user-provided sources and the project’s connected scholarly library, then official/primary sources, authoritative reproductions, repositories, and the open web. Use current web research for external sources and record direct URLs or local identifiers.

Optionally screen case identities with:

```bash
python3 <skill-dir>/scripts/check_cite.py --input-file <citation-text-file>
```

Retrieve the opinion itself for quotes, holdings, propositions, and pins. Before calling a lookup miss unconfirmed, run both caption and quoted citation-string fallbacks with `check_cite.py 'CITATION' --name 'A v. B'`; inspect candidate identities and citing passages, and record all routes tried or unavailable. A citing passage is corroboration, not conclusive identity proof. Use `too_recent_for_free_index` only with a basis for that explanation, never merely because a citation is unfamiliar. Recommend a direct official-record or database spot-check when unresolved.

Write one row per unique source to `source-ledger.jsonl` and one row per citation unit to `verdicts.jsonl`. For scholarship, inspect the project library before the web and compare cited and current versions of manuscripts. If no library is connected, state that once in the method section and continue to authoritative web sources. For an absent quote, search sibling sources named in the same footnote; use `misattributed` if the passage appears in a different cited source.

Store each retrieved or extracted full-text source under the hidden run directory, preserving form feeds or explicit page markers when available. For each source bundle, create a JSON array whose rows contain `prepared_unit_id`, `unit_id`, `source_id`, `quote`, and any resolved `pincite`, then run:

```bash
python3 <skill-dir>/scripts/verify_quotes.py RUN_DIR/cached-sources/SOURCE.txt \
  --json RUN_DIR/source-quote-items.json \
  --output RUN_DIR/quote-checks.jsonl --append
```

Use `verbatim` and `normalized` as deterministic match evidence. An `altered` result requires a human/model review of whether the marked brackets or ellipses are honest; set `alteration_reviewed: true` only after that review. `not_found` means only that the quote did not match this retrieved file. If no source text could be obtained, add an `unavailable` quote-check row with the reason and concrete unlock path. Never convert a fuzzy hint into source text without opening the indicated passage.

Explicit page markers use `<<pg. N>>` at the **start** of the page. For markers placed after their page, pass `--marker-follows`. For form-feed text, `--first-page` means the printed number of the first physical text segment, including any cover sheet: remove a nonpaginated cover from the working text copy or use calibrated explicit markers. Check at least one recovered page against a visible or authoritative page before relying on the mapping. Paragraph/section pins are not page numbers; record their direct confirmation in `pincite_verification`, or use `partial` and an unlock path. Review `bracket_map` alongside the complete `match_excerpt`; matching a bracket wildcard does not approve the substitution.

Keep exactly one final verdict per citation unit. A quote found only in a sibling source cannot verify the source assigned to the unit; resolve the attribution or report the discrepancy. For each `partial` or `unverified` verdict, record a concrete `unlock_path`. An unavailable source also needs `reason` (or `retrieval_notes`) and `unlock_path`. List those unit/source IDs and their exact unlock paths in **Couldn't check**, and use `complete_with_limits`.

For pincites, identify the pagination convention before proposing a correction: printed page, star/header marker preceding text, or footer marker following text. Record `page_delta` as an integer when proposing a page correction. Treat an exact-one-page difference as presumptively ambiguous until independently checked against the visual page; page corrections with no recoverable delta also require an audit.

### 4a. Check subsequent history and treatment

Read [references/case-review.md](references/case-review.md). Check every lower-court case for subsequent history and every case for treatment by both citation graph and caption-phrase routes. Use the history helper and the available companion treatment helper, or record equivalent direct searches. Read material hits and evaluate the draft's actual use. Reconcile one `case-review.jsonl` row per case source, including partial, skipped and unavailable passes. A skipped pass requires `complete_with_limits` and explicit disclosure; the advisory section separates required-history omissions, contradicted history, treatment flags and unchecked cases.

### 5. Verify the verifier

Independently reconstruct every critical/high adverse finding, every `not_found_in_sources_checked`, and every exact-one-page pincite correction from:

1. the complete footnote and body context;
2. the verbatim draft citation and find string;
3. the resolved source and any sibling cites;
4. the retrieved passage and identified pagination convention.

Write `confirmed`, `revised`, or `retracted` to `verifier-audit.jsonl`. When one audit relocates a passage, reconcile sibling units from the same sentence or footnote before reporting.

### 6. Write and publish the report

Write the canonical report to `<run-dir>/report.md`. Put genuine findings first; do not put cleared suspicions, near-findings, or internal deliberation in “Needs your attention.” Then include the history/treatment advisory, complete footnote ledger and limitations. State the existence-only share of citation instances using the exact summary sentence in the ledger reference; count instances, not unique sources.

Save `findings.json` beside the hidden `report.md` with:

```bash
python3 <skill-dir>/scripts/findings_diff.py --run-dir RUN_DIR --output RUN_DIR/findings.json
```

Generate it after finalizing the ledgers, manifest counts and completion target. On a re-run, copy the prior findings file into the new hidden run as `previous-findings.json`, record its SHA-256 as manifest `previous_findings_sha256`, and open the report (after title/provenance) with:

```bash
python3 <skill-dir>/scripts/findings_diff.py RUN_DIR/previous-findings.json RUN_DIR/findings.json \
  --output RUN_DIR/findings-diff.md
```

Insert that exact block. Keys use source/content/verdict, never footnote numbers or run IDs. An absent finding in an incomplete or focused re-run is **not rechecked**, not automatically resolved. Keep duplicate occurrence locations. If no previous structured file is available, disclose that no reliable automated comparison was possible. The structured files remain hidden under the publication policy; publish only the report unless the user explicitly requests the JSON sidecar, and retain the hidden file for the next run.

Every adverse item must contain the footnote number, verbatim draft find string, draft and source text where applicable, category, severity, verification basis, evidence location, suggested action, and required audit result.

After the readiness gate in step 7 passes, publish `<Draft name> — Cite Check.md` by default. Never copy a provisional report to the visible destination. Create a matching `.docx` only when the user or controlling project instruction expressly requests it. Put directly below the title:

```text
Created by: Codex
Model: <exact lead model label>
Generated: <YYYY-MM-DD HH:MM:SS timezone>
Elapsed: <wall-clock duration>
Tokens: <aggregate exact runtime usage or unavailable (runtime did not expose exact usage)>
```

Append the required `Topic:`, local `Date:`, `By: Codex-<exact lead model label>`, and `Production details:` block after all substantive content. Include elapsed time through audit, actual subagent roles (or `subagents: none`), and aggregate runtime usage or `tokens unavailable (runtime did not expose exact usage)`. Preserve the provenance header for the validator. Follow any user-specified publication location or naming policy.

For a requested DOCX, use one direct Pandoc conversion from the canonical Markdown with minimal styling. Pandoc is required only for this optional derivative; if absent, publish the Markdown and disclose that DOCX is unavailable. Then run `scripts/verify_docx_ooxml.py DOCX --markdown MARKDOWN --output <run-dir>/docx-verification.json`, inspect the extracted OOXML text for substantive synchronization, and disclose that pagination and visual layout were not rendered. Never invoke `soffice`, `libreoffice`, `render_docx.py`, the documents skill, or any command/helper/runtime that launches LibreOffice; do not run DOCX-to-PDF-to-image conversion inside or outside the sandbox. A DOCX failure must not block publication of the audited Markdown.

The ordinary readiness gate checks the canonical Markdown even when a legacy manifest says `matched_pair` or `docx_only`. To check the optional derivative record afterward, run `validate_run.py <run-dir> --require-ready --require-docx` separately. Do not add `--require-docx` to the Markdown publication gate.

### 7. Validate readiness

Run:

```bash
python3 <skill-dir>/scripts/validate_run.py <run-dir> --require-ready --mark-complete
```

Before running the gate, set manifest `status` to `ready_for_validation`, set `completion_target` to `complete` or `complete_with_limits`, and synchronize manifest counts including `quote_checks`. Only `--mark-complete` may move it to the final state, and only after every check passes. A `complete_with_limits` report may contain unavailable sources only if every unchecked item and unlock path is enumerated.

## Cost and retry controls

- Deduplicate sources and quote rows before retrieval.
- Use at most three materially different mirrors per source unless authorized otherwise.
- Stop after two materially different bot-wall attempts.
- If resources tighten, prioritize quotations, load-bearing propositions, broken cross-references, identity, and metadata, and disclose the exact degraded scope.
- Preserve ledgers so the run can resume; never sacrifice adverse-finding audits.
- Keep the lead agent responsible for resolution, grouping, severity, conflict resolution, audits, and publication. Delegate only bounded source bundles when parallel work is available and proportionate; do not recursively delegate.
