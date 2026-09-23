"""The runtime: start-up, triggers, coalescing, isolation of windows, unload.

Time is controlled by the ``freezer`` fixture; no test sleeps. The schedule
of every window uses fixed times (``runtime_kit.FIXED_ROUTINE``), so the sun
plays no part except as data the runtime has to obtain.
"""

from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from datetime import timedelta
from typing import Any
from unittest.mock import patch

import pytest
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util.async_ import get_scheduled_timer_handles
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.roller_shutter_suite import controller as controller_module
from custom_components.roller_shutter_suite import runtime as runtime_module
from custom_components.roller_shutter_suite.const import (
    CONF_SETTINGS,
    MIN_WAKE_UP_DISTANCE,
    STARTUP_GRACE,
)
from custom_components.roller_shutter_suite.controller import (
    WAKE_UP_NEXT_ACTION,
    WAKE_UP_STARTUP_GRACE,
    Phase,
)
from custom_components.roller_shutter_suite.core.model import (
    Decision,
    GateKind,
    GateOutcome,
    GateRule,
    JsonObject,
    Layer,
    MemberTarget,
    Position,
    WindowState,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.storage import MemoryStorage, storage_of
from tests.ha.helpers import set_cover, setup_entry
from tests.ha.runtime_kit import (
    COVER,
    FIXED_ROUTINE,
    advance,
    commands_sent,
    controller_of,
    is_active,
    local,
    monday_morning,
    phase_of,
    runtime_of,
    settle,
    setup_window,
    window_data,
    window_subentry,
)

BURST = 10

_monday_morning = pytest.fixture(autouse=True)(monday_morning)


@dataclass
class Registered:
    """What the controllers registered with Home Assistant, and what still exists.

    Every listener and timer is known by the remover it came back with; a
    remover that was called takes its entry off ``alive``.
    """

    entities: dict[int, tuple[str, ...]] = field(default_factory=dict)
    timers: dict[int, str] = field(default_factory=dict)
    alive: set[int] = field(default_factory=set)

    def tracked(self) -> set[str]:
        """Return the entity IDs of the listeners that are not removed."""
        return {
            entity_id
            for key in self.alive
            if key in self.entities
            for entity_id in self.entities[key]
        }

    def live_timers(self) -> list[str]:
        """Return the kinds of the timers that are not cancelled."""
        return sorted(self.timers[key] for key in self.alive if key in self.timers)


@pytest.fixture
def registered() -> Iterator[Registered]:
    """Watch every listener and timer the controllers register and remove."""
    watched = Registered()

    def watch(name: str, kind: str | None) -> Any:
        original = getattr(controller_module, name)

        def registering(hass: HomeAssistant, *args: Any, **kwargs: Any) -> Any:
            remove = original(hass, *args, **kwargs)
            key = id(remove)
            if kind is None:
                watched.entities[key] = tuple(args[0])
            else:
                watched.timers[key] = kind
            watched.alive.add(key)

            def removing() -> None:
                watched.alive.discard(key)
                remove()

            return removing

        return patch.object(controller_module, name, registering)

    with (
        watch("async_track_state_change_event", None),
        watch("async_track_time_interval", "interval"),
        watch("async_track_point_in_utc_time", "point_in_time"),
    ):
        yield watched


TIMER_KINDS = ("_on_debounce", "_TrackTimeInterval", "_TrackPointUTCTime")
"""The timers a controller can leave behind: the debouncer, the tick, a wake-up."""


def live_timers(hass: HomeAssistant) -> list[str]:
    """Return the kinds of the timer handles of the loop that are not cancelled.

    Only the kinds a controller uses are counted; Home Assistant's own
    delayed writes to its storage come and go on their own.
    """
    found: list[str] = []
    for handle in get_scheduled_timer_handles(hass.loop):
        if handle.cancelled():
            continue
        text = repr(handle)
        found.extend(kind for kind in TIMER_KINDS if kind in text)
    return sorted(found)


# ---------------------------------------------------------------------------
# Start-up and the first decision
# ---------------------------------------------------------------------------


async def test_no_decision_before_the_cover_is_available(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The window waits for its cover; when it appears, it decides without a reload."""
    entry = await setup_window(hass, covers_present=False, freezer=freezer)
    controller = controller_of(entry)

    assert entry.state is ConfigEntryState.LOADED
    assert phase_of(controller) is Phase.WAITING_FOR_MEMBERS
    assert controller.status == replace(controller.status, decision=None, wake_up=None)

    # Twenty minutes later the cover platform comes up. No reload happens.
    freezer.tick(timedelta(minutes=20))
    set_cover(hass, COVER, position=50)
    await settle(hass, freezer)

    assert phase_of(controller) is Phase.RUNNING
    decision = controller.status.decision
    assert decision is not None
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    assert [c.target.value for c in commands_sent(entry)] == [100]


async def test_window_with_a_cover_that_stays_away_reports_it_and_the_entry_loads(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A cover that never comes is the state of the window, not a failure of the entry."""
    entry = await setup_window(hass, covers_present=False, freezer=freezer)

    await advance(hass, freezer, local(10, 0) + STARTUP_GRACE + timedelta(minutes=10))

    assert entry.state is ConfigEntryState.LOADED
    status = controller_of(entry).status
    assert status.phase is Phase.WAITING_FOR_MEMBERS
    assert status.observation is not None
    assert not status.observation.available


async def test_window_with_two_members_waits_for_both_until_the_grace_has_passed(
    hass: HomeAssistant, freezer: Any
) -> None:
    """One member is up, the other not: wait for the grace, then decide with what is there."""
    set_cover(hass, "cover.example_left", position=100)
    entry = await setup_window(
        hass,
        window_data(["cover.example_left", "cover.example_right"]),
        covers_present=False,
        freezer=freezer,
    )
    controller = controller_of(entry)

    assert phase_of(controller) is Phase.WAITING_FOR_MEMBERS
    assert controller.status.wake_up is not None
    assert controller.status.wake_up.reason == WAKE_UP_STARTUP_GRACE
    assert controller.status.wake_up.at == local(10, 0) + STARTUP_GRACE

    await advance(hass, freezer, local(10, 0) + STARTUP_GRACE)

    assert phase_of(controller) is Phase.RUNNING
    assert controller.status.decision is not None


async def test_after_the_grace_a_silent_member_stays_unknown_and_the_gate_handles_it(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Three members, one never reports: after the grace the window decides with what is known.

    The silent member gets no assumed position and no assumed capability;
    only the members that are there are commanded (section 9). When none of
    the addressed members is available any more, the gate defers with
    ``cover_unavailable``.
    """
    left, middle, silent = (
        "cover.example_left",
        "cover.example_middle",
        "cover.example_silent",
    )
    set_cover(hass, left, position=50)
    set_cover(hass, middle, position=50)
    entry = await setup_window(
        hass,
        window_data([left, middle, silent]),
        covers_present=False,
        freezer=freezer,
    )
    controller = controller_of(entry)
    assert phase_of(controller) is Phase.WAITING_FOR_MEMBERS
    assert commands_sent(entry) == []

    await advance(hass, freezer, local(10, 0) + STARTUP_GRACE)

    assert phase_of(controller) is Phase.RUNNING
    profiles = {m.member_id: m.capabilities for m in controller.config.members}
    assert not profiles[silent].capabilities_known
    assert profiles[left].capabilities_known
    observation = controller.status.observation
    assert observation is not None
    observed = {m.member_id: m.observation for m in observation.members}
    assert not observed[silent].available
    assert observed[silent].position is None
    assert observed[left].available
    decision = controller.status.decision
    assert decision is not None
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    assert sorted(c.member_id for c in commands_sent(entry)) == [left, middle]
    assert silent not in controller.state.commanded_targets

    # The members that were there go away: no addressed member can execute.
    hass.states.async_set(left, "unavailable")
    hass.states.async_set(middle, "unavailable")
    await settle(hass, freezer)

    decision = controller.status.decision
    assert decision is not None
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.COVER_UNAVAILABLE
    assert sorted(c.member_id for c in commands_sent(entry)) == [left, middle]
    assert not controller.config.members[2].capabilities.capabilities_known


async def test_windows_start_in_dry_run_and_nothing_is_sent(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The dry-run of the subentry reaches the arbiter; the record shows the would-be command."""
    set_cover(hass, COVER, position=50)
    entry = await setup_window(
        hass, window_data(dry_run=True), covers_present=False, freezer=freezer
    )

    decision = controller_of(entry).status.decision
    assert decision is not None
    assert decision.gate is not None
    assert decision.gate.dry_run
    assert decision.gate.reason is ReasonCode.DRY_RUN
    assert [t.position.value for t in decision.gate.would_send if t.position] == [100]
    assert commands_sent(entry) == []


# ---------------------------------------------------------------------------
# Triggers
# ---------------------------------------------------------------------------


async def test_a_burst_of_ten_state_changes_causes_one_recompute(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Ten changes within a second are coalesced into one recompute."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    before = controller.status.recomputes

    for position in range(BURST):
        set_cover(hass, COVER, position=100 - position)
        freezer.tick(timedelta(milliseconds=50))
        await hass.async_block_till_done()
    assert controller.status.recomputes == before
    await settle(hass, freezer)

    assert controller.status.recomputes == before + 1


async def test_a_change_of_a_source_triggers_a_recompute(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The entities of the sources are listened to like the members."""
    hass.states.async_set("binary_sensor.example_workday", "on")
    entry = await setup_window(
        hass,
        window_data(
            settings={"schedule_workday_source": "binary_sensor.example_workday"}
        ),
        freezer=freezer,
    )
    controller = controller_of(entry)
    before = controller.status.recomputes

    hass.states.async_set("binary_sensor.example_workday", "off")
    await settle(hass, freezer)

    assert controller.status.recomputes == before + 1
    reading = controller.status.sources["binary_sensor.example_workday"]
    assert reading.value.value is False


async def test_the_next_planned_action_wakes_the_window_up(
    hass: HomeAssistant, freezer: Any
) -> None:
    """At the evening trigger the window is recomputed and wishes the night position."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    assert controller.status.wake_up is not None
    assert controller.status.wake_up.reason == WAKE_UP_NEXT_ACTION
    assert controller.status.wake_up.at == local(20, 0)

    await advance(hass, freezer, local(20, 0))

    decision = controller.status.decision
    assert decision is not None
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.SCHEDULE_NIGHT
    assert [c.target.value for c in commands_sent(entry)] == [0]


async def test_the_safety_tick_recomputes_without_any_trigger(
    hass: HomeAssistant, freezer: Any
) -> None:
    """Nothing changes, no wake-up is due, and the window is still looked at."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    before = controller.status.recomputes

    await advance(hass, freezer, local(10, 0) + timedelta(minutes=6))

    assert controller.status.recomputes > before


# ---------------------------------------------------------------------------
# Listeners and timers: one window does not touch the others
# ---------------------------------------------------------------------------


async def test_adding_reloading_and_removing_one_window_leaves_the_others_alone(
    hass: HomeAssistant, freezer: Any, registered: Registered
) -> None:
    """The listeners and timers of the other windows are untouched; unload leaves none."""
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_right")
    idle_timers = live_timers(hass)
    entry = await setup_entry(
        hass,
        {CONF_SETTINGS: FIXED_ROUTINE},
        subentries=[
            window_subentry("Left", "left", window_data(["cover.example_left"])),
        ],
    )
    await settle(hass, freezer)
    runtime = runtime_of(entry)
    left = runtime.windows["left"]
    assert registered.tracked() == {"cover.example_left"}
    # The safety tick and the wake-up at the evening trigger.
    assert registered.live_timers() == ["interval", "point_in_time"]
    left_alive = set(registered.alive)

    # Add a second window inside the running runtime: the first is untouched.
    template = entry.runtime_data.windows["left"]
    config = template.resolution.config
    assert config is not None
    right = replace(
        template,
        subentry_id="right",
        title="Right",
        resolution=replace(
            template.resolution,
            config=replace(
                config,
                window_id="right",
                members=(replace(config.members[0], member_id="cover.example_right"),),
            ),
        ),
    )
    assert runtime.async_add_window(right)
    await settle(hass, freezer)
    assert set(runtime.windows) == {"left", "right"}
    assert runtime.windows["left"] is left
    assert left_alive <= registered.alive
    assert registered.tracked() == {"cover.example_left", "cover.example_right"}
    assert registered.live_timers() == [
        "interval",
        "interval",
        "point_in_time",
        "point_in_time",
    ]

    # Reload one window: its own listener and timers are replaced, the other's stay.
    right_controller = runtime.windows["right"]
    assert runtime.async_reload_window(right)
    await settle(hass, freezer)
    assert not is_active(right_controller)
    assert runtime.windows["right"] is not right_controller
    assert runtime.windows["left"] is left
    assert is_active(left)
    assert left_alive <= registered.alive
    assert registered.live_timers() == [
        "interval",
        "interval",
        "point_in_time",
        "point_in_time",
    ]

    # Remove one window: the other keeps listening.
    runtime.async_remove_window("right")
    assert set(runtime.windows) == {"left"}
    assert is_active(left)
    assert registered.alive == left_alive
    assert registered.tracked() == {"cover.example_left"}

    # Unload: no listener and no timer of the integration remains.
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not is_active(left)
    assert registered.alive == set()
    assert registered.tracked() == set()
    assert live_timers(hass) == idle_timers


async def test_one_faulty_window_does_not_stop_the_others(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """The controller of one window raises: the other decides, the entry is loaded."""
    set_cover(hass, "cover.example_left")
    set_cover(hass, "cover.example_right", position=50)

    def failing(*args: Any, **kwargs: Any) -> Any:
        if kwargs.get("window_id") == "left":
            raise RuntimeError("the controller of this window cannot be built")
        return controller_module.WindowController(*args, **kwargs)

    with patch.object(runtime_module, "WindowController", failing):
        entry = await setup_entry(
            hass,
            {CONF_SETTINGS: FIXED_ROUTINE},
            subentries=[
                window_subentry("Left", "left", window_data(["cover.example_left"])),
                window_subentry("Right", "right", window_data(["cover.example_right"])),
            ],
        )
        await settle(hass, freezer)

    assert entry.state is ConfigEntryState.LOADED
    runtime = runtime_of(entry)
    assert set(runtime.windows) == {"right"}
    assert runtime.failed == {"left": "RuntimeError"}
    decision = runtime.windows["right"].status.decision
    assert decision is not None
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
    logged = [r for r in caplog.records if "Left" in r.getMessage()]
    assert len(logged) == 1
    assert "RuntimeError" in logged[0].getMessage()
    assert "cannot be built" not in logged[0].getMessage()


async def test_a_start_that_raises_after_registering_leaks_no_listener(
    hass: HomeAssistant, freezer: Any, registered: Registered
) -> None:
    """Whatever the start registered before it raised is released again."""
    entry = await setup_window(hass, freezer=freezer)
    runtime = runtime_of(entry)
    window = replace(entry.runtime_data.windows["w1"], subentry_id="w2", title="Second")
    alive_before = set(registered.alive)

    class StartsThenRaises(controller_module.WindowController):
        def async_start(self) -> None:
            super().async_start()
            raise RuntimeError("after the listeners were registered")

    with patch.object(runtime_module, "WindowController", StartsThenRaises):
        assert not runtime.async_add_window(window)

    assert runtime.failed == {"w2": "RuntimeError"}
    assert set(runtime.windows) == {"w1"}
    assert registered.alive == alive_before

    # A start that fails before the state was read writes nothing back.
    stored: JsonObject = {"schema_version": 999}
    storage_of(hass).save_window_state("w2", stored)

    def refusing(storage: MemoryStorage, window_id: str) -> Any:
        raise OSError("the storage cannot be read")

    with patch.object(MemoryStorage, "load_window_state", refusing):
        assert not runtime.async_add_window(window)
    assert runtime.failed == {"w2": "OSError"}
    assert storage_of(hass).windows["w2"] == stored


async def test_window_whose_configuration_is_withheld_is_left_out(
    hass: HomeAssistant, freezer: Any
) -> None:
    """A window without a configuration gets no controller and the others run."""
    entry = await setup_window(hass, freezer=freezer)
    window = entry.runtime_data.windows["w1"]
    withheld = replace(
        window, resolution=replace(window.resolution, config=None), subentry_id="w2"
    )
    runtime = runtime_of(entry)

    assert not runtime.async_add_window(withheld)

    assert runtime.failed == {"w2": runtime_module.CONFIGURATION_WITHHELD}
    assert set(runtime.windows) == {"w1"}


# ---------------------------------------------------------------------------
# Wake-ups cannot form a loop
# ---------------------------------------------------------------------------


async def test_a_core_that_keeps_asking_for_now_cannot_spin(
    hass: HomeAssistant, freezer: Any, caplog: pytest.LogCaptureFixture
) -> None:
    """A wake-up at "now" is refused, moved by the minimum distance, and logged once."""
    entry = await setup_window(hass, freezer=freezer)
    controller = controller_of(entry)
    controller.engine = WakeMeAtOnce()  # type: ignore[assignment]
    before = controller.status.recomputes
    controller.async_request_recompute()
    await settle(hass, freezer)

    # One minute of wake-ups, fired as they come due.
    now = local(10, 0) + timedelta(seconds=2)
    for _ in range(60):
        now += timedelta(seconds=1)
        freezer.move_to(now)
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

    recomputes = controller.status.recomputes - before
    at_most = 60 / MIN_WAKE_UP_DISTANCE.total_seconds() + 2
    assert 1 < recomputes <= at_most
    refusals = [r for r in caplog.records if "asked to be woken" in r.getMessage()]
    assert len(refusals) == 1
    assert controller.status.wake_up is not None
    assert controller.status.last_recompute is not None
    assert controller.status.wake_up.at > controller.status.last_recompute


class WakeMeAtOnce:
    """An engine whose every decision asks to be re-evaluated no later than now."""

    def recompute(self, snapshot: WorldSnapshot) -> Decision:
        """Defer the night wish "until now"."""
        members = tuple(
            MemberTarget(member.member_id, Position(0))
            for member in snapshot.observation.members
        )
        return Decision(
            winning_wish=Wish.target_per_member(
                Layer.SCHEDULE, ReasonCode.SCHEDULE_NIGHT, members
            ),
            targets=members,
            gate=GateOutcome.defer(
                GateRule.MOVEMENT_IN_FLIGHT,
                ReasonCode.MOVEMENT_IN_FLIGHT,
                reevaluate_no_later_than=snapshot.time,
            ),
        )

    def state_after(self, snapshot: WorldSnapshot, decision: Decision) -> WindowState:
        """Change nothing."""
        del decision
        return snapshot.state
