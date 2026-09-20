"""The schedule layer: the wish of the current part of the day, and its facts.

:func:`evaluate_schedule` is a pure function. It reads the time from the world
snapshot, asks the sun port for sun times, and keeps nothing between calls:
what has to survive is returned as the new persisted state. It never asks
whether a trigger "was seen". For any point in time it states which part of
the day it is; the direction of the wish does the rest, because the day target
only raises and the night target only lowers.
"""

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from enum import StrEnum, unique
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    DayType,
    Direction,
    HeldInput,
    LatchedDayType,
    Layer,
    Position,
    WindowConfig,
    WindowState,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.ports import Sun
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .day_types import (
    day_type_by_weekday,
    day_type_from_inputs,
    read_number,
    read_switch,
)
from .local_time import as_instant, local_date, local_instant, zone_of
from .settings import DayOfYear, ScheduleSettings, ScheduleTargets
from .triggers import Edge, random_offset, trigger_instant

_LOOK_AHEAD_DAYS: Final = 8
"""How many local dates the next planned action is searched on: a week and a day."""

SCHEDULE_NOT_CONFIGURED: Final = Wish.no_opinion(
    Layer.SCHEDULE, ReasonCode.NOT_CONFIGURED
)
"""The answer of the schedule layer for a window without schedule settings."""


@unique
class PartOfDay(StrEnum):
    """The two parts of the day."""

    DAY = "day"
    NIGHT = "night"


@dataclass(frozen=True, slots=True)
class PlannedAction:
    """The next change of the schedule: when, to which target, and why.

    ``at`` is an instant in UTC. ``reason`` is ``schedule_day`` or
    ``schedule_night``. It is what the schedule will wish then, not a promise
    that the window moves: a higher layer, a constraint or the gate may decide
    otherwise, and the wish only raises or only lowers.
    """

    at: datetime
    target: Position
    reason: ReasonCode


@dataclass(frozen=True, slots=True)
class ScheduleResult:
    """What the schedule says for one world snapshot.

    - ``evaluated_at``: the time of the snapshot as an instant in UTC.
    - ``wish``: the wish of the schedule layer.
    - ``part_of_day``, ``morning_trigger``, ``evening_trigger``: the part of
      the day and today's two triggers as instants in UTC. The evening trigger
      is the effective one; ``evening_by_brightness`` says whether the
      brightness began the evening before the time did.
    - ``part_of_day_since``: the instant at which the current part of the day
      really began, never later than ``evaluated_at``: the boundary as it was
      moved by an offset, a clamp, the random offset, the day type or the
      brightness, not the first evaluation that noticed it. Before today's
      morning trigger it is yesterday's evening; that one is exact as long as
      yesterday's latch and brightness instant are still in the persisted
      state, otherwise it is computed with the day of the week.
    - ``day_type``: today's day type. ``day_type_latched`` says whether it is
      fixed for the date; until then it is a preview that may correct itself
      with every evaluation. ``day_type_reason`` is ``day_type_fallback``
      while the day of the week stands in for an input without a value.
    - ``summer``: the season the evening position was chosen by, ``None``
      without a seasonal setup. ``season_reason`` says when it is not a fresh
      value: ``input_held_last_known``, or why the source counts for nothing.
    - ``brightness_reason``: why the brightness source gives no value now.
    - ``next_action``: the next planned action, or ``None`` if none lies within
      the next days.
    - ``recheck_at``: an instant at which the window has to be evaluated
      again although no planned action is due: the brightness will have been
      low for long enough then. It lies strictly after ``evaluated_at``, or it
      is ``None``; a result that says otherwise cannot be constructed.
    - ``state``: the persisted window state with what the schedule has to
      remember. The caller persists it; it equals the state of the snapshot
      if nothing changed.
    """

    evaluated_at: datetime
    wish: Wish
    part_of_day: PartOfDay
    part_of_day_since: datetime
    morning_trigger: datetime
    evening_trigger: datetime
    evening_by_brightness: bool
    day_type: DayType
    day_type_latched: bool
    day_type_reason: ReasonCode | None
    summer: bool | None
    season_reason: ReasonCode | None
    brightness_reason: ReasonCode | None
    next_action: PlannedAction | None
    recheck_at: datetime | None
    state: WindowState

    def __post_init__(self) -> None:
        """Refuse a wake-up time that is not strictly in the future."""
        if self.recheck_at is not None and self.recheck_at <= self.evaluated_at:
            raise ValueError(
                "the time of a recheck lies strictly after the time of the snapshot"
            )
        if self.part_of_day_since > self.evaluated_at:
            raise ValueError("a part of the day cannot have begun in the future")


