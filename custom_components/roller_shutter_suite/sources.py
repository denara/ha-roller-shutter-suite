"""The source adapter: from an entity state or an entity attribute to a source value.

A source is an input of the core (guardrail 8 of the brief): an entity state,
or one attribute of an entity. This module is the one place that reads them,
so "missing data is not good news" is enforced once for everybody:

- an entity that does not exist, or whose state is ``unavailable``, is
  **unavailable**;
- a state ``unknown`` (also for an attribute of that entity: an entity that
  does not know its own state is not trusted with its attributes), an
  attribute that is absent or ``None``, and a value that is no scalar (a
  list, a mapping) are **unknown**;
- everything else is a **value**: ``on`` and ``off`` become booleans, text
  that spells a finite number becomes that number, every other text stays
  text. What a value means for a layer is decided by the reader of the core
  (``read_switch``, ``read_number`` …), which refuses a value of the wrong
  kind and never turns it into a default.

Nothing here reads a clock or the change time of a state: durations are the
business of the window controller, measured with the integration's own
timestamps.

**Units.** Where Home Assistant states the unit of a value, it is converted
to the unit the core expects. Today that is temperature: a state with a
temperature unit and the temperature attributes of a ``climate`` entity (which
Home Assistant reports in the unit system of the installation) are converted
to degrees Celsius. Other quantities are passed through as they are.

**How an attribute is referenced.** A source reference is an entity ID
(``sensor.example_outdoor``) or an entity ID, ``#`` and an attribute name
(``climate.example_room#current_temperature``). An entity ID can never contain
``#``, so the two forms cannot be confused. A reference that is neither is
malformed; its value is unavailable, and nothing is guessed from it.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, State, split_entity_id, valid_entity_id
from homeassistant.util.unit_conversion import TemperatureConverter

from .core.model import AnySourceValue, SourceValue, WindowConfig
from .core.settings import WINDOW_SETTINGS, SettingKind

ATTRIBUTE_SEPARATOR: Final = "#"
"""What separates the entity ID from the attribute name in a source reference."""

CLIMATE_DOMAIN: Final = "climate"

# The temperature attributes of a climate entity. Home Assistant converts them
# to the unit system of the installation before it writes the state
# (``homeassistant/components/climate/__init__.py``, ``state_attributes``,
# through ``show_temp`` of ``homeassistant/helpers/temperature.py``, Core
# 2026.9.2), so their unit is ``hass.config.units.temperature_unit``. The
# names are those of ``ClimateEntityStateAttribute`` in the same version;
# ``temperature`` is the target temperature.
CLIMATE_TEMPERATURE_ATTRIBUTES: Final = frozenset(
    {"current_temperature", ATTR_TEMPERATURE, "target_temp_high", "target_temp_low"}
)

_TEMPERATURE_UNITS: Final = frozenset(str(unit) for unit in UnitOfTemperature)


@dataclass(frozen=True, slots=True)
class SourceReference:
    """What a source points at: an entity, and optionally one of its attributes."""

    entity_id: str
    attribute: str | None = None

    @classmethod
    def parse(cls, reference: str) -> SourceReference | None:
        """Read a reference; return ``None`` if it is malformed."""
        entity_id, separator, attribute = reference.partition(ATTRIBUTE_SEPARATOR)
        if not valid_entity_id(entity_id):
            return None
        if not separator:
            return cls(entity_id)
        if not attribute or ATTRIBUTE_SEPARATOR in attribute:
            return None
        return cls(entity_id, attribute)

    @property
    def domain(self) -> str:
        """Return the domain of the entity."""
        return split_entity_id(self.entity_id)[0]


def _as_scalar(
    value: object,
) -> (
    SourceValue[bool] | SourceValue[int] | SourceValue[float] | SourceValue[str] | None
):
    """Return a source value for a plain value, or ``None`` if it is no scalar."""
    if isinstance(value, bool):
        return SourceValue.of(value)
    if isinstance(value, int):
        return SourceValue.of(value)
    if isinstance(value, float):
        return SourceValue.of(value) if math.isfinite(value) else None
    if isinstance(value, str):
        return SourceValue.of(value)
    return None


def _from_text(text: str) -> AnySourceValue:
    """Return the value of a state: a switch position, a number, or the text."""
    if text == STATE_ON:
        return SourceValue.of(True)
    if text == STATE_OFF:
        return SourceValue.of(False)
    try:
        number = float(text)
    except ValueError:
        return SourceValue.of(text)
    if not math.isfinite(number):
        return SourceValue.of(text)
    return SourceValue.of(number)


def _to_celsius(value: AnySourceValue, unit: object) -> AnySourceValue:
    """Convert a temperature to degrees Celsius if its unit says it is one."""
    if (
        not isinstance(unit, str)
        or unit not in _TEMPERATURE_UNITS
        or not value.has_value
    ):
        return value
    number = value.value
    if isinstance(number, bool) or not isinstance(number, (int, float)):
        return value
    converted = TemperatureConverter.convert(
        float(number), unit, UnitOfTemperature.CELSIUS
    )
    return SourceValue.of(converted)


def _read_state(state: State) -> AnySourceValue:
    value = _from_text(state.state)
    return _to_celsius(value, state.attributes.get(ATTR_UNIT_OF_MEASUREMENT))


def _read_attribute(
    hass: HomeAssistant, state: State, entity_domain: str, attribute: str
) -> AnySourceValue:
    raw = state.attributes.get(attribute)
    if raw is None:
        return SourceValue.unknown()
    value = _as_scalar(raw)
    if value is None:
        return SourceValue.unknown()
    if entity_domain == CLIMATE_DOMAIN and attribute in CLIMATE_TEMPERATURE_ATTRIBUTES:
        return _to_celsius(value, hass.config.units.temperature_unit)
    return value


def read_source(hass: HomeAssistant, reference: SourceReference) -> AnySourceValue:
    """Return the value of a source as the core takes it.

    Unavailable: the entity does not exist or is unavailable. Unknown: the
    state is unknown, the attribute is absent or ``None``, or the value is
    no scalar. Otherwise a value, converted as the module docstring says.
    """
    state = hass.states.get(reference.entity_id)
    if state is None or state.state == STATE_UNAVAILABLE:
        return SourceValue.unavailable()
    if state.state == STATE_UNKNOWN:
        # An entity that does not know its own state is not trusted with
        # its attributes either.
        return SourceValue.unknown()
    if reference.attribute is not None:
        return _read_attribute(hass, state, reference.domain, reference.attribute)
    return _read_state(state)


def window_sources(config: WindowConfig) -> dict[str, SourceReference | None]:
    """Return the sources a window uses, by the reference as it is configured.

    Every setting of the kind "optional reference" whose resolved value names
    a source counts; "none" and a source that is configured but blind
    (``BLIND_SOURCE``) name nothing to read. The key is the reference itself,
    because that is the key under which the layers of the core look the
    value up in the snapshot. A malformed reference maps to ``None``.
    """
    found: dict[str, SourceReference | None] = {}
    for definition in WINDOW_SETTINGS.definitions:
        if definition.kind is not SettingKind.OPTIONAL_REFERENCE:
            continue
        value = getattr(config, definition.key, None)
        if isinstance(value, str) and value not in found:
            found[value] = SourceReference.parse(value)
    return found


def read_sources(
    hass: HomeAssistant, references: Mapping[str, SourceReference | None]
) -> dict[str, AnySourceValue]:
    """Return the values of the given sources, by their key.

    A malformed reference (``None``) is unavailable: nothing can be read
    from it, and nothing is guessed.
    """
    return {
        key: SourceValue.unavailable()
        if reference is None
        else read_source(hass, reference)
        for key, reference in references.items()
    }
