"""Partial settings, the "inherit" marker and the resolver global → group → window.

Configuration is stored per level: the house (global), a group, a window. Each
level states only what it sets itself; everything else is inherited. This
module turns the partial settings of the three levels into the complete
configuration of one window and says, for every value, which level it came
from.

The pieces:

- :data:`INHERIT` is the one marker for "this level does not set the value".
  ``None`` is never that marker: for a setting whose type allows ``None``, a
  set ``None`` is a set value like any other.
- :class:`PartialSettings` holds what one level sets.
  :func:`settings_from_stored` is the single place that turns stored data into
  partial settings; there, and only there, an absent key means "inherit" and
  :data:`STORED_NONE` means "explicitly none".
- :class:`SettingDefinition` describes one setting, and a
  :class:`SettingsRegistry` lists the settings that exist. The resolver is
  generic over the registry. :data:`WINDOW_SETTINGS` is the registry of the
  settings of :class:`~.model.WindowConfig`; a new setting is one more entry
  there.
- :func:`resolve_settings` resolves a registry over the three levels, with
  provenance, the capability mask, the handling of faults and the fallback
  for a group that is gone. :func:`resolve_window` does that for
  :data:`WINDOW_SETTINGS` and builds the ``WindowConfig``.

Nothing here raises because of what a user stored, and a fault in stored
settings never costs a window its configuration. What a fault costs follows
the fault behavior of the setting's function (``FunctionId.fault_behavior``).
**Fall back:** whatever protects or restricts movement never fails; the faulty
value is passed by and the next level supplies it. **Pause:** a function that
creates wishes for convenience is paused for the windows for which the faulty
value would have been the effective one, so a window never moves unexpectedly
because of a data fault. **Everything is reported.**
"""

import dataclasses
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import Enum, StrEnum, unique
from types import MappingProxyType
from typing import Any, Final

from .model import (
    CapabilityState,
    CoveringType,
    FaultBehavior,
    FunctionId,
    JsonValue,
    MemberConfig,
    ScheduleProfile,
    TemperatureTier,
    WindowCapabilityStates,
    WindowConfig,
)
from .model._data import as_enum, as_int, as_object, as_str, read, tuple_of
from .model._validation import require_identifier, require_type, require_unique


@unique
class Inherit(Enum):
    """The type of the marker :data:`INHERIT`. It has exactly one member."""

    INHERIT = "inherit"


INHERIT: Final = Inherit.INHERIT
"""This level does not set the value; it comes from the level above."""


@unique
class Level(StrEnum):
    """Where a resolved value came from, from the weakest to the strongest level."""

    BUILT_IN = "built_in"
    """No level sets the value; the default of the setting applies."""
    GLOBAL = "global"
    """The house."""
    GROUP = "group"
    WINDOW = "window"


@unique
class SettingKind(StrEnum):
    """The declared kind of a setting.

    The kind decides what stored data may say about the setting beyond a
    plain value; today that is one thing: only an ``OPTIONAL_REFERENCE``
    accepts :data:`STORED_NONE`.
    """

    BOOLEAN = "boolean"
    NUMBER = "number"
    ENUMERATION = "enumeration"
    LIST = "list"
    TIME = "time"
    """A local time of day, without a date and without a zone; see :func:`as_time`."""
    DURATION = "duration"
    """Whole seconds; see :func:`as_duration`."""
    DAY_OF_YEAR = "day_of_year"
    """A month and a day without a year; see :func:`as_day_of_year`."""
    OPTIONAL_REFERENCE = "optional_reference"
    """A reference to a source or an entity that may be absent: ``str | None``."""


STORED_NONE: Final = "__none__"
"""How stored data says "explicitly none" for an optional reference.

An absent key means "inherit", so it cannot also mean "none". This string is
the one marker for it. It exists in stored data only:
:func:`settings_from_stored` turns it into the set value ``None``, and it never
reaches partial settings or a resolved configuration as a string.
"""


@unique
class Capability(StrEnum):
    """A capability a setting can require; the fields of ``WindowCapabilityStates``."""

    SUPPORTS_OPEN_CLOSE = "supports_open_close"
    SUPPORTS_SET_POSITION = "supports_set_position"
    SUPPORTS_STOP = "supports_stop"
    REPORTS_POSITION = "reports_position"


@dataclass(frozen=True, slots=True)
class CapabilityRequirement[T]:
    """A setting works only if every member of the window has a capability.

    ``value_when_missing`` is the value the complete configuration carries
    when the capability is definitely missing: the one that makes the arbiter
    leave the option alone (``False`` for a switch, ``None`` for an optional
    position). A capability that is merely unknown masks nothing.
    """

    capability: Capability
    value_when_missing: T

    def __post_init__(self) -> None:
        """Validate the capability."""
        require_type(self.capability, Capability, "the required capability")


