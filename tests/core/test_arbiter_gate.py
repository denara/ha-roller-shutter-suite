"""The gate: its rules one by one, their order, and what registers with it."""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    ALL_CLASSES,
    BUILT_IN_GATE_RULES,
    MANUAL_OVERRIDE_DAM,
    MODE_TABLE,
    PERSON_AT_WINDOW_DAM,
    Arbiter,
    ConstraintInput,
    ConstraintRegistration,
    Dam,
    GateInput,
    GateRuleRegistration,
    apply_take_over,
    effective_controls,
)
from custom_components.roller_shutter_suite.core.engine import (
    BUILT_IN_CONSTRAINTS,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    Constraint,
    ConstraintResult,
    ControlLevel,
    Controls,
    Decision,
    FunctionId,
    GateKind,
    GateOutcome,
    GateRule,
    Layer,
    ManualOverrideDam,
    MemberState,
    MemberTarget,
    MotorProtectionSettings,
    OperatingMode,
    OverrideEndRule,
    OwnCommand,
    PersonAtWindowDam,
    Position,
    PositionOwner,
    SourceValue,
    TravelDirection,
    WindowState,
    Wish,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    ARMED,
    LEFT,
    NOW,
    RIGHT,
    STUB_LAYERS,
    day,
    engine,
    fire,
    night,
    observed,
    on_level,
    profile,
    registered,
    snapshot,
    storm,
    window,
)

LEVELS = ["global", "group", "window"]
LATER = NOW + timedelta(minutes=15)


def _gate(decision: Decision) -> GateOutcome:
    assert decision.gate is not None
    return decision.gate


_REASON_OF = {
    WishClass.FIRE: ReasonCode.FIRE_ALARM,
    WishClass.PROTECTION: ReasonCode.PROTECTION_EVENT,
    WishClass.COMFORT: ReasonCode.SCHEDULE_NIGHT,
}


def _commanded(
    target: int,
    seconds_ago: float,
    *,
    member: str = LEFT,
    direction: TravelDirection = TravelDirection.DOWN,
    wish_class: WishClass = WishClass.COMFORT,
) -> MemberState:
    return MemberState(
        member,
        last_own_command=OwnCommand(
            command_id="command-1",
            target=Position(target),
            direction=direction,
            time=NOW - timedelta(seconds=seconds_ago),
            wish_class=wish_class,
            reason=_REASON_OF[wish_class],
        ),
    )


def _override(ends_at: Any = LATER) -> ManualOverrideDam:
    rule = (
        OverrideEndRule.ROOM_EMPTY
        if ends_at is None
        else OverrideEndRule.NEXT_PART_OF_DAY
    )
    return ManualOverrideDam(
        armed_at=NOW - timedelta(hours=1),
        end_rule=rule,
        ends_at=ends_at,
        remembered_position=Position(40),
    )


# --- No rule applies ----------------------------------------------------------------


def test_without_a_rule_that_applies_the_command_is_sent() -> None:
    """Reason ``sent``; no rule is named."""
    gate = _gate(engine().recompute(snapshot(sources=night())))

    assert gate == GateOutcome.send()
    assert gate.reason is ReasonCode.SENT


def test_the_built_in_rules_stand_in_the_specified_order() -> None:
    """Backoff and staggering are registered by the blocks that build them."""
    rules = [registration.rule for registration in build_arbiter(()).gate_rules]

    assert rules == sorted(rules, key=list(GateRule).index)
    assert set(GateRule) - set(rules) == {GateRule.COMMAND_BACKOFF, GateRule.STAGGERING}
    # "Movement in flight" is registered in two parts, for different classes.
    assert [rule for rule in GateRule if rules.count(rule) > 1] == [
        GateRule.MOVEMENT_IN_FLIGHT
    ]
    assert rules[0] is GateRule.MAINTENANCE_LOCK
    assert rules[-1] is GateRule.DRY_RUN
    assert Arbiter(gate_rules=BUILT_IN_GATE_RULES[::-1]).gate_rules == tuple(
        BUILT_IN_GATE_RULES
    )


# --- 1 Maintenance lock -------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(
    "sources", [fire(), storm(), night()], ids=["fire", "protection", "comfort"]
)
def test_under_a_maintenance_lock_nothing_is_sent(
    sources: dict[str, Any], level: str
) -> None:
    """Not for fire either; the decision still names the winning wish."""
    decision = engine().recompute(
        snapshot(sources=sources, controls=on_level(level, maintenance_lock=True))
    )

    assert _gate(decision) == GateOutcome.suppress(
        GateRule.MAINTENANCE_LOCK, ReasonCode.MAINTENANCE_LOCK
    )
    assert decision.targets


def test_the_lock_still_names_fire_as_the_winning_wish() -> None:
    """So the fire event can be fired although nothing moves."""
    decision = engine().recompute(
        snapshot(sources=fire(), controls=on_level("global", maintenance_lock=True))
    )

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.FIRE_ALARM
    assert decision.target == Position(100)
    assert _gate(decision).kind is GateKind.SUPPRESS


# --- 2 No member can execute --------------------------------------------------------


