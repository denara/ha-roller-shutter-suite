"""The first scenarios of the time-lapse simulation (block C05).

Every test builds a named scenario of ``tests/sim/scenarios.py``, runs it and
judges the record with the assertions of ``tests/sim/assertions.py``. The
year scenario is run once per session (a fixture with the scope of the
module), because it takes seconds; the day scenarios take milliseconds.
"""

import itertools
import time as wall_clock
from datetime import time, timedelta
from typing import Final

import pytest

from custom_components.roller_shutter_suite.core.arbiter import member_expectation_end
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    GateRule,
    OperatingMode,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.sim.assertions import (
    ScenarioAssertionError,
    assert_at_most_movements_per_day,
    assert_min_interval,
    assert_no_command_loop,
    assert_no_commands,
    assert_no_intermediate_position,
    assert_schedule_commands_inside_clamps,
    movements_per_day,
)
from tests.sim.cover import CoverProfile, SimulatedCover
from tests.sim.record import EntryKind, Record
from tests.sim.runner import Simulation
from tests.sim.scenarios import (
    ARMED,
    MONDAY,
    PROFILES,
    SATURDAY,
    SCENARIOS,
    YEAR_START,
    calm_sources,
    configs,
    fire_in_dry_run,
    fire_in_mode,
    local,
    run_named,
    with_restarts,
    year,
)
from tests.sim.world import World

WINDOW: Final = "window_example"
MEMBER: Final = "cover.example_window"
A_YEAR: Final = timedelta(days=365)
A_MINUTE: Final = 60.0
"""Seconds; the acceptance criterion says well under a minute."""
TWICE_A_DAY: Final = 2
TEN_WINDOWS: Final = 10
DAYS_OF_THE_YEAR: Final = 365
HALF_OPEN: Final = 30
HALF: Final = 50
REPORT_DELAY: Final = timedelta(seconds=8)


@pytest.fixture(scope="module")
def year_run() -> tuple[Simulation, float]:
    """Run the year for ten windows once; return the simulation and the seconds."""
    simulation = year(seed=1)
    started = wall_clock.perf_counter()
    simulation.run(simulation.now + A_YEAR)
    return simulation, wall_clock.perf_counter() - started


def _sends_of(record: Record, window_id: str) -> list[tuple[str, int]]:
    """Return (local time, target) of every send of a window."""
    return [
        (entry.at.astimezone(record.zone).strftime("%H:%M:%S"), entry.target.value)
        for entry in record.sends(window_id)
        if entry.target is not None
    ]


# --- Workday and weekend with the schedule only --------------------------------------------


def test_a_workday_opens_at_seven_and_closes_after_sunset() -> None:
    """One window, schedule only: two movements, at the fixed morning and at sunset."""
    simulation = run_named("workday")
    record = simulation.record
    sends = _sends_of(record, WINDOW)

    assert len(sends) == TWICE_A_DAY
    assert sends[0] == ("07:00:00", FULLY_OPEN.value)
    assert sends[1][1] == FULLY_CLOSED.value
    assert "19:0" < sends[1][0] < "19:4"  # sunset at the round point on that Monday
    assert_no_command_loop(record)
    assert_min_interval(record, configs(simulation))
    assert_schedule_commands_inside_clamps(record, simulation.window(WINDOW).config)
    assert movements_per_day(record, WINDOW).counts == {MONDAY: 2}


def test_a_weekend_day_opens_later() -> None:
    """On a Saturday the free-day morning applies: 08:30."""
    simulation = run_named("weekend")
    sends = _sends_of(simulation.record, WINDOW)

    assert sends[0] == ("08:30:00", FULLY_OPEN.value)
    assert movements_per_day(simulation.record, WINDOW).counts == {SATURDAY: 2}


def test_a_report_that_changes_nothing_is_dropped() -> None:
    """The runner normalizes reports: duplicates and rewrites never reach the core."""
    simulation = run_named("chatty")

    assert simulation.record.dropped_reports > 0
    assert_no_command_loop(simulation.record)
    assert len(simulation.record.sends(WINDOW)) == TWICE_A_DAY
    reports = simulation.record.of_kind(EntryKind.REPORT, WINDOW)
    for earlier, later in itertools.pairwise(reports):
        assert earlier.observation != later.observation


# --- The year -----------------------------------------------------------------------------


