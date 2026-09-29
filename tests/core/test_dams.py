"""Arming and ending the two dams (section 3 of the specification, ``core/dams``).

The end rules of the manual override (E2), the person-at-the-window dam and
what it turns into, the clock that keeps running during a protection event
(decision 4), and the wake-ups a caller has to arm for all of it. The end at
the next part of the day needs the real schedule and is shown in the
time-lapse simulation (``tests/core/test_sim_tracking.py``).
"""

from dataclasses import replace
from datetime import timedelta

import pytest

from custom_components.roller_shutter_suite.core import dams as dams_module
from custom_components.roller_shutter_suite.core.arbiter import (
    override_ended_by_condition,
    room_empty_long_enough,
    wake_ups,
)
from custom_components.roller_shutter_suite.core.dams import (
    arm_after_external_movement,
    armed_since,
    end_override,
    new_override,
    protection_winning,
    update_dams,
    update_remembered_position,
    window_position,
)
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    FULLY_CLOSED,
    Decision,
    Layer,
    ManualOverrideDam,
    MemberCommand,
    MemberState,
    MemberTracking,
    OverrideEndRule,
    OwnCommand,
    PersonAtWindowDam,
    Position,
    PositionOwner,
    ShadingEpisodeState,
    SimulatedState,
    SourceValue,
    TrackerPhase,
    TravelDirection,
    WindowConfig,
    WindowState,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.schedule import evaluate_schedule
from tests.core.arbiter_kit import (
    LEFT,
    NOW,
    RIGHT,
    STUB_LAYERS,
    day,
    fire,
    registered,
    snapshot,
    storm,
    window,
)
from tests.core.schedule_kit import MONDAY, local, snapshot_with_almanac
from tests.core.schedule_kit import config as schedule_config
from tests.core.tracking_kit import codes, resting

PRESENCE = "binary_sensor.example_room_presence"
EARLIER = NOW - timedelta(minutes=10)


def _override(**changes: object) -> ManualOverrideDam:
    arguments: dict[str, object] = {
        "armed_at": EARLIER,
        "end_rule": OverrideEndRule.NEXT_PART_OF_DAY,
        "remembered_position": Position(40),
    }
    return ManualOverrideDam(**(arguments | changes))  # type: ignore[arg-type]


def _decision_of(wish_class: WishClass) -> Decision:
    layer = {
        WishClass.PROTECTION: Layer.PROTECTION,
        WishClass.FIRE: Layer.FIRE,
        WishClass.COMFORT: Layer.SCHEDULE,
    }[wish_class]
    reason = {
        WishClass.PROTECTION: ReasonCode.PROTECTION_EVENT,
        WishClass.FIRE: ReasonCode.FIRE_ALARM,
        WishClass.COMFORT: ReasonCode.SCHEDULE_DAY,
    }[wish_class]
    return Decision(winning_wish=Wish.leave_alone(layer, reason))


def _at(world: WorldSnapshot, minutes: float) -> WorldSnapshot:
    return replace(world, time=NOW + timedelta(minutes=minutes))


# --- Arming ------------------------------------------------------------------------


def test_an_external_movement_arms_the_override_with_the_position_the_person_chose() -> (
    None
):
    """No protection wish is winning: the manual override dam, owner ``user``."""
    armed = arm_after_external_movement(
        window(), WindowState(), NOW, _decision_of(WishClass.COMFORT), Position(40)
    )

    assert codes(armed.events) == [ReasonCode.OVERRIDE_STARTED]
    assert armed.events[0].position == Position(40)
    assert armed.state.owner is PositionOwner.USER
    assert armed.state.manual_override == ManualOverrideDam(
        armed_at=NOW,
        end_rule=OverrideEndRule.NEXT_PART_OF_DAY,
        remembered_position=Position(40),
    )


