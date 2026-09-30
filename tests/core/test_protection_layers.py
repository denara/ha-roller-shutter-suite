"""The fire layer, the two constraints of block C07, and the situations of section 4.

Situations 1 to 6 and 14 at the arbiter; 7 and 8 need the tracker and run as
scenarios of the time-lapse simulation (``test_sim_protection.py``), and 9
and 10 are the return tests of ``test_protection_events.py``. Situations 4
and 5 use the stand-in for lockout protection of block C08, situation 6 the
stand-in for sleep mode of block C11 (``tests/sim/stand_ins.py``).
"""

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from custom_components.roller_shutter_suite.core.arbiter import ConstraintInput
from custom_components.roller_shutter_suite.core.constraints import (
    NO_INTERMEDIATE_CONSTRAINT,
    SLEEP_EXCEPTION_CONSTRAINT,
    sleep_mode_active,
)
from custom_components.roller_shutter_suite.core.engine import Engine
from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    FULLY_CLOSED,
    FULLY_OPEN,
    AnySourceValue,
    BlindClock,
    Constraint,
    ConstraintResult,
    ControlLevel,
    Controls,
    Decision,
    GateKind,
    Layer,
    MemberTarget,
    OperatingMode,
    Position,
    SourceValue,
    TrackerEvent,
    WindowState,
    Wish,
    WishClass,
    WishKind,
    WishSubject,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.protection import (
    acknowledge_fire,
    fire_after,
    fire_alarm_active,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import LEFT, NOW, RIGHT, observed, window
from tests.core.protection_kit import (
    AWAY,
    FIRE,
    HAIL_EVENT,
    OFF,
    ON,
    STORM,
    STORM_EVENT,
    active,
    engine,
    protected,
    with_,
    world,
)
from tests.sim.stand_ins import DOOR_SOURCE, SLEEP_SOURCE, TAMPER_SOURCE

MINUTE = timedelta(minutes=1)


def decide(  # noqa: PLR0913 - the engine, the world, the moment and what a person set
    machine: Engine,
    sources: dict[str, AnySourceValue],
    *,
    state: WindowState | None = None,
    position: int | None = 50,
    controls: Controls | None = None,
    at: datetime = NOW,
) -> Decision:
    """Elapse and decide once, as the runtime does."""
    snapshot = world(sources, state=state, position=position, at=at)
    if controls is not None:
        snapshot = replace(snapshot, controls=controls)
    transition = machine.elapse(snapshot, None)
    return machine.recompute(replace(snapshot, state=transition.state))


def reasons(decision: Decision) -> tuple[ReasonCode | None, ...]:
    """Return winner / constraints / gate, as the table of section 4 names them."""
    winner = None if decision.winning_wish is None else decision.winning_wish.reason
    gate = None if decision.gate is None else decision.gate.reason
    return (winner, *(result.reason for result in decision.constraints), gate)


# --- The fire layer -----------------------------------------------------------------


def test_fire_opens_fully_with_its_source_as_the_subject() -> None:
    """Class fire, every member, no intermediate target, no constraint."""
    decision = decide(engine(), with_(fire=ON, storm=ON))

    wish = decision.winning_wish
    assert wish is not None
    assert (wish.layer, wish.reason, wish.position) == (
        Layer.FIRE,
        ReasonCode.FIRE_ALARM,
        FULLY_OPEN,
    )
    assert wish.wish_class is WishClass.FIRE
    assert wish.subject == WishSubject(source=FIRE)
    assert decision.constraints == ()
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


@pytest.mark.parametrize(
    "mode", [OperatingMode.AUTOMATIC, OperatingMode.PROTECTION_ONLY, OperatingMode.OFF]
)
def test_fire_opens_in_every_operating_mode_and_while_paused(
    mode: OperatingMode,
) -> None:
    """Situation 3 for ``off``: opens at once."""
    controls = Controls(
        dry_run=False, window_level=ControlLevel(mode=mode, paused=True)
    )

    decision = decide(engine(), with_(fire=ON), controls=controls)

    assert reasons(decision) == (ReasonCode.FIRE_ALARM, ReasonCode.SENT)


def test_situation_1_fire_under_a_maintenance_lock_moves_nothing() -> None:
    """The decision names the fire wish as the winner, so the event is fired."""
    locked = Controls(dry_run=False, window_level=ControlLevel(maintenance_lock=True))

    decision = decide(engine(), with_(fire=ON), controls=locked)

    assert reasons(decision) == (ReasonCode.FIRE_ALARM, ReasonCode.MAINTENANCE_LOCK)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SUPPRESS


def test_situation_2_fire_in_dry_run_records_would_open() -> None:
    """``dry_run`` with the would-be command 100."""
    decision = decide(engine(), with_(fire=ON), controls=Controls(dry_run=True))

    assert reasons(decision) == (ReasonCode.FIRE_ALARM, ReasonCode.DRY_RUN)
    assert decision.gate is not None
    assert decision.gate.would_send == (MemberTarget(LEFT, FULLY_OPEN),)


def test_after_the_alarm_nothing_moves_until_the_acknowledgement() -> None:
    """Leave alone with ``fire_unacknowledged``; it still wins over a storm."""
    machine = engine()
    burning = machine.elapse(world(with_(fire=ON)), None).state
    assert burning.fire_alarm_active
    assert burning.fire_unacknowledged

    ended = machine.elapse(world(with_(fire=OFF), state=burning), None).state
    decision = machine.recompute(world(with_(fire=OFF, storm=ON), state=ended))

    assert not ended.fire_alarm_active
    assert ended.fire_unacknowledged
    assert decision.winning_wish is not None
    assert decision.winning_wish.kind is WishKind.LEAVE_ALONE
    assert decision.winning_wish.reason is ReasonCode.FIRE_UNACKNOWLEDGED
    assert decision.gate is None


def test_the_acknowledgement_lets_the_lower_layers_act_again() -> None:
    """``fire_acknowledged`` once; the storm closes then."""
    state = WindowState(fire_unacknowledged=True)

    acknowledged = Engine.acknowledge_fire(state)
    nothing = acknowledge_fire(acknowledged.state)
    decision = decide(engine(), with_(storm=ON), state=acknowledged.state)

    assert acknowledged.events == (TrackerEvent(ReasonCode.FIRE_ACKNOWLEDGED),)
    assert not acknowledged.state.fire_unacknowledged
    assert nothing.events == ()
    assert nothing.state is acknowledged.state
    assert reasons(decision) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)