@dataclass(frozen=True, slots=True)
class SettingDefinition[T]:
    """Everything the resolver knows about one setting. The single place.

    - ``key``: the name of the setting, in stored data and in the resolved
      result. For a setting of a window it is the name of the field of
      ``WindowConfig``.
    - ``kind``: the declared kind of the setting.
    - ``function``: the function the setting belongs to, a member of the
      closed list ``FunctionId``. The fault behavior of the function
      (``FunctionId.fault_behavior``) decides what a fault in the setting
      costs: it falls back, or the function is paused and the arbiter skips
      it. ``None`` is allowed only for a setting that cannot be inherited and
      describes the window itself rather than a function (the covering
      type); a fault in such a setting falls back and pauses nothing.
    - ``default``: the built-in default, used when no level sets the value.
    - ``parse``: reads the value from stored data and raises a ``ValueError``
      if it cannot. It is never called for an absent key, blank text,
      ``null`` or :data:`STORED_NONE`.
    - ``inheritable``: ``False`` for what belongs to one window only (the
      cover itself, measurements). Such a setting is read from the window
      level alone; on a group or the house it is a fault.
    - ``requires``: the capability the setting needs, if any.
    """

    key: str
    kind: SettingKind
    function: FunctionId | None
    default: T
    parse: Callable[[JsonValue], T]
    inheritable: bool = True
    requires: CapabilityRequirement[T] | None = None

    def __post_init__(self) -> None:
        """Validate the description itself."""
        require_identifier(self.key, "the key of a setting")
        require_type(self.kind, SettingKind, "the kind of a setting")
        require_type(self.inheritable, bool, "the flag 'inheritable'")
        if self.function is None:
            if self.inheritable:
                raise ValueError(
                    f"the setting {self.key!r} can be inherited, so it belongs to "
                    "a function; name it"
                )
        else:
            require_type(self.function, FunctionId, "the function of a setting")
        if self.requires is not None:
            require_type(
                self.requires, CapabilityRequirement, "the capability requirement"
            )

    @property
    def fault_behavior(self) -> FaultBehavior:
        """Return the behavior of the setting's function; without one, fall back."""
        if self.function is None:
            return FaultBehavior.FALL_BACK
        return self.function.fault_behavior


@dataclass(frozen=True, slots=True)
class SettingsRegistry:
    """The settings that exist, each described once."""

    definitions: tuple[SettingDefinition[Any], ...]

    def __post_init__(self) -> None:
        """Validate the entries; a key occurs once."""
        object.__setattr__(self, "definitions", tuple(self.definitions))
        for definition in self.definitions:
            require_type(definition, SettingDefinition, "an entry of the registry")
        require_unique(self.keys, "the keys of the registry")

    @property
    def keys(self) -> tuple[str, ...]:
        """Return the keys in the order of the registry."""
        return tuple(definition.key for definition in self.definitions)

    @property
    def functions(self) -> frozenset[FunctionId]:
        """Return the functions that have at least one registered setting."""
        return frozenset(
            definition.function
            for definition in self.definitions
            if definition.function is not None
        )

    @property
    def pausable_functions(self) -> tuple[FunctionId, ...]:
        """Return the functions with a setting that a fault pauses, in a stable order."""
        return tuple(
            function
            for function in FunctionId
            if function in self.functions
            and function.fault_behavior is FaultBehavior.PAUSE
        )


@unique
class SettingProblem(StrEnum):
    """What is wrong with stored settings. The Home Assistant layer translates it."""

    UNREADABLE = "unreadable"
    """The stored value could not be read; ``null`` is such a value."""
    NONE_NOT_ALLOWED = "none_not_allowed"
    """The stored marker for "explicitly none" on a setting that is no optional reference."""
    INVALID = "invalid"
    """The value was read, but the window configuration refuses it."""
    NOT_INHERITABLE = "not_inheritable"
    """A group or the house sets what only a window can set."""
    UNKNOWN_SETTING = "unknown_setting"
    """The level sets a key that the registry does not know."""
    LEVEL_UNREADABLE = "level_unreadable"
    """The settings of the level are unreadable as a whole."""


SETTINGS_KEY: Final = "settings"
"""The key under which a level stores its settings, apart from its identity data.

It is also the key a fault names when the settings of a level are unreadable
as a whole.
"""


@dataclass(frozen=True, slots=True)
class SettingFault:
    """A fault in the stored settings of one level: the key and what is wrong.

    ``detail`` is English text for logs; ``problem`` is the code to translate.
    """

    key: str
    detail: str
    problem: SettingProblem = SettingProblem.UNREADABLE

    def __post_init__(self) -> None:
        """Validate key, text and code."""
        require_identifier(self.key, "the key of a faulty setting")
        require_identifier(self.detail, "the description of a fault")
        require_type(self.problem, SettingProblem, "the problem of a fault")


