"""Ports: what the domain core needs from the outside world.

The core never reads a clock, never computes anything astronomical, never
calls a cover and never touches a file. It receives all of that through the
protocols below. The Home Assistant layer implements them for the runtime; the
time-lapse simulation and the tests implement them with a synthetic world.

All methods are synchronous. A recompute is a pure function of a world
snapshot; an adapter whose work takes time (a service call, a write to disk)
starts it and returns, and reports the result of a command back to the engine.
"""

from datetime import date, datetime
from typing import Protocol

from .model import JsonObject, Position, SunPosition


class Clock(Protocol):
    """The only source of the current time."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware datetime."""


class Sun(Protocol):
    """Sun times and sun positions for the location of the installation.

    Every datetime that goes in or comes out is timezone-aware. The methods
    that look for a moment on a day return ``None`` if the day has none, for
    example no sunrise during the polar night.
    """

    def position(self, at: datetime) -> SunPosition:
        """Return where the sun is at the given time."""

    def sunrise(self, on: date) -> datetime | None:
        """Return the sunrise of the given local date."""

    def sunset(self, on: date) -> datetime | None:
        """Return the sunset of the given local date."""

    def elevation_reached(
        self, on: date, elevation: float, *, rising: bool
    ) -> datetime | None:
        """Return when the sun passes an elevation on the given local date.

        ``rising`` selects the passage in the morning (upwards) or in the
        evening (downwards). ``None`` means the elevation is not reached.
        """


class Actuator(Protocol):
    """Sends commands to the members of a window."""

    def move_to(self, member_id: str, target: Position) -> None:
        """Command one member to a position.

        The adapter translates the position into what the member supports
        (set position, open or close) and checks dry-run a second time before
        it calls anything.
        """


class Storage(Protocol):
    """Keeps state across restarts, as plain JSON-compatible data.

    The data of a window is what ``WindowState.to_data()`` returns, including
    its schema version.
    """

    def load_window_state(self, window_id: str) -> JsonObject | None:
        """Return the persisted data of a window, or ``None`` if there is none."""

    def save_window_state(self, window_id: str, data: JsonObject) -> None:
        """Persist the data of a window, replacing what was there."""

    def delete_window_state(self, window_id: str) -> None:
        """Delete the persisted data of a window that was removed."""

    def load_seed(self) -> int | None:
        """Return the installation's seed for random offsets, or ``None``."""

    def save_seed(self, seed: int) -> None:
        """Persist the installation's seed for random offsets."""
