"""The safety proof for the pilot: a window in dry-run never moves its cover.

The integration is set up the way a user sets it up: the house through the
config flow, one group and two windows through their subentry flows. Every
new window starts in dry-run. The window "Example window" stays in dry-run;
the window "Control window" is armed, which is the proof that the test would
notice a call: it does move. The control window is armed the way a user arms
it: through the page "dry-run or armed" of its reconfigure flow and the page
of the checks that follows; the update listener reloads the entry once, as
after every change, and the window starts armed with a clean state. Nothing
here sets a fact of the version: the runtime notices a movement by hand
(``MOVEMENT_DETECTION_WIRED`` ships true since block H10), and the page of
each cover states it as event-driven, as arming requires.

No cover platform is loaded. The three cover actions are stand-ins that
record every call (``runtime_kit.register_cover_services``), and the covers
are states the test writes, as the other controller would move them. After
a call to the control cover, the test writes the commanded position as that
cover's state, as an obedient actuator would report it.

The time is frozen and moved by the test through a whole workday and into
the next morning. The sun is the invented sun of ``runtime_kit`` (sunrise
06:00, sunset 18:00); the house keeps the built-in values of its form:
workdays open at 07:00, the evening begins at sunset, not before 17:00.
"""

import itertools
from datetime import date, datetime
from typing import Any

import pytest
from homeassistant.config_entries import (
    SOURCE_RECONFIGURE,
    SOURCE_USER,
    ConfigEntry,
    ConfigEntryState,
    SubentryFlowContext,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import (
    Context,
    Event,
    EventStateChangedData,
    HomeAssistant,
    callback,
)
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event

from custom_components.roller_shutter_suite import controller as controller_module
from custom_components.roller_shutter_suite.actuator import (
    ACTUATOR_KEY,
    forget_actuator,
)
from custom_components.roller_shutter_suite.const import (
    CONF_DRY_RUN,
    DOMAIN,
    SUBENTRY_GROUP,
    SUBENTRY_WINDOW,
)
from custom_components.roller_shutter_suite.controller import WindowController
from custom_components.roller_shutter_suite.controls import BLIND_MEMORY_KEY
from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    LayerRegistration,
)
from custom_components.roller_shutter_suite.core.engine import (
    FEATURE_LAYERS,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    FunctionId,
    Layer,
    PositionOwner,
    WindowState,
)
from custom_components.roller_shutter_suite.events import HISTORY_KEY, forget_history
from custom_components.roller_shutter_suite.flow.window_flow import ARMING_CHECKS
from custom_components.roller_shutter_suite.storage import STORAGE_KEY, forget_storage
from tests.ha.helpers import ROUTINE_HOUSE, routine_inherit, set_cover
from tests.ha.runtime_kit import (
    CoverCall,
    advance,
    cover_calls,
    local,
    register_cover_services,
    settle,
)
from tests.ha.status_kit import (
    DRY_RUN,
    NEXT_ACTION,
    OVERRIDE,
    REASON,
    FireAlarm,
    collect_reason_events,
    state_of,
)

DRY_COVER = "cover.example_window"
"""The cover of the window in dry-run; the other controller still moves it."""

CONTROL_COVER = "cover.example_control"
"""The cover of the armed control window."""

CONTROL_REASON = "sensor.control_window_reason"
CONTROL_DRY_RUN = "binary_sensor.control_window_dry_run"

TUESDAY = date(2026, 9, 22)

EVENING_POSITION = 20
"""The evening position the reconfigure gives the window in dry-run."""

EVENT_DRIVEN_PAGE: dict[str, Any] = {
    "position_source": "calculated",
    "reporting_kind": "event_driven",
    "reporting_time": 0,
}
"""The page of the cover as a user fills it for a cover that reports at once.

Both windows state it, so the movement tracker follows the window in dry-run
as well: every movement of the other controller is observed there, and still
nothing is sent. Arming requires it (rulings of the project owner,
2026-09-29 and 2026-10-01).
"""


