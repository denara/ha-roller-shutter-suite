"""The settings of block C07: the fire source, the events, the exception, the blind time.

Protection events are a list of the house (``protection_events``), read
leniently field by field; an unreadable list as a whole is "configured, but
unreadable" (ruling of the project owner of 2026-10-01). The sleep-room
exception is the per-window part. The blind time is one setting of the house
for every kind of source (ruling of 2026-09-29).
"""

from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    EVENTS_UNREADABLE,
    EventDirection,
    ProtectionEventConfig,
    ProtectionTrigger,
    TriggerType,
)
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    FaultAction,
    GroupLevel,
    Level,
    SettingProblem,
    WindowResolution,
    as_protection_events,
    resolve_window,
    settings_from_stored,
)
from tests.core.arbiter_kit import window

STORM: dict[str, Any] = {
    "event_id": "storm",
    "source": "binary_sensor.example_storm",
    "direction": "closed",
    "rank": 10,
}


def _resolve(
    *,
    house: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    own: dict[str, Any] | None = None,
) -> WindowResolution:
    return resolve_window(
        window_id="window.example",
        members=window().members,
        global_settings=settings_from_stored(house or {}, WINDOW_SETTINGS),
        group=GroupLevel(
            "group.example", settings_from_stored(group or {}, WINDOW_SETTINGS)
        ),
        window_settings=settings_from_stored(own or {}, WINDOW_SETTINGS),
    )


# --- Reading one level ------------------------------------------------------------


def test_a_stored_event_is_read_with_its_defaults() -> None:
    """A binary trigger by default, 30 minutes of waiting, 12 hours of maximum."""
    (event,) = as_protection_events([STORM])

    assert event == ProtectionEventConfig(
        event_id="storm",
        trigger=ProtectionTrigger("binary_sensor.example_storm"),
        direction=EventDirection.CLOSED,
        rank=10,
    )


def test_every_kind_of_trigger_is_read() -> None:
    """Binary with invert, a list of states, a number with a threshold."""
    calm = {**STORM, "event_id": "calm", "rank": 1, "invert": True}
    warning = {
        **STORM,
        "event_id": "warning",
        "rank": 2,
        "trigger": "states",
        "states": ["orange", "red"],
    }
    wind = {
        **STORM,
        "event_id": "wind",
        "rank": 3,
        "trigger": "threshold",
        "threshold": 60,
        "hysteresis": 10.5,
        "invert": False,
        "waiting_time": 600,
        "max_duration": 0,
    }

    first, second, third = as_protection_events([calm, warning, wind])

    assert first.trigger == ProtectionTrigger(STORM["source"], invert=True)
    assert second.trigger == ProtectionTrigger(
        STORM["source"], TriggerType.STATES, states=("orange", "red")
    )
    assert third.trigger == ProtectionTrigger(
        STORM["source"], TriggerType.THRESHOLD, threshold=60.0, hysteresis=10.5
    )
    assert third.waiting_time == timedelta(minutes=10)
    assert third.max_duration == timedelta(0)
    assert all(not event.faulty_fields for event in (first, second, third))


@pytest.mark.parametrize(
    ("changes", "faulty", "expected"),
    [
        ({"direction": "sideways"}, ("direction",), {"direction": None}),
        ({"direction": None}, ("direction",), {"direction": None}),
        ({"rank": "high"}, ("rank",), {"rank": None}),
        ({"rank": 0}, ("rank",), {"rank": None}),
        (
            {"waiting_time": -5},
            ("waiting_time",),
            {"waiting_time": timedelta(minutes=30)},
        ),
        (
            {"waiting_time": 2 * 24 * 3600},
            ("waiting_time",),
            {"waiting_time": timedelta(minutes=30)},
        ),
        (
            {"max_duration": "never"},
            ("max_duration",),
            {"max_duration": timedelta(hours=12)},
        ),
        (
            {"max_duration": 30 * 24 * 3600},
            ("max_duration",),
            {"max_duration": timedelta(hours=12)},
        ),
        ({"source": 7}, ("source",), {"trigger": None}),
        ({"source": ""}, ("source",), {"trigger": None}),
        ({"trigger": "morse"}, ("trigger",), {"trigger": None}),
        ({"trigger": "states"}, ("states",), {"trigger": None}),
        ({"trigger": "states", "states": []}, ("states",), {"trigger": None}),
        ({"trigger": "threshold"}, ("threshold",), {"trigger": None}),
        (
            {"trigger": "threshold", "threshold": 5, "hysteresis": -1},
            ("hysteresis",),
            {"trigger": None},
        ),
        ({"invert": "yes"}, ("invert",), {"trigger": None}),
        ({"colour": "red"}, ("colour",), {}),
    ],
)
def test_a_fault_inside_one_event_takes_the_cautious_value_of_its_field(
    changes: dict[str, Any], faulty: tuple[str, ...], expected: dict[str, Any]
) -> None:
    """Item 7 of the scope; the field is named, and the event keeps working."""
    missing = {key: value for key, value in changes.items() if value is not None}
    stored = {**STORM, **missing}
    if changes.get("direction", "") is None:
        del stored["direction"]

    (event,) = as_protection_events([stored])

    assert event.faulty_fields == faulty
    for field, value in expected.items():
        assert getattr(event, field) == value, field
    assert event.event_id == "storm"


