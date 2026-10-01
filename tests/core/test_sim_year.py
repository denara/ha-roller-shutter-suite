"""The year scenario of the time-lapse simulation: ten windows for a year.

The year is run once for this file (a fixture with the scope of the module),
because it takes seconds; every test here judges the same run. Its time is
measured on the wall clock and has a limit of a minute. Under coverage the year
runs slower, so CI runs this file in a step of its own, without coverage, and
the run of ``tests/core`` with coverage leaves it out. The marker ``year``
makes both selections: ``pytest tests/core -m year`` runs the year,
``pytest tests/core -m "not year"`` everything else.

Every test that reads the year belongs in this file: the marker applies to all
of them, and the fixture is not visible anywhere else.
"""

import os
import time as wall_clock
from datetime import time, timedelta
from pathlib import Path
from typing import Final

import pytest

from custom_components.roller_shutter_suite.core.model import FULLY_CLOSED, FULLY_OPEN
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.sim.assertions import (
    assert_at_most_movements_per_day,
    assert_dams_follow_foreign_movements,
    assert_min_interval,
    assert_no_command_loop,
    assert_schedule_commands_inside_clamps,
    movements_per_day,
)
from tests.sim.runner import Simulation
from tests.sim.scenarios import PROFILES, YEAR_START, configs, local, year

pytestmark = pytest.mark.year

A_YEAR: Final = timedelta(days=365)
A_MINUTE: Final = 60.0
"""Seconds; the acceptance criterion says well under a minute."""
TWICE_A_DAY: Final = 2
TEN_WINDOWS: Final = 10
DAYS_OF_THE_YEAR: Final = 365
STEP_SUMMARY: Final = "GITHUB_STEP_SUMMARY"
"""The variable through which GitHub names the summary page of a workflow step."""


@pytest.fixture(scope="module")
def year_run() -> tuple[Simulation, float]:
    """Run the year for ten windows once; return the simulation and the seconds."""
    simulation = year(seed=1)
    started = wall_clock.perf_counter()
    simulation.run(simulation.now + A_YEAR)
    return simulation, wall_clock.perf_counter() - started


def _add_to_the_summary_page(measurement: str) -> None:
    """Append the measurement to the summary page when a GitHub workflow runs this.

    Every process of a workflow step may append Markdown to the file that the
    variable names. Outside GitHub the variable is not set and nothing is
    written.
    """
    page = os.environ.get(STEP_SUMMARY)
    if not page:
        return
    with Path(page).open("a", encoding="utf-8") as summary:
        summary.write(
            "## The year of the time-lapse simulation\n\n"
            f"{measurement}; the limit is {A_MINUTE:.0f} s.\n"
        )


def test_a_year_for_ten_windows_runs_well_under_a_minute(
    year_run: tuple[Simulation, float],
) -> None:
    """The year is measured and reported; the test fails only at a full minute.

    "Well under a minute" is judged from the reported time and stated in the
    pull request. The time is printed (``pytest -rP`` or ``pytest -s`` shows
    it) and, in a GitHub workflow, added to the summary page of the run before
    it is judged, so a year over the limit shows its time there too. The bound
    here is the minute itself, so a loaded machine does not make a wall-clock
    test flaky, while a year that really takes a minute still fails.
    """
    simulation, seconds = year_run
    measurement = f"a year for ten windows took {seconds:.1f} s"
    print(measurement)  # noqa: T201 - the measurement
    _add_to_the_summary_page(measurement)

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


def test_in_the_year_no_own_movement_ever_arms_a_dam(
    year_run: tuple[Simulation, float],
) -> None:
    """Every detection follows the person's movement at noon; nothing else raises one."""
    simulation, _ = year_run
    record = simulation.record

    assert_dams_follow_foreign_movements(record)
    codes = {entry.event.code for entry in record.events() if entry.event is not None}
    assert codes == {
        ReasonCode.MANUAL_DETECTED,
        ReasonCode.MANUAL_DETECTED_MEMBER,
        ReasonCode.OVERRIDE_STARTED,
        ReasonCode.OVERRIDE_ENDED,
    }


def test_in_the_year_every_hand_movement_arms_the_window_once_until_the_evening(
    year_run: tuple[Simulation, float],
) -> None:
    """One override per window and day, ended at the evening boundary.

    The window without position feedback has no manual detection (section
    8.1); the windows with several members are armed once per movement of
    the window (decision 8).
    """
    simulation, _ = year_run
    record = simulation.record
    for window in simulation.windows:
        started = record.events(window.window_id, ReasonCode.OVERRIDE_STARTED)
        ended = record.events(window.window_id, ReasonCode.OVERRIDE_ENDED)
        if window.window_id == "window_6":
            assert started == []
            continue
        assert len(started) == DAYS_OF_THE_YEAR
        assert len(ended) == DAYS_OF_THE_YEAR
        for start, end in zip(started, ended, strict=True):
            assert record.local_date(start) == record.local_date(end)
            assert start.at.astimezone(record.zone).time() < time(12, 5)
            evening = [
                entry
                for entry in record.sends(window.window_id)
                if entry.at == end.at
                and entry.decision is not None
                and entry.decision.winning_wish is not None
                and entry.decision.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT
            ]
            assert evening, end.at


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
