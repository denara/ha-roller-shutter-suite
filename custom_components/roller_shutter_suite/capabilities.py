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
"""

from homeassistant.components.cover import ATTR_CURRENT_POSITION, CoverEntityFeature
from homeassistant.const import (
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import PROVISIONAL_TRAVEL_TIME
from .core.model import CapabilityProfile, MemberConfig


def _profile(features: int | None, reports_position: bool | None) -> CapabilityProfile:
    if features is None:
        return CapabilityProfile(
            supports_open_close=False,
            supports_set_position=False,
            supports_stop=False,
            reports_position=False,
            travel_time_up=PROVISIONAL_TRAVEL_TIME,
            travel_time_down=PROVISIONAL_TRAVEL_TIME,
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
        travel_time_up=PROVISIONAL_TRAVEL_TIME,
        travel_time_down=PROVISIONAL_TRAVEL_TIME,
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
