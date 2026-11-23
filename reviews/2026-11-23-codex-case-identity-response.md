# Codex response: deterministic case identity and year screening

Date: 2026-11-23
Requested branch: `workflow-fixes-1.6.11`
Release: Codex plugin 1.7.5
Status: implemented and tested offline; all Codex work left uncommitted.

Read the complete [handoff](2026-11-23-claude-case-identity-handoff-for-codex.md)
and all named Codex files before editing. Applied the Codex skill-creator
guidance. No substantive disagreement with the handoff. No subagents were used.

## What changed, by file

All paths in this table are repository-relative.

| File | Change |
| --- | --- |
| `codex/cite-check/scripts/check_cite.py` | Added deterministic caption/year comparison, `--year`, per-unit `--units-file` JSONL input, and exclusive-create `--output` JSONL output. Each row retains both compared values and comparison statuses. Existing `found`, lookup-state classification, fallback functions, search token selection, and rate-limit handling remain unchanged. |
| `codex/cite-check/scripts/identity_validation.py` | New offline gate: reconciles case-unit coverage, checks draft-grounded inputs, recomputes comparisons, requires separate evidenced resolutions for each mismatch, and checks report disclosure. Supports explicit unavailable-screening records and direct identity verification from an opened record. |
| `codex/cite-check/scripts/validate_run.py` | Invokes the new gate for new runs and any older run containing a screen ledger. Applies the existing metadata-record rules to year findings even when a combined finding's main category is `identity_error`; the record must identify `year`. |
| `codex/cite-check/scripts/init_run.py` | Sets `case_identity_version: 1` on new runs. The helper creates the screen ledger; the initializer does not pre-create a file that the exclusive output writer would refuse. |
| `codex/cite-check/scripts/prepare_source_bundle.py` | Includes the source's per-unit screen rows in worker packets, alongside the original citation units. |
| `codex/cite-check/scripts/findings_diff.py` | Preserves structured identity resolutions in adverse findings snapshots, including both discrepancies when a unit has caption and year errors. |
| `codex/cite-check/scripts/test_check_cite.py` | Added nine offline tests covering the handoff fixtures, the name-pair table, missing/generic captions, year rules, ambiguous lookup, repeated-citation input binding, CLI JSONL output, overwrite refusal, and missing credentials. Existing sibling-helper tests remain unchanged. |
| `codex/cite-check/scripts/test_case_identity.py` | Added twelve offline integration tests for failed readiness without resolution; successful finding/dismissal paths; metadata provenance; per-dimension resolution; report omission; stale or dropped screens; draft grounding; source packets; unavailable screening; and the existing high-severity audit requirement. |
| `codex/cite-check/scripts/test_case_review.py` | Explicitly retains its pre-identity-screen compatibility fixture by removing the new extension flag from that fixture's in-memory manifest. New-extension coverage lives in the new integration suite. |
| `codex/cite-check/scripts/test_support.py` | Makes the same compatibility-fixture adjustment for its pre-extension support run. |
| `codex/cite-check/SKILL.md` | Makes comparison preservation and resolution part of the workflow; documents per-unit input, output preservation, coverage, source packets, and report obligations. |
| `codex/cite-check/references/verification-protocol.md` | Describes deterministic comparison, its limits, required resolution, and the new ledger. |
| `codex/cite-check/references/ledger-fields.md` | Specifies all input, comparison, resolution, unavailable-screening, and report fields; gives commands and compatibility rules. |
| `codex/cite-check/references/case-review.md` | Places identity resolution before history and distinguishes a lookup hit from confirmation of the draft's authority. |
| `codex/CHANGELOG.md` | Adds 1.7.5, including actual offline test results and the work not performed. |
| `codex/.codex-plugin/plugin.json` | Bumps the Codex plugin from 1.7.4 to 1.7.5. |
| `reviews/2026-11-23-codex-case-identity-response.md` | This response. |