def test_a_year_for_ten_windows_runs_well_under_a_minute(
    year_run: tuple[Simulation, float],
) -> None:
    """The year is measured and printed; the test fails only at a full minute.

    "Well under a minute" is judged from the printed time (``pytest -s``
    shows it) and stated in the pull request. The bound here is the minute
    itself, so a loaded machine does not make a wall-clock test flaky, while
    a year that really takes a minute still fails.
    """
    simulation, seconds = year_run
    print(f"a year for ten windows took {seconds:.1f} s")  # noqa: T201 - the measurement

    assert seconds < A_MINUTE
    assert simulation.recomputes > 0
    assert len(simulation.windows) == TEN_WINDOWS


def test_in_the_year_each_window_moves_at_most_twice_a_day(
    year_run: tuple[Simulation, float],
) -> None:
    """Schedule only: the morning opening and the evening closing, never more.

    The first day of the run is left out: see the next test.
    """
    simulation, _ = year_run
    record = simulation.record
    second_day = local(YEAR_START + timedelta(days=1), time(0, 0))

    assert_at_most_movements_per_day(record, 2, since=second_day)
    for window in simulation.windows:
        counts = movements_per_day(record, window.window_id)
        assert counts.most <= TWICE_A_DAY + 1
        assert len(counts.counts) == DAYS_OF_THE_YEAR
        assert all(
            count == TWICE_A_DAY
            for day, count in counts.counts.items()
            if day != YEAR_START
        )


def test_a_member_without_position_feedback_is_commanded_once_at_the_start(
    year_run: tuple[Simulation, float],
) -> None:
    """Nobody knows where such a member stands, so the first recompute sends.

    Window 6 has the member without position feedback. Every other window
    starts closed at midnight and does not move until the morning.
    """
    simulation, _ = year_run
    record = simulation.record
    first_day = {
        window.window_id: movements_per_day(record, window.window_id).counts[YEAR_START]
        for window in simulation.windows
    }

    assert first_day == {f"window_{n}": 2 for n in range(1, 11)} | {"window_6": 3}
    first = record.sends("window_6")[0]
    assert first.at == local(YEAR_START, time(0, 0))
    assert first.target == FULLY_CLOSED


def test_in_the_year_no_window_moves_outside_its_clamps(
    year_run: tuple[Simulation, float],
) -> None:
    """Every schedule movement lies at its fixed time or between its clamps."""
    simulation, _ = year_run
    second_day = local(YEAR_START + timedelta(days=1), time(0, 0))
    for window in simulation.windows:
        assert_schedule_commands_inside_clamps(
            simulation.record, window.config, since=second_day
        )


def test_in_the_year_there_is_no_command_loop_and_the_interval_holds(
    year_run: tuple[Simulation, float],
) -> None:
    """Every profile is exercised over the year without a command loop."""
    simulation, _ = year_run

    assert_no_command_loop(simulation.record)
    assert_min_interval(simulation.record, configs(simulation))


def test_the_year_crosses_both_clock_changes(
    year_run: tuple[Simulation, float],
) -> None:
    """The morning opening stays at 07:00 on the clock on both days of a change."""
    simulation, _ = year_run
    record = simulation.record
    for day in (
        YEAR_START.replace(month=3, day=30),
        YEAR_START.replace(month=10, day=26),
    ):
        # 30 March and 26 October 2026 are Mondays, the days after the changes.
        opened = [
            entry
            for entry in record.sends("window_1")
            if record.local_date(entry) == day and entry.target == FULLY_OPEN
        ]
        assert len(opened) == 1
        assert opened[0].at.astimezone(record.zone).time() == time(7, 0)


def test_every_profile_is_exercised_in_the_year(
    year_run: tuple[Simulation, float],
) -> None:
    """Each behaviour profile belongs to a member of the year scenario."""
    simulation, _ = year_run
    used = {
        simulation.world.cover(member).profile.name
        for window in simulation.windows
        for member in window.member_ids
    }

    assert used == set(PROFILES)


# --- Reproducibility -----------------------------------------------------------------------


def test_a_run_is_reproducible() -> None:
    """Same scenario and seed, same record, entry by entry."""
    first = run_named("manual", seed=7).record
    second = run_named("manual", seed=7).record

    assert first.entries == second.entries
    assert first.timeline() == second.timeline()


# --- Restart ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "restart_times",
    [
        (time(3, 0),),
        (time(7, 0, 5),),
        (time(12, 0),),
        (time(20, 30),),
        (time(3, 0), time(7, 0, 5), time(12, 0), time(20, 30)),
    ],
)
def test_a_restart_yields_the_same_subsequent_commands(
    restart_times: tuple[time, ...],
) -> None:
    """Restart at night, in mid-movement, at noon and in the evening: same commands."""
    uninterrupted = run_named("workday", seed=3).record
    interrupted = with_restarts(3, restart_times)
    interrupted.run(interrupted.now + timedelta(days=1))
    record = interrupted.record

    assert interrupted.restarts == len(restart_times)
    assert record.of_kind(EntryKind.RESTART)
    assert _commands(record) == _commands(uninterrupted)
    assert_no_command_loop(record)


