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
**Fall back:** whatever protects or restricts movement never fails, and a fault
never loosens it; the faulty value is passed by and another level supplies a
valid one, or else the cautious fault value of the setting applies, not its
default. **Pause:** a function that
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
    BLIND_SOURCE,
    FULLY_CLOSED,
    FULLY_OPEN,
    GEOMETRY_FIELDS,
    GEOMETRY_PREFIX,
    MAX_RANDOM_OFFSET,
    MAX_STAGGER_GAP,
    MAX_SUN_OFFSET_MINUTES,
    MAX_TOLERANCE,
    MAX_TRIGGER_ELEVATION,
    MEMBER_MEASUREMENT_FIELDS,
    SCHEDULE_DAY_TYPES,
    SCHEDULE_EDGES,
    TRIGGER_FIELDS,
    BlindSource,
    CapabilityState,
    CoveringType,
    FaultBehavior,
    FunctionId,
    JsonValue,
    MemberConfig,
    MemberGlassError,
    MemberMeasurements,
    Position,
    ScheduleProfile,
    SettingsCombinationError,
    TemperatureTier,
    TriggerKind,
    WindowCapabilityStates,
    WindowConfig,
    member_glass_for,
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
    MEMBER = "member"
    """One member of the window; only member-level settings have this level."""


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


@unique
class NoFaultValue(Enum):
    """The type of the marker :data:`NO_FAULT_VALUE`. It has exactly one member."""

    NO_FAULT_VALUE = "no_fault_value"


NO_FAULT_VALUE: Final = NoFaultValue.NO_FAULT_VALUE
"""The setting states no fault value: a fault pauses its function, or it has none.

It is a marker of its own, because ``None``, ``False`` and ``0`` are fault
values somebody may state.
"""


_KINDS_WITH_A_RANGE: Final = frozenset({SettingKind.NUMBER, SettingKind.DURATION})


def format_number(value: float) -> str:
    """Return a number as language-neutral text; a whole number has no fraction.

    ``80.0`` is ``"80"``, ``22.5`` is ``"22.5"``, ``-720`` is ``"-720"``. The
    one place where a number of a setting becomes text for a user, so that a
    whole number never appears as ``80.0``.
    """
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


