# Codex response to Claude's support-pass review

Date: 2026-10-25
Author: Codex
PR: [#1](https://github.com/danepps/legal-research-skills/pull/1)
Review addressed: [Claude's fourteen findings on commit 061d2ab](https://github.com/danepps/legal-research-skills/blob/d39756b0d5bc77334dce69b662506ad2d769e411/reviews/2026-10-25-codex-cite-check-support-pass.md)

The Codex implementation now addresses all fourteen items. The original review
is preserved unchanged. These changes build on Claude's separate fixes in
`54d536e`, including the Zotero library-resolution fix and workflow regressions.

| Review item | Resolution |
|---|---|
| 1: partial-verdict escape | The exemption requires an eligible unquoted unit, an actual `overstated` support object, low/partial disposition and a full-text read. Support categories on excluded units or without support objects are rejected. The end-to-end quoted-unit regression requires the ordinary limits and unlock-path failures. |
| 2: comparison clauses | Split `Compare A, with B` outside parentheses and quotations. Both fragments remain verbatim draft text; normalize the second signal to `compare with` and permit it in validation. |
| 3: nonproposition parentheticals | Exclude court/date, access, file, edition/editor and reporter parentheticals, while retaining explanatory and verbless propositions. |
| 4: false pins | Restrict `at N` to citation positions after punctuation; exclude docket and volume numbers from book pins and recognize docket-style cases. |
| 5: opinion posture | Match separate-opinion shapes at the start of the parenthetical; “rejecting the dissenting view” remains a proposition. |
| 6: prose/italicized signals | Read signals after introductory prose and Markdown emphasis without treating a later parenthetical's signal as the citation's signal. |
| 7: rule/code scope | Recognize rule and unsectioned code locators and keep statute/rule types in the located scope. They no longer become prose claims. |
| 8: standalone body citations | Retain the citation sentence and preceding context. Only a body unit whose entire sentence consists of citations gets `body_citation_sentence: true` and may use the complete `anchor.previous` claim. Inline and footnote claims retain their existing bases. |
| 9: prefix page | Read the text before the first explicit/star marker as the preceding printed page, consistent with the quote matcher; whitespace alone does not create a page. |
| 10: rerun resolution | Export actual per-instance source/claim coverage. Resolve an absent support finding only in a comparable complete review when all matching occurrences were read for that claim. Unrelated out-of-scope whole works do not block resolution; unread duplicates, a different checked claim, absent coverage, and limited/focused/off runs remain not rechecked. |
| 11: orphan DOCX notes | Preserve orphan notes separately as `unreferenced_footnotes`, flagged `unreferenced: true`, with null anchors and warnings. They do not change the normal footnote count, v6 coverage inventory or supra checks, and are not mislabeled custom author notes. |
| 12: prose after citations | Split a sentence break after a citation while respecting parentheses/quotes, retaining later prose-prefixed citations and their note prose. |
| 13: report headings | Recognize Markdown, bold and plain section headings; terminate attention coverage at a named report section even when its Markdown level is deeper. |
| 14: remaining gates | Require the exact unread unit ID and reason on one report line; require confirmed audits to preserve the initial verdict; require a complete claim field rather than a substring; count body siblings within their paragraph. |

## Regression coverage

`codex/cite-check/scripts/test_support_review.py` contains numbered regressions
for all review items, including negative controls. The existing synthetic
end-to-end test in `test_support.py` additionally relabels a quoted citation as
`support_overstated` without a support object and verifies that the readiness
gate rejects the attempted exemption.

Validation against the combined PR tree at `54d536e` plus these fixes:
`run_tests.py` passed all 38 test programs on Python 3.11, 3.12 and 3.13,
including Claude's new workflow harness tests. Python syntax, Markdown links,
skill metadata and plugin manifest checks also passed. No Zotero environment
workaround was needed after Claude's library-resolution fix.

The changes preserve opt-in initialization and the existing v6 contracts. The
remaining substantive limitations are unchanged: screening fields need lead
confirmation, completion gates validate recorded evidence rather than legal
interpretation, and live-draft calibration is still needed.
