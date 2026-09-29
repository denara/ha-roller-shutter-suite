"""The named scenarios: how a world and its windows are built for each.

A scenario is a function that returns a :class:`Simulation` ready to run,
built from a seed. The tests under ``tests/core/test_sim_*.py`` run them and
assert on the record; the command-line entry point runs one and prints the
timeline. The profiles of the covers stand here too, one per behaviour of
section 8 of the architecture, so every scenario and every test names them
by their meaning.

The location is the made-up round point of :class:`Location`; the covers
carry neutral identifiers (``cover.example_...``). Nothing here is the
coordinate or the name of a real installation.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import Any, Final
from zoneinfo import ZoneInfo

from custom_components.roller_shutter_suite.core.model import (
    ControlLevel,
    Controls,
    OperatingMode,
    OverrideEndRule,
    Position,
    PositionSource,
    WindowConfig,
)

from .cover import CoverProfile, Reporting, SimulatedCover
from .runner import Simulation
from .sources import Script, Series
from .stubs import FIRE_SOURCE, STORM_SOURCE
from .world import Location, World

ZONE: Final = ZoneInfo(Location().time_zone)
MONDAY: Final = date(2026, 9, 21)
SATURDAY: Final = date(2026, 9, 26)
YEAR_START: Final = date(2026, 1, 1)

ARMED: Final = Controls(dry_run=False)
DRY_RUN: Final = Controls(dry_run=True)
LOCKED: Final = Controls(
    dry_run=False, window_level=ControlLevel(maintenance_lock=True)
)
PAUSED: Final = Controls(dry_run=False, window_level=ControlLevel(paused=True))


def mode(operating_mode: OperatingMode) -> Controls:
    """Return armed controls in one operating mode, set on the window level."""
    return Controls(dry_run=False, window_level=ControlLevel(mode=operating_mode))


def local(day: date, at: time) -> datetime:
    """Return a local time of the zone of the scenarios."""
    return datetime.combine(day, at, tzinfo=ZONE)


# --- The behaviour profiles ----------------------------------------------------------

PROFILES: Final[Mapping[str, CoverProfile]] = {
    "live": CoverProfile("live"),
    "end_only": CoverProfile(
        "end_only",
        reporting=Reporting.END_ONLY,
        travel_time_up=timedelta(seconds=24),
        travel_time_down=timedelta(seconds=22),
    ),
    "polled": CoverProfile(
        "polled",
        reporting=Reporting.GRID,
        transit_states=False,
        grid_interval=timedelta(seconds=60),
        travel_time_up=timedelta(seconds=30),
        travel_time_down=timedelta(seconds=27),
    ),
    "settles_off": CoverProfile(
        "settles_off",
        position_source=PositionSource.MEASURED,
        settle_offset_up=-2,
        settle_offset_down=1,
        start_offset_percent=3,
        end_stop_extra=timedelta(seconds=3),
    ),
    "no_stop": CoverProfile("no_stop", supports_stop=False),
    "no_position": CoverProfile(
        "no_position", reports_position=False, supports_set_position=False
    ),
    "late_report": CoverProfile(
        "late_report",
        report_delay=timedelta(seconds=8),
        position_before_rest=True,
        repeat_last_write=True,
    ),
    "chatty": CoverProfile(
        "chatty",
        rewrite_unchanged_every=timedelta(minutes=20),
        repeat_last_write=True,
        position_before_rest=True,
    ),
    "no_transit": CoverProfile("no_transit", transit_states=False),
    "blocked": CoverProfile(
        "blocked",
        position_source=PositionSource.CALCULATED,
        blocked_at=60,
        travel_time_up=timedelta(seconds=22),
    ),
}
"""One profile per behaviour; the year scenario uses all of them."""


def cover(
    name: str, profile: str, *, position: int = 100, since: datetime
) -> SimulatedCover:
    """Return a cover with a neutral identifier and one of the profiles."""
    return SimulatedCover(
        f"cover.example_{name}",
        PROFILES[profile],
        position=position,
        available_since=since,
    )


def calm_sources(since: datetime) -> Script:
    """Return the sources of a calm world: no fire, no storm."""
    return Script(
        {
            FIRE_SOURCE: Series.constant(False, since),
            STORM_SOURCE: Series.constant(False, since),
        }
    )


# --- Houses ---------------------------------------------------------------------------


def one_window(  # noqa: PLR0913 - every part of a scenario can be varied
    seed: int,
    start: datetime,
    *,
    profile: str = "live",
    controls: Controls = ARMED,
    script: Script | None = None,
    position: int = 0,
    **fields: Any,
) -> Simulation:
    """Return a simulation with one window over one cover, closed by default.

    Every day scenario starts at midnight, when the schedule wants the night
    position; a cover that starts closed does not move at the start.
    """
    world = World(start, seed=seed, script=script or calm_sources(start))
    world.add_cover(cover("window", profile, position=position, since=start))
    simulation = Simulation(world)
    simulation.add_window(
        world.window("window_example", "cover.example_window", **fields), controls
    )
    return simulation


def ten_windows(
    seed: int, start: datetime, *, script: Script | None = None
) -> Simulation:
    """Return the house of the year scenario: ten windows, every profile once.

    Eight windows have one member each, one per profile; the ninth has two
    members with different travel times; the tenth has three members, one
    of them the polled platform, which is where a polled platform reports on
    its grid while several members move at once.
    """
    world = World(start, seed=seed, script=script or calm_sources(start))
    simulation = Simulation(world)
    # The scenario starts at midnight, so the covers stand at the night position.
    closed = 0
    singles = (
        "live",
        "end_only",
        "polled",
        "settles_off",
        "no_stop",
        "no_position",
        "late_report",
        "blocked",
    )
    for index, profile in enumerate(singles, start=1):
        world.add_cover(cover(f"single_{index}", profile, position=closed, since=start))
        simulation.add_window(
            world.window(f"window_{index}", f"cover.example_single_{index}"), ARMED
        )
    world.add_cover(cover("pair_left", "live", position=closed, since=start))
    world.add_cover(cover("pair_right", "end_only", position=closed, since=start))
    simulation.add_window(
        world.window("window_9", "cover.example_pair_left", "cover.example_pair_right"),
        ARMED,
    )
    world.add_cover(cover("trio_a", "no_transit", position=closed, since=start))
    world.add_cover(cover("trio_b", "polled", position=closed, since=start))
    world.add_cover(cover("trio_c", "chatty", position=closed, since=start))
    simulation.add_window(
        world.window(
            "window_10",
            "cover.example_trio_a",
            "cover.example_trio_b",
            "cover.example_trio_c",
        ),
        ARMED,
    )
    return simulation


# --- The scenarios --------------------------------------------------------------------


def workday(seed: int = 1) -> Simulation:
    """Return a Monday with the schedule only: one window, midnight to midnight."""
    return one_window(seed, local(MONDAY, time(0, 0)))


def weekend(seed: int = 1) -> Simulation:
    """Return a Saturday with the schedule only: the later morning of a free day."""
    return one_window(seed, local(SATURDAY, time(0, 0)))


HAND_MOVEMENT_AT: Final = time(12, 0)
"""When the person of the year scenario moves every window by hand, every day."""
HAND_TARGET: Final = 70


def _every_day_by_hand(simulation: Simulation) -> None:
    """Move every window by hand, and do it again tomorrow."""
    for window in simulation.windows:
        simulation.move_by_hand(window.window_id, HAND_TARGET)
    tomorrow = simulation.now.date() + timedelta(days=1)
    simulation.at(
        local(tomorrow, HAND_MOVEMENT_AT),
        "a person moves every window by hand",
        _every_day_by_hand,
    )


def year(seed: int = 1) -> Simulation:
    """Return a full year for ten windows, across both clock changes.

    The schedule moves the windows, and at noon every day a person moves
    every window by hand to 70: the manual override holds it until the
    evening, when the schedule closes it (the default end rule).
    """
    simulation = ten_windows(seed, local(YEAR_START, time(0, 0)))
    simulation.at(
        local(YEAR_START, HAND_MOVEMENT_AT),
        "a person moves every window by hand",
        _every_day_by_hand,
    )
    return simulation


def dry_run_next_to_another_controller(seed: int = 1) -> Simulation:
    """Return a window in dry-run while a scripted controller moves the same cover.

    The other controller lowers the window at noon; at 15:00 a storm begins
    while the window is paused. Situation 2a of the architecture.
    """
    start = local(MONDAY, time(0, 0))
    script = calm_sources(start).with_series(
        STORM_SOURCE,
        Series.of(
            (start, False),
            (local(MONDAY, time(15, 0)), True),
            (local(MONDAY, time(16, 30)), False),
        ),
    )
    simulation = one_window(seed, start, controls=DRY_RUN, script=script)
    simulation.at(
        local(MONDAY, time(12, 0)),
        "another controller lowers the window to 40",
        lambda sim: sim.other_controller_moves("window_example", 40),
    )
    simulation.at(
        local(MONDAY, time(14, 0)),
        "the window is paused",
        lambda sim: sim.set_controls(
            "window_example",
            Controls(dry_run=True, window_level=ControlLevel(paused=True)),
        ),
    )
    return simulation


def fire_in_mode(operating_mode: OperatingMode | None, seed: int = 1) -> Simulation:
    """Return the stub fire trigger at 10:00 on a Monday, in one operating mode.

    ``None`` stands for the maintenance lock, which is not a mode but the
    fourth row of the table of section 2.5.
    """
    start = local(MONDAY, time(0, 0))
    script = calm_sources(start).with_series(
        FIRE_SOURCE, Series.of((start, False), (local(MONDAY, time(10, 0)), True))
    )
    controls = LOCKED if operating_mode is None else mode(operating_mode)
    return one_window(
        seed,
        start,
        controls=controls,
        script=script,
        schedule_morning_position=HALF_OPEN,
    )


HALF_OPEN: Final = Position(30)
"""The morning position of the fire scenarios, so the fire has somewhere to go."""


def fire_in_dry_run(seed: int = 1) -> Simulation:
    """Return the stub fire trigger at 10:00 for a window in dry-run: no movement."""
    start = local(MONDAY, time(0, 0))
    script = calm_sources(start).with_series(
        FIRE_SOURCE, Series.of((start, False), (local(MONDAY, time(10, 0)), True))
    )
    return one_window(
        seed,
        start,
        controls=DRY_RUN,
        script=script,
        position=HALF_OPEN.value,
        schedule_morning_position=HALF_OPEN,
    )


def maintenance_lock(seed: int = 1) -> Simulation:
    """Return a locked window over a whole Monday: decisions, no commands."""
    return one_window(
        seed, local(MONDAY, time(0, 0)), controls=LOCKED, position=HALF_OPEN.value
    )


def storm(seed: int = 1) -> Simulation:
    """Return a storm from 14:00 to 16:00 on a Monday: never an intermediate position."""
    start = local(MONDAY, time(0, 0))
    script = calm_sources(start).with_series(
        STORM_SOURCE,
        Series.of(
            (start, False),
            (local(MONDAY, time(14, 0)), True),
            (local(MONDAY, time(16, 0)), False),
        ),
    )
    return one_window(seed, start, script=script)


def manual_movement(seed: int = 1) -> Simulation:
    """Return a two-member window whose left member a person moves and stops at noon.

    The arbiter has no tracker yet (block C06), so nothing arms a dam; the
    scenario shows the observation and the decisions around it.
    """
    start = local(MONDAY, time(0, 0))
    world = World(start, seed=seed, script=calm_sources(start))
    world.add_cover(cover("left", "live", since=start))
    world.add_cover(cover("right", "settles_off", since=start))
    simulation = Simulation(world)
    simulation.add_window(
        world.window("window_example", "cover.example_left", "cover.example_right"),
        ARMED,
    )
    simulation.at(
        local(MONDAY, time(12, 0)),
        "a person lowers the left member to 50",
        lambda sim: sim.move_by_hand(
            "window_example", 50, member_id="cover.example_left"
        ),
    )
    simulation.at(
        local(MONDAY, time(12, 0, 8)),
        "the person stops it in mid-travel",
        lambda sim: sim.stop_by_hand("window_example", "cover.example_left"),
    )
    simulation.at(
        local(MONDAY, time(13, 0)),
        "the right member loses its connection for two minutes",
        lambda sim: sim.dropout(
            "window_example", "cover.example_right", timedelta(minutes=2)
        ),
    )
    return simulation


def blocked_curtain(seed: int = 1) -> Simulation:
    """Return a calculated position that reports the target while the curtain is blocked."""
    return one_window(seed, local(MONDAY, time(0, 0)), profile="blocked", position=0)


def chatty_cover(seed: int = 1) -> Simulation:
    """Return a cover that repeats its writes and rewrites an unchanged state all day."""
    return one_window(seed, local(MONDAY, time(0, 0)), profile="chatty")


def with_restarts(seed: int, restart_times: tuple[time, ...]) -> Simulation:
    """Return the workday scenario with a restart at every listed local time."""
    simulation = workday(seed)
    for at in restart_times:
        simulation.at(local(MONDAY, at), "restart", lambda sim: sim.restart())
    return simulation


# --- Movement tracking and the dams (block C06) ---------------------------------------

TRACKING_CASES: Final = (
    "own",
    "hand",
    "stop",
    "dropout_same",
    "dropout_moved",
    "reversal",
)
"""What happens to a cover after the morning opening of the tracking cases."""

MORNING: Final = local(MONDAY, time(7, 0))
"""The morning opening of the tracking cases: an own movement from 0 to 100."""

CASE_AT: Final = local(MONDAY, time(9, 0))
"""When the hand movement and the dropouts of the tracking cases happen."""

WINDOW_ID: Final = "window_example"
COVER_ID: Final = "cover.example_window"
"""The window and the cover of ``one_window``."""


def profile_case(profile: str, case: str, seed: int = 1) -> Simulation:
    """Return one window over a cover of one profile, closed until the morning.

    The schedule opens it at 07:00, an own movement from 0 to 100. Then:

    - ``own``: nothing more;
    - ``hand``: at 09:00 a person lowers it to 40;
    - ``stop``: a person stops the morning opening halfway;
    - ``dropout_same``: at 09:00 the cover is away for three minutes and
      returns as it was;
    - ``dropout_moved``: at 09:00 the cover is away for five minutes, and a
      person lowers it to 40 meanwhile;
    - ``reversal``: four seconds into the morning opening a person sends it
      down again.
    """
    if case not in TRACKING_CASES:
        raise ValueError(f"no tracking case {case!r}")
    start = local(MONDAY, time(6, 50))
    simulation = one_window(seed, start, profile=profile, position=0)
    travel = PROFILES[profile].travel_time_up
    if case == "hand":
        simulation.at(
            CASE_AT,
            "a person lowers the window to 40",
            lambda sim: sim.move_by_hand(WINDOW_ID, 40),
        )
    elif case == "stop":
        simulation.at(
            MORNING + travel / 2,
            "a person stops the morning opening",
            lambda sim: sim.stop_by_hand(WINDOW_ID, COVER_ID),
        )
    elif case == "dropout_same":
        simulation.at(
            CASE_AT,
            "the cover is away for three minutes",
            lambda sim: sim.dropout(WINDOW_ID, COVER_ID, timedelta(minutes=3)),
        )
    elif case == "dropout_moved":
        simulation.at(
            CASE_AT,
            "the cover is away for five minutes",
            lambda sim: sim.dropout(WINDOW_ID, COVER_ID, timedelta(minutes=5)),
        )
        simulation.at(
            CASE_AT + timedelta(minutes=1),
            "meanwhile a person lowers it to 40",
            lambda sim: sim.move_by_hand(WINDOW_ID, 40),
        )
    elif case == "reversal":
        simulation.at(
            MORNING + timedelta(seconds=4),
            "a person sends the opening cover down again",
            lambda sim: sim.move_by_hand(WINDOW_ID, 0),
        )
    return simulation


def polled_four(seed: int = 1) -> Simulation:
    """Return four members of a polled platform, commanded at once (spike S1).

    The platform reports on a grid of a minute, with no transit state and no
    report at the real end of a movement. The morning opens all four at
    07:00 and the evening closes them.
    """
    start = local(MONDAY, time(6, 50))
    world = World(start, seed=seed, script=calm_sources(start))
    names = tuple(f"polled_{index}" for index in range(1, 5))
    for name in names:
        world.add_cover(cover(name, "polled", position=0, since=start))
    simulation = Simulation(world)
    simulation.add_window(
        world.window(WINDOW_ID, *(f"cover.example_{name}" for name in names)), ARMED
    )
    return simulation


def pair_one_by_hand(seed: int = 1) -> Simulation:
    """Return two members side by side; at 10:00 a person lowers the left one to 40.

    Decision 8: the override applies to the whole window; the right member
    stays where it is; at the evening boundary the override ends and both
    are closed.
    """
    start = local(MONDAY, time(9, 0))
    world = World(start, seed=seed, script=calm_sources(start))
    world.add_cover(cover("left", "live", since=start))
    world.add_cover(cover("right", "settles_off", since=start))
    simulation = Simulation(world)
    simulation.add_window(
        world.window(WINDOW_ID, "cover.example_left", "cover.example_right"), ARMED
    )
    simulation.at(
        local(MONDAY, time(10, 0)),
        "a person lowers the left member to 40",
        lambda sim: sim.move_by_hand(WINDOW_ID, 40, member_id="cover.example_left"),
    )
    return simulation


PRESENCE_SOURCE: Final = "presence"
"""The presence source of the room of the override scenarios: on means occupied."""

OVERRIDE_ENDS: Final = (
    "fixed_minutes",
    "next_part_of_day",
    "room_empty",
    "resume",
    "sleep_mode",
)


def override_end(how: str, seed: int = 1) -> Simulation:
    """Return a window a person lowers to 40 at 10:00, and the way its override ends.

    - ``fixed_minutes``: after 30 minutes;
    - ``next_part_of_day``: at the evening boundary (the default rule);
    - ``room_empty``: the room is occupied until 11:00, empty from then on,
      and the override ends 30 minutes later;
    - ``resume``: the "resume automation" button at 11:00;
    - ``sleep_mode``: sleep mode is switched on at 11:00.
    """
    if how not in OVERRIDE_ENDS:
        raise ValueError(f"no end of an override {how!r}")
    start = local(MONDAY, time(9, 0))
    script = calm_sources(start).with_series(
        PRESENCE_SOURCE,
        Series.of((start, True), (local(MONDAY, time(11, 0)), False)),
    )
    fields: dict[str, Any] = {}
    if how == "fixed_minutes":
        fields = {
            "override_end_rule": OverrideEndRule.FIXED_MINUTES,
            "override_minutes": timedelta(minutes=30),
        }
    elif how == "room_empty":
        fields = {
            "override_end_rule": OverrideEndRule.ROOM_EMPTY,
            "override_presence_source": PRESENCE_SOURCE,
            "override_room_empty_after": timedelta(minutes=30),
        }
    simulation = one_window(seed, start, script=script, position=100, **fields)
    simulation.at(
        local(MONDAY, time(10, 0)),
        "a person lowers the window to 40",
        lambda sim: sim.move_by_hand(WINDOW_ID, 40),
    )
    if how == "resume":
        simulation.at(
            local(MONDAY, time(11, 0)),
            "resume automation",
            lambda sim: sim.resume(WINDOW_ID),
        )
    elif how == "sleep_mode":
        simulation.at(
            local(MONDAY, time(11, 0)),
            "sleep mode is switched on",
            lambda sim: sim.sleep_mode_switched_on(WINDOW_ID),
        )
    return simulation


def person_at_window(storm_until: time, seed: int = 1) -> Simulation:
    """Return a storm from 14:00, and a person who opens the window to 60 at 14:10.

    The stub protection layer closes the window at the storm. The person's
    movement arms the person-at-the-window dam for 15 minutes. With the storm
    still active when the dam ends, protection closes the window again; with
    the storm over by then, the dam turns into a manual override with the
    person's position, which holds the schedule's day position back until
    the evening.
    """
    start = local(MONDAY, time(13, 0))
    script = calm_sources(start).with_series(
        STORM_SOURCE,
        Series.of(
            (start, False),
            (local(MONDAY, time(14, 0)), True),
            (local(MONDAY, storm_until), False),
        ),
    )
    simulation = one_window(seed, start, script=script, position=100)
    simulation.at(
        local(MONDAY, time(14, 10)),
        "a person opens the window to 60 during the storm",
        lambda sim: sim.move_by_hand(WINDOW_ID, PERSON_CHOOSES),
    )
    return simulation


PERSON_CHOOSES: Final = 60
"""Where the person of the storm scenario opens the window to."""


OTHER_CONTROLLER: Final = (
    (time(7, 30), 100),
    (time(12, 0), 40),
    (time(15, 0), 70),
    (time(19, 45), 0),
)
"""When the second controller of the dry-run day moves the window, and where."""


def dry_run_whole_day(seed: int = 1) -> Simulation:
    """Return a window in dry-run for a whole day next to a scripted second controller.

    The other controller moves the window four times; the integration never
    commands it. Every movement is foreign: no dam, the owner stays unknown,
    one ``external_movement_observed`` per movement.
    """
    start = local(MONDAY, time(0, 0))
    simulation = one_window(seed, start, controls=DRY_RUN)
    for at, target in OTHER_CONTROLLER:
        simulation.at(
            local(MONDAY, at),
            f"the other controller moves the window to {target}",
            partial(_other_moves, target=target),
        )
    return simulation


def _other_moves(sim: Simulation, *, target: int) -> None:
    sim.other_controller_moves(WINDOW_ID, target)


RESTART_POINTS: Final = {
    "movement": time(10, 0, 5),
    "settling": time(10, 0, 15),
    "dam": time(12, 0),
}
"""A restart during a hand movement, during its settle time, and with the dam armed."""


def hand_movement_with_restart(restart: str | None, seed: int = 1) -> Simulation:
    """Return a window a person lowers to 40 at 10:00, with a restart at one point.

    The live cover travels from 100 to 40 in about 11 seconds and rests; the
    settle time ends two seconds later. ``None``: no restart, the reference.
    """
    start = local(MONDAY, time(9, 0))
    simulation = one_window(seed, start, position=100)
    simulation.at(
        local(MONDAY, time(10, 0)),
        "a person lowers the window to 40",
        lambda sim: sim.move_by_hand(WINDOW_ID, 40),
    )
    if restart is not None:
        simulation.at(
            local(MONDAY, RESTART_POINTS[restart]),
            "restart",
            lambda sim: sim.restart(),
        )
    return simulation


def own_movement_with_restart(restart: time | None, seed: int = 1) -> Simulation:
    """Return the morning opening of a live cover, with a restart at one instant.

    The opening runs from 07:00 for 20 seconds; it comes to rest at 07:00:20
    and is judged two seconds later.
    """
    simulation = one_window(seed, local(MONDAY, time(6, 50)), position=0)
    if restart is not None:
        simulation.at(local(MONDAY, restart), "restart", lambda sim: sim.restart())
    return simulation


@dataclass(frozen=True, slots=True)
class Scenario:
    """A named scenario: what it shows, how it is built, how long it runs."""

    description: str
    build: Callable[[int], Simulation]
    length: timedelta = timedelta(days=1)


RESTART_TIMES: Final = (time(3, 0), time(7, 0, 5), time(12, 0), time(20, 30))
"""At night, in mid-movement of the morning opening, at noon, in the evening."""

SCENARIOS: Final[Mapping[str, Scenario]] = {
    "workday": Scenario("a Monday with the schedule only, one window", workday),
    "weekend": Scenario("a Saturday: the later morning of a free day", weekend),
    "year": Scenario(
        "a full year for ten windows, across both clock changes",
        year,
        timedelta(days=365),
    ),
    "dry-run": Scenario(
        "a window in dry-run next to a scripted second controller, then a storm",
        dry_run_next_to_another_controller,
    ),
    "fire-automatic": Scenario(
        "the stub fire trigger in the mode automatic",
        partial(fire_in_mode, OperatingMode.AUTOMATIC),
    ),
    "fire-protection-only": Scenario(
        "the stub fire trigger in the mode protection only",
        partial(fire_in_mode, OperatingMode.PROTECTION_ONLY),
    ),
    "fire-off": Scenario(
        "the stub fire trigger in the mode off",
        partial(fire_in_mode, OperatingMode.OFF),
    ),
    "fire-locked": Scenario(
        "the stub fire trigger under the maintenance lock", partial(fire_in_mode, None)
    ),
    "fire-dry-run": Scenario("the stub fire trigger in dry-run", fire_in_dry_run),
    "maintenance-lock": Scenario("a locked window over a whole day", maintenance_lock),
    "storm": Scenario(
        "a storm in the afternoon: never an intermediate position", storm
    ),
    "manual": Scenario(
        "a member moved and stopped by hand, another with a dropout", manual_movement
    ),
    "blocked": Scenario(
        "a calculated position that reports the target while the curtain is blocked",
        blocked_curtain,
    ),
    "chatty": Scenario(
        "a cover that repeats and rewrites its state writes", chatty_cover
    ),
    "restarts": Scenario(
        "the workday with a restart at four points of the day",
        partial(with_restarts, restart_times=RESTART_TIMES),
    ),
    "hand": Scenario(
        "a live cover lowered by hand at 09:00: the manual override",
        partial(profile_case, "live", "hand"),
        timedelta(hours=16),
    ),
    "stop": Scenario(
        "a person stops the morning opening halfway",
        partial(profile_case, "live", "stop"),
        timedelta(hours=5),
    ),
    "reversal": Scenario(
        "a person sends the opening cover down again: external at once",
        partial(profile_case, "live", "reversal"),
        timedelta(hours=5),
    ),
    "dropout-moved": Scenario(
        "a cover moved by hand while it was away: moved during downtime",
        partial(profile_case, "live", "dropout_moved"),
        timedelta(hours=5),
    ),
    "polled-four": Scenario(
        "four members of a polled platform, commanded at once",
        polled_four,
        timedelta(hours=16),
    ),
    "pair-one-by-hand": Scenario(
        "one of two members lowered by hand: the override for the whole window",
        pair_one_by_hand,
        timedelta(hours=15),
    ),
    "override-room-empty": Scenario(
        "an override that ends 30 minutes after the room became empty",
        partial(override_end, "room_empty"),
        timedelta(hours=5),
    ),
    "person-at-window": Scenario(
        "a person opens the window during a storm; the storm lasts beyond the dam",
        partial(person_at_window, time(15, 0)),
        timedelta(hours=3),
    ),
    "dry-run-day": Scenario(
        "a window in dry-run next to a second controller for a whole day",
        dry_run_whole_day,
    ),
}
"""The scenarios by the name the command line takes."""


def run_named(name: str, seed: int = 1) -> Simulation:
    """Build and run a named scenario to its natural end; return it with its record."""
    scenario = SCENARIOS[name]
    simulation = scenario.build(seed)
    simulation.run(simulation.now + scenario.length)
    return simulation


def configs(simulation: Simulation) -> list[WindowConfig]:
    """Return the configurations of the windows of a simulation."""
    return [window.config for window in simulation.windows]
