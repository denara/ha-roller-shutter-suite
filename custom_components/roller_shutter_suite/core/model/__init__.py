"""Data types of the domain core: the vocabulary of ``docs/architecture.md``.

This package holds types only. There is no arbiter, no schedule, no tracker
logic and no geometry here; the blocks that build them exchange the types
defined below. Every type is immutable, validates itself on construction and
compares by value.

Import from the package, not from its modules: ``from ...core.model import
Position``. The modules exist so that blocks that work in parallel edit
different files. Their dependencies run one way:

``_validation`` ← ``_data`` ← ``values`` ← ``decision`` ← ``observation`` ←
``state`` ← ``snapshot``. ``functions`` depends on nothing; ``window`` depends
on ``_validation``, ``functions`` and ``values``, ``controls`` on
``_validation`` only; ``decision`` also uses ``functions``, and ``snapshot``
also uses ``controls`` and ``almanac``. ``schedule`` (the settings of the
schedule as values) depends on ``_validation`` and ``values`` and is used by
``window``; ``almanac`` depends on ``_validation`` and ``_data``. ``geometry``
(the measurements of shading as values) depends on ``_validation`` and
``values`` and is used by ``window``.

Conventions that hold for the whole package:

- A position is an integer from 0 to 100; 100 is fully open, 0 fully closed.
  Positions of members are on the motor scale.
- Every datetime is timezone-aware. A naive datetime is rejected. Persisted
  instants are kept in UTC; the time of a world snapshot keeps the local zone
  of the installation.
- A member is identified by a string that the core treats as opaque.
- Nothing converts "unknown" or "unavailable" into a number or a boolean.
"""

from ._data import JsonObject, JsonValue
from .almanac import ElevationPassage, SunAlmanac, SunDay
from .controls import ControlLevel, Controls, OperatingMode
from .decision import (
    CONSTRAINT_REASONS,
    GATE_RULE_REASONS,
    Constraint,
    ConstraintResult,
    Decision,
    Direction,
    EvaluationFault,
    EvaluationStage,
    GateKind,
    GateOutcome,
    GateRule,
    Layer,
    LayerReason,
    MemberTarget,
    Wish,
    WishClass,
    WishKind,
)
from .functions import FaultBehavior, FunctionId
from .geometry import (
    GEOMETRY_FIELDS,
    GEOMETRY_PREFIX,
    MAX_AMPLIFICATION_CAP,
    MAX_MEASURED_LENGTH,
    MEMBER_MEASUREMENT_FIELDS,
    MIN_CALIBRATION_SPAN,
    NO_CALIBRATION,
    NO_MEASUREMENTS,
    GeometryRuleError,
    GlassCalibration,
    MemberGlass,
    MemberGlassError,
    MemberMeasurements,
    ShadingGeometrySettings,
    member_glass_for,
)
from .observation import (
    CommandResult,
    MemberCommand,
    MemberObservation,
    MembersAtTargets,
    MovementState,
    Observation,
    OwnCommand,
    TravelDirection,
    WindowObservation,
)
from .schedule import (
    MAX_RANDOM_OFFSET,
    MAX_SUN_OFFSET_MINUTES,
    MAX_TRIGGER_ELEVATION,
    TRIGGER_FIELDS,
    DayTriggers,
    ScheduleProfile,
    ScheduleRuleError,
    ScheduleSettings,
    ScheduleTargets,
    Trigger,
    TriggerKind,
)
from .snapshot import WorldSnapshot
from .state import (
    WINDOW_STATE_SCHEMA_VERSION,
    DayType,
    ExternalRequest,
    HeldInput,
    LatchedDayType,
    ManualOverrideDam,
    MemberState,
    OverrideEndRule,
    PersonAtWindowDam,
    PositionOwner,
    PositionReference,
    ProtectionEventState,
    ProtectionEventStatus,
    ShadingEpisodeState,
    SimulatedState,
    SolarHeatingEpisodeState,
    WindowState,
)
from .values import (
    FULLY_CLOSED,
    FULLY_OPEN,
    AnySourceValue,
    MissingSourceValueError,
    Position,
    SourceScalar,
    SourceState,
    SourceValue,
    SunPosition,
)
from .window import (
    BLIND_SOURCE,
    DEFAULT_STAGGER_GAP,
    DEFAULT_TOLERANCE_CALCULATED,
    DEFAULT_TOLERANCE_MEASURED,
    MAX_STAGGER_GAP,
    MAX_TOLERANCE,
    MIN_TOLERANCE,
    SCHEDULE_DAY_TYPES,
    SCHEDULE_EDGES,
    BlindSource,
    CapabilityProfile,
    CapabilityState,
    CoveringType,
    FrostSettings,
    MemberConfig,
    MotorProtectionSettings,
    PositionSource,
    PositionUpdates,
    SettingsCombinationError,
    TemperatureTier,
    TransitReporting,
    WindowCapabilities,
    WindowCapabilityStates,
    WindowConfig,
)