## Input association and preservation

The batch interface accepts case citation units with `unit_id`, `source_id`,
`lookup_citation`, `draft_case_name`, and `draft_year`. Caption/year fields must
be explicit, with null for an absent value. Each unit's lookup is requested
separately, so repeated reporter citations can carry different draft captions
or years without mixing their metadata. Non-case units are ignored.

No API position field is used, and none was assumed to exist. This selects the
handoff's explicit-input alternative without needing network documentation or
live API inspection. Plain text batches do not infer captions or years;
single-citation callers can use `--name` and `--year`.

New runs require `case-identity-checks.jsonl` with one row per case citation
instance, including an explicit `not_screened` record if API screening cannot
be performed. Verified unscreened citations require declared direct inspection
of an identity record. Older runs retain their prior contract, but a screen
ledger present in an older run is still checked.

A mismatch cannot coexist with a clean verified verdict without an explicit
`not_error` resolution containing an opened-evidence declaration, locator,
evidence, and reason. Alternatively, it becomes an adverse `identity_error` or
`metadata_error` finding under the existing provenance and audit rules. Each
dimension needs its own resolution. The report must retain both compared values
and the disposition. Caption findings also state that either the name or the
reporter citation may be wrong. Dismissals belong in the full ledger with their
reason, outside findings sections.

Original screening output must be preserved on retries. The output option
refuses existing paths. The protocol forbids replacing a recorded mismatch with
an unscreened record. As with the existing ledgers, the gate checks supplied
records and declared provenance; it does not authenticate an API response or
prove that a person actually opened the stated evidence.

## How the name and year rules treat the requested cases

These are offline test fixtures, including the values supplied by the handoff;
they are not independently verified CourtListener or official case metadata.

The comparison removes punctuation/case differences, expands the listed
abbreviations, and excludes generic party, organization, and procedural words.
It considers every remaining word in each caption. Any shared distinctive word
yields screening `match`; disjoint nonempty sets yield `mismatch`. If either
side has no distinctive words, the result is `indeterminate`. Thus a generic
word alone establishes neither agreement nor disagreement.

| Draft / lookup comparison | Result |
| --- | --- |
| Sherman v. United States, 356 U.S. 396 (1958) / Thomas v. Arizona, filed 1958-06-30 | Caption `mismatch`; year `match`; `found` remains true. |
| Sorrells v. United States, 287 U.S. 435 (1934) / Sorrells v. United States, filed 1932-12-19 | Caption `match`; year `mismatch`; `found` remains true. |
| United States v. Sherman / United States v. Thomas | `mismatch`: the shared generic United States does not hide distinct parties. |
| State v. Adams / State v. Jones; People v. Smith / Commonwealth v. Brown | `mismatch`. |
| City of Austin v. County of Travis / City of Dallas v. County of Denton | `mismatch`: City and County supply no distinctive overlap. |
| Bd. of Educ. v. Allen / Board of Education v. Allen | `match`. |
| Dep't of Revenue v. Davis / Department of Revenue v. Davis | `match`. |
| Ass'n of Builders v. Jones / Association of Builders v. Jones | `match`. |
| Comm'n v. Brown / Commission v. Brown | `match`. |
| Nat'l Bank v. Smith / National Bank v. Smith | `match`. |
| Int'l Union v. Brown / International Union v. Brown | `match`. |
| Univ. of Michigan v. Doe / University of Michigan v. Doe | `match`. |
| Acme Co., Corp., or Inc. v. Doe / corresponding spelled-out Company, Corporation, or Incorporated caption | `match` for each variant. |
| EPA v. Brown / Environmental Protection Agency v. Brown | `match` through Brown; no general acronym expansion is claimed. |
| In re Gault / In the Matter of Gault | `match` through Gault. |
| Ex parte Young / Young | `match` through Young. |
| United States ex rel. Smith v. Jones / United States on behalf of Smith v. Jones | `match` through the distinctive parties. |
| United States v. Mathews / United States v. Frederick Mathews | `match` through Mathews. |
| Smith v. Jones / John Smith, Mary Smith, and James Doe v. Robert Jones et al. | `match`; additional first names and parties do not cause a flag. |
| SMITH, ET AL. v. JONES / Smith v Jones; O’Connor v. Jones / O'Connor v. Jones | `match`; case, punctuation, apostrophe variants, and et al. are tolerated. |
| United States / State; People / Commonwealth; City v. County / State v. People | `indeterminate`, not a mismatch or positive match. |
| United States / United States v. Mathews; State v. Smith / People | `indeterminate` because one side is generic-only. |
| Nameless 356 U.S. 396 / Thomas v. Arizona | Caption `not_supplied`; the returned name is never substituted for draft input. |
| Draft 1932 / resolved 1932-12-19 | Year `match`. |
| Missing draft year / resolved date present | Year `not_supplied`; no mismatch. |
| Draft year present / resolved date absent | Year `resolved_unavailable`; no mismatch. |
| Ambiguous lookup with multiple candidates | Both supplied comparisons remain `resolved_unavailable`; the first candidate is not treated as a confirmed identity. |

