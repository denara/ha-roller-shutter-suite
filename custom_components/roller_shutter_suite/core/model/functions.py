"""The functions of the integration: one closed list of identifiers.

A function is what a user switches on and configures: the schedule, shading,
frost protection. The settings registry, the layer, constraint and gate rule
registrations of the arbiter and the disabled functions of a window all name
functions by the members of ``FunctionId``; there are no free strings.

Every function has a fault behavior: what happens to it for a window when one
of its stored settings is faulty. What decides is the direction of the effect.
A function that **creates wishes** is paused: no wish, less movement, the
cautious side. A function that **restricts movement** (a constraint, a gate
rule) falls back to the value of the next level and keeps working: pausing a
restriction would mean more movement, a shutter closing completely in front of
a tilted window because of a data fault. The two behaviors are named by what
they do, so they cannot be confused with the wish classes of the arbiter.

The member list is provisional, the shape is not: a block that builds a new
function adds its member, with its fault behavior, in its own pull request.
"""

from enum import StrEnum, unique


@unique
class FaultBehavior(StrEnum):
    """What happens to a function when one of its stored settings is faulty."""

    FALL_BACK = "fall_back"
    PAUSE = "pause"


@unique
class FunctionId(StrEnum):
    """The closed list of function identifiers."""

    SCHEDULE = "schedule"
    SLEEP = "sleep"
    REQUEST = "request"
    PRIVACY = "privacy"
    SHADING = "shading"
    SOLAR_HEATING = "solar_heating"
    VENTILATION = "ventilation"
    FIRE = "fire"
    PROTECTION_EVENTS = "protection_events"
    LOCKOUT = "lockout"
    FROST = "frost"
    MOTOR_PROTECTION = "motor_protection"
    COMMAND_VERIFICATION = "command_verification"
    MANUAL_OVERRIDE = "manual_override"

    @property
    def fault_behavior(self) -> FaultBehavior:
        """Return what happens to the function when a stored setting is faulty."""
        if self in _PAUSED_ON_A_FAULT:
            return FaultBehavior.PAUSE
        return FaultBehavior.FALL_BACK


_PAUSED_ON_A_FAULT = frozenset(
    {
        FunctionId.SCHEDULE,
        FunctionId.SLEEP,
        FunctionId.REQUEST,
        FunctionId.PRIVACY,
        FunctionId.SHADING,
        FunctionId.SOLAR_HEATING,
    }
)
"""The functions that create wishes; every other function falls back."""
