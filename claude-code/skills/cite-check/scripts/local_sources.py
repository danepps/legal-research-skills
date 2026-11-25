"""Bounded offline source proposals; originals are read-only. Stdlib + optional pdftotext.

Keep this module identical in the two public plugins. Identity is a proposal:
the consuming agent must inspect the first content page before relying on it.
"""
from __future__ import annotations
import hashlib
import json
import os
import re
import selectors
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path
from source_options import discover_folders

VERSION = 2
SUFFIXES = {'.pdf', '.txt', '.md'}
MAX_FILE_BYTES = 60 * 1024 * 1024
MAX_TEXT_BYTES = 16 * 1024 * 1024
MAX_PREVIEW_BYTES = 256 * 1024
MAX_PAGES = 400
MAX_FILES = 500
PREVIEW_PAGES = 3


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def words(text):
    text = unicodedata.normalize('NFKD', text).casefold()
    return re.findall(r'[a-z0-9]+', ''.join(c for c in text if not unicodedata.combining(c)))


def protect_output(path, folders):
    path = Path(path).expanduser()
    if path.is_symlink() or any(p.is_symlink() for p in path.parents):
        raise ValueError('refusing a symlink output or output parent')
    if path.resolve() in [Path(f).expanduser().resolve() for f in folders]:
        raise ValueError('output must not replace a source folder')


