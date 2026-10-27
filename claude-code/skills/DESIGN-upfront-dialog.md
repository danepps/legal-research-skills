# Up-front dialog for /cite-check and /proofread — design note

*Drafted 2026-10-27 after a live test in the Claude desktop app. Not built. Nothing in this note
changes how either skill runs today.*

**TL;DR.** Both skills already stop once at the start with a single `AskUserQuestion` on depth.
The proposal is to let that one dialog carry the other opt-in choices a nontechnical user would
otherwise never discover — proposition support and the Zotero library for cite-check, style for
proofread — and nothing else. A three-question dialog was tested live in the desktop app and
rendered as one interaction. The one defect the test exposed (a free-text choice whose value never
came back) is fixed in the design below by listing registered Zotero libraries by name and
matching a typed description against them.

## What exists today

- `cite-check` SKILL.md step 1b asks Depth (Standard / Deep) up front, folds in the tracked-changes
  warning, and skips the ask when the request's wording settles it.
- `proofread` SKILL.md step 1b asks Depth with three tiers (Standard / Deep / Deep + Fable) under
  the same skip rule.
- Everything else is keyword-triggered from the request: `support` and `supportScope`
  (cite-check), `style` and `fable` (proofread), footnote ranges, `history:false`.
- cite-check's Zotero-library question happens later, in pre-flight step 2.3b, so a first-time
  user with a Zotero server registered is stopped twice. That contradicts the skill's own stated
  goal of one interaction.
- proofread's SKILL.md records an earlier decision to keep `style` out of the depth question because
  a second decision "taxes every run." That reasoning predates multi-question dialogs: one
  `AskUserQuestion` call now holds up to four questions in a single dialog, so the tax is one more
  row in a dialog that already appears, not a second interruption.

## Why expand the dialog

The README's audience does not know the flags exist. The support pass is the most valuable
capability in 1.6.0 and the only way a user finds it is one sentence in the README; a user who types
"cite-check my article" never sees it. `style` has the same problem. A dialog fixes discoverability
at the one moment the user is already being asked something.

Cost argues the same way. The support pass is the expensive option (see `cite-check/DESIGN.md`,
addendum 2026-10-27). A user who turns it on from a dialog whose option text states the cost has
made an informed choice; a user who found it in the README has not.

## What not to add

- **Footnote ranges.** Free text; they stay request-parsed.
- **History.** Defaults on and is cheap; asking adds noise.
- **Fable for proofread.** Already an option inside the Depth ladder.
- **The .docx copy.** Belongs at delivery, after the user has seen the report.
- **A "(Recommended)" tag** on any option, consistent with the existing rule: the right tier
  depends on how near-final the draft is, which the user knows and the skill does not.

## The live test (2026-10-27)

A three-question dialog (Depth, Support, Zotero) was put up in the Claude desktop app exactly as
the skill would. All three questions came back in one response, so the skill can ask everything
up front without stopping the user twice. The user reported that it rendered acceptably.

One defect: the user chose "A group library", whose description said to type the name in the
Other box, and no name came back, because the option label carried no value and the Other box was
not used. Options must carry their value. The Zotero question below is designed around that.

## Proposed dialogs

### cite-check — one `AskUserQuestion` call, up to three questions

**1. Depth** (header `Depth`) — unchanged.

| Option | Args | Description shown |
|---|---|---|
| Standard | `deep:false` | Verify agents at low effort. Every quotation is still checked against its source. Good for a working draft. |
| Deep | `deep:true` | Verify agents at medium effort: a closer reading of each quote against its source. No extra pass, same coverage. For a near-final draft. |

**2. Proposition support** (header `Support`)

| Option | Args | Description shown |
|---|---|---|
| Off (default) | `support:false` | Unquoted citations are confirmed to exist but not read. The report says so and marks them existence-only. |
| Pincited cites | `support:true, supportScope:"pincited"` | Each unquoted citation with a page, section or parenthetical is read at that place and judged through its signal. The most expensive part of a run; the step 3a estimate says what it will cost on this draft. Possible overstatement is reported as something to confirm, never as an error. |
| All cites | `support:true, supportScope:"all"` | Also reads bare whole-work citations with no pincite. The most expensive option and the most prone to checker artifacts; for a final pre-submission run. |

**3. Zotero library** (header `Zotero`) — asked only when pre-flight would otherwise ask: no
`Zotero library:` line in the project's CLAUDE.md and at least one Zotero MCP server registered.
Pre-flight steps 2.3a–b therefore move ahead of the dialog; they are a read of CLAUDE.md and of the
`mcpServers` entries in `~/.claude.json`, which cost nothing.

