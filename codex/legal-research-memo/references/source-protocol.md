# Source and Citation Protocol

Use this file when gathering, evaluating, or auditing authorities.

## Source ledger

Maintain a compact ledger while researching. It may be a Markdown table, spreadsheet, or working note. Use one row per source and include:

| Field | Record |
|---|---|
| Source | Full citation or stable identifier |
| Level | Binding / persuasive / secondary / historical / party material |
| Court or publisher | Court, agency, legislature, journal, or author |
| Date and currentness | Decision/publication date; later treatment or repeal if relevant |
| Proposition | The exact proposition for which the source is used |
| Claim ID | The research-matrix claim or subquestion this source supports or challenges |
| Coverage cells | Stable IDs for the issues, epochs, jurisdictions, conceptions, or other planned cells this source covers |
| Load-bearing | Whether an error in this source would materially change the conclusion |
| Pinpoint | Page, paragraph, section, footnote, or quotation location |
| Posture | Majority, concurrence, dissent, dicta, order, briefing, etc. |
| Case/source role | Direct classification or rule; assumed baseline; procedure/remedy only; boundary or transition evidence; contrary example; adjacent-doctrine analogy; historical background; or later interpretation |
| Classification status | Decided; assumed; arguendo; dictum; reserved; or not applicable |
| Precedential effect | Majority holding; plurality; concurrence/dissent; summary disposition; equally divided/nonprecedential; binding noncase text; or persuasive/historical only |
| Distinct contribution | What this source adds: controlling rule, new test, narrowing move, transition, corroboration, counterexample, or rival account |
| Verification | Direct-full-text; authoritative-reproduction; secondary-corroboration; citation-only; or unverified; separately note quotation and citation checks |
| Location | Local path, official URL, or database reference |
| Currentness check | Service/database, exact query or citator action, date, result, and limitation when current force matters |
| Notes | Distinctions, adverse language, later treatment, or uncertainty |

Do not confuse “found” with “verified.” A source belongs in the final memo only after the relevant text has been read and its use is accurately characterized. A case that assumes a category, resolves only procedure or remedy, or comes from adjacent doctrine may illuminate the legal baseline without directly deciding the memo's proposition; code that role instead of allowing proximity to masquerade as a holding. Track supporting and adverse source IDs at the claim level so a long source list cannot conceal an unsupported central proposition.

For schema-v4 autonomous runs, use these exact machine keys and values. Schema-v3 runs retain their original role values for compatibility.

- `source_role`: `direct_answer`, `assumed_baseline`, `method_or_process_only`, `boundary_or_transition`, `contrary_example`, `adjacent_domain_analogy`, `historical_background`, `later_interpretation`, `scholarly_analysis`, or `factual_record`;
- `classification_status`: `decided`, `assumed`, `arguendo`, `dictum`, `reserved`, or `not_applicable`;
- `precedential_effect`: `majority_holding`, `plurality`, `concurrence_or_dissent`, `summary_disposition`, `equally_divided_or_nonprecedential`, `binding_noncase_text`, `persuasive_or_historical`, or `not_applicable`;
- `coverage_cells`: a nonempty list of declared coverage-cell IDs; and
- `distinct_contribution`: a concise nonempty description.

Use verification labels consistently:

- **Direct-full-text:** the relevant passage was read in the complete source.
- **Authoritative-reproduction:** the passage was read in a reliable reproduction, but not the preferred official or complete source.
- **Secondary-corroboration:** the proposition was checked only through secondary material.
- **Citation-only:** bibliographic or docket metadata was confirmed, but the substantive proposition was not checked.
- **Unverified:** neither the citation nor the relied-on proposition was adequately confirmed.

Any global statement about verification must match the weakest material authority. Do not say that every authority was cite-checked or verified when a material proposition rests only on secondary corroboration, citation-only confirmation, or an unverified source; disclose the mixed verification levels instead.

For deep, scholarly, or high-stakes work, include a compact verification appendix for material authorities. For standard work, include such a table when verification levels are mixed; otherwise a truthful methods or limitations paragraph is enough. In targeted work, flag only a load-bearing source that remains at `secondary-corroboration`, `citation-only`, or `unverified`.

## Source hierarchy and selection

- Start with the law that governs: text, controlling precedent, and authoritative procedural materials.
- Use lower-court decisions to show application, splits, trends, or reasoning—not to imply a rule they cannot bind the deciding court to follow.
- Use treatises and articles to locate authorities, clarify terminology, expose historical context, and identify scholarly disagreement. Cite the primary source for a proposition when the primary source is available.
- Treat AI-generated summaries, snippets, citations copied from secondary sources, and uncited internet claims as leads only.
- Trace copied propositions, quotations, syndicated reporting, and database summaries to their common origin before treating them as independent support.
- For current law, check whether an apparently controlling authority has been overruled, abrogated, limited, superseded by statute, or affected by a later procedural decision.

## Cross-doctrinal analogies

