---
name: legal-research-memo
description: Research and write verified legal or scholarly memos, including doctrinal synthesis, historical research, literature reviews, and resumable investigations. Use for open legal questions or memo assignments; use find-cite for one proposition and cite-check for auditing an existing draft.
---

# Legal Research Memo

## Purpose

Turn an open-ended legal research request into an auditable research product. Use two modes:

- **Doctrinal mode:** answer what the law is, how a court is likely to decide, or how authorities apply to facts.
- **Scholarly mode:** explain how a legal idea, institution, doctrine, or category developed; map and evaluate the literature; reconstruct a historical or conceptual problem; or develop an original scholarly claim.

Treat neither mode as a collection of case summaries. In doctrinal mode, the central product is a defensible legal conclusion. In scholarly mode, it is a well-supported interpretation that makes its sources, method, historiography, and contribution visible.

## Choose the effort and deliverable

Use the lightest workflow that satisfies the assignment:

| Tier | Use when | Default product |
|---|---|---|
| Targeted | Narrow rule, source, citation, case synthesis, or update | Direct answer or short research note; verify the dispositive authority and adverse/currentness point |
| Standard memo | Several authorities or subquestions, fact application, prediction, or advice | Compact plan, authority/claim ledger, synthesis, counterargument, and audited memo |
| Deep/scholarly | High stakes, contested doctrine or history, broad literature/archive, comparative or empirical project | Research matrix, method-specific protocol, multiple source classes, explicit gaps, and full audit |

Do not create a full formal memo, authority table, or multi-agent plan when the user asked for a narrow answer and those artifacts would not improve reliability. Expand only for a material coverage gap, conflict, or requested format.

## Autonomous execution contract

When the user requests a completed memo or says to finish, continue through framing, research, verification, synthesis, drafting, audit, and delivery without waiting for approval at routine intermediate stages. Do not stop at a plan, outline, source list, research matrix, or provisional synthesis. Share concise progress updates without making continued work depend on a response.

Pause only when a missing choice would materially change the assignment, required access or authority is unavailable, confidentiality prevents safe research, a separately billed or external action needs authorization, or the user redirects the work. Otherwise make and label reasonable assumptions, record limitations, and proceed.

For standard or deep work that may cross turns, contexts, or tool limits, use [references/autonomous-runs.md](references/autonomous-runs.md). Initialize durable state with `scripts/init_research_run.py`, checkpoint only through `scripts/checkpoint_run.py` so timestamps are script-generated, and audit completion with `scripts/validate_research_run.py --require-ready`. For a large project needing explicit budgets, resumable search logs, or orchestrated lanes, use `deep-research` as the execution shell while this skill controls legal judgment and the final memo.

## Operating rules

- State the jurisdiction, court level, governing law, relevant date, factual assumptions, and research cutoff. If a missing detail would materially change the answer, ask for it; otherwise proceed with a clearly labeled assumption.
- Protect confidential and privileged information. Prefer local files and authorized sources. Do not upload confidential facts or documents to an external service merely to obtain a citation or summary.
- Never invent an authority, quotation, holding, pinpoint, docket number, procedural fact, or negative-research conclusion. If a citation or proposition cannot be verified, mark it for follow-up or omit it.
- Distinguish: binding authority, persuasive authority, commentary, party argument, judicial dicta, dissent, historical evidence, and the memo writer’s inference.
- Prefer synthesis over a case dump. Explain what each authority establishes, why it matters, how it bears on the question, and what limits its force.
- Report adverse authority and plausible counterarguments. Do not describe a search as exhaustive unless the search actually supports that characterization.
- When law may have changed, verify currentness as of the stated cutoff. Treat an old case, statute, regulation, or article as historical unless current authority confirms its continuing force.

## Multi-agent mode

Use the orchestration protocol in [references/subagent-orchestration.md](references/subagent-orchestration.md) when the assignment explicitly requests parallel research or when a standard/deep assignment has at least two independent, source-heavy coverage cells. Place a strong presumption on coverage-directed fan-out for deep scholarly and broad literature work when the environment permits it. Use at most 12 workers over the run, including queued workers but excluding the lead; treat 12 as a ceiling rather than a target, and keep targeted work single-agent. Keep a lead agent responsible for the research plan, claim and source ledgers, authority ranking, conflict resolution, thesis, final draft, and delivery audit. Do not let subagents independently produce the final memo.

