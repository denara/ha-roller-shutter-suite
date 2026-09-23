"""The source adapter: an entity state or an entity attribute becomes a source value."""

from datetime import timedelta
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util.unit_system import US_CUSTOMARY_SYSTEM

from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    CapabilityProfile,
    DayType,
    MemberConfig,
    SourceState,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.schedule import (
    day_type_from_inputs,
)
from custom_components.roller_shutter_suite.sources import (
    SourceReference,
    read_source,
    read_sources,
    window_sources,
)
from tests.ha.runtime_kit import MONDAY

STATE = SourceReference("sensor.example_outdoor")
ATTRIBUTE = SourceReference("climate.example_room", "current_temperature")
PROFILE = CapabilityProfile(
    supports_open_close=True,
    supports_set_position=True,
    supports_stop=True,
    reports_position=True,
    travel_time_up=timedelta(seconds=30),
    travel_time_down=timedelta(seconds=30),
)


def _value(hass: HomeAssistant, reference: SourceReference) -> Any:
    source = read_source(hass, reference)
    return source.value if source.has_value else source.state


async def test_an_attribute_works_like_a_state(hass: HomeAssistant) -> None:
    """The same number, read from a state and from an attribute, gives the same value."""
    hass.states.async_set("sensor.example_outdoor", "21.5")
    hass.states.async_set("climate.example_room", "heat", {"current_temperature": 21.5})

    assert read_source(hass, STATE) == read_source(hass, ATTRIBUTE)
    assert _value(hass, ATTRIBUTE) == 21.5  # noqa: PLR2004 - the value that was set


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("unavailable", SourceState.UNAVAILABLE),
        ("unknown", SourceState.UNKNOWN),
        (None, SourceState.UNAVAILABLE),
    ],
    ids=["unavailable", "unknown", "entity removed"],
)
async def test_missing_data_is_never_a_number(
    hass: HomeAssistant, state: str | None, expected: SourceState
) -> None:
    """Unavailable, unknown and a removed entity reach the core without a value."""
    if state is not None:
        hass.states.async_set("sensor.example_outdoor", state)
        hass.states.async_set("climate.example_room", state, {"current_temperature": 5})

    assert _value(hass, STATE) is expected
    assert _value(hass, ATTRIBUTE) is expected


async def test_a_non_numeric_state_reaches_the_core_as_text_and_is_no_number(
    hass: HomeAssistant,
) -> None:
    """Text stays text; a reader of the core that wants a number refuses it."""
    hass.states.async_set("sensor.example_outdoor", "warm")

    source = read_source(hass, STATE)

    assert source.has_value
    assert source.value == "warm"
    assert type(source.value) is str


async def test_an_attribute_that_is_absent_or_no_scalar_is_unknown(
    hass: HomeAssistant,
) -> None:
    """A missing attribute, ``None``, a list and a mapping carry no value."""
    hass.states.async_set(
        "climate.example_room",
        "heat",
        {"target_temp_low": None, "hvac_modes": ["heat", "off"], "extra": {"a": 1}},
    )

    for attribute in ("current_temperature", "target_temp_low", "hvac_modes", "extra"):
        reference = SourceReference("climate.example_room", attribute)
        assert _value(hass, reference) is SourceState.UNKNOWN


async def test_switch_positions_and_numbers_are_read_as_such(
    hass: HomeAssistant,
) -> None:
    """``on`` and ``off`` are booleans, numeric text is a number, the rest is text."""
    hass.states.async_set("binary_sensor.example_workday", "on")
    hass.states.async_set("sensor.example_brightness", "42")
    hass.states.async_set("sensor.example_odd", "inf")
    hass.states.async_set("binary_sensor.example_contact", "open")

    assert _value(hass, SourceReference("binary_sensor.example_workday")) is True
    assert _value(hass, SourceReference("sensor.example_brightness")) == 42  # noqa: PLR2004
    assert _value(hass, SourceReference("sensor.example_odd")) == "inf"
    assert _value(hass, SourceReference("binary_sensor.example_contact")) == "open"


async def test_attribute_values_keep_their_type(hass: HomeAssistant) -> None:
    """A boolean, a whole number, a fraction and text of an attribute stay what they are."""
    hass.states.async_set(
        "sensor.example_station",
        "ok",
        {"raining": True, "count": 3, "ratio": 0.5, "note": "dry", "bad": float("nan")},
    )

    values = {
        attribute: _value(hass, SourceReference("sensor.example_station", attribute))
        for attribute in ("raining", "count", "ratio", "note", "bad")
    }

    assert values == {
        "raining": True,
        "count": 3,
        "ratio": 0.5,
        "note": "dry",
        "bad": SourceState.UNKNOWN,
    }