@dataclass(frozen=True, slots=True)
class PartialSettings:
    """What one level sets itself. Every other setting is :data:`INHERIT`.

    ``values`` maps the key of a setting to the value this level sets; an
    entry whose value is :data:`INHERIT` is the same as no entry. ``0``,
    ``False``, an empty tuple and, where the type of the setting allows it,
    ``None`` are set values. ``faults`` lists stored values that could not be
    read; such a key is not set. ``unreadable`` says that the settings of the
    level could not be read as a whole; such a level sets nothing.

    Compared by value, but not hashable, because it holds a mapping.
    """

    values: Mapping[str, object] = field(default_factory=dict)
    faults: tuple[SettingFault, ...] = ()
    unreadable: bool = False

    def __post_init__(self) -> None:
        """Copy the values, drop the marker, validate the faults."""
        values: dict[str, object] = {}
        for key, value in dict(self.values).items():
            require_identifier(key, "the key of a setting")
            if value is not INHERIT:
                values[key] = value
        object.__setattr__(self, "values", MappingProxyType(values))
        object.__setattr__(self, "faults", tuple(self.faults))
        for fault in self.faults:
            require_type(fault, SettingFault, "a fault of partial settings")
            if fault.key in values:
                raise ValueError(f"the setting {fault.key!r} is both set and faulty")
        require_unique((fault.key for fault in self.faults), "the faulty settings")
        require_type(self.unreadable, bool, "the flag 'unreadable'")
        if self.unreadable and (values or self.faults):
            raise ValueError("settings that are unreadable as a whole set nothing")

    def get(self, key: str) -> object | Inherit:
        """Return the value this level sets, or :data:`INHERIT`."""
        return self.values.get(key, INHERIT)

    def with_value(self, key: str, value: object | Inherit) -> PartialSettings:
        """Return a copy in which the setting has the value; a fault of it is gone."""
        return PartialSettings(
            values={**self.values, key: value},
            faults=tuple(fault for fault in self.faults if fault.key != key),
        )

    def with_inherit(self, key: str) -> PartialSettings:
        """Return a copy in which the setting is inherited again."""
        return self.with_value(key, INHERIT)


_NULL_FAULT: Final = "null is not a stored value; a key that is absent is inherited"
_NONE_FAULT: Final = (
    f"{STORED_NONE!r} is accepted for an optional reference only; "
    "this setting always has a value"
)
_UNKNOWN_FAULT: Final = "the registry has no setting with this key"
_NOT_INHERITABLE_FAULT: Final = "only a window can set this; it cannot be inherited"
_LEVEL_FAULT: Final = "the settings of this level are not a mapping of keys to values"


def settings_from_stored(data: object, registry: SettingsRegistry) -> PartialSettings:
    """Turn the stored settings of one level into partial settings.

    ``data`` is the mapping that holds the settings of the level **and nothing
    else**. The Home Assistant layer stores it under a key of its own
    (:data:`SETTINGS_KEY`), apart from identity data such as the covers, the
    group reference and the name. Every key in it must therefore be known.

    This is the only place that knows how "inherit" is stored:

    - a key that is absent is inherited;
    - an empty string, or text of nothing but whitespace, is treated like an
      absent key, because a form can deliver an emptied text field that way;
    - ``0``, ``False`` and an empty list are set values;
    - ``null`` is never written, so it is a fault and not a second way to say
      "inherit" or "none";
    - :data:`STORED_NONE` on an optional reference is the set value ``None``:
      "explicitly none", which beats the levels below like any set value. On a
      setting of any other kind it is a fault (``none_not_allowed``);
    - a value the setting cannot read is a fault (``unreadable``);
    - a key the registry does not know is a fault (``unknown_setting``), so a
      misspelled key is noticed instead of silently meaning "inherit";
    - data that is no mapping at all is unreadable as a whole
      (``PartialSettings.unreadable``).

    The function does not raise for anything a user could have stored.
    """
    if not isinstance(data, Mapping):
        return PartialSettings(unreadable=True)
    definitions = {definition.key: definition for definition in registry.definitions}
    values: dict[str, object] = {}
    faults: dict[str, SettingFault] = {}
    for key, raw in data.items():
        if not isinstance(key, str) or not key:
            faults[SETTINGS_KEY] = SettingFault(
                SETTINGS_KEY, _UNKNOWN_FAULT, SettingProblem.UNKNOWN_SETTING
            )
            continue
        definition = definitions.get(key)
        if definition is None:
            faults[key] = SettingFault(
                key, _UNKNOWN_FAULT, SettingProblem.UNKNOWN_SETTING
            )
        elif isinstance(raw, str) and not raw.strip():
            continue
        elif raw is None:
            faults[key] = SettingFault(key, _NULL_FAULT)
        elif raw == STORED_NONE:
            if definition.kind is SettingKind.OPTIONAL_REFERENCE:
                values[key] = None
            else:
                faults[key] = SettingFault(
                    key, _NONE_FAULT, SettingProblem.NONE_NOT_ALLOWED
                )
        else:
            try:
                values[key] = definition.parse(raw)
            except ValueError as err:
                faults[key] = SettingFault(key, str(err))
    return PartialSettings(values=values, faults=tuple(faults.values()))