__all__ = [
    "BLIND_SOURCE",
    "CONSTRAINT_REASONS",
    "DEFAULT_STAGGER_GAP",
    "DEFAULT_TOLERANCE_CALCULATED",
    "DEFAULT_TOLERANCE_MEASURED",
    "FULLY_CLOSED",
    "FULLY_OPEN",
    "GATE_RULE_REASONS",
    "GEOMETRY_FIELDS",
    "GEOMETRY_PREFIX",
    "MAX_AMPLIFICATION_CAP",
    "MAX_MEASURED_LENGTH",
    "MAX_RANDOM_OFFSET",
    "MAX_STAGGER_GAP",
    "MAX_SUN_OFFSET_MINUTES",
    "MAX_TOLERANCE",
    "MAX_TRIGGER_ELEVATION",
    "MEMBER_MEASUREMENT_FIELDS",
    "MIN_CALIBRATION_SPAN",
    "MIN_TOLERANCE",
    "NO_CALIBRATION",
    "NO_MEASUREMENTS",
    "SCHEDULE_DAY_TYPES",
    "SCHEDULE_EDGES",
    "TRIGGER_FIELDS",
    "WINDOW_STATE_SCHEMA_VERSION",
    "AnySourceValue",
    "BlindSource",
    "CapabilityProfile",
    "CapabilityState",
    "CommandResult",
    "Constraint",
    "ConstraintResult",
    "ControlLevel",
    "Controls",
    "CoveringType",
    "DayTriggers",
    "DayType",
    "Decision",
    "Direction",
    "ElevationPassage",
    "EvaluationFault",
    "EvaluationStage",
    "ExternalRequest",
    "FaultBehavior",
    "FrostSettings",
    "FunctionId",
    "GateKind",
    "GateOutcome",
    "GateRule",
    "GeometryRuleError",
    "GlassCalibration",
    "HeldInput",
    "JsonObject",
    "JsonValue",
    "LatchedDayType",
    "Layer",
    "LayerReason",
    "ManualOverrideDam",
    "MemberCommand",
    "MemberConfig",
    "MemberGlass",
    "MemberGlassError",
    "MemberMeasurements",
    "MemberObservation",
    "MemberState",
    "MemberTarget",
    "MembersAtTargets",
    "MissingSourceValueError",
    "MotorProtectionSettings",
    "MovementState",
    "Observation",
    "OperatingMode",
    "OverrideEndRule",
    "OwnCommand",
    "PersonAtWindowDam",
    "Position",
    "PositionOwner",
    "PositionReference",
    "PositionSource",
    "PositionUpdates",
    "ProtectionEventState",
    "ProtectionEventStatus",
    "ScheduleProfile",
    "ScheduleRuleError",
    "ScheduleSettings",
    "ScheduleTargets",
    "SettingsCombinationError",
    "ShadingEpisodeState",
    "ShadingGeometrySettings",
    "SimulatedState",
    "SolarHeatingEpisodeState",
    "SourceScalar",
    "SourceState",
    "SourceValue",
    "SunAlmanac",
    "SunDay",
    "SunPosition",
    "TemperatureTier",
    "TransitReporting",
    "TravelDirection",
    "Trigger",
    "TriggerKind",
    "WindowCapabilities",
    "WindowCapabilityStates",
    "WindowConfig",
    "WindowObservation",
    "WindowState",
    "Wish",
    "WishClass",
    "WishKind",
    "WorldSnapshot",
    "member_glass_for",
]
