"""SPIKE S2: cover groups, member uniqueness and capabilities at flow time."""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_GROUP_ENTITIES,
    ATTR_SUPPORTED_FEATURES,
)
from homeassistant.core import HomeAssistant, split_entity_id
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.group import get_group_entities

from custom_components.roller_shutter_suite.const import CONF_COVERS, SUBENTRY_WINDOW

COVER_DOMAIN = "cover"
GROUP_PLATFORM = "group"
ATTR_CURRENT_POSITION = "current_position"


def group_members(hass: HomeAssistant, entity_id: str) -> list[str] | None:
    """Return the direct members if the entity is a group, otherwise None.

    Three signals, newest first, because Home Assistant 2026.9 is in the middle
    of a transition:

    1. The entity announces itself as a group (``Entity.group``). In 2026.9.2
       only the lock group does; the cover group does not yet.
    2. The state carries the member list: the new capability attribute
       ``group_entities`` or the classic attribute ``entity_id`` of the group
       platform. This is what identifies a cover group today, including one
       defined in YAML without a unique ID.
    3. The entity registry says the entity comes from the ``group`` platform and
       its config entry lists the members. This still works while the group
       has no state, for example during start-up.
    """
    if (
        entity := get_group_entities(hass).get(entity_id)
    ) is not None and entity.group is not None:
        return list(entity.group.member_entity_ids)

    if (state := hass.states.get(entity_id)) is not None:
        for attribute in (ATTR_GROUP_ENTITIES, ATTR_ENTITY_ID):
            members = state.attributes.get(attribute)
            if isinstance(members, (list, tuple)):
                return [str(member) for member in members]

    registry = er.async_get(hass)
    if (
        (entry := registry.async_get(entity_id)) is not None
        and entry.platform == GROUP_PLATFORM
        and entry.config_entry_id is not None
        and (group_entry := hass.config_entries.async_get_entry(entry.config_entry_id))
        is not None
    ):
        return er.async_validate_entity_ids(
            registry, group_entry.options.get("entities", [])
        )
    return None


@dataclass(slots=True)
class ResolvedCovers:
    """The member covers of a selection and the groups that were taken apart."""

    members: list[str] = field(default_factory=list)
    groups: list[str] = field(default_factory=list)


def resolve_covers(hass: HomeAssistant, selected: Iterable[str]) -> ResolvedCovers:
    """Replace cover groups by their members, recursively, keeping the order."""
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
    """Return (member, title of the other window) if a member is already used."""
    wanted = set(members)
    for subentry in entry.subentries.values():
        if (
            subentry.subentry_type != SUBENTRY_WINDOW
            or subentry.subentry_id == own_subentry_id
        ):
            continue
        for member in subentry.data.get(CONF_COVERS, []):
            if member in wanted:
                return member, subentry.title
    return None


@dataclass(slots=True)
class Capabilities:
    """Lowest common denominator of the members, and who limits it."""

    supported: dict[str, bool]
    limited_by: dict[str, str]


def detect_capabilities(hass: HomeAssistant, members: Iterable[str]) -> Capabilities:
    """Read what the members can do from their current state.

    A member without a state (unavailable at configuration time) proves
    nothing; the spike treats it as "cannot", names it as the limiting member
    and leaves the better answer to block H12.
    """
    checks: dict[str, Callable[[int, Mapping[str, Any]], bool]] = {
        "stop": lambda features, attributes: bool(features & CoverEntityFeature.STOP),
        "set_position": lambda features, attributes: bool(
            features & CoverEntityFeature.SET_POSITION
        ),
        "reports_position": lambda features, attributes: (
            attributes.get(ATTR_CURRENT_POSITION) is not None
        ),
    }
    supported = dict.fromkeys(checks, True)
    limited_by: dict[str, str] = {}
    for member in members:
        state = hass.states.get(member)
        attributes = {} if state is None else state.attributes
        features = int(attributes.get(ATTR_SUPPORTED_FEATURES, 0))
        for capability, check in checks.items():
            if not check(features, attributes) and supported[capability]:
                supported[capability] = False
                limited_by[capability] = member
    return Capabilities(supported, limited_by)
