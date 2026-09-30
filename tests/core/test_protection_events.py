"""The life cycle of a protection event: start, end, watchdog, waiting time, return.

Every test drives the engine as the runtime does: ``Engine.elapse`` persists
what the sources did, then ``Engine.recompute`` decides. The layer judges
the trigger live, so a test that skips ``elapse`` gets the same decision.
"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.roller_shutter_suite.core.engine import Engine
from custom_components.roller_shutter_suite.core.model import (
    EVENTS_UNREADABLE,
    FULLY_CLOSED,
    FULLY_OPEN,
    AnySourceValue,
    BlindClock,
    Decision,
    EventDirection,
    GateKind,
    OverrideEndRule,
    PersonAtWindowDam,
    Position,
    PositionOwner,
    ProtectionEventConfig,
    ProtectionEventState,
    ProtectionEventStatus,
    ProtectionTrigger,
    SourceValue,
    TrackerEvent,
    Transition,
    WindowState,
    WishClass,
    WishKind,
    WishSubject,
)
from custom_components.roller_shutter_suite.core.protection import (
    in_order_of_rank,
    judge_event,
    protection_after,
    return_applies,
)
from custom_components.roller_shutter_suite.core.protection.events import (
    override_in_force,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import NOW
from tests.core.protection_kit import (
    ARMED_AT,
    AWAY,
    HAIL,
    HAIL_EVENT,
    OFF,
    ON,
    STORM,
    STORM_EVENT,
    WIND,
    WIND_EVENT,
    active,
    ended,
    engine,
    override,
    protected,
    remembering,
    with_,
    world,
)

MINUTE = timedelta(minutes=1)


def value(number: float) -> AnySourceValue:
    """Return a numeric source value."""
    return SourceValue.of(number)


def step(  # noqa: PLR0913 - the engine, the world, the moment and two facts
    machine: Engine,
    sources: dict[str, AnySourceValue],
    state: WindowState,
    at: datetime,
    *,
    position: int | None = 50,
    last: Decision | None = None,
) -> tuple[Transition, Decision]:
    """Elapse and decide at one instant, as the runtime does."""
    snapshot = world(sources, state=state, position=position, at=at)
    transition = machine.elapse(snapshot, last)
    decision = machine.recompute(replace(snapshot, state=transition.state))
    return transition, decision


def codes(transition: Transition) -> list[ReasonCode]:
    """Return the codes of the events of a transition."""
    return [event.code for event in transition.events]


def event_state(state: WindowState, event_id: str = "storm") -> ProtectionEventState:
    """Return the persisted state of one event."""
    (found,) = (item for item in state.protection_events if item.event_id == event_id)
    return found


# --- Start and end ------------------------------------------------------------------


def test_a_storm_starts_remembers_the_window_and_closes() -> None:
    """Class protection, the end position, the event and its source as the subject."""
    machine = engine()
    state = WindowState(owner=PositionOwner.USER, manual_override=override())

    started, decision = step(machine, with_(storm=ON), state, NOW)

    assert started.events == (
        TrackerEvent(ReasonCode.PROTECTION_STARTED, event_id="storm", source=STORM),
    )
    storm = event_state(started.state)
    assert storm.status is ProtectionEventStatus.ACTIVE
    assert storm.active_since == NOW
    assert storm.remembered_position == Position(50)
    assert storm.remembered_owner is PositionOwner.USER
    assert storm.override_armed_at == ARMED_AT
    wish = decision.winning_wish
    assert wish is not None
    assert wish.reason is ReasonCode.PROTECTION_EVENT
    assert wish.wish_class is WishClass.PROTECTION
    assert wish.position == FULLY_CLOSED
    assert wish.subject == WishSubject(event_id="storm", source=STORM)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_the_end_is_persisted_and_the_waiting_time_holds_the_window() -> None:
    """Leave alone with ``waiting_for_delay``; nothing lower acts for 30 minutes."""
    machine = engine()
    state = WindowState(protection_events=(active(),))

    finished, decision = step(machine, with_(storm=OFF), state, NOW)

    assert codes(finished) == [ReasonCode.PROTECTION_ENDED]
    assert event_state(finished.state) == ProtectionEventState("storm", ended_at=NOW)
    assert decision.winning_wish is not None
    assert decision.winning_wish.kind is WishKind.LEAVE_ALONE
    assert decision.winning_wish.reason is ReasonCode.WAITING_FOR_DELAY
    assert decision.gate is None
    assert NOW + timedelta(minutes=30) in machine.wake_ups(
        finished.state, NOW, dry_run=False
    )
    later, decision = step(
        machine, with_(storm=OFF), finished.state, NOW + timedelta(minutes=30)
    )
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    # No return applies: the event forgets its end.
    assert event_state(later.state) == ProtectionEventState("storm")


def test_an_unknown_source_changes_nothing_and_starts_the_blind_clock() -> None:
    """Situation 14: the event stays active, the watchdog clock keeps running."""
    machine = engine()
    state = WindowState(protection_events=(active(),))

    held, decision = step(machine, with_(storm=AWAY), state, NOW)

    storm = event_state(held.state)
    assert storm.status is ProtectionEventStatus.ACTIVE
    assert storm.blind == BlindClock(NOW)
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_EVENT
    assert decision.winning_wish.subject == WishSubject(
        event_id="storm", source=STORM, held=ReasonCode.INPUT_UNAVAILABLE
    )
    assert NOW - timedelta(minutes=30) + timedelta(hours=12) in machine.wake_ups(
        held.state, NOW, dry_run=False
    )


def test_an_inactive_event_stays_inactive_while_its_source_is_away() -> None:
    """No opinion, and the reason says why."""
    machine = engine()

    held, decision = step(
        machine, with_(storm=SourceValue.unknown()), WindowState(), NOW
    )

    assert event_state(held.state).status is ProtectionEventStatus.INACTIVE
    (protection,) = (
        entry for entry in decision.other_layers if entry.layer.value == "protection"
    )
    assert protection.reason is ReasonCode.INPUT_UNKNOWN
    assert protection.subject == WishSubject(
        event_id="storm", source=STORM, held=ReasonCode.INPUT_UNKNOWN
    )


def test_the_blind_source_is_reported_once_and_changes_no_behavior() -> None:
    """After the blind time: ``input_held_last_known`` and one event."""
    machine = engine()
    state = WindowState(protection_events=(active(),))
    first, _ = step(machine, with_(storm=AWAY), state, NOW)

    blind, decision = step(
        machine, with_(storm=AWAY), first.state, NOW + timedelta(hours=1)
    )
    again, later = step(
        machine, with_(storm=AWAY), blind.state, NOW + timedelta(hours=2)
    )

    assert blind.events == (
        TrackerEvent(
            ReasonCode.PROTECTION_SOURCE_BLIND, event_id="storm", source=STORM
        ),
    )
    assert codes(again) == []
    for made in (decision, later):
        assert made.winning_wish is not None
        assert made.winning_wish.position == FULLY_CLOSED
        assert made.winning_wish.subject is not None
        assert made.winning_wish.subject.held is ReasonCode.INPUT_HELD_LAST_KNOWN
    back, _ = step(machine, with_(storm=ON), again.state, NOW + timedelta(hours=3))
    assert event_state(back.state).blind is None


def test_the_blind_time_is_the_setting_of_the_house() -> None:
    """``source_blind_after``: one setting for every kind of source."""
    machine = engine(protected(source_blind_after=timedelta(minutes=10)))
    first, _ = step(machine, with_(storm=AWAY), WindowState(), NOW)

    blind, _ = step(
        machine, with_(storm=AWAY), first.state, NOW + timedelta(minutes=10)
    )

    assert codes(blind) == [ReasonCode.PROTECTION_SOURCE_BLIND]
    assert NOW + timedelta(minutes=10) in machine.wake_ups(
        first.state, NOW, dry_run=False
    )


def test_a_source_that_reports_active_at_start_is_caught_up() -> None:
    """The pure function of the restart (block C12): active from now on."""
    machine = engine()
    snapshot = world(with_(storm=ON), state=WindowState())

    caught = machine.judge_protection_event(snapshot, "storm")
    held = machine.judge_protection_event(
        world(with_(storm=AWAY), state=WindowState(protection_events=(active(),))),
        "storm",
    )
    idle = judge_event(protected(), world(with_(storm=AWAY)), "storm")

    assert caught is not None
    assert caught.status is ProtectionEventStatus.ACTIVE
    assert caught.remembered_position == Position(50)
    assert held is not None
    assert held.status is ProtectionEventStatus.ACTIVE
    assert idle == ProtectionEventState("storm", blind=BlindClock(NOW))
    assert machine.judge_protection_event(snapshot, "fog") is None
    unreadable = protected(protection_events=EVENTS_UNREADABLE)
    assert judge_event(unreadable, snapshot, "storm") is None


# --- Several events -----------------------------------------------------------------


def test_two_events_at_once_the_higher_rank_wins() -> None:
    """Hail (open, rank 20) over storm (closed, rank 10), whatever the order."""
    for events in ((STORM_EVENT, HAIL_EVENT), (HAIL_EVENT, STORM_EVENT)):
        machine = engine(protected(*events))

        both, decision = step(machine, with_(storm=ON, hail=ON), WindowState(), NOW)

        assert decision.winning_wish is not None
        assert decision.winning_wish.position == FULLY_OPEN
        assert decision.winning_wish.subject is not None
        assert decision.winning_wish.subject.event_id == "hail"
        assert codes(both) == [ReasonCode.PROTECTION_STARTED] * 2


def test_an_active_event_outranks_one_in_its_waiting_time() -> None:
    """Hail has ended and waits; the storm that is active closes."""
    machine = engine(protected(STORM_EVENT, HAIL_EVENT))
    state = WindowState(protection_events=(ended("hail"), active()))

    _, decision = step(machine, with_(storm=ON), state, NOW)

    assert decision.winning_wish is not None
    assert decision.winning_wish.position == FULLY_CLOSED


def test_a_faulty_rank_loses_against_every_valid_rank() -> None:
    """Among faulty ranks the order of the list decides."""
    gale = ProtectionEventConfig(
        "gale",
        ProtectionTrigger(WIND),
        EventDirection.OPEN,
        None,
        faulty_fields=("rank",),
    )
    fog = ProtectionEventConfig(
        "fog",
        ProtectionTrigger(HAIL),
        EventDirection.CLOSED,
        None,
        faulty_fields=("rank",),
    )

    assert in_order_of_rank((gale, STORM_EVENT, fog)) == (STORM_EVENT, gale, fog)
    machine = engine(protected(gale, STORM_EVENT))
    _, decision = step(machine, with_(storm=ON, wind=ON), WindowState(), NOW)
    assert decision.winning_wish is not None
    assert decision.winning_wish.subject is not None
    assert decision.winning_wish.subject.event_id == "storm"


def test_an_event_with_a_faulty_direction_is_skipped() -> None:
    """There is no cautious direction; its state is still kept."""
    lost = ProtectionEventConfig(
        "storm", ProtectionTrigger(STORM), None, 10, faulty_fields=("direction",)
    )
    machine = engine(protected(lost))

    started, decision = step(machine, with_(storm=ON), WindowState(), NOW)

    assert event_state(started.state).status is ProtectionEventStatus.ACTIVE
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY


def test_an_event_that_starts_while_another_holds_takes_over_what_it_remembered() -> (
    None
):
    """The window stands where protection put it, not where the person had put it."""
    machine = engine(protected(STORM_EVENT, HAIL_EVENT))
    storm = remembering(active())
    state = WindowState(protection_events=(storm,), manual_override=override())

    both, _ = step(machine, with_(storm=ON, hail=ON), state, NOW, position=0)

    hail = event_state(both.state, "hail")
    assert hail.remembered_position == Position(40)
    assert hail.remembered_owner is PositionOwner.USER
    assert hail.override_armed_at == ARMED_AT


def test_a_persisted_event_that_is_no_longer_configured_is_dropped() -> None:
    """The house removed it; nothing of it is kept."""
    machine = engine(protected(STORM_EVENT))
    state = WindowState(protection_events=(active("hail"),))

    dropped, _ = step(machine, with_(), state, NOW)

    assert [item.event_id for item in dropped.state.protection_events] == ["storm"]


def test_a_threshold_event_holds_inside_its_band() -> None:
    """Wind from 50 on, calm below 40; in between the persisted state holds."""
    machine = engine(protected(WIND_EVENT))

    started, _ = step(machine, with_(wind=value(55)), WindowState(), NOW)
    holding, decision = step(
        machine, with_(wind=value(45)), started.state, NOW + MINUTE
    )
    calm, _ = step(machine, with_(wind=value(39)), holding.state, NOW + 2 * MINUTE)

    assert event_state(holding.state, "wind").status is ProtectionEventStatus.ACTIVE
    assert event_state(holding.state, "wind").blind is None
    assert decision.winning_wish is not None
    assert decision.winning_wish.subject == WishSubject(event_id="wind", source=WIND)
    assert codes(calm) == [ReasonCode.PROTECTION_ENDED]


# --- The watchdog -------------------------------------------------------------------


def test_the_watchdog_releases_after_the_maximum_duration() -> None:
    """Decision 10: no opinion (``watchdog_released``), the event raised once."""
    machine = engine()
    since = NOW - timedelta(hours=12)
    state = WindowState(protection_events=(active(since=since),))

    released, decision = step(machine, with_(storm=ON), state, NOW)

    assert released.events == (
        TrackerEvent(ReasonCode.WATCHDOG_RELEASED, event_id="storm", source=STORM),
    )
    assert event_state(released.state).released_at == since + timedelta(hours=12)
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    (protection,) = (e for e in decision.other_layers if e.layer.value == "protection")
    assert protection.reason is ReasonCode.WATCHDOG_RELEASED
    again, _ = step(machine, with_(storm=ON), released.state, NOW + MINUTE)
    assert codes(again) == []


def test_the_release_lasts_until_the_trigger_was_genuinely_inactive_once() -> None:
    """A source that is away does not end it; only a new activation re-arms."""
    machine = engine()
    state = WindowState(
        protection_events=(
            active(
                since=NOW - timedelta(hours=13), released_at=NOW - timedelta(hours=1)
            ),
        )
    )

    away, decision = step(machine, with_(storm=AWAY), state, NOW)
    assert event_state(away.state).released
    assert decision.winning_wish is not None
    assert decision.winning_wish.wish_class is WishClass.COMFORT

    calm, _ = step(machine, with_(storm=OFF), away.state, NOW + MINUTE)
    assert codes(calm) == [ReasonCode.PROTECTION_ENDED]
    # Inactive once: the release is over, and without a return the event
    # forgets its end and its release at once.
    assert event_state(calm.state) == ProtectionEventState("storm")

    storm, decision = step(machine, with_(storm=ON), calm.state, NOW + 2 * MINUTE)
    assert codes(storm) == [ReasonCode.PROTECTION_STARTED]
    assert not event_state(storm.state).released
    assert decision.winning_wish is not None
    assert decision.winning_wish.position == FULLY_CLOSED


def test_a_maximum_duration_of_zero_switches_the_watchdog_off() -> None:
    """The event holds for as long as its trigger does."""
    endless = replace(STORM_EVENT, max_duration=timedelta(0))
    machine = engine(protected(endless))
    state = WindowState(protection_events=(active(since=NOW - timedelta(days=30)),))

    held, decision = step(machine, with_(storm=ON), state, NOW)

    assert codes(held) == []
    assert decision.winning_wish is not None
    assert decision.winning_wish.position == FULLY_CLOSED


def test_a_release_that_fell_due_before_a_late_evaluation_keeps_its_instant() -> None:
    """After a restart the release comes before the end of the trigger."""
    machine = engine()
    since = NOW - timedelta(hours=13)
    state = WindowState(
        protection_events=(remembering(active(since=since)),),
        manual_override=override(),
    )

    late, decision = step(machine, with_(storm=OFF), state, NOW)

    assert codes(late) == [ReasonCode.WATCHDOG_RELEASED, ReasonCode.PROTECTION_ENDED]
    storm = event_state(late.state)
    assert storm.released_at == since + timedelta(hours=12)
    assert storm.ended_at == NOW
    assert storm.return_clock_start == storm.released_at
    # The waiting time ran from the release: the return is due already.
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL


# --- The return after an event: decision 14 -----------------------------------------

AFTER = NOW + timedelta(minutes=30)
"""The moment the waiting time after an end at ``NOW`` has passed."""


def _return_world(
    **changes: object,
) -> tuple[Engine, WindowState]:
    """Return a storm that ended now, remembering a person's 40 and the override."""
    storm = remembering(ended(at=NOW))
    state = WindowState(
        protection_events=(storm,),
        manual_override=override(),
        owner=PositionOwner.ENGINE,
    )
    return engine(), replace(state, **changes)  # type: ignore[arg-type]


