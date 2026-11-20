"""Tests for parsing and matching."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
        ("Kerkstraat", "Kerkestraat", False),  # short names must match exactly
        ("Molenweg", "Molenwegel", False),
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
    ],
)
def test_location_matches(location: Location, expected: bool) -> None:
    """A location matches on postcode and street together."""
    outage = parse_outage(record())
    assert outage is not None
    assert location.matches(outage) is expected


def test_touched_streets_only_in_own_postcode() -> None:
    """Only streets in the watched postcode are reported back."""
    outage = parse_outage(record())
    assert outage is not None
    assert Location("9000").touched_streets(outage) == ("TESTSTRAAT", "VOORBEELDWEG")
    assert Location("9100").touched_streets(outage) == ()


def test_ended_outage_is_neither_active_nor_upcoming() -> None:
    """An "End" record is history: it never counts as current or announced."""
    outage = parse_outage(record(event="End", planned=False))
    assert outage is not None
    assert outage.ended
    assert not outage.is_active(datetime(2026, 11, 20, 10, 0, tzinfo=UTC))
    assert not outage.is_upcoming(datetime(2026, 11, 20, 5, 0, tzinfo=UTC))


def test_resolved_within_retention() -> None:
    """Resolved means ended, and ended within the retention period."""
    outage = parse_outage(record(event="End"))  # ended 16:00 local = 15:00 UTC
    assert outage is not None
    retention = timedelta(hours=24)
    assert outage.is_resolved(datetime(2026, 11, 21, 14, 59, tzinfo=UTC), retention)
    assert not outage.is_resolved(datetime(2026, 11, 21, 15, 1, tzinfo=UTC), retention)
    assert not outage.is_resolved(
        datetime(2026, 11, 20, 16, 0, tzinfo=UTC), timedelta(0)
    )


def test_duration() -> None:
    """The duration is known when there is an end."""
    assert parse_outage(record())
    assert parse_outage(record()).duration == timedelta(hours=8, minutes=30)
    assert parse_outage(record(planned=False, end=None)).duration is None


def _two_areas() -> dict:
    """An outage that spans two postcodes: a Kerkweg in one, a Molenweg in the other."""
    item = record(postcode="9000", streets=("MOLENWEG",))
    item["impactedAreas"].append(
        {"city": "ELDERS", "zipCode": "9100", "affectedStreets": ["KERKWEG"]}
    )
    return item


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        (Location("9100", ("Kerkweg",)), True),
        (Location("9000", ("Molenweg",)), True),
        # the street must be in the SAME area as the postcode, not just anywhere
        (Location("9000", ("Kerkweg",)), False),
        (Location("9100", ("Molenweg",)), False),
        # a street name alone can never match: the postcode is always required
        (Location("9200", ("Kerkweg",)), False),
    ],
)
def test_postcode_and_street_must_both_match_in_the_same_area(
    location: Location, expected: bool
) -> None:
    """A common street name does not hit outages in other postcodes."""
    outage = parse_outage(_two_areas())
    assert outage is not None
    assert location.matches(outage) is expected