Choose the lowest-capability/lowest-cost model that can reliably perform a bounded role. Use fast or lower-end models for source discovery, metadata capture, constrained extraction from supplied documents, duplicate detection, citation-format checks, and checklist review. Use a stronger model for ambiguous issue framing, interpretation of conflicting authorities, historiographical synthesis, thesis formation, counterargument, and final drafting. If the environment does not expose model selection, preserve this division by narrowing low-judgment prompts and routing substantive decisions back to the lead agent.

## Workflow

### 1. Frame the assignment

Start with a one-sentence restatement of the question and a compact scope statement. Identify:

- the precise legal issue and any embedded subquestions;
- the relevant facts, procedural posture, and facts that are unknown;
- jurisdiction, court, time period, and choice-of-law assumptions;
- whether the task is predictive, advisory, historical, originalist, descriptive, or advocacy-oriented;
- the requested depth, audience, format, and citation style; and
- whether the user supplied a source universe that should be treated as exhaustive or merely as a starting set.

Classify the project before researching. Use **scholarly mode** when the user asks for a law-review paper, article, dissertation chapter, monograph section, intellectual history, historiography, conceptual genealogy, theoretical intervention, or source-driven historical reconstruction. In scholarly mode, replace “what is the governing rule?” with the appropriate research problem: what changed, what persisted, what competing accounts exist, what evidence has been overlooked, or what claim can the sources support. If the project serves both a legal audience and a scholarly audience, state which mode controls each section.

For a standard or deep question, create a research matrix before drafting. Each row should contain a claim or subquestion, one or more stable coverage-cell IDs, its importance, machine-readable claim type (`holding_rule`, `doctrinal_synthesis`, `factual_historical_inference`, `cross_doctrinal_analogy`, or `normative_proposal`), intended claim strength (`existence`, `illustrative`, `comparative`, `frequency`, `priority`, or `universal`), the likely governing or best evidence, search terms and historical synonyms, supporting and adverse source IDs, and status: open, supported, disputed, or unresolved. Frequency, priority, and universal claims require a recorded coverage protocol or narrower wording. In scholarly or literature work, include a separate direct-answer coverage cell for sources that address the exact phenomenon or relationship named by the user; do not merge it into general background or an adjacent-domain analogy. Do not require a matrix for a targeted answer when a few verified authorities suffice.

When the autonomous-run protocol applies, initialize or resume the run before broad research. Treat the manifest as operational state, not as a substitute for the memo or source ledger.

### 2. Build the authority map

Search in this order for ordinary U.S. doctrinal work unless the assignment requires a different order:

1. The relevant constitutional text, statute, regulation, rule, or contract.
2. Controlling decisions from the highest relevant court.
3. Binding decisions from the relevant intermediate or trial court.
4. Persuasive decisions, including other jurisdictions and older cases.
5. Official historical materials, restatements, treatises, and law-review scholarship.
6. Briefs, practice guides, reputable summaries, and secondary web sources as leads or context—not as substitutes for primary authority.

For scholarly and literature work, use a parallel specificity order: (1) sources whose title, abstract, table of contents, headings, or full text directly address the exact question; (2) works cited by and citing the closest direct sources; (3) sources addressing a component of the question; and only then (4) adjacent-domain and general background literature. Search the user’s exact formulation and close variants before broadening. Promote candidates to full-text review when metadata or snippets indicate a dedicated treatment. A large adjacent bibliography does not compensate for an empty direct-answer core.

Select any specialized method before searching. Use [references/specialized-methods.md](references/specialized-methods.md) for statutory/regulatory/administrative, comparative/foreign/international, empirical/quantitative, and record- or fact-intensive litigation research. Use only the relevant module; do not apply every checklist to every project.

Search local project files first. For web research, use official court, government, legislative, or other authoritative sources when available. Read the source itself, not only a search-result snippet or headnote. For every material authority, record the full citation, court and date, relevant page or paragraph, proposition supported, authority level, source location, and whether the text and quotation were personally verified. For cases and legally operative sources, also record the source's role in the analysis and its precedential effect. Trace copied quotations and propositions back to their original source; agreement among sources that share an origin is not independent corroboration.

