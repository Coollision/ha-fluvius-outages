"""Parse Fluvius interruptions and decide which ones concern a location."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from difflib import SequenceMatcher
import re
from typing import TYPE_CHECKING, Any
import unicodedata

from .const import OUTAGE_TYPE_PLANNED, OUTAGE_TYPE_UNPLANNED, STREET_MATCH_RATIO

if TYPE_CHECKING:
    from collections.abc import Iterable

POSTCODE_RE = re.compile(r"^\d{4}$")
_HOUSE_NUMBER_RE = re.compile(r"[\s,]+\d+\s*[a-z]?(?:\s*/\s*\d+)?\s*$", re.IGNORECASE)


def normalize(name: str) -> str:
    """Reduce a street name to lowercase letters and digits, without accents."""
    stripped = unicodedata.normalize("NFKD", name)
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", stripped.casefold())


def same_street(a: str, b: str) -> bool:
    """Return whether two street names are (almost) the same."""
    na = normalize(_HOUSE_NUMBER_RE.sub("", a))
    nb = normalize(_HOUSE_NUMBER_RE.sub("", b))
    if not na or not nb:
        return False
    return na == nb or SequenceMatcher(None, na, nb).ratio() >= STREET_MATCH_RATIO


@dataclass(frozen=True, slots=True)
class Area:
    """One municipality part touched by an outage."""

    city: str
    postcode: str
    streets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Outage:
    """One planned or unplanned interruption, as Fluvius reports it."""

    id: str
    werfcode: str
    planned: bool
    start: datetime
    end: datetime | None
    customers_affected: int
    customers_restored: int
    areas: tuple[Area, ...]
    ended: bool = False

    @property
    def type(self) -> str:
        """Return ``planned`` or ``unplanned``."""
        return OUTAGE_TYPE_PLANNED if self.planned else OUTAGE_TYPE_UNPLANNED

    def is_active(self, now: datetime) -> bool:
        """Return whether the power is (or should be) off at ``now``."""
        return (
            not self.ended
            and self.start <= now
            and (self.end is None or now < self.end)
        )

    def is_upcoming(self, now: datetime) -> bool:
        """Return whether the outage starts after ``now``."""
        return not self.ended and self.start > now

    def is_resolved(self, now: datetime, retention: timedelta) -> bool:
        """Return whether power was restored within the last ``retention``."""
        return self.ended and self.end is not None and self.end > now - retention

    @property
    def duration(self) -> timedelta | None:
        """Return how long the outage lasted or is planned to last, if known."""
        return self.end - self.start if self.end else None


@dataclass(frozen=True, slots=True)
class Location:
    """What to watch: a postcode, optionally narrowed to streets or work codes."""

    postcode: str
    streets: tuple[str, ...] = ()
    werfcodes: tuple[str, ...] = ()

    def matches(self, outage: Outage) -> bool:
        """Return whether an outage touches this location."""
        if outage.werfcode in self.werfcodes:
            return True
        for area in outage.areas:
            if area.postcode != self.postcode:
                continue
            if not self.streets:
                return True
            if any(same_street(s, mine) for s in area.streets for mine in self.streets):
                return True
        return False

    def touched_streets(self, outage: Outage) -> tuple[str, ...]:
        """Return the streets of an outage in this location's postcode."""
        found: list[str] = []
        for area in outage.areas:
            if area.postcode == self.postcode:
                found.extend(area.streets)
        return tuple(found)


def parse_outage(raw: dict[str, Any]) -> Outage | None:
    """Turn one API record into an ``Outage``; ``None`` if it is unusable."""
    try:
        start = datetime.fromisoformat(raw["startDateTime"])
        end_raw = raw.get("endDateTime")
        return Outage(
            id=str(raw["id"]),
            werfcode=str(raw.get("gonId", "")),
            planned=raw.get("interruptionType") == "Planned",
            start=start,
            end=datetime.fromisoformat(end_raw) if end_raw else None,
            customers_affected=int(raw.get("numberOfAffectedCustomers") or 0),
            customers_restored=int(raw.get("numberOfRestoredCustomers") or 0),
            areas=tuple(
                Area(
                    city=str(area.get("city", "")),
                    postcode=str(area.get("zipCode", "")),
                    streets=tuple(str(s) for s in area.get("affectedStreets") or ()),
                )
                for area in raw.get("impactedAreas") or ()
            ),
            ended=raw.get("eventType") == "End",
        )
    except KeyError, TypeError, ValueError:
        return None


def parse_outages(raw: Iterable[dict[str, Any]]) -> list[Outage]:
    """Parse every usable record."""
    return [outage for item in raw if (outage := parse_outage(item)) is not None]