def test_with_every_member_unavailable_the_command_waits_with_an_upper_bound() -> None:
    """Nobody knows when a member returns, so the deferral carries its bound."""
    config = window(LEFT, RIGHT, reevaluate_after=timedelta(minutes=3))
    gate = _gate(
        engine(config).recompute(
            snapshot(
                sources=fire(),
                observation=observed(left="unavailable", right="unavailable"),
            )
        )
    )

    assert gate == GateOutcome.defer(
        GateRule.NO_MEMBER_CAN_EXECUTE,
        ReasonCode.COVER_UNAVAILABLE,
        reevaluate_no_later_than=NOW + timedelta(minutes=3),
    )
    assert gate.until is None


def test_the_available_members_move_when_one_is_unavailable() -> None:
    """The command goes to every available member."""
    gate = _gate(
        engine(window(LEFT, RIGHT)).recompute(
            snapshot(
                sources=storm(), observation=observed(left=100, right="unavailable")
            )
        )
    )

    assert gate == GateOutcome.send()


def test_a_member_that_can_neither_be_positioned_nor_opened_is_a_missing_capability() -> (
    None
):
    """Suppressed with the capability reason; open and close alone is enough."""
    stop_only = profile(supports_open_close=False, supports_set_position=False)
    open_close = profile(supports_set_position=False)

    unable = engine(window(profiles={LEFT: stop_only})).recompute(
        snapshot(sources=night())
    )
    able = engine(window(profiles={LEFT: open_close})).recompute(
        snapshot(sources=night())
    )

    assert _gate(unable) == GateOutcome.suppress(
        GateRule.NO_MEMBER_CAN_EXECUTE, ReasonCode.CAPABILITY_MISSING
    )
    assert _gate(able) == GateOutcome.send()


# --- 3 Target reached ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("position", "reached"), [(0, True), (2, True), (3, False), (100, False)]
)
def test_a_target_within_tolerance_is_reached(position: int, reached: bool) -> None:
    """The tolerance of a calculated position is 2."""
    gate = _gate(engine().recompute(snapshot(sources=storm(), position=position)))

    assert (gate.reason is ReasonCode.TARGET_REACHED) is reached
    assert (gate.kind is GateKind.SUPPRESS) is reached


def test_a_member_without_feedback_is_reached_if_its_last_command_had_the_target() -> (
    None
):
    """Otherwise the same command would be repeated at every recompute."""
    config = window(profiles={LEFT: profile(reports_position=False)})
    same = WindowState(members=(_commanded(0, 3600),))
    other = WindowState(members=(_commanded(100, 3600),))

    def gate(state: WindowState | None) -> GateOutcome:
        return _gate(
            engine(config).recompute(
                snapshot(sources=storm(), position=None, state=state)
            )
        )

    assert gate(same).reason is ReasonCode.TARGET_REACHED
    assert gate(other) == GateOutcome.send()
    assert gate(None) == GateOutcome.send()


def test_a_member_that_reports_no_position_right_now_is_not_reached() -> None:
    """What is not known is not assumed."""
    gate = _gate(engine().recompute(snapshot(sources=storm(), position=None)))

    assert gate == GateOutcome.send()


def test_unavailable_members_are_not_judged_and_every_available_one_has_to_be_there() -> (
    None
):
    """Two members: both at the target, one missing, one elsewhere."""
    subject = engine(window(LEFT, RIGHT))

    def reason(**members: int | str | None) -> ReasonCode:
        world = snapshot(sources=storm(), observation=observed(**members))
        return _gate(subject.recompute(world)).reason

    assert reason(left=0, right=1) is ReasonCode.TARGET_REACHED
    assert reason(left=0, right="unavailable") is ReasonCode.TARGET_REACHED
    assert reason(left=0, right=50) is ReasonCode.SENT


def test_a_window_without_an_available_member_is_never_reported_as_reached() -> None:
    """Also if the rule that waits for a member were not registered."""
    without_rule_2 = Arbiter(
        layers=STUB_LAYERS,
        gate_rules=tuple(
            entry
            for entry in BUILT_IN_GATE_RULES
            if entry.rule is not GateRule.NO_MEMBER_CAN_EXECUTE
        ),
    )

    decision = without_rule_2.recompute(
        window(), snapshot(sources=storm(), observation=observed(left="unavailable"))
    )

    assert _gate(decision).reason is not ReasonCode.TARGET_REACHED


def test_target_reached_stands_before_mode_and_pause_and_after_the_lock() -> None:
    """A paused window that is where it should be says so."""
    paused = on_level("window", paused=True, mode=OperatingMode.OFF)
    locked = replace(paused, global_level=ControlLevel(maintenance_lock=True))

    there = engine().recompute(snapshot(sources=night(), position=0, controls=paused))
    locked_there = engine().recompute(
        snapshot(sources=night(), position=0, controls=locked)
    )

    assert _gate(there).reason is ReasonCode.TARGET_REACHED
    assert _gate(locked_there).reason is ReasonCode.MAINTENANCE_LOCK


