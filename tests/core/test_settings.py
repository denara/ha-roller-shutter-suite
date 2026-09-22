"""Partial settings, the resolver global → group → window, provenance, the mask."""

import dataclasses
from collections.abc import Mapping
from datetime import time, timedelta
from enum import StrEnum, unique
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    CapabilityState,
    CoveringType,
    FaultBehavior,
    FunctionId,
    JsonValue,
    MemberConfig,
    ScheduleProfile,
    SettingsCombinationError,
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
    MAX_DURATION_SECONDS,
    STORED_NONE,
    WINDOW_FIELDS_THAT_ARE_NO_SETTINGS,
    WINDOW_IDENTITY_FIELDS,
    WINDOW_SETTINGS,
    Capability,
    CapabilityRequirement,
    FaultAction,
    GroupLevel,
    GroupMissing,
    Inherit,
    Level,
    MissingCapability,
    PartialSettings,
    ReportedFault,
    ResolvedSettings,
    ResolvedValue,
    SettingDefinition,
    SettingFault,
    SettingKind,
    SettingProblem,
    SettingRules,
    SettingsRegistry,
    as_day_of_year,
    as_duration,
    as_time,
    functions_with_settings,
    resolve_settings,
    resolve_window,
    settings_from_stored,
)

LEFT = "cover.example_left"
RIGHT = "cover.example_right"
GROUP_ID = "group_example_south"

OWN_OFFSET = 30
DEFAULT_FROST_POSITION = 90
DEFAULT_VENTILATION_POSITION = 30
# The fault values of the settings that fall back differ from their defaults
# here, so that every test shows which of the two built-in values applied.
CAUTIOUS_FROST_POSITION = 75
CAUTIOUS_VENTILATION_POSITION = 35
CAUTIOUS_SOURCE = "blind"
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
            key="enabled",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.SCHEDULE,
            default=True,
            parse=as_bool,
        ),
        SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            function=FunctionId.SCHEDULE,
            default=5,
            parse=as_int,
        ),
        SettingDefinition(
            key="mode",
            kind=SettingKind.ENUMERATION,
            function=FunctionId.SHADING,
            default=ExampleMode.PLAIN,
            parse=as_enum(ExampleMode),
        ),
        SettingDefinition[str | None](
            key="source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            function=FunctionId.FROST,
            default=None,
            fault_value=CAUTIOUS_SOURCE,
            parse=as_str,
        ),
        SettingDefinition[tuple[str, ...]](
            key="lights",
            kind=SettingKind.LIST,
            function=FunctionId.PRIVACY,
            default=("light.example_default",),
            parse=tuple_of(as_str),
        ),
        SettingDefinition(
            key="hold_to_move",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.REQUEST,
            default=False,
            parse=as_bool,
            requires=CapabilityRequirement(Capability.SUPPORTS_STOP, False),
        ),
        SettingDefinition[int | None](
            key="shading_position",
            kind=SettingKind.NUMBER,
            function=FunctionId.SHADING,
            default=DEFAULT_SHADING_POSITION,
            parse=as_int,
            requires=CapabilityRequirement(Capability.SUPPORTS_SET_POSITION, None),
        ),
        SettingDefinition(
            key="frost_position",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=DEFAULT_FROST_POSITION,
            fault_value=CAUTIOUS_FROST_POSITION,
            parse=as_int,
        ),
        SettingDefinition(
            key="ventilation_position",
            kind=SettingKind.NUMBER,
            function=FunctionId.VENTILATION,
            default=DEFAULT_VENTILATION_POSITION,
            fault_value=CAUTIOUS_VENTILATION_POSITION,
            parse=as_int,
        ),
        SettingDefinition(
            key="glass_height",
            kind=SettingKind.NUMBER,
            function=FunctionId.SHADING,
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


MAX_POSITION = 100
LONELY_OFFSET = 99


def _check_value(key: str, value: object) -> None:
    """Refuse a number outside 0 to 100, as a window configuration would."""
    if (
        key in {"offset", "shading_position", "frost_position", "ventilation_position"}
        and isinstance(value, int)
        and not 0 <= value <= MAX_POSITION
    ):
        raise ValueError(f"{key} must be within 0 and 100")


UNDECLARED = "undeclared"


def _build(
    effective: Mapping[str, Any], disabled: frozenset[FunctionId]
) -> dict[str, Any]:
    """Refuse some combinations: rules that span several settings.

    Each rule names the keys it concerns, as the contract of the model asks:

    - two functions that pause: the mode "own" needs an offset;
    - one function that falls back: a frost position of zero needs a source;
    - one of each: an offset of 99 does not go with a ventilation position of 1.

    And one rule that breaks the contract and names nothing.
    """
    if effective.get("mode") is ExampleMode.OWN and effective.get("offset") == 0:
        raise SettingsCombinationError(
            "the mode 'own' needs an offset", ("mode", "offset")
        )
    if effective.get("frost_position") == 0 and effective.get("source") is None:
        raise SettingsCombinationError(
            "a frost position of zero needs a frost source",
            ("frost_position", "source"),
        )
    if (
        effective.get("offset") == LONELY_OFFSET
        and effective.get("ventilation_position") == 1
    ):
        raise SettingsCombinationError(
            "this offset does not go with this ventilation position",
            ("offset", "ventilation_position"),
        )
    if UNDECLARED in (effective.get("lights") or ()):
        raise ValueError("a rule that names no keys")
    if effective.get("source") == UNDECLARED:
        raise ValueError("another rule that names no keys")
    return dict(effective) | {"disabled_functions": disabled}


RULES = SettingRules(_check_value, _build)


def _resolve(  # noqa: PLR0913 - one argument per input of the resolver
    *,
    house: PartialSettings | None = None,
    group: GroupLevel | None = None,
    window: PartialSettings | None = None,
    members: tuple[MemberConfig, ...] = FULL,
    registry: SettingsRegistry = REGISTRY,
    rules: SettingRules | None = RULES,
) -> ResolvedSettings:
    return resolve_settings(
        registry,
        rules=rules,
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

    assert resolved.faults == ()
    assert resolved.group_missing is None
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

    assert resolved.faults == ()
    assert resolved.group_missing is None
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
                key="offset",
                kind=SettingKind.NUMBER,
                function=FunctionId.SCHEDULE,
                default=0,
                parse=as_int,
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
            key="",
            kind=SettingKind.NUMBER,
            function=FunctionId.SCHEDULE,
            default=0,
            parse=as_int,
        ),
        lambda: SettingDefinition(
            key="offset",
            kind="number",  # type: ignore[arg-type]
            function=FunctionId.SCHEDULE,
            default=0,
            parse=as_int,
        ),
        lambda: SettingFault("offset", "broken", "unreadable"),  # type: ignore[arg-type]
        lambda: SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            function=FunctionId.SCHEDULE,
            default=0,
            parse=as_int,
            inheritable=1,  # type: ignore[arg-type]
        ),
        lambda: SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            function=FunctionId.SCHEDULE,
            default=0,
            parse=as_int,
            requires=Capability.SUPPORTS_STOP,  # type: ignore[arg-type]
        ),
        lambda: CapabilityRequirement("supports_stop", False),  # type: ignore[arg-type]
        lambda: SettingsRegistry(("offset",)),  # type: ignore[arg-type]
        lambda: SettingsRegistry(
            (
                SettingDefinition(
                    key="offset",
                    kind=SettingKind.NUMBER,
                    function=FunctionId.SCHEDULE,
                    default=0,
                    parse=as_int,
                ),
                SettingDefinition(
                    key="offset",
                    kind=SettingKind.NUMBER,
                    function=FunctionId.SCHEDULE,
                    default=1,
                    parse=as_int,
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
        ({"source": "   "}, {}),
        ({"source": "\t\n"}, {}),
    ],
)
def test_absent_key_means_inherit_and_falsy_values_are_set(
    stored: dict[str, JsonValue], expected: dict[str, object]
) -> None:
    """Only an absent key and empty or blank text are "inherit"."""
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
    assert resolved.faults == ()
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

    assert inherited.group_missing is None
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

    assert [(fault.key, fault.level, fault.problem) for fault in resolved.faults] == [
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


SCHEDULE_KINDS = SettingsRegistry(
    (
        SettingDefinition(
            key="morning_time",
            kind=SettingKind.TIME,
            function=FunctionId.SCHEDULE,
            default=time(7, 0),
            parse=as_time,
        ),
        SettingDefinition(
            key="delay",
            kind=SettingKind.DURATION,
            function=FunctionId.SCHEDULE,
            default=timedelta(0),
            parse=as_duration,
        ),
        SettingDefinition(
            key="summer_begins",
            kind=SettingKind.DAY_OF_YEAR,
            function=FunctionId.SCHEDULE,
            default=(5, 1),
            parse=as_day_of_year,
        ),
    )
)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("06:30", time(6, 30)),
        ("00:00", time(0, 0)),
        ("23:59:59", time(23, 59, 59)),
        ("06:30:15", time(6, 30, 15)),
    ],
)
def test_time_is_read_in_its_two_spellings(stored: str, expected: time) -> None:
    """Hours and minutes, with or without seconds, on the 24-hour clock."""
    assert as_time(stored) == expected
    assert as_time(stored).tzinfo is None


