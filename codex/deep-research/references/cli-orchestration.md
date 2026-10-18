# CLI Orchestration and Model Tiers

## Contents

- Stages and lane types
- Native subagent launch contract
- Model selection and packet schema
- Merge, mandatory verification, budgets, and stopping

Use this protocol when the CLI can run parallel agents or subprocesses. If parallel execution is unavailable, execute the same lanes sequentially and preserve the same artifacts.

## Stages

### Lead setup

The lead agent defines the plan, source permissions, cutoff, budgets, lane boundaries, and stopping criteria. It owns the evidence ledger, source ranking, conflict resolution, synthesis, and final audit. For literature or scholarly questions, it must declare the direct-answer core separately from adjacent and background coverage before assigning lanes.

Use a four-pass cost shape: discover candidates cheaply, triage and deduplicate, deeply verify only high-value sources, then synthesize from compact evidence packets. Do not send the raw corpus to every lane or to the final writer.

Every lane runs inside a parent budget envelope. The parent assigns limits for calls, tool calls, pages, source records, output tokens, wall time, retries, and follow-up rounds. Workers cannot raise those limits, spawn child workers, or continue after the supervisor marks the lane complete.

Persist orchestration in `lane-manifest.json`. Initialize discovery lanes with `scripts/research_run.py lanes-init`, add promoted-source, gap-fill, verification, and audit lanes with `lanes-add`, call `lane-start` immediately before spawning, and call `lane-finish` only after the assigned packet exists. Use `lanes-next` after every wave and `resume` after interruption. The helper manages queue state and dependencies; the lead remains responsible for native subagent calls and substantive decisions.

### Research lanes

Use only the lanes needed:

| Lane | Bounded task | Model tier |
|---|---|---|
| Direct-answer core | Find works or primary materials whose title, abstract, headings, table of contents, or full text directly addresses the exact question; citation-chase the closest items | Balanced |
| Discovery | Find candidate sources and query expansions | Fast/low |
| Local extraction | Pull relevant passages and metadata from supplied files | Fast/low |
| Primary sources | Locate and extract authoritative texts | Fast/low or balanced |
| Currentness | Check dates, versions, amendments, updates, and later treatment | Fast/low or balanced |
| Literature/context | Map secondary sources and competing accounts | Balanced |
| Contrary evidence | Search disconfirming, adverse, skeptical, or minority sources | Balanced |
| Data/evidence | Extract tables, numbers, definitions, or methodology | Fast/low or balanced |
| Quality audit | Check citations, duplicates, dates, links, and claim support | Fast/low |
| Critic | Attack the provisional synthesis for gaps and overclaiming | Strong |

Researchers should not draft the final report. A lane may provide a preliminary synthesis, but every interpretive conclusion must be marked for lead review.

A focused run normally uses no fan-out and may use at most 2 workers. For standard and deep runs, start with the smallest set of disjoint lanes that covers the material cells. Automatic allocations are 8 standard and 24 deep; absolute ceilings are 12 and 32. Unlock at most one expansion after a productive wave. Simultaneous concurrency remains bounded by the host.

For deep runs, also apply these stage ceilings: discovery 5, promoted-source read 12, gap-fill and retry 3, verification 20, mechanical audit 2, evidence-bundle critic 1. The 32-lane total still controls. Add a lane only when the coverage matrix shows a missing direct-answer core, source type, jurisdiction, period, population, language, competing view, promoted source, or verification need. A worker may propose a follow-up, but only the lead may add it to the manifest and allocate budget. Prohibit recursive fan-out and duplicate generalist lanes.

## Native subagent launch contract

For every research, read, contrary, verification, and critic lane, run `lane-start` and then spawn a native Codex subagent with `fork_turns="none"`. Run `lane-followup` before every repair or continuation; do not send an uncounted follow-up. Use inherited context only when a recorded dependency cannot be represented by packet paths; document the exception in the manifest. A worker prompt must contain:

- lane ID, stage, exact task, stopping condition, and dependency packet paths;
- normalized question, relevant coverage cells, cutoff, source permissions, and confidentiality rules;
- hard call, search, page, source, retry, token/output, and wall-time limits;
- the unique output path `packets/<stage>/<lane-id>.json` and packet schema;
- an instruction to write only that packet, not shared ledgers, manifests, plans, drafts, or other workers' files;
- an instruction not to spawn descendants; and
- an instruction to return only the packet path, terminal status, and a one-sentence summary.

