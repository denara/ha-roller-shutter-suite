"""Protection events as values: trigger, direction, rank, times (section 10.1).

A protection event is a setting of the house (``WindowConfig.protection_events``,
inherited like any other setting): a trigger source with the kind of its
trigger, a direction, a rank, a waiting time after its end and a maximum
duration for the watchdog. The sleep-room exception is the per-window part
(``WindowConfig.protection_sleep_exception``, the identifiers of the events
that must not open the window while sleep mode is active).

**Faults inside one event are read leniently, field by field** (ruling of the
project owner of 2026-10-01). A field that cannot be read takes its cautious
value and is named in :attr:`ProtectionEventConfig.faulty_fields`, so that the
Home Assistant layer (block H08) can report it:

- a faulty **trigger** (source, kind, states, threshold, hysteresis, invert)
  makes the trigger blind: ``trigger`` is ``None``, the event never starts
  and never ends by its source, and a persisted state is held (D6);
- a faulty **direction** skips the event: ``direction`` is ``None``. There is
  no cautious direction: "open" is right for hail on some curtains and wrong
  on others (section 6 of the brief);
- a faulty **rank** makes the event lose against every valid rank: ``rank``
  is ``None``;
- a faulty **waiting time** or **maximum duration** is the default, never
  zero: a fault must not switch the watchdog off.

**A list that cannot be read as a whole** is :data:`EVENTS_UNREADABLE`: the
events are configured, but unreadable. The layer then holds the window where
it is for every persisted event that is active or still in its waiting time,
with the default waiting time and the default maximum duration.
"""

from dataclasses import dataclass
from datetime import timedelta
from enum import Enum, StrEnum, unique
from typing import Final

from ._validation import (
    require_finite,
    require_identifier,
    require_type,
    require_unique,
)
from .values import FULLY_CLOSED, FULLY_OPEN, Position

DEFAULT_WAITING_TIME: Final = timedelta(minutes=30)
"""The waiting time after the end of an event before the window returns (10.1)."""

DEFAULT_MAX_DURATION: Final = timedelta(hours=12)
"""The maximum duration of an event before the watchdog releases it (10.3)."""

MAX_WAITING_TIME: Final = timedelta(hours=24)
"""The longest waiting time an event can state."""

MAX_MAX_DURATION: Final = timedelta(days=7)
"""The longest maximum duration an event can state; zero switches the watchdog off."""

DEFAULT_SOURCE_BLIND_AFTER: Final = timedelta(hours=1)
"""How long a source may be without a value before it is reported as blind."""

MIN_SOURCE_BLIND_AFTER: Final = timedelta(minutes=1)
MAX_SOURCE_BLIND_AFTER: Final = timedelta(days=7)

MIN_RANK: Final = 1
MAX_RANK: Final = 1000
"""The ranks an event can state; the higher rank wins."""


@unique
class EventDirection(StrEnum):
    """Where a protection event drives the window: always an end position."""

    OPEN = "open"
    CLOSED = "closed"

    @property
    def end_position(self) -> Position:
        """Return the end position of the direction: 100 or 0."""
        return FULLY_OPEN if self is EventDirection.OPEN else FULLY_CLOSED


@unique
class TriggerType(StrEnum):
    """The kind of the trigger source of a protection event."""

    BINARY = "binary"
    """An on/off source: on is active (off with ``invert``)."""
    STATES = "states"
    """A source with states: active while its state is one of the listed ones."""
    THRESHOLD = "threshold"
    """A number: active from the threshold on, inactive below the threshold
    minus the hysteresis; with ``invert`` the other way round."""


@dataclass(frozen=True, slots=True)
class ProtectionTrigger:
    """The trigger source of a protection event and how it is read.

    - ``source``: the key of the source in the world snapshot.
    - ``kind``: see :class:`TriggerType`.
    - ``states``: for ``states``, the states that mean "active"; the text of
      the state is compared (``on`` and ``off`` for a switch, the number as
      text for a number).
    - ``threshold`` and ``hysteresis``: for ``threshold``. Active at or above
      the threshold, inactive below ``threshold - hysteresis``; in between the
      persisted state holds, so the trigger does not flap at the value.
    - ``invert``: for ``binary`` and ``threshold``: off is active, or active
      at or below the threshold and inactive above ``threshold + hysteresis``
      (a "calm" sensor, a pressure that falls).
    """

    source: str
    kind: TriggerType = TriggerType.BINARY
    states: tuple[str, ...] = ()
    threshold: float = 0.0
    hysteresis: float = 0.0
    invert: bool = False

    def __post_init__(self) -> None:
        """Validate the fields that belong to the kind of the trigger."""
        require_identifier(self.source, "the source of a trigger")
        require_type(self.kind, TriggerType, "the kind of a trigger")
        object.__setattr__(self, "states", tuple(self.states))
        for state in self.states:
            require_identifier(state, "a state of a trigger")
        require_unique(self.states, "the states of a trigger")
        if (self.kind is TriggerType.STATES) != bool(self.states):
            raise ValueError("a trigger of the kind 'states' and only it lists states")
        require_finite(self.threshold, "the threshold of a trigger")
        require_finite(self.hysteresis, "the hysteresis of a trigger")
        if self.hysteresis < 0:
            raise ValueError("the hysteresis of a trigger must not be negative")
        require_type(self.invert, bool, "the flag 'invert' of a trigger")
        if self.kind is TriggerType.STATES and self.invert:
            raise ValueError("a trigger of states names the active states itself")
        if self.kind is not TriggerType.THRESHOLD and (
            self.threshold != 0 or self.hysteresis != 0
        ):
            raise ValueError("only a trigger of the kind 'threshold' has a threshold")


