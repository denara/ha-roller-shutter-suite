"""Partial settings, the resolver global → group → window, provenance, the mask."""

import dataclasses
from datetime import time, timedelta
from enum import StrEnum, unique
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    CapabilityState,
    CoveringType,
    JsonValue,
    MemberConfig,
    ScheduleProfile,
    TemperatureTier,
    WindowCapabilities,
    WindowCapabilityStates,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.model._data import (
    as_bool,
    as_enum,
    as_int,
    as_str,
    tuple_of,
)
from custom_components.roller_shutter_suite.core.settings import (
    INHERIT,
    STORED_NONE,
    WINDOW_IDENTITY_FIELDS,
    WINDOW_SETTINGS,
    Capability,
    CapabilityRequirement,
    GroupFallback,
    GroupFallbackReason,
    GroupLevel,
    Inherit,
    Level,
    MissingCapability,
    PartialSettings,
    ResolvedSettings,
    ResolvedValue,
    SettingDefinition,
    SettingError,
    SettingFault,
    SettingKind,
    SettingProblem,
    SettingsRegistry,
    resolve_settings,
    resolve_window,
    settings_from_stored,
)

LEFT = "cover.example_left"
RIGHT = "cover.example_right"
GROUP_ID = "group_example_south"

OWN_OFFSET = 30
DEFAULT_SHADING_POSITION = 40
DEFAULT_GLASS_HEIGHT = 100
OWN_GLASS_HEIGHT = 140


@unique
class ExampleMode(StrEnum):
    """An enumeration with one distinct value per level."""

    PLAIN = "plain"
    HOUSE = "house"
    SOUTH = "south"
    OWN = "own"


# The settings of block C01 contain no boolean, no number and nothing that
# requires a capability yet. The resolver is generic over the registry, so the
# tests bring a registry with one setting of every kind.
REGISTRY = SettingsRegistry(
    (
        SettingDefinition(
            key="enabled", kind=SettingKind.BOOLEAN, default=True, parse=as_bool
        ),
        SettingDefinition(
            key="offset", kind=SettingKind.NUMBER, default=5, parse=as_int
        ),
        SettingDefinition(
            key="mode",
            kind=SettingKind.ENUMERATION,
            default=ExampleMode.PLAIN,
            parse=as_enum(ExampleMode),
        ),
        SettingDefinition[str | None](
            key="source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            default=None,
            parse=as_str,
        ),
        SettingDefinition[tuple[str, ...]](
            key="lights",
            kind=SettingKind.LIST,
            default=("light.example_default",),
            parse=tuple_of(as_str),
        ),
        SettingDefinition(
            key="hold_to_move",
            kind=SettingKind.BOOLEAN,
            default=False,
            parse=as_bool,
            requires=CapabilityRequirement(Capability.SUPPORTS_STOP, False),
        ),
        SettingDefinition[int | None](
            key="shading_position",
            kind=SettingKind.NUMBER,
            default=DEFAULT_SHADING_POSITION,
            parse=as_int,
            requires=CapabilityRequirement(Capability.SUPPORTS_SET_POSITION, None),
        ),
        SettingDefinition(
            key="glass_height",
            kind=SettingKind.NUMBER,
            default=DEFAULT_GLASS_HEIGHT,
            parse=as_int,
            inheritable=False,
        ),
    )
)


def _member(member_id: str, **changes: Any) -> MemberConfig:
    arguments: dict[str, Any] = {
        "supports_open_close": True,
        "supports_set_position": True,
        "supports_stop": True,
        "reports_position": True,
        "travel_time_up": timedelta(seconds=24),
        "travel_time_down": timedelta(seconds=21),
    }
    return MemberConfig(member_id, CapabilityProfile(**(arguments | changes)))


FULL = (_member(LEFT),)
RIGHT_CANNOT_STOP = (_member(LEFT), _member(RIGHT, supports_stop=False))


def _resolve(
    *,
    house: PartialSettings | None = None,
    group: GroupLevel | None = None,
    window: PartialSettings | None = None,
    members: tuple[MemberConfig, ...] = FULL,
    registry: SettingsRegistry = REGISTRY,
) -> ResolvedSettings:
    return resolve_settings(
        registry,
        capabilities=WindowConfig("window_example", members).capability_states,
        members=members,
        global_settings=house or PartialSettings(),
        window_settings=window or PartialSettings(),
        group=group,
    )


# --- Set and inherit over three levels -------------------------------------------

# One distinct value per level, for a boolean, a number whose zero is valid, an
# enumeration, an optional source and a list. A boolean has two values only;
# there the provenance tells the levels apart.
VALUES: dict[str, dict[Level, Any]] = {
    "enabled": {
        Level.BUILT_IN: True,
        Level.GLOBAL: False,
        Level.GROUP: True,
        Level.WINDOW: False,
    },
    "offset": {Level.BUILT_IN: 5, Level.GLOBAL: 0, Level.GROUP: 7, Level.WINDOW: 3},
    "mode": {
        Level.BUILT_IN: ExampleMode.PLAIN,
        Level.GLOBAL: ExampleMode.HOUSE,
        Level.GROUP: ExampleMode.SOUTH,
        Level.WINDOW: ExampleMode.OWN,
    },
    "source": {
        Level.BUILT_IN: None,
        Level.GLOBAL: "sensor.example_house",
        Level.GROUP: "sensor.example_south",
        Level.WINDOW: "sensor.example_window",
    },
    "lights": {
        Level.BUILT_IN: ("light.example_default",),
        Level.GLOBAL: ("light.example_house",),
        Level.GROUP: (),
        Level.WINDOW: ("light.example_window",),
    },
}