@pytest.mark.parametrize(
    "stored",
    [
        "6:30",
        "24:00",
        "06:60",
        "06:30:60",
        "0630",
        "T06:30",
        "06:30+01:00",
        "06:30Z",
        "06:30:15.5",
        "06:30:15,5",
        " 06:30",
        "06:30 ",
        "06:30\n",
        "06",
        "6 pm",
        630,
        6.5,
        True,
        ["06:30"],
    ],
)
def test_time_in_any_other_spelling_is_refused(stored: JsonValue) -> None:
    """No offset, no compact form, no fraction, nothing around it."""
    with pytest.raises(ValueError, match="expected"):
        as_time(stored)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        (0, timedelta(0)),
        (900, timedelta(minutes=15)),
        (86400, timedelta(days=1)),
        (MAX_DURATION_SECONDS, timedelta(days=366)),
    ],
)
def test_duration_is_a_whole_number_of_seconds(
    stored: int, expected: timedelta
) -> None:
    """Zero is a duration."""
    assert as_duration(stored) == expected


@pytest.mark.parametrize(
    "stored",
    [
        -1,
        1.5,
        900.0,
        True,
        False,
        "900",
        "00:15:00",
        MAX_DURATION_SECONDS + 1,
        10**15,
        10**400,
    ],
)
def test_duration_in_any_other_form_is_refused(stored: JsonValue) -> None:
    """No negative number, no fraction, no boolean, no text, nothing beyond 366 days."""
    with pytest.raises(ValueError, match="expected"):
        as_duration(stored)


@pytest.mark.parametrize(
    ("stored", "expected"),
    [("05-01", (5, 1)), ("02-28", (2, 28)), ("12-31", (12, 31)), ("01-01", (1, 1))],
)
def test_day_of_year_is_month_and_day(stored: str, expected: tuple[int, int]) -> None:
    """The result is (month, day)."""
    assert as_day_of_year(stored) == expected


@pytest.mark.parametrize(
    "stored",
    [
        "02-29",
        "02-30",
        "04-31",
        "13-01",
        "00-10",
        "05-00",
        "5-1",
        "05-1",
        "0501",
        "05/01",
        "2026-05-01",
        " 05-01",
        "05-01\n",
        501,
        True,
    ],
)
def test_day_that_does_not_exist_every_year_or_is_spelled_otherwise_is_refused(
    stored: JsonValue,
) -> None:
    """The twenty-ninth of February is refused on purpose."""
    with pytest.raises(ValueError, match="expected"):
        as_day_of_year(stored)


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


def test_only_the_optional_references_of_the_window_accept_the_marker() -> None:
    """Whatever the registry holds: the kind alone decides about the marker."""
    for definition in WINDOW_SETTINGS.definitions:
        partial = settings_from_stored({definition.key: STORED_NONE}, WINDOW_SETTINGS)
        if definition.kind is SettingKind.OPTIONAL_REFERENCE:
            assert partial == PartialSettings({definition.key: None})
        else:
            assert [(fault.key, fault.problem) for fault in partial.faults] == [
                (definition.key, SettingProblem.NONE_NOT_ALLOWED)
            ]
    kinds = {
        definition.key: definition.kind for definition in WINDOW_SETTINGS.definitions
    }
    assert kinds["morning_condition_source"] is SettingKind.OPTIONAL_REFERENCE
    assert kinds["schedule_profile"] is SettingKind.ENUMERATION


# --- Faults: fall back or pause, by the fault behavior of the function ------------------

# What the three levels store when nothing is wrong. "offset" belongs to the
# schedule, which pauses on a fault; the two positions belong to functions that
# fall back.
SOUND: dict[Level, dict[str, JsonValue]] = {
    Level.GLOBAL: {
        "offset": 10,
        "frost_position": 80,
        "ventilation_position": 20,
        "lights": [],
    },
    Level.GROUP: {"offset": 60, "frost_position": 85, "ventilation_position": 25},
    Level.WINDOW: {},
}
LEVELS = [Level.GLOBAL, Level.GROUP, Level.WINDOW]
# The level whose value applies when the given level is unreadable as a whole.
NEXT_SOUND_LEVEL = {
    Level.WINDOW: Level.GROUP,
    Level.GROUP: Level.GLOBAL,
    Level.GLOBAL: Level.GROUP,
}
# The level that supplies the value when the faulty value is passed by.
FURTHER_OUT = {
    Level.WINDOW: Level.GROUP,
    Level.GROUP: Level.GLOBAL,
    Level.GLOBAL: Level.BUILT_IN,
}
# What applies when the faulty value is passed by and no level is left: the
# default for a function that pauses (nobody acts on it), the fault value for a
# function that falls back.
BUILT_IN_VALUES: dict[str, JsonValue] = {
    "offset": 5,
    "frost_position": CAUTIOUS_FROST_POSITION,
    "ventilation_position": CAUTIOUS_VENTILATION_POSITION,
}
# (the faulty stored value, the problem)
FAULTY_VALUES = [
    pytest.param("many", SettingProblem.UNREADABLE, id="unreadable"),
    pytest.param(None, SettingProblem.UNREADABLE, id="null"),
    pytest.param(True, SettingProblem.UNREADABLE, id="wrong-type"),
    pytest.param(
        STORED_NONE, SettingProblem.NONE_NOT_ALLOWED, id="marker-on-wrong-kind"
    ),
    pytest.param(101, SettingProblem.INVALID, id="refused-by-the-rules"),
]


def _stored(data: object) -> PartialSettings:
    return settings_from_stored(data, REGISTRY)


