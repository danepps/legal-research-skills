"""Schema-v7 support gates. Structural evidence checks, never semantic guarantees."""
import json
import re
from prepare_support_units import build_support_units
from support_screen import kind_of

DISPOSITIONS = {
    'supported': ('verified', 'verified_support', 'info'),
    'supported_qualified': ('verified', 'support_qualified', 'info'),
    'overstated': ('partial', 'support_overstated', 'low'),
    'not_supported': ('mismatch', 'support_mismatch', 'medium'),
    'contradicted': ('mismatch', 'support_contradicted', 'high'),
}
COUNT_VERDICTS = dict(zip(DISPOSITIONS, ('supported', 'qualified', 'overstated', 'not_supported', 'contradicted')))
ARTIFACTS = ('paraphrased claim', 'signal misread', 'clause vs sentence',
             'wrong antecedent / wrong page', 'nearby passage', 'posture')
FULL_TEXT = {'primary_full_text', 'authoritative_reproduction', 'repository_full_text', 'local_library_full_text'}
SIGNALS = {'', 'see', 'see, e.g.', 'see also', 'see generally', 'cf.', 'but see', 'but cf.', 'compare', 'accord', 'contra', 'e.g.'}


def support_counts(rows, verdicts, audits):
    counts = dict.fromkeys(('units_total', 'in_scope', 'out_of_scope', 'read', 'supported', 'qualified',
                          'overstated', 'not_supported', 'contradicted', 'unverifiable', 'unread_budget',
                          'unread_failure', 'audits_retracted'), 0)
    by_unit = {v.get('unit_id'): v for v in verdicts}
    support_ids = {u['unit_id'] for u in rows}
    for row in rows:
        counts['units_total'] += 1
        reason = row.get('unread_reason')
        counts['out_of_scope' if reason == 'out_of_scope' else 'in_scope'] += 1
        if reason:
            if reason == 'budget': counts['unread_budget'] += 1
            if reason == 'agent_failure': counts['unread_failure'] += 1
            continue
        verdict = by_unit.get(row['unit_id'], {})
        support = verdict.get('support', {})
        result = support.get('verdict') if isinstance(support, dict) else None
        if verdict.get('support_read') is True: counts['read'] += 1
        if result in COUNT_VERDICTS: counts[COUNT_VERDICTS[result]] += 1
        if result == 'unverifiable': counts['unverifiable'] += 1
    verdict_ids = {v.get('verdict_id') for v in verdicts if v.get('unit_id') in support_ids}
    counts['audits_retracted'] = sum(a.get('verdict_id') in verdict_ids and a.get('audit_status') == 'retracted'
                                     and a.get('initial_support_verdict') in {'not_supported', 'contradicted'} for a in audits)
    return counts


def support_sentence(c):
    return (f"Support pass: {c['read']} of {c['in_scope']} in-scope unquoted instances were read; "
            f"{c['supported']} supported, {c['qualified']} qualified, {c['overstated']} to confirm (possible overstatement), "
            f"{c['not_supported']} not supported, {c['contradicted']} contradicted, {c['unverifiable']} unverifiable; "
            f"{c['out_of_scope']} whole-work cites were not read (out of scope).")


def attention_section(report):
    match = re.search(r'^ *(#{1,6}) +Needs your attention[^\n]*\n', report, re.M | re.I)
    if not match: return ''
    tail = report[match.end():]
    end = re.search(r'^ *#{1,' + str(len(match[1])) + r'} +', tail, re.M)
    return tail[:end.start()] if end else tail


