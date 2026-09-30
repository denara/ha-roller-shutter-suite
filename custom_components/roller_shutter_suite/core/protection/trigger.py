"""The trigger of a protection event: active, inactive, unknown (section 10.1).

A trigger has three states. **Active** and **inactive** come from a value of
the source. **Unknown** (the source is unavailable or unknown, missing from
the snapshot, delivers a value of the wrong kind, or the stored trigger is
faulty) changes nothing: an active event stays active, an inactive one stays
inactive (D6). A number inside the hysteresis band of a threshold changes
nothing either, but it is a value: the source is not blind.

The same reading serves the fire source, which is an on/off source.
"""

import math
from enum import StrEnum, unique

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    ProtectionTrigger,
    SourceState,
    TriggerType,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode


@unique
class Reading(StrEnum):
    """What the source of a trigger says now."""

    ACTIVE = "active"
    INACTIVE = "inactive"
    HOLD = "hold"
    """A number inside the hysteresis band: the persisted state holds."""
    UNKNOWN = "unknown"
    """No value that can be judged: the persisted state holds (D6)."""

    @property
    def has_value(self) -> bool:
        """Return whether the source delivered a value that could be judged."""
        return self is not Reading.UNKNOWN


def _as_text(value: object) -> str:
    """Return the text of a state: ``on``/``off`` for a switch, a whole number without fraction."""
    if isinstance(value, bool):
        return "on" if value else "off"
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def read_trigger(
    trigger: ProtectionTrigger | None, value: AnySourceValue | None
) -> Reading:
    """Return what the source of a trigger says; ``value`` is its source value.

    ``None`` as the trigger is a faulty stored trigger, and ``None`` as the
    value a source that the snapshot does not contain; both are unknown.
    """
    if trigger is None or value is None or not value.has_value:
        return Reading.UNKNOWN
    delivered = value.value
    if trigger.kind is TriggerType.STATES:
        return (
            Reading.ACTIVE
            if _as_text(delivered) in trigger.states
            else Reading.INACTIVE
        )
    if trigger.kind is TriggerType.BINARY:
        if not isinstance(delivered, bool):
            return Reading.UNKNOWN
        return Reading.ACTIVE if delivered is not trigger.invert else Reading.INACTIVE
    return _read_threshold(trigger, _number(delivered))


def _read_threshold(trigger: ProtectionTrigger, number: float | None) -> Reading:
    """Read a number against the threshold and its hysteresis band.

    ``beyond`` is how far the number lies on the active side of the
    threshold: above it, or below it for an inverted trigger.
    """
    if number is None:
        return Reading.UNKNOWN
    beyond = (
        trigger.threshold - number if trigger.invert else number - trigger.threshold
    )
    if beyond >= 0:
        return Reading.ACTIVE
    if beyond < -trigger.hysteresis:
        return Reading.INACTIVE
    return Reading.HOLD


def missing_reason(value: AnySourceValue | None) -> ReasonCode:
    """Return why a source has no value that can be judged."""
    if value is not None and value.state is SourceState.UNKNOWN:
        return ReasonCode.INPUT_UNKNOWN
    if value is not None and value.has_value:
        # A value of the wrong kind: the adapter's fault, it counts as unknown.
        return ReasonCode.INPUT_UNKNOWN
    return ReasonCode.INPUT_UNAVAILABLE
