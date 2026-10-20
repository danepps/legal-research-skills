# CLI Interface Design

## Contents

- Deterministic run helper and lane schema
- Inputs and interactive behavior
- Run artifacts and exit states

This is the host-facing interface for a thin CLI wrapper or Codex terminal command. Adapt unsupported flag names to the host environment, but preserve the behavior and artifact contract. Use the bundled deterministic helper for run state and validation; it does not perform retrieval or synthesis itself.

## Deterministic run helper

Use these commands inside the hidden run directory workflow:

```text
python scripts/research_run.py init RUN_DIRECTORY --request REQUEST.json
python scripts/research_run.py lanes-init RUN_DIRECTORY --lanes DISCOVERY-LANES.json
python scripts/research_run.py lanes-add RUN_DIRECTORY --lanes READ-OR-VERIFY-LANES.json
python scripts/research_run.py lanes-next RUN_DIRECTORY
python scripts/research_run.py lane-start RUN_DIRECTORY LANE_ID
python scripts/research_run.py lane-followup RUN_DIRECTORY LANE_ID --reason REASON --expected-gain GAIN
python scripts/research_run.py lane-finish RUN_DIRECTORY LANE_ID --status completed --output packets/STAGE/LANE_ID.json
python scripts/research_run.py budget-expand RUN_DIRECTORY --new-lane-limit N --reason REASON --evidence-gain GAIN
python scripts/research_run.py checkpoint RUN_DIRECTORY --event source_added --lane primary --usage '{"tool_calls":1,"sources":1}'
python scripts/research_run.py resume RUN_DIRECTORY
python scripts/research_run.py validate RUN_DIRECTORY [--output VALIDATION.json]
```

`init` refuses to overwrite an existing run, injects conservative default budgets, and requires accepted plans for deep runs. `lanes-init` and `lanes-add` validate lane IDs, stages, roles, dependencies, fresh-context settings, packet ownership, stage caps, and the current lane allocation. `lanes-next` returns only dependency-ready lanes from the earliest ready stage. `lane-start` counts every initial worker turn or retry against the fixed interaction ceiling. `lane-followup` authorizes and counts one bounded repair or continuation, with one allowed per lane. `budget-expand` unlocks the single bounded lane expansion only after a productive lane has finished; it cannot raise interaction or follow-up ceilings. `lane-finish` validates and registers completed or partial packets, including any output-character cap, or records a failed or blocked reason. `checkpoint` updates measured non-worker usage; worker turns cannot be entered manually. `validate` also reconciles worker starts and follow-ups with manifest accounting. Retrieval, native subagent calls, source promotion, worker termination, and substantive judgment remain the lead agent's responsibility.

A lane input file contains `{"lanes":[...]}`. Each lane requires `lane_id`, `stage`, `task`, and `role`; it may add `dependencies`, `claim_ids`, `coverage_cells`, `vote_group`, `max_attempts`, `max_followups`, `budget`, and `required`. The helper supplies `fresh_context=true`, `status=pending`, attempts, follow-up counts, timestamps, and the default output path `packets/<stage>/<lane-id>.json`. Setting `fresh_context=false` is rejected. For deep adaptive review, create two verification lanes with the same high-importance claim ID in both `claim_ids` and `vote_group`; add a third only after a split or uncertain pair. Use three initial lanes only when the accepted request selects `verification_quorum: "triple"`.

A completed or partial packet must be a JSON object with `lane_id`, `stage`, matching `status`, `exit_reason`, arrays named `sources`, `claims`, and `gaps`, and `confidence` set to `high`, `medium`, or `low`. Source entries should follow the source-ledger vocabulary. Every completed verification packet must contain exactly one result per assigned `claim_id`, with `verdict` equal to `supported`, `adverse`, or `uncertain`; include the source locations and basis for that result. A partial packet may leave assigned claims unreviewed, but only actual valid results count toward verification coverage. A quorum packet must contain exactly one result for its `vote_group`. Two supporting adaptive votes finish the group; a split or uncertain pair requires a third; two adverse votes require lead resolution. If a completed deep group is split, uncertain, or has at least two adverse votes, record the lead's source-based disposition in `verification-resolution.json`; allowed dispositions are `confirmed_after_lead_review`, `narrowed`, `disputed`, and `removed`.

Completion validation rejects dangling claim/source references even when the other ledger is absent or empty. A `complete` run must contain source records, and each material claim must have directly verified supporting evidence (`direct` or `verified` source status); a disputed claim may instead rely on directly verified contrary evidence. Material claims marked `stale` or `unverified` prevent `complete`. With `complete_with_limits`, disclosed evidence or verification gaps produce warnings and require `unresolved.md`; malformed records and dangling references still fail. Cutoffs must be real calendar dates, budgets and measured usage must be finite nonnegative numbers, and deep initialization requires the recorded authorization basis as well as `plan_accepted=true`.

## Inputs

Support a free-text question or a brief file. Useful options include:

