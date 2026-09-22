"""The fault value: what a function that falls back runs on when no level is left.

A faulty value of a function that falls back never makes that function less
restrictive than a valid value would. The faulty value is passed by; if
another level supplies a valid value, it applies; otherwise the **fault
value** of the setting applies, not its default. The same holds for a level
that is unreadable as a whole, for every setting that level could have held.

The registry here has one setting of every kind the block names (reference,
switch, number, position, duration), each with a fault value that differs
from its default, so that every assertion shows which of the two applied.
"""

import dataclasses
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    FaultBehavior,
    FunctionId,
    JsonValue,
    Position,
    SettingsCombinationError,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.model._data import (
    as_bool,
    as_int,
    as_str,
)
from custom_components.roller_shutter_suite.core.settings import (
    NO_FAULT_VALUE,
    WINDOW_SETTINGS,
    FaultAction,
    GroupLevel,
    Level,
    PartialSettings,
    ResolvedSettings,
    SettingDefinition,
    SettingKind,
    SettingProblem,
    SettingRules,
    SettingsRegistry,
    as_duration,
    resolve_settings,
    resolve_window,
    settings_from_stored,
)
from tests.core.arbiter_kit import window

GROUP_ID = "group_example_south"
BLIND = "blind"
"""Stands in for "configured, but blind" in this generic registry."""


def _as_position(value: JsonValue) -> Position:
    return Position(as_int(value))


REGISTRY = SettingsRegistry(
    (
        SettingDefinition[str | None](
            key="source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            function=FunctionId.FROST,
            default=None,
            fault_value=BLIND,
            parse=as_str,
        ),
        SettingDefinition(
            key="applies_to_protection",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.FROST,
            default=False,
            fault_value=True,
            parse=as_bool,
        ),
        SettingDefinition(
            key="threshold",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=0,
            fault_value=3,
            parse=as_int,
        ),
        SettingDefinition(
            key="position",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=Position(90),
            fault_value=Position(80),
            parse=_as_position,
        ),
        SettingDefinition(
            key="min_interval",
            kind=SettingKind.DURATION,
            function=FunctionId.MOTOR_PROTECTION,
            default=timedelta(minutes=10),
            fault_value=timedelta(minutes=20),
            parse=as_duration,
        ),
        # What only a window can set: a blocking contact.
        SettingDefinition[str | None](
            key="contact",
            kind=SettingKind.OPTIONAL_REFERENCE,
            function=FunctionId.LOCKOUT,
            default=None,
            fault_value=BLIND,
            parse=as_str,
            inheritable=False,
        ),
        SettingDefinition(
            key="offset",
            kind=SettingKind.NUMBER,
            function=FunctionId.SCHEDULE,
            default=5,
            parse=as_int,
        ),
    )
)
DEFINITIONS = {definition.key: definition for definition in REGISTRY.definitions}

INHERITABLE = [
    "source",
    "applies_to_protection",
    "threshold",
    "position",
    "min_interval",
]
"""One setting per kind: reference, switch, number, position, duration."""

VALID_STORED: dict[str, JsonValue] = {
    "source": "sensor.example_outdoor_temperature",
    "applies_to_protection": False,
    "threshold": 2,
    "position": 85,
    "min_interval": 300,
    "contact": "binary_sensor.example_terrace_door",
}
VALID: dict[str, object] = {
    "source": "sensor.example_outdoor_temperature",
    "applies_to_protection": False,
    "threshold": 2,
    "position": Position(85),
    "min_interval": timedelta(minutes=5),
    "contact": "binary_sensor.example_terrace_door",
}
FAULTY: JsonValue = {"broken": True}
"""No reader of any kind accepts an object."""

LEVELS = [Level.GLOBAL, Level.GROUP, Level.WINDOW]
ORDER = {Level.GLOBAL: 0, Level.GROUP: 1, Level.WINDOW: 2}
TWO_LEVELS = [(one, other) for one in LEVELS for other in LEVELS if one is not other]
"""Every pair of different levels: the faulty or unreadable one, and another."""


def _no_rules(_key: str, _value: object) -> None:
    return None


def _build(effective: Mapping[str, Any], _disabled: frozenset[FunctionId]) -> object:
    """One rule over two settings that fall back: a threshold of 9 needs a source."""
    if effective["threshold"] == 9 and effective["source"] is None:  # noqa: PLR2004
        raise SettingsCombinationError(
            "this threshold needs a source", ("threshold", "source")
        )
    return dict(effective)


def _resolve(stored: Mapping[Level, object]) -> ResolvedSettings:
    members = window().members
    return resolve_settings(
        REGISTRY,
        rules=SettingRules(_no_rules, _build),
        capabilities=WindowConfig("window_example", members).capability_states,
        members=members,
        global_settings=settings_from_stored(stored.get(Level.GLOBAL, {}), REGISTRY),
        group=GroupLevel(
            GROUP_ID, settings_from_stored(stored.get(Level.GROUP, {}), REGISTRY)
        ),
        window_settings=settings_from_stored(stored.get(Level.WINDOW, {}), REGISTRY),
    )


