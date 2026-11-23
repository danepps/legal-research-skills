#!/usr/bin/env python3
"""Deterministic, stdlib-only DOCX redlines. Python 3.9+. No external programs.

XML edits are byte-range patches, not whole-tree serialization. Untouched XML
and ZIP member payloads retain their original bytes. Staging hard links are
retained deliberately: this tool never unlinks or permanently deletes a file.
"""
import argparse
import dataclasses
import datetime
import errno
import hashlib
import json
import os
from pathlib import Path
import posixpath
import re
import sys
import uuid
import zipfile
from xml.parsers import expat
from xml.sax.saxutils import escape, quoteattr

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
COMMENTS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
COMMENTS_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'


def w(local):
    return W + '}' + local


@dataclasses.dataclass(eq=False)
class Node:
    tag: str
    attrs: dict
    start: int
    opening: int
    parent: object = None
    children: list = dataclasses.field(default_factory=list)
    text: str = ''
    closing: int = 0
    end: int = 0

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def ancestor(self, tag):
        node = self
        while node is not None:
            if node.tag == tag:
                return node
            node = node.parent
        return None


def tag_end(data, start):
    quote = None
    for i in range(start, len(data)):
        ch = data[i]
        if quote:
            if ch == quote:
                quote = None
        elif ch in (34, 39):
            quote = ch
        elif ch == 62:
            return i + 1
    raise ValueError('Unterminated XML tag')


def parse(data):
    # Byte patches are UTF-8. Reject other encodings instead of transcoding the
    # document or silently changing unrelated XML.
    if data.startswith((b'\xff\xfe', b'\xfe\xff')):
        raise ValueError('UTF-16 XML is not supported')
    declaration = re.search(br'<\?xml[^?]*encoding=[\'"]([^\'"]+)', data[:250])
    if declaration and declaration[1].lower() not in (b'utf-8', b'utf8'):
        raise ValueError('Only UTF-8 XML is supported')
    parser = expat.ParserCreate(namespace_separator='}')
    stack, roots = [], []

    def start(name, attrs):
        at = parser.CurrentByteIndex
        node = Node(name, attrs, at, tag_end(data, at), stack[-1] if stack else None)
        (stack[-1].children if stack else roots).append(node)
        stack.append(node)

    def end(name):
        node = stack.pop()
        if data[node.start:node.opening].rstrip().endswith(b'/>'):
            node.closing = node.opening; node.end = node.opening
        else:
            node.closing = parser.CurrentByteIndex
            node.end = tag_end(data, node.closing)

    def chars(text):
        if stack:
            stack[-1].text += text

    def no_doctype(*args):
        raise ValueError('DTD declarations are not supported')

    parser.StartElementHandler = start; parser.EndElementHandler = end
    parser.CharacterDataHandler = chars; parser.StartDoctypeDeclHandler = no_doctype
    parser.Parse(data, True)
    return roots[0]


@dataclasses.dataclass
class Atom:
    char: str
    node: object
    offset: int