# --- 4 Operating mode ---------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
@pytest.mark.parametrize(
    ("mode", "sources", "reason"),
    [
        (OperatingMode.OFF, night(), ReasonCode.MODE_OFF),
        (OperatingMode.OFF, storm(), ReasonCode.MODE_OFF),
        (OperatingMode.OFF, fire(), ReasonCode.SENT),
        (OperatingMode.PROTECTION_ONLY, night(), ReasonCode.MODE_PROTECTION_ONLY),
        (OperatingMode.PROTECTION_ONLY, storm(), ReasonCode.SENT),
        (OperatingMode.PROTECTION_ONLY, fire(), ReasonCode.SENT),
        (OperatingMode.AUTOMATIC, night(), ReasonCode.SENT),
        (OperatingMode.AUTOMATIC, storm(), ReasonCode.SENT),
        (OperatingMode.AUTOMATIC, fire(), ReasonCode.SENT),
    ],
)
def test_what_each_operating_mode_lets_through(
    mode: OperatingMode, sources: dict[str, Any], reason: ReasonCode, level: str
) -> None:
    """Off: fire only. Protection only: protection and fire. Automatic: everything."""
    gate = _gate(
        engine().recompute(
            snapshot(sources=sources, controls=on_level(level, mode=mode))
        )
    )

    assert gate.reason is reason
    if reason is not ReasonCode.SENT:
        assert gate == GateOutcome.suppress(GateRule.OPERATING_MODE, reason)


def test_the_operating_modes_are_a_table() -> None:
    """One row per mode, ranked, and no row holds back fire."""
    assert set(MODE_TABLE) == set(OperatingMode)
    ranks = [MODE_TABLE[mode].restrictiveness for mode in OperatingMode]
    assert ranks == sorted(set(ranks))
    for entry in MODE_TABLE.values():
        assert WishClass.FIRE not in entry.holds_back
        assert (entry.reason is None) == (not entry.holds_back)
    assert MODE_TABLE[OperatingMode.OFF].holds_back > (
        MODE_TABLE[OperatingMode.PROTECTION_ONLY].holds_back
    )


# --- Three levels -------------------------------------------------------------------


def test_the_effective_value_is_the_most_restrictive_of_the_three_levels() -> None:
    """Paused or locked if any level is; the mode is the most restrictive one."""
    controls = Controls(
        dry_run=False,
        global_level=ControlLevel(mode=OperatingMode.PROTECTION_ONLY),
        group_level=ControlLevel(paused=True, mode=OperatingMode.OFF),
        window_level=ControlLevel(maintenance_lock=True),
    )

    effective = effective_controls(controls)
    neutral = effective_controls(Controls(dry_run=True))

    assert (effective.paused, effective.maintenance_lock) == (True, True)
    assert effective.mode is OperatingMode.OFF
    assert effective.dry_run is False
    assert (neutral.paused, neutral.maintenance_lock) == (False, False)
    assert neutral.mode is OperatingMode.AUTOMATIC
    assert neutral.dry_run is True


def test_a_window_cannot_loosen_what_a_higher_level_restricts() -> None:
    """Automatic on the window does not lift "off" on the group."""
    controls = Controls(
        dry_run=False,
        group_level=ControlLevel(mode=OperatingMode.OFF),
        window_level=ControlLevel(mode=OperatingMode.AUTOMATIC),
    )

    gate = _gate(engine().recompute(snapshot(sources=night(), controls=controls)))

    assert gate.reason is ReasonCode.MODE_OFF


# --- 5 Pause ------------------------------------------------------------------------


@pytest.mark.parametrize("level", LEVELS)
def test_pause_holds_back_comfort_only(level: str) -> None:
    """Protection and fire are sent from a paused window."""
    paused = on_level(level, paused=True)

    def reason(sources: dict[str, Any]) -> ReasonCode:
        return _gate(
            engine().recompute(snapshot(sources=sources, controls=paused))
        ).reason

    assert _gate(
        engine().recompute(snapshot(sources=night(), controls=paused))
    ) == GateOutcome.suppress(GateRule.PAUSE, ReasonCode.PAUSED)
    assert reason(storm()) is ReasonCode.SENT
    assert reason(fire()) is ReasonCode.SENT


# --- 6 and 7 The dams ---------------------------------------------------------------


def test_the_person_at_the_window_dam_holds_protection_and_comfort_never_fire() -> None:
    """A deferral until the dam ends."""
    state = WindowState(person_at_window=PersonAtWindowDam(ends_at=LATER))

    def gate(sources: dict[str, Any]) -> GateOutcome:
        return _gate(engine().recompute(snapshot(sources=sources, state=state)))

    held = GateOutcome.defer(
        GateRule.PERSON_AT_WINDOW_DAM, ReasonCode.PERSON_AT_WINDOW, until=LATER
    )
    assert gate(storm()) == held
    assert gate(night()) == held
    assert gate(fire()) == GateOutcome.send()
    assert PERSON_AT_WINDOW_DAM.holds_back == {WishClass.PROTECTION, WishClass.COMFORT}


