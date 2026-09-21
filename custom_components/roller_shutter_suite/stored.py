"""Reading stored configuration: the one place that turns it into what the core takes.

The house (the config entry), every group and every window (config subentries)
store two things apart from each other:

- **identity data**: for a window its covers, the reference to its group and
  dry-run. The name is the title of the subentry and is stored nowhere else;
- **settings**, in a mapping of their own under ``settings``, which holds
  nothing but keys of the registry of the core. An absent key is inherited,
  "no group" is an absent key, and ``null`` is never written.

Stored data can be faulty: written by hand, left behind by a failed migration,
written by a newer version. Nothing here raises because of it. Settings go to
``settings_from_stored`` of the core, which reports every fault; identity data
is read tolerantly, and whatever cannot be read is named so that the set-up
can report it and the form can start from an empty field.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.core import split_entity_id, valid_entity_id

from .const import CONF_COVERS, CONF_DRY_RUN, CONF_GROUP_ID, CONF_SETTINGS
from .core.model import JsonValue
from .core.settings import PartialSettings, SettingsRegistry, settings_from_stored

COVER_DOMAIN = "cover"


def level_settings(
    data: Mapping[str, Any], registry: SettingsRegistry
) -> PartialSettings:
    """Return the partial settings a level stores.

    A level without the mapping ``settings`` is unreadable as a whole, like
    one whose ``settings`` is no mapping: the flows and the migration always
    write it, so its absence is a fault and never means "everything inherited".
    """
    return settings_from_stored(data.get(CONF_SETTINGS), registry)


def sound_own_values(
    data: Mapping[str, Any], registry: SettingsRegistry
) -> dict[str, JsonValue]:
    """Return the stored settings of a level that the core can read, as stored.

    This is what a form starts from. A faulty value, an unknown key and blank
    text are left out, so saving the form writes a mapping without them; that
    is how a repair issue about a stored setting is repaired.
    """
    stored = data.get(CONF_SETTINGS)
    if not isinstance(stored, Mapping):
        return {}
    sound = settings_from_stored(stored, registry).values
    return {key: stored[key] for key in sound}


def _is_cover(value: object) -> bool:
    return (
        isinstance(value, str)
        and valid_entity_id(value)
        and split_entity_id(value)[0] == COVER_DOMAIN
    )


@dataclass(frozen=True, slots=True)
class WindowIdentity:
    """The identity data of a window as far as it can be read.

    ``covers`` is ``None`` if the covers cannot be read: no list, an empty
    list, an entry that is no cover entity, or a cover twice. Such a window is
    not set up. ``group_id`` is ``None`` for a window without a group.
    ``group_readable`` is false if the key is there but holds no identifier
    (``null``, for example); the window then counts as having a group that
    cannot be read. ``dry_run`` falls back to ``True`` if it cannot be read,
    because a window in dry-run never moves.
    """

    covers: tuple[str, ...] | None
    group_id: str | None
    group_readable: bool
    dry_run: bool
    dry_run_readable: bool


def read_window_identity(data: Mapping[str, Any]) -> WindowIdentity:
    """Read the identity data of a window subentry without raising."""
    covers: tuple[str, ...] | None = None
    raw_covers = data.get(CONF_COVERS)
    if (
        isinstance(raw_covers, (list, tuple))
        and raw_covers
        and all(_is_cover(item) for item in raw_covers)
        and len(set(raw_covers)) == len(raw_covers)
    ):
        covers = tuple(raw_covers)

    group_id: str | None = None
    group_readable = True
    if CONF_GROUP_ID in data:
        raw_group = data[CONF_GROUP_ID]
        if isinstance(raw_group, str) and raw_group:
            group_id = raw_group
        else:
            group_readable = False

    raw_dry_run = data.get(CONF_DRY_RUN)
    dry_run_readable = isinstance(raw_dry_run, bool)
    return WindowIdentity(
        covers=covers,
        group_id=group_id,
        group_readable=group_readable,
        dry_run=raw_dry_run if isinstance(raw_dry_run, bool) else True,
        dry_run_readable=dry_run_readable,
    )
