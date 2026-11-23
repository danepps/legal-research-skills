"""Offline reconciliation of draft-grounded case screens and their resolutions."""
from check_cite import compare_identity


def present(value):
    return isinstance(value, str) and bool(value.strip())


def opened_record(record):
    return (isinstance(record, dict) and record.get('evidence_opened') is True
            and all(present(record.get(k)) for k in ('evidence_location', 'evidence', 'reason')))


def disclosure(row, dimension, disposition):
    comparison = row['identity_comparison'][dimension]
    line = (f"Case identity {row['unit_id']} {dimension}: draft={comparison['draft']}; "
            f"lookup={comparison['resolved']}; resolution={disposition}.")
    if dimension == 'caption' and disposition == 'finding':
        line += ' Either the name or the reporter citation may be wrong.'
    return line


def validate_identity(manifest, units, verdicts, rows, corpus, report, errors):
    cases = {u.get('unit_id'): u for u in units
             if u.get('source_type') == 'case' and u.get('unit_kind') != 'internal_reference'}
    by_unit = {v.get('unit_id'): v for v in verdicts}
    ids = [r.get('unit_id') for r in rows]
    if len(ids) != len(set(ids)):
        errors.append('case identity: duplicate unit_id in screen ledger')
    if manifest.get('case_identity_version') == 1 and set(ids) != set(cases):
        errors.append('case identity: requires exactly one screen row per case citation unit')
    for row in rows:
        uid = row.get('unit_id')
        unit = cases.get(uid)
        if unit is None or row.get('source_id') != unit.get('source_id'):
            errors.append(f'case identity {uid}: unknown or unrelated case unit/source')
            continue
        verdict = by_unit.get(uid, {})
        # Explicit absence is permitted for unavailable API access/short forms.
        # Direct verification still needs an opened identity record, or the
        # ordinary partial/unverified + unlock-path rules apply.
        if row.get('lookup_state') == 'not_screened':
            if not all(present(row.get(k)) for k in ('reason', 'unlock_path')):
                errors.append(f'case identity {uid}: not_screened needs reason and unlock_path')
            if verdict.get('status') == 'verified' and not opened_record(verdict.get('identity_evidence')):
                errors.append(f'case identity {uid}: unscreened verification needs opened identity_evidence')
            line = f"Case identity {uid}: not_screened; {row.get('reason')}; {row.get('unlock_path')}"
            if line not in report:
                errors.append(f'case identity {uid}: report omits unscreened disclosure')
            continue
        if row.get('lookup_state') not in {'matched', 'ambiguous', 'not_found_in_index', 'rate_limited', 'unresolved'}:
            errors.append(f'case identity {uid}: invalid lookup_state')
            continue
        if not present(unit.get('lookup_citation')) or row.get('lookup_citation') != unit.get('lookup_citation'):
            errors.append(f'case identity {uid}: lookup_citation differs from unit')
        if 'draft_case_name' not in unit or 'draft_year' not in unit:
            errors.append(f'case identity {uid}: unit needs explicit draft_case_name and draft_year')
        name, year = unit.get('draft_case_name'), unit.get('draft_year')
        caption_location = unit.get('caption_in_draft')
        context = unit.get('body_context') if caption_location == 'body' else unit.get('full_footnote')
        if caption_location == 'none':
            if name not in (None, ''):
                errors.append(f'case identity {uid}: nameless cite must not supply a caption')
        elif not present(name) or name not in str(context or '') or name not in corpus:
            errors.append(f'case identity {uid}: caption must occur in its declared draft context')
        if year not in (None, '') and str(year) not in str(unit.get('draft_citation_text', '')):
            errors.append(f'case identity {uid}: year must occur in draft_citation_text')
        try:
            expected = compare_identity(name, year, row.get('case_name'), row.get('date_filed'),
                                        matched=row.get('lookup_state') == 'matched')
        except ValueError as exc:
            errors.append(f'case identity {uid}: {exc}')
            continue
        if row.get('identity_comparison') != expected:
            errors.append(f'case identity {uid}: missing, stale or altered identity_comparison')
        resolutions = verdict.get('identity_resolutions', {})
        if not isinstance(resolutions, dict):
            errors.append(f'case identity {uid}: identity_resolutions must be an object')
            resolutions = {}
        for dimension, comparison in expected.items():
            if comparison['result'] != 'mismatch':
                if dimension in resolutions:
                    errors.append(f'case identity {uid}: stale {dimension} resolution without mismatch')
                continue
            resolution = resolutions.get(dimension)
            if not opened_record(resolution):
                errors.append(f'case identity {uid}: unresolved {dimension} mismatch; needs opened evidence and reason')
                continue
            disposition = resolution.get('disposition')
            if disposition == 'finding':
                category = 'identity_error' if dimension == 'caption' else 'metadata_error'
                if (resolution.get('category') != category
                        or verdict.get('category') not in {'identity_error', 'metadata_error'}
                        or verdict.get('status') not in {'mismatch', 'partial', 'unverified'}):
                    errors.append(f'case identity {uid}: {dimension} finding needs an adverse {category} verdict/resolution')
                if dimension == 'caption' and verdict.get('identity_confirmed') is True:
                    errors.append(f'case identity {uid}: caption error cannot confirm draft identity')
            elif disposition != 'not_error':
                errors.append(f'case identity {uid}: invalid {dimension} resolution disposition')
                continue
            # Derive disclosure from the inputs, even if a stored result was edited.
            line = disclosure(dict(row, identity_comparison=expected), dimension, disposition)
            if line not in report:
                errors.append(f'case identity {uid}: report omits {dimension} mismatch resolution: {line}')
            if disposition == 'not_error' and resolution['reason'] not in report:
                errors.append(f'case identity {uid}: report omits reason for dismissing {dimension} mismatch')