def _commands(record: Record) -> list[tuple[str, str | None, int | None]]:
    return [
        (
            entry.at.isoformat(timespec="milliseconds"),
            entry.member_id,
            None if entry.target is None else entry.target.value,
        )
        for entry in record.commands()
    ]


def test_a_restart_in_mid_movement_does_not_send_again() -> None:
    """The pending own command survives the restart: duplicate, not a new send."""
    simulation = with_restarts(3, (time(7, 0, 5),))
    simulation.run(simulation.now + timedelta(hours=8))
    record = simulation.record
    restart = record.of_kind(EntryKind.RESTART)[0]
    after = [
        entry
        for entry in record.decisions(WINDOW)
        if entry.at >= restart.at and entry.decision is not None
    ]

    assert after[0].decision is not None
    assert after[0].decision.gate is not None
    assert after[0].decision.gate.reason is ReasonCode.DUPLICATE_COMMAND
    assert len(record.commands(WINDOW)) == 1


def test_the_runner_wakes_a_window_up_at_the_deadline_of_the_gate() -> None:
    """The wake-up is the core's own deadline, report delay included, and nothing more.

    The cover settles short of the target, so the target is never reached,
    and its end stop takes longer than the travel time the user states, so
    its last report comes after the deadline: the recompute at the deadline
    is the runner's wake-up alone. Before it the gate reads the command as
    pending; at the deadline itself it does not any more (``time < end``).
    """
    start = local(MONDAY, time(6, 55))
    world = World(start, seed=1, script=calm_sources(start))
    world.add_cover(
        SimulatedCover(
            MEMBER,
            CoverProfile(
                "late_and_short",
                position_source=PROFILES["settles_off"].position_source,
                settle_offset_up=-6,
                end_stop_extra=timedelta(seconds=4),
                report_delay=REPORT_DELAY,
            ),
            position=0,
            available_since=start,
        )
    )
    simulation = Simulation(world)
    simulation.add_window(world.window(WINDOW, MEMBER), ARMED)
    simulation.run(local(MONDAY, time(7, 0, 1)))
    window = simulation.window(WINDOW)
    member = window.config.members[0]
    command = window.state.members[0].last_own_command
    assert command is not None
    deadline = member_expectation_end(member, command)

    assert member.capabilities.report_delay == REPORT_DELAY
    assert deadline == command.time + member.capabilities.travel_time_up + REPORT_DELAY
    assert deadline in window.wake_ups
    simulation.run(deadline + timedelta(seconds=30))
    reasons = {
        entry.at: entry.decision.gate.reason
        for entry in simulation.record.decisions(WINDOW)
        if entry.decision is not None
        and entry.decision.gate is not None
        and command.time < entry.at <= deadline
    }
    assert reasons[deadline] is not ReasonCode.DUPLICATE_COMMAND
    before = [reason for at, reason in reasons.items() if at < deadline]
    assert before
    assert all(reason is ReasonCode.DUPLICATE_COMMAND for reason in before)


# --- Dry-run and maintenance lock ----------------------------------------------------------


def test_dry_run_records_decisions_but_no_commands() -> None:
    """A window in dry-run: the record shows what it would have sent, nothing moves."""
    simulation = run_named("dry-run")
    record = simulation.record

    assert_no_commands(record, WINDOW)
    would_send = [
        entry
        for entry in record.decisions(WINDOW)
        if entry.decision is not None
        and entry.decision.gate is not None
        and entry.decision.gate.rule is GateRule.DRY_RUN
    ]
    assert would_send
    assert simulation.world.actuator.commands == []