def text_view(node, number_map, new_ids=frozenset(), accept=True):
    """The single text-view implementation used for matching and verification.

    Mirrors citeform.runs_spans, including custom marks, without collapsing
    whitespace. New deletions alone become visible in the rejected view.
    """
    atoms = []

    def visit(current, rejected_deletion=False, consumed=frozenset()):
        ident = current.attrs.get(w('id'))
        if current.tag in (w('del'), w('moveFrom')):
            if current.tag == w('del') and ident in new_ids and not accept:
                rejected_deletion = True
            else:
                return
        if current.tag == w('ins') and ident in new_ids and not accept:
            return
        if current.tag == w('r'):
            refs = [c for c in current.children if c.tag == w('footnoteReference')]
            if any(c.attrs.get(w('customMarkFollows'), '').lower() in ('1', 'true', 'on') for c in refs):
                consumed = frozenset(c for c in current.children if c.tag == w('t'))
        text = None
        if current.tag == w('t') and current not in consumed:
            text = current.text
        elif current.tag == w('delText') and rejected_deletion:
            text = current.text
        elif current.tag == w('footnoteReference'):
            custom = current.attrs.get(w('customMarkFollows'), '').lower() in ('1', 'true', 'on')
            text = '[FN#%s]' % number_map.get('*' if custom else current.attrs.get(w('id')), '?')
        elif current.tag in (w('tab'), w('br'), w('cr')):
            text = ' '
        elif current.tag == w('noBreakHyphen'):
            text = '-'
        if text is not None:
            atoms.extend(Atom(ch, current, i) for i, ch in enumerate(text))
        for child in current.children:
            visit(child, rejected_deletion, consumed)

    # The extractor walks descendants, not the paragraph/footnote itself.
    if node.tag == w('footnote'):
        for i, paragraph in enumerate(c for c in node.children if c.tag == w('p')):
            if i:
                atoms.append(Atom(' ', None, 0))
            for child in paragraph.children:
                visit(child)
    else:
        for child in node.children:
            visit(child)
    return atoms


def cleaned(atoms):
    chars, spans = [], []
    for i, atom in enumerate(atoms):
        if atom.char.isspace():
            if not chars:
                continue
            if chars[-1] == ' ':
                spans[-1] = (spans[-1][0], i + 1)
            else:
                chars.append(' '); spans.append((i, i + 1))
        else:
            chars.append(atom.char); spans.append((i, i + 1))
    if chars and chars[-1] == ' ':
        chars.pop(); spans.pop()
    return ''.join(chars), spans


class Document:
    def __init__(self, parts):
        self.parts = parts
        types = parse(parts['[Content_Types].xml'])
        overrides = {n.attrs.get('PartName', '').lstrip('/'): n.attrs.get('ContentType', '') for n in types.children if n.tag == CT + '}Override'}
        defaults = {n.attrs.get('Extension', '').lower(): n.attrs.get('ContentType', '') for n in types.children if n.tag == CT + '}Default'}
        def xml_part(name):
            kind = overrides.get(name, defaults.get(name.rsplit('.', 1)[-1].lower(), '')).lower()
            return name.endswith(('.xml', '.rels', '.vml')) or kind.endswith(('/xml', '+xml', '.vmldrawing'))
        self.roots = {name: parse(data) for name, data in parts.items() if xml_part(name)}
        self.body = self.roots['word/document.xml']
        self.notes = self.roots.get('word/footnotes.xml')
        self.numbers = {}
        self.note_refs = {}  # footnote id -> its first reference mark in the text
        # Match extract_proof.parse_docx's per-paragraph traversal, even for
        # references inside pre-existing deleted subtrees.
        for p in self.body.walk():
            if p.tag == w('p'):
                for ref in p.walk():
                    if ref.tag == w('footnoteReference'):
                        ident = ref.attrs.get(w('id'))
                        if ident not in self.numbers:
                            self.numbers[ident] = len(self.numbers) + 1
                            self.note_refs[ident] = ref
        self.locations, self.units, self.search = {}, {}, []
        body_index = 0
        for name, root in [('word/document.xml', self.body), ('word/footnotes.xml', self.notes)]:
            if root is None:
                continue
            for i, p in enumerate(n for n in root.walk() if n.tag == w('p')):
                self.units[(name, 'p', i)] = p
                if name == 'word/document.xml':
                    if cleaned(text_view(p, self.numbers))[0]:
                        self.locations['¶%d' % body_index] = (name, p)
                        body_index += 1
                    self.search.append((name, p))
        if self.notes:
            for i, fn in enumerate(c for c in self.notes.children if c.tag == w('footnote')):
                self.units[('word/footnotes.xml', 'fn', i)] = fn
                if fn.attrs.get(w('type')) in ('separator', 'continuationSeparator'):
                    continue
                number = self.numbers.get(fn.attrs.get(w('id')))
                if number is not None:
                    self.locations['n.%d' % number] = ('word/footnotes.xml', fn)
                self.search.append(('word/footnotes.xml', fn))