@pytest.fixture(autouse=True)
async def _early_monday(hass: HomeAssistant, freezer: Any) -> None:
    """Start on Monday at 05:00, before the morning, in a named zone."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(local(5, 0))


@pytest.fixture
def fire_alarm(monkeypatch: pytest.MonkeyPatch) -> FireAlarm:
    """Give every controller a stub fire layer and the real gate rules.

    The integration has no fire layer yet. Every controller builds its
    engine with ``build_arbiter`` when it is created, also after a reload
    or a restart, so the stub is put there and reaches each new controller.
    """
    alarm = FireAlarm()

    def with_fire() -> Arbiter:
        return build_arbiter(
            [
                *FEATURE_LAYERS,
                LayerRegistration(Layer.FIRE, alarm.layer, FunctionId.FIRE),
            ]
        )

    monkeypatch.setattr(controller_module, "build_arbiter", with_fire)
    return alarm


# ---------------------------------------------------------------------------
# Setting the installation up as a user does
# ---------------------------------------------------------------------------


async def _flow_step(
    hass: HomeAssistant, result: Any, user_input: dict[str, Any]
) -> Any:
    assert result["type"] is FlowResultType.FORM, result
    following = await hass.config_entries.subentries.async_configure(
        result["flow_id"], user_input
    )
    await hass.async_block_till_done()
    return following


async def _subentry_flow(
    hass: HomeAssistant,
    entry: ConfigEntry,
    subentry_type: str,
    inputs: list[dict[str, Any]],
    reconfigure: str | None = None,
) -> Any:
    context: SubentryFlowContext = (
        {"source": SOURCE_USER}
        if reconfigure is None
        else {"source": SOURCE_RECONFIGURE, "subentry_id": reconfigure}
    )
    result = await hass.config_entries.subentries.async_init(
        (entry.entry_id, subentry_type), context=context
    )
    for user_input in inputs:
        result = await _flow_step(hass, result, user_input)
    return result


def _subentry_id(entry: ConfigEntry, title: str) -> str:
    return next(s.subentry_id for s in entry.subentries.values() if s.title == title)


async def _install(hass: HomeAssistant, freezer: Any) -> ConfigEntry:
    """Add the house, one group and two windows through the forms; arm one."""
    register_cover_services(hass)
    # Night: both shutters are closed.
    set_cover(hass, DRY_COVER, position=0, state="closed")
    set_cover(hass, CONTROL_COVER, position=0, state="closed")

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    for user_input in [{}, *ROUTINE_HOUSE]:
        assert result["type"] is FlowResultType.FORM, result
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    entry: ConfigEntry = result["result"]

    created = await _subentry_flow(
        hass, entry, SUBENTRY_GROUP, [{"name": "Example group"}, *routine_inherit()]
    )
    assert created["type"] is FlowResultType.CREATE_ENTRY, created
    group_id = _subentry_id(entry, "Example group")
    for name, cover in (
        ("Example window", DRY_COVER),
        ("Control window", CONTROL_COVER),
    ):
        created = await _subentry_flow(
            hass,
            entry,
            SUBENTRY_WINDOW,
            [
                {"name": name, "covers": [cover], "group_id": group_id},
                *routine_inherit(),
                EVENT_DRIVEN_PAGE,
            ],
        )
        assert created["type"] is FlowResultType.CREATE_ENTRY, created

    # Every new window starts in dry-run: the forms never ask for it.
    for subentry in entry.subentries.values():
        if subentry.subentry_type == SUBENTRY_WINDOW:
            assert subentry.data[CONF_DRY_RUN] is True

    # Arm the control window through its form: dry-run or armed, then the checks.
    control_id = _subentry_id(entry, "Control window")
    armed = await _subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Control window", "covers": [CONTROL_COVER], "group_id": group_id},
            *routine_inherit(),
            EVENT_DRIVEN_PAGE,
            {"operation": "armed"},
            dict.fromkeys(ARMING_CHECKS, True),
        ],
        reconfigure=control_id,
    )
    assert armed["reason"] == "reconfigure_successful"
    assert entry.subentries[control_id].data[CONF_DRY_RUN] is False
    await settle(hass, freezer)
    assert entry.state is ConfigEntryState.LOADED
    # Armed with a clean state: no dam, nothing simulated, nobody owns the position.
    control_state = _controller(entry, "Control window").state
    assert control_state.simulated is None
    assert control_state.manual_override is None
    assert control_state.person_at_window is None
    return entry


def _controller(entry: ConfigEntry, title: str) -> WindowController:
    controller: WindowController = entry.runtime_data.runtime.windows[
        _subentry_id(entry, title)
    ]
    return controller


def _calls_to(hass: HomeAssistant, cover: str) -> list[CoverCall]:
    return [call for call in cover_calls(hass) if call.member_id == cover]


async def _obey(hass: HomeAssistant, freezer: Any) -> None:
    """Report the last commanded position of the control cover as its state."""
    calls = _calls_to(hass, CONTROL_COVER)
    if calls:
        target = calls[-1].target.value
        set_cover(
            hass, CONTROL_COVER, position=target, state="open" if target else "closed"
        )
        await settle(hass, freezer)


async def _other_controller_moves(
    hass: HomeAssistant, freezer: Any, position: int
) -> None:
    """Let the old controller move the cover of the window in dry-run."""
    set_cover(
        hass, DRY_COVER, position=position, state="open" if position else "closed"
    )
    await settle(hass, freezer)


async def _at(hass: HomeAssistant, freezer: Any, when: datetime) -> None:
    await advance(hass, freezer, when)
    await _obey(hass, freezer)


def _clean_state(state: WindowState) -> None:
    """No dam, no owner, no real own command: dry-run touches nothing real."""
    assert state.manual_override is None
    assert state.person_at_window is None
    assert state.owner is PositionOwner.UNKNOWN
    assert state.last_comfort_movement is None
    assert all(member.last_own_command is None for member in state.members)


async def _restart(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Stop the entry, lose what lives in memory only, and start it again.

    A restart of Home Assistant keeps the config entry, the registries and
    the states Home Assistant restores, and loses everything this version
    keeps in memory: the state of every window, the memory of the reason
    events and the queue of the actuator (persistence is block H05).
    """
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    forget_storage(hass)
    forget_history(hass)
    forget_actuator(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


def _reason_log(hass: HomeAssistant) -> list[tuple[str, dict[str, Any]]]:
    """Return a list that fills with every state the reason sensor takes."""
    seen: list[tuple[str, dict[str, Any]]] = []

    @callback
    def _record(event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is not None:
            seen.append((new.state, dict(new.attributes)))

    async_track_state_change_event(hass, [REASON], _record)
    return seen


def _record_of(hass: HomeAssistant) -> dict[str, Any]:
    """Return the decision record of the window in dry-run, as its sensor shows it."""
    return dict(state_of(hass, REASON).attributes)


# ---------------------------------------------------------------------------
# The proof
# ---------------------------------------------------------------------------


async def test_a_window_in_dry_run_moves_nothing_through_a_whole_pilot_day(  # noqa: PLR0915 - one day, in order
    hass: HomeAssistant, freezer: Any, fire_alarm: FireAlarm
) -> None:
    """Zero calls to the dry-run cover; the armed control window does move.

    A full day with the other controller moving the same cover, a restart,
    a reload, a reconfigure, an unavailable cover that returns and a stub
    fire alarm. The decisions keep showing the hypothetical outcome, never
    ``manual_override``; no dam is armed.
    """
    fired = collect_reason_events(hass)
    reasons = _reason_log(hass)
    entry = await _install(hass, freezer)
    dry = _subentry_id(entry, "Example window")

    # 05:00, night: both shutters are where the night wants them.
    assert state_of(hass, REASON).state == "schedule_night"
    assert _record_of(hass)["gate_reason"] == "target_reached"
    assert _record_of(hass)["dry_run"] is True
    assert state_of(hass, DRY_RUN).state == STATE_ON
    assert state_of(hass, CONTROL_DRY_RUN).state == STATE_OFF
    assert state_of(hass, OVERRIDE).state == STATE_OFF
    next_action = state_of(hass, NEXT_ACTION)
    assert datetime.fromisoformat(next_action.state) == local(7, 0)
    assert next_action.attributes["target"] == 100  # noqa: PLR2004
    assert next_action.attributes["reason"] == "schedule_day"

    # 07:00, the morning: the control window opens, the dry-run window would.
    await _at(hass, freezer, local(7, 0, second=1))
    assert [c.target.value for c in _calls_to(hass, CONTROL_COVER)] == [100]
    assert state_of(hass, REASON).state == "dry_run"
    assert _record_of(hass)["would_send"] == 100  # noqa: PLR2004
    assert _record_of(hass)["wish_reason"] == "schedule_day"
    # The two windows fire in no fixed order; the last one of the window counts.
    morning = [e for e in fired if e["subentry_id"] == dry][-1]
    assert morning["reason"] == "dry_run"
    assert morning["wish_reason"] == "schedule_day"
    assert morning["dry_run"] is True

    # 07:05: the other controller opens the shutter. Where it put it is
    # where this integration wanted it.
    freezer.move_to(local(7, 5))
    await _other_controller_moves(hass, freezer, 100)
    assert state_of(hass, REASON).state == "schedule_day"
    assert _record_of(hass)["gate_reason"] == "target_reached"

    # 12:00: the other controller lowers the shutter, as its shading would.
    # Observed, no dam: the record still reads "would have sent 100".
    freezer.move_to(local(12, 0))
    await _other_controller_moves(hass, freezer, 40)
    observed = _controller(entry, "Example window").status.observation
    assert observed is not None
    reported = observed.members[0].observation.position
    assert reported is not None
    assert reported.value == 40  # noqa: PLR2004
    assert state_of(hass, REASON).state == "dry_run"
    assert _record_of(hass)["would_send"] == 100  # noqa: PLR2004
    freezer.move_to(local(12, 30))
    await _other_controller_moves(hass, freezer, 100)
    assert _record_of(hass)["gate_reason"] == "target_reached"
    _clean_state(_controller(entry, "Example window").state)

    # 13:00, restart: nothing is persisted yet, and the schedule decision is
    # the same, because it is derived from the situation.
    freezer.move_to(local(13, 0))
    before = _record_of(hass)
    await _restart(hass, entry)
    await settle(hass, freezer)
    assert entry.state is ConfigEntryState.LOADED
    assert _record_of(hass) == before
    assert state_of(hass, DRY_RUN).state == STATE_ON
    assert _controller(entry, "Example window").state.simulated is None

    # 14:00, reload: the same.
    freezer.move_to(local(14, 0))
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    await settle(hass, freezer)
    assert _record_of(hass) == before

    # 15:00, reconfigure: the window gets an evening position of its own.
    # The last page offers dry-run or armed; the window stays in dry-run.
    freezer.move_to(local(15, 0))
    group_id = _subentry_id(entry, "Example group")
    result = await _subentry_flow(
        hass,
        entry,
        SUBENTRY_WINDOW,
        [
            {"name": "Example window", "covers": [DRY_COVER], "group_id": group_id},
            *routine_inherit({"schedule_evening_position": float(EVENING_POSITION)}),
            EVENT_DRIVEN_PAGE,
            {"operation": "dry_run"},
        ],
        reconfigure=dry,
    )
    assert result["reason"] == "reconfigure_successful"
    await settle(hass, freezer)
    assert entry.subentries[dry].data[CONF_DRY_RUN] is True
    assert state_of(hass, DRY_RUN).state == STATE_ON
    assert _record_of(hass)["gate_reason"] == "target_reached"

    # 16:00: the cover is unavailable, and returns ten minutes later.
    freezer.move_to(local(16, 0))
    hass.states.async_set(DRY_COVER, STATE_UNAVAILABLE)
    await settle(hass, freezer)
    assert state_of(hass, REASON).state == STATE_UNAVAILABLE
    freezer.move_to(local(16, 10))
    await _other_controller_moves(hass, freezer, 100)
    assert state_of(hass, REASON).state == "schedule_day"
    assert _record_of(hass)["gate_reason"] == "target_reached"

    # 18:00, the evening: the control window closes, the dry-run window
    # would close to its own evening position.
    await _at(hass, freezer, local(18, 0, second=1))
    assert [c.target.value for c in _calls_to(hass, CONTROL_COVER)] == [100, 0]
    assert state_of(hass, REASON).state == "dry_run"
    assert _record_of(hass)["would_send"] == EVENING_POSITION
    assert _record_of(hass)["wish_reason"] == "schedule_night"
    freezer.move_to(local(18, 10))
    await _other_controller_moves(hass, freezer, EVENING_POSITION)
    assert _record_of(hass)["gate_reason"] == "target_reached"

    # 19:00, a fire alarm: the event is fired at once. The control window
    # opens; the dry-run window records "would open" and stays where it is.
    freezer.move_to(local(19, 0))
    events_before = len(fired)
    fire_alarm.active = True
    for controller in entry.runtime_data.runtime.windows.values():
        controller.async_request_recompute()
    await settle(hass, freezer)
    await _obey(hass, freezer)
    fire_events = [e for e in fired[events_before:] if e["layer"] == "fire"]
    assert {e["subentry_id"] for e in fire_events} == set(
        entry.runtime_data.runtime.windows
    )
    dry_fire = next(e for e in fire_events if e["subentry_id"] == dry)
    assert dry_fire["reason"] == "dry_run"
    assert dry_fire["target"] == 100  # noqa: PLR2004
    assert state_of(hass, REASON).state == "dry_run"
    assert _record_of(hass)["wish_reason"] == "fire_alarm"
    assert _calls_to(hass, CONTROL_COVER)[-1].target.value == 100  # noqa: PLR2004

    # 19:10: the alarm is over (the stub has no acknowledgement phase).
    freezer.move_to(local(19, 10))
    fire_alarm.active = False
    for controller in entry.runtime_data.runtime.windows.values():
        controller.async_request_recompute()
    await settle(hass, freezer)
    await _obey(hass, freezer)

    # Tuesday 07:00, the next morning.
    await _at(hass, freezer, local(7, 0, day=TUESDAY, second=1))
    assert state_of(hass, REASON).state == "dry_run"
    assert _record_of(hass)["would_send"] == 100  # noqa: PLR2004

    # The proof: not one call to the cover of the window in dry-run, while
    # the armed window was commanded at every change of the day.
    assert _calls_to(hass, DRY_COVER) == []
    assert len(_calls_to(hass, CONTROL_COVER)) >= 4  # noqa: PLR2004
    assert {c.member_id for c in cover_calls(hass)} == {CONTROL_COVER}
    # Never a manual override, however often the other controller moved.
    assert reasons
    assert all(state != "manual_override" for state, _ in reasons)
    assert all(
        attributes.get("gate_reason") != "manual_override" for _, attributes in reasons
    )
    assert state_of(hass, OVERRIDE).state == STATE_OFF
    assert all(e["reason"] != "manual_override" for e in fired)
    assert all(e["dry_run"] is True for e in fired if e["subentry_id"] == dry)
    _clean_state(_controller(entry, "Example window").state)


async def test_every_movement_by_hand_of_the_dry_run_window_causes_no_call(
    hass: HomeAssistant, freezer: Any, hass_admin_user: Any
) -> None:
    """The tracker follows the window in dry-run; still not one call reaches its cover.

    Every movement by hand the test can make: a movement with transit states
    in both directions, a stop in mid-travel, a reversal, a jump without a
    transit state, a movement from a dashboard with a user in its context,
    an unavailable gap that returns elsewhere, and all of it around the
    morning, when the window would have sent a command. In dry-run nothing
    arms a dam, nobody owns the position, and no real command is recorded.
    """
    fired = collect_reason_events(hass)
    entry = await _install(hass, freezer)
    dry = _controller(entry, "Example window")

    def by_hand(state: str, position: int, **kwargs: Any) -> None:
        hass.states.async_set(
            DRY_COVER,
            state,
            {"supported_features": 15, "current_position": position},
            **kwargs,
        )

    moves: list[tuple[str, int]] = [
        ("opening", 0),
        ("opening", 40),
        ("open", 70),
        ("closing", 70),
        ("opening", 60),
        ("open", 80),
        ("open", 20),
        ("closing", 20),
        ("closed", 0),
    ]
    for when in (local(6, 30), local(7, 0, second=1), local(12, 0)):
        freezer.move_to(when)
        for state, position in moves:
            by_hand(state, position)
            await settle(hass, freezer, seconds=3)
        by_hand("opening", 0, context=Context(user_id=hass_admin_user.id))
        await settle(hass, freezer, seconds=3)
        by_hand("open", 100)
        await settle(hass, freezer, seconds=3)
        hass.states.async_set(DRY_COVER, STATE_UNAVAILABLE)
        await settle(hass, freezer, seconds=3)
        by_hand("open", 30)
        await settle(hass, freezer, seconds=10)
        await _obey(hass, freezer)

    assert _calls_to(hass, DRY_COVER) == []
    assert {c.member_id for c in cover_calls(hass)} <= {CONTROL_COVER}
    assert dry.config.members[0].capabilities.movement_detection_known is True
    _clean_state(dry.state)
    assert dry.state.members[0].position_reference.value == "referenced"
    assert state_of(hass, OVERRIDE).state == STATE_OFF
    # Observed and reported, and nothing else: the only event of the tracker
    # in dry-run.
    observed = [
        e for e in fired if e["subentry_id"] == dry.window_id and e["layer"] is None
    ]
    assert observed
    assert {e["reason"] for e in observed} == {"external_movement_observed"}
    assert all(e["dry_run"] is True for e in observed)


async def test_after_a_restart_in_the_night_the_decision_is_the_same(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The part of the day is derived from the time, not from a seen trigger."""
    entry = await _install(hass, freezer)
    await _at(hass, freezer, local(21, 0))
    await _other_controller_moves(hass, freezer, 0)
    before = _record_of(hass)
    next_action = state_of(hass, NEXT_ACTION).state
    assert before["wish_reason"] == "schedule_night"
    assert before["gate_reason"] == "target_reached"

    await _restart(hass, entry)
    await settle(hass, freezer)

    assert _record_of(hass) == before
    assert state_of(hass, NEXT_ACTION).state == next_action
    assert datetime.fromisoformat(next_action) == local(7, 0, day=TUESDAY)
    assert _calls_to(hass, DRY_COVER) == []


async def test_the_window_in_dry_run_would_act_after_a_restart_again(
    hass: HomeAssistant, freezer: Any
) -> None:
    """The simulated command is not persisted: the next record says "would send".

    Before the restart the record stands at "would have sent 100" from the
    morning; the other controller has not moved. After the restart the
    record is the same, and the reason event is fired once more, which the
    documentation says of a restart.
    """
    fired = collect_reason_events(hass)
    entry = await _install(hass, freezer)
    await _at(hass, freezer, local(7, 30))
    before = _record_of(hass)
    assert before["gate_reason"] == "dry_run"
    count = len([e for e in fired if e["reason"] == "dry_run"])

    await _restart(hass, entry)
    await settle(hass, freezer)

    assert _record_of(hass) == before
    assert len([e for e in fired if e["reason"] == "dry_run"]) == count + 1
    assert _calls_to(hass, DRY_COVER) == []


async def test_removing_the_integration_leaves_no_trace(
    hass: HomeAssistant, freezer: Any, hass_storage: dict[str, Any]
) -> None:
    """No entity, no device, no repair issue, nothing stored, nothing in memory."""
    entry = await _install(hass, freezer)
    await _at(hass, freezer, local(7, 30))
    entity_ids = [
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
    ]
    assert REASON in entity_ids
    assert dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id)

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()

    assert hass.config_entries.async_entries(DOMAIN) == []
    assert er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id) == []
    assert [
        e for e in er.async_get(hass).entities.values() if e.platform == DOMAIN
    ] == []
    assert dr.async_entries_for_config_entry(dr.async_get(hass), entry.entry_id) == []
    assert [i for i in ir.async_get(hass).issues.values() if i.domain == DOMAIN] == []
    assert all(hass.states.get(entity_id) is None for entity_id in entity_ids)
    for key in (STORAGE_KEY, HISTORY_KEY, ACTUATOR_KEY, BLIND_MEMORY_KEY):
        assert key not in hass.data
    # The integration writes no storage file of its own; nothing names it.
    assert [key for key in hass_storage if DOMAIN in key] == []
    assert _calls_to(hass, DRY_COVER) == []


# ---------------------------------------------------------------------------
# Every control of every level, in every combination
# ---------------------------------------------------------------------------

_LEVELS = ("roller_shutter_suite", "example_group", "example_window")
"""The house, the group and the window in dry-run, as their entity IDs begin."""

_STATES = ("neutral", "paused", "locked", "protection_only", "off")
"""What one level can say: nothing, pause, maintenance lock, or a mode."""


async def _set_level(hass: HomeAssistant, level: str, state: str) -> None:
    """Switch the controls of one level through their entities, as a user does."""
    await hass.services.async_call(
        "switch",
        "turn_on" if state == "paused" else "turn_off",
        {"entity_id": f"switch.{level}_pause"},
        blocking=True,
    )
    await hass.services.async_call(
        "switch",
        "turn_on" if state == "locked" else "turn_off",
        {"entity_id": f"switch.{level}_maintenance_lock"},
        blocking=True,
    )
    mode = state if state in ("protection_only", "off") else "automatic"
    await hass.services.async_call(
        "select",
        "select_option",
        {"entity_id": f"select.{level}_operating_mode", "option": mode},
        blocking=True,
    )


async def test_no_combination_of_the_controls_moves_the_window_in_dry_run(
    hass: HomeAssistant, freezer: Any, fire_alarm: FireAlarm
) -> None:
    """Pause, lock and mode on the house, the group and the window, each combination.

    At 07:00 the daily routine wants the shutters open. Every combination of
    the five states of the three levels is set through the entities, with the
    stub fire alarm off and on. The window in dry-run records what it would
    do and never calls its cover, and no change reloads the entry. The armed
    control window is commanded at least once during the combinations, which
    shows that the test would notice a call.

    """
    entry = await _install(hass, freezer)
    await _at(hass, freezer, local(7, 0, second=1))
    reloads = entry.runtime_data
    combinations = list(itertools.product(_STATES, repeat=len(_LEVELS)))
    assert len(combinations) == 125  # noqa: PLR2004 - five states, three levels

    for alarm in (False, True):
        fire_alarm.active = alarm
        for combination in combinations:
            for level, state in zip(_LEVELS, combination, strict=True):
                await _set_level(hass, level, state)
            await settle(hass, freezer)
            assert _calls_to(hass, DRY_COVER) == [], (alarm, combination)
            assert state_of(hass, REASON).state != STATE_UNAVAILABLE

    # No change of a control reloaded the entry.
    assert entry.runtime_data is reloads
    assert _calls_to(hass, DRY_COVER) == []
    assert _calls_to(hass, CONTROL_COVER)
    _clean_state(_controller(entry, "Example window").state)
