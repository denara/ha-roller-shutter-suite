"""The inheritance pattern of the forms: schema, placeholders, reading the input.

Everything here is driven by the registry of the core and by the result of its
resolver; see ``docs/dev/config-flow.md``. The rules of the pattern:

- **Stored form.** An absent key is inherited. ``null`` is never written.
- **A number, a duration, a time, a day of the year** is an optional field;
  empty means "inherit". The own value is the *suggested* value, never the
  default, because a default would come back when the field is emptied. Zero
  is an own value like any other.
- **A switch** is a required drop-down "inherit / on / off". Exactly one of
  two inherit entries is offered, the one that names the inherited state, so
  the effective value is visible and translated.
- **A choice** is a required drop-down with an additional entry "inherit".
- **An optional reference** is a required drop-down "inherit / none / own
  selection" plus an entity field, which counts only with "own selection".
  "None" is stored as the marker constant of the core.
- The inherited value and the level it comes from reach the helper text of a
  field as placeholders with language-neutral content.
- On the house level nothing is inherited: fields are required, a switch is a
  plain toggle, a reference is "none / own selection".
- An option that the covers of the window cannot do is not offered. In its
  place stands a read-only stand-in on the top level of the form, whose
  translated label and helper text give the reason. The own value stays
  stored and applies again when the capability is back (core model,
  "Capability mask").

The number selector delivers floats. Settings that are whole numbers are
normalized in :func:`_normalized_number`, the single place for it: a whole
float becomes an ``int``, and what the reader of the core then refuses because
of a fraction is reported as such.
"""

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import Enum
from typing import Any, Final

import probatio
from homeassistant.data_entry_flow import section
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TimeSelector,
)

from custom_components.roller_shutter_suite.core.model import JsonValue, Position
from custom_components.roller_shutter_suite.core.settings import (
    STORED_NONE,
    GroupLevel,
    Level,
    PartialSettings,
    ReportedFault,
    ResolvedSettings,
    ResolvedValue,
    SettingDefinition,
    SettingKind,
    SettingProblem,
    settings_from_stored,
)

from .model import PROBE_WINDOW_ID, Catalog, FieldForm, LevelContext

SECTION_EXPERT: Final = "expert"
UNAVAILABLE_SUFFIX: Final = "_unavailable"
CHOICE_SUFFIX: Final = "_choice"

INHERIT_ON: Final = "inherit_on"
INHERIT_OFF: Final = "inherit_off"
ON: Final = "on"
OFF: Final = "off"
INHERIT: Final = "inherit"
INHERIT_NONE: Final = "inherit_none"
INHERIT_REFERENCE: Final = "inherit_reference"
NONE: Final = "none"
OWN: Final = "own"

TRANSLATION_KEY_SWITCH: Final = "inherited_switch"
TRANSLATION_KEY_REFERENCE: Final = "reference_choice"

ERROR_INVALID_VALUE: Final = "invalid_value"
ERROR_FRACTION: Final = "fraction_not_allowed"
ERROR_DAY_OF_YEAR: Final = "invalid_day_of_year"
ERROR_LEAP_DAY: Final = "leap_day_not_allowed"
ERROR_REFERENCE_MISSING: Final = "reference_missing"
ERROR_COMBINATION: Final = "invalid_combination"
PLACEHOLDER_COMBINATION: Final = "combination"

_NO_REFERENCE: Final = "-"
_DAY_OF_YEAR: Final = re.compile(r"([0-9]{2})-([0-9]{2})")
_LEAP_YEAR: Final = 2000


def as_form_schema(schema: probatio.Schema) -> Any:
    """Hand a probatio schema to the flow API of Home Assistant.

    This is the one typing bridge of the integration. Home Assistant 2026.9
    still annotates its flow API (``async_show_form``, ``section``,
    ``add_suggested_values_to_schema``) with ``voluptuous.Schema``. At run
    time Home Assistant aliases ``voluptuous`` to ``probatio``, so the object
    is the right one; only ``mypy --strict`` disagrees. Schemas are written
    with ``probatio`` only, and nothing imports ``voluptuous``.
    """
    return schema