def _reached(level: Level, key: str, faulty: JsonValue) -> dict[Level, Any]:
    """Store a faulty value that no closer level covers with a sound one."""
    stored: dict[Level, Any] = SOUND | {level: SOUND[level] | {key: faulty}}
    for closer in LEVELS[LEVELS.index(level) + 1 :]:
        stored[closer] = {
            name: value for name, value in SOUND[closer].items() if name != key
        }
    return stored


def _expected(level: Level, key: str) -> JsonValue:
    supplier = FURTHER_OUT[level]
    if supplier is Level.BUILT_IN:
        return BUILT_IN_VALUES[key]
    return SOUND[supplier][key]


def _resolve_stored(stored: dict[Level, Any]) -> ResolvedSettings:
    return _resolve(
        house=_stored(stored[Level.GLOBAL]),
        group=GroupLevel(GROUP_ID, _stored(stored[Level.GROUP])),
        window=_stored(stored[Level.WINDOW]),
    )


# A setting of frost protection, which protects, and one of ventilation, a
# comfort feature that restricts movement: both fall back, neither is paused.
@pytest.mark.parametrize("key", ["frost_position", "ventilation_position"])
@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(("faulty", "problem"), FAULTY_VALUES)
def test_faulty_setting_of_a_function_that_falls_back_takes_the_next_level(
    key: str, level: Level, faulty: JsonValue, problem: SettingProblem
) -> None:
    """Nothing is paused; the result says which level supplied the value.

    A fault of the house has no level behind it: the fault value of the
    setting applies then, not its default, and the action says so.
    """
    resolved = _resolve_stored(_reached(level, key, faulty))

    no_level_left = FURTHER_OUT[level] is Level.BUILT_IN
    assert resolved.faults == (
        ReportedFault(
            key,
            level,
            problem,
            resolved.faults[0].detail,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
            if no_level_left
            else FaultAction.FELL_BACK,
            (),
            GROUP_ID if level is Level.GROUP else None,
        ),
    )
    assert resolved.disabled_functions == frozenset()
    item = resolved.values[key]
    assert item.level is FURTHER_OUT[level]
    assert item.value == _expected(level, key)
    assert item.effective == item.value
    assert item.cautious is no_level_left
    assert resolved.values["offset"].value == SOUND[Level.GROUP]["offset"]
    assert not resolved.values["offset"].cautious


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(("faulty", "problem"), FAULTY_VALUES)
def test_faulty_setting_of_a_function_that_pauses_pauses_it_for_the_window(
    level: Level, faulty: JsonValue, problem: SettingProblem
) -> None:
    """The function pauses for the window; the other functions are untouched."""
    resolved = _resolve_stored(_reached(level, "offset", faulty))

    assert resolved.faults == (
        ReportedFault(
            "offset",
            level,
            problem,
            resolved.faults[0].detail,
            FaultAction.FUNCTIONS_DISABLED,
            (FunctionId.SCHEDULE,),
            GROUP_ID if level is Level.GROUP else None,
        ),
    )
    assert resolved.disabled_functions == {FunctionId.SCHEDULE}
    assert resolved.faults_of(FunctionId.SCHEDULE) == resolved.faults
    assert resolved.faults_of(FunctionId.SHADING) == ()
    assert resolved.values["offset"].value == _expected(level, "offset")
    assert resolved.values["offset"].level is FURTHER_OUT[level]
    assert (
        resolved.values["frost_position"].value == SOUND[Level.GROUP]["frost_position"]
    )
    assert resolved.values["lights"].level is Level.GLOBAL


@pytest.mark.parametrize("key", ["offset", "frost_position", "ventilation_position"])
@pytest.mark.parametrize("level", [Level.GLOBAL, Level.GROUP])
def test_fault_behind_a_sound_value_of_a_closer_level_has_no_effect(
    level: Level, key: str
) -> None:
    """The window sets its own sound value: reported for the level, nothing paused."""
    stored = SOUND | {level: SOUND[level] | {key: "many"}, Level.WINDOW: {key: 7}}

    resolved = _resolve_stored(stored)

    assert [
        (fault.key, fault.level, fault.problem, fault.action, fault.disabled_functions)
        for fault in resolved.faults
    ] == [(key, level, SettingProblem.UNREADABLE, FaultAction.NO_EFFECT, ())]
    assert resolved.disabled_functions == frozenset()
    assert resolved.values[key].level is Level.WINDOW


def test_setting_that_falls_back_and_is_faulty_on_every_level_gets_its_fault_value() -> (
    None
):
    """Window, group and house are faulty: the cautious value is the last resort."""
    resolved = _resolve_stored(
        {
            Level.GLOBAL: {"frost_position": "low"},
            Level.GROUP: {"frost_position": 101},
            Level.WINDOW: {"frost_position": None},
        }
    )

    cautious = FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
    assert [(fault.level, fault.action) for fault in resolved.faults] == [
        (Level.WINDOW, cautious),
        (Level.GROUP, cautious),
        (Level.GLOBAL, cautious),
    ]
    assert resolved.values["frost_position"].value == CAUTIOUS_FROST_POSITION
    assert resolved.values["frost_position"].level is Level.BUILT_IN
    assert resolved.values["frost_position"].cautious
    assert resolved.disabled_functions == frozenset()


@pytest.mark.parametrize("level", [Level.GLOBAL, Level.GROUP])
def test_setting_that_cannot_be_inherited_set_above_the_window_has_no_effect(
    level: Level,
) -> None:
    """It could never have been the effective value of a window: reported, no more."""
    resolved = _resolve_stored(
        SOUND | {level: SOUND[level] | {"glass_height": OWN_GLASS_HEIGHT}}
    )

    assert [
        (fault.key, fault.level, fault.problem, fault.action, fault.disabled_functions)
        for fault in resolved.faults
    ] == [
        (
            "glass_height",
            level,
            SettingProblem.NOT_INHERITABLE,
            FaultAction.NO_EFFECT,
            (),
        )
    ]
    assert resolved.disabled_functions == frozenset()
    assert resolved.values["glass_height"].value == DEFAULT_GLASS_HEIGHT
    assert resolved.values["glass_height"].level is Level.BUILT_IN


def test_setting_that_cannot_be_inherited_is_set_by_the_window() -> None:
    """On the window it is no fault: the own value applies."""
    resolved = _resolve(window=PartialSettings({"glass_height": OWN_GLASS_HEIGHT}))

    assert resolved.faults == ()
    assert resolved.values["glass_height"].value == OWN_GLASS_HEIGHT
    assert resolved.values["glass_height"].level is Level.WINDOW


@pytest.mark.parametrize("level", LEVELS)
def test_unknown_key_is_reported_and_switches_nothing_off(level: Level) -> None:
    """A newer version may have written it; a misspelling is noticed all the same."""
    resolved = _resolve_stored(SOUND | {level: SOUND[level] | {"ofset": 3}})

    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolved.faults
    ] == [("ofset", level, SettingProblem.UNKNOWN_SETTING, FaultAction.IGNORED)]
    assert resolved.disabled_functions == frozenset()
    assert resolved.values["offset"].value == SOUND[Level.GROUP]["offset"]
    assert "ofset" not in resolved.values


