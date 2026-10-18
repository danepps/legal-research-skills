#!/usr/bin/env python3
"""Synthetic OOXML fixtures; no office application or converter is launched."""
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

SCRIPT = Path(__file__).resolve().parents[1] / 'verify_docx_ooxml.py'
NS='http://schemas.openxmlformats.org/wordprocessingml/2006/main'

def make_docx(path, body, footnote=''):
    with zipfile.ZipFile(path,'w') as z:
        z.writestr('[Content_Types].xml','<Types/>')
        z.writestr('_rels/.rels','<Relationships/>')
        z.writestr('word/document.xml',f'<w:document xmlns:w="{NS}"><w:body><w:p><w:r><w:t>{escape(body)}</w:t></w:r></w:p></w:body></w:document>')
        if footnote:
            z.writestr('word/footnotes.xml',f'<w:footnotes xmlns:w="{NS}"><w:footnote w:id="1"><w:p><w:r><w:t>{escape(footnote)}</w:t></w:r></w:p></w:footnote></w:footnotes>')

class SyncTests(unittest.TestCase):
    def run_fixture(self, body, footnote, markdown, extra=()):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);docx=root/'memo.docx';md=root/'memo.md'
            make_docx(docx,body,footnote);md.write_text(markdown)
            return subprocess.run([sys.executable,str(SCRIPT),str(docx),'--markdown',str(md),*extra],capture_output=True,text=True)

    def test_footnotes_are_retained_and_checked(self):
        p=self.run_fixture('Memo Body text.','Critical authority supports this precise proposition.', '# Memo\n\nBody text.[^1]\n\n[^1]: Critical authority supports this precise proposition.\n')
        self.assertEqual(p.returncode,0,p.stderr)
        self.assertEqual(json.loads(p.stdout)['substantive_sync']['markdown_coverage'],1.0)

    def test_missing_footnote_fails(self):
        p=self.run_fixture('Memo Body text.','', '# Memo\n\nBody text.[^1]\n\n[^1]: Critical authority supports this precise proposition.\n')
        self.assertNotEqual(p.returncode,0)

    def test_unrelated_docx_fails(self):
        p=self.run_fixture('An entirely different article.','', '# Memo\n\nThe claimed legal conclusion has substantial supporting evidence.\n')
        self.assertNotEqual(p.returncode,0)

    def test_invalid_threshold_fails(self):
        p=self.run_fixture('Memo','', '# Memo', ('--min-markdown-coverage','nan'))
        self.assertNotEqual(p.returncode,0)

if __name__ == '__main__':
    unittest.main()