@dataclass(frozen=True, slots=True)
class ValueRange:
    """The range of a number or a duration, both bounds included.

    The bounds are in the stored unit: a duration in seconds, a number in the
    unit of its entry. ``None`` means "no bound on this side". The reader of
    the setting refuses a value outside the range, the forms give their
    number boxes these bounds, and the documentation states them, so the
    range exists once.
    """

    minimum: float | None = None
    maximum: float | None = None

    def __post_init__(self) -> None:
        """Validate the bounds."""
        bounds = [bound for bound in (self.minimum, self.maximum) if bound is not None]
        if not bounds:
            raise ValueError("a range has at least one bound")
        for bound in bounds:
            if isinstance(bound, bool) or not isinstance(bound, (int, float)):
                raise TypeError("the bound of a range must be a number")
            if not math.isfinite(bound):
                raise ValueError("the bound of a range must be finite")
        if len(bounds) == 2 and bounds[0] > bounds[1]:  # noqa: PLR2004 - two bounds
            raise ValueError("the minimum of a range lies above its maximum")

    def contains(self, value: float) -> bool:
        """Return whether the number lies within the range."""
        return (self.minimum is None or value >= self.minimum) and (
            self.maximum is None or value <= self.maximum
        )

    def refusal(self) -> str:
        """Return the English text of a refusal, for logs."""
        if self.maximum is None:
            return f"expected a value of at least {format_number(self.minimum or 0)}"
        if self.minimum is None:
            return f"expected a value of at most {format_number(self.maximum)}"
        return (
            f"expected a value from {format_number(self.minimum)} "
            f"to {format_number(self.maximum)}"
        )


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
    - ``fault_value``: the **cautious value** of a setting whose function falls
      back. It is effective when a level tried to set the value and could not
      (a faulty value), or could have set it and nobody can see whether it did
      (a level that is unreadable as a whole), and no other level supplies a
      valid value. A fault must never make a function that restricts movement
      less restrictive than a valid value would, and a default often means
      "not configured" or "off". So the fault value is stated on purpose, also
      where it equals the default: the argument has no silent default, and an
      entry of a function that falls back does not construct without it. For
      a setting whose function pauses, and for a setting without a function,
      it does not exist and is refused: a fault pauses the function, or
      nothing depends on the setting.
    - ``parse``: reads the value from stored data and raises a ``ValueError``
      if it cannot. It is never called for an absent key, blank text,
      ``null`` or :data:`STORED_NONE`.
    - ``inheritable``: ``False`` for what belongs to one window only (the
      cover itself, measurements). Such a setting is read from the window
      level alone; on a group or the house it is a fault.
    - ``requires``: the capability the setting needs, if any.
    - ``value_range``: the range of a number or a duration, in the stored
      unit (seconds for a duration). :func:`settings_from_stored` refuses a
      stored number outside it as ``invalid``,
      the forms give their number boxes its bounds, and the documentation
      states it. ``None``: the setting has no range of its own.
    - ``unit``: the unit of a number, as the forms show it (``"%"``,
      ``"lx"``). A duration has none here: it is stored in seconds, and a
      form says in which unit it is entered.
    """

    key: str
    kind: SettingKind
    function: FunctionId | None
    default: T
    parse: Callable[[JsonValue], T]
    inheritable: bool = True
    requires: CapabilityRequirement[T] | None = None
    fault_value: T | NoFaultValue = NO_FAULT_VALUE
    value_range: ValueRange | None = None
    unit: str | None = None

    def __post_init__(self) -> None:
        """Validate the description itself."""
        require_identifier(self.key, "the key of a setting")
        require_type(self.kind, SettingKind, "the kind of a setting")
        require_type(self.inheritable, bool, "the flag 'inheritable'")
        if self.value_range is not None:
            require_type(self.value_range, ValueRange, "the range of a setting")
            if self.kind not in _KINDS_WITH_A_RANGE:
                raise ValueError(
                    f"the setting {self.key!r} is a {self.kind.value}; only a "
                    "number or a duration has a range"
                )
        if self.unit is not None:
            require_identifier(self.unit, "the unit of a setting")
            if self.kind is not SettingKind.NUMBER:
                raise ValueError(
                    f"the setting {self.key!r} is a {self.kind.value}; only a "
                    "number states a unit"
                )
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
        if self.function is not None and self.falls_back_cautiously:
            if not self.has_fault_value:
                raise ValueError(
                    f"the setting {self.key!r} belongs to the function "
                    f"{self.function.value!r}, which falls back on a fault, so it "
                    "states its fault value: add 'fault_value=<the cautious "
                    "value>', the value that applies when a stored value is "
                    "faulty and no level supplies a valid one. It must never make "
                    "the function less restrictive than a valid value would; if "
                    "that is the default, state the default"
                )
        elif self.has_fault_value:
            raise ValueError(
                f"the setting {self.key!r} has no fault value: a fault pauses its "
                "function, or it belongs to none; remove 'fault_value'"
            )

    @property
    def has_fault_value(self) -> bool:
        """Return whether the setting states a fault value."""
        return self.fault_value is not NO_FAULT_VALUE

    @property
    def falls_back_cautiously(self) -> bool:
        """Return whether a fault ends at the fault value: a function that falls back.

        A setting without a function falls back too, but to its default:
        nothing depends on it.
        """
        return (
            self.function is not None
            and self.function.fault_behavior is FaultBehavior.FALL_BACK
        )

    @property
    def fault_behavior(self) -> FaultBehavior:
        """Return the behavior of the setting's function; without one, fall back."""
        if self.function is None:
            return FaultBehavior.FALL_BACK
        return self.function.fault_behavior

    def out_of_range(self, value: JsonValue) -> bool:
        """Return whether a stored number lies outside the range of the setting."""
        return (
            self.value_range is not None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and not self.value_range.contains(value)
        )


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
_BLIND_FAULT: Final = (
    "the marker for a source that is configured, but blind, cannot be set; only "
    "the resolver produces it"
)
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
    - a number outside the range of its entry is a fault (``invalid``): it can
      be read, but the setting does not take it;
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
        elif definition.value_range is not None and definition.out_of_range(raw):
            # Readable, but outside the range of the entry: the one place that
            # applies the range to stored data.
            faults[key] = SettingFault(
                key, definition.value_range.refusal(), SettingProblem.INVALID
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

    ``cautious`` is true when ``value`` is the **fault value** of the setting
    and not its default: a level tried to set the value and could not, or is
    unreadable as a whole, and no other level supplied a valid one. ``level``
    is ``built_in`` then, because no level of the installation supplied it;
    the flag tells the two built-in values apart.
    """

    key: str
    value: T
    effective: T
    level: Level
    group_id: str | None = None
    capability: CapabilityState | None = None
    unavailable: MissingCapability | None = None
    cautious: bool = False
    member_id: str | None = None
    """The member, for a value the member states itself (level ``member``)."""

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
    """Fall back: the faulty value is passed by; another level supplies a valid
    value. For a setting without a function, the built-in default may supply it."""
    FELL_BACK_TO_CAUTIOUS_VALUE = "fell_back_to_cautious_value"
    """Fall back, and no level supplies a valid value: the **fault value** of the
    setting is effective, not its default, so the function is never less
    restrictive than a valid value would have made it. The window now runs on
    a value nobody chose, which is what a repair issue has to say; after
    ``fell_back`` it runs on a value somebody chose on another level."""
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
    capability is never a fault; see :class:`ResolvedValue`. ``member_id``
    names the member for a fault on the level ``member``.
    """

    key: str
    level: Level
    problem: SettingProblem
    detail: str
    action: FaultAction
    disabled_functions: tuple[FunctionId, ...] = ()
    group_id: str | None = None
    member_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    """The result of resolving a registry for one window.

    ``values`` has one entry per setting of the registry, in its order.
    ``faults`` lists every fault on the levels of this window (the window, its
    group, the house) once, with what it costs **this** window; a fault that
    does not reach the window has the action ``no_effect``. ``group_missing``
    is set when the window refers to a group that no longer exists.
    ``member_values`` has, per member and per member-level setting, the value
    that applies to the member with its provenance: the level ``member`` for
    a value the member states, else the level that gave the window's value.
    It is empty where no member level was resolved.
    """

    values: Mapping[str, ResolvedValue[Any]]
    faults: tuple[ReportedFault, ...] = ()
    group_missing: GroupMissing | None = None
    member_values: Mapping[str, Mapping[str, ResolvedValue[Any]]] = field(
        default_factory=dict
    )

    def __post_init__(self) -> None:
        """Copy the mappings so they cannot be changed afterwards."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        members = {
            member_id: MappingProxyType(dict(values))
            for member_id, values in dict(self.member_values).items()
        }
        object.__setattr__(self, "member_values", MappingProxyType(members))

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

    @property
    def unreadable(self) -> bool:
        """Return whether the settings of the level are unreadable as a whole."""
        return any(
            fault.problem is SettingProblem.LEVEL_UNREADABLE for fault in self.faults
        )

    def could_have_set(self, definition: SettingDefinition[Any]) -> bool:
        """Return whether an unreadable level may hide a value of the setting.

        Nobody can see what an unreadable level held. It could have held
        every setting that can be set on it: on the window all of them, on a
        group or the house the inheritable ones only.
        """
        return self.unreadable and (
            definition.inheritable or self.level is Level.WINDOW
        )

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
        if isinstance(value, BlindSource):
            # "Configured, but blind" is what a fault ends at. No level can
            # say it: a level that names no source says none.
            faults.append(SettingFault(key, _BLIND_FAULT, SettingProblem.INVALID))
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
    on outwards. Returned with the value are the levels whose fault was
    reached that way: for this window the faulty value would have been the
    effective one. A fault further out than a sound value is never reached.
    A level that is unreadable as a whole is passed by in the same way, for
    every setting it could have held.

    If the walk ends without a valid value, what applies depends on how it
    got there. No level was passed by: nobody tried to set the value, and the
    built-in default applies. A level was passed by, and the setting belongs
    to a function that falls back: the **fault value** applies, not the
    default, because a fault never makes such a function less restrictive
    than a valid value would (``cautious`` of the result says so). A setting
    without a function takes its default; nothing depends on it.

    ``forced_default`` says that the key must not take a value of any level.
    It takes part in a refused combination and belongs to a function that
    pauses: the walk then ends at the first sound value without taking it,
    and the built-in default stands in. The function is paused, so nobody
    acts on the value; taking a value from further out would combine values
    the user never chose together. Or a refusal of the whole could not be
    attributed at all, and every setting is forced: one of a function that
    falls back then takes its fault value.
    """
    value: Any = definition.default
    found: Level = Level.BUILT_IN
    found_group: str | None = None
    reached: list[Level] = []
    for level in levels:
        if level.is_faulty(definition.key) or level.could_have_set(definition):
            reached.append(level.level)
        elif definition.key in level.values:
            if not forced_default:
                value, found, found_group = (
                    level.values[definition.key],
                    level.level,
                    level.group_id,
                )
            break
    cautious = (
        found is Level.BUILT_IN
        and definition.falls_back_cautiously
        and (forced_default or bool(reached))
    )
    if cautious:
        value = definition.fault_value
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
        cautious=cautious,
    )
    return resolved, tuple(reached)


