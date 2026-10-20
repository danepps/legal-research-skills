# Subsequent history and treatment advisory

Read this during source verification. Review history for every cited lower-court
case and treatment for every case, including cases cited only as history or as a
foil. Deduplicate retrieval by source, but evaluate each citation instance's use.
If access, scope, or budget prevents a pass, record the skipped cases and reason;
never let omission imply coverage.

## Existence before history

A reporter-lookup miss triggers both a caption search (one distinctive word per
side in `caseName:`) and a full-text phrase search for the citation string:

```bash
python3 <skill-dir>/scripts/check_cite.py 'REPORTER CITATION' --name 'A v. B'
```

`--name` is for a single citation. Batch misses still receive citation-text
searches; obtain each missing caption from the draft/context and rerun that cite.
Record the routes tried, failed, or unavailable before calling identity
unconfirmed. Search results are candidates. A later opinion quoting a reporter
citation corroborates it but can repeat a miscitation; inspect that passage and
confirm parties, court, date and disposition against the best available record.
Do not silently select the first ambiguous match. After inspecting a candidate,
pass its explicit `cluster:ID` to the helpers when reporter lookup remains absent.

## History

```bash
python3 <skill-dir>/scripts/case_history.py 'REPORTER CITATION' \
  --limit 100 --output RUN_DIR/currentness/S1-history.json
```

The helper fetches post-decision entries with `docket=<id>` and
`date_filed__gte=<decision date>`, newest first within a disclosed cap. Same-day
entries require sequencing. For an empty linked scraper docket it searches
`type=d` using the `yy-type-number` core and exact court, and follows a unique,
untruncated RECAP candidate. Ambiguous twins require inspection. It also searches
later opinions by caption words. This second search works even where RECAP has no
state-court coverage. Missing dates, errors and caps stay visible in the packet.

Read flagged entries and the underlying documents when available: notice of
appeal, appellate judgment/opinion, mandate, certiorari grant/denial, amended or
substituted opinion, reconsideration, vacatur, remand, reversal and Rule 59/60
proceedings. Inspect attachments naming changed opinions. A motion requesting
vacatur does not establish vacatur. Retrieve and compare the operative version.

Verify that a later caption match concerns the same litigation and that the
court actually had reviewing jurisdiction. A higher court level alone is
insufficient: another circuit or a same-level transfer court may not review this
judgment. Do not infer the state appellate chain from federal court-ID patterns.
A U.S./S. Ct./L. Ed. citation is a Supreme Court screening clue; confirm court
identity, including slip and unreported decisions, before excluding a source
from the lower-court history pass.

Determine any required history under the applicable Bluebook Rule 10.7 and its
exceptions from an available rule source. Record the rule basis and application
before labeling an omission required. Do not demand every appeal or certiorari
denial indiscriminately. When the rule or outcome cannot be confirmed, report
an advisory question with the missing verification step.

## Treatment by two routes

When the companion `legal-research-memo` skill is available:

```bash
python3 <legal-research-memo-dir>/scripts/courtlistener_treatment.py 'REPORTER CITATION' \
  --limit 20 --output RUN_DIR/currentness/S1-treatment.json
```

Otherwise perform and record the equivalent available searches directly: the
`cites:(opinion IDs)` graph route and a full-text phrase route for the full caption,
its ampersand/and variant and distinctive `A v. B` short form, with `filed_after`
the decision date. Each route includes a recent-citing search and a separate
relevance-ordered treatment-language search. Record failed or unavailable routes.
Manual skill installs do not require importing code from a missing sibling.

Open every material hit. Treatment language can concern a different case in the
same opinion, and a name match can be a namesake. Report distinct retrieved
decisions by cluster (or stable decision URL), also merging versions that share
a reporter citation, court and date; do not count raw search rows or nested
opinions; do not combine separate appellate decisions into one litigation count.
Keep API totals separate from sample counts. A name-only hit is absent from the
retrieved graph sample, not necessarily from the full graph. Caps and partial
responses require partial coverage, even when useful leads were found.

## Report and record

Use `case-review.jsonl` and the exact fields in [ledger-fields.md](ledger-fields.md).
In **Subsequent history & treatment**, list separately:

1. Confirmed omissions of required history, with the rule basis and disposition.
2. Draft history contradicted by the record.
3. Treatment flags and their implications for the proposition actually cited.
4. Partial, skipped and unavailable case checks, reasons and unlock paths.

Keep this section advisory. An adverse-treatment flag does not itself invalidate
a historically accurate citation or a case used as a foil. Audit any critical/high
adverse finding under the ordinary protocol; record it in the unit verdict and
verifier audit as well as the advisory ledger.

Carry these limits in the section: RECAP is crowd-sourced, incomplete and
federal-only; appellate dockets are thin; Supreme Court dockets are not on PACER
(certiorari history rests on lower-court entries, later opinions or the Supreme
Court's own records); docket text is the clerk's language, not a holding; a notice
of appeal is not an outcome; no hits is not proof of good law. This is not
Shepard's or KeyCite. Neither the helper nor the validator decides legal effect.
