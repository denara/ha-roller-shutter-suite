"""Reason codes: the closed list of machine-readable reasons.

Every wish, constraint result, gate outcome and event carries one of these
codes and never free text. The list and its five groups are exactly those of
section 5 of ``docs/architecture.md``. An event with a variable subject (which
protection event, which member, which source) carries the subject as a separate
attribute, never inside the code.

No code claims that a curtain has arrived: with a calculated position the
integration can only know that an actuator did not react.
"""

from enum import StrEnum, unique
from types import MappingProxyType
from typing import Final


@unique
class ReasonCategory(StrEnum):
    """The five groups in which the architecture document lists the codes."""

    LAYER = "layer"
    """A winning or contributing layer."""

    LAYER_INACTIVE = "layer_inactive"
    """Why a layer did not act."""

    CONSTRAINT = "constraint"
    """A constraint that limited, pinned or deliberately spared the winning wish."""

    GATE = "gate"
    """The outcome of the gate."""

    EVENT = "event"
    """Movement tracker and life cycle; these codes appear in events only."""


@unique
class ReasonCode(StrEnum):
    """Closed enumeration of all reason codes."""

    # Winning or contributing layers
    FIRE_ALARM = "fire_alarm"
    FIRE_UNACKNOWLEDGED = "fire_unacknowledged"
    PROTECTION_EVENT = "protection_event"
    PROTECTION_RETURN_MANUAL = "protection_return_manual"
    SLEEP_MODE = "sleep_mode"
    EXTERNAL_REQUEST = "external_request"
    PRIVACY_LIGHTS_ON = "privacy_lights_on"
    SHADING_GEOMETRIC = "shading_geometric"
    SHADING_FIXED = "shading_fixed"
    SOLAR_HEATING = "solar_heating"
    SCHEDULE_DAY = "schedule_day"
    SCHEDULE_NIGHT = "schedule_night"

    # Why a layer did not act
    NOT_CONFIGURED = "not_configured"
    INACTIVE = "inactive"
    INPUT_UNAVAILABLE = "input_unavailable"
    INPUT_UNKNOWN = "input_unknown"
    INPUT_HELD_LAST_KNOWN = "input_held_last_known"
    WAITING_FOR_DELAY = "waiting_for_delay"
    OUTSIDE_EPISODE = "outside_episode"
    EPISODE_LOCKED = "episode_locked"
    WATCHDOG_RELEASED = "watchdog_released"
    CAPABILITY_MISSING = "capability_missing"
    DAY_TYPE_FALLBACK = "day_type_fallback"

    # Constraints
    ONLY_RAISE = "only_raise"
    ONLY_LOWER = "only_lower"
    SLEEP_EXCEPTION_NO_OPEN = "sleep_exception_no_open"
    LOCKOUT_DOOR_OPEN = "lockout_door_open"
    LOCKOUT_VOID_TAMPER = "lockout_void_tamper"
    LOCKOUT_CONTACT_UNAVAILABLE = "lockout_contact_unavailable"
    VENTILATION_FLOOR = "ventilation_floor"
    RAIN_VENTILATION_FLOOR = "rain_ventilation_floor"
    FROST_LIMIT = "frost_limit"
    FROST_LIMIT_SOURCE_BLIND = "frost_limit_source_blind"
    FROST_HOLD = "frost_hold"
    NO_INTERMEDIATE_POSITION = "no_intermediate_position"

    # Gate
    SENT = "sent"
    MAINTENANCE_LOCK = "maintenance_lock"
    DRY_RUN = "dry_run"
    COVER_UNAVAILABLE = "cover_unavailable"
    TARGET_REACHED = "target_reached"
    MODE_OFF = "mode_off"
    MODE_PROTECTION_ONLY = "mode_protection_only"
    PAUSED = "paused"
    PERSON_AT_WINDOW = "person_at_window"
    MANUAL_OVERRIDE = "manual_override"
    MOVEMENT_IN_FLIGHT = "movement_in_flight"
    DUPLICATE_COMMAND = "duplicate_command"
    MOVEMENT_TAKEN_OVER = "movement_taken_over"
    MIN_CHANGE = "min_change"
    MIN_INTERVAL = "min_interval"
    TRIGGER_TIME_MISSING = "trigger_time_missing"
    COMMAND_BACKOFF = "command_backoff"
    STAGGERED = "staggered"

    # Tracker and life cycle (events only)
    MANUAL_DETECTED = "manual_detected"
    MANUAL_DETECTED_MEMBER = "manual_detected_member"
    EXTERNAL_MOVEMENT_OBSERVED = "external_movement_observed"
    MOVED_DURING_DOWNTIME = "moved_during_downtime"
    PERSON_AT_WINDOW_STARTED = "person_at_window_started"
    PERSON_AT_WINDOW_ENDED = "person_at_window_ended"
    OVERRIDE_STARTED = "override_started"
    OVERRIDE_ENDED = "override_ended"
    PROTECTION_STARTED = "protection_started"
    PROTECTION_ENDED = "protection_ended"
    PROTECTION_SOURCE_BLIND = "protection_source_blind"
    LOCKOUT_CONTACT_BLIND = "lockout_contact_blind"
    FIRE_ACKNOWLEDGED = "fire_acknowledged"
    FROST_PROTECTION_WAIVED = "frost_protection_waived"
    FROST_WAIVER_ENDED = "frost_waiver_ended"
    FROST_RELEASED_BY_SUN = "frost_released_by_sun"
    FROST_SOURCE_BLIND = "frost_source_blind"
    POSITION_MAY_BE_INACCURATE = "position_may_be_inaccurate"
    COMMAND_FAILED = "command_failed"
    ACTUATOR_NO_REACTION = "actuator_no_reaction"
    MOVEMENT_NOT_FINISHED = "movement_not_finished"
    MEMBER_UNAVAILABLE = "member_unavailable"
    BUTTON_REFUSED_MAINTENANCE_LOCK = "button_refused_maintenance_lock"

    @property
    def category(self) -> ReasonCategory:
        """Return the group under which the architecture document lists the code."""
        return _CATEGORY_OF[self]


