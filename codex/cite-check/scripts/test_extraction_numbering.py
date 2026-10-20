#!/usr/bin/env python3
"""Regression test for DOCX note IDs that differ from displayed numbering."""

from pathlib import Path
import tempfile
import zipfile

from extract_cites import extract_document
from prepare_units import build_prepared_units


def main() -> int:
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "draft.docx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("word/document.xml", f'''
                <w:document xmlns:w="{namespace}"><w:body>
                <w:p><w:r><w:t>“The first quoted source has enough words for extraction.”</w:t></w:r>
                <w:r><w:footnoteReference w:id="2"/></w:r></w:p>
                <w:p><w:r><w:t>“The second quoted source also has enough words for extraction.”</w:t></w:r>
                <w:r><w:footnoteReference w:id="3"/></w:r></w:p>
                </w:body></w:document>''')
            archive.writestr("word/footnotes.xml", f'''
                <w:footnotes xmlns:w="{namespace}">
                <w:footnote w:id="2"><w:p><w:r><w:t>Authority One.</w:t></w:r></w:p></w:footnote>
                <w:footnote w:id="3"><w:p><w:r><w:t>Authority Two.</w:t></w:r></w:p></w:footnote>
                </w:footnotes>''')
        extraction = extract_document(path)
        prepared = build_prepared_units(extraction)
        assert [row["footnote_number"] for row in prepared] == [1, 2]
        assert [row["full_footnote"] for row in prepared] == ["Authority One.", "Authority Two."]
        focused = build_prepared_units(extraction, {2})
        assert len(focused) == 1 and focused[0]["full_footnote"] == "Authority Two."
    print("DOCX footnote-numbering tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
