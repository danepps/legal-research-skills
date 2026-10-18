# Parallel Proofreading Orchestration

## Roles and model routing

- Keep the lead on the user-selected parent model and reasoning effort. Retain adjudication, author-query decisions, final edits, and reporting in the lead thread.
- Spawn `proofread-chunk` agents on `gpt-5.6-terra` with medium reasoning for owned-core prose and seam review.
- Spawn `proofread-mechanical` agents on `gpt-5.6-luna` with low reasoning for bounded cross-reference, terminology, and structure inventories.
- Spawn `proofread-chunk` agents for semantic xref shards, the semantic consistency lane, and the independent recall packets.
- Spawn `proofread-verifier` agents on `gpt-5.6-sol` with high reasoning for retained high-impact findings and high-impact rejection audits.
- If named custom agents are unavailable, give the same role instructions to ordinary subagents and record the limitation. Do not silently omit verification.

## Fanout sequence

1. Initialize the run and inspect `run-manifest.json`, `chunks.jsonl`, and the packet counts.
2. Spawn one `proofread-chunk` agent per packet, respecting the session concurrency cap. Use `fork_turns="none"`; each agent must read only its packet plus `finding-schema.md`. Read-only agents return the requested JSON for the lead to persist at the unique result path; only agents with authorized write access may write that path directly.
3. Spawn the boundary lane with `proofread-chunk`.
4. Spawn formal xref, terminology, structure, and every `serial_comma_*` shard with `proofread-mechanical`; spawn consistency and every `xref_semantic_*` shard with `proofread-chunk`.
5. Launch each concurrency wave in one parent turn and wait once for the wave. Do not poll or list each child separately, and do not permit children to spawn descendants.
6. Validate coverage before merging. Retry malformed or incomplete results once. After one failed retry, stop and report the precise incomplete lane.
7. Run `merge_findings.py`, then `make_recall_packets.py`. Give every smaller recall packet to a fresh `proofread-chunk`; require new, nonoverlapping findings only. Merge again.
8. When the user supplies a competing proofread report, run `ingest_challenger.py` only after the blind first and recall passes. Resolve every unmatched challenger item, then merge again.
9. Adjudicate every finding against the frozen source. Write `dispositions.jsonl`; use `style` for accepted-variant or house-style normalization that is not an error.
10. Partition retained high-impact findings into neutral verifier packets of no more than eight findings. Give each packet to a fresh `proofread-verifier` without disclosing the first reviewers' conclusions. Supply the full paragraph, adjoining paragraph where needed, associated footnote, and neutral question for each item: “Is there an internal textual defect here? Explain from the text.” Require a separate audit row for every finding.
11. Run `make_rejection_packets.py`. Independently audit every high-impact rejected omission, duplication, cross-reference, and numbering candidate. Merge the result rows with `merge_rejection_audit.py`; reopen or revise dispositions as required.
12. Build the report and enforce readiness validation.

## Independent recall pass

The recall pass is mandatory. Standard review generates 900–1,200-word body packets and note packets bounded at 1,200 words or 40 notes. Exhaustive review uses 600–900-word body packets and note packets bounded at 900 words or 30 notes. Generate them only after the first merge so each packet can identify existing spans as do-not-repeat locations. The second reader must search for semantic editing residue, nonadjacent repetition, transposed defined terms, malformed noun phrases, internal name/date/number conflicts, and a second defect in a block where the first pass found something else. It must not turn accepted variants or stylistic elegance into errors.

## Challenger report

Keep challenger ingestion optional and post-blind. Uniquely mapped excerpts enter the ordinary ledger and are adjudicated like any other candidate. An ambiguous, truncated, or stale excerpt remains in `challenger-unmatched.jsonl`; readiness must fail until the lead marks it `resolved` or `waived` with a reason. Never treat challenger provenance as corroboration by itself.

## Rejection audit

Audit every high-impact rejection in the four protected categories, not a sample. For a `whether` or `if` omission candidate, require the verifier to identify the subject and finite predicate of the entire clause; a predicate inside an infinitive or nested modifier does not satisfy that requirement. Do not mass-reject a rule family merely because extraction is imperfect. Use TOC-derived numbering and displayed-note mappings before confirming an xref rejection.

## Clean-chunk audit

Select at least ten percent of chunks that returned no findings, with a minimum of one. Give them to a fresh `proofread-chunk` agent without revealing that the first pass found nothing. If the audit finds any high-impact miss, or more than two confirmed lower-impact misses per audited 5,000 words, independently re-review every previously clean chunk.

Record clean-audit agents as additional result files named `<chunk_id>-audit.json`. Their findings merge normally; coverage is still measured against the primary `<chunk_id>.json` result.

## Anti-runaway controls

- Keep `agents.max_depth` at 1.
- Keep primary owned-core packets at the configured depth: 1,200–1,800 words for standard review and 800–1,200 words for exhaustive review.
- Use a maximum of one retry for malformed output or incomplete coverage.
- Set one packet and one output path per agent.
- Keep worker completion messages terse; inspect the result files in one bounded lead-side validation call rather than streaming findings through the lead conversation.
- Cap each verifier packet at eight findings; do not create one thread per finding unless a single item is unusually complex.
- Use the depth-specific recall bounds above; do not combine recall and rejection audit in one agent.
- Prohibit research, source checking, substantive rewriting, and direct edits.
- Stop an agent that drifts outside the closed error taxonomy.
- Preserve partial results and return `complete_with_limits` only when the unresolved limitation is explicit.
- Expand scope or budget only from the lead thread.

## Lead adjudication rules

- Verify every exact excerpt against `document.json`.
- Deduplicate substantially overlapping same-block, same-category spans and preserve every source ID in `merged_finding_ids` and `corroborated_by`. Identical language at different locations is not a duplicate finding.
- Preserve disagreements and turn unresolved ambiguity into an author query.
- Treat pending official pagination, unresolved reporter pages, and equivalent correct-for-now placeholders as `prepublication`, not as confirmed errors.
- Do not suppress or condemn every `.”).` citation ending by shape alone. A quotation-only full-sentence parenthetical and a quotation integrated after `explaining that` follow different punctuation rules; adjudicate the actual grammatical structure.
- Never alter quotations silently. Query apparent errors in quoted material unless the authoritative source was supplied and quote checking was expressly requested.
- Do not turn proofreading into citation verification or substantive legal editing. Route those tasks to the cite-check or legal-research workflow when requested.
