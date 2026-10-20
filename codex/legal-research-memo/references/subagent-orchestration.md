# Subagent Orchestration

Use this protocol when the user requests parallel work or when a standard/deep assignment has at least two independent, source-heavy coverage cells. Keep targeted work single-agent. For deep scholarly and broad literature work, presume coverage-directed fan-out when the environment permits it. The goal is independent coverage with centralized judgment, not a committee of agents writing incompatible memos.

## Orchestration pattern

### Stage 0: Lead-agent setup

The lead agent should first:

1. classify the project as doctrinal, scholarly, or hybrid;
2. state the question, scope, jurisdiction, period, source universe, confidentiality limits, and research cutoff;
3. divide the work into non-overlapping lanes;
4. create a shared source-ledger schema; and
5. define what counts as a verified result.

Do not fan out an unclear question. A strong lead prompt and a narrow research lane are more valuable than many loosely instructed agents.

Set a default ceiling of 12 workers over the run, including queued workers but excluding the lead. Host concurrency may be lower. Treat the ceiling as capacity, not a quota: assign one worker to each independent coverage cell or source class and leave the remaining slots unused. Prohibit recursive fan-out and duplicate generalist lanes.

### Stage 1: Parallel research lanes

Use only the lanes the assignment needs. Typical lanes are:

| Lane | Primary task | Recommended model tier | Judgment boundary |
|---|---|---|---|
| Direct-answer core | Find sources whose title, abstract, headings, table of contents, or full text directly addresses the exact question; citation-chase the closest works | Medium | May identify and extract directly responsive works; lead decides centrality and implications |
| Primary-source discovery | Find likely cases, statutes, regulations, archival texts, or official materials; capture stable locations | Fast/low | May identify candidates; may not decide controlling force |
| Supplied-source extraction | Extract relevant passages, metadata, procedural posture, and pinpoints from provided files | Fast/low | May report what the text says; may not broaden the holding |
| Case-law extraction | For assigned cases, record issue, disposition, holding language, reasoning, and limits | Fast/low or medium | Must quote/pinpoint; lead decides doctrinal significance |
| Statutory/regulatory text | Locate versions, amendments, definitions, effective dates, and cross-references | Fast/low | Report textual differences; lead interprets legal effect |
| Literature map | Identify and classify secondary works by argument, method, period, evidence, and contribution | Fast/low or medium | May map positions; lead evaluates historiography |
| Historical/conceptual vocabulary | Search predecessor terms, period usage, and adjacent legal categories | Medium | May propose connections; lead tests whether meanings are equivalent |
| Adverse authority | Search contrary cases, exceptions, dissents, failed arguments, and negative treatment | Medium | May identify vulnerabilities; lead weighs them |
| Citation/currentness check | Check names, dates, pinpoints, quotations, amendments, and later treatment against sources | Fast/low | Mechanical verification only; escalate ambiguity |
| Independent critic | Attack the proposed synthesis, thesis, or draft for overclaiming and missing evidence | Medium/strong | May challenge; lead decides revisions |

Use at most one researcher per lane unless the question is unusually important or coverage needs independent replication. Always separate the direct-answer core from adjacent literature or general context; a large background packet cannot cure a missed directly responsive source. Prefer independent searches for the adverse-authority lane and, for high-stakes work, a second citation check on the most important authorities.

### Stage 2: Lead-agent synthesis

The lead agent should merge the packets into one ledger, deduplicate sources, resolve conflicting metadata, and independently open the most important authorities. Then it should:

- rank authorities by binding force, directness, currentness, and factual fit;
- separate source-reported facts from subagent inference;
- identify gaps, conflicts, and unresolved questions;
- form the doctrinal conclusion or scholarly thesis; and
- decide which subagent claims must be discarded.

For scholarly and literature work, the lead must also run a central-source omission audit before drafting: compare the ledger with the bibliography and citing works of the closest direct source, search the exact phenomenon with the relevant actors or institutions, inspect tables of contents or headings for underspecified candidates, and promote likely direct treatments to full text. If no direct source is located, record the bounded searches and access limits; do not infer absence from adjacent-source abstracts.

