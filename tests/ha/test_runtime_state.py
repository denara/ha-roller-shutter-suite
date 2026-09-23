"""The runtime and the state of a window: reload, restart, durations, the schedule's facts.

Time is controlled by the ``freezer`` fixture; no test sleeps.
"""

import logging
from dataclasses import replace
from datetime import date, timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.roller_shutter_suite import windows as windows_module
from custom_components.roller_shutter_suite.capabilities import member_configs
from custom_components.roller_shutter_suite.const import DOMAIN
from custom_components.roller_shutter_suite.controller import (
    WAKE_UP_DEFERRED,
    WAKE_UP_RECHECK,
    Phase,
)
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    ConstraintResult,
    Controls,
    Decision,
    EvaluationFault,
    GateKind,
    GateOutcome,
    GateRule,
    Layer,
    ManualOverrideDam,
    MemberCommand,
    MemberTarget,
    OverrideEndRule,
    OwnCommand,
    Position,
    PositionOwner,
    SimulatedState,
    TravelDirection,
    WindowState,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.schedule import PartOfDay
from custom_components.roller_shutter_suite.storage import storage_of
from tests.ha.helpers import NO_STOP, set_cover
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    MONDAY,
    WINDOW_ID,
    ZONE_NAME,
    advance,
    commands_sent,
    controller_of,
    local,
    monday_morning,
    phase_of,
    schedule_of,
    settle,
    setup_window,
    window_data,
)

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

REPORT_DELAY = timedelta(seconds=60)
WORKDAY_SOURCE = "binary_sensor.example_workday"
BRIGHTNESS_SOURCE = "sensor.example_brightness"
BRIGHTNESS_ROUTINE = FIXED_ROUTINE | {
    "schedule_brightness_source": BRIGHTNESS_SOURCE,
    "schedule_brightness_threshold": 50,
    "schedule_brightness_delay": 600,
    "schedule_workday_evening_not_before": "09:00",
}


def _reason(entry: Any) -> ReasonCode | None:
    decision = controller_of(entry).status.decision
    if decision is None or decision.gate is None:
        return None
    return decision.gate.reason


# ---------------------------------------------------------------------------
# A reload is harmless
# ---------------------------------------------------------------------------


@pytest.fixture
def slow_reports() -> Any:
    """Give every member a report delay of 60 seconds."""

    def delayed(hass: HomeAssistant, entity_ids: tuple[str, ...]) -> Any:
        return tuple(
            replace(
                member,
                capabilities=replace(member.capabilities, report_delay=REPORT_DELAY),
            )
            for member in member_configs(hass, entity_ids)
        )

    with patch.object(windows_module, "member_configs", delayed):
        yield


@pytest.mark.usefixtures("slow_reports")
async def test_reload_during_a_movement_sends_no_duplicate_and_detects_no_manual_movement(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The pending command, its expectation and the dams survive the reload."""
    set_cover(hass, COVER, position=50)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    assert [c.target.value for c in commands_sent(entry)] == [100]
    commanded = controller_of(entry).state.members[0].last_own_command
    assert commanded is not None
    assert commanded.command_id == commands_sent(entry)[0].command_id
    owner_before = controller_of(entry).state.owner

    # The whole entry reloads while the movement is in flight.
    freezer.tick(timedelta(seconds=20))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass, freezer)

    assert entry.state is ConfigEntryState.LOADED
    controller = controller_of(entry)
    assert controller.state.members[0].last_own_command == commanded
    assert _reason(entry) is ReasonCode.DUPLICATE_COMMAND
    assert commands_sent(entry) == []
    assert controller.state.owner is owner_before
    assert controller.state.manual_override is None

    # The end report arrives long after the reload, inside the report delay.
    freezer.tick(timedelta(seconds=70))
    set_cover(hass, COVER, position=100)
    await settle(hass, freezer)

    assert _reason(entry) is ReasonCode.TARGET_REACHED
    assert commands_sent(entry) == []
    assert controller.state.manual_override is None


async def test_a_dam_and_a_deferral_survive_the_reload(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A manual override that was armed before the reload still holds after it."""
    dam = ManualOverrideDam(
        armed_at=local(9, 30),
        end_rule=OverrideEndRule.FIXED_MINUTES,
        ends_at=local(11, 0),
        remembered_position=Position(50),
    )
    storage_of(hass).save_window_state(
        WINDOW_ID, WindowState(owner=PositionOwner.USER, manual_override=dam).to_data()
    )
    set_cover(hass, COVER, position=50)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    assert _reason(entry) is ReasonCode.MANUAL_OVERRIDE
    status = controller_of(entry).status
    assert status.wake_up is not None
    assert status.wake_up.reason == WAKE_UP_DEFERRED
    assert status.wake_up.at == local(11, 0)

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass, freezer)

    assert controller_of(entry).state.manual_override == dam
    assert _reason(entry) is ReasonCode.MANUAL_OVERRIDE
    assert commands_sent(entry) == []

    # When the dam ends, the window is recomputed and the day target is sent.
    await advance(hass, freezer, local(11, 0))
    assert _reason(entry) is ReasonCode.SENT


