"""The model of block C07: events of the house, their persisted state, subjects."""

from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    EVENTS_UNREADABLE,
    FULLY_CLOSED,
    FULLY_OPEN,
    BlindClock,
    EventDirection,
    Layer,
    LayerReason,
    Position,
    PositionOwner,
    ProtectionEventConfig,
    ProtectionEventState,
    ProtectionEventStatus,
    ProtectionTrigger,
    TriggerType,
    WindowState,
    Wish,
    WishSubject,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import NOW, window
from tests.core.protection_kit import HAIL_EVENT, STORM, STORM_EVENT


def test_the_direction_of_an_event_is_an_end_position() -> None:
    """Never in between (section 6 of the brief)."""
    assert EventDirection.OPEN.end_position == FULLY_OPEN
    assert EventDirection.CLOSED.end_position == FULLY_CLOSED


def test_a_trigger_states_only_what_its_kind_uses() -> None:
    """States for a trigger of states, a threshold for a threshold."""
    assert ProtectionTrigger(STORM).kind is TriggerType.BINARY
    assert ProtectionTrigger(STORM, TriggerType.STATES, states=("storm",)).states == (
        "storm",
    )
    ProtectionTrigger(STORM, TriggerType.THRESHOLD, threshold=12.5, hysteresis=2)
    ProtectionTrigger(STORM, invert=True)
    for arguments, error in (
        ({"kind": TriggerType.STATES}, ValueError),
        ({"states": ("storm",)}, ValueError),
        ({"threshold": 3.0}, ValueError),
        ({"hysteresis": 1.0}, ValueError),
        ({"kind": TriggerType.THRESHOLD, "hysteresis": -1.0}, ValueError),
        ({"kind": TriggerType.THRESHOLD, "threshold": float("nan")}, ValueError),
        (
            {"kind": TriggerType.STATES, "states": ("a",), "invert": True},
            ValueError,
        ),
        ({"kind": TriggerType.STATES, "states": ("a", "a")}, ValueError),
        ({"kind": TriggerType.STATES, "states": ("",)}, ValueError),
        ({"invert": 1}, TypeError),
        ({"kind": "binary"}, TypeError),
    ):
        with pytest.raises(error):
            ProtectionTrigger(STORM, **arguments)
    with pytest.raises(ValueError, match="empty"):
        ProtectionTrigger("")


def _event(**changes: Any) -> ProtectionEventConfig:
    arguments: dict[str, Any] = {
        "event_id": "storm",
        "trigger": ProtectionTrigger(STORM),
        "direction": EventDirection.CLOSED,
        "rank": 10,
    }
    return ProtectionEventConfig(**(arguments | changes))


def test_an_event_has_the_defaults_of_the_specification() -> None:
    """Waiting time 30 minutes, maximum duration 12 hours (sections 10.1 and 10.3)."""
    event = _event()

    assert event.waiting_time == timedelta(minutes=30)
    assert event.max_duration == timedelta(hours=12)
    assert event.faulty_fields == ()


def test_a_missing_value_of_an_event_is_named_as_a_fault() -> None:
    """``None`` in the trigger, the direction or the rank is only a fault."""
    for field in ("trigger", "direction", "rank"):
        with pytest.raises(ValueError, match="names the faulty fields"):
            _event(**{field: None})
        assert _event(**{field: None}, faulty_fields=(field,)).faulty_fields == (field,)


@pytest.mark.parametrize(
    ("changes", "error"),
    [
        ({"rank": 0}, ValueError),
        ({"rank": 1001}, ValueError),
        ({"rank": True}, TypeError),
        ({"rank": 1.0}, TypeError),
        ({"waiting_time": timedelta(hours=25)}, ValueError),
        ({"waiting_time": timedelta(seconds=-1)}, ValueError),
        ({"max_duration": timedelta(days=8)}, ValueError),
        ({"max_duration": 5}, TypeError),
        ({"trigger": STORM}, TypeError),
        ({"direction": "open"}, TypeError),
        ({"faulty_fields": ("rank", "rank")}, ValueError),
        ({"faulty_fields": ("",)}, ValueError),
        ({"event_id": ""}, ValueError),
    ],
)
def test_an_event_refuses_values_out_of_its_rules(
    changes: dict[str, Any], error: type[Exception]
) -> None:
    """Ranks 1 to 1000, a waiting time up to a day, a maximum up to a week."""
    with pytest.raises(error):
        _event(**changes)


def test_the_window_takes_the_events_and_their_unique_identifiers_and_ranks() -> None:
    """A duplicate never reaches the arbiter; the reader marks it faulty."""
    config = window(protection_events=(STORM_EVENT, HAIL_EVENT))

    assert config.protection_events == (STORM_EVENT, HAIL_EVENT)
    assert window(protection_events=EVENTS_UNREADABLE).protection_events is (
        EVENTS_UNREADABLE
    )
    with pytest.raises(ValueError, match="identifiers of protection events"):
        window(protection_events=(STORM_EVENT, STORM_EVENT))
    with pytest.raises(ValueError, match="ranks of protection events"):
        window(protection_events=(STORM_EVENT, _event(event_id="gale")))
    faulty = _event(event_id="gale", rank=None, faulty_fields=("rank",))
    assert window(protection_events=(STORM_EVENT, faulty)).protection_events
    with pytest.raises(TypeError, match="tuple"):
        window(protection_events=[STORM_EVENT])
    with pytest.raises(TypeError, match="a protection event"):
        window(protection_events=("storm",))