# (the house sets, the group sets, the window sets) -> the level that wins
COMBINATIONS = [
    (False, False, False, Level.BUILT_IN),
    (True, False, False, Level.GLOBAL),
    (False, True, False, Level.GROUP),
    (True, True, False, Level.GROUP),
    (False, False, True, Level.WINDOW),
    (True, False, True, Level.WINDOW),
    (False, True, True, Level.WINDOW),
    (True, True, True, Level.WINDOW),
]


def _level(key: str, level: Level, is_set: bool) -> PartialSettings:
    return PartialSettings({key: VALUES[key][level]} if is_set else {})


@pytest.mark.parametrize("key", list(VALUES))
@pytest.mark.parametrize(
    ("house_sets", "group_sets", "window_sets", "winner"), COMBINATIONS
)
def test_strongest_level_that_sets_a_value_wins(
    key: str, house_sets: bool, group_sets: bool, window_sets: bool, winner: Level
) -> None:
    """Window beats group beats house beats built-in default, for every kind."""
    resolved = _resolve(
        house=_level(key, Level.GLOBAL, house_sets),
        group=GroupLevel(GROUP_ID, _level(key, Level.GROUP, group_sets)),
        window=_level(key, Level.WINDOW, window_sets),
    )

    assert resolved.valid
    assert resolved.group_fallback is None
    assert resolved.values[key] == ResolvedValue(
        key=key,
        value=VALUES[key][winner],
        effective=VALUES[key][winner],
        level=winner,
        group_id=GROUP_ID if winner is Level.GROUP else None,
    )


@pytest.mark.parametrize("key", list(VALUES))
@pytest.mark.parametrize(
    ("house_sets", "window_sets", "winner"),
    [
        (False, False, Level.BUILT_IN),
        (True, False, Level.GLOBAL),
        (False, True, Level.WINDOW),
        (True, True, Level.WINDOW),
    ],
)
def test_window_without_a_group_inherits_from_the_house_directly(
    key: str, house_sets: bool, window_sets: bool, winner: Level
) -> None:
    """No group is no fallback: there is nothing to report."""
    resolved = _resolve(
        house=_level(key, Level.GLOBAL, house_sets),
        window=_level(key, Level.WINDOW, window_sets),
    )

    assert resolved.valid
    assert resolved.group_fallback is None
    assert resolved.values[key].value == VALUES[key][winner]
    assert resolved.values[key].level is winner
    assert resolved.values[key].group_id is None


TRUTHY: dict[str, Any] = {
    "enabled": True,
    "offset": 60,
    "lights": ("light.example_other",),
    "source": "sensor.example_other",
}


@pytest.mark.parametrize(
    ("key", "falsy"),
    [("enabled", False), ("offset", 0), ("lights", ()), ("source", None)],
)
@pytest.mark.parametrize("level", [Level.GLOBAL, Level.GROUP, Level.WINDOW])
def test_falsy_values_are_set_values_at_every_level(
    key: str, falsy: Any, level: Level
) -> None:
    """``False``, ``0``, an empty list and a set ``None`` beat what lies below them."""
    order = [Level.GLOBAL, Level.GROUP, Level.WINDOW]
    parts = {
        other: PartialSettings(
            {key: falsy}
            if other is level
            else {key: TRUTHY[key]}
            if order.index(other) < order.index(level)
            else {}
        )
        for other in order
    }

    resolved = _resolve(
        house=parts[Level.GLOBAL],
        group=GroupLevel(GROUP_ID, parts[Level.GROUP]),
        window=parts[Level.WINDOW],
    )

    assert resolved.values[key].value == falsy
    assert type(resolved.values[key].value) is type(falsy)
    assert resolved.values[key].level is level


def test_falsy_built_in_default_is_a_value() -> None:
    """A default of zero is what a window gets when no level says anything."""
    registry = SettingsRegistry(
        (
            SettingDefinition(
                key="offset", kind=SettingKind.NUMBER, default=0, parse=as_int
            ),
        )
    )

    resolved = _resolve(registry=registry)

    assert resolved.values["offset"] == ResolvedValue(
        key="offset", value=0, effective=0, level=Level.BUILT_IN
    )


def test_window_returns_a_value_to_inherit_and_gets_the_groups_value_again() -> None:
    """Returning to "inherit" leaves no trace of the own value."""
    group = GroupLevel(GROUP_ID, PartialSettings({"offset": 0}))
    own = PartialSettings().with_value("offset", OWN_OFFSET)

    before = _resolve(group=group, window=own)
    after = _resolve(group=group, window=own.with_inherit("offset"))

    assert before.values["offset"].value == OWN_OFFSET
    assert before.values["offset"].level is Level.WINDOW
    assert after.values["offset"].value == 0
    assert after.values["offset"].level is Level.GROUP
    assert after.values["offset"].group_id == GROUP_ID
    assert own.with_inherit("offset") == PartialSettings()


def test_every_setting_of_the_registry_is_resolved_in_its_order() -> None:
    """The result is complete: one entry per setting, also for untouched ones."""
    resolved = _resolve()

    assert tuple(resolved.values) == REGISTRY.keys
    assert {item.level for item in resolved.values.values()} == {Level.BUILT_IN}
    assert resolved.effective() == {
        definition.key: definition.default for definition in REGISTRY.definitions
    }


# --- The marker and the partial settings -----------------------------------------


def test_inherit_is_a_marker_of_its_own() -> None:
    """It is not ``None``, not falsy by accident, and there is exactly one."""
    assert INHERIT is Inherit.INHERIT
    assert list(Inherit) == [INHERIT]
    assert INHERIT is not None
    assert PartialSettings().get("offset") is INHERIT
    assert PartialSettings({"source": None}).get("source") is None


