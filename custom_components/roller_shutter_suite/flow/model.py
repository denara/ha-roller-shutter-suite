"""SPIKE S2: what a feature contributes to the configuration flows.

A feature module describes its settings as data. The flows of all three levels
(house, group, window) are generated from that description, so a feature block
never edits a flow class.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

type SettingValue = bool | float
type Settings = Mapping[str, SettingValue]


@dataclass(frozen=True, slots=True)
class SettingField:
    """One inheritable setting."""

    key: str
    kind: Literal["bool", "number"]
    default: SettingValue
    minimum: float = 0
    maximum: float = 100
    unit: str | None = None
    # Expert values are shown in the collapsed section of the step.
    expert: bool = False
    # Name of the capability the window's covers need for this setting, or None.
    requires: str | None = None


@dataclass(frozen=True, slots=True)
class FeatureFlow:
    """The configuration step of one feature."""

    feature_id: str
    enabled_by_default: bool
    fields: tuple[SettingField, ...]
    # Optional cross-field validation: effective values in, errors out
    # (field key or "base" -> error translation key).
    validate: Callable[[Settings], dict[str, str]] | None = None

    @property
    def step_id(self) -> str:
        """Return the step ID, which is also the prefix of its translations."""
        return f"feature_{self.feature_id}"

    @property
    def switch(self) -> SettingField:
        """Return the feature switch, an inheritable boolean like any other."""
        return SettingField(
            key=f"enable_{self.feature_id}",
            kind="bool",
            default=self.enabled_by_default,
        )


@dataclass(frozen=True, slots=True)
class Parent:
    """A level a value can be inherited from, nearest level first."""

    title: str
    settings: Settings


@dataclass(frozen=True, slots=True)
class Resolved:
    """An effective value and the title of the level it comes from."""

    value: SettingValue
    source: str


@dataclass(slots=True)
class LevelContext:
    """What a generated step needs to know about the level it edits."""

    own: dict[str, SettingValue]
    parents: tuple[Parent, ...]
    # Capabilities of the window's covers; None on levels without covers.
    capabilities: Mapping[str, bool] | None = None
    # Extra placeholders, for example the member that limits a capability.
    placeholders: dict[str, str] = field(default_factory=dict)


def resolve(setting: SettingField, own: Settings, parents: tuple[Parent, ...]) -> Any:
    """Return the effective value of a setting; the nearest level wins."""
    if setting.key in own:
        return own[setting.key]
    return resolve_inherited(setting, parents).value


def resolve_inherited(setting: SettingField, parents: tuple[Parent, ...]) -> Resolved:
    """Return what a level inherits when it does not state a value itself."""
    for parent in parents:
        if setting.key in parent.settings:
            return Resolved(parent.settings[setting.key], parent.title)
    return Resolved(setting.default, "")