In multi-agent mode, give each researcher a disjoint coverage lane and the same cutoff, source rules, and return schema. For scholarly or literature work, reserve one lane for the direct-answer core and separate it from historical bibliography, adjacent literatures, adverse accounts, and citation verification. Require raw source locations and pinpoints so the lead agent can independently verify the result.

Use the source protocol in [references/source-protocol.md](references/source-protocol.md) for source ledgers, currentness, quotations, negative research, and conflicts among authorities.

When a CourtListener token is available, use `scripts/check_cite.py` to check case-citation existence before final audit. Record an API match only as `citation-only`; it does not verify a pinpoint, quotation, holding, characterization, or negative treatment. When the current force of a controlling or load-bearing case matters, `scripts/courtlistener_treatment.py "CITATION" --output RUN_DIR/currentness/CASE.json` may generate a bounded citing-opinion treatment-triage packet. Open and read every material hit. The packet is not a citator; no hits do not establish good law, and citation recency does not establish doctrinal force or dormancy.

### 3. Extract before synthesizing

For each important case or source, capture only what the deliverable needs:

- the question presented and procedural posture;
- legally material facts;
- the precise holding and the rule or test announced;
- whether the relevant proposition was decided, assumed, accepted only for argument's sake, reserved, or unnecessary to the judgment;
- the opinion's precedential effect, including majority, plurality, concurrence or dissent, summary disposition, or affirmance by an equally divided court;
- reasoning that is necessary to the result;
- dicta, separate opinions, party arguments, and historical claims, labeled as such;
- treatment of earlier or later authority;
- the strongest limitation, distinction, or adverse reading; and
- the source's distinct contribution to the analysis, such as a new rule, narrowing move, transition, corroboration, or rival account;
- a verified quotation or pinpoint for each proposition the draft will rely on.

Do not infer a broad rule from a case merely because its facts resemble the assignment. Check the disposition, the actual issue decided, whether the Court assumed or decided the relevant classification, and whether the language was necessary to the judgment. Do not treat a plurality, concurrence, dissent, summary disposition, or affirmance by an equally divided Court as a majority holding. When authorities conflict, explain the conflict by court hierarchy, jurisdiction, date, procedural posture, text, or factual distinction instead of averaging the rules together.

When relying on an adjacent doctrine, constitutional provision, jurisdiction, or historical regime, label the authority as analogical. State the proposition being transferred, explain why the transfer is warranted, and identify any difference that limits the analogy.

### 4. Analyze by proposition and subquestion

Organize the memo around the legal work the reader needs done. For each subquestion:

1. State the short answer.
2. State the governing rule or framework with the best authority.
3. Synthesize the authorities in a useful sequence—normally controlling rule, leading application, adverse or limiting authority, then application to the facts.
4. Explain the strongest counterargument and the response or remaining uncertainty.
5. Give a calibrated conclusion (for example, strong, probable, uncertain, or unresolved) and identify what fact or authority could change it.

When the doctrine contains multiple stages, elements, or alternative routes to protection, map them separately before synthesizing. Do not use authority addressing one stage to establish another, and do not convert contextual considerations into universal elements unless the court did so. Distinguish the court's stated test from the memo's synthesis of the cases.

Use the special method in [references/historical-and-general-law.md](references/historical-and-general-law.md) for historical, originalist, common-law, or “general law” questions. Use the memo architecture in [references/memo-architecture.md](references/memo-architecture.md) for the default structure and house style.

For a purely scholarly project, also use [references/scholarly-research.md](references/scholarly-research.md). Do not force a scholarly argument to end in a single predictive answer. Instead, make the thesis, historiographical position, evidentiary basis, rival interpretations, and limits of the claim explicit.

For deep scholarly work, synthesize in two passes. First produce an evidence-rich provisional account that states the strongest plausible thesis and the anomalies it must explain. Then give a separate calibration pass the provisional account plus the research matrix, claim and source ledgers, conflict table, and prior-memorandum delta. Test claim strength, selection effects, period boundaries, case/source roles, precedential effect, rival explanations, and uncovered coverage cells against that record. Draft the final thesis from the calibrated pass rather than merely polishing the provisional account.

