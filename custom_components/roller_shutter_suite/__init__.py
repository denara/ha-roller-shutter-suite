"""The Roller Shutter Suite integration.

One config entry represents the house. At this stage the integration loads and
does nothing; later work blocks add groups and windows as config subentries.
"""

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@dataclass(slots=True)
class RollerShutterSuiteData:
    """Runtime data of the config entry.

    It lives exactly as long as the entry is loaded. It has no fields yet; later
    work blocks add what the loaded integration needs to keep.
    """


type RollerShutterSuiteConfigEntry = ConfigEntry[RollerShutterSuiteData]


async def async_setup_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Set up Roller Shutter Suite from its config entry."""
    entry.runtime_data = RollerShutterSuiteData()
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Unload the config entry.

    Nothing was set up outside of ``entry.runtime_data``, which Home Assistant
    discards itself, so there is nothing to tear down yet.
    """
    return True
