#!/usr/bin/env python3
"""Deterministic, stdlib-only DOCX redlines. Python 3.9+. No external programs.

XML edits are byte-range patches, not whole-tree serialization. Untouched XML
and ZIP member payloads retain their original bytes. Staging hard links are
retained deliberately: this tool never unlinks or permanently deletes a file.
"""
import argparse
import copy
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
from xml.etree import ElementTree as ET

# The host invokes this script with -I; import only its bundled sibling helper,
# not the working directory or an installed skill tree.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from header_footer import collect as collect_headers_footers, referenced_parts
from endnotes import index as endnote_index

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
COMMENTS_REL = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships/comments'
COMMENTS_CT = 'application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml'
SYMBOL_GAP = re.compile(r'([§¶]+)(\s+)(?=\S)')
NONBREAKING = frozenset('\u00a0\u202f\u2007')
SYMBOL_PARTS = ('word/document.xml', 'word/footnotes.xml', 'word/endnotes.xml')


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
            refs = [c for c in current.children if c.tag in (w('footnoteReference'), w('endnoteReference'))]
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
        elif current.tag == w('endnoteReference'):
            label = number_map.get('EN:' + current.attrs.get(w('id'), ''))
            text = '[EN#%s]' % label if label is not None else ''
        elif current.tag in (w('tab'), w('br'), w('cr')):
            text = ' '
        elif current.tag == w('noBreakHyphen'):
            text = '-'
        if text is not None:
            atoms.extend(Atom(ch, current, i) for i, ch in enumerate(text))
        for child in current.children:
            visit(child, rejected_deletion, consumed)

    # The extractor walks descendants, not the paragraph/footnote itself.
    if node.tag in (w('footnote'), w('endnote')):
        paragraphs = [c for c in node.children if c.tag == w('p')]
        if node.tag == w('endnote'):
            paragraphs = [c for c in node.walk() if c.tag == w('p')
                          and not any(c.ancestor(w(tag)) for tag in ('del', 'moveFrom'))]
        for i, paragraph in enumerate(paragraphs):
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
        self.endnotes = self.roots.get('word/endnotes.xml')
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
        def read_xml(name):
            return ET.fromstring(parts[name]) if name in parts else None
        self.endnote_records, _ = endnote_index(read_xml)
        self.endnote_by_id = {r['note_id']: r for r in self.endnote_records}
        self.numbers.update({'EN:' + r['note_id']: r['number'] for r in self.endnote_records})
        for ref in self.body.walk():
            if (ref.tag == w('endnoteReference') and ref.attrs.get(w('id')) in self.endnote_by_id
                    and not any(ref.ancestor(w(tag)) for tag in ('del', 'moveFrom'))):
                self.note_refs.setdefault('EN:' + ref.attrs[w('id')], ref)
        self.locations, self.units, self.search = {}, {}, []
        body_index = 0
        for name, root in [('word/document.xml', self.body), ('word/footnotes.xml', self.notes), ('word/endnotes.xml', self.endnotes)]:
            if root is None:
                continue
            for i, p in enumerate(n for n in root.walk() if n.tag == w('p')):
                self.units[(name, 'p', i)] = p
                if name == 'word/document.xml':
                    if (not self.endnote_records or not any(p.ancestor(w(tag)) for tag in ('del', 'moveFrom'))) and cleaned(text_view(p, self.numbers))[0]:
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
        if self.endnotes:
            for i, node in enumerate(c for c in self.endnotes.children if c.tag == w('endnote')):
                self.units[('word/endnotes.xml', 'en', i)] = node
                record = self.endnote_by_id.get(node.attrs.get(w('id')))
                if record is not None:
                    self.locations[record['location_label']] = ('word/endnotes.xml', node)
                    self.search.append(('word/endnotes.xml', node))
        def read_spans(paragraph):
            node = parse(ET.tostring(paragraph, encoding='utf-8'))
            return [(''.join(a.char for a in text_view(node, self.numbers)), frozenset())]
        def clean_spans(spans):
            return re.sub(r'\s+', ' ', ''.join(t for t, _ in spans)).strip(), []
        self.story_parts = {part for _, part in referenced_parts(read_xml)} & set(self.roots)
        self.header_locations = {}
        self.story_paragraphs = {}
        for name in sorted(self.story_parts):
            for i, node in enumerate(n for n in self.roots[name].walk() if n.tag == w('p')):
                self.units[(name, 'p', i)] = node
                self.story_paragraphs[(name, i + 1)] = node
        for record in collect_headers_footers(read_xml, read_spans, clean_spans):
            targets = []
            for occurrence in record['location']['occurrences']:
                part, para = occurrence['part'], occurrence['para']
                target = (part, self.story_paragraphs[(part, para)])
                if target not in targets:
                    targets.append(target)
            self.header_locations[record['location_label']] = targets


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


ZOTERO_NOTICE = ("Also changed in the Zotero citation's stored data. Rejecting this change in Word "
                 "does not undo it: a Zotero refresh will show the new text.")
LIBRARY_REASON = ('This text comes from the Zotero library item or the citation style '
                  'and must be changed in Zotero.')


def trimmed_change(old, new):
    a = 0
    while a < min(len(old), len(new)) and old[a] == new[a]:
        a += 1
    tail = 0
    while tail < min(len(old), len(new)) - a and old[-1-tail] == new[-1-tail]:
        tail += 1
    return a, len(old) - tail, new[a:len(new)-tail if tail else len(new)]


def json_source(code):
    """Parse one field object and locate string values without serializing it."""
    def pairs(entries):
        result = {}
        for key, value in entries:
            if key in result:
                raise ValueError('Duplicate JSON key')
            result[key] = value
        return result

    def invalid_constant(value):
        raise ValueError('Nonstandard JSON constant: ' + value)

    decoder = json.JSONDecoder(object_pairs_hook=pairs, parse_constant=invalid_constant)
    header = re.match(r'\s*ADDIN\s+ZOTERO_(ITEM\s+CSL_CITATION|BIBL)\s+', code)
    if not header:
        raise ValueError('Unrecognized Zotero field instruction')
    start = header.end()
    value, end = decoder.raw_decode(code, start)
    trailer = code[end:].strip()
    if not isinstance(value, dict) or trailer not in ('', 'CSL_BIBLIOGRAPHY') or ('ITEM' in header[1] and trailer):
        raise ValueError('Expected one Zotero JSON object')
    literals = {}

    def skip(at):
        while code[at].isspace():
            at += 1
        return at

    def walk(at, path):
        at = skip(at)
        if code[at] == '{':
            at = skip(at + 1)
            while code[at] != '}':
                key, at = decoder.raw_decode(code, at)
                at = walk(skip(at) + 1, path + (key,))  # colon
                at = skip(at)
                if code[at] != ',':
                    break
                at = skip(at + 1)
            return at + 1
        if code[at] == '[':
            at = skip(at + 1); index = 0
            while code[at] != ']':
                at = skip(walk(at, path + (index,))); index += 1
                if code[at] != ',':
                    break
                at = skip(at + 1)
            return at + 1
        item, stop = decoder.raw_decode(code, at)
        if isinstance(item, str):
            literals[path] = (at, stop)
        return stop

    walk(start, ())
    return value, literals


