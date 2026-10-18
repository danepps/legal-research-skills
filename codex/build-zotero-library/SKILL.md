---
name: build-zotero-library
description: Build or extend a verified Zotero collection for a research project, including attached full-text PDFs when requested. Use when the user asks Codex to build, populate, curate, or add sources or PDFs to a Zotero library or collection; gather books, articles, cases, reports, or other research sources into Zotero; attach open-access PDFs or files the user supplies; or audit newly added Zotero items and attachments. Search for candidates, prevent duplicates, record field-level provenance, write through the Zotero Web API, and enforce post-write verification before reporting completion.
---

# Build Zotero Library

Build a useful research collection without inventing sources or leaving uncertain records behind. Treat Zotero writes as a reviewed data pipeline: scope, discover, verify, deduplicate, preview, write, re-fetch, audit.

## Start a hidden run

Create run state inside the active project, not beside the final user-facing work:

```bash
python3 <skill-dir>/scripts/init_run.py \
  --project-dir <project-dir> \
  --request "<user request>" \
  --library user:<id> \
  --collection-name "<target collection>"
```

Add `--require-pdfs` whenever the request requires attached full text. Do not omit it merely because authenticated acquisition may be difficult; the validator must keep the run incomplete until every target has a verified PDF or the user accepts a narrower result.

Use the printed run directory for every artifact. Read [references/run-format.md](references/run-format.md) before populating it. Do not expose API keys in files, commands, logs, or chat.

Infer a sensible scope when the request is specific. Ask only when a missing choice would materially change the collection: target library, new collection name, source types, date range, jurisdiction, or whether representative rather than exhaustive coverage is wanted. Creating a new collection is authorized only when the user requested one or clearly requested a named destination that does not exist.

## Confirm access and destination

Use the connected Zotero MCP tools for semantic library search, metadata reads, and full text when available. Use the bundled Web API helper for exact collection reads and all writes:

```bash
python3 <skill-dir>/scripts/zotero_api.py key-info
python3 <skill-dir>/scripts/zotero_api.py collections --library user:<id>
python3 <skill-dir>/scripts/zotero_api.py collection-items --library user:<id> --collection <key>
```

For a new installation, configure the recipient’s own `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, and `ZOTERO_LIBRARY_TYPE` securely in the host environment. The helper reads those variables first; its macOS Keychain fallback is specific to an existing Codex Zotero setup and is optional. Resolve the recipient’s destination from the API and current request; never copy another researcher’s library IDs or credentials. Never read Claude configuration as a credential source. Pass `--library group:<id>` explicitly for a group library.

Before any write:

1. Confirm the target library and collection key.
2. Search both the collection and the wider library for duplicates using title, creator, ISBN, DOI, and close variants.
3. Record the search queries, possible matches, and `unique`, `duplicate`, or `uncertain` decision in `candidates.jsonl`.
4. Recheck duplicates immediately before each write, including late additions and items created earlier in this run. Reuse an existing item by adding collection membership rather than creating a duplicate. Because that modifies external state, preview the proposed membership change just like a new item.

## Discover and verify candidates

Search the local project and Zotero library first when relevant, then authoritative external sources. For books prefer publisher pages, national or university library catalogs, ISBN-linked catalog records, and Google Books. For articles prefer the journal, DOI registry, institutional repository, author manuscript, HeinOnline, SSRN, or another source that proves bibliographic identity. For cases and government materials prefer official repositories.

If a source is available only through an authenticated database (HeinOnline, a library proxy, a publisher paywall), do not try to automate access. Ask the user to download the PDF themselves and attach it with `--file --source-mode file`, recording the provenance URL with `--source-url`. Never type, request, store, or infer institutional credentials, and never drive a two-factor login.

For every candidate:

1. Open at least one source establishing that the work exists.
2. Cross-check surprising, conflicting, or high-risk metadata against a second independent source.
3. Record field-level provenance for every material field written: title, creators, date, publication, publisher, volume, issue, pages, edition, ISBN, DOI, URL, and item type as applicable.
4. Do not fill plausible metadata from memory. Leave a nonrequired field blank when it cannot be verified.
5. Use the edition's actual imprint and date. Preserve verified contributor roles; do not force an unsupported role into Zotero.
6. Put stable identifiers in their native fields. Normalize DOI values without a `doi.org` prefix. Prefer ISBN-13 when the edition supplies it.

Precheck proposed records before writing:

```bash
python3 <skill-dir>/scripts/verify_items.py --input <run-dir>/planned-items.json \
  --output <run-dir>/precheck.json
