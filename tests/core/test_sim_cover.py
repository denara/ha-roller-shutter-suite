"""The behaviour profiles of the simulated cover, one by one."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.roller_shutter_suite.core.model import (
    MovementState,
    Observation,
    Position,
    PositionSource,
    PositionUpdates,
    TransitReporting,
)
from tests.sim.cover import CoverProfile, RawReport, Reporting, SimulatedCover

T0 = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
LATER = T0 + timedelta(minutes=5)
OPEN = 100
HALF = 50
BLOCKED = 60
DRIFTED_TARGET = 80
DRIFTED_REAL = 40
A_FEW_PERCENT = 10
OFFSET = 8
SETTLED_UP = 48
SETTLED_DOWN = 21
CALCULATED_TOLERANCE = 2
UP = timedelta(seconds=20)
DOWN = timedelta(seconds=10)


def cover(profile: CoverProfile, position: int = 0) -> SimulatedCover:
    """Return a cover at rest at ``position`` that has reported once at T0."""
    return SimulatedCover(
        "cover.example_window", profile, position=position, available_since=T0
    )


def reports(cover: SimulatedCover, until: datetime = LATER) -> list[RawReport]:
    """Deliver every report up to ``until``."""
    return cover.reports_due(until)


def profile(**changes: object) -> CoverProfile:
    """Return a profile with a travel of 20 s up and 10 s down."""
    arguments: dict[str, object] = {"travel_time_up": UP, "travel_time_down": DOWN}
    return CoverProfile("test", **(arguments | changes))  # type: ignore[arg-type]


# --- Travel ------------------------------------------------------------------------------


def test_the_travel_time_follows_the_direction_and_the_distance() -> None:
    """Half the way up takes half the travel time up; the way down its own."""
    subject = cover(profile())
    reports(subject)
    subject.move_to(50, T0 + timedelta(seconds=1))

    assert subject.moving(T0 + timedelta(seconds=10))
    assert not subject.moving(T0 + timedelta(seconds=11.1))
    subject.move_to(0, T0 + timedelta(seconds=30))
    assert subject.moving(T0 + timedelta(seconds=34))
    assert not subject.moving(T0 + timedelta(seconds=35.1))


def test_a_movement_into_an_end_stop_takes_longer() -> None:
    """Not linear in percent: the end stop adds its extra time."""
    subject = cover(profile(end_stop_extra=timedelta(seconds=5)))
    reports(subject)
    subject.move_to(100, T0)

    assert subject.moving(T0 + timedelta(seconds=24))
    assert not subject.moving(T0 + timedelta(seconds=25.1))
    subject.move_to(50, T0 + timedelta(seconds=30))
    assert not subject.moving(T0 + timedelta(seconds=35.1))


def test_live_reports_carry_transit_states_and_positions() -> None:
    """A transit state with rising positions, then the resting state at the target."""
    subject = cover(profile(live_interval=timedelta(seconds=5)))
    reports(subject)
    subject.move_to(100, T0)
    written = reports(subject)

    assert [r.state for r in written] == ["opening"] * 4 + ["open"]
    positions = [r.position for r in written]
    assert positions == sorted(positions)  # type: ignore[type-var]
    assert positions[-1] == OPEN
    assert written[-1].at == T0 + UP
    # The start report is written a moment after the command and already a
    # few percent into the travel.
    assert written[0].at == T0 + profile().start_latency
    assert 0 < (written[0].position or 0) < A_FEW_PERCENT


def test_the_start_report_can_be_further_into_the_travel() -> None:
    """A platform whose first write already carries a position well into the travel."""
    subject = cover(profile(start_offset_percent=OFFSET))
    reports(subject)
    subject.move_to(100, T0)
    first = reports(subject)[0]

    assert first.position is not None
    assert first.position >= OFFSET


def test_end_only_keeps_the_old_position_and_jumps_at_the_end() -> None:
    """The transit state carries the old position; the end report the target."""
    subject = cover(profile(reporting=Reporting.END_ONLY), position=100)
    reports(subject)
    subject.move_to(0, T0)
    written = reports(subject)

    assert [(r.state, r.position) for r in written] == [("closing", 100), ("closed", 0)]
    assert written[-1].at == T0 + DOWN


def test_a_polled_platform_reports_on_its_grid_only() -> None:
    """No transit state, reports on the grid, none at the real end of the movement."""
    subject = cover(
        profile(
            reporting=Reporting.GRID,
            transit_states=False,
            grid_interval=timedelta(seconds=15),
        )
    )
    reports(subject)
    subject.move_to(100, T0 + timedelta(seconds=1))
    written = reports(subject)

    assert all(r.state in ("open", "closed") for r in written)
    assert [r.at for r in written] == [T0 + timedelta(seconds=15 * n) for n in (1, 2)]
    assert written[0].position is not None
    assert 0 < written[0].position < OPEN
    assert written[-1].position == OPEN
    assert written[-1].at != T0 + timedelta(seconds=1) + UP


def test_a_measured_cover_settles_a_few_percent_off_asymmetrically() -> None:
    """Up ends 2 short, down 1 short; the report is what the drive measures."""
    subject = cover(
        profile(
            position_source=PositionSource.MEASURED,
            settle_offset_up=-2,
            settle_offset_down=1,
        )
    )
    reports(subject)
    subject.move_to(50, T0)
    up = reports(subject)[-1]
    subject.move_to(20, LATER)
    down = reports(subject, LATER + timedelta(minutes=1))[-1]

    assert (up.state, up.position) == ("open", SETTLED_UP)
    assert (down.state, down.position) == ("open", SETTLED_DOWN)
    assert subject.real_position(LATER + timedelta(minutes=1)) == SETTLED_DOWN


def test_a_calculated_position_reports_the_target_although_the_curtain_is_blocked() -> (
    None
):
    """The actuator counts to the target; the curtain stopped where the motor cut out."""
    subject = cover(profile(blocked_at=BLOCKED))
    reports(subject)
    subject.move_to(100, T0)
    # Half way through the count the curtain is still following it ...
    assert subject.real_position(T0 + timedelta(seconds=10)) == pytest.approx(HALF)
    # ... and later it has stopped while the count goes on.
    assert subject.real_position(T0 + timedelta(seconds=16)) == BLOCKED
    assert subject.reported_position(T0 + timedelta(seconds=16)) == pytest.approx(80)
    written = reports(subject)

    assert written[-1] == RawReport(T0 + UP, "open", 100)
    assert subject.real_position(LATER) == BLOCKED
    assert subject.reported_position(LATER) == OPEN


def test_the_drift_after_a_block_persists_on_the_next_partial_movement() -> None:
    """The motor runs the counted distance down; the curtain goes down by as much."""
    subject = cover(profile(blocked_at=BLOCKED))
    reports(subject)
    subject.move_to(100, T0)
    reports(subject)
    subject.move_to(80, LATER)
    # The count runs 20 down in 2 s; half way the curtain is 10 lower, not higher.
    assert subject.real_position(LATER + timedelta(seconds=1)) == pytest.approx(50)
    written = reports(subject, LATER + timedelta(minutes=1))

    assert written[-1].position == DRIFTED_TARGET
    assert subject.real_position(LATER + timedelta(minutes=1)) == DRIFTED_REAL


def test_a_movement_into_an_end_position_references_the_curtain_again() -> None:
    """Closed is closed for curtain and count; afterwards they move as one."""
    subject = cover(profile(blocked_at=BLOCKED))
    reports(subject)
    subject.move_to(100, T0)
    subject.move_to(80, LATER)
    subject.move_to(0, LATER + timedelta(minutes=1))
    referenced = LATER + timedelta(minutes=2)

    assert subject.real_position(referenced) == 0
    assert subject.reported_position(referenced) == 0
    subject.move_to(HALF, referenced)
    assert subject.real_position(referenced + timedelta(minutes=1)) == HALF
    assert subject.reported_position(referenced + timedelta(minutes=1)) == HALF


def test_a_measured_cover_that_is_blocked_reports_where_it_stopped() -> None:
    """With a measured position the block is visible in the report."""
    subject = cover(
        profile(blocked_at=BLOCKED, position_source=PositionSource.MEASURED)
    )
    reports(subject)
    subject.move_to(100, T0)

    assert reports(subject)[-1].position == BLOCKED


def test_a_cover_without_position_feedback_reports_states_only() -> None:
    """No position anywhere; a target from 50 upwards opens, a lower one closes."""
    subject = cover(profile(reports_position=False, supports_set_position=False))
    reports(subject)
    subject.move_to(40, T0)
    written = reports(subject)

    assert written == []  # 40 closes, and the cover is closed already
    subject.move_to(70, T0 + timedelta(seconds=1))
    written = reports(subject)
    assert [(r.state, r.position) for r in written][-1] == ("open", None)
    assert subject.real_position(LATER) == OPEN


# --- Stop, reversal, dropout ----------------------------------------------------------------


def test_stop_freezes_the_curtain_and_reports_where_it_is() -> None:
    """A stop in mid-travel ends the movement; the resting report follows."""
    subject = cover(profile())
    reports(subject)
    subject.move_to(100, T0)
    subject.stop(T0 + timedelta(seconds=10))
    written = reports(subject)

    assert written[-1].state == "open"
    assert written[-1].position == HALF
    assert subject.real_position(LATER) == HALF
    assert not subject.moving(T0 + timedelta(seconds=11))


def test_a_cover_without_stop_ignores_it() -> None:
    """The movement runs to its end."""
    subject = cover(profile(supports_stop=False))
    reports(subject)
    subject.move_to(100, T0)
    subject.stop(T0 + timedelta(seconds=10))

    assert reports(subject)[-1].position == OPEN


def test_a_reversal_writes_a_transit_state_after_a_transit_state() -> None:
    """A new command during the travel starts from the current count."""
    subject = cover(profile(live_interval=timedelta(seconds=4)))
    reports(subject)
    subject.move_to(100, T0)
    reports(subject, T0 + timedelta(seconds=9))
    subject.move_to(0, T0 + timedelta(seconds=10))
    written = reports(subject)

    assert written[0].state == "closing"
    assert written[0].position is not None
    assert HALF - A_FEW_PERCENT < written[0].position < HALF
    assert written[-1] == RawReport(T0 + timedelta(seconds=10) + DOWN / 2, "closed", 0)


def test_a_dropout_swallows_the_writes_and_returns_with_the_state_of_that_moment() -> (
    None
):
    """Unavailable during the gap; afterwards the cover reports what it has then."""
    subject = cover(profile(live_interval=timedelta(seconds=4)))
    reports(subject)
    subject.move_to(100, T0)
    subject.disconnect(T0 + timedelta(seconds=5), T0 + timedelta(seconds=40))
    written = reports(subject)

    states = [r.state for r in written]
    assert states[-2:] == ["unavailable", "open"]
    assert written[-1] == RawReport(T0 + timedelta(seconds=40), "open", 100)
    assert all(
        not (T0 + timedelta(seconds=5) < r.at < T0 + timedelta(seconds=40))
        for r in written
    )


def test_returning_from_a_dropout_with_the_same_state_is_nothing_new() -> None:
    """The observation after the gap equals the one before the gap.

    The runner records the return, since it changes the observation from
    unavailable; that it brings nothing new is the tracker's judgement
    (section 8.3), not a report the runner drops.
    """
    subject = cover(profile(), position=100)
    before = reports(subject)[-1].observation()
    subject.disconnect(T0 + timedelta(seconds=5), T0 + timedelta(seconds=40))
    written = reports(subject)

    assert written[-1].observation() == before
    assert written[-2].observation() == Observation(MovementState.UNAVAILABLE)


# --- The writes of a platform ---------------------------------------------------------------


def test_a_late_last_report_with_a_position_write_before_rest_and_a_repeat() -> None:
    """The end arrives late, as a position write, then the resting state, then again."""
    subject = cover(
        profile(
            report_delay=timedelta(seconds=8),
            position_before_rest=True,
            repeat_last_write=True,
            live_interval=timedelta(minutes=1),
        )
    )
    reports(subject)
    subject.move_to(100, T0)
    written = reports(subject)
    end = T0 + UP + timedelta(seconds=8)

    assert [(r.at - end, r.state, r.position) for r in written[-3:]] == [
        (timedelta(milliseconds=-20), "opening", 100),
        (timedelta(0), "open", 100),
        (timedelta(milliseconds=10), "open", 100),
    ]
    assert written[-1].observation() == written[-2].observation()


def test_an_unchanged_state_is_rewritten_with_a_new_change_time() -> None:
    """While idle the platform writes the same state again and again."""
    subject = cover(profile(rewrite_unchanged_every=timedelta(minutes=1)), position=100)
    written = reports(subject, T0 + timedelta(minutes=3, seconds=30))

    assert [r.at for r in written] == [T0 + timedelta(minutes=n) for n in range(4)]
    assert len({r.observation() for r in written}) == 1


def test_a_platform_without_transit_states_reports_positions_at_rest() -> None:
    """The state stays open or closed while the position changes."""
    subject = cover(profile(transit_states=False, live_interval=timedelta(seconds=5)))
    reports(subject)
    subject.move_to(100, T0)
    written = reports(subject)

    assert {r.state for r in written} == {"open"}
    assert all(not r.observation().moving for r in written)


# --- The profile and what the user states --------------------------------------------------


def test_the_capability_profile_follows_the_behaviour() -> None:
    """A polled platform states its grid as the report delay; live is live."""
    polled = profile(
        reporting=Reporting.GRID,
        transit_states=False,
        grid_interval=timedelta(seconds=60),
        report_delay=timedelta(seconds=5),
    )
    live = profile()

    assert polled.capability_profile().report_delay == timedelta(seconds=65)
    assert polled.capability_profile().reports_transit_states is TransitReporting.NO
    assert polled.capability_profile().position_updates is PositionUpdates.END_ONLY
    assert live.capability_profile().position_updates is PositionUpdates.LIVE
    assert live.capability_profile().travel_time_up == UP
    assert live.capability_profile().tolerance == CALCULATED_TOLERANCE


@pytest.mark.parametrize(
    "changes",
    [
        {"travel_time_up": timedelta(0)},
        {"grid_interval": timedelta(0)},
        {"report_delay": timedelta(seconds=-1)},
        {"start_offset_percent": 101},
        {"blocked_at": -1},
        {"rewrite_unchanged_every": timedelta(0)},
    ],
)
def test_an_impossible_profile_is_refused(changes: dict[str, object]) -> None:
    """Durations and percentages are validated."""
    with pytest.raises(ValueError, match=r"must|percentage"):
        profile(**changes)


def test_a_target_outside_the_scale_and_a_dropout_that_ends_first_are_refused() -> None:
    """The cover checks what it is asked."""
    subject = cover(profile())
    with pytest.raises(ValueError, match="percentage"):
        subject.move_to(101, T0)
    with pytest.raises(ValueError, match="ends after"):
        subject.disconnect(T0, T0)


def test_the_first_observation_before_any_report_is_unavailable() -> None:
    """A member that has not reported yet is unavailable, never at a default."""
    subject = SimulatedCover("cover.example_window", profile(), position=0)

    assert subject.current_observation() == Observation(MovementState.UNAVAILABLE)
    assert subject.next_report_at() is None
    subject.move_to(100, T0)
    delivered = reports(subject)
    assert subject.current_observation() == Observation(
        MovementState.RESTING, Position(100)
    )
    assert subject.last_report == delivered[-1]
    assert subject.commands == [(T0, 100, "engine")]