def test_an_acknowledgement_during_the_alarm_leaves_nothing_held_after_it() -> None:
    """It can be done at any time; the alarm still opens while it is active."""
    machine = engine()
    burning = machine.elapse(world(with_(fire=ON)), None).state
    acknowledged = acknowledge_fire(burning).state

    during = decide(machine, with_(fire=ON), state=acknowledged)
    after = decide(machine, with_(fire=OFF), state=acknowledged)

    assert reasons(during)[0] is ReasonCode.FIRE_ALARM
    assert reasons(after)[0] is ReasonCode.SCHEDULE_DAY


@pytest.mark.parametrize("held", [True, False])
def test_a_fire_source_without_a_value_changes_nothing(held: bool) -> None:
    """D6: an active alarm stays active, an inactive one stays inactive."""
    machine = engine()
    state = WindowState(fire_alarm_active=held, fire_unacknowledged=held)

    transition = machine.elapse(world(with_(fire=AWAY), state=state), None)
    decision = machine.recompute(world(with_(fire=AWAY), state=transition.state))

    assert transition.state.fire_alarm_active is held
    assert transition.state.fire_blind == BlindClock(NOW)
    assert fire_alarm_active(protected(), world(with_(fire=AWAY), state=state)) is held
    if held:
        assert reasons(decision)[0] is ReasonCode.FIRE_ALARM
        assert decision.winning_wish is not None
        assert decision.winning_wish.subject == WishSubject(
            source=FIRE, held=ReasonCode.INPUT_UNAVAILABLE
        )
    else:
        (fire,) = (
            entry for entry in decision.other_layers if entry.layer is Layer.FIRE
        )
        assert fire.reason is ReasonCode.INPUT_UNAVAILABLE