def test_the_remembered_manual_position_is_restored_after_the_waiting_time() -> None:
    """Situation 9: ``protection_return_manual``, comfort, passing the override."""
    machine, state = _return_world()

    _, waiting = step(machine, with_(), state, AFTER - MINUTE, position=0)
    back, decision = step(machine, with_(), state, AFTER, position=0)

    assert waiting.winning_wish is not None
    assert waiting.winning_wish.reason is ReasonCode.WAITING_FOR_DELAY
    wish = decision.winning_wish
    assert wish is not None
    assert wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert wish.wish_class is WishClass.COMFORT
    assert wish.position == Position(40)
    assert wish.triggered_at == AFTER
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    # The event keeps its return phase while the return applies.
    assert event_state(back.state).ended_at == NOW


def test_condition_a_without_the_override_there_is_no_return() -> None:
    """Situation 10: the override expired meanwhile; the window is recomputed."""
    machine, state = _return_world(manual_override=None)

    back, decision = step(machine, with_(), state, AFTER, position=0)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert event_state(back.state) == ProtectionEventState("storm")


def test_condition_a_the_override_must_be_the_one_armed_at_the_start() -> None:
    """A new override after the event restores nothing; it holds comfort itself."""
    machine, state = _return_world(manual_override=override(armed_at=NOW + MINUTE))

    _, decision = step(machine, with_(), state, AFTER, position=0)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MANUAL_OVERRIDE