def morning_condition_fulfilled(window: WindowConfig, snapshot: WorldSnapshot) -> bool:
    """Return whether the condition of the morning opening holds: always.

    This is the place where a conditional morning opening will read
    ``WindowConfig.morning_condition_source`` from the snapshot. Until that
    feature exists the condition is fulfilled, whatever the source reports.
    """
    del window, snapshot
    return True


@dataclass(frozen=True, slots=True)
class _Context:
    """What stays the same during one evaluation.

    ``now`` is the time of the snapshot as an instant in UTC, ``today`` the
    local date of that time, ``zone`` the local zone.
    """

    settings: ScheduleSettings
    snapshot: WorldSnapshot
    window_id: str
    seed: int
    sun: Sun
    zone: tzinfo
    now: datetime
    today: date


@dataclass(frozen=True, slots=True)
class _DayPlan:
    """The two triggers of one local date; the evening never precedes the morning."""

    morning: datetime
    evening: datetime


def _plan(context: _Context, day: date, day_type: DayType) -> _DayPlan:
    triggers = context.settings.triggers_for(day_type)
    morning, evening = (
        trigger_instant(
            trigger,
            edge,
            day,
            zone=context.zone,
            sun=context.sun,
            offset=random_offset(
                context.seed,
                context.window_id,
                day,
                edge,
                context.settings.random_offset,
            ),
        )
        for trigger, edge in (
            (triggers.morning, Edge.MORNING),
            (triggers.evening, Edge.EVENING),
        )
    )
    return _DayPlan(morning=morning, evening=max(morning, evening))


def _latch_of(state: WindowState, day: date) -> LatchedDayType | None:
    for latch in state.latched_day_types:
        if latch.day == day:
            return latch
    return None


def _day_type_today(context: _Context) -> tuple[LatchedDayType | None, DayType, bool]:
    """Return today's latch if it is or becomes set, the day type, "fallback".

    The day type latches at the first boundary between parts of the day of
    the date, which is the morning trigger, and not before: a workday sensor
    is updated at midnight or shortly after it, and an evaluation before that
    update must not write yesterday's value down for the whole day. Until the
    morning trigger the day type is a preview that follows the inputs, or the
    day of the week while they have no value, and may correct itself with
    every evaluation. The first evaluation at or after the morning trigger of
    the preview fixes it; if the day of the week stood in at that moment, the
    latch is marked as a fallback, and an input that comes back later cannot
    move the morning trigger after the fact.
    """
    today = context.today
    latch = _latch_of(context.snapshot.state, today)
    if latch is not None:
        return latch, latch.day_type, latch.fallback
    from_inputs = day_type_from_inputs(
        context.settings, context.snapshot.sources, today
    )
    fallback = from_inputs is None
    preview = day_type_by_weekday(today) if from_inputs is None else from_inputs
    if context.now >= _plan(context, today, preview).morning:
        return LatchedDayType(today, preview, fallback=fallback), preview, fallback
    return None, preview, fallback


def _kept_latches(
    context: _Context, latch: LatchedDayType | None
) -> tuple[LatchedDayType, ...]:
    """Return the latches to persist.

    Today's and tomorrow's if there is one. Until today's is set, yesterday's
    is kept in its place: the night that is still running began with
    yesterday's evening trigger.
    """
    tomorrow = context.today + timedelta(days=1)
    keep_instead = context.today - timedelta(days=1) if latch is None else None
    kept = [
        entry
        for entry in context.snapshot.state.latched_day_types
        if entry.day in (keep_instead, tomorrow)
    ]
    if latch is not None:
        kept.insert(0, latch)
    return tuple(kept)


