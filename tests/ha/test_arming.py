"""Arming a window (E11): the page "dry-run or armed" and the page of the checks.

A window is armed only through its reconfigure flow: the last page offers
dry-run or armed, and the step from dry-run to armed leads to a page that
repeats the checks of section 8 of the pilot guide and saves only when every
one is confirmed. Going back to dry-run needs no confirmation. The controller
starts the armed window with a clean state (``Engine.arm``): nothing it would
have sent in dry-run counts, and no dam is armed.

Facts refuse arming whatever is ticked. The reporting of every cover is one
(rulings of the project owner, 2026-09-29 and 2026-10-01): each must be
stated on its page as event-driven with a known reporting time; a polled
cover, or one whose reporting is not stated, refuses and is named, while a
reporting time above zero does not refuse. The guard of maintenance item X10
is the other: ``MOVEMENT_DETECTION_WIRED`` ships true since block H10, and
the fixture ``no_movement_detection`` proves that the guard still holds when
it is false. The same facts hold in operation: a window stored as armed runs
in dry-run with a repair issue while one of them refuses.
"""

import json
import re
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from homeassistant.config_entries import ConfigEntry, ConfigSubentry
from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.selector import BooleanSelector, SelectSelector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.roller_shutter_suite import const
from custom_components.roller_shutter_suite.const import (
    CONF_DRY_RUN,
    DOMAIN,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.core.model import (
    ManualOverrideDam,
    OverrideEndRule,
)
from custom_components.roller_shutter_suite.flow.window_flow import ARMING_CHECKS
from tests.ha.helpers import (
    KEEP_ARMED,
    KEEP_DRY_RUN,
    MEMBER_PAGE,
    configure_subentry_flow,
    marker_of,
    page_as_shown,
    routine_inherit,
    run_subentry_flow,
    schema_keys,
    schema_of,
    start_subentry_flow,
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


@pytest.fixture
def saved_dry_run(hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    """Record the value of dry-run of every window that is added or updated."""
    saved: list[bool] = []
    entries = hass.config_entries
    add, update = entries.async_add_subentry, entries.async_update_subentry

    def adding(entry: ConfigEntry, subentry: ConfigSubentry) -> bool:
        if subentry.subentry_type == SUBENTRY_WINDOW:
            saved.append(subentry.data[CONF_DRY_RUN])
        return add(entry, subentry)

    def updating(entry: ConfigEntry, subentry: ConfigSubentry, **changes: Any) -> bool:
        if subentry.subentry_type == SUBENTRY_WINDOW and "data" in changes:
            saved.append(changes["data"][CONF_DRY_RUN])
        return update(entry, subentry, **changes)

    monkeypatch.setattr(entries, "async_add_subentry", adding)
    monkeypatch.setattr(entries, "async_update_subentry", updating)
    return saved


async def _to_the_last_page(
    hass: HomeAssistant, entry: MockConfigEntry, member: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Walk the reconfigure flow of the window up to the page "dry-run or armed".

    ``member`` changes the page of the cover, where ``None`` empties a field;
    without it the page is left as it is shown, with what the cover states.
    """
    inputs = [BASICS, *routine_inherit()]
    if member is not None:
        result = await start_subentry_flow(hass, entry, SUBENTRY_WINDOW, WINDOW_ID)
        for user_input in inputs:
            result = await configure_subentry_flow(hass, result, user_input)
        assert result["step_id"] == MEMBER_PAGE, result
        changed = page_as_shown(result) | member
        result = await configure_subentry_flow(
            hass, result, {k: v for k, v in changed.items() if v is not None}
        )
    else:
        result = await run_subentry_flow(
            hass, entry, SUBENTRY_WINDOW, inputs, WINDOW_ID
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
    """Dry-run first; "armed" leads to the checks; an unchecked point saves nothing.

    The checkbox "reports at once" of X10 is gone: the page of each cover
    states it, and the page of the checks reads it.
    """
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
    assert result["errors"] == {}
    assert "reports_at_once" not in ARMING_CHECKS
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


@pytest.mark.usefixtures("no_movement_detection")
async def test_going_back_to_dry_run_needs_no_confirmation(
    hass: HomeAssistant, freezer: Any
) -> None:
    """An armed window offers "armed"; "dry-run" saves at once, nothing moves any more.

    This runs as the version ships: a window armed by an older version, or by
    a test, can always go back, although this version refuses to arm.
    """
    entry = await setup_window(hass, freezer=freezer)
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is False

    result = await _to_the_last_page(hass, entry)
    assert marker_of(result, "operation").default() == "armed"
    # "Armed" would lead to the page of the checks, which refuses.
    assert result["last_step"] is False
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
# What refuses arming whatever is ticked (maintenance item X10)
# ---------------------------------------------------------------------------


def test_this_version_notices_a_movement_by_hand() -> None:
    """The flag ships true since block H10, which feeds the tracker from the runtime."""
    assert const.MOVEMENT_DETECTION_WIRED is True


@pytest.mark.usefixtures("no_movement_detection")
async def test_the_page_of_the_checks_says_why_and_arms_nothing(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The reason shows when the page opens; no combination of ticks saves."""
    entry = await _window_in_dry_run(hass, freezer)

    result = await _to_the_last_page(hass, entry)
    result = await configure_subentry_flow(hass, result, KEEP_ARMED)
    assert result["step_id"] == "arm"
    assert result["errors"] == {"base": "no_movement_detection"}
    assert schema_keys(result) == list(ARMING_CHECKS)

    for answer in (ALL_CHECKS, {}, ALL_CHECKS | {"way_back": False}):
        result = await configure_subentry_flow(hass, result, answer)
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "arm"
        assert result["errors"] == {"base": "no_movement_detection"}
        assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True
    await settle(hass, freezer)
    assert cover_calls(hass) == []
    assert state_of(hass, DRY_RUN).state == STATE_ON


@pytest.mark.usefixtures("no_movement_detection")
async def test_no_path_of_the_window_flow_writes_armed(
    hass: HomeAssistant, freezer: Any, saved_dry_run: list[bool]
) -> None:
    """Every save of every path writes dry-run: new, kept, refused, went back.

    An armed window cannot stay armed through the form either: "armed" leads
    it to the same page, which refuses, so the form never confirms a state
    this version cannot arm.
    """
    entry = await _window_in_dry_run(hass, freezer)
    hass.states.async_set(
        "cover.example_other",
        "open",
        {"supported_features": 15, "current_position": 100},
    )
    created = await run_subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Other window", "covers": ["cover.example_other"]},
            *routine_inherit(),
        ],
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY

    for choice in (KEEP_DRY_RUN, KEEP_ARMED):
        result = await _to_the_last_page(hass, entry)
        result = await configure_subentry_flow(hass, result, choice)
        if choice is KEEP_ARMED:
            result = await configure_subentry_flow(hass, result, ALL_CHECKS)
            assert result["errors"] == {"base": "no_movement_detection"}
        assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True
    # The new window and the choice "dry-run"; the refused page saved nothing.
    assert saved_dry_run == [True, True]

    # A window armed before this version refused: it cannot stay armed.
    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries[WINDOW_ID],
        data={**entry.subentries[WINDOW_ID].data, CONF_DRY_RUN: False},
    )
    await settle(hass, freezer)
    saved_dry_run.clear()
    result = await _to_the_last_page(hass, entry)
    assert result["last_step"] is False
    result = await configure_subentry_flow(hass, result, KEEP_ARMED)
    assert result["step_id"] == "arm"
    result = await configure_subentry_flow(hass, result, ALL_CHECKS)
    assert result["errors"] == {"base": "no_movement_detection"}
    result = await _to_the_last_page(hass, entry)
    result = await configure_subentry_flow(hass, result, KEEP_DRY_RUN)
    assert result["reason"] == "reconfigure_successful"
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True

    assert saved_dry_run == [True]


POLLED = {"reporting_kind": "polled", "reporting_time": 60}
NOT_STATED = {"reporting_kind": "not_stated"}
TIME_NOT_STATED = {"reporting_kind": "event_driven", "reporting_time": None}
DELAYED = {"reporting_kind": "event_driven", "reporting_time": 45}


@pytest.mark.parametrize(
    ("member", "error"),
    [
        (POLLED, "reporting_polled"),
        (NOT_STATED, "reporting_not_stated"),
        (TIME_NOT_STATED, "reporting_not_stated"),
    ],
    ids=["polled", "kind-not-stated", "time-not-stated"],
)
async def test_a_polled_or_unstated_cover_refuses_arming_by_name(
    hass: HomeAssistant, freezer: Any, member: dict[str, Any], error: str
) -> None:
    """The fact of the page of the cover refuses, names the cover, keeps an armed window.

    No tick outweighs it, not for a window in dry-run and not for one that is
    armed already and would stay armed (rulings of the project owner,
    2026-09-29 and 2026-10-01).
    """
    entry = await _window_in_dry_run(hass, freezer)

    result = await _to_the_last_page(hass, entry, member)
    result = await configure_subentry_flow(hass, result, KEEP_ARMED)
    assert result["errors"] == {"base": error}
    assert result["description_placeholders"] == {"covers": COVER}
    result = await configure_subentry_flow(hass, result, ALL_CHECKS)
    assert result["errors"] == {"base": error}
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True

    hass.config_entries.async_update_subentry(
        entry,
        entry.subentries[WINDOW_ID],
        data={**entry.subentries[WINDOW_ID].data, CONF_DRY_RUN: False},
    )
    await settle(hass, freezer)
    result = await _to_the_last_page(hass, entry, member)
    assert result["last_step"] is False
    result = await configure_subentry_flow(hass, result, KEEP_ARMED)
    assert result["errors"] == {"base": error}


async def test_a_reporting_time_above_zero_does_not_refuse_arming(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A delay is normal and enters the deadline; polling is what refuses."""
    entry = await _window_in_dry_run(hass, freezer)

    result = await _to_the_last_page(hass, entry, DELAYED)
    result = await submit_steps(hass, result, [KEEP_ARMED, ALL_CHECKS])

    assert result["reason"] == "reconfigure_successful"
    stored = entry.subentries[WINDOW_ID].data
    assert stored[CONF_DRY_RUN] is False
    assert stored["members"] == {COVER: DELAYED}
    await settle(hass, freezer)
    member = controller_of(entry).config.members[0]
    assert member.capabilities.reporting_time == timedelta(seconds=45)
    assert [call.target.value for call in cover_calls(hass)] == [100]


# ---------------------------------------------------------------------------
# The same fact in operation: a window stored as armed
# ---------------------------------------------------------------------------

ARMED_ISSUE = f"armed_without_movement_detection_{WINDOW_ID}"


def _issue_ids(hass: HomeAssistant) -> set[str]:
    return {
        issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN
    }


async def _window_stored_as_armed(hass: HomeAssistant, freezer: Any) -> MockConfigEntry:
    """Return the entry with the window stored as armed, half open in the day."""
    hass.states.async_set(
        COVER, "open", {"supported_features": 15, "current_position": 50}
    )
    return await setup_window(
        hass, window_data(dry_run=False), covers_present=False, freezer=freezer
    )


@pytest.mark.usefixtures("no_movement_detection")
async def test_a_window_stored_as_armed_runs_in_dry_run_with_an_issue(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Stored as armed (a downgrade, a test): it moves nothing and says why.

    The stored data is left as it is. Setting the window to dry-run in its
    form removes the issue.
    """
    entry = await _window_stored_as_armed(hass, freezer)

    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is False
    assert entry.runtime_data.windows[WINDOW_ID].dry_run is True
    assert cover_calls(hass) == []
    assert state_of(hass, DRY_RUN).state == STATE_ON
    assert controller_of(entry).state.simulated is not None
    assert _issue_ids(hass) == {ARMED_ISSUE}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, ARMED_ISSUE)
    assert issue is not None
    assert issue.translation_key == "armed_without_movement_detection"
    assert issue.translation_placeholders == {"window": "Example window"}

    result = await _to_the_last_page(hass, entry)
    result = await configure_subentry_flow(hass, result, KEEP_DRY_RUN)
    assert result["reason"] == "reconfigure_successful"
    await settle(hass, freezer)
    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is True
    assert _issue_ids(hass) == set()
    assert cover_calls(hass) == []


async def test_a_stored_armed_window_moves_and_raises_no_issue(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Movements by hand are noticed and its cover is event-driven: armed, no issue."""
    entry = await _window_stored_as_armed(hass, freezer)

    assert entry.runtime_data.windows[WINDOW_ID].dry_run is False
    assert state_of(hass, DRY_RUN).state == STATE_OFF
    assert [call.target.value for call in cover_calls(hass)] == [100]
    assert _issue_ids(hass) == set()


REPORTING_ISSUE = f"armed_without_reporting_{WINDOW_ID}"


@pytest.mark.parametrize(
    "members",
    [{}, {COVER: {"reporting_kind": "event_driven"}}, {COVER: POLLED}],
    ids=["nothing-stated", "time-not-stated", "polled"],
)
async def test_a_stored_armed_window_with_a_cover_it_cannot_trust_runs_in_dry_run(
    hass: HomeAssistant, freezer: Any, members: dict[str, Any]
) -> None:
    """Fail closed: dry-run and an issue that names the cover; the data stays."""
    hass.states.async_set(
        COVER, "open", {"supported_features": 15, "current_position": 50}
    )
    entry = await setup_window(
        hass,
        window_data(dry_run=False, members=members),
        covers_present=False,
        freezer=freezer,
    )

    assert entry.subentries[WINDOW_ID].data[CONF_DRY_RUN] is False
    assert entry.runtime_data.windows[WINDOW_ID].dry_run is True
    assert state_of(hass, DRY_RUN).state == STATE_ON
    assert cover_calls(hass) == []
    assert _issue_ids(hass) == {REPORTING_ISSUE}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, REPORTING_ISSUE)
    assert issue is not None
    assert issue.translation_key == "armed_without_reporting"
    assert issue.translation_placeholders == {
        "window": "Example window",
        "covers": COVER,
    }

    # Stating the cover as event-driven on its page repairs it; the window
    # stays in dry-run until it is armed on purpose, which it is here.
    result = await _to_the_last_page(
        hass, entry, {"reporting_kind": "event_driven", "reporting_time": 0}
    )
    result = await configure_subentry_flow(hass, result, KEEP_ARMED)
    assert result["reason"] == "reconfigure_successful"
    await settle(hass, freezer)
    assert _issue_ids(hass) == set()
    assert [call.target.value for call in cover_calls(hass)] == [100]


@pytest.mark.parametrize("language", ["en", "de"])
@pytest.mark.parametrize(
    ("key", "placeholders"),
    [
        ("armed_without_movement_detection", {"{window}"}),
        ("armed_without_reporting", {"{window}", "{covers}"}),
    ],
)
def test_the_issues_of_a_window_stored_as_armed_have_their_text(
    language: str, key: str, placeholders: set[str]
) -> None:
    """Both languages explain the issues and name the window and the covers."""
    strings = json.loads(
        (
            ROOT
            / "custom_components"
            / "roller_shutter_suite"
            / "translations"
            / f"{language}.json"
        ).read_text(encoding="utf-8")
    )
    issue = strings["issues"][key]
    assert "{window}" in issue["title"]
    for placeholder in placeholders:
        assert placeholder in issue["description"]


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
    """Both languages name every check of the page and every reason it refuses."""
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
    errors = strings["config_subentries"]["window"]["error"]
    for key in (
        "confirm_every_check",
        "no_movement_detection",
        "reporting_not_stated",
        "reporting_polled",
    ):
        assert errors[key]
    assert "report_delay" not in errors
    assert "{covers}" in errors["reporting_not_stated"]
    assert "{covers}" in errors["reporting_polled"]
