"""What a run must satisfy, judged on the record.

Every assertion raises :class:`ScenarioAssertionError` with the moment it
found and the timeline around that moment, so a failed scenario points at the
place where something went wrong instead of at a number. The checks:

- **movements per window and day**: a movement is one decision that sent, so
  a window with two members that move together moved once;
- **the minimum interval** between two comfort movements of a window;
- **no command loop**: the same member commanded to the same target twice
  without a report of that member in between;
- **no intermediate position** in a span of time (a storm): every command
  targets an end position;
- **inside the clamps**: every command of the schedule falls inside the
  window of its trigger, on the local clock.
"""

import itertools
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta

from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    DayType,
    Trigger,
    TriggerKind,
    WindowConfig,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.schedule import day_type_by_weekday

from .record import Entry, EntryKind, Record


class ScenarioAssertionError(AssertionError):
    """A run violated what the scenario demands; the message shows the moment."""

    def __init__(
        self,
        record: Record,
        moment: datetime,
        what: str,
        *,
        window_id: str | None = None,
    ) -> None:
        """Build the message: what went wrong, when, and the timeline around it."""
        local = moment.astimezone(record.zone).isoformat(timespec="seconds")
        excerpt = record.around(moment, window_id=window_id)
        super().__init__(
            f"{what} at {local}\n--- timeline around that moment ---\n{excerpt}"
        )
        self.moment = moment
        self.what = what


@dataclass(frozen=True, slots=True)
class MovementsPerDay:
    """How often a window moved on each local date."""

    window_id: str
    counts: dict[date, int]

    @property
    def most(self) -> int:
        """Return the largest number of movements on one day."""
        return max(self.counts.values(), default=0)


def movements_per_day(record: Record, window_id: str) -> MovementsPerDay:
    """Count the movements of a window per local date; a movement is one send."""
    counts: Counter[date] = Counter(
        record.local_date(entry) for entry in record.sends(window_id)
    )
    return MovementsPerDay(window_id, dict(sorted(counts.items())))


def assert_at_most_movements_per_day(
    record: Record, limit: int, *, since: datetime | None = None
) -> None:
    """Fail if any window moved more often than ``limit`` times on one day.

    ``since`` leaves the start of the run out: at its first recompute a
    window may have to move once to where the schedule wants it, and a
    member without position feedback is always commanded once then, because
    nobody knows where it stands.
    """
    for window_id in record.window_ids():
        by_day: dict[date, list[Entry]] = {}
        for entry in record.sends(window_id):
            if since is not None and entry.at < since.astimezone(UTC):
                continue
            by_day.setdefault(record.local_date(entry), []).append(entry)
        for day, sends in by_day.items():
            if len(sends) > limit:
                raise ScenarioAssertionError(
                    record,
                    sends[limit].at,
                    f"{window_id} moved {len(sends)} times on {day}, more than {limit}",
                    window_id=window_id,
                )


def assert_min_interval(record: Record, configs: Iterable[WindowConfig]) -> None:
    """Fail if two comfort movements of a window lie closer than its minimum interval.

    A fresh wish may legitimately follow the last comfort movement inside the
    interval (the arbiter says so); a scenario that expects that does not
    call this assertion.
    """
    for config in configs:
        interval = config.motor_protection.min_interval
        comfort = [
            entry
            for entry in record.sends(config.window_id)
            if entry.wish_class is WishClass.COMFORT
        ]
        for earlier, later in itertools.pairwise(comfort):
            if later.at - earlier.at < interval:
                raise ScenarioAssertionError(
                    record,
                    later.at,
                    f"{config.window_id} made two comfort movements "
                    f"{later.at - earlier.at} apart, closer than {interval}",
                    window_id=config.window_id,
                )


def assert_no_command_loop(record: Record) -> None:
    """Fail on a repeated command to the same target without a report in between."""
    last_command: dict[str, Entry] = {}
    for entry in record.entries:
        if entry.member_id is None:
            continue
        if entry.kind is EntryKind.REPORT:
            last_command.pop(entry.member_id, None)
        elif entry.kind is EntryKind.COMMAND:
            previous = last_command.get(entry.member_id)
            if previous is not None and previous.target == entry.target:
                raise ScenarioAssertionError(
                    record,
                    entry.at,
                    f"{entry.member_id} was commanded to "
                    f"{entry.target.value if entry.target else '?'} again without "
                    "a report in between (command loop)",
                    window_id=entry.window_id,
                )
            last_command[entry.member_id] = entry


def assert_no_intermediate_position(
    record: Record, window_id: str, since: datetime, until: datetime
) -> None:
    """Fail if a command of the window inside the span targets a position between the ends."""
    for entry in record.between(since, until):
        if (
            entry.kind is EntryKind.COMMAND
            and entry.window_id == window_id
            and entry.target not in (FULLY_OPEN, FULLY_CLOSED)
        ):
            raise ScenarioAssertionError(
                record,
                entry.at,
                f"{window_id} was sent to the intermediate position "
                f"{entry.target.value if entry.target else '?'} during the storm",
                window_id=window_id,
            )


def _trigger_window(trigger: Trigger) -> tuple[time, time]:
    if trigger.kind is TriggerKind.FIXED_TIME:
        return trigger.time, trigger.time
    return trigger.not_before, trigger.not_after


def assert_schedule_commands_inside_clamps(
    record: Record, config: WindowConfig, *, since: datetime | None = None
) -> None:
    """Fail if a command of the schedule lies outside the window of its trigger.

    The day type of a date is the one by the day of the week, which is what a
    scenario without day-type sources gets. A movement of the morning lies at
    the fixed time or between the clamps of the morning trigger, one of the
    evening at or between those of the evening trigger, on the local clock.
    A command later than the trigger by up to the settle time of the runner
    is still that trigger's. ``since`` leaves the start of the run out, as
    for the movements per day.
    """
    settings = config.schedule
    slack = timedelta(minutes=1)
    for entry in record.sends(config.window_id):
        if since is not None and entry.at < since.astimezone(UTC):
            continue
        decision = entry.decision
        if decision is None or decision.winning_wish is None:
            continue
        reason = decision.winning_wish.reason
        if reason not in (ReasonCode.SCHEDULE_DAY, ReasonCode.SCHEDULE_NIGHT):
            continue
        local = entry.at.astimezone(record.zone)
        day_type: DayType = day_type_by_weekday(local.date())
        triggers = settings.triggers_for(day_type)
        trigger = (
            triggers.morning if reason is ReasonCode.SCHEDULE_DAY else triggers.evening
        )
        not_before, not_after = _trigger_window(trigger)
        earliest = datetime.combine(local.date(), not_before, tzinfo=record.zone)
        latest = datetime.combine(local.date(), not_after, tzinfo=record.zone) + slack
        if not earliest <= local <= latest:
            raise ScenarioAssertionError(
                record,
                entry.at,
                f"{config.window_id} moved for {reason.value} at "
                f"{local.time().isoformat(timespec='seconds')}, outside "
                f"{not_before.isoformat(timespec='minutes')} to "
                f"{not_after.isoformat(timespec='minutes')}",
                window_id=config.window_id,
            )


def assert_no_commands(record: Record, window_id: str) -> None:
    """Fail if the window was sent anything at all (dry-run, maintenance lock)."""
    commands = record.commands(window_id)
    if commands:
        raise ScenarioAssertionError(
            record,
            commands[0].at,
            f"{window_id} was sent a command although nothing may move",
            window_id=window_id,
        )
