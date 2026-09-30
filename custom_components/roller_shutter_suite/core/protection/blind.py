"""The clock of a blind source: "a blind protection must not stay silent" (10.1).

Holding the last state of a source without a value is right (D6), but nobody
notices that the protection has stopped seeing. So while a source has had no
value for longer than ``source_blind_after`` (a setting of the house, default
one hour), the layer says so (``input_held_last_known``) and the event
``protection_source_blind`` is raised once per blind phase. The behavior of
the protection does not change. The repair issue is the Home Assistant
layer's (block H08); it disappears when the source has a value again.

One clock for every kind of source (open question 1 of block C07): the
trigger of a protection event and the fire source here, and from block C08
the blocking contact of lockout protection. Its state is a
:class:`~custom_components.roller_shutter_suite.core.model.BlindClock`.
"""

from dataclasses import replace
from datetime import datetime, timedelta

from custom_components.roller_shutter_suite.core.model import BlindClock


def advance_blind_clock(
    clock: BlindClock | None, *, has_value: bool, now: datetime, blind_after: timedelta
) -> tuple[BlindClock | None, bool]:
    """Return the clock after this moment, and whether the blind event is due now.

    A source with a value drops the clock. A source without one starts it, or
    keeps it running; once it has run for ``blind_after`` and was not reported
    in this phase, it is reported, and the event is due exactly once.
    """
    if has_value:
        return None, False
    if clock is None:
        clock = BlindClock(missing_since=now)
    if clock.reported or now - clock.missing_since < blind_after:
        return clock, False
    return replace(clock, reported=True), True


def is_blind(
    clock: BlindClock | None, *, now: datetime, blind_after: timedelta
) -> bool:
    """Return whether a source without a value has been without one long enough."""
    return clock is not None and (
        clock.reported or now - clock.missing_since >= blind_after
    )


def blind_wake_up(clock: BlindClock | None, blind_after: timedelta) -> datetime | None:
    """Return the instant at which the source will be reported as blind, if any."""
    if clock is None or clock.reported:
        return None
    return clock.missing_since + blind_after
