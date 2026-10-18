---
name: deep-research
description: Run a resumable, source-grounded investigation from the CLI or a Codex terminal workflow. Use for broad, current, external, literature, policy, technical, market, empirical, systematic/scoping-review, legal, historical, comparative, or scholarly questions that need explicit scope, iterative search, evidence tracking, contradiction checks, citations, budgets, reusable artifacts, and coverage-directed parallel orchestration. Use local files, live web search, permitted apps or MCP sources; do not imply that this skill reproduces the ChatGPT web app’s private backend or UI.
---

# Deep Research

## Purpose and boundaries

Recreate the useful research behavior of Deep Research in a terminal workflow: plan before searching, gather and evaluate many sources, revisit the question as evidence accumulates, preserve an audit trail, and produce a cited report. Treat this as a portable orchestration protocol, not as the ChatGPT web app itself. Capabilities depend on the CLI’s available web, file, app, MCP, and model tools.

For current or external facts, require live web access or an authorized connected source. If it is unavailable, say that the run can only cover the supplied local corpus and do not present the result as current or comprehensive.

## Run contract

Before research begins, determine:

- the goal, audience, deliverable, and desired depth;
- the main question and subquestions;
- jurisdictions, markets, periods, versions, or populations in scope;
- source restrictions, trusted domains, uploaded/local files, and authorized apps;
- a research cutoff date and a proportional search/iteration budget;
- a cost/quality budget, including source, lane, context, and critic caps;
- whether the anticipated answer requires existence, illustrative, comparative, frequency, priority, or universal claims, and what coverage could support that strength;
- confidentiality, privilege, licensing, and data-handling constraints; and
- the output directory and formats requested.

Choose the lightest run profile that can answer responsibly:

- **Focused:** one or two bounded questions, modest stakes, and a small source universe. Use one pass plus a contrary/currentness check and produce only the minimum artifacts.
- **Standard:** several subquestions, mixed source types, a recommendation, or a reusable report. Use a coverage matrix, coverage-directed parallel lanes when at least two independent cells exist, targeted follow-ups, and the standard artifact set.
- **Deep:** high-stakes or contested work, broad comparisons, systematic/scoping reviews, or a request for comprehensive coverage. Presume coverage-directed parallelism when the environment permits it. Use a reviewed protocol, explicit inclusion/exclusion criteria when relevant, multiple lanes, checkpoints, and a full audit trail.

Show a compact plan before all runs. Pause only for a materially missing scope decision, an unapproved expense or external action, or requested plan review. An explicit instruction to perform deep research within a stated or already accepted scope and budget supplies authorization; do not ask for it again. Require `plan_accepted=true` before initializing a deep run and record the actual authorization basis in `request.json` under `plan_authorization_basis`. Never set it merely because time passed, the work is high-stakes, or the lead silently chose an expensive budget. For an ordinary research request, use a proportional focused or standard run and proceed; seek approval only before a material expansion beyond that authorization. Support resume and checkpointing so an interrupted run can continue without silently repeating or losing the source ledger. Use `scripts/research_run.py` for deterministic run initialization, lane manifests, ready-queue inspection, lane attempts and packet registration, checkpoints, budget accounting, resume summaries, and artifact validation. The host-facing interface and artifact tiers are in [references/cli-interface.md](references/cli-interface.md).

Use the quality-preserving cost policy in [references/cost-control.md](references/cost-control.md). Preserve direct verification of central claims, primary-authority coverage where available, currentness for time-sensitive claims, and at least one contrary search. Save tokens by eliminating duplicate retrieval, oversized intermediate summaries, repeated full-source context, and critics that cannot change the conclusion.

Use the circuit breakers in [references/anti-spiral-controls.md](references/anti-spiral-controls.md). Every worker must have a hard budget envelope, a finite output contract, and a supervisor that can stop it. A worker that reaches a limit returns a partial packet and stops; it may not expand its own budget or recursively create more workers.

## Core workflow

### 1. Plan

Write a compact plan containing the question, subquestions, claim/coverage matrix, source strategy, search lanes, authority or quality rules, stop conditions, and expected outputs. For each material claim, record its intended strength (`existence`, `illustrative`, `comparative`, `frequency`, `priority`, or `universal`), the coverage needed to justify that strength, and material selection risks. A frequency, priority, or universal claim requires a documented coverage protocol; if the budget cannot support one, plan narrower wording. Use source restrictions exactly as supplied. Prefer primary and authoritative sources; use secondary sources for context, terminology, and leads.

