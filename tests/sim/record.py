"""The record of a run: every decision, command, report and event, in order.

The record is what the assertions judge and what the timeline prints. An
entry is a value: two runs of the same scenario with the same seed produce
equal records, which is how reproducibility is asserted. A decision entry
keeps the whole decision, so an assertion can look at reasons and targets
without parsing text; the ``summary`` is the one readable line of the
timeline.
"""

from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum, unique

from custom_components.roller_shutter_suite.core.model import (
    Decision,
    GateKind,
    Observation,
    Position,
    WishClass,
)


@unique
class EntryKind(StrEnum):
    """What an entry of the record is about."""

    DECISION = "decision"
    COMMAND = "command"
    REPORT = "report"
    SOURCE = "source"
    EVENT = "event"
    RESTART = "restart"


@dataclass(frozen=True, slots=True)
class Entry:
    """One line of the record.

    - ``at``: the instant, in UTC.
    - ``window_id`` and ``member_id``: whom it concerns; a source change or a
      restart concerns nobody in particular.
    - ``summary``: the readable line.
    - ``target``: the target of a command, or of a decision that sends.
    - ``wish_class``: the class of the wish behind a command.
    - ``decision``: the whole decision, for a decision entry.
    - ``observation``: the normalized observation, for a report entry.
    """

    at: datetime
    kind: EntryKind
    summary: str
    window_id: str | None = None
    member_id: str | None = None
    target: Position | None = None
    wish_class: WishClass | None = None
    decision: Decision | None = field(default=None, repr=False)
    observation: Observation | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        """Keep the instant in UTC."""
        if self.at.tzinfo is None or self.at.utcoffset() is None:
            raise ValueError("an entry is recorded at a timezone-aware instant")
        object.__setattr__(self, "at", self.at.astimezone(UTC))

    def line(self, zone: tzinfo) -> str:
        """Return the entry as one line of the timeline, in the local zone."""
        local = self.at.astimezone(zone)
        stamp = local.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        offset = local.strftime("%z")
        subject = self.window_id or "-"
        if self.member_id is not None:
            subject = f"{subject} [{self.member_id}]"
        return f"{stamp} {offset}  {self.kind.value:<8}  {subject:<40}  {self.summary}"


def decision_summary(decision: Decision) -> str:
    """Return one readable line for a decision."""
    wish = decision.winning_wish
    if wish is None:
        return "no layer has an opinion"
    parts = [f"{wish.layer.value}: {wish.reason.value}"]
    if wish.position is not None:
        parts.append(f"wants {wish.position.value}")
    elif wish.member_positions:
        parts.append(
            "wants "
            + ", ".join(
                f"{target.member_id}={target.position.value}"
                for target in wish.member_positions
                if target.position is not None
            )
        )
    else:
        parts.append(f"({wish.kind.value})")
    for result in decision.constraints:
        parts.append(f"{result.constraint.value}: {result.reason.value}")
    gate = decision.gate
    if gate is None:
        if decision.targets:
            parts.append("every member pinned")
    else:
        text = f"{gate.kind.value}: {gate.reason.value}"
        if gate.would_send:
            text += " (would send " + ", ".join(
                f"{t.member_id}={t.position.value}"
                for t in gate.would_send
                if t.position is not None
            )
            text += ")"
        if gate.until is not None:
            text += f" until {gate.until.isoformat(timespec='seconds')}"
        if gate.reevaluate_no_later_than is not None:
            text += (
                " re-evaluate by "
                f"{gate.reevaluate_no_later_than.isoformat(timespec='seconds')}"
            )
        parts.append(text)
    if decision.faults:
        parts.append("faults: " + ", ".join(f.error for f in decision.faults))
    return " | ".join(parts)


class Record:
    """The entries of one run, in the order in which they were recorded."""

    def __init__(self, zone: tzinfo) -> None:
        """Start empty; ``zone`` is the local zone the timeline is printed in."""
        self.zone = zone
        self.entries: list[Entry] = []
        self.dropped_reports = 0
        """Reports that changed no observation and were not recorded."""

    def add(self, entry: Entry) -> None:
        """Append an entry; the order of the record is the order of recording."""
        self.entries.append(entry)

    def of_kind(self, kind: EntryKind, window_id: str | None = None) -> list[Entry]:
        """Return the entries of one kind, of one window if given."""
        return [
            entry
            for entry in self.entries
            if entry.kind is kind
            and (window_id is None or entry.window_id == window_id)
        ]

    def commands(self, window_id: str | None = None) -> list[Entry]:
        """Return the commands that were really sent."""
        return self.of_kind(EntryKind.COMMAND, window_id)

    def decisions(self, window_id: str | None = None) -> list[Entry]:
        """Return the decisions."""
        return self.of_kind(EntryKind.DECISION, window_id)

    def sends(self, window_id: str | None = None) -> list[Entry]:
        """Return the decisions whose gate said "send": one per movement."""
        return [
            entry
            for entry in self.decisions(window_id)
            if entry.decision is not None
            and entry.decision.gate is not None
            and entry.decision.gate.kind is GateKind.SEND
        ]

    def window_ids(self) -> list[str]:
        """Return the windows that appear in the record, in order of appearance."""
        seen: dict[str, None] = {}
        for entry in self.entries:
            if entry.window_id is not None:
                seen.setdefault(entry.window_id, None)
        return list(seen)

    def local_date(self, entry: Entry) -> date:
        """Return the local date of an entry."""
        return entry.at.astimezone(self.zone).date()

    def between(
        self, since: datetime | None, until: datetime | None
    ) -> Iterator[Entry]:
        """Return the entries inside a span of time."""
        for entry in self.entries:
            if since is not None and entry.at < since.astimezone(UTC):
                continue
            if until is not None and entry.at > until.astimezone(UTC):
                continue
            yield entry

    def timeline(
        self,
        *,
        window_id: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        kinds: Iterable[EntryKind] | None = None,
    ) -> str:
        """Return the readable timeline, filtered by window, span and kinds."""
        wanted = None if kinds is None else set(kinds)
        lines = [
            entry.line(self.zone)
            for entry in self.between(since, until)
            if (window_id is None or entry.window_id in (window_id, None))
            and (wanted is None or entry.kind in wanted)
        ]
        return "\n".join(lines)

    def around(
        self,
        moment: datetime,
        *,
        window_id: str | None = None,
        span: timedelta | None = None,
    ) -> str:
        """Return the timeline around a moment, for the message of a failed assertion."""
        half = timedelta(minutes=15) if span is None else span
        return self.timeline(
            window_id=window_id, since=moment - half, until=moment + half
        )