def test_the_manual_override_dam_holds_comfort_and_lets_protection_pass() -> None:
    """With a known end it defers until then; without one it suppresses."""
    timed = WindowState(manual_override=_override())
    open_ended = WindowState(manual_override=_override(None))

    def gate(sources: dict[str, Any], state: WindowState) -> GateOutcome:
        return _gate(engine().recompute(snapshot(sources=sources, state=state)))

    assert gate(night(), timed) == GateOutcome.defer(
        GateRule.MANUAL_OVERRIDE_DAM, ReasonCode.MANUAL_OVERRIDE, until=LATER
    )
    assert gate(night(), open_ended) == GateOutcome.suppress(
        GateRule.MANUAL_OVERRIDE_DAM, ReasonCode.MANUAL_OVERRIDE
    )
    assert gate(storm(), timed) == GateOutcome.send()
    assert gate(fire(), open_ended) == GateOutcome.send()
    assert MANUAL_OVERRIDE_DAM.holds_back == {WishClass.COMFORT}


@pytest.mark.parametrize("ends_at", [NOW, NOW - timedelta(minutes=1)])
def test_an_expired_dam_has_no_effect(ends_at: Any) -> None:
    """The gate reads the end; it does not wait for somebody to clear the dam."""
    state = WindowState(
        manual_override=_override(ends_at),
        person_at_window=PersonAtWindowDam(ends_at=ends_at),
    )

    assert _gate(engine().recompute(snapshot(sources=night(), state=state))) == (
        GateOutcome.send()
    )


def test_the_override_dam_lets_exactly_the_return_to_the_manual_position_pass() -> None:
    """It is a comfort wish, so every other rule still applies to it."""
    back = day(return_to=SourceValue.of(40))
    armed = WindowState(manual_override=_override())
    both = replace(armed, person_at_window=PersonAtWindowDam(ends_at=LATER))

    def decide(state: WindowState, controls: Controls = ARMED) -> Decision:
        return engine().recompute(
            snapshot(sources=back, state=state, controls=controls)
        )

    returned = decide(armed)
    assert returned.winning_wish is not None
    assert returned.winning_wish.reason is ReasonCode.PROTECTION_RETURN_MANUAL
    assert returned.winning_wish.wish_class is WishClass.COMFORT
    assert returned.target == Position(40)
    assert _gate(returned) == GateOutcome.send()
    assert MANUAL_OVERRIDE_DAM.lets_pass == {ReasonCode.PROTECTION_RETURN_MANUAL}
    # (b) the person-at-the-window dam still holds it back
    assert _gate(decide(both)).reason is ReasonCode.PERSON_AT_WINDOW
    # every other gate rule applies as to any comfort wish
    assert _gate(decide(armed, on_level("group", paused=True))).reason is (
        ReasonCode.PAUSED
    )
    assert (
        _gate(
            decide(armed, on_level("window", mode=OperatingMode.PROTECTION_ONLY))
        ).reason
        is ReasonCode.MODE_PROTECTION_ONLY
    )
    clock = replace(armed, last_comfort_movement=NOW - timedelta(minutes=1))
    assert _gate(decide(clock)).reason is ReasonCode.MIN_INTERVAL


def test_a_dam_never_holds_back_fire() -> None:
    """The mechanism refuses such a dam."""
    with pytest.raises(ValueError, match="never holds back fire"):
        Dam(
            rule=GateRule.PERSON_AT_WINDOW_DAM,
            reason=ReasonCode.PERSON_AT_WINDOW,
            holds_back=ALL_CLASSES,
            lets_pass=frozenset(),
            armed=lambda _state: None,
        )


# --- 8 Movement in flight -----------------------------------------------------------


def test_the_same_target_as_the_pending_own_command_is_a_duplicate() -> None:
    """The member has not reported anything yet; the command is 5 seconds old."""
    state = WindowState(members=(_commanded(0, 5),))

    gate = _gate(
        engine().recompute(snapshot(sources=night(), position=100, state=state))
    )

    assert gate == GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND
    )


def test_another_target_waits_until_the_members_have_come_to_rest() -> None:
    """The end is not known; the bound is the end of the pending command's window."""
    config = window(profiles={LEFT: profile(report_delay=timedelta(seconds=60))})
    state = WindowState(members=(_commanded(30, 5),))

    gate = _gate(
        engine(config).recompute(
            snapshot(sources=night(), observation=observed(left="down:80"), state=state)
        )
    )

    assert gate == GateOutcome.defer(
        GateRule.MOVEMENT_IN_FLIGHT,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        reevaluate_no_later_than=NOW + timedelta(seconds=-5 + 18 + 60),
    )


def test_the_travel_time_of_a_command_follows_its_direction() -> None:
    """Up takes 20 seconds here, down 18; afterwards the command is not pending."""
    up = WindowState(members=(_commanded(100, 19, direction=TravelDirection.UP),))
    down = WindowState(members=(_commanded(100, 19),))

    def reason(state: WindowState) -> ReasonCode:
        return _gate(
            engine().recompute(snapshot(sources=night(), position=60, state=state))
        ).reason

    assert reason(up) is ReasonCode.MOVEMENT_IN_FLIGHT
    assert reason(down) is ReasonCode.SENT


