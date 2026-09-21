"""The schedule as a layer of the arbiter: almanac, trigger time, faults, direction.

A recompute asks no port. Sun times reach the schedule as the almanac of the
snapshot, the seed as a field of the snapshot. These tests go that way, as the
runtime does, and through the arbiter that ``build_arbiter()`` returns.
"""

import json
from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta

import pytest

from custom_components.roller_shutter_suite.core.engine import (
    FEATURE_LAYERS,
    Engine,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    Constraint,
    DayTriggers,
    Decision,
    Direction,
    ElevationPassage,
    FunctionId,
    GateKind,
    Layer,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    ScheduleTargets,
    SunAlmanac,
    WindowConfig,
    WindowObservation,
    WindowState,
    WishKind,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.ports import Sun
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.schedule import (
    ALMANAC_DAYS_AHEAD,
    ALMANAC_DAYS_BEFORE,
    SCHEDULE_LAYER,
    SCHEDULE_NOT_CONFIGURED,
    AlmanacSun,
    ScheduleInputMissingError,
    build_sun_almanac,
    evaluate_schedule,
    schedule_layer,
    schedule_state_after,
)
from tests.core.schedule_kit import (
    CLOCKS_BACK,
    CLOCKS_FORWARD,
    CLOSED,
    CONFIG,
    EARLY,
    LATE,
    MEMBER,
    MONDAY,
    OPEN,
    SEED,
    SUN,
    ZONE,
    FakeSun,
    config,
    elevation_trigger,
    evaluate,
    fixed,
    local,
    snapshot,
    snapshot_with_almanac,
    sun_event,
)

BY_THE_SUN = config(
    workday=DayTriggers(sun_event(EARLY, 20), elevation_trigger(-6, LATE)),
    weekend=DayTriggers(sun_event(EARLY, 90), elevation_trigger(-4, LATE)),
    random_offset=timedelta(minutes=15),
)
POLAR_NIGHT = FakeSun(sunrise_at=None, sunset_at=None, highest=-5.0)
POLAR_DAY = FakeSun(sunrise_at=None, sunset_at=None, highest=50.0, lowest=5.0)


def _at_position(world: WorldSnapshot, position: int) -> WorldSnapshot:
    observation = WindowObservation(
        (
            MemberObservation(
                MEMBER, Observation(MovementState.RESTING, Position(position))
            ),
        )
    )
    return replace(world, observation=observation)


def _decide(window: WindowConfig, world: WorldSnapshot) -> Decision:
    return Engine(window, build_arbiter()).recompute(world)


# --- The almanac -------------------------------------------------------------------------


def test_the_almanac_runs_from_yesterday_to_seven_days_ahead() -> None:
    """Nine local dates, and only the elevations that elevation triggers name."""
    almanac = build_sun_almanac(BY_THE_SUN, local(MONDAY, 12), SUN)

    assert [entry.day for entry in almanac.days] == [
        MONDAY + timedelta(days=ahead)
        for ahead in range(-ALMANAC_DAYS_BEFORE, ALMANAC_DAYS_AHEAD + 1)
    ]
    assert (ALMANAC_DAYS_BEFORE, ALMANAC_DAYS_AHEAD) == (1, 7)
    monday = almanac.day(MONDAY)
    assert monday is not None
    assert monday.sunrise == local(MONDAY, 6)
    assert monday.sunset == local(MONDAY, 18)
    assert [(entry.elevation, entry.rising) for entry in monday.passages] == [
        (-6.0, False),
        (-4.0, False),
    ]
    assert monday.passages[0].at == local(MONDAY, 18, 24)
    assert build_sun_almanac(CONFIG, local(MONDAY, 12), SUN).days[0].passages == ()


def test_the_almanac_is_a_value_that_survives_json() -> None:
    """Immutable, compared by value, hashable, and plain data both ways."""
    almanac = build_sun_almanac(BY_THE_SUN, local(CLOCKS_BACK, 2, 30), SUN)
    restored = SunAlmanac.from_data(json.loads(json.dumps(almanac.to_data())))

    assert restored == almanac
    assert hash(restored) == hash(almanac)
    assert almanac.day(date(2000, 1, 1)) is None
    with pytest.raises(ValueError, match="occurs twice"):
        SunAlmanac((almanac.days[0], almanac.days[0]))
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(almanac.days[0], sunrise=datetime(2026, 9, 21, 6, 0))  # noqa: DTZ001
    with pytest.raises(TypeError, match="a date, not a datetime"):
        replace(almanac.days[0], day=local(MONDAY, 6))
    with pytest.raises(ValueError, match="occurs twice"):
        replace(
            almanac.days[0],
            passages=(almanac.days[0].passages[0], almanac.days[0].passages[0]),
        )
    with pytest.raises(ValueError, match="elevation: expected a number"):
        ElevationPassage.from_data(
            almanac.days[0].passages[0].to_data() | {"elevation": "high"}
        )


@pytest.mark.parametrize(
    ("first", "sun"),
    [
        (CLOCKS_FORWARD - timedelta(days=1), SUN),
        (CLOCKS_BACK - timedelta(days=1), SUN),
        (MONDAY, SUN),
        (CLOCKS_FORWARD - timedelta(days=1), POLAR_NIGHT),
        (MONDAY, POLAR_DAY),
    ],
    ids=[
        "across the clocks going forward",
        "across the clocks going back",
        "three ordinary days",
        "polar night: no sunrise, no passage",
        "polar day: no sunset, no passage",
    ],
)
def test_the_almanac_gives_exactly_the_schedule_of_the_sun_port(
    first: date, sun: Sun
) -> None:
    """The runtime and the simulation must not diverge, at any half hour.

    Three days across each clock change, midnights included, with sunrise,
    elevation, clamps and a random offset, the state carried along.
    """
    start = local(first, 0).astimezone(UTC)
    by_almanac = by_port = WindowState()
    for step in range(3 * 48 + 4):
        at = (start + timedelta(minutes=30 * step)).astimezone(ZONE)
        from_port = evaluate(at, BY_THE_SUN, state=by_port, sun=sun)
        from_almanac = evaluate_schedule(
            BY_THE_SUN,
            snapshot_with_almanac(at, BY_THE_SUN, state=by_almanac, sun=sun),
        )
        by_port, by_almanac = from_port.state, from_almanac.state

        assert from_almanac == from_port, at


# --- A day without a sun event is an answer, not missing data ---------------------------------


def test_the_almanac_tells_no_event_on_this_date_from_not_in_the_almanac() -> None:
    """Two states, both of which survive plain data: "none" is recorded, "unknown" is absent."""
    almanac = build_sun_almanac(BY_THE_SUN, local(MONDAY, 12), POLAR_NIGHT)
    restored = SunAlmanac.from_data(json.loads(json.dumps(almanac.to_data())))
    monday = restored.day(MONDAY)

    assert restored == almanac
    assert monday is not None
    assert monday.sunrise is None
    assert monday.sunset is None
    recorded = monday.passage(-4, rising=False)
    assert recorded is not None
    assert recorded.at is None
    assert monday.passage(-4, rising=True) is None
    assert restored.day(MONDAY + timedelta(days=30)) is None
    source = AlmanacSun(restored)
    assert source.sunrise(MONDAY) is None
    assert source.elevation_reached(MONDAY, -4, rising=False) is None
    with pytest.raises(ScheduleInputMissingError):
        source.elevation_reached(MONDAY, -4, rising=True)


@pytest.mark.parametrize(
    "sun", [POLAR_NIGHT, POLAR_DAY], ids=["polar night", "polar day"]
)
@pytest.mark.parametrize(
    "window",
    [
        config(workday=DayTriggers(sun_event(EARLY), sun_event(LATE))),
        config(workday=DayTriggers(elevation_trigger(-3, EARLY), sun_event(LATE))),
        config(workday=DayTriggers(sun_event(EARLY), elevation_trigger(3, LATE))),
    ],
    ids=["sunrise and sunset", "elevation in the morning", "elevation in the evening"],
)
def test_without_a_sun_event_the_layer_has_an_opinion_and_the_clamp_decides(
    window: WindowConfig, sun: Sun
) -> None:
    """Never ``input_unavailable``: morning at "not before", evening at "not after"."""
    day = schedule_layer(
        window, snapshot_with_almanac(local(MONDAY, 12), window, sun=sun)
    )
    result = evaluate_schedule(
        window, snapshot_with_almanac(local(MONDAY, 12), window, sun=sun)
    )
    by_port = evaluate(local(MONDAY, 12), window, sun=sun)

    assert day.kind is WishKind.TARGET
    assert day.reason is ReasonCode.SCHEDULE_DAY
    assert result.morning_trigger == local(MONDAY, 5, 0)
    assert result.evening_trigger == local(MONDAY, 22, 0)
    assert result == by_port
    night = schedule_layer(
        window, snapshot_with_almanac(local(MONDAY, 22), window, sun=sun)
    )
    assert night.reason is ReasonCode.SCHEDULE_NIGHT


# --- Missing data is never guessed -----------------------------------------------------------


def _without_monday(world: WorldSnapshot) -> WorldSnapshot:
    assert world.almanac is not None
    days = tuple(entry for entry in world.almanac.days if entry.day != MONDAY)
    return replace(world, almanac=SunAlmanac(days))


@pytest.mark.parametrize(
    ("window", "world"),
    [
        (BY_THE_SUN, snapshot(local(MONDAY, 12), installation_seed=SEED)),
        (BY_THE_SUN, _without_monday(snapshot_with_almanac(local(MONDAY, 12)))),
        (BY_THE_SUN, snapshot_with_almanac(local(MONDAY, 12), CONFIG)),
        (BY_THE_SUN, snapshot_with_almanac(local(MONDAY, 12), BY_THE_SUN, seed=None)),
    ],
    ids=[
        "no almanac",
        "a date is missing from the almanac",
        "a passage is missing from the almanac",
        "no seed although a random offset is configured",
    ],
)
def test_a_missing_input_gives_no_opinion_and_changes_no_state(
    window: WindowConfig, world: WorldSnapshot
) -> None:
    """``input_unavailable``: the layer steps aside, and nothing is persisted."""
    wish = schedule_layer(window, world)

    assert wish.kind is WishKind.NO_OPINION
    assert wish.reason is ReasonCode.INPUT_UNAVAILABLE
    assert schedule_state_after(window, world) is world.state
    with pytest.raises(ScheduleInputMissingError):
        evaluate_schedule(window, world)
    decision = _decide(window, world)
    assert decision.winning_wish is None
    assert decision.gate is None


def test_a_snapshot_checks_the_almanac_and_the_seed_it_carries() -> None:
    """Both are optional, but what is there has its type."""
    bad_almanac: object = {"days": []}
    bad_seed: object = True

    assert snapshot(local(MONDAY, 12)).almanac is None
    assert snapshot(local(MONDAY, 12)).installation_seed is None
    with pytest.raises(TypeError, match="almanac of a snapshot"):
        snapshot(local(MONDAY, 12), almanac=bad_almanac)
    with pytest.raises(TypeError, match="seed of the installation"):
        snapshot(local(MONDAY, 12), installation_seed=bad_seed)


def test_without_a_random_offset_the_seed_is_not_needed() -> None:
    """Nothing is asked for that the settings do not use."""
    world = snapshot_with_almanac(local(MONDAY, 12), seed=None)

    assert schedule_layer(CONFIG, world).position == OPEN


def test_an_almanac_answers_only_what_stands_in_it() -> None:
    """'There is none on this day' is an answer; a question never asked is missing."""
    almanac = build_sun_almanac(BY_THE_SUN, local(MONDAY, 12), SUN)
    source = AlmanacSun(almanac)

    assert source.elevation_reached(MONDAY, -6, rising=False) == local(MONDAY, 18, 24)
    with pytest.raises(ScheduleInputMissingError, match="passes -6"):
        source.elevation_reached(MONDAY, -6, rising=True)
    with pytest.raises(ScheduleInputMissingError, match="no entry"):
        source.sunrise(MONDAY + timedelta(days=30))


# --- The layer in the arbiter ---------------------------------------------------------------


def test_the_arbiter_of_the_integration_contains_the_schedule() -> None:
    """One registration, for the layer ``schedule`` and the function ``schedule``."""
    assert SCHEDULE_LAYER in FEATURE_LAYERS
    assert SCHEDULE_LAYER in build_arbiter().layers
    assert SCHEDULE_LAYER.layer is Layer.SCHEDULE
    assert SCHEDULE_LAYER.function is FunctionId.SCHEDULE


def test_the_schedule_wins_as_the_bottom_layer_and_the_window_moves() -> None:
    """Noon: open. Night: closed. Sent, because nothing holds it back."""
    noon = _decide(CONFIG, _at_position(snapshot_with_almanac(local(MONDAY, 12)), 40))
    night = _decide(CONFIG, _at_position(snapshot_with_almanac(local(MONDAY, 22)), 40))

    assert noon.winning_function is FunctionId.SCHEDULE
    assert noon.winning_wish is not None
    assert noon.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert noon.winning_wish.direction is Direction.RAISE_ONLY
    assert noon.target == OPEN
    assert noon.gate is not None
    assert noon.gate.kind is GateKind.SEND
    assert night.winning_wish is not None
    assert night.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT
    assert night.target == CLOSED
    assert night.gate is not None
    assert night.gate.kind is GateKind.SEND


def test_morning_only_raises_and_night_only_lowers_through_the_direction_constraint() -> (
    None
):
    """The schedule states the direction; the constraint of the arbiter enforces it."""
    window = config(targets=ScheduleTargets(Position(80), Position(30), Position(30)))
    higher_by_day = _decide(
        window, _at_position(snapshot_with_almanac(local(MONDAY, 12), window), 100)
    )
    lower_by_night = _decide(
        window, _at_position(snapshot_with_almanac(local(MONDAY, 22), window), 10)
    )

    for decision, reason in (
        (higher_by_day, ReasonCode.ONLY_RAISE),
        (lower_by_night, ReasonCode.ONLY_LOWER),
    ):
        assert [entry.constraint for entry in decision.constraints] == [
            Constraint.DIRECTION
        ]
        assert decision.constraints[0].reason is reason
        assert decision.target is None
        assert decision.gate is None


def test_a_schedule_that_is_switched_off_has_no_opinion() -> None:
    """The switch of the feature: ``not_configured``, and nothing is persisted."""
    window = config(enabled=False)
    world = snapshot_with_almanac(local(MONDAY, 12), window)

    assert schedule_layer(window, world) is SCHEDULE_NOT_CONFIGURED
    assert schedule_state_after(window, world) is world.state
    assert _decide(window, world).winning_wish is None


def test_the_arbiter_never_calls_a_schedule_that_a_faulty_setting_paused() -> None:
    """``function_disabled_by_fault``; the layer itself does not look at the set.

    The snapshot has no almanac. A layer that was called would answer
    ``input_unavailable``; the record shows that it was not asked at all.
    """
    paused = replace(CONFIG, disabled_functions=frozenset({FunctionId.SCHEDULE}))
    world = snapshot(local(MONDAY, 12))

    decision = _decide(paused, world)
    asked = _decide(CONFIG, world)

    reasons = {entry.function: entry.reason for entry in decision.other_layers}
    assert decision.winning_wish is None
    assert reasons[FunctionId.SCHEDULE] is ReasonCode.FUNCTION_DISABLED_BY_FAULT
    assert {entry.function: entry.reason for entry in asked.other_layers}[
        FunctionId.SCHEDULE
    ] is ReasonCode.INPUT_UNAVAILABLE
    assert schedule_state_after(paused, snapshot_with_almanac(local(MONDAY, 12))) == (
        WindowState()
    )


def test_the_runtime_persists_what_the_schedule_has_to_remember() -> None:
    """The layer only reads; ``schedule_state_after`` returns the state to keep."""
    world = snapshot_with_almanac(local(MONDAY, 12))

    assert schedule_state_after(CONFIG, world) == evaluate(local(MONDAY, 12)).state
    assert schedule_state_after(CONFIG, world).latched_day_types != ()


# --- The trigger of the wish: the actual start of the part of the day -----------------------

MORNING = local(MONDAY, 6, 30)


def _after_a_restart(
    at: datetime, last_movement: datetime, window: WindowConfig = CONFIG
) -> Decision:
    """Decide from persisted state only, with the shutter not where it belongs."""
    persisted = WindowState(last_comfort_movement=last_movement)
    restored = WindowState.from_data(json.loads(json.dumps(persisted.to_data())))
    world = snapshot_with_almanac(at, window, state=restored)
    return _decide(window, _at_position(world, 60))


@pytest.mark.parametrize(
    ("last_movement", "kind", "reason"),
    [
        (MORNING + timedelta(seconds=5), GateKind.DEFER, ReasonCode.MIN_INTERVAL),
        (MORNING, GateKind.DEFER, ReasonCode.MIN_INTERVAL),
        (MORNING - timedelta(seconds=1), GateKind.SEND, ReasonCode.SENT),
    ],
    ids=[
        "the movement came after the boundary",
        "the movement came at the very instant of the boundary",
        "the movement came before the boundary",
    ],
)
def test_a_restart_after_a_boundary_does_not_make_the_wish_fresh(
    last_movement: datetime, kind: GateKind, reason: ReasonCode
) -> None:
    """06:33, three minutes after the morning trigger, first evaluation after a start.

    The trigger of the wish is the boundary (06:30), not this evaluation. A
    last own comfort movement at or after the boundary was its answer, so the
    wish is not fresh and the minimum interval of motor protection holds it;
    equal instants count as not fresh. A movement from before the boundary
    does not: the boundary is something new.
    """
    decision = _after_a_restart(local(MONDAY, 6, 33), last_movement)

    assert decision.winning_wish is not None
    assert decision.winning_wish.triggered_at == MORNING
    assert decision.gate is not None
    assert (decision.gate.kind, decision.gate.reason) == (kind, reason)
    if kind is GateKind.DEFER:
        assert decision.gate.until == last_movement + CONFIG.motor_min_interval


def test_a_boundary_shifted_by_a_clamp_reports_its_actual_start() -> None:
    """Sunrise at 06:00, 'not before' 06:30: the day began at 06:30.

    The last movement was at 06:28, after the nominal and before the actual
    start. With the nominal time as trigger the wish would not be fresh and
    would wait; with the actual one it is fresh and is sent.
    """
    window = config(
        workday=DayTriggers(sun_event((time(6, 30), time(9, 0))), fixed(20, 0))
    )

    decision = _after_a_restart(local(MONDAY, 6, 31), local(MONDAY, 6, 28), window)

    assert decision.winning_wish is not None
    assert decision.winning_wish.triggered_at == local(MONDAY, 6, 30)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_a_boundary_shifted_by_the_random_offset_reports_its_actual_start() -> None:
    """The offset of this window and date moves 06:30; the trigger moves with it."""
    window = config(random_offset=timedelta(minutes=30))
    actual = evaluate(local(MONDAY, 12), window).morning_trigger.astimezone(ZONE)
    assert actual != MORNING

    fresh = _after_a_restart(
        actual + timedelta(minutes=2), actual - timedelta(minutes=1), window
    )
    answered = _after_a_restart(actual + timedelta(minutes=2), actual, window)

    assert fresh.winning_wish is not None
    assert fresh.winning_wish.triggered_at == actual
    assert fresh.gate is not None
    assert fresh.gate.kind is GateKind.SEND
    assert answered.gate is not None
    assert answered.gate.reason is ReasonCode.MIN_INTERVAL


def test_an_evening_begun_by_the_brightness_reports_its_actual_start() -> None:
    """Dark since 17:00, ten minutes of delay: the night began at 17:10, not at 18:00."""
    window = config(
        workday=DayTriggers(fixed(6, 30), sun_event(LATE)),
        brightness_source="outdoor_brightness",
        brightness_threshold=50,
        brightness_delay=timedelta(minutes=10),
    )
    began = local(MONDAY, 17, 10)
    no_value: dict[str, AnySourceValue] = {}

    def at_17_13(last_movement: datetime) -> Decision:
        persisted = WindowState(
            last_comfort_movement=last_movement,
            brightness_below_since=local(MONDAY, 17),
            evening_brightness_at=began,
        )
        world = snapshot_with_almanac(
            local(MONDAY, 17, 13), window, sources=no_value, state=persisted
        )
        return _decide(window, _at_position(world, 60))

    fresh = at_17_13(local(MONDAY, 17, 8))
    answered = at_17_13(began)

    assert fresh.winning_wish is not None
    assert fresh.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT
    assert fresh.winning_wish.triggered_at == began
    assert fresh.gate is not None
    assert fresh.gate.kind is GateKind.SEND
    assert answered.gate is not None
    assert answered.gate.reason is ReasonCode.MIN_INTERVAL
