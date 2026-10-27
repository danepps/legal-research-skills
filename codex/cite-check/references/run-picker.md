# Choose coverage before source work

This is a conversation picker backed by a local preview, not a separate app.
Settle the amount of work before retrieval or delegation. Keep explicit user
instructions, including existing budget limits, throughout the handoff.

## Preview

Run `scripts/prepare_run_options.py DRAFT --output PREVIEW.json`, with the preview
inside `<project>/.codex-memo/preflight/<run-id>/`. Do not put it in the final run
directory: `init_run.py` requires that directory to be new. Extraction is local;
the preview performs no research, downloads or agent calls.

Translate already-given instructions into flags:

| Choice | Preview flag | Meaning |
| --- | --- | --- |
| Whole draft | `--coverage all` | All notes and citations in the body |
| Small sample | `--coverage sample` | First ten numbered notes, or all numbered notes if fewer; list their exact numbers |
| Specific notes | `--footnotes 18 23 45-50` | Those notes only; cannot combine with `--coverage` |
| Review depth | `--depth standard` or `--depth deep` | Deep adds independent review of load-bearing checks and all adverse findings in the selected scope |
| Dedicated support pass | `--support off`, `pincited`, or `all` | Off by default; `all` also includes whole-work reading |

A numbered-note sample excludes body citations and custom-marked author notes.
It is a small test, not a representative quality estimate for the entire draft.
If the user named particular sources or quotations, preserve those constraints
in the run scope and report; do not replace them with the first-ten-notes preset.
The helper only encodes whole-draft and numbered-footnote coverage. Other focused
requests use the existing direct initializer `--scope focused` route.

The preview reports extracted note and prepared-quotation counts, not an exhaustive
citation count. Optional `--inventory PRIOR_RUN_DIR` uses a completed, reconciled
inventory for the same draft hash and a scope covering the selection. It counts
unique full-text sources for quotes, recorded pincites and the selected support
pass. Cached files must match their recorded hashes. Missing, stale, incomplete or
incompatible inventories produce **unknown** counts, never an assumed zero.
The saved `inventory_path` identifies the existing cache to consult during source
work; counts alone do not copy or retrieve sources into the new run.
Do not create a full citation inventory just to populate this picker.

Display the selected note/quote counts and, when known, source/cache counts.
Explain that these measure scope, not a hard token or dollar ceiling: metadata,
history, newly found quotations, independent audits and retries also consume
resources. Changing coverage or support changes the counts; regenerate afterward.
Follow [resource-controls.md](resource-controls.md) for explicit budget limits.

## One interaction, only unsettled choices

The helper emits up to three `questions`: coverage, depth, support. By default it
offers them for at least 30 selected notes, 20 prepared quotations or ten known
uncached sources. These are UI heuristics, not cost guarantees. `--ask` requests
unsettled choices on a shorter draft. Flags supplied from the user's instructions
remove the corresponding questions. Never infer support from deep review.

Use the available structured question tool in one call. In a runtime with
`request_user_input_async`, map each title and its labeled option descriptions
to that tool's question format. Use a synchronous picker only when that tool is
available in the current mode. If no structured tool is available in an
interactive session, ask the same compact choices in ordinary text. The helper's
`value` strings are CLI values, not raw tool arguments; respect the tool's schema.
For a tool limited to three options, all generated questions already fit.

Default choices are whole draft, standard and support off. Existing explicit
instructions take precedence over defaults. When the request already settles the
work, pass those flags plus `--defaults` for any remaining defaults and proceed.
Also use defaults for a noninteractive run or a user who says not to ask. Do not
silently replace an explicit budget or scope constraint with a default; if it
cannot be honored, explain the limit and obtain the needed clarification.

A pending `needs_choice` preview cannot initialize a run. Continue independent
local inspection while a question is pending, but do not start dependent source
work. A preselected option, absent reply or elapsed time is not an answer.
Free-text answers can specify note ranges; resolve ambiguity before broadening
the scope. Do not ask another approval question after clear choices arrive.

## Bind the selection to the run

Regenerate the preview from the answers, supplying each settled flag. For example:

```bash
python3 <skill-dir>/scripts/prepare_run_options.py DRAFT \
  --output PREVIEW.json --coverage sample --depth deep --support pincited
python3 <skill-dir>/scripts/init_run.py DRAFT --run-dir NEW_RUN_DIR --options PREVIEW.json
```

Initialization accepts only `ready`, unblocked options for the current draft hash.
It rejects simultaneous scope/support overrides and saves a hashed copy in the
run. A changed draft needs a regenerated preview; retain choices that still apply
without asking again. A blocked extraction must be addressed under the skill's
normal extraction rules before research begins.

The manifest keeps `scope: focused` for selected notes and stores review depth
separately in `review_depth`. Apply deep audit obligations when that field is
`deep` (or a legacy manifest has `scope: deep`). The readiness gate checks that
the saved scope, depth and support settings agree with the resolved preview.
Keep the original choices as provenance if resources later require a limited
result; enumerate unchecked work and use `complete_with_limits` rather than
quietly broadening or rewriting the choices.