def test_a_blind_fire_source_is_reported_like_a_protection_source() -> None:
    """Ruling of 2026-10-01: the same blind time, the event without an event."""
    machine = engine()
    first = machine.elapse(world(with_(fire=AWAY)), None)
    assert NOW + timedelta(hours=1) in machine.wake_ups(first.state, NOW, dry_run=False)

    later = world(with_(fire=AWAY), state=first.state, at=NOW + timedelta(hours=1))
    blind = machine.elapse(later, None)
    decision = machine.recompute(replace(later, state=blind.state))

    assert blind.events == (
        TrackerEvent(ReasonCode.PROTECTION_SOURCE_BLIND, source=FIRE),
    )
    (fire,) = (entry for entry in decision.other_layers if entry.layer is Layer.FIRE)
    assert fire.reason is ReasonCode.INPUT_HELD_LAST_KNOWN
    back = machine.elapse(
        replace(later, sources=with_(fire=OFF), state=blind.state), None
    )
    assert back.state.fire_blind is None


def test_a_faulty_fire_source_holds_the_alarm_at_once_without_a_clock() -> None:
    """Configured, but blind: the held state applies; the resolver reports the fault."""
    config = protected(fire_source=BLIND_SOURCE)
    machine = engine(config)
    held = WindowState(fire_alarm_active=True)

    transition = fire_after(config, world(with_(), state=held))
    burning = decide(machine, with_(), state=held)
    calm = decide(machine, with_())

    assert transition.state is held
    assert burning.winning_wish is not None
    assert burning.winning_wish.subject == WishSubject(
        held=ReasonCode.INPUT_HELD_LAST_KNOWN
    )
    (fire,) = (entry for entry in calm.other_layers if entry.layer is Layer.FIRE)
    assert fire.reason is ReasonCode.INPUT_HELD_LAST_KNOWN


def test_without_a_fire_source_an_unacknowledged_alarm_still_holds() -> None:
    """The source was removed after an alarm: the acknowledgement is still needed."""
    config = protected(fire_source=None)
    machine = engine(config)

    calm = decide(machine, with_())
    held = decide(machine, with_(), state=WindowState(fire_unacknowledged=True))
    transition = fire_after(
        config, world(with_(), state=WindowState(fire_blind=BlindClock(NOW)))
    )

    (fire,) = (entry for entry in calm.other_layers if entry.layer is Layer.FIRE)
    assert fire.reason is ReasonCode.NOT_CONFIGURED
    assert reasons(held) == (ReasonCode.FIRE_UNACKNOWLEDGED, None)
    assert transition.state.fire_blind is None


def test_the_watchdog_never_releases_the_fire_alarm() -> None:
    """Decision 10: not for fire. An alarm active for days still opens."""
    machine = engine()
    burning = machine.elapse(world(with_(fire=ON)), None)
    days_later = world(with_(fire=ON), state=burning.state, at=NOW + timedelta(days=3))

    transition = machine.elapse(days_later, None)
    decision = machine.recompute(replace(days_later, state=transition.state))

    assert transition.events == ()
    assert reasons(decision) == (ReasonCode.FIRE_ALARM, ReasonCode.SENT)
    assert machine.wake_ups(transition.state, days_later.time, dry_run=False) == ()


def test_an_inactive_fire_alarm_says_so() -> None:
    """The fire layer steps aside with ``inactive`` and names its source."""
    decision = decide(engine(), with_())

    (fire,) = (entry for entry in decision.other_layers if entry.layer is Layer.FIRE)
    assert fire.reason is ReasonCode.INACTIVE
    assert fire.subject == WishSubject(source=FIRE)


# --- Constraint 2: the sleep-room exception -----------------------------------------


def _hail_config(*marked: str) -> Engine:
    return engine(
        protected(STORM_EVENT, HAIL_EVENT, protection_sleep_exception=marked),
        stand_ins=True,
    )


SLEEPING = {SLEEP_SOURCE: ON}


def test_situation_6_hail_with_the_sleep_room_exception_while_sleeping() -> None:
    """Stays closed: ``protection_event`` / ``sleep_exception_no_open`` / —."""
    decision = decide(_hail_config("hail"), with_(hail=ON, **SLEEPING), position=0)

    assert reasons(decision) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.SLEEP_EXCEPTION_NO_OPEN,
        None,
    )
    assert decision.targets == (MemberTarget(LEFT, None),)