def _hidden_by(
    level: _LevelInput,
    fault: SettingFault,
    values: Mapping[str, ResolvedValue[Any]],
    reached: Mapping[str, tuple[Level, ...]],
) -> list[ReportedFault]:
    """Name the settings that run on their fault value because a level is unreadable.

    One entry per setting, with the unreadable level and the action
    ``fell_back_to_cautious_value``, so a repair issue can name each of them.
    """
    return [
        ReportedFault(
            key,
            level.level,
            fault.problem,
            fault.detail,
            FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE,
            (),
            level.group_id,
        )
        for key, item in values.items()
        if item.cautious and level.level in reached[key]
    ]


def _report(
    registry: SettingsRegistry,
    levels: tuple[_LevelInput, ...],
    values: Mapping[str, ResolvedValue[Any]],
    reached: Mapping[str, tuple[Level, ...]],
) -> tuple[ReportedFault, ...]:
    """List every fault of every level once, with what it costs this window.

    A level that is unreadable as a whole is listed once as a whole and once
    more for every setting that runs on its fault value because of it.
    """
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
            elif values[fault.key].cautious:
                action = FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE
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
            if fault.problem is SettingProblem.LEVEL_UNREADABLE:
                reports.extend(_hidden_by(level, fault, values, reached))
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
    return values, _report(registry, levels, values, reached)


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
    settings of the functions that fall back take their fault values (a
    setting without a function its default): what they restrict stays
    restricted; only if even these built-in values are refused is the
    configuration withheld.
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
        action, disabled = FaultAction.FELL_BACK_TO_CAUTIOUS_VALUE, ()
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
      outwards; ``level`` of the resolved value says which level finally
      supplied it (``fell_back``). If no level supplies a valid value, the
      **fault value** of the setting applies, not its default
      (``fell_back_to_cautious_value``, and ``cautious`` of the resolved
      value): a fault never makes a function that restricts movement less
      restrictive than a valid value would. Nothing is paused.
    - **pause:** the **function** of the setting is paused for this window,
      so it never moves unexpectedly because of a data fault. The value is
      resolved in the same way, but the arbiter does not act on it.
    - **an unknown key** is reported and switches nothing off: a newer
      version may have written it.
    - **a level that is unreadable as a whole** counts as not present: every
      function that a fault pauses is paused for the windows in whose chain
      the level lies, and the functions that fall back take the values of the
      other levels. Nobody can see whether the unreadable level had set a
      value, so a setting of a function that falls back **that the level
      could have held** and that no other level supplies takes its fault
      value, and the result names each such setting with the level. A
      setting that cannot be inherited is touched by an unreadable window
      only, never by an unreadable group or house.

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
    settings that fall back take their fault values, and only if these
    built-in values are refused too is the configuration withheld.

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


