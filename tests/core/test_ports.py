"""The ports can be implemented with a synthetic world, without Home Assistant."""

import inspect
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol

from custom_components.roller_shutter_suite.core import ports
from custom_components.roller_shutter_suite.core.model import (
    JsonObject,
    Position,
    SunPosition,
    WindowState,
)
from custom_components.roller_shutter_suite.core.ports import (
    Actuator,
    Clock,
    Storage,
    Sun,
)

START = datetime(2026, 3, 1, 6, 0, tzinfo=UTC)
HIGHEST_ELEVATION = 40.0
SEED = 1234


class FakeClock:
    """A clock that a test moves by hand."""

    def __init__(self, start: datetime) -> None:
        """Start at the given time."""
        self.current = start

    def now(self) -> datetime:
        """Return the time the test has set."""
        return self.current


class FakeSun:
    """A sun that rises at six, sets at eighteen and never gets above 40 degrees."""

    def position(self, at: datetime) -> SunPosition:
        """Return 15 degrees of azimuth per hour at a fixed elevation."""
        return SunPosition(azimuth=(at.hour * 15.0) % 360, elevation=10.0)

    def sunrise(self, on: date) -> datetime | None:
        """Return six o'clock."""
        return datetime.combine(on, time(6, 0), tzinfo=UTC)

    def sunset(self, on: date) -> datetime | None:
        """Return eighteen o'clock."""
        return datetime.combine(on, time(18, 0), tzinfo=UTC)

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Return eight or sixteen o'clock, or nothing above the highest elevation."""
        if elevation > HIGHEST_ELEVATION:
            return None
        return datetime.combine(on, time(8 if rising else 16, 0), tzinfo=UTC)


class FakeActuator:
    """An actuator that only remembers what it was asked to do."""

    def __init__(self) -> None:
        """Start without commands."""
        self.commands: list[tuple[str, Position]] = []

    def move_to(self, member_id: str, target: Position) -> None:
        """Remember the command."""
        self.commands.append((member_id, target))


class FakeStorage:
    """A storage that lives in memory."""

    def __init__(self) -> None:
        """Start empty."""
        self.windows: dict[str, JsonObject] = {}
        self.seed: int | None = None

    def load_window_state(self, window_id: str) -> JsonObject | None:
        """Return what was saved for the window."""
        return self.windows.get(window_id)

    def save_window_state(self, window_id: str, data: JsonObject) -> None:
        """Keep the data of the window."""
        self.windows[window_id] = data

    def delete_window_state(self, window_id: str) -> None:
        """Forget the window."""
        self.windows.pop(window_id, None)

    def load_seed(self) -> int | None:
        """Return the saved seed."""
        return self.seed

    def save_seed(self, seed: int) -> None:
        """Keep the seed."""
        self.seed = seed


def test_the_four_ports_are_protocols() -> None:
    """Clock, sun, actuator and storage, and nothing else."""
    found = {
        name
        for name, value in inspect.getmembers(ports, inspect.isclass)
        if value.__module__ == ports.__name__
    }

    assert found == {"Clock", "Sun", "Actuator", "Storage"}
    for port in (Clock, Sun, Actuator, Storage):
        assert Protocol in port.__mro__


def test_clock_port() -> None:
    """The time comes from outside and is timezone-aware."""
    clock: Clock = FakeClock(START)

    assert clock.now() == START
    assert clock.now().tzinfo is not None


def test_sun_port() -> None:
    """Sun times and positions come from outside; a day can lack a moment."""
    sun: Sun = FakeSun()
    day = date(2026, 3, 1)
    sunrise = sun.sunrise(day)
    sunset = sun.sunset(day)

    assert sun.position(START) == SunPosition(azimuth=90.0, elevation=10.0)
    assert sunrise is not None
    assert sunset is not None
    assert sunset - sunrise == timedelta(hours=12)
    assert sun.elevation_reached(day, 20.0, rising=True) is not None
    assert sun.elevation_reached(day, 20.0, rising=False) is not None
    assert sun.elevation_reached(day, 60.0, rising=True) is None


def test_actuator_port() -> None:
    """Commands go to a member, as a position."""
    fake = FakeActuator()
    actuator: Actuator = fake

    actuator.move_to("cover.example_window", Position(0))

    assert fake.commands == [("cover.example_window", Position(0))]


def test_storage_port_keeps_window_state_as_plain_data() -> None:
    """Save, load and delete per window; the seed per installation."""
    storage: Storage = FakeStorage()
    state = WindowState(fire_unacknowledged=True)

    assert storage.load_window_state("window_example") is None
    assert storage.load_seed() is None

    storage.save_window_state("window_example", state.to_data())
    storage.save_seed(SEED)
    loaded = storage.load_window_state("window_example")

    assert loaded is not None
    assert WindowState.from_data(loaded) == state
    assert storage.load_seed() == SEED

    storage.delete_window_state("window_example")

    assert storage.load_window_state("window_example") is None
