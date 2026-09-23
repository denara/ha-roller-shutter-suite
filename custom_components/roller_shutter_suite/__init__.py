"""The Roller Shutter Suite integration.

One config entry represents the house; groups and windows are config
subentries. The set-up reads the stored configuration, resolves the settings
of every window with the resolver of the core, creates one device per window,
reports what is wrong with stored data as repair issues, and starts the
runtime: one controller per window that feeds the core and calls it
(``docs/dev/runtime.md``).

**Every change reloads the whole config entry.** An update listener schedules
the reload; the flows only create or update and never reload themselves. Home
Assistant calls the listener after a subentry was added, changed, renamed or
removed and after the data of the entry changed, and only if something really
changed. The runtime state of every window survives the reload through the
storage port.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr

from .actuator import RecordingActuator
from .const import CONF_SETTINGS, CONFIG_MINOR_VERSION, CONFIG_VERSION, DOMAIN
from .features import get_catalog
from .issues import async_sync_issues
from .location import HomeAssistantClock, local_zone, sun_port
from .runtime import SuiteRuntime
from .storage import forget_storage, storage_of
from .windows import WindowRuntime, resolve_entry


@dataclass(slots=True)
class RollerShutterSuiteData:
    """Runtime data of the config entry; it lives as long as the entry is loaded.

    ``windows`` holds the windows that are set up, by subentry ID, each with
    its resolved settings. ``not_set_up`` names the windows whose covers could
    not be read. ``runtime`` holds the controllers of the windows.
    """

    runtime: SuiteRuntime
    windows: dict[str, WindowRuntime] = field(default_factory=dict)
    not_set_up: tuple[str, ...] = ()


type RollerShutterSuiteConfigEntry = ConfigEntry[RollerShutterSuiteData]


async def _async_reload_on_update(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> None:
    """Schedule the reload after any change of the entry or one of its subentries."""
    hass.config_entries.async_schedule_reload(entry.entry_id)


async def async_setup_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Set up Roller Shutter Suite from its config entry.

    The ports of the core come first: a zone that is not a named one or a
    missing sun port fails the set-up closed, before any window is looked
    at. After that nothing raises for a single window.
    """
    runtime = SuiteRuntime(
        hass,
        clock=HomeAssistantClock(local_zone(hass)),
        sun=sun_port(hass),
        storage=storage_of(hass),
        actuator=RecordingActuator(),
    )
    resolved = resolve_entry(hass, entry, get_catalog())
    entry.runtime_data = RollerShutterSuiteData(
        runtime=runtime,
        windows=resolved.windows,
        not_set_up=tuple(resolved.not_set_up),
    )

    # One device per window, tied to the window's subentry and to nothing
    # else. Removing the subentry removes the device without code of ours.
    device_registry = dr.async_get(hass)
    for window in resolved.windows.values():
        device_registry.async_get_or_create(
            config_entry_id=entry.entry_id,
            config_subentry_id=window.subentry_id,
            identifiers={(DOMAIN, window.subentry_id)},
            name=window.title,
        )

    async_sync_issues(hass, resolved.issues.values())
    runtime.async_start(resolved.windows)
    entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Unload the config entry: stop every controller, cancel every listener and timer.

    The state of every window stays in the storage, so a reload continues
    where the windows were.
    """
    entry.runtime_data.runtime.async_stop()
    return True


async def async_remove_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> None:
    """Delete the repair issues and the stored state of an entry that is removed."""
    async_sync_issues(hass, ())
    forget_storage(hass)


def _with_settings(data: Mapping[str, Any]) -> dict[str, Any]:
    """Return stored data of version 1.1 in the layout of version 1.2."""
    return {CONF_SETTINGS: {}} | dict(data)


async def async_migrate_entry(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> bool:
    """Migrate the stored data of the entry and of its subentries.

    The version of the config entry covers the data of the subentries too,
    because Home Assistant keeps no version per subentry.

    - 1.1 -> 1.2: every level gets the mapping ``settings``. A value that is
      already there is left alone, whatever it is: judging stored settings is
      the job of the fault rule at set-up, never a reason to fail a migration.
    - A newer minor version (a downgrade) is accepted unchanged: unknown keys
      are reported at set-up and harm nothing.

    Errors are reported by raising, as the developer documentation asks for:
    a version this code cannot start from raises ``ConfigEntryError``, and
    Home Assistant puts the entry into the state "migration error". A newer
    major version never gets here; Home Assistant refuses it itself.
    """
    if entry.version != CONFIG_VERSION or entry.minor_version < 1:
        raise ConfigEntryError(
            f"cannot migrate from version {entry.version}.{entry.minor_version}"
        )
    if entry.minor_version >= CONFIG_MINOR_VERSION:
        return True
    for subentry in entry.subentries.values():
        hass.config_entries.async_update_subentry(
            entry, subentry, data=_with_settings(subentry.data)
        )
    hass.config_entries.async_update_entry(
        entry,
        data=_with_settings(entry.data),
        version=CONFIG_VERSION,
        minor_version=CONFIG_MINOR_VERSION,
    )
    return True
