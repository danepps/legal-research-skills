# /cite-check — Design Spec (v1)

*Drafted 2026-07-12 for review. Sprint item 4. Build target: one focused session once this spec is approved.*

**TL;DR:** A skill that takes an article draft (.docx with footnotes), extracts every citation and quotation, verifies each against the real source — CourtListener for cases, the user's Zotero library then the open web for scholarship — and returns a graded, footnote-by-footnote report with a "needs your attention" section first. Deterministic scripts do extraction and existence checks for near-zero tokens; model agents do quote/pincite verification in chunked fan-out. Bluebook checking is basic sanity only (dead cites, wrong reporter/court/year, broken supra references) — no format linting. Reuses the legal-research skill's proven machinery (`check_cite.py`, `fetch_page.py`, chunked verify, budget-degradation ladder).

## What it is / isn't

- **Is:** a verification pass over a finished or in-progress draft. Every authority checked for existence; every quotation checked verbatim against source text; every URL confirmed to resolve; pincites sanity-checked where source pagination is recoverable.
- **Isn't:** a Bluebook format linter (signals, typefaces, short-form style — out of scope per the author, 2026-07-12), a substantive editor, or a substitute for the journal's cite-check. The report says what was verified *and on what basis*, in the legal-research skill's disclosure style (direct-full-text / authoritative-reproduction / citation-only).

## Placement & invocation

