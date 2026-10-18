---
name: build-library
description: Build or extend a Zotero collection of verified sources for a project — find the sources (web, catalogs, HeinOnline via an institutional library proxy), add them with full metadata via the Zotero Web API, then run a deterministic anti-hallucination check that every added item must pass. Trigger when the user wants sources gathered into Zotero ("build a library for X", "add the books/articles on X to my Zotero", "populate <collection> with …").
---

# Build Library

Populate a Zotero collection with sources for a project. Two-layer defense against
fabricated sources: (1) verify every candidate against a real source *before* adding;
(2) after adding, run the bundled **deterministic checker** — no item ships unverified.
All global authority rules (never invent a cite; flag uncertainty) apply throughout.

## 0. Step zero — read the whole library before you do anything else

**Before scoping, before searching, before proposing a single candidate**, dump the target
library and *read all of it*:

```
python3 ~/.claude/skills/build-library/library_inventory.py --group <ID>   # or --user
python3 ~/.claude/skills/build-library/library_inventory.py --group <ID> --grep <terms>
```

One line per top-level item: year, PDF-or-not, authors, title, publication, item key.
A 100-item library is well under 3k tokens. There is no budget reason to skip this and no
substitute for it. For a large library (thousands of items), save the full dump to a file and
read the relevant `--grep` slices plus the overall shape — but the coordinator still owns the
check, and a slice that was never grepped is not evidence of absence.

This is step zero rather than part of the dedup screen because knowing the library changes
*what you go looking for*. A run that skips it will propose things the user already owns,
describe them as "newly identified," and make false claims about gaps in the collection.

**Four hard rules, each from a real failure (2026-08-01, on a 105-item group library):**

1. **Never delegate the inventory or the dedup check to a subagent.** A research subagent
   reported that group held "only the 13 listed items plus a handful of unrelated works."
   It held 105. The coordinator believed it and created three duplicates. Subagents are
   fine for *finding* candidates; the coordinator owns *knowing the library*.
2. **Treat a subagent's negative finding as unverified.** "I checked and it's not there"
   is exactly the claim subagents get wrong, because absence is unfalsifiable from inside
   a narrow search. Re-check any "not in the library" claim against your own inventory.
3. **Every add goes through the check, including late ones.** Two of the three duplicates
   were added at the very end of the session, off the back of footnotes in an article that
   had just been read — outside the main pipeline, so they skipped the screen entirely.
   No candidate is too small or too late to check; grep the inventory you already have.
4. **Pass the inventory down.** Any subagent asked to find sources gets the actual list
   (or a filtered slice) pasted into its prompt — never an instruction to go check itself.

**The library is also evidence.** When the task is "what's missing," what the user already
owns tells you what they care about and often reframes the answer. In the run that
prompted this rule, the user's library turned out to hold a deep shelf of criminal-law
scholarship on exactly the topics the memo had just described as unaddressed — which
changed the finding from "nobody has written about this" to "these two literatures don't
cite each other." Read the inventory for what it says about the project, not just for
duplicate-matching.

## 1. Zotero plumbing

The `zotero` / `zotero-group` MCP tools are **read-only** (good for duplicate checks and
search). All writes go through the Zotero Web API v3 with the key from the `zotero` entry
in `~/.claude.json` (`env.ZOTERO_API_KEY`; verified to have write access to the personal
library, `<USER_ID>`, and any group libraries you use).

- Collections: `GET /users/<USER_ID>/collections?limit=100` → find the target key; create
  with `POST /collections` if the user wants a new one (confirm name first).
- **Duplicate check — inventory first (§0), screen the candidate list (§2a), backstop
  before adding**: read the whole library up front (§0); dedup the candidate list before
  any verification or PDF work (§2a); then keep a lightweight final check right before the
  `POST /items` as a backstop — it catches items added earlier in the same run and
  exact-edition collisions the earlier screens miss. For one-off lookups mid-run,
  `library_inventory.py --grep <terms>` beats `mcp__zotero__zotero_search_items`, because
  it searches the list you already hold rather than issuing a fresh narrow query.
