"""Helpers that drive the flows the way the frontend does, and a second catalog.

The forms are generic over the registry of the core. Most of what they can do
is shown with the real settings. Two things have no real setting yet: a
setting that needs a capability of the covers, and a setting that only a
window can set and that a form shows. For these the tests use a second
catalog: the registry of the core plus two made-up entries, their form
description, and a resolver with the value rules of the core. Nothing of it
exists outside the tests.
"""

import dataclasses
from collections.abc import Mapping
from typing import Any

from homeassistant.components.cover import CoverEntityFeature
from homeassistant.config_entries import SOURCE_USER, ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    CONFIG_MINOR_VERSION,
    CONFIG_VERSION,
    DOMAIN,
    ENTRY_TITLE,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.model import (
    FunctionId,
    MemberConfig,
    WindowConfig,
)
from custom_components.roller_shutter_suite.core.model._data import as_bool, as_int
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    Capability,
    CapabilityRequirement,
    GroupLevel,
    PartialSettings,
    SettingDefinition,
    SettingKind,
    SettingRules,
    SettingsRegistry,
    WindowResolution,
    resolve_settings,
)
from custom_components.roller_shutter_suite.features.daily_routine import (
    DAILY_ROUTINE,
)
from custom_components.roller_shutter_suite.flow.model import (
    Catalog,
    FeatureForm,
    FieldForm,
    StepForm,
)

FULL_COVER = (
    CoverEntityFeature.OPEN
    | CoverEntityFeature.CLOSE
    | CoverEntityFeature.STOP
    | CoverEntityFeature.SET_POSITION
)
NO_STOP = FULL_COVER & ~CoverEntityFeature.STOP
OPEN_CLOSE_ONLY = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE

EXAMPLE_KEYS = ("example_hold", "example_window_only")

EXAMPLE_REGISTRY = SettingsRegistry(
    (
        *WINDOW_SETTINGS.definitions,
        # A switch that needs a capability of the covers: the registry of the
        # core has no such setting yet.
        SettingDefinition(
            key="example_hold",
            kind=SettingKind.BOOLEAN,
            function=FunctionId.SCHEDULE,
            default=False,
            parse=as_bool,
            requires=CapabilityRequirement(Capability.SUPPORTS_STOP, False),
        ),
        # A setting that only a window can set and that a form shows: the
        # registry of the core has one (the covering type), but it has a
        # single value and no form.
        SettingDefinition(
            key="example_window_only",
            kind=SettingKind.NUMBER,
            function=None,
            default=1,
            parse=as_int,
            inheritable=False,
        ),
    )
)

_GENERAL, *_DAY_TYPES = DAILY_ROUTINE.steps

EXAMPLE_FEATURE = FeatureForm(
    feature_id=DAILY_ROUTINE.feature_id,
    switch=DAILY_ROUTINE.switch,
    steps=(
        StepForm(
            name=_GENERAL.name,
            fields=(
                *_GENERAL.fields,
                FieldForm(key="example_hold"),
                FieldForm(key="example_window_only"),
            ),
        ),
        *_DAY_TYPES,
    ),
)


def resolve_example(
    *,
    window_id: str,
    members: tuple[MemberConfig, ...],
    global_settings: PartialSettings,
    window_settings: PartialSettings,
    group: GroupLevel | None = None,
) -> WindowResolution:
    """Resolve the extended registry the way ``resolve_window`` resolves its own.

    The value rules are those of ``WindowConfig``; the made-up settings have
    none and are no fields of it.
    """
    identity = WindowConfig(window_id=window_id, members=members)

    def check_value(key: str, value: object) -> None:
        if key not in EXAMPLE_KEYS:
            change: dict[str, Any] = {key: value}
            dataclasses.replace(identity, **change)

    def build(effective: Mapping[str, Any], disabled: frozenset[FunctionId]) -> object:
        known = {k: v for k, v in effective.items() if k not in EXAMPLE_KEYS}
        return dataclasses.replace(identity, **known, disabled_functions=disabled)

    settings = resolve_settings(
        EXAMPLE_REGISTRY,
        capabilities=identity.capability_states,
        members=identity.members,
        global_settings=global_settings,
        window_settings=window_settings,
        group=group,
        rules=SettingRules(check_value, build),
    )
    return WindowResolution(identity, settings)


EXAMPLE_CATALOG = Catalog(
    registry=EXAMPLE_REGISTRY, features=(EXAMPLE_FEATURE,), resolve=resolve_example
)

# What a browser sends for the pages of the daily routine when every field is
# left as it is: the required drop-downs and the section, nothing else.
SWITCHES_INHERIT: dict[str, Any] = {"schedule_enabled": "inherit_on"}
GENERAL_INHERIT: dict[str, Any] = {
    "schedule_workday_source_choice": "inherit_none",
    "schedule_holiday_source_choice": "inherit_none",
    "schedule_season_source_choice": "inherit_none",
    "schedule_summer_by_date": "inherit_off",
    "schedule_brightness_source_choice": "inherit_none",
    "expert": {},
}
SWITCHES_HOUSE: dict[str, Any] = {"schedule_enabled": True}
GENERAL_HOUSE: dict[str, Any] = {
    "schedule_workday_source_choice": "none",
    "schedule_holiday_source_choice": "none",
    "schedule_season_source_choice": "none",
    "schedule_brightness_source_choice": "none",
    "expert": {},
}
DAY_HOUSE: dict[str, Any] = {"expert": {}}
DAY_TYPES = ("workday", "weekend", "holiday")


def day_inherit(day_type: str, **changes: Any) -> dict[str, Any]:
    """Return the input of the page of one day type on a level that inherits."""
    return {
        f"schedule_{day_type}_morning_kind": "inherit",
        f"schedule_{day_type}_evening_kind": "inherit",
        "expert": {},
    } | changes


