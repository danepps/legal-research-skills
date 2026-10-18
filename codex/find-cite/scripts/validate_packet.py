#!/usr/bin/env python3
"""Validate a find-cite evidence packet using only the Python standard library."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


AUTHORITY_TYPES = {
    "case",
    "statute",
    "regulation",
    "scholarship",
    "report",
    "dataset",
    "archive",
    "other",
}
OPINION_PARTS = {
    "majority",
    "unanimous",
    "per-curiam",
    "plurality",
    "concurrence",
    "dissent",
    "other",
}
NONMAJORITY_PARTS = {"plurality", "concurrence", "dissent", "other"}


def nonempty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def true(value: Any) -> bool:
    return value is True


def string_list(value: Any) -> bool:
    return isinstance(value, list) and all(nonempty_string(item) for item in value)


def valid_url(value: Any) -> bool:
    if not nonempty_string(value):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def valid_date(value: Any) -> bool:
    if not nonempty_string(value) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return False
    try:
        return date.fromisoformat(value) <= date.today()
    except ValueError:
        return False


def load_packet(path: str) -> dict[str, Any]:
    try:
        if path == "-":
            data = json.load(sys.stdin)
        else:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"could not read valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("packet root must be a JSON object")
    return data


def validate(packet: dict[str, Any], require_ready: bool) -> list[str]:
    errors: list[str] = []

    for field in ("proposition", "jurisdiction"):
        if not nonempty_string(packet.get(field)):
            errors.append(f"{field}: must be a non-empty string")

    requested_count = packet.get("requested_count", 2)
    if not isinstance(requested_count, int) or isinstance(requested_count, bool) or not 1 <= requested_count <= 4:
        errors.append("requested_count: must be an integer from 1 through 4")
        requested_count = 2

    status = packet.get("status")
    if status not in {"ready", "limited"}:
        errors.append("status: must be 'ready' or 'limited'")
    if require_ready and status != "ready":
        errors.append("status: --require-ready requires 'ready'")

    limitations = packet.get("limitations", [])
    if not string_list(limitations):
        errors.append("limitations: must be a list of non-empty strings")
        limitations = []
    if status == "limited" and not limitations:
        errors.append("limitations: a limited packet must explain its limitation")

    authorities = packet.get("authorities")
    if not isinstance(authorities, list):
        errors.append("authorities: must be a list")
        return errors
    if not 1 <= len(authorities) <= 4:
        errors.append("authorities: must contain between 1 and 4 entries")
    if status == "ready" and len(authorities) < requested_count:
        errors.append(
            f"authorities: ready packet needs requested_count={requested_count}, found {len(authorities)}"
        )

    seen_ids: set[str] = set()
    seen_citations: set[str] = set()
    ranks: list[int] = []

    for index, authority in enumerate(authorities, start=1):
        prefix = f"authorities[{index - 1}]"
        if not isinstance(authority, dict):
            errors.append(f"{prefix}: must be an object")
            continue

        authority_id = authority.get("id")
        if not nonempty_string(authority_id):
            errors.append(f"{prefix}.id: must be a non-empty string")
        elif authority_id in seen_ids:
            errors.append(f"{prefix}.id: duplicate {authority_id!r}")
        else:
            seen_ids.add(authority_id)

        rank = authority.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 1:
            errors.append(f"{prefix}.rank: must be a positive integer")
        else:
            ranks.append(rank)

        authority_type = authority.get("type")
        if authority_type not in AUTHORITY_TYPES:
            errors.append(f"{prefix}.type: unsupported authority type {authority_type!r}")

        for field in ("citation", "pinpoint", "fit"):
            if not nonempty_string(authority.get(field)):
                errors.append(f"{prefix}.{field}: must be a non-empty string")

        citation = authority.get("citation")
        if nonempty_string(citation):
            key = citation.casefold().strip()
            if key in seen_citations:
                errors.append(f"{prefix}.citation: duplicate citation")
            seen_citations.add(key)

        if not valid_url(authority.get("url")):
            errors.append(f"{prefix}.url: must be an http(s) source URL")

        authority_limitations = authority.get("limitations", [])
        if not string_list(authority_limitations):
            errors.append(f"{prefix}.limitations: must be a list of non-empty strings")
            authority_limitations = []

        support = authority.get("support")
        if not isinstance(support, dict):
            errors.append(f"{prefix}.support: must be an object")
            support = {}
        mode = support.get("mode")
        if mode not in {"quote", "paraphrase"}:
            errors.append(f"{prefix}.support.mode: must be 'quote' or 'paraphrase'")
        if not nonempty_string(support.get("text")):
            errors.append(f"{prefix}.support.text: must be a non-empty string")

        verification = authority.get("verification")
        if not isinstance(verification, dict):
            errors.append(f"{prefix}.verification: must be an object")
            verification = {}
        for field in ("opened", "identity_checked", "support_checked"):
            if not true(verification.get(field)):
                errors.append(f"{prefix}.verification.{field}: must be true")
        if mode == "quote" and not true(verification.get("quote_checked")):
            errors.append(f"{prefix}.verification.quote_checked: must be true for a quote")
        if not valid_date(verification.get("checked_on")):
            errors.append(f"{prefix}.verification.checked_on: must be a valid, non-future ISO date")
        if not nonempty_string(verification.get("basis")):
            errors.append(f"{prefix}.verification.basis: must identify the opened source")

        if authority_type == "case":
            context = authority.get("case_context")
            if not isinstance(context, dict):
                errors.append(f"{prefix}.case_context: required for case authority")
                context = {}
            opinion_part = context.get("opinion_part")
            if opinion_part not in OPINION_PARTS:
                errors.append(f"{prefix}.case_context.opinion_part: invalid value {opinion_part!r}")
            if opinion_part in NONMAJORITY_PARTS and not authority_limitations:
                errors.append(
                    f"{prefix}.limitations: explain reliance on a nonmajority or uncertain opinion part"
                )
            if not true(context.get("current_validity_checked")):
                errors.append(f"{prefix}.case_context.current_validity_checked: must be true")
            if not nonempty_string(context.get("validity_basis")):
                errors.append(f"{prefix}.case_context.validity_basis: must describe the check")

        if authority_type == "scholarship":
            context = authority.get("scholarship_context")
            if not isinstance(context, dict):
                errors.append(f"{prefix}.scholarship_context: required for scholarship")
                context = {}
            if not true(context.get("authorship_checked")):
                errors.append(f"{prefix}.scholarship_context.authorship_checked: must be true")
            if not true(context.get("bibliography_checked")):
                errors.append(f"{prefix}.scholarship_context.bibliography_checked: must be true")

    if ranks and sorted(ranks) != list(range(1, len(authorities) + 1)):
        errors.append("authorities[*].rank: ranks must be unique and consecutive starting at 1")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packet", help="JSON packet path, or '-' for stdin")
    parser.add_argument(
        "--require-ready",
        action="store_true",
        help="fail unless the packet declares and satisfies ready status",
    )
    args = parser.parse_args()

    try:
        packet = load_packet(args.packet)
    except ValueError as exc:
        print(f"INVALID\n- {exc}", file=sys.stderr)
        return 1

    errors = validate(packet, args.require_ready)
    if errors:
        print("INVALID", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    count = len(packet["authorities"])
    label = "READY" if packet.get("status") == "ready" else "LIMITED"
    print(f"{label}: {count} verified authorit{'y' if count == 1 else 'ies'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