POSITION_RANGE: Final = ValueRange(FULLY_CLOSED.value, FULLY_OPEN.value)
"""The range of a position: 0 (fully closed) to 100 (fully open)."""

PERCENT: Final = "%"

_NOT_NEGATIVE: Final = ValueRange(minimum=0)


@dataclass(frozen=True, slots=True)
class _Reader:
    """Kind, reader, range and unit of a setting that is generated from a list."""

    kind: SettingKind
    parse: Callable[[JsonValue], Any]
    value_range: ValueRange | None = None
    unit: str | None = None


_TRIGGER_FIELD_KINDS: Final[Mapping[str, _Reader]] = MappingProxyType(
    {
        "kind": _Reader(SettingKind.ENUMERATION, as_enum(TriggerKind)),
        "time": _Reader(SettingKind.TIME, as_time),
        "offset_minutes": _Reader(
            SettingKind.NUMBER,
            _signed_minutes,
            ValueRange(-MAX_SUN_OFFSET_MINUTES, MAX_SUN_OFFSET_MINUTES),
            "min",
        ),
        "elevation": _Reader(
            SettingKind.NUMBER,
            _as_number,
            ValueRange(-MAX_TRIGGER_ELEVATION, MAX_TRIGGER_ELEVATION),
            "°",
        ),
        "not_before": _Reader(SettingKind.TIME, as_time),
        "not_after": _Reader(SettingKind.TIME, as_time),
    }
)
"""Kind, reader, range and unit of every field of a trigger of the schedule."""


def _schedule_setting(key: str, reader: _Reader) -> SettingDefinition[Any]:
    """Return one setting of the schedule; its default is that of the field.

    The built-in defaults of the schedule stand in one place, at the fields
    of ``WindowConfig``; this entry reads them from there.
    """
    defaults = {entry.name: entry.default for entry in dataclasses.fields(WindowConfig)}
    return SettingDefinition(
        key=key,
        kind=reader.kind,
        function=FunctionId.SCHEDULE,
        default=defaults[key],
        parse=reader.parse,
        value_range=reader.value_range,
        unit=reader.unit,
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
        _schedule_setting(key, _TRIGGER_FIELD_KINDS[name])
        for key, name in _trigger_entries()
    )
    boolean, number = SettingKind.BOOLEAN, SettingKind.NUMBER
    reference, duration = SettingKind.OPTIONAL_REFERENCE, SettingKind.DURATION
    position = _Reader(number, _as_position, POSITION_RANGE, PERCENT)
    others = (
        ("schedule_enabled", _Reader(boolean, as_bool)),
        ("schedule_morning_position", position),
        ("schedule_evening_position", position),
        ("schedule_evening_position_summer", position),
        ("schedule_workday_source", _Reader(reference, as_str)),
        ("schedule_holiday_source", _Reader(reference, as_str)),
        ("schedule_season_source", _Reader(reference, as_str)),
        ("schedule_summer_by_date", _Reader(boolean, as_bool)),
        (
            "schedule_summer_first_day",
            _Reader(SettingKind.DAY_OF_YEAR, as_day_of_year),
        ),
        ("schedule_summer_last_day", _Reader(SettingKind.DAY_OF_YEAR, as_day_of_year)),
        ("schedule_brightness_source", _Reader(reference, as_str)),
        # In lux: the unit the brightness source has to report in.
        (
            "schedule_brightness_threshold",
            _Reader(number, _as_number, _NOT_NEGATIVE, "lx"),
        ),
        ("schedule_brightness_delay", _Reader(duration, as_duration, _NOT_NEGATIVE)),
        (
            "schedule_random_offset",
            _Reader(
                duration,
                as_duration,
                ValueRange(0, MAX_RANDOM_OFFSET.total_seconds()),
            ),
        ),
    )
    return (*triggers, *(_schedule_setting(*entry) for entry in others))


_GEOMETRY_POSITION: Final = _Reader(
    SettingKind.NUMBER, _as_position, POSITION_RANGE, PERCENT
)

