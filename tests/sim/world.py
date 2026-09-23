"""The synthetic world: the ports of the core, implemented for a scenario.

A :class:`World` holds the controllable clock, the shared astral-backed sun
port for a configurable location, the script of the sources, the simulated
covers, the in-memory storage and the actuator that forwards commands to the
covers. It also holds the seeded random generator a scenario may draw noise
from while it is built, so that a run is reproducible.
"""

import random
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from custom_components.roller_shutter_suite.core.model import (
    MemberConfig,
    Position,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.ports import Sun
from custom_components.roller_shutter_suite.sun_astral import AstralSun

from .clock import SimClock
from .cover import SimulatedCover
from .sources import Script
from .storage import MemoryStorage


@dataclass(frozen=True, slots=True)
class Location:
    """Where the installation stands: the arguments of the sun port.

    The defaults are a made-up round point, 50 north and 10 east at sea
    level, in the zone ``Europe/Berlin``; never the coordinates of a real
    installation.
    """

    latitude: float = 50.0
    longitude: float = 10.0
    elevation: float = 0.0
    time_zone: str = "Europe/Berlin"

    def sun(self) -> Sun:
        """Return the sun port for this location."""
        return AstralSun(self.latitude, self.longitude, self.elevation, self.time_zone)


class SimActuator:
    """The actuator port: hands a command to the cover of the member.

    It remembers every command it received, with its identifier, as the
    runtime's adapter would log it. The second check of dry-run that the
    runtime's adapter makes is the runner's business here: the runner never
    calls this for a window in dry-run and fails loudly if it would.
    """

    def __init__(self, clock: SimClock, covers: Mapping[str, SimulatedCover]) -> None:
        """Forward to these covers at the time of the clock."""
        self._clock = clock
        self._covers = covers
        self.commands: list[tuple[datetime, str, str, Position]] = []
        """(instant, command identifier, member, target) of every command."""

    def move_to(self, command_id: str, member_id: str, target: Position) -> None:
        """Command one member; return without waiting."""
        cover = self._covers.get(member_id)
        if cover is None:
            raise KeyError(f"no simulated cover for {member_id!r}")
        now = self._clock.now()
        self.commands.append((now, command_id, member_id, target))
        cover.move_to(target.value, now, by="engine")


class World:
    """Everything the core's ports need, for one scenario."""

    def __init__(
        self,
        start: datetime,
        *,
        seed: int,
        location: Location | None = None,
        script: Script | None = None,
        covers: Iterable[SimulatedCover] = (),
    ) -> None:
        """Build the world at a start instant in the local zone of the installation."""
        self.seed = seed
        self.random = random.Random(seed)  # noqa: S311 - reproducible noise, no security use
        self.clock = SimClock(start)
        self.location = Location() if location is None else location
        self.sun: Sun = self.location.sun()
        self.script = Script.empty() if script is None else script
        self.storage = MemoryStorage()
        self.storage.save_seed(seed)
        self.covers: dict[str, SimulatedCover] = {}
        for cover in covers:
            self.add_cover(cover)
        self.actuator = SimActuator(self.clock, self.covers)

    def add_cover(self, cover: SimulatedCover) -> SimulatedCover:
        """Add a cover; its identifier is the member identifier of the core."""
        if cover.cover_id in self.covers:
            raise ValueError(f"a cover {cover.cover_id!r} exists already")
        self.covers[cover.cover_id] = cover
        return cover

    def cover(self, member_id: str) -> SimulatedCover:
        """Return the cover of a member."""
        return self.covers[member_id]

    def window(self, window_id: str, *member_ids: str, **fields: Any) -> WindowConfig:
        """Return a window configuration over covers of this world.

        The capability profile of every member is what the user would state
        for its cover. ``fields`` are fields of ``WindowConfig``.
        """
        members = tuple(
            MemberConfig(member_id, self.covers[member_id].profile.capability_profile())
            for member_id in member_ids
        )
        return WindowConfig(window_id, members, **fields)