When using an authority from an adjacent doctrine, constitutional provision, jurisdiction, or historical regime, record that the use is analogical rather than controlling. Identify the exact proposition transferred, the reason the analogy is sound, and the doctrinal or institutional difference that limits it. Do not silently use a case about one element, stage, or legal category to establish another.

## Citation and quotation checks

Before delivery, check each citation against the source:

1. Correct case, party names, court, year, reporter or docket, and disposition.
2. Correct page, paragraph, section, or footnote pinpoint.
3. The cited passage supports the sentence as written, including its level of generality.
4. Quotation marks, omissions, brackets, capitalization, and emphasis are accurate.
5. The speaker is identified correctly when quoting a concurrence, dissent, party, lower court, or historical source.
6. The disposition and precedential effect support the characterization, especially for pluralities, summary dispositions, and equally divided affirmances.
7. A short cite is used only after a full cite makes the source unambiguous.

When available, run `scripts/check_cite.py` over the case citations as a deterministic existence and reporter-identity check. Treat a match as `citation-only` unless the relied-on passage was separately read. The API does not check pinpoints, quotations, holdings, characterization, or negative treatment.

Prefer a short paraphrase when a quote would obscure the holding or when the surrounding context materially narrows the language. Preserve a longer excerpt in research notes only when it helps a later reviewer verify the analysis.

## Currentness and online research

For date-sensitive research, state “Research current through [date].” Verify current text and later treatment from an authoritative source. If official sources are unavailable, identify the source used and lower confidence accordingly. Do not claim that research is current merely because a search engine returned a recent result.

When browsing, search by the issue, doctrinal label, statutory provision, distinctive phrase, and predecessor terminology. Open the underlying opinion, statute, or article. Capture the publication date and the relevant text. Do not cite a search-result page.

## Bounded source access

Inspect supplied files and any authorized, available project library or Zotero collection before repeating external retrieval. Treat library metadata, prior memos, and unread sources as leads; verify the relied-on text. For a blocked source, prefer an official HTML version, an authorized repository or author copy, or an already authorized database connector. Do not infer access from an installed integration, and do not change browser permissions, global configuration, or login state to obtain a source.

Give each researcher, verifier, and rescue/fill worker a per-source access cap: normally three retrieval attempts total, including alternate copies and any transient retry. Stop on repeated authorization failures or a paywall; report the best source location, evidence reached, and remaining gap. An explicitly authorized access workflow may use its own bounded procedure. A missing central source warrants a lead decision to narrow or disclose the claim, not an open-ended sequence of browser, proxy, or SSO attempts.

When a raw public page or PDF needs local extraction, use `scripts/fetch_source.py URL --out RUN_DIR/sources/UNIQUE_SOURCE.txt`. Create the parent directory first and give parallel workers unique per-run, per-source output names. The helper refuses existing files, caps downloaded bytes and PDF pages, preserves PDF page separators, and writes an adjacent `.json` record with requested/final URLs, raw/text hashes, and extraction limits. Inspect `complete_text` and `limit_note`; unknown or capped PDF coverage must remain partial. `complete_text=true` means the helper did not truncate the retrieved representation, not that source identity, version, OCR, or proposition support has been verified. Read targeted passages from the saved text instead of placing an entire document in context. The stdout form has a smaller character cap and reports truncation explicitly.

## Negative research

Negative conclusions require calibrated language. Prefer:

- “I located no published decision in the searched jurisdictions addressing …”
- “The cases located discuss X but do not decide Y.”
- “The available authorities appear sparse and do not establish a clear rule.”

State the databases, courts, date range, search terms, and source set only when you actually recorded them. Distinguish “no authority located” from “authority rejects the proposition.” Search for contrary terminology and cases that avoid, reserve, or expressly decline the issue.

## Conflicts and later treatment

When authorities disagree, create a mini conflict table with the court, date, rule, rationale, and present force. Explain which authority controls and why. Check cited precedent for later narrowing language, rehearing or amended opinions, en banc treatment, statutory amendments, and overruling decisions. Treat a citation in a later opinion as evidence of treatment only after reading what the later opinion says about it.

For each controlling or load-bearing case whose current force matters, record the service or database, exact query or citator action, date, result, and limitations of the check. A search-engine query or list of citing opinions can seed review but is not equivalent to KeyCite, Shepard's, or a comparable citator and must not be described as one.

When CourtListener coverage is useful, run `scripts/courtlistener_treatment.py` to preserve the exact citing-opinion and treatment-language queries in a hidden currentness artifact. Treat every signal as a lead: open the citing opinion and determine which authority the language concerns, the type and scope of treatment, the relevant court, and whether the discussion affects the proposition used. Do not infer good law from an empty probe or infer dormancy from an old newest-citation date.

## Confidentiality

Keep client names, privileged communications, internal strategy, and nonpublic facts in local working files unless the user has expressly authorized external transmission. When a web search can be framed using a generic legal issue, remove identifying facts. If the assignment cannot be researched safely without exposing confidential material, say so and request a redacted version.
