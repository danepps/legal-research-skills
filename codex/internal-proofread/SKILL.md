---
name: internal-proofread
description: Proofread long legal, scholarly, academic, policy, or professional drafts for internal textual defects using deterministic whole-document checks, bounded subagent review, independent verification, and machine-enforced completion gates. Use when Codex is asked to proofread, copyedit for errors, conduct an internal pre-circulation review, catch typos or missing and duplicated words, audit internal cross-references, check headings/footnotes/numbering/defined terms, or return a verified proofreading report or marked DOCX from a .docx, Markdown, or text draft. Do not use this workflow as a substitute for substantive legal editing, source verification, or comprehensive Bluebook checking.
---

# Internal Proofread

Compile the draft into stable text blocks, check its global structure deterministically, distribute owned chunks to bounded readers, and synthesize every candidate through a proof ledger. Preserve the source draft and distinguish genuine errors from stylistic preferences.

## Non-negotiable rules

- Preserve the original draft. Keep all snapshots, packets, ledgers, audits, and intermediate reports inside the hidden run directory.
- Never move, rename, delete, quarantine, or reorganize any artifact outside the current run directory unless the user expressly asks. Treat files and hidden run directories created by other tools or earlier workflows as out of scope.
- By default, place the run under `<draft-parent>/.codex-proofread/runs/`; never create a visible `proofread-runs`, `AI Memos/proofread-runs`, packet, ledger, verifier, diagnostic, or temporary file in the user's workspace.
- Publish nothing visible until the readiness gate passes. For report-only work, the sole visible output is `<draft-stem> — Proofread.md` beside the draft.
- Give every published report a provenance header and a final production block naming Codex, the exact model, local date, elapsed wall-clock time through audit, aggregate runtime-reported tokens or the explicit unavailable disclosure, and subagent roles. Never invent accounting or let unavailable tokens block an audited report.
- Freeze a byte-for-byte source snapshot inside the run directory and bind every artifact to its SHA-256 hash. Never review the live draft path.
- Give every reviewable block and footnote exactly one primary owner.
- Use overlap only as context. Do not report context-only defects from a chunk packet.
- Return structured findings with exact excerpts and stable block coordinates.
- Do not rewrite for elegance, organization, tone, or substantive argument.
- Do not silently correct quotations. Query apparent quotation errors unless source comparison was expressly requested.
- Independently verify every high-impact missing-text, duplication, cross-reference, or numbering finding.
- Run a smaller independent recall pass over every reviewable block and note after the first merge.
- Independently audit every high-impact rejected omission, duplication, cross-reference, or numbering candidate.
- Treat OOXML footnote IDs as storage identifiers, never as Word's displayed note numbers. Resolve note cross-references through `display_note_to_block` in `symbols.json`.
- Prohibit recursive delegation and retry malformed worker output at most once.
- Do not call a run complete until `validate_run.py --require-ready` passes.

## Initialize the run

Identify the draft and requested output. Ask only when a missing choice would materially change whether the workflow may edit a copy or should report only.

Create a fresh hidden run directory. Omit `--run-dir` for the standard location. Standard review uses moderately larger packets to control orchestration cost while retaining the mandatory second pass:

```bash
python3 <skill-dir>/scripts/init_run.py <draft>
```

Use `--review-depth exhaustive` for unusually dense, high-stakes, or expressly exhaustive pre-publication review. It restores the 800–1,200-word primary packet range and smaller recall packets:

```bash
python3 <skill-dir>/scripts/init_run.py <draft> --review-depth exhaustive
```

Read the printed `run_dir` from initialization and use it for every later command. Supply `--run-dir` only when an explicit hidden or temporary audit location is required. Never point it at a visible workspace folder.

Initialization copies the live draft to `source-snapshot.<ext>` before extraction. Treat that copy as immutable. `draft_path` and the readiness gate point to the snapshot; `original_draft_path` records the live source only for provenance. Later saves to the live draft cannot stale the run. To review later edits, start a new run and create a new snapshot.