@dataclass(frozen=True, slots=True)
class GroupLevel:
    """The group a window refers to.

    ``settings`` is ``None`` when the group no longer exists. A window without
    a group passes no ``GroupLevel`` at all.
    """

    group_id: str
    settings: PartialSettings | None

    def __post_init__(self) -> None:
        """Validate identifier and settings."""
        require_identifier(self.group_id, "the identifier of a group")
        if self.settings is not None:
            require_type(self.settings, PartialSettings, "the settings of a group")


@dataclass(frozen=True, slots=True)
class GroupMissing:
    """The group a window refers to no longer exists; the house level applies.

    This is no data fault: removing a group is something a user may do. The
    window inherits from the house, nothing is switched off, and the Home
    Assistant layer turns this into a repair issue that names the window.
    """

    group_id: str


@dataclass(frozen=True, slots=True)
class MissingCapability:
    """A capability the window definitely lacks, and the members that lack it."""

    capability: Capability
    limiting_members: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolvedValue[T]:
    """One resolved setting with its provenance.

    ``value`` is what the levels yield and ``level`` where it came from
    (``group_id`` names the group if that is the level). ``effective`` is
    what the complete configuration carries. A faulty value of a level is
    never ``value``: the level counts as not setting the key.

    ``capability`` is the state of the capability the setting requires, or
    ``None`` if it requires none:

    - ``PRESENT``: the value applies.
    - ``MISSING``: the setting is **not available**. ``unavailable`` names the
      capability and the limiting members, the provenance stays, and
      ``effective`` is the stand-in of the setting instead of ``value``. This
      holds for an inherited value and for the window's own value alike; the
      own value stays stored and applies again once the capability is back.
    - ``UNKNOWN``: nothing was ever known about a member. The value applies
      unmasked and nothing is reported, but it is not confirmed either. A
      member that is merely unreachable is not unknown: its last known
      capabilities are handed in as known, so a mask stays while it is away.
    """

    key: str
    value: T
    effective: T
    level: Level
    group_id: str | None = None
    capability: CapabilityState | None = None
    unavailable: MissingCapability | None = None

    @property
    def available(self) -> bool:
        """Return whether the setting is in use: it is not masked."""
        return self.unavailable is None

    @property
    def own_value_masked(self) -> bool:
        """Return whether the window's **own** value is the one that is masked.

        The user asked for this option on this very window, so the Home
        Assistant layer raises a repair issue, worded differently from the
        explanation of a masked inherited value.
        """
        return self.unavailable is not None and self.level is Level.WINDOW


@unique
class FaultAction(StrEnum):
    """What the resolver did about a fault."""

    FELL_BACK = "fell_back"
    """Fall back: the faulty value is passed by; the next level supplies the value."""
    FUNCTIONS_DISABLED = "functions_disabled"
    """Pause: the functions named by the fault are paused for this window."""
    IGNORED = "ignored"
    """An unknown key: reported, nothing else. Newer versions may have written it."""
    NO_EFFECT = "no_effect"
    """A level closer to the window sets a sound value for the key, so the faulty
    value would never have been the effective one for this window. Reported for
    the repair issue of its level, without any effect here."""
    CONFIGURATION_WITHHELD = "configuration_withheld"
    """Not a fault of stored settings: the identity of the window or the registry
    itself is broken, and no configuration can be built."""


