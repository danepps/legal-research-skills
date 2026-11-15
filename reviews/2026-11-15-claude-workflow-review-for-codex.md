# Note for Codex: defects found in the three Claude workflow scripts, and what to check on your side

Date: 2026-11-15
Author: Claude (Claude Code side), on branch `claude/research-workflows-review-r7cyn2`
For: Codex, and Daniel Epps
Subject: a code review of `cite-check.workflow.js`, `legal-research.workflow.js` and `proofread.workflow.js` (Claude Code plugin 1.6.4), the fixes released as 1.6.5, and the same questions put to the Codex skills

## 1. How to read this

**Method.** I read the three workflow scripts in full and ran each under stubbed agents: a harness replaces `agent()` with a function that returns canned results, so the script's own accounting can be exercised without a model or the network. Every defect in section 2 was reproduced that way before it was fixed, and each has a regression test that fails on the old script.

**What that does and does not show.** Each item is "the script allowed this", not "this happened in a run". Several depend on a worker answering in a particular way (echoing the wrong id, marking a corrected verdict as not upheld). The prompts permitted those answers; I did not observe them live.

**What I did on the Codex side.** Not a review. I searched the `codex/` tree for the same patterns and read the lines cited in section 3. Section 3 is a list of questions with pointers. Where I say Codex already handles something, I read the code that does it; where I ask, I did not find the handling and you should check.

The Codex skills are built differently (worker ledgers in a run directory, checked by `validate_run.py`), so few of these defects can exist in the same form. The reason to send this anyway is that every one of them is an instance of a general mistake that does not depend on the architecture. Section 2 is organized by the general mistake.

## 2. The defects, by kind

### A. A second check that corrects, where the code only knew "confirm" and "clear"

`cite-check`: the mandatory re-verification of every high-severity quote finding returned `upheld: true|false` plus a verdict. The script treated `upheld: false` as "checker artifact, drop it" whatever verdict came back. If the second checker found that a reported mismatch was in fact a syllabus quotation, or a wrong pincite, and said the first verdict was not upheld, the corrected finding left the report, was counted as "verbatim after all", and its ledger instance read `existence-only` (never read) after two agents had read it.

Fix: a finding is an artifact only when the corrected verdict clears the quote (`verbatim`, `altered_marked`, `fragment_framing`). Any other corrected verdict is reported under the new verdict with the first one named. A cleared finding's ledger instance is `verified`. The support pass in the same script already had this rule; the quote pass did not.

### B. Joining a worker's result to a unit by an identifier the worker echoes

Four instances, all the same shape: a batch of workers runs in parallel, each returns rows carrying an id, and the script files every row under the id it carries.

- `cite-check` re-verify: the prompt showed the unit id only inside the command `--ids N N+1`. A worker echoing `N+1` rewrote the neighbouring quote's verdict. In the test a verbatim quote became a HIGH mismatch labelled as re-verified.
- `cite-check` verify: a worker's verdict for a quote that belonged to another source was accepted, and the quote was counted twice.
- `legal-research` cite-check chunks: a verdict under an index outside the worker's chunk claimed another chunk's authority, first one winning.
- `proofread` verify batches: last one winning, so a stray "rejected" from another batch removed a confirmed finding.

Fix: the script knows which units each job was given. A single-unit job's result is joined by job position and the echoed id is ignored. A multi-unit job's rows are kept only for the ids that job was given, first row per id; the rest are dropped and counted in the run's degradation list.

### C. The reserve for the mandatory second check

`cite-check` projects cost per agent kind and gates each phase. The reserves held back for re-verification were 40,000 and 30,000, left from an earlier budget unit, against a re-verify agent costed at 100,000 in the current one. The re-verify gate was also all-or-nothing: if all the high-severity findings did not fit, none was re-derived. Together: a budget-bound run with two or more high-severity findings skipped the whole pass, which is exactly the run that has the most findings to get wrong.

Fix: the reserve is three quote re-verifications and two support re-verifications, capped at a tenth and a twentieth of the run cap. Both re-verify passes launch as many as fit and label the rest single-checker.

### D. Several checkers, one answer: "first non-empty wins"

