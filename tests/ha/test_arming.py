"""Arming a window (E11): the page "dry-run or armed" and the page of the checks.

A window is armed only through its reconfigure flow: the last page offers
dry-run or armed, and the step from dry-run to armed leads to a page that
repeats the checks of section 8 of the pilot guide and saves only when every
one is confirmed. Going back to dry-run needs no confirmation. The controller
starts the armed window with a clean state (``Engine.arm``): nothing it would
have sent in dry-run counts, and no dam is armed.
"""

import json
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.selector import BooleanSelector, SelectSelector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite.const import CONF_DRY_RUN, SUBENTRY_WINDOW
from custom_components.roller_shutter_suite.core.model import (
    ManualOverrideDam,
    OverrideEndRule,
)
from custom_components.roller_shutter_suite.flow.window_flow import ARMING_CHECKS
from tests.ha.helpers import (
    KEEP_ARMED,
    KEEP_DRY_RUN,
    configure_subentry_flow,
    marker_of,
    routine_inherit,
    run_subentry_flow,
    schema_keys,
    schema_of,
    submit_steps,
)
from tests.ha.runtime_kit import (
    COVER,
    WINDOW_ID,
    controller_of,
    cover_calls,
    monday_morning,
    settle,
    setup_window,
    window_data,
)
from tests.ha.status_kit import DRY_RUN, state_of

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

ROOT = Path(__file__).parents[2]
BASICS = {"name": "Example window", "covers": [COVER]}
ALL_CHECKS = dict.fromkeys(ARMING_CHECKS, True)


async def _to_the_last_page(
    hass: HomeAssistant, entry: MockConfigEntry
) -> dict[str, Any]:
    """Walk the reconfigure flow of the window up to the page "dry-run or armed"."""
    result = await run_subentry_flow(
        hass, entry, SUBENTRY_WINDOW, [BASICS, *routine_inherit()], WINDOW_ID
    )
    assert result["step_id"] == "operation", result
    return result


async def _window_in_dry_run(hass: HomeAssistant, freezer: Any) -> MockConfigEntry:
    """Return the entry with the window in dry-run, half open while the day wants 100."""
    entry = await setup_window(hass, window_data(dry_run=True), freezer=freezer)
    hass.states.async_set(
        COVER, "open", {"supported_features": 15, "current_position": 50}
    )
    await settle(hass, freezer)
    return entry