For literature, policy, historical, market, and scholarly questions, declare a **direct-answer core** before broader context: the exact phenomenon or relationship named by the user; sources whose title, abstract, table of contents, headings, or full text directly address it; and the closest terminology variants. Keep this coverage cell distinct from adjacent-domain analogies and general background. Agent count and total source count do not establish coverage if this cell is empty.

Before duplicating external retrieval, inspect relevant prior local reports and research packets. Extract their thesis, authority/source universe, unresolved issues, and material conflicts into a compact authority/claim delta. Treat prior prose as a map rather than evidence, and verify any proposition reused in the new report.

Select the research method before searching. Use [references/research-methods.md](references/research-methods.md) for systematic or scoping reviews, empirical and quantitative claims, historical or archival work, comparative research, and fast-moving events. Apply only the modules relevant to the question.

### 2. Discover broadly but cheaply

Run query families appropriate to the selected method: the user’s exact formulation, close title/abstract formulations, plain-language terms, technical or historical synonyms, named entities, distinctive phrases, controlled vocabulary where available, source-type searches, citation trails, and contrary or skeptical formulations. For a literature question, search the direct-answer core first and citation-chase the closest work in both directions before spending substantial budget on adjacent fields. Use snippets, titles, metadata, tables of contents, and short passages to discover candidates; do not spend full-document context on every result. Promote a candidate to full-text review when its title, abstract, headings, citations, or snippets indicate that it directly treats a central question. Search local files and permitted connected sources as well as the public web. Start broad enough to map the landscape, then narrow to the best sources. Do not treat snippets, rankings, or generated summaries as evidence.

### 3. Fan out when useful

Split lanes only after the plan is clear. A focused run normally stays single-agent. For standard and deep runs, use the smallest fan-out that covers genuinely independent cells; do not create a lane merely because a worker slot exists. Assign workers by disjoint coverage cell, source class, period, jurisdiction, or adversarial function—never as duplicate generalists. Reserve one lane for the direct-answer core and add separate primary-source, currentness, contrary, historical, data, or local-extraction lanes only when the coverage matrix makes them material.

Start with automatic lane allocations of **2 focused, 8 standard, and 24 deep** and absolute lane ceilings of **2, 12, and 32** respectively. These are limits, never targets. A standard or deep run may unlock one lane expansion only after a completed productive wave, using `budget-expand` with a concrete remaining gap and expected evidence gain; never expand the fixed worker-interaction or follow-up ceiling. For deep runs, apply stage ceilings of 5 discovery, 12 read, 3 gap-fill, 20 verification, 2 mechanical-audit, and 1 critic lane; the 32-lane total still controls. Let host concurrency determine wave size. The lead may add a lane only for a documented empty cell, promoted source, unresolved conflict, or verification failure; workers may not spawn recursively.

Run subagents in deterministic stage waves: discovery; lead-side deduplication and triage; promoted-source reads; bounded gap fill; provisional synthesis; mandatory verification; evidence-bundle criticism when required; calibrated final synthesis; audit. Do not cross a barrier until required predecessor lanes have completed or returned a recorded partial packet. Give every worker a unique lane ID and a unique packet path under `packets/<stage>/`; workers may write only their assigned packet and may not edit shared ledgers or drafts. If a worker is read-only, have it return the packet JSON and let the lead persist it; do not change its sandbox. Call `lane-start` before every initial worker turn or retry, and call `lane-followup` before every repair or continuation turn; both consume the fixed worker-interaction budget. Allow at most one follow-up per lane and one gap/repair wave. Spawn research, read, contrary, verification, and critic workers with `fork_turns="none"` unless a documented task-specific dependency requires inherited conversation. Pass only the normalized brief, lane scope, cutoff, permissions, budgets, dependency packet paths, and output schema; never pass the expected answer to an independent lane. Use the detailed model, budget, isolation, packet, and wave rules in [references/cli-orchestration.md](references/cli-orchestration.md).

Use fast or lower-cost models for bounded discovery, extraction, metadata, deduplication, and mechanical checks. Use stronger models for question refinement, source ranking, contradiction resolution, causal or legal interpretation, historiography, recommendations, and final synthesis. Never let a low-judgment subagent silently determine the conclusion.

