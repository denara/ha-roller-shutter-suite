"""The controls of the house, the groups and the windows, and what they mean for a window.

Pause, maintenance lock and operating mode exist on three levels: the house,
every group and every window (guardrail 2 of the brief; section 2.3 of the
specification). The switches and the select of each level (``switch.py``,
``select.py``) hold them; the :class:`ControlBoard` of the config entry is
where they are kept while the entry is loaded, and it is the controls
provider of the runtime (``SuiteRuntime.controls_of``): it hands every window
the three levels and dry-run as the core's ``Controls``. The core works out
the most restrictive value, as it has since the arbiter was built; nothing
here decides what a control holds back.

**A change never reloads the entry.** A switch or the select writes the new
value into the board, and the board asks every window the level concerns for
a recompute (``WindowController.async_request_recompute``), which runs within
the coalescing time. When a pause ends the window is recomputed, and nothing
is replayed.

**The external pause entity** (E4, the setting ``pause_source``) pauses a
level in addition to its switch while its state is ``on``. The house's own
entity pauses the house level, a group's own entity the group level, and the
window level is paused by the window's resolved reference: its own, or the
one it inherits from its group or the house. Because the most restrictive
level wins, a window cannot opt out of a house-wide external pause; "none" on
the window only keeps the inherited entity from also acting on the window
level. An entity that is unavailable or unknown, or whose state is neither
``on`` nor ``off``, **pauses** its level (ruling 4 of block H06): a pause holds
back comfort only, so this is the cautious side, as with a blind protection
source. A faulty stored reference is "configured, but blind" and pauses too.
After :data:`~.const.PAUSE_SOURCE_BLIND_AFTER` without a value, a repair issue
names the level that configured the entity and the entity; it disappears by
itself when the entity has a value again. An inherited entity is reported once,
at the level that configured it.

**A group reference that cannot be read** leaves it unknown which group's
controls apply. The window then takes the most restrictive combination of
every group, because a lock that nobody can see must not be dropped; its
comfort is suspended by the fault anyway. Nobody can see either whether that
group named a pause entity, so the resolved entity of the window level is
blind, and the window level is paused as well.
"""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import (
    async_track_point_in_utc_time,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN, PAUSE_SOURCE_BLIND_AFTER, SUBENTRY_GROUP
from .core.arbiter import MODE_TABLE, effective_controls
from .core.model import (
    BLIND_SOURCE,
    AnySourceValue,
    BlindSource,
    ControlLevel,
    Controls,
    OperatingMode,
    SourceState,
    SourceValue,
)
from .core.settings import WINDOW_SETTINGS, Level, PartialSettings
from .sources import SourceReference, read_source
from .stored import level_settings, read_window_identity
from .windows import WindowRuntime

_LOGGER = logging.getLogger(__name__)

PAUSE_SOURCE: Final = "pause_source"
"""The key of the external pause entity in the registry of the core."""

ISSUE_PAUSE_SOURCE_BLIND: Final = "pause_source_blind"
"""Repair issue: an external pause entity has had no value for too long."""

type Reference = str | BlindSource | None
"""An external pause entity as a level states it: an entity, blind, or none."""


@dataclass(frozen=True, slots=True)
class BlindSince:
    """An external pause entity without a value, and since when."""

    reference: str
    since: datetime


BLIND_MEMORY_KEY: HassKey[dict[str, BlindSince]] = HassKey(f"{DOMAIN}_pause_blind")
"""Since when each external pause entity has had no value, by issue ID.

Kept in ``hass.data`` next to the storage, so a reload of the entry does not
start the clock again; like the storage it is lost at a restart.
"""


@dataclass(slots=True)
class LevelSwitches:
    """What the switches and the select of one level say."""

    paused: bool = False
    maintenance_lock: bool = False
    mode: OperatingMode = OperatingMode.AUTOMATIC


@dataclass(frozen=True, slots=True)
class PauseCause:
    """Why one level of a window is paused: its switch or its external entity.

    ``entity_id`` is ``None`` for the switch. ``state`` is ``on`` for an
    entity that is on, ``unavailable`` or ``unknown`` for one without a value,
    ``blind`` for a reference that cannot be used, and the text of any other
    state; all but ``on`` pause because nothing is known.
    """

    level: Level
    entity_id: str | None = None
    state: str | None = None

    def as_data(self) -> dict[str, Any]:
        """Return the cause as plain data for the status and the diagnostics."""
        return {
            "level": self.level.value,
            "entity_id": self.entity_id,
            "state": self.state,
        }


@dataclass(frozen=True, slots=True)
class _Watched:
    """An external pause entity that a level configured itself."""

    issue_id: str
    level: Level
    name: str
    reference: str


def own_reference(settings: PartialSettings) -> Reference:
    """Return the external pause entity a level states itself.

    A level whose settings cannot be read, or whose own reference cannot be
    read, is blind: it could have named an entity, and nobody can see which.
    """
    if settings.unreadable or any(f.key == PAUSE_SOURCE for f in settings.faults):
        return BLIND_SOURCE
    value = settings.get(PAUSE_SOURCE)
    return value if isinstance(value, str) else None


def _read(hass: HomeAssistant, reference: str) -> AnySourceValue:
    parsed = SourceReference.parse(reference)
    return SourceValue.unavailable() if parsed is None else read_source(hass, parsed)


def _entity_of(reference: str) -> str:
    parsed = SourceReference.parse(reference)
    return reference if parsed is None else parsed.entity_id


def _pause_state(hass: HomeAssistant, reference: Reference) -> str | None:
    """Return why an external entity pauses its level, or ``None`` if it does not."""
    if reference is None:
        return None
    if isinstance(reference, BlindSource):
        return "blind"
    value = _read(hass, reference)
    if not value.has_value:
        return value.state.value
    if value.value is False:
        return None
    if value.value is True:
        return "on"
    return str(value.value)


def _has_value(hass: HomeAssistant, reference: str) -> bool:
    """Return whether an external entity says on or off."""
    value = _read(hass, reference)
    return value.state is SourceState.VALUE and isinstance(value.value, bool)


class ControlBoard:
    """The controls of every level of the config entry, and the provider of the runtime."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        windows: Mapping[str, WindowRuntime],
    ) -> None:
        """Read the levels, their groups and their external entities from the entry."""
        self.hass = hass
        self.house_id = entry.entry_id
        self.house_title = entry.title
        self.windows = dict(windows)
        self.groups: dict[str, str] = {
            subentry.subentry_id: subentry.title
            for subentry in entry.subentries.values()
            if subentry.subentry_type == SUBENTRY_GROUP
        }
        self.switches: dict[str, LevelSwitches] = {
            level_id: LevelSwitches()
            for level_id in (self.house_id, *self.groups, *self.windows)
        }
        self.request_recompute: Callable[[str], None] = lambda window_id: None
        """Ask the controller of a window for a recompute; the runtime sets it."""

        registry = WINDOW_SETTINGS
        self.house_reference = own_reference(level_settings(entry.data, registry))
        self.group_references: dict[str, Reference] = {
            group_id: own_reference(
                level_settings(entry.subentries[group_id].data, registry)
            )
            for group_id in self.groups
        }
        self._group_of: dict[str, str | None] = {}
        self._unreadable_group: set[str] = set()
        self._window_own: dict[str, Reference] = {}
        for window_id in self.windows:
            data = entry.subentries[window_id].data
            identity = read_window_identity(data)
            if not identity.group_readable:
                self._unreadable_group.add(window_id)
            group_id = identity.group_id
            self._group_of[window_id] = group_id if group_id in self.groups else None
            self._window_own[window_id] = own_reference(level_settings(data, registry))
        self._unsubscribe: list[CALLBACK_TYPE] = []
        self._timers: dict[str, CALLBACK_TYPE] = {}

    # ------------------------------------------------------------------
    # The levels
    # ------------------------------------------------------------------

    def level_kind(self, level_id: str) -> Level:
        """Return whether a level is the house, a group or a window."""
        if level_id == self.house_id:
            return Level.GLOBAL
        if level_id in self.groups:
            return Level.GROUP
        return Level.WINDOW

    def _name(self, level_id: str) -> str:
        """Return the name the user gave to a level."""
        kind = self.level_kind(level_id)
        if kind is Level.GLOBAL:
            return self.house_title
        if kind is Level.GROUP:
            return self.groups[level_id]
        return self.windows[level_id].title

    def windows_of(self, level_id: str) -> tuple[str, ...]:
        """Return the windows a level concerns."""
        kind = self.level_kind(level_id)
        if kind is Level.GLOBAL:
            return tuple(self.windows)
        if kind is Level.GROUP:
            return tuple(
                window_id
                for window_id in self.windows
                if self._group_of[window_id] == level_id
                or window_id in self._unreadable_group
            )
        return (level_id,) if level_id in self.windows else ()

    def _reference(self, level_id: str) -> Reference:
        """Return the external entity that pauses a level."""
        kind = self.level_kind(level_id)
        if kind is Level.GLOBAL:
            return self.house_reference
        if kind is Level.GROUP:
            return self.group_references[level_id]
        config = self.windows[level_id].resolution.config
        return None if config is None else config.pause_source

    def _level(self, level_id: str) -> ControlLevel:
        switches = self.switches[level_id]
        return ControlLevel(
            paused=switches.paused
            or _pause_state(self.hass, self._reference(level_id)) is not None,
            maintenance_lock=switches.maintenance_lock,
            mode=switches.mode,
        )

    def _group_level(self, window_id: str) -> ControlLevel:
        if window_id in self._unreadable_group:
            levels = [self._level(group_id) for group_id in self.groups]
            if not levels:
                return ControlLevel()
            return ControlLevel(
                paused=any(level.paused for level in levels),
                maintenance_lock=any(level.maintenance_lock for level in levels),
                mode=max(
                    (level.mode for level in levels),
                    key=lambda mode: MODE_TABLE[mode].restrictiveness,
                ),
            )
        group_id = self._group_of[window_id]
        return ControlLevel() if group_id is None else self._level(group_id)

    def controls_of(self, window: WindowRuntime) -> Controls:
        """Return the three levels and dry-run of a window: the controls provider.

        A window the entry did not name at set-up (the runtime can add one)
        is taken in with no group and with the default controls of its level.
        """
        window_id = window.subentry_id
        if window_id not in self.windows:
            self.windows[window_id] = window
            self.switches[window_id] = LevelSwitches()
            self._group_of[window_id] = None
            self._window_own[window_id] = None
        return Controls(
            dry_run=window.dry_run,
            window_level=self._level(window_id),
            group_level=self._group_level(window_id),
            global_level=self._level(self.house_id),
        )

    def _levels_of(self, window_id: str) -> list[str]:
        levels = [self.house_id]
        if window_id in self._unreadable_group:
            levels.extend(self.groups)
        elif (group_id := self._group_of[window_id]) is not None:
            levels.append(group_id)
        levels.append(window_id)
        return levels

    def pause_causes(self, window_id: str) -> list[PauseCause]:
        """Return every level that pauses a window, and whether by switch or entity."""
        causes: list[PauseCause] = []
        for level_id in self._levels_of(window_id):
            kind = self.level_kind(level_id)
            if self.switches[level_id].paused:
                causes.append(PauseCause(kind))
            reference = self._reference(level_id)
            state = _pause_state(self.hass, reference)
            if state is not None:
                entity = reference if isinstance(reference, str) else None
                causes.append(
                    PauseCause(
                        kind, None if entity is None else _entity_of(entity), state
                    )
                )
        return causes

    def level_report(self, level_id: str) -> dict[str, Any]:
        """Return the controls of one level as plain data."""
        switches = self.switches[level_id]
        reference = self._reference(level_id)
        return {
            "level": self.level_kind(level_id).value,
            "name": self._name(level_id),
            "paused": switches.paused,
            "maintenance_lock": switches.maintenance_lock,
            "mode": switches.mode.value,
            "pause_source": (
                reference if not isinstance(reference, BlindSource) else reference.value
            ),
            "pause_source_pauses": _pause_state(self.hass, reference),
        }

    def window_report(self, window_id: str) -> dict[str, Any]:
        """Return the controls of the levels of a window and the effective value."""
        effective = effective_controls(self.controls_of(self.windows[window_id]))
        return {
            "levels": [
                self.level_report(level_id) for level_id in self._levels_of(window_id)
            ],
            "effective": {
                "paused": effective.paused,
                "maintenance_lock": effective.maintenance_lock,
                "mode": effective.mode.value,
                "dry_run": effective.dry_run,
            },
            "paused_by": [cause.as_data() for cause in self.pause_causes(window_id)],
        }

    # ------------------------------------------------------------------
    # Changes
    # ------------------------------------------------------------------

    @callback
    def async_set(self, level_id: str, **changes: Any) -> None:
        """Change what the switches or the select of a level say; recompute its windows."""
        switches = self.switches[level_id]
        for name, value in changes.items():
            setattr(switches, name, value)
        self._recompute(self.windows_of(level_id))

    def _recompute(self, window_ids: Iterable[str]) -> None:
        for window_id in window_ids:
            self.request_recompute(window_id)

    # ------------------------------------------------------------------
    # External entities: listening, and the repair issue of a blind one
    # ------------------------------------------------------------------

    def _watched(self) -> list[_Watched]:
        """Return the external entities each level configured itself."""
        own: list[tuple[str, Level, str, Reference]] = [
            (self.house_id, Level.GLOBAL, self.house_title, self.house_reference),
            *(
                (group_id, Level.GROUP, title, self.group_references[group_id])
                for group_id, title in self.groups.items()
            ),
            *(
                (window_id, Level.WINDOW, window.title, self._window_own[window_id])
                for window_id, window in self.windows.items()
            ),
        ]
        return [
            _Watched(f"{ISSUE_PAUSE_SOURCE_BLIND}_{owner}", level, name, reference)
            for owner, level, name, reference in own
            if isinstance(reference, str)
        ]

    def _listened(self) -> dict[str, set[str]]:
        """Return the levels by the entity of the external pause entity they use."""
        listened: dict[str, set[str]] = {}
        for level_id in self.switches:
            reference = self._reference(level_id)
            if isinstance(reference, str):
                listened.setdefault(_entity_of(reference), set()).add(level_id)
        for item in self._watched():
            listened.setdefault(_entity_of(item.reference), set())
        return listened

    @callback
    def async_start(self) -> None:
        """Listen to the external entities and report the blind ones."""
        listened = self._listened()
        watched = self._watched()
        memory = self.hass.data.setdefault(BLIND_MEMORY_KEY, {})
        for issue_id in set(memory) - {item.issue_id for item in watched}:
            del memory[issue_id]
        if listened:

            @callback
            def _on_change(event: Event[EventStateChangedData]) -> None:
                entity_id = event.data["entity_id"]
                window_ids: set[str] = set()
                for level_id in listened.get(entity_id, ()):
                    window_ids.update(self.windows_of(level_id))
                self._recompute(sorted(window_ids))
                for item in watched:
                    if _entity_of(item.reference) == entity_id:
                        self._judge(item)

            self._unsubscribe.append(
                async_track_state_change_event(self.hass, list(listened), _on_change)
            )
        for item in watched:
            self._judge(item)

    @callback
    def async_stop(self) -> None:
        """Stop listening and cancel every timer; the issues and the memory stay."""
        for unsubscribe in self._unsubscribe:
            unsubscribe()
        self._unsubscribe.clear()
        for timer in self._timers.values():
            timer()
        self._timers.clear()

    def _judge(self, item: _Watched) -> None:
        """Start, keep or end the clock of a blind entity; report it when it is due."""
        memory = self.hass.data.setdefault(BLIND_MEMORY_KEY, {})
        if (timer := self._timers.pop(item.issue_id, None)) is not None:
            timer()
        if _has_value(self.hass, item.reference):
            memory.pop(item.issue_id, None)
            ir.async_delete_issue(self.hass, DOMAIN, item.issue_id)
            return
        now = dt_util.utcnow()
        known = memory.get(item.issue_id)
        if known is None or known.reference != item.reference:
            known = memory[item.issue_id] = BlindSince(item.reference, now)
        due = known.since + PAUSE_SOURCE_BLIND_AFTER
        if now >= due:
            self._report(item)
            return

        @callback
        def _on_due(moment: datetime) -> None:
            del moment
            self._timers.pop(item.issue_id, None)
            self._judge(item)

        self._timers[item.issue_id] = async_track_point_in_utc_time(
            self.hass, _on_due, due
        )

    def _report(self, item: _Watched) -> None:
        _LOGGER.debug(
            "The external pause entity of %s has had no value for %s",
            item.name,
            PAUSE_SOURCE_BLIND_AFTER,
        )
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            item.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=f"{ISSUE_PAUSE_SOURCE_BLIND}_{item.level.value}",
            translation_placeholders={
                "name": item.name,
                "entity": _entity_of(item.reference),
            },
        )


def forget_blind_memory(hass: HomeAssistant) -> None:
    """Drop the memory of blind external entities; for a removed entry."""
    hass.data.pop(BLIND_MEMORY_KEY, None)
