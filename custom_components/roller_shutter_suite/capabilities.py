"""What a cover can do, read from Home Assistant (F7, first part).

The result is the capability profile of the core. Three cases are told apart,
because the core tells them apart (``docs/dev/core-model.md``, "Capability
mask"):

- The cover has a usable state: its supported features and whether it reports
  a position are read from it.
- The cover has no usable state at present (unavailable, or not loaded yet),
  but the entity registry still knows its supported features: those are the
  last known capabilities and are handed in as **known**. Whether it reports a
  position cannot be seen then; a cover that can be driven to a position is
  taken to report one, and one that cannot is taken not to.
- Nothing is known about the cover, not even a registry entry: the profile
  says so (``capabilities_known=False``), and nothing is concluded from it.

``homeassistant.helpers.entity.get_supported_features`` is not used: for an
entity whose state is ``unavailable`` it answers from the state, which has no
attributes then, and returns 0. That would turn "unavailable" into "cannot do
anything".

What no entity reports (the position source, the tolerance, the reporting
kind and time, the travel times) is what the user states per member on the
member pages of the window's form; :func:`with_stated` puts it into the
profile. A member without stated values has the defaults of the registry
(``CAPABILITY_SETTINGS``) and an unknown reporting kind and time.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass

from homeassistant.components.cover import ATTR_CURRENT_POSITION, CoverEntityFeature
from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .core.model import (
    DEFAULT_TRAVEL_TIME,
    CapabilityProfile,
    MemberConfig,
    ReportingKind,
)
from .core.settings import stated_capabilities

STATED_FIELDS: tuple[str, ...] = (
    "position_source",
    "stated_tolerance",
    "reporting_kind",
    "reporting_time",
    "travel_time_up",
    "travel_time_down",
)
"""The fields of the capability profile that the user states, not the entity."""


def _profile(features: int | None, reports_position: bool | None) -> CapabilityProfile:
    if features is None:
        return CapabilityProfile(
            supports_open_close=False,
            supports_set_position=False,
            supports_stop=False,
            reports_position=False,
            travel_time_up=DEFAULT_TRAVEL_TIME,
            travel_time_down=DEFAULT_TRAVEL_TIME,
            capabilities_known=False,
        )
    supported = CoverEntityFeature(features)
    set_position = CoverEntityFeature.SET_POSITION in supported
    return CapabilityProfile(
        supports_open_close=CoverEntityFeature.OPEN in supported
        and CoverEntityFeature.CLOSE in supported,
        supports_set_position=set_position,
        supports_stop=CoverEntityFeature.STOP in supported,
        reports_position=set_position if reports_position is None else reports_position,
        travel_time_up=DEFAULT_TRAVEL_TIME,
        travel_time_down=DEFAULT_TRAVEL_TIME,
    )


def member_config(hass: HomeAssistant, entity_id: str) -> MemberConfig:
    """Return a cover as a member of a window, with what is known about it."""
    features: int | None = None
    reports_position: bool | None = None
    state = hass.states.get(entity_id)
    if state is not None and state.state != STATE_UNAVAILABLE:
        features = int(state.attributes.get(ATTR_SUPPORTED_FEATURES, 0))
        if state.state != STATE_UNKNOWN:
            reports_position = state.attributes.get(ATTR_CURRENT_POSITION) is not None
    elif (entry := er.async_get(hass).async_get(entity_id)) is not None:
        features = entry.supported_features
    return MemberConfig(
        member_id=entity_id, capabilities=_profile(features, reports_position)
    )


def member_configs(
    hass: HomeAssistant, entity_ids: tuple[str, ...]
) -> tuple[MemberConfig, ...]:
    """Return the members of a window in the order in which they are stored."""
    return tuple(member_config(hass, entity_id) for entity_id in entity_ids)


def with_stated(
    members: tuple[MemberConfig, ...], stated: Mapping[str, object]
) -> tuple[MemberConfig, ...]:
    """Return the members with what the user stated for each of them.

    ``stated`` holds the stored capability settings per member ID, as
    ``stored.member_capability_settings`` reads them; a member that is not
    in it states nothing. The core reads every value with a tolerant rule of
    its own (``stated_capabilities``), so no stored value can make a profile
    invalid.
    """
    return tuple(
        dataclasses.replace(
            member,
            capabilities=stated_capabilities(
                member.capabilities, stated.get(member.member_id, {})
            ),
        )
        for member in members
    )


@dataclass(frozen=True, slots=True)
class ReportingFacts:
    """What the covers of a window state about how they report, for arming.

    Arming requires every cover to be event-driven with a known reporting
    time (rulings of the project owner, 2026-09-29 and 2026-10-01): on a
    polled platform a movement by hand between two polls is invisible, and
    a command sent again would overrule the person, until command
    verification (block H15) lifts the condition on the kind. A known
    reporting time above zero does not refuse arming; it enters the
    deadline.
    """

    not_stated: tuple[str, ...]
    """The covers whose reporting kind or reporting time is not stated."""
    polled: tuple[str, ...]
    """The covers that are stated as polled."""

    @property
    def armable(self) -> bool:
        """Return whether every cover is event-driven with a known reporting time."""
        return not self.not_stated and not self.polled


def reporting_facts(members: tuple[MemberConfig, ...]) -> ReportingFacts:
    """Return which covers of a window keep it from being armed, and why."""
    return ReportingFacts(
        not_stated=tuple(
            member.member_id
            for member in members
            if member.capabilities.reporting_kind is None
            or member.capabilities.reporting_time is None
        ),
        polled=tuple(
            member.member_id
            for member in members
            if member.capabilities.reporting_kind is ReportingKind.POLLED
        ),
    )


def keeping_stated(
    known: CapabilityProfile, learned: CapabilityProfile
) -> CapabilityProfile:
    """Return a profile learned from the entity with the stated values of the known one."""
    return dataclasses.replace(
        learned, **{name: getattr(known, name) for name in STATED_FIELDS}
    )