@dataclass(frozen=True, slots=True)
class ReportedFault:
    """A fault as the result reports it: where, what, and what was done about it.

    ``level`` (with ``group_id`` for a group) and ``key`` say where, ``problem``
    what; ``detail`` is English text for logs and diagnostics, never for the
    user. ``action`` says what the resolver did, and ``disabled_functions``
    names the functions it switched off because of this fault. A missing
    capability is never a fault; see :class:`ResolvedValue`.
    """

    key: str
    level: Level
    problem: SettingProblem
    detail: str
    action: FaultAction
    disabled_functions: tuple[FunctionId, ...] = ()
    group_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    """The result of resolving a registry for one window.

    ``values`` has one entry per setting of the registry, in its order.
    ``faults`` lists every fault on the levels of this window (the window, its
    group, the house) once, with what it costs **this** window; a fault that
    does not reach the window has the action ``no_effect``. ``group_missing``
    is set when the window refers to a group that no longer exists.
    """

    values: Mapping[str, ResolvedValue[Any]]
    faults: tuple[ReportedFault, ...] = ()
    group_missing: GroupMissing | None = None

    def __post_init__(self) -> None:
        """Copy the mapping so it cannot be changed afterwards."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def disabled_functions(self) -> frozenset[FunctionId]:
        """Return the functions that are paused for this window."""
        return frozenset(
            function for fault in self.faults for function in fault.disabled_functions
        )

    def faults_of(self, function: FunctionId) -> tuple[ReportedFault, ...]:
        """Return the faults that switched the function off."""
        return tuple(
            fault for fault in self.faults if function in fault.disabled_functions
        )

    @property
    def masked_own_values(self) -> tuple[ResolvedValue[Any], ...]:
        """Return the settings the window sets itself and cannot use at present.

        This is what the Home Assistant layer reports as a repair issue. It is
        no fault: the entry disappears by itself when the capability is back.
        A capability that is unknown never appears here.
        """
        return tuple(item for item in self.values.values() if item.own_value_masked)

    def effective(self) -> dict[str, Any]:
        """Return the value the complete configuration carries, per key."""
        return {key: item.effective for key, item in self.values.items()}


@dataclass(frozen=True, slots=True)
class SettingRules:
    """The value rules of the structure the settings are resolved for.

    The resolver knows no value rule itself. ``check_value(key, value)`` raises
    a ``TypeError`` or ``ValueError`` for a value the structure refuses;
    ``build(effective, disabled_functions)`` builds the structure from the
    effective values of all settings and raises likewise, which is where a
    rule that spans two settings speaks up. For a window both are
    ``WindowConfig``.
    """

    check_value: Callable[[str, object], None]
    build: Callable[[Mapping[str, Any], frozenset[FunctionId]], object]


@dataclass(frozen=True, slots=True)
class _LevelInput:
    """One level as the resolution reads it: its sound values and its faults."""

    level: Level
    values: Mapping[str, object]
    faults: tuple[SettingFault, ...] = ()
    group_id: str | None = None

    def is_faulty(self, key: str) -> bool:
        """Return whether the level sets the key, but not soundly."""
        return any(fault.key == key for fault in self.faults)

    def blamed(self, fault: SettingFault) -> _LevelInput:
        """Return the level with one of its sound values turned into a fault."""
        kept = {key: value for key, value in self.values.items() if key != fault.key}
        return _LevelInput(self.level, kept, (*self.faults, fault), self.group_id)


def _read_level(
    registry: SettingsRegistry,
    level: Level,
    settings: PartialSettings,
    group_id: str | None,
    rules: SettingRules | None,
) -> _LevelInput:
    """Split the data of one level into its sound values and its faults.

    Every set value is judged, whether or not it wins for this window.
    """
    if settings.unreadable:
        whole = SettingFault(
            SETTINGS_KEY, _LEVEL_FAULT, SettingProblem.LEVEL_UNREADABLE
        )
        return _LevelInput(level, {}, (whole,), group_id)
    definitions = {definition.key: definition for definition in registry.definitions}
    faults = list(settings.faults)
    sound: dict[str, object] = {}
    for key, value in settings.values.items():
        definition = definitions.get(key)
        if definition is None:
            faults.append(
                SettingFault(key, _UNKNOWN_FAULT, SettingProblem.UNKNOWN_SETTING)
            )
            continue
        if level is not Level.WINDOW and not definition.inheritable:
            faults.append(
                SettingFault(
                    key, _NOT_INHERITABLE_FAULT, SettingProblem.NOT_INHERITABLE
                )
            )
            continue
        if rules is not None:
            try:
                rules.check_value(key, value)
            except (TypeError, ValueError) as err:
                faults.append(SettingFault(key, str(err), SettingProblem.INVALID))
                continue
        sound[key] = value
    return _LevelInput(level, sound, tuple(faults), group_id)


def _limiting_members(
    capability: Capability, members: tuple[MemberConfig, ...]
) -> tuple[str, ...]:
    """Return the members that definitely lack the capability."""
    return tuple(
        member.member_id
        for member in members
        if member.capabilities.capability_state(capability.value)
        is CapabilityState.MISSING
    )


def _resolve_one(
    definition: SettingDefinition[Any],
    levels: tuple[_LevelInput, ...],
    capabilities: WindowCapabilityStates,
    members: tuple[MemberConfig, ...],
) -> tuple[ResolvedValue[Any], tuple[Level, ...]]:
    """Walk the levels from the window outwards; the first that sets the key decides.

    A level whose value for the key is faulty is passed by, and the walk goes
    on outwards, last to the built-in default. Returned with the value are the
    levels whose fault was reached that way: for this window the faulty value
    would have been the effective one. A fault further out than a sound value
    is never reached.
    """
    value: Any = definition.default
    found: Level = Level.BUILT_IN
    found_group: str | None = None
    reached: list[Level] = []
    for level in levels:
        if level.is_faulty(definition.key):
            reached.append(level.level)
        elif definition.key in level.values:
            value, found, found_group = (
                level.values[definition.key],
                level.level,
                level.group_id,
            )
            break
    effective = value
    state: CapabilityState | None = None
    missing: MissingCapability | None = None
    if definition.requires is not None:
        required = definition.requires.capability
        state = getattr(capabilities, required.value)
        if state is CapabilityState.MISSING:
            effective = definition.requires.value_when_missing
            missing = MissingCapability(required, _limiting_members(required, members))
    resolved = ResolvedValue(
        key=definition.key,
        value=value,
        effective=effective,
        level=found,
        group_id=found_group,
        capability=state,
        unavailable=missing,
    )
    return resolved, tuple(reached)


def _report(
    registry: SettingsRegistry,
    levels: tuple[_LevelInput, ...],
    reached: Mapping[str, tuple[Level, ...]],
) -> tuple[ReportedFault, ...]:
    """List every fault of every level once, with what it costs this window."""
    definitions = {definition.key: definition for definition in registry.definitions}
    reports: list[ReportedFault] = []
    for level in levels:
        for fault in level.faults:
            definition = definitions.get(fault.key)
            disabled: tuple[FunctionId, ...] = ()
            if fault.problem is SettingProblem.LEVEL_UNREADABLE:
                action = FaultAction.FUNCTIONS_DISABLED
                disabled = registry.pausable_functions
            elif definition is None:
                action = FaultAction.IGNORED
            elif level.level not in reached[fault.key]:
                action = FaultAction.NO_EFFECT
            elif (
                definition.function is not None
                and definition.fault_behavior is FaultBehavior.PAUSE
            ):
                action = FaultAction.FUNCTIONS_DISABLED
                disabled = (definition.function,)
            else:
                action = FaultAction.FELL_BACK
            reports.append(
                ReportedFault(
                    fault.key,
                    level.level,
                    fault.problem,
                    fault.detail,
                    action,
                    disabled,
                    level.group_id,
                )
            )
    return tuple(reports)


def _resolve_levels(
    registry: SettingsRegistry,
    levels: tuple[_LevelInput, ...],
    capabilities: WindowCapabilityStates,
    members: tuple[MemberConfig, ...],
) -> tuple[dict[str, ResolvedValue[Any]], tuple[ReportedFault, ...]]:
    """Resolve every setting of the registry over the given levels."""
    values: dict[str, ResolvedValue[Any]] = {}
    reached: dict[str, tuple[Level, ...]] = {}
    for definition in registry.definitions:
        values[definition.key], reached[definition.key] = _resolve_one(
            definition, levels, capabilities, members
        )
    return values, _report(registry, levels, reached)


def _blame(  # noqa: PLR0913 - the state of one resolution
    registry: SettingsRegistry,
    levels: tuple[_LevelInput, ...],
    *,
    capabilities: WindowCapabilityStates,
    members: tuple[MemberConfig, ...],
    rules: SettingRules,
    disabled: frozenset[FunctionId],
) -> tuple[_LevelInput | None, str]:
    """Return the level and the key a refusal of the whole is attributed to.

    A rule that spans several settings cannot say which of them is wrong. The
    levels are therefore added one by one, from the built-in defaults over
    the house and the group to the window: the level whose values make the
    whole fail first is the one that spoke last, and it is held responsible.
    Of its values, the last in the order of the registry is named. ``None``
    as level means that the built-in defaults alone are refused.
    """
    blamed: _LevelInput | None = levels[0]
    values, _ = _resolve_levels(registry, levels, capabilities, members)
    for count in range(len(levels)):
        weakest = levels[len(levels) - count :]
        partial, _ = _resolve_levels(registry, weakest, capabilities, members)
        try:
            rules.build(
                {key: item.effective for key, item in partial.items()}, disabled
            )
        except TypeError, ValueError:
            blamed = weakest[0] if weakest else None
            values = partial
            break
    level = Level.BUILT_IN if blamed is None else blamed.level
    named = [item.key for item in values.values() if item.level is level]
    return blamed, named[-1]


def _resolve(  # noqa: PLR0913 - the three levels and the window are the input
    registry: SettingsRegistry,
    *,
    capabilities: WindowCapabilityStates,
    members: tuple[MemberConfig, ...],
    global_settings: PartialSettings,
    window_settings: PartialSettings,
    group: GroupLevel | None,
    rules: SettingRules | None,
) -> tuple[ResolvedSettings, object | None]:
    """Resolve, and build the structure if there are rules."""
    group_missing: GroupMissing | None = None
    levels = [_read_level(registry, Level.WINDOW, window_settings, None, rules)]
    if group is not None and group.settings is None:
        group_missing = GroupMissing(group.group_id)
    elif group is not None and group.settings is not None:
        levels.append(
            _read_level(registry, Level.GROUP, group.settings, group.group_id, rules)
        )
    levels.append(_read_level(registry, Level.GLOBAL, global_settings, None, rules))

    while True:
        values, faults = _resolve_levels(registry, tuple(levels), capabilities, members)
        resolved = ResolvedSettings(values, faults, group_missing)
        if rules is None:
            return resolved, None
        try:
            return resolved, rules.build(
                resolved.effective(), resolved.disabled_functions
            )
        except (TypeError, ValueError) as err:
            blamed, key = _blame(
                registry,
                tuple(levels),
                capabilities=capabilities,
                members=members,
                rules=rules,
                disabled=resolved.disabled_functions,
            )
            fault = SettingFault(key, str(err), SettingProblem.INVALID)
        if blamed is None:
            withheld = ReportedFault(
                key,
                Level.BUILT_IN,
                fault.problem,
                fault.detail,
                FaultAction.CONFIGURATION_WITHHELD,
            )
            return dataclasses.replace(resolved, faults=(*faults, withheld)), None
        levels[levels.index(blamed)] = blamed.blamed(fault)


def resolve_settings(  # noqa: PLR0913 - the three levels and the window are the input
    registry: SettingsRegistry,
    *,
    capabilities: WindowCapabilityStates,
    members: tuple[MemberConfig, ...],
    global_settings: PartialSettings,
    window_settings: PartialSettings,
    group: GroupLevel | None = None,
    rules: SettingRules | None = None,
) -> ResolvedSettings:
    """Resolve every setting of the registry for one window.

    The value of a window beats the value of its group, which beats the value
    of the house, which beats the built-in default. ``capabilities`` are those
    of the window in three states (``WindowConfig.capability_states`` of
    ``members``); the members are needed to name who limits. ``rules`` are the
    value rules of the structure that is resolved, if it has any.

    - **No group:** the window inherits from the house directly. **A group
      that no longer exists:** the same, and the result says so
      (``group_missing``); that is no fault and switches nothing off.
    - **Capability mask:** a setting that requires a capability the window
      definitely lacks is not available: provenance kept, capability and
      limiting members named, ``effective`` is the stand-in. That is never a
      fault. A capability that is unknown masks nothing and reports nothing.

    **Faults.** A fault is a stored value that cannot be read (``null``
    included), the marker for "none" on a setting that always has a value, a
    value of the wrong type or one the rules refuse, a setting that cannot be
    inherited set above the window, and a refusal of the whole by a rule that
    spans several settings. Every set value of every level in the chain of
    this window (the window, its group, the house) is judged and reported,
    whether or not it wins. The rule is the same on all three levels.

    For every key the levels are walked from the window outwards, and the
    first level that sets the key decides. If its value is sound, it is
    effective and nothing is switched off, whatever lies further out: a fault
    there is reported with the action ``no_effect``. If its value is faulty,
    the faulty value would have been the effective one for this window, and
    what that costs depends on the fault behavior of the setting's function:

    - **fall back:** the faulty value is passed by and the walk goes on
      outwards, last to the built-in default; ``level`` of the resolved value
      says which level finally supplied it. Nothing is paused.
    - **pause:** the **function** of the setting is paused for this window,
      so it never moves unexpectedly because of a data fault. The value is
      resolved in the same way, but the arbiter does not act on it.
    - **an unknown key** is reported and switches nothing off: a newer
      version may have written it.
    - **a level that is unreadable as a whole** counts as not present: every
      function that a fault pauses is paused for the windows in whose chain
      the level lies, and the functions that fall back take the values of the
      other levels.

    A refusal of the whole is attributed to the level whose values make the
    whole fail first when the levels are added from the house to the window,
    and to the last of its values in the order of the registry; that value
    is then a fault of that key on that level like any other, and the window
    is resolved again.

    Everything is reported in ``faults``. The function does not raise for
    anything a user could have stored.
    """
    return _resolve(
        registry,
        capabilities=capabilities,
        members=members,
        global_settings=global_settings,
        window_settings=window_settings,
        group=group,
        rules=rules,
    )[0]


# --- Shared readers of stored values ----------------------------------------------

_TIME: Final = re.compile(r"([01][0-9]|2[0-3]):([0-5][0-9])(?::([0-5][0-9]))?")
_DAY_OF_YEAR: Final = re.compile(r"([0-9]{2})-([0-9]{2})")
_YEAR_WITHOUT_LEAP_DAY: Final = 2001


def as_time(value: JsonValue) -> time:
    """Read a setting of the kind ``time``: a local time of day.

    Exactly ``"HH:MM"`` or ``"HH:MM:SS"`` on the 24-hour clock. No offset, no
    zone, no fraction, no compact form, no surrounding whitespace.
    """
    match = _TIME.fullmatch(as_str(value))
    if match is None:
        raise ValueError('expected a time of day as "HH:MM" or "HH:MM:SS"')
    hour, minute, second = match.groups(default="0")
    return time(int(hour), int(minute), int(second))


def as_duration(value: JsonValue) -> timedelta:
    """Read a setting of the kind ``duration``: whole seconds, zero or more."""
    seconds = as_int(value)
    if seconds < 0:
        raise ValueError("expected a number of seconds that is not negative")
    return timedelta(seconds=seconds)


def as_day_of_year(value: JsonValue) -> tuple[int, int]:
    """Read a setting of the kind ``day_of_year``: ``"MM-DD"`` as (month, day).

    The day has to exist in every year, so ``"02-29"`` is refused.
    """
    match = _DAY_OF_YEAR.fullmatch(as_str(value))
    if match is None:
        raise ValueError('expected a day of the year as "MM-DD"')
    month, day = int(match.group(1)), int(match.group(2))
    try:
        date(_YEAR_WITHOUT_LEAP_DAY, month, day)
    except ValueError as err:
        raise ValueError("expected a day that exists in every year") from err
    return month, day


# --- The settings of a window -----------------------------------------------------


def _as_number(value: JsonValue) -> float:
    """Return the number; a boolean is not a number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")  # noqa: TRY004
    return float(value)