def test_dry_run_next_to_another_controller_arms_no_dam_and_shows_the_outcome() -> None:
    """Situation 2a: the noon movement is logged, no dam; the storm reads dry_run."""
    simulation = run_named("dry-run")
    record = simulation.record
    window = simulation.window(WINDOW)
    noon = local(MONDAY, time(12, 0))
    storm = local(MONDAY, time(15, 0))

    # The other controller's movement was observed ...
    reports = [
        entry
        for entry in record.of_kind(EntryKind.REPORT, WINDOW)
        if noon <= entry.at < noon + timedelta(minutes=1)
    ]
    assert reports
    # ... and armed nothing.
    assert window.state.manual_override is None
    assert window.state.person_at_window is None
    assert window.state.owner.value == "unknown"
    # During the storm, while paused, the record shows "would have sent 0".
    during = [
        entry
        for entry in record.decisions(WINDOW)
        if storm <= entry.at < storm + timedelta(minutes=1)
        and entry.decision is not None
    ]
    assert during
    gate = during[0].decision.gate  # type: ignore[union-attr]
    assert gate is not None
    assert gate.dry_run
    assert gate.rule is GateRule.DRY_RUN
    assert gate.would_send[0].position == FULLY_CLOSED
    # Before the storm, paused, a comfort wish shows the rule that held it back.
    paused = [
        entry
        for entry in record.decisions(WINDOW)
        if local(MONDAY, time(14, 0)) <= entry.at < storm and entry.decision is not None
    ]
    assert paused
    held = paused[0].decision.gate  # type: ignore[union-attr]
    assert held is not None
    assert held.dry_run
    assert held.reason is ReasonCode.PAUSED
    assert_no_commands(record, WINDOW)


def test_maintenance_lock_records_decisions_but_no_commands() -> None:
    """Under the lock every decision reads maintenance_lock and nothing is sent."""
    simulation = run_named("maintenance-lock")
    record = simulation.record

    assert_no_commands(record, WINDOW)
    decisions = [e.decision for e in record.decisions(WINDOW) if e.decision is not None]
    assert decisions
    assert all(
        d.gate is not None and d.gate.reason is ReasonCode.MAINTENANCE_LOCK
        for d in decisions
    )


# --- The stub fire trigger in every operating mode ------------------------------------------


@pytest.mark.parametrize(
    "operating_mode",
    [OperatingMode.AUTOMATIC, OperatingMode.PROTECTION_ONLY, OperatingMode.OFF],
)
def test_fire_opens_in_every_operating_mode(operating_mode: OperatingMode) -> None:
    """Fire is sent at once in automatic, protection only and off."""
    simulation = fire_in_mode(operating_mode)
    simulation.run(simulation.now + timedelta(days=1))
    record = simulation.record
    alarm = local(MONDAY, time(10, 0))
    fire_commands = [
        entry
        for entry in record.commands(WINDOW)
        if entry.at >= alarm and entry.decision is None and entry.target == FULLY_OPEN
    ]

    assert fire_commands
    assert fire_commands[0].at == alarm
    assert fire_commands[0].wish_class is not None
    assert fire_commands[0].wish_class.value == "fire"
    assert (
        simulation.world.cover(MEMBER).real_position(simulation.now) == FULLY_OPEN.value
    )


def test_fire_under_the_maintenance_lock_moves_nothing() -> None:
    """Situation 1: the decision names fire as the winner; nothing is sent."""
    simulation = fire_in_mode(None)
    simulation.run(simulation.now + timedelta(days=1))
    record = simulation.record
    alarm = local(MONDAY, time(10, 0))
    at_alarm = [
        entry.decision
        for entry in record.decisions(WINDOW)
        if entry.at == alarm and entry.decision is not None
    ]

    assert_no_commands(record, WINDOW)
    assert at_alarm
    decision = at_alarm[0]
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.FIRE_ALARM
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.MAINTENANCE_LOCK


def test_fire_in_dry_run_records_would_open_and_moves_nothing() -> None:
    """Situation 2: the record shows "would open"; the cover stays where it is."""
    simulation = fire_in_dry_run()
    simulation.run(simulation.now + timedelta(days=1))
    record = simulation.record
    alarm = local(MONDAY, time(10, 0))
    at_alarm = [
        entry.decision
        for entry in record.decisions(WINDOW)
        if entry.at == alarm and entry.decision is not None
    ]

    assert_no_commands(record, WINDOW)
    decision = at_alarm[0]
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.DRY_RUN
    assert decision.gate.would_send[0].position == FULLY_OPEN
    assert simulation.world.cover(MEMBER).real_position(simulation.now) == HALF_OPEN


# --- Storm, manual movement, the blocked curtain ---------------------------------------------


