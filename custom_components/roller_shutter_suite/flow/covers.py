"""Cover groups and the rule "a cover belongs to at most one window" (N3).

A window has one or more covers that are moved together. If the user selects a
Home Assistant cover group, it is taken apart into its members, recursively;
the members are stored, never the group entity, because a group reports only
the mean of its members (``docs/architecture.md``, section 9).
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, ATTR_GROUP_ENTITIES
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.group import get_group_entities

from custom_components.roller_shutter_suite.const import SUBENTRY_WINDOW
from custom_components.roller_shutter_suite.stored import (
    COVER_DOMAIN,
    read_window_identity,
)

GROUP_PLATFORM = "group"
GROUP_OPTION_ENTITIES = "entities"


def group_members(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """Return the direct members if the entity is a group, otherwise ``None``.

    Three signals, newest first, because Home Assistant 2026.9 is in the
    middle of a change (``docs/dev/config-flow-findings.md``, section 10):

    1. The entity announces itself as a group (``Entity.group``). In 2026.9.2
       the cover group does not do that yet.
    2. The state carries the member list: the attribute ``group_entities`` or
       the attribute ``entity_id`` of the group platform. This is what
       identifies a cover group today, also one defined in YAML without a
       unique ID.
    3. The entity registry says that the entity comes from the ``group``
       platform, and the config entry of the group lists the members. This
       still answers while the group has no state.
    """
    entity = get_group_entities(hass).get(entity_id)
    if entity is not None and entity.group is not None:
        return list(entity.group.member_entity_ids)

    if (state := hass.states.get(entity_id)) is not None:
        for attribute in (ATTR_GROUP_ENTITIES, ATTR_ENTITY_ID):
            members = state.attributes.get(attribute)
            if isinstance(members, (list, tuple)):
                return [str(member) for member in members]

    registry = er.async_get(hass)
    entry = registry.async_get(entity_id)
    if (
        entry is not None
        and entry.platform == GROUP_PLATFORM
        and entry.config_entry_id is not None
        and (group_entry := hass.config_entries.async_get_entry(entry.config_entry_id))
        is not None
    ):
        return er.async_validate_entity_ids(
            registry, list(group_entry.options.get(GROUP_OPTION_ENTITIES, []))
        )
    return None


@dataclass(slots=True)
class ResolvedCovers:
    """The member covers of a selection and the groups that were taken apart."""

    members: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


def resolve_covers(hass: HomeAssistant, selected: Iterable[str]) -> ResolvedCovers:
    """Replace cover groups by their members, recursively.

    The order of the selection is kept, a cover that is reached twice is kept
    once, a group that contains itself ends the descent (cycle guard), and
    members that are no covers are dropped.
    """
    result = ResolvedCovers()
    visited: set[str] = set()

    def visit(entity_id: str) -> None:
        if entity_id in visited:
            return
        visited.add(entity_id)
        members = group_members(hass, entity_id)
        if members is None:
            result.members.append(entity_id)
            return
        result.groups.append(entity_id)
        for member in members:
            if split_entity_id(member)[0] == COVER_DOMAIN:
                visit(member)

    for entity_id in selected:
        visit(entity_id)
    return result


def find_conflict(
    entry: ConfigEntry, members: Iterable[str], own_subentry_id: str | None
) -> tuple[str, str] | None:
    """Return (member, title of the other window) if a member is already used.

    The window's own subentry is left out, so a window keeps its covers on
    reconfigure. A window whose covers cannot be read claims none.
    """
    wanted = set(members)
    for subentry in entry.subentries.values():
        if (
            subentry.subentry_type != SUBENTRY_WINDOW
            or subentry.subentry_id == own_subentry_id
        ):
            continue
        for member in read_window_identity(subentry.data).covers or ():
            if member in wanted:
                return member, subentry.title
    return None
