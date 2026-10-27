# Evaluation of commit 30438ba ("probe before fetch, self-measured spend, budget-sized waves")

Date: 2026-10-27. Question: is this commit likely to stop the cite-check budget from spiraling?

**Short answer: partly, and not for the reason it gives.** The commit's diagnosis (58k output
tokens per agent, six times the gates' estimate, so no gate ever closed) is wrong. The agent
transcripts of the 2026-10-26 run show the gates saw the right number and behaved correctly.
The real cost is input context re-read on every turn, which neither the gates nor the waves can
see. Of the three changes, only the probe aims at that, and only at part of it.

## 1. What the run actually spent (from the 34 agent transcripts, wf_7d9ac2ad-c18)

| Phase | Agents | Turns | Output tokens | Input + cache write | Cache read |
|---|---|---|---|---|---|
| Verify | 18 | 230 | 82,475 | 1,697,398 | 10,506,047 |
| Support | 5 | 124 | 59,877 | 861,327 | 6,592,259 |
| Existence | 5 | 100 | 83,233 | 719,770 | 4,302,890 |
| Re-verify | 2 | 15 | 7,950 | 136,914 | 585,698 |
| History / Segment / Form / Report | 4 | 17 | 44,710 | 361,215 | 461,847 |
| **Total** | **34** | **486** | **278,245** | **3,776,624** | **22,448,741** |

- Output per agent: about 8,200, in line with the 9–10k the gates assumed since July. The soft
  cap was 1,000,000 output tokens; the run used 278k. "0 dropped for budget" was correct.
- `budget.spent()` is documented as output tokens for the turn. The notification's
  `subagent_tokens` (1,989,264) is a different, unlabeled aggregate: it is not output, not
  output + input, and not any simple weighting of the columns above. The commit divided it by
  34 and treated the result as per-agent output; that is the 58k.
- The cost is turns × context. 486 turns at 50–60k tokens of context each. The most expensive
  agents were not the URL-guessers: the two `exist-secondary:12` batches (30 and 34 turns, 12
  Zotero searches plus 6–9 web searches each, 1.3–1.5M cache-read each) and the four
  `support-tail` agents (25–33 turns, 1.3–1.8M each). Verify agents ran 8–19 turns, three of
  them Zotero searches across three libraries before anything was fetched.

## 2. The three changes against that picture

1. **Self-measured spend.** Measures the wrong currency. The run's measured mean will come in
   near 8k, so the raised floors (25k verify, 30k support) govern every gate and overstate output
   threefold. On a full draft the ladder will degrade and drop sources well before the real
   cost is bounded. The side-by-side footer (workflow figure beside the notification's) is
   useful: the first run will show ~300k against ~2M and expose the mismatch.
2. **Waves.** Bound output-token spend per phase, which never spiraled. They add a barrier
   every 12 agents (slower wall-clock), and the first wave launches on the floor estimates.
   Harmless, but not the fix.
3. **Probe before fetch.** The only change aimed at turn count, which is the real driver.
   It should shorten the agents that guessed repository URLs. It does nothing for the
   Zotero- and WebSearch-heavy existence batches, which were the largest per-agent spenders.

## 3. What would actually bound it

- **Cut turns per agent.** Do Zotero lookups deterministically before the fan-out (one script,
  Zotero Web API, every secondary source at once; hand agents item keys and attachment paths).
  Search one Zotero library once, not three. Cap tool calls per agent in the prompt.
- **Cut context per turn.** Every agent carries the SOURCES and DETERMINISTIC_CHECK blocks plus
  tool results (Zotero fulltext, WebSearch pages). Route big tool results through files.
- **Smaller batches.** A 12-source existence batch means 30+ turns in one growing context; cost
  per agent is roughly quadratic in turns. Batches of 4–6 cost less in total.
- **Gate on turns or agents, not `budget.spent()`.** The runtime exposes only output tokens, so a
  budget gate cannot see this cost. Turn and agent counts are the usable proxy.
- **Reconcile the unit** by printing both figures, as the commit now does, and by totaling the
  transcripts after each run (the script used for this note is a one-liner over
  `agent-*.jsonl` usage fields).

Sources: workflow runtime reference (`budget.spent()` = output tokens this turn); journal and
agent transcripts under the 2026-10-26 session's `subagents/workflows/wf_7d9ac2ad-c18/`; the
completion notification in that session's transcript.

## 4. What was done in response (same day)

Implemented on `cite-check-proposition-support`: `scripts/zotero_lookup.py` (deterministic
Zotero matching, metadata confirm notes, PDF download and text extraction before launch; agents
no longer call Zotero tools), cost-model projection in the workflow gates (per agent kind, in the
notification's unit, `costModel` overridable, projection printed in the footer), smaller batches
(5 / 4 / 3) and a tool-call budget in every fetching agent's prompt. Tests: `test_zotero_lookup.py`
and two new harness scenarios. DESIGN.md carries the corrected addendum.

## 5. Live test on the same passage (footnotes 1–30, support on), same day

Both figures below are from the agent transcripts (`scripts/run_usage.py`), in input-equivalent
tokens (uncached input + cache writes + cache reads ÷ 10 + output × 5; 1M ≈ $3 at Sonnet rates).
The completion notification's `subagent_tokens` is the sum of each agent's peak context
(1,988,912 by the transcripts vs 1,989,264 reported; 1,102,009 vs 1,102,299), not a cost.

| Run | Agents | Turns | Zotero tool calls | Cost (IET) | Quotes settled of 21 | Support read / unreachable (18 in scope) |
|---|---|---|---|---|---|---|
| 2026-10-26, before the fixes | 34 | 486 | dozens | 7.41M (~$22) | 11 (9 verbatim, 2 altered); 6 unverifiable | 9 / 11 |
| 2026-10-27 run 1, old caps | 20 | 144 | 0 | 2.70M (~$8) | 11; 10 unverifiable; support dropped by the ladder | 1 / 0 (17 unread) |
| 2026-10-27 run 2, recalibrated | 40 | 310 | 0 | 5.28M (~$16); projected 5.08M | 18 (15 verbatim, 1 altered, 2 pincite); 3 unverifiable | 8 / 10 |

Run 2 reused 15 cached agents from run 1 (their run-1 cost is included above). Its two
not-supported verdicts (n.19, n.25) were re-derived; nothing was skipped for budget. The three
quotes still unverifiable are Ely (no attachment, Google Books rate-limited) ×2 and one blocked
repository. Per-kind measurements set the final constants (web verify 150k, Zotero verify 80k,
support tail 210k, re-verify 100k, report 250k).

Run 1 exposed two defects, both fixed before run 2: a record whose subtitle the draft omits was on
disk but not joined to its verify bundle, and the old caps (still in the output-token unit)
degraded the verify phase into tail batches whose agents gave up on four reachable sources.

Reports from both runs are in the session scratchpad run directory
(`test draft — Cite Check (2026-10-27 run 1).md`, `test draft — Cite Check (Claude) (2026-10-27 run 2).md`);
the committed sample from 2026-10-26 is untouched apart from its rename.
