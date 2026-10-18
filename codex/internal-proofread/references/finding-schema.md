# Finding and Result Schemas

Use JSON or JSONL exactly as described. Preserve the source hash and stable block coordinates. Never identify a location only by page number.

## Finding

```json
{
  "finding_id": "C0001-F001",
  "category": "possible_omission",
  "impact": "high",
  "confidence": 0.91,
  "location": {
    "story": "body",
    "block_id": "B000124",
    "char_start": 86,
    "char_end": 101,
    "heading_path": ["III. General Law", "A. Background"]
  },
  "excerpt": "the court concluded statute applied",
  "message": "The sentence likely lost a conjunction and article.",
  "suggestion": "Change to: the court concluded that the statute applied.",
  "severity": "warning",
  "detection": "semantic"
}
```

Use these controlled categories: `typo`, `duplication`, `possible_omission`, `grammar`, `punctuation`, `delimiter`, `xref`, `heading`, `numbering`, `footnote`, `defined_term`, `consistency`, `formatting`, or `other`.

Use `impact: high` for missing text, duplicated clauses or blocks, broken cross-references, incorrect numbering, or a defect likely to alter meaning. Use `medium` for ordinary grammatical or consistency problems and `low` for spacing or surface punctuation.

## Chunk result

Write one file at `agent-results/<chunk_id>.json`:

```json
{
  "chunk_id": "C0001",
  "source_sha256": "...",
  "status": "complete",
  "reviewed_block_ids": ["B000001", "B000002"],
  "reviewed_note_ids": ["FN1"],
  "findings": []
}
```

Copy `reviewed_block_ids` and `reviewed_note_ids` from the packet metadata. Return an empty findings array when the owned material is clean. Never report defects located only in context blocks.

## Global-lane result

Write one file at `lane-results/<lane>.json`:

```json
{
  "lane": "xref",
  "source_sha256": "...",
  "status": "complete",
  "findings": []
}
```

Valid base lanes are `boundary`, `xref`, `terminology`, `consistency`, and `structure`; semantic cross-reference shards use names such as `xref_semantic_001`. Copy the exact lane name from the packet.

## Recall result

Write one file at `recall-results/<packet_id>.json` using the same finding schema:

```json
{
  "packet_id": "RB0001",
  "source_sha256": "...",
  "status": "complete",
  "reviewed_block_ids": ["B000001", "B000002"],
  "reviewed_note_ids": [],
  "findings": []
}
```

Copy the ownership arrays from `recall-packets.jsonl`. Report only new, nonoverlapping defects; do not repeat any do-not-repeat span in the packet.

## Disposition

Write one row per merged finding to `dispositions.jsonl`:

```json
{"finding_id":"A123","status":"confirmed","suggestion":"Insert ‘that.’","rationale":"The sentence is otherwise grammatically incomplete."}
```

Valid statuses are:

- `confirmed`: definite error to correct;
- `likely`: probable error that should be reviewed;
- `query`: ambiguity requiring author judgment;
- `rejected`: false positive;
- `fixed`: confirmed and corrected in an output copy;
- `style`: optional house-style or accepted-variant normalization, kept outside the error count;
- `prepublication`: a correct-for-now placeholder or publication-stage task that is not a present textual error;
- `waived`: could not be resolved, with a stated limitation.

Give `rejected`, `query`, and `waived` rows a specific rationale.

## Human-report search anchor

For every visible report item, `build_report.py` adds `Find in draft`, an exact contiguous span from the frozen block containing the finding. It targets 14 words and may expand to 24 words to become unique in the extracted draft. If a short repeated footnote remains nonunique, the anchor instead identifies its body-text call site and is labeled `(note call site)`. Keep `Draft` as the shorter defect excerpt; use `Find in draft` as the text the author can paste into Ctrl-F.

## Verifier audit

Write one row per high-impact finding that is confirmed, likely, queried, or fixed to `verifier-audit.jsonl`:

```json
{"finding_id":"A123","source_sha256":"...","audit_status":"confirmed","verifier":"proofread-verifier","rationale":"Independent review of the full paragraph confirms an omitted word."}
```

Valid audit statuses are `confirmed`, `revised`, and `retracted`. A retracted finding must ultimately be rejected.

## Rejection audit

Every high-impact rejected omission, duplication, cross-reference, or numbering candidate receives a second independent audit:

```json
{"finding_id":"A123","source_sha256":"...","rejection_status":"confirmed_rejection","verifier":"proofread-verifier","rationale":"The complete whether clause has subject X and finite predicate Y."}
```

Valid rejection statuses are:

- `confirmed_rejection`: the candidate is not an internal defect and remains rejected;
- `reopen`: the candidate identifies a real defect substantially as stated;
- `revised`: a real defect exists but its diagnosis or suggested change needs material revision.

For `reopen` or `revised`, the lead must change the disposition away from `rejected`. Add `revised_suggestion` when useful.

## Challenger ledgers

`ingest_challenger.py` writes uniquely mapped external-report items to `challenger-findings.jsonl` using the normal finding schema. It writes unresolved items to `challenger-unmatched.jsonl` with `status: pending`. Before readiness validation, change every unmatched row to `resolved` or `waived` and add a nonempty `resolution` explaining the mapping or disposition.
