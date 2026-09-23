"""A clock that the runner moves by hand, in the local zone of the installation."""

from datetime import UTC, datetime, tzinfo


class SimClock:
    """The clock port of the synthetic world.

    It starts at a timezone-aware instant and only moves forward, in the zone
    it was started in, which is the local zone of the installation: the zone
    of ``now()`` becomes the zone of every world snapshot.
    """

    def __init__(self, start: datetime) -> None:
        """Start at an aware instant; its zone is the local zone."""
        if start.tzinfo is None or start.utcoffset() is None:
            raise ValueError("the simulated clock starts at a timezone-aware time")
        self._now = start
        self._zone: tzinfo = start.tzinfo

    @property
    def zone(self) -> tzinfo:
        """Return the local zone of the installation."""
        return self._zone

    def now(self) -> datetime:
        """Return the current simulated time in the local zone."""
        return self._now

    def advance_to(self, moment: datetime) -> None:
        """Move the clock forward to an instant; going back is refused."""
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError("the simulated clock moves to timezone-aware times only")
        # Two datetimes of the same zone object compare by their wall-clock
        # reading, which runs backwards in the repeated hour of a clock
        # change; instants are compared in UTC.
        if moment.astimezone(UTC) < self._now.astimezone(UTC):
            raise ValueError("the simulated clock never goes back")
        self._now = moment.astimezone(self._zone)