def occurrences(text, find):
    start = 0
    while True:
        at = text.find(find, start)
        if at < 0:
            return
        yield at
        start = at + 1


def patches(data, changes):
    end, output = 0, []
    for a, b, replacement in sorted(changes, key=lambda c: c[0]):
        if a < end:
            raise ValueError('Overlapping XML patches')
        output.extend([data[end:a], replacement]); end = b
    output.append(data[end:])
    return b''.join(output)


def append_children(data, children):
    root = parse(data)
    if root.closing == root.opening:
        opening = data[root.start:root.opening]
        qname = re.match(br'<([^\s/>]+)', opening)[1]
        return patches(data, [(root.start, root.end, opening[:-2] + b'>' + children + b'</' + qname + b'>')])
    return patches(data, [(root.closing, root.closing, children)])


class Writer:
    def __init__(self, document, author, date):
        self.doc = document; self.author = author; self.date = date
        self.prefix = 'dubitante'
        while any(('xmlns:' + self.prefix).encode() in data for data in document.parts.values()):
            self.prefix += 'x'
        ids = {n.attrs[w('id')] for root in document.roots.values() for n in root.walk() if w('id') in n.attrs}
        self.next_id = max([int(i) for i in ids if i.isdigit()] + [0]) + 1
        self.new_ids = set()
        self.events, self.replacements, self.comments = {}, {}, []
        self.requests = {}
        self.claimed = []
        self.note_comments = {}  # footnote id -> index of the one comment that speaks for it
        self.around = {}  # run -> (XML placed before it, XML placed after it); the run itself is not split
        self.fields = {}
        for part, root in document.roots.items():
            stack, intervals = [], []
            for n in root.walk():
                if n.tag == w('fldSimple'):
                    intervals.append((n.start, n.end, 'ZOTERO' in n.attrs.get(w('instr'), '').upper()))
                if n.tag == w('fldChar'):
                    kind = n.attrs.get(w('fldCharType'))
                    if kind == 'begin':
                        stack.append([n.start, False])
                    elif kind == 'end' and stack:
                        a, zotero = stack.pop(); intervals.append((a, n.end, zotero))
                if n.tag == w('instrText') and 'ZOTERO' in n.text.upper():
                    for entry in stack:
                        entry[1] = True
            intervals.extend((a, len(document.parts[part]), z) for a, z in stack)
            self.fields[part] = intervals

    def ident(self, revision=False):
        value = str(self.next_id); self.next_id += 1
        if revision:
            self.new_ids.add(value)
        return value

    def element(self, name, content=b'', attrs=None):
        attrs = attrs or {}
        tag = self.prefix + ':' + name
        attributes = ' xmlns:%s=%s' % (self.prefix, quoteattr(W))
        attributes += ''.join(' %s:%s=%s' % (self.prefix, k, quoteattr(v)) for k, v in attrs.items())
        return ('<' + tag + attributes + '>').encode() + content + ('</' + tag + '>').encode()

    def text(self, text, deleted=False):
        tag = self.prefix + (':delText' if deleted else ':t')
        return ('<%s xmlns:%s=%s xml:space="preserve">%s</%s>' %
                (tag, self.prefix, quoteattr(W), escape(text), tag)).encode('utf-8')

    def event(self, node, offset, xml):
        self.events.setdefault(node, {}).setdefault(offset, []).append(xml)

    def run(self, node, content):
        run = node.ancestor(w('r'))
        if run is None or node.parent is not run:
            raise ValueError('Unsupported text outside a direct Word run')
        data = self.doc.parts[self.part_for(run)]
        props = b''.join(data[c.start:c.end] for c in run.children if c.tag == w('rPr'))
        return data[run.start:run.opening] + props + content + data[run.closing:run.end]

    def part_for(self, node):
        while node.parent:
            node = node.parent
        return next(part for part, root in self.doc.roots.items() if root is node)

    def place(self, edit):
        # The deterministic lint reports an excerpt with an ellipsis at either end
        # ("…concerns the the relationship…"). The words between are verbatim, so
        # anchor a comment on them; an excerpt is never applied as a change.
        find = edit['find'].strip().strip('\u2026').strip()
        excerpt = find != edit['find']
        if not find:
            return dict(id=edit['id'], status='unplaced', reason='No matching span')
        candidates = [self.doc.locations[edit['location']]] if edit['location'] in self.doc.locations else self.doc.search
        matches = []
        for part, node in candidates:
            atoms = text_view(node, self.doc.numbers)
            text, spans = cleaned(atoms)
            for at in occurrences(text, find):
                a, b = spans[at][0], spans[at + len(find) - 1][1]
                matches.append((part, node, atoms, spans, at, a, b))
        if len(matches) != 1:
            return dict(id=edit['id'], status='unplaced', reason='No matching span' if not matches else 'Several matching spans')
        part, unit, atoms, spans, at, a, b = matches[0]
        selected = atoms[a:b]
        first, last = next((c for c in selected if c.node), None), next((c for c in reversed(selected) if c.node), None)
        if not first or not last:
            return dict(id=edit['id'], status='unplaced', reason='No anchorable Word text')
        lo, hi = (first.node.start, first.offset), (last.node.start, last.offset + 1)
        # Several findings often land on one span (a lint hit and a reader's finding, say).
        # Only the first to claim it is anchored; a later one is added to that comment, so
        # nothing is lost and no two edits ever patch the same bytes.
        for p, s, e, earlier in self.claimed:
            if p == part and lo < e and s < hi:
                extra = 'Also at this place: ' + edit['note']
                if edit['kind'] == 'change':
                    extra += '\nProposed replacement: ' + edit['replacement']
                if earlier is None:  # the holder is a change in a footnote that has no reference mark
                    return dict(id=edit['id'], status='unplaced', reason='The footnote has no reference mark in the text to carry a comment.')
                self.comments[earlier][1] += '\n' + extra
                if edit['kind'] == 'comment':
                    return dict(id=edit['id'], status='commented')
                return dict(id=edit['id'], status='commented_instead', reason='Another finding is already anchored at this place.')
        if any(c.node and (c.node.ancestor(w('r')) is None or c.node.parent is not c.node.ancestor(w('r'))) for c in selected):
            return dict(id=edit['id'], status='unplaced', reason='Unsupported nested text structure')
        reason = None
        if edit['kind'] == 'change':
            if excerpt:
                reason = 'The find text is an excerpt, not the exact text to replace.'
            for start, end, zotero in self.fields[part] if reason is None else ():
                if first.node.start < end and start < last.node.end:
                    reason = ('The citation is generated by Zotero and must be changed there.' if zotero else 'The span touches a Word field; change the field at its source.')
                    if zotero:
                        break
            if reason is None and any(c.node and c.node.tag == w('footnoteReference') for c in selected):
                reason = 'The span touches a footnote reference mark.'
            if reason is None and any(n.tag in (w('del'), w('moveFrom')) and first.node.start < n.end and n.start < last.node.end for n in self.doc.roots[part].walk()):
                reason = 'The span crosses an existing tracked deletion or move source.'
            if reason is None and (any(c.node is None or c.node.tag != w('t') for c in selected)
                                   or first.node.ancestor(w('p')) is not last.node.ancestor(w('p'))):
                reason = 'The span crosses a paragraph boundary or non-text Word control.'
        status = 'commented' if edit['kind'] == 'comment' else ('commented_instead' if reason else 'applied')
        note = edit['note']
        if reason:
            note += '\nProposed replacement: ' + edit['replacement'] + '\nNot applied: ' + reason
        if part == 'word/footnotes.xml':
            # Word has no comments inside footnotes and drops any it finds there when it
            # opens the file. A footnote finding's comment hangs on the footnote's reference
            # mark in the text instead: one comment per footnote, naming the words it is about.
            note_node = unit if unit.tag == w('footnote') else unit.ancestor(w('footnote'))
            ident = note_node.attrs.get(w('id')) if note_node is not None else None
            ref = self.doc.note_refs.get(ident)
            if ref is None or ref.parent is None or ref.parent.tag != w('r'):
                if status != 'applied':
                    return dict(id=edit['id'], status='unplaced', reason='The footnote has no reference mark in the text to carry a comment.')
                index = None
            else:
                labelled = 'Footnote %s, at \u201c%s\u201d: %s' % (self.doc.numbers.get(ident, '?'), find, note)
                if ident in self.note_comments:
                    index = self.note_comments[ident]
                    self.comments[index][1] += '\n' + labelled
                else:
                    cid = self.ident(); index = len(self.comments)
                    self.comments.append([cid, labelled]); self.note_comments[ident] = index
                    # Around the whole run, which stays intact: a custom footnote mark keeps
                    # its mark text in the same run as the reference.
                    before, after = self.around.setdefault(ref.parent, ([], []))
                    before.append(self.element('commentRangeStart', attrs={'id': cid}))
                    after.append(self.element('commentRangeEnd', attrs={'id': cid}) +
                                 self.element('r', self.element('commentReference', attrs={'id': cid})))
        else:
            cid = self.ident(); index = len(self.comments)
            self.comments.append([cid, note])
            start_offset = first.offset if first.node.tag == w('t') else 0
            end_offset = last.offset + 1 if last.node.tag == w('t') else 1
            self.event(first.node, start_offset, self.element('commentRangeStart', attrs={'id': cid}))
            self.event(last.node, end_offset, self.element('commentRangeEnd', attrs={'id': cid}) +
                       self.element('r', self.element('commentReference', attrs={'id': cid})))
        self.claimed.append((part, lo, hi, index))
        if status == 'applied':
            self.requests.setdefault(unit, []).append((at, at + len(find), edit['replacement']))
            old, new = find, edit['replacement']
            prefix = 0
            while prefix < min(len(old), len(new)) and old[prefix] == new[prefix]:
                prefix += 1
            suffix = 0
            while suffix < min(len(old), len(new)) - prefix and old[-1-suffix] == new[-1-suffix]:
                suffix += 1
            ca, cb = at + prefix, at + len(old) - suffix
            replacement = new[prefix:len(new)-suffix if suffix else len(new)]
            if ca == cb:
                boundary = spans[ca][0] if ca < len(spans) else b
                anchor = atoms[boundary] if boundary < len(atoms) else atoms[-1]
                offset = anchor.offset if boundary < len(atoms) else anchor.offset + 1
                self.replacements.setdefault(anchor.node, []).append((offset, offset, replacement))
            else:
                changed = atoms[spans[ca][0]:spans[cb-1][1]]
                groups = []
                for atom in changed:
                    if not groups or groups[-1][0] is not atom.node:
                        groups.append([atom.node, atom.offset, atom.offset + 1])
                    else:
                        groups[-1][2] = atom.offset + 1
                # Retain each deleted run's properties; new text uses the same
                # character slots, with excess characters in the last run style.
                for i, (node, s, e) in enumerate(groups):
                    count = len(replacement) if i == len(groups)-1 else min(e-s, len(replacement))
                    inserted, replacement = replacement[:count], replacement[count:]
                    self.replacements.setdefault(node, []).append((s, e, inserted))
        result = dict(id=edit['id'], status=status)
        if reason:
            result['reason'] = reason
        return result

    def expected(self, atoms):
        output = []
        for i, atom in enumerate(atoms):
            changes = self.replacements.get(atom.node, [])
            for a, b, replacement in changes:
                if atom.offset == a:
                    output.append(replacement)
            if not any(a <= atom.offset < b for a, b, _ in changes):
                output.append(atom.char)
            if i + 1 == len(atoms) or atoms[i+1].node is not atom.node:
                for a, b, replacement in changes:
                    if a == b == atom.offset + 1:
                        output.append(replacement)
        return ''.join(output)

    def edited_parts(self):
        result = dict(self.doc.parts)
        runs = {node.ancestor(w('r')) for node in set(self.events) | set(self.replacements)} | set(self.around)
        edits = {}
        for run in sorted(runs, key=lambda n: (self.part_for(n), n.start)):
            part = self.part_for(run); data = self.doc.parts[part]
            fragments = []
            split = any(node in self.events or node in self.replacements for node in run.children)
            if not split:
                fragments.append(data[run.start:run.end])
            for node in run.children if split else ():
                if node.tag == w('rPr'):
                    continue
                events = self.events.get(node, {})
                changes = {a: (b, text) for a, b, text in self.replacements.get(node, [])}
                if node.tag == w('t'):
                    cuts = sorted(set([0, len(node.text)] + list(events) + list(changes) + [b for b, _ in changes.values()]))
                    skip_until = -1
                    for i, at in enumerate(cuts):
                        fragments.extend(events.get(at, []))
                        if at in changes:
                            end, inserted = changes[at]
                            attrs = {'id': self.ident(True), 'author': self.author, 'date': self.date}
                            if end > at:
                                fragments.append(self.element('del', self.run(node, self.text(node.text[at:end], True)), attrs))
                            if inserted:
                                attrs = {'id': self.ident(True), 'author': self.author, 'date': self.date}
                                fragments.append(self.element('ins', self.run(node, self.text(inserted)), attrs))
                            skip_until = end
                        if i + 1 < len(cuts) and at >= skip_until:
                            fragments.append(self.run(node, self.text(node.text[at:cuts[i+1]])))
                else:
                    fragments.extend(events.get(0, []))
                    fragments.append(self.run(node, data[node.start:node.end]))
                    fragments.extend(events.get(1, []))
            before, after = self.around.get(run, ([], []))
            edits.setdefault(part, []).append((run.start, run.end, b''.join(before) + b''.join(fragments) + b''.join(after)))
        for part, changes in edits.items():
            result[part] = patches(result[part], changes)
        if self.comments:
            relname = 'word/_rels/document.xml.rels'
            relationships = result.get(relname, ('<Relationships xmlns="%s"/>' % REL).encode())
            root = parse(relationships)
            existing = [n for n in root.children if n.attrs.get('Type') == COMMENTS_REL]
            if len(existing) > 1:
                raise ValueError('Multiple comments relationships')
            if existing:
                if existing[0].attrs.get('TargetMode') == 'External':
                    raise ValueError('External comments part')
                target = existing[0].attrs['Target']
                comment_part = posixpath.normpath('word/' + target) if not target.startswith('/') else target[1:]
                if comment_part not in result:
                    raise ValueError('Missing existing comments part')
            else:
                comment_part = 'word/comments.xml'
                used = {n.attrs.get('Id') for n in root.children}
                rid = 'dubitanteComments'
                while rid in used:
                    rid += 'x'
                entry = ('<Relationship xmlns=%s Id=%s Type=%s Target="comments.xml"/>' %
                         (quoteattr(REL), quoteattr(rid), quoteattr(COMMENTS_REL))).encode()
                result[relname] = append_children(relationships, entry)
            comments = result.get(comment_part, ('<w:comments xmlns:w="%s"/>' % W).encode())
            # One Word paragraph per line of the note: a line break inside w:t shows as a space.
            built = b''.join(self.element('comment', b''.join(self.element('p', self.element('r', self.text(line)))
                                                              for line in note.split('\n') if line.strip()),
                                          {'id': cid, 'author': self.author, 'date': self.date})
                             for cid, note in self.comments)
            result[comment_part] = append_children(comments, built)
            types = result['[Content_Types].xml']; root = parse(types)
            matching = [n for n in root.children if n.attrs.get('PartName') == '/' + comment_part]
            if matching and any(n.attrs.get('ContentType') != COMMENTS_CT for n in matching):
                raise ValueError('Incorrect existing comments content type')
            if not matching:
                entry = ('<Override xmlns=%s PartName=%s ContentType=%s/>' %
                         (quoteattr(CT), quoteattr('/' + comment_part), quoteattr(COMMENTS_CT))).encode()
                result['[Content_Types].xml'] = append_children(types, entry)
        return result