def test_an_entry_with_the_marker_is_the_same_as_no_entry() -> None:
    """Partial settings compare by what they set."""
    assert PartialSettings({"offset": INHERIT, "enabled": False}) == PartialSettings(
        {"enabled": False}
    )
    assert "offset" not in PartialSettings({"offset": INHERIT}).values


def test_partial_settings_cannot_be_changed_afterwards() -> None:
    """The mapping is a copy and read-only; the type is not hashable."""
    source = {"offset": 0}
    partial = PartialSettings(source)
    source["offset"] = 50

    assert partial.get("offset") == 0
    with pytest.raises(TypeError):
        partial.values["offset"] = 50  # type: ignore[index]
    with pytest.raises(dataclasses.FrozenInstanceError):
        partial.values = {}  # type: ignore[misc]
    with pytest.raises(TypeError):
        hash(partial)


def test_with_value_replaces_a_fault_of_the_same_setting() -> None:
    """Setting a value repairs what could not be read; other faults stay."""
    partial = PartialSettings(
        faults=(SettingFault("offset", "broken"), SettingFault("mode", "broken"))
    )

    repaired = partial.with_value("offset", 0)

    assert repaired.get("offset") == 0
    assert repaired.faults == (SettingFault("mode", "broken"),)


@pytest.mark.parametrize(
    ("arguments", "error"),
    [
        ({"values": {"": 1}}, ValueError),
        ({"values": {1: 1}}, TypeError),
        ({"faults": ("offset",)}, TypeError),
        (
            {"values": {"offset": 1}, "faults": (SettingFault("offset", "x"),)},
            ValueError,
        ),
        (
            {"faults": (SettingFault("offset", "x"), SettingFault("offset", "y"))},
            ValueError,
        ),
    ],
)
def test_partial_settings_refuse_what_makes_no_sense(
    arguments: dict[str, Any], error: type[Exception]
) -> None:
    """Keys are identifiers, and a key is set, faulty or neither."""
    with pytest.raises(error):
        PartialSettings(**arguments)


@pytest.mark.parametrize(
    "build",
    [
        lambda: SettingFault("", "broken"),
        lambda: SettingFault("offset", ""),
        lambda: SettingDefinition(
            key="", kind=SettingKind.NUMBER, default=0, parse=as_int
        ),
        lambda: SettingDefinition(
            key="offset",
            kind="number",  # type: ignore[arg-type]
            default=0,
            parse=as_int,
        ),
        lambda: SettingFault("offset", "broken", "unreadable"),  # type: ignore[arg-type]
        lambda: SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            default=0,
            parse=as_int,
            inheritable=1,  # type: ignore[arg-type]
        ),
        lambda: SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            default=0,
            parse=as_int,
            requires=Capability.SUPPORTS_STOP,  # type: ignore[arg-type]
        ),
        lambda: CapabilityRequirement("supports_stop", False),  # type: ignore[arg-type]
        lambda: SettingsRegistry(("offset",)),  # type: ignore[arg-type]
        lambda: SettingsRegistry(
            (
                SettingDefinition(
                    key="offset", kind=SettingKind.NUMBER, default=0, parse=as_int
                ),
                SettingDefinition(
                    key="offset", kind=SettingKind.NUMBER, default=1, parse=as_int
                ),
            )
        ),
        lambda: GroupLevel("", PartialSettings()),
        lambda: GroupLevel(GROUP_ID, {}),  # type: ignore[arg-type]
    ],
)
def test_descriptions_validate_themselves(build: Any) -> None:
    """A registry, a definition or a group level that exists is well-formed."""
    with pytest.raises((TypeError, ValueError)):
        build()


# --- From stored data ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ({}, {}),
        ({"offset": 0}, {"offset": 0}),
        ({"enabled": False}, {"enabled": False}),
        ({"lights": []}, {"lights": ()}),
        ({"source": ""}, {}),
        ({"mode": ""}, {}),
        ({"source": "sensor.example"}, {"source": "sensor.example"}),
        ({"mode": "south"}, {"mode": ExampleMode.SOUTH}),
        ({"offset": 7, "covers": [LEFT], "group_id": GROUP_ID}, {"offset": 7}),
    ],
)
def test_absent_key_means_inherit_and_falsy_values_are_set(
    stored: dict[str, JsonValue], expected: dict[str, object]
) -> None:
    """Only an absent key and an empty string are "inherit"; foreign keys are left."""
    partial = settings_from_stored(stored, REGISTRY)

    assert partial == PartialSettings(expected)
    assert partial.faults == ()


@pytest.mark.parametrize(
    ("stored", "detail"),
    [
        ({"offset": None}, "null is not a stored value"),
        ({"source": None}, "null is not a stored value"),
        ({"offset": "7"}, "expected an integer"),
        ({"offset": True}, "expected an integer"),
        ({"enabled": 0}, "expected true or false"),
        ({"mode": "unheard_of"}, "unheard_of"),
        ({"lights": "light.example"}, "expected a list"),
    ],
)
def test_value_that_cannot_be_read_is_a_fault_and_not_set(
    stored: dict[str, JsonValue], detail: str
) -> None:
    """``null`` is no second way to say "inherit", and nothing is guessed."""
    partial = settings_from_stored(stored, REGISTRY)

    (key,) = stored
    assert partial.values == {}
    assert [fault.key for fault in partial.faults] == [key]
    assert detail in partial.faults[0].detail


# --- "Explicitly none" for an optional reference --------------------------------


def test_marker_for_none_is_one_documented_string() -> None:
    """The stored form is fixed; forms and stored data rely on it."""
    assert STORED_NONE == "__none__"