async def test_stored_state_that_cannot_be_read_starts_fresh_and_is_logged(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Corrupt stored data never stops a window; it starts with a fresh state."""
    storage_of(hass).save_window_state(WINDOW_ID, {"schema_version": 999})

    entry = await setup_window(hass, freezer=freezer)

    assert phase_of(controller_of(entry)) is Phase.RUNNING
    state = controller_of(entry).state
    # Fresh apart from what the first recompute latched.
    assert state == replace(WindowState(), latched_day_types=state.latched_day_types)
    logged = [
        r for r in caplog.records if "stored state cannot be read" in r.getMessage()
    ]
    assert len(logged) == 1
    assert "999" not in logged[0].getMessage()


async def test_removing_the_entry_forgets_the_stored_state(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The in-memory storage does not outlive the entry it belongs to."""
    entry = await setup_window(hass, freezer=freezer)
    assert storage_of(hass).windows.get(WINDOW_ID) is not None

    assert await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert storage_of(hass).windows == {}


# ---------------------------------------------------------------------------
# The schedule: state at a boundary, day types, durations, the named zone
# ---------------------------------------------------------------------------


async def test_schedule_state_is_persisted_right_after_the_boundary(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The latched day type of Tuesday is in the storage right after the morning trigger."""
    entry = await setup_window(hass, freezer=freezer)
    tuesday = MONDAY + timedelta(days=1)

    await advance(hass, freezer, local(7, 0, tuesday))

    stored = WindowState.from_data(storage_of(hass).load_window_state(WINDOW_ID))
    assert [latch.day for latch in stored.latched_day_types] == [tuesday]
    status = controller_of(entry).status
    assert status.schedule is not None
    assert status.schedule.part_of_day is PartOfDay.DAY
    assert status.schedule.day_type_latched


async def test_unavailable_day_type_input_follows_the_fallback(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A workday source that is unavailable: the day of the week decides, and says so."""
    hass.states.async_set(WORKDAY_SOURCE, "unavailable")
    entry = await setup_window(
        hass, house=FIXED_ROUTINE | {"schedule_workday_source": WORKDAY_SOURCE}
    )
    await settle(hass, freezer)

    status = controller_of(entry).status
    assert status.schedule is not None
    assert status.schedule.day_type_reason is ReasonCode.DAY_TYPE_FALLBACK
    assert status.schedule.day_type.value == "workday"
    assert status.sources[WORKDAY_SOURCE].value.state.value == "unavailable"
    # The morning trigger of a workday, not of a weekend day.
    assert status.schedule.morning_trigger == local(7, 0)


async def test_restored_state_does_not_count_as_the_start_of_a_duration(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Dark for an hour before the restart: the evening begins ten minutes after the start."""
    freezer.move_to(local(9, 0))
    hass.states.async_set(BRIGHTNESS_SOURCE, "10", {"unit_of_measurement": "lx"})
    freezer.move_to(local(10, 0))
    entry = await setup_window(hass, house=BRIGHTNESS_ROUTINE, freezer=freezer)
    controller = controller_of(entry)
    first = controller.status.last_recompute
    assert first is not None

    status = controller.status
    assert status.schedule is not None
    assert status.schedule.part_of_day is PartOfDay.DAY
    assert status.wake_up is not None
    assert status.wake_up.reason == WAKE_UP_RECHECK
    assert status.wake_up.at == first + timedelta(minutes=10)
    assert status.sources[BRIGHTNESS_SOURCE].since == first

    await advance(hass, freezer, first + timedelta(minutes=5))
    assert schedule_of(controller).part_of_day is PartOfDay.DAY

    await advance(hass, freezer, first + timedelta(minutes=10))
    assert schedule_of(controller).part_of_day is PartOfDay.NIGHT
    assert schedule_of(controller).evening_by_brightness


async def test_fixed_times_stay_on_the_clock_across_a_clock_change(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The snapshot carries the named zone: 07:00 is 07:00 on both days of the change."""
    saturday = date(2026, 10, 24)
    sunday = date(2026, 10, 25)  # the clocks go back at 03:00
    freezer.move_to(local(10, 0, saturday))
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    assert schedule_of(controller).evening_trigger == local(21, 0, saturday)
    # The time of the snapshot carries the named zone, in summer time.
    recomputed = controller.status.last_recompute
    assert recomputed is not None
    assert getattr(recomputed.tzinfo, "key", None) == ZONE_NAME
    assert recomputed.utcoffset() == timedelta(hours=2)

    await advance(hass, freezer, local(21, 0, saturday))
    assert schedule_of(controller).part_of_day is PartOfDay.NIGHT
    wake_up = controller.status.wake_up
    assert wake_up is not None
    assert wake_up.at == local(8, 30, sunday)
    # Across the change the wake-up is one hour further away than the clock says.
    assert wake_up.at - local(21, 0, saturday) == timedelta(hours=12, minutes=30)

    await advance(hass, freezer, local(8, 30, sunday))
    assert schedule_of(controller).part_of_day is PartOfDay.DAY
    assert schedule_of(controller).morning_trigger == local(8, 30, sunday)
    # Now in standard time, still the named zone.
    recomputed = controller.status.last_recompute
    assert recomputed is not None
    assert getattr(recomputed.tzinfo, "key", None) == ZONE_NAME
    assert recomputed.utcoffset() == timedelta(hours=1)


async def test_the_almanac_is_built_again_only_when_the_date_changes(
    hass: HomeAssistant, freezer: Any, fake_sun: Any
) -> None:
    """One almanac per local date; the sun port is asked again after midnight."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    sun = fake_sun.ports[0]
    asked: list[date] = []
    original = sun.sunrise

    def counting(on: date) -> Any:
        asked.append(on)
        return original(on)

    with patch.object(type(sun), "sunrise", side_effect=counting, autospec=False):
        controller.async_request_recompute()
        await settle(hass, freezer)
        assert asked == []

        await advance(hass, freezer, local(0, 1, MONDAY + timedelta(days=1)))
        assert asked
        assert asked[0] == MONDAY
        assert asked[-1] == MONDAY + timedelta(days=8)


async def test_the_installation_seed_is_created_once_and_reaches_the_snapshot(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The seed is stored on first use and is the same after a reload."""
    entry = await setup_window(hass, freezer=freezer)
    seed = storage_of(hass).load_seed()
    assert seed is not None

    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass, freezer)

    assert storage_of(hass).load_seed() == seed


# ---------------------------------------------------------------------------
# Capabilities do not flap
# ---------------------------------------------------------------------------


def _register_cover(hass: HomeAssistant) -> None:
    er.async_get(hass).async_get_or_create(
        "cover",
        "example_platform",
        "example_unique",
        suggested_object_id="example_window",
        supported_features=int(NO_STOP),
    )


def _issues(hass: HomeAssistant) -> set[str]:
    return {issue for domain, issue in ir.async_get(hass).issues if domain == DOMAIN}


async def test_a_restart_with_a_cover_that_comes_late_changes_no_capability(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The last known capabilities apply while the cover is away; nothing masks or reports."""
    _register_cover(hass)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    config = entry.runtime_data.windows[WINDOW_ID].resolution.config
    assert config is not None
    profile = config.members[0].capabilities
    assert profile.capabilities_known
    assert not profile.supports_stop
    assert _issues(hass) == set()
    assert phase_of(controller_of(entry)) is Phase.WAITING_FOR_MEMBERS

    freezer.tick(timedelta(minutes=3))
    set_cover(hass, COVER, NO_STOP, position=50)
    await settle(hass, freezer)

    assert phase_of(controller_of(entry)) is Phase.RUNNING
    assert controller_of(entry).config is config
    assert _issues(hass) == set()


async def test_a_cover_that_is_away_for_minutes_changes_no_capability(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A gap of a few minutes: no mask, no repair issue, the same resolved configuration."""
    _register_cover(hass)
    set_cover(hass, COVER, NO_STOP, position=100)
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    controller = controller_of(entry)
    config = controller.config

    hass.states.async_set(COVER, "unavailable")
    await settle(hass, freezer)
    assert _reason(entry) is ReasonCode.COVER_UNAVAILABLE
    await advance(hass, freezer, local(10, 4))
    assert _issues(hass) == set()

    set_cover(hass, COVER, NO_STOP, position=100)
    await settle(hass, freezer)

    assert controller.config is config
    assert phase_of(controller) is Phase.RUNNING
    assert _reason(entry) is ReasonCode.TARGET_REACHED
    assert _issues(hass) == set()


async def test_a_cover_that_was_never_seen_is_read_once_when_it_appears(
    hass: HomeAssistant, freezer: Any
) -> None:
    """No registry entry, cover late: its capabilities are learned once, its position counts."""
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    controller = controller_of(entry)
    unknown = controller.config.members[0].capabilities
    assert not unknown.capabilities_known
    assert phase_of(controller) is Phase.WAITING_FOR_MEMBERS

    freezer.tick(timedelta(minutes=3))
    set_cover(hass, COVER, NO_STOP, position=50)
    await settle(hass, freezer)

    learned = controller.config.members[0].capabilities
    assert learned.capabilities_known
    assert not learned.supports_stop
    assert learned.reports_position
    assert _reason(entry) is ReasonCode.SENT
    assert [c.target.value for c in commands_sent(entry)] == [100]
    assert _issues(hass) == set()

    # The cover reports the target: reached, and the command is not repeated,
    # also after the expectation window has closed.
    freezer.tick(timedelta(seconds=30))
    set_cover(hass, COVER, NO_STOP, position=100)
    await settle(hass, freezer)
    assert _reason(entry) is ReasonCode.TARGET_REACHED
    await advance(hass, freezer, local(10, 30))
    assert _reason(entry) is ReasonCode.TARGET_REACHED
    assert len(commands_sent(entry)) == 1

    # The learned profile is never read again: a change of the entity's
    # features does not reach the configuration.
    set_cover(hass, COVER, position=100)
    await settle(hass, freezer)
    assert controller.config.members[0].capabilities == learned


async def test_a_window_switched_from_dry_run_to_armed_starts_clean(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The simulated state and the dams of the dry-run time are discarded when armed."""
    would_be = MemberCommand(
        COVER,
        OwnCommand(
            "simulated",
            Position(100),
            TravelDirection.UP,
            local(9, 0),
            WishClass.COMFORT,
            ReasonCode.SCHEDULE_DAY,
        ),
    )
    stored = WindowState(
        owner=PositionOwner.USER,
        simulated=SimulatedState(
            commands=(would_be,), last_comfort_movement=local(9, 0)
        ),
        manual_override=ManualOverrideDam(
            armed_at=local(9, 30),
            end_rule=OverrideEndRule.FIXED_MINUTES,
            ends_at=local(11, 0),
        ),
    )
    storage_of(hass).save_window_state(WINDOW_ID, stored.to_data())
    set_cover(hass, COVER, position=50)

    entry = await setup_window(hass, covers_present=False, freezer=freezer)

    state = controller_of(entry).state
    assert state.simulated is None
    assert state.manual_override is None
    assert state.owner is PositionOwner.UNKNOWN
    # Armed and clean: the real command is given, not judged against the would-be one.
    assert _reason(entry) is ReasonCode.SENT
    assert [c.target.value for c in commands_sent(entry)] == [100]


async def test_a_window_in_dry_run_keeps_its_simulated_state(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Arming happens only for an armed window; dry-run keeps the would-be commands."""
    would_be = MemberCommand(
        COVER,
        OwnCommand(
            "simulated",
            Position(100),
            TravelDirection.UP,
            local(9, 0),
            WishClass.COMFORT,
            ReasonCode.SCHEDULE_DAY,
        ),
    )
    stored = WindowState(simulated=SimulatedState(commands=(would_be,)))
    storage_of(hass).save_window_state(WINDOW_ID, stored.to_data())
    set_cover(hass, COVER, position=50)

    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )

    state = controller_of(entry).state
    assert state.simulated is not None
    assert state.simulated.commands == (would_be,)
    assert commands_sent(entry) == []


class RaisingActuator:
    """An actuator that raises for the second member it is asked to move."""

    def __init__(self) -> None:
        """Start with nothing moved."""
        self.moved: list[str] = []

    def move_to(self, command_id: str, member_id: str, target: Position) -> None:
        """Record the first member and raise for the second."""
        del command_id, target
        if self.moved:
            raise OSError("the platform is gone")
        self.moved.append(member_id)


async def test_a_command_is_recorded_per_member_when_the_actuator_raises(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The member that was commanded keeps its own command; the other has none."""
    set_cover(hass, "cover.example_left", position=50)
    set_cover(hass, "cover.example_right", position=50)
    entry = await setup_window(
        hass,
        window_data(["cover.example_left", "cover.example_right"], dry_run=True),
        covers_present=False,
        freezer=freezer,
    )
    controller = controller_of(entry)
    actuator = RaisingActuator()
    controller.actuator = actuator
    controller.controls = lambda: Controls(dry_run=False)

    controller.async_request_recompute()
    await settle(hass, freezer)

    assert actuator.moved == ["cover.example_left"]
    assert controller.status.error == "OSError"
    commanded = controller.state.commanded_targets
    assert commanded == {"cover.example_left": Position(100)}
    stored = WindowState.from_data(storage_of(hass).load_window_state(WINDOW_ID))
    assert stored.commanded_targets == commanded
    assert [
        r for r in caplog.records if "the recompute raised OSError" in r.getMessage()
    ]


# ---------------------------------------------------------------------------
# Faults of the safety net, disabled functions, the second dry-run check
# ---------------------------------------------------------------------------


class Faulty:
    """An engine whose decisions carry a fault of the frost constraint."""

    def __init__(self, faults: tuple[EvaluationFault, ...]) -> None:
        """Keep the faults every decision carries; the test changes them."""
        self.faults = faults

    def recompute(self, snapshot: WorldSnapshot) -> Decision:
        """Wish the night position, limited by a constraint that raised."""
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
            faults=self.faults,
        )

    def state_after(self, snapshot: WorldSnapshot, decision: Decision) -> WindowState:
        """Change nothing."""
        del decision
        return snapshot.state


def _fault(error: Exception) -> EvaluationFault:
    return EvaluationFault.of(Constraint.FROST_PROTECTION, None, error)


async def test_faults_of_the_safety_net_are_logged_once_per_change_and_are_facts(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The same fault on every recompute is logged once; a new one is logged again."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    engine = Faulty((_fault(TypeError("a value with cover.example_secret")),))
    controller.engine = engine  # type: ignore[assignment]
    caplog.set_level(logging.INFO, logger="custom_components.roller_shutter_suite")

    for _ in range(3):
        controller.async_request_recompute()
        await settle(hass, freezer)

    def logged(text: str) -> list[str]:
        return [r.getMessage() for r in caplog.records if text in r.getMessage()]

    assert len(logged("raised TypeError")) == 1
    assert "frost_protection" in logged("raised TypeError")[0]
    assert "Example window" in logged("raised TypeError")[0]
    assert "cover.example_secret" not in logged("raised TypeError")[0]
    assert controller.status.faults == engine.faults

    engine.faults = (_fault(ValueError("another")),)
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert len(logged("raised ValueError")) == 1

    engine.faults = ()
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert len(logged("without a fault again")) == 1
    assert controller.status.faults == ()


async def test_disabled_functions_reach_the_arbiter_and_the_status(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A faulty schedule setting pauses the schedule: no wish, and the status says so."""
    entry = await setup_window(
        hass,
        window_data(settings={"schedule_morning_position": "not a position"}),
        freezer=freezer,
    )

    status = controller_of(entry).status
    assert status.phase is Phase.RUNNING
    assert {f.value for f in status.disabled_functions} == {"schedule"}
    assert status.decision is not None
    assert status.decision.winning_wish is None
    assert status.schedule is None
    reasons = {(r.layer, r.reason) for r in status.decision.other_layers}
    assert (Layer.SCHEDULE, ReasonCode.FUNCTION_DISABLED_BY_FAULT) in reasons


class FireThroughFailedDryRun:
    """An engine that sends a fire wish because the dry-run rule itself raised."""

    def recompute(self, snapshot: WorldSnapshot) -> Decision:
        """Open fully, with the dry-run rule among the faults."""
        members = tuple(
            MemberTarget(member.member_id, Position(100))
            for member in snapshot.observation.members
        )
        return Decision(
            winning_wish=Wish.target_per_member(
                Layer.FIRE, ReasonCode.FIRE_ALARM, members
            ),
            targets=members,
            gate=GateOutcome.send(),
            faults=(EvaluationFault.of(GateRule.DRY_RUN, None, RuntimeError("x")),),
        )

    def state_after(self, snapshot: WorldSnapshot, decision: Decision) -> WindowState:
        """Change nothing."""
        del decision
        return snapshot.state


async def test_second_dry_run_check_lets_a_fire_command_through_only_with_the_ruling(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """In dry-run a fire command that passed a failed dry-run rule is sent; anything else is not."""
    set_cover(hass, COVER, position=0)
    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )
    controller = controller_of(entry)
    assert commands_sent(entry) == []

    controller.engine = FireThroughFailedDryRun()  # type: ignore[assignment]
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert [c.target.value for c in commands_sent(entry)] == [100]
    assert controller.state.members[0].last_own_command is not None
    assert controller.state.members[0].last_own_command.reason is ReasonCode.FIRE_ALARM

    # A "send" for a comfort wish of a window in dry-run is a fault of the
    # arbiter; the second check refuses it and says so.
    class ComfortSend(FireThroughFailedDryRun):
        def recompute(self, snapshot: WorldSnapshot) -> Decision:
            decision = super().recompute(snapshot)
            assert decision.winning_wish is not None
            return replace(
                decision,
                winning_wish=replace(
                    decision.winning_wish,
                    layer=Layer.SCHEDULE,
                    reason=ReasonCode.SCHEDULE_DAY,
                ),
                faults=(),
            )

    controller.engine = ComfortSend()  # type: ignore[assignment]
    controller.async_request_recompute()
    await settle(hass, freezer)
    assert len(commands_sent(entry)) == 1
    assert [r for r in caplog.records if "nothing is sent" in r.getMessage()]


async def test_an_exception_of_the_recompute_itself_is_logged_and_the_window_goes_on(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """Outside the safety net: the error is a fact of the status, the next trigger retries."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)

    class Broken:
        def recompute(self, snapshot: WorldSnapshot) -> Decision:
            raise KeyError("cover.example_secret")

    controller.engine = Broken()  # type: ignore[assignment]
    for _ in range(2):
        controller.async_request_recompute()
        await settle(hass, freezer)

    assert controller.status.error == "KeyError"
    logged = [r for r in caplog.records if "the recompute raised" in r.getMessage()]
    assert len(logged) == 1
    assert "cover.example_secret" not in logged[0].getMessage()

    controller.engine = Engine(controller.config, build_arbiter())
    controller.async_request_recompute()
    await settle(hass, freezer)
    recovered = controller.status
    assert recovered.error is None
    assert recovered.decision is not None
    assert recovered.decision.gate is not None
    assert recovered.decision.gate.kind is GateKind.SUPPRESS
