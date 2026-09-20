"""Local wall-clock times as instants, including the two days of a clock change.

The schedule compares instants only, and it compares them in UTC. Two aware
datetimes that share a zone object are compared by their wall-clock reading in
Python, which is wrong in the repeated hour of a clock change; in UTC the
comparison is always the comparison of two instants.

**The rule for a local time on the day of a clock change.** A local time is
read with the UTC offset that is valid *before* the change:

- A time that exists twice (clocks set back) means its **first** occurrence.
- A time that does not exist (clocks set forward) happens as long after the
  change as it lies inside the skipped hour: with a change from 02:00 to
  03:00, "02:30" happens at 03:30.

Both cases are the same statement: such a time happens as much elapsed time
after local midnight as on any other day. The rule applies to fixed times, to
"not before" and "not after", and to local midnight itself.
"""

from datetime import UTC, date, datetime, time, timedelta, tzinfo

_MIDNIGHT = time(0, 0)


def zone_of(moment: datetime) -> tzinfo:
    """Return the zone of an aware datetime; refuse a naive one.

    The zone of the snapshot's time is the local zone of the installation.
    """
    zone = moment.tzinfo
    if zone is None or moment.utcoffset() is None:
        raise ValueError("the schedule needs a timezone-aware time")
    return zone


def as_instant(moment: datetime, what: str) -> datetime:
    """Return an aware datetime as an instant in UTC; refuse a naive one.

    A naive datetime would be read in the zone of the machine, which is a
    clock the core must not look at.
    """
    if moment.tzinfo is None or moment.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got a naive datetime")
    return moment.astimezone(UTC)


def local_instant(day: date, at: time, zone: tzinfo) -> datetime:
    """Return the instant (in UTC) of a local time on a local date.

    See the module documentation for the day of a clock change.
    """
    return datetime.combine(day, at.replace(fold=0), tzinfo=zone).astimezone(UTC)


def start_of_day(day: date, zone: tzinfo) -> datetime:
    """Return the instant of local midnight at the start of a local date."""
    return local_instant(day, _MIDNIGHT, zone)


def end_of_day(day: date, zone: tzinfo) -> datetime:
    """Return the instant of local midnight at the end of a local date."""
    return start_of_day(day + timedelta(days=1), zone)


def local_date(instant: datetime, zone: tzinfo) -> date:
    """Return the local date on which an instant lies."""
    return instant.astimezone(zone).date()
