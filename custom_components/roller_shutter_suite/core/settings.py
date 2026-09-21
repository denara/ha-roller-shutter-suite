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
import math
import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from enum import Enum, StrEnum, unique
from types import MappingProxyType
from typing import Any, Final

from .model import (
    GEOMETRY_FIELDS,
    GEOMETRY_PREFIX,
    SCHEDULE_DAY_TYPES,
    SCHEDULE_EDGES,
    TRIGGER_FIELDS,
    CapabilityState,
    CoveringType,
    FaultBehavior,
    FunctionId,
    JsonValue,
    MemberConfig,
    Position,
    ScheduleProfile,
    SettingsCombinationError,
    TemperatureTier,
    TriggerKind,
    WindowCapabilityStates,
    WindowConfig,
)
from .model._data import (
    as_bool,
    as_enum,
    as_int,
    as_object,
    as_str,
    read,
    tuple_of,
)
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
    COMBINATION = "combination"
    """A rule that spans several settings refuses the combination of the
    effective values; each of them may be fine on its own."""
    RULE_WITHOUT_KEYS = "rule_without_keys"
    """Not a fault of stored data: the whole was refused without naming the
    keys concerned, so nothing can be attributed."""


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

_REFUSALS: Final = (
    TypeError,
    ValueError,
    ArithmeticError,
    LookupError,
    AttributeError,
    RecursionError,
)
"""What a reader or the value rules may raise for a value somebody stored.

A refusal is meant to be a ``ValueError`` or a ``TypeError``. The others are
what Python raises by itself for hostile data: a number too large for a float
(``OverflowError``), data nested too deeply, a lookup in something that is not
what it seemed. None of them may escape, because one stored value would then
stop the set-up of every window.
"""


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
            except _REFUSALS as err:
                faults[key] = SettingFault(key, str(err) or type(err).__name__)
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
    a ``TypeError`` or ``ValueError`` for a value the structure refuses on its
    own. ``build(effective, disabled_functions)`` builds the structure from
    the effective values of all settings; a rule that spans several settings
    speaks up there and raises a ``SettingsCombinationError`` that names the
    keys it concerns. For a window both are ``WindowConfig``.
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
            except SettingsCombinationError:
                # The value is fine on its own; a combination is judged with
                # the effective values of the window, when the whole is built.
                pass
            except _REFUSALS as err:
                detail = str(err) or type(err).__name__
                faults.append(SettingFault(key, detail, SettingProblem.INVALID))
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
    forced_default: bool,
) -> tuple[ResolvedValue[Any], tuple[Level, ...]]:
    """Walk the levels from the window outwards; the first that sets the key decides.

    A level whose value for the key is faulty is passed by, and the walk goes
    on outwards, last to the built-in default. Returned with the value are the
    levels whose fault was reached that way: for this window the faulty value
    would have been the effective one. A fault further out than a sound value
    is never reached.

    ``forced_default`` says that the key takes part in a refused combination
    and belongs to a function that pauses: the walk then ends at the first
    sound value without taking it, and the built-in default stands in. The
    function is paused, so nobody acts on the value; taking a value from
    further out would combine values the user never chose together.
    """
    value: Any = definition.default
    found: Level = Level.BUILT_IN
    found_group: str | None = None
    reached: list[Level] = []
    for level in levels:
        if level.is_faulty(definition.key):
            reached.append(level.level)
        elif definition.key in level.values:
            if not forced_default:
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
            elif (
                fault.problem is SettingProblem.NOT_INHERITABLE
                or level.level not in reached[fault.key]
            ):
                # A key that cannot be inherited could never have been the
                # effective value of any window from up there.
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
    forced: frozenset[str] = frozenset(),
) -> tuple[dict[str, ResolvedValue[Any]], tuple[ReportedFault, ...]]:
    """Resolve every setting of the registry over the given levels."""
    values: dict[str, ResolvedValue[Any]] = {}
    reached: dict[str, tuple[Level, ...]] = {}
    for definition in registry.definitions:
        values[definition.key], reached[definition.key] = _resolve_one(
            definition, levels, capabilities, members, definition.key in forced
        )
    return values, _report(registry, levels, reached)


def _pauses(definition: SettingDefinition[Any]) -> bool:
    """Return whether a fault in the setting pauses its function."""
    return (
        definition.function is not None
        and definition.fault_behavior is FaultBehavior.PAUSE
    )


