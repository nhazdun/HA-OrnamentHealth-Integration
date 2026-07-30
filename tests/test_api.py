"""Tests for the Ornament API dictionaries."""

from __future__ import annotations

import pytest

from custom_components.ornament_health.api import Thesaurus

UNITS = {
    1: "%",
    2: "mmol/L",
    3: "×10⁹/L",
    4: "×10¹²/L",
    5: "×100%",
    6: "x 100 %",
    7: "",
    1001: "Undetected|Detected",
}


@pytest.mark.parametrize(
    ("unit_id", "expected"),
    [
        (1, "%"),
        (2, "mmol/L"),
        # Multiplier units name a quantity and must survive.
        (3, "×10⁹/L"),
        (4, "×10¹²/L"),
        # "×100%" is Ornament's note that the value is a dimensionless ratio.
        (5, None),
        (6, None),
        (7, ""),
        # Qualitative units carry the outcomes, not a unit.
        (1001, None),
        (None, None),
        (999, None),
    ],
)
def test_unit_title(unit_id: int | None, expected: str | None) -> None:
    """Only real units are reported as a unit."""
    assert Thesaurus(units=UNITS).unit_title(unit_id) == expected


def test_ratio_notation_does_not_swallow_qualitative_options() -> None:
    """Dropping the ratio unit leaves qualitative outcomes readable."""
    thesaurus = Thesaurus(units=UNITS)
    assert thesaurus.unit_options(1001) == ["Undetected", "Detected"]
    assert thesaurus.unit_options(5) is None