_GEOMETRY_FIELD_KINDS: Final[Mapping[str, _Reader]] = MappingProxyType(
    {
        "use_measurements": _Reader(SettingKind.BOOLEAN, as_bool),
        "fixed_position": _GEOMETRY_POSITION,
        "orientation_known": _Reader(SettingKind.BOOLEAN, as_bool),
        # Degrees; an azimuth runs clockwise from north.
        "orientation": _Reader(SettingKind.NUMBER, _as_number),
        "view_left": _Reader(SettingKind.NUMBER, _as_number),
        "view_right": _Reader(SettingKind.NUMBER, _as_number),
        "min_elevation": _Reader(SettingKind.NUMBER, _as_number),
        "end_elevation": _Reader(SettingKind.NUMBER, _as_number),
        # Metres.
        "element_bottom": _Reader(SettingKind.NUMBER, _as_number),
        "element_height": _Reader(SettingKind.NUMBER, _as_number),
        "depth": _Reader(SettingKind.NUMBER, _as_number),
        "pitch": _Reader(SettingKind.NUMBER, _as_number),
        "amplification_cap": _Reader(SettingKind.NUMBER, _as_number),
        "calibration_seat": _GEOMETRY_POSITION,
        "calibration_glass_top": _GEOMETRY_POSITION,
    }
)
"""Kind and reader of every window-level measurement of shading.

Only the positions carry a range here. The other measurements have rules of
their own in ``ShadingGeometrySettings``, and no form shows them yet; the
block that adds their form carries their ranges into these entries.
"""


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
            kind=_GEOMETRY_FIELD_KINDS[name].kind,
            function=FunctionId.SHADING,
            default=defaults[key],
            parse=_GEOMETRY_FIELD_KINDS[name].parse,
            value_range=_GEOMETRY_FIELD_KINDS[name].value_range,
            unit=_GEOMETRY_FIELD_KINDS[name].unit,
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
        # The fault values of the settings that fall back were confirmed by the
        # project owner. Each entry says why its value is the cautious one. Two
        # rules decide: a fault value never makes the function less restrictive
        # for a comfort wish than a valid value would, and a fault ON ITS OWN
        # never restricts a PROTECTION wish more than the default does. (Where
        # a person validly switched "frost applies to protection" on, the
        # cautious values reach protection wishes as valid restrictive values
        # would. Fire is untouched in every case.)
        SettingDefinition[str | BlindSource | None](
            key="frost_source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            function=FunctionId.FROST,
            default=None,
            # "None" means "not configured" and would lift the frost limit.
            # Configured, but blind: the limit stays until somebody repairs
            # the setting or waives frost protection.
            fault_value=BLIND_SOURCE,
            parse=as_str,
        ),
        SettingDefinition(
            key="frost_threshold",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=0.0,
            # The default, stated on purpose. A higher threshold engages
            # earlier, but a number has no most restrictive value; the
            # freezing point never engages later than the approved default.
            fault_value=0.0,
            parse=_as_number,
        ),
        SettingDefinition(
            key="frost_hysteresis",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=1.0,
            # The default, stated on purpose: frost never ends earlier than
            # with the approved band.
            fault_value=1.0,
            parse=_as_number,
        ),
        SettingDefinition(
            key="frost_position",
            kind=SettingKind.NUMBER,
            function=FunctionId.FROST,
            default=Position(90),
            # The default, stated on purpose. Lower would open less, and its
            # extreme, no opening at all in frost, was rejected (decision 13).
            fault_value=Position(90),
            parse=_as_position,
            value_range=POSITION_RANGE,
            unit=PERCENT,
        ),
        SettingDefinition(
            key="frost_applies_to_protection",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.FROST,
            default=False,
            # The default, although "on" restricts more: the switch restricts
            # protection wishes only, and a fault value never restricts a
            # protection wish more than the default does. A hail opening must
            # not stop short because of a data fault.
            fault_value=False,
            parse=as_bool,
        ),
        SettingDefinition(
            key="frost_hold_closed",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.FROST,
            default=False,
            # The more restrictive of the two: a closed shutter is not raised
            # at all in frost. It reaches comfort wishes only, because with
            # the fault value of "applies to protection" the constraint never
            # touches a protection wish.
            fault_value=True,
            parse=as_bool,
        ),
        SettingDefinition(
            key="motor_min_change",
            kind=SettingKind.NUMBER,
            function=FunctionId.MOTOR_PROTECTION,
            default=5,
            # The default, stated on purpose: never smaller than approved;
            # zero would switch the minimum change off.
            fault_value=5,
            parse=as_int,
            value_range=ValueRange(0, MAX_TOLERANCE),
            unit=PERCENT,
        ),
        SettingDefinition(
            key="motor_min_interval",
            kind=SettingKind.DURATION,
            function=FunctionId.MOTOR_PROTECTION,
            default=timedelta(minutes=10),
            # The default, stated on purpose: never shorter than approved.
            fault_value=timedelta(minutes=10),
            parse=as_duration,
            value_range=_NOT_NEGATIVE,
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
            # The default, stated on purpose. Neither direction is "more
            # restrictive": the bound never lets a command through, it only
            # says when a deferred window is evaluated again at the latest.
            fault_value=timedelta(minutes=5),
            parse=as_duration,
            # Longer than zero: the smallest whole number of seconds.
            value_range=ValueRange(minimum=1),
        ),
        # Staggering between motors (E13) spares the motors and the supply of
        # a house from starting all at once: it protects hardware and restricts
        # movement, so it belongs to motor protection and falls back on a
        # fault. The gap is the time reserved after each motor of the window,
        # also between its own members; zero switches staggering off for the
        # motors of this window.
        SettingDefinition(
            key="stagger_gap",
            kind=SettingKind.DURATION,
            function=FunctionId.MOTOR_PROTECTION,
            default=timedelta(seconds=2),
            # The default, stated on purpose. Staggering applies to protection
            # movements too (never to fire), and a longer gap would delay them
            # more than the approved default: a fault on its own never
            # restricts a protection wish more than the default does.
            fault_value=timedelta(seconds=2),
            parse=as_duration,
            value_range=ValueRange(0, MAX_STAGGER_GAP.total_seconds()),
        ),
        *_schedule_settings(),
        *_shading_geometry_settings(),
    )
)
"""The settings of ``WindowConfig``. A new setting is one more entry here.

The key of an entry is the name of its field of ``WindowConfig``. The fields
in :data:`WINDOW_FIELDS_THAT_ARE_NO_SETTINGS` have no entry.
"""