```

An identifier-based `PASS` proves bibliographic identity and detects contradictions; it does not prove every Zotero field. The provenance ledger carries that burden. `NO_IDENTIFIER`, `UNRESOLVED`, `UNAVAILABLE`, and `MISMATCH` require more research or a documented manual verification, not optimism.

## Preview and write

Show the user a compact preview before a broad or judgment-heavy write: destination, item count, representative inclusions, exclusions, and unresolved duplicate or scope questions. A routine write that directly matches a precise request may proceed without an extra confirmation. Never silently broaden the project.

Write no more than 50 items per request. The helper adds an idempotency token and records the exact request hash and API response:

```bash
python3 <skill-dir>/scripts/zotero_api.py create-items \
  --library user:<id> \
  --input <run-dir>/planned-items.json \
  --output <run-dir>/write-result.json
```

Inspect the response's successful, unchanged, and failed maps. Do not report an item as added merely because the HTTP request returned successfully.

For corrections, fetch the current item and use a version-guarded partial update:

```bash
python3 <skill-dir>/scripts/zotero_api.py patch-item \
  --library user:<id> --key <item-key> --version <version> \
  --input <patch.json>
```

Do not delete preexisting items. If a newly created item cannot be corrected or verified, disclose the problem and request approval before deleting it.

## Acquire and attach requested PDFs

Prefer an open publisher, journal, repository, author, SSRN, government, or other authorized direct PDF URL. Attach direct PDF bytes and append the verified result to the run ledger:

```bash
python3 <skill-dir>/scripts/attach_pdf.py \
  --library user:<id> --item <parent-key> --url <pdf-url> \
  --ledger <run-dir>/attachment-results.jsonl
```

For a PDF the user downloaded themselves from an authenticated source, attach the local file with its provenance URL:

```bash
python3 <skill-dir>/scripts/attach_pdf.py \
  --library user:<id> --item <parent-key> --file <path-to.pdf> --source-mode file \
  --source-url <item-url> --ledger <run-dir>/attachment-results.jsonl
```

If a reused Zotero item already has a stored PDF, verify its bytes instead of adding a duplicate:

```bash
python3 <skill-dir>/scripts/attach_pdf.py \
  --library user:<id> --item <parent-key> --verify-existing \
  --ledger <run-dir>/attachment-results.jsonl
```

The helper rejects HTML masquerading as PDF, re-fetches Zotero attachment metadata, matches Zotero's MD5, computes a local SHA-256, and writes `VERIFIED` only after the parent, content type, and stored hash agree.

For each new attachment, the helper fetches the parent item's verified Zotero metadata and stores the PDF as `Creator - Year - Title.pdf`. It uses two creator surnames, switches to `FirstCreator et al.` for three or more, omits unavailable components, removes filesystem-unsafe characters, and limits the UTF-8 filename length. Use `--filename` only when a source needs a distinct descriptive label, such as a supplement; the override is normalized to the same safe PDF rules. Do not preserve opaque download names when parent metadata is available. `--verify-existing` audits an existing filename but does not rename it.

## Re-fetch and enforce the gate

Verify exactly what Zotero stored, using only the keys returned by the write response:

```bash
python3 <skill-dir>/scripts/verify_items.py \
  --library user:<id> --keys <K1,K2,...> \
  --output <run-dir>/verification.json

python3 <skill-dir>/scripts/validate_run.py <run-dir> --require-ready
```

For a genuine item without a resolvable ISBN or DOI, add a line to `manual-verifications.jsonl` following the run-format reference. A `MANUAL_PASS` requires an opened authoritative source, the item key, the source URL, access time, checked fields, and a concise note. Search snippets, memory, and secondary mentions do not qualify.

Do not call the run complete unless the validator prints `READY`. For a `--require-pdfs` run, `READY` also requires one structurally verified PDF attachment for every added or reused target item. Repair failed writes, duplicates, provenance gaps, attachment gaps, and verification failures, then re-run the gate. A network outage may justify a candid incomplete or limited handoff, never a fabricated pass.

## Report

Return a concise summary containing:

- destination library and collection;
- items added, reused, skipped as duplicates, and excluded;
- the validator's status and verification counts;
- any `MANUAL_PASS` items and their verification basis;
- material judgment calls, remaining limits, and decisions the user should make.

Keep run artifacts hidden unless the user asks to inspect them. Do not publish a memo merely to describe the run.