The standard local-review chunk is 1,200–1,800 core words with about 120 context words on each side. Reduce the limits further for unusually dense footnotes or tables:

```bash
python3 <skill-dir>/scripts/init_run.py <draft> --run-dir <run-dir> \
  --min-words 500 --target-words 700 --max-words 900 --context-words 100
```

Inspect `run-manifest.json`, `document.json`, `symbols.json`, `static-findings.jsonl`, and `chunks.jsonl`. Run basic validation before delegation:

```bash
python3 <skill-dir>/scripts/validate_run.py <run-dir>
```

For DOCX limitations and marked-copy rules, read [references/docx-output.md](references/docx-output.md).

## Fan out the review

Read [references/orchestration.md](references/orchestration.md) and [references/finding-schema.md](references/finding-schema.md) completely before spawning agents.

Distribute every file under `packets/` to a separate `proofread-chunk` agent. Distribute boundary, consistency, and every `xref_semantic_*` lane to `proofread-chunk`; distribute formal xref, terminology, structure, and every `serial_comma_*` lane to `proofread-mechanical`. Semantic xref packets include the source call site, source note, target note, target call site, and nearby note chain; require the reviewer to test support, not merely target existence. Serial-comma packets are a deterministic candidate sweep: every candidate must receive a contextual yes/no review so a clean set supports an affirmative class clearance. Require each worker to return its uniquely identified JSON result. If its role is read-only, the lead writes that result to the assigned file; never ask a read-only worker to change its sandbox. A worker with authorized write access may write only its unique result file.

Use the installed routing when available:

- `proofread-chunk`: `gpt-5.6-terra`, medium reasoning;
- `proofread-mechanical`: `gpt-5.6-luna`, low reasoning;
- `proofread-verifier`: `gpt-5.6-sol`, high reasoning.

Launch each concurrency wave with parallel cold-context spawns (`fork_turns="none"`) in one lead turn, then wait once for the wave. Avoid per-agent polling, repeated status listings, and full-result messages; workers write result files and return only a terse completion notice. Check result identity, source hash, reviewed block IDs, reviewed note IDs, and status. Retry one malformed or incomplete result once. Do not let a worker broaden into source research, substantive editing, or direct document changes.

Audit at least ten percent of chunks reported clean as specified in the orchestration reference. Expand the clean-chunk audit when the threshold is exceeded.

## Merge and adjudicate

Merge static and agent candidates:

```bash
python3 <skill-dir>/scripts/merge_findings.py <run-dir>
```

Create the mandatory fine-grained recall pass:

```bash
python3 <skill-dir>/scripts/make_recall_packets.py <run-dir>
```

Give each recall packet to a fresh `proofread-chunk`, wait for complete ownership, and merge again. Recall packets search for new semantic residue, nonadjacent duplication, transposed defined terms, malformed noun phrases, internal conflicts, and secondary errors; they must not repeat listed first-pass spans.

When another current or prior proofreading report exists for the same draft, ingest it only after the blind passes. This includes an earlier Codex report whose findings should be carried forward and freshly verified:

```bash
python3 <skill-dir>/scripts/ingest_challenger.py <run-dir> <report.md>
```

Resolve or waive every pending `challenger-unmatched.jsonl` item with a reason, then merge again. Do not assume a challenger is correct merely because it reported an item.

After confirming any repeated-form or rule-class defect, sweep the frozen document for every exact and normalized occurrence of that class. Reopen the merge if the sweep yields additional candidates; do not publish a report that lists only a sampled subset of a known deterministic class.

Re-read each candidate in `document.json`. Write one disposition row per finding to `dispositions.jsonl`. Confirm actual errors, reject false positives with reasons, and convert unresolved ambiguity into author queries.

Partition high-impact findings that remain confirmed, likely, queried, or fixed into neutral packets of no more than eight. Give each packet to a fresh `proofread-verifier` without revealing the first reviewers' conclusions. Require a separate outcome for every finding and write the results to `verifier-audit.jsonl`.

