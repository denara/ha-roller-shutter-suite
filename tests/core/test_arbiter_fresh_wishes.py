"""The minimum interval holds back repetition, not a wish that is fresh.

A wish is fresh if its trigger lies after the last own comfort movement. The
stub layers of ``arbiter_kit`` state their trigger from the sources
``part_of_day_since``, ``shading_since`` and ``sleep_since``.

Recording a real command is not part of the arbiter, so ``_House`` does here
what the sending block will do: after a decision "send" the shutter stands at
the target, and the motor protection clock shows the time of the movement.
"""

import itertools
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    Decision,
    GateKind,
    GateOutcome,
    GateRule,
    SourceValue,
    WindowState,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import DRY_RUN, NOW, day, engine, night, since, snapshot

MORNING = NOW - timedelta(hours=2)
INTERVAL = timedelta(minutes=10)


def _minutes(count: float) -> datetime:
    return NOW + timedelta(minutes=count)


@dataclass
class _House:
    """One armed window whose comfort commands are carried out at once."""

    position: int
    moved_at: datetime | None = None
    movements: list[tuple[datetime, ReasonCode, int]] = field(default_factory=list)

    def recompute(self, at: datetime, sources: dict[str, AnySourceValue]) -> Decision:
        state = WindowState(last_comfort_movement=self.moved_at)
        world = replace(
            snapshot(sources=sources, position=self.position, state=state), time=at
        )
        decision = engine().recompute(world)
        assert decision.winning_wish is not None
        assert decision.gate is not None
        if decision.gate.kind is GateKind.SEND:
            assert decision.target is not None
            self.position = decision.target.value
            self.moved_at = at
            self.movements.append(
                (at, decision.winning_wish.reason, decision.target.value)
            )
        return decision


def _shading(position: int, began: datetime) -> dict[str, AnySourceValue]:
    return day(
        part_of_day_since=since(MORNING),
        shading_position=SourceValue.of(position),
        shading_since=since(began),
    )


def _held_until(moment: datetime) -> GateOutcome:
    return GateOutcome.defer(
        GateRule.MOTOR_PROTECTION, ReasonCode.MIN_INTERVAL, until=moment
    )


def test_tracking_within_an_episode_keeps_the_minimum_interval() -> None:
    """The episode began before the last movement: a new position is not fresh."""
    house = _House(position=100)
    began = _minutes(0)

    house.recompute(_minutes(0), _shading(40, began))
    early = house.recompute(_minutes(4), _shading(55, began))
    on_time = house.recompute(_minutes(10), _shading(55, began))

    assert early.gate == _held_until(_minutes(10))
    assert on_time.gate == GateOutcome.send()
    assert house.movements == [
        (_minutes(0), ReasonCode.SHADING_GEOMETRIC, 40),
        (_minutes(10), ReasonCode.SHADING_GEOMETRIC, 55),
    ]


def test_the_start_of_an_episode_is_fresh() -> None:
    """Shading begins two minutes after the morning opening and runs at once."""
    house = _House(position=0)

    house.recompute(_minutes(0), day(part_of_day_since=since(_minutes(0))))
    shaded = house.recompute(_minutes(2), _shading(40, began=_minutes(2)))

    assert shaded.gate == GateOutcome.send()
    assert house.position == 40  # noqa: PLR2004 - the shading position above


def test_an_older_wish_that_wins_again_is_not_fresh() -> None:
    """The day position after the end of shading: its trigger is hours old."""
    house = _House(position=100)
    house.recompute(_minutes(0), _shading(40, began=_minutes(0)))

    back = house.recompute(_minutes(4), day(part_of_day_since=since(MORNING)))

    assert back.winning_wish is not None
    assert back.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert back.gate == _held_until(_minutes(10))


def test_an_evening_boundary_two_minutes_after_the_return_movement_at_the_end_of_shading_runs_on_time() -> (
    None
):
    """The return itself is not fresh and waits its turn; the evening wish is fresh."""
    house = _House(position=100)
    house.recompute(_minutes(-30), _shading(40, began=_minutes(-30)))

    returned = house.recompute(_minutes(0), day(part_of_day_since=since(MORNING)))
    evening = house.recompute(_minutes(2), night(part_of_day_since=since(_minutes(2))))

    assert returned.gate == GateOutcome.send()  # the last movement is 30 minutes old
    assert evening.gate == GateOutcome.send()
    assert house.movements[1:] == [
        (_minutes(0), ReasonCode.SCHEDULE_DAY, 100),
        (_minutes(2), ReasonCode.SCHEDULE_NIGHT, 0),
    ]