def test_a_stored_null_inside_an_event_is_a_fault_of_its_field() -> None:
    """``null`` is never written; it is not a second way to say "absent"."""
    (event,) = as_protection_events([{**STORM, "rank": None}])

    assert event.rank is None
    assert event.faulty_fields == ("rank",)


def test_a_key_that_does_not_belong_to_the_kind_is_reported_and_changes_nothing() -> (
    None
):
    """A threshold on a binary trigger, an invert on states: named, not blind."""
    binary = {**STORM, "threshold": 5}
    states = {**STORM, "trigger": "states", "states": ["red"], "invert": True}

    (first,) = as_protection_events([binary])
    (second,) = as_protection_events([states])

    assert first.trigger == ProtectionTrigger(STORM["source"])
    assert first.faulty_fields == ("threshold",)
    assert second.trigger is not None
    assert second.faulty_fields == ("invert",)


def test_a_rank_that_two_events_state_is_faulty_on_both() -> None:
    """A duplicate rank is read leniently (ruling of the project owner, 2026-10-01).

    Both events that state it lose their rank and name ``rank`` among their
    faulty fields; the rest of the list stays valid. A duplicate never
    reaches the arbiter.
    """
    gale = {**STORM, "event_id": "gale"}
    hail = {**STORM, "event_id": "hail", "rank": 20, "direction": "open"}

    storm, second, third = as_protection_events([STORM, gale, hail])

    assert (storm.rank, second.rank, third.rank) == (None, None, 20)
    assert storm.faulty_fields == second.faulty_fields == ("rank",)
    assert third.faulty_fields == ()


@pytest.mark.parametrize(
    "stored",
    [
        "storm",
        [STORM, STORM],
        ["storm"],
        [{"source": "binary_sensor.example_storm"}],
        [{**STORM, "event_id": "  "}],
    ],
    ids=["no list", "the same event twice", "no object", "no identifier", "blank"],
)
def test_a_list_without_readable_identifiers_is_refused_as_a_whole(stored: Any) -> None:
    """The persisted state of an event is found by its identifier."""
    with pytest.raises(ValueError):  # noqa: PT011 - each case has its own message
        as_protection_events(stored)


# --- Resolving a window -----------------------------------------------------------


def test_an_unreadable_list_is_configured_but_unreadable_not_empty() -> None:
    """An empty list would take protection away; the fault value holds instead."""
    resolution = _resolve(house={"protection_events": "not a list"})

    assert resolution.config is not None
    assert resolution.config.protection_events is EVENTS_UNREADABLE
    item = resolution.settings.values["protection_events"]
    assert (item.level, item.cautious) == (Level.BUILT_IN, True)
    (fault,) = resolution.settings.faults
    assert fault.problem is SettingProblem.UNREADABLE
    assert fault.action is FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE


def test_an_unreadable_house_leaves_the_events_configured_but_unreadable() -> None:
    """Nobody can see whether the house named events: the fault value applies."""
    resolution = resolve_window(
        window_id="window.example",
        members=window().members,
        global_settings=settings_from_stored("not a mapping", WINDOW_SETTINGS),
        window_settings=settings_from_stored({}, WINDOW_SETTINGS),
    )

    assert resolution.config is not None
    assert resolution.config.protection_events is EVENTS_UNREADABLE
    assert resolution.config.fire_source is BLIND_SOURCE
    assert resolution.config.protection_sleep_exception == ()
    assert resolution.config.source_blind_after == timedelta(hours=1)


def test_a_valid_list_of_a_group_stands_in_for_an_unreadable_one_of_the_house() -> None:
    """Fall back: another level that supplies a valid value decides."""
    resolution = _resolve(
        house={"protection_events": 7}, group={"protection_events": [STORM]}
    )

    assert resolution.config is not None
    assert [event.event_id for event in resolution.config.protection_events] == [  # type: ignore[union-attr]
        "storm"
    ]


def test_the_other_settings_of_the_block_fall_back_to_their_fault_values() -> None:
    """A faulty fire source is blind; a faulty exception is none; the hour stays."""
    resolution = _resolve(
        house={"fire_source": 7, "source_blind_after": "soon"},
        own={"protection_sleep_exception": "hail"},
    )

    assert resolution.config is not None
    assert resolution.config.fire_source is BLIND_SOURCE
    assert resolution.config.protection_sleep_exception == ()
    assert resolution.config.source_blind_after == timedelta(hours=1)
    assert not resolution.config.disabled_functions


def test_the_settings_resolve_with_valid_values() -> None:
    """The house names the fire source and the events, a window its exception."""
    resolution = _resolve(
        house={
            "fire_source": "binary_sensor.example_smoke",
            "protection_events": [STORM],
            "source_blind_after": 1800,
        },
        own={"protection_sleep_exception": ["storm"]},
    )

    assert resolution.config is not None
    assert resolution.config.fire_source == "binary_sensor.example_smoke"
    assert resolution.config.protection_sleep_exception == ("storm",)
    assert resolution.config.source_blind_after == timedelta(minutes=30)
    assert not resolution.settings.faults