def test_unknown_key_in_stored_data_is_noticed() -> None:
    """A misspelled key does not silently mean "inherit"; the good keys are read."""
    partial = _stored({"ofset": 3, "offset": 7, 5: 1, "": 2})

    assert partial.values == {"offset": 7}
    assert [(fault.key, fault.problem) for fault in partial.faults] == [
        ("ofset", SettingProblem.UNKNOWN_SETTING),
        ("settings", SettingProblem.UNKNOWN_SETTING),
    ]


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("stored", [None, "text", 7, [["offset", 3]], True])
def test_level_that_is_unreadable_as_a_whole_counts_as_not_present(
    level: Level, stored: object
) -> None:
    """What pauses is paused for the window; what falls back uses the other levels.

    No level names a frost source here. Nobody can see whether the unreadable
    level had named one, so the source takes its fault value, and the result
    says so for that setting and that level.
    """
    resolved = _resolve_stored(SOUND | {level: stored})

    assert _stored(stored) == PartialSettings(unreadable=True)
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolved.faults
    ] == [
        (
            "settings",
            level,
            SettingProblem.LEVEL_UNREADABLE,
            FaultAction.FUNCTIONS_DISABLED,
        ),
        (
            "source",
            level,
            SettingProblem.LEVEL_UNREADABLE,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
        ),
    ]
    assert resolved.values["source"].value == CAUTIOUS_SOURCE
    assert resolved.values["source"].cautious
    assert resolved.faults[1].disabled_functions == ()
    assert resolved.disabled_functions == set(REGISTRY.pausable_functions)
    assert resolved.disabled_functions == {
        FunctionId.SCHEDULE,
        FunctionId.SHADING,
        FunctionId.PRIVACY,
        FunctionId.REQUEST,
    }
    frost = resolved.values["frost_position"]
    assert frost.level is NEXT_SOUND_LEVEL[level]
    assert frost.value == SOUND[NEXT_SOUND_LEVEL[level]]["frost_position"]


def test_partial_settings_built_in_code_are_judged_like_stored_ones() -> None:
    """An unknown key or a refused value needs no detour through stored data."""
    resolved = _resolve(
        house=PartialSettings({"offse": 7}),
        group=GroupLevel(GROUP_ID, PartialSettings({"frost_position": -1})),
        window=PartialSettings({"offset": 101, "source": None}),
    )

    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolved.faults
    ] == [
        (
            "offset",
            Level.WINDOW,
            SettingProblem.INVALID,
            FaultAction.FUNCTIONS_DISABLED,
        ),
        (
            "frost_position",
            Level.GROUP,
            SettingProblem.INVALID,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
        ),
        ("offse", Level.GLOBAL, SettingProblem.UNKNOWN_SETTING, FaultAction.IGNORED),
    ]
    assert resolved.values["source"].level is Level.WINDOW


def test_unreadable_settings_set_nothing() -> None:
    """The flag excludes values and faults."""
    with pytest.raises(ValueError, match="set nothing"):
        PartialSettings({"offset": 1}, unreadable=True)
    with pytest.raises(TypeError):
        PartialSettings(unreadable=1)  # type: ignore[arg-type]


def test_without_rules_no_value_is_refused() -> None:
    """The resolver has no value rules of its own."""
    resolved = _resolve(window=PartialSettings({"offset": 101}), rules=None)

    assert resolved.faults == ()
    assert resolved.values["offset"].value == MAX_POSITION + 1


def test_masked_own_value_is_validated_all_the_same() -> None:
    """A value the rules refuse is a fault of the window, masked or not."""
    resolved = _resolve(
        window=PartialSettings({"shading_position": 150}),
        members=(_member(LEFT, supports_set_position=False),),
    )

    assert [
        (fault.key, fault.level, fault.problem, fault.disabled_functions)
        for fault in resolved.faults
    ] == [
        (
            "shading_position",
            Level.WINDOW,
            SettingProblem.INVALID,
            (FunctionId.SHADING,),
        )
    ]
    assert resolved.masked_own_values == ()


# --- A fault reaches exactly the windows for which it would have been effective -------

NORTH_ID = "group_example_north"


def _four_windows(
    *, house: object, south: object, north: object
) -> dict[str, ResolvedSettings]:
    """Resolve two windows of the group south, one of north, one without a group.

    The second window of south sets its own sound mode and offset.
    """
    groups = {GROUP_ID: _stored(south), NORTH_ID: _stored(north)}
    windows: dict[str, tuple[str | None, dict[str, JsonValue]]] = {
        "south_inheriting": (GROUP_ID, {}),
        "south_overriding": (GROUP_ID, {"mode": "own", "offset": 5}),
        "north": (NORTH_ID, {}),
        "alone": (None, {}),
    }
    return {
        name: _resolve(
            house=_stored(house),
            group=None if group_id is None else GroupLevel(group_id, groups[group_id]),
            window=_stored(own),
        )
        for name, (group_id, own) in windows.items()
    }


def _paused(results: dict[str, ResolvedSettings]) -> dict[str, set[FunctionId]]:
    return {name: set(result.disabled_functions) for name, result in results.items()}


def test_fault_of_a_group_pauses_the_function_for_windows_that_inherit_the_key() -> (
    None
):
    """The window that overrides the key keeps running; the fault is reported anyway."""
    results = _four_windows(
        house={"offset": 10}, south={"mode": "sideways"}, north={"mode": "house"}
    )

    assert _paused(results) == {
        "south_inheriting": {FunctionId.SHADING},
        "south_overriding": set(),
        "north": set(),
        "alone": set(),
    }
    assert [
        (fault.key, fault.level, fault.group_id, fault.action)
        for fault in results["south_overriding"].faults
    ] == [("mode", Level.GROUP, GROUP_ID, FaultAction.NO_EFFECT)]
    assert results["south_overriding"].values["mode"].value is ExampleMode.OWN
    assert [fault.action for fault in results["south_inheriting"].faults] == [
        FaultAction.FUNCTIONS_DISABLED
    ]
    assert results["north"].faults == ()
    assert results["alone"].faults == ()


def test_fault_of_the_house_pauses_the_function_for_windows_that_inherit_the_key() -> (
    None
):
    """A window or a group with a sound value of its own is not reached."""
    results = _four_windows(
        house={"offset": "many"}, south={"mode": "south"}, north={"offset": 60}
    )

    assert _paused(results) == {
        "south_inheriting": {FunctionId.SCHEDULE},
        "south_overriding": set(),
        "north": set(),
        "alone": {FunctionId.SCHEDULE},
    }
    for name, result in results.items():
        assert [(fault.key, fault.level) for fault in result.faults] == [
            ("offset", Level.GLOBAL)
        ], name
    assert results["south_overriding"].faults[0].action is FaultAction.NO_EFFECT
    assert results["north"].faults[0].action is FaultAction.NO_EFFECT
    assert results["north"].values["offset"].level is Level.GROUP


