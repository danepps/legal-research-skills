#!/usr/bin/env python3
"""Offline unit tests for CourtListener treatment triage helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT = Path(__file__).with_name("courtlistener_treatment.py")
SPEC = importlib.util.spec_from_file_location("courtlistener_treatment", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def main() -> int:
    signals = MODULE.signal_names(
        "Roe was overruled by Dobbs, and the earlier rule is no longer good law."
    )
    assert "overruled" in signals and "no_longer_good_law" in signals
    assert MODULE.signal_names("The judgment is affirmed.") == []

    assert MODULE.target_party_tokens("Barnes v. Gorman") == ["Barnes", "Gorman"]
    assert MODULE.mentions_target(
        "The court explained why Barnes did not control.", "Barnes v. Gorman"
    )
    assert not MODULE.mentions_target(
        "The court explained why Smith did not control.", "Barnes v. Gorman"
    )

    print("courtlistener_treatment tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