The abbreviation tests also exercise each listed abbreviation with an Acme
caption and no opposing-party shortcut. This is deliberately a high-precision
screen, not a case-identity adjudicator: common distinctive words can hide a
different case, unfamiliar abbreviations can need human resolution, and the
lead must confirm which draft year/party context belongs to the citation.

## Commands and actual results

Read-only repository inspection used `pwd`, `git status --short`,
`git branch --show-current`, `rg`, `cat`, `head`, `sed`, and `wc`. The starting
branch was `workflow-fixes-1.6.11`. No Git command that writes was run. No
Claude-side file was opened for style or edited; Git status merely showed
concurrent changes in that tree.

`/usr/bin/python3 --version` returned Python 3.9.6.

Initial focused commands, before the last test additions:

```bash
env -u COURTLISTENER_TOKEN -u COURTLISTENER_API_TOKEN PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 codex/cite-check/scripts/test_check_cite.py
env -u COURTLISTENER_TOKEN -u COURTLISTENER_API_TOKEN PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 codex/cite-check/scripts/test_case_identity.py
```

Both exited 0: 14 tests and 9 tests, respectively. The complete suite was then
run twice; the second run includes all final test additions and the final code.
Both complete runs passed. The final invocation was:

```bash
env -u COURTLISTENER_TOKEN -u COURTLISTENER_API_TOKEN PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
from pathlib import Path
import subprocess
import sys
paths = sorted(Path('codex/cite-check/scripts').resolve().glob('test_*.py'))
failures = []
for path in paths:
    result = subprocess.run([sys.executable, str(path)], cwd=str(path.parent), capture_output=True, text=True)
    print('{} {} (exit {})'.format('PASS' if result.returncode == 0 else 'FAIL', path.name, result.returncode), flush=True)
    print((result.stdout + result.stderr).strip(), flush=True)
    if result.returncode:
        failures.append(path.name)
print('TOTAL: {} programs; {} passed; {} failed'.format(len(paths), len(paths) - len(failures), len(failures)), flush=True)
sys.exit(bool(failures))
PY
```

Final result: exit 0; **19 programs passed, 0 failed**. This includes 177
unittest tests and four standalone assertion-based programs, with 21 new
unittest tests added by this change. Every test used the system Python 3.9.6.
The new lookup tests forbid network access and real credential reads; their
responses are mocked, and the CLI success test uses only a boolean auth-presence
stub. Neither environment token variable was passed to the test processes.