Subagent agreement is not evidence. A proposition is ready for the draft only when the underlying source and its support have been checked.

### Stage 3: Critique and finalization

Use an independent critic when risk justifies it: high-stakes advice, conflicting central authorities, contested history or causation, a requested claim of comprehensive coverage, or an audit that finds unsupported material claims. Send only the assignment, source ledger, and provisional synthesis or draft. Ask the critic to find unsupported claims, missing adverse authority, mischaracterized holdings, historiographical omissions, quotation problems, and overbroad conclusions. Do not ask the critic to rewrite the memo.

The lead agent should resolve the critique, run the final checklist, and produce the deliverable. Use a fast/low model for a last mechanical citation pass only after the substantive draft is stable.

For deep or high-stakes work, a bounded fresh-context verifier may try to refute the quotation, pinpoint, holding attribution, and use of the three to five load-bearing authorities. Give it the source and claim, not the draft's defense of the claim. Treat a correction as a correction rather than forcing an artificial disagreement. Skip this lane when a distinct lead-agent pass provides adequate assurance or the independence benefit does not justify the cost.

## Model-tier policy

### Fast/low models

Assign low-end models tasks with a constrained output and a supplied source or clearly defined search lane. Good tasks include:

- extracting a quote and pinpoint from a known document;
- normalizing case names and source metadata;
- tagging a passage as rule, fact, holding, dicta, dissent, or commentary;
- deduplicating citations;
- comparing two statutory versions line by line;
- producing search-term variants;
- checking whether a draft citation matches the supplied source; and
- running a completeness checklist.

Require them to return “not located,” “uncertain,” or “needs lead review” rather than guessing. Do not use them as the sole decision-maker for a legal test, historical meaning, authority hierarchy, causal claim, or scholarly contribution.

### Medium models

Use medium models for broader but still bounded research: collecting a defined jurisdiction’s cases, mapping a clearly specified literature debate, identifying contrary authority, or proposing period-specific vocabulary. Require source-backed packets and make the lead agent review interpretive claims.

### Strong models

Reserve stronger models for tasks where ambiguity and synthesis matter: refining the research problem, selecting the structure, reconciling conflicting authorities, evaluating the historiography, developing the thesis, testing counterarguments, and drafting the final memo.

## Return packet schema

Require every research subagent to return a compact packet in this form:

```text
Lane:
Research question:
Scope and cutoff:

Verified sources:
- Source ID:
  Full citation:
  Source location:
  Court/publisher and date:
  Authority level:
  Proposition supported:
  Exact quote or close paraphrase:
  Pinpoint:
  Procedural/posture or genre note:
  Limitation, contrary language, or later treatment:
  Verification status: directly checked / partial / lead only

Synthesis (preliminary, not final):
Gaps or unresolved questions:
Searches run:
Confidence: high / medium / low
```

For a low-end model, omit “Synthesis” or restrict it to a one-sentence description of the source. The lead agent should not treat a source as verified when the packet says “partial” or “lead only.”

## Prompting and isolation rules

- Give each subagent the minimum context needed for its lane.
- Pass the same jurisdiction, time cutoff, and confidentiality rules to every lane.
- Ask researchers to report raw sources and passages before conclusions.
- Do not reveal the lead’s expected answer to independent discovery or adverse-authority agents.
- Do not let one subagent’s unverified conclusion become another subagent’s premise during the first research pass.
- Keep client identifiers and privileged strategy out of prompts unless the environment and user have authorized their use.
- Use local files and redacted issue descriptions when external research is needed.
- Apply the bounded source-access protocol to every lane and rescue/fill pass: normally three retrieval attempts per source, stop on repeated paywalls or authorization failures, preserve extraction limits, and use unique per-run/per-source output paths. No worker may change permissions, configuration, or login state to keep a stalled source search going.

## When not to fan out

Use one strong agent when the task is narrow, the authority set is small, the question turns on one ambiguous passage, or the overhead of merging packets would exceed the research benefit. Fan-out is not a substitute for a clear research design or for reading the controlling sources.
