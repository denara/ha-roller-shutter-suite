"""The instant of a trigger on a local date: kind, random offset, clamps.

Nothing here computes anything astronomical; sunrise, sunset, the passage of
an elevation are answers of the sun port, asked directly or read from the
almanac (module ``sun``).
"""

import hashlib
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum, unique

from custom_components.roller_shutter_suite.core.model import Trigger, TriggerKind

from .local_time import end_of_day, local_instant, start_of_day
from .sun import SunSource


@unique
class Edge(StrEnum):
    """The two triggers of a day."""

    MORNING = "morning"
    EVENING = "evening"


def random_offset(
    seed: int, window_id: str, day: date, edge: Edge, maximum: timedelta
) -> timedelta:
    """Return the random offset of one trigger of one window on one date.

    It is a pure function of its arguments: the same within a day and after a
    restart, different between windows, dates and the two triggers. The
    offset is a whole number of seconds, uniform within ± ``maximum``.
    """
    span = int(maximum.total_seconds())
    if span <= 0:
        return timedelta(0)
    text = f"{seed}|{window_id}|{day.isoformat()}|{edge.value}"
    number = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
    return timedelta(seconds=number % (2 * span + 1) - span)


def _moment_from_sun(
    trigger: Trigger, edge: Edge, day: date, sun: SunSource
) -> datetime | None:
    morning = edge is Edge.MORNING
    if trigger.kind is TriggerKind.ELEVATION:
        return sun.elevation_reached(day, trigger.elevation, rising=morning)
    found = sun.sunrise(day) if morning else sun.sunset(day)
    return None if found is None else found + trigger.offset


def _clamp_in_its_direction(trigger: Trigger, edge: Edge) -> time:
    """Return the clamp a trigger falls on when the sun gives no moment.

    The sun does not rise, does not set, or never passes the elevation on
    the date. The clamp decides: the morning falls on "not before", the
    evening on "not after". That is an answer, not missing data.
    """
    return trigger.not_before if edge is Edge.MORNING else trigger.not_after


def trigger_instant(  # noqa: PLR0913 - the inputs of one trigger, all of them needed
    trigger: Trigger,
    edge: Edge,
    day: date,
    *,
    zone: tzinfo,
    sun: SunSource,
    offset: timedelta = timedelta(0),
) -> datetime:
    """Return the instant (in UTC) of a trigger on a local date.

    The order is fixed: the moment of the kind, plus the random offset, then
    the clamps where they apply (``Trigger.clamps_apply``), and last the
    limits of the local date itself, so a trigger always lies on its own
    date. A trigger that falls on a clamp because the sun gives no moment
    gets no random offset: it is on the clamp already.
    """
    if trigger.kind is TriggerKind.FIXED_TIME:
        moment: datetime | None = local_instant(day, trigger.time, zone)
    else:
        moment = _moment_from_sun(trigger, edge, day, sun)
    if moment is None:
        fallback = _clamp_in_its_direction(trigger, edge)
        moment = local_instant(day, fallback, zone)
    else:
        moment += offset
    if trigger.clamps_apply:
        moment = max(moment, local_instant(day, trigger.not_before, zone))
        moment = min(moment, local_instant(day, trigger.not_after, zone))
    return min(max(moment, start_of_day(day, zone)), end_of_day(day, zone))