def test_window_says_none_although_its_group_names_a_source() -> None:
    """The marker is a set value: it beats the group, and the provenance is "window"."""
    group = settings_from_stored({"source": "sensor.example_south"}, REGISTRY)
    window = settings_from_stored({"source": STORED_NONE}, REGISTRY)

    resolved = _resolve(
        house=PartialSettings({"source": "sensor.example_house"}),
        group=GroupLevel(GROUP_ID, group),
        window=window,
    )

    assert window == PartialSettings({"source": None})
    assert resolved.valid
    assert resolved.values["source"] == ResolvedValue(
        key="source", value=None, effective=None, level=Level.WINDOW
    )


def test_group_says_none_and_a_window_can_still_name_a_source() -> None:
    """On group level the marker beats the house; a window's own value beats it."""
    house = PartialSettings({"source": "sensor.example_house"})
    group = GroupLevel(
        GROUP_ID, settings_from_stored({"source": STORED_NONE}, REGISTRY)
    )

    inherited = _resolve(house=house, group=group)
    own = _resolve(
        house=house,
        group=group,
        window=settings_from_stored({"source": "sensor.example_window"}, REGISTRY),
    )

    assert inherited.group_fallback is None
    assert inherited.values["source"].value is None
    assert inherited.values["source"].level is Level.GROUP
    assert inherited.values["source"].group_id == GROUP_ID
    assert own.values["source"].value == "sensor.example_window"
    assert own.values["source"].level is Level.WINDOW


@pytest.mark.parametrize("key", ["enabled", "offset", "mode", "lights"])
def test_marker_for_none_on_another_kind_of_setting_is_a_fault(key: str) -> None:
    """A switch, a number, a choice and a list always have a value."""
    partial = settings_from_stored({key: STORED_NONE}, REGISTRY)

    assert partial.values == {}
    assert [(fault.key, fault.problem) for fault in partial.faults] == [
        (key, SettingProblem.NONE_NOT_ALLOWED)
    ]
    assert "optional reference only" in partial.faults[0].detail

    resolved = _resolve(window=partial)

    assert [(error.key, error.level, error.problem) for error in resolved.errors] == [
        (key, Level.WINDOW, SettingProblem.NONE_NOT_ALLOWED)
    ]


def test_null_stays_a_fault_and_an_absent_key_still_inherits() -> None:
    """The marker is the only way to say "none"; nothing else changed."""
    with_null = settings_from_stored({"source": None}, REGISTRY)
    absent = settings_from_stored({}, REGISTRY)

    assert [(fault.key, fault.problem) for fault in with_null.faults] == [
        ("source", SettingProblem.UNREADABLE)
    ]
    assert absent.get("source") is INHERIT

    resolved = _resolve(
        group=GroupLevel(GROUP_ID, PartialSettings({"source": "sensor.example_south"})),
        window=absent,
    )

    assert resolved.values["source"].value == "sensor.example_south"
    assert resolved.values["source"].level is Level.GROUP


def test_marker_never_reaches_the_window_configuration_as_a_string() -> None:
    """The morning condition of a window is switched off although the group has one."""
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings(),
        group=GroupLevel(
            GROUP_ID,
            settings_from_stored(
                {"morning_condition_source": "binary_sensor.example_south"},
                WINDOW_SETTINGS,
            ),
        ),
        window_settings=settings_from_stored(
            {"morning_condition_source": STORED_NONE}, WINDOW_SETTINGS
        ),
    )

    assert resolution.config is not None
    assert resolution.config.morning_condition_source is None
    item = resolution.settings.values["morning_condition_source"]
    assert item.level is Level.WINDOW
    assert STORED_NONE not in [
        str(value) for value in resolution.settings.effective().values()
    ]


def _as_day_of_year(value: JsonValue) -> tuple[int, int]:
    month, day = as_str(value).split("-")
    return int(month), int(day)


SCHEDULE_KINDS = SettingsRegistry(
    (
        SettingDefinition(
            key="morning_time",
            kind=SettingKind.TIME,
            default=time(7, 0),
            parse=lambda value: time.fromisoformat(as_str(value)),
        ),
        SettingDefinition(
            key="delay",
            kind=SettingKind.DURATION,
            default=timedelta(0),
            parse=lambda value: timedelta(seconds=as_int(value)),
        ),
        SettingDefinition(
            key="summer_begins",
            kind=SettingKind.DAY_OF_YEAR,
            default=(5, 1),
            parse=_as_day_of_year,
        ),
    )
)


def test_time_duration_and_day_of_year_are_read_in_their_stored_forms() -> None:
    """The kinds exist for the schedule; zero seconds is a set duration."""
    partial = settings_from_stored(
        {"morning_time": "06:30", "delay": 0, "summer_begins": "06-15"},
        SCHEDULE_KINDS,
    )

    assert partial == PartialSettings(
        {
            "morning_time": time(6, 30),
            "delay": timedelta(0),
            "summer_begins": (6, 15),
        }
    )


@pytest.mark.parametrize("key", ["morning_time", "delay", "summer_begins"])
def test_marker_for_none_on_a_time_a_duration_or_a_day_of_year_is_a_fault(
    key: str,
) -> None:
    """A time of day, a duration and a day of the year always have a value."""
    partial = settings_from_stored({key: STORED_NONE}, SCHEDULE_KINDS)

    assert partial.values == {}
    assert [(fault.key, fault.problem) for fault in partial.faults] == [
        (key, SettingProblem.NONE_NOT_ALLOWED)
    ]


def test_kinds_are_the_documented_ones() -> None:
    """A new kind is a decision: it needs a documented stored form."""
    assert [kind.value for kind in SettingKind] == [
        "boolean",
        "number",
        "enumeration",
        "list",
        "time",
        "duration",
        "day_of_year",
        "optional_reference",
    ]


