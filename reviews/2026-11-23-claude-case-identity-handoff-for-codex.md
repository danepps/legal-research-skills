# Handoff for Codex: a case cite that resolves to a different case or year must not pass

Date: 2026-11-23
Author: Claude (Fable 5.2), on branch `workflow-fixes-1.6.11`
For: Codex, and Daniel Epps
Skill: none (ad hoc session)
Subject: a hole found in the Claude Code cite-check skill on 2026-11-23, the same gap in `codex/cite-check/scripts/check_cite.py`, and the change requested on the Codex side

## 1. What was found

A live Claude Code cite-check run on an invented six-footnote draft, with seeded defects, reported that all five case cites were confirmed with no metadata issues. Two were wrong:

- The draft cited `Sherman v. United States, 356 U.S. 396 (1958)`. CourtListener's citation lookup resolves 356 U.S. 396 to Thomas v. Arizona, decided 1958-06-30. Sherman is at 356 U.S. 369.
- The draft cited `Sorrells v. United States, 287 U.S. 435 (1934)`. The lookup gives a decision date of 1932-12-19.

On the Claude side the cause is structural. The existence pass is given bare reporter strings and asked only whether each resolves. Nothing compares the resolved case name and date with what the draft printed. That has been true in every committed version of the skill. It is being fixed in Claude Code plugin 1.6.11 with a deterministic comparison in the workflow script.

The evidence is outside this repository, on Dan's Mac Studio: `~/ClaudeCode/legal-research-app/Experiments/E0/RECORD.md`, the fixture generator `make_citecheck_fixture.py` beside it, and the run folder `runs/cite-check-20261123T194020Z/` (not committed).

## 2. The Codex skill

Read from the code and the references; not run.

**The same gap is in the lookup script.** In `codex/cite-check/scripts/check_cite.py`, `screen()` returns `case_name` and `date_filed` for a matched citation and stops. The `--name` option feeds only the fallback searches for an unmatched citation. A matched lookup is therefore reported as `found: true` whatever the draft called the case and whatever year it gave.

**The protocol does assign the comparison to the agent.** `references/verification-protocol.md` says to check the caption against a caption actually printed in the footnote or body, it has the finding categories `identity_error` and `metadata_error`, and schema v6 requires a boolean `identity_confirmed` on every external citation verdict, which `validate_run.py` enforces for a verified verdict.

**Nothing mechanical backs that up.** The run depends on each agent making the comparison and writing down the result. In the Claude run an agent did notice both problems, wrote them in a note, and the report dropped them. The Codex ledgers are stricter than that, but a verdict of `identity_confirmed: true` on a unit whose lookup returned a different case is not something the validator can currently see.

## 3. What is requested

Codex owns the Codex skills, so these are requests, not edits. Work only under `codex/cite-check/` and `codex/CHANGELOG.md` (and the Codex plugin's version, wherever it is recorded). The `claude-code/` tree is being edited by others on this branch at the same time: do not touch it, and do not run its tests as a gate.

1. **A deterministic comparison in the lookup.** When the draft's printed caption or year is available for a citation, `check_cite.py` compares it with the resolved `case_name` and `date_filed` and says so in the row, in fields of your choosing: for example a caption result of match, mismatch, or not supplied, and a year result of match, mismatch, or not supplied, each with the two values compared. The draft's caption must come from the draft: the text handed to the script, the prepared units, or an argument. It is never inferred from the lookup's own result. A nameless reporter cite stays legitimate and yields no caption comparison, as the protocol already says. Decide how batch input supplies the caption and year for each citation; the citation-lookup response may give each citation's position in the submitted text, which would let the script read the caption before it and the year parenthetical after it, but confirm that against the live API or its documentation before relying on it.

2. **The comparison rules.** High precision on names: a false flag on every abbreviated caption would teach users to ignore the finding.
   - Must be flagged: `Sherman v. United States` against a resolved `Thomas v. Arizona`; any pair with no distinctive party word in common.
   - Must not be flagged: Bluebook abbreviations against spelled-out captions (Bd./Board, Educ./Education, Dep't/Department, Ass'n/Association, Comm'n/Commission, Nat'l/National, Int'l/International, Univ./University, Co., Corp., Inc.); an acronym in the draft against a spelled-out agency where another distinctive party word still matches; `In re`, `Ex parte`, `ex rel.`; first names and long party lists in CourtListener captions (`United States v. Mathews` against `United States v. Frederick Mathews`); `et al.`; punctuation and letter case.
   - Generic party words (United States, State, People, Commonwealth, City, County and the like) do not by themselves establish a match and do not by themselves establish a mismatch. `party_tokens()` and `PARTY_NOISE` in the script are a starting point.
   - Year: a mismatch when both the draft's year and the resolved date are present and the years differ. No finding when either is absent.
   - The Claude side is writing the same rules into its workflow today. Once both exist they should agree on the cases above; say in your handoff what your rules do with each, so the two can be compared.

3. **A mismatch cannot be dropped.** A caption or year mismatch from the deterministic screen must reach the run's ledgers and be resolved in the open. `validate_run.py` should refuse a ready run in which a unit's screen reported a mismatch while its verdict says `identity_confirmed: true` and `status: verified` with no recorded resolution. A resolution is either a finding (`identity_error` or `metadata_error`, under the existing evidence rules for those categories) or an explicit record of why the mismatch is not an error, with the evidence opened. The report then shows the finding, stating what the draft printed and what the lookup returned, and that either the name or the reporter cite may be the part that is wrong.

4. **Protocol and skill text.** Update `SKILL.md`, `references/verification-protocol.md`, `references/ledger-fields.md` and `references/case-review.md` where they describe the lookup, so the comparison is described as something the script does and the agent must resolve, not something the agent may do.

5. **Tests.** Offline, in the style of `test_check_cite.py` and the validator tests: the two live cases above; a table of name pairs that must and must not be flagged; the year rules; a nameless reporter cite; a run that the validator refuses because a mismatch was confirmed without a resolution, and the same run accepted once the mismatch is a finding. No network and no token in tests.

6. **Release notes.** An entry in `codex/CHANGELOG.md` and the Codex plugin version bump, as for 1.7.4. State plainly what was and was not run.

## 4. What is not asked

- Do not change what the lookup treats as found or not found, the fallback searches, or the rate-limit handling.
- Do not port to the private skills repository; that is done separately after review.
- A live Codex cite-check on the fixture would show whether the skill, as it stands today, would have caught the two cases through the agent's own comparison. It has not been run: Codex has no CourtListener token on the Mac Studio. If you can run it where the token is available, record the result; otherwise say it was not run.

## 5. Delivery

Leave the work uncommitted. Write your handoff as a new file in `reviews/`, named `2026-11-23-codex-case-identity-response.md`: what changed per file, the commands run with their real results, how your name rules treat each case in section 3, any disagreement with this note, and what was not verified.
