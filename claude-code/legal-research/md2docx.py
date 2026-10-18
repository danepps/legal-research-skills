#!/usr/bin/env python3
"""Minimal, dependency-free Markdown -> .docx converter (stdlib only).
Handles: #/##/### headings, **bold**, *italic*, `code`, bullet & numbered lists,
blockquotes, horizontal rules, and [^n]-style footnote markers/defs (rendered inline).
Usage: python3 md2docx.py input.md output.docx ["Document Title"]
"""
import sys, re, zipfile, html

def esc(s):
    return html.escape(s, quote=False)

def runs(text):
    """Convert inline markdown to a list of w:r run XML strings."""
    # tokenize on **bold**, *italic*/_italic_, `code`
    pattern = re.compile(r'(\*\*.+?\*\*|\*[^*]+?\*|_[^_]+?_|`[^`]+?`)')
    out = []
    for part in pattern.split(text):
        if not part:
            continue
        b = i = c = False
        t = part
        if part.startswith('**') and part.endswith('**') and len(part) > 4:
            b, t = True, part[2:-2]
        elif part.startswith('`') and part.endswith('`') and len(part) > 2:
            c, t = True, part[1:-1]
        elif part.startswith('*') and part.endswith('*') and len(part) > 2:
            i, t = True, part[1:-1]
        elif part.startswith('_') and part.endswith('_') and len(part) > 2:
            i, t = True, part[1:-1]
        props = []
        if b: props.append('<w:b/>')
        if i: props.append('<w:i/>')
        if c: props.append('<w:rFonts w:ascii="Consolas" w:hAnsi="Consolas"/>')
        rpr = f'<w:rPr>{"".join(props)}</w:rPr>' if props else ''
        out.append(f'<w:r>{rpr}<w:t xml:space="preserve">{esc(t)}</w:t></w:r>')
    return ''.join(out) or '<w:r><w:t/></w:r>'

def para(text, style=None, ind=False):
    ppr = '<w:pPr>'
    if style:
        ppr += f'<w:pStyle w:val="{style}"/>'
    if ind:
        ppr += '<w:ind w:left="360" w:hanging="360"/>'
    ppr += '</w:pPr>'
    return f'<w:p>{ppr}{runs(text)}</w:p>'

def convert(md):
    body = []
    lines = md.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        s = line.strip()
        if not s:
            i += 1
            continue
        if s.startswith('### '):
            body.append(para(s[4:], 'Heading3'))
        elif s.startswith('## '):
            body.append(para(s[3:], 'Heading2'))
        elif s.startswith('# '):
            body.append(para(s[2:], 'Heading1'))
        elif re.match(r'^(\*\*\*|---|___)\s*$', s):
            body.append('<w:p><w:pPr><w:pBdr><w:bottom w:val="single" w:sz="6" w:space="1" w:color="999999"/></w:pBdr></w:pPr></w:p>')
        elif s.startswith('> '):
            body.append(para(s[2:], 'Quote'))
        elif re.match(r'^[-*+]\s+', s):
            body.append(para(re.sub(r'^[-*+]\s+', '', s), 'ListBullet', ind=True))
        elif re.match(r'^\d+[.)]\s+', s):
            body.append(para('• ' + re.sub(r'^\d+[.)]\s+', '', s), 'ListNumber', ind=True))
        else:
            body.append(para(s))
        i += 1
    return '\n'.join(body)

def build(md, title):
    parts = []
    if title:
        parts.append(para(title, 'Title'))
    parts.append(convert(md))
    body = '\n'.join(parts)
    document = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:body>{body}<w:sectPr><w:pgSz w:w="12240" w:h="15840"/><w:pgMar w:top="1440" w:bottom="1440" w:left="1440" w:right="1440"/></w:sectPr></w:body></w:document>'''
    return document

STYLES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/><w:sz w:val="22"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="160" w:line="276" w:lineRule="auto"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:pPr><w:spacing w:after="240"/><w:jc w:val="center"/></w:pPr><w:rPr><w:b/><w:sz w:val="40"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:pPr><w:keepNext/><w:spacing w:before="320" w:after="120"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:b/><w:sz w:val="30"/><w:color w:val="1F3864"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="120"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/><w:color w:val="2E5496"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:pPr><w:keepNext/><w:spacing w:before="200" w:after="80"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:b/><w:i/><w:sz w:val="23"/><w:color w:val="2E5496"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Quote"><w:name w:val="Quote"/><w:pPr><w:ind w:left="720" w:right="720"/><w:spacing w:after="160"/></w:pPr><w:rPr><w:i/><w:color w:val="404040"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="ListBullet"><w:name w:val="List Bullet"/><w:pPr><w:spacing w:after="80"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="ListNumber"><w:name w:val="List Number"/><w:pPr><w:spacing w:after="80"/></w:pPr></w:style>
</w:styles>'''

CONTENT_TYPES = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>'''

RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>'''

DOC_RELS = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>'''

def main():
    inp, outp = sys.argv[1], sys.argv[2]
    title = sys.argv[3] if len(sys.argv) > 3 else ''
    with open(inp, encoding='utf-8') as f:
        md = f.read()
    document = build(md, title)
    with zipfile.ZipFile(outp, 'w', zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml', CONTENT_TYPES)
        z.writestr('_rels/.rels', RELS)
        z.writestr('word/document.xml', document)
        z.writestr('word/styles.xml', STYLES)
        z.writestr('word/_rels/document.xml.rels', DOC_RELS)
    print(f'Wrote {outp}')

if __name__ == '__main__':
    main()