- Create items: `POST /users/<USER_ID>/items` with a JSON array (≤50/request). Check the
  response's `success`/`failed` maps. Get a blank template from
  `GET https://api.zotero.org/items/new?itemType=book` when unsure of fields.
- Conventions: illustrators/“with”-credits → `contributor` creators plus an
  `extra` note (Zotero books have no illustrator role); editors → `editor`; put the
  edition's real publisher/imprint (e.g. Sentinel, not “Penguin”); full pub date when
  verified, year otherwise; ISBN always for books, DOI always for articles.

## 1a. Law-review article metadata — fixes for Zotero-Connector defects (author, 2026-07-16)

Claude creates items via the Web API, so it can get these right where the user's Zotero
Connector reliably gets them wrong. Apply to every law-review article added; Hein (§4a)
shows the correct data, so take the fields from there.

1. **Leading "The"/"A"/"An":** keep the article in natural front position — title
   `The Common Law`, never the Connector's sort-inverted `Common Law, The`.
2. **Year = the issue's year, not the volume's span.** The Connector often grabs the whole
   volume's date range; use the specific issue's year, which Hein's citation gives.
3. **Trailing question mark:** preserve it — `Are Judges Political?`, not `Are Judges Political`.
4. **Italics in titles:** the Zotero title field accepts inline HTML — wrap case names (and
   other Bluebook-italicized terms) in `<i>…</i>`, e.g. `The Real Meaning of <i>Erie</i>` or
   `Rethinking <i>Chevron</i> Deference`. Zotero renders and exports these as italics (this is
   the `<i>case name</i>` the user otherwise adds by hand).
5. **Strip appended piece-type / symposium labels from the title — but preserve real Bluebook
   designations in `extra`.** The Connector tacks designations onto the title — `Essay`,
   `Comment`, `Note`, `Foreword`, `Book Review`, `Symposium: <name>`, etc. Keep only the
   article's actual title as it heads the piece / appears in the Bluebook cite. If unsure
   whether trailing text is a real subtitle vs. an appended label, check the first page.
   - **Student notes and comments** (and other designations Bluebook prints between the author
     and the title — `Recent Development`, `Essay`, `Foreword`, `Book Review`, etc.): don't just
     discard the label. Record it in the item's `extra` field as a `genre:` line — `genre: Note`
     for a student note, `genre: Comment` for a comment (title-case; the style title-cases it
     regardless, but store it clean). The Bluebook style then inserts it in the right place
     (`Jane Doe, Note, <i>Title</i>, 120 Harv. L. Rev. 1627 (2007)`). Strip it from the title
     as above **and** add the `genre:` line — the two go together for these pieces.
   - **Anonymous student notes** (no author listed): leave the creators empty and still set
     `genre: Note`. If the `extra` field already carries other lines (e.g. `Verified-URL:`),
     add `genre: Note` on its own newline — don't overwrite them.
6. **Suffixes ("Jr.", "III", "Sr."):** Zotero has no suffix field — encode the suffix in the
   **First-name** field, appended to the given name with a comma and **no space** (lastName
   stays just the surname; never append the suffix to the last name or add a second author).
   A leading `!` on the suffix controls whether a comma is rendered before it (citeproc-js
   markup, per the author):
   - "John Smith Jr." (no comma) → `firstName: "John,Jr."`,  `lastName: "Smith"`
   - "John Smith, Jr." (with comma) → `firstName: "John,!Jr."`, `lastName: "Smith"`
   The given name incl. any middle name/initial goes before the comma (e.g. `John B.,Jr.`).
   Same mechanism for numerals/other suffixes — `John,III` vs `John,!III`, `John,Sr.` etc.
   Match whichever comma form the author/source uses.