def test_group_that_is_unreadable_as_a_whole_pauses_every_pausable_function() -> None:
    """Also for the window that overrides some keys; what falls back takes the house's.

    What the house does not supply either takes its fault value, for the
    windows of that group only.
    """
    results = _four_windows(
        house={"frost_position": 80, "source": "sensor.example_house"},
        south="not a mapping",
        north={"mode": "house"},
    )

    everything = set(REGISTRY.pausable_functions)
    assert _paused(results) == {
        "south_inheriting": everything,
        "south_overriding": everything,
        "north": set(),
        "alone": set(),
    }
    for name in ("south_inheriting", "south_overriding"):
        assert [
            (fault.key, fault.level, fault.group_id, fault.problem, fault.action)
            for fault in results[name].faults
        ] == [
            (
                "settings",
                Level.GROUP,
                GROUP_ID,
                SettingProblem.LEVEL_UNREADABLE,
                FaultAction.FUNCTIONS_DISABLED,
            ),
            (
                "ventilation_position",
                Level.GROUP,
                GROUP_ID,
                SettingProblem.LEVEL_UNREADABLE,
                FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
            ),
        ]
        frost = results[name].values["frost_position"]
        assert (frost.value, frost.level, frost.cautious) == (80, Level.GLOBAL, False)
        floor = results[name].values["ventilation_position"]
        assert (floor.value, floor.cautious) == (CAUTIOUS_VENTILATION_POSITION, True)
    assert results["south_overriding"].values["mode"].value is ExampleMode.OWN
    for name in ("north", "alone"):
        assert results[name].faults == ()
        floor = results[name].values["ventilation_position"]
        assert (floor.value, floor.cautious) == (DEFAULT_VENTILATION_POSITION, False)


def test_fault_of_the_house_in_a_setting_that_falls_back_pauses_nothing() -> None:
    """Every window keeps all its functions and gets the cautious value."""
    results = _four_windows(
        house={"frost_position": "low"}, south={"mode": "south"}, north={}
    )

    for name, result in results.items():
        assert result.disabled_functions == frozenset(), name
        assert result.values["frost_position"].level is Level.BUILT_IN, name
        assert result.values["frost_position"].value == CAUTIOUS_FROST_POSITION, name
        assert [fault.action for fault in result.faults] == [
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
        ]


# --- A rule that spans several settings ---------------------------------------------------
# The refusal names the keys it concerns. Only those keys become faulty, on the
# levels that supply their effective values, each by the fault behavior of its
# function. Nothing else is touched, reported or blamed.

COMBINATION = SettingProblem.COMBINATION


def _summary(resolved: ResolvedSettings) -> list[tuple[Any, ...]]:
    return [
        (fault.key, fault.level, fault.problem, fault.action, fault.disabled_functions)
        for fault in resolved.faults
    ]


def test_built_in_defaults_alone_are_never_refused() -> None:
    """Falling back ends at the defaults, so they have to build: here and for real."""
    assert _resolve().faults == ()
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings(),
        window_settings=PartialSettings(),
    )
    assert resolution.config is not None
    assert resolution.settings.faults == ()


def test_refused_combination_leaves_unrelated_own_values_of_the_window_alone() -> None:
    """The window's sound frost and ventilation values stay and are not reported."""
    resolved = _resolve(
        house=PartialSettings({"offset": 0}),
        window=PartialSettings(
            {"mode": ExampleMode.OWN, "frost_position": 70, "ventilation_position": 55}
        ),
    )

    assert _summary(resolved) == [
        (
            "mode",
            Level.WINDOW,
            COMBINATION,
            FaultAction.FUNCTIONS_DISABLED,
            (FunctionId.SHADING,),
        ),
        (
            "offset",
            Level.GLOBAL,
            COMBINATION,
            FaultAction.FUNCTIONS_DISABLED,
            (FunctionId.SCHEDULE,),
        ),
    ]
    assert resolved.faults[0].detail == "the mode 'own' needs an offset"
    assert resolved.disabled_functions == {FunctionId.SHADING, FunctionId.SCHEDULE}
    for key, value in (("frost_position", 70), ("ventilation_position", 55)):
        assert resolved.values[key].value == value
        assert resolved.values[key].level is Level.WINDOW
    for key in ("mode", "offset"):
        assert resolved.values[key].level is Level.BUILT_IN


def test_refused_combination_leaves_unrelated_values_of_the_house_alone() -> None:
    """The same one level up: the house's ventilation floor stays for its windows."""
    resolved = _resolve(
        house=PartialSettings(
            {"mode": ExampleMode.OWN, "offset": 0, "ventilation_position": 20}
        ),
        group=GroupLevel(GROUP_ID, PartialSettings({"enabled": False})),
    )

    assert [(key, level) for key, level, *_ in _summary(resolved)] == [
        ("mode", Level.GLOBAL),
        ("offset", Level.GLOBAL),
    ]
    assert resolved.values["ventilation_position"].value == 20  # noqa: PLR2004
    assert resolved.values["ventilation_position"].level is Level.GLOBAL
    assert resolved.values["enabled"].level is Level.GROUP
    assert FunctionId.VENTILATION not in resolved.disabled_functions


def test_combination_that_a_closer_level_heals_is_no_fault() -> None:
    """The house and the group contradict each other; the window's value fits."""
    resolved = _resolve(
        house=PartialSettings({"mode": ExampleMode.OWN}),
        group=GroupLevel(GROUP_ID, PartialSettings({"offset": 0})),
        window=PartialSettings({"offset": 7}),
    )

    assert resolved.faults == ()
    assert resolved.values["mode"].value is ExampleMode.OWN


def test_refused_combination_of_pausing_functions_names_the_levels_that_supply() -> (
    None
):
    """House, group, window: the group's healing value is not blamed."""
    resolved = _resolve(
        house=PartialSettings({"mode": ExampleMode.OWN}),
        group=GroupLevel(GROUP_ID, PartialSettings({"offset": 7})),
        window=PartialSettings({"offset": 0}),
    )

    assert [
        (key, level, problem) for key, level, problem, *_ in _summary(resolved)
    ] == [
        ("offset", Level.WINDOW, COMBINATION),
        ("mode", Level.GLOBAL, COMBINATION),
    ]
    assert resolved.disabled_functions == {FunctionId.SHADING, FunctionId.SCHEDULE}
    # The paused schedule gets its default, not the group's 7: a combination of
    # values nobody chose together must not stand in.
    assert resolved.values["offset"].value == REGISTRY.definitions[1].default
    assert resolved.values["offset"].level is Level.BUILT_IN


def test_refused_combination_of_a_function_that_falls_back_passes_the_innermost_by() -> (
    None
):
    """House zero frost position, group heals with a source, window says "none"."""
    resolved = _resolve(
        house=PartialSettings({"frost_position": 0}),
        group=GroupLevel(GROUP_ID, PartialSettings({"source": "sensor.example_south"})),
        window=PartialSettings({"source": None, "ventilation_position": 55}),
    )

    assert _summary(resolved) == [
        ("source", Level.WINDOW, COMBINATION, FaultAction.FELL_BACK, ())
    ]
    assert resolved.values["source"].value == "sensor.example_south"
    assert resolved.values["source"].level is Level.GROUP
    assert resolved.values["frost_position"].value == 0
    assert resolved.values["frost_position"].level is Level.GLOBAL
    assert resolved.values["ventilation_position"].level is Level.WINDOW
    assert resolved.disabled_functions == frozenset()


def test_refused_combination_falls_back_level_by_level_to_the_fault_value() -> None:
    """Every level sets the refused frost position: the fault value is the last resort."""
    zero = PartialSettings({"frost_position": 0})

    resolved = _resolve(house=zero, group=GroupLevel(GROUP_ID, zero), window=zero)

    assert _summary(resolved) == [
        (
            "frost_position",
            level,
            COMBINATION,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
            (),
        )
        for level in (Level.WINDOW, Level.GROUP, Level.GLOBAL)
    ]
    assert resolved.values["frost_position"].value == CAUTIOUS_FROST_POSITION
    assert resolved.values["frost_position"].level is Level.BUILT_IN
    assert resolved.values["frost_position"].cautious
    # The source was never part of a fault, so it keeps its default.
    assert resolved.values["source"].value is None
    assert not resolved.values["source"].cautious