async def test_temperatures_are_converted_to_celsius(hass: HomeAssistant) -> None:
    """A state in Fahrenheit and a climate attribute in the system unit become Celsius."""
    hass.states.async_set("sensor.example_outdoor", "50", {"unit_of_measurement": "°F"})
    hass.states.async_set("sensor.example_indoor", "20", {"unit_of_measurement": "°C"})
    hass.states.async_set("sensor.example_wind", "50", {"unit_of_measurement": "km/h"})
    hass.states.async_set(
        "climate.example_room",
        "heat",
        {"current_temperature": 68, "temperature": 70, "hvac_mode": "heat"},
    )

    assert _value(hass, STATE) == 10  # noqa: PLR2004 - 50 °F
    assert _value(hass, SourceReference("sensor.example_indoor")) == 20  # noqa: PLR2004
    assert _value(hass, SourceReference("sensor.example_wind")) == 50  # noqa: PLR2004
    # The system of the test installation is metric: the attribute is Celsius already.
    assert _value(hass, ATTRIBUTE) == 68  # noqa: PLR2004


async def test_climate_attributes_follow_the_unit_system_of_the_installation(
    hass: HomeAssistant,
) -> None:
    """With an imperial installation the climate attributes are Fahrenheit and are converted."""
    hass.config.units = US_CUSTOMARY_SYSTEM
    hass.states.async_set(
        "climate.example_room",
        "heat",
        {"current_temperature": 68, "temperature": 50, "hvac_mode": "heat"},
    )

    assert _value(hass, ATTRIBUTE) == 20  # noqa: PLR2004 - 68 °F
    assert _value(hass, SourceReference("climate.example_room", "temperature")) == 10  # noqa: PLR2004
    # An attribute that is no temperature is not touched.
    assert _value(hass, SourceReference("climate.example_room", "hvac_mode")) == "heat"


@pytest.mark.parametrize(
    "reference",
    ["", "no_domain", "sensor.example#", "sensor.example#a#b", "#temperature", "a.b c"],
)
def test_malformed_references_are_refused(reference: str) -> None:
    """A reference that is neither an entity ID nor entity ID, ``#``, attribute is refused."""
    assert SourceReference.parse(reference) is None


def test_references_are_parsed() -> None:
    """An entity ID alone, and an entity ID with an attribute."""
    assert SourceReference.parse("sensor.example_outdoor") == STATE
    assert (
        SourceReference.parse("climate.example_room#current_temperature") == ATTRIBUTE
    )
    assert ATTRIBUTE.domain == "climate"


async def test_a_malformed_reference_reads_as_unavailable(hass: HomeAssistant) -> None:
    """Nothing can be read from it, and nothing is guessed."""
    values = read_sources(hass, {"broken": None})

    assert values["broken"].state is SourceState.UNAVAILABLE


def test_window_sources_are_the_optional_references_of_the_configuration() -> None:
    """Every configured source, keyed by its reference; none and blind name nothing."""
    config = WindowConfig(
        "w1",
        (MemberConfig("cover.example_window", PROFILE),),
        schedule_workday_source="binary_sensor.example_workday",
        schedule_holiday_source="binary_sensor.example_workday",
        schedule_brightness_source="sensor.example_station#illuminance",
        morning_condition_source="not an entity",
        frost_source=BLIND_SOURCE,
    )

    assert window_sources(config) == {
        "binary_sensor.example_workday": SourceReference(
            "binary_sensor.example_workday"
        ),
        "sensor.example_station#illuminance": SourceReference(
            "sensor.example_station", "illuminance"
        ),
        "not an entity": None,
    }


async def test_the_schedule_reads_a_day_type_from_an_attribute(
    hass: HomeAssistant,
) -> None:
    """End to end: a workday given as an attribute decides the day type like a state."""
    hass.states.async_set("sensor.example_calendar", "ok", {"workday": True})
    reference = "sensor.example_calendar#workday"
    config = WindowConfig(
        "w1",
        (MemberConfig("cover.example_window", PROFILE),),
        schedule_workday_source=reference,
    )
    sunday = MONDAY + timedelta(days=6)

    sources = read_sources(hass, window_sources(config))

    assert day_type_from_inputs(config.schedule, sources, sunday) is DayType.WORKDAY