@dataclass(slots=True)
class _Refusals:
    """What one resolution has done about refusals of the whole so far."""

    forced: set[str] = field(default_factory=set)
    reports: list[ReportedFault] = field(default_factory=list)
    unattributed: int = 0


def _refused_combination(
    registry: SettingsRegistry,
    levels: list[_LevelInput],
    values: Mapping[str, ResolvedValue[Any]],
    error: Exception,
    state: _Refusals,
) -> bool:
    """Make the keys a refused combination concerns faulty; say whether any were.

    The refusal names its keys (``SettingsCombinationError``). Only those keys
    are touched, each by the fault behavior of its function, and only where a
    level supplies the effective value; a built-in default is nobody's fault.

    - Keys of a function that **pauses**: the level that supplies the value
      gets a fault of the kind ``combination``, the function is paused by the
      ordinary rule, and the built-in default stands in for the value.
    - Keys of a function that **falls back**, only when no pausing key was
      left to handle: the innermost level that supplies one of them is passed
      by for the keys it supplies, and the build is tried again.

    Sound values of other settings are never touched or reported.
    """
    if not isinstance(error, SettingsCombinationError):
        return False
    definitions = {definition.key: definition for definition in registry.definitions}
    involved = [
        values[key]
        for key in error.keys
        if key in values
        and values[key].level is not Level.BUILT_IN
        and key not in state.forced
    ]
    pausing = [item for item in involved if _pauses(definitions[item.key])]
    if pausing:
        blamed = pausing
        state.forced.update(item.key for item in pausing)
    else:
        order = (Level.GLOBAL, Level.GROUP, Level.WINDOW)
        innermost = max(
            (item.level for item in involved), key=order.index, default=None
        )
        blamed = [item for item in involved if item.level is innermost]
    for item in blamed:
        index = next(i for i, level in enumerate(levels) if level.level is item.level)
        levels[index] = levels[index].blamed(
            SettingFault(item.key, str(error), SettingProblem.COMBINATION)
        )
    return bool(blamed)


def _refused_without_keys(
    registry: SettingsRegistry, error: Exception, state: _Refusals
) -> bool:
    """Handle a refusal that cannot be attributed; say whether anything is left to try.

    A rule that does not name its keys is a programming error, not a fault of
    stored data. Protection has to keep running all the same, so the window
    is not given up at once: first every function that pauses is paused and
    its settings take their defaults; if the whole is still refused, the
    settings of the functions that fall back take their defaults as well;
    only if even the built-in defaults are refused is the configuration
    withheld.
    """
    detail = str(error) or type(error).__name__
    state.unattributed += 1
    if state.unattributed == 1:
        state.forced.update(
            definition.key for definition in registry.definitions if _pauses(definition)
        )
        action, disabled = FaultAction.FUNCTIONS_DISABLED, registry.pausable_functions
    elif state.unattributed == 2:  # noqa: PLR2004 - the second of three steps
        state.forced.update(registry.keys)
        action, disabled = FaultAction.FELL_BACK, ()
    else:
        action, disabled = FaultAction.CONFIGURATION_WITHHELD, ()
    state.reports.append(
        ReportedFault(
            SETTINGS_KEY,
            Level.BUILT_IN,
            SettingProblem.RULE_WITHOUT_KEYS,
            detail,
            action,
            disabled,
        )
    )
    return action is not FaultAction.CONFIGURATION_WITHHELD


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

    state = _Refusals()
    while True:
        values, faults = _resolve_levels(
            registry, tuple(levels), capabilities, members, frozenset(state.forced)
        )
        resolved = ResolvedSettings(values, (*faults, *state.reports), group_missing)
        if rules is None:
            return resolved, None
        try:
            return resolved, rules.build(
                resolved.effective(), resolved.disabled_functions
            )
        except _REFUSALS as err:
            if _refused_combination(registry, levels, values, err, state):
                continue
            if _refused_without_keys(registry, err, state):
                continue
        return (
            ResolvedSettings(values, (*faults, *state.reports), group_missing),
            None,
        )


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

    **A rule that spans several settings** refuses the whole with a
    ``SettingsCombinationError`` that names the keys it concerns. Only those
    keys become faulty (``combination``), on the levels that supply their
    effective values, and each is judged by the fault behavior of its
    function: a function that pauses is paused and its key takes the
    built-in default; for functions that fall back the innermost level that
    supplies one of the keys is passed by, and the build is tried again. A
    sound value of a setting the rule does not concern is never touched,
    reported or blamed. A refusal that names no keys cannot be attributed
    (``rule_without_keys``): every function that pauses is paused, then the
    settings that fall back take their defaults, and only if the defaults
    are refused too is the configuration withheld.

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

