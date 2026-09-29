"""What the tests of the controls share: a house, a group, a window, and stub alarms.

The installation of these tests: the house with the fixed daily routine of
``runtime_kit``, the group "Example group" and the armed window "Example
window" in it, whose cover stands half open at 50 %. At Monday 10:00 the
daily routine wants the day position, 100 %, so the next decision of the
window has a comfort wish that would move the shutter.

The arbiter of the integration has no protection or fire layer yet. The
fixture ``alarms`` (:func:`install_alarms`) gives every controller
 the layers of the feature blocks
plus a stub protection layer (``storm``: close to 0 %) and a stub fire layer
(``fire``: open to 100 %), with the real gate rules, so pause, maintenance
lock and operating mode decide as they will in the finished integration.
"""

from dataclasses import dataclass
from typing import Any

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite import controller as controller_module
from custom_components.roller_shutter_suite.const import (
    CONF_GROUP_ID,
    CONF_SETTINGS,
    SUBENTRY_GROUP,
)
from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.engine import (
    FEATURE_LAYERS,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    FunctionId,
    Layer,
    WindowConfig,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.ha.helpers import set_cover, setup_entry, subentry_data
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    WINDOW_ID,
    controller_of,
    register_cover_services,
    settle,
    window_data,
    window_subentry,
)

GROUP_ID = "g1"
HOUSE = "roller_shutter_suite"
GROUP = "example_group"
WINDOW = "example_window"
LEVELS = (HOUSE, GROUP, WINDOW)
"""The house, the group and the window, as their entity IDs begin."""

HALF_OPEN = 50


def pause_of(level: str) -> str:
    """Return the pause switch of a level."""
    return f"switch.{level}_pause"


def lock_of(level: str) -> str:
    """Return the maintenance lock of a level."""
    return f"switch.{level}_maintenance_lock"


def mode_of(level: str) -> str:
    """Return the operating mode of a level."""
    return f"select.{level}_operating_mode"


@dataclass
class Alarms:
    """A storm and a fire alarm that the test switches; the stub layers read them."""

    storm: bool = False
    fire: bool = False

    def protection(self, config: WindowConfig, world: WorldSnapshot) -> Wish:
        """Close while the storm is on; no opinion otherwise."""
        del config, world
        if self.storm:
            return Wish.target(
                Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED
            )
        return Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE)

    def fire_layer(self, config: WindowConfig, world: WorldSnapshot) -> Wish:
        """Open fully while the fire alarm is on; no opinion otherwise."""
        del config, world
        if self.fire:
            return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN)
        return Wish.no_opinion(Layer.FIRE, ReasonCode.INACTIVE)


def install_alarms(monkeypatch: pytest.MonkeyPatch) -> Alarms:
    """Give every controller the stub protection and fire layers and the real rules.

    Test modules turn this into a fixture: ``alarms = pytest.fixture(install_alarms)``.
    """
    stub = Alarms()

    def with_alarms() -> Arbiter:
        return build_arbiter(
            [
                *FEATURE_LAYERS,
                LayerRegistration(
                    Layer.PROTECTION, stub.protection, FunctionId.PROTECTION_EVENTS
                ),
                LayerRegistration(Layer.FIRE, stub.fire_layer, FunctionId.FIRE),
            ]
        )

    monkeypatch.setattr(controller_module, "build_arbiter", with_alarms)
    return stub


async def setup_house(  # noqa: PLR0913 - the three levels and the cover
    hass: HomeAssistant,
    freezer: Any,
    *,
    house: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
    window: dict[str, Any] | None = None,
    dry_run: bool = False,
    position: int = HALF_OPEN,
) -> MockConfigEntry:
    """Set the house up with the group and the window; the first recompute has run."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=position, state="open")
    data = window_data(settings=window, dry_run=dry_run) | {CONF_GROUP_ID: GROUP_ID}
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: FIXED_ROUTINE | (house or {})},
        subentries=[
            subentry_data(
                SUBENTRY_GROUP, "Example group", {CONF_SETTINGS: group or {}}, GROUP_ID
            ),
            window_subentry(data=data),
        ],
    )
    await settle(hass, freezer)
    return entry


async def turn(hass: HomeAssistant, entity_id: str, *, on: bool) -> None:
    """Turn a switch on or off through its action, as a user does."""
    await hass.services.async_call(
        "switch",
        "turn_on" if on else "turn_off",
        {"entity_id": entity_id},
        blocking=True,
    )


async def select_mode(hass: HomeAssistant, entity_id: str, mode: str) -> None:
    """Choose an operating mode through the action of the select."""
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": entity_id, "option": mode},
        blocking=True,
    )


async def recompute(hass: HomeAssistant, freezer: Any, entry: MockConfigEntry) -> None:
    """Ask the window for a recompute, as a stub layer that changed needs."""
    controller_of(entry, WINDOW_ID).async_request_recompute()
    await settle(hass, freezer)
