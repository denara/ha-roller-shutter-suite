"""How the forms behave in a browser: errors, buttons, counters, times.

The tests drive every flow the way the frontend does and look at what a user
would see:

- **No untranslated validation text.** Every value the core refuses, on every
  page of every flow, comes back as an error key that both languages
  translate. Home Assistant's own check of a selector never answers first:
  its text ("Value -100.0 is too small") is no translation key, and the
  frontend would show it as it is.
- **No whole number with ".0"** in a placeholder or an error text.
- **Next or Submit.** Every page but the last one says it is not the last
  step, so the frontend labels its button "Next".
- **Counted pages.** The pages of the kinds of day count "(1/3)", following
  the pages the flow really shows.
- **Times without seconds**, and a stored time with seconds still loads.
"""

import json
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite import features
from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    DOMAIN,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    SettingKind,
    resolve_window,
)
from custom_components.roller_shutter_suite.features.daily_routine import (
    DAILY_ROUTINE,
)
from custom_components.roller_shutter_suite.features.movement import MOVEMENT
from custom_components.roller_shutter_suite.flow import inheritance, steps
from custom_components.roller_shutter_suite.flow.model import (
    Catalog,
    FeatureForm,
    FieldForm,
    StepForm,
)
from tests.ha.helpers import (
    EXAMPLE_REGISTRY,
    ROUTINE_HOUSE,
    configure_subentry_flow,
    resolve_example,
    routine_inherit,
    schema_of,
    set_cover,
    setup_entry,
    subentry_data,
    suggested_value,
)

COVER = "cover.example_window"
NEW_COVER = "cover.example_door"
BELOW_ZERO = -100.0
INTEGRATION_DIR = (
    Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
)
LANGUAGES = ("en", "de")
WHOLE_WITH_FRACTION = re.compile(r"(?<![\d.])-?\d+\.0(?![\d])")
"""A whole number written with ".0", as ``float`` prints it: ``-100.0``."""


def _translations(language: str) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(
        (INTEGRATION_DIR / "translations" / f"{language}.json").read_text(
            encoding="utf-8"
        )
    )
    return content


def _flow_errors(language: str, flow: str) -> dict[str, str]:
    strings = _translations(language)
    node = strings["config"] if flow == "house" else strings["config_subentries"][flow]
    errors: dict[str, str] = node["error"]
    return errors


type Configure = Callable[[str, dict[str, Any]], Awaitable[Mapping[str, Any]]]


@dataclass(frozen=True)
class Walk:
    """One flow as the frontend walks it: the first result and how to go on."""

    flow: str
    """``house``, ``group`` or ``window``: where its translations live."""
    first: Mapping[str, Any]
    configure: Configure
    inputs: list[dict[str, Any]]
    """What a browser sends for every page when nothing is changed."""


async def _house_setup(hass: HomeAssistant) -> Walk:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    return Walk(
        "house",
        result,
        hass.config_entries.flow.async_configure,
        [{}, *ROUTINE_HOUSE],
    )


async def _entry(hass: HomeAssistant, **settings: Any) -> MockConfigEntry:
    set_cover(hass, COVER)
    set_cover(hass, NEW_COVER)
    return await setup_entry(
        hass,
        {CONF_SETTINGS: settings},
        [
            subentry_data(SUBENTRY_GROUP, "South", {CONF_SETTINGS: {}}, "g1"),
            subentry_data(
                SUBENTRY_WINDOW,
                "Kitchen",
                {"covers": [COVER], "dry_run": True, CONF_SETTINGS: {}},
                "w1",
            ),
        ],
    )


async def _subentry_walk(
    hass: HomeAssistant, entry: MockConfigEntry, flow: str, reconfigure: bool
) -> Walk:
    result: Mapping[str, Any]
    if reconfigure:
        result = await entry.start_subentry_reconfigure_flow(
            hass, "g1" if flow == SUBENTRY_GROUP else "w1"
        )
    else:
        result = await hass.config_entries.subentries.async_init(
            (entry.entry_id, flow), context={"source": SOURCE_USER}
        )
    basics: dict[str, Any] = {"name": "South" if flow == SUBENTRY_GROUP else "Kitchen"}
    if flow == SUBENTRY_WINDOW:
        # A new window takes a cover that no other window has.
        basics["covers"] = [COVER if reconfigure else NEW_COVER]
    return Walk(
        flow,
        result,
        hass.config_entries.subentries.async_configure,
        [basics, *routine_inherit()],
    )