| Program in `codex/cite-check/scripts/` | Final result |
| --- | --- |
| `test_audit_outcomes.py` | 3 tests, pass |
| `test_cache_recovery.py` | 20 tests, pass |
| `test_case_history.py` | 10 tests, pass |
| `test_case_identity.py` | 12 tests, pass |
| `test_case_review.py` | 9 tests, pass |
| `test_check_cite.py` | 16 tests, pass |
| `test_cost_controls.py` | 15 tests, pass |
| `test_extraction_numbering.py` | Standalone assertions, pass |
| `test_findings_diff.py` | 7 tests, pass |
| `test_library_options.py` | 10 tests, pass |
| `test_readiness_safety.py` | Standalone assertions, pass |
| `test_review_regressions.py` | 20 tests, pass |
| `test_run_options.py` | 15 tests, pass |
| `test_snapshot.py` | 1 test, pass |
| `test_support.py` | 16 tests, pass |
| `test_support_review.py` | 16 tests, pass |
| `test_support_sample.py` | 7 tests, pass |
| `test_validate_schema_v3.py` | Standalone assertions, pass |
| `test_verify_quotes.py` | Standalone assertions, pass |

Additional static checks imported `run_tests.py` as a module and set its
in-memory `ROOT` to `codex/cite-check` before calling only `compile_python()`,
`check_markdown_links()`, and `check_frontmatter()`. They exited 0: 38 Python
files parsed, 0 failures; 21 relative Markdown links checked, 0 broken; one
SKILL.md checked, 0 problems. A standard-library JSON/regex check confirmed
plugin version 1.7.5 matches the dated changelog entry. This used the repository's
standard-library checks instead of the skill-creator validator's PyYAML import.

`git diff --check -- codex/cite-check codex/CHANGELOG.md
codex/.codex-plugin/plugin.json` exited 0, with no whitespace errors. Read-only
scoped diff inspection confirmed the unchanged fallback/search/rate-limit
functions. New files were also inspected directly because ordinary `git diff`
does not include untracked files.

## What was not verified or performed

- No live cite-check was run. No network calls were made and no token was used.
  Credential availability was not probed, and no configuration was changed.
- No claim that the existing Codex agent workflow would have caught the original
  six-footnote live fixture. That would require the separate live experiment.
- No live API response shape/position-field verification, official case-record
  research, or empirical false-positive/false-negative measurement beyond the
  offline fixtures. The two handoff case results are mocked, not new API evidence.
- No Claude-side tests or root-wide test run. Accordingly, this response makes
  no claim about the concurrent Claude work or its test results. Importing the
  root runner for the narrowly scoped static checks did not execute its test
  runner or Claude manifest checks.
- No private-skill port, installed-skill edit, network installation, new
  dependency, commit, stage, stash, checkout, reset, or restore. No repository
  file was deleted or replaced by move/copy/redirection. The test suites used
  their existing temporary fixtures and cleanup routines.

The remaining review step is comparison with the independently implemented
Claude rules. I did not read that implementation to make the two look alike.

## Post-delivery quotation-hook verification

The stop hook flagged wording in two concurrently edited Claude skill files.
After implementation and testing, I read those files with separate, read-only
`cat` commands solely to verify the flagged wording. In
`claude-code/skills/find-cite/SKILL.md`, the flagged strings appear as example
user requests in the frontmatter description and example propositions or
constraints in section 1. In `claude-code/skills/cite-check/SKILL.md`, the two
flagged strings are report-section labels in the frontmatter description.
They are not attributed quotations from courts or scholars. This inspection
made no Claude-side changes and supplied no style or implementation guidance
for the completed Codex patch. No code changed after the passing test run.

The hook repeated the same failure after those reads. Read-only inspection of
`~/.codex/hooks.json` and its configured
`/Users/dan/ClaudeCode/research-skills-private/codex/hooks/quote_guard.py`
identified the cause: `snapshot()` scans the whole workspace; `handle()` treats
all files changed since its baseline, plus pending files, as deliverables without
distinguishing concurrent authors; and `local_source()` refuses a changed file
as its own quotation evidence. Thus reading the flagged Claude files cannot
clear these example-prompt and section-label findings. The hook remains failed
on those unrelated files. I did not modify its configuration, implementation,
or state, or change the Claude files to silence it; all are outside this work
package's authorized edit scope. The Codex test results above remain valid.

