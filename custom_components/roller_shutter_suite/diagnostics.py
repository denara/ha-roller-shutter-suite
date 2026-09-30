"""The diagnostics download: for the config entry, and for the device of one window.

What a window shows: its resolved configuration with the level every value
comes from, the capability profile of every member, the status of its
controller (phase, sources, schedule, commands, next wake-up, and under
``movement_tracking`` per member whether its movements are judged, what the
user stated and what the tracker measured, next to the daily count of
comfort movements and its threshold), the controls
of its levels (house, group, window) with the effective value and what pauses
it, the last decisions with the time each was first made, and its persisted
state. The download of the entry adds the controls of the house and of every
group.

**Redaction** follows the convention of Home Assistant: a download is meant
to be attached to a bug report, and a report can only be matched with the
installation by its entity IDs and names. They stay: the names of windows and
groups, the member IDs, the entity IDs of sources and of settings that refer
to an entity, and the identifier of a simulated command in dry-run, which
names its member. Removed with Home Assistant's ``async_redact_data`` are the
coordinates and the elevation of a location (``latitude``, ``longitude``,
``elevation``) and anything secret-like (``password``, ``token``,
``access_token``, ``api_key``), by their key wherever they would appear. None
of them is part of a window today; the list keeps a later addition from
writing one out. A sun elevation of the schedule is a setting value under its
own setting key, so it is shown. Members appear in the order of the
configuration, so the targets and observations of the same member stand at
the same place in every list.

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
from homeassistant.const import (
    CONF_ACCESS_TOKEN,
    CONF_API_KEY,
    CONF_ELEVATION,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_PASSWORD,
    CONF_TOKEN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from . import RollerShutterSuiteConfigEntry
from .const import DOMAIN
from .controller import SourceReading, WindowController
from .core.arbiter.capabilities import has_no_position_feedback, is_tracked
from .core.model import MemberConfig, SampleStatistic, SourceState
from .core.settings import ResolvedValue
from .events import WindowHistory, history_of
from .record import decision_attributes, member_targets, plain
from .sources import SourceReference
from .windows import WindowRuntime

TO_REDACT: Final = frozenset(
    {
        CONF_LATITUDE,
        CONF_LONGITUDE,
        CONF_ELEVATION,
        CONF_PASSWORD,
        CONF_TOKEN,
        CONF_ACCESS_TOKEN,
        CONF_API_KEY,
    }
)

DETECTION_ACTIVE: Final = "active"
"""Movements of the member are judged: the tracker follows it."""
DETECTION_UNKNOWN: Final = "unknown"
"""The reporting time of the member is not stated: nothing is judged."""
DETECTION_INACTIVE: Final = "inactive"
"""The member reports no position: there is nothing to judge (section 8.1)."""

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


def _setting(item: ResolvedValue[Any]) -> dict[str, Any]:
    return {
        "key": item.key,
        "value": plain(item.value),
        "effective": plain(item.effective),
        "level": item.level.value,
        "group_id": item.group_id,
        "cautious": item.cautious,
        "capability": None if item.capability is None else item.capability.value,
        "unavailable": (
            None if item.unavailable is None else item.unavailable.capability.value
        ),
    }


def _configuration(window: WindowRuntime) -> dict[str, Any]:
    settings = window.resolution.settings
    config = window.resolution.config
    return {
        "settings": [_setting(item) for item in settings.values.values()],
        "member_settings": [
            {
                "member_id": member_id,
                "settings": [_setting(item) for item in values.values()],
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
    return {
        "entity_id": None if reference is None else reference.entity_id,
        "attribute": None if reference is None else reference.attribute,
        "state": value.state.value,
        "value": plain(value.value) if value.state is SourceState.VALUE else None,
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
        "movement_tracking": _movement_tracking(controller),
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


def _statistic(statistic: SampleStatistic) -> dict[str, Any]:
    return {
        "count": statistic.count,
        "median": statistic.median,
        "maximum": statistic.maximum,
    }


def _detection(member: MemberConfig) -> str:
    """Say whether movements of the member are judged: active, unknown or inactive."""
    if has_no_position_feedback(member.capabilities):
        return DETECTION_INACTIVE
    if is_tracked(member.capabilities):
        return DETECTION_ACTIVE
    return DETECTION_UNKNOWN


def _movement_tracking(controller: WindowController) -> dict[str, Any]:
    """Return what the tracker knows per member, next to what the user stated.

    The measured latency and time to rest stand next to the reporting time
    and the travel times the member states, so that a user can tune them;
    nothing is tuned automatically. The daily count of comfort movements
    stands with its threshold.
    """
    state = controller.state
    count = state.comfort_movements
    members = []
    for member in controller.config.members:
        profile = member.capabilities
        member_state = state.member_state(member.member_id)
        measured = member_state.self_measurement
        members.append(
            {
                "member_id": member.member_id,
                "movement_detection": _detection(member),
                "reporting_kind": plain(profile.reporting_kind),
                "reporting_time": plain(profile.reporting_time),
                "travel_time_up": plain(profile.travel_time_up),
                "travel_time_down": plain(profile.travel_time_down),
                "tolerance": profile.tolerance,
                "phase": member_state.tracking.phase.value,
                "position_reference": member_state.position_reference.value,
                "latency_ms": _statistic(measured.latency),
                "time_to_rest_ms": _statistic(measured.time_to_rest),
                "end_deviation": _statistic(measured.end_deviation),
            }
        )
    return {
        "members": members,
        "comfort_movements": {
            "day": None if count is None else count.day.isoformat(),
            "count": 0 if count is None else count.count,
            "reported": False if count is None else count.reported,
            "threshold": controller.config.comfort_movements_threshold,
        },
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
        "controls": data.board.window_report(window_id),
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
            "controls": [
                data.board.level_report(level_id)
                for level_id in (data.board.house_id, *data.board.groups)
            ],
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