def test_a_movement_nobody_commanded_is_waited_for_too() -> None:
    """Somebody is moving the shutter right now; the bound is the general one."""
    gate = _gate(
        engine().recompute(
            snapshot(sources=night(), observation=observed(left="up:40"))
        )
    )

    assert gate == GateOutcome.defer(
        GateRule.MOVEMENT_IN_FLIGHT,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        reevaluate_no_later_than=NOW + timedelta(minutes=5),
    )


def test_a_duplicate_needs_every_member_to_be_commanded_to_its_target() -> None:
    """One member is pending with the target, the other was never commanded."""
    state = WindowState(members=(_commanded(0, 5), MemberState(RIGHT)))

    gate = _gate(
        engine(window(LEFT, RIGHT)).recompute(
            snapshot(
                sources=night(), observation=observed(left=100, right=100), state=state
            )
        )
    )

    assert gate.reason is ReasonCode.MOVEMENT_IN_FLIGHT
    assert gate.reevaluate_no_later_than == NOW + timedelta(seconds=13)


def test_protection_and_fire_retarget_at_once() -> None:
    """Movement in flight holds back comfort only."""
    state = WindowState(members=(_commanded(30, 5),))
    moving = observed(left="down:80")

    for sources in (storm(), fire()):
        gate = _gate(
            engine().recompute(
                snapshot(sources=sources, observation=moving, state=state)
            )
        )
        assert gate == GateOutcome.send()


def test_a_pending_command_with_the_same_target_is_not_sent_again_for_any_class() -> (
    None
):
    """Protection during its own closing: a duplicate, until the window closes."""
    pending = WindowState(members=(_commanded(0, 5, wish_class=WishClass.PROTECTION),))
    closed = WindowState(members=(_commanded(0, 18, wish_class=WishClass.PROTECTION),))

    def gate(state: WindowState) -> GateOutcome:
        return _gate(
            engine().recompute(snapshot(sources=storm(), position=100, state=state))
        )

    assert gate(pending) == GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND
    )
    assert gate(closed) == GateOutcome.send()


def test_a_wish_of_a_higher_class_takes_over_a_movement_with_the_same_target() -> None:
    """A storm begins while the evening closing is under way: nothing is sent."""
    state = WindowState(members=(_commanded(0, 5),))
    world = snapshot(sources=storm(), observation=observed(left="down:70"), state=state)

    decision = engine().recompute(world)
    after = engine().state_after(world, decision)

    assert _gate(decision) == GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.MOVEMENT_TAKEN_OVER
    )
    command = after.members[0].last_own_command
    assert command is not None
    # Class, reason and owner change; everything else about the command stays.
    assert command.wish_class is WishClass.PROTECTION
    assert command.reason is ReasonCode.PROTECTION_EVENT
    assert after.owner is PositionOwner.ENGINE
    assert state.owner is PositionOwner.UNKNOWN
    assert replace(
        command, wish_class=WishClass.COMFORT, reason=ReasonCode.SCHEDULE_NIGHT
    ) == (state.members[0].last_own_command)
    assert replace(after, members=state.members, owner=state.owner) == state
    # From now on it is a protection movement: the same wish is a duplicate.
    again = engine().recompute(replace(world, state=after))
    assert _gate(again).reason is ReasonCode.DUPLICATE_COMMAND
    assert engine().state_after(replace(world, state=after), again) is after


def test_a_wish_of_the_same_or_a_lower_class_does_not_take_over() -> None:
    """The evening closing meets a protection closing that is under way."""
    state = WindowState(
        members=(
            _commanded(
                0,
                5,
                wish_class=WishClass.PROTECTION,
            ),
        ),
        owner=PositionOwner.USER,
    )
    world = snapshot(sources=night(), position=100, state=state)

    decision = engine().recompute(world)

    assert _gate(decision).reason is ReasonCode.DUPLICATE_COMMAND
    assert engine().state_after(world, decision) is state
    assert apply_take_over(world, decision) is state
    # The same class changes nothing either: a second storm wish, same target.
    stormy = replace(world, sources=storm())
    same_class = engine().recompute(stormy)
    assert _gate(same_class).reason is ReasonCode.DUPLICATE_COMMAND
    assert engine().state_after(stormy, same_class) is state


def test_a_take_over_raises_only_the_commands_of_a_lower_class() -> None:
    """Two members open: one for comfort, the other for fire already."""
    state = WindowState(
        members=(
            _commanded(100, 5, direction=TravelDirection.UP),
            _commanded(
                100,
                5,
                member=RIGHT,
                direction=TravelDirection.UP,
                wish_class=WishClass.FIRE,
            ),
        )
    )
    world = snapshot(
        sources=fire(), observation=observed(left=40, right=40), state=state
    )
    subject = engine(window(LEFT, RIGHT))

    decision = subject.recompute(world)
    after = subject.state_after(world, decision)

    assert _gate(decision).reason is ReasonCode.MOVEMENT_TAKEN_OVER
    assert [
        member.last_own_command.wish_class
        for member in after.members
        if member.last_own_command is not None
    ] == [WishClass.FIRE, WishClass.FIRE]
    assert [
        member.last_own_command.reason
        for member in after.members
        if member.last_own_command is not None
    ] == [ReasonCode.FIRE_ALARM, ReasonCode.FIRE_ALARM]
    assert after.members[1] == state.members[1]