```text
research QUESTION
research --brief brief.md
  --sources PATH[,PATH...]       local files or directories
  --sites DOMAIN[,DOMAIN...]     allowed or prioritized domains
  --apps NAME[,NAME...]          authorized read-only connectors
  --cutoff YYYY-MM-DD
  --audience AUDIENCE
  --format md|md,docx|docx|pdf|json   default: md; DOCX is an optional derivative
  --output RUN_DIRECTORY         default: hidden project-local .codex-memo/runs/RUN_ID
  --depth focused|standard|deep
  --budget low|standard|deep
  --max-rounds N
  --max-sources N
  --max-deep-reads N
  --max-packet-tokens N
  --max-context-tokens N
  --max-critic-calls N
  --max-tool-calls N
  --max-searches-per-lane N
  --max-open-pages N
  --max-wall-time MINUTES
  --max-retries N
  --max-fanout N                  automatic: focused 2, standard 8, deep 24
  --absolute-fanout N             fixed ceilings: focused 2, standard 12, deep 32
  --max-worker-interactions N     defaults: focused 3, standard 12, deep 36
  --max-followups N               defaults: focused 1, standard 4, deep 8
  --verification-quorum adaptive|triple  default: adaptive
  --reserve-audit-percent N
  --model-tier fast|balanced|strong
  --worker-profile PROFILE       override the mapped Codex worker profile
  --critic-profile PROFILE       override the selective critic profile
  --critic auto|off|required
  --budget-expansion lead-only|off
  --cache-dir PATH
  --trace-cost
  --plan-only
  --accept-plan
  --resume RUN_DIRECTORY
  --no-web
```

Do not imply that every environment supports every option. If a requested source or connector is unavailable, report the limitation before research begins.

Map `fast` to `research-mechanical`, `balanced` to `research-balanced`, and `strong` to the parent lead session by default. Use `research-critic` only through `--critic required` or a documented risk trigger. If named profiles are unavailable, disclose that routing was advisory rather than enforced.

## Interactive behavior

At startup, print:

1. the normalized question;
2. scope and cutoff;
3. source permissions;
4. proposed subquestions and lanes;
5. model, reasoning/profile, and budget tier; and
6. expected artifacts.

Pause for a materially missing scope decision, unapproved expense/external action, or requested plan review. Every deep request passed to `init` must record `plan_accepted: true` and a truthful `plan_authorization_basis`; an explicit deep-research instruction within a stated or already accepted scope and budget can supply that authorization without another question. Do not infer acceptance of an undisclosed expansion. A focused or ordinary standard run may print the compact plan and proceed. During a long run, emit checkpoint events such as `plan_ready`, `lane_started`, `lane_followup_authorized`, `budget_expanded`, `source_added`, `conflict_found`, `synthesis_started`, `audit_complete`, and `report_written`.

## Run artifacts

Use a hidden, project-local per-run directory such as `<project>/.codex-memo/runs/<run-id>/` to make research resumable and inspectable. Create only artifacts useful for the selected depth. Never leave this bundle, its packets, or its logs in a visible project folder; after audit, publish the completed Markdown and only those optional derivatives the user requested.

**Focused minimum:**

```text
run/
├── request.json
├── run-state.json
├── lane-manifest.json          # when any subagent is used
├── source-ledger.jsonl
├── report.md
└── unresolved.md             # only when material gaps remain
```

**Standard:** add `plan.md`, `search-log.md`, `claim-ledger.jsonl`, `evidence-table.md`, and `cost-report.json`.

**Deep or orchestrated:** use the full bundle when each file carries information:

```text
run/
├── request.json
├── run-state.json
├── lane-manifest.json
├── plan.md
├── events.jsonl
├── search-log.md
├── claim-ledger.jsonl
├── source-ledger.jsonl
├── evidence-table.md
├── conflicts.md
├── unresolved.md
├── authority-delta.md         # optional reconciliation with prior local reports
├── quantifier-audit.md        # optional frequency/priority/universal claim checks
├── verification-resolution.json # required when deep quorum results are contested
├── synthesis-decisions.md     # optional provisional-to-calibrated thesis record
├── cost-report.json
├── watchdog.json
├── validation.json          # only when a persisted validation record is useful
├── report.md
├── packets/
│   ├── discovery/
│   ├── read/
│   ├── gap_fill/
│   ├── verification/
│   ├── mechanical_audit/
│   └── critique/
└── sources/                 # optional cached or copied source material
```

Never overwrite an existing run. Resume it in place or create a new run; replacement requires a separately authorized archival or deletion step. Do not emit empty placeholder artifacts; `init` creates only `request.json` and `run-state.json`. Create the three optional deep-scholarly audit files only when they preserve material decisions that are not already clear in the ledgers or report. Store timestamps, cutoff, tool/source identifiers, verification status, cache hits, and budget events. Do not cache confidential source material unless the user authorized local persistence. If a source is reused, identify it by canonical URL plus content hash so the run does not pay to retrieve or summarize the same material repeatedly.

## Exit states

Use clear exit states rather than silently producing a weak report:

- `complete`: planned coverage met and audit passed;
- `complete_with_limits`: useful report produced with documented gaps;
- `needs_input`: scope, source permission, or missing file blocks responsible research;
- `source_unavailable`: a required source or live-search capability was unavailable;
- `budget_exhausted`: search or model budget ended before coverage criteria were met; and
- `failed`: an execution error prevented a reliable report.

The report should include the exit state and the next best action. A completed visible report or memo must end with the required Codex production block: topic, local date, exact lead model, elapsed run time through the completed audit, aggregate runtime-reported tokens across the lead and all workers or critics, subagent roles, and material limits. Never estimate token usage; disclose when the runtime did not expose an exact total. For a requested DOCX, use OOXML structural verification plus normalized Markdown-to-DOCX text coverage and state that visual layout was not rendered; never launch LibreOffice or a DOCX-to-PDF renderer.