def test_rule_over_a_pausing_and_a_falling_back_function_pauses_first() -> None:
    """Pausing the schedule heals it, so the ventilation value is never touched."""
    resolved = _resolve(
        group=GroupLevel(GROUP_ID, PartialSettings({"ventilation_position": 1})),
        window=PartialSettings({"offset": LONELY_OFFSET}),
    )

    assert _summary(resolved) == [
        (
            "offset",
            Level.WINDOW,
            COMBINATION,
            FaultAction.FUNCTIONS_DISABLED,
            (FunctionId.SCHEDULE,),
        )
    ]
    assert resolved.values["ventilation_position"].value == 1
    assert resolved.values["ventilation_position"].level is Level.GROUP


def test_value_that_is_refused_only_in_a_combination_is_sound_on_its_own() -> None:
    """The check of single values ignores a refusal that names several keys."""

    def check(key: str, _value: object) -> None:
        if key == "offset":
            raise SettingsCombinationError("not alone", ("offset", "mode"))

    resolved = _resolve(
        window=PartialSettings({"offset": 7}), rules=SettingRules(check, _build)
    )

    assert resolved.faults == ()
    assert resolved.values["offset"].value == 7  # noqa: PLR2004


def test_rule_that_names_no_keys_pauses_everything_pausable_and_keeps_protection() -> (
    None
):
    """A programming error, not stored data: the window is still configured."""
    resolved = _resolve(
        window=PartialSettings(
            {"lights": (UNDECLARED,), "frost_position": 70, "ventilation_position": 55}
        ),
    )

    assert _summary(resolved) == [
        (
            "settings",
            Level.BUILT_IN,
            SettingProblem.RULE_WITHOUT_KEYS,
            FaultAction.FUNCTIONS_DISABLED,
            REGISTRY.pausable_functions,
        )
    ]
    assert resolved.values["lights"].level is Level.BUILT_IN
    assert resolved.values["frost_position"].value == 70  # noqa: PLR2004
    assert resolved.values["ventilation_position"].value == 55  # noqa: PLR2004


def test_rule_that_names_no_keys_in_a_function_that_falls_back_takes_fault_values() -> (
    None
):
    """Second step: the settings that fall back take their fault values as well.

    Nobody knows which of them the refusal concerned, so none of them may end
    less restrictive than a level had made it.
    """
    resolved = _resolve(window=PartialSettings({"source": UNDECLARED}))

    assert [(fault.problem, fault.action) for fault in resolved.faults] == [
        (SettingProblem.RULE_WITHOUT_KEYS, FaultAction.FUNCTIONS_DISABLED),
        (SettingProblem.RULE_WITHOUT_KEYS, FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE),
    ]
    assert {item.level for item in resolved.values.values()} == {Level.BUILT_IN}
    assert {
        key: item.value for key, item in resolved.values.items() if item.cautious
    } == {
        "source": CAUTIOUS_SOURCE,
        "frost_position": CAUTIOUS_FROST_POSITION,
        "ventilation_position": CAUTIOUS_VENTILATION_POSITION,
    }
    assert resolved.values["offset"].value == REGISTRY.definitions[1].default


def test_refusal_of_the_built_in_defaults_is_reported_and_not_raised() -> None:
    """A broken registry is nobody's stored data, but it must not raise either."""

    def refuse(
        _effective: Mapping[str, Any], _disabled: frozenset[FunctionId]
    ) -> object:
        raise SettingsCombinationError("nothing fits", ("offset", "nonexistent"))

    resolved = _resolve(rules=SettingRules(_check_value, refuse))

    assert [(fault.level, fault.action) for fault in resolved.faults] == [
        (Level.BUILT_IN, FaultAction.FUNCTIONS_DISABLED),
        (Level.BUILT_IN, FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE),
        (Level.BUILT_IN, FaultAction.CONFIGURATION_WITHHELD),
    ]


def test_combination_error_names_its_keys() -> None:
    """The contract of the model: a rule over several settings says which."""
    error = SettingsCombinationError("morning before evening", ["morning", "evening"])

    assert isinstance(error, ValueError)
    assert error.keys == ("morning", "evening")
    assert str(error) == "morning before evening"
    with pytest.raises(ValueError, match="names the keys"):
        SettingsCombinationError("nothing", ())
    with pytest.raises(ValueError, match="must not be empty"):
        SettingsCombinationError("nothing", ("",))


# --- Hostile stored values ------------------------------------------------------------------

HUGE = 10**400
DEEP: list[Any] = []
for _ in range(3000):
    DEEP = [DEEP]
HOSTILE: list[Any] = [
    None,
    True,
    False,
    0,
    -1,
    HUGE,
    -HUGE,
    float("inf"),
    float("-inf"),
    float("nan"),
    1e308,
    "",
    "   ",
    STORED_NONE,
    "x" * 10000,
    "06:30",
    "\x00",
    [],
    [None],
    [HUGE],
    [[]],
    DEEP,
    {},
    {"threshold": HUGE, "hysteresis": 1},
    [{"threshold": HUGE, "hysteresis": 1}],
    [{"threshold": 1, "hysteresis": HUGE}],
    [{"threshold": float("nan"), "hysteresis": float("inf")}],
    [{"threshold": 1, "hysteresis": 1}] * 1000,
    {1: 2},
    {"": ""},
]


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("value", HOSTILE, ids=lambda value: repr(value)[:24])
def test_hostile_value_in_any_setting_on_any_level_never_costs_the_configuration(
    level: Level, value: Any
) -> None:
    """No exception, a configuration for the window, and only pausable functions off."""
    for registry in (WINDOW_SETTINGS, REGISTRY, SCHEDULE_KINDS):
        for key in (*registry.keys, "unheard_of"):
            stored = settings_from_stored({key: value}, registry)
            empty = PartialSettings()
            if registry is WINDOW_SETTINGS:
                resolution = resolve_window(
                    window_id="window_example",
                    members=FULL,
                    global_settings=stored if level is Level.GLOBAL else empty,
                    group=GroupLevel(
                        GROUP_ID, stored if level is Level.GROUP else empty
                    ),
                    window_settings=stored if level is Level.WINDOW else empty,
                )
                assert resolution.config is not None, key
                resolved = resolution.settings
                assert resolution.config.disabled_functions == (
                    resolved.disabled_functions
                )
            else:
                resolved = _resolve(
                    house=stored if level is Level.GLOBAL else empty,
                    group=GroupLevel(
                        GROUP_ID, stored if level is Level.GROUP else empty
                    ),
                    window=stored if level is Level.WINDOW else empty,
                    registry=registry,
                    rules=RULES if registry is REGISTRY else None,
                )
            for function in resolved.disabled_functions:
                assert function.fault_behavior is FaultBehavior.PAUSE, key
            assert FaultAction.CONFIGURATION_WITHHELD not in {
                fault.action for fault in resolved.faults
            }, key


@pytest.mark.parametrize("value", HOSTILE, ids=lambda value: repr(value)[:24])
def test_hostile_value_handed_in_as_a_typed_value_is_refused_by_the_model(
    value: Any,
) -> None:
    """Partial settings built in code reach the model unparsed; it must not raise."""
    for key in WINDOW_SETTINGS.keys:
        resolution = resolve_window(
            window_id="window_example",
            members=FULL,
            global_settings=PartialSettings({key: value}),
            window_settings=PartialSettings(),
        )

        assert resolution.config is not None, key