def write_json(path, data):
    path = Path(path)
    protect_output(path, [])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def pdf_text(path, full):
    decoder = shutil.which('pdftotext')
    if not decoder:
        raise ValueError('pdftotext unavailable; no extraction or installation attempted')
    limit = MAX_TEXT_BYTES if full else MAX_PREVIEW_BYTES
    # One extra page detects a full copy beyond the page cap without extracting it all.
    proc = subprocess.Popen([decoder, '-layout', '-enc', 'UTF-8', '-f', '1', '-l',
                             str(MAX_PAGES + 1 if full else PREVIEW_PAGES), str(path), '-'],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    data = bytearray()
    try:
        deadline = time.monotonic() + 120
        with selectors.DefaultSelector() as selector:
            selector.register(proc.stdout, selectors.EVENT_READ)
            while True:
                if time.monotonic() >= deadline:
                    raise ValueError('PDF extraction timed out')
                if not selector.select(min(1, max(0, deadline-time.monotonic()))):
                    continue
                chunk = os.read(proc.stdout.fileno(), min(65536, limit + 1 - len(data)))
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > limit:
                    raise ValueError('extracted size limit exceeded')
        if proc.wait(timeout=max(.1, deadline-time.monotonic())):
            raise ValueError('pdftotext could not read this PDF')
        return data.decode('utf-8')
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()


def plain_text(path, full):
    limit = MAX_TEXT_BYTES if full else MAX_PREVIEW_BYTES
    data = bytearray()
    with path.open('rb') as stream:
        while len(data) <= limit:
            chunk = stream.read(min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if not full and data.count(b'\f') >= PREVIEW_PAGES:
                data = bytearray(b'\f'.join(data.split(b'\f')[:PREVIEW_PAGES]) + b'\f')
                break
        if len(data) > limit:
            raise ValueError('extracted size limit exceeded')
    return data.decode('utf-8-sig')


def index_file(path, cache, *, full=False):
    protect_output(cache, [])
    path, cache = Path(path).resolve(), Path(cache).resolve()
    entry = dict(filePath=str(path), fileName=path.name, readable=False, cacheReused=False, fullText=full)
    meta = None
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError('file size limit exceeded')
        sha = digest(path)
        entry['fileSha256'] = sha
        stem = f'{sha}-{path.suffix.lower()[1:]}-v{VERSION}-' + ('full' if full else 'head')
        meta, text_path = cache/(stem+'.json'), cache/(stem+'.txt')
        limits = [MAX_FILE_BYTES, MAX_TEXT_BYTES, MAX_PREVIEW_BYTES, MAX_PAGES]
        if meta.is_file() and not meta.is_symlink():
            saved = json.loads(meta.read_text(encoding='utf-8'))
            if saved.get('limits') == limits:
                if saved.get('readable') and text_path.is_file() and not text_path.is_symlink() and digest(text_path) == saved.get('textSha256'):
                    return {**saved, **entry, 'readable': True, 'cacheReused': True}
                if not saved.get('readable') and saved.get('decoderAvailable') == bool(shutil.which('pdftotext')):
                    return {**saved, **entry, 'cacheReused': True}
        cache.mkdir(parents=True, exist_ok=True)
        protect_output(text_path, [])
        text = pdf_text(path, full) if path.suffix.lower() == '.pdf' else plain_text(path, full)
        if not re.search(r'[^\W\d_]', text) or '\x00' in text:
            raise ValueError('no readable text layer; OCR is not performed')
        pages = text.split('\f')
        if pages and not pages[-1].strip():
            pages.pop()
        if full and len(pages) > MAX_PAGES:
            raise ValueError('page count limit exceeded')
        if digest(path) != sha:
            raise ValueError('source changed during extraction; rerun before using it')
        text_path.write_text(text, encoding='utf-8')
        entry.update(readable=True, textPath=str(text_path), textSha256=digest(text_path), textPages=len(pages),
                     textSource='pdf' if path.suffix.lower()=='.pdf' else 'text', firstPages=pages[:PREVIEW_PAGES])
    except (OSError, ValueError, MemoryError, subprocess.TimeoutExpired) as exc:
        # Exception text can contain private absolute paths. Stable, path-free reasons only.
        reason = str(exc) if isinstance(exc, ValueError) and not isinstance(exc, UnicodeError) else type(exc).__name__ + ' during extraction'
        entry.update(readable=False, reason=reason, decoderAvailable=bool(shutil.which('pdftotext')))
    entry['limits'] = [MAX_FILE_BYTES, MAX_TEXT_BYTES, MAX_PREVIEW_BYTES, MAX_PAGES]
    if meta is not None:
        write_json(meta, entry)
    return entry


def index_folders(folders, cache, *, exclude=()):
    folders = [Path(f).expanduser().resolve() for f in folders]
    protect_output(cache, folders)
    excluded = [Path(p).resolve() for p in (*exclude, cache)]
    entries, errors, seen = [], [], set()
    for folder in folders:
        if not folder.is_dir():
            errors.append(dict(folder=folder.name, reason='source folder is missing or not a directory'))
            continue
        for root, dirs, names in os.walk(folder, followlinks=False):
            base = Path(root)
            dirs[:] = sorted(d for d in dirs if not d.startswith('.') and not (base/d).is_symlink()
                             and not any((base/d).resolve() == e or e in (base/d).resolve().parents for e in excluded))
            for name in sorted(names):
                path = base/name
                if name.startswith('.') or path.is_symlink() or path.suffix.lower() not in SUFFIXES or path.resolve() in seen:
                    continue
                if any(path.resolve() == e or e in path.resolve().parents for e in excluded):
                    continue
                if len(entries) >= MAX_FILES:
                    errors.append(dict(folder=folder.name, reason=f'file count limit {MAX_FILES} reached; remaining files not indexed'))
                    print(f'Local sources: file count limit {MAX_FILES} reached; remaining files skipped.', file=sys.stderr)
                    return entries, errors
                seen.add(path.resolve())
                print(f'Local sources: indexing {len(entries)+1}/{MAX_FILES}: {path.relative_to(folder)}', file=sys.stderr)
                row = index_file(path, cache)
                row['relativePath'] = str(path.relative_to(folder))
                entries.append(row)
    return entries, errors


EDITION_RE = re.compile(r'\b(\d+)(?:st|nd|rd|th|d)?\s+(?:ed\.?|edition)\b|\b(first|second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth)\s+(?:ed\.?|edition)\b', re.I)
ORDINALS = 'first second third fourth fifth sixth seventh eighth ninth tenth'.split()

def editions(text):
    return list(dict.fromkeys(m.group(1) or str(ORDINALS.index(m.group(2).lower())+1) for m in EDITION_RE.finditer(text)))


def nonblank_pages(entry):
    return [(i+1,p) for i,p in enumerate(entry.get('firstPages',[])) if p.strip()]


def lines_of(page):
    return [line.strip().lstrip('#').strip() for line in page.splitlines() if line.strip()]


STYLE_LABEL = re.compile(r'^(?:ALWD|APA|Chicago|McGill|AGLC|MLA|OSCOLA|Bluebook)\b', re.I)
HEIN_HEAD = re.compile(r'^(?:HeinOnline$|DATE DOWNLOADED\b|SOURCE: Content Downloaded from HeinOnline|(?:https?://)?heinonline\.org \||Downloaded from HeinOnline|Content downloaded/printed from HeinOnline)', re.I)
HEIN_OLD_LINE = re.compile(r'^Citation:\s*\d+ \S.{1,80}? \d+ (?:1[6-9]|20)\d{2}(?:-\d{4})?\s*$', re.I)
HEIN_OLD_FURNITURE = re.compile(r'Content downloaded/printed from|HeinOnline \(http|HeinOnline.s Terms', re.I)
REPOSITORY_FURNITURE = re.compile(r'Follow this and additional works|^Available at:|brought to you|Repository|Commons\b', re.I | re.M)
MARKER = re.compile(r'^(?:(?:this (?:is|article is|paper is) (?:an? |the )?)?(?:working paper|forthcoming|preprint|postprint|accepted (?:manuscript|version)|peer[- ]reviewed version|author[- ](?:accepted manuscript|produced version)|author[’\']?s? (?:manuscript|version)|to be published in|post[- ]peer[- ]review|pre[- ]copyedit|submitted manuscript|final publication is available|manuscript has been accepted for publication)|draft(?:\s*(?:$|[:(—-]|version|dated|\d)))',re.I)
# Version statements that the anchored MARKER list does not carry.
QUALIFIER = re.compile(r'\b(?:forthcoming|reprinted (?:in|from|with)|early view|advance (?:sheet|access|article)|provisional|uncorrected proofs?|accepted manuscript|'
                       r'working paper|preprint|draft|electronic copy available at|ssrn\.com)\b', re.I)
AFTER_BYLINE = re.compile(r'\b(?:reviewed by|review by|reviewer|reviewing)\b|^pp?\.\s*\d|\$\s?\d', re.I)
SUFFIXES_OF_NAMES = {'jr','sr','ii','iii','iv'}
JOURNAL_STOP = {'of','the','and','for','on','in','at','a'}
ROLE_WORDS = {'for','to','edited','editor','editors','eds','translated','translator','reviewer','reviewed','review','with','from',
              'foreword','introduction','her','his','their','colleagues','memory','dedicated','in','honor','of','the','an','on'}
INSTITUTION = re.compile(r'\b(?:university|college|school|law|professor|institute|center|centre|department|judge|court|esq|fellow|faculty)\b', re.I)
INSTITUTION_HEAD = re.compile(r'\b(?:university|college|school of law|law school|institute|center for|centre for)\b', re.I)
NOT_A_BANNER = re.compile(r'\b(?:list|reading|readings|schedule|syllabus|course|seminar|cases|materials|contents|selected)\b', re.I)
HEADING_WORDS = {'summary','executive','framework','findings','key','introduction','abstract','contents','overview','background','conclusion',
                 'conclusions','part','section','chapter','table','keywords','acknowledgments','acknowledgements','preface','legal','analysis',
                 'discussion','methods','results','article','essay','note','comment','prologue','epilogue','appendix','synopsis','outline'}
STOP_WORDS = {'a','an','the','of','and','or','in','on','to','for','by','with','at','as','is','it'}
SECTION_LABELS = {'article','articles','essay','essays','note','notes','comment','comments','lecture','lectures','feature','features',
                  'symposium','colloquium','address','commentary','tribute','tributes','book review','book reviews','review essay','essay review'}
COMMON_TITLES = {'introduction','foreword','preface','afterword','comment','comments','note','notes','response','reply','rejoinder','conclusion',
                 'book review','dedication','tribute','in memoriam','editor s note','editors note','symposium','postscript','prologue','epilogue',
                 'faculty tribute','case comment','case comments','recent cases','recent developments','book note','book notes','case note',
                 'case notes','editor s foreword','editors foreword','in tribute','remarks','essay','article','commentary','panel discussion',
                 'keynote address','opening remarks','closing remarks','a reply','a response','a comment','a tribute','concluding remarks'}
SERIES_WORDS = {'foreword','term','symposium','lecture','colloquy','colloquium','tribute'}
MONTHS = r'(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|spring|summer|fall|autumn|winter)'
FRONT_MATTER = re.compile(r'^(?:(?:vol(?:ume)?|issue|no|number)\.?\s*\d+\b.{0,60}|' + MONTHS + r'\.?,?\s+(?:\d{1,2},?\s+)?\d{4}|\[?\d{1,5}\]?|'
                          r'(?:copyright|©).{0,120}|.*(?:\.docx?\b|\.pdf\b|do not delete|\b\d{1,2}/\d{1,2}/\d{2,4}\b).*|'
                          r'(?:\S+ ){0,6}(?:https?://|www\.)\S+(?: \S+){0,3}|.*\b(?:research|working|discussion) papers? (?:series|no)\b.{0,60}|.*\bpaper no\.?\s*\d.*|'
                          r'.*(?:\\\\|\.txt\b|\bSeq:|\bSheet No\.).*|'
                          r'[\d\s,.:;()–—-]*\b(?:vol|volume|no|number|issue|pp?|pages)\b\.?[\w\s,.:;()–—-]{0,70})$', re.I)
BANNER = re.compile(r'\b(?:repository|scholarship|scholarly commons|digital commons|faculty (?:works|publications|scholarship))\b|^(?:received|revised|accepted|doi|published online|research article|original article)\b', re.I)
LEAD = re.compile(r'\s*[|,\[—–]\s*|\s+(?=vol(?:ume)?\b|\d)', re.I)


def expanded(text):
    expansion={'l':'law','rev':'review','j':'journal'}
    return [expansion.get(w,w) for w in words(text)]


def initials(text):
    return [w[0] for w in words(text) if w not in JOURNAL_STOP]


def journals_agree(a, b):
    """Word-for-word agreement, also when one side writes an acronym (NYU) and the other its letters."""
    return journal_compatible(a, b) or journal_compatible(a, b, spell=True)


def journal_compatible(a, b, spell=False):
    """Two journal names agree word for word, each word a prefix or contraction of its partner."""
    def parts(text):
        text = unicodedata.normalize('NFKD', text).casefold().replace('’', "'")
        return [t for t in re.findall(r"[a-z0-9]+(?:'[a-z]+)?", text.replace('.', ' ')) if t not in JOURNAL_STOP]
    def same(x, y):
        for short, long in ((x, y), (y, x)):
            if "'" in short:
                head, tail = short.split("'", 1)
                if long.replace("'", '').startswith(head) and long.endswith(tail): return True
            elif long.replace("'", '').startswith(short): return True
            elif len(short) <= 5 and len(long) > len(short) and short[:1] == long[:1] and short[-1:] in long[1:]:
                it = iter(long)                      # a contraction: its letters appear in order (va: virginia)
                if all(c in it for c in short): return True
        return False
    x, y = parts(a), parts(b)
    if spell and len(x) != len(y):
        # Spell out one short all-letter word on the shorter side: nyu -> n, y, u.
        short, long = (x, y) if len(x) < len(y) else (y, x)
        for i, t in enumerate(short):
            if 2 <= len(t) <= 5 and t.isalpha() and len(short) - 1 + len(t) == len(long):
                trial = short[:i] + list(t) + short[i+1:]
                if all(same(p, q) for p, q in zip(trial, long)): return True
        return False
    return bool(x) and len(x) == len(y) and all(same(p, q) for p, q in zip(x, y))


def cited_authors(fields):
    """Each named author as a list of name words; et al. is reported separately."""
    raw = fields.get('authors','') or ''
    et_al = bool(re.search(r'\bet\s+al\b', raw, re.I)) or bool(fields.get('etAl'))
    raw = re.sub(r'\bet\s+al\.?', '', raw, flags=re.I).strip()
    inverted = re.fullmatch(r"([^\W\d_][\w'’-]*),\s*((?:[^\W\d_][\w.'’-]*\s*){1,3})", raw)
    if inverted and words(inverted.group(2))[-1] not in SUFFIXES_OF_NAMES:
        raw = inverted.group(2).strip() + ' ' + inverted.group(1)      # "Vale, Mina"
    return [p for p in map(words, split_people(raw)) if p], et_al


def split_people(text):
    """Split a byline or author string into one string per person."""
    return [p for p in re.split(r'\s*(?:&|\band\b|;|\n|[∗*†‡§]+\s+(?=\S)|,(?!\s*(?:jr|sr|ii|iii|iv)\b))\s*', text, flags=re.I) if p.strip(' ∗*†‡§')]


def last_name(person):
    core = [w for w in person if w not in SUFFIXES_OF_NAMES]
    return core[-1] if core else ''


def person_matches(tokens, person, ocr=False):
    """One written name against one cited name, word by word and in order.

    The surname is the last word on both sides. Every cited word must appear, in
    order; only a cited initial may be left out, and only a non-final word may be
    abbreviated to its initial. The written name may carry up to two extra middle
    words. So 'Mina Cruz' is not 'Mina de la Cruz', and 'Oscar Vale' is not 'Mina Vale'.
    """
    suffix = lambda p: [w for w in p if w in SUFFIXES_OF_NAMES]
    theirs, cited = [w for w in tokens if w not in SUFFIXES_OF_NAMES], [w for w in person if w not in SUFFIXES_OF_NAMES]
    if not theirs or not cited or (suffix(tokens) and suffix(person) and suffix(tokens) != suffix(person)):
        return False
    surname = cited[-1]
    # OCR reads a dagger after a surname as t; allowed only on longer surnames.
    if theirs[-1] != surname and not (ocr and len(surname) >= 5 and theirs[-1] == surname + 't'):
        return False
    theirs, cited = theirs[:-1], cited[:-1]
    if cited and (not theirs or not (theirs[0] == cited[0] or theirs[0] == cited[0][0] or (len(cited[0]) == 1 and theirs[0].startswith(cited[0])))):
        return False
    at = 0; skipped = 0
    for want in cited:
        hit = next((j for j in range(at, len(theirs)) if theirs[j] == want or theirs[j] == want[0] or (len(want) == 1 and theirs[j].startswith(want))), None)
        if hit is None:
            if len(want) == 1: continue          # a cited middle initial the page omits
            return False
        skipped += hit - at; at = hit + 1
    return skipped + (len(theirs) - at) <= 2


def match_people(written, people, et_al=False, ocr=False):
    """Written names, person by person and in order, against the cited authors."""
    segments = [[w for w in words(re.sub(r'\d+', ' ', part)) if not w.isdigit()] for part in split_people(written)]
    segments = [seg[1:] if i == 0 and seg[:1] == ['by'] else seg for i, seg in enumerate(segments)]
    segments = [seg for seg in segments if seg]
    if not people or len(segments) < len(people) or (len(segments) != len(people) and not et_al):
        return False
    if not all(person_matches(seg, person, ocr) for seg, person in zip(segments, people)):
        return False
    return all(2 <= len(seg) <= 5 and all(t.isalpha() for t in seg) and not any(t in ROLE_WORDS for t in seg) for seg in segments[len(people):])


def contains_sequence(haystack, needle):
    n = len(needle)
    return bool(n) and any(haystack[i:i+n] == needle for i in range(len(haystack)-n+1))


def title_matches(title, actual):
    if actual == title:
        return True
    # A footnote call glued to the last word ("Rivers1").
    return bool(title and len(actual) == len(title) and actual[:-1] == title[:-1]
                and not title[-1].isdigit() and re.fullmatch(re.escape(title[-1]) + r'\d{1,2}', actual[-1]))


def title_is_weak(fields):
    """Too short or too common to identify a document without its publication details."""
    title = words(fields.get('title',''))
    return (len(title) <= 1 or ' '.join(title) in COMMON_TITLES or all(w.isdigit() for w in title)
            or all(w in STOP_WORDS for w in title))


def other_script(text):
    """Letters the ASCII word list discards (another script), kept for comparison."""
    raw = unicodedata.normalize('NFKD', text or '')
    return ''.join(c for c in raw if c.isalpha() and not c.isascii() and not unicodedata.combining(c))


def title_loses_script(fields):
    return bool(other_script(fields.get('title','')))


def flat(text):
    """Case and accents folded, punctuation kept: for locating delimited fields in a citation."""
    raw = unicodedata.normalize('NFKD', text or '')
    return re.sub(r'\s+', ' ', ''.join(c for c in raw if not unicodedata.combining(c)).casefold().replace('’', "'"))


def series_suffix(fields):
    """The title proper of a piece cited with a series prefix ('... Term—Foreword: X')."""
    raw = fields.get('title','') or ''
    parts = re.split(r':\s+|\s*[—–]\s*', raw)
    lead = words(' '.join(parts[:-1]))
    if len(parts) < 2 or not (set(lead) & SERIES_WORDS) or set(lead) & {'reply','response','rejoinder','comment','review','erratum','correction'}:
        return []
    tail = words(parts[-1])
    return tail if len(tail) >= 4 else []


def cover_sheet(entry):
    """A database or repository cover page that states the file's own citation.

    Recognised only by the provider's own page furniture at the head of page one:
    a mention of the provider, or a quoted citation label, in ordinary text is not a cover.
    """
    pages = nonblank_pages(entry)
    if not pages:
        return None
    number, page = pages[0]
    page = re.sub(r'(?<=\S)(?=(?:Author\(s\)|Review by|Source|Published by|Stable URL):)', '\n', page)
    lines = [re.sub(r'\s+', ' ', l) for l in lines_of(page)]; kind = None; cite = ''; parts = {}
    old_line = next((i for i,l in enumerate(lines[:6]) if HEIN_OLD_LINE.match(re.sub(r'\s+', ' ', l))), None)
    if any(HEIN_HEAD.match(l) for l in lines[:6]):
        kind = 'hein'
        start = next((i for i,l in enumerate(lines) if re.match(r'Bluebook\b', l, re.I)), None)
        if start is not None:
            block = [re.sub(r'^Bluebook\b.*?\bed\.?\s*', '', lines[start], flags=re.I)]   # a citation on the label line
            for l in lines[start+1:start+9]:
                if STYLE_LABEL.match(l): break
                block.append(l)
            cite = ' '.join(b for b in block if b)
    elif any(re.fullmatch(r'Citation:', l, re.I) for l in lines[:4]) and any(HEIN_OLD_FURNITURE.search(l) for l in lines):
        # The older layout with the full citation on the lines under the label.
        kind = 'hein'; at = next(i for i,l in enumerate(lines[:4]) if re.fullmatch(r'Citation:', l, re.I)); block = []
        for l in lines[at+1:at+6]:
            if re.match(r'(?:Content downloaded|Provided by|--|HeinOnline|\w{3} \w{3} +\d)', l, re.I): break
            block.append(l)
        cite = ' '.join(block).replace(';', ' &')
    elif old_line is not None and any(HEIN_OLD_FURNITURE.search(l) for l in lines):
        # The older layout gives only volume, journal, page and year.
        kind = 'hein_citation_line'; cite = re.sub(r'^Citation:\s*', '', lines[old_line], flags=re.I)
    elif any(re.match(r'Stable URL:', l) for l in lines[:14]) and any(re.match(r'Source:', l) for l in lines[:14]) \
            and any(re.search(r'jstor', l, re.I) for l in lines):
        kind = 'jstor'
        label = re.compile(r'(Author\(s\)|Review by|Reviewed Work\(s\)|Source|Published by|Stable URL):\s*(.{0,400})')
        current = 'title'; parts = {'title': []}
        for l in lines[:14]:
            m = label.match(l)
            if m:
                current = m.group(1); parts.setdefault(current, []).append(m.group(2))
                if current in ('Published by', 'Stable URL'): break
            else:
                parts.setdefault(current, []).append(l)
        parts = {k: ' '.join(v) for k, v in parts.items()}
        cite = parts.get('Source', '')
    elif any(re.fullmatch(r'Recommended Citation:?', l, re.I) for l in lines) and REPOSITORY_FURNITURE.search('\n'.join(lines)):
        at = next(i for i,l in enumerate(lines) if re.fullmatch(r'Recommended Citation:?', l, re.I))
        kind = 'repository'
        cite = re.split(r'\bAvailable at\b', ' '.join(lines[at+1:at+7]), 1, flags=re.I)[0]
    if not kind:
        return None
    return dict(kind=kind, page_in_file=number, text=re.sub(r'\s+', ' ', cite).strip()[:1200], parts=parts)


def content_page(entry):
    pages = nonblank_pages(entry)
    if pages and cover_sheet(entry):
        pages = pages[1:]
    return (pages[0][0], lines_of(pages[0][1])) if pages else (0, [])


def years_agree(cited, stated):
    return bool(cited) and any(abs(int(cited) - int(y)) <= 1 for y in stated if y.isdigit() and cited.isdigit())


def cover_identity(fields, cover):
    """Compare ONE citation on a cover sheet, field by field, with the cited article.

    Returns None when the cover carries no citation that can be read (the caller then
    looks at the page itself). Otherwise the volume, journal, first page and year, the
    title and the authors must all come from the same citation: the title is the
    comma-delimited text directly before the volume, and the authors are everything
    before the title, person by person.
    """
    text = flat(cover['text'])
    vol, first, year = fields.get('volume',''), fields.get('first',''), fields.get('year','')
    if fields.get('pattern') not in ('article', None, '') or not (vol and first and year and text):
        return None
    people, et_al = cited_authors(fields); title = words(fields.get('title',''))
    out = dict(ok=False, entitled=False, same_year=False, stated_years=[], observed_title='', observed_authors='')
    if cover['kind'] == 'jstor':
        parts = cover['parts']; source = flat(parts.get('Source',''))
        tail = bool(re.search(r'\bvol\.?\s*%s\b' % re.escape(vol), source) and re.search(r'\bpp?\.\s*%s\b' % re.escape(first), source))
        out['stated_years'] = re.findall(r'\b(?:1[6-9]|20)\d{2}\b', source[source.find('vol'):] if 'vol' in source else source)
        name = re.sub(r'\([^)]*\)', ' ', source.split(',')[0])
        journal = journals_agree(name, fields.get('journal',''))
        stated = words(parts.get('title','')); publisher = words(parts.get('Published by',''))
        lead = stated[:-len(title)] if title and stated[-len(title):] == title else None
        if lead and 'Review by' in parts and lead[-1] == 'review': lead = lead[:-1]
        def furniture(rest):
            # Whole runs of at least two words from the publisher's or the journal's name, nothing else.
            while rest:
                size = next((n for n in range(len(rest), 1, -1) if contains_sequence(publisher, rest[:n]) or contains_sequence(words(name), rest[:n])), 0)
                if not size: return False
                rest = rest[size:]
            return True
        out['entitled'] = lead is not None and furniture(lead) and not other_script(parts.get('title',''))
        who = parts.get('Review by') if 'Review by' in parts else parts.get('Author(s)', '')
        named = bool(people) and match_people(who or '', people, et_al)
        out['observed_title'] = parts.get('title',''); out['observed_authors'] = who or ''
    else:
        m = re.search(r'(?<![\w.])%s (?P<j>[^\d()]{2,90}?) %s(?!\d)' % (re.escape(vol), re.escape(first)), text)
        if not m:
            # No such volume and page. If the cover holds some other citation, it names another work.
            return out if re.search(r'\b\d+ [^\d()]{2,90}? \d+\b.{0,24}\b(?:1[6-9]|20)\d{2}\b', text) else None
        journal = journals_agree(m.group('j'), fields.get('journal',''))
        rest = text[m.end():]
        if cover['kind'] == 'hein_citation_line':
            y = re.match(r' ((?:1[6-9]|20)\d{2})(?:-(\d{4}))?\s*$', rest)
            out['stated_years'] = [g for g in y.groups() if g] if y else []
            out['same_year'] = year in out['stated_years']
            out['ok'] = journal and out['same_year']       # identity still needs the content page
            return out
        y = re.match(r'(?:\s*,\s*[\d\s,–-]{1,30})?\s*\(([^)]{0,40})\)', rest)   # the year of THIS citation only
        out['stated_years'] = re.findall(r'\b(?:1[6-9]|20)\d{2}\b', y.group(1)) if y else []
        before = text[:m.start()].rstrip(' ,')
        for wanted in (title, series_suffix(fields)):
            if not wanted: continue
            spans = list(re.finditer(r'(?<![a-z0-9])' + r'[^a-z0-9]*'.join(map(re.escape, wanted)) + r'(?![a-z0-9])', before))
            if not spans: continue
            span = spans[-1]
            after = before[span.end():]; lead = before[:span.start()].rstrip(' "“”\'‘')
            # Only punctuation, or one parenthetical subtitle, may follow the title; a comma must precede it.
            if not re.fullmatch(r'[^a-z0-9(]*(?:\([^()]*\))?[^a-z0-9(]*', after) or (lead and not lead.endswith(',')):
                continue
            if other_script(before[span.start():span.end()]):
                continue
            out['entitled'] = True
            out['observed_title'] = before[span.start():span.end()]; out['observed_authors'] = lead.rstrip(' ,')
            break
        named = bool(people) and out['entitled'] and match_people(out['observed_authors'], people, et_al)
        tail = True
    out['same_year'] = year in out['stated_years']
    out['ok'] = bool(tail and journal and named and out['entitled'] and years_agree(year, out['stated_years'])
                     and not title_loses_script(fields))
    return out


def name_line(line, people, et_al):
    """A line that could be part of a byline: name words only, no role or institution words."""
    tokens = [w for w in words(re.sub(r'\d+', ' ', line)) if not w.isdigit()]
    if tokens[:1] == ['by']: tokens = tokens[1:]
    known = {w for p in people for w in p} | {last_name(p) + 't' for p in people}
    if not tokens or len(tokens) > 12 or not all(t.isalpha() for t in tokens) or any(t in ROLE_WORDS for t in tokens):
        return False
    if INSTITUTION.search(line) and not all(t in known for t in tokens):
        return False
    return et_al or any(t in known for t in tokens)


def front_matter(line, fields):
    """Lines a journal or repository prints above a title: never a heading of another work."""
    line = re.sub(r'\s+', ' ', line).strip(); flat_words = ' '.join(words(line)); journal = fields.get('journal','')
    if flat_words in SECTION_LABELS and flat_words not in ('book review','book reviews'):
        return True
    if FRONT_MATTER.match(line) or MARKER.search(line) or (BANNER.search(line) and len(words(line)) <= 16 and not NOT_A_BANNER.search(line)):
        return True
    if journal:
        lead = LEAD.split(line, 1)[0]
        if journal_compatible(lead, journal) or expanded(lead) == expanded(journal):
            return True
    return bool(INSTITUTION_HEAD.search(line) and len(words(line)) <= 14 and not NOT_A_BANNER.search(line))


def other_person_line(line, people):
    """A short line shaped like someone's name that the citation does not list: a co-author or a contents entry."""
    tokens = [w for w in words(re.sub(r'\d+', ' ', line)) if not w.isdigit()]
    known = {w for p in people for w in p}
    if '..' in line or re.match(r'\s*(?:[IVXLC]+|\d+)\.\s', line) or not 2 <= len(tokens) <= 4 or len(tokens[-1]) < 3:
        return False
    if not all(t.isalpha() for t in tokens) or all(t in known for t in tokens):
        return False
    if any(t in ROLE_WORDS or t in HEADING_WORDS or t in STOP_WORDS for t in tokens) or INSTITUTION.search(line):
        return False
    return all(part[:1].isupper() for part in re.findall(r"[^\W\d_]+", line))


def title_on_page(fields, lines):
    """For the citation-line cover: the cited title heading the content page beside its author.

    Exact words with a proper byline, or the same number of words with close OCR spelling
    beside the author's surname. Lines above it must be journal furniture.
    """
    exact = page_identity(fields, 0, lines)
    if exact['strong']:
        return exact['evidence'][0]['title']
    people, _ = cited_authors(fields); head = lines[:25]
    surnames = {last_name(p) for p in people}
    for wanted in (words(fields.get('title','')), series_suffix(fields)):
        if len(wanted) < 4: continue
        for i in range(len(head)):
            for width in range(1, min(5, len(head)-i)+1):
                block = '\n'.join(head[i:i+width]); actual = words(block)
                if len(actual) != len(wanted) or len(set(wanted) & set(actual))/len(set(wanted)) < .8:
                    continue
                near = set(words(' '.join(head[max(0, i-2):i] + head[i+width:i+width+3])))
                if surnames and any(n in near or n + 't' in near for n in surnames) and all(front_matter(x, fields) or name_line(x, people, False) for x in head[:i]) \
                        and not other_script(block):
                    return block
    return ''


def page_publication(fields, lines):
    """What the page itself says about where it was published (for weak titles)."""
    vol, first, journal = fields.get('volume',''), fields.get('first',''), fields.get('journal','')
    seen = dict(journal=False, volume=None, first=False)
    for line in lines[:10] + lines[-3:]:
        line = re.sub(r'\s+', ' ', line).strip(); lead = LEAD.split(line, 1)[0]
        if journal and (journal_compatible(lead, journal) or expanded(lead) == expanded(journal)): seen['journal'] = True
        m = re.search(r'\bvol(?:ume)?\.?\s*(\d+)\b', line, re.I)
        if m: seen['volume'] = m.group(1)
        own = re.fullmatch(r'(\d+) ([^\d()]{2,60}?) (\d+)\s*\((?:[^)\d]*\s)?(?:1[6-9]|20)\d{2}\)\.?', line)
        if own and journal and journal_compatible(own.group(2), journal):
            seen['journal'] = True; seen['volume'] = own.group(1); seen['first'] = seen['first'] or own.group(3) == first
        if re.fullmatch(r'\[?%s\]?' % re.escape(first), line) if first else False: seen['first'] = True
    return seen


def page_identity(fields, number, lines, need_byline=True):
    """The cited title heading its own first page, with an adjacent names-only byline."""
    title = words(fields.get('title','')); people, et_al = cited_authors(fields)
    out = dict(strong=False, plausible=False, evidence=[], reasons=[])
    if not title or not people:
        return out
    for i in range(min(20, len(lines))):
        for width in range(1, min(4, len(lines)-i)+1):
            block = '\n'.join(lines[i:i+width]); actual = words(block)
            if len(set(title) & set(actual))/len(set(title)) >= .7 and len(actual) <= len(title)+4:
                out['plausible'] = True
            if not title_matches(title, actual):
                continue
            if other_script(block) != other_script(fields.get('title','')):
                out['reasons'].append('title differs in a script the matcher cannot compare')
                continue
            under = []
            for line in lines[i+width:i+width+5]:
                if words(line) == ['by'] and not under: continue
                if not name_line(line, people, et_al): break
                under.append(line)
            over = []
            for line in reversed(lines[max(0, i-3):i]):
                if not name_line(line, people, et_al): break
                over.insert(0, line)
            byline, where = None, ''
            for group, side in ((under, 'under'), (over, 'over')):
                for k in range(len(group), 0, -1):
                    part = group[:k] if side == 'under' else group[-k:]
                    if match_people('\n'.join(part), people, et_al, ocr=True):
                        byline, where = part, side; break
                if byline: break
            if not byline:
                out['reasons'].append('title is not at the document head or adjacent author text is not a byline')
                continue
            head = lines[:i - (len(byline) if where == 'over' else 0)]
            skip = 1 if lines[i+width:i+width+1] and words(lines[i+width]) == ['by'] else 0
            tail = lines[i+width+skip+(len(byline) if where == 'under' else 0):][:5]
            if len(head) > 10 or not all(front_matter(s, fields) for s in head):
                out['reasons'].append('title is not at the document head: another heading stands above it')
                continue
            if any(AFTER_BYLINE.search(s) for s in tail) or (not et_al and any(other_person_line(s, people) for s in tail[:3])):
                out['reasons'].append('review, response, comment or contents layout, or an unlisted name after the byline')
                continue
            out['evidence'] = [dict(page_in_file=number, title=block, byline=' '.join(byline), basis='first page')]
            out['strong'] = True
    return out


def identity(fields, entry):
    result = dict(strong=False, plausible=False, evidence=[], reasons=[])
    if not words(fields.get('title','')) or not entry.get('readable'):
        return result
    cover = cover_sheet(entry)
    number, lines = content_page(entry)
    found = cover_identity(fields, cover) if cover and cover['text'] else None
    if found is not None and cover['kind'] == 'hein_citation_line':
        if found['ok']:
            # Volume, journal, page and year name a page, not a work: the title must head the content page.
            seen = title_on_page(fields, lines)
            if seen and not title_loses_script(fields):
                return dict(strong=True, plausible=True, reasons=[], evidence=[dict(
                    page_in_file=number, title=seen, byline='', basis='hein_citation_line cover sheet',
                    cover_citation=cover['text'][:300], cover_years=[])])
            result['plausible'] = True
            result['reasons'].append('cover citation line agrees, but the cited title and author do not head the content page')
            return result
        result['reasons'].append('cover sheet cites a different work'); return result
    if found is not None and found['ok']:
        return dict(strong=True, plausible=True, reasons=[], evidence=[dict(
            page_in_file=cover['page_in_file'], title=found['observed_title'], byline=found['observed_authors'],
            basis=cover['kind'] + ' cover sheet', cover_citation=cover['text'][:300],
            cover_years=[] if found['same_year'] else found['stated_years'])])
    if found is not None and cover['kind'] in ('hein', 'jstor'):
        # The provider says what this file is. A title that also appears inside it
        # cannot make it a different article.
        result['plausible'] = found['entitled']
        result['reasons'].append('cover sheet names this title but its volume, page, year, journal or author differs' if found['entitled']
                                 else 'cover sheet cites a different work')
        return result
    result = page_identity(fields, number, lines)
    if result['strong'] and title_loses_script(fields):
        result['strong'] = False; result['reasons'].append('title uses a script the matcher cannot compare')
    if result['strong'] and fields.get('pattern') in ('article', None, '') and title_is_weak(fields):
        seen = page_publication(fields, lines)
        # Several pieces in one volume can share a stock title: the page must show this one's first page too.
        if not (seen['journal'] and seen['volume'] == fields.get('volume') and seen['first']):
            result['strong'] = False
            result['reasons'].append('short or common title: the page does not show the cited journal, volume and first page')
    if result['strong'] and fields.get('pattern')=='book':
        head='\n'.join(lines[:12])
        observed=editions(head); wanted=fields.get('edition')
        years=re.findall(r'\b(?:1[6-9]|20)\d{2}\b',head)
        if wanted and observed and any(e!=wanted for e in observed):
            result['reasons'].append('copy edition conflicts with cited edition')
        if fields.get('year') and years and fields['year'] not in years:
            result['reasons'].append('copy year conflicts with cited year')
        if result['reasons']:
            result['strong']=False
    return result


NOTICE_START = re.compile(r'(?:this (?:is|article|paper|version|copy)\b.{0,40}?)?(?:an? |the )?(?:draft|uncorrected|version\b|early view|reprinted|advance|electronic copy|preprint|'
                          r'accepted|forthcoming|working paper|author\S* (?:manuscript|version)|post-?print|pre-?print)', re.I)


def version_notices(lines, title_words):
    """Short front-matter statements that this copy is not the published version."""
    found = []
    for i, line in enumerate(lines):
        mine = words(line)
        if not mine or contains_sequence(title_words, mine):      # the work's own title, in any capitalisation
            continue
        joined = line + ' ' + (lines[i+1] if i + 1 < len(lines) else '')
        # A notice starts its own line with a capital; a lower-case start is prose wrapped from the line above.
        if MARKER.search(line) or (len(mine) <= 30 and line[:1].isupper() and NOTICE_START.match(line) and (QUALIFIER.search(line) or QUALIFIER.search(joined))):
            found.append(line)
    return found


def version_evidence(fields, entry):
    pages=entry['firstPages']; number,content=content_page(entry)
    ident=identity(fields,entry); evidence=ident['evidence']
    cover=cover_sheet(entry); cover_page=cover['page_in_file'] if cover else 0
    title_words=words(fields.get('title',''))
    # Version statements are anchored labels in front matter or page margins,
    # not mentions inside prose, bibliographies, titles or footnotes.
    markers=[]; journals=[]; printed=[]; volumes=[]; years=[]
    journal=fields.get('journal',''); jw=expanded(journal)
    def mark(line):
        if line not in markers: markers.append(line)
    for n,page in enumerate(pages,1):
        lines=lines_of(page)
        region=lines if n==cover_page else (lines[:40] if n<=number else lines[:6])+lines[-3:]
        for line in version_notices(region,title_words): mark(line)
        if n==cover_page: continue                      # provider boilerplate carries no page furniture of the article
        for line in lines[:8]+lines[-3:]:
            tokens=expanded(line); flat_line=re.sub(r'\s+',' ',line)
            if jw and tokens==jw:
                journals.append(dict(page_in_file=n,text=line))
            vol=re.match(r'(?:vol(?:ume)?\.?\s*)(\d+)\b',line,re.I) if len(tokens)<=9 else None
            if vol:
                volumes.append((n,vol.group(1))); years.extend((n,y) for y in re.findall(r'\b(?:1[6-9]|20)\d{2}\b',line))
                if QUALIFIER.search(line): mark(line)
            # A running head or foot that gives the article's own citation is a
            # publication label, never a page label: the page must also carry its number.
            own=re.fullmatch(r'(\d+) ([^\d()]{2,60}?) (\d+)\s*\((?:[^)\d]*\s)?((?:1[6-9]|20)\d{2})\)\.?',flat_line)
            if own and journal and journal_compatible(own.group(2),journal):
                journals.append(dict(page_in_file=n,text=line)); volumes.append((n,own.group(1))); years.append((n,own.group(4)))
            # Date labels must be front matter, not years buried in citations.
            if re.fullmatch(r'(?:Volume\s+\d+\s*\(|Copyright\s*(?:©\s*)?|©\s*|Published\s+)?(?:1[6-9]|20)\d{2}\)?',line,re.I):
                years.extend((n,y) for y in re.findall(r'\b(?:1[6-9]|20)\d{2}\b',line))
            label=re.fullmatch(r'\[?(\d{1,5})\]?',line)
            if label and not re.fullmatch(r'(?:19|20)\d{2}',label.group(1)):
                printed.append(dict(page_in_file=n,printed_page=int(label.group(1)),text=line))
    observed_editions=editions('\n'.join(content[:12]))
    # Publication details must cohere on the article's own first page: a volume on one
    # page and a page number on another prove nothing together.
    here=lambda pairs:[v for n,v in pairs if n==number]
    vols_here=here(volumes); years_here=here(years)
    article=bool(any(j['page_in_file']==number for j in journals) and fields.get('volume') in vols_here
                 and all(v==fields.get('volume') for v in vols_here) and fields.get('year') in years_here
                 and any(p['page_in_file']==number and str(p['printed_page'])==fields.get('first') for p in printed))
    volumes=[v for _,v in volumes]; years=[y for _,y in years]
    # A book needs an actual publication imprint, a matching date/edition and labels.
    imprint=any(re.match(r'^(?:Published by\s+.+|.+\b(?:University Press|Publishing|Publishers))$',s,re.I) for s in content[:12])
    book=bool(fields.get('pattern')=='book' and imprint and fields.get('year') in years
              and (not fields.get('edition') or observed_editions==[fields['edition']])
              and ident['strong'])
    by_cover=bool(evidence and str(evidence[0].get('basis','')).startswith(('hein','jstor')))
    if evidence: years.extend(evidence[0].get('cover_years',[]))
    # A database scan is the published volume unless its own pages number differently:
    # consecutive page labels on consecutive pages. One compatible run and one that is
    # not leaves the pagination unsettled.
    first=int(fields['first']) if str(fields.get('first','')).isdigit() else None
    by_page={}
    for p in printed: by_page.setdefault(p['page_in_file'],set()).add(p['printed_page'])
    runs=[a-(k-number) for k in sorted(by_page) for a in by_page[k] if a+1 in by_page.get(k+1,())]   # each run, as the label it implies for the first page
    conflicting=bool(by_cover and first is not None and any(r!=first for r in runs))
    published=bool(not markers and ((by_cover and not conflicting and content) or (printed and (article or book))))
    kind='working_paper' if markers else 'published' if published else 'unknown'
    note=('Working-paper/forthcoming/manuscript marker: '+'; '.join(markers[:3]) if markers else
          'Database cover sheet states this citation; its page images are the published pages.' if published and by_cover else
          'Publication imprint and printed pages present; publication details agree.' if published else
          'Database cover sheet states this citation, but the page labels in this copy run differently.' if conflicting else
          'Published version not established from the first pages.')
    if journals: note+=' Journal heading: '+'; '.join(dict.fromkeys(j['text'] for j in journals))+'.'
    if volumes: note+=' Volume labels: '+', '.join(dict.fromkeys(volumes))+'.'
    if years: note+=' First-page date labels: '+', '.join(dict.fromkeys(years))+'.'
    if observed_editions: note+=' Edition labels: '+', '.join(observed_editions)+'.'
    note+=(' Printed page labels: '+', '.join(dict.fromkeys(str(p['printed_page']) for p in printed))+'.') if printed else ' No printed page labels established.'
    return dict(kind=kind,note=note,markers=markers,journalHeadings=journals,printedPages=printed,
                observedVolumes=list(dict.fromkeys(volumes)),observedYears=list(dict.fromkeys(years)),observedEditions=observed_editions,
                pinciteEligible=published,pinciteReason='Inspect the cited printed page and calibrate its mapping; never use file-page numbers as published pins.' if published else
                'Pincite not judged: cited-version printed pagination is not established in this copy.')


def match(fields, entries):
    candidates=[]; seen={}
    for entry in entries:
        result=identity(fields,entry)
        if not (result['plausible'] or result['strong']): continue
        sha=entry.get('fileSha256')
        if sha and sha in seen:
            seen[sha].setdefault('duplicateNames',[]).append(entry['fileName'])
            continue
        candidate=dict(entry,identity=result,version=version_evidence(fields,entry))
        candidates.append(candidate)
        if sha: seen[sha]=candidate
    strong=[e for e in candidates if e['identity']['strong']]
    published=[e for e in strong if e['version']['kind']=='published']
    chosen=published[0] if len(published)==1 else strong[0] if len(candidates)==len(strong)==1 else None
    return chosen,candidates


def extract_chosen(chosen, cache):
    if not chosen: return None
    print('Local sources: extracting selected copy: '+chosen['fileName'],file=sys.stderr)
    full=index_file(chosen['filePath'],cache,full=True)
    if not full['readable']:
        chosen.update(readable=False,reason=full['reason'])
        return None
    if full['fileSha256']!=chosen['fileSha256']:
        chosen.update(readable=False,reason='source changed after identity preview')
        return None
    return {**chosen,**full}


def public_candidate(entry):
    return {k:entry[k] for k in ('fileName','relativePath','duplicateNames','identity','reason') if k in entry}