# --- The settings of a member: a fourth level below the window ---------------------
#
# Kept apart from the resolution of the three levels above: a member inherits
# from the RESOLVED window, so this runs after it and changes nothing in it.


@dataclass(frozen=True, slots=True)
class MemberSettingsRegistry:
    """The settings one member of a window can state itself, and what they inherit.

    ``registry`` describes them like any other setting. ``inherits_from`` maps
    every key to the key of the **window** setting whose resolved value
    applies to a member that does not state its own, or to ``None`` if the
    built-in default of the member setting applies.

    **Only a function that pauses on a fault may have member-level
    settings.** A faulty member-level value pauses its function for the whole
    window and never falls back. What a fault would mean for a function that
    falls back (which cautious value applies, and for which member) is not
    defined, so such an entry is refused here until somebody defines it. A
    capability requirement is refused for the same reason: there is no mask
    on this level.
    """

    registry: SettingsRegistry
    inherits_from: Mapping[str, str | None]

    def __post_init__(self) -> None:
        """Validate the entries and that the mapping names exactly their keys."""
        require_type(self.registry, SettingsRegistry, "the registry of member settings")
        object.__setattr__(
            self, "inherits_from", MappingProxyType(dict(self.inherits_from))
        )
        if set(self.inherits_from) != set(self.registry.keys):
            raise ValueError(
                "every member-level setting says what it inherits from, and "
                "nothing else does"
            )
        for definition in self.registry.definitions:
            if not _pauses(definition):
                raise ValueError(
                    f"the member-level setting {definition.key!r} belongs to a "
                    "function that falls back on a fault; what a member-level "
                    "fault of such a function means is not defined yet"
                )
            if definition.requires is not None:
                raise ValueError(
                    f"the member-level setting {definition.key!r} requires a "
                    "capability; there is no capability mask on this level"
                )

    @property
    def pausable_functions(self) -> tuple[FunctionId, ...]:
        """Return the functions a member-level fault pauses, in a stable order."""
        return self.registry.pausable_functions


def _member_settings() -> MemberSettingsRegistry:
    window_keys = (
        "shading_element_height",
        None,
        "shading_calibration_seat",
        "shading_calibration_glass_top",
    )
    inherits = dict(zip(MEMBER_MEASUREMENT_FIELDS, window_keys, strict=True))
    readers = (_as_number, _as_number, _as_position, _as_position)
    defaults = {entry.name: entry.default for entry in dataclasses.fields(WindowConfig)}
    definitions = tuple(
        SettingDefinition(
            key=key,
            kind=SettingKind.NUMBER,
            function=FunctionId.SHADING,
            default=0.0 if window_key is None else defaults[window_key],
            parse=parse,
        )
        for (key, window_key), parse in zip(inherits.items(), readers, strict=True)
    )
    return MemberSettingsRegistry(SettingsRegistry(definitions), inherits)


MEMBER_SETTINGS: Final = _member_settings()
"""What a member of a window can state itself: glass height, top offset and
the two calibration positions, all of the function ``shading``.

``settings_from_stored(data, MEMBER_SETTINGS.registry)`` reads the stored
settings of one member, with the rules of every level. How and where the Home
Assistant side stores them is its own decision; the core takes one mapping
per member. The default of an entry is what applies while no level sets the
window's value either.
"""

_UNKNOWN_MEMBER_FAULT: Final = "the window has no member with this identifier"


