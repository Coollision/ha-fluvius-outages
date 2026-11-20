"""Config flow: pick a postcode, optionally narrowed to streets or work codes."""

from __future__ import annotations

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
    CONF_WERFCODES,
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

_LIST = selector.TextSelector(selector.TextSelectorConfig(multiple=True))
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


def _clean(values: list[str] | None) -> list[str]:
    """Strip entries and drop empty ones."""
    return [v.strip() for v in values or [] if v and v.strip()]


def _unique_id(postcode: str, streets: list[str], werfcodes: list[str]) -> str:
    return "|".join(
        (
            postcode,
            ",".join(sorted(normalize(s) for s in streets)),
            ",".join(sorted(werfcodes)),
        )
    )


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
            streets = _clean(user_input.get(CONF_STREETS))
            werfcodes = _clean(user_input.get(CONF_WERFCODES))
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
                    await self.async_set_unique_id(
                        _unique_id(postcode, streets, werfcodes)
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=_title(postcode, streets),
                        data={
                            CONF_POSTCODE: postcode,
                            CONF_STREETS: streets,
                            CONF_WERFCODES: werfcodes,
                            CONF_LOOKAHEAD_DAYS: int(user_input[CONF_LOOKAHEAD_DAYS]),
                            CONF_RESOLVED_HOURS: int(user_input[CONF_RESOLVED_HOURS]),
                        },
                    )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(
                    {
                        vol.Required(CONF_POSTCODE): str,
                        vol.Optional(CONF_STREETS): _LIST,
                        vol.Optional(CONF_WERFCODES): _LIST,
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
    """Change the streets, work codes and how often to look."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Edit the options."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    CONF_STREETS: _clean(user_input.get(CONF_STREETS)),
                    CONF_WERFCODES: _clean(user_input.get(CONF_WERFCODES)),
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
                        vol.Optional(CONF_STREETS): _LIST,
                        vol.Optional(CONF_WERFCODES): _LIST,
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
                merged,
            ),
            description_placeholders={"postcode": merged[CONF_POSTCODE]},
        )