## Review follow-up: sovereign names

Accepted the follow-up correction. `check_cite.py` now recognizes all 50 states,
the District of Columbia, Puerto Rico and Guam, including their Bluebook
abbreviations. It consumes the longest complete name before comparing other
words, so New York, West Virginia and North Carolina cannot leave shared
fragments. Each caption excludes sovereign names when other distinctive words
remain; otherwise it compares canonical whole sovereign names. Fallback search,
lookup-found status and year comparison are unchanged.

The added `test_check_cite.py` cases confirm:

- Mapp v. Ohio / Terry v. Ohio, Arizona v. Gant / Arizona v. Fulminante, and
  Miranda v. Arizona / Thomas v. Arizona all return `mismatch`.
- Arizona v. California matches itself and Ariz. v. Cal., but mismatches
  Texas v. New Mexico and Tex. v. N.M.
- New York v. Quarles mismatches New York Times Co. v. Sullivan; the latter
  matches itself and its N.Y. abbreviation.
- All 53 sovereign names match their corresponding abbreviation; a shared
  sovereign never clears different distinctive parties. Multi-word names,
  spaced/unspaced initials, and a non-state phrase such as New Yorker are covered.

Updated the three protocol references and the existing 1.7.5 changelog entry.
Before the fix, running the new
`DraftComparisonTests.test_shared_sovereigns_do_not_clear_distinct_parties`
method exited 1 with eight failing subcases, including all three reported pairs.
After the fix, the full `test_check_cite.py` command documented above exited 0
with 19 tests passing. Re-ran the same full-suite harness documented above on
`/usr/bin/python3` 3.9.6: **19 programs passed, 0 failed**, comprising **180
unittest tests plus four standalone assertion programs**. The three additional
test methods bring this release's new-test count to 24. The scoped
`git diff --check` also passed. No network, token use, Git writes, or Claude-side
inspection/changes occurred during this follow-up. All work remains uncommitted.

## Final review follow-up: prefixes and one-edit spellings

Accepted both requested agreement rules in `check_cite.py`: a prefix qualifies
when its shorter word has at least four letters; otherwise one insertion,
deletion or substitution qualifies when both words have at least five letters.
Transposition and two-edit differences do not qualify under the edit rule.
Nonexact matches retain both normalized words and the applicable rule in
`word_agreements`; `shared_words` remains the exact overlap. Updated the protocol,
ledger reference and 1.7.5 changelog accordingly.

Both new regression pairs now return `match`: McCulloch v. Maryland against
M’Culloch v. State of Maryland, and Commonwealth v. Mass. Elec. Co. against
Commonwealth v. Massachusetts Electric Company. All existing must-flag tests
still pass. The suite expressly retains `mismatch` for Mapp/Terry, Gant/Fulminante,
Miranda/Thomas, Lopez/Morrison, Roe/Doe, and Quarles/New York Times, using the full
captions in the review request. Additional tests exercise both directions,
length cutoffs, insertion/deletion/substitution positions, the non-prefix
mfrs/manufacturers pair, transpositions, and two-edit differences.

Before the fix, the new
`DraftComparisonTests.test_prefix_and_old_reporter_spelling_agreement` method
exited 1 with both requested pairs failing. Afterward, the documented offline
`test_check_cite.py` command exited 0 with **21 tests passing**. Re-ran the same
full-suite harness on `/usr/bin/python3` 3.9.6: **19 programs passed, 0 failed**,
comprising **182 unittest tests plus four standalone assertion programs**.
The two new methods bring the release's added-test count to 26. Scoped
`git diff --check` passed. No network, token use, Git writes, Claude-side changes,
or hook investigation occurred. All work remains uncommitted.