def _as_temperature_tier(value: JsonValue) -> TemperatureTier:
    """Return one tier of the temperature condition of shading."""
    data = as_object(value, "threshold", "hysteresis")
    return TemperatureTier(
        threshold=read(data, "threshold", _as_number),
        hysteresis=read(data, "hysteresis", _as_number),
    )


WINDOW_SETTINGS: Final = SettingsRegistry(
    (
        SettingDefinition(
            key="covering_type",
            kind=SettingKind.ENUMERATION,
            function=None,
            default=CoveringType.ROLLER_SHUTTER,
            parse=as_enum(CoveringType),
            inheritable=False,
        ),
        SettingDefinition[str | None](
            key="morning_condition_source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            function=FunctionId.SCHEDULE,
            default=None,
            parse=as_str,
        ),
        SettingDefinition[tuple[TemperatureTier, ...]](
            key="shading_temperature_tiers",
            kind=SettingKind.LIST,
            function=FunctionId.SHADING,
            default=(),
            parse=tuple_of(_as_temperature_tier),
        ),
        SettingDefinition(
            key="schedule_profile",
            kind=SettingKind.ENUMERATION,
            function=FunctionId.SCHEDULE,
            default=ScheduleProfile.DEFAULT,
            parse=as_enum(ScheduleProfile),
        ),
    )
)
"""The settings of ``WindowConfig``. A new setting is one more entry here.

The key of an entry is the name of its field of ``WindowConfig``. The fields
in :data:`WINDOW_FIELDS_THAT_ARE_NO_SETTINGS` have no entry.
"""