@dataclasses.dataclass(eq=False)
class Field:
    start: int
    end: int
    nodes: list = dataclasses.field(default_factory=list)
    separate: object = None
    finish: object = None
    simple: object = None
    nested: bool = False

    @property
    def code(self):
        return self.simple.attrs.get(w('instr'), '') if self.simple else ''.join(n.text for n in self.nodes)

    @property
    def zotero(self):
        return 'ZOTERO' in self.code.upper()

    def raw(self, data):
        # Compare node boundaries as well as their exact payloads.
        return [data[self.simple.start:self.simple.opening]] if self.simple else [data[n.start:n.end] for n in self.nodes]

    def atoms(self, root, numbers, new_ids=frozenset()):
        if self.separate is None or self.finish is None:
            return []
        return [a for a in text_view(root, numbers, new_ids) if a.node is not None
                and self.separate.end <= a.node.start and a.node.end <= self.finish.start]


def field_inventory(document):
    result = {}
    for part, root in document.roots.items():
        stack, fields = [], []
        for node in root.walk():
            if node.tag == w('fldSimple'):
                fields.append(Field(node.start, node.end, simple=node))
            elif node.tag == w('fldChar'):
                kind = node.attrs.get(w('fldCharType'))
                if kind == 'begin':
                    for parent in stack:
                        parent.nested = True
                    field = Field(node.start, len(document.parts[part]), nested=bool(stack))
                    fields.append(field); stack.append(field)
                elif kind == 'separate' and stack:
                    if stack[-1].separate is not None:
                        stack[-1].nested = True  # malformed structure is never editable
                    stack[-1].separate = node
                elif kind == 'end' and stack:
                    field = stack.pop(); field.end = node.end; field.finish = node
            elif node.tag == w('instrText') and stack:
                stack[-1].nodes.append(node)
        result[part] = sorted(fields, key=lambda f: f.start)
    return result


def xml_char_spans(field, data):
    """Map decoded instruction characters to original XML bytes, across runs."""
    spans, text = [], []
    entities = {'amp': '&', 'lt': '<', 'gt': '>', 'quot': '"', 'apos': "'"}
    for node in field.nodes:
        raw = data[node.opening:node.closing].decode('utf-8')
        i, offset = 0, node.opening
        while i < len(raw):
            end = i + 1; char = raw[i]
            if char == '<':
                raise ValueError('The Zotero instruction contains XML markup inside its text.')
            if char == '&':
                end = raw.index(';', i) + 1; entity = raw[i+1:end-1]
                char = (chr(int(entity[2:], 16)) if entity.startswith('#x') else
                        chr(int(entity[1:])) if entity.startswith('#') else entities[entity])
            elif char == '\r':
                end += int(raw[i:i+2] == '\r\n'); char = '\n'
            stop = offset + len(raw[i:end].encode('utf-8'))
            spans.append((node, offset, stop)); text.append(char)
            offset = stop; i = end
    if ''.join(text) != field.code:
        raise ValueError('The Zotero instruction cannot be mapped to its original XML bytes.')
    return spans


def json_char_spans(code, literal):
    """Map a JSON string's Unicode characters to its original lexical spelling."""
    start, stop = literal
    spans = []; at = start + 1
    while at < stop - 1:
        end = at + 1
        if code[at] == '\\':
            end = at + (6 if code[at+1] == 'u' else 2)
            if (code[at+1] == 'u' and 0xD800 <= int(code[at+2:end], 16) <= 0xDBFF
                    and code[end:end+2] == '\\u' and 0xDC00 <= int(code[end+2:end+6], 16) <= 0xDFFF):
                end += 6
        spans.append((at, end)); at = end
    return spans


def value_at(value, path):
    for key in path:
        value = value[key]
    return value


def literal_patch(field, data, literals, path, a, b, replacement):
    """Patch only changed characters inside a literal; retain all other bytes."""
    code = field.code; literal = literals[path]
    chars = json_char_spans(code, literal); xml = xml_char_spans(field, data)
    lo = chars[a][0] if a < len(chars) else literal[1] - 1
    hi = chars[b-1][1] if b > a else lo
    # Match the literal's JSON escape style and the instruction's XML entities.
    spelling = code[literal[0]:literal[1]]
    encoded = json.dumps(replacement, ensure_ascii='\\u' in spelling)[1:-1]
    if '\\/' in spelling:
        encoded = encoded.replace('/', '\\/')
    raw = b''.join(data[n.opening:n.closing] for n in field.nodes)
    styles = {}
    for entity in re.finditer(br'&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9A-Fa-f]+);', raw):
        token = entity[0].decode('ascii')
        decoded = parse(('<t>' + token + '</t>').encode()).text
        styles.setdefault(decoded, token)
    escaped = ''.join(styles.get(ch, escape(ch)) for ch in encoded).encode('utf-8')
    if lo == hi:
        return [(xml[lo][1], xml[lo][1], escaped)]
    groups = []
    for node, start, end in xml[lo:hi]:
        if groups and groups[-1][0] is node and groups[-1][2] == start:
            groups[-1][2] = end
        else:
            groups.append([node, start, end])
    return [(start, end, escaped if i == 0 else b'') for i, (_, start, end) in enumerate(groups)]


def rtf_plain_positions(text):
    """Literal ASCII positions only; control words, escapes and fallbacks are not text."""
    plain = set(); at = 0; uc = 1; stack = []; fallback = 0
    while at < len(text):
        char = text[at]
        if char in '{}':
            if char == '{':
                stack.append(uc)
            elif stack:
                uc = stack.pop()
            at += 1
        elif char == '\\':
            match = re.match(r"\\(?:([A-Za-z]+)(-?\d+)? ?|'[0-9A-Fa-f]{2}|.)", text[at:])
            if not match:
                break
            if fallback:
                fallback -= 1
            elif match[1] == 'uc' and match[2] is not None:
                uc = max(0, int(match[2]))
            elif match[1] == 'u':
                fallback = uc
            at += len(match[0])
        else:
            if fallback:
                fallback -= 1
            elif 32 <= ord(char) < 127:
                plain.add(at)
            at += 1
    return plain


