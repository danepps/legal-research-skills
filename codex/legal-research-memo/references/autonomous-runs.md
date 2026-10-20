# Autonomous Legal Research Runs

Use this protocol for a completed standard or deep memo that may span many tool calls, context windows, or sessions. It supplies operational persistence; the main skill and specialized references continue to control legal analysis.

## Contents

1. Execution state
2. Run artifacts
3. Checkpoints and resume
4. Completion gates
5. Failure recovery
6. Exit states
7. CLI integration

## Execution state

Advance through this state machine:

`frame -> research -> verify -> synthesize -> draft -> audit -> deliver`

Do not wait for approval between ordinary phases after the user requests a completed memo. A progress update informs the user; it is not a permission gate. Pause only for a material scope decision, required authorization, confidentiality problem, or unavailable indispensable source.

Before changing phase, record what finished, what remains, the next concrete action, and any changed assumption or limit. Never mark a phase complete merely because its budget expired.

## Run artifacts

Use a dedicated hidden, project-local run directory. Default to `<project>/.codex-memo/runs/<run-id>/`; keep all operational artifacts there and publish only the requested completed memo deliverable or deliverables outside it. Initialize it with:

```bash
python3 <skill-dir>/scripts/init_research_run.py \
  --question "QUESTION" --mode doctrinal --effort standard \
  --jurisdiction "JURISDICTION" --cutoff YYYY-MM-DD \
  --output-format md \
  --memo-path "../../../topic-short-name-YYYY-MM-DD.md"
```

Run the initializer from the project root or pass `--project-dir PROJECT`. Omit `RUN_DIR` to use the unique hidden default. Pass an explicit hidden `RUN_DIR` only when resuming an established project convention.

Maintain these core files:

```text
run/
├── manifest.json
├── events.jsonl
├── claim-ledger.jsonl
├── source-ledger.jsonl
└── quantifier-audit.jsonl      # schema v4+; may be empty when the final scan has no hits
```

Add plans, notes, cached sources, drafts, and audit files only when useful. The manifest records status, phase, next action, completed phases, assumptions, unresolved issues, blockers, budgets, actual or estimated usage when exposed, evidence-backed completion gates, provenance, and artifact locations. Keep research evidence in the ledgers rather than inflating the manifest. The initializer records a run ID, producer, skill hash, and an available session ID; never invent unavailable provenance. Do not expose the run directory, ledgers, packets, logs, audits, or intermediate drafts in a visible project folder.

New runs use schema version 6. Give each claim a stable ID, proposition, machine-readable claim type (`holding_rule`, `doctrinal_synthesis`, `factual_historical_inference`, `cross_doctrinal_analogy`, or `normative_proposal`), `claim_strength` (`existence`, `illustrative`, `comparative`, `frequency`, `priority`, or `universal`), `coverage_cells`, importance (`dispositive`, `material`, `supporting`, or `contextual`), status, and supporting/adverse source IDs. Add a nonempty `coverage_protocol` to frequency, priority, and universal claims. Before prose, map the planned dispositive/material claims to memo sections and analytical roles. After the final draft, set `included_in_memo` on every claim; each included dispositive/material claim must have `memo_section`, one or more `analysis_roles`, and a short `draft_anchor` that occurs exactly once in the final memo. A dispositive claim may not be omitted.

Give each source a stable ID, citation, location, authority level, verification status, pinpoint, claim IDs, `coverage_cells`, `source_role`, `classification_status`, `precedential_effect`, and `distinct_contribution`. Use the exact source-field values in [source-protocol.md](source-protocol.md). Schema-v2 through schema-v5 runs remain valid under their original rules, but do not downgrade a new run to avoid the additional checks.

For a standard or deep scholarly/hybrid run, record an event named `direct_source_search` after searching the direct-answer core. The event detail should identify the exact-question and close-variant searches, the closest work’s references and citing works, likely direct candidates promoted to full text, and material access limits. If directly verified `direct_answer` sources exist, cite at least one of them in the `direct_source_audit` gate evidence. If none were found, say so in the gate note and preserve the bounded search record; the gate tests that the search occurred, not that the literature must exist.