def test_a_storm_never_sends_an_intermediate_position() -> None:
    """From the storm's start to its end every command targets an end position."""
    simulation = run_named("storm")
    record = simulation.record
    since = local(MONDAY, time(14, 0))
    until = local(MONDAY, time(16, 0))

    assert_no_intermediate_position(record, WINDOW, since, until)
    closing = [e for e in record.commands(WINDOW) if e.at == since]
    assert closing
    assert closing[0].target == FULLY_CLOSED
    assert closing[0].wish_class is not None
    assert closing[0].wish_class.value == "protection"
    # After the storm the schedule opens the window again, once, before the evening.
    evening = local(MONDAY, time(18, 0))
    reopened = [e for e in record.commands(WINDOW) if until <= e.at < evening]
    assert [e.target for e in reopened] == [FULLY_OPEN]


def test_manual_movements_are_observed_and_the_run_stays_clean() -> None:
    """One member moved by hand and stopped, another drops out: no loop, no crash."""
    simulation = run_named("manual")
    record = simulation.record
    left = "cover.example_left"
    right = "cover.example_right"
    stop = local(MONDAY, time(12, 0, 8))

    assert_no_command_loop(record)
    stopped = [
        e
        for e in record.of_kind(EntryKind.REPORT, WINDOW)
        if e.member_id == left and e.at > stop and e.observation is not None
    ]
    assert stopped
    position = stopped[0].observation.position  # type: ignore[union-attr]
    assert position is not None
    assert HALF < position.value < FULLY_OPEN.value
    gone = [
        e
        for e in record.of_kind(EntryKind.REPORT, WINDOW)
        if e.member_id == right
        and e.observation is not None
        and not e.observation.available
    ]
    assert len(gone) == 1
    # The tracker of a later block arms dams; today nothing does.
    assert simulation.window(WINDOW).state.manual_override is None


def test_a_calculated_position_reports_the_target_while_the_curtain_is_blocked() -> (
    None
):
    """The actuator counts to 100 and reports it; the curtain stopped at 60."""
    simulation = SCENARIOS["blocked"].build(1)
    noon = local(MONDAY, time(12, 0))
    simulation.run(noon)
    record = simulation.record
    cover = simulation.world.cover(MEMBER)
    reported = simulation.window(WINDOW).observations[MEMBER].position

    assert reported == FULLY_OPEN
    assert cover.real_position(noon) == 60  # noqa: PLR2004 - the profile blocks at 60
    assert cover.reported_position(noon) == FULLY_OPEN.value
    # The core reads "target reached" and does not fight the blocked curtain.
    # The actuator's last report says 100: from then on the core reads
    # "target reached", although the curtain stands at 60.
    arrived = local(MONDAY, time(7, 0)) + PROFILES["blocked"].travel_time_up
    after_arrival = [
        e.decision
        for e in record.decisions(WINDOW)
        if noon > e.at >= arrived and e.decision is not None
    ]
    assert after_arrival
    assert all(
        d.gate is not None and d.gate.reason is ReasonCode.TARGET_REACHED
        for d in after_arrival
    )
    assert_no_command_loop(record)


# --- The assertions catch a broken run ---------------------------------------------------------


def test_a_cover_that_settles_beyond_its_tolerance_is_sent_every_interval() -> None:
    """A member that settles 6 short of the target is sent again every ten minutes.

    Command verification and the backoff (N1) are not built yet, so this is
    what the core does today with such a cover: the target is never reached,
    the wish is not fresh, and motor protection lets the command through once
    per minimum interval. The assertion on the movements per day finds it,
    and its message shows the timeline around the third movement.
    """
    start = local(MONDAY, time(6, 55))
    world = World(start, seed=1, script=calm_sources(start))
    world.add_cover(
        SimulatedCover(
            MEMBER,
            CoverProfile(
                "settles_far_off",
                position_source=PROFILES["settles_off"].position_source,
                settle_offset_up=-6,
            ),
            position=0,
            available_since=start,
        )
    )
    simulation = Simulation(world)
    simulation.add_window(world.window(WINDOW, MEMBER), ARMED)
    simulation.run(start + timedelta(hours=1))

    with pytest.raises(ScenarioAssertionError) as caught:
        assert_at_most_movements_per_day(simulation.record, 2)
    message = str(caught.value)
    assert "more than 2" in message
    assert "timeline around that moment" in message
    assert "send 100" in message
    assert caught.value.moment.astimezone(simulation.record.zone).time() > time(7, 15)
    sends = simulation.record.sends(WINDOW)
    for earlier, later in itertools.pairwise(sends):
        assert later.at - earlier.at >= timedelta(minutes=10)


def test_every_named_scenario_runs() -> None:
    """The command line can run every name; the year is covered by its fixture."""
    for name in SCENARIOS:
        if name == "year":
            continue
        simulation = run_named(name)
        assert simulation.record.entries
        assert simulation.record.timeline()
