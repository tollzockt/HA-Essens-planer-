"""Config flow for the Essensplaner integration."""

from __future__ import annotations

from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
)
import voluptuous as vol

from .const import (
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_ENABLED_MEALS,
    CONF_IMPORT_STARTER,
    CONF_MEAL_TIME_PREFIX,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_PANTRY,
    DEFAULT_SERVINGS,
    DOMAIN,
    NAME,
)
from .options_schema import SERVINGS_RANGE

_SERVINGS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=SERVINGS_RANGE[0], max=SERVINGS_RANGE[1], step=1, mode=NumberSelectorMode.BOX
    )
)


class EssensplanerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle the initial setup."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """First (and only) step."""
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")
        if user_input is not None:
            return self.async_create_entry(
                title=NAME,
                data={CONF_IMPORT_STARTER: user_input[CONF_IMPORT_STARTER]},
                options={
                    CONF_DEFAULT_SERVINGS: int(user_input[CONF_DEFAULT_SERVINGS]),
                    CONF_DEFAULT_MEAL: DEFAULT_MEAL,
                    CONF_ENABLED_MEALS: list(DEFAULT_ENABLED_MEALS),
                    CONF_PANTRY: DEFAULT_PANTRY,
                    CONF_REGISTER_INTENTS: True,
                    CONF_SHOW_PANEL: True,
                    **{
                        f"{CONF_MEAL_TIME_PREFIX}{meal}": time
                        for meal, time in DEFAULT_MEAL_TIMES.items()
                    },
                },
            )
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_IMPORT_STARTER, default=True): BooleanSelector(),
                    vol.Required(
                        CONF_DEFAULT_SERVINGS, default=DEFAULT_SERVINGS
                    ): _SERVINGS_SELECTOR,
                }
            ),
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return EssensplanerOptionsFlow()


class EssensplanerOptionsFlow(OptionsFlow):
    """Einstellungen → Geräte & Dienste → Essensplaner → Konfigurieren (1.4: one step).

    All settings live in the panel's own settings view (⚙️, websockets
    essensplaner/get_settings and essensplaner/save_settings with the rules of
    options_schema.py). This step only shows or hides the sidebar panel, so nobody locks
    themselves out of the settings; every other option is kept exactly as it is.
    """

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Show the sidebar panel or not."""
        if user_input is not None:
            return self.async_create_entry(
                data={
                    **self.config_entry.options,
                    CONF_SHOW_PANEL: bool(user_input[CONF_SHOW_PANEL]),
                }
            )
        shown = self.config_entry.options.get(CONF_SHOW_PANEL, True)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {vol.Required(CONF_SHOW_PANEL, default=bool(shown)): BooleanSelector()}
            ),
        )