def test_a_take_over_leaves_the_motor_protection_clock_as_it_is() -> None:
    """The movement was sent as comfort; the take-over sends nothing."""
    sent_at = NOW - timedelta(seconds=5)
    state = WindowState(members=(_commanded(0, 5),), last_comfort_movement=sent_at)
    world = snapshot(sources=storm(), position=100, state=state)

    decision = engine().recompute(world)
    after = engine().state_after(world, decision)

    assert _gate(decision).reason is ReasonCode.MOVEMENT_TAKEN_OVER
    assert after.last_comfort_movement == sent_at
    assert after.manual_override is None
    assert after.person_at_window is None


def test_a_command_to_a_member_the_window_no_longer_has_is_ignored() -> None:
    """The persisted state may be older than the configuration."""
    state = WindowState(members=(_commanded(30, 5, member=RIGHT),))

    gate = _gate(engine().recompute(snapshot(sources=night(), state=state)))

    assert gate == GateOutcome.send()


# --- 9 Motor protection -------------------------------------------------------------


def _shaded(position: int) -> dict[str, Any]:
    return day(shading_position=SourceValue.of(position))


@pytest.mark.parametrize(
    ("position", "held"), [(36, True), (44, True), (35, False), (45, False)]
)
def test_a_comfort_movement_below_the_minimum_change_is_suppressed(
    position: int, held: bool
) -> None:
    """The default minimum is 5 percent; the target here is 40."""
    gate = _gate(engine().recompute(snapshot(sources=_shaded(40), position=position)))

    assert (
        gate == GateOutcome.suppress(GateRule.MOTOR_PROTECTION, ReasonCode.MIN_CHANGE)
    ) is held


@pytest.mark.parametrize(
    ("sources", "position"), [(night(), 3), (night(), 4), (day(), 97), (day(), 96)]
)
def test_an_end_position_is_driven_even_if_the_change_is_below_the_minimum(
    sources: dict[str, Any], position: int
) -> None:
    """A shutter does not stay a few percent open because the rest is "too little"."""
    gate = _gate(engine().recompute(snapshot(sources=sources, position=position)))

    assert gate == GateOutcome.send()


def test_the_exemption_of_end_positions_does_not_lift_the_minimum_interval() -> None:
    """Three percent to go, but the last comfort movement was a minute ago."""
    state = WindowState(last_comfort_movement=NOW - timedelta(minutes=1))

    gate = _gate(engine().recompute(snapshot(sources=night(), position=3, state=state)))

    assert gate.reason is ReasonCode.MIN_INTERVAL


def test_an_end_position_within_tolerance_is_reached_not_driven() -> None:
    """The exemption is for a target that is not reached."""
    gate = _gate(engine().recompute(snapshot(sources=night(), position=2)))

    assert gate.reason is ReasonCode.TARGET_REACHED


def test_an_end_position_of_one_member_exempts_the_movement_of_the_window() -> None:
    """Two members per-member: one goes to 0 from 4, the other barely moves."""
    wish = Wish.target_per_member(
        Layer.SHADING,
        ReasonCode.SHADING_GEOMETRIC,
        (MemberTarget(LEFT, Position(0)), MemberTarget(RIGHT, Position(40))),
    )
    arbiter = build_arbiter([registered(Layer.SHADING, lambda _config, _world: wish)])

    def reason(left: int, right: int) -> ReasonCode:
        world = snapshot(observation=observed(left=left, right=right))
        return _gate(arbiter.recompute(window(LEFT, RIGHT), world)).reason

    assert reason(4, 38) is ReasonCode.SENT
    assert reason(1, 36) is ReasonCode.MIN_CHANGE


def _floor_of_30(*, knows_violation: bool) -> ConstraintRegistration:
    """Return a stand-in for the ventilation floor: no member lower than 30."""
    floor = Position(30)

    def apply(constraint: ConstraintInput) -> ConstraintResult | None:
        targets = tuple(
            MemberTarget(
                target.member_id,
                None if target.position is None else max(target.position, floor),
            )
            for target in constraint.targets
        )
        if targets == constraint.targets:
            return None
        return ConstraintResult(
            Constraint.VENTILATION_FLOOR, ReasonCode.VENTILATION_FLOOR, targets
        )

    def violated(constraint: ConstraintInput) -> bool:
        return any(
            position is not None and position < floor
            for position in constraint.current_positions.values()
        )

    return ConstraintRegistration(
        Constraint.VENTILATION_FLOOR,
        frozenset({WishClass.COMFORT}),
        apply,
        FunctionId.VENTILATION,
        violated_by_position=violated if knows_violation else None,
    )


