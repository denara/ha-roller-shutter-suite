"""The functions of the integration: one closed list of identifiers.

A function is what a user switches on and configures: the schedule, shading,
frost protection. The settings registry, the layer and constraint
registrations of the arbiter and the disabled functions of a window all name
functions by the members of ``FunctionId``; there are no free strings.

Every function has a class. A comfort function can be disabled for a window
when one of its stored settings is faulty; a protection function never is.

The member list is provisional, the shape is not: a block that builds a new
function adds its member, with its class, in its own pull request.
"""

from enum import StrEnum, unique


@unique
class FunctionClass(StrEnum):
    """Whether a function protects something or serves comfort."""

    PROTECTION = "protection"
    COMFORT = "comfort"


@unique
class FunctionId(StrEnum):
    """The closed list of function identifiers."""

    # Comfort
    SCHEDULE = "schedule"
    SLEEP = "sleep"
    REQUEST = "request"
    PRIVACY = "privacy"
    SHADING = "shading"
    SOLAR_HEATING = "solar_heating"
    VENTILATION = "ventilation"

    # Protection
    FIRE = "fire"
    PROTECTION_EVENTS = "protection_events"
    LOCKOUT = "lockout"
    FROST = "frost"
    MOTOR_PROTECTION = "motor_protection"
    COMMAND_VERIFICATION = "command_verification"
    MANUAL_OVERRIDE = "manual_override"

    @property
    def function_class(self) -> FunctionClass:
        """Return the class of the function."""
        if self in _COMFORT_FUNCTIONS:
            return FunctionClass.COMFORT
        return FunctionClass.PROTECTION


_COMFORT_FUNCTIONS = frozenset(
    {
        FunctionId.SCHEDULE,
        FunctionId.SLEEP,
        FunctionId.REQUEST,
        FunctionId.PRIVACY,
        FunctionId.SHADING,
        FunctionId.SOLAR_HEATING,
        FunctionId.VENTILATION,
    }
)
