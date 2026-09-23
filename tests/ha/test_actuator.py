"""The cover actuator adapter: dry-run, cover actions, staggering, results.

Every cover here is a stand-in: a state on the state machine and three
recording services (``runtime_kit.register_cover_services``). No cover
platform is loaded and nothing is ever sent to a real installation. Time is
controlled by the ``freezer`` fixture; no test sleeps.
"""

import logging
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import pytest
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.cover import CoverEntityFeature
from homeassistant.const import (
    EVENT_HOMEASSISTANT_STOP,
    SERVICE_CLOSE_COVER,
    SERVICE_OPEN_COVER,
    SERVICE_SET_COVER_POSITION,
)
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
)

from custom_components.roller_shutter_suite.actuator import (
    ACTUATOR_KEY,
    CommandNotPossibleError,
    CoverActuator,
    WindowActuator,
    actuator_of,
    cover_action,
    fire_passed_failed_dry_run,
    forget_actuator,
)
from custom_components.roller_shutter_suite.controller import WindowController
from custom_components.roller_shutter_suite.core.arbiter import member_expectation_end
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    AnySourceValue,
    CommandResult,
    Controls,
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
from custom_components.roller_shutter_suite.core.ports import Actuator
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import STUB_LAYERS, day, fire, storm
from tests.ha.helpers import FULL_COVER, set_cover, setup_entry
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    CoverCall,
    controller_of,
    cover_calls,
    local,
    monday_morning,
    register_cover_services,
    runtime_of,
    settle,
    setup_window,
    window_data,
    window_subentry,
)

_monday_morning = pytest.fixture(autouse=True)(monday_morning)