def test_the_window_takes_a_fire_source_a_sleep_exception_and_a_blind_time() -> None:
    """One minute to one week for the blind time; identifiers for the rest."""
    config = window(
        fire_source="binary_sensor.example_smoke",
        protection_sleep_exception=("hail",),
        source_blind_after=timedelta(minutes=30),
    )

    assert config.fire_source == "binary_sensor.example_smoke"
    assert window(fire_source=BLIND_SOURCE).fire_source is BLIND_SOURCE
    assert config.protection_sleep_exception == ("hail",)
    assert window().source_blind_after == timedelta(hours=1)
    for changes, error in (
        ({"fire_source": ""}, ValueError),
        ({"protection_sleep_exception": ["hail"]}, TypeError),
        ({"protection_sleep_exception": ("hail", "hail")}, ValueError),
        ({"protection_sleep_exception": ("",)}, ValueError),
        ({"source_blind_after": timedelta(seconds=59)}, ValueError),
        ({"source_blind_after": timedelta(days=8)}, ValueError),
        ({"source_blind_after": 3600}, TypeError),
    ):
        with pytest.raises(error):
            window(**changes)


# --- The persisted state ----------------------------------------------------------


def test_a_blind_clock_goes_through_plain_data() -> None:
    """Kept in UTC, like every persisted instant."""
    clock = BlindClock(NOW, reported=True)

    assert BlindClock.from_data(clock.to_data()) == clock
    assert clock.missing_since.utcoffset() == timedelta(0)
    with pytest.raises(ValueError, match="timezone-aware"):
        BlindClock(NOW.replace(tzinfo=None))
    with pytest.raises(TypeError, match="reported"):
        BlindClock(NOW, reported=1)  # type: ignore[arg-type]


def test_the_new_keys_of_an_event_state_go_through_plain_data() -> None:
    """The override of the start and the blind clock; optional in schema 1."""
    state = ProtectionEventState(
        "storm",
        ProtectionEventStatus.ACTIVE,
        active_since=NOW,
        remembered_position=Position(40),
        remembered_owner=PositionOwner.USER,
        override_armed_at=NOW - timedelta(hours=1),
        blind=BlindClock(NOW),
    )

    assert ProtectionEventState.from_data(state.to_data()) == state
    older = state.to_data()
    del older["override_armed_at"], older["blind"]
    assert ProtectionEventState.from_data(older) == ProtectionEventState(
        "storm",
        ProtectionEventStatus.ACTIVE,
        active_since=NOW,
        remembered_position=Position(40),
        remembered_owner=PositionOwner.USER,
    )
    with pytest.raises(TypeError, match="blind clock"):
        ProtectionEventState("storm", blind=NOW)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        ProtectionEventState("storm", override_armed_at=NOW.replace(tzinfo=None))


def test_the_fire_keys_of_the_window_state_go_through_plain_data() -> None:
    """The held alarm and its blind clock; optional in schema 1."""
    state = WindowState(
        fire_alarm_active=True, fire_unacknowledged=True, fire_blind=BlindClock(NOW)
    )

    assert WindowState.from_data(state.to_data()) == state
    older = WindowState().to_data()
    del older["fire_alarm_active"], older["fire_blind"]
    assert WindowState.from_data(older) == WindowState()
    with pytest.raises(TypeError, match="held state of the fire alarm"):
        WindowState(fire_alarm_active=1)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="fire_blind"):
        WindowState(fire_blind=NOW)  # type: ignore[arg-type]


# --- The subject of a wish --------------------------------------------------------


def test_a_wish_carries_its_subject_as_attributes_never_in_the_code() -> None:
    """Every kind of wish can name the event and its source (section 5)."""
    subject = WishSubject(event_id="storm", source=STORM)
    wish = Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED)

    assert wish.about(subject).subject == subject
    assert Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE).about(
        subject
    ).subject == (subject)
    reason = LayerReason(Layer.PROTECTION, ReasonCode.WATCHDOG_RELEASED, None, subject)
    assert reason.subject == subject
    held = WishSubject(held=ReasonCode.INPUT_HELD_LAST_KNOWN)
    assert held.event_id is None
    with pytest.raises(ValueError, match="why the input of a subject is held"):
        WishSubject(held=ReasonCode.PROTECTION_EVENT)
    with pytest.raises(ValueError, match="empty"):
        WishSubject(event_id="")
    with pytest.raises(TypeError, match="subject of a wish"):
        Wish.target(
            Layer.PROTECTION,
            ReasonCode.PROTECTION_EVENT,
            FULLY_CLOSED,
        ).about("storm")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="subject of a reason"):
        LayerReason(Layer.PROTECTION, ReasonCode.INACTIVE, None, "storm")  # type: ignore[arg-type]
