# Run format

Keep all state under `<project>/.codex-zotero/runs/<run-id>/`.

## `run.json`

Created by `init_run.py`. Preserve `schema_version`, `run_id`, `created_at`, `request`, `library`, and `collection`. Update `status` only to describe the current stage; the validator, not this field, decides readiness.

Set `require_pdfs` by initializing with `--require-pdfs` whenever the user asks for attached full text. The completion gate then requires one structurally verified PDF attachment for every added or reused target item.

## `candidates.jsonl`

Write one JSON object per candidate:

```json
{
  "candidate_id": "c001",
  "decision": "add",
  "reason": "Within scope and verified",
  "item": {
    "itemType": "book",
    "title": "Example",
    "creators": [{"creatorType": "author", "firstName": "A.", "lastName": "Writer"}],
    "date": "2024",
    "publisher": "Example Press",
    "ISBN": "9780000000002",
    "collections": ["ABCD2345"]
  },
  "provenance": [
    {
      "url": "https://publisher.example/book",
      "source_type": "publisher",
      "accessed_at": "2026-07-15T19:00:00-07:00",
      "fields": ["itemType", "title", "creators", "date", "publisher", "ISBN"]
    }
  ],
  "duplicate_check": {
    "scope": "collection_and_library",
    "queries": ["Example A. Writer", "9780000000002"],
    "matches": [],
    "decision": "unique"
  }
}
```

Allowed candidate decisions are `add`, `reuse`, `skip_duplicate`, and `exclude`. Do not leave `pending` candidates at completion. `add` and `reuse` require a resolved duplicate decision. `add` requires provenance covering every nonempty material bibliographic field in `item`; omit generated fields such as `collections`, tags, and access dates from this coverage calculation.

For `reuse`, record the existing Zotero key as `existing_item_key` and put the intended collection-membership patch in `item`.

## `reuse-results.jsonl`

For every `reuse` decision, record the successful version-guarded membership update after using `zotero_api.py patch-item`:

```json
{"candidate_id":"c010","item_key":"ABCD2345","collection_key":"WXYZ6789","operation":"add-to-collection","http_status":204,"written_at":"2026-07-15T19:12:00-07:00"}
```

The validator requires one successful result for each reused item.

## `planned-items.json`

Write a JSON array in candidate order. Each element contains `candidate_id` and `item`:

```json
[
  {"candidate_id": "c001", "item": {"itemType": "book", "title": "Example"}}
]
```

The API helper unwraps this format before upload while preserving the index-to-candidate mapping in `write-result.json`.

## `write-result.json`

Created by `zotero_api.py create-items`. It records the operation, library, request count, SHA-256 of the exact uploaded JSON, candidate order, HTTP status, response, write time, and last library version. Never edit it to turn a failure into a success.

## `verification.json`

Created by `verify_items.py`. A machine `PASS` requires an ISBN or DOI to resolve to a record whose title matches and whose available creator/year fields do not contradict the Zotero item. The file records every resolver result and a summary.

## `manual-verifications.jsonl`

Use only when deterministic identifier verification cannot pass. One object per item:

```json
{
  "item_key": "ABCD2345",
  "candidate_id": "c007",
  "verdict": "MANUAL_PASS",
  "source_url": "https://heinonline.org/HOL/Page?...",
  "source_type": "journal_or_database_record",
  "accessed_at": "2026-07-15T19:15:00-07:00",
  "checked_fields": ["title", "creators", "date", "publicationTitle", "volume", "pages"],
  "note": "Opened the journal record and matched the complete citation metadata."
}
```

The source must have been opened. Record a stable journal page, catalog page, publisher page, official repository, or database record. A search-results page or snippet is insufficient.

## `attachment-results.jsonl`

Append the exact result emitted by `attach_pdf.py --ledger`. A verified entry records the parent and attachment keys, PDF filename and content type, byte size, MD5 returned by Zotero, local SHA-256, acquisition mode, provenance URL, and verification time. New attachments default to a filesystem-safe `Creator - Year - Title.pdf` filename derived from the parent Zotero item; use a normalized `--filename` override only for a genuinely distinct attachment such as a supplement. The verification step confirms that Zotero stored the requested filename. Existing attachments are audited without renaming. Allowed acquisition modes are `url`, `file`, and `existing`. Never hand-author a `VERIFIED` result without re-fetching the attachment from Zotero.

## `audit.json`

Created by `validate_run.py`. `READY` requires resolved candidate decisions, provenance coverage, verified reuse operations, a one-to-one planned/write mapping, no failed writes, and a `PASS` or `MANUAL_PASS` for every newly written key. When `require_pdfs` is true, it also requires one valid `VERIFIED` attachment result for every added or reused target item.