WALKS = [
    "house setup",
    "house reconfigure",
    "group setup",
    "group reconfigure",
    "window setup",
    "window reconfigure",
]


async def _walk(hass: HomeAssistant, name: str) -> Walk:
    if name == "house setup":
        return await _house_setup(hass)
    entry = await _entry(hass)
    if name == "house reconfigure":
        result = await entry.start_reconfigure_flow(hass)
        return Walk(
            "house", result, hass.config_entries.flow.async_configure, ROUTINE_HOUSE
        )
    flow, _, how = name.partition(" ")
    return await _subentry_walk(hass, entry, flow, how == "reconfigure")


async def _submit(walk: Walk, result: Mapping[str, Any], data: dict[str, Any]) -> Any:
    """Submit a page; fail when Home Assistant's schema check answers first."""
    try:
        return await walk.configure(result["flow_id"], data)
    except InvalidData as err:
        pytest.fail(f"the schema refused the input by itself: {err.schema_errors}")


def _assert_nothing_is_written_with_a_fraction(result: Mapping[str, Any]) -> None:
    for name, value in (result.get("description_placeholders") or {}).items():
        assert not WHOLE_WITH_FRACTION.search(value), (result["step_id"], name, value)


# --- Next or Submit, and the counter of the pages ---------------------------------


@pytest.mark.parametrize("name", WALKS)
async def test_every_page_but_the_last_says_next(
    hass: HomeAssistant, name: str
) -> None:
    """The frontend labels the button "Next" unless the page is the last step."""
    walk = await _walk(hass, name)
    result = walk.first
    seen: list[tuple[str, bool | None]] = []
    counters: dict[str, tuple[str, str]] = {}
    for data in walk.inputs:
        assert result["type"] is FlowResultType.FORM, result
        seen.append((result["step_id"], result["last_step"]))
        placeholders = result["description_placeholders"] or {}
        if steps.PLACEHOLDER_PAGE_NUMBER in placeholders:
            counters[result["step_id"]] = (
                placeholders[steps.PLACEHOLDER_PAGE_NUMBER],
                placeholders[steps.PLACEHOLDER_PAGE_COUNT],
            )
        _assert_nothing_is_written_with_a_fraction(result)
        result = await _submit(walk, result, data)

    assert result["type"] in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT)
    assert [last for _, last in seen] == [False] * (len(seen) - 1) + [True]
    assert seen[-1][0] == "feature_movement_general"
    assert counters == {
        "feature_daily_routine_workday": ("1", "3"),
        "feature_daily_routine_weekend": ("2", "3"),
        "feature_daily_routine_holiday": ("3", "3"),
    }


@pytest.mark.parametrize("language", LANGUAGES)
def test_title_of_a_kind_of_day_carries_the_counter(language: str) -> None:
    """The title is a translated text; only the two numbers are placeholders."""
    for level in ("config", "group", "window"):
        strings = _translations(language)
        node = (
            strings["config"]
            if level == "config"
            else strings["config_subentries"][level]
        )
        title = node["step"]["feature_daily_routine_workday"]["title"]
        rendered = title.format(page_number="1", page_count="3")
        assert rendered.endswith("(1/3)"), rendered
        assert rendered.startswith(
            {"en": "Daily routine: workdays", "de": "Tagesablauf: Werktage"}[language]
        )


def _routine_with(*day_types: str) -> Catalog:
    """Return the catalog with only some of the pages of the kinds of day."""
    general, *days = DAILY_ROUTINE.steps
    kept = tuple(step for step in days if step.name in day_types)
    return Catalog(
        registry=WINDOW_SETTINGS,
        features=(
            FeatureForm(
                DAILY_ROUTINE.feature_id, (general, *kept), DAILY_ROUTINE.switch
            ),
            MOVEMENT,
        ),
        resolve=resolve_window,
    )