# --- A faulty value, per kind of setting and per level -----------------------------


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize("key", INHERITABLE)
def test_faulty_value_without_another_level_ends_at_the_fault_value(
    key: str, level: Level
) -> None:
    """Not at the default: the default of a reference or a switch means "off"."""
    resolved = _resolve({level: {key: FAULTY}})

    item = resolved.values[key]
    assert item.value == DEFINITIONS[key].fault_value
    assert item.value != DEFINITIONS[key].default
    assert item.effective == item.value
    assert (item.level, item.cautious) == (Level.BUILT_IN, True)
    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolved.faults
    ] == [
        (
            key,
            level,
            SettingProblem.UNREADABLE,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
        )
    ]
    assert resolved.disabled_functions == frozenset()
    # No other setting is touched: each of them keeps its default.
    for other in REGISTRY.keys:
        if other != key:
            assert resolved.values[other].value == DEFINITIONS[other].default
            assert not resolved.values[other].cautious


@pytest.mark.parametrize(("faulty_on", "valid_on"), TWO_LEVELS)
@pytest.mark.parametrize("key", INHERITABLE)
def test_valid_value_of_another_level_applies_and_the_fault_value_does_not(
    key: str, faulty_on: Level, valid_on: Level
) -> None:
    """Whether the valid value lies closer to the window or further out."""
    resolved = _resolve({faulty_on: {key: FAULTY}, valid_on: {key: VALID_STORED[key]}})

    item = resolved.values[key]
    assert item.value == VALID[key]
    assert (item.level, item.cautious) == (valid_on, False)
    (fault,) = resolved.faults
    closer = ORDER[valid_on] > ORDER[faulty_on]
    assert fault.action is (FaultAction.NO_EFFECT if closer else FaultAction.FELL_BACK)


def test_faulty_value_of_what_only_a_window_can_set_ends_at_its_fault_value() -> None:
    """A blocking contact that cannot be read is configured, but blind."""
    resolved = _resolve({Level.WINDOW: {"contact": FAULTY}})

    assert resolved.values["contact"].value == BLIND
    assert resolved.values["contact"].cautious
    assert [fault.action for fault in resolved.faults] == [
        FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
    ]


def test_value_refused_by_the_rules_ends_at_the_fault_value_too() -> None:
    """A value that was read and then refused is a fault like an unreadable one."""

    def refuse_negative(key: str, value: object) -> None:
        if key == "threshold" and isinstance(value, int) and value < 0:
            raise ValueError("the threshold must not be negative")

    members = window().members
    resolved = resolve_settings(
        REGISTRY,
        rules=SettingRules(refuse_negative, _build),
        capabilities=WindowConfig("window_example", members).capability_states,
        members=members,
        global_settings=PartialSettings(),
        window_settings=PartialSettings({"threshold": -1}),
    )

    assert resolved.values["threshold"].value == DEFINITIONS["threshold"].fault_value
    (fault,) = resolved.faults
    assert (fault.problem, fault.action) == (
        SettingProblem.INVALID,
        FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
    )


def test_explicit_none_of_a_closer_level_is_a_valid_value_and_beats_a_fault() -> None:
    """A source that was switched off on purpose is a decision of a person, no fault."""
    resolved = _resolve(
        {Level.GLOBAL: {"source": FAULTY}, Level.WINDOW: {"source": "__none__"}}
    )

    assert resolved.values["source"].value is None
    assert not resolved.values["source"].cautious
    assert [fault.action for fault in resolved.faults] == [FaultAction.NO_EFFECT]


def test_setting_of_a_function_that_pauses_still_takes_its_default() -> None:
    """The function is paused, so nobody acts on the value; it has no fault value."""
    resolved = _resolve({Level.WINDOW: {"offset": FAULTY}})

    assert resolved.values["offset"].value == DEFINITIONS["offset"].default
    assert not resolved.values["offset"].cautious
    assert [fault.action for fault in resolved.faults] == [
        FaultAction.FUNCTIONS_DISABLED
    ]


# --- A level that is unreadable as a whole -----------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_unreadable_level_hides_what_it_could_have_held(level: Level) -> None:
    """Nobody can see whether it had set a value, so the fault value applies.

    A setting that only a window can set is never touched by an unreadable
    house or group: one broken house level must not blind the blocking
    contact of every window.
    """
    resolved = _resolve({level: "not a mapping"})

    hidden = [*INHERITABLE, "contact"] if level is Level.WINDOW else INHERITABLE
    for key in hidden:
        item = resolved.values[key]
        assert item.value == DEFINITIONS[key].fault_value, key
        assert (item.level, item.cautious) == (Level.BUILT_IN, True), key
    if level is not Level.WINDOW:
        assert resolved.values["contact"].value is None
        assert not resolved.values["contact"].cautious
    assert not resolved.values["offset"].cautious
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
        *(
            (
                key,
                level,
                SettingProblem.LEVEL_UNREADABLE,
                FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
            )
            for key in REGISTRY.keys
            if key in hidden
        ),
    ]
    assert resolved.disabled_functions == {FunctionId.SCHEDULE}