def test_only_the_optional_reference_of_the_window_accepts_the_marker() -> None:
    """The kinds of the window's settings are declared in the registry."""
    kinds = {
        definition.key: definition.kind for definition in WINDOW_SETTINGS.definitions
    }

    assert kinds == {
        "covering_type": SettingKind.ENUMERATION,
        "morning_condition_source": SettingKind.OPTIONAL_REFERENCE,
        "shading_temperature_tiers": SettingKind.LIST,
        "schedule_profile": SettingKind.ENUMERATION,
    }
    partial = settings_from_stored(
        {"schedule_profile": STORED_NONE, "covering_type": STORED_NONE},
        WINDOW_SETTINGS,
    )
    assert sorted(fault.key for fault in partial.faults) == [
        "covering_type",
        "schedule_profile",
    ]


# --- Validation errors name the field and the level --------------------------------


@pytest.mark.parametrize("level", [Level.GLOBAL, Level.WINDOW])
def test_unreadable_value_of_house_or_window_is_an_error_of_that_level(
    level: Level,
) -> None:
    """The error names the key and the level whose stored data is broken."""
    broken = settings_from_stored({"offset": "many"}, REGISTRY)

    resolved = _resolve(
        house=broken if level is Level.GLOBAL else None,
        window=broken if level is Level.WINDOW else None,
    )

    assert not resolved.valid
    assert resolved.errors == (
        SettingError(
            "offset",
            level,
            SettingProblem.UNREADABLE,
            "expected an integer",
        ),
    )
    assert resolved.values["offset"].level is Level.BUILT_IN


@pytest.mark.parametrize(
    ("level", "group_id"), [(Level.GLOBAL, None), (Level.GROUP, GROUP_ID)]
)
def test_setting_that_cannot_be_inherited_is_refused_above_the_window(
    level: Level, group_id: str | None
) -> None:
    """A measurement of a window is read from the window alone."""
    above = PartialSettings({"glass_height": OWN_GLASS_HEIGHT})

    resolved = _resolve(
        house=above if level is Level.GLOBAL else None,
        group=GroupLevel(GROUP_ID, above) if level is Level.GROUP else None,
    )

    assert [
        (error.key, error.level, error.problem, error.group_id)
        for error in resolved.errors
    ] == [("glass_height", level, SettingProblem.NOT_INHERITABLE, group_id)]
    assert resolved.values["glass_height"].value == DEFAULT_GLASS_HEIGHT
    assert resolved.values["glass_height"].level is Level.BUILT_IN


def test_setting_that_cannot_be_inherited_is_set_by_the_window() -> None:
    """The window's own value applies, with the usual provenance."""
    resolved = _resolve(window=PartialSettings({"glass_height": OWN_GLASS_HEIGHT}))

    assert resolved.valid
    assert resolved.values["glass_height"].value == OWN_GLASS_HEIGHT
    assert resolved.values["glass_height"].level is Level.WINDOW


def test_key_the_registry_does_not_know_is_an_error_of_its_level() -> None:
    """Partial settings built in code cannot smuggle in a setting nobody described."""
    resolved = _resolve(group=GroupLevel(GROUP_ID, PartialSettings({"offse": 7})))

    assert [
        (error.key, error.level, error.problem, error.group_id)
        for error in resolved.errors
    ] == [("offse", Level.GROUP, SettingProblem.UNKNOWN_SETTING, GROUP_ID)]
    assert "offse" not in resolved.values


# --- A group reference that leads nowhere -----------------------------------------


def test_group_that_no_longer_exists_falls_back_to_the_house() -> None:
    """The window inherits from the house, and the result says why."""
    resolved = _resolve(
        house=PartialSettings({"offset": 0}),
        group=GroupLevel(GROUP_ID, None),
        window=PartialSettings({"enabled": False}),
    )

    assert resolved.valid
    assert resolved.group_fallback == GroupFallback(
        GROUP_ID, GroupFallbackReason.GROUP_MISSING
    )
    assert resolved.values["offset"].value == 0
    assert resolved.values["offset"].level is Level.GLOBAL
    assert resolved.values["enabled"].level is Level.WINDOW
    assert resolved.values["mode"].level is Level.BUILT_IN


def test_group_with_faulty_data_falls_back_to_the_house_as_a_whole() -> None:
    """Nothing of a group that cannot be read is used, not even its good values."""
    group = settings_from_stored({"offset": "many", "mode": "south"}, REGISTRY)

    resolved = _resolve(
        house=PartialSettings({"mode": ExampleMode.HOUSE}),
        group=GroupLevel(GROUP_ID, group),
    )

    assert resolved.valid
    assert resolved.group_fallback == GroupFallback(
        GROUP_ID,
        GroupFallbackReason.GROUP_DATA_FAULTY,
        (SettingFault("offset", "expected an integer"),),
    )
    assert resolved.values["mode"].value is ExampleMode.HOUSE
    assert resolved.values["mode"].level is Level.GLOBAL
    assert resolved.values["offset"].level is Level.BUILT_IN


def test_dangling_group_of_one_window_does_not_stop_the_others() -> None:
    """Three windows are resolved in a row; the middle one lost its group."""
    house = PartialSettings({"offset": 10})
    south = GroupLevel(GROUP_ID, PartialSettings({"offset": 60}))
    gone = GroupLevel("group_example_removed", None)

    results = [
        _resolve(house=house, group=group) for group in (south, gone, south, None)
    ]

    assert [result.values["offset"].value for result in results] == [60, 10, 60, 10]
    assert [result.group_fallback is not None for result in results] == [
        False,
        True,
        False,
        False,
    ]
    assert all(result.valid for result in results)


# --- The capability mask -----------------------------------------------------------