OPEN_CLOSE = CoverEntityFeature.OPEN | CoverEntityFeature.CLOSE
QUIET = FIXED_ROUTINE | {"schedule_enabled": False}
"""No daily routine: nothing is sent until a test hands in its wish."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


@dataclass
class Scripted:
    """The real arbiter with the stub layers of the core kit, fed invented sources.

    The stub layers answer fire, storm (protection) and the part of the day
    (comfort) from plain sources, so every class of wish can reach the gate
    and the adapter; the gate, dry-run and the recorder are the real ones.
    """

    engine: Engine
    sources: dict[str, AnySourceValue]

    @property
    def arbiter(self) -> Any:
        """Return the arbiter, as the controller reads it."""
        return self.engine.arbiter

    def recompute(self, snapshot: WorldSnapshot) -> Decision:
        """Decide with the invented sources."""
        return self.engine.recompute(replace(snapshot, sources=self.sources))

    def state_after(self, snapshot: WorldSnapshot, decision: Decision) -> WindowState:
        """Remember a would-be send as the real engine does."""
        return self.engine.state_after(
            replace(snapshot, sources=self.sources), decision
        )


def script(controller: WindowController, sources: dict[str, AnySourceValue]) -> None:
    """Let the controller decide with the stub layers and these sources."""
    engine = Engine(controller.config, build_arbiter(STUB_LAYERS))
    controller.engine = Scripted(engine, sources)  # type: ignore[assignment]
    controller.async_request_recompute()


async def tick(hass: HomeAssistant, freezer: Any, seconds: float, steps: int) -> None:
    """Advance the time in steps and fire what is due after each."""
    for _ in range(steps):
        freezer.tick(timedelta(seconds=seconds))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def setup_windows(
    hass: HomeAssistant,
    count: int,
    *,
    gap: int,
    position: int = 50,
    features: CoverEntityFeature = FULL_COVER,
) -> tuple[MockConfigEntry, list[str]]:
    """Set up ``count`` armed windows with one cover each and no daily routine."""
    register_cover_services(hass)
    covers = [f"cover.example_window_{index}" for index in range(count)]
    for cover in covers:
        set_cover(hass, cover, features=features, position=position)
    entry = await setup_entry(
        hass,
        {"settings": QUIET | {"stagger_gap": gap}},
        subentries=[
            window_subentry(
                f"Example window {index}", f"w{index}", window_data([cover])
            )
            for index, cover in enumerate(covers)
        ],
    )
    return entry, covers


def controllers(entry: MockConfigEntry) -> list[WindowController]:
    """Return the controllers of the entry in the order of their windows."""
    return list(runtime_of(entry).windows.values())


def decision(
    layer: Layer = Layer.SCHEDULE,
    reason: ReasonCode = ReasonCode.SCHEDULE_DAY,
    *,
    faults: tuple[EvaluationFault, ...] = (),
) -> Decision:
    """Return a "send" decision for one member, as a forged or a real one."""
    targets = (MemberTarget(COVER, FULLY_OPEN),)
    return Decision(
        winning_wish=Wish.target_per_member(layer, reason, targets),
        targets=targets,
        gate=GateOutcome.send(),
        faults=faults,
    )


FIRE = decision(Layer.FIRE, ReasonCode.FIRE_ALARM)
FIRE_THROUGH_FAILED_DRY_RUN = decision(
    Layer.FIRE,
    ReasonCode.FIRE_ALARM,
    faults=(EvaluationFault.of(GateRule.DRY_RUN, None, RuntimeError("x")),),
)


@dataclass
class Window:
    """A window bound to the adapter directly, without a controller."""

    dry_run: bool = False
    results: list[CommandResult] = field(default_factory=list)

    def controls(self) -> Controls:
        """Return the controls the adapter reads itself."""
        return Controls(dry_run=self.dry_run)


def bind(
    actuator: CoverActuator, window: Window, *, gap: float = 0, window_id: str = "w1"
) -> WindowActuator:
    """Bind a window to the adapter and return its actuator port."""
    return actuator.bind(
        window_id,
        title="Example window",
        controls=window.controls,
        gap=timedelta(seconds=gap),
        on_result=window.results.append,
    )


# ---------------------------------------------------------------------------
# Dry-run: nothing is sent, for every class of wish
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sources", "target", "reason"),
    [
        (day(), 100, ReasonCode.SCHEDULE_DAY),
        (storm(), 0, ReasonCode.PROTECTION_EVENT),
        (fire(), 100, ReasonCode.FIRE_ALARM),
    ],
    ids=["comfort", "protection", "fire"],
)
async def test_a_window_in_dry_run_calls_nothing_and_records_the_would_be_command(
    hass: HomeAssistant,
    freezer: Any,
    sources: dict[str, AnySourceValue],
    target: int,
    reason: ReasonCode,
) -> None:
    """Zero service calls; the would-be command stands with target and reason."""
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass,
        window_data(dry_run=True),
        house=QUIET,
        covers_present=False,
        freezer=freezer,
    )
    controller = controller_of(entry)

    script(controller, sources)
    await settle(hass, freezer)
    await tick(hass, freezer, 5, 3)

    assert cover_calls(hass) == []
    status = controller.status.decision
    assert status is not None
    assert status.gate is not None
    assert status.gate.reason is ReasonCode.DRY_RUN
    simulated = controller.state.simulated
    assert simulated is not None
    (would_be,) = simulated.commands
    assert would_be.command.target == Position(target)
    assert would_be.command.reason is reason
    assert controller.state.members == ()


@pytest.mark.parametrize(
    "forged",
    [
        decision(),
        decision(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT),
        FIRE,
        None,
    ],
    ids=["comfort", "protection", "fire", "no decision"],
)
async def test_a_forged_send_for_a_window_in_dry_run_sends_nothing(
    hass: HomeAssistant,
    caplog: pytest.LogCaptureFixture,
    forged: Decision | None,
) -> None:
    """The adapter checks dry-run itself, whatever reaches it."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    window = Window(dry_run=True)
    port = bind(actuator_of(hass), window)

    port.move_to("command-1", COVER, FULLY_OPEN, decision=forged)
    await hass.async_block_till_done()

    assert cover_calls(hass) == []
    assert window.results == []
    assert [r for r in caplog.records if "nothing is sent" in r.getMessage()]


