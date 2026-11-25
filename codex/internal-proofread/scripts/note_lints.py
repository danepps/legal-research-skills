"""Local citation checks for each note series; no external verification or typeface claims."""
import re

CAPTION = re.compile(r"\b([A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)*\s+v\.\s+[A-Z][\w'’.-]*(?:\s+[A-Z][\w'’.-]*)*),\s+(\d{1,4})\s+([A-Z][A-Za-z. ]+?)\s+(\d{1,5})")
PIN = re.compile(r"\b(\d{1,4})\s+((?:[A-Z][\w.'’&]*\.?\s+){1,6}?)(\d{2,5}),\s+(\d{1,5})\b")
US_YEAR = re.compile(r'\b(\d{3})\s+U\.\s?S\.\s+(?:__|\d{1,4})(?:,\s+(?:__|\d{1,4})(?:[–—-]\d{1,4})?)?\s*\((1[89]\d\d|20[0-3]\d)\)')
ANCHORS = [(100,1879),(200,1906),(300,1937),(400,1971),(500,1991),(550,2007),(600,2023),(620,2030)]
SUPRA_NAME = re.compile(r"([A-Z][A-Za-z'’\-]{2,}(?:\s+&\s+[A-Z][A-Za-z'’\-]{2,}|\s+[A-Z][A-Za-z'’\-]{2,}){0,2}),?\s+supra\s+notes?\s+(\d+|[ivxlcdmIVXLCDM]+)\b")
SIGNALS = {'see', 'cf', 'but', 'accord', 'compare', 'contra', 'also', 'and', 'id', 'in', 'of', 'generally'}


def surname(text):
    return re.sub('[^a-z]', '', text.lower())


def local(text):
    """Yield (rule, start, end, message, suggestion) in the caller's coordinates."""
    for match in PIN.finditer(text):
        reporter, first, pin = match[2], int(match[3]), int(match[4])
        if '.' in reporter and 0 < pin < first:
            yield ('citation.pincite_arithmetic', match.start(), match.end(),
                   'The pincite precedes the citation\'s first page.', 'Check the pincite against the source.')
    for match in US_YEAR.finditer(text):
        vol, year = int(match[1]), int(match[2])
        expected = next((y1+(vol-v1)*(y2-y1)/(v2-v1) for (v1,y1),(v2,y2) in zip(ANCHORS,ANCHORS[1:]) if v1<=vol<=v2), None)
        if expected is not None and abs(year-expected)>3:
            yield ('citation.us_volume_year', match.start(), match.end(),
                   'The U.S. Reports volume and year appear inconsistent.', 'Check the volume and decision year against the reporter.')
    for match in CAPTION.finditer(text):
        tail = text[match.end():match.end()+120].split(';')[0]
        if not re.search(r'\([^)]*\b(?:1[6-9]\d\d|20[0-3]\d)\b[^)]*\)', tail) and not any(x in tail for x in ('__','slip op','_ ')):
            yield ('citation.missing_year', match.start(), match.end(),
                   'The full case citation has no decision year in its parentheticals.', 'Verify and add the decision year.')


def supra(text, lookup):
    for match in SUPRA_NAME.finditer(text):
        candidates = lookup.get(match[2].casefold(), [])
        if len(candidates) != 1:
            continue
        tokens = match[1].split('&')[0].split()
        while tokens and surname(tokens[0]) in SIGNALS:
            tokens.pop(0)
        key = surname(tokens[0]) if tokens else ''
        if len(key) < 4:
            continue
        target = candidates[0]['text']
        rule = ('xref.supra_target_name' if key not in surname(target) else
                'xref.supra_name_spelling' if key not in {surname(w) for w in target.split()} else None)
        if rule:
            yield (rule, match.start(), match.end(),
                   'The author name is absent or spelled differently in the target note of this series.',
                   'Check the name and note target within this series.')