CAN_STOP = (_member(LEFT), _member(RIGHT))
# Nothing was ever known about a member: no flag claims anything. A member
# that is merely unreachable is handed in with its last known flags, as known.
NEVER_SEEN: dict[str, Any] = {
    "supports_open_close": False,
    "supports_set_position": False,
    "supports_stop": False,
    "reports_position": False,
    "capabilities_known": False,
}
RIGHT_UNKNOWN = (_member(LEFT), _member(RIGHT, **NEVER_SEEN))
MISSING_STOP = MissingCapability(Capability.SUPPORTS_STOP, (RIGHT,))


def test_capabilities_are_the_fields_of_the_window_capabilities() -> None:
    """A setting can require exactly what the model knows about a window."""
    names = [capability.value for capability in Capability]

    assert names == [field.name for field in dataclasses.fields(WindowCapabilities)]
    assert names == [field.name for field in dataclasses.fields(WindowCapabilityStates)]


def _hold_to_move_set_by(level: Level) -> dict[str, Any]:
    own = PartialSettings({"hold_to_move": True})
    return {
        "house": own if level is Level.GLOBAL else None,
        "group": GroupLevel(
            GROUP_ID, own if level is Level.GROUP else PartialSettings()
        ),
        "window": own if level is Level.WINDOW else None,
    }


@pytest.mark.parametrize("level", [Level.GLOBAL, Level.GROUP, Level.WINDOW])
@pytest.mark.parametrize(
    ("members", "state", "effective", "unavailable"),
    [
        (CAN_STOP, CapabilityState.PRESENT, True, None),
        (RIGHT_CANNOT_STOP, CapabilityState.MISSING, False, MISSING_STOP),
        (RIGHT_UNKNOWN, CapabilityState.UNKNOWN, True, None),
    ],
)
def test_present_missing_and_unknown_for_inherited_and_own_values(
    level: Level,
    members: tuple[MemberConfig, ...],
    state: CapabilityState,
    effective: bool,
    unavailable: MissingCapability | None,
) -> None:
    """Only "missing" masks; the provenance stays; nothing here is an error."""
    resolved = _resolve(members=members, **_hold_to_move_set_by(level))

    item = resolved.values["hold_to_move"]
    assert resolved.valid
    assert item == ResolvedValue(
        key="hold_to_move",
        value=True,
        effective=effective,
        level=level,
        group_id=GROUP_ID if level is Level.GROUP else None,
        capability=state,
        unavailable=unavailable,
    )
    assert item.available is (unavailable is None)
    assert resolved.effective()["hold_to_move"] is effective
    reported = level is Level.WINDOW and state is CapabilityState.MISSING
    assert item.own_value_masked is reported
    assert resolved.masked_own_values == ((item,) if reported else ())


def test_setting_without_a_requirement_has_no_capability_state() -> None:
    """Nothing is claimed about a capability nobody asked for."""
    resolved = _resolve(members=RIGHT_CANNOT_STOP)

    assert resolved.values["offset"].capability is None
    assert resolved.values["offset"].available


def test_built_in_default_is_masked_too_and_every_limiting_member_is_named() -> None:
    """The arbiter never gets a shading position for covers without set position."""
    members = (
        _member(LEFT, supports_set_position=False),
        _member(RIGHT, supports_set_position=False),
    )

    resolved = _resolve(members=members)

    item = resolved.values["shading_position"]
    assert resolved.valid
    assert item.value == DEFAULT_SHADING_POSITION
    assert item.effective is None
    assert item.level is Level.BUILT_IN
    assert item.unavailable == MissingCapability(
        Capability.SUPPORTS_SET_POSITION, (LEFT, RIGHT)
    )
    assert resolved.masked_own_values == ()
    assert resolved.values["hold_to_move"].capability is CapabilityState.PRESENT


@pytest.mark.parametrize(
    ("members", "state", "limiting"),
    [
        (
            (
                _member(LEFT),
                _member(RIGHT, **NEVER_SEEN),
                _member("cover.example_third", supports_stop=False),
            ),
            CapabilityState.MISSING,
            ("cover.example_third",),
        ),
        (
            (_member(LEFT, supports_stop=False), _member(RIGHT, **NEVER_SEEN)),
            CapabilityState.MISSING,
            (LEFT,),
        ),
        (RIGHT_UNKNOWN, CapabilityState.UNKNOWN, None),
        (CAN_STOP, CapabilityState.PRESENT, None),
    ],
)
def test_with_several_members_missing_beats_unknown_beats_present(
    members: tuple[MemberConfig, ...],
    state: CapabilityState,
    limiting: tuple[str, ...] | None,
) -> None:
    """Only members that definitely lack the capability are named as limiting."""
    resolved = _resolve(window=PartialSettings({"hold_to_move": True}), members=members)

    item = resolved.values["hold_to_move"]
    assert item.capability is state
    if limiting is None:
        assert item.unavailable is None
    else:
        assert item.unavailable == MissingCapability(Capability.SUPPORTS_STOP, limiting)


def test_own_value_survives_a_missing_capability_and_applies_again() -> None:
    """The cover is replaced by one that cannot stop, and later by one that can."""
    own = PartialSettings({"hold_to_move": True})

    before = _resolve(window=own, members=CAN_STOP)
    during = _resolve(window=own, members=RIGHT_CANNOT_STOP)
    after = _resolve(window=own, members=CAN_STOP)

    assert before.values["hold_to_move"].effective is True
    assert during.valid
    assert during.values["hold_to_move"].value is True
    assert during.values["hold_to_move"].effective is False
    assert during.values["hold_to_move"].level is Level.WINDOW
    assert [item.key for item in during.masked_own_values] == ["hold_to_move"]
    assert during.masked_own_values[0].unavailable == MISSING_STOP
    assert own.get("hold_to_move") is True
    assert after == before
    assert after.masked_own_values == ()