7. **Journal Abbr (Bluebook, mixed case):** always populate the Zotero `journalAbbreviation`
   field ("Journal Abbr" in the UI) with the journal's **Bluebook** abbreviation (Table T13) in
   **normal mixed case** — `Colum. L. Rev.`, `Harv. L. Rev.`, `Nw. U. L. Rev.`, `J. Sup. Ct.
   Hist.`, `Sup. Ct. Rev.` — NOT all caps. The citation style applies the small caps itself, so
   store `Colum. L. Rev.`, never `COLUM. L. REV.` Full name stays in `publicationTitle`; the
   abbreviation goes in `journalAbbreviation`. Hein's citation display renders it in caps/small
   caps ("62 COLUM. L. REV. 633") — use it for the wording but convert to mixed case; for an
   unfamiliar journal, verify the T13 form rather than guessing. For an online companion/
   supplement, append the supplement name abbreviated per Bluebook — **`Forum` → `F.`** (e.g.
   `Harv. L. Rev. F.`), while `Colloquy` has no short form (`Nw. U. L. Rev. Colloquy`).
   Known name-specific exceptions (don't "correct" these): **`California Law Review` → `Calif. L.
   Rev.`** (not `Cal.`, even though California is `Cal.` in reporters and elsewhere). The `Calif.`
   oddity is specific to that journal — contrast **`Southern California Law Review` → `S. Cal. L.
   Rev.`**, where California takes the usual `Cal.`

## 2. Find candidates

Scope with the user if the request is open-ended (which justices/scholars/era; books
only or articles too; trade books vs. casebooks/treatises — flag judgment calls in the
report rather than silently deciding). **Do this after §0, never before** — the inventory
tells you what the user already has, which changes what is worth looking for.

Search in parallel: WebSearch; Open Library (`search.json?title=&author=` beats bare
`q=`); Wikipedia infoboxes (`/w/index.php?title=<page>&action=raw`, grep the infobox)
for publisher/date/ISBN of notable books; publisher pages. For legal scholarship, HeinOnline
(§4). Google Books API is a shared anonymous quota that is often
exhausted — treat it as bonus, not backbone.

## 2a. Screen candidates against the library

With the inventory in hand, dedup the candidate list **before** the expensive
verify → download → add pipeline (§3+). Verifying metadata and pulling PDFs (Hein curl
chains, `attach_pdf.py`) is the costly part of a run; doing it for a source already
in the library is pure waste.

1. Match each candidate against the inventory on **author + year first, title second** —
   titles vary (subtitles, "Part I", sort-inverted articles, HTML entities) but
   author-plus-year collisions are a reliable trigger for a closer look.
2. **Drop** clear matches (same work already present) — don't verify or download them.
3. **Flag, don't silently drop, ambiguous near-matches** (same author, similar-but-not-
   identical title; a different edition/printing; article vs. its online companion). You
   sometimes only pin the exact edition down during verification, so carry a genuine
   maybe forward and note it in the report rather than guessing it away.

Only the survivors go through §3. The pre-add backstop in §1 then catches within-run
duplicates and exact-edition collisions.

**If you do create a duplicate, merge before deleting.** The pre-existing item may hold
the user's PDF, annotations, tags, and collection memberships; your new one may hold
better metadata. PATCH the good fields onto the *existing* item, then DELETE yours. Never
delete the older record. (In the 2026-08-01 cleanup this recovered a real defect: the
user's Kahan item had the string "10.2307" sitting in its `issue` field and no DOI.)

**Workflow rule (author, 2026-07-16): resolve every law-review source through HeinOnline.** Hein is
the clean autonomous path (§4a: IP-authenticated, no bot wall, no gate). A source that Hein does
not carry and that no open repository serves is reported as such (§5) rather than added without
a verified record.

## 3. Verify → add → deterministic check (non-negotiable)

**Before adding**: every field you write must come from a fetched source — an Open
Library edition record (`/isbn/<isbn>.json`), a publisher page, a Wikipedia infobox, a
bookseller listing. Never write a plausible ISBN/date/publisher from memory. Beware
corrupt OL edition records (a wrong book behind an ISBN happens); cross-check any
surprise against a second source.

**After adding**, run the bundled checker on exactly what landed in Zotero:

```
python3 ~/.claude/skills/build-library/check_source.py --collection <KEY>   # whole collection
python3 ~/.claude/skills/build-library/check_source.py --keys K1,K2,K3      # just new items
```

It resolves each item's ISBN through five independent catalogs (Open Library edition +
search index, Google Books, Harvard Library, Library of Congress) or its DOI through
Crossref, and does normalized string comparison of title/authors/year. Verdicts: `PASS`,
`FAIL` (resolved but mismatched), `UNRESOLVED` (identifier not found in any catalog
checked — a prompt to re-verify, not proof of fabrication: catalogs are incomplete and
sometimes down), `BAD_ISBN` (checksum), `NO_IDENTIFIER`. `--stdin` accepts
a JSON array of Zotero-shaped items to pre-check candidates *before* adding.

**Every item you added must end PASS.** Playbook for non-PASS:
- `FAIL` on one source only → usually catalog corruption; the checker already tries the
  other sources, so a persistent FAIL usually means your data is wrong — re-verify against
  an opened authoritative page and PATCH the item (send `If-Unmodified-Since-Version:
  <item version>`). If the opened page confirms your data, record it as `Verified-URL:`
  and say so in the report rather than "fixing" correct metadata to match a catalog.
- `UNRESOLVED`/too-new-for-catalogs (books <~1 yr old) → add a fetchable authoritative
  page as `Verified-URL: <https://…>` in the item's `extra` (or the item `url`); the
  checker then requires ISBN + title + every author surname on that page. IndieCommerce
  bookstore pages (politics-prose.com/book/<isbn>) fetch cleanly; simonandschuster.com
  and strandbooks.com 403 bots.
- `NO_IDENTIFIER` → find the ISBN/DOI and PATCH it in; if none exists (older law review
  articles), verify by eye against Hein and say so explicitly in the report.
- An item **you created this run** that can't be made to PASS or explicitly hand-verified
  against an opened source gets deleted, not left in place. Never delete a pre-existing
  item — report it and let the user decide.

## 3a. Attaching the PDF (not just metadata)

To put the actual PDF on a Zotero item — not merely the citation — use the bundled
`attach_pdf.py`, which runs the Zotero Web API file-upload protocol (create attachment
child → request upload authorization with md5/size → upload bytes → register):

```
python3 ~/.claude/skills/build-library/attach_pdf.py --item <KEY> --url  <https://…pdf>  # Tier 1
python3 ~/.claude/skills/build-library/attach_pdf.py --item <KEY> --file <~/Downloads/x.pdf>  # Tier 3
```

It refuses non-PDF bytes (a bot-wall/login page starts with HTML, not `%PDF-`), so a
failed fetch fails loudly instead of attaching garbage. Three tiers, because getting the
bytes is the hard part (verified 2026-07-16):

- **Tier 1 — open-access / curl-reachable** (most law-review repositories, SSRN, digital
  commons, government PDFs): `--url` fetches with a browser UA and uploads. **Fully
  autonomous.** This is the default; try it for every added scholarly source.
- **Tier 1a — HeinOnline on campus IP or institutional VPN**: Hein authenticates plain curl by
  IP, so the whole find-article-and-download-PDF flow runs autonomously from the shell —
  no browser at all. Verified end-to-end 2026-07-16 over the VPN. Recipe in §4a; download
  with curl (cookie jar required), then `attach_pdf.py --file`.
- **Tier 2 — IP-authenticated, no per-session gate** (some HeinOnline/campus sources):
  a Zotero *connector* `saveItems` POST to `http://127.0.0.1:23119/connector/saveItems`
  makes the running Zotero desktop fetch the PDF itself. Works on campus IP; does NOT
  work for WAF-walled repos, and it creates a NEW
  item in Zotero's selected collection (reconcile/dedupe afterward).
- **Tier 3 — WAF-walled (some digital-commons `cgi/viewcontent`
  endpoints)**: the Claude-in-Chrome extension, driving the user's real browser, suppresses ALL
  browser downloads — blob, same-origin anchor, and even a genuine click on Edge's own
  PDF-viewer save button produce nothing on disk. (Cowork *can* download because it runs its
  own Chrome inside a VM with a host-mounted `~/Downloads`.) So for these: a human clicks the
  Zotero connector once, or a Cowork task downloads to `~/Downloads`; then `attach_pdf.py
  --file`.

## 4. HeinOnline (browser)

**On a campus network or your institution's VPN, no proxy is needed** —
heinonline.org authenticates by IP; use the direct URL. So: navigate to
the direct site first and check whether it shows subscriber access (Hein: "Provided By:
<your institution>"). Only fall back to the proxy flow below if it doesn't.
For Hein on an institutional IP, prefer the pure-curl flow in §4a (no browser needed at all).

Off campus, Hein works through the library proxy when the user has an **active proxy
session**. The proxy login is institutional SSO with two-factor, so the session cannot be
established by automation (and never enter credentials regardless). If a proxied page
shows the SSO/2FA login screen, pause and ask the user to complete the login in the browser
themselves, then resume — that's the expected flow, not an error. Use claude-in-chrome, in
the browser the user designates (ask via the list_connected_browsers flow):

- Entry URL pattern: `https://<proxy-host>/login?url=<target>` — rewrites to
  `<host-with-dashes>.<proxy-host>` (e.g. `access-heinonline-com.…`).
- The extension is allowed on all sites, but an action fired immediately after
  navigating to a *new* proxied hostname can fail with a spurious domain-permission
  error while the redirect settles. Wait a beat and retry once before diagnosing;
  only involve the user if the error persists across retries.
- Use it to find articles and read accurate citation data (journal, volume, first
  page, year). Hein law-review pages usually lack DOIs → record the Hein
  permalink in `extra`, verify fields by eye, and flag as hand-verified.
- The Zotero Connector extension is installed in the user's browser; its save button is an
  alternative capture path, but items still get the post-add deterministic check.

## 4a. HeinOnline via curl (campus IP or institutional VPN) — fully autonomous

When the machine's public IP is your institution's (check `curl -s ipinfo.io/json` against your institution's ASN), Hein needs no browser. All requests: browser UA + one
persistent cookie jar (`-b`/`-c` the same file). Hein chains **JavaScript** redirects that
`curl -L` won't follow — extract each `window.location="…"` target and fetch it yourself:

1. `GET https://heinonline.org/HOL/Welcome` → lands on access.heinonline.com; page should
   say "Provided By: <your institution>" (if not, you're not IP-authenticated —
   fall back to §4).
2. Citation lookup: `GET /HOL/OneBoxCitation?cit_string=110+Harv.+L.+Rev.+815` → returns a
   "Secure Request and Redirect" page with a tokenized `/HOL/mojo?…auth_token=…` URL →
   fetch it (sets session cookies) → re-fetch the OneBoxCitation URL → JS redirect to a
   `Page?…handle=hein.journals/<vol>…&page=<firstpage>` URL (relative to `/HOL/`).
3. Fetch that Page URL; its HTML contains the section's PrintRequest link, e.g.
   `PrintRequest?collection=journals&handle=hein.journals/hlr110&div=37&id=833&print=section&format=PDFsearchable&submit=Print%2FDownload`
   (the `div` is the article section; the most-repeated `id=` on the page is the current
   section's).
4. Fetch the PrintRequest URL → another JS redirect to a `PDFsearchable?handle=…` URL →
   fetch that → the PDF bytes (`application/pdf`; verify `%PDF-` magic / `file` says PDF).
   Note the PDF opens with a Hein citation cover page.
5. `attach_pdf.py --item <KEY> --file <downloaded.pdf>` (don't use `--url` here — the
   script doesn't carry the cookie jar).

## 5. Report

End with: items added (grouped sensibly), the checker's summary line (verbatim verdict
counts), any hand-verified or flagged items, judgment calls made (inclusions/exclusions),
and anything the user should prune or decide. If the deliverable is a memo file, the
global provenance-header rule applies.

**Sources not added (per the §2 workflow rule):** list any source that neither Hein nor an open
repository could supply with a verified record, with its best URL, so the user can decide
whether to add it by hand. Say plainly that it was left out and why.