def test_condition_a_an_override_whose_end_has_passed_is_not_armed() -> None:
    """Its end lies in the past: no return."""
    machine, state = _return_world(manual_override=override(ends_at=AFTER - MINUTE))

    _, decision = step(machine, with_(), state, AFTER, position=0)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY


def test_condition_b_the_person_at_the_window_dam_holds_the_return_back() -> None:
    """The return is a comfort wish; the dam of the person stands before the override."""
    machine, state = _return_world(
        person_at_window=PersonAtWindowDam(ends_at=AFTER + 10 * MINUTE)
    )

    _, decision = step(machine, with_(), state, AFTER, position=0)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.PERSON_AT_WINDOW


def test_condition_c_every_constraint_applies_to_the_return() -> None:
    """Frost limits the return like any own comfort movement."""
    frost_source = "sensor.example_outdoor"
    machine, state = _return_world()
    machine = engine(protected(frost_source=frost_source))
    frozen = with_(**{frost_source: value(-5.0)})
    raised = replace(
        state,
        protection_events=(remembering(ended(at=NOW), position=100),),
    )

    _, decision = step(machine, frozen, raised, AFTER, position=0)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert [result.reason for result in decision.constraints] == [
        ReasonCode.FROST_LIMIT
    ]
    assert decision.target == Position(90)