def verify(staged, original, writer):
    with zipfile.ZipFile(staged) as archive:
        parts = {i.filename: archive.read(i) for i in archive.infolist()}
    document = Document(parts)  # parses every .xml and .rels part
    if document.units.keys() != original.units.keys() or document.numbers != original.numbers:
        raise ValueError('Verification failed: paragraph/footnote structure changed')
    for key, node in original.units.items():
        before = text_view(node, original.numbers)
        after = document.units[key]
        rejected = ''.join(a.char for a in text_view(after, document.numbers, writer.new_ids, False))
        accepted = ''.join(a.char for a in text_view(after, document.numbers, writer.new_ids, True))
        if rejected != ''.join(a.char for a in before):
            raise ValueError('Verification failed: rejected view differs at %r' % (key,))
        if accepted != writer.expected(before):
            raise ValueError('Verification failed: accepted view differs at %r' % (key,))
        # Independently check the requested full substitutions, rather than
        # trusting the run-splitting/common-prefix transformation plan alone.
        if node in writer.requests:
            expected = cleaned(before)[0]
            for a, b, replacement in sorted(writer.requests[node], reverse=True):
                expected = expected[:a] + replacement + expected[b:]
            if re.sub(r'\s+', ' ', expected).strip() != cleaned(text_view(after, document.numbers, writer.new_ids, True))[0]:
                raise ValueError('Verification failed: requested substitution differs at %r' % (key,))