@pytest.mark.parametrize("level", [Level.GROUP, Level.WINDOW])
def test_mask_and_report_stay_while_the_entity_is_unavailable(level: Level) -> None:
    """The last known "cannot stop" is handed in as known: nothing flaps.

    While the entity of the right member is unavailable, the Home Assistant
    layer builds its profile from the last known capabilities. For the
    resolver the three steps are therefore the same input, and the result is
    identical at every step: masked, and reported for an own value.
    """
    last_known = (_member(LEFT), _member(RIGHT, supports_stop=False))
    sequence = [
        _resolve(members=members, **_hold_to_move_set_by(level))
        for members in (RIGHT_CANNOT_STOP, last_known, RIGHT_CANNOT_STOP)
    ]

    assert sequence[0] == sequence[1] == sequence[2]
    for result in sequence:
        item = result.values["hold_to_move"]
        assert result.valid
        assert item.capability is CapabilityState.MISSING
        assert item.unavailable == MISSING_STOP
        assert item.effective is False
        assert result.masked_own_values == ((item,) if level is Level.WINDOW else ())


@pytest.mark.parametrize("level", [Level.GROUP, Level.WINDOW])
def test_present_unknown_present_never_reports(level: Level) -> None:
    """Present, unknown, present: never masked, never reported, never an error."""
    sequence = [
        _resolve(members=members, **_hold_to_move_set_by(level))
        for members in (CAN_STOP, RIGHT_UNKNOWN, CAN_STOP)
    ]

    assert [result.values["hold_to_move"].capability for result in sequence] == [
        CapabilityState.PRESENT,
        CapabilityState.UNKNOWN,
        CapabilityState.PRESENT,
    ]
    for result in sequence:
        assert result.valid
        assert result.masked_own_values == ()
        assert result.values["hold_to_move"].available
        assert result.values["hold_to_move"].effective is True


def test_window_with_a_masked_own_value_keeps_a_valid_result() -> None:
    """Mask and report, never withhold: the other settings resolve as usual."""
    resolved = _resolve(
        house=PartialSettings({"offset": 0}),
        window=PartialSettings({"hold_to_move": True, "shading_position": 0}),
        members=RIGHT_CANNOT_STOP,
    )

    assert resolved.valid
    assert resolved.errors == ()
    assert resolved.values["offset"].value == 0
    assert resolved.values["shading_position"].effective == 0
    assert [item.key for item in resolved.masked_own_values] == ["hold_to_move"]


# --- The settings of a window ------------------------------------------------------


def test_registry_of_the_window_covers_every_field_of_the_window_configuration() -> (
    None
):
    """A field without an entry, or an entry without a field, fails here.

    The failure says what to add where; see ``_registry_mismatches``.
    """
    defaults = WindowConfig("window_example", FULL)
    mismatches = _registry_mismatches(
        fields={
            field.name: getattr(defaults, field.name)
            for field in dataclasses.fields(WindowConfig)
            if field.name not in WINDOW_IDENTITY_FIELDS
        },
        entries={
            definition.key: definition.default
            for definition in WINDOW_SETTINGS.definitions
        },
    )

    assert not mismatches, "\n".join(mismatches)
    assert set(WINDOW_IDENTITY_FIELDS) <= {
        field.name for field in dataclasses.fields(WindowConfig)
    }


def _registry_mismatches(
    *, fields: dict[str, object], entries: dict[str, object]
) -> list[str]:
    """Compare the fields of ``WindowConfig`` with the registry, with advice."""
    settings_module = "custom_components/roller_shutter_suite/core/settings.py"
    window_module = "custom_components/roller_shutter_suite/core/model/window.py"
    messages = [
        f"WindowConfig has the field {name!r}, but WINDOW_SETTINGS has no entry for "
        f"it. Add SettingDefinition(key={name!r}, kind=SettingKind.<kind>, "
        f"default={default!r}, parse=<reader of the stored value>) to "
        f"WINDOW_SETTINGS in {settings_module}. Only if the caller hands the field "
        f"in and it is never stored as a setting, add {name!r} to "
        f"WINDOW_IDENTITY_FIELDS there instead."
        for name, default in fields.items()
        if name not in entries
    ]
    messages += [
        f"WINDOW_SETTINGS has the entry {key!r}, but WindowConfig has no field of "
        f"that name. Add the field {key!r} with the default {default!r} to "
        f"WindowConfig in {window_module} (the key of an entry is the name of its "
        f"field), or remove the entry from WINDOW_SETTINGS in {settings_module}."
        for key, default in entries.items()
        if key not in fields
    ]
    messages += [
        f"The setting {key!r} has two different defaults: {entries[key]!r} in "
        f"WINDOW_SETTINGS ({settings_module}) and {default!r} in WindowConfig "
        f"({window_module}). Make them the same value."
        for key, default in fields.items()
        if key in entries and entries[key] != default
    ]
    return messages


def test_mismatch_between_registry_and_window_configuration_says_what_to_add() -> None:
    """A contributor who forgot one half reads where the other half goes."""
    messages = _registry_mismatches(
        fields={"morning_position": 100, "evening_position": 0},
        entries={"evening_position": 10, "night_position": 0},
    )

    missing_entry, missing_field, different_defaults = messages
    assert "SettingDefinition(key='morning_position'" in missing_entry
    assert "WINDOW_SETTINGS in custom_components" in missing_entry
    assert "WINDOW_IDENTITY_FIELDS" in missing_entry
    assert "Add the field 'night_position'" in missing_field
    assert "core/model/window.py" in missing_field
    assert "'evening_position' has two different defaults: 10" in different_defaults