`legal-research` deep mode sends each load-bearing authority to three voters with different routes. The aggregation took the first voter's `currentTreatment` and the first voter's `correctedCitation`.

- Treatment: voter 1 said "no negative treatment found", voter 3 (whose route leads with adverse treatment) said "overruled by …". Only the first reached the finalizer, and the run ended `complete`.
- Correction: one voter, on a citation-only basis, proposed a different citation; the other two found it accurate as written. The verdict became `needs-correction` and the finalizer was told to replace the citation.

Fix: every distinct treatment report is kept and attributed to its voter, and the finalizer is told that one voter's "none found" does not cancel another's overruling. A correction is applied only when a strict majority of the returned voters propose the same one; a minority proposal is disclosed and listed in the memo's Limits section.

### E. A label that does not follow the verdict

- `legal-research`: the validation tier was computed from "did the panel run", not from what the panel decided, so a refuted authority carried `[unverified | … | tier: verified (3-voter refutation panel)]`. Statutes and articles were labelled as having had a citing-opinion probe that only resolves judicial opinions.
- `legal-research`: any authority a research reader had opened was stamped `direct-full-text`, although readers are told to prefer CourtListener and LII, which the script's own vocabulary calls `authoritative-reproduction`, and the cite-checker did not re-open the source.

Fix: tier labels are derived from the verdict and the source type. The read-this-run basis has a floor of `authoritative-reproduction`, a checker's own stronger report stands, and the note says whose read the basis rests on.

### F. A worker that dies and leaves no trace

- `legal-research`: a dead survey vector or a dead reader was filtered out of the results. A selected source whose reader died was absent from the read results and, being "selected", from the unread leads too, so the top-ranked source could be missing from the draft with the run still `complete`. A dead triage agent crashed the run with a TypeError, because `agent()` returns null on death and the `.catch` covered only a rejection.
- `cite-check`: a dead case-existence batch (up to 30 cites) was not retried and produced no degradation line, though every other fan-out in the script retried.

Fix: each of these retries once. A second death is a named coverage gap that changes the exit state and is passed to the finalizer for the Limits section. The unread source stays in the findings as an unread lead. Triage falls back to survey order.

### G. A cap that always cut the same thing, while the log said otherwise

`legal-research` harvests the authorities each read source relies on and adds them to the unread leads. They were appended after the search leftovers and the list was then cut at the lead cap. The leftovers alone usually filled the cap (40 candidates less 8 reads against a cap of 16), so the harvest never reached the draft, and the log line counted the harvest before the cut.

Fix: a third of the lead slots are kept for harvested authorities, taken round-robin across the read sources, and the log reports what was carried.

### H. A budget measured from the wrong origin

`legal-research` compared its soft cap with the runtime's spend figure, which covers the whole turn, not the run. With 200,000 tokens spent earlier in the turn, a lean run trimmed its reads from 8 to 3 and left a citation unchecked. Fix: baseline at the run's start, as the other two scripts did.

### I. Shared scratch files

`cite-check` told every worker to write `/tmp/src-<slug>.txt` and `/tmp/q-<slug>.json` with a slug the worker chose. Two re-verify workers on the same source could overwrite each other's quote list between the write and the verifier run. Fix: a path prefix unique to the run and to the worker.

### J. Documentation that had drifted from the code

- `cite-check/SKILL.md` quoted the history batch at 110k; the script had said 350k since 2026-11-12. The orchestrator quotes these figures to the user before launch.
- The `cite-check` report prompt sent secondary-source items to sections G and H, which became history and support when those were added.
- `legal-research/SKILL.md` said readers probe candidate URLs with `probe_sources.py`. The read prompt never said so. The prompt now does.
- `legal-research/SKILL.md` said the workflow only lets the memo cite authorities an independent agent confirmed. Unconfirmed authorities are kept with a caveat and read-this-run sources are not re-read. The sentence now says what happens.
- `proofread` called its agents "structurally" read-only. The agent type has no file-editing tools but does have a shell. The wording now rests the guarantee on the draft's path never reaching an agent and on the write-protected snapshot.

## 3. Questions for the Codex skills

Pointers are to files in `codex/` at commit `414b9ff`.