def validate_edits(edits):
    if not isinstance(edits, list):
        raise ValueError('edits must be a list')
    ids = set()
    for edit in edits:
        if not isinstance(edit, dict) or any(not isinstance(edit.get(k), str) for k in ('id', 'location', 'find', 'kind', 'note')):
            raise ValueError('Invalid edit fields')
        if not edit['id'] or edit['id'] in ids or not edit['find'] or edit['kind'] not in ('change', 'comment'):
            raise ValueError('Invalid or duplicate edit id, empty find, or invalid kind')
        if edit['kind'] == 'change' and not isinstance(edit.get('replacement'), str):
            raise ValueError('A change requires a string replacement')
        ids.add(edit['id'])


def edits_from_findings(findings):
    # Accept the proofread workflow's whole output file as well as the bare array, so
    # the skill can point --findings at the file its completion notification names.
    if isinstance(findings, dict):
        result = findings.get('result')
        holder = result if isinstance(result, dict) else findings
        if 'findings' not in holder:
            raise ValueError('No findings in the workflow output (the proofread workflow returns them from plugin 1.6.8 on)')
        findings = holder['findings']
    if not isinstance(findings, list):
        raise ValueError('Malformed findings: expected an array')
    edits = []
    fields = ('location', 'find', 'problem', 'fix', 'severity', 'category')
    for index, finding in enumerate(findings, 1):
        if (not isinstance(finding, dict) or any(not isinstance(finding.get(k), str) for k in fields)
                or not finding['find'] or finding['severity'] not in ('error', 'likely', 'style', 'query')
                or ('replacement' in finding and not isinstance(finding['replacement'], str))):
            raise ValueError('Malformed findings: invalid fields in finding %d' % index)
        replacement = finding.get('replacement')
        change = finding['severity'] == 'error' and bool(replacement) and replacement != finding['find']
        edit = dict(id=str(index), location=finding['location'], find=finding['find'],
                    kind='change' if change else 'comment', note=finding['problem'] + '\n' + finding['fix'])
        if change:
            edit['replacement'] = replacement
        edits.append(edit)
    return edits