@pytest.mark.parametrize(
    ("marked", "sources", "sent"),
    [
        ((), with_(hail=ON, **SLEEPING), FULLY_OPEN),
        (("hail",), with_(hail=ON, **{SLEEP_SOURCE: OFF}), FULLY_OPEN),
        (("storm",), with_(hail=ON, **SLEEPING), FULLY_OPEN),
    ],
    ids=["not marked", "not sleeping", "another event marked"],
)
def test_the_exception_needs_its_event_and_sleep_mode(
    marked: tuple[str, ...], sources: dict[str, AnySourceValue], sent: Position
) -> None:
    """Otherwise protection wins over sleep."""
    decision = decide(_hail_config(*marked), sources, position=0)

    assert reasons(decision) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)
    assert decision.target == sent


def test_the_exception_never_limits_closing_and_never_fire() -> None:
    """A marked storm closes a sleeping room; fire opens it."""
    storm = decide(_hail_config("storm"), with_(storm=ON, **SLEEPING), position=100)
    fire = decide(_hail_config("hail"), with_(fire=ON, hail=ON, **SLEEPING), position=0)

    assert reasons(storm) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)
    assert reasons(fire) == (ReasonCode.FIRE_ALARM, ReasonCode.SENT)


def _input(
    wish: Wish,
    *,
    targets: tuple[MemberTarget, ...],
    positions: dict[str, int | None],
    answers: tuple[Wish, ...] = (),
    marked: tuple[str, ...] = ("hail",),
) -> ConstraintInput:
    config = window(
        *positions,
        fire_source=FIRE,
        protection_events=(STORM_EVENT, HAIL_EVENT),
        protection_sleep_exception=marked,
    )
    names = {LEFT: "left", RIGHT: "right"}
    snapshot = WorldSnapshot(
        time=NOW,
        sun=world({}).sun,
        sources={},
        observation=observed(**{names[m]: p for m, p in positions.items()}),
        state=WindowState(),
        controls=Controls(dry_run=False),
    )
    return ConstraintInput(config, snapshot, wish, targets, answers)


HAIL_WISH = Wish.target(
    Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_OPEN
).about(WishSubject(event_id="hail"))
SLEEP_WISH = Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, FULLY_CLOSED)


def test_a_member_without_a_known_position_is_not_raised_by_a_marked_event() -> None:
    """A target above fully closed could be a raise: the member stays."""
    constraint = _input(
        HAIL_WISH,
        targets=(MemberTarget(LEFT, FULLY_OPEN),),
        positions={LEFT: None},
        answers=(HAIL_WISH, SLEEP_WISH),
    )

    result = SLEEP_EXCEPTION_CONSTRAINT.apply(constraint)

    assert sleep_mode_active(constraint)
    assert result == ConstraintResult(
        Constraint.SLEEP_ROOM_EXCEPTION,
        ReasonCode.SLEEP_EXCEPTION_NO_OPEN,
        (MemberTarget(LEFT, None),),
    )


def test_the_cautious_result_of_the_exception_raises_nobody() -> None:
    """If it raised: as if sleeping and marked; nothing without any exception."""
    constraint = _input(
        HAIL_WISH, targets=(MemberTarget(LEFT, FULLY_OPEN),), positions={LEFT: 0}
    )
    unmarked = replace(
        constraint, config=replace(constraint.config, protection_sleep_exception=())
    )
    closing = replace(constraint, targets=(MemberTarget(LEFT, FULLY_CLOSED),))

    assert SLEEP_EXCEPTION_CONSTRAINT.cautious is not None
    assert SLEEP_EXCEPTION_CONSTRAINT.cautious(constraint) == ConstraintResult(
        Constraint.SLEEP_ROOM_EXCEPTION,
        ReasonCode.SLEEP_EXCEPTION_NO_OPEN,
        (MemberTarget(LEFT, None),),
    )
    assert SLEEP_EXCEPTION_CONSTRAINT.cautious(unmarked) is None
    assert SLEEP_EXCEPTION_CONSTRAINT.cautious(closing) is None
    assert SLEEP_EXCEPTION_CONSTRAINT.applies_to == frozenset({WishClass.PROTECTION})


