"""The world snapshot: everything one recompute may look at."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType

from ._validation import require_aware, require_identifier, require_type
from .observation import WindowObservation
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
    """

    time: datetime
    sun: SunPosition
    sources: Mapping[str, AnySourceValue]
    observation: WindowObservation
    state: WindowState

    def __post_init__(self) -> None:
        """Reject a naive time and copy the sources."""
        require_aware(self.time, "the time of a world snapshot")
        require_type(self.sun, SunPosition, "the sun position of a snapshot")
        require_type(self.observation, WindowObservation, "the observed window")
        require_type(self.state, WindowState, "the persisted window state")
        sources = dict(self.sources)
        for key, value in sources.items():
            require_identifier(key, "the key of a source")
            require_type(value, SourceValue, f"the source {key!r}")
        object.__setattr__(self, "sources", MappingProxyType(sources))

    def window_position(self, tolerances: Mapping[str, int]) -> Position | None:
        """Return the logical position of the window, or ``None`` if it has none.

        The observed members are compared with the last commanded targets of
        the persisted state; the rules are those of
        ``WindowObservation.position``. ``tolerances`` gives the tolerance of
        every member (``CapabilityProfile.tolerance``).
        """
        return self.observation.position(self.state.commanded_targets, tolerances)