def test_condition_d_the_waiting_time_follows_a_changed_setting_at_once() -> None:
    """The waiting time is configuration, applied when it is evaluated."""
    machine, state = _return_world()
    shorter = engine(protected(replace(STORM_EVENT, waiting_time=timedelta(minutes=5))))

    _, before = step(machine, with_(), state, NOW + 5 * MINUTE, position=0)
    _, after = step(shorter, with_(), state, NOW + 5 * MINUTE, position=0)

    assert before.winning_wish is not None
    assert before.winning_wish.reason is ReasonCode.WAITING_FOR_DELAY
    assert after.winning_wish is not None
    assert after.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert NOW + 5 * MINUTE in shorter.wake_ups(state, NOW, dry_run=False)


@pytest.mark.parametrize(
    "remembered",
    [
        {"remembered_owner": PositionOwner.ENGINE},
        {"remembered_owner": PositionOwner.UNKNOWN},
        {"remembered_position": None},
        {"override_armed_at": None},
    ],
    ids=["owner engine", "owner unknown", "position unknown", "no override then"],
)
def test_without_a_known_manual_position_there_is_no_return(
    remembered: dict[str, object],
) -> None:
    """Only a person's position is restored; an unknown position is skipped."""
    machine, state = _return_world()
    storm = replace(event_state(state), **remembered)  # type: ignore[arg-type]

    _, decision = step(
        machine, with_(), replace(state, protection_events=(storm,)), AFTER, position=0
    )

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY


