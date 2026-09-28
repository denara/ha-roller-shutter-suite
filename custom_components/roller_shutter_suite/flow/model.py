"""What a feature contributes to the configuration forms, described as data.

The settings themselves are described once, in the registry of the core
(``core/settings.py``): key, kind, function, default, reader, inheritance and
the capability a setting requires. Nothing here repeats that. A
:class:`FieldForm` adds only what the core does not know, because it concerns
the form and nothing else: the step a setting appears in, whether it sits in
the collapsed section of expert values, and how its input control looks (the
unit a duration is entered in, the step of a number box, the entity domains of
a reference). The range and the unit of a number are part of the registry
entry; :meth:`Catalog.number_bounds` turns them into the bounds of the number box,
so the form carries no bounds of its own.

A :class:`Catalog` ties the registry, the forms of the features and the
resolver together. The flows read it when a step is shown, so a block that adds
settings adds registry entries, form descriptions and translations, and edits
no flow class.

This module imports nothing from Home Assistant: the translation generator
reads it too.
"""

import math
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Final, Protocol

from custom_components.roller_shutter_suite.const import PROVISIONAL_TRAVEL_TIME
from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    JsonValue,
    MemberConfig,
)
from custom_components.roller_shutter_suite.core.settings import (
    GroupLevel,
    Level,
    PartialSettings,
    SettingDefinition,
    SettingKind,
    SettingsRegistry,
    WindowResolution,
    format_number,
)

DURATION_UNITS: Final = MappingProxyType({1: "s", 60: "min", 3600: "h"})
"""The units a duration can be entered in, by their size in seconds."""

OUT_OF_RANGE_PREFIX: Final = "out_of_range_"
"""The error of a number outside its range is ``out_of_range_<field name>``.

One key per field, because the text names the range of that field; the
translation generator writes the texts from the ranges of the registry.
"""

_KINDS_WITHOUT_A_GENERATED_FIELD: Final = frozenset({SettingKind.LIST})
"""A list has no generic input control; it needs a step written by hand."""

_KINDS_KEPT_OUT_OF_SECTIONS: Final = frozenset(
    {SettingKind.DAY_OF_YEAR, SettingKind.OPTIONAL_REFERENCE}
)
"""Kinds that stay on the top level of their form.

A day of the year is entered in a text field. Inside a section the frontend
does not strip an emptied text, and that case was not confirmed in a browser,
so an inheritable text field stays out of sections
(``docs/dev/config-flow-findings.md``, section 12). An optional reference
stays out because its two fields belong together and its entity field is the
only place where an error about it can be shown. A time has a selector of its
own and no text field; like every field, an empty text from it would count as
an absent key.
"""


@dataclass(frozen=True, slots=True)
class FieldForm:
    """How one setting of the registry appears in its form.

    ``step`` is the step of the number box of a number or a duration; its
    bounds and its unit come from the registry entry. ``seconds_per_unit`` is
    the size of the unit a duration is entered in (60 for minutes, one of
    :data:`DURATION_UNITS`); it is stored in whole seconds.
    ``entity_domains`` limits the entity selector of an optional reference.
    ``options_key`` is the translation key of the options of an enumeration;
    without it the key of the setting is used, and settings that offer the
    same choice share one. ``form_name`` is the name of the field in the form
    and therefore in the translations, where it differs from the key of the
    setting: a name can say what the key leaves to its documentation, the
    unit of a threshold for example.
    """

    key: str
    expert: bool = False
    step: float = 1
    seconds_per_unit: int = 1
    entity_domains: tuple[str, ...] = ()
    options_key: str | None = None
    form_name: str | None = None

    def __post_init__(self) -> None:
        """Validate what does not depend on the registry."""
        if self.seconds_per_unit not in DURATION_UNITS:
            raise ValueError(
                f"the unit of the duration {self.key!r} is not one of "
                f"{sorted(DURATION_UNITS)} seconds"
            )

    @property
    def out_of_range_error(self) -> str:
        """Return the error key of a number outside the range of this field."""
        return f"{OUT_OF_RANGE_PREFIX}{self.name}"

    @property
    def name(self) -> str:
        """Return the name of the field in the form and in the translations."""
        return self.key if self.form_name is None else self.form_name


@dataclass(frozen=True, slots=True)
class StepForm:
    """One page of a feature: a name and the fields it shows.

    A page has at most one section, the collapsed one of the expert values,
    because sections cannot be nested. The ``numbered`` pages of a feature
    carry a counter in their title: the placeholders ``{page_number}`` and
    ``{page_count}`` count the numbered pages of the feature that the flow
    shows, in their order ("Daily routine: workdays (1/3)").
    """

    name: str
    fields: tuple[FieldForm, ...]
    numbered: bool = False


@dataclass(frozen=True, slots=True)
class NumberBounds:
    """The number box of a field: bounds, unit and step in the unit of the form."""

    minimum: float | None
    maximum: float | None
    unit: str | None
    step: float

    def text(self, value: float, *, with_unit: bool = True) -> str:
        """Return a value of the box as language-neutral text, with its unit."""
        number = format_number(value)
        return f"{number} {self.unit}" if with_unit and self.unit else number


@dataclass(frozen=True, slots=True)
class FeatureForm:
    """The configuration pages of one feature.

    ``switch`` is the key of the inheritable boolean that switches the feature
    on, if the registry has one. A feature without a switch is always on and
    has no entry in the step of the switches.
    """

    feature_id: str
    steps: tuple[StepForm, ...]
    switch: str | None = None

    def step_id(self, step: StepForm) -> str:
        """Return the step ID of a page, which is also the key of its translations."""
        return f"feature_{self.feature_id}_{step.name}"

    @property
    def fields(self) -> tuple[FieldForm, ...]:
        """Return the fields of all pages."""
        return tuple(item for step in self.steps for item in step.fields)