def resolve_level(
    catalog: Catalog, context: LevelContext, own: Mapping[str, JsonValue]
) -> ResolvedSettings:
    """Resolve a window as it looks from the edited level with the given own values.

    For a window these are its real members and levels. The house and a group
    have no covers: an imaginary window that sets nothing itself shows what
    they pass on, and lets the rules of the core judge their values.
    """
    own_settings = settings_from_stored(dict(own), catalog.registry)
    empty = PartialSettings()
    group: GroupLevel | None = None
    if context.level is Level.GLOBAL:
        house, window = own_settings, empty
    elif context.level is Level.GROUP:
        house, window = context.house or empty, empty
        group = GroupLevel(PROBE_WINDOW_ID, own_settings)
    else:
        house, window = context.house or empty, own_settings
        if context.group is not None:
            group = GroupLevel(context.group.group_id, context.group.settings)
    return catalog.resolve(
        window_id=PROBE_WINDOW_ID,
        members=context.members,
        global_settings=house,
        window_settings=window,
        group=group,
    ).settings


def inherited_settings(catalog: Catalog, context: LevelContext) -> ResolvedSettings:
    """Resolve what the edited level inherits when it sets nothing itself."""
    return resolve_level(catalog, context, {})


def visible_fields(
    catalog: Catalog, fields: tuple[FieldForm, ...], context: LevelContext
) -> tuple[FieldForm, ...]:
    """Return the fields the level can set: only a window sets what is not inherited."""
    definitions = catalog.definitions
    return tuple(
        item
        for item in fields
        if definitions[item.key].inheritable or context.level is Level.WINDOW
    )


def is_masked(resolved: ResolvedValue[Any]) -> bool:
    """Return whether the covers of the window definitely lack what the setting needs.

    Decided by the capability *state* of the resolver: ``missing`` masks,
    ``unknown`` neither masks nor reports.
    """
    return resolved.unavailable is not None


def stored_form(
    definition: SettingDefinition[Any], item: FieldForm, value: object
) -> JsonValue:
    """Return a resolved value in the form in which a form field carries it."""
    if isinstance(value, timedelta):
        return value.total_seconds() / item.seconds_per_unit
    if isinstance(value, time):
        return value.isoformat()
    if definition.kind is SettingKind.DAY_OF_YEAR and isinstance(value, tuple):
        month, day = value
        return f"{month:02d}-{day:02d}"
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, Position):
        return value.value
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"the setting {definition.key!r} has no form value")


def _shown(definition: SettingDefinition[Any], item: FieldForm, value: object) -> str:
    """Return an inherited value as language-neutral text for a helper text."""
    form_value = stored_form(definition, item, value)
    if form_value is None:
        return _NO_REFERENCE
    if isinstance(form_value, bool):
        return ON if form_value else OFF
    if isinstance(form_value, (int, float)):
        text = f"{form_value:g}"
        return text if item.unit is None else f"{text} {item.unit}"
    return str(form_value)


def _own_form_value(
    definition: SettingDefinition[Any], item: FieldForm, own: JsonValue
) -> JsonValue:
    """Return an own stored value as the form shows it."""
    if definition.kind is SettingKind.DURATION and isinstance(own, int):
        return own / item.seconds_per_unit
    return own


def _number_selector(item: FieldForm) -> NumberSelector:
    # Box mode on purpose: a slider cannot be emptied, so it cannot say "inherit".
    config = NumberSelectorConfig(step=item.step, mode=NumberSelectorMode.BOX)
    if item.minimum is not None:
        config["min"] = item.minimum
    if item.maximum is not None:
        config["max"] = item.maximum
    if item.unit is not None:
        config["unit_of_measurement"] = item.unit
    return NumberSelector(config)


def _dropdown(options: list[str], translation_key: str) -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=options,
            mode=SelectSelectorMode.DROPDOWN,
            translation_key=translation_key,
        )
    )


def _enumeration_options(definition: SettingDefinition[Any]) -> list[str]:
    """Return the values of the enumeration the default of the setting belongs to."""
    return [str(member.value) for member in type(definition.default)]


