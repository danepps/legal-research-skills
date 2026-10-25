# Codex review of Claude's proposition-support pass

Date: 2026-10-25
Reviewer: Codex
For: Claude and Daniel Epps
PR: [#1](https://github.com/danepps/legal-research-skills/pull/1)
Reviewed commit: `d39756b0d5bc77334dce69b662506ad2d769e411`

## Scope and recommendation

This review covers the Claude Code implementation of the opt-in proposition-support pass, including the latest screening and rerun-diff edits at the commit above. It does not review the Codex implementation.

Fix the four findings below before merging. The main gaps are in accepting agent output, enforcing independent review, and preserving the final verdict through reporting and reruns. The extraction helpers' existing tests pass, but those tests do not establish that the workflow handles these cases correctly.

The independent-review and reporting findings conflict with the author's fixed decisions: every not-supported or contradicted conclusion needs a second derivation before reporting; qualified support remains an advisory; limited reruns must not silently resolve findings.

## 1. [P1] Unaudited adverse conclusions still reach the report

**Location:** [workflow audit scheduling and reconciliation](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L1332-L1346), [report formatting/filter](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L1610-L1620).

When `tight(supportToReverify.length * 6000)` is true, the workflow skips the support audit and records a degradation message. If a reviewer fails, the missing result is handled similarly. In either case, `if (!rv) continue` leaves the original adverse verdict unchanged.

The report filter excludes artifacts, but does not exclude unaudited adverse findings. The formatter adds “SINGLE-CHECKER — not re-verified”; it does not withhold the conclusion.

**Reproduction:** execute the workflow's audit/reconciliation block with one `contradicted` finding and a stubbed `tight() => true`. Observed:

```json
{
  "reportedAdverse": 1,
  "ledgerEntries": [[0, "contradicted"]],
  "degradation": [
    "support re-verify skipped for 1 findings (budget) — flagged as single-checker"
  ]
}
```

**Recommendation:** reserve audit capacity before increasing support coverage. If an audit still cannot finish, retain the attempt for resumption but mark the conclusion unverified and exclude it from confirmed adverse sections and counts. A warning label is not a substitute for the required second derivation.

**Regression tests:** budget exhausted before audit; reviewer returns no result; reviewer returns an invalid result. None may emit an unaudited confirmed `not_supported` or `contradicted` conclusion.

## 2. [P1] Agent output can claim support without source evidence or a matching source

**Location:** [support result schema](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L408-L427), [result join](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L1207-L1224).

The item schema requires only `id` and `verdict`. Passage, locator, claim, claim basis, posture, search evidence, and verification basis are optional. The join looks up the returned ID but does not verify its source key, evidence basis, or verbatim claim. It defaults missing evidence to empty strings and accepts the verdict.

**Reproduction:** for a unit belonging to `correct-source`, supply:

```json
{
  "id": 0,
  "sourceKey": "wrong-source",
  "verdict": "supported",
  "claim": "Invented stronger claim.",
  "basis": "citation-only"
}
```

The join accepts it as `supported`, assigns the unit's source label, retains the invented claim, and stores empty `sourceText`, `locator`, and `posture`. The read-count expression counts this verdict as checked.

**Recommendation:** validate every returned result before accepting it. Require an assigned, in-scope unit; a matching source key; an allowed full-text basis; a nonempty passage and locator for read verdicts; a claim occurring verbatim in the declared full unit field; and source-search evidence for adverse conclusions. Apply equivalent checks to reviewer output. Invalid responses should remain unchecked or unverifiable, with their reason disclosed.

Schema descriptions and prompt instructions are useful, but cannot replace these checks. Validate against full prepared units, not truncated compact claims.

**Regression tests:** wrong source key, out-of-scope ID, fabricated claim, citation-only basis, missing passage, missing locator, and missing adverse-search evidence. None should count as a completed support read.

## 3. [P2] A qualified-support downgrade is hidden and miscounted

**Location:** [audit reconciliation](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L1348-L1361), [support counts](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L1574-L1576).

The comment says a downgrade to qualified support stays reported. The code instead sets:

```javascript
f.artifact = rv.upheld === false &&
  ['supported', 'supported_qualified'].includes(corrected)
```

An independent reviewer correcting `contradicted` to `supported_qualified` therefore causes the final advisory to be filtered out. The counts also treat the artifact as ordinary supported, and the support ledger mapping drops it.

**Reproduction:** a first verdict of `contradicted`, followed by:

```json
{
  "id": 0,
  "upheld": false,
  "verdict": "supported_qualified",
  "posture": "dissent",
  "sourceText": "A source passage.",
  "locator": "p. 5"
}
```

Observed: `artifact: true`, `supported: 1`, `qualified: 0`, and an empty support ledger mapping.

**Recommendation:** separate the historical fact that the original finding was retracted from the final verdict's disposition. Keep `supported_qualified` in the advisory and qualified count. Preserve the final support disposition in the ledger even when the original adverse finding was withdrawn. A fully supported retraction should likewise remain recorded as read/supported in the ledger.

**Regression tests:** adverse-to-supported, adverse-to-qualified, and adverse-to-overstated corrections, checking the report lists, ledger, and counts together.

## 4. [P2] A limited rerun can falsely resolve an old support finding

**Location:** [diff comparability check](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/scripts/findings_diff.py#L70-L82), [exported findings metadata](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/cite-check/cite-check.workflow.js#L1860).

The diff treats a support finding as rechecked whenever the current pass ran and its scope matches the previous scope. It does not account for budget skips, agent failures, unavailable sources, focused coverage, or an incomplete run. The exported support metadata contains only `on`, `ran`, and `scope`.

**Reproduction:** previous findings contain one support contradiction. Current findings omit it, keep `ran: true` and `scope: "pincited"`, but describe a limited run with unchecked/unread units. The result is:

```json
{"resolved": ["the previous finding"], "not_rechecked": []}
```

**Recommendation:** export coverage evidence sufficient to determine whether the prior item was rechecked. Prefer per-instance/content-based coverage; at minimum, conservatively treat absent findings as not rechecked when the current support pass is incomplete or narrowed. Equal scope names do not establish equal actual coverage.

**Regression tests:** same-scope reruns with budget skips, failed agents, unavailable sources, and focused subsets. An old item omitted because it was not checked must remain not rechecked.

## Separate pre-existing issue: the CI failure exposes a library-resolution bug

**Location:** [configuration fallback](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/build-library/attach_pdf.py#L80-L106), [later application of the explicit library argument](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/claude-code/skills/build-library/attach_pdf.py#L108-L119).

This code was not introduced by the proposition-support changes. It nevertheless explains the failing upload/readback tests in CI.

`resolve_library()` decides whether configuration fallback is needed using the environment's library ID, before applying `--library`. A caller with a valid API key and an explicit library destination can therefore fail for lack of a configuration file, even though the needed inputs were supplied.

**Offline reproduction:**

```python
resolve_library(
    library="group:77",
    environ={"ZOTERO_API_KEY": "fake-test-key"},
    claude_json="/tmp/no-such-review-config.json",
)
```

This raises `ConfigError` instead of resolving group 77.

**Recommendation:** apply and validate the explicit destination before determining which missing fields need fallback configuration. Preserve lookup of a missing API key when necessary, but do not require a redundant configured destination. Keep a regression test with an API key, an explicit library, and no environment library ID or config file.

Supplying `ZOTERO_LIBRARY_ID=77` makes the mocked suite pass, but masks this execution path. My earlier description of this as merely a test-fixture issue was incomplete; the resolver itself should be corrected.

## Verification performed

All five existing Claude cite-check helper test programs passed at the reviewed revision:

- `test_citation_ledger.py`
- `test_extract_cites.py`
- `test_findings_diff.py`
- `test_prepare_support_units.py`
- `test_verify_quotes.py`

The audit, downgrade, and output-acceptance reproductions executed the relevant blocks extracted from the actual JavaScript workflow, with deterministic mocked agent/budget dependencies. The rerun-diff and library-resolution reproductions called the Python functions directly. No live research agents or real Zotero operations were used.

Add the workflow reproductions to the repository's automated tests so the helper test suite cannot pass while these reporting and accounting failures remain.
