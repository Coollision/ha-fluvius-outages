"""Tests for parsing and matching."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.fluvius_outages.matching import (
    Location,
    normalize,
    parse_outage,
    parse_outages,
    same_street,
)

from .conftest import record


def test_normalize_strips_accents_case_and_punctuation() -> None:
    """Names compare on letters and digits only."""
    assert normalize("Sint-Pieters Plein") == "sintpietersplein"
    assert normalize("Ééndrachtstraat") == "eendrachtstraat"


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ("MOLENBEEKSTRAAT", "Molenbekstraat", True),  # a typo is still the street
        ("Sint-Pieters Plein", "SINTPIETERSPLEIN", True),
        ("Dorp 12", "DORP", True),  # also for short names
        ("Kerkstraat 3b", "Kerkstraat", True),
        ("Kerkstraat 12/2", "Kerkstraat", True),
        ("Kerkstraat", "Kerkplein", False),
        ("Kerkstraat", "Molenstraat", False),
        ("", "Kerkstraat", False),
    ],
)
def test_same_street(a: str, b: str, expected: bool) -> None:
    """Street names match despite spelling differences, but not different streets."""
    assert same_street(a, b) is expected


def test_parse_outage_planned() -> None:
    """A planned record keeps its window, counts and streets."""
    outage = parse_outage(record())
    assert outage is not None
    assert outage.planned
    assert outage.type == "planned"
    assert outage.werfcode == "400001"
    assert outage.customers_affected == 18
    assert outage.areas[0].streets == ("TESTSTRAAT", "VOORBEELDWEG")
    assert outage.end is not None


def test_parse_outage_unplanned_without_end() -> None:
    """An unplanned outage under way has no end yet."""
    outage = parse_outage(record(planned=False, end=None))
    assert outage is not None
    assert outage.type == "unplanned"
    assert outage.end is None


def test_parse_outages_skips_garbage() -> None:
    """Records that cannot be parsed are dropped, not fatal."""
    outages = parse_outages(
        [record(), {"id": "x"}, {"startDateTime": "nope", "id": "y"}]
    )
    assert len(outages) == 1


def test_active_and_upcoming_windows() -> None:
    """Active between start and end; upcoming before start."""
    outage = parse_outage(record())
    assert outage is not None
    before = datetime(2026, 11, 20, 5, 0, tzinfo=UTC)  # 06:00 local, before 07:30
    during = datetime(2026, 11, 20, 10, 0, tzinfo=UTC)
    after = datetime(2026, 11, 20, 16, 0, tzinfo=UTC)
    assert outage.is_upcoming(before)
    assert not outage.is_active(before)
    assert outage.is_active(during)
    assert not outage.is_active(after)


def test_open_ended_outage_stays_active() -> None:
    """Without an end the outage is active for as long as it is reported."""
    outage = parse_outage(record(planned=False, end=None))
    assert outage is not None
    assert outage.is_active(datetime(2026, 12, 31, tzinfo=UTC))


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (Location("9000", ("Teststraat",)), True),
        (Location("9000", ("Teststraat 12",)), True),  # a house number is ignored
        (Location("9000", ("Voorbeeldweg",)), True),
        (Location("9000"), True),  # whole postcode
        (Location("9000", ("Andere straat",)), False),
        (Location("9100", ("Teststraat",)), False),  # right street, wrong postcode
        (Location("9100", (), ("400001",)), True),  # work code wins over postcode
        (Location("9100", (), ("999999",)), False),
    ],
)
def test_location_matches(location: Location, expected: bool) -> None:
    """A location matches by postcode and street, or by work code."""
    outage = parse_outage(record())
    assert outage is not None
    assert location.matches(outage) is expected


def test_touched_streets_only_in_own_postcode() -> None:
    """Only streets in the watched postcode are reported back."""
    outage = parse_outage(record())
    assert outage is not None
    assert Location("9000").touched_streets(outage) == ("TESTSTRAAT", "VOORBEELDWEG")
    assert Location("9100").touched_streets(outage) == ()