async def test_the_one_exception_a_fire_command_that_passed_a_failed_dry_run_rule(
    hass: HomeAssistant,
) -> None:
    """Section 13a: an escape route that stays closed in a fire is the greater evil."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    window = Window(dry_run=True)
    port = bind(actuator_of(hass), window, gap=2)

    port.move_to("command-1", COVER, FULLY_OPEN, decision=FIRE_THROUGH_FAILED_DRY_RUN)
    await hass.async_block_till_done()

    assert [(c.member_id, c.target.value) for c in cover_calls(hass)] == [(COVER, 100)]
    (result,) = window.results
    assert not result.failed
    assert fire_passed_failed_dry_run(FIRE_THROUGH_FAILED_DRY_RUN)
    assert not fire_passed_failed_dry_run(FIRE)
    assert not fire_passed_failed_dry_run(None)


async def test_dry_run_is_checked_again_right_before_the_call(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A window that goes into dry-run while its command waits for its slot sends nothing."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    set_cover(hass, "cover.example_other", position=50)
    actuator = actuator_of(hass)
    first = Window()
    second = Window()
    bind(actuator, first, gap=2).move_to(
        "command-a", "cover.example_other", FULLY_OPEN, decision=decision()
    )
    port = bind(actuator, second, gap=2, window_id="w2")
    port.move_to("command-b", COVER, FULLY_OPEN, decision=decision())
    await hass.async_block_till_done()
    assert [c.member_id for c in cover_calls(hass)] == ["cover.example_other"]

    second.dry_run = True
    await tick(hass, freezer, 1, 3)

    assert [c.member_id for c in cover_calls(hass)] == ["cover.example_other"]
    assert second.results == [CommandResult("command-b", COVER, None, failed=True)]


# ---------------------------------------------------------------------------
# What the cover supports
# ---------------------------------------------------------------------------


def _state(features: int | str, state: str = "open") -> State:
    return State(COVER, state, {"supported_features": features})


@pytest.mark.parametrize(
    ("target", "service"),
    [
        (0, SERVICE_CLOSE_COVER),
        (30, SERVICE_CLOSE_COVER),
        (49, SERVICE_CLOSE_COVER),
        (50, SERVICE_OPEN_COVER),
        (70, SERVICE_OPEN_COVER),
        (100, SERVICE_OPEN_COVER),
    ],
)
def test_a_cover_without_set_position_is_only_opened_or_closed(
    target: int, service: str
) -> None:
    """Below 50 it closes, from 50 it opens (section 8.1)."""
    assert cover_action(_state(int(OPEN_CLOSE)), Position(target)) == (service, {})


def test_a_cover_with_set_position_gets_the_position() -> None:
    """Also for an end position: one action for every target."""
    assert cover_action(_state(int(FULL_COVER)), Position(0)) == (
        SERVICE_SET_COVER_POSITION,
        {"position": 0},
    )


@pytest.mark.parametrize(
    ("state", "target"),
    [
        (None, 100),
        (_state(int(FULL_COVER), "unavailable"), 100),
        (_state(int(CoverEntityFeature.OPEN)), 0),
        (_state(int(CoverEntityFeature.CLOSE)), 100),
        (_state("everything"), 100),
    ],
    ids=["no state", "unavailable", "open only", "close only", "no features"],
)
def test_an_action_the_cover_does_not_support_is_never_called(
    state: State | None, target: int
) -> None:
    """The adapter refuses instead of guessing."""
    with pytest.raises(CommandNotPossibleError):
        cover_action(state, Position(target))


async def test_a_window_whose_cover_has_no_set_position_and_no_feedback(
    hass: HomeAssistant, freezer: Any
) -> None:
    """No position in the window state, no exception, and only open is called."""
    set_cover(hass, COVER, features=OPEN_CLOSE, position=None, state="closed")
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    controller = controller_of(entry)

    observation = controller.status.observation
    assert observation is not None
    assert observation.members[0].observation.position is None
    assert controller.status.error is None
    assert [(c.service, c.target.value) for c in cover_calls(hass)] == [
        (SERVICE_OPEN_COVER, 100)
    ]


async def test_a_cover_that_cannot_execute_the_command_reports_a_failure(
    hass: HomeAssistant,
) -> None:
    """Nothing is called, and the core hears ``command_failed``."""
    register_cover_services(hass)
    set_cover(hass, COVER, features=CoverEntityFeature.STOP, position=50)
    window = Window()

    bind(actuator_of(hass), window).move_to(
        "command-1", COVER, FULLY_OPEN, decision=decision()
    )
    await hass.async_block_till_done()

    assert cover_calls(hass) == []
    (result,) = window.results
    assert result.failed


# ---------------------------------------------------------------------------
# Staggering
# ---------------------------------------------------------------------------


def _gaps(calls: list[CoverCall]) -> list[timedelta]:
    times = sorted(call.at for call in calls)
    return [later - earlier for earlier, later in pairwise(times)]


async def test_ten_windows_commanded_together_are_sent_with_the_gap(
    hass: HomeAssistant, freezer: Any
) -> None:
    """One motor every two seconds, in the order in which they were commanded."""
    entry, covers = await setup_windows(hass, 10, gap=2)
    await settle(hass, freezer)
    assert cover_calls(hass) == []

    for controller in controllers(entry):
        script(controller, day())
    await settle(hass, freezer)
    assert len(cover_calls(hass)) == 1

    await tick(hass, freezer, 1, 20)

    calls = cover_calls(hass)
    assert sorted(call.member_id for call in calls) == sorted(covers)
    assert _gaps(calls) == [timedelta(seconds=2)] * 9


async def test_the_same_ten_windows_at_fire_are_sent_without_a_gap(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Fire is never staggered: every call at the same instant."""
    entry, covers = await setup_windows(hass, 10, gap=2)
    await settle(hass, freezer)

    for controller in controllers(entry):
        script(controller, fire())
    await settle(hass, freezer)

    calls = cover_calls(hass)
    assert sorted(call.member_id for call in calls) == sorted(covers)
    assert _gaps(calls) == [timedelta(0)] * 9