MAX_DURATION_SECONDS: Final = 366 * 24 * 60 * 60
"""The longest duration a setting can store: 366 days, in seconds.

Generous on purpose: no setting of a shutter needs more than a year. The bound
keeps a number that somebody stored from being too large for a duration.
"""


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
    """Read a setting of the kind ``duration``: whole seconds, 0 to 366 days."""
    seconds = as_int(value)
    if not 0 <= seconds <= MAX_DURATION_SECONDS:
        raise ValueError(
            f"expected a number of seconds from 0 to {MAX_DURATION_SECONDS} (366 days)"
        )
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
    """Return the finite number; a boolean is not a number.

    JSON carries whole numbers of any size and, from some writers, infinity
    and "not a number"; none of them is a temperature.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("expected a number")  # noqa: TRY004
    try:
        number = float(value)
    except OverflowError:
        number = math.inf
    if not math.isfinite(number):
        raise ValueError("expected a finite number")
    return number


def _as_position(value: JsonValue) -> Position:
    """Return a position: a whole number from 0 to 100."""
    return Position(as_int(value))


def _as_temperature_tier(value: JsonValue) -> TemperatureTier:
    """Return one tier of the temperature condition of shading."""
    data = as_object(value, "threshold", "hysteresis")
    return TemperatureTier(
        threshold=read(data, "threshold", _as_number),
        hysteresis=read(data, "hysteresis", _as_number),
    )


def _signed_minutes(value: JsonValue) -> int:
    """Return a whole number of minutes; it may be negative."""
    return as_int(value)


_TRIGGER_FIELD_KINDS: Final[
    Mapping[str, tuple[SettingKind, Callable[[JsonValue], Any]]]
] = MappingProxyType(
    {
        "kind": (SettingKind.ENUMERATION, as_enum(TriggerKind)),
        "time": (SettingKind.TIME, as_time),
        "offset_minutes": (SettingKind.NUMBER, _signed_minutes),
        "elevation": (SettingKind.NUMBER, _as_number),
        "not_before": (SettingKind.TIME, as_time),
        "not_after": (SettingKind.TIME, as_time),
    }
)
"""Kind and reader of every field of a trigger of the schedule."""


def _schedule_setting(
    key: str, kind: SettingKind, parse: Callable[[JsonValue], Any]
) -> SettingDefinition[Any]:
    """Return one setting of the schedule; its default is that of the field.

    The built-in defaults of the schedule stand in one place, at the fields
    of ``WindowConfig``; this entry reads them from there.
    """
    defaults = {entry.name: entry.default for entry in dataclasses.fields(WindowConfig)}
    return SettingDefinition(
        key=key,
        kind=kind,
        function=FunctionId.SCHEDULE,
        default=defaults[key],
        parse=parse,
    )


def schedule_trigger_keys() -> tuple[str, ...]:
    """Return the keys of the trigger settings: day type, edge, field.

    The registry entries are generated from this one list, and the tests walk
    the same list, so no entry can be forgotten or mistyped.
    """
    return tuple(key for key, _ in _trigger_entries())


def _trigger_entries() -> tuple[tuple[str, str], ...]:
    """Return every trigger setting as (key, field of the trigger)."""
    return tuple(
        (f"schedule_{day_type}_{edge}_{name}", name)
        for day_type in SCHEDULE_DAY_TYPES
        for edge in SCHEDULE_EDGES
        for name in TRIGGER_FIELDS
    )


def _schedule_settings() -> tuple[SettingDefinition[Any], ...]:
    triggers = tuple(
        _schedule_setting(key, *_TRIGGER_FIELD_KINDS[name])
        for key, name in _trigger_entries()
    )
    boolean, number = SettingKind.BOOLEAN, SettingKind.NUMBER
    reference, duration = SettingKind.OPTIONAL_REFERENCE, SettingKind.DURATION
    others = (
        ("schedule_enabled", boolean, as_bool),
        ("schedule_morning_position", number, _as_position),
        ("schedule_evening_position", number, _as_position),
        ("schedule_evening_position_summer", number, _as_position),
        ("schedule_workday_source", reference, as_str),
        ("schedule_holiday_source", reference, as_str),
        ("schedule_season_source", reference, as_str),
        ("schedule_summer_by_date", boolean, as_bool),
        ("schedule_summer_first_day", SettingKind.DAY_OF_YEAR, as_day_of_year),
        ("schedule_summer_last_day", SettingKind.DAY_OF_YEAR, as_day_of_year),
        ("schedule_brightness_source", reference, as_str),
        # In lux: the unit the brightness source has to report in.
        ("schedule_brightness_threshold", number, _as_number),
        ("schedule_brightness_delay", duration, as_duration),
        ("schedule_random_offset", duration, as_duration),
    )
    return (*triggers, *(_schedule_setting(*entry) for entry in others))


_GEOMETRY_FIELD_KINDS: Final[
    Mapping[str, tuple[SettingKind, Callable[[JsonValue], Any]]]
] = MappingProxyType(
    {
        "use_measurements": (SettingKind.BOOLEAN, as_bool),
        "fixed_position": (SettingKind.NUMBER, _as_position),
        "orientation_known": (SettingKind.BOOLEAN, as_bool),
        # Degrees; an azimuth runs clockwise from north.
        "orientation": (SettingKind.NUMBER, _as_number),
        "view_left": (SettingKind.NUMBER, _as_number),
        "view_right": (SettingKind.NUMBER, _as_number),
        "min_elevation": (SettingKind.NUMBER, _as_number),
        "end_elevation": (SettingKind.NUMBER, _as_number),
        # Metres.
        "element_bottom": (SettingKind.NUMBER, _as_number),
        "element_height": (SettingKind.NUMBER, _as_number),
        "depth": (SettingKind.NUMBER, _as_number),
        "pitch": (SettingKind.NUMBER, _as_number),
        "amplification_cap": (SettingKind.NUMBER, _as_number),
        "calibration_seat": (SettingKind.NUMBER, _as_position),
        "calibration_glass_top": (SettingKind.NUMBER, _as_position),
    }
)
"""Kind and reader of every window-level measurement of shading."""


def shading_geometry_keys() -> tuple[str, ...]:
    """Return the keys of the window-level measurements of shading.

    They are the fields of ``WindowConfig.geometry`` with the prefix in
    front; the registry entries are generated from this one list.
    """
    return tuple(f"{GEOMETRY_PREFIX}{name}" for name in GEOMETRY_FIELDS)


def _shading_geometry_settings() -> tuple[SettingDefinition[Any], ...]:
    """Return the measurements of shading; their defaults are those of the fields.

    They belong to ``shading``, which pauses on a fault: a faulty measurement
    never moves a shutter to a position somebody else's numbers gave.
    """
    defaults = {entry.name: entry.default for entry in dataclasses.fields(WindowConfig)}
    return tuple(
        SettingDefinition(
            key=key,
            kind=_GEOMETRY_FIELD_KINDS[name][0],
            function=FunctionId.SHADING,
            default=defaults[key],
            parse=_GEOMETRY_FIELD_KINDS[name][1],
        )
        for key, name in zip(shading_geometry_keys(), GEOMETRY_FIELDS, strict=True)
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
        SettingDefinition[str | None](
            key="frost_source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            function=FunctionId.FROST,
            default=None,
            parse=as_str,
        ),
        SettingDefinition(
            key="frost_threshold",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=0.0,
            parse=_as_number,
        ),
        SettingDefinition(
            key="frost_hysteresis",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=1.0,
            parse=_as_number,
        ),
        SettingDefinition(
            key="frost_position",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=Position(90),
            parse=_as_position,
        ),
        SettingDefinition(
            key="frost_applies_to_protection",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.FROST,
            default=False,
            parse=as_bool,
        ),
        SettingDefinition(
            key="frost_hold_closed",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.FROST,
            default=False,
            parse=as_bool,
        ),
        SettingDefinition(
            key="motor_min_change",
            kind=SettingKind.NUMBER,
            function=FunctionId.MOTOR_PROTECTION,
            default=5,
            parse=as_int,
        ),
        SettingDefinition(
            key="motor_min_interval",
            kind=SettingKind.DURATION,
            function=FunctionId.MOTOR_PROTECTION,
            default=timedelta(minutes=10),
            parse=as_duration,
        ),
        # The upper bound of a deferral that waits for a report of a member (a
        # member becomes available, the members come to rest). Waiting for the
        # reports of members is what command verification is about, and like
        # everything that restricts movement it falls back on a fault.
        SettingDefinition(
            key="reevaluate_after",
            kind=SettingKind.DURATION,
            function=FunctionId.COMMAND_VERIFICATION,
            default=timedelta(minutes=5),
            parse=as_duration,
        ),
        *_schedule_settings(),
        *_shading_geometry_settings(),
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
    except _REFUSALS as err:
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