def test_a_movement_that_restores_a_violated_constraint_is_exempt_from_the_minimum_change() -> (
    None
):
    """The shutter stands at 27, just below the floor of 30: it is raised."""
    restoring = build_arbiter(
        STUB_LAYERS, constraints=[_floor_of_30(knows_violation=True)]
    )
    unaware = build_arbiter(
        STUB_LAYERS, constraints=[_floor_of_30(knows_violation=False)]
    )

    def gate(arbiter: Arbiter, position: int, **changes: Any) -> GateOutcome:
        world = snapshot(sources=night(), position=position, **changes)
        decision = arbiter.recompute(window(), world)
        assert decision.target == Position(30)
        return _gate(decision)

    assert gate(restoring, 27) == GateOutcome.send()
    assert gate(unaware, 27).reason is ReasonCode.MIN_CHANGE
    # Above the floor nothing is violated: 33 to 30 is simply too little.
    assert gate(restoring, 33).reason is ReasonCode.MIN_CHANGE
    # The minimum interval still applies to the restoring movement.
    recently = WindowState(last_comfort_movement=NOW - timedelta(minutes=1))
    assert gate(restoring, 27, state=recently).reason is ReasonCode.MIN_INTERVAL


def test_a_constraint_that_does_not_apply_to_the_wish_restores_nothing() -> None:
    """The floor is about comfort; a storm below it is not a restoring movement."""
    arbiter = build_arbiter(
        STUB_LAYERS, constraints=[_floor_of_30(knows_violation=True)]
    )

    for sources in (storm(), fire()):
        decision = arbiter.recompute(window(), snapshot(sources=sources, position=27))
        assert decision.constraints == ()
        assert _gate(decision) == GateOutcome.send()


def test_the_constraints_of_this_block_cannot_be_violated_by_a_position() -> None:
    """Direction and frost say which movements are allowed, not where to stand."""
    for registration in BUILT_IN_CONSTRAINTS:
        assert registration.violated_by_position is None


def test_a_comfort_movement_inside_the_minimum_interval_is_deferred_until_it_ends() -> (
    None
):
    """The clock is the time of the last own comfort movement."""
    inside = WindowState(last_comfort_movement=NOW - timedelta(minutes=4))
    outside = WindowState(last_comfort_movement=NOW - timedelta(minutes=10))

    def gate(state: WindowState) -> GateOutcome:
        return _gate(engine().recompute(snapshot(sources=night(), state=state)))

    assert gate(inside) == GateOutcome.defer(
        GateRule.MOTOR_PROTECTION,
        ReasonCode.MIN_INTERVAL,
        until=NOW + timedelta(minutes=6),
    )
    assert gate(outside) == GateOutcome.send()


def test_motor_protection_never_holds_back_protection_or_fire() -> None:
    """Below the minimum change and inside the interval, both are sent."""
    state = WindowState(last_comfort_movement=NOW - timedelta(seconds=10))

    closing = engine().recompute(snapshot(sources=storm(), position=4, state=state))
    opening = engine().recompute(snapshot(sources=fire(), position=96, state=state))

    assert _gate(closing) == GateOutcome.send()
    assert _gate(opening) == GateOutcome.send()


def test_motor_protection_judges_the_largest_change_among_the_members() -> None:
    """One member has far to go: the window moves. A blind member is not counted."""
    subject = engine(window(LEFT, RIGHT))

    def reason(**members: int | None) -> ReasonCode:
        world = snapshot(sources=_shaded(40), observation=observed(**members))
        return _gate(subject.recompute(world)).reason

    assert reason(left=44, right=37) is ReasonCode.MIN_CHANGE
    assert reason(left=44, right=80) is ReasonCode.SENT
    assert reason(left=44, right=None) is ReasonCode.MIN_CHANGE
    assert reason(left=None, right=None) is ReasonCode.SENT


def test_zero_switches_a_part_of_motor_protection_off() -> None:
    """No minimum change, no minimum interval."""
    config = window(motor_protection=MotorProtectionSettings(0, timedelta(0)))
    state = WindowState(last_comfort_movement=NOW)

    gate = _gate(
        engine(config).recompute(
            snapshot(sources=_shaded(40), position=43, state=state)
        )
    )

    assert gate == GateOutcome.send()


# --- The order of the rules ---------------------------------------------------------


def test_the_first_rule_that_applies_decides() -> None:
    """Everything holds a comfort wish back at once; lift one rule after the other."""
    controls = Controls(
        dry_run=False,
        global_level=ControlLevel(maintenance_lock=True),
        group_level=ControlLevel(mode=OperatingMode.OFF),
        window_level=ControlLevel(paused=True),
    )
    state = WindowState(
        members=(_commanded(30, 5),),
        person_at_window=PersonAtWindowDam(ends_at=LATER),
        manual_override=_override(),
        last_comfort_movement=NOW - timedelta(seconds=5),
    )
    steps: list[tuple[Controls, WindowState]] = [(controls, state)]
    controls = replace(controls, global_level=ControlLevel())
    steps.append((controls, state))
    controls = replace(controls, group_level=ControlLevel())
    steps.append((controls, state))
    controls = replace(controls, window_level=ControlLevel())
    steps.append((controls, state))
    state = replace(state, person_at_window=None)
    steps.append((controls, state))
    state = replace(state, manual_override=None)
    steps.append((controls, state))
    state = replace(state, members=())
    steps.append((controls, state))
    state = replace(state, last_comfort_movement=None)
    steps.append((controls, state))

    reasons = [
        _gate(
            engine().recompute(
                snapshot(sources=night(), state=state, controls=controls)
            )
        ).reason
        for controls, state in steps
    ]

    assert reasons == [
        ReasonCode.MAINTENANCE_LOCK,
        ReasonCode.MODE_OFF,
        ReasonCode.PAUSED,
        ReasonCode.PERSON_AT_WINDOW,
        ReasonCode.MANUAL_OVERRIDE,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        ReasonCode.MIN_INTERVAL,
        ReasonCode.SENT,
    ]


