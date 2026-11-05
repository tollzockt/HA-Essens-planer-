"""Config flow for the Essensplaner integration."""

from __future__ import annotations

import re
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    BooleanSelector,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TimeSelector,
)
import voluptuous as vol

from .const import (
    ALL_MEALS,
    CONF_AUTO_COOKED,
    CONF_BUDGET,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_ENABLED_MEALS,
    CONF_EXCLUDED,
    CONF_IMPORT_STARTER,
    CONF_MEAL_TIME_PREFIX,
    CONF_OFFERS_SOURCE,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    CONF_STORES,
    CONF_STRATEGY,
    CONF_SYNC_TODO,
    CONF_WATCHLIST,
    CONF_ZIP,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_PANTRY,
    DEFAULT_SERVINGS,
    DOMAIN,
    NAME,
    OFFERS_MARKTGURU,
    OFFERS_OFF,
    STRATEGIES,
    STRATEGY_BALANCED,
)
from .offers import DEFAULT_STORES, STORES

_SERVINGS_SELECTOR = NumberSelector(
    NumberSelectorConfig(min=1, max=20, step=1, mode=NumberSelectorMode.BOX)
)
_MEAL_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=ALL_MEALS, translation_key="meal", mode=SelectSelectorMode.DROPDOWN
    )
)
_MEALS_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=ALL_MEALS,
        translation_key="meal",
        multiple=True,
        mode=SelectSelectorMode.LIST,
    )
)


def _normalize_time(value: Any) -> str:
    text = str(value or "")
    return text[:5] if len(text) >= 5 else text


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
    """Options: meals, times, pantry, shopping list sync, voice."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_ENABLED_MEALS):
                errors[CONF_ENABLED_MEALS] = "no_meals"
            else:
                data = dict(user_input)
                data[CONF_DEFAULT_SERVINGS] = int(data[CONF_DEFAULT_SERVINGS])
                for meal in ALL_MEALS:
                    key = f"{CONF_MEAL_TIME_PREFIX}{meal}"
                    if key in data:
                        data[key] = _normalize_time(data[key])
                self._general = data
                return await self.async_step_economy()

        options = {**self.config_entry.options, **(user_input or {})}
        schema: dict[Any, Any] = {
            vol.Required(
                CONF_DEFAULT_SERVINGS,
                default=options.get(CONF_DEFAULT_SERVINGS, DEFAULT_SERVINGS),
            ): _SERVINGS_SELECTOR,
            vol.Required(
                CONF_ENABLED_MEALS,
                default=options.get(CONF_ENABLED_MEALS, list(DEFAULT_ENABLED_MEALS)),
            ): _MEALS_SELECTOR,
            vol.Required(
                CONF_DEFAULT_MEAL, default=options.get(CONF_DEFAULT_MEAL, DEFAULT_MEAL)
            ): _MEAL_SELECTOR,
        }
        for meal in ALL_MEALS:
            key = f"{CONF_MEAL_TIME_PREFIX}{meal}"
            default = options.get(key, DEFAULT_MEAL_TIMES[meal])
            if len(default) == 5:
                default = f"{default}:00"
            schema[vol.Required(key, default=default)] = TimeSelector()
        schema.update(
            {
                vol.Optional(
                    CONF_PANTRY, default=options.get(CONF_PANTRY, DEFAULT_PANTRY)
                ): TextSelector(TextSelectorConfig(multiline=True)),
                vol.Optional(CONF_EXCLUDED, default=options.get(CONF_EXCLUDED, "")): TextSelector(),
                vol.Required(
                    CONF_AUTO_COOKED, default=options.get(CONF_AUTO_COOKED, True)
                ): BooleanSelector(),
                vol.Optional(
                    CONF_SYNC_TODO,
                    description={"suggested_value": options.get(CONF_SYNC_TODO)},
                ): EntitySelector(EntitySelectorConfig(domain="todo")),
                vol.Required(
                    CONF_REGISTER_INTENTS,
                    default=options.get(CONF_REGISTER_INTENTS, True),
                ): BooleanSelector(),
                vol.Required(
                    CONF_SHOW_PANEL, default=options.get(CONF_SHOW_PANEL, True)
                ): BooleanSelector(),
            }
        )
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema), errors=errors)

    def _branch_postcodes(self) -> list[str]:
        """Postcodes of the selected branches (empty if the entry is not loaded)."""
        manager = getattr(self.config_entry, "runtime_data", None)
        if manager is None or not hasattr(manager, "branch_postcodes"):
            return []
        return manager.branch_postcodes()

    async def async_step_economy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Budget, planning strategy and supermarket offers."""
        errors: dict[str, str] = {}
        options = {**self.config_entry.options, **(user_input or {})}
        if user_input is not None:
            zip_code = str(user_input.get(CONF_ZIP) or "").strip()
            # marktguru needs a zip code or selected branches with a postcode (panel)
            if user_input.get(CONF_OFFERS_SOURCE) == OFFERS_MARKTGURU and (
                (zip_code and not re.fullmatch(r"\d{5}", zip_code))
                or (not zip_code and not self._branch_postcodes())
            ):
                errors[CONF_ZIP] = "invalid_zip"
            else:
                data = {**self.config_entry.options, **getattr(self, "_general", {}), **user_input}
                data[CONF_ZIP] = zip_code
                data[CONF_BUDGET] = float(user_input.get(CONF_BUDGET) or 0)
                return self.async_create_entry(data=data)
        schema = {
            vol.Required(CONF_BUDGET, default=float(options.get(CONF_BUDGET) or 0)): NumberSelector(
                NumberSelectorConfig(
                    min=0, max=2000, step=5, mode=NumberSelectorMode.BOX, unit_of_measurement="€"
                )
            ),
            vol.Required(
                CONF_STRATEGY, default=options.get(CONF_STRATEGY, STRATEGY_BALANCED)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=STRATEGIES, translation_key="strategy", mode=SelectSelectorMode.LIST
                )
            ),
            vol.Required(
                CONF_OFFERS_SOURCE, default=options.get(CONF_OFFERS_SOURCE, OFFERS_OFF)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[OFFERS_OFF, OFFERS_MARKTGURU],
                    translation_key="offers_source",
                    mode=SelectSelectorMode.LIST,
                )
            ),
            vol.Optional(CONF_ZIP, default=str(options.get(CONF_ZIP) or "")): TextSelector(),
            vol.Required(
                CONF_STORES, default=list(options.get(CONF_STORES) or DEFAULT_STORES)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=[{"value": k, "label": v} for k, v in STORES.items()],
                    multiple=True,
                    mode=SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(CONF_WATCHLIST, default=options.get(CONF_WATCHLIST, "")): TextSelector(),
        }
        return self.async_show_form(
            step_id="economy", data_schema=vol.Schema(schema), errors=errors
        )
