---
name: find-cite
description: Find a small set of verified, footnote-ready authorities for one legal, doctrinal, scholarly, historical, or empirical proposition. Use when the user asks for a cite, authority, source, canonical case, supporting article, pincite, footnote filler, or support for a particular sentence or claim. Return a concise ranked answer rather than a research memo; route broad synthesis, many propositions, or open-ended legal research to legal-research-memo, and route audits of existing citations to cite-check.
---

# Find Cite

Fill one footnote with the best authority that actually supports the proposition. Return a short ranked list, normally 2–4 authorities, with pinpoints, support, fit, and verification. Keep the work bounded and the answer concise.

## Set the target

Extract before searching:

- the exact proposition needing support;
- jurisdiction and relevant time, if legally material;
- requested authority type or source constraints;
- requested count, defaulting to two and never exceeding four without user direction.

Treat the sentence bearing the footnote as the target, not the surrounding section. Infer sensible defaults when the context is clear. Ask only when ambiguity would materially change the search.

Choose authority by proposition:

- Use primary law for holdings, legal rules, institutional facts, and vote lineups.
- Use scholarship for claims about literature, theory, intellectual history, or scholarly consensus.
- Use both when the claim characterizes doctrine or connects doctrine to a scholarly account.
- Use the original dataset, report, archive, or other primary source for empirical or historical claims when available.

Do not default to Supreme Court cases unless the proposition calls for federal constitutional or Supreme Court authority. Respect the governing jurisdiction.

## Keep the task small

Run focused research for one proposition. Begin with the likeliest canonical authority, then seek a recent or especially precise corroborating authority if useful. Usually stop after two focused query rounds and roughly 6–10 substantive source opens.

Switch workflows when scope expands:

- Use `legal-research-memo` for multiple propositions, contested synthesis, broad adverse-authority analysis, or an open legal question.
- Use `cite-check` when the authorities are already supplied and the task is to audit citations, quotations, pincites, or source support.
- Tell the user when the requested proposition itself needs narrowing or qualification rather than manufacturing support for an overstatement.

## Search in source order

Browse for current and external authority. Search local materials or the user's connected library first when likely relevant, then use the open web.

For primary law:

1. Find the canonical or controlling authority.
2. Prefer official court sources, government repositories, authenticated codes, and official agency materials.
3. Use CourtListener, Google Scholar, Cornell LII, Justia, or comparable services for discovery and cross-checking, not as a substitute for opening the relevant text when an official source is available.
4. Prefer controlling authority over persuasive authority and holdings over dicta.

For scholarship:

1. Search the user's Zotero or local corpus first when available.
2. Prefer the journal, institutional repository, author manuscript, SSRN, HeinOnline citation page, or another source that establishes bibliographic identity and exposes the relevant text.
3. Rank substance first, then author expertise, venue quality, influence, and recency as relevant to the proposition.
4. Use student work only when it is unusually apt or no stronger source exists, and label it accurately.

For empirical or historical material, prefer the original study, dataset, government report, archive, transcript, or contemporaneous document over later summaries.

## Verify every authority

Opinions, articles and dockets may postdate the model’s training data; an unfamiliar 2025–2026 decision is not a hallucination signal.

Do not ship an authority that has only appeared in a search snippet or secondary discussion.

For every candidate:

1. Verify bibliographic or case identity from a reliable source.
2. Open the underlying text.
3. Confirm the cited page or paragraph supports the precise proposition.
4. Record the supporting language as either a verbatim quote or a clearly labeled paraphrase.
5. Confirm the pinpoint against the source's pagination or paragraph numbering.
6. For cases, identify the opinion part and precedential posture. Never silently rely on a concurrence, dissent, plurality rationale, vacated opinion, or nonprecedential disposition.
7. For load-bearing current-law cases, perform a modest negative-treatment/current-validity check using available open sources. Describe it accurately; do not imply KeyCite or Shepard's coverage. If current validity is immaterial to a historical proposition, record `current_validity_required: false` and explain the scope in `validity_basis` and the authority's `limitations`. An incomplete required check instead needs a `limited` packet and an explicit caveat.
8. For scholarship, verify author, title, venue, volume, year, first page, and the pinpoint used.

Drop a candidate that fails support verification. If the best available authority supports only a weaker proposition, narrow the parenthetical and explain the gap.

## Enforce the evidence gate

Before answering, create a small JSON evidence packet following [references/evidence-packet.md](references/evidence-packet.md). Keep it under `<project>/.codex-memo/runs/<run-id>/` or an allowed temporary directory. Publish only the requested answer unless the user asks for the packet. The validator checks recorded evidence fields; the lead must still open the source and assess its meaning, provenance, and pagination.

Validate it with:

```bash
python3 <skill-dir>/scripts/validate_packet.py <packet.json> --require-ready
```

Do not present the result as fully verified unless the validator reports `READY`. A `LIMITED` packet may still support a candid partial answer, but state the limitation prominently and do not imply square support.

## Deliver footnote-ready results

Lead with the best authority. For each authority provide:

1. a complete citation with pinpoint;
2. a short parenthetical or a brief verified quotation;
3. one phrase explaining fit, such as controlling case, canonical formulation, recent reaffirmation, leading article, or closest available authority;
4. the verification basis and a direct source link.

Then add only material caveats: jurisdiction, nonmajority posture, incomplete validity checking, unavailable pagination, or the gap between the source and the user's wording. Suggest a citation signal only tentatively when signal choice depends on how the proposition is framed.

Do not write a memo, pad the answer with search history, or list weak authorities merely to reach a target count. Never invent or smooth over a citation, pinpoint, quotation, holding, authorship, or verification result.
