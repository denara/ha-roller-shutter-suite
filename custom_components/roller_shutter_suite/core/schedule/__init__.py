"""The schedule: parts of the day, triggers, day types, and the schedule layer.

Section 6 of ``docs/architecture.md`` in code. The schedule is state-based: it
fires no events that could be missed. :func:`evaluate_schedule` says for the
time of a world snapshot which part of the day it is and what the schedule
layer wishes; :data:`SCHEDULE_LAYER` registers it with the arbiter;
``docs/dev/schedule.md`` explains the rules. The settings of the schedule are
values of the model (``WindowConfig.schedule``).

Import from the package. Its modules depend on each other in one direction:
``local_time`` depends on none of the others; ``sun`` uses it, ``triggers``
uses both, ``day_types`` stands alone, and ``layer`` uses all of them.
"""

from .day_types import day_type_by_weekday, day_type_from_inputs
from .layer import (
    SCHEDULE_LAYER,
    SCHEDULE_NOT_CONFIGURED,
    PartOfDay,
    PlannedAction,
    ScheduleResult,
    evaluate_schedule,
    morning_condition_fulfilled,
    schedule_layer,
    schedule_state_after,
)
from .local_time import local_instant
from .sun import (
    ALMANAC_DAYS_AHEAD,
    ALMANAC_DAYS_BEFORE,
    AlmanacSun,
    PortSun,
    ScheduleInputMissingError,
    build_sun_almanac,
)
from .triggers import Edge, random_offset, trigger_instant

__all__ = [
    "ALMANAC_DAYS_AHEAD",
    "ALMANAC_DAYS_BEFORE",
    "SCHEDULE_LAYER",
    "SCHEDULE_NOT_CONFIGURED",
    "AlmanacSun",
    "Edge",
    "PartOfDay",
    "PlannedAction",
    "PortSun",
    "ScheduleInputMissingError",
    "ScheduleResult",
    "build_sun_almanac",
    "day_type_by_weekday",
    "day_type_from_inputs",
    "evaluate_schedule",
    "local_instant",
    "morning_condition_fulfilled",
    "random_offset",
    "schedule_layer",
    "schedule_state_after",
    "trigger_instant",
]
