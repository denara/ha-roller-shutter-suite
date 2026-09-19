"""SPIKE S2: the recommended inheritance pattern for forms.

Pattern (a), refined:

- A number is an optional field in box mode. Empty means "inherit". The own
  value, if there is one, is the suggested value; zero is a value like any other
  because only the *absence* of the key means "inherit".
- A boolean is NOT a toggle, because a toggle has no empty state. It is a
  drop-down with three entries: "inherit", "on", "off". Exactly one of the two
  "inherit" entries is offered, the one that names the inherited state
  ("Inherit (currently on)"), so the effective value is visible and translated.
- The inherited value and the level it comes from are handed to the form as
  description placeholders ``{<key>_inherited}`` and ``{<key>_source}``; the
  field's helper text shows them.
- On the house level there is nothing to inherit from: fields are required and
  a boolean is a plain toggle.
- A setting the window's covers cannot support is left out. In its place a
  read-only field ``<key>_unavailable`` carries the translated reason as its
  label and helper text.
"""

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .model import LevelContext, SettingField, SettingValue, resolve_inherited

SECTION_EXPERT = "expert"
UNAVAILABLE_SUFFIX = "_unavailable"

INHERIT_ON = "inherit_on"
INHERIT_OFF = "inherit_off"
ON = "on"
OFF = "off"


def as_form_schema(schema: probatio.Schema) -> Any:
    """Hand a probatio schema to Home Assistant's flow API.

    At 2026.9.2 the flow API is still annotated with `voluptuous.Schema`. At
    runtime Home Assistant aliases voluptuous to probatio, so the object is the
    right one; only the type checker disagrees. This is the single place that
    bridges the two.
    """
    return schema


def is_available(setting: SettingField, context: LevelContext) -> bool:
    """Tell whether the covers of this level can support the setting."""
    if setting.requires is None or context.capabilities is None:
        return True
    return context.capabilities.get(setting.requires, False)


def _number_selector(setting: SettingField) -> NumberSelector:
    config = NumberSelectorConfig(
        min=setting.minimum,
        max=setting.maximum,
        step=1,
        # Box mode on purpose: a slider cannot be emptied, so it cannot say
        # "inherit".
        mode=NumberSelectorMode.BOX,
    )
    if setting.unit is not None:
        config["unit_of_measurement"] = setting.unit
    return NumberSelector(config)


def _field_schema(
    setting: SettingField, context: LevelContext
) -> tuple[probatio.Marker, Any]:
    own = context.own.get(setting.key)

    if not context.parents:
        # House level: every setting has a value.
        default = setting.default if own is None else own
        if setting.kind == "bool":
            return probatio.Required(setting.key, default=default), BooleanSelector()
        return probatio.Required(setting.key, default=default), _number_selector(
            setting
        )

    if setting.kind == "bool":
        inherited = resolve_inherited(setting, context.parents).value
        inherit_option = INHERIT_ON if inherited else INHERIT_OFF
        current = inherit_option if own is None else (ON if own else OFF)
        return probatio.Required(setting.key, default=current), SelectSelector(
            SelectSelectorConfig(
                options=[inherit_option, ON, OFF],
                mode=SelectSelectorMode.DROPDOWN,
                translation_key="inherited_switch",
            )
        )

    description = None if own is None else {"suggested_value": own}
    return probatio.Optional(setting.key, description=description), _number_selector(
        setting
    )


def build_schema(fields: tuple[SettingField, ...], context: LevelContext) -> Any:
    """Build the schema of a generated step."""
    top: dict[probatio.Marker, Any] = {}
    expert: dict[probatio.Marker, Any] = {}
    for setting in fields:
        if not is_available(setting, context):
            # Forms cannot disable a field. The reason is the translated label
            # and helper text of a read-only stand-in. It stays on the top
            # level: the frontend only strips read-only values there.
            top[
                probatio.Optional(
                    f"{setting.key}{UNAVAILABLE_SUFFIX}",
                    description={"suggested_value": False},
                )
            ] = BooleanSelector(BooleanSelectorConfig(read_only=True))
            continue
        marker, selector = _field_schema(setting, context)
        (expert if setting.expert else top)[marker] = selector
    if expert:
        top[probatio.Required(SECTION_EXPERT)] = section(
            as_form_schema(probatio.Schema(expert)), {"collapsed": True}
        )
    return as_form_schema(probatio.Schema(top))


def build_placeholders(
    fields: tuple[SettingField, ...], context: LevelContext
) -> dict[str, str]:
    """Return the inherited value and its source for every field."""
    placeholders = dict(context.placeholders)
    for setting in fields:
        resolved = resolve_inherited(setting, context.parents)
        value = resolved.value
        if isinstance(value, bool):
            # Only used by texts that do not rely on it; the drop-down carries
            # the translated state.
            shown = ON if value else OFF
        else:
            shown = f"{value:g}"
            if setting.unit is not None:
                shown = f"{shown} {setting.unit}"
        placeholders[f"{setting.key}_inherited"] = shown
        placeholders[f"{setting.key}_source"] = resolved.source
    return placeholders


def parse_input(
    fields: tuple[SettingField, ...],
    context: LevelContext,
    user_input: Mapping[str, Any],
) -> dict[str, SettingValue]:
    """Turn the input of a generated step into the level's own values.

    A key that is missing from the result is inherited.
    """
    flat = {
        key: value for key, value in user_input.items() if key != SECTION_EXPERT
    } | dict(user_input.get(SECTION_EXPERT, {}))

    own: dict[str, SettingValue] = {}
    for setting in fields:
        if not is_available(setting, context) or setting.key not in flat:
            continue
        value = flat[setting.key]
        if setting.kind == "bool" and context.parents:
            if value in (INHERIT_ON, INHERIT_OFF):
                continue
            value = value == ON
        own[setting.key] = value
    return own
