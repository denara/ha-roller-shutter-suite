"""SPIKE S2: the three inheritance patterns side by side on real forms.

A subentry type that exists only in the spike. Its flow starts with a menu;
each entry edits the same three settings (a boolean, a number whose valid value
is zero, an expert number) with one pattern:

- ``pattern_a``: optional fields, empty means inherit (the recommended pattern,
  implemented in ``inheritance.py``).
- ``pattern_b``: an explicit "use own value" toggle next to every field.
- ``pattern_c``: a separate step that lists the settings this level sets
  itself, followed by a step with only those fields.

The values are inherited over two levels if a group exists: the first group of
the entry, then the house.
"""

from typing import Any

import probatio
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.helpers.selector import (
    BooleanSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from custom_components.roller_shutter_suite.const import (
    CONF_PATTERN,
    CONF_SETTINGS,
    SUBENTRY_GROUP,
)
from custom_components.roller_shutter_suite.features.daily_routine.flow import FEATURE

from .inheritance import (
    as_form_schema,
    build_placeholders,
    build_schema,
    parse_input,
)
from .model import LevelContext, Parent, SettingField, resolve_inherited

LAB_FIELDS: tuple[SettingField, ...] = tuple(
    setting
    for setting in FEATURE.fields
    if setting.key in ("open_in_morning", "morning_position", "random_offset")
)
OVERRIDE_PREFIX = "override_"
CONF_OVERRIDDEN = "overridden"


def _value_selector(setting: SettingField) -> Any:
    if setting.kind == "bool":
        return BooleanSelector()
    return NumberSelector(
        NumberSelectorConfig(
            min=setting.minimum, max=setting.maximum, mode=NumberSelectorMode.BOX
        )
    )


class PatternLabSubentryFlow(ConfigSubentryFlow):
    """Edit the same settings with pattern a, b or c."""

    _level: LevelContext
    _picked: list[str]

    def _load(self) -> None:
        entry = self._get_entry()
        parents = [Parent(entry.title, entry.data.get(CONF_SETTINGS, {}))]
        for subentry in entry.subentries.values():
            if subentry.subentry_type == SUBENTRY_GROUP:
                parents.insert(
                    0, Parent(subentry.title, subentry.data.get(CONF_SETTINGS, {}))
                )
                break
        own: dict[str, Any] = {}
        if self.source == SOURCE_RECONFIGURE:
            own = dict(self._get_reconfigure_subentry().data.get(CONF_SETTINGS, {}))
        self._level = LevelContext(own=own, parents=tuple(parents))

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Let the user pick the pattern."""
        self._load()
        return self.async_show_menu(
            step_id="user", menu_options=["pattern_a", "pattern_b", "pattern_c"]
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Reopen the pattern the lab entry was created with."""
        self._load()
        pattern = self._get_reconfigure_subentry().data[CONF_PATTERN]
        step = getattr(self, f"async_step_{pattern}")
        result: SubentryFlowResult = await step()
        return result

    def _finish(self, pattern: str, own: dict[str, Any]) -> SubentryFlowResult:
        data = {CONF_PATTERN: pattern, CONF_SETTINGS: own}
        if self.source == SOURCE_RECONFIGURE:
            return self.async_update_and_abort(
                self._get_entry(), self._get_reconfigure_subentry(), data=data
            )
        return self.async_create_entry(title=pattern, data=data)

    # --- pattern (a) ---------------------------------------------------------

    async def async_step_pattern_a(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show pattern (a): optional fields, empty means inherit."""
        if user_input is not None:
            return self._finish(
                "pattern_a", parse_input(LAB_FIELDS, self._level, user_input)
            )
        return self.async_show_form(
            step_id="pattern_a",
            data_schema=build_schema(LAB_FIELDS, self._level),
            description_placeholders=build_placeholders(LAB_FIELDS, self._level),
        )

    # --- pattern (b) ---------------------------------------------------------

    async def async_step_pattern_b(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Show pattern (b): a toggle per field next to the effective value."""
        level = self._level
        errors: dict[str, str] = {}
        if user_input is not None:
            own = {}
            for setting in LAB_FIELDS:
                inherited = resolve_inherited(setting, level.parents).value
                if user_input[f"{OVERRIDE_PREFIX}{setting.key}"]:
                    own[setting.key] = user_input[setting.key]
                elif user_input[setting.key] != inherited:
                    # The trap of this pattern: a value was changed, but the
                    # toggle next to it was not switched on.
                    errors[setting.key] = "changed_without_override"
            if not errors:
                return self._finish("pattern_b", own)

        schema: dict[probatio.Marker, Any] = {}
        for setting in LAB_FIELDS:
            shown = level.own.get(
                setting.key, resolve_inherited(setting, level.parents).value
            )
            if user_input is not None:
                shown = user_input[setting.key]
            overridden = (
                setting.key in level.own
                if user_input is None
                else user_input[f"{OVERRIDE_PREFIX}{setting.key}"]
            )
            schema[
                probatio.Required(f"{OVERRIDE_PREFIX}{setting.key}", default=overridden)
            ] = BooleanSelector()
            schema[probatio.Required(setting.key, default=shown)] = _value_selector(
                setting
            )
        return self.async_show_form(
            step_id="pattern_b",
            data_schema=as_form_schema(probatio.Schema(schema)),
            errors=errors,
        )

    # --- pattern (c) ---------------------------------------------------------

    async def async_step_pattern_c(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """List the settings this level sets itself."""
        if user_input is not None:
            self._picked = user_input.get(CONF_OVERRIDDEN, [])
            if not self._picked:
                return self._finish("pattern_c", {})
            return await self.async_step_pattern_c_values()

        schema = probatio.Schema(
            {
                probatio.Optional(
                    CONF_OVERRIDDEN,
                    description={"suggested_value": list(self._level.own)},
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[setting.key for setting in LAB_FIELDS],
                        multiple=True,
                        mode=SelectSelectorMode.LIST,
                        translation_key="lab_setting",
                    )
                )
            }
        )
        return self.async_show_form(
            step_id="pattern_c",
            data_schema=as_form_schema(schema),
            description_placeholders=build_placeholders(LAB_FIELDS, self._level),
        )

    async def async_step_pattern_c_values(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Ask for the values of the listed settings only."""
        level = self._level
        if user_input is not None:
            return self._finish(
                "pattern_c", {key: user_input[key] for key in self._picked}
            )
        schema: dict[probatio.Marker, Any] = {}
        for setting in LAB_FIELDS:
            if setting.key not in self._picked:
                continue
            shown = level.own.get(
                setting.key, resolve_inherited(setting, level.parents).value
            )
            schema[probatio.Required(setting.key, default=shown)] = _value_selector(
                setting
            )
        return self.async_show_form(
            step_id="pattern_c_values",
            data_schema=as_form_schema(probatio.Schema(schema)),
        )