def functions_with_settings(
    registry: SettingsRegistry | None = None,
) -> frozenset[FunctionId]:
    """Return the functions that have at least one registered setting.

    Without an argument the registry of the window is asked. The arbiter's
    tests use this to check that every function that a faulty setting can
    pause has a layer that respects it, and that nothing that restricts
    movement is pausable.
    """
    return (WINDOW_SETTINGS if registry is None else registry).functions


WINDOW_IDENTITY_FIELDS: Final = ("window_id", "members")
"""What identifies a window and what it consists of. The caller hands them in."""

WINDOW_FIELDS_THAT_ARE_NO_SETTINGS: Final = (
    *WINDOW_IDENTITY_FIELDS,
    "disabled_functions",
)
"""Fields of ``WindowConfig`` without a registry entry: the identity, and the
functions the resolver switched off, which are a result and never stored."""


@dataclass(frozen=True, slots=True)
class WindowResolution:
    """The resolved window: its configuration and how it came about.

    A fault in stored settings never costs a window its configuration.
    ``config`` is ``None`` only if the identity of the window is refused (it
    has no member, for example) or the registry itself is broken; the fault
    with the action ``configuration_withheld`` says why. ``settings`` carries
    the values with their provenance, every fault and what was done about it,
    the functions that are switched off, and a missing group.
    """

    config: WindowConfig | None
    settings: ResolvedSettings