- Ships as one skill of the `law` plugin (`claude-code/skills/cite-check/`), beside legal-research, whose helper scripts it calls via `${CLAUDE_PLUGIN_ROOT}/skills/legal-research/`. Installed as a plugin it works from any folder (drafts live outside this repo).
- Trigger: `/cite-check <path-to-draft>` or natural language ("cite-check this draft"). Optional args: `--footnotes 45-80` (partial pass), `deep` (adversarial re-verification of load-bearing quotes, mirroring legal-research's 3-vote pattern).

## Pipeline

**0. Pre-flight** (same as legal-research): ensure WebSearch/WebFetch pre-allowed; confirm CourtListener token (installed 2026-07-12: `COURTLISTENER_API_TOKEN` via synced `.claude/courtlistener.key` + `~/.config/courtlistener/token`); probe Zotero MCP availability (degrade gracefully to web-only for scholarship if absent).

**1. Extract — deterministic script, zero model tokens for structure.**
New `extract_cites.py`: parses the .docx XML directly (`word/footnotes.xml` + body), emitting JSON: every footnote (number, full text) and every quotation in body text ≥ ~8 words, paired with its supporting footnote. Stdlib-only like the other house scripts. Markdown/plain-text drafts supported as a fallback input.

**2. Segment & resolve — one model pass (Sonnet, chunked).**
Splits each footnote into citation units and classifies: case / statute-rule / law-review article / book / internet source / cross-reference. Resolves the cross-reference web deterministically where possible: `id.` chains walk back to the antecedent; `supra note N` is checked against footnote N's actual contents (a *supra* pointing at the wrong note is the classic post-edit break — cheap to catch, catastrophic to miss; this is in scope as "basic"). Repeated authorities collapse to ONE verification target with a list of instances, so a case cited 30 times is fetched once and each instance's pincite checked against the same retrieved text.

**3. Verify — fan-out, path per authority type.**
- **Cases:** `check_cite.py` first (deterministic existence + caption + date via CourtListener citation-lookup API — now authenticated, so the fan-out isn't throttled). Then one read agent per authority fetches the opinion (CourtListener → CAP/LII/Justia fallback chain, PDFs via `fetch_page.py`) and checks: caption spelling, year, court, every quotation verbatim, pincite plausibility. Pincite checking is **best-effort** — star pagination in free full text is imperfect; report `pincite unverifiable` rather than guessing.
- **Statutes/rules:** fetch from uscode.house.gov / LII / official state sources; verify quoted operative text verbatim.
- **Law-review articles:** **Zotero library first** (author, 2026-07-12): `zotero_search_items` → `zotero_item_metadata` (existence, volume/page) → `zotero_item_fulltext` for quote/pincite verification when the PDF is attached. Fallback: open web (SSRN, digital commons, journal sites — the legal-research mirror chain). Paywalled and not in Zotero → existence-verified only, flagged with what would resolve it ("add to Zotero").
- **Working papers / forthcoming pieces — VERSION DRIFT CHECK (author, 2026-07-12):** for any cited manuscript (SSRN preprint, "forthcoming" article), verify against BOTH the Zotero-attached PDF (the as-quoted version) and the *current* SSRN/repository version. Quote present in Zotero copy but absent or moved in the current version → flag **`superseded-source`** with the current version's revision date and, where findable, the passage's new location/wording — distinct from a misquote, and actionable ("re-pull and re-pin every cite to this source"). Motivating case: the practice run caught a Bradley & Goldsmith quote that had been revised out of the current SSRN version (rev. 2026-05-30) after the user quoted an earlier draft he had locally; his pins to the same manuscript had also drifted pages. Same logic applies to slip-opinion cites: when a cited slip op. gains U.S. Reports pagination, flag the cite for conversion (the SCOTUS Syncer folder + CourtListener give the trigger). If the Zotero copy is missing, run the check against the current version only and note the one-sided basis.
- **Books:** tiered (the user has PDFs for a decent number of their books in Zotero, but not all). Zotero metadata always verifies existence + edition/year; when a PDF is attached, quotes and pincites verify against `zotero_item_fulltext` like articles; when not, try Google Books / archive.org snippet search for the quoted language (existence-of-quote, not pincite), else flag `citation-only`. The report's Couldn't-check appendix lists which books lacked full text, so adding a PDF to Zotero and re-running upgrades them.
- **Internet sources:** URL must actually resolve (house rule: a fabricated link = hallucination-grade error) and the page must support the proposition; archive.org fallback for dead links, with a "link rot — suggest archived URL" flag.
- **Quotes:** verbatim or flagged. Bracketed alterations and ellipses are matched against the source with the alteration masked — the check is "does the marked-up quote honestly map to the source text," not deeper Bluebook alteration style.

**4. Report — session model.**
`<Draft name> — Cite Check.md` next to the draft. Structure:
- TL;DR counts: N verified / M partial / K mismatches / J unverifiable.
- **Needs your attention** (mismatches + broken supra/id. + dead URLs first, each with the draft's text and the source's actual text side by side, footnote-numbered).
- Full footnote-by-footnote ledger with per-authority verification basis.
- **Couldn't check** appendix: what and why (paywalled, no pincite mapping, book), and what would unlock it.
Optional `.docx` output via the existing `md2docx.py`.

## Bluebook scope (locked 2026-07-12; PARTIALLY LIFTED 2026-08-10)

> **Superseded in part.** the author lifted the lock for form problems decidable from the draft
> alone — short forms (R. 10.9 / R. 4.2) and typeface (R. 2.1(a)) — after reader feedback
> that the skills were missing obvious ones. They run in a `Form` phase off the shared
> `legal-research/citeform.py`, reported in their own section. Signal order, citation order,
> and cite composition remain out. See NOTES.md "LOCK LIFTED 2026-08-10".

In: cite resolves to the claimed source; caption/author/title spelled right; right reporter, volume, first page, court, year; quotes verbatim or honestly marked; supra/id. integrity; URLs live. Out: everything else — signals, short-form consistency, typeface, parentheticals style, citation order.

## Models, cost, guardrails

- Extraction structure: script (free). Segmentation: Sonnet. Verify agents: Sonnet, chunks of ~8 units. Report: session model. Same model policy as house convention — mechanical work cheap, prose on the session model.
- A 300-footnote draft ≈ ~120–180 unique authorities after collapse → ~20–25 verify agents ≈ **150–350k output tokens** lean. Soft ceiling + degradation ladder copied from legal-research (trim reads → verify only load-bearing/quoted authorities → existence-only pass), so a monster draft degrades instead of spiraling.
- Hard rules inherited: never verify from memory; an unfetchable source is reported unverified, never assumed; negative-treatment glance on cases (approximate, not Shepard's — say so in the report).

## Open questions for the author (defaults chosen; object if wrong)

1. **Input:** .docx with real Word footnotes assumed canonical. If drafts sometimes come as PDF or with tracked changes, say so — tracked-changes handling (accept-all before parse?) needs a decision.
2. **Report format:** v1 is a Markdown report (+ optional .docx). Margin comments *inside* the draft .docx is a v2 candidate — meaningfully more build.
3. **Pincite strictness:** default = verify when the source's pagination is recoverable, flag otherwise. Alternative (hard-fail anything unverifiable) would drown the report in flags.

## Build plan (one session)

1. `extract_cites.py` + tests against a real draft (prototype exists — see below).
2. Workflow script (adapted from `legal-research.workflow.js` — segment → verify fan-out → report).
3. `SKILL.md` + symlink install + sync-from-live registration.
4. End-to-end run on the real draft; tune the report from what it gets wrong.

## Lessons from the 2026-07-12 practice run (406-footnote draft; report: `Mac Setup/Claude Config/test draft — Cite Check.md`)

The full manual pipeline ran end-to-end and caught real errors (a fabricated quote, a dropped "not" reversing a source's meaning, 16 broken supras, ~15 bad pincites). Build changes it forces:

1. **Chunk verify work by UNIQUE SOURCE, not by draft order.** The practice run's per-30-quotes chunks re-fetched the same sources across chunks (one cited manuscript was fetched by at least three agents). Collapse quotes onto their source first; one agent per source-bundle. This is the main cost fix.
2. **Resolve *Id.*/supra antecedent chains BEFORE fan-out.** ~20 of 41 unverifiable quotes were bare-*Id.* footnotes the agents couldn't trace because they only saw their own chunk. The segmentation stage must hand each quote its resolved source. (Two *Id.* chains resolved to *cases* buried two notes back — the resolver must cross source-type boundaries.)
3. **Word footnote XML ids ≠ rendered numbers** (ids run one ahead; ids 0–1 are separators). Map via body `footnoteReference` order. A prototype `extract_cites.py` handling this is in the practice run's scratch folder — promote it into the skill.
4. **Never truncate footnote text handed to agents — this caused the run's one false accusation.** Two separate truncations bit: a 400-char cap broke 4 article checks, and a 500-char cap on the quote chunks cut off n.367's own final parenthetical (`see also Merrill, Landscape, supra note 50, at 914 (describing Drye as…)`), which attributed the quote the agent was checking. Seeing only case cites, the agent searched the cases, found nothing, and reported the quote "fabricated" — it was verbatim Merrill, caught by the user. Corollary calibration rule for verify-agent prompts AND the report: absence of a match licenses **"not found in the sources checked"**, never "fabricated" — a fabrication claim requires the full footnote visible and every named source actually searched.
   **4b. Give every quote its BODY CONTEXT, not just its footnote — second false finding (also caught by the user).** A verify agent flagged a "dropped not reversing the source's meaning" where the draft actually quoted a verbatim *fragment* from a negated descriptive sentence and supplied its own accurate prescriptive framing ("has encouraged state courts to '…'"). The agent saw only {quote, footnote} and pattern-matched. Fragment-quoting with a framing verb is standard, legitimate practice; judging it requires the draft's surrounding sentence. The extraction layer must ship each quote with its full body sentence (it already knows the paragraph), and the mismatch taxonomy needs a distinct category — "fragment-with-framing: check framing fidelity" — separate from true misquotation. Meaning-reversal claims get the same discipline as fabrication claims: full context on both sides before the verdict.
   **4c. Resolve the citation the quote actually hangs on — three more false findings, all caught by the user.** (i) A quote pinned to a bare "*Id.*" was checked against the footnote's "see also" case instead of the *Id.* antecedent two notes back — verbatim there (*Radford*). (ii) An "*Id.* at 522" was resolved to the nearest FULL cite of that author instead of following the intervening "supra note 19" redirect — the supra target made the pincite valid and the quote verbatim. (iii) A quote cited to "536 U.S. 181, 181" was compared against the OPINION text and called a "silent splice" — p. 181 is the **syllabus**, which the quote reproduces verbatim; CourtListener carries no syllabus text, so syllabus-page pincites (first page of a U.S. cite) must be checked against the bound-volume PDF (LOC usrep), never CL. **And per the author (2026-07-12): a verbatim syllabus quote is itself a first-class finding — "never cite the syllabus, that's not the law" (*Detroit Timber* disclaimer). New check: any quote whose pincite equals the U.S. cite's first page, or that matches syllabus rather than opinion text, gets flagged `syllabus-quote` with the opinion's equivalent passage suggested as the replacement — even though the quote is accurate.** The segmentation stage must therefore (a) fully resolve *Id.*/supra chains BEFORE assigning a quote its source, (b) pair each quote with the specific cite its parenthetical/position attaches it to (never "the lead cite"), and (c) route first-page pincites of U.S. Reports cites to the bound volume. Scorecard from the practice run: 5 of the 6 gravest findings were checker artifacts; the report's per-item correction notes show the shape of each. A "verify the verifier" pass on high-severity findings (re-derive from the full footnote + body context before reporting) is now a REQUIRED pipeline stage, not an option.
5. **CourtListener citation-lookup:** rate-limited at 60 cites/min (pace batches, retry on 429), and "not found" is usually its own pagination gap for recent U.S. Reports volumes, NOT a bad cite (12/96 false misses, all real cases) — auto-escalate misses to a web-verify agent, never report them raw. Feed it raw footnote text rather than regex-extracted cites.
6. **WAF reality:** SSRN, bepress/digital-commons, and several university repositories block scripted fetches outright. Mirror chain that worked: journal's own site → non-bepress repositories → Wayback → Google Books snippet search (rescued every bookseller-checkable book quote). Cap attempts per source; mark unverifiable with the unlock path (Hein pull) rather than burning retries.
7. **Agent hygiene rules to hardwire in prompts:** never `open`/GUI-view a PDF (popped the user's PDF reader mid-run); never install software without asking (an agent Homebrew-installed `tesseract` — useful, but ask; consider bundling OCR as a declared optional dependency instead); dedupe quote rows before chunking.
8. **Cost estimate revised:** the practice run spent ~2.2M subagent tokens — way over the 150–350k spec estimate — driven by cross-chunk re-fetching, WAF retry loops, and unresolved *Id.* dead ends. With fixes 1, 2, and 6, a realistic target is **400–700k for a ~400-footnote draft**; keep legal-research's soft-cap/degradation ladder armed regardless.
