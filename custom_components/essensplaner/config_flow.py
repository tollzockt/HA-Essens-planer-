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
    CONF_ALDI_ONLINE,
    CONF_AUTO_COOKED,
    CONF_BRANCH_RADIUS,
    CONF_BRANCH_ROUTE,
    CONF_BRANCH_ROUTE_RADIUS,
    CONF_BRANCH_ZONES,
    CONF_BUDGET,
    CONF_DEFAULT_MEAL,
    CONF_DEFAULT_SERVINGS,
    CONF_EDEKA_OFFERS,
    CONF_ENABLED_MEALS,
    CONF_EXCLUDED,
    CONF_IMPORT_STARTER,
    CONF_MEAL_TIME_PREFIX,
    CONF_OFFERS_SOURCE,
    CONF_PANTRY,
    CONF_RECEIPT_AI,
    CONF_REGISTER_INTENTS,
    CONF_REWE_ONLINE,
    CONF_SHOW_PANEL,
    CONF_SPLIT_MIN_PERCENT,
    CONF_SPLIT_MIN_SAVING,
    CONF_SPLIT_MODE,
    CONF_SPLIT_OFFER_MIN,
    CONF_SPLIT_TRIP_MIN,
    CONF_STORES,
    CONF_STRATEGY,
    CONF_SYNC_TODO,
    CONF_WATCHLIST,
    CONF_ZIP,
    DEFAULT_ALDI_ONLINE,
    DEFAULT_BRANCH_RADIUS,
    DEFAULT_BRANCH_ROUTE,
    DEFAULT_BRANCH_ROUTE_RADIUS,
    DEFAULT_EDEKA_OFFERS,
    DEFAULT_ENABLED_MEALS,
    DEFAULT_MEAL,
    DEFAULT_MEAL_TIMES,
    DEFAULT_PANTRY,
    DEFAULT_REWE_ONLINE,
    DEFAULT_SERVINGS,
    DEFAULT_SPLIT_MIN_PERCENT,
    DEFAULT_SPLIT_MIN_SAVING,
    DEFAULT_SPLIT_MODE,
    DEFAULT_SPLIT_OFFER_MIN,
    DEFAULT_SPLIT_TRIP_MIN,
    DOMAIN,
    NAME,
    OFFERS_OFF,
    SPLIT_MODES,
    STRATEGIES,
    STRATEGY_BALANCED,
)
from .offers import DEFAULT_STORES, STORES
from .options_schema import (
    BUDGET_RANGE,
    EUR_MAX,
    OFFERS_SOURCES,
    PERCENT_MAX,
    RADIUS_KM,
    ROUTE_RADIUS_M,
    SERVINGS_RANGE,
    TRIP_MAX,
    meals_error,
    normalize_time,
    number,
    whole,
    zip_error,
    zone_list,
)

