# Context and usage controls

Read this before delegating a source bundle or estimating a long run. The Codex
sample test exposed avoidable context overhead: a source reviewer inherited the
conversation and began with more than 100k input tokens. This is evidence for
smaller assignments and fresh contexts, not a universal per-source token price.

## Prepare once, reuse by source

The lead resolves the project library and source identities once. Record found
item keys, cache paths, source hashes, versions and failed retrieval routes in
`source-ledger.jsonl`. Workers use those records before making new searches;
do not repeat the same lookup across multiple libraries without a concrete reason.
Combine a source's quotes, pins and support units in the same first read. An
independent audit reuses the file but independently examines the relevant passage.

After segmentation, prepare the bounded assignment:

```bash
python3 <skill-dir>/scripts/prepare_source_bundle.py RUN_DIR SOURCE_ID \
  --output RUN_DIR/source-bundles/SOURCE_ID.json
```

The packet preserves complete footnotes and body context, relevant prepared
quotes and support anchors, sibling citations, and source/cache references. It
does not load full source documents or prior verdicts. Quotes appearing at the
same location are context candidates, not automatic attribution to this source.
For a new source without a ledger record, `source_record_available: false` leaves
its retrieval status unspecified; the resolved citation remains in the packet.
Resolve attribution before checking them. Referenced antecedents outside the
packet may be opened selectively; do not load the entire extraction to find them.
The byte count printed by the helper is a packet-size measurement, not tokens.

When delegating, use `fork_turns="none"` where supported. Supply the packet path,
specific question, necessary verification rules, permitted retrieval routes and
owned output path. Do not inherit the conversation or attach the entire draft,
source ledger, report or tool history. If fresh contexts are unavailable, perform
small bundles in the lead rather than paying for a duplicate long conversation.
Give audit workers the same original context plus the precise disputed item;
do not supply the earlier reviewer's reasoning as a substitute for derivation.

Read files with targeted page/line windows. Keep full text on disk, preserving
pagination; do not paste an article or a large library response into every turn.
Return concise structured evidence: unit/source IDs, retrieved passage, locator,
file/hash, verdict, searches actually performed and remaining uncertainty.

## Estimate work and stop repeated attempts

Estimate work from unique uncached sources, required independent audits and
planned worker assignments, including retries. Existing source files should not
be counted as new retrievals. Small focused checks usually stay with the lead;
delegation is useful only when independence or parallel source work warrants it.
Avoid a universal token multiplier or dollar estimate from a single sample.

Keep the existing three-mirror and two-bot-wall limits per source across workers,
not separately for each worker. A failed bundle receives another attempt only
for a concrete new route or a correctable execution failure, not a generic
"try harder" continuation. Record the route and reason before retrying.

For an explicit user budget, check remaining resources before each new bundle
and retain capacity for required audits and the report. Cut additional support
retrieval before those obligations; disclose the exact unread units. A script
that measures past usage is not a runtime-enforced spending cap. If the runtime
cannot enforce the requested token/dollar ceiling, say so and use bounded source
and worker counts rather than promise a hard financial limit.

## Measure the run in the correct units

Record the run's start time and every worker session used. Prefer runtime usage
directly when available. If local Codex JSONL logs are available, explicitly name
the lead and all worker logs and the bounded run interval:

```bash
python3 <skill-dir>/scripts/usage_report.py \
  --session LEAD.jsonl --session WORKER.jsonl \
  --start START_ISO_WITH_TIMEZONE --end END_ISO_WITH_TIMEZONE \
  --output RUN_DIR/usage-summary.json
```

The helper subtracts cumulative counters at the window boundaries. Repeated
counter events and duplicate paths do not add usage. It rejects duplicate session
identities, counter resets and unsupported arithmetic instead of guessing. Missing
usage or an unestablished starting counter stays unavailable; per-session
measurements and their baseline basis remain visible. Requests are
counted when usage is reported, so a request may have started before the window.
Do not include later skill-development work in a draft-checking run's totals.

For these Codex counters, `cached_input_tokens` is already inside `input_tokens`
and `reasoning_output_tokens` is inside `output_tokens`. The total is input plus
output; do not add those subsets again. Keep cached input separate for analysis
because token categories need not have the same price. Context-window size and
an unlabeled aggregate from another runtime are not generation counts or output
usage. Never infer a monetary cost without the applicable pricing and usage basis.

Use the measured total in provenance only when every participating session and
the intended time interval are covered. Otherwise disclose the measured subset
and preserve `tokens unavailable` for the aggregate. Keep logs, packets and usage
reports inside the hidden run directory; publish only requested deliverables.