@dataclass(frozen=True, slots=True)
class _Season:
    """The season now, why it is not a fresh value, and what to remember."""

    summer: bool | None
    reason: ReasonCode | None
    held: HeldInput | None


def _in_summer_range(day: date, first: DayOfYear, last: DayOfYear) -> bool:
    current = DayOfYear.of(day)
    if first <= last:
        return first <= current <= last
    return current >= first or current <= last


def _season(context: _Context) -> _Season:
    """Return the season: the source, else its last known value, else the dates.

    The held value is renewed when the source reports another value than the
    one that is held, not at every evaluation: nothing depends on its age, and
    a state that does not change needs no write.
    """
    settings = context.settings
    held = context.snapshot.state.held_season
    reason: ReasonCode | None = None
    if settings.season_source is not None:
        value, reason = read_switch(context.snapshot.sources, settings.season_source)
        if value is not None:
            if held is None or held.value != value:
                held = HeldInput(value=value, seen_at=context.now)
            return _Season(value, None, held)
        if held is not None:
            return _Season(held.value, ReasonCode.INPUT_HELD_LAST_KNOWN, held)
    summer_range = settings.summer_range
    if summer_range is None:
        return _Season(None, reason, held)
    return _Season(_in_summer_range(context.today, *summer_range), reason, held)


@dataclass(frozen=True, slots=True)
class _Brightness:
    """The brightness trigger after this evaluation.

    ``evening_at`` is today's evening begun by the brightness. ``last_night``
    is yesterday's, kept until today's morning trigger, because the night
    that is still running began with it.
    """

    below_since: datetime | None = None
    evening_at: datetime | None = None
    reason: ReasonCode | None = None
    recheck_at: datetime | None = None
    last_night: datetime | None = None


def _brightness(context: _Context, plan: _DayPlan, day_type: DayType) -> _Brightness:
    """Return what the brightness source does to this evening.

    The evening begins early once the brightness has been below its threshold
    for the configured time, but not before "not before" of the evening
    trigger and only ahead of the time-based trigger. The instant is kept, so
    a brightness that rises again, or a source that drops out, does not bring
    the day back. A source without a value is not "dark": the time since when
    it was dark is dropped, and the time-based trigger stays as it is.
    """
    settings = context.settings
    threshold = settings.brightness_threshold
    not_before = settings.triggers_for(day_type).evening.not_before
    if settings.brightness_source is None or threshold is None or not_before is None:
        return _Brightness()
    state = context.snapshot.state
    evening_at = state.evening_brightness_at
    last_night = None
    if evening_at is not None:
        lies_on = local_date(evening_at, context.zone)
        yesterday = context.today - timedelta(days=1)
        if lies_on == yesterday and context.now < plan.morning:
            last_night = evening_at
        if lies_on != context.today or evening_at >= plan.evening:
            evening_at = None
    level, reason = read_number(context.snapshot.sources, settings.brightness_source)
    below_since = state.brightness_below_since
    if level is None or level >= threshold:
        below_since = None
    elif below_since is None:
        below_since = context.now
    recheck_at = None
    if evening_at is None and below_since is not None:
        due = max(
            below_since + settings.brightness_delay,
            local_instant(context.today, not_before, context.zone),
            plan.morning,
        )
        if due < plan.evening:
            if due <= context.now:
                evening_at = due
            else:
                recheck_at = due
    return _Brightness(below_since, evening_at, reason, recheck_at, last_night)


def _next_action(
    context: _Context,
    state: WindowState,
    today_plan: _DayPlan,
    targets: ScheduleTargets,
    season: _Season,
) -> PlannedAction | None:
    """Return the first change of the part of the day after now.

    Today counts with its effective triggers. A later date counts with its
    latched day type if it has one, otherwise with the day of the week: that
    is a forecast; it is final when that date's day type latches.

    A date whose two triggers coincide has no part ``day`` and therefore no
    action; that takes a random offset that swaps two triggers set seconds
    apart. An evening can be the next action only today: on every later date
    the morning comes first.
    """
    morning = PlannedAction(
        today_plan.morning, targets.morning_position, ReasonCode.SCHEDULE_DAY
    )
    if today_plan.morning < today_plan.evening:
        if today_plan.morning > context.now:
            return morning
        if today_plan.evening > context.now:
            return PlannedAction(
                today_plan.evening,
                targets.evening(summer=season.summer),
                ReasonCode.SCHEDULE_NIGHT,
            )
    for ahead in range(1, _LOOK_AHEAD_DAYS):
        day = context.today + timedelta(days=ahead)
        latch = _latch_of(state, day)
        day_type = day_type_by_weekday(day) if latch is None else latch.day_type
        plan = _plan(context, day, day_type)
        if plan.morning < plan.evening:
            return replace(morning, at=plan.morning)
    return None


