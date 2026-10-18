# Evidence packet

Use one temporary JSON object per proposition. The validator is deliberately strict: each delivered authority must have a source link, pinpoint, supporting text, and explicit verification fields.

```json
{
  "proposition": "Exact proposition needing support.",
  "jurisdiction": "U.S. Supreme Court",
  "requested_count": 2,
  "status": "ready",
  "limitations": [],
  "authorities": [
    {
      "id": "A1",
      "rank": 1,
      "type": "case",
      "citation": "Full citation excluding the separately recorded pinpoint",
      "pinpoint": "410 U.S. 113, 152–53",
      "url": "https://example.gov/opinion.pdf",
      "support": {
        "mode": "quote",
        "text": "Exact supporting language from the opened source."
      },
      "fit": "controlling and canonical formulation",
      "limitations": [],
      "verification": {
        "opened": true,
        "identity_checked": true,
        "support_checked": true,
        "quote_checked": true,
        "checked_on": "2026-07-14",
        "basis": "official opinion PDF"
      },
      "case_context": {
        "opinion_part": "majority",
        "current_validity_checked": true,
        "validity_basis": "open-web citing-reference and negative-treatment check"
      }
    },
    {
      "id": "A2",
      "rank": 2,
      "type": "scholarship",
      "citation": "Author, Title, volume Journal first-page (year)",
      "pinpoint": "at 123–24",
      "url": "https://repository.example.edu/article.pdf",
      "support": {
        "mode": "paraphrase",
        "text": "The author argues the proposition in substantially this form."
      },
      "fit": "leading scholarly treatment",
      "limitations": [],
      "verification": {
        "opened": true,
        "identity_checked": true,
        "support_checked": true,
        "quote_checked": false,
        "checked_on": "2026-07-14",
        "basis": "journal repository PDF"
      },
      "scholarship_context": {
        "authorship_checked": true,
        "bibliography_checked": true
      }
    }
  ]
}
```

## Field rules

- `requested_count`: integer from 1 through 4; default to 2.
- `status`: use `ready` only when the requested number of authorities pass every applicable check. Otherwise use `limited` and explain why in top-level `limitations`.
- `type`: one of `case`, `statute`, `regulation`, `scholarship`, `report`, `dataset`, `archive`, or `other`.
- `citation`: full citation identity. Put the source-specific page or paragraph in `pinpoint` even if it is repeated in the final rendered citation.
- `support.mode`: `quote` only for text copied verbatim from the opened source; otherwise use `paraphrase`.
- `verification.basis`: state what was actually opened, such as `official opinion HTML`, `U.S. Reports scan`, `journal PDF`, or `agency dataset documentation`.
- `limitations`: record source-specific shortcomings, including nonmajority posture, an incomplete validity check, uncertain pagination, or only partial support.
- `case_context.opinion_part`: use `majority`, `unanimous`, `per-curiam`, `plurality`, `concurrence`, `dissent`, or `other`.
- `case_context.current_validity_checked`: means only that a reasonable open-source check was performed. It does not imply citator coverage.

The validator checks structural and declared verification completeness. It cannot determine whether a quotation is accurate, a source really supports the proposition, or the legal analysis is correct; those remain source-reading tasks.