class Resolver(Protocol):
    """Resolve the settings of one window; the signature of ``resolve_window``."""

    def __call__(
        self,
        *,
        window_id: str,
        members: tuple[MemberConfig, ...],
        global_settings: PartialSettings,
        window_settings: PartialSettings,
        group: GroupLevel | None = None,
    ) -> WindowResolution:
        """Return the resolved window."""


@dataclass(frozen=True, slots=True)
class Catalog:
    """The settings that exist, their forms, and the resolver that reads them."""

    registry: SettingsRegistry
    features: tuple[FeatureForm, ...]
    resolve: Resolver

    def __post_init__(self) -> None:
        """Refuse a form description that does not fit the registry."""
        seen: set[str] = set()
        for feature in self.features:
            if feature.switch is not None:
                switch = self._known(feature.switch, feature)
                if switch.kind is not SettingKind.BOOLEAN or not switch.inheritable:
                    raise ValueError(
                        f"the switch of the feature {feature.feature_id!r} must be "
                        "an inheritable boolean"
                    )
            for item in feature.fields:
                definition = self._known(item.key, feature)
                if definition.kind in _KINDS_WITHOUT_A_GENERATED_FIELD:
                    raise ValueError(
                        f"the setting {item.key!r} is a {definition.kind.value}; "
                        "it needs a step of its own"
                    )
                if item.expert and definition.kind in _KINDS_KEPT_OUT_OF_SECTIONS:
                    raise ValueError(
                        f"the setting {item.key!r} is a {definition.kind.value} and "
                        "must stay out of the section of expert values"
                    )
            keys = [item.key for item in feature.fields]
            if feature.switch is not None:
                keys.append(feature.switch)
            for key in keys:
                if key in seen:
                    raise ValueError(f"the setting {key!r} appears in two forms")
                seen.add(key)
        step_ids = [
            feature.step_id(step) for feature in self.features for step in feature.steps
        ]
        if len(set(step_ids)) != len(step_ids):
            raise ValueError("two pages of the forms have the same step ID")

    def _known(self, key: str, feature: FeatureForm) -> SettingDefinition[Any]:
        definition = self.definitions.get(key)
        if definition is None:
            raise ValueError(
                f"the feature {feature.feature_id!r} shows the setting {key!r}, "
                "which the registry does not know"
            )
        return definition

    @property
    def definitions(self) -> dict[str, SettingDefinition[Any]]:
        """Return the entries of the registry by key."""
        return {definition.key: definition for definition in self.registry.definitions}

    def number_bounds(self, item: FieldForm) -> NumberBounds:
        """Return the number box of a number or a duration, from its registry entry.

        A duration is stored in seconds and entered in the unit of the form,
        in whole units: the bounds are the whole units that lie within the
        range. A number keeps the bounds and the unit of its entry.
        """
        definition = self.definitions[item.key]
        value_range = definition.value_range
        minimum = None if value_range is None else value_range.minimum
        maximum = None if value_range is None else value_range.maximum
        if definition.kind is SettingKind.DURATION:
            size = item.seconds_per_unit
            return NumberBounds(
                minimum=None if minimum is None else math.ceil(minimum / size),
                maximum=None if maximum is None else math.floor(maximum / size),
                unit=DURATION_UNITS[size],
                step=item.step,
            )
        return NumberBounds(
            minimum=_whole(minimum),
            maximum=_whole(maximum),
            unit=definition.unit,
            step=item.step,
        )

    def step(self, step_id: str) -> StepForm | None:
        """Return the page with the step ID, or ``None`` if the catalog has none."""
        return next(
            (
                step
                for feature in self.features
                for step in feature.steps
                if feature.step_id(step) == step_id
            ),
            None,
        )

    @property
    def form_keys(self) -> frozenset[str]:
        """Return the keys that some form shows: fields and switches."""
        return frozenset(
            key
            for feature in self.features
            for key in (
                *(item.key for item in feature.fields),
                *((feature.switch,) if feature.switch is not None else ()),
            )
        )


def _whole(value: float | None) -> float | None:
    """Return a whole bound as an ``int``, so no form shows it as ``80.0``."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    return value


PROBE_WINDOW_ID: Final = "probe"

PROBE_MEMBER: Final = MemberConfig(
    member_id="probe",
    capabilities=CapabilityProfile(
        supports_open_close=False,
        supports_set_position=False,
        supports_stop=False,
        reports_position=False,
        travel_time_up=PROVISIONAL_TRAVEL_TIME,
        travel_time_down=PROVISIONAL_TRAVEL_TIME,
        capabilities_known=False,
    ),
)
"""A member about which nothing is known, so no capability masks anything.

The house and a group have no covers. To show what they pass on and to check
their values with the rules of the core, the forms resolve an imaginary window
with this member that sets nothing itself.
"""


@dataclass(frozen=True, slots=True)
class GroupParent:
    """The group a window inherits from, as the forms see it."""

    group_id: str
    title: str
    settings: PartialSettings


@dataclass(slots=True)
class LevelContext:
    """The level a flow edits: its own values and where it inherits from.

    ``own`` holds the own values in their stored form, keyed by registry key;
    an absent key is inherited. ``house`` is ``None`` on the house level,
    which inherits from nothing. ``members`` are the covers of a window; the
    other levels carry the probe member.
    """

    level: Level
    own: dict[str, JsonValue]
    house_title: str
    house: PartialSettings | None = None
    group: GroupParent | None = None
    members: tuple[MemberConfig, ...] = (PROBE_MEMBER,)

    @property
    def inherits(self) -> bool:
        """Return whether the level has a level above it."""
        return self.level is not Level.GLOBAL