Prioritize verification by consequence: controlling rule and dispositive application first, strongest adverse authority second, then supporting and contextual material. Source count is not coverage; the central proposition must be supported at the level of generality written. Before synthesizing scholarly or literature work, perform a central-source omission audit: compare the ledger with the closest direct source’s references and citing works, search each central concept paired with the relevant actor or institution, inspect headings or tables of contents when abstracts are underspecific, and record why any apparently direct candidate was excluded or left unread. Do not infer that book-specific, doctrine-specific, institution-specific, or other direct scholarship is absent merely because adjacent-source abstracts do not mention it.

For deep or high-stakes work, mark the three to five load-bearing authorities and run a fresh-context refutation pass that tries to disprove the quotation, pinpoint, holding attribution, and use of each source. Use a separate agent only when independence justifies the coordination cost; otherwise perform a distinct post-draft pass without treating the draft as presumptively correct. For standard work, use this pass only where ambiguity or consequence warrants it; do not add it to routine targeted answers.

### 5. Draft the memo

For every standard or deep run, build the analytical skeleton in the claim ledger before writing prose. For each dispositive or material claim that will appear in the memo, identify its memo section and analytical role (`conclusion`, `rule_or_synthesis`, `application_or_inference`, `counterauthority`, or `limitation`), and confirm its supporting and adverse source IDs. Mark an unsupported load-bearing line `open` or `unresolved`; retrieve support, narrow it, or omit it instead of smoothing it into prose.

After the final Markdown is stable, set `included_in_memo` on every claim. For each included dispositive or material claim, add `memo_section`, `analysis_roles`, and a short `draft_anchor` that occurs exactly once in the final memo. Regenerate these anchors after substantive edits. The schema-v6 validator treats this as the machine-visible claim-to-prose map; do not pass `draft_claim_map` from a provisional outline or stale draft.

For a standard doctrinal memo, default to this sequence unless the user requests another format:

1. Title, author/date, and research cutoff.
2. Question Presented.
3. Short Answer or Executive Summary.
4. Facts, assumptions, and scope.
5. Governing legal framework.
6. Analysis, organized by subquestion or doctrinal strand.
7. Counterarguments, adverse authority, and unresolved issues.
8. Conclusion and practical research or fact-development next steps.
9. Optional authority table or research limitations note when it helps the reader audit the work.

For targeted work, lead with the answer and use only the rule, authority, application, caveat, and status note needed. For scholarly mode, adapt the sequence to: research problem; thesis or provisional claim; historiography and literature gap; sources and method; periodized or conceptually organized analysis; rival interpretations; contribution; and limits or further research. Retain a short answer only when it clarifies the thesis; otherwise use an abstract or opening argument.

Lead with the conclusion. Use descriptive headings and topic sentences. Quote sparingly in the body and more fully only when the precise language matters; use footnotes or parenthetical explanations to make the authority traceable. Every named scholar, work, case, or source-specific characterization in the prose must have a nearby citation or footnote and a ledger entry; include a direct clickable source link for each cited web source, alongside the full citation when available; do not rely on an uncited remembered attribution. A formal memo should use Bluebook-style citations unless the user specifies another style, but do not guess at a reporter, edition, pinpoint, or short cite. Preserve a verified citation even if formatting is imperfect, and flag the formatting issue. Before delivery, check that selected bibliographies and tables of authorities contain complete citations for every listed work.

For project files, publish to `<project>/AI Memos/[topic]-[YYYY-MM-DD]-Codex-[exact lead model label].md` unless the user specifies another destination or name. Use the user's local date after the content audit passes, and distinguish that date from the research cutoff. Record the published path in the run manifest. State the tools or source universe used when it affects completeness or confidence.

Treat the Markdown file as the canonical text source and keep citations and footnotes readable in plain text. Publish it as soon as the research and content audit passes. A DOCX is an optional, nonblocking derivative: generate one only when the user requests it, a downstream workflow requires it, or Word-specific review materially helps. Use one direct Pandoc conversion from the final Markdown with minimal or no custom styling, then run `scripts/verify_docx_ooxml.py DOCX --markdown MARKDOWN --output RECORD`. Inspect the extracted OOXML text for substantive synchronization and disclose that pagination and visual layout were not rendered. Never invoke `soffice`, `libreoffice`, `render_docx.py`, the documents skill, or any helper/runtime that launches LibreOffice; this prohibition applies inside and outside the sandbox. If conversion or structural verification fails, leave the Markdown published, disclose the limitation, and stop. When a structurally verified DOCX is produced, keep its text, citations, footnotes, status, and provenance synchronized with the Markdown.