async def test_the_members_of_one_window_are_staggered_too(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Section 9: the gap applies per motor, also inside a window."""
    left, right = "cover.example_left", "cover.example_right"
    set_cover(hass, left, position=50)
    set_cover(hass, right, position=50)
    entry = await setup_window(
        hass,
        window_data([left, right]),
        house=FIXED_ROUTINE | {"stagger_gap": 3},
        covers_present=False,
        freezer=freezer,
    )
    await tick(hass, freezer, 1, 5)

    calls = cover_calls(hass)
    assert [c.member_id for c in calls] == [left, right]
    assert _gaps(calls) == [timedelta(seconds=3)]
    assert {c.context_id for c in calls} == {
        m.last_own_command.context_id
        for m in controller_of(entry).state.members
        if m.last_own_command is not None
    }


async def test_a_window_with_a_gap_of_zero_does_not_stagger_its_members(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Zero switches staggering off for the motors of this window."""
    left, right = "cover.example_left", "cover.example_right"
    set_cover(hass, left, position=50)
    set_cover(hass, right, position=50)
    await setup_window(
        hass,
        window_data([left, right], settings={"stagger_gap": 0}),
        house=FIXED_ROUTINE | {"stagger_gap": 3},
        covers_present=False,
        freezer=freezer,
    )

    assert _gaps(cover_calls(hass)) == [timedelta(0)]


async def test_a_newer_command_replaces_a_queued_one(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The member is called once, with the newer target."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    set_cover(hass, "cover.example_other", position=50)
    actuator = actuator_of(hass)
    first = bind(actuator, Window(), gap=2)
    window = Window()
    port = bind(actuator, window, gap=2, window_id="w2")
    first.move_to("command-a", "cover.example_other", FULLY_OPEN, decision=decision())
    port.move_to("command-b", COVER, Position(30), decision=decision())
    port.move_to("command-c", COVER, Position(70), decision=decision())

    await tick(hass, freezer, 1, 8)

    assert [(c.member_id, c.target.value) for c in cover_calls(hass)] == [
        ("cover.example_other", 100),
        (COVER, 70),
    ]
    assert [r.command_id for r in window.results] == ["command-c"]


# ---------------------------------------------------------------------------
# Results: context, failures, other windows
# ---------------------------------------------------------------------------


def fail_for(hass: HomeAssistant, failing: set[str]) -> None:
    """Let set position raise for the given covers and record the others."""
    calls = cover_calls(hass)

    async def handler(call: ServiceCall) -> None:
        member_id = call.data["entity_id"]
        if member_id in failing:
            raise HomeAssistantError("the platform refused")
        calls.append(
            CoverCall(
                member_id,
                call.service,
                Position(call.data["position"]),
                call.context.id,
                datetime.now().astimezone(),
            )
        )

    hass.services.async_register(COVER_DOMAIN, SERVICE_SET_COVER_POSITION, handler)


async def test_a_failing_call_does_not_stop_other_windows_and_reaches_the_core(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The failed command is marked; the other window's command goes out."""
    entry, covers = await setup_windows(hass, 2, gap=0)
    await settle(hass, freezer)
    fail_for(hass, {covers[0]})

    for controller in controllers(entry):
        script(controller, day())
    await settle(hass, freezer)

    failing, working = controllers(entry)
    assert [c.member_id for c in cover_calls(hass)] == [covers[1]]
    own = failing.state.members[0].last_own_command
    assert own is not None
    assert own.failed
    assert own.context_id is not None
    other = working.state.members[0].last_own_command
    assert other is not None
    assert not other.failed
    assert other.context_id == cover_calls(hass)[0].context_id
    # The status shows the result too.
    assert failing.status.commands[0].command == own
    logged = [
        r for r in caplog.records if "failed (HomeAssistantError)" in r.getMessage()
    ]
    assert len(logged) == 1
    assert "Example window 0" in logged[0].getMessage()
    assert logged[0].levelno == logging.WARNING


async def test_a_failure_is_logged_once_until_a_call_works_again(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Repeated failures of one cover stay quiet; the recovery is logged."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    failing = {COVER}
    fail_for(hass, failing)
    caplog.set_level(logging.INFO, logger="custom_components.roller_shutter_suite")
    window = Window()
    port = bind(actuator_of(hass), window)

    for index in range(3):
        port.move_to(f"command-{index}", COVER, FULLY_OPEN, decision=FIRE)
        await hass.async_block_till_done()
    failing.clear()
    port.move_to("command-9", COVER, FULLY_OPEN, decision=FIRE)
    await hass.async_block_till_done()

    messages = [r.getMessage() for r in caplog.records]
    assert len([m for m in messages if "failed (HomeAssistantError)" in m]) == 1
    assert len([m for m in messages if "accepts commands again" in m]) == 1
    assert [r.failed for r in window.results] == [True, True, True, False]


async def test_a_member_without_feedback_whose_command_failed_is_sent_again(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Gate rule 3 does not take a failed command for a reached target."""
    set_cover(hass, COVER, position=None, state="closed")
    entry = await setup_window(hass, covers_present=False)
    fail_for(hass, {COVER})
    await settle(hass, freezer)
    controller = controller_of(entry)
    own = controller.state.members[0].last_own_command
    assert own is not None
    assert own.failed
    assert cover_calls(hass) == []

    register_cover_services(hass)
    # The command stays pending until its expectation window has closed, and
    # the comfort wish is no fresh one: the minimum interval of motor
    # protection runs from the failed send as well.
    end = member_expectation_end(controller.config.members[0], own)
    assert end < own.time + controller.config.motor_min_interval
    freezer.move_to(own.time + controller.config.motor_min_interval)
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    await settle(hass, freezer)

    assert [c.target.value for c in cover_calls(hass)] == [100]
    decision_now = controller.status.decision
    assert decision_now is not None
    assert decision_now.gate is not None
    assert decision_now.gate.reason is ReasonCode.SENT


# ---------------------------------------------------------------------------
# Lifetime: reload, windows without a controller, shutdown
# ---------------------------------------------------------------------------


async def test_a_result_for_a_window_without_a_controller_is_handed_over_later(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """A queued command of a window that stopped is dropped and reported as failed."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    set_cover(hass, "cover.example_other", position=50)
    actuator = actuator_of(hass)
    bind(actuator, Window(), gap=2).move_to(
        "command-a", "cover.example_other", FULLY_OPEN, decision=decision()
    )
    port = bind(actuator, Window(), gap=2, window_id="w2")
    port.move_to("command-b", COVER, FULLY_OPEN, decision=decision())
    port.release()
    port.release()  # a second release changes nothing

    await tick(hass, freezer, 1, 3)
    assert [c.member_id for c in cover_calls(hass)] == ["cover.example_other"]
    assert [r for r in caplog.records if "its window is not running" in r.getMessage()]

    later = Window()
    bind(actuator, later, window_id="w2")
    assert later.results == [CommandResult("command-b", COVER, None, failed=True)]


async def test_a_newer_binding_of_the_same_window_is_kept_on_release_of_the_older(
    hass: HomeAssistant,
) -> None:
    """A reload binds the new controller before the old one lets go at the latest."""
    set_cover(hass, COVER, features=CoverEntityFeature.STOP)
    actuator = actuator_of(hass)
    old_window, new_window = Window(), Window()
    old = bind(actuator, old_window)
    new = bind(actuator, new_window)

    old.release()
    new.move_to("command-1", COVER, FULLY_OPEN, decision=decision())
    await hass.async_block_till_done()

    assert old_window.results == []
    assert [r.command_id for r in new_window.results] == ["command-1"]


async def test_shutdown_drops_queued_commands_and_reports_them_as_failed(
    hass: HomeAssistant,
) -> None:
    """When Home Assistant stops, nothing queued is sent any more."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    set_cover(hass, "cover.example_other", position=50)
    actuator = actuator_of(hass)
    bind(actuator, Window(), gap=2).move_to(
        "command-a", "cover.example_other", FULLY_OPEN, decision=decision()
    )
    window = Window()
    bind(actuator, window, gap=2, window_id="w2").move_to(
        "command-b", COVER, FULLY_OPEN, decision=decision()
    )

    hass.bus.async_fire(EVENT_HOMEASSISTANT_STOP)
    await hass.async_block_till_done()

    assert window.results == [CommandResult("command-b", COVER, None, failed=True)]
    assert [c.member_id for c in cover_calls(hass)] == ["cover.example_other"]


async def test_removing_the_entry_forgets_the_actuator(hass: HomeAssistant) -> None:
    """A later entry starts with a fresh adapter."""
    actuator = actuator_of(hass)
    assert actuator_of(hass) is actuator

    forget_actuator(hass)
    forget_actuator(hass)  # nothing left to forget

    assert ACTUATOR_KEY not in hass.data
    assert actuator_of(hass) is not actuator


async def test_the_adapter_of_a_window_is_the_actuator_port_of_the_core(
    hass: HomeAssistant,
) -> None:
    """``move_to(command_id, member_id, target)`` works without the decision too."""
    register_cover_services(hass)
    set_cover(hass, COVER, position=50)
    window = Window()
    port: Actuator = bind(actuator_of(hass), window)

    port.move_to("command-1", COVER, Position(40))
    await hass.async_block_till_done()

    assert [(c.member_id, c.target.value) for c in cover_calls(hass)] == [(COVER, 40)]
    assert window.results[0].context_id == cover_calls(hass)[0].context_id


async def test_a_member_at_its_target_is_not_commanded(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Only the member that is away from the target within tolerance is called."""
    left, right = "cover.example_left", "cover.example_right"
    set_cover(hass, left, position=99)
    set_cover(hass, right, position=50)
    entry = await setup_window(
        hass, window_data([left, right]), covers_present=False, freezer=freezer
    )

    assert [c.member_id for c in cover_calls(hass)] == [right]
    controller = controller_of(entry)
    assert [m.member_id for m in controller.state.members] == [right]

    # While the right member travels, a recompute sends nothing again.
    set_cover(hass, right, position=60, state="opening")
    await settle(hass, freezer)
    assert len(cover_calls(hass)) == 1
    assert local(10, 0) < controller.status.last_recompute  # type: ignore[operator]
