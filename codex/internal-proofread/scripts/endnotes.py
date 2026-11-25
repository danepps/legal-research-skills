"""Endnote identity and numbering, bundled independently by each proofreader.

Only referenced, visible notes are indexed. Display labels are separate from raw
OOXML IDs and reference order; repeated labels never silently overwrite a note.
"""
import copy
import re
from collections import Counter

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
NOTE_REF = re.compile(r'\b(supra|infra)\s+notes?\s+(\d+|[ivxlcdm]+)\b(?:\s*[–—-]\s*(\d+|[ivxlcdm]+)\b)?', re.I)
MARKER = re.compile(r'\[EN#[^\]\r\n]+\]')


def visible(root):
    if root.tag in {W + 'del', W + 'moveFrom', W + 'sectPrChange'}:
        return
    yield root
    for child in root:
        yield from visible(child)


def roman(number):
    result = ''
    for value, glyph in ((1000, 'M'), (900, 'CM'), (500, 'D'), (400, 'CD'),
                         (100, 'C'), (90, 'XC'), (50, 'L'), (40, 'XL'),
                         (10, 'X'), (9, 'IX'), (5, 'V'), (4, 'IV'), (1, 'I')):
        count, number = divmod(number, value)
        result += glyph * count
    return result


def formatted(number, fmt):
    if fmt == 'decimal':
        return str(number)
    if fmt in {'lowerRoman', 'upperRoman'}:
        value = roman(number)
        return value.lower() if fmt == 'lowerRoman' else value
    value = ''
    while number:
        number, digit = divmod(number - 1, 26)
        value = chr(65 + digit) + value
    return value.lower() if fmt == 'lowerLetter' else value


def properties(root):
    if root is None:
        return {}
    prop = root.find(W + 'endnotePr')
    return {name: node.get(W + 'val') for name in ('numFmt', 'numStart', 'numRestart')
            if prop is not None and (node := prop.find(W + name)) is not None}


def index(read_xml):
    document = read_xml('word/document.xml')
    notes = read_xml('word/endnotes.xml')
    if document is None or notes is None:
        return [], []
    by_id = {n.get(W + 'id'): n for n in notes.findall(W + 'endnote')
             if n.get(W + 'type') not in {'separator', 'continuationSeparator', 'continuationNotice'}}
    body = document.find(W + 'body')
    if body is None:
        return [], []
    parents = {child: parent for parent in document.iter() for child in parent}
    sections, refs = [], []
    for child in body:
        refs += [n for n in visible(child) if n.tag == W + 'endnoteReference']
        sect = child if child.tag == W + 'sectPr' else child.find(W + 'pPr/' + W + 'sectPr')
        if sect is not None:
            sections.append((refs, properties(sect)))
            refs = []
    if refs:
        sections.append((refs, {}))
    defaults = properties(read_xml('word/settings.xml'))
    records, limitations, seen = [], [], set()
    counter = None
    for section, (refs, overrides) in enumerate(sections, 1):
        props = dict(defaults, **overrides)
        fmt = props.get('numFmt', 'lowerRoman')
        if fmt not in {'decimal', 'lowerRoman', 'upperRoman', 'lowerLetter', 'upperLetter'}:
            limitations.append('Endnote number format %r is unsupported; lowerRoman default used.' % fmt)
            fmt = 'lowerRoman'
        start = props.get('numStart', '1')
        if not str(start).isdigit() or not 1 <= int(start) <= 32767:
            limitations.append('Endnote number start is indeterminate; default 1 used.')
            start = '1'
        restart = props.get('numRestart', 'continuous')
        if restart not in {'continuous', 'eachSect'}:
            limitations.append('Endnote restart %r cannot be determined without pagination; continuous numbering used.' % restart)
            restart = 'continuous'
        if counter is None or restart == 'eachSect':
            counter = int(start)
        for ref in refs:
            ident = ref.get(W + 'id')
            if ident in seen:
                continue
            seen.add(ident)
            # Separators and absent note bodies never become proofreading units.
            if ident not in by_id:
                limitations.append('Endnote reference %s has no ordinary note body; omitted.' % ident)
                continue
            custom = ref.get(W + 'customMarkFollows', '').lower() in {'1', 'true', 'on'}
            value = None if custom else counter
            if custom:
                parent = parents.get(ref)
                label = ''.join(n.text or '' for n in parent.findall(W + 't')) if parent is not None else ''
                if not label.strip() or re.search(r'[\[\]\r\n@]', label):
                    limitations.append('Endnote custom mark for ID %s cannot be represented; a placeholder label is used.' % ident)
                    label = 'custom-%d' % (len(records) + 1)
            else:
                label = formatted(counter, fmt)
                counter += 1
            records.append(dict(note_id=ident, number=label, number_value=value,
                                number_format=fmt, custom_mark=custom, order=len(records) + 1,
                                section=section))
    repeated = Counter(r['number'] for r in records)
    if any(count > 1 for count in repeated.values()):
        limitations.append('Repeated endnote labels are ambiguous for note cross-references; those references are suppressed. Location suffix @N identifies reference order, not a displayed number.')
    for row in records:
        label = row['number'] + ('@%d' % row['order'] if repeated[row['number']] > 1 else '')
        row['location_label'] = 'en.' + label
        row['location'] = dict(where='endnote', note=row['number'], note_id=row['note_id'],
                               section=row['section'], order=row['order'], location_label=row['location_label'])
    return records, list(dict.fromkeys(limitations))


def reference_copy(paragraph, numbers):
    """Give a tree's existing reader literal EN markers without changing it globally."""
    if paragraph.find('.//' + W + 'endnoteReference') is None:
        return paragraph
    paragraph = copy.deepcopy(paragraph)
    for run in paragraph.iter(W + 'r'):
        refs = [n for n in run if n.tag == W + 'endnoteReference']
        if any(n.get(W + 'customMarkFollows', '').lower() in {'1', 'true', 'on'} for n in refs):
            for text in list(run.findall(W + 't')):
                run.remove(text)
        for ref in refs:
            label = numbers.get(ref.get(W + 'id'))
            ref.tag = W + 't'
            ref.attrib.clear()
            ref.text = '[EN#%s]' % label if label is not None else ''
    return paragraph


def targets(records):
    """Display-label map, with decimal aliases for roman/letter automatic numbers."""
    result = {}
    for row in records:
        labels = {row['number'].casefold()}
        if row.get('number_value') is not None:
            labels.add(str(row['number_value']))
        for label in labels:
            result.setdefault(label, []).append(row)
    return result


def references(text, records):
    """Yield resolvable or missing references; suppress ambiguous duplicate labels."""
    lookup = targets(records)
    for match in NOTE_REF.finditer(text):
        labels = [match[2]] + ([match[3]] if match[3] else [])
        candidates = [lookup.get(label.casefold(), []) for label in labels]
        if any(len(rows) > 1 for rows in candidates):
            continue
        yield match, [rows[0] if rows else None for rows in candidates]
