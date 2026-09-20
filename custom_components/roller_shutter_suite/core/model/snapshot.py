"""The world snapshot: everything one recompute may look at."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from ._validation import require_aware, require_identifier, require_type
from .controls import Controls
from .observation import MembersAtTargets, WindowObservation
from .state import WindowState
from .values import AnySourceValue, Position, SourceValue, SunPosition


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    """Everything one recompute may look at.

    ``time`` is timezone-aware and keeps its zone: **the zone of ``time`` is
    the local zone of the installation**, the same zone in which the clock
    port reports the time. Everything that is local by nature is read from
    it: fixed times of the schedule, "local midnight" of the day-type latch,
    and the local date that is handed to the sun port. Unlike the persisted
    instants, it is therefore not converted to UTC.

    ``sources`` maps the key of a source to its value. The mapping is copied
    and cannot be changed afterwards. A snapshot is compared by value, but it
    is not hashable, because it contains a mapping.

    `controls` is what a person has set for the window at this moment: pause,
    maintenance lock and operating mode on their three levels, and dry-run.
    They change while the integration runs, so they are part of the snapshot
    and not of the window configuration.
    """

    time: datetime
    sun: SunPosition
    sources: Mapping[str, AnySourceValue]
    observation: WindowObservation
    state: WindowState
    controls: Controls

    def __post_init__(self) -> None:
        """Reject a naive time and copy the sources."""
        require_aware(self.time, "the time of a world snapshot")
        require_type(self.sun, SunPosition, "the sun position of a snapshot")
        require_type(self.observation, WindowObservation, "the observed window")
        require_type(self.state, WindowState, "the persisted window state")
        require_type(self.controls, Controls, "the controls of a snapshot")
        sources = dict(self.sources)
        for key, value in sources.items():
            require_identifier(key, "the key of a source")
            require_type(value, SourceValue, f"the source {key!r}")
        object.__setattr__(self, "sources", MappingProxyType(sources))

    def window_position(self, tolerances: Mapping[str, int]) -> Position | None:
        """Return the logical position of the window, or ``None`` if it has none.

        The rules are those of ``WindowObservation.position``: all members
        report the same position within tolerance. ``tolerances`` gives the
        tolerance of every member (``CapabilityProfile.tolerance``).
        """
        return self.observation.position(tolerances)

    def members_at_commanded_targets(
        self, tolerances: Mapping[str, int]
    ) -> MembersAtTargets:
        """Say whether every member stands at its own last commanded target.

        The observed members are compared with the last commanded targets of
        the persisted state (``WindowState.commanded_targets``); the rules are
        those of ``WindowObservation.members_at_commanded_targets``.
        """
        return self.observation.members_at_commanded_targets(
            self.state.commanded_targets, tolerances
        )
