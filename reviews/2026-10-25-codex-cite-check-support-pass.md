# Review: Codex cite-check proposition-support pass (commit 061d2ab)

Date: 2026-10-25
Reviewer: Claude (Claude Code side), on branch `cite-check-proposition-support` (PR #1)
Subject: `codex/cite-check` changes in commit 061d2ab, implementing the memo
"opt-in proposition-support pass for the Codex cite-check skill"

Every finding below was reproduced against the code at 061d2ab, either by the
reviewer or by an independent review agent whose probe scripts are not kept in the
repository. Line numbers refer to 061d2ab. Nothing here is a hunch.

Overall: the implementation is faithful to the memo and in several gates stricter
than the memo asked. Its new test program passes on Python 3.11 through 3.13. Items 3
through 6 and 12 trace back to regexes copied from the Claude Code side; those were
fixed on the Claude side in commits abd96b9 and the one that adds this file, and the
Codex side still needs the equivalent changes. The "Claude side" column says what
happened there so the two implementations do not drift.

## Must fix

| # | Finding | Where | Claude side |
|---|---|---|---|
| 1 | **A `partial` verdict can escape the limits gate in any v7 run.** The exemption that lets `support_overstated` be `partial` without an `unlock_path` keys only on the verdict's category, not on the unit being a support unit that carries a `support` object. A quoted unit relabelled `category: support_overstated, status: partial` with no `support` object and no `unlock_path` passes `validate_run.py --require-ready` with `completion_target: complete`; identical ledgers fail as v6 ("unchecked items require complete_with_limits", "lacks unlock_path"). `support_validation.py` only inspects verdicts that have a `support` object, so it does not catch this. | `validate_run.py:597`; `support_validation.py:192-194` | n/a (no validator) |
| 2 | **"Compare A, with B" is not split and `compare with` is rejected as a signal.** `Compare Roe v. Wade, 410 U.S. 113, 153 (1973), with Doe v. Bolton, 410 U.S. 179, 190 (1973).` is one clause, signal `compare`, pincite 153; Doe v. Bolton is swallowed. If the lead creates B by hand with `signal: "compare with"`, the gate says "invalid signal". The updated memo (section 3.2) makes the split binding. | `support_screen.py:66-74, 84-94`; `support_validation.py:18, 114` | fixed (a0fc550, f8c5f7c): `_split_compare_with`, signal `compare with` |
| 3 | **Court/date, access-date, editor and file parentheticals are returned as the proposition parenthetical.** `(S.D.N.Y. Mar. 3, 2020)`, `(Jan. 5, 2020)`, `(last visited Jan. 5, 2020)`, `(Jane Doe & John Roe eds., 2010)`, `(on file with author)` all come back as a proposition. Consequences: a whole-work slip-opinion cite becomes `scope: pincited`, and a date string is a valid verbatim `claim_basis: parenthetical`. The `_NON_PROP` character classes have no comma, so any dated parenthetical passes. | `support_screen.py:156-172`; `prepare_support_units.py:53` | fixed (abd96b9): a parenthetical that ends in a year, or starts with a file/access/editor/docket word, is never a proposition unless it starts with a verb |
| 4 | **Spurious pincites from titles and docket numbers.** `Jack Balkin, Brown at 50: The Legacy, 90 Va. L. Rev. 1537 (2004).` yields pincite `50` (AT_PIN runs before the article rule). `See Smith v. Jones, No. 19-123 (S.D.N.Y. Mar. 3, 2020).` yields kind `book` and pincite `19-123` (BOOK_PIN matches the docket number). | `support_screen.py:99, 104, 112-114, 131-134` | fixed (abd96b9): "at N" counts only after a comma or period; a number after "No." or "Vol." is never a book page |
| 5 | **A posture note is matched anywhere in a parenthetical.** `(rejecting the dissenting view that the rule is absolute)` becomes `opinion_note` and the proposition parenthetical is lost. Anything containing "dissenting", "concurring", "plurality opinion", "per curiam" is treated as the draft's declared posture. | `support_screen.py:161-162, 175-181` | fixed (abd96b9): the shape is anchored ("Thomas, J., concurring", "Roberts, C.J., dissenting", "Kagan & Sotomayor, JJ., dissenting", "opinion of Roberts, C.J.", "plurality opinion", "per curiam", "en banc", "statement of ...") |
| 6 | **A signal preceded by prose or markdown italics reads as no signal.** `For a contrary view, cf. Smith v. Jones, 100 F.3d 200, 205 (2d Cir. 1996).` gives `""` (direct support) instead of `cf.`; `*See* Smith v. Jones` (common in .md drafts) gives `""`. This is the signal-misread artifact the pass exists to avoid, produced by the screening aid itself. | `support_screen.py:84-94` | fixed (abd96b9): `*`/`_` stripped before matching; a signal after a prose prefix that contains no digit is read |

## Should fix

| # | Finding | Where | Claude side |
|---|---|---|---|
| 7 | **Rules and unsectioned statutes fall out of scope.** `See Fed. R. Civ. P. 12(b)(6).` is `kind_hint: text` with no pincite; `prose_clauses` returns the cite text itself as note prose (so the cite satisfies `claim_basis: note_prose`); with lead `source_type: rule` the unit is whole-work and unread by default. Same for `Fed. R. Evid. 403.` and `42 U.S.C. 1983.` (no `§`). Treat statute and rule source types as located. | `support_screen.py:184-193, 203-215`; `prepare_support_units.py:53-54` | the ledger already classed these as statutes (pincited); the locator now reads the rule number and the unsectioned code section |
| 8 | **Body citations in their own citation sentence get an anchor that is the citation itself.** For `The rule applies to everyone. Roe v. Wade, 410 U.S. 113, 153 (1973). Next sentence.` the synthesized marker precedes the cite text, so `anchor.sentence` is the citation sentence, `position` is `mid-sentence`, `clause` is empty, and the real proposition is in `previous`, which is not an allowed `claim_basis`. The lead cannot record the proposition for a brief-style body cite without tripping the verbatim gate. | `prepare_support_units.py:56-65`; `support_validation.py:143-147` | n/a (the Claude ledger inventories footnotes only; body citations are a known gap on that side) |
| 9 | **`--page` cannot read the page before the first star or explicit marker**, although the matcher assigns that text `first-1`. `Intro text *431 First *432 Second` → `printed_page` reports the intro as page 430, but `read_pages(raw, '430')` raises "unavailable; available page range: 431-433". A pincite to an opinion's first page gets "unavailable". | `verify_quotes.py:643-646` vs `:216-219` | not affected (`--page` serves the segment before the first marker as `first-1`); a test now locks that in |
| 10 | **Support findings can effectively never be resolved on a re-run under the default scope.** `support_complete` is false whenever `counts.support.out_of_scope > 0`, which is true for any draft with one whole-work cite under scope `pincited`. Two complete runs at the same scope with a support finding absent in the second give `resolved: 0, not_rechecked: 1`. Compare per unit (was the prior finding's unit in scope and read this run). | `findings_diff.py:101-105, 115-116` | had the opposite defect (a run without the pass resolved everything); fixed (abd96b9): absent support findings are "not rechecked" when the pass did not run or ran at another scope |
| 11 | **Unreferenced docx footnotes now change v6 runs.** A .docx with a footnote that has no body reference, initialized without `--support`: `footnote_count` rises, `footnote-coverage.jsonl` gains `{"footnote_number": null, "note_id": "fn:N", "status": "pending"}`, and the v6 gate then requires the lead to review it; the note has no `custom_mark`, so report display code that treats number-null notes as author's notes sees a null label. `supra_problem_candidates` rows for such notes carry `footnote_number: None`. The changelog says v6 contracts are unchanged. Either flag them (`unreferenced: true`, excluded from expected coverage, listed as a warning) or document the new requirement. | `extract_cites.py:323-331`; `init_run.py:75-79` | not affected (unreferenced notes are warned about and excluded) |
| 12 | **Footnote prose that follows a citation in the same sentence run is not captured.** `Scholars disagree. See A, 1 U.S. 2 (2000). For the contrary view, see B, 2 U.S. 3 (2001).` gives `note_prose: ['Scholars disagree.']` only: the "For the contrary view" prefix is skipped because the prefix text contains a citation. | `support_screen.py:203-215` | the same merge existed in the ledger's clause splitter (B became a nested cite and was dropped from the support units); fixed in the commit that adds this file: a sentence break after a citation starts a new clause |

## Low

| # | Finding | Where |
|---|---|---|
| 13 | The overstatement-placement gate recognizes only a `#` heading for "Needs your attention". `attention_section("**Needs your attention**\nU3: ...")` returns `''`, so an overstatement under a bold or plain heading passes. Conversely a deeper heading after it (`## Needs your attention` ... `### Proposition support`) is swallowed into the section, and a correctly placed overstatement is rejected. | `support_validation.py:54-59, 185-191` |
| 14 | Minor gate gaps: the word "budget" anywhere in the report satisfies unread disclosure (`reason not in report`); an audit's `initial_support_verdict` is not tied to the final verdict (a `confirmed` audit with initial `contradicted` on a final `not_supported` passes); a one-word claim such as `rule` passes the verbatim substring check; `siblings` for body units counts every body unit (`note_key` is `None` for all of them). | `support_validation.py:128, 146, 162-177`; `prepare_support_units.py:74-76` |

## Verified correct

- `pin_for`: an own `at N` wins; a bare `Id.` inherits through multi-step chains, including from a `supra ... at 50` antecedent; a bare supra or a full cite never inherits; the chain stops at a non-Id. row with no pin; the gate rejects a chain whose antecedent follows the instance or changes source.
- `eligible`: quoted units (via quote checks or `prepared_unit_ids`), nested `(quoting ...)` cites, internal and prose units, and unresolved Id./supra are excluded; a statute with `§` and a URL are `pincited`.
- `--refresh-counts` preserves `budget` and `agent_failure` reasons by unit id and never overrides `out_of_scope`; `init_run.py` creates `quote-checks.jsonl`, so running `prepare_support_units.py` before `verify_quotes.py` does not crash.
- v6 isolation: every exemption is guarded by `support_enabled`, which also requires `schema_version == 7`; a v6 manifest with `support_pass.enabled` is rejected; the existing v6 fixture validates unchanged (subject to item 11).
- Gates that work: `overstated` at medium or as `mismatch` rejected; `support_mismatch` / `support_contradicted` without an audit rejected in both validators; `contradicted` on a contrary signal rejected; an in-scope unit with neither a support object nor an `unread_reason` rejected; counts reconciliation is exact; the support sentence must immediately follow the existence-only line; a `support` object on an excluded unit rejected; `unverifiable` requires `unverified`, an `unlock_path` and `support_read: false`; each of the six audit artifact classes needs its own explanation.
- `read_pages`: form-feed numbering matches the quote matcher in all three cases (a text cover is `first_page`; a whitespace-only cover or a leading form feed is dropped by both); `431-32` and `431–32` ranges; a page beyond the file errors with the range; the no-boundary advice; `--marker-follows` footer mode is consistent with the matcher; `--page` refuses the output modes; truncation at 12,000 characters.
- `split_clauses`: splits on `;` outside parentheses and curly or straight quotes, and on `. See|Cf.|But see|Compare|Accord|Contra|E.g.,|Id.` outside parentheticals; `(holding "one; two")` and `"one. See two"` are handled; `signal_of` normalizes `See, e.g.,`, `See e.g.,` and `E.g.,`.
- `locate`: a case pin after a parallel-reporter parenthetical (`5 U.S. (1 Cranch) 137, 177`), `at N`, `at N n.4`, the article page, a book page before an edition parenthetical, `§ 1983(a)`, `¶ 12`; subsequent-history strings (`cert. denied ...`) produce no false pin.
- `findings_diff.key_of` for support items ignores the footnote number and differs by category and verdict; a run without the pass marks prior support findings `not_rechecked`.
- `footnote_anchors`: sentence-end versus mid-sentence, the clause text, the previous sentence across a paragraph break, the block-quote flag, first occurrence wins for duplicate markers; orphan markdown and docx notes get `anchor: null` plus a warning.

## Suggested order of work

1. Item 1 (gate leak), then items 2 through 6 (screener), which are small regex changes with the Claude-side versions available for comparison in `claude-code/skills/cite-check/scripts/citation_ledger.py` (`signal_of`, `locate`, `proposition_parenthetical`, `opinion_note`, `_split_compare_with`).
2. Items 7, 9 and 12 (scope and reading).
3. Items 8, 10 and 11 (design calls: body-cite anchors, per-unit re-run resolution, orphan notes), which the author should decide.
4. Items 13 and 14 as time allows.

Add an offline check for each item fixed, in `test_support.py`, with the failing input from this file.
