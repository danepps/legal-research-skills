"""Referenced Word header/footer prose; no pagination or external relationships.

This module is bundled independently with each proofreader. Readers supply their
own text/formatting view. Nothing here edits the source XML.
"""
import copy
import posixpath
from urllib.parse import unquote, urlsplit

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
R = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
BREAK = '\ufdd0'  # internal boundary, never emitted as draft text
FURNITURE = {'PAGE', 'PAGEREF', 'NUMPAGES', 'SECTIONPAGES', 'SECTION', 'STYLEREF', 'DATE', 'TIME', 'PRINTDATE', 'SAVEDATE', 'CREATEDATE'}


def visible_nodes(root):
    if root.tag in {W + 'del', W + 'moveFrom', W + 'sectPrChange'}:
        return
    yield root
    for child in root:
        yield from visible_nodes(child)


def referenced_parts(read_xml):
    """Resolve section references, including Link to Previous inheritance.

    Explicit references are reviewed even if first/even display is currently
    disabled: those settings and actual page occupancy can change in Word.
    """
    document = read_xml('word/document.xml')
    relationships = read_xml('word/_rels/document.xml.rels')
    rels = {n.get('Id'): n for n in relationships} if relationships is not None else {}
    inherited = {}
    uses = {}
    for section, sect in enumerate((n for n in visible_nodes(document) if n.tag == W + 'sectPr'), 1):
        for kind in ('header', 'footer'):
            for ref in sect.findall(W + kind + 'Reference'):
                typ = ref.get(W + 'type', 'default')
                if typ not in {'default', 'first', 'even'}:
                    continue
                rel = rels.get(ref.get(R + 'id'))
                target = None
                if (rel is not None and rel.get('TargetMode') != 'External'
                        and rel.get('Type') == R[1:-1] + '/' + kind):
                    uri = urlsplit(rel.get('Target', ''))
                    path = unquote(uri.path)
                    if path and not (uri.scheme or uri.netloc or uri.query or uri.fragment or '\\' in path):
                        target = posixpath.normpath(path.lstrip('/') if path.startswith('/') else 'word/' + path)
                        if target.startswith('../') or target in {'.', '..'}:
                            target = None
                # An invalid explicit reference must not inherit the old part.
                inherited[(kind, typ)] = target
        for (kind, typ), target in inherited.items():
            if target:
                uses.setdefault((kind, target), []).append({'section': section, 'type': typ})
    return uses


def prose_copy(root):
    """Suppress generated furniture, preserving boundaries on either side.

    Field instructions are never text. Other field results (e.g. REF and Zotero)
    retain the reader's normal treatment. Complex/nested fields may span runs or
    paragraphs. Excluded results become boundaries, so a find never jumps over
    a displayed page number to join unrelated words.
    """
    root = copy.deepcopy(root)
    stack, suppressed = [], set()
    for node in visible_nodes(root):
        if node.tag == W + 'fldSimple':
            command = node.get(W + 'instr', '').strip().split()
            if command and command[0].upper() in FURNITURE:
                suppressed.update(node.iter())
        for frame in stack:
            frame['nodes'].append(node)
        if node.tag == W + 'fldChar':
            typ = node.get(W + 'fldCharType')
            if typ == 'begin':
                stack.append({'code': '', 'nodes': [node]})
            elif typ == 'end' and stack:
                frame = stack.pop()
                command = frame['code'].strip().split()
                if command and command[0].upper() in FURNITURE:
                    suppressed.update(frame['nodes'])
        elif node.tag == W + 'instrText' and stack:
            stack[-1]['code'] += node.text or ''
    for frame in stack:  # incomplete furniture fields still are not prose
        command = frame['code'].strip().split()
        if command and command[0].upper() in FURNITURE:
            suppressed.update(frame['nodes'])
    for node in suppressed:
        if node.tag in {W + 't', W + 'tab', W + 'br', W + 'cr', W + 'noBreakHyphen'}:
            node.tag = W + 't'
            node.text = BREAK
    return root


def location_label(location):
    names = {'first': 'First-page', 'even': 'Even-page', 'default': 'Default'}
    return '; '.join('%s %s, section %d, paragraph %d, segment %d' % (
        names[o['type']], location['where'], o['section'], o['para'], o['segment'])
        for o in location['occurrences'])


def collect(read_xml, read_spans, clean_spans):
    records, by_text = [], {}
    for (kind, part), uses in referenced_parts(read_xml).items():
        root = read_xml(part)
        if root is None:
            continue
        filtered = prose_copy(root)
        visible = set(visible_nodes(filtered))
        # Physical paragraph numbers are stable even for empty/deleted paragraphs.
        for para, paragraph in enumerate(filtered.iter(W + 'p'), 1):
            if paragraph not in visible:
                continue
            segments = [[]]
            for text, props in read_spans(paragraph):
                pieces = text.split(BREAK)
                for i, piece in enumerate(pieces):
                    if i:
                        segments.append([])
                    segments[-1].append((piece, props))
            segment = 0
            for spans in segments:
                text, formatting = clean_spans(spans)
                if not text:
                    continue
                segment += 1
                key = (kind, text)
                if key not in by_text:
                    record = {'text': text, 'spans': formatting, 'words': len(text.split()),
                              'location': {'where': kind, 'occurrences': []}}
                    by_text[key] = record
                    records.append(record)
                record = by_text[key]
                for use in uses:
                    occurrence = dict(part=part, para=para, segment=segment, **use)
                    if occurrence not in record['location']['occurrences']:
                        record['location']['occurrences'].append(occurrence)
                # Equal words with different typeface must not claim one shared format.
                if record['spans'] != formatting:
                    record['spans'] = []
                    record['formatting_ambiguous'] = True
    for record in records:
        record['location']['occurrences'].sort(key=lambda o: (o['section'], o['type'], o['part'], o['para'], o['segment']))
        record['location_label'] = location_label(record['location'])
    return records