#### Publish the completed memo

Keep the entire research run—plans, manifests, ledgers, cached sources, intermediate drafts, audits, verifier packets, logs, and cost records—under a hidden project-local path such as `<project>/.codex-memo/runs/<run-id>/`. Do not create visible `research-runs`, packet, ledger, audit, diagnostic, or temporary files. Only the completed Markdown memo and any expressly requested final derivatives may remain visible.

Put the following production block at the very end, after all body text and appendices, in every completed format:

```text
Topic: <memo topic>
Date: <YYYY-MM-DD in the user's local timezone after audit>
By: Codex-<exact lead model label>
Production details: <aggregate runtime-reported tokens; elapsed wall-clock time from run start through audit; subagents and roles; material limits>
```

Include the lead and all worker/verifier usage, including cached-input tokens when the runtime total includes them. Never estimate. If the aggregate is unavailable, write `tokens unavailable (runtime did not expose exact usage)`; a known subtotal may be reported separately as a subtotal. If no subagents were used, write `subagents: none`. Do not block an audited memo because token accounting is unavailable. Use identical production values in derivatives.

Publish the Markdown after all applicable research completion gates pass and it receives its final content audit. Do not delay that publication for a DOCX. Publish a requested DOCX only after its bounded structural OOXML check; use the same provenance values in both files and state that visual layout was not rendered. A deliverable whose remaining limits are fully disclosed may be published as `complete with limits`; do not label unfinished work complete.

### 6. Perform a pre-delivery audit

Run the checklist in [references/review-checklist.md](references/review-checklist.md). At minimum, confirm that:

- every material legal proposition has a source and usable pinpoint;
- the source actually supports the proposition stated;
- quoted language is exact and attributed to the correct opinion or speaker;
- holdings, dicta, dissents, commentary, and inference are labeled correctly;
- binding, persuasive, current, and historical authority are not conflated;
- adverse authority and meaningful uncertainty are visible;
- the direct-answer core was searched and either contains the strongest directly responsive sources or discloses the exact bounded search and access limits that left it empty;
- facts and assumptions are not presented as established facts;
- “no cases,” “settled,” “first,” “earliest,” “overwhelmingly,” “most,” and similar frequency, priority, or universal claims are supported by a documented protocol or qualified;
- citations, case names, statutory sections, dates, and cross-references are internally consistent; and
- the final memo states its cutoff date, scope, and material limitations.

End with a short research-status note when appropriate: what was reviewed, what remains to be checked, and what would most improve confidence in the answer.

For an autonomous run, mark the work `complete` only after every applicable completion gate passes. If a useful memo can be delivered but a source, jurisdiction, claim, or audit step remains unresolved, deliver it as `complete_with_limits`, identify the exact limits, and name the next best action. Do not silently convert a partial research packet into a final memo.

For schema-v5-and-newer standard/deep scholarly or hybrid runs, pass the non-waivable `direct_source_audit` described in [references/autonomous-runs.md](references/autonomous-runs.md). Record `event:direct_source_search` and cite a directly verified `direct_answer` source when one exists; if none was found, disclose the bounded search and access limits. For schema-v4-and-newer runs, generate and resolve the deterministic quantifier audit. For schema-v6 standard/deep runs, pass `draft_claim_map` with `artifact:memo` evidence only after the final claim anchors validate. Do not pass a machine-visible gate merely because a human checklist was reviewed.

## Output standard

In doctrinal mode, the finished memo should let a supervising reader answer four questions quickly: What is the answer? Why? What is the best authority against it? What remains uncertain? In scholarly mode, the reader should be able to identify the thesis, intervention or contribution, source base, method, relationship to existing literature, strongest rival account, and evidentiary limits. Favor precise, candid analysis over inflated certainty or unnecessary length.