def resolve_window(
    *,
    window_id: str,
    members: Iterable[MemberConfig],
    global_settings: PartialSettings,
    window_settings: PartialSettings,
    group: GroupLevel | None = None,
) -> WindowResolution:
    """Resolve :data:`WINDOW_SETTINGS` and build the configuration of one window.

    The window configuration validates itself, and it is the only place with
    value rules: every set value of every level is handed to it on its own,
    and the final configuration is built under the same protection. A refusal
    is a fault of that key on that level and is handled as described for
    :func:`resolve_settings`. The configuration carries the functions that
    were switched off (``WindowConfig.disabled_functions``), so the arbiter
    can skip them and say so. The function does not raise for anything a user
    could have stored.
    """
    try:
        identity = WindowConfig(window_id=window_id, members=tuple(members))
    except (TypeError, ValueError) as err:
        key = (
            "window_id"
            if not isinstance(window_id, str) or not window_id
            else "members"
        )
        fault = ReportedFault(
            key,
            Level.WINDOW,
            SettingProblem.INVALID,
            str(err),
            FaultAction.CONFIGURATION_WITHHELD,
        )
        return WindowResolution(None, ResolvedSettings({}, (fault,)))

    def check_value(key: str, value: object) -> None:
        change: dict[str, Any] = {key: value}
        dataclasses.replace(identity, **change)

    def build(
        effective: Mapping[str, Any], disabled: frozenset[FunctionId]
    ) -> WindowConfig:
        return dataclasses.replace(identity, **effective, disabled_functions=disabled)

    resolved, config = _resolve(
        WINDOW_SETTINGS,
        capabilities=identity.capability_states,
        members=identity.members,
        global_settings=global_settings,
        window_settings=window_settings,
        group=group,
        rules=SettingRules(check_value, build),
    )
    return WindowResolution(
        config if isinstance(config, WindowConfig) else None, resolved
    )
