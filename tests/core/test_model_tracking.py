"""The types the tracker and the dams add to the model (block C06).

What the tracker keeps per member (``MemberTracking``), what it measures
(``SelfMeasurement``), what it reports (``TrackerEvent``), the daily count, the
optional keys of the persisted state within schema version 1, and the
settings of the dams on the window configuration.
"""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    DEFAULT_PERSON_AT_WINDOW,
    SELF_MEASUREMENT_SAMPLES,
    ComfortMovementCount,
    ManualOverrideDam,
    ManualOverrideSettings,
    MemberState,
    MemberTracking,
    OverrideEndRule,
    PersonAtWindowDam,
    Position,
    SampleStatistic,
    SelfMeasurement,
    TrackerEvent,
    TrackerPhase,
    Transition,
    WindowState,
)
from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
)
from tests.core.arbiter_kit import LEFT, NOW, window
from tests.core.tracking_kit import UNAVAILABLE, resting

NAIVE = datetime(2026, 1, 15, 7, 30)  # noqa: DTZ001 - the rejected case


# --- MemberTracking ------------------------------------------------------------------


@pytest.mark.parametrize(
    "tracking",
    [
        MemberTracking(),
        MemberTracking(phase=TrackerPhase.EXPECTING, command_id="c-1"),
        MemberTracking(
            phase=TrackerPhase.MOVING,
            command_id="c-1",
            moved_at=NOW,
            transit_seen=True,
        ),
        MemberTracking(
            phase=TrackerPhase.SETTLING,
            external=True,
            detected=True,
            moved_at=NOW,
            rested_at=NOW + timedelta(seconds=12),
            user_hint="user-example",
        ),
        MemberTracking(before_gap=resting(40)),
    ],
    ids=["idle", "expecting", "moving", "settling", "gap"],
)
def test_the_tracking_of_a_member_goes_through_plain_data(
    tracking: MemberTracking,
) -> None:
    """Every phase survives a restart; instants are kept in UTC."""
    assert MemberTracking.from_data(tracking.to_data()) == tracking
    if tracking.moved_at is not None:
        assert tracking.moved_at.tzinfo is UTC


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        (
            {"command_id": "c-1", "external": True, "phase": TrackerPhase.MOVING},
            "either",
        ),
        (
            {"detected": True, "phase": TrackerPhase.MOVING, "command_id": "c-1"},
            "only an external",
        ),
        ({"command_id": "c-1"}, "idle tracker follows no movement"),
        ({"moved_at": NOW}, "idle tracker"),
        ({"phase": TrackerPhase.EXPECTING}, "waits for an own command"),
        (
            {"phase": TrackerPhase.EXPECTING, "command_id": "c-1", "moved_at": NOW},
            "waits for an own command",
        ),
        ({"phase": TrackerPhase.MOVING}, "belongs to an own command"),
        (
            {"phase": TrackerPhase.SETTLING, "command_id": "c-1"},
            "knows when the member came to rest",
        ),
        (
            {"phase": TrackerPhase.MOVING, "command_id": "c-1", "rested_at": NOW},
            "only a settling tracker",
        ),
        ({"before_gap": UNAVAILABLE}, "available one"),
        ({"command_id": ""}, "must not be empty"),
    ],
)
def test_the_tracking_of_a_member_refuses_what_contradicts_its_phase(
    changes: dict[str, Any], message: str
) -> None:
    """An object that exists is valid."""
    with pytest.raises(ValueError, match=message):
        MemberTracking(**changes)


def test_the_tracking_refuses_wrong_types_and_naive_times() -> None:
    """The model validates on construction."""
    with pytest.raises(TypeError, match="phase"):
        MemberTracking(phase="idle")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="external"):
        MemberTracking(external=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="timezone-aware"):
        MemberTracking(phase=TrackerPhase.MOVING, external=True, moved_at=NAIVE)
    with pytest.raises(TypeError, match="user hint"):
        MemberTracking(user_hint=3)  # type: ignore[arg-type]
    assert not MemberTracking().follows_own_command


# --- SelfMeasurement -------------------------------------------------------------------