def test_a_new_activation_during_the_waiting_time_keeps_what_was_remembered() -> None:
    """The window stands at the storm's position; the person's 40 is kept."""
    machine, state = _return_world()

    again, decision = step(
        machine, with_(storm=ON), state, NOW + 10 * MINUTE, position=0
    )

    storm = event_state(again.state)
    assert storm.status is ProtectionEventStatus.ACTIVE
    assert storm.remembered_position == Position(40)
    assert storm.remembered_owner is PositionOwner.USER
    assert decision.winning_wish is not None
    assert decision.winning_wish.position == FULLY_CLOSED


def test_a_new_activation_after_a_hand_movement_in_the_waiting_time_remembers_afresh() -> (
    None
):
    """Section 10.2: the person's 60 and the new override, not the old 40."""
    moved_at = NOW + 5 * MINUTE
    machine, state = _return_world(
        manual_override=override(armed_at=moved_at, position=60),
        owner=PositionOwner.USER,
    )

    again, _ = step(machine, with_(storm=ON), state, NOW + 10 * MINUTE, position=60)

    storm = event_state(again.state)
    assert storm.remembered_position == Position(60)
    assert storm.remembered_owner is PositionOwner.USER
    assert storm.override_armed_at == moved_at


def test_a_new_activation_while_a_person_holds_the_window_remembers_afresh() -> None:
    """The same override, but a person took the window since: remembered afresh."""
    machine, state = _return_world(owner=PositionOwner.USER)

    again, _ = step(machine, with_(storm=ON), state, NOW + 10 * MINUTE, position=70)

    storm = event_state(again.state)
    assert storm.remembered_position == Position(70)
    assert storm.override_armed_at == ARMED_AT