Do not include the lead's provisional answer in first-pass discovery, contrary, source-read, or verification prompts. Do not use full-history forks merely for convenience. Launch no more than the host's available worker slots in one wave, then wait once for the wave. Avoid repeated per-agent polling; inspect registered packets together after the wave.

Use deterministic barriers:

1. Complete discovery packets before lead-side merge, deduplication, and triage.
2. Add one-source read lanes for every controlling, direct-answer, uniquely probative, or material contrary source. Batch only short contextual sources whose combined packet remains bounded.
3. Complete required read lanes before provisional synthesis; a partial packet may cross the barrier only when its limit and missing evidence are recorded.
4. Add bounded gap-fill lanes only for draft-identified or ledger-identified material gaps, with one repair/retry wave at most.
5. Complete the mandatory verification and mechanical-audit waves before calibrated final synthesis.
6. Run the evidence-bundle critic after verification when triggered, then resolve its findings in the lead.

## Model selection

Prefer the lowest-cost model that can perform the lane reliably:

- **Fast/low:** search-term variants, source metadata, passage extraction, table comparison, deduplication, classification, and mechanical citation checks.
- **Balanced:** bounded source collection, literature mapping, adverse-authority searches, and preliminary theme grouping.
- **Strong:** ambiguous question framing, source-quality disputes, causal or legal interpretation, contradiction resolution, recommendations, thesis development, and final writing.

Use this default mapping when the named custom-agent roles or matching CLI profile files are installed:

| Work | Profile | Effective reasoning |
|---|---|---|
| Query expansion, metadata, passage extraction, deduplication, classification, mechanical citation checks | `research-mechanical` | low |
| Bounded source collection, literature mapping, currentness and adverse-source searches, preliminary grouping | `research-balanced` | medium |
| Planning, authority/source ranking, conflict resolution, substantive interpretation, final synthesis | parent lead session | high |
| Independent full-text proposition verification and adaptive-quorum review | `research-balanced` | medium |
| Fresh-context critique of the evidence bundle and three to five highest-risk claims when high-stakes, conflicted, exhaustive, or unusually difficult | `research-critic` | xhigh |

Do not make `research-critic` the default for deep runs, and do not use it merely to restate a stable draft. Keep the model family fixed during the first calibration; change model family only after representative evaluations show that a lower-cost model preserves the required accuracy.

For a bounded standalone CLI worker, enforce the matching profile file with a command shaped like:

```bash
codex exec --profile research-mechanical -C WORKDIR "BOUNDED TASK AND RETURN SCHEMA"
```

Use `research-balanced` for the medium tier. In an existing multi-agent session, spawn the corresponding `research_mechanical`, `research_balanced`, or `research_critic` custom-agent role instead of launching a nested CLI. The lead remains in the parent session. If neither named roles nor profile files are available, fall back to the available agent mechanism, narrow the task and output contract, and record that model/reasoning routing was not enforced.

When a strong model is needed, make one well-packed call do more work: provide the plan, compact evidence table, conflict list, and explicit decision questions. Avoid separate strong calls for each source unless the source itself is unusually ambiguous or central.

Do not pass the expected answer to discovery, contrary-evidence, source-read, or verification lanes. Give all lanes the same cutoff, source restrictions, and confidentiality rules. Use fresh contexts and independent first-pass searches so one agent’s unsupported assumption does not contaminate the others.

## Research packet

Require each lane to write one JSON packet at its unique manifest path. The human-readable shape is:

```text
Lane:
Lane ID:
Stage:
Question and scope:
Cutoff:
Terminal status: completed / partial / failed / blocked
Exit reason:

Sources:
- Source ID:
  Canonical citation/title:
  URL or local path:
  Publisher/court and date/version:
  Source type:
  Source role: direct_answer / assumed_baseline / method_or_process_only / boundary_or_transition / contrary_example / adjacent_domain_analogy / historical_background / later_interpretation / scholarly_analysis / factual_record
  Coverage cells:
  Distinct contribution:
  Claim IDs supported or opposed:
  Relevant passage or data:
  Location/pinpoint:
  Reliability or limitation:
  Verification: direct / partial / lead only

Preliminary pattern or conflict:
Gaps and follow-up queries:
Confidence: high / medium / low
```

