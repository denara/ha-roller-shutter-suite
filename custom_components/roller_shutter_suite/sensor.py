"""SPIKE S2: one dummy sensor per window, attached to the window's subentry.

Its state is the effective morning position, resolved window -> group -> house,
so a test can watch a value being inherited over two levels after a reload.
"""

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import RollerShutterSuiteConfigEntry
from .const import CONF_GROUP_ID, CONF_SETTINGS, DOMAIN, SUBENTRY_WINDOW
from .features.daily_routine.flow import FEATURE
from .flow.model import Parent, resolve

MORNING_POSITION = next(
    setting for setting in FEATURE.fields if setting.key == "morning_position"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: RollerShutterSuiteConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the dummy sensor of every window to that window's subentry."""
    for subentry in entry.subentries.values():
        if subentry.subentry_type != SUBENTRY_WINDOW:
            continue
        async_add_entities(
            [EffectiveMorningPosition(entry, subentry)],
            config_subentry_id=subentry.subentry_id,
        )


class EffectiveMorningPosition(SensorEntity):
    """The morning position that applies to a window."""

    _attr_has_entity_name = True
    _attr_translation_key = "effective_morning_position"
    _attr_native_unit_of_measurement = "%"

    def __init__(
        self, entry: RollerShutterSuiteConfigEntry, subentry: ConfigSubentry
    ) -> None:
        """Resolve the value once; a change of the configuration reloads."""
        self._attr_unique_id = f"{subentry.subentry_id}_morning_position"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, subentry.subentry_id)}, name=subentry.title
        )
        parents = [Parent(entry.title, entry.data.get(CONF_SETTINGS, {}))]
        group = entry.subentries.get(subentry.data.get(CONF_GROUP_ID) or "")
        if group is not None:
            parents.insert(0, Parent(group.title, group.data.get(CONF_SETTINGS, {})))
        self._attr_native_value = resolve(
            MORNING_POSITION, subentry.data.get(CONF_SETTINGS, {}), tuple(parents)
        )