def _value_field(
    definition: SettingDefinition[Any],
    item: FieldForm,
    context: LevelContext,
    selector: Any,
) -> dict[probatio.Marker, Any]:
    """Build a field whose emptiness means "inherit"."""
    own = context.own.get(item.key)
    if context.inherits:
        description = (
            None
            if own is None
            else {"suggested_value": _own_form_value(definition, item, own)}
        )
        return {probatio.Optional(item.name, description=description): selector}
    default = (
        stored_form(definition, item, definition.default)
        if own is None
        else _own_form_value(definition, item, own)
    )
    return {probatio.Required(item.name, default=default): selector}


def _switch_field(
    definition: SettingDefinition[Any],
    item: FieldForm,
    context: LevelContext,
    inherited: ResolvedValue[Any],
) -> dict[probatio.Marker, Any]:
    own = context.own.get(item.key)
    if not context.inherits:
        default = definition.default if own is None else own
        return {probatio.Required(item.name, default=default): BooleanSelector()}
    inherit_option = INHERIT_ON if inherited.value else INHERIT_OFF
    current = inherit_option if own is None else (ON if own else OFF)
    return {
        probatio.Required(item.name, default=current): _dropdown(
            [inherit_option, ON, OFF], TRANSLATION_KEY_SWITCH
        )
    }


def _enumeration_field(
    definition: SettingDefinition[Any], item: FieldForm, context: LevelContext
) -> dict[probatio.Marker, Any]:
    own = context.own.get(item.key)
    options = _enumeration_options(definition)
    default: JsonValue = stored_form(definition, item, definition.default)
    if context.inherits:
        options = [INHERIT, *options]
        default = INHERIT
    if own is not None:
        default = own
    translation_key = item.name if item.options_key is None else item.options_key
    return {
        probatio.Required(item.name, default=default): _dropdown(
            options, translation_key
        )
    }


def _reference_field(
    item: FieldForm, context: LevelContext, inherited: ResolvedValue[Any]
) -> dict[probatio.Marker, Any]:
    own = context.own.get(item.key)
    options = [NONE, OWN]
    if context.inherits:
        options.insert(
            0, INHERIT_NONE if inherited.value is None else INHERIT_REFERENCE
        )
    current = options[0]
    if own is not None:
        current = NONE if own == STORED_NONE else OWN
    entity_config = EntitySelectorConfig()
    if item.entity_domains:
        entity_config["domain"] = list(item.entity_domains)
    suggested = (
        {"suggested_value": own} if own is not None and own != STORED_NONE else None
    )
    return {
        probatio.Required(f"{item.name}{CHOICE_SUFFIX}", default=current): _dropdown(
            options, TRANSLATION_KEY_REFERENCE
        ),
        probatio.Optional(item.name, description=suggested): EntitySelector(
            entity_config
        ),
    }


def _field_schema(
    definition: SettingDefinition[Any],
    item: FieldForm,
    context: LevelContext,
    inherited: ResolvedValue[Any],
) -> dict[probatio.Marker, Any]:
    kind = definition.kind
    if kind is SettingKind.BOOLEAN:
        return _switch_field(definition, item, context, inherited)
    if kind is SettingKind.ENUMERATION:
        return _enumeration_field(definition, item, context)
    if kind is SettingKind.OPTIONAL_REFERENCE:
        return _reference_field(item, context, inherited)
    if kind is SettingKind.TIME:
        return _value_field(definition, item, context, TimeSelector())
    if kind is SettingKind.DAY_OF_YEAR:
        return _value_field(definition, item, context, TextSelector())
    return _value_field(definition, item, context, _number_selector(item))


def build_schema(
    catalog: Catalog,
    fields: tuple[FieldForm, ...],
    context: LevelContext,
    inherited: ResolvedSettings,
) -> Any:
    """Build the schema of a generated step."""
    definitions = catalog.definitions
    top: dict[probatio.Marker, Any] = {}
    expert: dict[probatio.Marker, Any] = {}
    for item in visible_fields(catalog, fields, context):
        resolved = inherited.values[item.key]
        if is_masked(resolved):
            # Forms cannot disable a field. The reason is the translated label
            # and helper text of a read-only stand-in. It stays on the top
            # level: the frontend strips read-only values only there.
            top[
                probatio.Optional(
                    f"{item.name}{UNAVAILABLE_SUFFIX}",
                    description={"suggested_value": False},
                )
            ] = BooleanSelector(BooleanSelectorConfig(read_only=True))
            continue
        entries = _field_schema(definitions[item.key], item, context, resolved)
        (expert if item.expert else top).update(entries)
    if expert:
        top[probatio.Required(SECTION_EXPERT)] = section(
            as_form_schema(probatio.Schema(expert)), {"collapsed": True}
        )
    return as_form_schema(probatio.Schema(top))