The options are the registered libraries themselves, by their real names, so nobody types:

| Option | Where the label comes from |
|---|---|
| Personal library | the server registered with `ZOTERO_LIBRARY_TYPE=user` |
| *Group: \<real group name\>* (one option per registered group) | `GET https://api.zotero.org/groups/<ZOTERO_LIBRARY_ID>` with the server's `ZOTERO_API_KEY`, which returns the group's name and description; fall back to the server's own name (`zotero-<short-name>`) if the request fails |
| No Zotero this run | — |

With more than two group libraries the question would exceed four options; list the three most
recently registered and let the Other box cover the rest.

The description text for a group option carries no technical content:

> *Group: Epps–Dave Federalism Project* — The shared library of that name. Claude will remember
> this choice for this folder so it does not ask again.

**Free-text descriptions.** If the user types in the Other box instead ("my library with Dave",
"the one for the federalism paper"), the skill matches the text against each registered library's
group name, group description and server name, case-insensitively, by shared words. One clear
match: say which library was chosen, in one sentence, and proceed. Several or none: ask once more,
listing the candidates by name. If only one group library is registered, any description that is
not "personal" resolves to it. Zotero's API lists group members only as numeric ids, so "the one
with Dave" cannot be resolved from membership; it resolves only when the group's name or
description mentions Dave, which in practice it usually does.

**Recording the answer.** Whatever is chosen is written to the project folder's CLAUDE.md as the
existing `Zotero library: <name> → MCP server <server>` line, so the question never recurs for
that project. A group library that exists in Zotero but was never registered during setup is
named and pointed at `/legal-research:setup` rather than silently falling back to the web.

### proofread — one `AskUserQuestion` call, two questions

**1. Depth** (header `Depth`) — unchanged, three tiers.

**2. Style** (header `Style`)

| Option | Args | Description shown |
|---|---|---|
| Off (default) | `style:false` | Proofreading only: typos, grammar, missing or doubled words, consistency. |
| On | `style:true` | Also flags confusing sentences and unintended repetition, in a clearly separated section. This is editing, not proofreading, and it is opinion; turn it on when you want a second reader's reactions. |

## Rules that carry over unchanged

- **Skip when the request settles it.** "Check that the sources support what I cite" never produces
  a Support question; "deep", "quick", "near-final" never produce a Depth question; a request that
  names the library never produces a Zotero question. A question whose answer is already known is
  dropped from the call, not asked with a preselected default.
- **One call.** All questions for a run go in a single `AskUserQuestion`; the tracked-changes
  warning rides along as today.
- **Before the snapshot.** The dialog precedes step 2b, as the depth question does now, because
  depth changes extraction in proofread and support changes which units are built in cite-check.
- **Give the real reason in the option text**, not just labels, as the existing depth tables do.

## Availability and fallback

`AskUserQuestion` exists in Claude Code only. The Codex skills have no equivalent and stay
keyword-driven; the two sides diverge in interaction, not in defaults. When the tool is unavailable
(a headless or scheduled run), the skill uses the defaults (Standard, support off, style off, the
CLAUDE.md library or web-only) and states them in the deliver message and the report footer.

## Implementation, when wanted

Confined to three files plus a changelog line:

1. `cite-check/SKILL.md`: rewrite step 1b as the three-question dialog above; move pre-flight
   2.3a–b ahead of it; add the description-matching rule and the CLAUDE.md write; point the
   Support option text at step 3a's cost estimate.
2. `proofread/SKILL.md`: rewrite step 1b as the two-question dialog; retire the paragraph that
   keeps `style` out of the question, with a note on why the reasoning changed.
3. `README.md`: the sentence that currently tells users to ask for a support check in words
   becomes a sentence saying the skill asks.
4. `CHANGELOG.md`: one bullet.

No script changes. The group-name lookup is one HTTPS request per registered group server, done by
the orchestrating session before the dialog, and can be skipped (falling back to the server name)
if it fails or takes more than a few seconds.

## Open questions for the author

1. Whether the Zotero question should appear at all when only a personal library is registered,
   or whether that case should resolve silently to it with a one-line note. The dialog is lighter
   without it; the note keeps the choice visible.
2. Whether a run started with a `+Nk` budget should skip the Support question, on the theory that
   a user who wrote a budget already knows what they are buying. Probably not: the budget lifts
   the cap, it does not choose the pass.