@dataclass(slots=True)
class _MemberFaults:
    """The faults of the member level found so far, and the sound stated values."""

    reports: list[ReportedFault] = field(default_factory=list)
    stated: dict[str, dict[str, Any]] = field(default_factory=dict)

    def report(
        self, member_id: str, fault: SettingFault, *, ignored: bool = False
    ) -> None:
        """Report a fault of one member; unless ignored, it pauses the functions."""
        self.reports.append(
            ReportedFault(
                fault.key,
                Level.MEMBER,
                fault.problem,
                fault.detail,
                FaultAction.IGNORED if ignored else FaultAction.FUNCTIONS_DISABLED,
                () if ignored else MEMBER_SETTINGS.pausable_functions,
                member_id=member_id,
            )
        )


def _read_member(
    member_id: str, settings: PartialSettings, found: _MemberFaults
) -> None:
    """Judge every value one member states on its own; keep the sound ones."""
    require_type(settings, PartialSettings, "the settings of a member")
    if settings.unreadable:
        whole = SettingFault(
            SETTINGS_KEY, _LEVEL_FAULT, SettingProblem.LEVEL_UNREADABLE
        )
        found.report(member_id, whole)
        return
    for fault in settings.faults:
        unknown = fault.problem is SettingProblem.UNKNOWN_SETTING
        found.report(member_id, fault, ignored=unknown)
    sound = found.stated.setdefault(member_id, {})
    for key, value in settings.values.items():
        if key not in MEMBER_SETTINGS.registry.keys:
            stranger = SettingFault(key, _UNKNOWN_FAULT, SettingProblem.UNKNOWN_SETTING)
            found.report(member_id, stranger, ignored=True)
            continue
        try:
            single: dict[str, Any] = {key: value}
            MemberMeasurements(**single)
        except _REFUSALS as err:
            detail = str(err) or type(err).__name__
            found.report(member_id, SettingFault(key, detail, SettingProblem.INVALID))
            continue
        sound[key] = value


def _fitting_measurements(
    config: WindowConfig, member_id: str, found: _MemberFaults
) -> MemberMeasurements:
    """Return what the member states, without what a rule over several values refuses.

    The refused values are reported (``combination``), and the member
    inherits in their place, so the configuration builds.
    """
    stated = dict(found.stated.get(member_id, {}))
    while True:
        measurements = MemberMeasurements(**stated)
        try:
            member_glass_for(config.geometry, member_id, measurements)
        except MemberGlassError as err:
            for key in err.fields:
                del stated[key]
                found.report(
                    member_id, SettingFault(key, str(err), SettingProblem.COMBINATION)
                )
            continue
        return measurements


def _member_values(
    config: WindowConfig, window: Mapping[str, ResolvedValue[Any]]
) -> dict[str, dict[str, ResolvedValue[Any]]]:
    """Return every member-level value with its provenance."""
    result: dict[str, dict[str, ResolvedValue[Any]]] = {}
    for member, glass in zip(config.members, config.member_glass, strict=True):
        applying = dict(
            zip(
                MEMBER_MEASUREMENT_FIELDS,
                (
                    glass.glass_height,
                    glass.top_offset,
                    glass.calibration.seat_position,
                    glass.calibration.glass_top_position,
                ),
                strict=True,
            )
        )
        values: dict[str, ResolvedValue[Any]] = {}
        for key, value in applying.items():
            window_key = MEMBER_SETTINGS.inherits_from[key]
            if key in member.measurements.stated:
                values[key] = ResolvedValue(
                    key, value, value, Level.MEMBER, member_id=member.member_id
                )
            elif window_key is None:
                values[key] = ResolvedValue(key, value, value, Level.BUILT_IN)
            else:
                source = window[window_key]
                values[key] = ResolvedValue(
                    key, value, value, source.level, source.group_id
                )
        result[member.member_id] = values
    return result


def _resolve_members(
    config: WindowConfig,
    resolved: ResolvedSettings,
    member_settings: Mapping[str, PartialSettings],
) -> tuple[WindowConfig, ResolvedSettings]:
    """Resolve the member level on top of a resolved window.

    Every fault of a member pauses the functions that have member-level
    settings for the **whole** window: the members are one element with one
    curtain edge and one status, and a fall-back to the window's value would
    move a shutter by a number nobody chose for it. Nothing else is touched:
    no member-level setting belongs to a function that falls back
    (:class:`MemberSettingsRegistry` refuses one), so protection and whatever
    restricts movement keep their values.

    While such a function is paused, by a fault of the window's levels or of
    a member, no member carries measurements of its own in the configuration:
    nobody acts on them. If the window's levels paused it, their values are
    stand-ins, so what the members state is judged value by value, but not
    together with them.
    """
    found = _MemberFaults()
    known = {member.member_id for member in config.members}
    for member_id, settings in member_settings.items():
        if member_id in known:
            _read_member(member_id, settings, found)
        else:
            # Stored data that names something the window does not know, like
            # an unknown key: the same problem code, reported and ignored. The
            # key is that of the settings as a whole, and ``member_id`` names
            # the stranger. No problem code of its own: the Home Assistant
            # side explains every code on every level it knows, and the block
            # that builds the member forms adds what the member level needs.
            stranger = SettingFault(
                SETTINGS_KEY, _UNKNOWN_MEMBER_FAULT, SettingProblem.UNKNOWN_SETTING
            )
            found.report(str(member_id), stranger, ignored=True)
    pausable = frozenset(MEMBER_SETTINGS.pausable_functions)
    fitting: dict[str, MemberMeasurements] = {}
    if not pausable & config.disabled_functions:
        fitting = {
            member.member_id: _fitting_measurements(config, member.member_id, found)
            for member in config.members
        }
    paused = frozenset(
        function for fault in found.reports for function in fault.disabled_functions
    )
    if paused:
        fitting = {}
    config = dataclasses.replace(
        config,
        members=tuple(
            dataclasses.replace(
                member,
                measurements=fitting.get(member.member_id, MemberMeasurements()),
            )
            for member in config.members
        ),
        disabled_functions=config.disabled_functions | paused,
    )
    return config, ResolvedSettings(
        resolved.values,
        (*resolved.faults, *found.reports),
        resolved.group_missing,
        _member_values(config, resolved.values),
    )


