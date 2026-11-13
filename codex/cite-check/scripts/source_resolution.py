"""Structural safeguards for source grouping; never infer an antecedent by name."""
import re
from collections import Counter

SHORT = re.compile(r"^(?:(?:see(?:\s+also)?|cf\.)\s+)?(?:id|ibid)\b|\bsupra(?:\s+(?:note|at)\b|[.,;]?\s*$)", re.I)
SUPRA_NOTE = re.compile(r"\bsupra\s+note\s+(\d+)\b", re.I)


def short_reference(text):
    return bool(SHORT.search(str(text or "").strip()))


def resolution_errors(units, sources, verdicts=()):
    errors = []
    by_id = {u.get("unit_id"): u for u in units}
    by_source = {s.get("source_id"): s for s in sources}
    note_numbers = {u['note_id']: u['footnote_number'] for u in units
                    if u.get('note_id') and u.get('footnote_number') is not None}
    counts = Counter(u.get("source_id") for u in units)
    verified = {v.get("unit_id") for v in verdicts if v.get("status") == "verified"}
    for u in units:
        uid, sid = u.get("unit_id"), u.get("source_id")
        state = u.get("xref_status")
        labels = (u.get("resolved_source_label"), by_source.get(sid, {}).get("canonical_citation"))
        if any(short_reference(label) for label in labels) and state != "unresolved":
            errors.append(f"{uid}: short reference is not a resolved source identity")
        if state == "unresolved":
            if counts[sid] != 1:
                errors.append(f"{uid}: unresolved reference must have its own source_id")
            if uid in verified:
                errors.append(f"{uid}: unresolved reference cannot be verified")
        if short_reference(u.get("draft_citation_text")) and state not in {"resolved", "recovered", "unresolved"}:
            errors.append(f"{uid}: cross-reference needs explicit resolution status")
        if state not in {"resolved", "recovered"}:
            continue
        current, visited = u, set()
        while current.get("xref_status") in {"resolved", "recovered"}:
            cid = current.get("unit_id")
            if cid in visited:
                errors.append(f"{uid}: cross-reference cycle")
                break
            visited.add(cid)
            target = current.get("antecedent_unit_id")
            if current.get("xref_status") == "recovered":
                recovery = current.get("xref_recovery") or {}
                target = recovery.get("candidate_unit_id")
                if recovery.get("identity_confirmed") is not True or not str(recovery.get("evidence") or "").strip():
                    errors.append(f"{cid}: recovered reference needs confirmed identity and evidence")
            if target not in by_id:
                errors.append(f"{cid}: cross-reference needs an existing antecedent unit")
                break
            cited_note = SUPRA_NOTE.search(str(current.get("draft_citation_text") or ""))
            if cited_note and current.get("xref_status") == "resolved":
                target_note = by_id[target].get("footnote_number")
                if target_note is None:
                    target_note = note_numbers.get(by_id[target].get("note_id"))
                if target_note != int(cited_note.group(1)):
                    errors.append(f"{cid}: supra target does not match cited note; confirm and disclose recovery or leave unresolved")
            current = by_id[target]
            if current.get("source_id") != sid or current.get("xref_status") == "unresolved":
                errors.append(f"{uid}: cross-reference chain does not establish the assigned source")
                break
    return errors


def recovery_lines(units):
    return [f"Cross-reference {u['unit_id']}: stale reference; recovered source {u['source_id']}."
            for u in units if u.get("xref_status") == "recovered"]