def validate_support(manifest, extraction, units, quote_checks, rows, verdicts, audits, sources, report, errors):
    config = manifest.get('support_pass', {})
    if config.get('enabled') is not True: return
    if manifest.get('schema_version') != 7 or config.get('scope') not in {'pincited', 'all'}:
        errors.append('support pass requires schema 7 and scope pincited or all')
    expected = build_support_units(extraction, units, quote_checks, config.get('scope'))
    expected_by_id = {r['unit_id']: r for r in expected}
    row_ids = [r.get('unit_id') for r in rows]
    if set(row_ids) != set(expected_by_id) or len(row_ids) != len(set(row_ids)):
        errors.append('support-units.jsonl requires exactly one row per eligible unquoted citation unit')
    by_unit = {v.get('unit_id'): v for v in verdicts}
    unit_by_id = {u.get('unit_id'): u for u in units}
    source_by_id = {s.get('source_id'): s for s in sources}
    audit_by_verdict = {a.get('verdict_id'): a for a in audits}
    for unit in units:
        uid = unit.get('unit_id')
        linked = unit.get('prepared_unit_ids', [])
        actual = {q.get('prepared_unit_id') for q in quote_checks if q.get('unit_id') == uid}
        if linked and (not isinstance(linked, list) or any(p not in actual for p in linked)):
            errors.append(f'support unit {uid}: prepared quotation links must reconcile to quote-checks')
        if kind_of(unit.get('draft_citation_text', '')) in {'id', 'supra'}:
            if unit.get('xref_status') not in {'resolved', 'unresolved'}:
                errors.append(f'support unit {uid}: cross-reference resolution status required')
            elif unit.get('xref_status') == 'unresolved' and by_unit.get(uid, {}).get('status') not in {'mismatch', 'unverified', 'partial'}:
                errors.append(f'support unit {uid}: unresolved cross-reference must be reported separately')
    for row in rows:
        uid = row.get('unit_id')
        canonical = expected_by_id.get(uid)
        if canonical is None: continue
        for key, value in canonical.items():
            if key != 'unread_reason' and row.get(key) != value:
                errors.append(f'support unit {uid}: stale or altered {key}; rebuild from extraction')
        unit = unit_by_id[uid]
        if kind_of(unit.get('draft_citation_text', '')) == 'id':
            seen, current = {uid}, unit
            while kind_of(current.get('draft_citation_text', '')) == 'id':
                target_id = current.get('antecedent_unit_id')
                target = unit_by_id.get(target_id)
                if not target or target_id in seen or target.get('source_id') != unit.get('source_id'):
                    errors.append(f'support unit {uid}: invalid Id. antecedent chain')
                    break
                seen.add(target_id)
                if units.index(target) >= units.index(current):
                    errors.append(f'support unit {uid}: Id. antecedent must precede the instance')
                    break
                current = target
        for field in ('parenthetical', 'opinion_note'):
            value = unit.get(field)
            if value and value not in unit.get('draft_citation_text', ''):
                errors.append(f'support unit {uid}: {field} must occur verbatim in draft citation')
        for field in ('signal', 'pincite', 'parenthetical', 'opinion_note'):
            if not isinstance(unit.get(field), str): errors.append(f'support unit {uid}: lead must confirm {field} on citation unit')
        if row.get('signal') not in SIGNALS: errors.append(f'support unit {uid}: invalid signal')
        verdict = by_unit.get(uid, {})
        support = verdict.get('support')
        reason = row.get('unread_reason')
        out = canonical.get('unread_reason') == 'out_of_scope'
        if out and reason != 'out_of_scope': errors.append(f'support unit {uid}: out-of-scope unit must remain unread')
        if reason:
            if reason not in {'out_of_scope', 'budget', 'agent_failure'} or (reason == 'out_of_scope' and not out):
                errors.append(f'support unit {uid}: invalid unread_reason')
            if verdict.get('support_read') is not False or support:
                errors.append(f'support unit {uid}: unread unit must have support_read false and no support verdict')
            if reason in {'budget', 'agent_failure'}:
                if manifest.get('completion_target', manifest.get('status')) != 'complete_with_limits':
                    errors.append('unread support units require complete_with_limits')
                if uid not in report or reason not in report:
                    errors.append(f'report must disclose unread support unit {uid} and {reason}')
            continue
        if not isinstance(support, dict):
            errors.append(f'in-scope support unit {uid} lacks support verdict or unread_reason')
            continue
        result = support.get('verdict')
        if result not in {*DISPOSITIONS, 'unverifiable'}:
            errors.append(f'support unit {uid}: invalid support verdict')
            continue
        for field in ('claim', 'claim_basis', 'reason'):
            if not isinstance(support.get(field), str) or not support[field].strip():
                errors.append(f'support unit {uid}: missing support.{field}')
        if support.get('signal') != row.get('signal'): errors.append(f'support unit {uid}: signal mismatch')
        anchor = canonical.get('anchor') or {}
        bases = {'anchor.sentence': [anchor.get('sentence', '')], 'anchor.clause': [anchor.get('clause', '')],
                 'parenthetical': [canonical.get('parenthetical', '')], 'note_prose': canonical.get('note_prose', [])}
        claim = support.get('claim')
        if not claim or not any(claim in text for text in bases.get(support.get('claim_basis'), [])):
            errors.append(f'support unit {uid}: claim not verbatim in declared extraction context')
        if result == 'unverifiable':
            if verdict.get('status') != 'unverified' or not verdict.get('unlock_path') or verdict.get('support_read') is not False:
                errors.append(f'support unit {uid}: unverifiable requires unverified, unlock_path, support_read false')
            continue
        if (verdict.get('status'), verdict.get('category'), verdict.get('severity')) != DISPOSITIONS[result]:
            errors.append(f'support unit {uid}: invalid disposition for {result}')
        source = source_by_id.get(row.get('source_id'), {})
        if (verdict.get('support_read') is not True or verdict.get('verification_basis') not in FULL_TEXT
                or source.get('verification_basis') not in FULL_TEXT or source.get('status') != 'retrieved'):
            errors.append(f'support unit {uid}: support_read requires retrieved full-text evidence')
        for field in ('locator_read', 'source_passage', 'posture'):
            if not isinstance(support.get(field), str) or not support[field].strip():
                errors.append(f'support unit {uid}: missing support.{field}')
        if len(str(support.get('source_passage', ''))) > 400: errors.append(f'support unit {uid}: source_passage exceeds 400 characters')
        audit = audit_by_verdict.get(verdict.get('verdict_id'), {})
        if result in {'not_supported', 'contradicted'} or audit:
            if not audit or audit.get('audit_status') not in {'confirmed', 'revised', 'retracted'}:
                errors.append(f'support unit {uid}: adverse support requires independent verifier audit')
            if audit.get('initial_support_verdict') not in {'not_supported', 'contradicted'}:
                errors.append(f'support unit {uid}: audit requires initial_support_verdict')
            evidence = audit.get('evidence', {})
            # Each class needs an actual explanation, not a checklist of names.
            if not isinstance(evidence, dict) or any(not isinstance(evidence.get(k), str) or not evidence[k].strip() for k in ARTIFACTS):
                errors.append(f'support unit {uid}: audit evidence must address all six artifact classes')
            if audit.get('independent_rederivation') is not True or not audit.get('reviewer') or not audit.get('page_reread'):
                errors.append(f'support unit {uid}: audit needs independent_rederivation, reviewer, page_reread')
            if audit.get('audit_status') == 'retracted' and result != 'supported':
                errors.append(f'support unit {uid}: retracted finding must end supported')
            if audit.get('audit_status') == 'revised' and result not in {'overstated', 'supported_qualified'}:
                errors.append(f'support unit {uid}: revised finding must end overstated or supported_qualified')
        if result in {'not_supported', 'contradicted'}:
            search = support.get('source_search')
            if (not isinstance(search, dict) or not isinstance(search.get('terms'), list) or not search['terms']
                    or any(not isinstance(t, str) or not t.strip() for t in search['terms']) or not search.get('result')):
                errors.append(f'support unit {uid}: adverse support requires named source_search terms and result')
        if result == 'contradicted' and row.get('signal') in {'but see', 'but cf.', 'contra'}:
            errors.append(f'support unit {uid}: contrary signal failing its job is not_supported, not contradicted')
        if result == 'overstated':
            section = attention_section(report)
            unit_named = re.search(r'(?<![\w-])' + re.escape(uid) + r'(?![\w-])', section)
            cite_named = any(value and value in section for value in
                             (unit.get('draft_citation_text'), unit.get('resolved_source_label')))
            if unit_named or (cite_named and support.get('claim') in section):
                errors.append(f'support unit {uid}: overstatement cannot appear in Needs your attention')
    for verdict in verdicts:
        if verdict.get('support') and verdict.get('unit_id') not in expected_by_id:
            errors.append('support verdict on excluded or unknown citation unit')
    counts = support_counts(rows, verdicts, audits)
    if manifest.get('counts', {}).get('support') != counts: errors.append('counts.support does not reconcile to ledgers')
    sentence = support_sentence(counts)
    if sentence not in report: errors.append('report.md lacks accurate support summary: ' + sentence)
    elif not re.search(r'Existence-only:[^\n]*\n\s*' + re.escape(sentence), report):
        errors.append('support summary must immediately follow existence-only sentence')
    if 'Proposition support' not in report: errors.append('report.md lacks Proposition support section')