def build_placeholders(
    catalog: Catalog,
    fields: tuple[FieldForm, ...],
    context: LevelContext,
    inherited: ResolvedSettings,
) -> dict[str, str]:
    """Return the inherited value and its source for every field, and who limits.

    Everything here is language-neutral: numbers with units, entity IDs,
    names the user chose. Text that needs a language is a translation key.
    """
    placeholders: dict[str, str] = {}
    if not context.inherits:
        return placeholders
    definitions = catalog.definitions
    for item in visible_fields(catalog, fields, context):
        resolved = inherited.values[item.key]
        if resolved.unavailable is not None:
            capability = resolved.unavailable.capability.value
            placeholders[f"limited_by_{capability}"] = ", ".join(
                resolved.unavailable.limiting_members
            )
            continue
        source = context.house_title
        if resolved.level is Level.GROUP and context.group is not None:
            source = context.group.title
        placeholders[f"{item.name}_inherited"] = _shown(
            definitions[item.key], item, resolved.value
        )
        placeholders[f"{item.name}_source"] = source
    return placeholders


@dataclass(slots=True)
class StepInput:
    """What the input of a generated step means for the edited level."""

    own: dict[str, JsonValue]
    errors: dict[str, str] = field(default_factory=dict)
    placeholders: dict[str, str] = field(default_factory=dict)


def _is_sound(catalog: Catalog, key: str, value: JsonValue) -> bool:
    """Ask the reader of the core whether it accepts the stored value."""
    return not settings_from_stored({key: value}, catalog.registry).faults


def _normalized_number(
    catalog: Catalog, item: FieldForm, kind: SettingKind, raw: float
) -> tuple[JsonValue, str | None]:
    """Turn what the number selector delivers into the stored value.

    The selector delivers floats: 80 arrives as ``80.0``. A whole float is
    stored as an ``int``. A duration is entered in its unit and stored in whole
    seconds. A value with a fraction is kept only if the reader of the setting
    accepts it; if the reader refuses it but accepts the whole number next to
    it, the fraction is the problem, and the error says so.
    """
    if not math.isfinite(raw):
        return None, ERROR_INVALID_VALUE
    if not isinstance(raw, float) or raw.is_integer():
        factor = item.seconds_per_unit if kind is SettingKind.DURATION else 1
        return int(raw) * factor, None
    if kind is not SettingKind.DURATION and _is_sound(catalog, item.key, raw):
        return raw, None
    whole_is_sound = kind is SettingKind.DURATION or _is_sound(
        catalog, item.key, int(raw)
    )
    return None, ERROR_FRACTION if whole_is_sound else ERROR_INVALID_VALUE


def _is_leap_day(value: JsonValue) -> bool:
    """Return whether the text names a day that exists in leap years only."""
    match = _DAY_OF_YEAR.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return False
    month, day = int(match.group(1)), int(match.group(2))
    return _day_exists(_LEAP_YEAR, month, day) and not _day_exists(
        _LEAP_YEAR + 1, month, day
    )


