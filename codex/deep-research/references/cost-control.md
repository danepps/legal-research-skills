# Cost Control Without Quality Loss

## Contents

- Quality invariants and four-pass design
- Coverage-based stopping and budget profiles
- Context packing, escalation, and cost reporting

Use this policy to reduce token and tool spend while protecting the parts of research that determine reliability.

## Quality invariants

Do not cut these merely to meet a budget:

- direct verification of the sources behind central claims;
- primary or authoritative sources where they exist;
- at least one deliberate search for contrary evidence;
- currentness checks for time-sensitive claims;
- disclosure of source gaps, uncertainty, and budget exhaustion; and
- a final citation/support and claim-strength audit.

Cut or compress these first:

- duplicate search results and repeated copies of the same source;
- weak secondary sources after a primary source is found;
- full-document context passed to multiple agents;
- verbose lane summaries that add no new evidence;
- repeated searches using equivalent query language; and
- critics or follow-up rounds that cannot change the conclusion.

## Default four-pass design

### Pass 1: Candidate discovery

First extract the thesis, source universe, gaps, and conflicts from relevant prior local reports so the new run searches the delta rather than paying to rediscover the same map. Then use search results, titles, metadata, snippets, local file names, and table-of-contents material to create candidate records. Use fast/low models or deterministic tooling. Do not treat this pass or prior prose as evidence and do not deeply read every candidate.

### Pass 2: Triage and deduplication

Normalize URLs and citations, hash available content, remove duplicates, and score candidates by:

`priority = authority × directness × novelty × conflict-relevance × currentness`

Use qualitative high/medium/low values rather than pretending the score is objective. Promote primary sources, sources directly answering a subquestion, sources that may contradict the current synthesis, and sources likely to change the answer.

Order promoted sources by interleaved coverage: first the best candidate for every material subquestion, epoch, jurisdiction, conception, or other declared coverage cell; then the second-best for each; then later rounds. If a budget reduction becomes necessary, trim the latest round before eliminating the only planned deep read for a material cell. Do not silently increase a hard budget to preserve coverage.

### Pass 3: Targeted verification

Deep-read only the promoted set. Extract the smallest evidence packet that supports each material claim, plus enough surrounding context to avoid distortion. Route ordinary extraction to fast/low models. Escalate ambiguous passages, conflicting authorities, causal claims, and central scholarly interpretations to a balanced or strong model.

### Pass 4: Synthesis and audit

Give the lead agent the plan, coverage matrix, compact evidence table, conflict list, and unresolved questions—not the entire raw corpus by default. Run one strong synthesis call. Add a critic only when a risk trigger in the orchestration guide is met. Finish with a fast mechanical audit and a lead-agent substantive review.

## Coverage-based stopping

Stop searching when all applicable conditions are met:

- each subquestion has at least one credible direct source;
- central claims have either independent support or an explicit reason independent support is unavailable;
- contrary or skeptical formulations have been searched;
- no unresolved high-impact conflict is being silently ignored; and
- the expected value of another search is lower than its cost.

For legal or scholarly work, “one source” is not automatically enough. Increase the verification set when the source is nonbinding, the history is contested, the archive is narrow, the claim is causal, or the user requests exhaustive coverage.

Frequency, priority, and universal claims require more coverage than existence or illustrative claims. If the recorded source universe, search protocol, or remaining budget cannot support `first`, `only`, `most`, `overwhelmingly`, `always`, `never`, or equivalent language, narrow the claim. Do not automatically trigger an open-ended census merely to preserve ambitious wording.

When a material coverage cell remains empty, spend reserved follow-up budget on one targeted retrieval if that could change the answer. Otherwise disclose the gap and finish `complete_with_limits` or `budget_exhausted`; do not deliver a nominally complete report whose declared issue or epoch has no read authority.

Prioritize by claim, not by source count. Label each planned claim as dispositive/high, supporting/medium, or contextual/low. Spend verification budget first on dispositive claims and the best evidence against them. A report with ten deeply verified sources can be stronger than one with fifty shallow sources; a report with many sources is still weak if its central claim is unsupported.

## Budget profiles

Use an automatic allocation below an absolute ceiling. The automatic allocation is enough for the expected memo workflow; the unused ceiling is insurance for a documented material gap, not prepaid capacity. A run may unlock one expansion after a productive wave, but may never expand its worker-interaction or follow-up ceiling.

| Profile | Automatic / absolute lanes | Worker interactions | Follow-ups | Candidates screened | Deep reads | Verification |
|---|---:|---:|---:|---:|---:|---|
| Focused | 2 / 2 | 3 | 1 | 5–12 | 2–6 | Lead verifies every material link |
| Standard | 8 / 12 | 12 | 4 | 12–30 | 5–12 | Independent coverage of every material link, batched by source |
| Deep | 24 / 32 | 36 | 8 | 30–80 | 12–30 | Every material link plus adaptive quorum on 5–8 highest-risk claims |

These are ceilings and source-count budgets, not quotas or guarantees of token usage. One worker interaction means an initial worker turn, retry, repair, or continuation; `lane-start` and `lane-followup` count them automatically. A deep run may use up to 12 read workers: give controlling, direct-answer, uniquely probative, and material contrary sources their own workers, and batch short contextual sources. Large PDFs, long opinions, and dense scholarly corpora require lower source counts or tighter excerpt caps, not additional unrestricted workers.

Use adaptive quorum verification by default. Two agreeing support votes finish a high-risk claim; a split or uncertain pair may receive one tie-breaker; two adverse votes require lead resolution or narrower wording. Use three votes for every selected claim only when an accepted high-stakes plan explicitly selects the triple policy. This preserves independent review while avoiding 15–24 mandatory verification turns in ordinary deep work.

## Context packing

- Pass source IDs and compact excerpts rather than repeating full URLs, instructions, and documents.
- Put shared instructions in the lead prompt, not in every evidence packet.
- Use structured JSONL for metadata and short Markdown for human-readable excerpts.
- Preserve full documents locally when authorized; pass relevant windows to the model.
- Keep intermediate summaries under a fixed packet cap and discard summaries that lack a new source or claim.
- Ask the final writer to cite source IDs that map back to the ledger, then resolve them to canonical citations/links during packaging.

## Adaptive escalation

Escalate only when a cheap pass detects a reason:

- a source is likely controlling or uniquely probative;
- two credible sources disagree;
- a passage is ambiguous or difficult to interpret;
- a central claim lacks direct support;
- a recommendation depends on uncertain assumptions; or
- a critic finds a material gap.

Do not use a low-end model to decide that an authority is irrelevant when it may be controlling. Use low-end models to identify candidates and extract text; use the lead agent to decide importance.

## Cost report

Write a machine-readable cost report when possible. Include:

- calls by lane, profile, model, and reasoning effort;
- exact runtime-reported input/output tokens when exposed, otherwise an unavailable marker;
- tool calls and pages/documents opened;
- cache hits and duplicate sources suppressed;
- candidates screened versus deeply verified;
- critic and follow-up calls;
- budget exceptions and waived quality gates; and
- quality checks passed, failed, or incomplete.

If token accounting is unavailable, report the other measured counts and write `tokens unavailable (runtime did not expose exact usage)`; do not estimate tokens. A cheap run that silently omits verification is not a successful optimization.