1. **Kind A, quote audits.** `cite-check/scripts/support_validation.py` (about lines 214–227) constrains the final verdict after a support audit: `confirmed` must match, `retracted` must end `supported`, and `references/verification-protocol.md` (about line 260) says `revised` moves to `overstated` or `supported_qualified`. For quote verdicts, `cite-check/scripts/validate_run.py` (about lines 792–830) requires only that an audit row exists with a valid status and evidence. What must a quote verdict be after a `retracted` or `revised` audit, and does a revised quote finding (a mismatch that is really a wrong pincite) stay in the report under its new category? I found no rule. `internal-proofread/references/finding-schema.md` (line 114) says a retracted finding must end rejected; the same question applies to `revised` there.
2. **Kind B, assignment.** `validate_run.py` rejects duplicate and unknown ids (`verdict_id`, `unit_id`, `quote_check_id`; lines 476–485, 697, 794–797). That covers a made-up id. Does anything check that a row was written by the worker the unit was assigned to, so that a valid id from another worker's packet is caught? `internal-proofread/scripts/validate_run.py` counts owners per block (lines 130–137, 196–203), which looks like that check; I did not find its equivalent for cite-check workers or for `legal-research-memo` reviewers.
3. **Kind C.** `verification-protocol.md` (line 241) says never sacrifice audits to expand coverage. Is that enforced by the run options, in the same unit as the cost estimates (`prepare_run_options.py`, `usage_report.py`, `references/resource-controls.md`)? And if the audits cannot all be afforded, are some done, or none?
4. **Kind D.** Where `legal-research-memo` or `deep-research` has more than one reviewer report on the same authority, how are a disagreement about treatment and a proposed citation change merged? `legal-research-memo/scripts/courtlistener_treatment.py` and `validate_research_run.py` are the places I would look first.
5. **Kind E.** Is any validation label or verification basis in a memo computed from "a check ran" instead of from its result, and is a basis ever raised on the strength of a different worker's read (`legal-research-memo/references/source-protocol.md`)?
6. **Kind F.** `cite-check` records `unread_reason: agent_failure`, which is the right shape. In `deep-research/scripts/research_run.py` and `legal-research-memo/scripts/checkpoint_run.py`, can a lane that died be told apart from a lane that returned nothing, and does the exit state change?
7. **Kind G.** Any list that is concatenated and then truncated: which part is at the end, and is it ever non-empty after the cut?
8. **Kind I.** I found no fixed `/tmp` names in `codex/`; the scripts use run directories and `tempfile`. Nothing to do unless a prompt names a shared path.
9. **Kind J.** The same drift is likely wherever a `SKILL.md` or reference file repeats a number that a script owns (cost estimates, caps, batch sizes).

## 4. What changed on the Claude side

Workflow scripts: `claude-code/skills/cite-check/cite-check.workflow.js`, `claude-code/skills/legal-research/legal-research.workflow.js`, `claude-code/skills/proofread/proofread.workflow.js`.

Regression tests, all offline, all driven by stubbed agents:

| Test | Scenarios |
|---|---|
| `cite-check/scripts/test_workflow_quotes.py` with `workflow_quote_harness.mjs` | second checker corrects, withdraws, or echoes the wrong id; a verdict for another source's quote; budget fits three of five re-verifications; dead existence batch (once, twice); per-agent scratch prefixes |
| `cite-check/scripts/test_workflow_support.py` (updated) | budget fits one of two support re-verifications; an inflated re-verify cost does not starve the earlier phases |
| `legal-research/test_workflow_pipeline.py` with `workflow_harness.mjs` | dead triage, reader, survey vector; duplicate triage indices; harvested leads reach the draft; baselined cap; refuted label; split treatment; minority and majority corrections; foreign chunk index; read-this-run basis |
| `proofread/scripts/test_workflow_verify.py` | a verdict from another batch; a duplicate verdict |

Two judgment calls a later run should test, because I set them without live data: the size of the re-verify reserve (three and two agents), and the share of lead slots kept for harvested authorities (a third).

The harness pattern is the part most worth borrowing. It takes about a hundred lines, needs no model, and every item above was invisible to tests that exercise only the Python helpers.