When named Codex custom-agent roles or matching CLI profile files are available, enforce the tier rather than merely requesting cheaper behavior: use `research-mechanical` (low reasoning) for discovery metadata and mechanical audits; use `research-balanced` (medium) for collection, promoted-source reads, gap fill, contrary searches, and independent source-support verification; preserve the user's selected lead model and reasoning effort; and invoke `research-critic` (xhigh) once for a bounded fresh-context review of the evidence bundle when risk justifies it. Use only roles and models exposed by the current host. Treat these role names as examples of responsibilities, not portable model availability guarantees; record the effective role/model and any fallback. Do not rewrite global configuration to make a role exist. See [references/cli-orchestration.md](references/cli-orchestration.md).

### 4. Build the evidence record

Maintain two linked records:

- a **claim ledger** with claim ID, subquestion, coverage cell, importance, evidence needed, status, supporting and contrary source IDs, and confidence; and
- a **source ledger** with canonical location, title/citation, publisher or court, date/version, source type, source role, coverage cells, distinct contribution, relevant passage or data, supported claim IDs, reliability notes, and verification status.

Code source role with the shared canonical vocabulary: `direct_answer`, `assumed_baseline`, `method_or_process_only`, `boundary_or_transition`, `contrary_example`, `adjacent_domain_analogy`, `historical_background`, `later_interpretation`, `scholarly_analysis`, or `factual_record`. Domain skills may add separate classification or precedential-effect fields but should preserve these role values during handoff. Keep evidence packets compact: source metadata, the smallest passage or data needed for the claim, enough context to preserve qualifications, one limitation, and a confidence flag. Track whether claims are directly supported, indirectly supported, disputed, stale, or unverified. Deduplicate sources, trace apparently independent claims to their common origin, cache verified material when authorized, and preserve the strongest canonical link.

### 5. Iterate deliberately

After the first pass, inspect the claim and source ledgers for missing subquestions, empty coverage cells, unsupported high-importance claims, contradictory claims, source-quality problems, stale results, geographic, language, population, or version gaps, and overreliance on one source type. For literature and scholarly work, run a **central-source omission audit**: compare the ledger against the closest direct work’s references and citing works; search each central concept paired with the relevant actor or institution; and investigate any candidate whose metadata suggests a dedicated section. Do not conclude that a direct literature is absent merely because adjacent-source abstracts do not mention it. Either promote and read the best candidates or disclose the bounded search and remaining access limit.

Use remaining budget for the gap most likely to change the answer. Stop a lane after two consecutive calls add no new canonical source, material passage, coverage cell, contradiction, or verified correction. Run at most one targeted follow-up wave and stop when coverage criteria are met, high-impact conflicts are resolved or disclosed, or additional searching has low expected value; state which condition applies. Prefer a narrower, candid memo over consuming the reserve to preserve ambitious wording.

Before the calibrated final synthesis, run a verification wave. For focused work, the lead may directly verify every material claim. For standard work, require independent coverage of every material claim and every citation used for it, batching related claims into bounded packets when one verifier can open the same source once. For deep work, independently verify every material claim-source link and use an adaptive quorum for the five to eight highest-risk load-bearing claims: start with two fresh-context `research-balanced` votes; stop at two when both support the calibrated claim; add a third only when the first two split or include uncertainty; treat two materially adverse votes as a verification failure requiring lead resolution or narrower wording. Use blanket three-vote groups only when the accepted plan marks the run high-stakes enough to justify `verification_quorum=triple`. Record split, uncertain, and two-adverse groups in `verification-resolution.json` with the lead's disposition and source-based rationale. Run mechanical metadata, date, version, quotation, link, and duplicate checks separately. A `research-critic` may challenge the synthesis, but does not replace source-level verification.

### 6. Synthesize in two passes

For standard and deep scholarly runs, first write an evidence-rich provisional synthesis: state the strongest plausible thesis, organize the record that supports it, and identify anomalies or contrary evidence. Then perform a calibration pass that receives the provisional synthesis together with the claim ledger, source ledger, coverage matrix, conflicts, and prior-report delta. Test claim strength, selection effects, period or category boundaries, source roles, rival explanations, and uncovered cells against that evidence record; do not ask a draft-only critic to reconstruct source roles from prose. The final report should reflect the calibrated pass, not merely polish the provisional thesis.

Separate confirmed findings, interpretation, recommendations, and uncertainty. Resolve disagreements by source quality, directness, date/version, jurisdiction, methodology, or factual fit. Do not average conflicting sources into a false consensus. Explain why a source is persuasive and what would change the conclusion.

### 7. Audit and package