@pytest.mark.parametrize(("unreadable", "valid_on"), TWO_LEVELS)
def test_unreadable_level_does_not_beat_a_valid_value_of_another_level(
    unreadable: Level, valid_on: Level
) -> None:
    """Protection runs with the values of the other levels; only the rest is hidden."""
    supplied = {key: VALID_STORED[key] for key in ("source", "position")}
    resolved = _resolve({unreadable: 7, valid_on: supplied})

    for key in supplied:
        item = resolved.values[key]
        assert (item.value, item.level, item.cautious) == (VALID[key], valid_on, False)
    assert resolved.values["threshold"].cautious
    reported = {fault.key for fault in resolved.faults}
    assert "threshold" in reported
    assert not reported & set(supplied)


def test_contact_of_the_window_survives_an_unreadable_house() -> None:
    """The window's own, valid contact applies; the house cannot have held one."""
    resolved = _resolve(
        {Level.GLOBAL: None, Level.WINDOW: {"contact": VALID_STORED["contact"]}}
    )

    contact = resolved.values["contact"]
    assert (contact.value, contact.level) == (VALID["contact"], Level.WINDOW)
    assert "contact" not in {fault.key for fault in resolved.faults}


def test_faulty_value_and_an_unreadable_level_are_both_named() -> None:
    """The window's value is faulty and the house is unreadable: two reports."""
    resolved = _resolve({Level.GLOBAL: [], Level.WINDOW: {"position": FAULTY}})

    assert resolved.values["position"].value == DEFINITIONS["position"].fault_value
    assert [
        (fault.level, fault.problem, fault.action)
        for fault in resolved.faults
        if fault.key == "position"
    ] == [
        (
            Level.WINDOW,
            SettingProblem.UNREADABLE,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
        ),
        (
            Level.GLOBAL,
            SettingProblem.LEVEL_UNREADABLE,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
        ),
    ]


# --- A rule over several settings of functions that fall back ----------------------


def test_refused_combination_ends_at_the_fault_values_when_no_level_is_left() -> None:
    """The window's threshold needs a source nobody names: it is passed by."""
    resolved = _resolve({Level.WINDOW: {"threshold": 9}})

    assert [
        (fault.key, fault.level, fault.problem, fault.action)
        for fault in resolved.faults
    ] == [
        (
            "threshold",
            Level.WINDOW,
            SettingProblem.COMBINATION,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
        )
    ]
    assert resolved.values["threshold"].value == DEFINITIONS["threshold"].fault_value
    assert resolved.values["threshold"].cautious
    # The source took no part in a fault of its own level: nobody set it.
    assert resolved.values["source"].value is None


def test_refused_combination_takes_the_valid_value_of_another_level_first() -> None:
    """The group's threshold fits, so it applies and no fault value is needed."""
    resolved = _resolve({Level.GROUP: {"threshold": 2}, Level.WINDOW: {"threshold": 9}})

    assert [(fault.key, fault.action) for fault in resolved.faults] == [
        ("threshold", FaultAction.FELL_BACK)
    ]
    threshold = resolved.values["threshold"]
    assert (threshold.value, threshold.level, threshold.cautious) == (
        2,
        Level.GROUP,
        False,
    )


def test_fault_values_of_the_window_build_together() -> None:
    """Falling back ends at the fault values, so together they satisfy every rule.

    An unreadable window makes every setting of a function that falls back
    take its fault value at once. The configuration is built, and no refusal
    of the whole is reported. The same test exists for the defaults.
    """
    resolution = resolve_window(
        window_id="window_example",
        members=window().members,
        global_settings=PartialSettings(),
        window_settings=settings_from_stored("not a mapping", WINDOW_SETTINGS),
    )

    assert resolution.config is not None
    assert {fault.problem for fault in resolution.settings.faults} == {
        SettingProblem.LEVEL_UNREADABLE
    }
    cautious = {
        key for key, item in resolution.settings.values.items() if item.cautious
    }
    assert cautious == {
        definition.key
        for definition in WINDOW_SETTINGS.definitions
        if definition.has_fault_value
    }
    for key in cautious:
        definition = next(d for d in WINDOW_SETTINGS.definitions if d.key == key)
        assert getattr(resolution.config, key) == definition.fault_value, key


# --- The safety net of the registry ------------------------------------------------