@pytest.mark.parametrize("wish_class", [WishClass.COMFORT, WishClass.FIRE])
def test_only_a_winning_protection_wish_arms_the_person_at_the_window_dam(
    wish_class: WishClass,
) -> None:
    """Fire, including its unacknowledged phase, arms the override (situation 3a)."""
    armed = arm_after_external_movement(
        window(), WindowState(), NOW, _decision_of(wish_class), Position(40)
    )

    assert armed.state.person_at_window is None
    assert armed.state.manual_override is not None


def test_while_protection_wins_the_person_at_the_window_dam_holds_for_its_time() -> (
    None
):
    """Default 15 minutes, decided; the person's position is kept for later."""
    config = window(person_at_window_duration=timedelta(minutes=20))
    armed = arm_after_external_movement(
        config, WindowState(), NOW, _decision_of(WishClass.PROTECTION), Position(100)
    )

    assert codes(armed.events) == [ReasonCode.PERSON_AT_WINDOW_STARTED]
    assert armed.state.person_at_window == PersonAtWindowDam(
        ends_at=NOW + timedelta(minutes=20), remembered_position=Position(100)
    )
    assert armed.state.manual_override is None
    assert armed_since(config, armed.state) == NOW


def test_protection_winning_counts_an_unknown_decision_as_yes() -> None:
    """Without a decision the person at the window comes first."""
    assert protection_winning(None)
    assert not protection_winning(Decision(winning_wish=None))


def test_fixed_minutes_end_at_an_instant() -> None:
    """The rule has an absolute end from the start."""
    config = window(
        override_end_rule=OverrideEndRule.FIXED_MINUTES,
        override_minutes=timedelta(minutes=45),
    )

    override = new_override(config, WindowState(), NOW, Position(40))

    assert override.end_rule is OverrideEndRule.FIXED_MINUTES
    assert override.ends_at == NOW + timedelta(minutes=45)


def test_a_rule_the_window_cannot_meet_ends_at_the_next_part_of_the_day() -> None:
    """No shading episode to wait for; no readable presence source."""
    episode = window(override_end_rule=OverrideEndRule.SHADING_EPISODE_END)
    room = window(override_end_rule=OverrideEndRule.ROOM_EMPTY)
    blind = window(
        override_end_rule=OverrideEndRule.ROOM_EMPTY,
        override_presence_source=BLIND_SOURCE,
    )

    for config in (episode, room, blind):
        override = new_override(config, WindowState(), NOW, None)
        assert override.end_rule is OverrideEndRule.NEXT_PART_OF_DAY
        assert override.ends_at is None


def test_the_shading_episode_rule_holds_while_the_episode_it_was_armed_in_runs() -> (
    None
):
    """Armed during an episode: the rule stays, and ends with the episode."""
    config = window(override_end_rule=OverrideEndRule.SHADING_EPISODE_END)
    running = WindowState(shading_episode=ShadingEpisodeState(active_since=EARLIER))
    override = new_override(config, running, NOW, Position(40))
    assert override.end_rule is OverrideEndRule.SHADING_EPISODE_END

    armed = replace(running, manual_override=override)
    during = snapshot(sources=day(), state=armed)
    after = snapshot(
        sources=day(), state=replace(armed, shading_episode=ShadingEpisodeState())
    )

    assert not override_ended_by_condition(config, during)
    assert override_ended_by_condition(config, after)
    ended = update_dams(config, _at(after, 1), None)
    assert codes(ended.events) == [ReasonCode.OVERRIDE_ENDED]
    assert ended.state.manual_override is None
    none_at_all = replace(armed, shading_episode=None)
    assert override_ended_by_condition(config, snapshot(state=none_at_all))


# --- Ending the override ---------------------------------------------------------


def test_an_override_whose_end_has_come_ends_with_its_event() -> None:
    """Fixed minutes: at the instant, not a moment later."""
    config = window(override_end_rule=OverrideEndRule.FIXED_MINUTES)
    armed = WindowState(
        manual_override=_override(
            end_rule=OverrideEndRule.FIXED_MINUTES, ends_at=NOW + timedelta(minutes=5)
        )
    )
    world = snapshot(sources=day(), state=armed)

    before = update_dams(config, _at(world, 4.9), None)
    at_the_end = update_dams(config, _at(world, 5), None)

    assert before.events == ()
    assert before.state is armed
    assert codes(at_the_end.events) == [ReasonCode.OVERRIDE_ENDED]
    assert at_the_end.state.manual_override is None