For standard and deep runs, declare each planned coverage cell during framing:

```bash
python3 <skill-dir>/scripts/checkpoint_run.py RUN_DIR \
  --phase frame --event "Declared planned coverage" \
  --coverage-cell issue-property-definition \
  --coverage-cell epoch-1897-1936
```

Use short stable IDs. A ready schema-v3-or-newer standard or deep run requires every declared cell to appear in a material claim and in at least one directly verified source.

After the final deliverable is written, generate the schema-v4-and-newer quantifier audit template:

```bash
python3 <skill-dir>/scripts/quantifier_audit.py DELIVERABLE \
  --output RUN_DIR/quantifier-audit.jsonl --replace
```

The script scans Markdown, text, DOCX, or PDF deliverables in document order for `first`, `earliest`, `only`, `settled`, `overwhelmingly`, `most`, `always`, and `never`. It assigns stable-in-that-version occurrence IDs (`Q1`, `Q2`, and so on), plus the line and excerpt. Resolve every row in exactly one of two ways:

- set `claim_id` to a claim whose `claim_strength` is `frequency`, `priority`, or `universal` and whose `coverage_protocol` is nonempty; or
- set `waiver` to a concise occurrence-specific reason, such as quoted source language, a case title, or non-thesis usage.

Leave the other field empty. Regenerate and re-review the audit after any deliverable edit because the validator rejects stale hit IDs, terms, lines, or excerpts.

## Checkpoints and resume

Checkpoint after framing, each research lane, verification, synthesis, draft completion, and audit; also checkpoint before a likely context/tool limit or external dependency. Use `scripts/checkpoint_run.py`; the model supplies the phase and event text but never writes a timestamp or rewrites `events.jsonl` or `updated_at` manually. For example:

```bash
python3 <skill-dir>/scripts/checkpoint_run.py RUN_DIR \
  --phase research --event "Completed controlling-authority search" \
  --complete-phase frame --next-action "Verify the dispositive cases"
```

Use the same script to record artifacts, gates, and actual or estimated usage. Label estimates as estimates; when usage is not exposed, leave it `unavailable` rather than inventing numbers.

On resume:

1. Read `manifest.json` and the last events.
2. Validate the ledgers and artifact paths.
3. Reopen only the sources needed for the next decision.
4. Reuse directly verified material unless its currentness or content may have changed.
5. Continue from `next_action`; do not repeat completed searches merely to rebuild context.

Run `validate_research_run.py RUN_DIR` for checkpoint integrity during research. Pending coverage and final claim-to-prose mapping do not make an otherwise valid pre-draft checkpoint fail. The validator enforces those completion checks with `--require-ready`, when the run is marked `complete`, or when the respective completion gate is marked `pass`; do not mark `draft_claim_map` passed before the final memo exists. Missing or unreadable required logs remain validation errors. A disputed material claim still requires directly verified supporting or adverse evidence.

If state and artifacts conflict, prefer the underlying verified source, repair the manifest, record the repair, and continue.

## Completion gates

Before delivery, mark each gate `pass`, `not_applicable`, or `blocked` with a short note. A `pass` also requires one or more resolvable evidence pointers in the form `source:ID`, `claim:ID`, `event:NAME_OR_PHASE`, or `artifact:KEY`:

