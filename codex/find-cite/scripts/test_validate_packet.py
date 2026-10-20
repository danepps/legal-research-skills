#!/usr/bin/env python3
"""Offline evidence-gate tests, including scoped historical authorities."""

from copy import deepcopy
from datetime import date

from validate_packet import validate


def main() -> int:
    packet = {
        "proposition": "The court adopted a historical rule.", "jurisdiction": "United States",
        "requested_count": 1, "status": "ready", "limitations": [],
        "authorities": [{
            "id": "A1", "rank": 1, "type": "case", "citation": "Historical Authority, 1 U.S. 1 (1900)",
            "pinpoint": "2", "url": "https://example.test/opinion",
            "support": {"mode": "paraphrase", "text": "The court adopted the rule."},
            "fit": "primary historical evidence", "limitations": [],
            "verification": {"opened": True, "identity_checked": True, "support_checked": True,
                             "quote_checked": False, "checked_on": date.today().isoformat(),
                             "basis": "offline opinion fixture"},
            "case_context": {"opinion_part": "majority", "current_validity_checked": True,
                             "validity_basis": "Offline validity-check fixture."},
        }],
    }
    assert not validate(packet, True)

    historical = deepcopy(packet)
    authority = historical["authorities"][0]
    authority["case_context"].update(current_validity_required=False, current_validity_checked=False,
                                     validity_basis="Historical claim only; no current-law reliance.")
    authority["limitations"] = ["Current validity was not checked; offered only as historical evidence."]
    assert not validate(historical, True)

    current = deepcopy(historical)
    current["authorities"][0]["case_context"]["current_validity_required"] = True
    assert any("ready current-law authority" in error for error in validate(current, True))
    current.update(status="limited", limitations=["Current validity remains unchecked."])
    assert not validate(current, False)
    assert validate(current, True)

    undisclosed = deepcopy(historical)
    undisclosed["authorities"][0]["limitations"] = []
    assert any("disclose" in error for error in validate(undisclosed, True))

    quote = deepcopy(packet)
    quote["authorities"][0]["support"]["mode"] = "quote"
    assert any("quote_checked" in error for error in validate(quote, True))
    dissent = deepcopy(packet)
    dissent["authorities"][0]["case_context"]["opinion_part"] = "dissent"
    assert any("nonmajority" in error for error in validate(dissent, True))
    future = deepcopy(packet)
    future["authorities"][0]["verification"]["checked_on"] = "9999-01-01"
    assert any("non-future" in error for error in validate(future, True))

    print("find-cite evidence-packet tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