class Writer:
    def __init__(self, document, author, date, zotero_fields='edit'):
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
        self.fields = field_inventory(document)
        self.zotero_fields = zotero_fields
        self.field_changes = {}
        self.period_ends = set()
        self.period_fields = set()
        self.period_text = {}  # expected text only; never patch a field's text node
        self.period_patches = {}
        self.body_comment_patches = []
        self.story_comments = {}
        self.symbol_checks = None
        self.symbol_fields = set()

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

    def zotero_change(self, part, touched, selected, changed, insertion, replacement):
        """Return a deferred, three-literal plan; never mutate on a failed check."""
        if len(touched) != 1:
            raise ValueError('The span must lie inside the displayed result of exactly one Zotero citation field.')
        field = touched[0]
        if 'ZOTERO_BIBL' in field.code.upper():
            raise ValueError('This is a Zotero bibliography field, not an individual citation.')
        if (field.simple is not None or field.nested or field.separate is None or field.finish is None
                or any(c.node is None or not (field.separate.end <= c.node.start and c.node.end <= field.finish.start)
                       for c in selected)):
            raise ValueError('The span is not wholly inside one complete, unnested Zotero citation result.')
        try:
            value, literals = json_source(field.code)
        except ValueError as error:
            raise ValueError('The Zotero field JSON cannot be parsed safely: ' + str(error)) from error
        props = value.get('properties')
        if not isinstance(props, dict) or not isinstance(value.get('citationItems'), list):
            raise ValueError('The Zotero field has no usable properties or citation items.')
        if props.get('dontUpdate') is True:
            raise ValueError('Zotero has marked this citation not to update (dontUpdate is true).')
        shown = field.atoms(self.doc.roots[part], self.doc.numbers)
        positions = {(a.node, a.offset): i for i, a in enumerate(shown)}
        display = ''.join(a.char for a in shown)
        if changed:
            a = positions.get((changed[0].node, changed[0].offset))
            last = positions.get((changed[-1].node, changed[-1].offset))
            b = None if last is None else last + 1
        else:
            anchor, offset = insertion
            a = positions.get((anchor.node, anchor.offset))
            a = None if a is None else a + offset - anchor.offset
            b = a
        if a is None or b is None:
            raise ValueError('The changed characters cannot be located inside the Zotero result.')
        candidates = []; ambiguous = False; markup = False
        for index, item in enumerate(value['citationItems']):
            if not isinstance(item, dict):
                raise ValueError('The Zotero citation items are not objects.')
            for name in ('prefix', 'suffix', 'locator'):
                component = item.get(name)
                if not isinstance(component, str) or not component:
                    continue
                markup |= any(c in component for c in '<{\\')
                places = list(occurrences(display, component))
                if name == 'locator':
                    places = [i for i in places if
                              (i == 0 or not (display[i-1].isalnum() or display[i-1] == '_')) and
                              (i + len(component) == len(display) or not
                               (display[i+len(component)].isalnum() or display[i+len(component)] == '_'))]
                covering = [i for i in places if i <= a <= b <= i + len(component)]
                if covering and len(places) != 1:
                    ambiguous = True
                if covering and len(places) == 1:
                    candidates.append((index, name, component, covering[0]))
        if ambiguous or len(candidates) > 1:
            raise ValueError('The changed text does not identify exactly one prefix, suffix or whole-token locator; a component occurs more than once or overlaps another.')
        if not candidates:
            raise ValueError(LIBRARY_REASON + ' No stored prefix, suffix or whole-token locator matches this span verbatim.' +
                             (' Stored components contain markup that cannot be mapped safely.' if markup else ''))
        index, name, component, start = candidates[0]
        ca, cb = a - start, b - start
        if any(c in component[max(0, ca-1):cb+1] for c in '<>{}\\'):
            raise ValueError('The stored citation component has markup within or next to the changed characters.')
        if any(ord(c) < 32 or ord(c) >= 127 or c in '<>{}\\' for c in replacement):
            raise ValueError('The replacement cannot be written safely as plain ASCII in the formatted Zotero citation.')
        plain, formatted = props.get('plainCitation'), props.get('formattedCitation')
        if not isinstance(plain, str) or plain != display:
            raise ValueError('The stored plainCitation does not exactly match the displayed citation at corresponding positions.')
        if not isinstance(formatted, str) or not component.isascii():
            raise ValueError('The affected component is not available as plain ASCII in formattedCitation.')
        locations = list(occurrences(formatted, component))
        if len(locations) != 1:
            raise ValueError('The affected component must occur exactly once as plain ASCII in formattedCitation; formatting or RTF escapes prevent a certain match.')
        fa = locations[0]
        if not set(range(fa, fa + len(component))) <= rtf_plain_positions(formatted):
            raise ValueError('The affected component overlaps an RTF control sequence or escape in formattedCitation.')
        plan = [(('citationItems', index, name), ca, cb, replacement),
                (('properties', 'plainCitation'), a, b, replacement),
                (('properties', 'formattedCitation'), fa + ca, fa + cb, replacement)]
        for path, lo, hi, text in plan:
            if value_at(value, path)[lo:hi] != display[a:b]:
                raise ValueError('The old changed text does not match the stored citation at corresponding positions.')
            for previous, pa, pb, _ in self.field_changes.get(field, []):
                overlap = (lo < pb and pa < hi) or (lo == hi and pa <= lo <= pb) or (pa == pb and lo <= pa <= hi)
                if path == previous and overlap:
                    raise ValueError('Another correction already touches these stored citation characters.')
            literal_patch(field, self.doc.parts[part], literals, path, lo, hi, text)
        if any(n.ancestor(w('r')) is c.node.ancestor(w('r')) for n in field.nodes for c in selected if c.node):
            raise ValueError('The Zotero instruction shares a Word run with the displayed text.')
        return field, plan

    def footnote_comment(self, unit, find, note):
        kind = 'endnote' if unit.tag == w('endnote') or unit.ancestor(w('endnote')) is not None else 'footnote'
        note_node = unit if unit.tag == w(kind) else unit.ancestor(w(kind))
        raw_id = note_node.attrs.get(w('id')) if note_node is not None else None
        ident = ('EN:' + raw_id) if kind == 'endnote' and raw_id is not None else raw_id
        ref = self.doc.note_refs.get(ident)
        if ref is None or ref.parent is None or ref.parent.tag != w('r'):
            return None
        number = self.doc.numbers.get(ident, '?')
        label = '%s %s' % (kind.title(), number)
        if kind == 'endnote':
            record = self.doc.endnote_by_id[raw_id]
            if '@' in record['location_label']:
                label += ' (section %s, reference %s)' % (record['section'], record['order'])
        labelled = '%s, at “%s”: %s' % (label, find, note)
        if ident in self.note_comments:
            index = self.note_comments[ident]
            self.comments[index][1] += '\n' + labelled
        else:
            cid = self.ident(); index = len(self.comments)
            self.comments.append([cid, labelled]); self.note_comments[ident] = index
            # Keep custom reference marks in their original, unsplit run.
            before, after = self.around.setdefault(ref.parent, ([], []))
            before.append(self.element('commentRangeStart', attrs={'id': cid}))
            after.append(self.element('commentRangeEnd', attrs={'id': cid}) +
                         self.element('r', self.element('commentReference', attrs={'id': cid})))
        return index

    def story_comment(self, location, find, note):
        # No evidence of Word accepting header/footer anchors is assumed. Put a
        # point comment in the first actual body paragraph, after its properties.
        key = (location, find, note)
        if key in self.story_comments:
            return self.story_comments[key]
        body = next((n for n in self.doc.body.children if n.tag == w('body')), None)
        paragraph = next((n for n in body.walk() if n.tag == w('p')), None) if body else None
        if paragraph is None or paragraph.closing == paragraph.opening:
            return None
        point = paragraph.opening
        if paragraph.children and paragraph.children[0].tag == w('pPr'):
            point = paragraph.children[0].end
        cid = self.ident(); index = len(self.comments)
        self.comments.append([cid, '%s, at “%s”: %s' % (location, find, note)])
        anchor = (self.element('commentRangeStart', attrs={'id': cid}) +
                  self.element('commentRangeEnd', attrs={'id': cid}) +
                  self.element('r', self.element('commentReference', attrs={'id': cid})))
        self.body_comment_patches.append((point, point, anchor))
        self.story_comments[key] = index
        return index

    def period_plan(self, part, unit, find):
        """Locate a plain insertion without changing any fields or existing revisions."""
        atoms = text_view(unit, self.doc.numbers)
        text, spans = cleaned(atoms)
        if not find or not text or not text.endswith(find):
            raise ValueError('The excerpt does not match the footnote end.')
        terminal = text.rstrip()
        # Match extract_proof.terminal_punct_finding exactly: closing quotes are
        # stripped, but a closing parenthesis is not.
        while terminal and terminal[-1] in '\u201d"\'\u2019':
            terminal = terminal[:-1].rstrip()
        if not terminal or terminal[-1] in '.?!':
            raise ValueError('The footnote already has terminal punctuation.')
        end = spans[-1][1]
        last = atoms[end - 1]
        if last.node is None or last.node.tag != w('t') or last.node.parent.tag != w('r'):
            raise ValueError('The footnote end is not ordinary Word text.')
        if any(n.tag in (w('del'), w('moveFrom')) and n.end > last.node.end for n in unit.walk()):
            raise ValueError('The footnote end touches an existing tracked deletion or move source.')
        # Move ranges are paired markers, not ancestors of the affected text.
        active = set()
        for node in self.doc.roots[part].walk():
            if node.start > unit.end:
                break
            if node is last.node and active:
                raise ValueError('The footnote end is inside a moved-from range.')
            if node.tag in (w('moveFromRangeStart'), w('moveFromRangeEnd')):
                if last.node.start <= node.start < unit.end:
                    raise ValueError('A moved-from range touches the footnote end.')
                ident = node.attrs.get(w('id'))
                if node.tag == w('moveFromRangeStart'):
                    active.add(ident)
                else:
                    active.discard(ident)
        if unit in self.period_ends:
            raise ValueError('Another edit already adds a period at this footnote end.')
        for node, changes in self.replacements.items():
            if self.part_for(node) != part or not (unit.start <= node.start < unit.end):
                continue
            if any(node.start > last.node.start or
                   (node is last.node and b >= last.offset + 1) for a, b, _ in changes):
                raise ValueError('Another applied edit touches the footnote end.')

        fields = [f for f in self.fields[part] if f.start <= last.node.start < f.end]
        stack = []
        for node in unit.walk():
            if node.tag != w('fldChar'):
                continue
            kind = node.attrs.get(w('fldCharType'))
            if kind == 'begin':
                stack.append(False)
            elif kind == 'separate' and stack and not stack[-1]:
                stack[-1] = True
            elif kind == 'end' and stack:
                stack.pop()
            else:
                raise ValueError('The footnote has malformed field boundaries.')
        if stack:
            raise ValueError('The footnote has an incomplete field.')
        for field in fields:
            if (field.end > unit.end or (field.simple is None and
                    (field.separate is None or field.finish is None or
                     not (field.separate.end <= last.node.start < field.finish.start)))):
                raise ValueError('The terminal field is incomplete or its result is uncertain.')
            if any(f.start < field.end and field.start < f.end for f in self.field_changes):
                raise ValueError('Another applied edit touches the terminal field.')
        target = last.node.parent
        if fields:
            outer = max(fields, key=lambda f: f.end)
            target = outer.simple or outer.finish
        paragraph = last.node.ancestor(w('p'))
        while target.parent is not None and target.parent is not paragraph:
            target = target.parent
        if target.parent is not paragraph:
            raise ValueError('The terminal field or text crosses a paragraph boundary.')
        # A paragraph-level insertion leaves a whole field (including the end
        # marker's run), or an existing insertion, byte-for-byte intact.
        boundary = max(i + 1 for i, a in enumerate(atoms) if a.node and a.node.end <= target.end)
        outside_space = [a for a in atoms[end:boundary] if a.node and
                         not any(f.start <= a.node.start < f.end for f in fields)]
        point = target.end
        if outside_space:
            if fields:
                raise ValueError('Trailing whitespace shares the terminal field container; placement is uncertain.')
            # Splitting ordinary text is already supported by the writer. The
            # new run has no rPr, so it uses the paragraph's ordinary formatting.
            parent = last.node.parent.parent
            while parent is not paragraph and parent is not None and parent.tag == w('ins'):
                parent = parent.parent
            if parent is not paragraph:
                raise ValueError('Trailing whitespace has an unsupported text container.')
            boundary = end; point = None
        if point is not None and any(f.start < point < f.end for f in self.fields[part]):
            raise ValueError('The insertion point is still inside a Word field.')
        anchor = atoms[boundary - 1]
        if anchor.node is None:
            raise ValueError('The footnote end has no anchorable text.')
        return atoms, text, boundary, anchor, point

    def place_period(self, edit):
        find = edit['find'].strip()
        if find.startswith('\u2026'):
            find = find[1:].lstrip()
        location = self.doc.locations.get(edit['location'])
        if not location or location[1].tag not in (w('footnote'), w('endnote')):
            result = self.place(dict(edit, kind='comment'))
            if result['status'] == 'commented':
                result['status'] = 'commented_instead'
            return dict(result, kind='append-period', reason='The location is not a known footnote.')
        part, unit = location
        reason = None
        try:
            atoms, text, boundary, anchor, point = self.period_plan(part, unit, find)
        except ValueError as error:
            reason = str(error)
            if unit.tag == w('endnote'):
                reason = reason.replace('footnote', 'endnote')
        note = edit['note'] + ('\nNot applied: ' + reason if reason else '')
        index = self.footnote_comment(unit, find, note)
        if reason:
            return dict(id=edit['id'], kind='append-period',
                        status='commented_instead' if index is not None else 'unplaced', reason=reason)
        attrs = {'id': self.ident(True), 'author': self.author, 'date': self.date}
        inserted = self.element('ins', self.element('r', self.text('.')), attrs)
        if point is None:
            self.event(anchor.node, anchor.offset + 1, inserted)
        else:
            self.period_patches.setdefault(part, []).append((point, point, inserted))
        self.period_text.setdefault(anchor.node, []).append((anchor.offset + 1, anchor.offset + 1, '.'))
        self.period_ends.add(unit)
        self.period_fields.update(f for f in self.fields[part]
                                  if unit.start <= f.start < f.end <= unit.end and not any(
                                      changed.start < f.end and f.start < changed.end
                                      for changed in self.field_changes))
        # Independent requested-text check, including whitespace retained inside
        # an unedited field before the period. Outside whitespace stays after it.
        suffix = ' .' if atoms[boundary - 1].char.isspace() else '.'
        self.requests.setdefault(unit, []).append((len(text), len(text), suffix))
        return dict(id=edit['id'], status='applied', kind='append-period')

    def place(self, edit):
        location = edit['location']
        if location.startswith('en.') and location not in self.doc.locations:
            return dict(id=edit['id'], status='unplaced', reason='Unknown or ambiguous endnote location; no body fallback attempted.')
        if location not in self.doc.header_locations:
            if re.search(r'\b(?:header|footer)\b', location, re.I):
                return dict(id=edit['id'], status='unplaced', reason='Unknown header/footer location; no body fallback attempted.')
            return self._place(edit)
        if edit['kind'] == 'append-period':
            result = self.place(dict(edit, kind='comment'))
            if result['status'] == 'commented':
                result['status'] = 'commented_instead'
            return dict(result, kind='append-period', reason='The location is not a known footnote.')
        # A deduplicated finding may represent several physical parts. Plan all
        # copies on an isolated writer; never apply only some of a repeated text.
        # Source nodes/fields are immutable identities used by verification and
        # existing edit maps. Clone only the mutable plan, retaining those keys.
        memo = {id(self.doc): self.doc}
        memo.update({id(n): n for root in self.doc.roots.values() for n in root.walk()})
        memo.update({id(f): f for fields in self.fields.values() for f in fields})
        trial = copy.deepcopy(self, memo)
        outcomes = [trial._place(dict(edit, _candidate=target))
                    for target in trial.doc.header_locations[location]]
        statuses = {r['status'] for r in outcomes}
        if statuses <= {'applied', 'commented'}:
            self.__dict__.update(trial.__dict__)
            return dict(id=edit['id'], status='applied' if 'applied' in statuses else 'commented')
        reason = '; '.join(dict.fromkeys(r.get('reason', r['status']) for r in outcomes if r['status'] not in {'applied', 'commented'}))
        # No matched/anchorable copy means unplaced, rather than a guessed comment.
        if 'unplaced' in statuses:
            return dict(id=edit['id'], status='unplaced', reason=reason)
        commented = [self._place(dict(edit, kind='comment', note=edit['note'] +
                      '\nProposed replacement: ' + edit.get('replacement', '') + '\nNot applied: ' + reason,
                      _candidate=target)) for target in self.doc.header_locations[location]]
        status = 'commented_instead' if all(r['status'] == 'commented' for r in commented) else 'unplaced'
        return dict(id=edit['id'], status=status, reason=reason)

    def _place(self, edit):
        if edit['kind'] == 'append-period':
            return self.place_period(edit)
        # The deterministic lint reports an excerpt with an ellipsis at either end
        # ("…concerns the the relationship…"). The words between are verbatim, so
        # anchor a comment on them; an excerpt is never applied as a change.
        core = edit['find'].strip()
        find = core.strip('\u2026').strip()
        excerpt = find != core
        if edit['kind'] == 'change' and not excerpt and core != edit['find']:
            # A find string padded with spaces is still exact text when the replacement
            # carries the same padding; drop it from both. Otherwise treat it as an excerpt.
            raw, new = edit['find'], edit['replacement']
            lead, trail = raw[:len(raw) - len(raw.lstrip())], raw[len(raw.rstrip()):]
            if new.startswith(lead) and new.endswith(trail) and len(new) >= len(lead) + len(trail):
                edit = dict(edit, replacement=new[len(lead):len(new) - len(trail)])
            else:
                excerpt = True
        if not find:
            return dict(id=edit['id'], status='unplaced', reason='No matching span')
        candidates = ([edit['_candidate']] if '_candidate' in edit else
                      [self.doc.locations[edit['location']]] if edit['location'] in self.doc.locations else self.doc.search)
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
        reason = None; field_plan = None
        if edit['kind'] == 'change':
            touched = [f for f in self.fields[part] if first.node.start < f.end and f.start < last.node.end]
            prefix, end, replacement = trimmed_change(find, edit['replacement'])
            ca, cb = at + prefix, at + end
            changed = atoms[spans[ca][0]:spans[cb-1][1]] if ca < cb else []
            insertion = None
            if ca == cb:
                if ca == at + len(find) and any(f.zotero for f in touched):
                    # Stay in the citation's last selected run, not the next
                    # run (which may be outside the field). Other text retains
                    # the original writer's insertion and formatting behavior.
                    anchor = atoms[b-1]; offset = anchor.offset + 1
                else:
                    boundary = spans[ca][0] if ca < len(spans) else b
                    anchor = atoms[boundary] if boundary < len(atoms) else atoms[-1]
                    offset = anchor.offset if boundary < len(atoms) else anchor.offset + 1
                insertion = (anchor, offset)
            if excerpt:
                reason = 'The find text is an excerpt, not the exact text to replace.'
            if reason is None and touched:
                if part in self.doc.story_parts:
                    reason = 'The header/footer span touches a Word field; fields in these parts are preserved.'
                elif not any(f.zotero for f in touched):
                    reason = 'The span touches a Word field; change the field at its source.'
                elif self.zotero_fields == 'comment':
                    reason = 'The citation is generated by Zotero and must be changed there.'
                else:
                    try:
                        field_plan = self.zotero_change(part, touched, selected, changed, insertion, replacement)
                    except ValueError as error:
                        reason = str(error)
            if reason is None and any(c.node and c.node.tag in (w('footnoteReference'), w('endnoteReference')) for c in selected):
                reason = 'The span touches a note reference mark.'
            if reason is None and any(n.tag in (w('del'), w('moveFrom')) and first.node.start < n.end and n.start < last.node.end for n in self.doc.roots[part].walk()):
                reason = 'The span crosses an existing tracked deletion or move source.'
            if reason is None and (any(c.node is None or c.node.tag != w('t') for c in selected)
                                   or first.node.ancestor(w('p')) is not last.node.ancestor(w('p'))):
                reason = 'The span crosses a paragraph boundary or non-text Word control.'
        status = 'commented' if edit['kind'] == 'comment' else ('commented_instead' if reason else 'applied')
        note = edit['note']
        if reason:
            note += '\nProposed replacement: ' + edit['replacement'] + '\nNot applied: ' + reason
        elif field_plan:
            note += '\n' + ZOTERO_NOTICE
        if part in self.doc.story_parts:
            index = self.story_comment(edit['location'], find, note)
            if index is None:
                return dict(id=edit['id'], status='unplaced', reason='No body paragraph can carry the header/footer comment.')
        elif part in ('word/footnotes.xml', 'word/endnotes.xml'):
            # Word has no comments inside footnotes and drops any it finds there when it
            # opens the file. A footnote finding's comment hangs on the footnote's reference
            # mark in the text instead: one comment per footnote, naming the words it is about.
            index = self.footnote_comment(unit, find, note)
            if index is None:
                if status != 'applied' or field_plan:
                    return dict(id=edit['id'], status='unplaced', reason='The footnote has no reference mark in the text to carry a comment.')
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
            if field_plan:
                field, plan = field_plan
                self.field_changes.setdefault(field, []).extend(plan)
            self.requests.setdefault(unit, []).append((at, at + len(find), edit['replacement']))
            if ca == cb:
                anchor, offset = insertion
                self.replacements.setdefault(anchor.node, []).append((offset, offset, replacement))
            else:
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
        if status == 'applied' and field_plan:
            result['field'] = 'zotero'
        if reason:
            result['reason'] = reason
        return result

    def fix_symbol_spaces(self):
        """Plan from the snapshot after findings, with an independent strict ledger.

        in_fields counts displayed gaps; instruction gaps have their own skip
        count, since citeform deliberately excludes instructions from its view.
        No comments or finding totals are added by this pass.
        """
        summary = dict(applied=0, in_fields=0, skipped={})
        records = {}  # source text node -> source character offsets

        def skip(reason, count=1):
            if count:
                summary['skipped'][reason] = summary['skipped'].get(reason, 0) + count

        edited_runs = {n.ancestor(w('r')) for n in set(self.events) | set(self.replacements)} | set(self.around)
        for part in SYMBOL_PARTS:
            root = self.doc.roots.get(part)
            if root is None:
                continue
            fields = self.fields[part]
            # The pass never splits a run intersecting a field. Also verify the
            # entire bytes of fields which findings have left untouched.
            other_patches = self.period_patches.get(part, [])
            if part == 'word/document.xml':
                other_patches = other_patches + self.body_comment_patches
            for field in fields:
                if (field not in self.field_changes
                        and not any(r and self.part_for(r) == part and r.start < field.end and field.start < r.end
                                    for r in edited_runs)
                        and not any(field.start < b and a < field.end for a, b, _ in other_patches)):
                    self.symbol_fields.add(field)

            # Move ranges can span paragraphs without wrapping the moved text.
            ranges, active = [], {}
            for n in root.walk():
                for kind in ('moveFrom', 'moveTo'):
                    key = (kind, n.attrs.get(w('id')))
                    if n.tag == w(kind + 'RangeStart'):
                        active[key] = n.start
                    elif n.tag == w(kind + 'RangeEnd') and key in active:
                        ranges.append((active.pop(key), n.end))
            ranges.extend((start, root.end) for start in active.values())

            # Deleted text is absent from the accepted detector stream, but is
            # inventoried separately so it is explicitly accounted for, once.
            for n in root.walk():
                if n.tag in (w('del'), w('moveFrom')) and not any(
                        n.parent and n.parent.ancestor(w(t)) for t in ('del', 'moveFrom')):
                    raw = ''.join(c.text if c.tag in (w('t'), w('delText')) else
                                  ' ' if c.tag in (w('tab'), w('br'), w('cr'), w('p')) else ''
                                  for c in n.walk())
                    skip('tracked_revision', sum(1 for _ in SYMBOL_GAP.finditer(raw)))
            instructions = [f.code for f in fields]
            covered = {n for f in fields for n in f.nodes}
            instructions.extend(n.text for n in root.walk() if n.tag == w('instrText') and n not in covered)
            skip('field_instruction', sum(1 for code in instructions for m in SYMBOL_GAP.finditer(code)
                                          if not all(c in NONBREAKING for c in m[2])))

            if part == 'word/document.xml':
                units = [n for n in root.walk() if n.tag == w('p')]
            else:
                kind = 'footnote' if part == 'word/footnotes.xml' else 'endnote'
                units = [n for n in root.children if n.tag == w(kind)]
            for unit in units:
                if any(unit.ancestor(w(t)) for t in ('del', 'moveFrom')):
                    continue
                if part == 'word/document.xml':
                    atoms = text_view(unit, self.doc.numbers)
                else:
                    # Include paragraphs in note tables as well as direct ones.
                    # The synthetic separator can be detected, but never edited.
                    atoms = []
                    paragraphs = [n for n in unit.walk() if n.tag == w('p') and not any(
                        n.ancestor(w(t)) for t in ('del', 'moveFrom'))]
                    for i, p in enumerate(paragraphs):
                        if i:
                            atoms.append(Atom(' ', None, 0))
                        atoms.extend(text_view(p, self.doc.numbers))
                raw = ''.join(a.char for a in atoms)
                for match in SYMBOL_GAP.finditer(raw):
                    gap = atoms[match.start(2):match.end(2)]
                    context = atoms[match.start():match.end() + 1]
                    nodes = [a.node for a in context if a.node is not None]
                    lo, hi = min(n.start for n in nodes), max(n.end for n in nodes)
                    if all(c in NONBREAKING for c in match[2]):
                        skip('already_nonbreaking')
                    elif any(lo < f.end and f.start < hi for f in fields):
                        summary['in_fields'] += 1
                    elif match[2] != ' ' or gap[0].node is None or gap[0].node.tag != w('t'):
                        skip('non_single_space')
                    elif (any(n.ancestor(w(t)) for n in nodes for t in ('ins', 'del', 'moveFrom', 'moveTo'))
                          or any(n.tag in (w('del'), w('moveFrom')) and lo < n.end and n.start < hi for n in unit.walk())
                          or any(lo < end and start < hi for start, end in ranges)):
                        skip('tracked_revision')
                    else:
                        atom = gap[0]; run = atom.node.ancestor(w('r'))
                        note_tags = {w(t) for t in ('footnoteReference', 'endnoteReference', 'footnoteRef', 'endnoteRef')}
                        if (any(n.tag in note_tags and lo < n.end and n.start < hi for n in unit.walk())
                                or (run and any(n.tag in note_tags for n in run.walk()))):
                            skip('note_mark')
                        elif (run is None or atom.node.parent is not run
                              or any(a.node is None or a.node.tag != w('t') for a in context)
                              or len({n.ancestor(w('p')) for n in nodes}) != 1
                              or any(n.ancestor(w('p')).parent.ancestor(w('p')) for n in nodes)):
                            skip('unsupported_structure')
                        elif (any(run.start < f.end and f.start < run.end for f in fields)
                              or any(n.tag in (w('instrText'), w('fldChar'), w('fldSimple')) for n in run.walk())):
                            skip('field_run')
                        elif any(run.start < end and start < run.end for start, end in ranges):
                            skip('tracked_revision')
                        elif any(a <= c.offset < b or a == b and c.offset <= a <= c.offset + 1
                                 for c in context for a, b, _ in
                                 self.replacements.get(c.node, []) + self.period_text.get(c.node, [])):
                            skip('other_edit')
                        else:
                            records.setdefault(atom.node, set()).add(atom.offset)

        # Freeze the ordinary-edit baseline BEFORE adding symbol replacements.
        # Record positions after its length changes, independently of the mutable
        # replacement map consumed by edited_parts() and the existing verifier.
        self.symbol_checks = {}
        for key, unit in self.doc.units.items():
            if key[0] not in SYMBOL_PARTS:
                continue
            atoms = text_view(unit, self.doc.numbers)
            starts = {a.node: i - a.offset for i, a in enumerate(atoms) if a.node is not None}
            changes = [(starts[n] + a, starts[n] + b, replacement)
                       for n in starts for a, b, replacement in
                       self.replacements.get(n, []) + self.period_text.get(n, [])]
            positions = []
            baseline = self.expected(atoms)
            for i, atom in enumerate(atoms):
                if atom.offset in records.get(atom.node, ()):
                    at = i + sum(len(r) - (b - a) for a, b, r in changes if b <= i)
                    if atom.char != ' ' or baseline[at:at + 1] != ' ':
                        raise ValueError('Verification failed: symbol-space source is not U+0020')
                    positions.append(at)
            self.symbol_checks[key] = (baseline, tuple(positions))
        for node, offsets in records.items():
            for offset in sorted(offsets):
                self.replacements.setdefault(node, []).append((offset, offset + 1, '\u00a0'))
                summary['applied'] += 1
        return summary

    def expected(self, atoms):
        output = []
        for i, atom in enumerate(atoms):
            changes = self.replacements.get(atom.node, []) + self.period_text.get(atom.node, [])
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
        edits = {part: list(changes) for part, changes in self.period_patches.items()}
        if self.body_comment_patches:
            edits.setdefault('word/document.xml', []).extend(self.body_comment_patches)
        for part, fields in self.fields.items():
            for field in fields:
                if field in self.field_changes:
                    _, literals = json_source(field.code)
                    for path, a, b, replacement in self.field_changes[field]:
                        edits.setdefault(part, []).extend(literal_patch(field, result[part], literals, path, a, b, replacement))
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
        raise ValueError('Verification failed: paragraph/note structure changed')
    for key, node in original.units.items():
        before = text_view(node, original.numbers)
        after = document.units[key]
        rejected = ''.join(a.char for a in text_view(after, document.numbers, writer.new_ids, False))
        accepted = ''.join(a.char for a in text_view(after, document.numbers, writer.new_ids, True))
        if rejected != ''.join(a.char for a in before):
            raise ValueError('Verification failed: rejected view differs at %r' % (key,))
        if writer.symbol_checks is not None and key in writer.symbol_checks:
            baseline, positions = writer.symbol_checks[key]
            expected = list(baseline)
            for at in positions:
                if expected[at] != ' ':
                    raise ValueError('Verification failed: symbol-space position is not U+0020')
                expected[at] = '\u00a0'
            if accepted != ''.join(expected):
                raise ValueError('Verification failed: strict symbol-space view differs at %r' % (key,))
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
    verify_fields(document, original, writer)