# The settings can also be changed in the panel (⚙️, 1.4): ranges, defaults and checks of
# both live in options_schema.py; this flow keeps Home Assistant's selectors.
_SERVINGS_SELECTOR = NumberSelector(
    NumberSelectorConfig(
        min=SERVINGS_RANGE[0], max=SERVINGS_RANGE[1], step=1, mode=NumberSelectorMode.BOX
    )
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


def _eur_selector(maximum: float, step: float) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=maximum, step=step, mode=NumberSelectorMode.BOX, unit_of_measurement="€"
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
    """Options: meals, times, pantry, shopping list sync, voice."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if error := meals_error(user_input.get(CONF_ENABLED_MEALS)):
                errors[CONF_ENABLED_MEALS] = error
            else:
                data = dict(user_input)
                data[CONF_DEFAULT_SERVINGS] = int(data[CONF_DEFAULT_SERVINGS])
                for meal in ALL_MEALS:
                    key = f"{CONF_MEAL_TIME_PREFIX}{meal}"
                    if key in data:
                        data[key] = normalize_time(data[key])
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

    def _manager(self) -> Any:
        """The loaded manager (None while the entry is not loaded)."""
        manager = getattr(self.config_entry, "runtime_data", None)
        return manager if hasattr(manager, "branch_postcodes") else None

    def _branch_postcodes(self) -> list[str]:
        """Postcodes of the selected branches (empty if the entry is not loaded)."""
        manager = self._manager()
        return manager.branch_postcodes() if manager is not None else []

    def _branch_placeholders(self) -> dict[str, str]:
        """Number of saved branches and the main branch for the step description."""
        manager = self._manager()
        if manager is None:
            return {"branches": "0", "main_branch": "–"}
        main = manager.get_main_branch()
        return {
            "branches": str(len(manager.branches)),
            "main_branch": manager.branch_label(main) if main else "–",
        }

    async def async_step_economy(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Budget, planning strategy and supermarket offers."""
        errors: dict[str, str] = {}
        options = {**self.config_entry.options, **(user_input or {})}
        if user_input is not None:
            zip_code = str(user_input.get(CONF_ZIP) or "").strip()
            # marktguru needs a zip code or selected branches with a postcode (panel)
            if error := zip_error(
                user_input.get(CONF_OFFERS_SOURCE), zip_code, self._branch_postcodes()
            ):
                errors[CONF_ZIP] = error
            else:
                data = dict(user_input)
                data[CONF_ZIP] = zip_code
                data[CONF_BUDGET] = float(user_input.get(CONF_BUDGET) or 0)
                self._economy = data
                return await self.async_step_stores()
        schema = {
            vol.Required(CONF_BUDGET, default=float(options.get(CONF_BUDGET) or 0)): NumberSelector(
                NumberSelectorConfig(
                    min=BUDGET_RANGE[0],
                    max=BUDGET_RANGE[1],
                    step=5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="€",
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
                    options=OFFERS_SOURCES,
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

    async def async_step_stores(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Stores & shopping: store split, branch search, chain sources (REWE / ALDI SÜD
        online prices, EDEKA offers) and the AI Task entity for receipt photos."""
        if user_input is not None:
            data = {
                **self.config_entry.options,
                **getattr(self, "_general", {}),
                **getattr(self, "_economy", {}),
                **user_input,
            }
            # an optional selector the user cleared is missing in the step's input
            general = getattr(self, "_general", None)
            if general is not None and CONF_SYNC_TODO not in general:
                data.pop(CONF_SYNC_TODO, None)
            if not user_input.get(CONF_RECEIPT_AI):
                data.pop(CONF_RECEIPT_AI, None)  # receipts as pasted text only
            data[CONF_SPLIT_MIN_SAVING] = whole(user_input[CONF_SPLIT_MIN_SAVING])
            data[CONF_SPLIT_MIN_PERCENT] = round(user_input[CONF_SPLIT_MIN_PERCENT])
            data[CONF_SPLIT_OFFER_MIN] = whole(user_input[CONF_SPLIT_OFFER_MIN])
            data[CONF_SPLIT_TRIP_MIN] = whole(user_input[CONF_SPLIT_TRIP_MIN])
            # empty = automatic (zone.home + "Arbeit"/"Work" zones)
            data[CONF_BRANCH_ZONES] = list(user_input.get(CONF_BRANCH_ZONES) or [])
            data[CONF_BRANCH_RADIUS] = whole(user_input[CONF_BRANCH_RADIUS])
            data[CONF_BRANCH_ROUTE_RADIUS] = round(user_input[CONF_BRANCH_ROUTE_RADIUS])
            return self.async_create_entry(data=data)

        options = self.config_entry.options
        mode = options.get(CONF_SPLIT_MODE, DEFAULT_SPLIT_MODE)
        zones = zone_list(options.get(CONF_BRANCH_ZONES))
        radius = min(
            max(number(options.get(CONF_BRANCH_RADIUS), DEFAULT_BRANCH_RADIUS), RADIUS_KM[0]),
            RADIUS_KM[1],
        )
        route_radius = min(
            max(
                number(options.get(CONF_BRANCH_ROUTE_RADIUS), DEFAULT_BRANCH_ROUTE_RADIUS),
                ROUTE_RADIUS_M[0],
            ),
            ROUTE_RADIUS_M[1],
        )

        def clamp(key: str, default: float, maximum: float) -> float:
            return min(max(number(options.get(key), default), 0), maximum)

        schema = {
            vol.Required(
                CONF_SPLIT_MODE, default=mode if mode in SPLIT_MODES else DEFAULT_SPLIT_MODE
            ): SelectSelector(
                SelectSelectorConfig(
                    options=SPLIT_MODES, translation_key="split_mode", mode=SelectSelectorMode.LIST
                )
            ),
            vol.Required(
                CONF_SPLIT_MIN_SAVING,
                default=clamp(CONF_SPLIT_MIN_SAVING, DEFAULT_SPLIT_MIN_SAVING, EUR_MAX),
            ): _eur_selector(EUR_MAX, 0.1),
            vol.Required(
                CONF_SPLIT_MIN_PERCENT,
                default=clamp(CONF_SPLIT_MIN_PERCENT, DEFAULT_SPLIT_MIN_PERCENT, PERCENT_MAX),
            ): NumberSelector(
                NumberSelectorConfig(
                    min=0,
                    max=PERCENT_MAX,
                    step=1,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="%",
                )
            ),
            vol.Required(
                CONF_SPLIT_OFFER_MIN,
                default=clamp(CONF_SPLIT_OFFER_MIN, DEFAULT_SPLIT_OFFER_MIN, EUR_MAX),
            ): _eur_selector(EUR_MAX, 0.05),
            vol.Required(
                CONF_SPLIT_TRIP_MIN,
                default=clamp(CONF_SPLIT_TRIP_MIN, DEFAULT_SPLIT_TRIP_MIN, TRIP_MAX),
            ): _eur_selector(TRIP_MAX, 0.5),
            vol.Optional(
                CONF_BRANCH_ZONES, description={"suggested_value": list(zones)}
            ): EntitySelector(EntitySelectorConfig(domain="zone", multiple=True)),
            vol.Required(CONF_BRANCH_RADIUS, default=radius): NumberSelector(
                NumberSelectorConfig(
                    min=RADIUS_KM[0],
                    max=RADIUS_KM[1],
                    step=0.5,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="km",
                )
            ),
            vol.Required(
                CONF_BRANCH_ROUTE,
                default=bool(options.get(CONF_BRANCH_ROUTE, DEFAULT_BRANCH_ROUTE)),
            ): BooleanSelector(),
            vol.Required(CONF_BRANCH_ROUTE_RADIUS, default=route_radius): NumberSelector(
                NumberSelectorConfig(
                    min=ROUTE_RADIUS_M[0],
                    max=ROUTE_RADIUS_M[1],
                    step=50,
                    mode=NumberSelectorMode.BOX,
                    unit_of_measurement="m",
                )
            ),
            vol.Required(
                CONF_REWE_ONLINE,
                default=bool(options.get(CONF_REWE_ONLINE, DEFAULT_REWE_ONLINE)),
            ): BooleanSelector(),
            vol.Required(
                CONF_ALDI_ONLINE,
                default=bool(options.get(CONF_ALDI_ONLINE, DEFAULT_ALDI_ONLINE)),
            ): BooleanSelector(),
            vol.Required(
                CONF_EDEKA_OFFERS,
                default=bool(options.get(CONF_EDEKA_OFFERS, DEFAULT_EDEKA_OFFERS)),
            ): BooleanSelector(),
            # receipt photos are read by this AI Task entity (none: pasted receipt text only)
            vol.Optional(
                CONF_RECEIPT_AI, description={"suggested_value": options.get(CONF_RECEIPT_AI)}
            ): EntitySelector(EntitySelectorConfig(domain="ai_task")),
        }
        return self.async_show_form(
            step_id="stores",
            data_schema=vol.Schema(schema),
            description_placeholders=self._branch_placeholders(),
        )
