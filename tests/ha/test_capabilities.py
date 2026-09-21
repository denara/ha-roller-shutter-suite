"""What is known about a cover: a usable state, the last known features, or nothing."""

from types import SimpleNamespace
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.group import get_group_entities

from custom_components.roller_shutter_suite.capabilities import member_config
from custom_components.roller_shutter_suite.core.model import CapabilityState
from custom_components.roller_shutter_suite.flow.covers import group_members
from tests.ha.helpers import FULL_COVER, NO_STOP, OPEN_CLOSE_ONLY, set_cover

CAPABILITIES = (
    "supports_open_close",
    "supports_set_position",
    "supports_stop",
    "reports_position",
)


def _states(hass: HomeAssistant, entity_id: str) -> dict[str, CapabilityState]:
    profile = member_config(hass, entity_id).capabilities
    return {name: profile.capability_state(name) for name in CAPABILITIES}


async def test_capabilities_are_read_from_a_usable_state(hass: HomeAssistant) -> None:
    """Supported features and the reported position decide."""
    set_cover(hass, "cover.example_full")
    set_cover(hass, "cover.example_roof", NO_STOP)
    set_cover(hass, "cover.example_plain", OPEN_CLOSE_ONLY, position=None)
    set_cover(hass, "cover.example_silent", FULL_COVER, position=None)

    present, missing = CapabilityState.PRESENT, CapabilityState.MISSING
    assert set(_states(hass, "cover.example_full").values()) == {present}
    assert _states(hass, "cover.example_roof")["supports_stop"] is missing
    assert _states(hass, "cover.example_plain") == {
        "supports_open_close": present,
        "supports_set_position": missing,
        "supports_stop": missing,
        "reports_position": missing,
    }
    # It can be driven to a position, but it reports none.
    assert _states(hass, "cover.example_silent")["reports_position"] is missing


@pytest.mark.parametrize(
    "state", ["unavailable", None], ids=["unavailable", "no state"]
)
async def test_unavailable_cover_keeps_its_last_known_capabilities(
    hass: HomeAssistant, state: str | None
) -> None:
    """A cover that is merely away is not unknown: the entity registry still knows it."""
    er.async_get(hass).async_get_or_create(
        "cover",
        "example_platform",
        "example_unique",
        suggested_object_id="example_away",
        supported_features=int(NO_STOP),
    )
    if state is not None:
        hass.states.async_set("cover.example_away", state, {})

    states = _states(hass, "cover.example_away")

    assert member_config(hass, "cover.example_away").capabilities.capabilities_known
    assert states["supports_stop"] is CapabilityState.MISSING
    assert states["supports_set_position"] is CapabilityState.PRESENT
    # Whether it reports a position cannot be seen now; it can be driven to one.
    assert states["reports_position"] is CapabilityState.PRESENT


async def test_cover_with_unknown_state_is_judged_by_its_features(
    hass: HomeAssistant,
) -> None:
    """A cover without feedback often stays "unknown"; its features are known all the same."""
    set_cover(
        hass, "cover.example_blind", OPEN_CLOSE_ONLY, position=None, state="unknown"
    )

    states = _states(hass, "cover.example_blind")

    assert states["supports_open_close"] is CapabilityState.PRESENT
    assert states["reports_position"] is CapabilityState.MISSING


async def test_cover_that_was_never_seen_is_unknown(hass: HomeAssistant) -> None:
    """Nothing is concluded from a cover about which nothing was ever known."""
    profile = member_config(hass, "cover.example_never_seen").capabilities

    assert profile.capabilities_known is False
    assert set(_states(hass, "cover.example_never_seen").values()) == {
        CapabilityState.UNKNOWN
    }


async def test_entity_that_announces_itself_as_a_group_is_believed_first(
    hass: HomeAssistant,
) -> None:
    """The new group mechanism of Home Assistant answers before state and registry."""
    members = ["cover.example_left", "cover.example_right"]
    announced: Any = SimpleNamespace(group=SimpleNamespace(member_entity_ids=members))
    silent: Any = SimpleNamespace(group=None)
    get_group_entities(hass)["cover.example_announced"] = announced
    get_group_entities(hass)["cover.example_silent"] = silent

    assert group_members(hass, "cover.example_announced") == members
    assert group_members(hass, "cover.example_silent") is None