def _entry(**changes: Any) -> SettingDefinition[Any]:
    arguments: dict[str, Any] = {
        "key": "example_position",
        "kind": SettingKind.NUMBER,
        "function": FunctionId.VENTILATION,
        "default": 30,
        "parse": as_int,
    }
    return SettingDefinition(**(arguments | changes))


@pytest.mark.parametrize(
    "function",
    [
        function
        for function in FunctionId
        if function.fault_behavior is FaultBehavior.FALL_BACK
    ],
)
def test_entry_of_a_function_that_falls_back_does_not_construct_without_a_fault_value(
    function: FunctionId,
) -> None:
    """The message says what to add and what the value must never do."""
    with pytest.raises(ValueError, match="states its fault value") as refusal:
        _entry(function=function)

    message = str(refusal.value)
    assert "'example_position'" in message
    assert repr(function.value) in message
    assert "fault_value=<the cautious value>" in message
    assert "never make the function less restrictive" in message
    assert "if that is the default, state the default" in message


@pytest.mark.parametrize("stated", [None, False, 0, 30])
def test_falsy_value_and_the_default_are_fault_values_somebody_stated(
    stated: object,
) -> None:
    """The marker for "not stated" is its own, so none, off and zero can be stated."""
    entry = _entry(fault_value=stated)

    assert entry.has_fault_value
    assert entry.fault_value == stated
    assert entry.fault_value is not NO_FAULT_VALUE


@pytest.mark.parametrize(
    "changes",
    [
        {"function": FunctionId.SHADING},
        {"function": None, "inheritable": False},
    ],
    ids=["a function that pauses", "no function"],
)
def test_fault_value_is_refused_where_nothing_ends_at_it(
    changes: dict[str, Any],
) -> None:
    """A fault pauses the function, or nothing depends on the setting."""
    assert not _entry(**changes).has_fault_value
    with pytest.raises(ValueError, match="has no fault value"):
        _entry(**changes, fault_value=30)


def _fault_value_mismatches(registry: SettingsRegistry) -> list[str]:
    """Judge the fault values of a registry of the window, with advice.

    An entry cannot be constructed without its fault value; this is the
    second net, for an entry that was built around the constructor, and the
    only place that checks that the window configuration accepts the value.
    """
    settings_module = "custom_components/roller_shutter_suite/core/settings.py"
    identity = window()
    messages: list[str] = []
    for definition in registry.definitions:
        if not definition.falls_back_cautiously:
            continue
        if not definition.has_fault_value:
            messages.append(
                f"The setting {definition.key!r} belongs to a function that falls "
                f"back and states no fault value. Add 'fault_value=<the cautious "
                f"value>' to its entry in WINDOW_SETTINGS in {settings_module}: "
                f"the value that never makes the function less restrictive than "
                f"a valid value would; often the default {definition.default!r}, "
                f"but never a default that means 'not configured' or 'off'."
            )
            continue
        change: dict[str, Any] = {definition.key: definition.fault_value}
        try:
            dataclasses.replace(identity, **change)
        except (TypeError, ValueError) as err:
            messages.append(
                f"The window configuration refuses the fault value "
                f"{definition.fault_value!r} of the setting {definition.key!r} "
                f"({err}). State a value in {settings_module} that the field "
                f"accepts; falling back must never end at a refused value."
            )
    return messages


def test_every_setting_of_the_window_that_falls_back_states_a_valid_fault_value() -> (
    None
):
    """The safety net: the failure says what to add where."""
    mismatches = _fault_value_mismatches(WINDOW_SETTINGS)

    assert not mismatches, "\n".join(mismatches)
    stated = {
        definition.key
        for definition in WINDOW_SETTINGS.definitions
        if definition.has_fault_value
    }
    assert stated == {
        definition.key
        for definition in WINDOW_SETTINGS.definitions
        if definition.function is not None
        and definition.function.fault_behavior is FaultBehavior.FALL_BACK
    }
    assert stated  # the comparison above is not empty on both sides


def test_safety_net_advises_for_a_missing_and_for_a_refused_fault_value() -> None:
    """Both messages, shown with entries that were built around the constructor."""
    missing = _entry(key="frost_position", function=FunctionId.FROST, fault_value=90)
    object.__setattr__(missing, "fault_value", NO_FAULT_VALUE)
    refused = _entry(key="frost_position", function=FunctionId.FROST, fault_value=90)

    no_value, wrong_value = (
        *_fault_value_mismatches(SettingsRegistry((missing,))),
        *_fault_value_mismatches(SettingsRegistry((refused,))),
    )

    assert "'frost_position' belongs to a function that falls back" in no_value
    assert "fault_value=<the cautious value>" in no_value
    assert "core/settings.py" in no_value
    assert "refuses the fault value 90 of the setting 'frost_position'" in wrong_value
