---
name: case-prep
description: Gather the full document set for a SCOTUS case being prepped for a podcast episode, class, or article — cert-stage filings, merits briefs, lower-court opinion, questions presented, and oral-argument transcript — and load them onto the user's reMarkable in a per-case folder. Manual trigger — use when the user says "prep <case>", "grab the briefs for <case>", "load up <case>", or similar.
---

# SCOTUS case prep → reMarkable

Given a case name (and optionally a docket number), collect the canonical
reading set and upload it to the tablet under `<Project>/<Case>/`.

## Hard rules

- **Every uploaded document is a real PDF you actually downloaded.** Verify
  each file begins with `%PDF` before uploading. Never hand-construct a
  document URL and assume it worked — fetch it and check.
- **Web-confirm the caption and docket number first.** If the name is
  ambiguous (multiple granted cases, consolidated cases, common party
  names), confirm with the user before downloading the wrong case's briefs.
- **Report gaps honestly.** If a document isn't filed yet, isn't public, or
  can't be found, say so in the final manifest. Never substitute a
  look-alike document.

## Step 1 — Resolve the case

1. Web-search the case name to confirm the exact caption and Supreme Court
   docket number (format `NN-NNN`, e.g. `24-316`). Good confirming sources:
   supremecourt.gov, SCOTUSblog's case page, Oyez.
2. Note whether the case is consolidated with others (grab the lead docket;
   mention companions in the manifest).
3. Note argument status: not yet argued / argued (transcript available) /
   decided.

## Step 2 — Download documents (to the scratchpad, via curl)

**Docket page** (index of every filing, with PDF links):
`https://www.supremecourt.gov/search.aspx?filename=/docket/docketfiles/html/public/<DOCKET>.html`
Fetch it and extract the `DocketPDF` links. Entry text identifies each
filing ("Petition for a writ of certiorari filed", "Brief of petitioner",
"Brief amicus curiae of United States", etc.).

**Default document set** (in reading order — skip whatever doesn't exist
yet; note it in the manifest):

| # | Document | Source |
|---|----------|--------|
| 00 | Questions presented | `https://www.supremecourt.gov/qp/<TERM>-<5-digit-zero-padded-number>qp.pdf` (e.g. docket 24-316 → `24-00316qp.pdf`) |
| 01 | Lower-court opinion | CourtListener (below) |
| 02 | Cert petition | docket page |
| 03 | Brief in opposition | docket page |
| 04 | Cert-stage reply | docket page |
| 05 | Petitioner's merits brief | docket page |
| 06 | Respondent's merits brief | docket page |
| 07 | Merits reply brief | docket page |
| 08 | U.S. / SG amicus brief (if any, either stage) | docket page |
| 09 | Oral-argument transcript (if argued) | `https://www.supremecourt.gov/oral_arguments/argument_transcripts/` — links follow `.../argument_transcripts/<TERM>/<docket>_<suffix>.pdf`; find the real link on the term's transcript index page |

Other amicus briefs: **don't** download them all by default (there can be
dozens). Tell the user how many were filed and offer to add specific ones.

**Lower-court opinion via CourtListener:** search
`https://www.courtlistener.com/api/rest/v4/search/?q=<case name>&court=<lower court id>`
or the website search, matching the docket number / caption from the cert
petition (the petition's first pages identify the opinion below precisely).
Then resolve and download the PDF deterministically with the legal-research
skill's helper (prefers CourtListener's stored copy, falls back to the
court's own file, verifies `%PDF` magic before saving):
```
python3 ~/.claude/skills/legal-research/cl_case_tools.py pdf cluster:<cluster_id> --out "01 Lower-court opinion.pdf"
```
(`cluster_id` comes from the search result; a reporter cite works too once
one exists). If no PDF is on CourtListener or the court's site, the cert
petition's appendix contains the opinion below — flag that as the fallback
rather than uploading something unverified.

Use a browser-plausible User-Agent for supremecourt.gov (it 403s bare
curl): `curl -sL -A "Mozilla/5.0" -o <file> <url>`.

## Step 3 — Upload to the reMarkable

Tools: the `remarkable_*` MCP tools (if not loaded:
`ToolSearch "select:mcp__remarkable__remarkable_upload,mcp__remarkable__remarkable_mkdir,mcp__remarkable__remarkable_browse"`
— adjust prefix to whatever the connected server exposes).

1. **Crop margins first** — run this skill's `crop_pdf.py` on every PDF so
   documents open margin-free on the tablet (the user shouldn't have to adjust
   borders by hand):
   `uv run <this skill's directory>/crop_pdf.py <file.pdf>`
   A nonzero exit means no plausible content box was found — upload that
   file uncropped rather than failing.
2. `remarkable_mkdir` → `<Project>/<Short Caption>` (e.g.
   `SCOTUS Prep/Smith v. Arizona`).
3. Upload each PDF named `NN Title.pdf` per the table (keep the numbers so
   they sort in reading order), e.g. `02 Cert Petition.pdf`,
   `06 Respondent Merits Brief.pdf`.
4. `remarkable_browse` the folder afterward to confirm everything landed.

## Step 4 — Report

Give the user a manifest: caption, docket number, argument date/status, each
document uploaded (with filing date where the docket shows it), each
document *not* available and why, companion cases, and the amicus count
with an offer to pull specific ones.
