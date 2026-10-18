# legal-research-skills

Agent skills for legal scholarship: research memos, citation finding, cite-checking, proofreading, Zotero library construction, and Supreme Court case prep. Built and used daily by a law professor; released as-is under the MIT license.

Two parallel implementations live here, one per agent runtime. They share a design philosophy but are **separate codebases**, not ports of each other. Pick the folder for the tool you use.

| Folder | Runtime | Install location |
|---|---|---|
| [`claude-code/`](claude-code/) | [Claude Code](https://claude.com/claude-code) (Anthropic) | `~/.claude/skills/<skill>/` |
| [`codex/`](codex/) | [Codex CLI](https://github.com/openai/codex) (OpenAI) | `~/.codex/skills/<skill>/` |

## What the skills enforce

The skills differ in detail but all follow the same house rules, which came out of real failures on real drafts:

- **Verify against primary sources, not model memory.** Cases are checked against [CourtListener](https://www.courtlistener.com/) and official reporters; scholarship against the user's Zotero library and then the open web. Nothing is reported as verified without saying *on what basis*.
- **Deterministic scripts for structure, models for judgment.** Footnote extraction, `Id.`/`supra` resolution, quote matching, and schema validation are plain Python so they cost zero tokens and cannot hallucinate. Model agents handle only the parts that need reading.
- **Verify the verifier.** Multi-agent runs end with an independent pass over the findings before anything reaches the user, because the first pass produces confident false positives.
- **Budgets enforced by script.** Fetch sizes, page counts, chunk sizes, and token ceilings are hard caps in code, with a documented degradation ladder for when a run exceeds them.
- **Report for a reader in Word.** Findings carry verbatim find-strings and footnote numbers rather than internal paragraph ids, so each one can be located with Cmd+F.

## Claude Code skills (`claude-code/`)

| Skill | What it does |
|---|---|
| **legal-research** | Multi-agent legal research that fans out across free legal sources, verifies every authority, and returns a memo. Modes: case law, scholarship, or both. Also the shared toolbox: `check_cite.py` (CourtListener citation lookup), `cl_case_tools.py` (opinion PDFs), `fetch_page.py` (hard-capped fetcher), `citeform.py` (reads italics and small caps out of .docx runs), `md2docx.py`. |
| **cite-check** | Takes an article draft (.docx with footnotes), extracts every citation and quotation, resolves the cross-reference web, verifies each against the real source, and returns a graded footnote-by-footnote report with a "needs your attention" section first. `DESIGN.md` records the design and the lessons from the first full practice run, including where the cost estimate was wrong and what changed. |
| **proofread** | Prose-only proofreading of a long draft: typos, doubled words, editing residue, and internal consistency (hyphenation, capitalization, defined terms, cross-references). Owns the prose; cite-check owns the authorities. |
| **find-cite** | Quick, verified citation-finding for one proposition. A footnote-filler, not a memo. Prefers Supreme Court cites and flagship-journal scholarship, each with a pincite and a parenthetical, verified before delivery. |
| **build-library** | Builds or extends a Zotero collection of verified sources via the Zotero Web API, then runs a deterministic anti-hallucination check (`check_source.py`) that every added item must pass. Includes a whole-library inventory script, because delegating the duplicate check to a subagent produced duplicates. |
| **case-prep** | Gathers the full document set for a Supreme Court case (questions presented, lower-court opinion, cert-stage and merits briefs, SG amicus, argument transcript), crops margins, and loads it onto a reMarkable tablet in a per-case folder. |

### Install

```sh
git clone https://github.com/danepps/legal-research-skills.git
for s in legal-research cite-check proofread find-cite build-library case-prep; do
  ln -s "$PWD/legal-research-skills/claude-code/$s" ~/.claude/skills/$s
done
```

The skills reference each other at `~/.claude/skills/<skill>/...` (cite-check, proofread, find-cite, and case-prep all import from legal-research), so install the set together at that path.

**Credentials and environment.** Nothing is hard-coded; set what you use:

- `COURTLISTENER_API_TOKEN` (or `~/.config/courtlistener/token`): free token from [courtlistener.com](https://www.courtlistener.com/profile/api-token/). Without it, case lookups fall back to web search.
- `ZOTERO_API_KEY`, `ZOTERO_LIBRARY_ID`, `ZOTERO_LIBRARY_TYPE`, and for build-library `ZOTERO_USER_ID`: from [zotero.org/settings/keys](https://www.zotero.org/settings/keys). The scripts also look in the `zotero` MCP server entry of `~/.claude.json`.
- cite-check, proofread, and legal-research use Claude Code's `Workflow` tool (the `.workflow.js` files) for multi-agent fan-out, and cite-check and find-cite assume a Zotero MCP server for library search.
- build-library's HeinOnline sections assume an institutional library proxy; replace `<proxy-host>` with yours.
- case-prep assumes a reMarkable MCP server; the download-and-crop steps work without one.

`NOTES.md` session-handoff files and practice-run test data are not included.

## Codex skills (`codex/`)

Independent implementations for Codex CLI. These lean harder on machine-enforced completion gates: each skill has an `init_run.py` / `validate_run.py` pair, and a run is not reported complete until its validator passes a JSON schema over the run directory.

| Skill | What it does |
|---|---|
| **legal-research-memo** | Verified legal or scholarly memos: doctrinal synthesis, historical research, literature reviews, resumable investigations. References cover source protocol, subagent orchestration, autonomous runs, and a review checklist. |
| **cite-check** | Verifies citations, quotations, pincites, proposition support, cross-references, source versions, and URLs in a draft, with a documented verification protocol and schema-validated run output. |
| **internal-proofread** | Proofreads long drafts for internal textual defects using deterministic whole-document checks, bounded subagent review, an independent "challenger" pass, and machine-enforced completion gates. |
| **find-cite** | A small set of verified, footnote-ready authorities for one proposition, delivered as a validated evidence packet. |
| **build-zotero-library** | Builds or extends a verified Zotero collection, including full-text PDFs. PDFs from authenticated databases are attached from user-downloaded files, with provenance recorded; nothing automates institutional access. |
| **deep-research** | A resumable, source-grounded investigation runner for the CLI, with cost controls and anti-spiral rules. General-purpose rather than legal, but used by the legal skills. |

### Install

```sh
for s in legal-research-memo cite-check internal-proofread find-cite build-zotero-library deep-research; do
  ln -s "$PWD/legal-research-skills/codex/$s" ~/.codex/skills/$s
done
```

Each skill's `SKILL.md` lists its own environment variables.

## Status

These are working tools, not a product. They are written for a specific workflow (law-review drafts in Word, a Zotero library, free legal sources) and will need adapting elsewhere. Date-stamped notes in the skill files record why a rule exists; they are left in deliberately.

## License

MIT. See [LICENSE](LICENSE).
