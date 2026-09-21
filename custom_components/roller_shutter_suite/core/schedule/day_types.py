"""The day type of a date from the day-type inputs, and reading those inputs.

Missing data is not good news: a source that is unknown, unavailable, absent
from the snapshot or of the wrong type yields no value here, together with the
reason code that says why. Nothing turns it into "off".
"""

from collections.abc import Mapping
from datetime import date
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    DayType,
    ScheduleSettings,
    SourceState,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

_SATURDAY: Final = 5


def _missing_reason(sources: Mapping[str, AnySourceValue], key: str) -> ReasonCode:
    source = sources.get(key)
    if source is not None and source.state is SourceState.UNKNOWN:
        return ReasonCode.INPUT_UNKNOWN
    return ReasonCode.INPUT_UNAVAILABLE


def read_switch(
    sources: Mapping[str, AnySourceValue], key: str
) -> tuple[bool | None, ReasonCode | None]:
    """Return the value of an on/off source, or no value and the reason.

    A source that is not part of the snapshot counts as unavailable. A value
    that is not a boolean is a fault of the adapter; it counts as unknown.
    """
    source = sources.get(key)
    if source is None or not source.has_value:
        return None, _missing_reason(sources, key)
    value = source.value
    if isinstance(value, bool):
        return value, None
    return None, ReasonCode.INPUT_UNKNOWN


def read_number(
    sources: Mapping[str, AnySourceValue], key: str
) -> tuple[float | None, ReasonCode | None]:
    """Return the value of a numeric source, or no value and the reason."""
    source = sources.get(key)
    if source is None or not source.has_value:
        return None, _missing_reason(sources, key)
    value = source.value
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None, ReasonCode.INPUT_UNKNOWN
    return float(value), None


def day_type_by_weekday(day: date) -> DayType:
    """Return rule 3: Monday to Friday is a workday, the rest is weekend."""
    return DayType.WEEKEND if day.weekday() >= _SATURDAY else DayType.WORKDAY


def day_type_from_inputs(
    settings: ScheduleSettings, sources: Mapping[str, AnySourceValue], day: date
) -> DayType | None:
    """Return the day type the inputs give for today, or ``None``.

    ``None`` means that an input the rules need has no value at the moment.
    The rules, in order: holiday source on is a holiday; otherwise the workday
    source decides; without a workday source the day of the week decides. A
    holiday source that reports "on" decides alone, whatever the workday
    source says or lacks.
    """
    if settings.holiday_source is not None:
        holiday, _ = read_switch(sources, settings.holiday_source)
        if holiday is None:
            return None
        if holiday:
            return DayType.HOLIDAY
    if settings.workday_source is None:
        return day_type_by_weekday(day)
    workday, _ = read_switch(sources, settings.workday_source)
    if workday is None:
        return None
    return DayType.WORKDAY if workday else DayType.WEEKEND