def test_the_room_has_to_be_empty_for_the_configured_time() -> None:
    """Seen empty since a moment; occupied or silent resets it; then it ends."""
    config = window(
        override_end_rule=OverrideEndRule.ROOM_EMPTY,
        override_presence_source=PRESENCE,
        override_room_empty_after=timedelta(minutes=30),
    )
    armed = WindowState(manual_override=_override(end_rule=OverrideEndRule.ROOM_EMPTY))

    def at(
        minutes: float, present: SourceValue[bool], state: WindowState
    ) -> WorldSnapshot:
        return _at(snapshot(sources=day(**{PRESENCE: present}), state=state), minutes)

    empty = SourceValue.of(False)
    seen = update_dams(config, at(0, empty, armed), None).state
    assert seen.manual_override is not None
    assert seen.manual_override.room_empty_since == NOW
    occupied = update_dams(config, at(10, SourceValue.of(True), seen), None).state
    assert occupied.manual_override is not None
    assert occupied.manual_override.room_empty_since is None
    silent = update_dams(config, at(11, SourceValue.unavailable(), seen), None).state
    assert silent.manual_override is not None
    assert silent.manual_override.room_empty_since is None
    still = update_dams(config, at(29, empty, seen), None)
    assert still.state.manual_override is not None
    assert not room_empty_long_enough(config, at(29, empty, seen))

    ended = update_dams(config, at(30, empty, seen), None)

    assert room_empty_long_enough(config, at(30, empty, seen))
    assert codes(ended.events) == [ReasonCode.OVERRIDE_ENDED]
    assert ended.state.manual_override is None


def test_an_empty_room_needs_a_configured_source() -> None:
    """A source that is "none" or blind never says that the room is empty."""
    armed = WindowState(
        manual_override=_override(
            end_rule=OverrideEndRule.ROOM_EMPTY,
            room_empty_since=NOW - timedelta(hours=2),
        )
    )
    world = snapshot(sources=day(**{PRESENCE: SourceValue.of(False)}), state=armed)

    for source in (None, BLIND_SOURCE):
        config = window(
            override_end_rule=OverrideEndRule.ROOM_EMPTY,
            override_presence_source=source,
        )
        assert not room_empty_long_enough(config, world)
        after = update_dams(config, world, None)
        assert after.state.manual_override is not None
        assert after.state.manual_override.room_empty_since is None


def test_the_gate_lets_comfort_pass_once_the_room_has_been_empty_long_enough() -> None:
    """The gate reads the same condition, so the dam never holds longer than its rule."""
    config = window(
        override_end_rule=OverrideEndRule.ROOM_EMPTY,
        override_presence_source=PRESENCE,
    )
    armed = WindowState(
        manual_override=_override(
            end_rule=OverrideEndRule.ROOM_EMPTY,
            room_empty_since=NOW - timedelta(hours=2),
        )
    )
    engine = Engine(config, build_arbiter(STUB_LAYERS))
    empty = snapshot(sources=day(**{PRESENCE: SourceValue.of(False)}), state=armed)
    occupied = snapshot(sources=day(**{PRESENCE: SourceValue.of(True)}), state=armed)

    assert engine.recompute(occupied).gate is not None
    assert engine.recompute(occupied).gate.reason is ReasonCode.MANUAL_OVERRIDE  # type: ignore[union-attr]
    assert engine.recompute(empty).gate is not None
    assert engine.recompute(empty).gate.reason is ReasonCode.SENT  # type: ignore[union-attr]