@pytest.mark.parametrize(
    ("day_types", "expected"),
    [
        (("workday",), {"workday": ("1", "1")}),
        (("weekend", "holiday"), {"weekend": ("1", "2"), "holiday": ("2", "2")}),
        (
            ("workday", "weekend", "holiday"),
            {"workday": ("1", "3"), "weekend": ("2", "3"), "holiday": ("3", "3")},
        ),
    ],
    ids=["one kind of day", "two kinds of day", "three kinds of day"],
)
async def test_counter_follows_the_pages_of_the_kinds_of_day_that_are_shown(
    hass: HomeAssistant,
    monkeypatch: pytest.MonkeyPatch,
    day_types: tuple[str, ...],
    expected: dict[str, tuple[str, str]],
) -> None:
    """One, two or three kinds of day: the count is that of the pages shown."""
    monkeypatch.setattr(features, "CATALOG", _routine_with(*day_types))
    walk = await _house_setup(hass)
    general_house, *day_pages = ROUTINE_HOUSE[1:-1]
    inputs = [
        {},
        ROUTINE_HOUSE[0],
        general_house,
        *day_pages[: len(day_types)],
        ROUTINE_HOUSE[-1],
    ]
    result = walk.first
    counters: dict[str, tuple[str, str]] = {}
    for data in inputs:
        placeholders = result["description_placeholders"] or {}
        if steps.PLACEHOLDER_PAGE_NUMBER in placeholders:
            day_type = result["step_id"].removeprefix("feature_daily_routine_")
            counters[day_type] = (
                placeholders[steps.PLACEHOLDER_PAGE_NUMBER],
                placeholders[steps.PLACEHOLDER_PAGE_COUNT],
            )
        result = await _submit(walk, result, data)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert counters == expected