The JSON packet must contain `lane_id`, `stage`, `status`, `exit_reason`, `sources`, `claims`, `gaps`, and `confidence`. Reject packets whose lane ID, stage, or registered path differs from the manifest, or that contain conclusions without source locations. “Not found,” “uncertain,” and “needs lead review” are valid results. A failed or blocked lane may omit a packet only when `lane-finish` records the terminal reason.

Cap packets by tokens or characters. Include only the passage needed to support the claim, a short context window when necessary, and one limitation. Store the full source locally or by reference rather than repeating it in every packet.

## Merge and verify

The lead agent should:

1. merge and deduplicate source records;
2. resolve conflicting metadata;
3. independently open the sources behind material claims;
4. compare sources for contradiction, stale information, incentives, and scope;
5. run targeted follow-up searches;
6. preserve discarded or weak sources in notes when they explain a decision; and
7. write the report only after the evidence table is stable.

The lead alone merges packets into the shared claim and source ledgers. Workers never edit shared ledgers. Validate packets and manifest state before using their findings; a worker completion message is not evidence that its packet is present or well formed.

Before synthesis of a literature, policy, market, historical, or scholarly question, run a central-source omission check. Compare the ledger with the bibliography and citing works of the closest direct source; search the exact phenomenon with the relevant actor or institution; inspect tables of contents or headings for candidates that abstracts underspecify; and promote the best candidates to full text. If no directly responsive work is found, preserve the searches and access limits rather than inferring absence from adjacent-source abstracts.

Subagent agreement is not corroboration. Corroboration requires independent sources or direct verification. Trace syndicated reporting, copied statistics, common datasets, and citation chains to their origin before counting them as independent support.

Use a canonical-source cache keyed by normalized URL/path and content hash. Reuse verified metadata and excerpts across lanes. If the source changed, invalidate the cached verification and record the new version.

## Mandatory verification wave

For focused work, the lead may directly open and verify every material claim-source link. For standard work, assign fresh-context `research-balanced` lanes so every material claim and every citation used for it receives independent source-support review. Run `research-mechanical` lanes separately for metadata, dates, versions, quotation matching, URLs, duplicate origins, and ledger structure.

For deep work:

1. independently verify every material claim-source link against opened source text;
2. select the five to eight highest-risk load-bearing claims by importance, ambiguity, conflict, source weakness, and effect on the conclusion;
3. assign two independent fresh-context `research-balanced` votes to each selected claim when the source is independently accessible;
4. stop at two when both votes support the calibrated claim; add one tie-breaker when they split or include uncertainty; use three votes for every selected claim only under an accepted `verification_quorum=triple` plan;
5. treat two materially adverse votes as a verification failure; the lead must resolve the source directly, narrow the claim, or mark it disputed;
6. treat split votes as a lead-review trigger, not as automatic corroboration; and
7. run at most one `research-critic` over the provisional synthesis plus claim ledger, source ledger, coverage matrix, verification packets, conflicts, and prior-report delta.

Each voter packet must give `supported`, `adverse`, or `uncertain` for its `vote_group`. Record every split, uncertain, or two-adverse result in `verification-resolution.json` with the lead's disposition, basis, and source IDs. The critic tests synthesis and claim calibration; it does not substitute for source opening, quotation checks, or proposition verification. Three agents repeating the same source error are not independent support.

## Budgets and stopping

Set budgets before fan-out: maximum rounds, sources, lane calls, wall time, and output tokens. Stop a lane when it has exhausted its assigned search family, reaches diminishing returns, or cannot access the required source. Use remaining budget for gaps and contrary evidence rather than endless expansion of already-covered themes.

For expensive API-backed runs, show the planned profile, model, reasoning effort, and expected call pattern before starting. Prefer local extraction and lower-effort profiles for routine work, and reserve high/xhigh calls for the small number of decisions that change the report.

Use risk-triggered escalation for the evidence-bundle critic. Invoke it only when the question is high-stakes, central sources conflict, the conclusion depends on an ambiguous passage, the user requests exhaustive coverage, or the audit finds an unsupported material claim. The mandatory standard/deep verification wave is not optional merely because a critic is unnecessary.

Apply the detailed circuit breakers in [anti-spiral-controls.md](anti-spiral-controls.md) to every lane and subprocess.