def test_the_next_part_of_the_day_is_the_next_boundary_of_the_schedule() -> None:
    """Armed at 10:00 on a workday: it ends at 20:00, the evening trigger."""
    config = schedule_config()
    armed = WindowState(
        manual_override=_override(armed_at=local(MONDAY, 10, 0), ends_at=None)
    )

    learned = update_dams(
        config, snapshot_with_almanac(local(MONDAY, 12, 0), config, state=armed), None
    )
    missed = update_dams(
        config, snapshot_with_almanac(local(MONDAY, 20, 30), config, state=armed), None
    )

    assert learned.events == ()
    assert learned.state.manual_override is not None
    assert learned.state.manual_override.ends_at == local(MONDAY, 20, 0)
    # Nothing woke the window at the boundary: it ends at the next look.
    assert codes(missed.events) == [ReasonCode.OVERRIDE_ENDED]


def test_without_a_next_boundary_the_override_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The schedule names no action within the next days: the dam keeps its end."""
    config = schedule_config()
    armed = WindowState(
        manual_override=_override(armed_at=local(MONDAY, 13, 0), ends_at=None)
    )
    world = snapshot_with_almanac(local(MONDAY, 14, 0), config, state=armed)
    silent = replace(evaluate_schedule(config, world), next_action=None)
    monkeypatch.setattr(dams_module, "evaluate_schedule", lambda *_: silent)

    after = update_dams(config, world, None)

    assert after.events == ()
    assert after.state.manual_override is not None
    assert after.state.manual_override.ends_at is None


def test_without_an_armed_override_no_condition_has_ended_it() -> None:
    """The gate asks only for an armed dam."""
    assert not override_ended_by_condition(window(), snapshot(state=WindowState()))


def test_the_next_part_of_the_day_waits_while_the_schedule_cannot_say() -> None:
    """Without the almanac the schedule names no boundary: the dam holds."""
    armed = WindowState(manual_override=_override())
    world = snapshot(sources=day(), state=armed)

    after = update_dams(window(), world, None)

    assert after.events == ()
    assert after.state.manual_override == _override()


def test_resume_and_sleep_mode_end_the_override_at_once() -> None:
    """The button, the action and switching sleep mode on; without one, nothing."""
    armed = WindowState(manual_override=_override())

    for ended in (Engine.resume(armed), Engine.sleep_mode_switched_on(armed)):
        assert codes(ended.events) == [ReasonCode.OVERRIDE_ENDED]
        assert ended.state.manual_override is None
    nothing = end_override(WindowState())
    assert nothing.events == ()
    assert nothing.state == WindowState()


def test_resume_leaves_the_person_at_the_window_dam_alone() -> None:
    """The button ends the override; the person-at-the-window dam ends by itself."""
    dam = PersonAtWindowDam(ends_at=NOW + timedelta(minutes=5))
    state = WindowState(manual_override=_override(), person_at_window=dam)

    ended = Engine.resume(state)

    assert ended.state.person_at_window == dam


# --- The person-at-the-window dam ends ---------------------------------------------


def _person(minutes: float = 5) -> WindowState:
    return WindowState(
        person_at_window=PersonAtWindowDam(
            ends_at=NOW + timedelta(minutes=minutes), remembered_position=Position(100)
        )
    )


def test_the_person_at_the_window_dam_ends_and_protection_reasserts_itself() -> None:
    """The storm still wins: the dam ends, the recompute closes the window again."""
    world = snapshot(sources=storm(), state=_person())

    ended = update_dams(window(), _at(world, 5), _decision_of(WishClass.PROTECTION))

    assert codes(ended.events) == [ReasonCode.PERSON_AT_WINDOW_ENDED]
    assert ended.state.person_at_window is None
    assert ended.state.manual_override is None


@pytest.mark.parametrize(
    "decision", [_decision_of(WishClass.COMFORT), None], ids=["event over", "unknown"]
)
def test_after_the_event_the_dam_turns_into_an_override_with_the_persons_position(
    decision: Decision | None,
) -> None:
    """Section 3.2: the comfort logic does not undo what the person did."""
    world = snapshot(sources=day(), state=_person())

    turned = update_dams(window(), _at(world, 5), decision)

    assert codes(turned.events) == [
        ReasonCode.PERSON_AT_WINDOW_ENDED,
        ReasonCode.OVERRIDE_STARTED,
    ]
    assert turned.events[1].position == Position(100)
    override = turned.state.manual_override
    assert override is not None
    assert override.remembered_position == Position(100)
    assert override.armed_at == NOW + timedelta(minutes=5)


def test_the_person_at_the_window_dam_holds_protection_and_comfort_but_never_fire() -> (
    None
):
    """Rule 6 of the gate, armed by the tracker."""
    state = _person()
    engine = Engine(window(), build_arbiter(STUB_LAYERS))

    for sources, reason in (
        (storm(), ReasonCode.PERSON_AT_WINDOW),
        (day(), ReasonCode.PERSON_AT_WINDOW),
        (fire(), ReasonCode.SENT),
    ):
        world = snapshot(sources=sources, position=40, state=state)
        gate = engine.recompute(world).gate
        assert gate is not None
        assert gate.reason is reason


def test_the_remembered_position_follows_the_person() -> None:
    """The end of a movement that was reported at its start brings it up to date."""
    both = WindowState(
        manual_override=_override(), person_at_window=_person().person_at_window
    )

    updated = update_remembered_position(both, Position(30))
    only = update_remembered_position(WindowState(manual_override=_override()), None)

    assert updated.person_at_window is not None
    assert updated.person_at_window.remembered_position == Position(30)
    assert updated.manual_override == _override()
    assert only.manual_override is not None
    assert only.manual_override.remembered_position is None
    assert update_remembered_position(WindowState(), Position(3)) == WindowState()


# --- The clock keeps running during a protection event (decision 4) -------------------


def _return_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Answer as a stub protection layer: the storm closes, afterwards the return.

    The return to the manual position is a wish only while the override is
    still armed when the return is due (decision 4, section 10.2): the stub
    reads the persisted dam, as the protection layer of block C07 will.
    """
    storm_now = world.sources.get("storm")
    if storm_now is not None and storm_now.value is True:
        return Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED)
    override = world.state.manual_override
    if override is None or override.remembered_position is None:
        return Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE)
    return Wish.target(
        Layer.PROTECTION,
        ReasonCode.PROTECTION_RETURN_MANUAL,
        override.remembered_position,
    ).triggered(NOW)


