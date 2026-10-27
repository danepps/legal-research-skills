# Cite-check report — "test draft" (293 footnotes)

Topic: Cite-check of test draft.docx — PARTIAL PASS, footnotes 1–30 only (a test of the opt-in proposition-support pass)
Date: 2026-10-26 16:34 CDT
By: Claude-fable-5-1

> **Scope note.** This run checked footnotes 1–30 of 293 (21 quotations, 2 case cites, 39 secondary sources, 31 support units). Counts below describe that range, not the whole draft; the "293 footnotes swept" phrasing is the workflow's standard title and should be read with this note.

**TL;DR.** 293 footnotes swept. 21 quotations checked: 9 verbatim, 2 marked alterations, **0 mismatches**, 0 syllabus quotes, 0 superseded sources, **4 pincite issues**, 6 unverifiable (no text obtainable). 2 case cites checked, both confirmed, no reporter typos; 0 broken supras; 39 of 39 unquoted secondary sources existence-checked (0 not found, 3 unconfirmed from free sources); 0 missing subsequent history, 0 treatment flags; 4 URLs checked, none dead (one SSRN link returned 403, bot-blocked but presumptively live). Nothing rose to high severity this run. **8 of 50 citation instances are existence-only** — confirmed to exist, never read for whether they support the proposition. The proposition-support pass ran (opt-in, pincited scope): 20 unquoted cites in scope, 9 read — 6 supported, 1 qualified (posture), 0 overstated, **2 not supported**, 0 contradicted — and 11 in-scope cites unverifiable because no page text could be reached; 11 bare whole-work cites were not read (out of scope), 0 dropped for budget. Everything below rests on a fetched source; nothing was judged from memory. The two items most worth your time are the two not-supported cites in section H (n.19 cites the wrong page of the Défenseur des droits site; n.25's Federalist No. 37 cite does not carry the property/majority-rule claim), followed by the four pincite corrections in section D.

---

## D. Wrong pincites & citation typos

1. **n.10 — Skolnik pincite is 1724, not 1723.** Find: `limits the capacity of public defenders and court-appointed counsel to protect defendants’ constitutional rights in the criminal justice process`
   - Draft: 66 B.C. L. Rev. 1679, **1723**.
   - Source (journal's own PDF, printed running header "1724" at the top of the page; the sentence follows the text of n.324 on that page): "Underfunding thus limits the capacity of public defenders and court-appointed counsel to protect defendants’ constitutional rights in the criminal justice process."
   - Quote is verbatim and in the author's own voice; the draft's "inadequate funding" framing is faithful. **Fix: change 1723 to 1724.**

2. **n.2 — Barton pincite looks one page low (1233, cited 1232); confirm before changing.** Find: `may not have been consistent with the original understanding of the Constitution, but it is hard to argue in retrospect that it was not absolutely the right decision`
   - Draft: 62 Fla. L. Rev. 1227, **1232**.
   - Source (Florida Law Review PDF, pages set by form-feed breaks with first page 1227): "Nonetheless, Gideon is a little bit like Brown v. Board of Education. It may not have been consistent with the original understanding of the Constitution, but it is hard to argue in retrospect that it was not absolutely the right decision." The passage sits about 1,400 characters into the page the script numbers 1233.
   - Quote verbatim, Barton's own words, framing faithful. Form-feed pagination can be off by one; check the print page before editing.

3. **n.16 — Barkow, *Administering Crime*: passage appears on 727, cited 728; confirm against the Hein page image.** Find: `one of the most—if not the most—powerful lobbying groups in criminal law consists of those charged with exercising the penal power`
   - Draft: 52 UCLA L. Rev. 715, **728**.
   - Source (HeinOnline PDF attached to Zotero item 5PV4FMJV): "Perhaps because government interference is a given, one of the mostif not the most-powerful lobbying groups in criminal law consists of those charged with exercising the penal power: law enforcement and, in particular, prosecutors." (The OCR dropped the em-dashes; the words are otherwise identical, so the quote is verbatim.) The running head "Administering Crime 727" precedes the passage and "52 UCLA LAW REVIEW 715 (2005) / 728" follows it, which places it on 727 — unless the Hein extraction puts running heads at the page foot. Author's own voice; "arguing that" framing fits.

4. **n.29 — Levinson, *Rights and Votes*, pincite 1355 is probably too high; confirm against Yale L.J. pagination.** Find: `federalism and other systems of decentralized government effectively permit groups to exit a single, centralized collective decisionmaking process`
   - Draft: 121 Yale L.J. 1286, **1355**.
   - Source (Zotero item 3G2BEKZ4 fulltext): "federalism and other systems of decentralized government effectively permit groups to exit a single, centralized collective decisionmaking process by claiming autonomy over certain issues." Quote verbatim, Levinson's own voice, accurately framed as explaining exit.
   - The Zotero text has no page markers; a running-head count (about 34 of 38 heads precede the passage, which is followed by the article's n.319) puts it roughly at 1319–20 in an article the checker estimated at 1286–1323. Rough inference only — verify on Hein or the journal before changing.

---

## E. Article/book metadata discrepancies

**Errors (fix)**

- **n.25 — Farrand cite is incomplete.** Find: `Farrand WEDNESDAY, MAY 30TH, 1787.` The footnote gives a bare day heading with no editor, volume, or page. Supply the full cite: Max Farrand ed., The Records of the Federal Convention of 1787, vol. 1, at __ (1911). [source: the checker fetched Yale Avalon's Madison notes for May 30 and June 26; neither page contains the quoted phrase, so the date question below is a confirm item, not a finding.]
- **NORC brief — title reads "Long-Term Care Ombudsman Program," draft has "Ombudsmen Program."** Find: `Ombudsmen Program`. Authors (Kim Nguyen, Emily White), publisher (NORC), date (Sept. 2019) and page 1 otherwise match the cover page. [source: https://acl.gov/sites/default/files/programs/2020-10/NORC%20Research%20Brief_Systems%20Advocacy_508.pdf]

**Confirm**

- **n.25 — Farrand date.** Confirm whether "protect the minority of the opulent against the majority" is from May 30 or from Madison's June 26 speech. The first checker's recollection was June 26 (1 Farrand 422), but that is memory, not a fetched source, and neither Avalon page fetched contains the phrase; check Farrand vol. 1 directly.
- **n.25 — Federalist No. 37 (Rossiter ed.).** Confirm the 1999 Signet Classics printing as publisher/year and the 198–99 pages; the existence pass did not reach this item (attempt cap spent elsewhere). Find: `The Federalist No. 37, at 198–99`
- **n.25 — Wood, *Empire of Liberty*, year and publisher.** Search results give publication as Oct. 28, 2009; the draft cites (2011), which may be the paperback. Confirm the edition and the Oxford University Press publisher. Find: `Empire of Liberty: A History of the Early Republic, 1789–1815, at 15–20 (2011)`
- **n.5 — Gottschalk, *Caught*, year.** The Zotero record (an Amazon import) is dated Dec. 2014, probably the 2015 hardcover; the draft says 2016, likely the paperback. Confirm the edition you cited matches the pagination (p. 2). Find: `Caught: The Prison State and the Lockdown of American Politics 2 (2016)`
- **n.12 — Eagly, *Gideon's Migration*, first page.** Search results show vol. 122 (2013) but did not show the first page; confirm 2282 and the 2300–13 pin against the Yale page. Find: `Gideon’s Migration, 122 Yale L.J. 2282, 2300–13 (2013)`
- **n.214 vs. n.10 — Primus first page.** n.10 cites 122 Mich. L. Rev. **205** (confirmed by the journal's issue index), but the full cite repeated at n.214 reads `122 Mich. L. Rev. 207, 240 (2023)`. Confirm the 207 is a typo (and see Citation form: n.214 should be a supra short form in any event).

---

## H. Proposition support (opt-in; pincited scope)

Scope: 31 unquoted citation units, 20 in scope (pincited or parenthetical), 11 bare whole-work cites out of scope and not read. 9 units read; 6 supported (counts only); 0 overstated; 0 contradicted. Both adverse verdicts below were re-derived by a second checker.

**Not supported (fix or re-cite)**

1. **n.19 — Défenseur des droits: the URL points to the wrong page.** Find: `Promotion de l’égalité et de l’accès aux droits`
   - Claim (text): "For example, the French Defender of Rights (Défenseur des droits) conducts studies, investigates complaints, and proposes legal reforms." Signal: bare *see*.
   - What the cited URL actually shows (fetched live 2026-10-26): the page headed "Le Défenseur des droits et ses adjoints" — appointment, term, biography and deputies. Sample: "Le Défenseur des droits et ses adjoints ... Les adjoints En attente de nomination." The first checker's Wayback capture likewise yielded only "Elle peut leur déléguer certaines de ses attributions." Searches of the page text for étude, réclamation, saisi, réforme, propos, Promotion, égalité hit only site-navigation menu items ("Les propositions de réforme", "Études et rapports").
   - Diagnosis: footnote title and URL are mismatched. The page the footnote *names* exists elsewhere on the site; the site's own navigation links it at `/promotion-de-legalite-et-de-lacces-aux-droits-373`. **Fix: replace the URL with the page the title names (and refresh the "last visited" date), then confirm that page actually describes studies, complaint investigation and reform proposals.**

2. **n.25 — Federalist No. 37 does not carry the majority-rule/property claim.** Find: `The Federalist No. 37, at 198–99`
   - Claim (text): "The Framers were particularly concerned, for example, that majority rule posed a significant danger to property entitlements, and tried to design the Constitution to “protect the minority of the opulent against the majority.”" Signal: *see also, e.g.*, so the source must state or clearly imply the proposition.
   - What No. 37 says (full text, Yale Avalon; the Rossiter 198–99 pages are not marked in the open text, so the whole essay was searched for property, minority, opulent, majority, wealth, rich, creditors, faction, classes, contending): the closest passage is "As every State may be divided into different districts, and its citizens into different classes, which give birth to contending interests and local jealousies, so the different parts of the United States are distinguished from each other by a variety of circumstances". The essay is about the difficulty of the Convention's task (contending class and state interests, large v. small states) and never ties any of it to majority tyranny over property.
   - Both checkers suggested No. 10 or No. 51 as the better fit. **Fix: re-cite, or drop the Federalist cite and let the Farrand cite (once completed — see E) carry the quotation.**

**Confirm: possible overstatement** — none.

**Qualified support (posture)**

- **n.26 — *United States v. Carolene Products Co.*, 304 U.S. 144, 152 n.4 (1938)** (*see also*), cited for "Most famously, John Hart Ely argued that “discrete and insular” minorities are most in need of protection against prejudice by majorities." Footnote 4 is the source of the phrase — "whether prejudice against discrete and insular minorities may be a special condition, which tends seriously to curtail the operation of those political processes ordinarily to be relied upon to protect minorities, and which may call for a correspondingly more searching judicial inquiry." — and the pincite 152 n.4 is correct (footnote anchored before the *153 marker on CourtListener). It is dicta (Stone, J., footnote) and of course does not mention Ely; fine as *see also* support, but the parenthetical, if you add one, should not attribute Ely's argument to the Court.

**Not read / unverifiable.** 11 bare whole-work cites were out of scope and not read; 0 were dropped for budget or agent failure. 11 in-scope units could not be read because no page text was reachable — they are listed with unlock paths in section I.

---

## I. Couldn't check (what would unlock each)

**Quotations with no source text obtained (6)**

- **n.6 — Ely, *Democracy and Distrust* 173 (1980)**, two quotes: `system is constructed so that ‘people like us’ run no realistic risk` and `some nonpolitical check on excessive severity is needed`. Zotero has the item (ETI78ZHV) but no attachment; the Google Books lookup hit a quota error. Unlock: p. 173 from the print copy or an archive.org/Hein scan, or attach a PDF to ETI78ZHV and rerun.
- **n.25 — Farrand**, quote `protect the minority of the opulent against the majority.` No Farrand item in Zotero; the Avalon pages for May 30 and June 26 do not contain "opulent". Unlock: Farrand vol. 1 (archive.org or HathiTrust scan) or the Library of Congress Century of Lawmaking page for Madison's notes. Also fix the incomplete cite (section E).
- **n.4 — Butler, *The System Is Working the Way It Is Supposed to*, 104 Geo. L.J. 1419, 1425 (2016)**, quote `national consensus that there is a race problem in criminal justice`. Not in any Zotero library; Georgetown PDF guess and journal page 404, SSRN 403, one guessed repository URL returned an unrelated article (the verifier's not_found there says nothing about the draft). Existence also unconfirmed from free sources. Unlock: Hein/Westlaw or the Georgetown Law Journal site PDF; or add to Zotero with PDF.
- **n.8 — Golden & Lee, 92 Fordham L. Rev. 397, 410 (2023)**, quote beginning `[T]he Constitution provides many indicators of the special sensitivity of criminal matters`. Not in Zotero; Fordham repository PDF and SSRN returned 403. The Fordham issue listing confirms the article, title and authors; quote and pincite 410 unverified. Unlock: Hein/Westlaw PDF or add to Zotero.
- **n.10 — Primus, 122 Mich. L. Rev. 205, 210 (2023)**, quote `Assigned-counsel and flat-fee contract systems fuel mass incarceration.` Only the repository abstract was reachable (PDF 403); the abstract makes the same substantive claim ("In those assigned-counsel and flat-fee contract systems, the lawyers representing indigent defendants have financial incentives to get rid of assigned criminal cases as quickly as possible. Those incentives fuel mass incarceration because the lawyers put less time into each case.") but the exact sentence and p. 210 are unconfirmed. Unlock: Hein/Westlaw pull or add the PDF to Zotero.

**Proposition-support units not readable (11)** — each confirmed to exist; the pincited pages could not be read.

- **n.4 — Garrett, *Defending Due Process* 6 (2025)** (cataloguing threats to due process), for "Six decades after the decision, there is near consensus that our criminal process remains too harsh, too arbitrary, and too stratified on racial and class lines." Not in Zotero; only the catalog blurb seen. Unlock: library copy or Wiley preview, p. 6.
- **n.5 — Barkow, *Prisoners of Politics* 5 (2019)** (*see also, e.g.*), for "Critics blame these many failings on a politics of criminal punishment decried as “pathological.”" In Zotero without an attachment; the abstract ("America’s criminal justice policy reflects irrational fears stoked by politicians seeking to win election.") fits the proposition generally, but p. 5 was not read. Unlock: attach PDF/ebook or pull the print copy.
- **n.5 — Gottschalk, *Caught* 2 (2016)**, same proposition. In Zotero (dated 2014; see E on edition), no full text. Unlock: attach PDF or pull the 2016 paperback.
- **n.9 — Ortman, *Confrontation in the Age of Plea Bargaining*, 121 Colum. L. Rev. 451, 463–64 (2021)**, for "Moreover, political actors can impose heavy costs on actually exercising rights, reducing constitutional protections in many cases to rights theater." Not in Zotero; Columbia site gave only the abstract, Wayne State repository PDF 403. Unlock: Hein/Westlaw or SSRN PDF, read 463–64.
- **n.12 — Eagly, *Gideon's Migration*, 122 Yale L.J. 2282, 2300–13 (2013)**, for extending appointed counsel to immigration. Not in Zotero; openYLS demands a login, guessed Yale PDF URLs 404. Unlock: yalelawjournal.org/article/gideons-migration PDF or Hein.
- **n.13 — Kleinman, *Housing Gideon*, 31 Fordham Urb. L.J. 1507, 1532**, for extending appointed counsel to eviction. Not in Zotero; only the Fordham issue index reached; existence also unconfirmed from free sources (several secondary sources cite it as the draft does). Unlock: ir.lawnet.fordham.edu/ulj/vol31 or Hein; check the 1532 pin.
- **n.14 — Barton & Bibas, *Triaging Appointed-Counsel Funding and Pro Se Access to Justice*, 160 U. Pa. L. Rev., at 977–80**, for the "civil Gideon" sentence. Not in Zotero; Penn repository PDF guesses 404. Unlock: scholarship.law.upenn.edu/penn_law_review/vol160/iss4/2 PDF or Hein.
- **n.16 — Eisenberg, *Incarceration Incentives in the Decarceration Era*, 69 Vand. L. Rev. 71, 106 (2016)**, for the parenthetical `provide[s] moral authority for pro-incarceration policies`. Not in Zotero; Vanderbilt PDF 403; repository landing page had no match for the phrase. Unlock: Hein/Westlaw PDF or the FSU repository copy (ir.law.fsu.edu/articles/408).
- **n.17 — Luban, *Lawyers and Justice* xix–xxi (2018)**, for "The Advocate would be motivated to zealously defend her constituency because of role morality, not self-interest." Zotero attachment stops at the epigraphs. Unlock: 2018 Princeton edition via De Gruyter (WashU proxy), read xix–xxi.
- **n.25 — Wood, *Creation of the American Republic* 403–09 (1998)**, for the majority-rule/property sentence. Zotero item QWAAQWVQ exists without fulltext; Google Books and archive.org returned nothing readable. Unlock: attach a scan to QWAAQWVQ or check the print copy.
- **n.25 — Wood, *Empire of Liberty* 15–20 (2011)**, same sentence. Not in Zotero; nothing readable found. Unlock: add to Zotero with PDF or check pp. 15–20 in print.

**Not checked this run (agent failure)** — none. **Adverse support verdicts not re-derived** — none.

---

## J. Citation coverage ledger

50 citation instances were inventoried across the 293 footnotes: 8 existence-only, 4 finding, 2 support-finding, 7 supported, 11 support-unverifiable, 6 verified, 5 unverifiable, 5 xref, 2 not-a-citation. The 8 **existence-only** instances were confirmed to exist but were **not** read for whether they support the proposition they are cited for (the support pass read only the supported / support-finding / support-unverifiable instances); the 5 **xref** instances (*Id.*, *supra*, short forms) inherit their antecedent's status.

**Unchecked (no pass reached them):** none.

**Unverifiable (existence not confirmable from free sources; quote-level items are above in I):**
- n.4 — Paul Butler, The System Is Working the Way It Is Supposed to: The Limits of Criminal Justice Reform, 104 Geo. L.J. 1419, 1425 (2016)
- n.8 — See, e.g., John M. Golden & Thomas H. Lee, Article III, the Bill of Rights, and Administrative Adjudication, 92 Fordham L. Rev. 397, 410 (2023)
- n.10 — Eve Brensike Primus, The Problematic Structure of Indigent Defense Delivery, 122 Mich. L. Rev. 205, 210 (2023)
- n.25 — [Farrand WEDNESDAY, MAY 30TH, 1787.]
- n.29 — Levinson treats “exit” as a distinct third mechanism, separate from rights or votes. (This is footnote prose, not a citation — a parser artifact; the actual Levinson cite, `Levinson, supra note 23`, resolved to Zotero 3G2BEKZ4 and matches.)

**Unresolved cross-references:** none.

---

## Citation form

Governing rules, so you can check the calls: a case may be short-cited if it was cited in full in the same footnote or one of the preceding five footnotes (R. 10.9); a secondary source takes "Author, *supra* note N" from its second appearance onward, with no distance limit (R. 4.2); and in law review footnotes case names are roman in full citations standing in a citation sentence or clause but italic in textual sentences and in short forms (R. 2.1(a)).

**Short forms**
- n.121 — `See Terry Skolnik, Criminal Justice and the Erosion of Constitutional Rights, 66 B. C. L. Rev. 1679, 1736–45 (2025)` — full citation repeated; first cited in full at n.10 — use "Skolnik, *supra* note 10, at 1736–45".
- n.214 — `See, e.g., Eve Brensike Primus, The Problematic Structure of Indigent Defense Delivery, 122 Mich. L. Rev. 207, 240 (2023)` — full citation repeated; first cited in full at n.10 — use "Primus, *supra* note 10, at 240" (and see E on the 207/205 first-page discrepancy).

**Typeface**
- n.29 — `See generally Levinson, supra note 23.` — *supra* not italicized — italicize.
- n.89 — `Peter W. Low & Benjamin Charles Wood, Lambert Revisited, 100 Va. L. Rev. 1603, 1616 (2014).` — comma after the italicized title is inside the italics — move it outside.
- n.108 — `See Stephanos Bibas, The Real-World Shift in Cri` — signal *See* not italicized — italicize.
- n.163 — `See Irene Oritseweyinmi Joe, Systematizing Public Defender Rationing, 93 Denv. L. Rev. 389 (2016)` — comma after the italicized title is inside the italics — move it outside.
- n.250 — `Id.` — not italicized — italicize.
- n.267 — `See Saturno & Lynch, supra note 263, at 4-7.` — neither *See* nor *supra* italicized — italicize both.
- n.278 — `See 31 U.S.C. § 716(b)(2).` — signal *See* not italicized — italicize.
- n.245 — `Mistretta v. United States, 488 U.S. 361, 407 (1989)` — full citation in a citation sentence set in italics — set the case name roman; keep *See* italic.
- ¶137 (text) — `Brady v. United States by fashioning` — case name in a textual sentence set roman — italicize *Brady v. United States* (the later short "Brady" in the paragraph is already italic).
- ¶181 (text) — `Trump v. Slaughter.` — case name in a textual sentence set roman — italicize *Trump v. Slaughter*; period and footnote call stay roman.

**Document-wide conventions**

| Issue | Dominant | Minority | Recommendation |
|---|---|---|---|
| Case names in full citations in footnotes | roman (28) | italic (1) | Inconsistent; R. 2.1(a) puts them in roman |
| Case names in textual sentences of footnotes | italic (1) | roman (6) | Inconsistent; R. 2.1(a) puts them in italics |
| Case names in body text | italic (3) | roman (2) | Inconsistent; R. 2.1(a) puts them in italics |

---

## Method note

Deterministic extraction of every footnote, with deterministic supra-resolution and existence checks; quotations verified by agents against fetched source text; a mandatory verify-the-verifier pass re-derived every high-severity and every adverse support verdict (0 checker artifacts caught this run; 0 single-checker items); free/open-web sources only (CourtListener, journal and repository PDFs, Zotero attachments, Yale Avalon), so a Westlaw/Lexis + manual Bluebook pass is still recommended. On the Zotero question: the support pass does not *require* Zotero, but Zotero was the first stop and did the work wherever it held an attachment (Barkow, *Administering Crime*, and Levinson, *Rights and Votes*, were read from Zotero fulltext); where the library had no item or a metadata-only record, the pass fell back to the open web, and that fallback — 403s from SSRN, Fordham, Vanderbilt, Wayne State, Michigan; login walls at Yale — is what produced most of the 11 support-unverifiable and 6 quote-unverifiable items above. Attaching PDFs to the Zotero items named in section I and rerunning is the cheapest unlock for nearly all of them. Coverage limits, plainly: every citation instance is inventoried in section J; quoted passages were verified against fetched text; case cites and unquoted secondary sources were existence/metadata-checked; the unquoted cites in scope (pincited or parenthetical; bare whole-work cites were not read) were read for proposition support through their signals — a judgment, re-derived by a second checker for every not-supported/contradicted verdict; subsequent history and treatment were checked against CourtListener's opinion index and the RECAP docket archive (federal, incomplete), not Shepard's/KeyCite, and no hits is not proof of good law.

---
Production details: Claude Code /cite-check (branch cite-check-proposition-support, plugin 1.6.0 pre-release), support:true, supportScope pincited, deep:false, history:true, Zotero server "zotero" (personal library); partial pass unitIds for footnotes 1–30; 9m 36s; 1,989,264 subagent output tokens across 34 agents (workflow agents Claude Sonnet ×33 + Claude Fable 5.1 report; orchestrator overhead not included).
  Draft checked: test draft.docx, SHA-256 183db96397e5854bb11df0b0dcdad2108bc325065fb8981ddaaf5d8853c8003a (report is stale if the hash no longer matches the draft). Live draft re-hashed at delivery: unchanged.