def _require_duration(value: timedelta, maximum: timedelta, what: str) -> None:
    require_type(value, timedelta, what)
    if not timedelta(0) <= value <= maximum:
        raise ValueError(f"{what} must lie within zero and {maximum}")


@dataclass(frozen=True, slots=True)
class ProtectionEventConfig:
    """One protection event as the house configures it.

    ``None`` in ``trigger``, ``direction`` or ``rank`` means that the stored
    field is faulty, and ``faulty_fields`` names the stored keys that could not
    be read; see the module docstring for what each fault costs. A higher
    rank wins; a ``None`` rank loses against every valid rank. A maximum
    duration of zero switches the watchdog off for this event.
    """

    event_id: str
    trigger: ProtectionTrigger | None
    direction: EventDirection | None
    rank: int | None
    waiting_time: timedelta = DEFAULT_WAITING_TIME
    max_duration: timedelta = DEFAULT_MAX_DURATION
    faulty_fields: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Validate the fields; a missing value must be named as a fault."""
        require_identifier(self.event_id, "the identifier of a protection event")
        if self.trigger is not None:
            require_type(self.trigger, ProtectionTrigger, "the trigger of an event")
        if self.direction is not None:
            require_type(self.direction, EventDirection, "the direction of an event")
        if self.rank is not None:
            if isinstance(self.rank, bool) or not isinstance(self.rank, int):
                raise TypeError("the rank of a protection event is a whole number")
            if not MIN_RANK <= self.rank <= MAX_RANK:
                raise ValueError(
                    f"the rank of a protection event lies within {MIN_RANK} and "
                    f"{MAX_RANK}"
                )
        _require_duration(self.waiting_time, MAX_WAITING_TIME, "the waiting time")
        _require_duration(self.max_duration, MAX_MAX_DURATION, "the maximum duration")
        object.__setattr__(self, "faulty_fields", tuple(self.faulty_fields))
        for key in self.faulty_fields:
            require_identifier(key, "a faulty field of a protection event")
        require_unique(self.faulty_fields, "the faulty fields of a protection event")
        missing = None in (self.trigger, self.direction, self.rank)
        if missing and not self.faulty_fields:
            raise ValueError(
                "a protection event without a trigger, a direction or a rank "
                "names the faulty fields"
            )


@unique
class UnreadableEvents(Enum):
    """The type of the marker :data:`EVENTS_UNREADABLE`. It has exactly one member."""

    UNREADABLE = "unreadable"


EVENTS_UNREADABLE: Final = UnreadableEvents.UNREADABLE
"""The protection events are **configured, but unreadable**.

The fault value of ``protection_events``: a level tried to set the list and
the stored value cannot be read, or a level that could have set it is
unreadable as a whole, and no other level supplies a valid list. It is not an
empty list: an empty list means "no protection events", and a data fault must
never take protection away. It has no stored form, and only the inheritance
resolver produces it.
"""

type ProtectionEvents = tuple[ProtectionEventConfig, ...] | UnreadableEvents
"""The protection events of a window: a list, or configured but unreadable."""


def validate_protection_events(events: object) -> None:
    """Validate the value of ``WindowConfig.protection_events``.

    Identifiers are unique, and so are the valid ranks: the reader of the
    stored list marks a duplicated rank as faulty on every event that states
    it, so a duplicate never reaches the arbiter.
    """
    if events is EVENTS_UNREADABLE:
        return
    if not isinstance(events, tuple):
        raise TypeError("the protection events are a tuple of events")
    for event in events:
        require_type(event, ProtectionEventConfig, "a protection event")
    require_unique(
        (event.event_id for event in events), "the identifiers of protection events"
    )
    require_unique(
        (str(event.rank) for event in events if event.rank is not None),
        "the ranks of protection events",
    )


def validate_sleep_exception(event_ids: object) -> None:
    """Validate the value of ``WindowConfig.protection_sleep_exception``."""
    if not isinstance(event_ids, tuple):
        raise TypeError("the sleep-room exception is a tuple of event identifiers")
    for event_id in event_ids:
        require_identifier(event_id, "an event of the sleep-room exception")
    require_unique(event_ids, "the events of the sleep-room exception")