def verify_fields(document, original, writer):
    inventory = field_inventory(document)
    for part in set(inventory) | set(writer.fields):
        old_fields, new_fields = writer.fields.get(part, []), inventory.get(part, [])
        if len(old_fields) != len(new_fields):
            raise ValueError('Verification failed: Word field structure changed')
        for before, after in zip(old_fields, new_fields):
            if before in writer.symbol_fields and original.parts[part][before.start:before.end] != document.parts[part][after.start:after.end]:
                raise ValueError('Verification failed: unedited field bytes changed during symbol-space pass')
            if part in original.story_parts and original.parts[part][before.start:before.end] != document.parts[part][after.start:after.end]:
                raise ValueError('Verification failed: header/footer field bytes changed')
            if before in writer.period_fields and original.parts[part][before.start:before.end] != document.parts[part][after.start:after.end]:
                raise ValueError('Verification failed: unedited field bytes changed while appending a period')
            if not (before.zotero or after.zotero):
                continue
            plan = writer.field_changes.get(before)
            if not plan:
                # An unedited field must be untouched, whatever is in it. A draft with a
                # damaged citation field still gets its redline: that field was only ever
                # commented on, and its bytes are checked here, not its JSON.
                if before.raw(original.parts[part]) != after.raw(document.parts[part]):
                    raise ValueError('Verification failed: unedited Zotero instruction bytes changed')
                continue
            try:
                old_json, literals = json_source(before.code)
                new_json, _ = json_source(after.code)
            except ValueError as error:
                raise ValueError('Verification failed: Zotero field JSON does not parse: ' + str(error)) from error
            expected = copy.deepcopy(old_json)
            for path in {entry[0] for entry in plan}:
                text = value_at(old_json, path)
                for _, a, b, replacement in sorted((e for e in plan if e[0] == path), key=lambda e: e[1], reverse=True):
                    text = text[:a] + replacement + text[b:]
                value_at(expected, path[:-1])[path[-1]] = text
            # Compare JSON types too (Python considers True == 1). Serialization
            # here is only a comparison; it is never written into a field.
            if json.dumps(new_json, sort_keys=True) != json.dumps(expected, sort_keys=True):
                raise ValueError('Verification failed: Zotero JSON differs from the intended three-string changes')
            changes = []
            for path, a, b, replacement in plan:
                changes.extend(literal_patch(before, original.parts[part], literals, path, a, b, replacement))
            expected_bytes = [patches(original.parts[part][n.start:n.end],
                                      [(a-n.start, b-n.start, r) for a, b, r in changes if n.start <= a <= b <= n.end])
                              for n in before.nodes]
            if after.raw(document.parts[part]) != expected_bytes:
                raise ValueError('Verification failed: Zotero instruction bytes changed outside the intended literals')
            accepted = ''.join(a.char for a in after.atoms(document.roots[part], document.numbers, writer.new_ids))
            if re.sub(r'\s+', ' ', new_json['properties']['plainCitation']).strip() != re.sub(r'\s+', ' ', accepted).strip():
                raise ValueError('Verification failed: Zotero plainCitation differs from its accepted displayed text')


