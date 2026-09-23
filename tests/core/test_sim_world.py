"""The small ports of the synthetic world: clock, sources, storage, actuator."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.roller_shutter_suite.core.model import (
    Position,
    SourceState,
    WindowState,
)
from tests.sim.clock import SimClock
from tests.sim.cover import CoverProfile, SimulatedCover
from tests.sim.sources import UNAVAILABLE, UNKNOWN, Script, Series
from tests.sim.storage import MemoryStorage
from tests.sim.world import Location, World

ZONE = ZoneInfo("Europe/Berlin")
TWO_IN_THE_MORNING = 2
START = datetime(2026, 6, 1, 12, 0, tzinfo=ZONE)
TEMPERATURE = 21.5
SEED = 5
CLOCKS_BACK = datetime(2026, 10, 24, 23, 30, tzinfo=UTC)
"""01:30 on the clock of the zone, an hour and a half before the autumn change."""


# --- Clock ---------------------------------------------------------------------------------


def test_the_clock_moves_forward_only_and_keeps_its_zone() -> None:
    """The zone of the start is the local zone; instants are compared, not wall clocks."""
    clock = SimClock(CLOCKS_BACK.astimezone(ZONE))

    assert clock.zone is ZONE
    clock.advance_to(CLOCKS_BACK + timedelta(hours=1))
    assert clock.now().utcoffset() == timedelta(hours=2)
    assert clock.now().hour == TWO_IN_THE_MORNING
    # Across the autumn change the wall clock reads 02:30 twice; the instant
    # still moves forward, and the clock does not refuse it.
    clock.advance_to(CLOCKS_BACK + timedelta(hours=2))
    assert clock.now().utcoffset() == timedelta(hours=1)
    assert clock.now().hour == TWO_IN_THE_MORNING
    with pytest.raises(ValueError, match="never goes back"):
        clock.advance_to(CLOCKS_BACK)
    with pytest.raises(ValueError, match="timezone-aware"):
        clock.advance_to(datetime(2026, 10, 26))  # noqa: DTZ001
    with pytest.raises(ValueError, match="timezone-aware"):
        SimClock(datetime(2026, 10, 26))  # noqa: DTZ001


# --- Sources -------------------------------------------------------------------------------


def test_a_series_is_unavailable_before_its_first_step() -> None:
    """Nothing turns a source that has not reported into a value."""
    series = Series.of((START, 21.5), (START + timedelta(hours=1), UNKNOWN))

    assert series.value_at(START - timedelta(seconds=1)) is UNAVAILABLE
    assert series.value_at(START) == TEMPERATURE
    assert series.value_at(START + timedelta(minutes=59)) == TEMPERATURE
    assert series.value_at(START + timedelta(hours=1)) is UNKNOWN
    assert series.next_change_after(START) == START + timedelta(hours=1)
    assert series.next_change_after(START + timedelta(hours=1)) is None


def test_a_script_turns_steps_into_source_values() -> None:
    """Values, unknown and unavailable arrive as the three states of the core."""
    script = Script(
        {
            "temperature": Series.of(
                (START, 21.5), (START + timedelta(hours=1), UNAVAILABLE)
            ),
            "rain": Series.constant(True, START + timedelta(minutes=30)),
            "contact": Series.of(
                (START, "open"), (START + timedelta(minutes=10), UNKNOWN)
            ),
        }
    )
    values = script.values_at(START + timedelta(minutes=15))

    assert values["temperature"].value == TEMPERATURE
    assert values["rain"].state is SourceState.UNAVAILABLE
    assert values["contact"].state is SourceState.UNKNOWN
    assert script.values_at(START + timedelta(hours=1))["temperature"].state is (
        SourceState.UNAVAILABLE
    )
    assert script.next_change_after(START) == START + timedelta(minutes=10)
    assert set(script.keys()) == {"temperature", "rain", "contact"}
    assert (
        script.with_series("wind", Series.constant(3, START)).next_change_after(
            START + timedelta(hours=2)
        )
        is None
    )
    assert Script.empty().values_at(START) == {}


def test_a_generated_series_keeps_only_the_changes() -> None:
    """A slowly changing curve wakes nobody up for an unchanged value."""
    series = Series.generated(
        START,
        START + timedelta(hours=3),
        timedelta(minutes=30),
        lambda at: 20 if at < START + timedelta(hours=1) else 25,
    )

    assert [step.value for step in series.steps] == [20, 25]
    assert series.steps[1].at == START + timedelta(hours=1)
    with pytest.raises(ValueError, match="longer than zero"):
        Series.generated(START, START, timedelta(0), lambda _: 1)


def test_a_series_refuses_two_steps_at_one_instant_and_naive_times() -> None:
    """One value per instant; every instant aware."""
    with pytest.raises(ValueError, match="one value per instant"):
        Series.of((START, 1), (START, 2))
    with pytest.raises(ValueError, match="timezone-aware"):
        Series.of((datetime(2026, 1, 1), 1))  # noqa: DTZ001


# --- Storage -------------------------------------------------------------------------------


def test_the_storage_round_trips_through_json() -> None:
    """A saved state comes back equal; the seed is kept; a deleted window is gone."""
    storage = MemoryStorage()
    state = WindowState(fire_unacknowledged=True)

    assert storage.load_window_state("w") is None
    storage.save_window_state("w", state.to_data())
    loaded = storage.load_window_state("w")
    assert loaded is not None
    assert WindowState.from_data(loaded) == state
    assert storage.saves == 1
    storage.delete_window_state("w")
    assert storage.load_window_state("w") is None
    assert storage.load_seed() is None
    storage.save_seed(SEED)
    assert storage.load_seed() == SEED


# --- World and actuator ------------------------------------------------------------------------


def test_the_world_forwards_commands_to_the_covers_and_builds_windows() -> None:
    """The actuator hands a command to the cover; a window takes the covers' profiles."""
    world = World(
        START,
        seed=1,
        covers=[SimulatedCover("cover.example_a", CoverProfile("a"), position=0)],
    )
    world.add_cover(
        SimulatedCover("cover.example_b", CoverProfile("b", supports_stop=False))
    )
    world.actuator.move_to("c-1", "cover.example_a", Position(100))

    assert world.actuator.commands == [(START, "c-1", "cover.example_a", Position(100))]
    assert world.cover("cover.example_a").moving(START + timedelta(seconds=1))
    window = world.window("window_example", "cover.example_a", "cover.example_b")
    assert [m.member_id for m in window.members] == [
        "cover.example_a",
        "cover.example_b",
    ]
    assert not window.members[1].capabilities.supports_stop
    assert world.storage.load_seed() == 1
    assert world.location == Location()
    with pytest.raises(KeyError):
        world.actuator.move_to("c-2", "cover.example_none", Position(0))
    with pytest.raises(ValueError, match="exists already"):
        world.add_cover(SimulatedCover("cover.example_a", CoverProfile("a")))


def test_the_sun_of_the_world_is_the_shared_astral_port() -> None:
    """The location builds the same port the runtime uses."""
    world = World(START, seed=1)
    noon = datetime(2026, 6, 21, 13, 20, tzinfo=ZONE)

    assert world.sun.position(noon).elevation > 60  # noqa: PLR2004 - the round point in June
    assert world.sun.sunrise(noon.date()) is not None
    assert world.clock.now().astimezone(UTC) == START.astimezone(UTC)
