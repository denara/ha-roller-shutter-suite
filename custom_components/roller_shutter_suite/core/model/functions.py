"""The functions of the integration: one closed list for settings, layers and faults.

A function is what a user would call a feature: the schedule, shading, frost
protection. Its identifier is used wherever something belongs to a function:
a setting in the registry of the inheritance resolver, a layer, a constraint
or a gate rule of the arbiter, and the functions that are paused for a window
because a stored setting of theirs is faulty. There are no free strings for
this.

The list is closed, and provisional in its members only: a block that needs a
function adds a member here, with its fault behavior, in its own pull request.
"""

from enum import StrEnum, unique
from typing import Final


@unique
class FaultBehavior(StrEnum):
    """What a function does when a stored setting of it is faulty.

    What decides is the **direction of the effect**. A paused layer creates no
    wish: less movement, which is cautious. A paused constraint or gate rule
    removes a restriction: more movement, the wrong direction (a data fault
    would let a shutter close completely in front of a tilted window).

    - ``FALL_BACK``: every function that protects people or hardware or that
      **restricts** movement. It is never paused. A faulty setting is passed
      by, and the next level supplies the value, last the built-in default.
    - ``PAUSE``: only functions that **create** wishes for convenience. A
      faulty setting pauses the function for the windows the fault reaches,
      because falling back to another value could make a window do what was
      explicitly excluded.

    This is not the wish class of the arbiter (fire, protection, comfort):
    ventilation is a comfort feature and still falls back, because it
    restricts movement.
    """

    FALL_BACK = "fall_back"
    PAUSE = "pause"


@unique
class FunctionId(StrEnum):
    """The functions of the integration, each with one fault behavior.

    **The order of the members has meaning.** The arbiter asks the parts of
    one layer in the order in which the functions are defined here, so
    reordering the members, or inserting one between two others, changes
    behavior. Add a new member deliberately, at the place where its parts
    shall be asked; a test pins names, values and order.
    """

    # The order has meaning, see the docstring: the arbiter evaluates the parts
    # of a layer in this order. Do not sort, do not insert without intent.
    SCHEDULE = "schedule"
    SLEEP = "sleep"
    REQUEST = "request"
    PRIVACY = "privacy"
    SHADING = "shading"
    SOLAR_HEATING = "solar_heating"
    FIRE = "fire"
    PROTECTION_EVENTS = "protection_events"
    """Like fire, they create wishes too, but they protect: never paused."""
    LOCKOUT = "lockout"
    """Blocking contacts and the tamper contact."""
    VENTILATION = "ventilation"
    """The floor under comfort wishes while a window is open or tilted,
    including rain while ventilating. It restricts movement."""
    FROST = "frost"
    MOTOR_PROTECTION = "motor_protection"
    COMMAND_VERIFICATION = "command_verification"
    MANUAL_OVERRIDE = "manual_override"
    """Detecting a movement by hand, and the two dams. A fault there must never
    make the integration fight a person."""

    @property
    def fault_behavior(self) -> FaultBehavior:
        """Return what the function does when a stored setting of it is faulty."""
        return _BEHAVIOR[self]


_BEHAVIOR: Final = {
    FunctionId.SCHEDULE: FaultBehavior.PAUSE,
    FunctionId.SLEEP: FaultBehavior.PAUSE,
    FunctionId.REQUEST: FaultBehavior.PAUSE,
    FunctionId.PRIVACY: FaultBehavior.PAUSE,
    FunctionId.SHADING: FaultBehavior.PAUSE,
    FunctionId.SOLAR_HEATING: FaultBehavior.PAUSE,
    FunctionId.FIRE: FaultBehavior.FALL_BACK,
    FunctionId.PROTECTION_EVENTS: FaultBehavior.FALL_BACK,
    FunctionId.LOCKOUT: FaultBehavior.FALL_BACK,
    FunctionId.VENTILATION: FaultBehavior.FALL_BACK,
    FunctionId.FROST: FaultBehavior.FALL_BACK,
    FunctionId.MOTOR_PROTECTION: FaultBehavior.FALL_BACK,
    FunctionId.COMMAND_VERIFICATION: FaultBehavior.FALL_BACK,
    FunctionId.MANUAL_OVERRIDE: FaultBehavior.FALL_BACK,
}