def test_oversized_number_of_the_house_stops_no_window() -> None:
    """The reviewer's case: a threshold with four hundred digits, stored in the house."""
    house = settings_from_stored(
        {"shading_temperature_tiers": [{"threshold": HUGE, "hysteresis": 1}]},
        WINDOW_SETTINGS,
    )

    assert [(fault.key, fault.problem) for fault in house.faults] == [
        ("shading_temperature_tiers", SettingProblem.UNREADABLE)
    ]
    assert "expected a finite number" in house.faults[0].detail
    for window_id in ("window_example_one", "window_example_two"):
        resolution = resolve_window(
            window_id=window_id,
            members=FULL,
            global_settings=house,
            window_settings=PartialSettings(),
        )
        assert resolution.config is not None
        assert resolution.config.disabled_functions == {FunctionId.SHADING}


def test_reader_that_raises_something_unexpected_is_a_fault_too() -> None:
    """The second line of defence: a reader of a later block cannot break the promise."""

    def clumsy(value: JsonValue) -> float:
        return 1 / float(value["ratio"])  # type: ignore[index,call-overload,arg-type]

    registry = SettingsRegistry(
        (
            SettingDefinition(
                key="ratio",
                kind=SettingKind.NUMBER,
                function=FunctionId.SHADING,
                default=1.0,
                parse=clumsy,
            ),
        )
    )

    hostile: list[JsonValue] = [0, [1], {"a": 1}, {"ratio": 0}, {"ratio": HUGE}]
    for stored in hostile:
        partial = settings_from_stored({"ratio": stored}, registry)
        assert [fault.problem for fault in partial.faults] == [
            SettingProblem.UNREADABLE
        ]
        assert partial.faults[0].detail


# --- A group that no longer exists ------------------------------------------------------------


def test_group_that_no_longer_exists_falls_back_to_the_house() -> None:
    """The window inherits from the house; nothing is switched off."""
    resolved = _resolve(
        house=PartialSettings({"offset": 0}),
        group=GroupLevel(GROUP_ID, None),
        window=PartialSettings({"enabled": False}),
    )

    assert resolved.faults == ()
    assert resolved.disabled_functions == frozenset()
    assert resolved.group_missing == GroupMissing(GROUP_ID)
    assert resolved.values["offset"].value == 0
    assert resolved.values["offset"].level is Level.GLOBAL
    assert resolved.values["enabled"].level is Level.WINDOW
    assert resolved.values["mode"].level is Level.BUILT_IN


def test_lost_group_of_one_window_does_not_touch_the_others() -> None:
    """Four windows in a row: two of a sound group, one of a lost one, one alone."""
    house = PartialSettings({"offset": 10})
    south = GroupLevel(GROUP_ID, PartialSettings({"offset": 60}))
    gone = GroupLevel("group_example_removed", None)

    results = [
        _resolve(house=house, group=group) for group in (south, gone, south, None)
    ]

    assert [result.values["offset"].value for result in results] == [60, 10, 60, 10]
    assert [result.group_missing is not None for result in results] == [
        False,
        True,
        False,
        False,
    ]
    assert all(result.faults == () for result in results)


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
    assert resolved.faults == ()
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
    assert resolved.faults == ()
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
    assert during.faults == ()
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
        assert result.faults == ()
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
        assert result.faults == ()
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

    assert resolved.faults == ()
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
            if field.name not in WINDOW_FIELDS_THAT_ARE_NO_SETTINGS
        },
        entries={
            definition.key: definition.default
            for definition in WINDOW_SETTINGS.definitions
        },
    )

    assert not mismatches, "\n".join(mismatches)
    assert set(WINDOW_FIELDS_THAT_ARE_NO_SETTINGS) <= {
        field.name for field in dataclasses.fields(WindowConfig)
    }
    assert (
        *WINDOW_IDENTITY_FIELDS,
        "disabled_functions",
    ) == WINDOW_FIELDS_THAT_ARE_NO_SETTINGS


def _registry_mismatches(
    *, fields: dict[str, object], entries: dict[str, object]
) -> list[str]:
    """Compare the fields of ``WindowConfig`` with the registry, with advice."""
    settings_module = "custom_components/roller_shutter_suite/core/settings.py"
    window_module = "custom_components/roller_shutter_suite/core/model/window.py"
    messages = [
        f"WindowConfig has the field {name!r}, but WINDOW_SETTINGS has no entry for "
        f"it. Add SettingDefinition(key={name!r}, kind=SettingKind.<kind>, "
        f"function=FunctionId.<function>, default={default!r}, "
        f"parse=<reader of the stored value>) to WINDOW_SETTINGS in "
        f"{settings_module}; the function decides whether a fault in the setting "
        f"falls back or pauses the function (FunctionId.fault_behavior). Only if "
        f"the field is never stored as a setting, add {name!r} to "
        f"WINDOW_FIELDS_THAT_ARE_NO_SETTINGS there instead."
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
        if key in entries
        and (type(entries[key]) is not type(default) or entries[key] != default)
    ]
    return messages


def test_mismatch_between_registry_and_window_configuration_says_what_to_add() -> None:
    """A contributor who forgot one half reads where the other half goes."""
    messages = _registry_mismatches(
        fields={"morning_position": 100, "evening_position": 0, "enabled": False},
        entries={"evening_position": 10, "night_position": 0, "enabled": 0},
    )

    missing_entry, missing_field, different_defaults, different_types = messages
    assert "'enabled' has two different defaults: 0" in different_types
    assert "SettingDefinition(key='morning_position'" in missing_entry
    assert "WINDOW_SETTINGS in custom_components" in missing_entry
    assert "function=FunctionId.<function>" in missing_entry
    assert "WINDOW_FIELDS_THAT_ARE_NO_SETTINGS" in missing_entry
    assert "Add the field 'night_position'" in missing_field
    assert "core/model/window.py" in missing_field
    assert "'evening_position' has two different defaults: 10" in different_defaults


def test_covering_type_cannot_be_inherited() -> None:
    """What cannot be inherited is marked in the registry and nowhere else."""
    marked = [
        definition.key
        for definition in WINDOW_SETTINGS.definitions
        if not definition.inheritable
    ]

    assert "covering_type" in marked
    assert "morning_condition_source" not in marked


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

    assert resolution.settings.faults == ()
    config = resolution.config
    assert config is not None
    assert config.window_id == "window_example"
    assert config.members == (_member(LEFT), _member(RIGHT))
    assert config.covering_type is CoveringType.ROLLER_SHUTTER
    assert config.morning_condition_source == "binary_sensor.example_south"
    assert config.shading_temperature_tiers == ()
    assert config.schedule_profile is ScheduleProfile.DEFAULT
    levels = {key: item.level for key, item in resolution.settings.values.items()}
    assert levels["covering_type"] is Level.WINDOW
    assert levels["morning_condition_source"] is Level.GROUP
    assert levels["shading_temperature_tiers"] is Level.WINDOW
    assert levels["schedule_profile"] is Level.BUILT_IN
    assert tuple(levels) == WINDOW_SETTINGS.keys
    assert house.get("shading_temperature_tiers") == (TemperatureTier(24.0, 1.5),)