def test_the_self_measurement_keeps_the_last_twenty_samples_and_their_median() -> None:
    """The median, never the mean: one movement cut short does not distort it."""
    measured = SelfMeasurement()
    for sample in range(25):
        measured = measured.with_sample(700 + sample, 20000, 0)
    cut_short = measured.with_sample(700, 20000, 60)

    assert len(measured.latency_ms) == SELF_MEASUREMENT_SAMPLES
    assert measured.latency_ms[0] == 705  # noqa: PLR2004 - the oldest five are gone
    assert measured.latency == SampleStatistic(20, 714.5, 724)
    assert cut_short.end_deviation == SampleStatistic(20, 0.0, 60)
    assert cut_short.time_to_rest.median == 20000.0  # noqa: PLR2004 - all equal
    assert SelfMeasurement().latency == SampleStatistic(0, None, None)
    assert SelfMeasurement.from_data(cut_short.to_data()) == cut_short


def test_the_self_measurement_refuses_what_is_no_sample() -> None:
    """Whole numbers, not negative, at most twenty."""
    with pytest.raises(TypeError, match="whole number"):
        SelfMeasurement(latency_ms=(1.5,))  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="whole number"):
        SelfMeasurement(rest_ms=(True,))
    with pytest.raises(ValueError, match="not negative"):
        SelfMeasurement(deviation=(-1,))
    with pytest.raises(ValueError, match="at most 20"):
        SelfMeasurement(latency_ms=tuple(range(21)))


# --- TrackerEvent, Transition -------------------------------------------------------


def test_an_event_carries_an_event_code_and_its_subject_as_attributes() -> None:
    """The subject is never part of the code (section 5)."""
    event = TrackerEvent(ReasonCode.COMFORT_MOVEMENTS_THRESHOLD, count=41, threshold=40)

    assert event.to_data() == {
        "code": "comfort_movements_threshold",
        "member_id": None,
        "position": None,
        "count": 41,
        "threshold": 40,
        "user_id": None,
        "event_id": None,
        "source": None,
    }
    with pytest.raises(ValueError, match="group 'event'"):
        TrackerEvent(ReasonCode.SENT)
    with pytest.raises(ValueError, match="group 'event'"):
        TrackerEvent(ReasonCode.INPUT_HELD_LAST_KNOWN)


def test_the_release_by_the_watchdog_is_an_event_with_the_event_and_its_source() -> (
    None
):
    """``watchdog_released`` stays a code of its group and is raised as an event too."""
    event = TrackerEvent(
        ReasonCode.WATCHDOG_RELEASED,
        event_id="storm",
        source="binary_sensor.example_storm",
    )

    assert event.to_data()["event_id"] == "storm"
    assert event.to_data()["source"] == "binary_sensor.example_storm"
    assert ReasonCode.WATCHDOG_RELEASED.category is not ReasonCategory.EVENT
    with pytest.raises(ValueError, match="empty"):
        TrackerEvent(ReasonCode.PROTECTION_STARTED, event_id="")
    with pytest.raises(TypeError, match="source"):
        TrackerEvent(ReasonCode.PROTECTION_STARTED, source=7)  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="count"):
        TrackerEvent(ReasonCode.OVERRIDE_ENDED, count=True)
    with pytest.raises(ValueError, match="must not be empty"):
        TrackerEvent(ReasonCode.OVERRIDE_ENDED, member_id="")
    with pytest.raises(TypeError, match="position"):
        TrackerEvent(ReasonCode.OVERRIDE_ENDED, position=40)  # type: ignore[arg-type]


def test_a_transition_holds_a_state_and_its_events() -> None:
    """What a call of the engine returns."""
    transition = Transition(WindowState(), [TrackerEvent(ReasonCode.OVERRIDE_ENDED)])  # type: ignore[arg-type]

    assert transition.events == (TrackerEvent(ReasonCode.OVERRIDE_ENDED),)
    with pytest.raises(TypeError, match="state"):
        Transition("state")  # type: ignore[arg-type]
    with pytest.raises(TypeError, match="event"):
        Transition(WindowState(), ("event",))  # type: ignore[arg-type]


# --- The daily count --------------------------------------------------------------


def test_the_daily_count_is_a_count_on_a_date() -> None:
    """A date, not a datetime; a whole number that is not negative."""
    with pytest.raises(TypeError, match="per date"):
        ComfortMovementCount(NOW)
    with pytest.raises(TypeError, match="whole number"):
        ComfortMovementCount(date(2026, 1, 15), count=True)
    with pytest.raises(ValueError, match="not negative"):
        ComfortMovementCount(date(2026, 1, 15), count=-1)
    with pytest.raises(TypeError, match="reported"):
        ComfortMovementCount(date(2026, 1, 15), reported=1)  # type: ignore[arg-type]