def test_a_wish_without_an_event_is_never_marked() -> None:
    """A protection wish that names no event (a stub) is not concerned."""
    unnamed = Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_OPEN)
    constraint = _input(
        unnamed,
        targets=(MemberTarget(LEFT, FULLY_OPEN),),
        positions={LEFT: 0},
        answers=(unnamed, SLEEP_WISH),
    )

    assert SLEEP_EXCEPTION_CONSTRAINT.apply(constraint) is None


# --- Constraint 7: no intermediate position -----------------------------------------


def test_an_intermediate_protection_target_is_pinned() -> None:
    """The window is left alone rather than driven halfway."""
    constraint = _input(
        HAIL_WISH,
        targets=(MemberTarget(LEFT, Position(30)), MemberTarget(RIGHT, FULLY_OPEN)),
        positions={LEFT: 0, RIGHT: 0},
    )

    result = NO_INTERMEDIATE_CONSTRAINT.apply(constraint)

    assert result == ConstraintResult(
        Constraint.NO_INTERMEDIATE_POSITION,
        ReasonCode.NO_INTERMEDIATE_POSITION,
        (MemberTarget(LEFT, None), MemberTarget(RIGHT, FULLY_OPEN)),
    )
    assert NO_INTERMEDIATE_CONSTRAINT.cautious is not None
    assert NO_INTERMEDIATE_CONSTRAINT.cautious(constraint) == result
    ends = replace(constraint, targets=(MemberTarget(LEFT, FULLY_CLOSED),))
    assert NO_INTERMEDIATE_CONSTRAINT.apply(ends) is None


def test_the_frost_position_counts_as_the_open_end_where_frost_applies_to_protection() -> (
    None
):
    """Constraint 7 and frost protection configured for protection movements."""
    frost_source = "sensor.example_outdoor"
    config = protected(
        STORM_EVENT,
        HAIL_EVENT,
        frost_source=frost_source,
        frost_applies_to_protection=True,
    )

    decision = decide(
        engine(config),
        with_(hail=ON, **{frost_source: SourceValue.of(-4.0)}),
        position=0,
    )

    assert reasons(decision) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.FROST_LIMIT,
        ReasonCode.SENT,
    )
    assert decision.target == Position(90)


# --- Situations 4, 5 and 14 ----------------------------------------------------------


def test_situation_4_a_storm_with_an_open_terrace_door() -> None:
    """No movement while the door is open; closes when the door is shut."""
    machine = engine(stand_ins=True)

    open_door = decide(machine, with_(storm=ON, **{DOOR_SOURCE: ON}))
    shut = decide(machine, with_(storm=ON, **{DOOR_SOURCE: OFF}))

    assert reasons(open_door) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.LOCKOUT_DOOR_OPEN,
        None,
    )
    assert reasons(shut) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)
    assert shut.target == FULLY_CLOSED


def test_situation_5_the_same_with_an_active_tamper_contact() -> None:
    """Closes: ``lockout_void_tamper`` / ``sent``."""
    decision = decide(
        engine(stand_ins=True),
        with_(storm=ON, **{DOOR_SOURCE: ON, TAMPER_SOURCE: ON}),
    )

    assert reasons(decision) == (
        ReasonCode.PROTECTION_EVENT,
        ReasonCode.LOCKOUT_VOID_TAMPER,
        ReasonCode.SENT,
    )
    assert decision.target == FULLY_CLOSED


def test_situation_14_the_source_of_an_active_event_becomes_unavailable() -> None:
    """The event stays active (D6), the watchdog clock keeps running; input held."""
    machine = engine()
    state = WindowState(protection_events=(active(since=NOW - timedelta(hours=11)),))

    held = decide(machine, with_(storm=AWAY), state=state)
    released = decide(
        machine, with_(storm=AWAY), state=state, at=NOW + timedelta(hours=1)
    )

    assert reasons(held) == (ReasonCode.PROTECTION_EVENT, ReasonCode.SENT)
    assert held.winning_wish is not None
    assert held.winning_wish.subject == WishSubject(
        event_id="storm", source=STORM, held=ReasonCode.INPUT_UNAVAILABLE
    )
    (protection,) = (e for e in released.other_layers if e.layer is Layer.PROTECTION)
    assert protection.reason is ReasonCode.WATCHDOG_RELEASED
