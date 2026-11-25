# DOCX Handling and Output

The extractor reads visible inserted text and excludes deleted text. Disclose that tracked-change view at the start of every DOCX run. Do not accept or reject existing changes in the source draft.

The deterministic extractor reads body paragraphs, tables, referenced headers and footers, and footnotes directly from OOXML. It also indexes bookmarks and field instructions in body and footnote material; instructions are metadata, never proofreading prose. Header/footer page, page-reference, page-count, section, running-title and date/time field results are excluded; other field results retain the normal text view. Identical header/footer prose is deduplicated with every section/type/part/paragraph occurrence retained. It cannot establish final pagination, read image-only text, or fully reproduce Microsoft Word's field updating and numbering behavior. It does not resolve effective run italics, small caps, or capitalization inherited through Word styles. Do not infer displayed capitalization or make typeface findings from plain extracted text; Word may apply all caps to a heading through its style. Disclose this formatting limitation in DOCX reports.

Treat `PAGEREF` fields and prose page-number references as unresolved until the user opens the document in Microsoft Word and updates the fields. Never launch an office application to update them automatically. Treat text boxes, equations, embedded objects, pagination, and visual layout as limitations if extraction counts cannot be reconciled.

Default to report-only output. When the user requests a marked draft:

1. Preserve the original file.
2. Use a direct OOXML writer that does not launch an office application to create a new `.docx`; if none is available, stop after the report.
3. Apply a `confirmed` correction as a tracked change only when its final row in `dispositions.jsonl` carries a `replacement`. Join that row to `findings.jsonl` by `finding_id`, using explicit disposition fields when present. Replace its exact excerpt at the recorded location with that string. If the field is absent, leave the correction for manual review; never apply prose from `suggestion`.
4. Add comments for `likely`, `query`, and quoted-material findings.
   For a header/footer finding, use a body-start comment beginning with its complete
   location and exact affected words unless Microsoft documentation establishes support
   for anchors in that story. Do not infer Word compatibility from the XML schema.
5. Do not apply `rejected` or `waived` candidates.
6. Re-extract the marked copy, rerun deterministic linting, and confirm that every intended change appears and no unrelated text changed.
7. Confirm that the marked copy is a valid ZIP/OOXML package, parse every XML part, re-extract its text, and disclose that pagination and visual layout were not rendered.

Never invoke `soffice`, `libreoffice`, `render_docx.py`, the documents skill, or any helper/runtime that launches LibreOffice, whether inside or outside the sandbox.

Full quotation fidelity, source support, pincites, and Bluebook form are outside this skill. Use cite-check when those tasks are requested.