def test_sleep_mode_switched_on_directly_after_a_tracking_movement_runs_at_once() -> (
    None
):
    """Somebody flipped the switch just now; that is not flapping."""
    house = _House(position=100)
    began = _minutes(-20)
    house.recompute(_minutes(-20), _shading(40, began))
    house.recompute(_minutes(0), _shading(55, began))

    asleep = house.recompute(
        _minutes(1),
        _shading(55, began)
        | {"sleep": SourceValue.of(True), "sleep_since": since(_minutes(1))},
    )

    assert asleep.winning_wish is not None
    assert asleep.winning_wish.reason is ReasonCode.SLEEP_MODE
    assert asleep.gate == GateOutcome.send()
    assert house.position == 0


def test_shading_toggling_every_three_minutes_yields_one_return_per_minimum_interval() -> (
    None
):
    """Each start is fresh but finds the window in place; the returns are held."""
    house = _House(position=100)
    outcomes: list[ReasonCode] = []
    began = _minutes(0)
    for step in range(13):
        at = _minutes(3 * step)
        if step % 2 == 0:
            began = at
            sources = _shading(40, began)
        else:
            sources = day(part_of_day_since=since(MORNING))
        decision = house.recompute(at, sources)
        assert decision.gate is not None
        outcomes.append(decision.gate.reason)

    returns = [
        at for at, reason, _ in house.movements if reason is ReasonCode.SCHEDULE_DAY
    ]
    assert returns == [_minutes(15), _minutes(33)]
    assert all(
        later - earlier >= INTERVAL for earlier, later in itertools.pairwise(returns)
    )
    assert outcomes[:6] == [
        ReasonCode.SENT,  # 0: the episode begins, the shutter goes to 40
        ReasonCode.MIN_INTERVAL,  # 3: the return is not fresh
        ReasonCode.TARGET_REACHED,  # 6: fresh, but the shutter is there already
        ReasonCode.MIN_INTERVAL,  # 9
        ReasonCode.TARGET_REACHED,  # 12
        ReasonCode.SENT,  # 15: the one return of this interval
    ]


def test_a_wish_without_a_trigger_is_never_fresh() -> None:
    """What a layer does not state is not assumed in its favour."""
    house = _House(position=100, moved_at=_minutes(-1))

    decision = house.recompute(_minutes(0), night())

    assert decision.gate == _held_until(_minutes(9))


def test_a_trigger_at_the_moment_of_the_last_movement_is_not_fresh() -> None:
    """That movement was the answer to this trigger."""
    house = _House(position=100)
    fired = _minutes(0)
    house.recompute(fired, _shading(40, began=fired))

    tracking = house.recompute(_minutes(1), _shading(50, began=fired))

    assert tracking.gate == _held_until(_minutes(10))


def test_in_dry_run_freshness_is_judged_by_the_simulated_clock() -> None:
    """The real clock says "just moved"; the simulated one decides."""
    subject = engine()
    real = WindowState(last_comfort_movement=_minutes(0))
    shaded = replace(
        snapshot(
            sources=_shading(40, began=_minutes(-5)),
            position=70,
            state=real,
            controls=DRY_RUN,
        ),
        time=_minutes(0),
    )
    state = subject.state_after(shaded, subject.recompute(shaded))

    def later(sources: dict[str, AnySourceValue]) -> GateOutcome | None:
        world = replace(shaded, time=_minutes(2), sources=sources, state=state)
        return subject.recompute(world).gate

    stale = later(day(part_of_day_since=since(MORNING)))
    fresh = later(night(part_of_day_since=since(_minutes(2))))

    assert stale == replace(_held_until(_minutes(10)), dry_run=True)
    assert fresh is not None
    assert fresh.reason is ReasonCode.DRY_RUN
