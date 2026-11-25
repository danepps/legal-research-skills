"""Opt-in exact corrections; prose suggestions are never executable edits."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import re

from common import read_jsonl, validate_finding_location


SECTION = '\n## Optional exact corrections (enabled runs only)\n'
BOUND_FIELDS = ('suggestion', 'excerpt', 'location', 'severity')
FLAGS = ('quoted_material', 'requires_author_judgment', 'excerpt_only')
REPLACEMENT_KEYS = {'replacement', 'revised_replacement', 'replacement_basis'}


def finding_schema(enabled: bool) -> str:
    text = (Path(__file__).resolve().parent.parent / 'references/finding-schema.md').read_text(encoding='utf-8')
    return text if enabled else text.split(SECTION, 1)[0]


def instructions(enabled: bool) -> str:
    if not enabled:
        return ''
    return '\n' + SECTION + finding_schema(True).split(SECTION, 1)[1]


def without_replacements(value):
    """Ignore unsolicited fields everywhere, including nested audit outcomes."""
    if isinstance(value, dict):
        return {key: without_replacements(item) for key, item in value.items() if key not in REPLACEMENT_KEYS}
    if isinstance(value, list):
        return [without_replacements(item) for item in value]
    return value


def basis(row: dict) -> dict:
    return deepcopy({key: row.get(key) for key in BOUND_FIELDS})


def allowed(row: dict, blocks: dict | None = None) -> bool:
    location = row.get('location')
    block = (blocks or {}).get(location.get('block_id'), {}) if isinstance(location, dict) else {}
    return not (
        row.get('category') in {'formatting', 'typeface', 'quote', 'quotation', 'quote-integrity'}
        or row.get('status') in {'rejected', 'waived', 'query', 'style', 'prepublication'}
        or row.get('severity') == 'query'
        or row.get('quoted_material')
        or row.get('requires_author_judgment')
        or row.get('excerpt_only') is False
        or block.get('kind') in {'quote', 'blockquote'}
    )


def validate_replacement(row: dict, blocks: dict | None = None) -> None:
    if 'replacement' not in row:
        return
    if not isinstance(row['replacement'], str):
        raise ValueError('replacement must be a string')
    if any(re.search(r'\[EN#[^\]\r\n]+\]', str(row.get(key, ''))) for key in ('excerpt', 'replacement')):
        raise ValueError('replacement cannot include or alter a synthetic endnote marker')
    if 'replacement_basis' in row and not isinstance(row['replacement_basis'], dict):
        raise ValueError('replacement_basis must be an object')
    if not allowed(row, blocks):
        raise ValueError('replacement is not allowed for this finding type or disposition')
    if blocks is not None:
        validate_finding_location(row, blocks)
        location = row['location']
        text = blocks[location['block_id']]['text']
        if row.get('excerpt') != text[location['char_start']:location['char_end']]:
            raise ValueError('replacement requires an exact excerpt matching its character range')


def clear(row: dict) -> dict:
    row.pop('replacement', None)
    row.pop('replacement_basis', None)
    return row


def withdraw(row: dict) -> dict:
    """Retain the old basis so another merge cannot revive an obsolete edit."""
    row.pop('replacement', None)
    return row


def bind(row: dict, enabled: bool, blocks: dict | None = None) -> dict:
    """Keep exact bytes; drop no-ops and corrections with an obsolete basis."""
    row = deepcopy(row) if enabled else without_replacements(row)
    if 'replacement' not in row:
        return row
    validate_replacement(row, blocks)
    value = row['replacement']
    old = row.get('replacement_basis')
    current = dict(basis(row), value=value)
    if value == '' or value == row.get('excerpt'):
        return clear(row)
    if old is not None and old != current and old.get('value') == value:
        return withdraw(row)
    row['replacement_basis'] = current
    return row


def effective_finding(finding: dict, disposition: dict) -> dict:
    row = deepcopy(finding)
    for key in (*BOUND_FIELDS, 'category', *FLAGS, 'status'):
        if key in disposition:
            # Match the existing report's fallback for empty suggestions.
            if key == 'suggestion' and not disposition[key]:
                continue
            row[key] = deepcopy(disposition[key])
    return row


def audit_update(audit: dict) -> dict:
    if audit.get('audit_status') == 'revised':
        final = audit.get('final_disposition')
        return final if isinstance(final, dict) else {}
    if audit.get('rejection_status') in {'reopen', 'revised'}:
        update = {key.removeprefix('revised_'): audit[key] for key in
                  ('revised_suggestion', 'revised_excerpt', 'revised_location', 'revised_severity', 'revised_replacement')
                  if key in audit}
        return update
    return {}


def check_audit(audit: dict, finding: dict, blocks: dict) -> None:
    """Validate audit corrections against the proposed finding, before filtering."""
    if 'revised_replacement' in audit:
        if audit.get('rejection_status') not in {'reopen', 'revised'}:
            raise ValueError('revised_replacement requires a reopened or revised rejection audit')
        update = audit_update(audit)
        if audit['revised_replacement'] != '':
            validate_replacement(effective_finding(dict(finding, status='candidate'), update) | {
                'replacement': audit['revised_replacement']}, blocks)
    if 'replacement' in audit:
        validate_replacement(dict(finding, replacement=audit['replacement']), blocks)
        raise ValueError('audit correction belongs in revised_replacement or final_disposition')
    final = audit.get('final_disposition')
    if isinstance(final, dict) and 'replacement' in final:
        validate_replacement(effective_finding(finding, final) | {'replacement': final['replacement']}, blocks)
        if audit.get('audit_status') != 'revised':
            raise ValueError('a final_disposition replacement requires a revised verifier audit')


def bind_audit(audit: dict, finding: dict, blocks: dict) -> dict:
    audit = deepcopy(audit)
    check_audit(audit, finding, blocks)
    update = audit_update(audit)
    if 'replacement' in update:
        if update['replacement'] == '':
            container = audit['final_disposition'] if audit.get('audit_status') == 'revised' else audit
            container.pop('replacement_basis', None)
            return audit
        proposed = clear(effective_finding(dict(finding, status='candidate'), update))
        proposed['replacement'] = update['replacement']
        container = audit['final_disposition'] if audit.get('audit_status') == 'revised' else audit
        if 'replacement_basis' in container:
            proposed['replacement_basis'] = container['replacement_basis']
        bound = bind(proposed, True, blocks)
        key = 'replacement' if audit.get('audit_status') == 'revised' else 'revised_replacement'
        container[key] = bound.get('replacement', '')
        if 'replacement_basis' in bound:
            container['replacement_basis'] = bound['replacement_basis']
        else:
            container.pop('replacement_basis', None)
    return audit


def resolve(finding: dict, disposition: dict, audits: list[dict], blocks: dict) -> tuple[dict, dict]:
    """Resolve the final correction without replacing the original diagnosis."""
    effective = effective_finding(finding, disposition)
    candidate = bind(finding, True, blocks)
    if 'replacement' in disposition:
        candidate = bind(dict(clear(deepcopy(effective)), **{key: disposition[key] for key in
                         ('replacement', 'replacement_basis') if key in disposition}), True, blocks)
    elif basis(candidate) != basis(effective):
        clear(candidate)

    for audit in audits:
        check_audit(audit, finding, blocks)
        update = audit_update(audit)
        if audit.get('audit_status') == 'retracted' or audit.get('rejection_status') == 'confirmed_rejection':
            clear(candidate)
        elif update:
            if any(key in update and update[key] != effective.get(key) for key in BOUND_FIELDS):
                clear(candidate)  # The lead has not reconciled the audit yet.
            elif 'replacement' in update:
                clear(candidate)
                if allowed(effective, blocks):
                    supplied = dict(clear(deepcopy(effective)), replacement=update['replacement'])
                    container = audit.get('final_disposition', {}) if audit.get('audit_status') == 'revised' else audit
                    if 'replacement_basis' in container:
                        supplied['replacement_basis'] = container['replacement_basis']
                    candidate = bind(supplied, True, blocks)
            elif any(key in update and update[key] != finding.get(key) for key in BOUND_FIELDS):
                clear(candidate)

    if not allowed(effective, blocks):
        clear(candidate)
    final = withdraw(deepcopy(disposition))
    ledger = withdraw(deepcopy(finding))
    if 'replacement' in candidate:
        for key in ('replacement', 'replacement_basis'):
            final[key] = deepcopy(candidate[key])
        if basis(finding) == basis(effective):
            for key in ('replacement', 'replacement_basis'):
                ledger[key] = deepcopy(candidate[key])
    return ledger, final


def resolve_records(run_dir: Path, findings: list[dict], dispositions: list[dict], enabled: bool, blocks: dict):
    if not enabled:
        return without_replacements(findings), without_replacements(dispositions)
    audits = read_jsonl(run_dir / 'rejection-audit.jsonl') + read_jsonl(run_dir / 'verifier-audit.jsonl')
    by_id = {row.get('finding_id'): row for row in dispositions}
    final_by_id = {}
    ledger = []
    for finding in findings:
        finding_id = finding.get('finding_id')
        row, final = resolve(finding, by_id.get(finding_id, {}),
                             [audit for audit in audits if audit.get('finding_id') == finding_id], blocks)
        ledger.append(row)
        final_by_id[finding_id] = final
    return ledger, [final_by_id.get(row.get('finding_id'), row) for row in dispositions]


def validate_records(run_dir: Path, findings: list[dict], dispositions: list[dict], blocks: dict) -> list[str]:
    """Check raw inputs too: a merge must not hide a malformed duplicate."""
    from common import read_json
    errors = []
    indexed = {row.get('finding_id'): row for row in findings}

    def check(row, label):
        try:
            validate_replacement(row, blocks)
        except (ValueError, TypeError, KeyError) as exc:
            errors.append(f'{label}: {exc}')

    for name in ('static-findings.jsonl', 'challenger-findings.jsonl', 'findings.jsonl'):
        for row in read_jsonl(run_dir / name):
            check(row, name)
    for directory in ('agent-results', 'lane-results', 'recall-results'):
        for path in sorted((run_dir / directory).glob('*.json')):
            try:
                result = read_json(path)
                rows = result.get('findings', [])
                if isinstance(rows, list):
                    for row in rows:
                        if isinstance(row, dict):
                            check(row, path.name)
            except (OSError, ValueError) as exc:
                errors.append(f'{path.name}: {exc}')
    for disposition in dispositions:
        row = effective_finding(indexed.get(disposition.get('finding_id'), {}), disposition)
        clear(row)
        if 'replacement' in disposition:
            row['replacement'] = disposition['replacement']
            check(row, 'dispositions.jsonl')
    paths = [run_dir / 'verifier-audit.jsonl', run_dir / 'rejection-audit.jsonl']
    paths += sorted((run_dir / 'rejection-results').glob('*.jsonl'))
    for path in paths:
        try:
            for audit in read_jsonl(path):
                check_audit(audit, indexed.get(audit.get('finding_id'), {}), blocks)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            errors.append(f'{path.name}: {exc}')
    return errors