def test_only_the_covering_type_cannot_be_inherited() -> None:
    """What cannot be inherited is marked in the registry and nowhere else."""
    marked = [
        definition.key
        for definition in WINDOW_SETTINGS.definitions
        if not definition.inheritable
    ]

    assert marked == ["covering_type"]


def test_window_is_resolved_from_stored_data_of_three_levels() -> None:
    """House, group and window each contribute; the rest is built in."""
    house = settings_from_stored(
        {
            "morning_condition_source": "binary_sensor.example_house",
            "shading_temperature_tiers": [{"threshold": 24, "hysteresis": 1.5}],
        },
        WINDOW_SETTINGS,
    )
    group = settings_from_stored(
        {"morning_condition_source": "binary_sensor.example_south"}, WINDOW_SETTINGS
    )
    window = settings_from_stored(
        {
            "covering_type": "roller_shutter",
            "shading_temperature_tiers": [],
            "covers": [LEFT, RIGHT],
        },
        WINDOW_SETTINGS,
    )

    resolution = resolve_window(
        window_id="window_example",
        members=[_member(LEFT), _member(RIGHT)],
        global_settings=house,
        group=GroupLevel(GROUP_ID, group),
        window_settings=window,
    )

    assert resolution.settings.valid
    assert resolution.config == WindowConfig(
        window_id="window_example",
        members=(_member(LEFT), _member(RIGHT)),
        covering_type=CoveringType.ROLLER_SHUTTER,
        morning_condition_source="binary_sensor.example_south",
        shading_temperature_tiers=(),
        schedule_profile=ScheduleProfile.DEFAULT,
    )
    assert {key: item.level for key, item in resolution.settings.values.items()} == {
        "covering_type": Level.WINDOW,
        "morning_condition_source": Level.GROUP,
        "shading_temperature_tiers": Level.WINDOW,
        "schedule_profile": Level.BUILT_IN,
    }
    assert house.get("shading_temperature_tiers") == (TemperatureTier(24.0, 1.5),)


@pytest.mark.parametrize(
    ("tiers", "detail"),
    [
        ([{"threshold": True, "hysteresis": 1}], "threshold: expected a number"),
        ([{"threshold": 24}], "the key 'hysteresis' is missing"),
        ([{"threshold": 24, "hysteresis": 1, "extra": 0}], "unknown key 'extra'"),
        ([{"threshold": 24, "hysteresis": -1}], "must not be negative"),
        ({"threshold": 24, "hysteresis": 1}, "expected a list"),
    ],
)
def test_temperature_tier_that_cannot_be_read_is_a_fault(
    tiers: JsonValue, detail: str
) -> None:
    """The model's own validation speaks through the fault."""
    partial = settings_from_stored(
        {"shading_temperature_tiers": tiers}, WINDOW_SETTINGS
    )

    assert partial.values == {}
    assert detail in partial.faults[0].detail


def test_value_the_window_configuration_refuses_names_field_and_level() -> None:
    """Two tiers come from the group; the error says so and no configuration exists."""
    tiers = (TemperatureTier(24.0, 1.0), TemperatureTier(28.0, 1.0))

    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings({"morning_condition_source": ""}),
        group=GroupLevel(
            GROUP_ID, PartialSettings({"shading_temperature_tiers": tiers})
        ),
        window_settings=PartialSettings(),
    )

    assert resolution.config is None
    assert [
        (error.key, error.level, error.problem, error.group_id)
        for error in resolution.settings.errors
    ] == [
        ("morning_condition_source", Level.GLOBAL, SettingProblem.INVALID, None),
        ("shading_temperature_tiers", Level.GROUP, SettingProblem.INVALID, GROUP_ID),
    ]
    assert "more than one temperature tier" in resolution.settings.errors[1].detail


def test_errors_of_the_levels_leave_the_window_without_a_configuration() -> None:
    """An unreadable own value is reported; the provenance is still there."""
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings(),
        window_settings=settings_from_stored(
            {"schedule_profile": "holiday_home"}, WINDOW_SETTINGS
        ),
    )

    assert resolution.config is None
    assert [
        (error.key, error.level, error.problem) for error in resolution.settings.errors
    ] == [("schedule_profile", Level.WINDOW, SettingProblem.UNREADABLE)]
    assert resolution.settings.values["schedule_profile"].level is Level.BUILT_IN


def test_window_with_a_dangling_group_still_gets_its_configuration() -> None:
    """The fallback is reported next to a complete configuration."""
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings(
            {"morning_condition_source": "binary_sensor.example_house"}
        ),
        group=GroupLevel(GROUP_ID, None),
        window_settings=PartialSettings(),
    )

    assert resolution.config is not None
    assert resolution.config.morning_condition_source == "binary_sensor.example_house"
    assert resolution.settings.group_fallback == GroupFallback(
        GROUP_ID, GroupFallbackReason.GROUP_MISSING
    )


@pytest.mark.parametrize(
    ("window_id", "members", "key"),
    [
        ("window_example", (), "members"),
        ("window_example", (_member(LEFT), _member(LEFT)), "members"),
        ("window_example", None, "members"),
        ("", FULL, "window_id"),
        (None, FULL, "window_id"),
    ],
)
def test_identity_the_model_refuses_is_an_error_and_not_an_exception(
    window_id: Any, members: Any, key: str
) -> None:
    """A window without a cover must not stop the windows next to it."""
    resolution = resolve_window(
        window_id=window_id,
        members=members,
        global_settings=PartialSettings(),
        window_settings=PartialSettings(),
    )

    assert resolution.config is None
    assert resolution.settings.values == {}
    assert [
        (error.key, error.level, error.problem) for error in resolution.settings.errors
    ] == [(key, Level.WINDOW, SettingProblem.INVALID)]
