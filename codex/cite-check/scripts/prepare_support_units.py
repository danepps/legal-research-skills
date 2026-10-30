#!/usr/bin/env python3
"""Build support-units.jsonl after lead-confirmed citation segmentation.

Run: prepare_support_units.py RUN_DIR [--refresh-counts]
Existing unread decisions are preserved by unit ID. All other fields are rebuilt
from extraction and citation units; stale/omitted support rows cannot pass gates.
"""
import argparse
import json
import re
from pathlib import Path
from extract_cites import note_key, footnote_anchors, FN_MARKER
from support_screen import kind_of, screen_clause, split_clauses, prose_clauses


def read_rows(path):
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]


def eligible(unit, quoted):
    return (unit.get('unit_id') not in quoted and not unit.get('prepared_unit_ids')
            and not re.match(r'^\s*\(?\s*(?:quoting|citing)\b', unit.get('draft_citation_text', ''), re.I)
            and not unit.get('nested') and unit.get('unit_kind') not in {'internal_reference', 'prose', 'nested_citation'}
            and unit.get('xref_status') != 'unresolved'
            and not (kind_of(unit.get('draft_citation_text', '')) in {'id', 'supra'}
                     and unit.get('xref_status') != 'resolved'))


def location_key(unit):
    if unit.get('location') == 'body':
        return ('body', unit.get('paragraph_number'))
    return ('footnote', note_key(unit))


def claim_bases(row):
    """Complete deterministic claim fields; never accept an arbitrary substring."""
    anchor = row.get('anchor') or {}
    bases = {'anchor.sentence': [anchor.get('sentence', '')],
             'anchor.clause': [anchor.get('clause', '')],
             'parenthetical': [row.get('parenthetical', '')],
             'note_prose': row.get('note_prose', [])}
    if row.get('body_citation_sentence'):
        bases['anchor.previous'] = [anchor.get('previous', '')]
    return bases


def build_support_units(extraction, units, quote_checks=(), scope='pincited'):
    quoted = {q.get('unit_id') for q in quote_checks if q.get('prepared_unit_id')}
    by_id = {u['unit_id']: u for u in units}
    notes = {note_key(n): n for n in extraction.get('footnotes', [])}
    def pin_for(unit):
        if unit.get('pincite'): return unit['pincite'], 'own'
        seen = set()
        current = unit
        while kind_of(current.get('draft_citation_text', '')) == 'id':
            target = current.get('antecedent_unit_id')
            if not target or target in seen or target not in by_id: break
            seen.add(target)
            current = by_id[target]
            if current.get('pincite'): return current['pincite'], 'inherited'
        return '', ''
    rows = []
    for u in units:
        if not eligible(u, quoted): continue
        home = notes.get(note_key(u), {})
        text = u.get('draft_citation_text', '')
        pin, basis = pin_for(u)
        screening = screen_clause(text, u.get('source_type'))
        parenthetical = u.get('parenthetical', screening['parenthetical'])
        kind = u.get('source_type')
        located = bool(pin or parenthetical or kind in {'statute', 'rule'}
                       or kind in {'internet', 'url', 'web', 'website'} or 'http' in text)
        anchor = home.get('anchor')
        citation_sentence = False
        if u.get('location') == 'body':
            paragraph_number = u.get('paragraph_number')
            paragraphs = extraction.get('paragraphs', [])
            if isinstance(paragraph_number, int) and 1 <= paragraph_number <= len(paragraphs):
                context = paragraphs[paragraph_number - 1]
                offset = context.find(text)
                if text and offset >= 0:
                    marked = context[:offset] + '[[FN:support]]' + context[offset:]
                    context_paragraphs = paragraphs[:paragraph_number - 1] + [marked]
                    anchor = footnote_anchors(context_paragraphs).get('support')
                    if anchor:
                        remaining = anchor['sentence']
                        for sibling in units:
                            if location_key(sibling) == location_key(u):
                                cite = sibling.get('draft_citation_text', '')
                                if cite: remaining = remaining.replace(cite, '')
                        remaining = FN_MARKER.sub('', remaining)
                        remaining = re.sub(r'\b(?:see|also|generally|cf|but|compare|with|accord|contra)\b', '', remaining, flags=re.I)
                        citation_sentence = not re.search(r'\w', remaining)
                        if citation_sentence:
                            anchor = dict(anchor, position='citation-sentence', clause='')
        row = {k: u.get(k) for k in ('unit_id', 'source_id', 'footnote_number', 'note_id', 'paragraph_number',
                                    'draft_citation_text', 'resolved_source_label')}
        row.update(support_unit_id='SUP-' + u['unit_id'], signal=u.get('signal', screening['signal']),
                   pincite=pin, pincite_basis=basis, parenthetical=parenthetical,
                   opinion_note=u.get('opinion_note', screening['opinion_note']),
                   scope='pincited' if located else 'whole-work', anchor=anchor,
                   full_footnote=home.get('text', u.get('body_context', '')),
                   note_prose=prose_clauses(home.get('text', '')),
                   siblings=sum(1 for sibling in units if location_key(sibling) == location_key(u)
                                and sibling.get('unit_kind') not in {'internal_reference', 'prose', 'nested_citation'}
                                and not sibling.get('nested')))
        if u.get('location') == 'body': row['body_citation_sentence'] = citation_sentence
        if not located and scope != 'all': row['unread_reason'] = 'out_of_scope'
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_dir', type=Path)
    parser.add_argument('--refresh-counts', action='store_true')
    args = parser.parse_args()
    run = args.run_dir
    manifest = json.loads((run / 'run-manifest.json').read_text())
    if manifest.get('support_pass', {}).get('enabled') is not True:
        parser.error('support pass was not enabled at initialization')
    path = run / 'support-units.jsonl'
    existing = {u['unit_id']: u for u in read_rows(path)} if path.exists() else {}
    rows = build_support_units(json.loads((run/'extraction.json').read_text()),
                               read_rows(run/'citation-units.jsonl'), read_rows(run/'quote-checks.jsonl'),
                               manifest['support_pass']['scope'])
    for row in rows:
        old = existing.get(row['unit_id'], {})
        if row.get('unread_reason') != 'out_of_scope' and old.get('unread_reason') in {'budget', 'agent_failure'}:
            row['unread_reason'] = old['unread_reason']
    path.write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows), encoding='utf-8')
    if args.refresh_counts:
        from support_validation import support_counts, support_sentence
        counts = support_counts(rows, read_rows(run/'verdicts.jsonl'), read_rows(run/'verifier-audit.jsonl'))
        manifest.setdefault('counts', {})['support'] = counts
        (run/'run-manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
        print(support_sentence(counts))
    else:
        print(json.dumps({'units_total': len(rows), 'out_of_scope': sum(r.get('unread_reason') == 'out_of_scope' for r in rows)}))


if __name__ == '__main__':
    main()
