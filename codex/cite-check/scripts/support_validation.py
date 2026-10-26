"""Schema-v7 support gates. Structural evidence checks, never semantic guarantees."""
import json
import re
from prepare_support_units import build_support_units, claim_bases
from support_screen import kind_of, signal_of

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
SIGNALS = {'', 'see', 'see, e.g.', 'see also', 'see generally', 'cf.', 'but see', 'but cf.', 'compare', 'compare with', 'accord', 'contra', 'e.g.'}


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


REPORT_SECTIONS = {"needs your attention", "proposition support", "subsequent history & treatment",
                   "other confirmed corrections", "full footnote ledger", "footnote ledger",
                   "couldn't check", "couldn’t check", "method limits", "scope/method", "counts"}


def report_heading(line):
    text = line.strip()
    markdown = re.match(r'^(#{1,6})\s+(.+?)(?:\s+#+)?$', text)
    level = len(markdown[1]) if markdown else None
    if markdown: text = markdown[2].strip()
    if text.startswith('**') and text.endswith('**'): text = text[2:-2].strip()
    text = text.rstrip(':').casefold()
    if markdown or text in REPORT_SECTIONS:
        return text, level
    return None


def attention_section(report):
    active, level, content = False, None, []
    for line in report.splitlines():
        heading = report_heading(line)
        if heading and heading[0] == 'needs your attention':
            active, level = True, heading[1]
            continue
        if active and heading and (heading[0] in REPORT_SECTIONS or
                                   (level is not None and heading[1] is not None and heading[1] <= level)):
            active = False
        if active: content.append(line)
    return '\n'.join(content)


def read_overstatement(verdict, eligible_ids):
    support = verdict.get('support')
    return (verdict.get('unit_id') in eligible_ids and isinstance(support, dict)
            and support.get('verdict') == 'overstated' and verdict.get('category') == 'support_overstated'
            and verdict.get('status') == 'partial' and verdict.get('severity') == 'low'
            and verdict.get('support_read') is True and verdict.get('verification_basis') in FULL_TEXT)


def disclosed_unread(report, uid, reason):
    unit_pattern = r'(?<![\w-])' + re.escape(uid) + r'(?![\w-])'
    reason_pattern = r'(?<![\w-])' + re.escape(reason) + r'(?![\w-])'
    return any(re.search(unit_pattern, line) and re.search(reason_pattern, line) for line in report.splitlines())


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
        if (signal_of(unit.get('draft_citation_text', '')) == 'see generally'
                and row.get('signal') != 'see generally'):
            errors.append(f'support unit {uid}: preserve the background meaning of generally')
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
                if not disclosed_unread(report, uid, reason):
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
        bases = claim_bases(canonical)
        claim = support.get('claim')
        if not claim or claim not in bases.get(support.get('claim_basis'), []):
            errors.append(f'support unit {uid}: claim not verbatim as a complete declared extraction field')
        if result == 'unverifiable':
            if verdict.get('status') != 'unverified' or not verdict.get('unlock_path') or verdict.get('support_read') is not False:
                errors.append(f'support unit {uid}: unverifiable requires unverified, unlock_path, support_read false')
            continue
        anchor = canonical.get('anchor') or {}
        if (anchor.get('position') == 'mid-sentence'
                and support.get('claim_basis') in {'anchor.clause', 'anchor.sentence'}):
            review = support.get('claim_scope_review')
            if (not isinstance(review, dict)
                    or not isinstance(review.get('prefix_is_proposition'), bool)
                    or not isinstance(review.get('reason'), str) or not review['reason'].strip()):
                errors.append(f'support unit {uid}: mid-sentence claim requires claim_scope_review')
            else:
                basis = 'anchor.clause' if review['prefix_is_proposition'] else 'anchor.sentence'
                if support.get('claim_basis') != basis:
                    errors.append(f'support unit {uid}: claim basis conflicts with reviewed prefix scope')
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
            if audit.get('audit_status') == 'confirmed' and audit.get('initial_support_verdict') != result:
                errors.append(f'support unit {uid}: confirmed audit must preserve initial_support_verdict')
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
    categories = {value[1] for value in DISPOSITIONS.values()}
    for verdict in verdicts:
        if verdict.get('category') in categories and (verdict.get('unit_id') not in expected_by_id or not isinstance(verdict.get('support'), dict)):
            errors.append('support category requires an eligible unquoted unit and complete support object')
        if verdict.get('support') and verdict.get('unit_id') not in expected_by_id:
            errors.append('support verdict on excluded or unknown citation unit')
    counts = support_counts(rows, verdicts, audits)
    if manifest.get('counts', {}).get('support') != counts: errors.append('counts.support does not reconcile to ledgers')
    sentence = support_sentence(counts)
    if sentence not in report: errors.append('report.md lacks accurate support summary: ' + sentence)
    elif not re.search(r'Existence-only:[^\n]*\n\s*' + re.escape(sentence), report):
        errors.append('support summary must immediately follow existence-only sentence')
    if not any(report_heading(line) and report_heading(line)[0] == 'needs your attention' for line in report.splitlines()):
        errors.append('support report requires a Needs your attention heading')
    if 'Proposition support' not in report: errors.append('report.md lacks Proposition support section')