Check that every important claim has a usable citation, every named-source characterization is traceable to a citation and pinpoint, every citation supports the sentence written, dates and versions are correct, quotations are short and exact, contrary evidence is represented, apparently independent sources are genuinely independent, and confidence matches the evidence. For literature or scholarly reports, require the direct-source audit to identify directly responsive works or document the exact searches and access limits that found none. Audit `first`, `earliest`, `only`, `always`, `never`, `settled`, `overwhelmingly`, `most`, and equivalent frequency, priority, or universal language against the recorded protocol; downgrade unsupported wording instead of silently expanding the search. Enforce the chosen boundary policy in counts and period claims, and reconcile material differences from prior local reports. Record measured calls, effective role or profile, model, reasoning effort, cache hits, sources screened, sources deeply read, and budget exceptions. Record runtime-reported tokens exactly; if the runtime does not expose them, say `tokens unavailable (runtime did not expose exact usage)` and do not estimate. Preserve the artifacts required by the selected run profile; do not create empty or redundant files merely because the full schema supports them.

Keep all run artifacts under a hidden project-local path such as `<project>/.codex-memo/runs/<run-id>/`. Do not leave visible plans, ledgers, packets, audits, logs, cost reports, cached sources, or intermediate drafts. Publish the audited Markdown by default to `<project>/AI Memos/[topic]-[YYYY-MM-DD]-Codex-[exact lead model label].md`, using the user's local date after audit unless the user specifies another name or destination. Treat DOCX as an optional, nonblocking derivative and create it only when the user requests it or a downstream workflow requires it.

Put this production block at the very end of every completed report or memo, after the body, appendices, and all other substantive content:

```text
Topic: <report or memo topic>
Date: <YYYY-MM-DD in the user's local timezone>
By: Codex-<exact lead model label>
Production details: <aggregate runtime-reported tokens or the required unavailable statement; elapsed wall-clock time through audit; subagents and roles; material limits>
```

Include cached-input tokens when the runtime aggregate includes them. Never estimate or invent token usage; if exact usage is unavailable, write `tokens unavailable (runtime did not expose exact usage)`. Generate the date and final production values only after the content audit succeeds. An optional derivative must retain the same production values and pass its bounded format check before it is described as verified.

## Default report

Unless the user requests another format, produce:

1. Executive summary with the answer and highest-impact caveats.
2. Scope, method, sources used, and cutoff date.
3. Findings organized by subquestion or theme.
4. For standard or deep runs, an evidence table connecting claims to sources and reliability notes.
5. Contradictions, gaps, and unresolved questions.
6. Recommendations or next steps, if requested.
7. Canonical source list with citations or links.

Before publishing a run as `complete`, run `scripts/research_run.py validate RUN_DIRECTORY`; a failed validation requires repair or a disclosed non-complete exit state. For standard and deep runs, validation must also show that every required lane is terminal, every completed or partial lane has a valid registered packet, no stage dependency is unresolved, all worker starts and follow-ups reconcile with automatic interaction accounting, and the mandatory verification stage is represented. Treat the Markdown report as canonical and publish it when the research and content audit passes. If a DOCX is requested, use one direct Pandoc conversion with minimal styling, then run `scripts/verify_docx_ooxml.py DOCX --markdown MARKDOWN --output RECORD`. Require the verifier's normalized text-coverage check to pass and record that pagination and visual layout were not rendered. Never invoke `soffice`, `libreoffice`, `render_docx.py`, the documents skill, or any helper/runtime that launches LibreOffice; do not run a DOCX-to-PDF-to-image chain inside or outside the sandbox. A DOCX failure must not delay Markdown publication. Make the hidden evidence record reusable by a downstream skill. For a formal legal analysis or memo, hand the claim and source ledgers to `legal-research-memo` before final legal synthesis so holding, dicta, hierarchy, pinpoint, currentness, and specialized-method review can shape the deliverable.

## Safety and integrity

- Announce whether the run uses local/Codex tools, connected sources, or separately billed API calls before invoking an external API path.
- Do not transmit confidential, privileged, or nonpublic information to an external source without authorization; redact issue descriptions where possible.
- Do not claim exhaustive research, comprehensive coverage, or currentness without a recorded scope and search that support the claim.
- If a source cannot be opened or verified, label it as a lead and do not use it as sole support for a material claim.
- Keep primary-source quotations short and prefer paraphrase with a citation.
- Never launch LibreOffice, directly or indirectly. DOCX verification is limited to OOXML structure, XML parseability, extractable text, and normalized substantive synchronization with the canonical Markdown; disclose that pagination and visual layout were not rendered.
- For high-stakes legal, medical, financial, or regulatory decisions, present the report as research support and surface the need for qualified review.