async def test_the_step_from_dry_run_to_armed_asks_for_every_check(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Dry-run first; "armed" leads to the checks; an unchecked point saves nothing."""
    entry = await _window_in_dry_run(hass, freezer)

    result = await _to_the_last_page(hass, entry)
    assert marker_of(result, "operation").default() == "dry_run"
    selector = schema_of(result)["operation"]
    assert isinstance(selector, SelectSelector)
    assert selector.config["options"] == ["dry_run", "armed"]
    assert selector.config["translation_key"] == "operation"
    assert result["last_step"] is False

    result = await configure_subentry_flow(hass, result, KEEP_ARMED)
    assert result["step_id"] == "arm"
    assert result["last_step"] is True
    assert schema_keys(result) == list(ARMING_CHECKS)
    for check in ARMING_CHECKS:
        assert isinstance(schema_of(result)[check], BooleanSelector)
        assert marker_of(result, check).default() is False

    for missing in ARMING_CHECKS:
        answer = await configure_subentry_flow(
            hass, result, ALL_CHECKS | {missing: False}
        )
        assert answer["type"] is FlowResultType.FORM
        assert answer["errors"] == {"base": "confirm_every_check"}
        assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True
        result = answer

    result = await configure_subentry_flow(hass, result, ALL_CHECKS)
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is False


async def test_arming_through_the_form_starts_the_window_clean_and_it_moves(
    hass: HomeAssistant, freezer: Any
) -> None:
    """What dry-run simulated, and a dam, are gone; the next decision is sent."""
    entry = await _window_in_dry_run(hass, freezer)
    controller = controller_of(entry)
    assert controller.state.simulated is not None
    assert cover_calls(hass) == []
    assert state_of(hass, DRY_RUN).state == STATE_ON
    # A dam as a later block would arm it: arming must clear it too. The
    # controller saves its state when the reload stops it.
    controller.state = replace(
        controller.state,
        manual_override=ManualOverrideDam(
            armed_at=controller.clock.now(), end_rule=OverrideEndRule.NEXT_PART_OF_DAY
        ),
    )

    result = await _to_the_last_page(hass, entry)
    result = await submit_steps(hass, result, [KEEP_ARMED, ALL_CHECKS])
    assert result["reason"] == "reconfigure_successful"
    await settle(hass, freezer)

    armed = controller_of(entry)
    assert armed is not controller
    assert armed.state.simulated is None
    assert armed.state.manual_override is None
    assert state_of(hass, DRY_RUN).state == STATE_OFF
    assert [call.target.value for call in cover_calls(hass)] == [100]


async def test_going_back_to_dry_run_needs_no_confirmation(
    hass: HomeAssistant, freezer: Any
) -> None:
    """An armed window offers "armed"; "dry-run" saves at once, nothing moves any more."""
    entry = await setup_window(hass, freezer=freezer)
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is False

    result = await _to_the_last_page(hass, entry)
    assert marker_of(result, "operation").default() == "armed"
    assert result["last_step"] is True
    result = await configure_subentry_flow(hass, result, KEEP_DRY_RUN)

    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True
    await settle(hass, freezer)
    assert state_of(hass, DRY_RUN).state == STATE_ON
    calls = len(cover_calls(hass))
    hass.states.async_set(
        COVER, "open", {"supported_features": 15, "current_position": 50}
    )
    await settle(hass, freezer, seconds=timedelta(minutes=20).total_seconds())
    assert len(cover_calls(hass)) == calls


async def test_the_window_removed_on_the_last_pages_saves_nothing(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Removed while "dry-run or armed" or the checks are open: the flow ends."""
    entry = await _window_in_dry_run(hass, freezer)
    first = await _to_the_last_page(hass, entry)
    second = await _to_the_last_page(hass, entry)
    second = await configure_subentry_flow(hass, second, KEEP_ARMED)
    assert second["step_id"] == "arm"

    assert hass.config_entries.async_remove_subentry(entry, WINDOW_ID)
    await hass.async_block_till_done()

    result = await configure_subentry_flow(hass, first, KEEP_ARMED)
    assert result["reason"] == "subentry_removed"
    result = await configure_subentry_flow(hass, second, ALL_CHECKS)
    assert result["reason"] == "subentry_removed"


# ---------------------------------------------------------------------------
# The checks of the page and the checklist of the pilot guide
# ---------------------------------------------------------------------------


def _section_8() -> str:
    text = (ROOT / "docs" / "pilot.md").read_text(encoding="utf-8")
    start = text.index("\n## 8.")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_the_page_names_the_checks_of_the_pilot_guide_in_their_order() -> None:
    """Every point of the page is an item of section 8, in the same order.

    Section 8 marks the items that the page repeats with an invisible
    comment ``<!-- check: <key> -->``; the list has more items than the
    page, and the page has none that the list lacks.
    """
    marked = re.findall(r"<!-- check: ([a-z_]+) -->", _section_8())

    assert marked == list(ARMING_CHECKS)


@pytest.mark.parametrize("language", ["en", "de"])
def test_every_check_has_its_text(language: str) -> None:
    """Both languages name every check of the page."""
    strings = json.loads(
        (
            ROOT
            / "custom_components"
            / "roller_shutter_suite"
            / "translations"
            / f"{language}.json"
        ).read_text(encoding="utf-8")
    )
    page = strings["config_subentries"]["window"]["step"]["arm"]
    assert set(page["data"]) == set(ARMING_CHECKS)
    assert all(page["data"].values())
    options = strings["selector"]["operation"]["options"]
    assert set(options) == {"dry_run", "armed"}