def _with_return() -> Engine:
    layers = [entry for entry in STUB_LAYERS if entry.layer is not Layer.PROTECTION]
    config = window(
        override_end_rule=OverrideEndRule.FIXED_MINUTES,
        override_minutes=timedelta(minutes=60),
    )
    return Engine(
        config,
        build_arbiter([*layers, registered(Layer.PROTECTION, _return_layer)]),
    )


def test_during_a_storm_the_clock_of_the_override_keeps_running() -> None:
    """The storm closes although the override is armed; the dam keeps its end."""
    engine = _with_return()
    armed = WindowState(
        manual_override=_override(
            end_rule=OverrideEndRule.FIXED_MINUTES, ends_at=NOW + timedelta(minutes=50)
        )
    )
    world = snapshot(sources=storm(), position=40, state=armed)

    decision = engine.recompute(world)
    during = engine.elapse(_at(world, 30), decision)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.SENT
    assert during.state.manual_override == armed.manual_override
    ended = engine.elapse(_at(world, 50), decision)
    assert codes(ended.events) == [ReasonCode.OVERRIDE_ENDED]


def test_the_return_restores_the_position_only_while_the_override_is_armed() -> None:
    """After the storm: armed, the remembered 40; expired, the window is recomputed."""
    engine = _with_return()
    armed = WindowState(
        manual_override=_override(
            end_rule=OverrideEndRule.FIXED_MINUTES, ends_at=NOW + timedelta(minutes=50)
        )
    )
    after_the_storm = snapshot(sources=day(), position=0, state=armed)

    still_armed = engine.recompute(after_the_storm)
    expired_state = engine.elapse(_at(after_the_storm, 50), still_armed).state
    expired = engine.recompute(replace(_at(after_the_storm, 50), state=expired_state))

    assert still_armed.winning_wish is not None
    assert still_armed.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert still_armed.target == Position(40)
    assert still_armed.gate is not None
    assert still_armed.gate.reason is ReasonCode.SENT
    assert expired.winning_wish is not None
    assert expired.winning_wish.reason is ReasonCode.SCHEDULE_DAY
    assert expired.target == Position(100)


