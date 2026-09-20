"""The schedule: parts of the day, triggers, day types, and the schedule layer.

Section 6 of ``docs/architecture.md`` in code. The schedule is state-based: it
fires no events that could be missed. :func:`evaluate_schedule` says for the
time of a world snapshot which part of the day it is and what the schedule
layer wishes; ``docs/dev/schedule.md`` explains the rules.

Import from the package. Its modules depend on each other in one direction:
``settings`` and ``local_time`` depend on none of the others; ``triggers``
uses both, ``day_types`` uses ``settings``, and ``layer`` uses all of them.
"""

from .day_types import day_type_by_weekday, day_type_from_inputs
from .layer import (
    SCHEDULE_NOT_CONFIGURED,
    PartOfDay,
    PlannedAction,
    ScheduleResult,
    evaluate_schedule,
    morning_condition_fulfilled,
)
from .local_time import local_instant
from .settings import (
    MAX_RANDOM_OFFSET,
    DayOfYear,
    DayTriggers,
    ScheduleSettings,
    ScheduleTargets,
    Trigger,
    TriggerKind,
)
from .triggers import Edge, random_offset, trigger_instant

__all__ = [
    "MAX_RANDOM_OFFSET",
    "SCHEDULE_NOT_CONFIGURED",
    "DayOfYear",
    "DayTriggers",
    "Edge",
    "PartOfDay",
    "PlannedAction",
    "ScheduleResult",
    "ScheduleSettings",
    "ScheduleTargets",
    "Trigger",
    "TriggerKind",
    "day_type_by_weekday",
    "day_type_from_inputs",
    "evaluate_schedule",
    "local_instant",
    "morning_condition_fulfilled",
    "random_offset",
    "trigger_instant",
]