_ORIENTATION_KEY: Final = f"{GEOMETRY_PREFIX}orientation"
_ORIENTATION_KNOWN_KEY: Final = f"{GEOMETRY_PREFIX}orientation_known"


def _orientation_as_stated(
    config: WindowConfig, resolved: ResolvedSettings
) -> tuple[WindowConfig, ResolvedSettings]:
    """Let the orientation count as known only if a level really stated it.

    Shading needs the orientation, and nothing is assumed in its place. The
    switch "orientation known" and the azimuth are two settings that inherit
    on their own, and the azimuth always has a value. A house or a group that
    stores only the switch would therefore turn every window below it into a
    window that faces the built-in azimuth, a number nobody entered. So the
    configuration carries "known" only if the switch is on **and** a level
    supplies the azimuth: its provenance is not the built-in level, and no
    fault in it reached the window (shading is paused then anyway).

    This is no fault: nothing stored is wrong, the configuration is
    incomplete. The geometry says ``orientation_unknown``, which explains it.
    ``value`` of the switch stays what the levels yield; ``effective`` says
    what the configuration carries.
    """
    if not config.shading_orientation_known:
        return config, resolved
    azimuth = resolved.values[_ORIENTATION_KEY]
    faulty = any(
        fault.key == _ORIENTATION_KEY and fault.action is FaultAction.FUNCTIONS_DISABLED
        for fault in resolved.faults
    )
    if azimuth.level is not Level.BUILT_IN and not faulty:
        return config, resolved
    switch = resolved.values[_ORIENTATION_KNOWN_KEY]
    values = dict(resolved.values)
    values[_ORIENTATION_KNOWN_KEY] = dataclasses.replace(switch, effective=False)
    return (
        dataclasses.replace(config, shading_orientation_known=False),
        ResolvedSettings(
            values, resolved.faults, resolved.group_missing, resolved.member_values
        ),
    )


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


def resolve_window(  # noqa: PLR0913 - the levels of a window are the input
    *,
    window_id: str,
    members: Iterable[MemberConfig],
    global_settings: PartialSettings,
    window_settings: PartialSettings,
    group: GroupLevel | None = None,
    member_settings: Mapping[str, PartialSettings] | None = None,
    registry: SettingsRegistry = WINDOW_SETTINGS,
) -> WindowResolution:
    """Resolve :data:`WINDOW_SETTINGS` and build the configuration of one window.

    ``registry`` is for tests that judge a changed registry of the window (a
    fault value that was made less cautious, for example); the integration
    never passes it.

    The window configuration validates itself, and it is the only place with
    value rules: every set value of every level is handed to it on its own,
    and the final configuration is built under the same protection. A refusal
    is a fault of that key on that level and is handled as described for
    :func:`resolve_settings`. The configuration carries the functions that
    were switched off (``WindowConfig.disabled_functions``), so the arbiter
    can skip them and say so. The function does not raise for anything a user
    could have stored.

    ``member_settings`` holds, per member identifier, what that member states
    itself (:data:`MEMBER_SETTINGS`). A member inherits the resolved values of
    the window. A faulty member-level value pauses its function for the whole
    window and never falls back to the window's value; it is reported with
    the level ``member`` and the member. ``settings.member_values`` has the
    value that applies to every member, with its provenance.
    """
    try:
        # The member level is the only input for what a member states itself.
        # Measurements that arrive on a member are dropped here: a comfort
        # measurement must never cost the window its configuration, and it
        # must never make a sound value of the window look invalid.
        identity = WindowConfig(
            window_id=window_id,
            members=tuple(
                dataclasses.replace(member, measurements=MemberMeasurements())
                if isinstance(member, MemberConfig)
                else member
                for member in members
            ),
        )
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
        registry,
        capabilities=identity.capability_states,
        members=identity.members,
        global_settings=global_settings,
        window_settings=window_settings,
        group=group,
        rules=SettingRules(check_value, build),
    )
    if not isinstance(config, WindowConfig):
        return WindowResolution(None, resolved)
    config, resolved = _orientation_as_stated(config, resolved)
    return WindowResolution(*_resolve_members(config, resolved, member_settings or {}))
