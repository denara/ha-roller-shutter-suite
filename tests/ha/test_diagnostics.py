"""The diagnostics download: what it contains, and what it never contains.

The functions of the platform are called directly and their result is put
through Home Assistant's JSON encoder, as the download does. Home Assistant's
own endpoint is not used: setting up its ``http`` dependency raises a warning
of ``aiohttp`` in this test environment, which the warning policy of the
project turns into an error (``docs/dev/testing.md``). That Home Assistant
finds the platform by its name is shown separately. The snapshot is written
with neutral test data only.
"""

import json
from typing import Any

import pytest
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.integration_platform import (
    async_process_integration_platforms,
)
from homeassistant.helpers.json import json_dumps
from pytest_homeassistant_custom_component.common import MockConfigEntry
from syrupy.assertion import SnapshotAssertion

from custom_components.roller_shutter_suite import diagnostics as platform
from custom_components.roller_shutter_suite.const import CONF_SETTINGS, DOMAIN
from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    ConstraintResult,
    Decision,
    EvaluationFault,
    GateOutcome,
    GateRule,
    Layer,
    MemberTarget,
    Position,
    WindowState,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.diagnostics import REDACTED
from tests.ha.helpers import set_cover, setup_entry
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    WINDOW_ID,
    controller_of,
    monday_morning,
    settle,
    setup_window,
    window_data,
    window_subentry,
)
from tests.ha.status_kit import REASON, state_of

_monday_morning = pytest.fixture(autouse=True)(monday_morning)


async def get_diagnostics_for_config_entry(
    hass: HomeAssistant, entry: MockConfigEntry
) -> Any:
    """Return the diagnostics of the entry as the download serializes them."""
    result = await platform.async_get_config_entry_diagnostics(hass, entry)
    return json.loads(json_dumps(result))


async def get_diagnostics_for_device(
    hass: HomeAssistant, entry: MockConfigEntry, device: dr.DeviceEntry
) -> Any:
    """Return the diagnostics of a device as the download serializes them."""
    result = await platform.async_get_device_diagnostics(hass, entry, device)
    return json.loads(json_dumps(result))


TELLING_TEXT = "cover.example_secret_room"
"""Text that an exception message could carry and that must never be written out."""


class FaultyConstraint:
    """An engine whose decision carries a fault with a telling exception message."""

    def recompute(self, snapshot: WorldSnapshot) -> Decision:
        """Wish the night position; the frost constraint raised."""
        members = tuple(
            MemberTarget(member.member_id, Position(0))
            for member in snapshot.observation.members
        )
        return Decision(
            winning_wish=Wish.target_per_member(
                Layer.SCHEDULE, ReasonCode.SCHEDULE_NIGHT, members
            ),
            constraints=(
                ConstraintResult(
                    Constraint.FROST_PROTECTION, ReasonCode.CONSTRAINT_FAILED, members
                ),
            ),
            targets=members,
            gate=GateOutcome.suppress(
                GateRule.PAUSE, ReasonCode.PAUSED, dry_run=snapshot.controls.dry_run
            ),
            faults=(
                EvaluationFault.of(
                    Constraint.FROST_PROTECTION,
                    None,
                    RuntimeError(f"cannot read {TELLING_TEXT}"),
                ),
            ),
        )

    def state_after(self, snapshot: WorldSnapshot, decision: Decision) -> WindowState:
        """Change nothing."""
        del decision
        return snapshot.state


async def test_home_assistant_finds_the_diagnostics_platform(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The download looks for a platform named ``diagnostics``."""
    await setup_window(hass, freezer=freezer)
    found: dict[str, Any] = {}

    @callback
    def _process(hass: HomeAssistant, domain: str, module: Any) -> None:
        del hass
        found[domain] = module

    await async_process_integration_platforms(hass, "diagnostics", _process)
    await hass.async_block_till_done()
    assert found[DOMAIN] is platform


async def test_diagnostics_of_the_entry_match_the_snapshot(
    hass: HomeAssistant,
    freezer: Any,
    snapshot: SnapshotAssertion,
) -> None:
    """Configuration with provenance, profile, status, decisions, persisted state."""
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass,
        window_data(
            settings={"schedule_workday_source": "binary_sensor.example_workday"},
            dry_run=True,
        ),
        covers_present=False,
        freezer=freezer,
    )

    diagnostics = await get_diagnostics_for_config_entry(hass, entry)
    assert diagnostics == snapshot


async def test_diagnostics_of_a_device_show_its_window(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The device of a window downloads the diagnostics of that window alone."""
    set_cover(hass, COVER)
    set_cover(hass, "cover.example_other")
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: FIXED_ROUTINE},
        subentries=[
            window_subentry(),
            window_subentry(
                "Other example", "w2", window_data(["cover.example_other"])
            ),
        ],
    )
    await settle(hass, freezer)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, WINDOW_ID), entry.entry_id
    )
    assert device is not None

    diagnostics = await get_diagnostics_for_device(hass, entry, device)
    windows = diagnostics["windows"]
    assert isinstance(windows, list)
    assert [window["subentry_id"] for window in windows] == [WINDOW_ID]


@pytest.mark.parametrize("dry_run", [False, True])
async def test_names_and_entity_ids_are_redacted(
    hass: HomeAssistant, freezer: Any, dry_run: bool
) -> None:
    """Nothing in the download names a room, a cover or another entity."""
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass,
        window_data(
            settings={"schedule_workday_source": "binary_sensor.example_workday"},
            dry_run=dry_run,
        ),
        covers_present=False,
        freezer=freezer,
    )
    # A text that an entity reports can name anything; it is not shown.
    hass.states.async_set("binary_sensor.example_workday", "example text")
    await settle(hass, freezer)

    text = json.dumps(await get_diagnostics_for_config_entry(hass, entry))
    assert "example_window" not in text
    assert "example_workday" not in text
    assert "Example window" not in text
    assert "example text" not in text
    assert REDACTED in text


async def test_a_fault_is_shown_by_stage_and_code_never_by_its_exception(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The diagnostics and the attributes name the stage and the code, not the message."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    controller.engine = FaultyConstraint()  # type: ignore[assignment]
    controller.async_request_recompute()
    await settle(hass, freezer)

    attributes = state_of(hass, REASON).attributes
    assert attributes["faults"] == [
        {
            "stage": "constraint",
            "place": "frost_protection",
            "function": None,
            "reason": ReasonCode.CONSTRAINT_FAILED,
        }
    ]
    diagnostics = await get_diagnostics_for_config_entry(hass, entry)
    for text in (json.dumps(diagnostics), json.dumps(dict(attributes))):
        assert TELLING_TEXT not in text
        assert "cannot read" not in text
        assert "RuntimeError" not in text
    assert "constraint_failed" in json.dumps(diagnostics)
