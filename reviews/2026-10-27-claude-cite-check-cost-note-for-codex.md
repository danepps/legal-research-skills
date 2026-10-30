# Note for Codex: what the first live support-pass run cost, and why

Date: 2026-10-27
Author: Claude (Claude Code side), on branch `cite-check-proposition-support` (PR #1)
For: Codex, and Daniel Epps
Subject: the Claude Code cite-check run of 2026-10-26 (footnotes 1–30 of a 293-note draft, `support:true`, report committed as `Sample/test draft — Cite Check.md`), the review of that report, and the changes made on the Claude side in response

Everything in the first two sections is read off the committed report, the workflow source, and the test fixtures; nothing is estimated except where it says so. Section 3 is what changed on the Claude side. Section 4 is what seems worth porting.

## 1. The cost

| Quantity | Value |
|---|---|
| Subagent tokens reported by the completion notification | 1,989,264 |
| Agents | 34 (33 Sonnet, 1 session model for the report) |
| Mean per agent | about 58,000 |
| Per-source estimate the budget gates assumed (verify / support) | 9,000 / 10,000 |
| Soft cap for this configuration (650k + 350k for support) | 1,000,000 |
| Degradation recorded | none ("0 dropped for budget") |

Three facts explain it.

**The work was already delegated to the cheapest acceptable tier.** Every mechanical stage runs on Sonnet; only the report agent inherits the session model. Haiku is excluded on purpose. So the question was never which model, but why Sonnet agents produced 58k tokens each.

**The gates assumed a sixth of the real per-agent cost, and only ran before a phase.** Each phase asked whether the remaining budget covered `sources × estimate` and then launched every agent in the phase at once. With estimates of 9–10k and real spend near 60k, every gate passed, and nothing could stop a phase that had started. The cap never bound.

**The tokens went to failed fetches.** The report's section I lists 17 of roughly 30 sources as unverifiable, with notes such as "Georgetown PDF guess and journal page 404, SSRN 403, one guessed repository URL returned an unrelated article," "guessed Yale PDF URLs 404," "Penn repository PDF guesses 404." Each guess is a tool call with reasoning around it; support agents run at medium effort, so their thinking counts too. Sources that Zotero held were cheap. Sources that produced nothing were the expensive ones. This is lesson 6 of the July 2026 practice run (the WAF reality), and the three-attempt cap per source did not contain it because the spend is in finding and testing candidates, not in the fetches.

**One thing is unreconciled.** The gates read `budget.spent()`, which the workflow runtime documents as output tokens for the turn. If that number had tracked the notification's 1.99M, the Re-verify and Form gates, which come after Verify and Support, would have been tight and skipped their work. The report shows both adverse verdicts re-derived and the form agent run. So either the notification's `subagent_tokens` counts something broader, or spend is reported with a lag. The run's journal would settle it; the Claude side now prints both figures in every report footer so the next run settles it.

**Scaling.** Thirty footnotes cost 2M. A full draft will not cost ten times that (unique-source collapse and `Id.` chains help more over a whole draft, and opening footnotes are dense with secondary sources), but 8–15M by this run's rates is plausible. The earlier full-draft run in SKILL.md's example footer spent 2.4M across 53 agents without the support pass, so the support pass roughly tripled per-agent cost. The skill's "two to four times a standard run" was about right as a multiplier; the standard run was never 650k.

## 2. The report itself

The sample report is internally consistent on its main counts, both adverse support verdicts are well evidenced and were re-derived, and the Carolene, Federalist No. 37, and Défenseur des droits analyses hold. Problems, most important first:

1. **Section D item 4 (Levinson, 121 Yale L.J. 1286) rests on an inferred page range.** The checker estimated the article at 1286–1323 from running-head counts in a Zotero fulltext with no page markers, and called the draft's 1355 "probably too high." Claude's recollection (unverified; the journal site was unreachable from the review session) is that the article runs into the 1360s, which would make 1355 plausible. Whoever is right, the design rule is to report a pincite unverifiable when pagination is unrecoverable, not to infer it. **This applies to Codex's verification protocol as well:** a pincite verdict needs page boundaries in the text (form feeds with a known first page, star pagination, or explicit page markers); running-head counting is not one.
2. **Three counts disagree.** The TL;DR says 3 sources unconfirmed from free sources; section J lists four real ones plus a parser artifact; section I calls a fifth (Kleinman, n.13) "existence unconfirmed" without listing it in J.
3. **Scope leaks.** Title, TL;DR and section J say 293 footnotes (fixed for future runs in 20d6b77; the sample predates the fix). The Citation form section covers the whole draft without saying so.
4. **Internal paragraph ids reach the report** (¶137, ¶181) in the form section. The author's rule (2026-08-23, recorded in the proofread skill) is that reader-facing locations are Part/section, visible note numbers and the find-string, never extractor ids. The cite-check workflow's location formatter still emits them. Not yet fixed on the Claude side.
5. Smaller: the NORC brief finding in section E has no footnote number; one find-string is cut mid-word; section D is not in footnote order.

## 3. What changed on the Claude side (this commit)

1. **`legal-research/probe_sources.py`** (shared toolbox, stdlib). An agent gathers every candidate URL for a source and tests them in one call. Per URL: `fetchable`, `status` (ok / blocked / not-found / login-wall / subscription / rate-limited / server-error / unreachable), HTTP status, final URL, content type (PDF sniffed from the body), the known behaviour of the host, a Wayback Machine snapshot for anything unreachable, and an `unlock` path. Subscription hosts (HeinOnline, JSTOR, Westlaw, Lexis) are marked without a request. SSRN, Justia and bepress Digital Commons hosts (`digitalcommons.*`, `scholarship.law.*`, `ir.lawnet.fordham.edu`, `repository.law.umich.edu`, …) are probed once and labelled, never retried with variants; openYLS is treated as a sign-in page. The shared `SOURCES` prompt block tells every fetching agent to probe first, fetch only what is marked fetchable, count each probed failure as an attempt, and stop with the unlock path when nothing is fetchable. Twenty URLs per call at most.
2. **Self-measurement.** Every agent goes through one counter; spend per phase is logged at each phase boundary and returned as `spend` (`measured`, `agents`, `perAgent`, `softCap`, `byPhase`). The per-agent estimates behind every gate became floors (verify 25k, support 30k, existence and history 8k, re-verify 10k, form 15k) that the run's measured mean replaces as soon as agents report, in the same units the gates compare against. SKILL.md prints `spend` in the footer beside the notification's figure.
3. **Waves.** The verify and support fan-outs launch through `gatedFanout`: waves sized to the budget left after the reserves (at most `maxWave`, default 12, about the concurrency cap), re-measured between waves, at least one job while any budget beyond the reserve remains. What is never launched is disclosed by source as NOT CHECKED (budget) with the `+Nk` budget that lifts the cap. Budget skips are never reported as agent failures.
4. **SKILL.md step 3c:** the orchestrator states the expected agents and tokens against the cap before launching, from the deterministic counts, and says what will degrade if the estimate exceeds the cap.

Not done, by decision: splitting support agents into a low-effort fetch half and a medium-effort judgment half. With the probe, the fetch half is cheap; the split adds a file handoff between agents for a gain that cannot be measured until a run reports its `spend`. Also not done: the report-quality items in section 2 (the ¶ ids, the count reconciliation), which are separate from cost.

Tests: `legal-research/test_probe_sources.py` (host rules, status mapping, sign-in detection, Wayback parsing, the per-call cap; offline, fake `urlopen`) and a `budget-wave` scenario in `cite-check/scripts/test_workflow_support.py` (the first support wave exhausts the cap; the second job is never launched; its units are unread, the export is incomplete, the exit state says so). The offline suite is 40 programs, all passing.

## 4. For the Codex side

The Codex cite-check has its own bounded fetcher and its validators check recorded usage against budgets, so the shape of the fix differs, but the findings carry over:

- **Probe candidates deterministically before any model-driven fetch.** `probe_sources.py` is stdlib and shares nothing with the Claude workflow, so it can be called from the Codex scripts as is, or its `HOST_RULES` table copied. The point is that a 403 or 404 should cost zero model tokens.
- **Treat the known-host list as data, not prompt text.** The hosts above have failed in every live run on both sides. A table the scripts consult beats a sentence the model may or may not weigh.
- **Measure per-agent cost in the run and compare it with the estimate the budget logic uses.** Whatever Codex's run validators assume per source, the Claude figure was wrong by six times, and the only way to know is to record what each agent spent.
- **Pincites without page boundaries are unverifiable, never inferred** (section 2, item 1). Worth a line in `references/verification-protocol.md` if it is not already explicit.
- **The cost sentence to users.** Any user-facing statement of what the support pass costs should rest on the measured run, not on the pre-run multiplier.

---
Response from Codex, if any, belongs below this line, with the original left unchanged.
