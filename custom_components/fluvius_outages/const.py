"""Constants for Fluvius outages."""

from datetime import timedelta
from typing import Final

DOMAIN: Final = "fluvius_outages"

CONF_POSTCODE: Final = "postcode"
CONF_STREETS: Final = "streets"
CONF_SCAN_INTERVAL: Final = "scan_interval"
CONF_LOOKAHEAD_DAYS: Final = "lookahead_days"
CONF_RESOLVED_HOURS: Final = "resolved_hours"

# The outage map on fluvius.be is fed by this endpoint. It is not a documented API:
# the page hands every visitor the same key, so we read it from the page too.
API_URL: Final = (
    "https://api.fluvius.be/ext/klanten-nuc-interruptions/v1/api/interruptions"
)
PAGE_URL: Final = "https://www.fluvius.be/nl/storingen-en-werken/stroomonderbrekingen"
ORIGIN: Final = "https://www.fluvius.be"

# Fluvius reports every outage once, under its latest event: "New" (just announced or
# started), "Update" (changed since) or "End" (restored). The map asks for New+Update
# over the last 14 days to show what is current, so we do the same. Fluvius refuses a
# DateUntil more than 15 days ahead, so planned works announced further out only show
# up once they come within that window.
LOOKBACK: Final = timedelta(days=14)
# How far ahead to show planned works. 0 = only what is happening now. Capped below
# Fluvius's own limit of 15 days.
DEFAULT_LOOKAHEAD_DAYS: Final = 7
MAX_LOOKAHEAD_DAYS: Final = 14

# Fluvius's own outage map refreshes every 5 minutes, so asking more often gains
# nothing. Data arrives continuously, not in batches.
DEFAULT_SCAN_INTERVAL: Final = 300
MIN_SCAN_INTERVAL: Final = 300
MAX_SCAN_INTERVAL: Final = 3600

# Resolved outages stay visible this long after they end (0 = do not show them).
DEFAULT_RESOLVED_HOURS: Final = 24
MAX_RESOLVED_HOURS: Final = 168
# The resolved list is the bulkiest request and changes slowly, so it is fetched at
# most this often, or sooner when an outage we were showing as current disappears.
RESOLVED_REFRESH: Final = timedelta(minutes=15)

REQUEST_TIMEOUT: Final = 30

# How alike two street names must be (0..1) to count as the same street. Fluvius
# spells names its own way ("Molenbeekstraat"), so an exact match would miss typos.
STREET_MATCH_RATIO: Final = 0.9
# Names shorter than this (letters and digits only) must match exactly, so that
# "Kerkstraat" and "Kerkestraat" stay two streets.
STREET_FUZZY_MIN_LENGTH: Final = 12

# How long an unplanned outage without a known end is drawn in the calendar.
OPEN_ENDED_CALENDAR_SPAN: Final = timedelta(hours=1)

OUTAGE_TYPE_PLANNED: Final = "planned"
OUTAGE_TYPE_UNPLANNED: Final = "unplanned"

CONFIGURATION_URL: Final = PAGE_URL