def _day_exists(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _read_field(
    catalog: Catalog,
    item: FieldForm,
    context: LevelContext,
    flat: Mapping[str, Any],
    result: StepInput,
) -> None:
    """Read one field; leave the key out of ``result.own`` when it is inherited."""
    kind = catalog.definitions[item.key].kind
    value = flat.get(item.name)
    if kind is SettingKind.OPTIONAL_REFERENCE:
        _read_reference(item, flat, result)
        return
    if value is None or (isinstance(value, str) and not value.strip()):
        # An emptied field sends no key; an empty text counts as absent.
        return
    if kind is SettingKind.BOOLEAN:
        if value in (INHERIT_ON, INHERIT_OFF):
            return
        result.own[item.key] = value is True or value == ON
    elif kind is SettingKind.ENUMERATION:
        if value != INHERIT:
            result.own[item.key] = value
    elif kind in (SettingKind.NUMBER, SettingKind.DURATION):
        number, error = _normalized_number(catalog, item, kind, value)
        if error is None:
            result.own[item.key] = number
        else:
            result.errors[_error_field(item)] = error
    else:
        result.own[item.key] = value


def _read_reference(
    item: FieldForm, flat: Mapping[str, Any], result: StepInput
) -> None:
    """Read the three choices of an optional reference."""
    choice = flat.get(f"{item.name}{CHOICE_SUFFIX}")
    value = flat.get(item.name)
    if choice == NONE:
        result.own[item.key] = STORED_NONE
    elif choice == OWN:
        # The entity field counts only with "own selection".
        if isinstance(value, str) and value.strip():
            result.own[item.key] = value
        else:
            result.errors[item.name] = ERROR_REFERENCE_MISSING


def _error_field(item: FieldForm) -> str:
    """Return where the error of a field is shown; a section has no field errors."""
    return "base" if item.expert else item.name


def _is_own_fault(fault: ReportedFault, context: LevelContext) -> bool:
    """Return whether a fault lies on the level the form edits."""
    return fault.level is context.level


def _fault_error(
    catalog: Catalog, fault: ReportedFault, own: Mapping[str, JsonValue]
) -> str:
    definition = catalog.definitions.get(fault.key)
    if (
        definition is not None
        and definition.kind is SettingKind.DAY_OF_YEAR
        and fault.problem is SettingProblem.UNREADABLE
    ):
        return ERROR_LEAP_DAY if _is_leap_day(own.get(fault.key)) else ERROR_DAY_OF_YEAR
    return ERROR_INVALID_VALUE


def read_step_input(
    catalog: Catalog,
    fields: tuple[FieldForm, ...],
    context: LevelContext,
    inherited: ResolvedSettings,
    user_input: Mapping[str, Any],
) -> StepInput:
    """Turn the input of a generated step into the own values of the level.

    The result carries **all** own values of the level, not only those of the
    step: the values of other steps and of options that are masked at present
    stay as they are. A key that is missing from the result is inherited.
    Every value is judged by the core: by the reader of its setting, by the
    rules of the window configuration, and by the rules that span several
    settings. A stand-in field is never read, so a client that submits one
    cannot smuggle a value in.
    """
    flat: dict[str, Any] = {
        key: value for key, value in user_input.items() if key != SECTION_EXPERT
    }
    flat.update(user_input.get(SECTION_EXPERT, {}))

    shown = [
        item
        for item in visible_fields(catalog, fields, context)
        if not is_masked(inherited.values[item.key])
    ]
    result = StepInput(
        own={
            key: value
            for key, value in context.own.items()
            if key not in {item.key for item in shown}
        }
    )
    for item in shown:
        _read_field(catalog, item, context, flat, result)
    if result.errors:
        return result

    by_key = {item.key: item for item in shown}
    combination: list[str] = []
    involved: set[str] = set()
    for fault in resolve_level(catalog, context, result.own).faults:
        if fault.problem is SettingProblem.COMBINATION:
            involved.add(fault.key)
        if not _is_own_fault(fault, context):
            continue
        if fault.problem is SettingProblem.COMBINATION:
            combination.append(fault.key)
        elif fault.key in by_key:
            result.errors[_error_field(by_key[fault.key])] = _fault_error(
                catalog, fault, result.own
            )
    on_this_page = [key for key in combination if key in by_key]
    if on_this_page:
        # Each value alone is fine, together the core refuses them. The error
        # stands at every field of this page that is concerned and can show
        # one, and on the form. The keys of all settings concerned are named,
        # also those of another level, because a field inside the section or
        # of another level cannot show an error of its own. A combination that
        # concerns no field of this page is left to the page it belongs to, so
        # the user can get there.
        for key in on_this_page:
            result.errors[_error_field(by_key[key])] = ERROR_COMBINATION
        result.errors.setdefault("base", ERROR_COMBINATION)
        result.placeholders[PLACEHOLDER_COMBINATION] = ", ".join(sorted(involved))
    return result