def validate_edits(edits):
    if not isinstance(edits, list):
        raise ValueError('edits must be a list')
    ids = set()
    for edit in edits:
        if not isinstance(edit, dict) or any(not isinstance(edit.get(k), str) for k in ('id', 'location', 'find', 'kind', 'note')):
            raise ValueError('Invalid edit fields')
        if not edit['id'] or edit['id'] in ids or not edit['find'] or edit['kind'] not in ('change', 'comment', 'append-period'):
            raise ValueError('Invalid or duplicate edit id, empty find, or invalid kind')
        if edit['kind'] == 'change' and not isinstance(edit.get('replacement'), str):
            raise ValueError('A change requires a string replacement')
        if edit['kind'] == 'append-period' and 'replacement' in edit:
            raise ValueError('An append-period edit must not carry a replacement')
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
        period = finding['category'] == 'cite-terminal-punct' and not replacement
        edit = dict(id=str(index), location=finding['location'], find=finding['find'],
                    kind='append-period' if period else ('change' if change else 'comment'),
                    note=finding['problem'] + '\n' + finding['fix'])
        if change:
            edit['replacement'] = replacement
        edits.append(edit)
    return edits


def generate(draft, edits, output, result, author, date, fault_hook=None, staging_dir=None, zotero_fields='edit', symbol_spaces='off'):
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
            if zotero_fields not in ('edit', 'comment'):
                raise ValueError('zotero_fields must be edit or comment')
            if symbol_spaces not in ('fix', 'off'):
                raise ValueError('symbol_spaces must be fix or off')
            stamp = datetime.datetime.fromisoformat(date.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                raise ValueError('Date must include a time zone')
            if not author:
                raise ValueError('Author is required')
            totals = dict(applied=0, commented=0, commented_instead=0, unplaced=0, applied_in_zotero_fields=0)
            if not edits and symbol_spaces == 'off':
                answer = dict(status='no_edits', reason='No confirmed findings to redline', edits=[], totals=totals)
                json.dump(answer, result_file, ensure_ascii=False, indent=2)
                return answer
            with zipfile.ZipFile(draft, 'r') as archive:
                infos = archive.infolist()
                if len({i.filename for i in infos}) != len(infos):
                    raise ValueError('Duplicate ZIP members')
                parts = {i.filename: archive.read(i) for i in infos}
                archive_comment = archive.comment
            document = Document(parts); writer = Writer(document, author, date, zotero_fields)
            # Changes claim their spans first, so a comment on the same words never
            # displaces a correction; results are reported in the order given.
            placed = {}
            for kind in ('change', 'append-period', 'comment'):
                for edit in edits:
                    if edit['kind'] == kind:
                        placed[edit['id']] = writer.place(edit)
            outcomes = [placed[edit['id']] for edit in edits]
            spacing = writer.fix_symbol_spaces() if symbol_spaces == 'fix' else None
            if not edits and not spacing['applied']:
                answer = dict(status='no_edits', reason='No confirmed findings or symbol spaces to redline',
                              edits=[], totals=totals, symbol_spaces=spacing)
                json.dump(answer, result_file, ensure_ascii=False, indent=2)
                return answer
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
                if entry.get('field') == 'zotero':
                    totals['applied_in_zotero_fields'] += 1
            digest = hashlib.sha256(stage.read_bytes()).hexdigest()
            answer = dict(status='written', edits=outcomes, totals=totals, sha256=digest)
            if spacing is not None:
                answer['symbol_spaces'] = spacing
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--edits')
    mode.add_argument('--findings')
    parser.add_argument('--staging-dir')
    parser.add_argument('--zotero-fields', choices=('edit', 'comment'), default='edit')
    parser.add_argument('--symbol-spaces', choices=('fix', 'off'), default='off')
    args = parser.parse_args()
    if not (args.edits or args.findings) and args.symbol_spaces != 'fix':
        parser.error('one of --edits or --findings is required unless --symbol-spaces fix is set')
    try:
        values = []
        if args.edits or args.findings:
            with open(args.edits or args.findings, encoding='utf-8') as source:
                values = json.load(source)
        edits = edits_from_findings(values) if args.findings else values
        generate(args.draft, edits, args.output, args.result, args.author, args.date,
                 staging_dir=args.staging_dir, zotero_fields=args.zotero_fields, symbol_spaces=args.symbol_spaces)
        return 0
    except Exception as error:
        print('Redline not made: ' + str(error), file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
