# DOCX Handling and Output

The extractor reads visible inserted text and excludes deleted text. Disclose that tracked-change view at the start of every DOCX run. Do not accept or reject existing changes in the source draft.

The deterministic extractor reads body paragraphs, tables, headers, footers, footnotes, bookmarks, and field instructions directly from OOXML. It cannot establish final pagination, read image-only text, or fully reproduce Microsoft Word's field updating and numbering behavior.

Treat `PAGEREF` fields and prose page-number references as unresolved until the user opens the document in Microsoft Word and updates the fields. Never launch an office application to update them automatically. Treat text boxes, equations, embedded objects, pagination, and visual layout as limitations if extraction counts cannot be reconciled.

Default to report-only output. When the user requests a marked draft:

1. Preserve the original file.
2. Use a direct OOXML writer that does not launch an office application to create a new `.docx`; if none is available, stop after the report.
3. Apply only `confirmed` corrections as tracked changes.
4. Add comments for `likely`, `query`, and quoted-material findings.
5. Do not apply `rejected` or `waived` candidates.
6. Re-extract the marked copy, rerun deterministic linting, and confirm that every intended change appears and no unrelated text changed.
7. Confirm that the marked copy is a valid ZIP/OOXML package, parse every XML part, re-extract its text, and disclose that pagination and visual layout were not rendered.

Never invoke `soffice`, `libreoffice`, `render_docx.py`, the documents skill, or any helper/runtime that launches LibreOffice, whether inside or outside the sandbox.

Full quotation fidelity, source support, pincites, and Bluebook form are outside this skill. Use cite-check when those tasks are requested.
