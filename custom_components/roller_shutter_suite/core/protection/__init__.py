"""Protection: the fire layer, the protection events, the return and the watchdog.

Block C07, section 10 of the specification. ``docs/dev/protection.md``
explains the trigger state machine, the life cycle of an event from its start
to the return, the watchdog, the fire layer and its acknowledgement, and how
the Home Assistant layer feeds the sources in.

- :mod:`.trigger`: what a trigger source says (active, inactive, unknown).
- :mod:`.blind`: the clock of a source without a value, one for every kind.
- :mod:`.events`: the life cycle of an event, the return, the watchdog.
- :mod:`.layer`: layer 2, the protection events.
- :mod:`.fire`: layer 1, the fire alarm and its acknowledgement.
"""

from .blind import advance_blind_clock, blind_wake_up, is_blind
from .events import (
    NOTHING_REMEMBERED,
    Remembered,
    advance_event,
    in_order_of_rank,
    judge_event,
    protection_after,
    protection_wake_ups,
    return_applies,
)
from .fire import (
    FIRE_LAYER,
    acknowledge_fire,
    fire_after,
    fire_alarm_active,
    fire_layer,
    fire_wake_ups,
)
from .layer import PROTECTION_LAYER, held_reason, protection_layer
from .trigger import Reading, read_trigger

__all__ = [
    "FIRE_LAYER",
    "NOTHING_REMEMBERED",
    "PROTECTION_LAYER",
    "Reading",
    "Remembered",
    "acknowledge_fire",
    "advance_blind_clock",
    "advance_event",
    "blind_wake_up",
    "fire_after",
    "fire_alarm_active",
    "fire_layer",
    "fire_wake_ups",
    "held_reason",
    "in_order_of_rank",
    "is_blind",
    "judge_event",
    "protection_after",
    "protection_layer",
    "protection_wake_ups",
    "read_trigger",
    "return_applies",
]
