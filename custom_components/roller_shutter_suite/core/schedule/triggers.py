"""The instant of a trigger on a local date: kind, random offset, clamps.

Nothing here computes anything astronomical; sunrise, sunset, the passage of
an elevation and the elevation at noon are answers of the sun port.
"""

import hashlib
from datetime import date, datetime, time, timedelta, tzinfo
from enum import StrEnum, unique
from typing import Final

from custom_components.roller_shutter_suite.core.ports import Sun

from .local_time import as_instant, end_of_day, local_instant, start_of_day
from .settings import Trigger, TriggerKind

_NOON: Final = time(12, 0)

_HORIZON: Final = 0.0


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


def _threshold(trigger: Trigger) -> float:
    """Return the elevation a trigger waits for; the horizon for a sun event."""
    if trigger.kind is TriggerKind.ELEVATION and trigger.elevation is not None:
        return trigger.elevation
    return _HORIZON


def _moment_from_sun(
    trigger: Trigger, edge: Edge, day: date, sun: Sun
) -> datetime | None:
    morning = edge is Edge.MORNING
    if trigger.kind is TriggerKind.ELEVATION:
        found = sun.elevation_reached(day, _threshold(trigger), rising=morning)
        return None if found is None else as_instant(found, "a time of the sun port")
    found = sun.sunrise(day) if morning else sun.sunset(day)
    if found is None:
        return None
    return as_instant(found, "a time of the sun port") + trigger.offset


def _clamp_in_its_direction(
    trigger: Trigger, edge: Edge, day: date, zone: tzinfo, sun: Sun
) -> time:
    """Return the clamp a trigger falls on when the sun gives no moment.

    Either the sun stays below the elevation all day: the morning never comes
    by itself (latest morning), and the evening has begun already (earliest
    evening). Or it stays above: the morning has begun already (earliest
    morning), and the evening never comes by itself (latest evening). The
    elevation at local noon, asked of the sun port, tells the two apart.
    """
    noon = sun.position(local_instant(day, _NOON, zone))
    sun_is_up = noon.elevation >= _threshold(trigger)
    if sun_is_up == (edge is Edge.MORNING):
        return trigger.earliest
    return trigger.latest


def trigger_instant(  # noqa: PLR0913 - the inputs of one trigger, all of them needed
    trigger: Trigger,
    edge: Edge,
    day: date,
    *,
    zone: tzinfo,
    sun: Sun,
    offset: timedelta = timedelta(0),
) -> datetime:
    """Return the instant (in UTC) of a trigger on a local date.

    The order is fixed: the moment of the kind, plus the random offset, then
    the clamps, and last the limits of the local date itself, so a trigger
    always lies on its own date. A trigger that falls on a clamp because the
    sun gives no moment gets no random offset: it is on the clamp already.
    """
    if trigger.kind is TriggerKind.FIXED_TIME:
        moment: datetime | None = local_instant(day, trigger.fixed_time, zone)
    else:
        moment = _moment_from_sun(trigger, edge, day, sun)
    if moment is None:
        fallback = _clamp_in_its_direction(trigger, edge, day, zone, sun)
        moment = local_instant(day, fallback, zone)
    else:
        moment += offset
    if trigger.not_before is not None:
        moment = max(moment, local_instant(day, trigger.not_before, zone))
    if trigger.not_after is not None:
        moment = min(moment, local_instant(day, trigger.not_after, zone))
    return min(max(moment, start_of_day(day, zone)), end_of_day(day, zone))