# --- Wake-ups ---------------------------------------------------------------------


def _command(seconds_ago: float) -> OwnCommand:
    return OwnCommand(
        "command-1",
        Position(100),
        TravelDirection.UP,
        NOW - timedelta(seconds=seconds_ago),
        WishClass.COMFORT,
        ReasonCode.SCHEDULE_DAY,
        start_position=Position(0),
    )


def test_every_instant_a_caller_has_to_wake_the_window_comes_from_the_core() -> None:
    """Deadlines, settle ends, dam ends, the end of an empty room; only after now."""
    config = window(
        LEFT,
        RIGHT,
        override_end_rule=OverrideEndRule.ROOM_EMPTY,
        override_presence_source=PRESENCE,
        override_room_empty_after=timedelta(minutes=30),
    )
    settling = MemberState(
        RIGHT,
        last_own_command=replace(_command(5), command_id="command-2"),
        command_attempts=1,
        last_attempt_at=NOW,
        tracking=MemberTracking(
            phase=TrackerPhase.SETTLING,
            command_id="command-2",
            moved_at=NOW - timedelta(seconds=4),
            rested_at=NOW - timedelta(seconds=1),
        ),
    )
    state = WindowState(
        members=(
            MemberState(
                LEFT,
                last_own_command=_command(5),
                command_attempts=1,
                last_attempt_at=NOW,
            ),
            settling,
        ),
        person_at_window=PersonAtWindowDam(ends_at=NOW + timedelta(minutes=15)),
        manual_override=_override(
            end_rule=OverrideEndRule.ROOM_EMPTY,
            ends_at=NOW + timedelta(hours=1),
            room_empty_since=NOW - timedelta(minutes=10),
        ),
    )

    times = wake_ups(config, state, NOW, dry_run=False)

    deadline = NOW + timedelta(seconds=-5 + 10 + 30 + 5)
    assert times == (
        NOW + timedelta(seconds=1),  # the settle time of the right member
        deadline,
        NOW + timedelta(minutes=15),
        NOW + timedelta(minutes=20),
        NOW + timedelta(hours=1),
    )
    assert (
        Engine(config, build_arbiter(STUB_LAYERS)).wake_ups(state, NOW, dry_run=False)
        == times
    )
    assert wake_ups(config, state, NOW + timedelta(hours=2), dry_run=False) == ()


def test_in_dry_run_the_deadlines_of_the_simulated_commands_count() -> None:
    """A window in dry-run is woken where its would-be commands end."""
    state = WindowState(
        simulated=SimulatedState(commands=(MemberCommand(LEFT, _command(5)),))
    )

    assert wake_ups(window(), state, NOW, dry_run=True) == (
        NOW + timedelta(seconds=-5 + 10 + 30 + 5),
    )
    assert wake_ups(window(), state, NOW, dry_run=False) == ()


def test_a_command_of_a_member_the_window_no_longer_has_wakes_nothing() -> None:
    """A cover that was removed from the window leaves its record behind."""
    state = WindowState(
        members=(
            MemberState(
                "cover.example_removed",
                last_own_command=_command(5),
                command_attempts=1,
                last_attempt_at=NOW,
            ),
        )
    )

    assert wake_ups(window(), state, NOW, dry_run=False) == ()


def test_the_window_position_needs_every_member_observed() -> None:
    """A member never seen leaves the window without a position."""
    config = window(LEFT, RIGHT)
    one = WindowState(members=(MemberState(LEFT, last_observation=resting(40)),))
    both = WindowState(
        members=(
            MemberState(LEFT, last_observation=resting(40)),
            MemberState(RIGHT, last_observation=resting(41)),
        )
    )

    assert window_position(config, one) is None
    assert window_position(config, both) == Position(41)