def generate(draft, edits, output, result, author, date, fault_hook=None, staging_dir=None):
    """fault_hook is in-process tests only, never a command-line option."""
    output, result = Path(output), Path(result)
    if os.path.lexists(output):
        raise FileExistsError('Output already exists; left unchanged')
    if result.resolve() in (Path(draft).resolve(), output.resolve()):
        raise ValueError('Draft, result, and output must be distinct')
    # Reserve the result path exclusively. It also guarantees diagnostics can be
    # saved before committing the output hard link as the final filesystem step.
    with result.open('x', encoding='utf-8') as result_file:
        try:
            validate_edits(edits)
            stamp = datetime.datetime.fromisoformat(date.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Date must include a time zone')
            if not author:
                raise ValueError('Author is required')
            totals = dict(applied=0, commented=0, commented_instead=0, unplaced=0)
            if not edits:
                answer = dict(status='no_edits', reason='No confirmed findings to redline', edits=[], totals=totals)
                json.dump(answer, result_file, ensure_ascii=False, indent=2)
                return answer
            with zipfile.ZipFile(draft, 'r') as archive:
                infos = archive.infolist()
                if len({i.filename for i in infos}) != len(infos):
                    raise ValueError('Duplicate ZIP members')
                parts = {i.filename: archive.read(i) for i in infos}
                archive_comment = archive.comment
            document = Document(parts); writer = Writer(document, author, date)
            # Changes claim their spans first, so a comment on the same words never
            # displaces a correction; results are reported in the order given.
            placed = {}
            for kind in ('change', 'comment'):
                for edit in edits:
                    if edit['kind'] == kind:
                        placed[edit['id']] = writer.place(edit)
            outcomes = [placed[edit['id']] for edit in edits]
            changed = writer.edited_parts()
            if fault_hook:
                changed = fault_hook(changed)
            staging = Path(staging_dir) if staging_dir is not None else output.parent
            if not staging.is_dir():
                raise ValueError('Staging directory must already exist')
            stage = staging / ('.' + output.name + '.' + uuid.uuid4().hex + '.staging')
            with stage.open('xb') as handle:
                with zipfile.ZipFile(handle, 'w') as archive:
                    archive.comment = archive_comment
                    for info in infos:
                        archive.writestr(info, changed.pop(info.filename))
                    for name in sorted(changed):
                        info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                        info.compress_type = zipfile.ZIP_DEFLATED
                        archive.writestr(info, changed[name])
                handle.flush(); os.fsync(handle.fileno())
            verify(stage, document, writer)
            for entry in outcomes:
                totals[entry['status']] += 1
            digest = hashlib.sha256(stage.read_bytes()).hexdigest()
            answer = dict(status='written', edits=outcomes, totals=totals, sha256=digest)
            json.dump(answer, result_file, ensure_ascii=False, indent=2)
            result_file.flush(); os.fsync(result_file.fileno())
            try:
                os.link(stage, output)  # Atomic exclusive create; retain staging link.
            except OSError as error:
                if error.errno == errno.EXDEV:
                    raise ValueError('Staging directory and output must be on the same volume') from error
                raise
            return answer
        except Exception as error:
            result_file.seek(0); result_file.truncate()
            json.dump(dict(status='failed', reason=str(error)), result_file, ensure_ascii=False, indent=2)
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('draft', 'output', 'result', 'author', 'date'):
        parser.add_argument('--' + name, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--edits')
    mode.add_argument('--findings')
    parser.add_argument('--staging-dir')
    args = parser.parse_args()
    try:
        with open(args.edits or args.findings, encoding='utf-8') as source:
            values = json.load(source)
        edits = edits_from_findings(values) if args.findings else values
        generate(args.draft, edits, args.output, args.result, args.author, args.date, staging_dir=args.staging_dir)
        return 0
    except Exception as error:
        print('Redline not made: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
