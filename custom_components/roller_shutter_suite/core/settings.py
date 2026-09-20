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
  provenance, the capability mask and the fallback for a group that is gone.
  :func:`resolve_window` does that for :data:`WINDOW_SETTINGS` and builds the
  ``WindowConfig``.

Nothing here raises because of what a user stored. Problems are part of the
result, so one broken window or group never stops the others.
"""

import dataclasses
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from enum import Enum, StrEnum, unique
from types import MappingProxyType
from typing import Any, Final

from .model import (
    CapabilityState,
    CoveringType,
    JsonValue,
    MemberConfig,
    ScheduleProfile,
    TemperatureTier,
    WindowCapabilityStates,
    WindowConfig,
)
from .model._data import as_enum, as_object, as_str, read, tuple_of
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
    - ``default``: the built-in default, used when no level sets the value.
    - ``parse``: reads the value from stored data and raises a ``ValueError``
      if it cannot. It is never called for an absent key, an empty string,
      ``null`` or :data:`STORED_NONE`.
    - ``inheritable``: ``False`` for what belongs to one window only (the
      cover itself, measurements). Such a setting is read from the window
      level alone, and a group or the house that sets it is reported.
    - ``requires``: the capability the setting needs, if any.
    """

    key: str
    kind: SettingKind
    default: T
    parse: Callable[[JsonValue], T]
    inheritable: bool = True
    requires: CapabilityRequirement[T] | None = None

    def __post_init__(self) -> None:
        """Validate the description itself."""
        require_identifier(self.key, "the key of a setting")
        require_type(self.kind, SettingKind, "the kind of a setting")
        require_type(self.inheritable, bool, "the flag 'inheritable'")
        if self.requires is not None:
            require_type(
                self.requires, CapabilityRequirement, "the capability requirement"
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


@unique
class SettingProblem(StrEnum):
    """What is wrong with a setting. The Home Assistant layer translates it."""

    UNREADABLE = "unreadable"
    """The stored value could not be read."""
    NONE_NOT_ALLOWED = "none_not_allowed"
    """The stored marker for "explicitly none" on a setting that is no optional reference."""
    INVALID = "invalid"
    """The value was read, but the window configuration refuses it."""
    NOT_INHERITABLE = "not_inheritable"
    """A group or the house sets what only a window can set."""
    UNKNOWN_SETTING = "unknown_setting"
    """The level sets a key that the registry does not know."""


@dataclass(frozen=True, slots=True)
class SettingFault:
    """A stored value that could not be read: the key and what is wrong with it.

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
    read; such a key is not set.

    Compared by value, but not hashable, because it holds a mapping.
    """

    values: Mapping[str, object] = field(default_factory=dict)
    faults: tuple[SettingFault, ...] = ()

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


def settings_from_stored(
    data: Mapping[str, JsonValue], registry: SettingsRegistry
) -> PartialSettings:
    """Turn the stored data of one level into partial settings.

    This is the only place that knows how "inherit" is stored:

    - a key that is absent is inherited;
    - an empty string is treated like an absent key, because a form can
      deliver an emptied text field that way;
    - ``0``, ``False`` and an empty list are set values;
    - ``null`` is never written, so it is a fault and not a second way to say
      "inherit" or "none";
    - :data:`STORED_NONE` on an optional reference is the set value ``None``:
      "explicitly none", which beats the levels below like any set value. On a
      setting of any other kind it is a fault (``none_not_allowed``);
    - a value the setting cannot read is a fault.

    Keys the registry does not know are left alone: the stored data of a
    window also holds what is not a setting, such as its covers and its group.
    The function does not raise for anything a user could have stored.
    """
    values: dict[str, object] = {}
    faults: list[SettingFault] = []
    for definition in registry.definitions:
        if definition.key not in data:
            continue
        raw = data[definition.key]
        if isinstance(raw, str) and not raw:
            continue
        if raw is None:
            faults.append(SettingFault(definition.key, _NULL_FAULT))
            continue
        if raw == STORED_NONE:
            if definition.kind is SettingKind.OPTIONAL_REFERENCE:
                values[definition.key] = None
            else:
                faults.append(
                    SettingFault(
                        definition.key, _NONE_FAULT, SettingProblem.NONE_NOT_ALLOWED
                    )
                )
            continue
        try:
            values[definition.key] = definition.parse(raw)
        except ValueError as err:
            faults.append(SettingFault(definition.key, str(err)))
    return PartialSettings(values=values, faults=tuple(faults))


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


@unique
class GroupFallbackReason(StrEnum):
    """Why a window that refers to a group inherits from the house instead."""

    GROUP_MISSING = "group_missing"
    GROUP_DATA_FAULTY = "group_data_faulty"


@dataclass(frozen=True, slots=True)
class GroupFallback:
    """The group reference of a window leads nowhere; the house level applies.

    The Home Assistant layer turns this into a repair issue. ``faults`` names
    what could not be read when the reason is faulty data.
    """

    group_id: str
    reason: GroupFallbackReason
    faults: tuple[SettingFault, ...] = ()


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
    what the complete configuration carries.

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


@dataclass(frozen=True, slots=True)
class SettingError:
    """A validation error: the field, the level that set the value, the problem.

    ``detail`` is English text for logs and diagnostics, never for the user.
    A missing capability is never an error; see :class:`ResolvedValue`.
    """

    key: str
    level: Level
    problem: SettingProblem
    detail: str
    group_id: str | None = None


@dataclass(frozen=True, slots=True)
class ResolvedSettings:
    """The result of resolving a registry for one window.

    ``values`` has one entry per setting of the registry, in its order.
    ``errors`` is empty for a valid result. ``group_fallback`` is set when the
    window refers to a group that could not be used.
    """

    values: Mapping[str, ResolvedValue[Any]]
    errors: tuple[SettingError, ...] = ()
    group_fallback: GroupFallback | None = None

    def __post_init__(self) -> None:
        """Copy the mapping so it cannot be changed afterwards."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))

    @property
    def valid(self) -> bool:
        """Return whether the result has no error. A group fallback is no error."""
        return not self.errors

    @property
    def masked_own_values(self) -> tuple[ResolvedValue[Any], ...]:
        """Return the settings the window sets itself and cannot use at present.

        This is what the Home Assistant layer reports as a repair issue. It is
        no error: the window keeps its configuration, and the entry disappears
        by itself when the capability is back. A capability that is unknown
        never appears here.
        """
        return tuple(item for item in self.values.values() if item.own_value_masked)

    def effective(self) -> dict[str, Any]:
        """Return the value the complete configuration carries, per key."""
        return {key: item.effective for key, item in self.values.items()}


type _LevelInput = tuple[Level, PartialSettings, str | None]


def _group_fallback(group: GroupLevel | None) -> GroupFallback | None:
    """Return why the group cannot be used, or ``None`` if it can or is not asked."""
    if group is None:
        return None
    if group.settings is None:
        return GroupFallback(group.group_id, GroupFallbackReason.GROUP_MISSING)
    if group.settings.faults:
        return GroupFallback(
            group.group_id,
            GroupFallbackReason.GROUP_DATA_FAULTY,
            group.settings.faults,
        )
    return None


def _level_errors(
    registry: SettingsRegistry, level_input: _LevelInput
) -> Iterable[SettingError]:
    """Yield what is wrong with one level, whatever wins in the end."""
    level, settings, group_id = level_input
    for fault in settings.faults:
        yield SettingError(fault.key, level, fault.problem, fault.detail, group_id)
    definitions = {definition.key: definition for definition in registry.definitions}
    for key in settings.values:
        definition = definitions.get(key)
        if definition is None:
            yield SettingError(
                key,
                level,
                SettingProblem.UNKNOWN_SETTING,
                "the registry has no setting with this key",
                group_id,
            )
        elif level is not Level.WINDOW and not definition.inheritable:
            yield SettingError(
                key,
                level,
                SettingProblem.NOT_INHERITABLE,
                "only a window can set this; it cannot be inherited",
                group_id,
            )


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
) -> ResolvedValue[Any]:
    """Return the value of the strongest level that sets it, else the default."""
    value: Any = definition.default
    found: Level = Level.BUILT_IN
    found_group: str | None = None
    for level, settings, group_id in levels:
        if level is not Level.WINDOW and not definition.inheritable:
            continue
        own = settings.get(definition.key)
        if own is not INHERIT:
            value, found, found_group = own, level, group_id
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
    return ResolvedValue(
        key=definition.key,
        value=value,
        effective=effective,
        level=found,
        group_id=found_group,
        capability=state,
        unavailable=missing,
    )


def resolve_settings(  # noqa: PLR0913 - the three levels and the window are the input
    registry: SettingsRegistry,
    *,
    capabilities: WindowCapabilityStates,
    members: tuple[MemberConfig, ...],
    global_settings: PartialSettings,
    window_settings: PartialSettings,
    group: GroupLevel | None = None,
) -> ResolvedSettings:
    """Resolve every setting of the registry for one window.

    The value of a window beats the value of its group, which beats the value
    of the house, which beats the built-in default. ``capabilities`` are those
    of the window in three states (``WindowConfig.capability_states`` of
    ``members``); the members are needed to name who limits.

    - **No group:** the window inherits from the house directly.
    - **A group that is gone or whose data is faulty:** the same, and the
      result carries a :class:`GroupFallback`. That is not an error.
    - **Capability mask:** a setting that requires a capability the window
      definitely lacks is not available: provenance kept, capability and
      limiting members named, ``effective`` is the stand-in. That is never an
      error, also not for the window's own value, which is listed in
      ``masked_own_values`` instead. A capability that is unknown masks
      nothing and reports nothing.
    - **Errors** name the key and the level that set the offending value.

    The function does not raise for anything a user could have stored.
    """
    fallback = _group_fallback(group)
    ordered: list[_LevelInput] = [(Level.WINDOW, window_settings, None)]
    if group is not None and group.settings is not None and fallback is None:
        ordered.append((Level.GROUP, group.settings, group.group_id))
    ordered.append((Level.GLOBAL, global_settings, None))
    levels = tuple(ordered)

    errors: list[SettingError] = []
    for level_input in levels:
        errors.extend(_level_errors(registry, level_input))

    values = {
        definition.key: _resolve_one(definition, levels, capabilities, members)
        for definition in registry.definitions
    }
    return ResolvedSettings(values, tuple(errors), fallback)


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
            default=CoveringType.ROLLER_SHUTTER,
            parse=as_enum(CoveringType),
            inheritable=False,
        ),
        SettingDefinition[str | None](
            key="morning_condition_source",
            kind=SettingKind.OPTIONAL_REFERENCE,
            default=None,
            parse=as_str,
        ),
        SettingDefinition[tuple[TemperatureTier, ...]](
            key="shading_temperature_tiers",
            kind=SettingKind.LIST,
            default=(),
            parse=tuple_of(_as_temperature_tier),
        ),
        SettingDefinition(
            key="schedule_profile",
            kind=SettingKind.ENUMERATION,
            default=ScheduleProfile.DEFAULT,
            parse=as_enum(ScheduleProfile),
        ),
    )
)
"""The settings of ``WindowConfig``. A new setting is one more entry here.

The key of an entry is the name of its field of ``WindowConfig``. The fields
in :data:`WINDOW_IDENTITY_FIELDS` are no settings: the caller hands them in.
"""

WINDOW_IDENTITY_FIELDS: Final = ("window_id", "members")
"""What identifies a window and what it consists of. Never inherited, never resolved."""


@dataclass(frozen=True, slots=True)
class WindowResolution:
    """The resolved window: its configuration, or ``None`` if there are errors.

    ``settings`` always carries the values with their provenance, the errors
    and the group fallback, so the Home Assistant layer can explain a window
    that could not be configured.
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

    The window configuration validates itself. Its refusals become errors of
    the setting concerned, with the level that set the value. An identity it
    refuses (no member, a member twice) is an error of the key ``members`` or
    ``window_id``. The function does not raise for anything a user could have
    stored.
    """
    try:
        identity = WindowConfig(window_id=window_id, members=tuple(members))
    except (TypeError, ValueError) as err:
        key = (
            "window_id"
            if not isinstance(window_id, str) or not window_id
            else "members"
        )
        error = SettingError(key, Level.WINDOW, SettingProblem.INVALID, str(err))
        return WindowResolution(None, ResolvedSettings({}, (error,)))

    resolved = resolve_settings(
        WINDOW_SETTINGS,
        capabilities=identity.capability_states,
        members=identity.members,
        global_settings=global_settings,
        window_settings=window_settings,
        group=group,
    )
    errors = list(resolved.errors)
    for key, item in resolved.values.items():
        change: dict[str, Any] = {key: item.effective}
        try:
            dataclasses.replace(identity, **change)
        except (TypeError, ValueError) as err:
            errors.append(
                SettingError(
                    key, item.level, SettingProblem.INVALID, str(err), item.group_id
                )
            )
    if errors:
        return WindowResolution(
            None, dataclasses.replace(resolved, errors=tuple(errors))
        )
    return WindowResolution(
        dataclasses.replace(identity, **resolved.effective()), resolved
    )