@pytest.mark.parametrize(
    ("tiers", "detail"),
    [
        ([{"threshold": True, "hysteresis": 1}], "threshold: expected a number"),
        ([{"threshold": 24}], "the key 'hysteresis' is missing"),
        ([{"threshold": 24, "hysteresis": 1, "extra": 0}], "unknown key 'extra'"),
        ([{"threshold": 24, "hysteresis": -1}], "must not be negative"),
        ([{"threshold": 10**400, "hysteresis": 1}], "expected a finite number"),
        ([{"threshold": 24, "hysteresis": -(10**400)}], "expected a finite number"),
        ([{"threshold": float("inf"), "hysteresis": 1}], "expected a finite number"),
        ([{"threshold": float("nan"), "hysteresis": 1}], "expected a finite number"),
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


TWO_TIERS = (TemperatureTier(24.0, 1.0), TemperatureTier(28.0, 1.0))
HOUSE_SOURCE = "binary_sensor.example_house"


@pytest.mark.parametrize("level", LEVELS)
def test_value_the_model_refuses_pauses_shading_and_keeps_the_window(
    level: Level,
) -> None:
    """Two tiers on any level: the window is configured, shading is switched off."""
    faulty = PartialSettings({"shading_temperature_tiers": TWO_TIERS})
    sound = PartialSettings({"morning_condition_source": HOUSE_SOURCE})

    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=faulty if level is Level.GLOBAL else sound,
        group=GroupLevel(
            GROUP_ID, faulty if level is Level.GROUP else PartialSettings()
        ),
        window_settings=faulty if level is Level.WINDOW else PartialSettings(),
    )

    config = resolution.config
    assert config is not None
    assert config.disabled_functions == {FunctionId.SHADING}
    assert config.shading_temperature_tiers == ()
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolution.settings.faults
    ] == [
        (
            "shading_temperature_tiers",
            level,
            SettingProblem.INVALID,
            FaultAction.FUNCTIONS_DISABLED,
        )
    ]
    assert "more than one temperature tier" in resolution.settings.faults[0].detail
    if level is not Level.GLOBAL:
        assert config.morning_condition_source == HOUSE_SOURCE


def test_group_that_sets_the_covering_type_costs_nothing() -> None:
    """What only a window can set never reaches a window from a group: no effect."""
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings(),
        group=GroupLevel(
            GROUP_ID,
            settings_from_stored({"covering_type": "roller_shutter"}, WINDOW_SETTINGS),
        ),
        window_settings=PartialSettings(),
    )

    assert resolution.config is not None
    assert resolution.config.disabled_functions == frozenset()
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolution.settings.faults
    ] == [
        (
            "covering_type",
            Level.GROUP,
            SettingProblem.NOT_INHERITABLE,
            FaultAction.NO_EFFECT,
        )
    ]


@pytest.mark.parametrize(
    ("own", "problem", "disabled"),
    [
        (
            PartialSettings({"morning_condition_source": 7}),
            SettingProblem.INVALID,
            {FunctionId.SCHEDULE},
        ),
        (
            settings_from_stored({"schedule_profile": "holiday_home"}, WINDOW_SETTINGS),
            SettingProblem.UNREADABLE,
            {FunctionId.SCHEDULE},
        ),
        (
            settings_from_stored({"schedule_profil": "default"}, WINDOW_SETTINGS),
            SettingProblem.UNKNOWN_SETTING,
            set(),
        ),
        (
            settings_from_stored({"covering_type": "awning"}, WINDOW_SETTINGS),
            SettingProblem.UNREADABLE,
            set(),
        ),
        (
            settings_from_stored("not a mapping", WINDOW_SETTINGS),
            SettingProblem.LEVEL_UNREADABLE,
            {FunctionId.SCHEDULE, FunctionId.SHADING},
        ),
    ],
)
def test_fault_in_the_windows_own_data_never_costs_it_its_configuration(
    own: PartialSettings, problem: SettingProblem, disabled: set[FunctionId]
) -> None:
    """Fire and protection need a configured window; convenience pauses instead."""
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings(),
        window_settings=own,
    )

    assert resolution.config is not None
    assert resolution.config.disabled_functions == disabled
    assert resolution.settings.disabled_functions == disabled
    # One fault; an unreadable window is named once more for every setting that
    # runs on its fault value because of it.
    faults = resolution.settings.faults
    assert {(fault.level, fault.problem) for fault in faults} == {
        (Level.WINDOW, problem)
    }
    assert [fault.key for fault in faults[1:]] == (
        [
            definition.key
            for definition in WINDOW_SETTINGS.definitions
            if definition.has_fault_value
        ]
        if problem is SettingProblem.LEVEL_UNREADABLE
        else []
    )
    assert tuple(resolution.settings.values) == WINDOW_SETTINGS.keys


def test_only_the_covering_type_names_no_function() -> None:
    """A second setting without a function cannot appear unnoticed."""
    without = [
        definition.key
        for definition in WINDOW_SETTINGS.definitions
        if definition.function is None
    ]

    assert without == ["covering_type"]


def test_settings_of_the_window_name_their_function() -> None:
    """The decisions for today's settings, stated once."""
    declared = {
        definition.key: (definition.function, definition.fault_behavior)
        for definition in WINDOW_SETTINGS.definitions
    }

    assert declared["covering_type"] == (None, FaultBehavior.FALL_BACK)
    assert declared["morning_condition_source"] == (
        FunctionId.SCHEDULE,
        FaultBehavior.PAUSE,
    )
    assert declared["schedule_profile"] == (FunctionId.SCHEDULE, FaultBehavior.PAUSE)
    assert declared["shading_temperature_tiers"] == (
        FunctionId.SHADING,
        FaultBehavior.PAUSE,
    )
    assert functions_with_settings() >= {FunctionId.SCHEDULE, FunctionId.SHADING}
    assert functions_with_settings() == WINDOW_SETTINGS.functions
    assert functions_with_settings(REGISTRY) == {
        FunctionId.SCHEDULE,
        FunctionId.SHADING,
        FunctionId.FROST,
        FunctionId.VENTILATION,
        FunctionId.PRIVACY,
        FunctionId.REQUEST,
    }


def test_setting_without_a_function_is_allowed_for_what_is_not_inherited_only() -> None:
    """Whatever can be inherited belongs to a function, and only members count."""
    with pytest.raises(ValueError, match="belongs to a function"):
        SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            function=None,
            default=0,
            parse=as_int,
        )
    with pytest.raises(TypeError, match="the function of a setting"):
        SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            function="schedule",  # type: ignore[arg-type]
            default=0,
            parse=as_int,
        )


def test_window_with_a_lost_group_still_gets_its_configuration() -> None:
    """The lost group is reported next to a complete configuration."""
    resolution = resolve_window(
        window_id="window_example",
        members=FULL,
        global_settings=PartialSettings({"morning_condition_source": HOUSE_SOURCE}),
        group=GroupLevel(GROUP_ID, None),
        window_settings=PartialSettings(),
    )

    assert resolution.config is not None
    assert resolution.config.morning_condition_source == HOUSE_SOURCE
    assert resolution.config.disabled_functions == frozenset()
    assert resolution.settings.group_missing == GroupMissing(GROUP_ID)


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
    """The one case without a configuration: the covers themselves are unusable."""
    resolution = resolve_window(
        window_id=window_id,
        members=members,
        global_settings=PartialSettings(),
        window_settings=PartialSettings(),
    )

    assert resolution.config is None
    assert resolution.settings.values == {}
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolution.settings.faults
    ] == [
        (
            key,
            Level.WINDOW,
            SettingProblem.INVALID,
            FaultAction.CONFIGURATION_WITHHELD,
        )
    ]
