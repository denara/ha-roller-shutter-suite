"""The page of one cover of a window: what no entity can report about it.

One page per cover of the window, "Cover 1 of 2: cover.example_left", because
sections cannot be nested and a cover has several fields (ruling 3 of the
project owner for block H10). The fields are the settings of
``CAPABILITY_SETTINGS`` of the core, which describes each once: its kind, its
default and its range. Nothing here repeats a range or a default; the error
texts and the helper texts get them as placeholders.

- **Position source**: a required choice, preset to what is stored or to the
  default of the registry.
- **Reporting kind**: a required choice with the entry "Not stated", preset
  to it while nothing is stored. There is no default: a kind that is not
  stated is unknown (ruling of the project owner, 2026-10-01).
- **Tolerance, reporting time, travel times**: optional number boxes; empty
  means the default (tolerance, travel times) or unknown (reporting time).

What is stored holds only what differs: a value equal to the default of the
registry is not written, and a cover that states nothing is not listed. As
on every page of the forms, no selector judges first (:class:`NumberBox`
hands every value on unchanged); a refusal is a translated error of the page.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from enum import Enum
from typing import Any, Final, cast

import probatio
from homeassistant.helpers.selector import (
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_TOLERANCE_CALCULATED,
    DEFAULT_TOLERANCE_MEASURED,
    JsonValue,
    PositionSource,
    ReportingKind,
)
from custom_components.roller_shutter_suite.core.settings import (
    CAPABILITY_SETTINGS,
    SettingDefinition,
    SettingKind,
    ValueRange,
    format_number,
)

from .inheritance import (
    ERROR_FRACTION,
    ERROR_INVALID_VALUE,
    NumberBox,
    as_form_schema,
)
from .model import OUT_OF_RANGE_PREFIX

STEP_MEMBER: Final = "member"

NOT_STATED: Final = "not_stated"
"""The entry of the reporting kind that stores nothing: the kind is unknown."""

PLACEHOLDER_MEMBER: Final = "member"
PLACEHOLDER_MEMBER_NUMBER: Final = "member_number"
PLACEHOLDER_MEMBER_COUNT: Final = "member_count"

_CHOICES: Final[Mapping[str, tuple[str, ...]]] = {
    "position_source": tuple(source.value for source in PositionSource),
    "reporting_kind": (NOT_STATED, *(kind.value for kind in ReportingKind)),
}
"""The entries of the two choices, in the order of the page."""

FIELDS: Final = (
    "position_source",
    "tolerance",
    "reporting_kind",
    "reporting_time",
    "travel_time_up",
    "travel_time_down",
)
"""The fields of the page, in their order: the keys of ``CAPABILITY_SETTINGS``."""


def _definition(key: str) -> SettingDefinition[Any]:
    return next(d for d in CAPABILITY_SETTINGS.definitions if d.key == key)


def _stored_default(key: str) -> JsonValue:
    """Return the default of a setting in its stored form, or ``None`` for none."""
    default = _definition(key).default
    if isinstance(default, timedelta):
        return int(default.total_seconds())
    if isinstance(default, Enum):
        return str(default.value)
    return None


def _unit(key: str) -> str:
    """Return the unit of a number box: the unit of a number, seconds for a duration."""
    definition = _definition(key)
    return (
        cast("str", definition.unit) if definition.kind is SettingKind.NUMBER else "s"
    )


def _bounds(key: str) -> tuple[int, int]:
    """Return the bounds of a number box: every number on this page has two."""
    value_range = cast("ValueRange", _definition(key).value_range)
    return int(cast("float", value_range.minimum)), int(
        cast("float", value_range.maximum)
    )


def _number_box(key: str) -> NumberBox:
    """Return the number box of a field with the bounds and the unit of the registry."""
    minimum, maximum = _bounds(key)
    # Box mode on purpose: a slider cannot be emptied, so it cannot say "unknown".
    return NumberBox(
        NumberSelectorConfig(
            min=minimum,
            max=maximum,
            step=1,
            mode=NumberSelectorMode.BOX,
            unit_of_measurement=_unit(key),
        )
    )


def _with_unit(key: str, value: float) -> str:
    return f"{format_number(value)} {_unit(key)}"


def placeholders(member_id: str, number: int, count: int) -> dict[str, str]:
    """Return the placeholders of the page: the cover, its number, the ranges and defaults.

    Everything is language-neutral: an entity ID, numbers and units. The
    range of every number box is named for its error text, from the
    registry, so the range is written down once.
    """
    result = {
        PLACEHOLDER_MEMBER: member_id,
        PLACEHOLDER_MEMBER_NUMBER: str(number),
        PLACEHOLDER_MEMBER_COUNT: str(count),
        "tolerance_calculated": f"{DEFAULT_TOLERANCE_CALCULATED} %",
        "tolerance_measured": f"{DEFAULT_TOLERANCE_MEASURED} %",
    }
    for key in FIELDS:
        if key in _CHOICES:
            continue
        minimum, maximum = _bounds(key)
        result[f"{key}_minimum"] = format_number(minimum)
        result[f"{key}_maximum"] = _with_unit(key, maximum)
        default = _stored_default(key)
        if isinstance(default, int):
            result[f"{key}_default"] = _with_unit(key, default)
    return result


def schema(own: Mapping[str, JsonValue]) -> Any:
    """Return the schema of the page, preset to what the cover states."""
    fields: dict[probatio.Marker, Any] = {}
    for key in FIELDS:
        stored = own.get(key)
        if key in _CHOICES:
            preset = stored if stored in _CHOICES[key] else _stored_default(key)
            fields[probatio.Required(key, default=preset or NOT_STATED)] = (
                SelectSelector(
                    SelectSelectorConfig(
                        options=list(_CHOICES[key]),
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key=key,
                    )
                )
            )
            continue
        # Optional and without a default: empty means the default or
        # unknown, and a default would come back when the field is emptied.
        description = None if stored is None else {"suggested_value": stored}
        fields[probatio.Optional(key, description=description)] = _number_box(key)
    return as_form_schema(probatio.Schema(fields))


@dataclass(slots=True)
class MemberInput:
    """What the input of the page means: the values the cover states, or errors."""

    own: dict[str, JsonValue] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)


def _number(key: str, raw: object) -> tuple[int | None, str | None]:
    """Return a whole number within the range of the registry, or an error key."""
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None, ERROR_INVALID_VALUE
    if not math.isfinite(raw):
        return None, ERROR_INVALID_VALUE
    if _definition(key).out_of_range(raw):
        return None, f"{OUT_OF_RANGE_PREFIX}{key}"
    if isinstance(raw, float) and not raw.is_integer():
        return None, ERROR_FRACTION
    return int(raw), None


def read_input(user_input: Mapping[str, Any]) -> MemberInput:
    """Turn the input of the page into what the cover states.

    "Not stated" and an empty number box store nothing; a value equal to the
    default of the registry is not stored either, so only what differs is
    listed.
    """
    result = MemberInput()
    for key in FIELDS:
        value = user_input.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        if key in _CHOICES:
            # The drop-down offers its entries only, like every choice of the
            # forms; "Not stated" and the default store nothing.
            if value not in (NOT_STATED, _stored_default(key)):
                result.own[key] = value
            continue
        number, error = _number(key, value)
        if error is not None:
            result.errors[key] = error
        elif number != _stored_default(key):
            result.own[key] = number
    return result
