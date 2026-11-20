"""Config flow: a postal code and, optionally, a street."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import (
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlowWithReload,
)
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.loader import async_get_integration
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api import FluviusApi, FluviusError
from .const import (
    CONF_LOOKAHEAD_DAYS,
    CONF_POSTCODE,
    CONF_RESOLVED_HOURS,
    CONF_SCAN_INTERVAL,
    CONF_STREETS,
    DEFAULT_LOOKAHEAD_DAYS,
    DEFAULT_RESOLVED_HOURS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_LOOKAHEAD_DAYS,
    MAX_RESOLVED_HOURS,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .matching import POSTCODE_RE, normalize

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

# A plain text box: a list widget is confusing for one street. Several streets can be
# given in one box, separated by commas.
FIELD_STREET = "street"
_TEXT = selector.TextSelector()
_HOURS = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=MAX_RESOLVED_HOURS,
        step=1,
        mode=selector.NumberSelectorMode.BOX,
        unit_of_measurement="hours",
    )
)
_DAYS = selector.NumberSelector(
    selector.NumberSelectorConfig(
        min=0,
        max=MAX_LOOKAHEAD_DAYS,
        step=1,
        mode=selector.NumberSelectorMode.SLIDER,
        unit_of_measurement="days",
    )
)


def _split(text: str | None) -> list[str]:
    """Split "a, b; c" into ["a", "b", "c"], dropping blanks and repeats."""
    seen: dict[str, None] = {}
    for part in re.split(r"[,;\n]", text or ""):
        if part.strip():
            seen.setdefault(part.strip(), None)
    return list(seen)


def _join(values: list[str] | None) -> str:
    return ", ".join(values or [])


def _fields(data: dict[str, Any]) -> dict[str, Any]:
    """Show stored lists as the text a person would type."""
    return {
        CONF_POSTCODE: data.get(CONF_POSTCODE, ""),
        FIELD_STREET: _join(data.get(CONF_STREETS)),
    }


def _unique_id(postcode: str, streets: list[str]) -> str:
    # The trailing empty part is where work codes used to go. Keeping it means an
    # entry made before they were dropped is still recognised as the same location.
    return "|".join((postcode, ",".join(sorted(normalize(s) for s in streets)), ""))


def _title(postcode: str, streets: list[str]) -> str:
    return f"{postcode} {', '.join(streets)}".strip()


class FluviusOutagesFlow(ConfigFlow, domain=DOMAIN):
    """Set up one watched location."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask where to watch for outages."""
        errors: dict[str, str] = {}
        if user_input is not None:
            postcode = user_input[CONF_POSTCODE].strip()
            streets = _split(user_input.get(FIELD_STREET))
            if not POSTCODE_RE.match(postcode):
                errors[CONF_POSTCODE] = "invalid_postcode"
            else:
                integration = await async_get_integration(self.hass, DOMAIN)
                api = FluviusApi(
                    async_get_clientsession(self.hass),
                    f"HomeAssistant-FluviusOutages/{integration.version}",
                )
                try:
                    await api.interruptions(dt_util.utcnow())
                except FluviusError:
                    errors["base"] = "cannot_connect"
                else:
                    await self.async_set_unique_id(_unique_id(postcode, streets))
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=_title(postcode, streets),
                        data={
                            CONF_POSTCODE: postcode,
                            CONF_STREETS: streets,
                            CONF_LOOKAHEAD_DAYS: int(user_input[CONF_LOOKAHEAD_DAYS]),
                            CONF_RESOLVED_HOURS: int(user_input[CONF_RESOLVED_HOURS]),
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_POSTCODE): _TEXT,
                        vol.Optional(FIELD_STREET): _TEXT,
                        vol.Required(
                            CONF_LOOKAHEAD_DAYS, default=DEFAULT_LOOKAHEAD_DAYS
                        ): _DAYS,
                        vol.Required(
                            CONF_RESOLVED_HOURS, default=DEFAULT_RESOLVED_HOURS
                        ): _HOURS,
                    }
                ),
                user_input,
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> FluviusOutagesOptions:
        """Return the options flow."""
        return FluviusOutagesOptions()


class FluviusOutagesOptions(OptionsFlowWithReload):
    """Change where to look, what to show and how often."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            postcode = user_input[CONF_POSTCODE].strip()
            if not POSTCODE_RE.match(postcode):
                errors[CONF_POSTCODE] = "invalid_postcode"
            else:
                return self.async_create_entry(
                    data={
                        CONF_POSTCODE: postcode,
                        CONF_STREETS: _split(user_input.get(FIELD_STREET)),
                        CONF_LOOKAHEAD_DAYS: int(user_input[CONF_LOOKAHEAD_DAYS]),
                        CONF_RESOLVED_HOURS: int(user_input[CONF_RESOLVED_HOURS]),
                        CONF_SCAN_INTERVAL: user_input[CONF_SCAN_INTERVAL],
                    }
                )
        merged = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_POSTCODE): _TEXT,
                        vol.Optional(FIELD_STREET): _TEXT,
                        vol.Required(
                            CONF_LOOKAHEAD_DAYS, default=DEFAULT_LOOKAHEAD_DAYS
                        ): _DAYS,
                        vol.Required(
                            CONF_RESOLVED_HOURS, default=DEFAULT_RESOLVED_HOURS
                        ): _HOURS,
                        vol.Required(
                            CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL
                        ): vol.All(
                            int, vol.Range(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL)
                        ),
                    }
                ),
                {**merged, **_fields(merged)} if user_input is None else user_input,
            ),
            errors=errors,
            description_placeholders={"postcode": merged[CONF_POSTCODE]},
        )