async def test_switches_are_the_last_page_when_no_page_can_follow(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A group cannot set what only a window sets, so no page follows the switches."""
    only_window = Catalog(
        registry=EXAMPLE_REGISTRY,
        features=(
            FeatureForm(
                DAILY_ROUTINE.feature_id,
                (StepForm("general", (FieldForm("example_window_only"),)),),
                DAILY_ROUTINE.switch,
            ),
        ),
        resolve=resolve_example,
    )
    monkeypatch.setattr(features, "CATALOG", only_window)
    entry = await _entry(hass)
    walk = await _subentry_walk(hass, entry, SUBENTRY_GROUP, reconfigure=False)

    result = await _submit(walk, walk.first, walk.inputs[0])
    assert result["step_id"] == "features"
    assert result["last_step"] is True
    result = await _submit(walk, result, {"schedule_enabled": "inherit_on"})
    assert result["type"] is FlowResultType.CREATE_ENTRY


# --- No untranslated validation text -----------------------------------------------


def _number_fields(page: StepForm) -> list[FieldForm]:
    definitions = features.CATALOG.definitions
    return [
        item
        for item in page.fields
        if definitions[item.key].kind in (SettingKind.NUMBER, SettingKind.DURATION)
    ]


def _outside_the_range(page: StepForm) -> list[tuple[FieldForm, float]]:
    """Return one value below and one above the range of every number field."""
    values: list[tuple[FieldForm, float]] = []
    for item in _number_fields(page):
        bounds = features.CATALOG.number_bounds(item)
        if bounds.minimum is not None:
            values.append((item, float(bounds.minimum) - 1))
        if bounds.maximum is not None:
            values.append((item, float(bounds.maximum) + 1))
    return values


_REFUSED: dict[str, list[tuple[str, Any]]] = {
    # Every other kind of refusal the core can produce, page by page.
    "feature_daily_routine_general": [
        ("schedule_morning_position", 50.5),  # a fraction of a whole number
        ("schedule_morning_position", "fifty"),  # no number at all
        ("schedule_brightness_threshold_lux", float("inf")),  # not finite
        ("schedule_brightness_delay", 600_000.0),  # longer than any duration
        ("schedule_random_offset", 0.5),  # a fraction of a minute
        ("schedule_summer_first_day", "13-01"),  # no day of the year
        ("schedule_summer_last_day", "02-29"),  # not in every year
        ("schedule_season_source_choice", "own"),  # own selection, no entity
    ],
    "feature_daily_routine_workday": [
        ("schedule_workday_morning_time", "25:00"),  # no time of day
        ("schedule_workday_morning_time", "7:30"),  # not "HH:MM"
        ("schedule_workday_morning_time", "21:00"),  # after the earliest evening
        ("schedule_workday_evening_offset_minutes", 12.5),
    ],
    "feature_daily_routine_weekend": [
        ("schedule_weekend_evening_not_before", "17:00:00.5")
    ],
    "feature_daily_routine_holiday": [
        ("schedule_holiday_morning_offset_minutes", "early")
    ],
    "feature_movement_general": [
        ("motor_min_change", 5.5),
        ("stagger_gap", 1.5),
        ("reevaluate_after", 0.5),
    ],
}


def _page(step_id: str) -> StepForm | None:
    return features.CATALOG.step(step_id)


def _changed(page: StepForm, base: dict[str, Any], name: str, value: Any) -> Any:
    """Return the input of the page with one field changed, inside its section."""
    data = {key: dict(item) if key == "expert" else item for key, item in base.items()}
    expert = {item.name for item in page.fields if item.expert}
    if name in expert:
        data.setdefault(inheritance.SECTION_EXPERT, {})[name] = value
    else:
        data[name] = value
    return data


def _refusals(step_id: str, page: StepForm) -> list[tuple[str, Any]]:
    outside = [(item.name, value) for item, value in _outside_the_range(page)]
    return outside + _REFUSED[step_id]


@pytest.mark.parametrize("name", WALKS)
async def test_no_untranslated_validation_text_reaches_the_user(
    hass: HomeAssistant, name: str
) -> None:
    """Every refusal on every page is an error key that both languages translate.

    Each page gets every value the core refuses there, one at a time: below
    and above the range of every number field, a fraction where the setting
    takes whole numbers, no number, a number that is not finite, a duration
    longer than the core takes, a day that is no day of the year or not in
    every year, a time of day that is none, an own selection without an
    entity, and a combination the core refuses. The page has to come back
    with errors, and every error has to be a key with a text in both
    languages, without a whole number written with ".0".
    """
    walk = await _walk(hass, name)
    errors_by_language = {
        language: _flow_errors(language, walk.flow) for language in LANGUAGES
    }
    result = walk.first
    refused = 0
    for data in walk.inputs:
        page = _page(result["step_id"])
        refusals = [] if page is None else _refusals(result["step_id"], page)
        for field_name, value in refusals:
            assert page is not None
            answer = await _submit(
                walk, result, _changed(page, data, field_name, value)
            )
            assert answer["type"] is FlowResultType.FORM, (field_name, value)
            assert answer["step_id"] == result["step_id"], (field_name, value)
            assert answer["errors"], (field_name, value)
            for where, error in answer["errors"].items():
                assert where == "base" or where in {
                    str(marker) for marker in schema_of(answer)
                }, (field_name, where)
                for language, known in errors_by_language.items():
                    text = known.get(error)
                    assert text, (language, field_name, error)
                    assert not WHOLE_WITH_FRACTION.search(text), (language, text)
            _assert_nothing_is_written_with_a_fraction(answer)
            refused += 1
        result = await _submit(walk, result, data)

    assert result["type"] in (FlowResultType.CREATE_ENTRY, FlowResultType.ABORT)
    assert refused > 40  # noqa: PLR2004 - every page had its share


async def test_value_below_the_range_is_refused_before_anything_is_stored(
    hass: HomeAssistant,
) -> None:
    """The finding of the review: -100 and 200 as positions of the house."""
    walk = await _house_setup(hass)
    result = await _submit(walk, walk.first, {})
    result = await _submit(walk, result, ROUTINE_HOUSE[0])

    result = await _submit(
        walk,
        result,
        ROUTINE_HOUSE[1]
        | {"schedule_morning_position": -100, "schedule_evening_position": 200.0},
    )

    assert result["errors"] == {
        "schedule_morning_position": "out_of_range_schedule_morning_position",
        "schedule_evening_position": "out_of_range_schedule_evening_position",
    }
    texts = {language: _flow_errors(language, "house") for language in LANGUAGES}
    assert texts["en"]["out_of_range_schedule_morning_position"] == (
        "Enter a value from 0 to 100 %."
    )
    assert texts["de"]["out_of_range_schedule_morning_position"] == (
        "Gib einen Wert von 0 bis 100 % ein."
    )
    assert hass.config_entries.async_entries(DOMAIN) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_no_error_text_writes_a_whole_number_with_a_fraction(language: str) -> None:
    """The texts are written from the ranges of the registry, never as ``100.0``."""
    strings = _translations(language)
    flows = [strings["config"], *strings["config_subentries"].values()]
    texts = [text for flow in flows for text in flow.get("error", {}).values()]

    assert any("out_of_range" not in text for text in texts)
    for text in texts:
        assert not WHOLE_WITH_FRACTION.search(text), text


def test_number_box_hands_every_value_on_and_keeps_its_bounds() -> None:
    """The box judges nothing, so Home Assistant's own text never answers first."""
    item = next(
        item
        for item in DAILY_ROUTINE.steps[0].fields
        if item.key == "schedule_morning_position"
    )
    box = inheritance._number_selector(features.CATALOG, item)  # noqa: SLF001

    assert box.serialize() == {
        "selector": {
            "number": {
                "min": 0,
                "max": 100,
                "step": 1,
                "mode": "box",
                "unit_of_measurement": "%",
            }
        }
    }
    assert box(BELOW_ZERO) == BELOW_ZERO
    assert box("fifty") == "fifty"


# --- Times without seconds ---------------------------------------------------------


def test_every_time_of_day_is_entered_without_seconds() -> None:
    """The frontend reads ``no_second`` from the configuration of the selector."""
    definitions = features.CATALOG.definitions
    times = [
        item
        for feature in features.CATALOG.features
        for item in feature.fields
        if definitions[item.key].kind is SettingKind.TIME
    ]

    assert len(times) == 18  # noqa: PLR2004 - three per edge of each kind of day
    field = inheritance.TimeOfDay()
    assert field.serialize() == {"selector": {"time": {"no_second": True}}}
    assert field("25:00") == "25:00"


async def test_every_time_field_of_the_forms_uses_the_field_without_seconds(
    hass: HomeAssistant,
) -> None:
    """On a page of a kind of day, in sight and in the section."""
    walk = await _walk(hass, "window setup")
    result = walk.first
    for data in walk.inputs[:3]:
        result = await _submit(walk, result, data)
    assert result["step_id"] == "feature_daily_routine_workday"

    schema = schema_of(result)
    expert = schema["expert"].schema.schema
    assert isinstance(schema["schedule_workday_morning_time"], inheritance.TimeOfDay)
    assert isinstance(
        expert["schedule_workday_evening_not_before"], inheritance.TimeOfDay
    )


async def test_stored_time_with_seconds_still_loads_and_is_kept(
    hass: HomeAssistant,
) -> None:
    """``HH:MM:SS`` stays readable: shown as it is, kept when the page is saved."""
    entry = await _entry(hass, schedule_workday_morning_time="06:45:30")
    walk = await _subentry_walk(hass, entry, SUBENTRY_WINDOW, reconfigure=True)
    result = walk.first
    for data in walk.inputs[:3]:
        result = await _submit(walk, result, data)
    assert result["step_id"] == "feature_daily_routine_workday"
    # The window inherits the time of the house, with its seconds.
    placeholders = result["description_placeholders"]
    assert placeholders["schedule_workday_morning_time_inherited"] == "06:45:30"

    # The window sets a time with seconds of its own; it loads as the own value.
    result = await configure_subentry_flow(
        hass,
        result,
        walk.inputs[3] | {"schedule_workday_morning_time": "06:50:15"},
    )
    for data in walk.inputs[4:]:
        result = await _submit(walk, result, data)
    await hass.async_block_till_done()
    window = entry.subentries["w1"]
    assert window.data[CONF_SETTINGS]["schedule_workday_morning_time"] == "06:50:15"

    walk = await _subentry_walk(hass, entry, SUBENTRY_WINDOW, reconfigure=True)
    result = walk.first
    for data in walk.inputs[:3]:
        result = await _submit(walk, result, data)
    marker = next(
        marker
        for marker in schema_of(result)
        if str(marker) == "schedule_workday_morning_time"
    )
    assert suggested_value(marker) == "06:50:15"
    # Saved unchanged, the time keeps its seconds; without them it is kept too.
    result = await _submit(
        walk, result, walk.inputs[3] | {"schedule_workday_morning_time": "06:50:15"}
    )
    for data in walk.inputs[4:]:
        result = await _submit(walk, result, data)
    await hass.async_block_till_done()
    window = entry.subentries["w1"]
    assert window.data[CONF_SETTINGS]["schedule_workday_morning_time"] == "06:50:15"
