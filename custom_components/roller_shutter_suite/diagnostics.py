"""The diagnostics download: for the config entry, and for the device of one window.

What a window shows: its resolved configuration with the level every value
comes from, the capability profile of every member, the status of its
controller (phase, sources, schedule, commands, next wake-up), the last
decisions with the time each was first made, and its persisted state.

**Redaction.** A download is meant to be attached to a bug report, so what
names the installation is removed with Home Assistant's
``async_redact_data``: the names of windows and groups (``name``), and every
entity ID (``member_id``, ``entity_id``, the identifier of a command, which
names the member for a simulated command in dry-run, and the value of every
setting that refers to an entity). A source that holds text shows its state but not the
text. Members appear in the order of the configuration, so the targets and
observations of the same member stand at the same place in every list.

**Faults of the arbiter** appear with their stage, place, function and
reason code, never with the exception or its message
(``record.fault_attributes``). The English detail of a fault in stored
settings, which is meant for logs, is left out as well.

**``seen_unchanged_since``** of a source is the time of the first recompute
that saw its present value. The controller keeps it, not the storage, so it
starts again with every reload and restart; it is not a persisted fact.
"""

from collections.abc import Mapping
from typing import Any, Final

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import RollerShutterSuiteConfigEntry
from .const import DOMAIN
from .controller import SourceReading, WindowController
from .core.model import SourceState
from .core.settings import ResolvedValue, SettingKind
from .events import WindowHistory, history_of
from .features import get_catalog
from .record import decision_attributes, member_targets, plain
from .sources import SourceReference
from .windows import WindowRuntime

REDACTED: Final = "**REDACTED**"
TO_REDACT: Final = frozenset({"name", "member_id", "entity_id", "command_id"})

_SCHEDULE_FACTS: Final = (
    "evaluated_at",
    "part_of_day",
    "part_of_day_since",
    "morning_trigger",
    "evening_trigger",
    "evening_by_brightness",
    "day_type",
    "day_type_latched",
    "day_type_reason",
    "summer",
    "season_reason",
    "brightness_reason",
    "next_action",
    "recheck_at",
)


def _setting(item: ResolvedValue[Any], reference: bool) -> dict[str, Any]:
    def shown(value: object) -> object:
        return REDACTED if reference and value is not None else plain(value)

    return {
        "key": item.key,
        "value": shown(item.value),
        "effective": shown(item.effective),
        "level": item.level.value,
        "group_id": item.group_id,
        "cautious": item.cautious,
        "capability": None if item.capability is None else item.capability.value,
        "unavailable": (
            None if item.unavailable is None else item.unavailable.capability.value
        ),
    }


def _configuration(window: WindowRuntime) -> dict[str, Any]:
    definitions = get_catalog().definitions
    settings = window.resolution.settings

    def is_reference(key: str) -> bool:
        definition = definitions.get(key)
        return (
            definition is not None and definition.kind is SettingKind.OPTIONAL_REFERENCE
        )

    config = window.resolution.config
    return {
        "settings": [
            _setting(item, is_reference(key)) for key, item in settings.values.items()
        ],
        "member_settings": [
            {
                "member_id": member_id,
                "settings": [
                    _setting(item, is_reference(key)) for key, item in values.items()
                ],
            }
            for member_id, values in settings.member_values.items()
        ],
        "faults": [
            {
                "key": fault.key,
                "level": fault.level.value,
                "group_id": fault.group_id,
                "problem": fault.problem.value,
                "action": fault.action.value,
                "disabled_functions": [f.value for f in fault.disabled_functions],
            }
            for fault in settings.faults
        ],
        "disabled_functions": sorted(f.value for f in settings.disabled_functions),
        "group_missing": settings.group_missing is not None,
        "members": (
            []
            if config is None
            else [
                {
                    "member_id": member.member_id,
                    "capabilities": plain(member.capabilities),
                }
                for member in config.members
            ]
        ),
    }


def _source(
    reference: SourceReference | None, reading: SourceReading
) -> dict[str, Any]:
    value = reading.value
    shown: object = None
    if value.state is SourceState.VALUE:
        shown = REDACTED if isinstance(value.value, str) else plain(value.value)
    return {
        "entity_id": None if reference is None else reference.entity_id,
        "attribute": None if reference is None else reference.attribute,
        "state": value.state.value,
        "value": shown,
        "seen_unchanged_since": reading.since.isoformat(),
    }


def _status(controller: WindowController) -> dict[str, Any]:
    status = controller.status
    schedule = status.schedule
    observation = status.observation
    return {
        "phase": status.phase.value,
        "dry_run": controller.controls().dry_run,
        "recomputes": status.recomputes,
        "last_recompute": plain(status.last_recompute),
        "error": status.error,
        "wake_up": plain(status.wake_up),
        "observation": [] if observation is None else plain(observation.members),
        "sources": [
            _source(controller.sources.get(key), reading)
            for key, reading in status.sources.items()
        ],
        "schedule": (
            None
            if schedule is None
            else {name: plain(getattr(schedule, name)) for name in _SCHEDULE_FACTS}
        ),
        "commands": [command.to_data() for command in status.commands],
        "decision": (
            None
            if status.decision is None
            else {
                **decision_attributes(
                    status.decision, dry_run=controller.controls().dry_run
                ),
                "member_targets": member_targets(status.decision.targets),
            }
        ),
    }


def _decisions(history: WindowHistory) -> list[dict[str, Any]]:
    return [
        {
            "first_made_at": plain(item.at),
            **decision_attributes(item.decision, dry_run=item.dry_run),
            "member_targets": member_targets(item.decision.targets),
        }
        for item in history.recent
    ]


def _window(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry, window_id: str
) -> dict[str, Any]:
    data = entry.runtime_data
    window = data.windows[window_id]
    controller = data.runtime.windows.get(window_id)
    persisted: Mapping[str, Any] | None = (
        controller.state.to_data()
        if controller is not None
        else data.runtime.storage.load_window_state(window_id)
    )
    return {
        "subentry_id": window_id,
        "name": window.title,
        "dry_run": window.dry_run,
        "not_controlled": data.runtime.failed.get(window_id),
        "configuration": _configuration(window),
        "status": None if controller is None else _status(controller),
        "recent_decisions": _decisions(
            history_of(hass).get(window_id) or WindowHistory()
        ),
        "persisted_state": persisted,
    }


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry
) -> dict[str, Any]:
    """Return the diagnostics of the entry: every window that is set up."""
    data = entry.runtime_data
    return async_redact_data(
        {
            "entry": {
                "version": entry.version,
                "minor_version": entry.minor_version,
            },
            "windows": [_window(hass, entry, window_id) for window_id in data.windows],
            "windows_not_set_up": list(data.not_set_up),
        },
        TO_REDACT,
    )


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: RollerShutterSuiteConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return the diagnostics of the window that the device stands for."""
    window_ids = [
        identifier
        for domain, identifier in device.identifiers
        if domain == DOMAIN and identifier in entry.runtime_data.windows
    ]
    return async_redact_data(
        {"windows": [_window(hass, entry, window_id) for window_id in window_ids]},
        TO_REDACT,
    )