After provisional dispositions, create and run the rejection audit:

```bash
python3 <skill-dir>/scripts/make_rejection_packets.py <run-dir>
python3 <skill-dir>/scripts/merge_rejection_audit.py <run-dir>
```

Give every rejection packet to a fresh `proofread-verifier`. Reopen or revise every disposition required by `rejection-audit.jsonl`. For a `whether` or `if` omission, require identification of the subject and finite predicate of the entire clause.

Rerun `merge_findings.py` after any worker or lane result changes. Keep the lead agent responsible for all dispositions, verifier reconciliation, and final wording.

## Report and optionally mark a copy

Build the canonical report:

```bash
python3 <skill-dir>/scripts/build_report.py <run-dir>
```

Put confirmed errors first, followed by likely errors, author queries, pre-publication checks, an optional style-consistency section, and limitations. Use `prepublication` for correct-for-now slip-opinion pagination placeholders and similar publication-stage tasks; do not call them confirmed errors. For every visible item, include a `Find in draft` anchor copied exactly from the frozen source: normally 14 words and expanded up to 24 when needed for uniqueness. When a short repeated footnote cannot yield a unique anchor, use a unique anchor from its body-text call site and label it. Keep the shorter `Draft` field focused on the defect. Use the `style` disposition for accepted spelling, hyphenation, capitalization, or house-style alternatives that are not textual errors. Summarize the rejected-candidate count; keep full rejection details in the ledgers. Add `--include-rejected` only when the user wants an audit appendix. Report findings in document order.

Default to report-only output. Treat `report.md` inside the hidden run directory as canonical but internal. Do not ask the user to browse the run directory and do not copy any other artifact into a visible folder.

After the readiness gate passes, publish the only visible report with exact provenance values:

```bash
python3 <skill-dir>/scripts/publish_report.py <run-dir> \
  --model <exact-model-label> --tokens <aggregate-run-token-count> \
  --subagents "<actual roles and counts, or none>"
```

The publisher calculates generation time and elapsed wall-clock time, inserts the provenance header, and records the metadata in the hidden manifest. It may replace an existing Codex-authored report, but it must preserve a non-Codex file at `<draft-stem> — Proofread.md` and fall back to `<draft-stem> — Codex Proofread.md`; an explicit occupied `--output` path is an error. Obtain the model label and aggregate token count from the current Codex run or session accounting. Do not estimate either value. If exact aggregate token accounting is unavailable, replace `--tokens N` with `--tokens-unavailable`. This prints `tokens unavailable (runtime did not expose exact usage)` and records a null count. The final production block follows all report content. Accounting limitations never waive the readiness gate.

If the user requests a marked DOCX, create a separate tracked-change copy only through a direct OOXML method that does not launch an office application. Apply only confirmed corrections; add comments for likely errors and author queries. Re-extract and re-lint the marked copy, confirm ZIP/OOXML integrity and XML parseability, and disclose that pagination and visual layout were not rendered. Never invoke `soffice`, `libreoffice`, `render_docx.py`, the documents skill, or any helper/runtime that launches LibreOffice. If a safe direct-OOXML writer is unavailable, publish the report and explain that the marked DOCX was not created. A specifically requested marked copy is the only exception to the one-visible-file default.

## Enforce readiness

Run:

```bash
python3 <skill-dir>/scripts/validate_run.py <run-dir> --require-ready
```

Fix stale merges or reports, first-pass or recall coverage gaps, pending challenger items, missing lane results, undisposed findings, overlapping duplicate findings, and missing retained-finding or rejection audits. Use `complete_with_limits` only for explicit unresolved limitations; never use it to bypass required coverage or independent verification.

Publish and deliver the visible report only after `--require-ready` passes. State the tracked-change view, unresolved limitations, and whether the readiness gate passed. Keep the hidden audit directory out of the handoff unless the user asks for it.