def test_a_released_event_passes_nothing_on_to_an_event_that_starts() -> None:
    """Its window was recomputed; the new event remembers the window as it stands."""
    machine = engine(protected(STORM_EVENT, HAIL_EVENT))
    released_at = NOW - timedelta(hours=1)
    storm = remembering(
        active(since=released_at - timedelta(hours=12), released_at=released_at)
    )
    state = WindowState(protection_events=(storm,), owner=PositionOwner.ENGINE)

    started, _ = step(machine, with_(storm=ON, hail=ON), state, NOW, position=100)

    hail = event_state(started.state, "hail")
    assert hail.remembered_position == Position(100)
    assert hail.remembered_owner is PositionOwner.ENGINE
    assert hail.override_armed_at is None


def test_after_a_release_the_return_comes_after_release_plus_waiting_time() -> None:
    """The waiting time runs from the release; the trigger is still active."""
    machine = engine()
    released_at = NOW - timedelta(minutes=30)
    storm = remembering(
        active(since=released_at - timedelta(hours=12), released_at=released_at)
    )
    state = WindowState(protection_events=(storm,), manual_override=override())

    _, decision = step(machine, with_(storm=ON), state, NOW, position=0)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert decision.winning_wish.triggered_at == NOW


# --- A list that cannot be read -----------------------------------------------------

UNREADABLE = protected(protection_events=EVENTS_UNREADABLE)