- `controlling_law`: governing text and controlling authority were checked.
- `currentness`: later treatment and current text were checked through the cutoff.
- `adverse_authority`: the strongest contrary authority and terminology were searched.
- `planned_coverage`: every material declared coverage cell has a mapped material claim and directly verified source; any remaining empty cell is disclosed and prevents a `complete` result.
- `direct_source_audit`: for schema-v5-and-newer standard/deep scholarly or hybrid runs, the direct-answer core was searched and omission-checked before adjacent literature was treated as the best available answer. Pass with `event:direct_source_search` and, when one exists, a directly verified `source:ID` whose role is `direct_answer`. This gate is non-waivable for those runs.
- `quantifier_audit`: the final deliverable was deterministically scanned and every trigger occurrence maps to a protocol-backed frequency/priority/universal claim or an explicit waiver. This gate must be `pass`, even when the scan finds zero hits; cite `artifact:quantifier_audit` as evidence.
- `draft_claim_map`: for schema-v6 standard/deep work, the final memo—not a provisional draft—has a machine-checked map from every included dispositive/material claim to a unique exact anchor, memo heading, analytical role, and ledger support. This gate is non-waivable; cite `artifact:memo` as evidence.
- `material_claim_support`: every dispositive/material claim has verified support and a usable pinpoint; frequency, priority, and universal wording also has a documented coverage protocol or has been narrowed.
- `citation_audit`: citations and quotations match the relied-on sources.
- `limitations_disclosed`: material factual, source, jurisdictional, methodological, and access limits appear in the deliverable.

Set gates through `checkpoint_run.py`, for example `--gate currentness=pass --gate-evidence currentness=source:S4,artifact:currentness_log --gate-note currentness="Later treatment checked through cutoff"`. Run `python3 <skill-dir>/scripts/validate_research_run.py RUN_DIR --require-ready` before marking the run complete. The validator checks schema consistency, evidence pointers, event chronology, and readiness; the lead remains responsible for substantive legal judgment.

After validation, append the final Topic / Date / By / Production details block required by SKILL.md to the canonical Markdown memo and publish it in the project’s AI Memos folder (unless the user specified otherwise). Record the exact lead model, local generation timestamp, elapsed wall-clock duration, and aggregate runtime-reported tokens across the lead and worker/verifier sessions. Never estimate tokens; if exact usage is unavailable, preserve the field and disclose that the runtime did not expose it. Generate a DOCX only when the user requests it, a downstream workflow requires it, or Word-specific review materially helps. Use one direct Pandoc conversion with minimal or no custom styling, then run `scripts/verify_docx_ooxml.py` and inspect the extracted text for synchronization. Never launch LibreOffice or any helper that launches it, and never use DOCX-to-PDF rendering. Do not delay Markdown publication or retry a failed conversion. If a structurally verified DOCX is produced, use identical provenance values in both formats and disclose that visual layout was not rendered.

## Failure recovery

- Retry a transient failure once when the expected value justifies it.
- Try an authorized official mirror, docket, reporter, archive, database, or supplied local copy when the preferred source fails.
- Downgrade verification status and record the affected claim when direct verification remains impossible.
- Continue unaffected claims and lanes; one unavailable source does not end the run unless it is indispensable.
- After repeated no-progress searches, stop that search family, record the exact coverage gap, and spend remaining effort on the claim most likely to change the answer.
- Never replace unavailable authority with an invented citation, quotation, pinpoint, holding, or negative-research conclusion.

## Exit states

- `complete`: every applicable gate passed and the requested deliverable was produced.
- `complete_with_limits`: a useful deliverable was produced, but one or more disclosed gates or material questions remain blocked.
- `needs_input`: a material user choice prevents responsible continuation.
- `source_unavailable`: an indispensable source could not be accessed or verified.
- `budget_exhausted`: the run reached an authorized hard limit before a responsible deliverable could be completed.
- `failed`: an execution error prevented a reliable deliverable.

Do not return only a plan or ledger when a useful memo can still be completed. For noncomplete exits, preserve the checkpoint and state the precise condition needed to resume.

## CLI integration

Use `deep-research` for persistent budgets, search logs, caching, watchdogs, and research-lane orchestration. Preserve its claim/source IDs during handoff. Apply this skill to authority hierarchy, holdings and dicta, currentness, legal interpretation, pinpoints, adverse authority, synthesis, and the final audit. Keep one lead responsible for the conclusion and final memo.