def _night_since(
    context: _Context, plan: _DayPlan, brightness: _Brightness
) -> datetime:
    """Return the instant at which the night that is running now began.

    After today's evening trigger that is the effective evening trigger. Before
    today's morning trigger the night began yesterday: with the evening the
    brightness began, if its instant is still kept, otherwise with the
    time-based evening trigger of yesterday's day type, latched or by the day
    of the week.
    """
    if plan.morning < plan.evening <= context.now:
        return plan.evening
    yesterday = context.today - timedelta(days=1)
    latch = _latch_of(context.snapshot.state, yesterday)
    day_type = day_type_by_weekday(yesterday) if latch is None else latch.day_type
    last_night = _plan(context, yesterday, day_type)
    evening = last_night.evening
    if brightness.last_night is not None:
        evening = min(evening, brightness.last_night)
    return max(evening, last_night.morning)


def evaluate_schedule(
    settings: ScheduleSettings,
    window: WindowConfig,
    snapshot: WorldSnapshot,
    sun: Sun,
    *,
    seed: int,
) -> ScheduleResult:
    """Return the wish of the schedule and its facts for one world snapshot.

    ``seed`` is the installation's seed for random offsets (storage port).
    The local zone is the zone of ``snapshot.time``. The function reads no
    clock and keeps nothing: the same arguments give the same result.
    """
    context = _Context(
        settings=settings,
        snapshot=snapshot,
        window_id=window.window_id,
        seed=seed,
        sun=sun,
        zone=zone_of(snapshot.time),
        now=as_instant(snapshot.time, "the time of the snapshot"),
        today=snapshot.time.date(),
    )
    targets = settings.targets_for(window.schedule_profile)

    latch, day_type, fallback = _day_type_today(context)
    plan = _plan(context, context.today, day_type)
    brightness = _brightness(context, plan, day_type)
    if brightness.evening_at is not None:
        plan = _DayPlan(plan.morning, max(brightness.evening_at, plan.morning))
    season = _season(context)

    is_day = plan.morning <= context.now < plan.evening
    is_day = is_day and morning_condition_fulfilled(window, snapshot)
    if is_day:
        wish = Wish.target(
            Layer.SCHEDULE,
            ReasonCode.SCHEDULE_DAY,
            targets.morning_position,
            direction=Direction.RAISE_ONLY,
        )
    else:
        wish = Wish.target(
            Layer.SCHEDULE,
            ReasonCode.SCHEDULE_NIGHT,
            targets.evening(summer=season.summer),
            direction=Direction.LOWER_ONLY,
        )

    state = replace(
        snapshot.state,
        latched_day_types=_kept_latches(context, latch),
        held_season=season.held,
        brightness_below_since=brightness.below_since,
        evening_brightness_at=brightness.evening_at or brightness.last_night,
    )
    return ScheduleResult(
        evaluated_at=context.now,
        wish=wish,
        part_of_day=PartOfDay.DAY if is_day else PartOfDay.NIGHT,
        part_of_day_since=(
            plan.morning if is_day else _night_since(context, plan, brightness)
        ),
        morning_trigger=plan.morning,
        evening_trigger=plan.evening,
        evening_by_brightness=brightness.evening_at is not None,
        day_type=day_type,
        day_type_latched=latch is not None,
        day_type_reason=ReasonCode.DAY_TYPE_FALLBACK if fallback else None,
        summer=season.summer,
        season_reason=season.reason,
        brightness_reason=brightness.reason,
        next_action=_next_action(context, state, plan, targets, season),
        recheck_at=brightness.recheck_at,
        state=state,
    )