def test_every_deferral_names_its_time_or_its_upper_bound() -> None:
    """Exactly one of the two, for every rule of this block that defers."""
    situations = {
        ReasonCode.COVER_UNAVAILABLE: snapshot(
            sources=night(), observation=observed(left="unavailable")
        ),
        ReasonCode.PERSON_AT_WINDOW: snapshot(
            sources=night(),
            state=WindowState(person_at_window=PersonAtWindowDam(ends_at=LATER)),
        ),
        ReasonCode.MANUAL_OVERRIDE: snapshot(
            sources=night(), state=WindowState(manual_override=_override())
        ),
        ReasonCode.MOVEMENT_IN_FLIGHT: snapshot(
            sources=night(), observation=observed(left="up:40")
        ),
        ReasonCode.MIN_INTERVAL: snapshot(
            sources=night(), state=WindowState(last_comfort_movement=NOW)
        ),
    }

    for reason, world in situations.items():
        gate = _gate(engine().recompute(world))
        assert gate.kind is GateKind.DEFER
        assert gate.reason is reason
        assert (gate.until is None) != (gate.reevaluate_no_later_than is None)
        known_end = reason in {
            ReasonCode.PERSON_AT_WINDOW,
            ReasonCode.MANUAL_OVERRIDE,
            ReasonCode.MIN_INTERVAL,
        }
        assert (gate.until is not None) is known_end


# --- Registration -------------------------------------------------------------------


def _staggered(gate: GateInput) -> GateOutcome | None:
    return GateOutcome.defer(
        GateRule.STAGGERING,
        ReasonCode.STAGGERED,
        until=gate.snapshot.time + timedelta(seconds=4),
    )


STAGGERING = GateRuleRegistration(
    GateRule.STAGGERING,
    frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
    _staggered,
    None,
)


def test_adding_a_gate_rule_is_a_registration() -> None:
    """A stand-in for staggering takes its place; fire skips it."""
    arbiter = build_arbiter(STUB_LAYERS, gate_rules=[STAGGERING])

    def gate(sources: dict[str, Any], **changes: Any) -> GateOutcome:
        return _gate(arbiter.recompute(window(), snapshot(sources=sources, **changes)))

    assert [entry.rule for entry in arbiter.gate_rules][-2:] == [
        GateRule.STAGGERING,
        GateRule.DRY_RUN,
    ]
    assert gate(storm()).reason is ReasonCode.STAGGERED
    assert gate(night()).until == NOW + timedelta(seconds=4)
    assert gate(night(), controls=on_level("window", paused=True)).reason is (
        ReasonCode.PAUSED
    )
    assert gate(fire()) == GateOutcome.send()


def test_the_registry_refuses_what_would_break_the_gate() -> None:
    """Twice the same rule, no classes, no lock, no dry-run, a wrong place."""
    bad: Any = "pause"
    without_lock = tuple(
        entry
        for entry in BUILT_IN_GATE_RULES
        if entry.rule is not GateRule.MAINTENANCE_LOCK
    )

    with pytest.raises(ValueError, match="'staggering' is registered twice"):
        build_arbiter((), gate_rules=[STAGGERING, STAGGERING])
    with pytest.raises(ValueError, match="names the wish classes"):
        GateRuleRegistration(GateRule.STAGGERING, frozenset(), _staggered, None)
    with pytest.raises(TypeError, match="member of 'GateRule'"):
        GateRuleRegistration(bad, ALL_CLASSES, _staggered, None)
    with pytest.raises(ValueError, match="without the gate rule 'maintenance_lock'"):
        Arbiter(gate_rules=without_lock)
    with pytest.raises(ValueError, match="without the gate rule 'dry_run'"):
        Arbiter(gate_rules=BUILT_IN_GATE_RULES[:-1])


def test_a_gate_rule_answers_in_its_own_name_and_never_sends() -> None:
    """A rule either holds back or returns nothing.

    Anything else is a programming error and counts like an exception of the
    rule: it holds the wish back, and the decision carries the fault.
    """
    classes = frozenset({WishClass.COMFORT})
    sends = GateRuleRegistration(
        GateRule.STAGGERING, classes, lambda _gate: GateOutcome.send(), None
    )
    impostor = GateRuleRegistration(GateRule.COMMAND_BACKOFF, classes, _staggered, None)

    for registration in (sends, impostor):
        arbiter = build_arbiter(STUB_LAYERS, gate_rules=[registration])
        decision = arbiter.recompute(window(), snapshot(sources=night()))

        assert decision.gate is not None
        assert decision.gate.kind is GateKind.DEFER
        assert decision.gate.reason is ReasonCode.GATE_RULE_FAILED
        assert decision.gate.rule is registration.rule
        (fault,) = decision.faults
        assert fault.place is registration.rule
        assert "holds back in its own name" in str(fault.exception)
