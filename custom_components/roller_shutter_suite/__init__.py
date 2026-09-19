"""The Roller Shutter Suite integration (SPIKE S2, throwaway code).

One config entry represents the house; groups and windows are config
subentries. The spike sets up just enough to answer the questions of block S2:
it counts set-ups, creates one device per group and per window, and reports a
window whose group is gone.
"""

from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import issue_registry as ir

from .const import (
    CONF_GROUP_ID,
    DATA_SETUP_COUNT,
    DOMAIN,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)

PLATFORMS = [Platform.SENSOR]


@dataclass(slots=True)
class RollerShutterSuiteData:
    """Runtime data of the config entry."""

    # Window subentry IDs whose group reference points nowhere.
    dangling: set[str] = field(default_factory=set)


type RollerShutterSuiteConfigEntry = ConfigEntry[RollerShutterSuiteData]


async def _async_reload_on_update(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> None:
    """Reload after any change of the entry or of one of its subentries.

    This listener is the only thing that reloads. Home Assistant calls it after
    a subentry was added, changed or removed and after the entry data changed,
    but only if something really changed. The flows therefore end with
    ``async_update_and_abort`` and never with a reloading method.
    """
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Set up Roller Shutter Suite from its config entry."""
    hass.data[DATA_SETUP_COUNT] = hass.data.get(DATA_SETUP_COUNT, 0) + 1
    data = RollerShutterSuiteData()
    entry.runtime_data = data

    device_registry = dr.async_get(hass)
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_GROUP:
            # A group gets a device of its own (for its future switches). It is
            # a different device than any window's, so "a device belongs to at
            # most one subentry" holds.
            device_registry.async_get_or_create(
                config_entry_id=entry.entry_id,
                config_subentry_id=subentry.subentry_id,
                identifiers={(DOMAIN, subentry.subentry_id)},
                name=subentry.title,
            )
        elif subentry.subentry_type == SUBENTRY_WINDOW:
            issue_id = f"dangling_group_{subentry.subentry_id}"
            group_id = subentry.data.get(CONF_GROUP_ID)
            if group_id is not None and group_id not in entry.subentries:
                # Home Assistant offers no hook to refuse the removal of a
                # subentry. Fallback: the window inherits from the house only,
                # and a repair issue says so. The stored data is not touched
                # here, because changing it would call the listener again.
                data.dangling.add(subentry.subentry_id)
                ir.async_create_issue(
                    hass,
                    DOMAIN,
                    issue_id,
                    is_fixable=False,
                    severity=ir.IssueSeverity.WARNING,
                    translation_key="dangling_group",
                    translation_placeholders={"window": subentry.title},
                )
            else:
                ir.async_delete_issue(hass, DOMAIN, issue_id)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Unload the config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