def routine_inherit(
    general: dict[str, Any] | None = None, **days: dict[str, Any]
) -> list[dict[str, Any]]:
    """Return the inputs of all pages of the daily routine, with the given changes."""
    return [
        SWITCHES_INHERIT,
        GENERAL_INHERIT | (general or {}),
        *(day_inherit(day_type, **days.get(day_type, {})) for day_type in DAY_TYPES),
    ]


ROUTINE_HOUSE: list[dict[str, Any]] = [
    SWITCHES_HOUSE,
    GENERAL_HOUSE,
    DAY_HOUSE,
    DAY_HOUSE,
    DAY_HOUSE,
]


def set_cover(
    hass: HomeAssistant,
    entity_id: str,
    features: CoverEntityFeature = FULL_COVER,
    position: int | None = 100,
    state: str = "open",
) -> None:
    """Put a cover state on the state machine, as a cover platform would."""
    attributes: dict[str, Any] = {"supported_features": int(features)}
    if position is not None:
        attributes["current_position"] = position
    hass.states.async_set(entity_id, state, attributes)


def new_entry(
    data: dict[str, Any] | None = None,
    subentries: list[dict[str, Any]] | None = None,
) -> MockConfigEntry:
    """Return the house entry in the current stored layout."""
    return MockConfigEntry(
        domain=DOMAIN,
        title=ENTRY_TITLE,
        data={CONF_SETTINGS: {}} if data is None else data,
        version=CONFIG_VERSION,
        minor_version=CONFIG_MINOR_VERSION,
        subentries_data=subentries or [],
    )


def subentry_data(
    subentry_type: str, title: str, data: dict[str, Any], subentry_id: str
) -> dict[str, Any]:
    """Return a stored subentry as ``MockConfigEntry`` takes it."""
    return {
        "data": data,
        "subentry_id": subentry_id,
        "subentry_type": subentry_type,
        "title": title,
        "unique_id": None,
    }


async def setup_entry(
    hass: HomeAssistant,
    data: dict[str, Any] | None = None,
    subentries: list[dict[str, Any]] | None = None,
) -> MockConfigEntry:
    """Create the house entry and set it up."""
    entry = new_entry(data, subentries)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def schema_of(result: Mapping[str, Any]) -> dict[Any, Any]:
    """Return the fields of a form: marker to selector."""
    schema = result["data_schema"]
    assert schema is not None
    fields: dict[Any, Any] = schema.schema
    return fields


def schema_keys(result: Mapping[str, Any]) -> list[str]:
    """Return the top-level field names of a form."""
    return [str(marker) for marker in schema_of(result)]


def marker_of(result: Mapping[str, Any], key: str) -> Any:
    """Return the schema marker of a top-level field."""
    return next(m for m in schema_of(result) if str(m) == key)


def section_marker_of(result: Mapping[str, Any], section: str, key: str) -> Any:
    """Return the schema marker of a field inside a section."""
    inner = schema_of(result)[marker_of(result, section)].schema.schema
    return next(m for m in inner if str(m) == key)


def suggested_value(marker: Any) -> Any:
    """Return the suggested value of a field, or ``None``."""
    return (marker.description or {}).get("suggested_value")


async def start_subentry_flow(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    subentry_type: str,
    reconfigure: str | None = None,
) -> dict[str, Any]:
    """Start a subentry flow and return its first result."""
    result: Mapping[str, Any]
    if reconfigure is None:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, subentry_type), context={"source": SOURCE_USER}
        )
    else:
        result = await entry.start_subentry_reconfigure_flow(hass, reconfigure)
    return dict(result)


async def configure_subentry_flow(
    hass: HomeAssistant, result: Mapping[str, Any], user_input: dict[str, Any]
) -> dict[str, Any]:
    """Submit one step of a subentry flow."""
    assert result["type"] in (FlowResultType.FORM, FlowResultType.MENU), result
    following = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return dict(following)


async def submit_steps(
    hass: HomeAssistant, result: Mapping[str, Any], inputs: list[dict[str, Any]]
) -> dict[str, Any]:
    """Submit several steps of a subentry flow, one input per step."""
    following = dict(result)
    for user_input in inputs:
        following = await configure_subentry_flow(hass, following, user_input)
    return following


async def run_subentry_flow(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    subentry_type: str,
    inputs: list[dict[str, Any]],
    reconfigure: str | None = None,
) -> dict[str, Any]:
    """Start a subentry flow, feed it one input per step, return the last result."""
    result = await start_subentry_flow(hass, entry, subentry_type, reconfigure)
    for user_input in inputs:
        result = await configure_subentry_flow(hass, result, user_input)
    return result


def subentry_named(entry: MockConfigEntry, title: str) -> ConfigSubentry:
    """Return the subentry with the given title."""
    return next(s for s in entry.subentries.values() if s.title == title)


async def add_group(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    name: str,
    *steps: dict[str, Any],
) -> ConfigSubentry:
    """Add a group through its flow; ``steps`` are the inputs after the name."""
    result = await run_subentry_flow(
        hass, entry, SUBENTRY_GROUP, [{"name": name}, *steps]
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    return subentry_named(entry, name)


async def add_window(
    hass: HomeAssistant,
    entry: MockConfigEntry,
    name: str,
    covers: list[str],
    *steps: dict[str, Any],
    group_id: str | None = None,
) -> ConfigSubentry:
    """Add a window through its flow; ``steps`` are the inputs after the basics."""
    basics: dict[str, Any] = {"name": name, "covers": covers}
    if group_id is not None:
        basics["group_id"] = group_id
    result = await run_subentry_flow(hass, entry, SUBENTRY_WINDOW, [basics, *steps])
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    return subentry_named(entry, name)