_GROUPS: Final = MappingProxyType(
    {
        ReasonCategory.LAYER: (
            ReasonCode.FIRE_ALARM,
            ReasonCode.FIRE_UNACKNOWLEDGED,
            ReasonCode.PROTECTION_EVENT,
            ReasonCode.PROTECTION_RETURN_MANUAL,
            ReasonCode.SLEEP_MODE,
            ReasonCode.EXTERNAL_REQUEST,
            ReasonCode.PRIVACY_LIGHTS_ON,
            ReasonCode.SHADING_GEOMETRIC,
            ReasonCode.SHADING_FIXED,
            ReasonCode.SOLAR_HEATING,
            ReasonCode.SCHEDULE_DAY,
            ReasonCode.SCHEDULE_NIGHT,
        ),
        ReasonCategory.LAYER_INACTIVE: (
            ReasonCode.NOT_CONFIGURED,
            ReasonCode.INACTIVE,
            ReasonCode.INPUT_UNAVAILABLE,
            ReasonCode.INPUT_UNKNOWN,
            ReasonCode.INPUT_HELD_LAST_KNOWN,
            ReasonCode.WAITING_FOR_DELAY,
            ReasonCode.OUTSIDE_EPISODE,
            ReasonCode.EPISODE_LOCKED,
            ReasonCode.WATCHDOG_RELEASED,
            ReasonCode.CAPABILITY_MISSING,
            ReasonCode.DAY_TYPE_FALLBACK,
        ),
        ReasonCategory.CONSTRAINT: (
            ReasonCode.ONLY_RAISE,
            ReasonCode.ONLY_LOWER,
            ReasonCode.SLEEP_EXCEPTION_NO_OPEN,
            ReasonCode.LOCKOUT_DOOR_OPEN,
            ReasonCode.LOCKOUT_VOID_TAMPER,
            ReasonCode.LOCKOUT_CONTACT_UNAVAILABLE,
            ReasonCode.VENTILATION_FLOOR,
            ReasonCode.RAIN_VENTILATION_FLOOR,
            ReasonCode.FROST_LIMIT,
            ReasonCode.FROST_LIMIT_SOURCE_BLIND,
            ReasonCode.FROST_HOLD,
            ReasonCode.NO_INTERMEDIATE_POSITION,
        ),
        ReasonCategory.GATE: (
            ReasonCode.SENT,
            ReasonCode.MAINTENANCE_LOCK,
            ReasonCode.DRY_RUN,
            ReasonCode.COVER_UNAVAILABLE,
            ReasonCode.TARGET_REACHED,
            ReasonCode.MODE_OFF,
            ReasonCode.MODE_PROTECTION_ONLY,
            ReasonCode.PAUSED,
            ReasonCode.PERSON_AT_WINDOW,
            ReasonCode.MANUAL_OVERRIDE,
            ReasonCode.MOVEMENT_IN_FLIGHT,
            ReasonCode.DUPLICATE_COMMAND,
            ReasonCode.MOVEMENT_TAKEN_OVER,
            ReasonCode.MIN_CHANGE,
            ReasonCode.MIN_INTERVAL,
            ReasonCode.TRIGGER_TIME_MISSING,
            ReasonCode.COMMAND_BACKOFF,
            ReasonCode.STAGGERED,
        ),
        ReasonCategory.EVENT: (
            ReasonCode.MANUAL_DETECTED,
            ReasonCode.MANUAL_DETECTED_MEMBER,
            ReasonCode.EXTERNAL_MOVEMENT_OBSERVED,
            ReasonCode.MOVED_DURING_DOWNTIME,
            ReasonCode.PERSON_AT_WINDOW_STARTED,
            ReasonCode.PERSON_AT_WINDOW_ENDED,
            ReasonCode.OVERRIDE_STARTED,
            ReasonCode.OVERRIDE_ENDED,
            ReasonCode.PROTECTION_STARTED,
            ReasonCode.PROTECTION_ENDED,
            ReasonCode.PROTECTION_SOURCE_BLIND,
            ReasonCode.LOCKOUT_CONTACT_BLIND,
            ReasonCode.FIRE_ACKNOWLEDGED,
            ReasonCode.FROST_PROTECTION_WAIVED,
            ReasonCode.FROST_WAIVER_ENDED,
            ReasonCode.FROST_RELEASED_BY_SUN,
            ReasonCode.FROST_SOURCE_BLIND,
            ReasonCode.POSITION_MAY_BE_INACCURATE,
            ReasonCode.COMMAND_FAILED,
            ReasonCode.ACTUATOR_NO_REACTION,
            ReasonCode.MOVEMENT_NOT_FINISHED,
            ReasonCode.MEMBER_UNAVAILABLE,
            ReasonCode.BUTTON_REFUSED_MAINTENANCE_LOCK,
        ),
    }
)

_CATEGORY_OF: Final = MappingProxyType(
    {code: category for category, codes in _GROUPS.items() for code in codes}
)


def codes_of(category: ReasonCategory) -> tuple[ReasonCode, ...]:
    """Return the codes of one group, in the order of the architecture document."""
    return _GROUPS[category]
