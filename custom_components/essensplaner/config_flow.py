"""Config flow for the Essensplaner integration."""

from __future__ import annotations

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
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_ENABLED_MEALS,
    CONF_IMPORT_STARTER,
    CONF_MEAL_TIME_PREFIX,
    CONF_PANTRY,
    CONF_REGISTER_INTENTS,
    CONF_SHOW_PANEL,
    CONF_SYNC_TODO,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_PANTRY,
    DEFAULT_SERVINGS,
    DOMAIN,
    NAME,
)

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
                return self.async_create_entry(data=data)

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