# --- The persisted state keeps its schema version ----------------------------------------


def test_member_state_written_before_block_c06_is_read() -> None:
    """Tracking, self-measurement and the missed command are optional keys."""
    data = MemberState(LEFT).to_data()
    for key in ("tracking", "self_measurement", "missed_command"):
        del data[key]

    assert MemberState.from_data(data) == MemberState(LEFT)


def test_dams_written_before_block_c06_are_read() -> None:
    """The time the room was seen empty and the person's position are optional keys."""
    override = ManualOverrideDam(
        NOW, OverrideEndRule.ROOM_EMPTY, room_empty_since=NOW
    ).to_data()
    person = PersonAtWindowDam(NOW, remembered_position=Position(40)).to_data()
    del override["room_empty_since"]
    del person["remembered_position"]

    assert ManualOverrideDam.from_data(override) == ManualOverrideDam(
        NOW, OverrideEndRule.ROOM_EMPTY
    )
    assert PersonAtWindowDam.from_data(person) == PersonAtWindowDam(NOW)


def test_a_state_with_everything_of_the_tracker_goes_through_plain_data() -> None:
    """Round trip of the whole window state with the new parts."""
    member = MemberState(
        LEFT,
        last_observation=resting(40),
        tracking=MemberTracking(before_gap=resting(40)),
        self_measurement=SelfMeasurement().with_sample(700, 20000, 1),
    )
    state = WindowState(
        members=(member,),
        manual_override=ManualOverrideDam(
            NOW,
            OverrideEndRule.ROOM_EMPTY,
            remembered_position=Position(40),
            room_empty_since=NOW,
        ),
        person_at_window=PersonAtWindowDam(NOW, remembered_position=Position(40)),
        comfort_movements=ComfortMovementCount(date(2026, 1, 15), 3, reported=False),
    )

    assert WindowState.from_data(state.to_data()) == state


def test_the_window_state_answers_for_one_member() -> None:
    """A member the state keeps nothing for is a fresh one; replacing keeps the order."""
    first = MemberState(LEFT, last_observation=resting(10))
    second = MemberState("cover.example_right")
    state = WindowState(members=(first, second))

    assert state.member_state("cover.example_other") == MemberState(
        "cover.example_other"
    )
    changed = state.with_member(replace(first, last_observation=resting(20)))
    assert [m.member_id for m in changed.members] == [LEFT, "cover.example_right"]
    added = WindowState().with_member(first)
    assert added.members == (first,)
    assert not state.moving


# --- The settings of the dams on the window configuration --------------------------------


def test_the_settings_of_the_dams_are_a_view_of_the_window_configuration() -> None:
    """One field per setting, inherited one by one; the view holds their rules."""
    config = window(
        override_end_rule=OverrideEndRule.ROOM_EMPTY,
        override_presence_source="binary_sensor.example_presence",
        override_room_empty_after=timedelta(minutes=20),
    )

    assert config.manual_override == ManualOverrideSettings(
        end_rule=OverrideEndRule.ROOM_EMPTY,
        presence_source="binary_sensor.example_presence",
        room_empty_after=timedelta(minutes=20),
    )
    assert window().manual_override.person_at_window == DEFAULT_PERSON_AT_WINDOW
    assert window(
        override_presence_source=BLIND_SOURCE
    ).manual_override.presence_source is (BLIND_SOURCE)


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        (
            {"override_minutes": timedelta(seconds=30)},
            ValueError,
            "one minute and one day",
        ),
        ({"person_at_window_duration": timedelta(days=2)}, ValueError, "one minute"),
        ({"override_room_empty_after": 30}, TypeError, "empty room"),
        ({"override_end_rule": "next_part_of_day"}, TypeError, "end rule"),
        ({"override_presence_source": ""}, ValueError, "must not be empty"),
        ({"comfort_movements_threshold": 0}, ValueError, "within 1 and"),
        ({"comfort_movements_threshold": 2.5}, TypeError, "whole number"),
    ],
)
def test_the_window_configuration_refuses_faulty_settings_of_the_dams(
    changes: dict[str, Any], error: type[Exception], message: str
) -> None:
    """The value rules live in the model; the registry reads them."""
    with pytest.raises(error, match=message):
        window(**changes)
