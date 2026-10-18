# Bluebook typeface & short forms — the rules this skill applies

Written down 2026-08-10 because these are the two conventions nobody remembers, and
because a checker that flags them should show its work. Everything here is decidable
from the draft alone — no external source needed — which is why it lives in `/proofread`
and not in `/cite-check`.

Scope note: this is the **law review footnote** convention (Bluebook Rule 2.1(a), Rule
4.2, Rule 10.9), not the Bluepages/practitioner convention (B2, B10.2), which italicizes
case names everywhere. Journals impose their own house style at the editing stage; these
checks describe deviations, they do not settle them.

---

## 1. Typeface — what is italic in a footnote

**Italic:**

| Thing | Examples |
|---|---|
| Introductory signals | *See*, *See also*, *See generally*, *Cf.*, *Compare* … *with* …, *But see*, *But cf.*, *Accord*, *Contra*, *E.g.* |
| Short-form and cross-reference words | *Id.*, *supra*, *infra* — but NOT "hereinafter", see below |
| Subsequent history | *aff'd*, *rev'd*, *cert. denied*, *overruled by*, *abrogated by* |
| Case names in **textual sentences** | "in the early case *Hylton v. United States*, the Justices …" — including textual sentences that sit inside a footnote |
| Case names in **short forms** | *Hylton*, 3 U.S. at 174 |
| Article titles | Erwin Chemerinsky, *In Defense of Judicial Supremacy*, 58 Wm. & Mary L. Rev. 1459 (2017) |
| Procedural phrases in a case name | *In re* Smith, *Doe* ex rel. *Roe* |

**Roman — the ones people get backwards:**

| Thing | Examples |
|---|---|
| Case names in a **full citation standing in a citation clause or sentence** | See Knowlton v. Moore, 178 U.S. 41, 106 (1900). |
| The note reference after an italicized *supra*/*infra* | *supra* note 3 — not *supra note 3* |
| The "at" of a short form | *Hylton*, 3 U.S. at 174 |
| Punctuation separating a name or title from its citation | *Hylton*, 3 U.S. … — the comma is roman |
| The word "hereinafter" | [hereinafter *Hearings*] — only the short title takes the typeface of the full cite (italic article title, small-caps book); "hereinafter" itself is roman. Verified 2026-10-07 against Georgetown Writing Center, *Differences in Citation in Scholarly and Practitioner Legal Writing* (2026) § III.A, which also writes "*Supra* and hereinafter" with only *supra* italic. |
| "quoting" / "citing" in an explanatory parenthetical | (quoting Marbury v. Madison, 5 U.S. (1 Cranch) 137 (1803)) — roman in law review footnotes (Bluebook R. 1.5(b), 10.6.3 examples). Italicizing them is the Bluepages/practitioner convention ("explanatory phrases introducing … related authority," B2), which is where the earlier version of this table got it from. |

**Large and small caps:** book authors and titles, institutional authors, and periodical
names (Harv. L. Rev.). Checked here for *consistency* across the draft rather than against
the rule in the abstract, since drafts legitimately differ on how much of a source gets
small caps.

### The distinction that does the work

The same case name is roman or italic depending on **where it sits**, not on what it is:

> See Knowlton v. Moore, 178 U.S. 41 (1900).   ← citation clause → **roman**
> Flint relied on *Veazie Bank v. Fenno*, 75 U.S. 533 (1869). ← textual sentence → **italic**

A name opens a citation clause when it follows a signal ("See, e.g.,"), an explanatory
phrase ("(quoting"), a semicolon stringing cites together ("); and"), or the start of the
footnote. It is textual when ordinary prose runs into it ("relied on", "in the case of").
A deterministic pattern gets this wrong often enough that the script only *nominates*
case names; a model agent reads the sentence and decides.

---

## 2. Short forms

### Cases — Rule 10.9

A short form is permitted when the case was cited in full **in the same footnote or in one
of the preceding five footnotes**. That single window cuts both ways:

- **Inside the window**, a repeated *full* citation is the error — use `Hylton, 3 U.S. at
  174`.
- **Outside the window**, repeating the full citation is *correct*, so a repeat five-plus
  notes later is not flagged. What *is* flagged is a bare short form stranded out there:
  the reader has nothing nearby to resolve it against.
- A short form appearing **before** the case is ever cited in full is almost always
  renumbering residue from a moved footnote.

Cases and statutes do **not** take `supra`.

### Secondary sources — Rule 4.2

After one full citation, every later reference is `Author, supra note N, at X`. There is
**no distance window** — a second full citation of the same article or book is flagged
wherever it appears.

### What the checker does not decide

Whether the short form should be the case name, a party name, or a draft-defined
shorthand ("*Pollock II*") is the authors' call. Short-form resolution here is deliberately
loose — it matches on the first party's leading word — so a draft's own naming convention
resolves rather than generating noise. It errs toward silence.

---

## 3. All caps is not capitalization

Word applies ALL CAPS to Part headers through the paragraph **style** (`<w:caps/>` on
`Heading1`), not by storing capital letters. A header stored as `understanding
temporalism` and one stored as `OPTIMIZING temporalism` print identically. Nothing
downstream may draw a capitalization finding from a paragraph flagged `display: ALL CAPS`
— the reader never sees the stored casing. Their wording and spelling are still checked.