def test_an_unreadable_list_holds_the_window_for_an_active_event() -> None:
    """Leave alone with ``protection_event``; no direction is known."""
    machine = engine(UNREADABLE)
    state = WindowState(protection_events=(active(),))

    _, decision = step(machine, with_(storm=ON), state, NOW)

    assert decision.winning_wish is not None
    assert decision.winning_wish.kind is WishKind.LEAVE_ALONE
    assert decision.winning_wish.reason is ReasonCode.PROTECTION_EVENT
    assert decision.winning_wish.subject == WishSubject(event_id="storm")


def test_an_unreadable_list_holds_during_the_default_waiting_time_only() -> None:
    """Thirty minutes after the end, then the window is recomputed."""
    machine = engine(UNREADABLE)
    state = WindowState(protection_events=(ended(at=NOW),))

    _, waiting = step(machine, with_(), state, NOW + 29 * MINUTE)
    _, after = step(machine, with_(), state, NOW + 30 * MINUTE)

    assert waiting.winning_wish is not None
    assert waiting.winning_wish.kind is WishKind.LEAVE_ALONE
    assert after.winning_wish is not None
    assert after.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert NOW + 30 * MINUTE in machine.wake_ups(state, NOW, dry_run=False)


def test_an_unreadable_list_is_watched_with_the_default_maximum_duration() -> None:
    """Twelve hours, and the release is raised; a released event holds nothing."""
    machine = engine(UNREADABLE)
    since = NOW - timedelta(hours=12)
    state = WindowState(protection_events=(active(since=since),))

    assert since + timedelta(hours=12) in machine.wake_ups(
        state, NOW - MINUTE, dry_run=False
    )
    released, decision = step(machine, with_(), state, NOW)

    assert released.events == (
        TrackerEvent(ReasonCode.WATCHDOG_RELEASED, event_id="storm"),
    )
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    quiet = protection_after(UNREADABLE, world(with_(), state=released.state))
    assert quiet.state is released.state


def test_an_override_whose_end_has_passed_or_whose_condition_ended_it_is_not_armed() -> (
    None
):
    """Also when ``elapse`` has not ended it yet: the return reads the dam live."""
    storm = remembering(ended(at=NOW))
    config = protected()
    past = WindowState(
        protection_events=(storm,), manual_override=override(ends_at=AFTER - MINUTE)
    )
    episode = WindowState(
        protection_events=(storm,),
        manual_override=override(end_rule=OverrideEndRule.SHADING_EPISODE_END),
    )

    assert override_in_force(config, world(with_(), state=past, at=AFTER)) is None
    assert override_in_force(config, world(with_(), state=episode, at=AFTER)) is None
    for state in (past, episode):
        assert not return_applies(
            STORM_EVENT, storm, config, world(with_(), state=state, at=AFTER)
        )


def test_a_released_event_returns_only_after_its_waiting_time() -> None:
    """Released a minute ago: no opinion, no return yet."""
    machine = engine()
    released_at = NOW - MINUTE
    storm = remembering(
        active(since=released_at - timedelta(hours=12), released_at=released_at)
    )
    state = WindowState(protection_events=(storm,), manual_override=override())

    _, decision = step(machine, with_(storm=ON), state, NOW, position=0)

    (protection,) = (e for e in decision.other_layers if e.layer.value == "protection")
    assert protection.reason is ReasonCode.WATCHDOG_RELEASED
    assert released_at + timedelta(minutes=30) in machine.wake_ups(
        state, NOW, dry_run=False
    )


def test_an_event_without_a_persisted_state_has_no_wake_up() -> None:
    """Nothing of it can change without a report."""
    assert engine().wake_ups(WindowState(), NOW, dry_run=False) == ()


def test_without_events_the_layer_is_not_configured() -> None:
    """No list, no opinion."""
    machine = engine(protected(protection_events=()))

    _, decision = step(machine, with_(storm=ON), WindowState(), NOW)

    (protection,) = (e for e in decision.other_layers if e.layer.value == "protection")
    assert protection.reason is ReasonCode.NOT_CONFIGURED
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
