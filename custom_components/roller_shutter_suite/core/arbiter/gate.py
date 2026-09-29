"""The gate rules that belong to no single feature, and the dam mechanism.

Built here: maintenance lock (1), no member can execute the command (2),
target reached (3), operating mode (4), pause (5), the two dams (6, 7),
movement in flight (8), motor protection (9) and dry-run (12). Command backoff
(10) and staggering (11) are registered by the blocks that build them.

Every rule is a pure function of its ``GateInput`` and returns its outcome or
``None``. No rule knows about fire (see ``fire_bypass``) and none knows about
dry-run, except the last one: the arbiter hands a dry-run window its simulated
commands and marks the outcome as hypothetical.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    FunctionId,
    GateOutcome,
    GateRule,
    MemberConfig,
    MemberTracking,
    OverrideEndRule,
    OwnCommand,
    TravelDirection,
    WindowConfig,
    WindowState,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .capabilities import cannot_execute, has_no_position_feedback
from .controls import MODE_TABLE
from .registry import ALL_CLASSES, GateInput, GateRuleRegistration, outranks

_COMFORT: Final = frozenset({WishClass.COMFORT})
_PROTECTION_AND_COMFORT: Final = frozenset({WishClass.PROTECTION, WishClass.COMFORT})


# --- 1 Maintenance lock ---------------------------------------------------------


def _maintenance_lock(gate: GateInput) -> GateOutcome | None:
    if not gate.controls.maintenance_lock:
        return None
    return GateOutcome.suppress(GateRule.MAINTENANCE_LOCK, ReasonCode.MAINTENANCE_LOCK)


# --- 2 No member can execute the command ----------------------------------------


def _available_with_target(gate: GateInput) -> list[MemberConfig]:
    """Return the members that have a target and are available right now."""
    wanted = {target.member_id for target in gate.to_send}
    available = {
        member.member_id
        for member in gate.snapshot.observation.members
        if member.observation.available
    }
    return [
        member
        for member in gate.config.members
        if member.member_id in wanted and member.member_id in available
    ]


def addressed_members(gate: GateInput) -> list[MemberConfig]:
    """Return the members a send commands: the core names them itself.

    A member is addressed if it has a target, is available right now, and
    does not stand at that target within its own tolerance. A member without
    position feedback cannot be judged and is addressed. A member that is
    not addressed gets no command and no record (ruling of the project owner
    for block C06). The rules "no member can execute" and "target reached"
    reason over the available members with a target, "movement in flight"
    over these; the decision names them (``Decision.addressed``), and the
    runtime and the simulation send to exactly them.
    """
    return [
        member
        for member in _available_with_target(gate)
        if not _stands_at_target(gate, member)
    ]


def completing_members(gate: GateInput) -> frozenset[str]:
    """Return the members a send would bring to a command they missed, if that is all.

    A member that was unavailable when the other members were commanded
    remembers the command it missed (``MemberState.missed_command``). If
    every addressed member has missed a command with the target it has now,
    and with the class of the wish at the gate, the send is the completion of
    that command and not a fresh wish: the members are commanded with the
    class and the reason of the missed command, the minimum interval does not
    apply, and it counts no comfort movement. Otherwise, or for a window in
    dry-run, which commands nothing, the set is empty.
    """
    if gate.controls.dry_run:
        return frozenset()
    targets = {target.member_id: target.position for target in gate.to_send}
    missed = {
        member.member_id: member.missed_command
        for member in gate.snapshot.state.members
        if member.missed_command is not None
    }
    addressed = addressed_members(gate)
    completing = frozenset(
        member.member_id
        for member in addressed
        if (command := missed.get(member.member_id)) is not None
        and command.target == targets[member.member_id]
        and command.wish_class is gate.wish.wish_class
    )
    return completing if len(completing) == len(addressed) else frozenset()


def _no_member_can_execute(gate: GateInput) -> GateOutcome | None:
    addressed = _available_with_target(gate)
    if not addressed:
        return GateOutcome.defer(
            GateRule.NO_MEMBER_CAN_EXECUTE,
            ReasonCode.COVER_UNAVAILABLE,
            reevaluate_no_later_than=gate.snapshot.time + gate.config.reevaluate_after,
        )
    if all(cannot_execute(member.capabilities) for member in addressed):
        return GateOutcome.suppress(
            GateRule.NO_MEMBER_CAN_EXECUTE, ReasonCode.CAPABILITY_MISSING
        )
    return None


# --- 3 Target reached -----------------------------------------------------------


def _target_reached(gate: GateInput) -> GateOutcome | None:
    """Compare with the real position, also for a window in dry-run.

    A member without position feedback counts as reached if its last real own
    command already had this target, unless that command failed
    (``command_failed``): the actuator never received it. Members that are
    unavailable are not commanded and therefore not judged.
    """
    targets = {
        target.member_id: target.position
        for target in gate.to_send
        if target.position is not None
    }
    reported = gate.current_positions
    real_commands = {
        member.member_id: member.last_own_command.target
        for member in gate.snapshot.state.members
        if member.last_own_command is not None and not member.last_own_command.failed
    }
    addressed = _available_with_target(gate)
    if not addressed:
        return None  # nobody to judge: nothing is known to be reached
    for member in addressed:
        target = targets[member.member_id]
        position = reported[member.member_id]
        if has_no_position_feedback(member.capabilities):
            if real_commands.get(member.member_id) != target:
                return None
        elif (
            position is None
            or abs(position.value - target.value) > member.capabilities.tolerance
        ):
            return None
    return GateOutcome.suppress(GateRule.TARGET_REACHED, ReasonCode.TARGET_REACHED)


# --- 4 Operating mode, 5 pause --------------------------------------------------


def _operating_mode(gate: GateInput) -> GateOutcome | None:
    entry = MODE_TABLE[gate.controls.mode]
    if entry.reason is None or gate.wish.wish_class not in entry.holds_back:
        return None
    return GateOutcome.suppress(GateRule.OPERATING_MODE, entry.reason)


def _pause(gate: GateInput) -> GateOutcome | None:
    if not gate.controls.paused:
        return None
    return GateOutcome.suppress(GateRule.PAUSE, ReasonCode.PAUSED)


# --- 6 and 7 The dam mechanism --------------------------------------------------


@dataclass(frozen=True, slots=True)
class ArmedDam:
    """A dam as it stands in the persisted state: until when it holds.

    ``ends_at`` is ``None`` if the dam ends with a condition whose time is not
    known (the room becomes empty, the shading episode ends).
    """

    ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class Dam:
    """A dam names what it holds back and until when.

    - ``holds_back``: the wish classes it holds back; never fire.
    - ``lets_pass``: reason codes of wishes that pass although their class is
      held back.
    - ``armed``: reads the dam from what the gate sees (the persisted state,
      and for a dam that ends with a condition the configuration and the
      sources); ``None`` if it is not armed or its condition has ended it.
      Arming and ending a dam is not the gate's business (``core/dams``);
      the gate only never lets a dam hold longer than its end.

    A dam whose end lies in the past has no effect. A dam with a known end
    defers until that end; a dam without one suppresses.
    """

    rule: GateRule
    reason: ReasonCode
    holds_back: frozenset[WishClass]
    lets_pass: frozenset[ReasonCode]
    armed: Callable[[GateInput], ArmedDam | None]

    def __post_init__(self) -> None:
        """Refuse a dam that would hold back fire."""
        if WishClass.FIRE in self.holds_back:
            raise ValueError("a dam never holds back fire")

    def evaluate(self, gate: GateInput) -> GateOutcome | None:
        """Return the outcome of the dam for the wish at the gate."""
        armed = self.armed(gate)
        if armed is None or gate.wish.reason in self.lets_pass:
            return None
        if armed.ends_at is None:
            return GateOutcome.suppress(self.rule, self.reason)
        if armed.ends_at <= gate.snapshot.time:
            return None
        return GateOutcome.defer(self.rule, self.reason, until=armed.ends_at)

    def registration(self) -> GateRuleRegistration:
        """Return the dam as a gate rule."""
        return GateRuleRegistration(
            self.rule, self.holds_back, self.evaluate, FunctionId.MANUAL_OVERRIDE
        )


def _person_at_window(gate: GateInput) -> ArmedDam | None:
    dam = gate.snapshot.state.person_at_window
    return None if dam is None else ArmedDam(dam.ends_at)


def room_empty_long_enough(config: WindowConfig, snapshot: WorldSnapshot) -> bool:
    """Return whether the room of an override has been empty for the configured time.

    Only for an override with the end rule "the room has been empty". The
    presence source has to be configured (a reference, neither "none" nor
    blind) and to say "empty" (off) now, and the dam has to have seen it say
    so without interruption for ``override_room_empty_after``
    (``ManualOverrideDam.room_empty_since``, kept by ``core/dams``). A
    source without a value never counts as "empty": missing data is not
    good news.
    """
    dam = snapshot.state.manual_override
    if dam is None or dam.end_rule is not OverrideEndRule.ROOM_EMPTY:
        return False
    source = config.override_presence_source
    if not isinstance(source, str):
        return False
    value = snapshot.sources.get(source)
    if value is None or not value.has_value or value.value is not False:
        return False
    since = dam.room_empty_since
    return (
        since is not None and since + config.override_room_empty_after <= snapshot.time
    )


def override_ended_by_condition(config: WindowConfig, snapshot: WorldSnapshot) -> bool:
    """Return whether the condition of the armed manual override has ended it.

    The two end rules without a known end: the room has been empty for the
    configured time, or the shading episode it was armed during has ended.
    ``core/dams`` ends such a dam and raises the event; the gate reads the
    same function, so the dam never holds a moment longer than its rule
    says, whether or not the dam was ended already.
    """
    dam = snapshot.state.manual_override
    if dam is None:
        return False
    if dam.end_rule is OverrideEndRule.SHADING_EPISODE_END:
        episode = snapshot.state.shading_episode
        return episode is None or episode.active_since is None
    return room_empty_long_enough(config, snapshot)


def _manual_override(gate: GateInput) -> ArmedDam | None:
    dam = gate.snapshot.state.manual_override
    if dam is None or override_ended_by_condition(gate.config, gate.snapshot):
        return None
    return ArmedDam(dam.ends_at)


PERSON_AT_WINDOW_DAM: Final = Dam(
    rule=GateRule.PERSON_AT_WINDOW_DAM,
    reason=ReasonCode.PERSON_AT_WINDOW,
    holds_back=_PROTECTION_AND_COMFORT,
    lets_pass=frozenset(),
    armed=_person_at_window,
)
"""Holds back protection and comfort, never fire; it always has an end."""

MANUAL_OVERRIDE_DAM: Final = Dam(
    rule=GateRule.MANUAL_OVERRIDE_DAM,
    reason=ReasonCode.MANUAL_OVERRIDE,
    holds_back=_COMFORT,
    lets_pass=frozenset({ReasonCode.PROTECTION_RETURN_MANUAL}),
    armed=_manual_override,
)
"""Holds back comfort, except the return to the manual position.

That return restores exactly what the dam protects. It is a comfort wish, so
every other rule applies to it: the person-at-the-window dam stands before
this one and still holds it back, and every constraint applies. Whether the
return wish exists at all (the override is still armed, the waiting time has
passed) is the decision of the protection layer.
"""


# --- 8 Movement in flight -------------------------------------------------------
#
# The rule has two parts, registered separately because they apply to different
# wish classes. Neither depends on the other being asked first.
#
# - The same targets as the pending own commands: nothing is sent again. This
#   holds for every class, fire included. It hangs on the running expectation
#   window and not on "was sent once": when the window has closed and the
#   target is still not reached, the command is no longer pending, and fire is
#   sent again at once. If the wish is of a higher class than a pending
#   command, the movement is taken over: see ``take_over``.
# - Other targets, or a movement nobody commanded: a comfort wish waits until
#   the members have come to rest. Protection and fire retarget at once.


START_ALLOWANCE: Final = timedelta(seconds=10)
"""How long a movement may take to start before the deadline counts (section 8.3)."""

TRAVEL_SLACK: Final = 1.5
"""The factor on the share of the travel time: travel is not linear in percent."""

END_ALLOWANCE: Final = timedelta(seconds=5)
"""What a movement into an end stop takes beyond its share of the travel."""


def member_expectation_end(member: MemberConfig, command: OwnCommand) -> datetime:
    """Return the deadline of the expectation of an own command to a member.

    The formula of section 8.3 of the specification: the time of the command
    plus ``report delay + start allowance + travel time of the direction *
    share of the travel * slack + end allowance``, with a start allowance of
    10 s, a slack of 1.5 and an end allowance of 5 s. The share of the travel
    runs from the position the member reported when the command was given
    (``OwnCommand.start_position``) to the target; without a start position
    the whole travel counts. The proportional share alone underestimates a
    movement that ends in an end stop, and a fixed allowance alone would
    raise a false "did not react" on a polled platform.

    This is the one deadline: the gate reads it through
    ``expectation_window_end`` (a command counts as pending until then), the
    tracker judges "no reaction" and "not finished" at it, and the runtime
    and the time-lapse simulation wake the window up at it. A later change of
    the formula reaches every waiter at once.
    """
    profile = member.capabilities
    travel_time = (
        profile.travel_time_up
        if command.direction is TravelDirection.UP
        else profile.travel_time_down
    )
    return (
        command.time
        + profile.report_delay
        + START_ALLOWANCE
        + travel_time * (command.share_of_travel * TRAVEL_SLACK)
        + END_ALLOWANCE
    )


SETTLE_TIME: Final = timedelta(seconds=2)
"""How long after a report of rest a movement is judged (section 8.3)."""


def settle_time(member: MemberConfig, tracking: MemberTracking) -> timedelta:
    """Return how long the tracker waits after a report of rest before it judges.

    The settle time of section 8.3 (2 s) covers platforms that write the
    position shortly before or after the resting state. A movement nobody
    commanded on a member that showed no transit state is seen only through
    its reports of rest, and on a platform with a report delay the next one
    comes up to that delay later: the settle time grows by the report delay,
    so a person's movement on a polled platform is judged once, at its end.
    """
    if tracking.external and not tracking.transit_seen:
        return SETTLE_TIME + member.capabilities.report_delay
    return SETTLE_TIME


def wake_ups(
    config: WindowConfig, state: WindowState, now: datetime, *, dry_run: bool
) -> tuple[datetime, ...]:
    """Return every instant after ``now`` at which the caller has to wake the window.

    The one source of the timers of the runtime and of the time-lapse
    simulation, next to ``member_expectation_end``, so that neither computes
    a time of its own:

    - the deadline of every pending own command (the simulated ones for a
      window in dry-run), where the gate stops counting it as pending and
      the tracker judges "no reaction" or "not finished";
    - the end of the settle time of every member that has come to rest;
    - the end of the person-at-the-window dam and of the manual override,
      and for the rule "the room has been empty" the instant the configured
      time has passed since the room was seen empty.

    The caller hands the window to ``Engine.elapse`` at each, and then
    recomputes it. Deferrals and the planned actions of the schedule come
    from the decision and the schedule as before.
    """
    times: set[datetime] = set()
    commands: dict[str, OwnCommand] = (
        {c.member_id: c.command for c in state.simulated.commands}
        if dry_run and state.simulated is not None
        else {
            m.member_id: m.last_own_command
            for m in state.members
            if m.last_own_command is not None
        }
    )
    by_id = {member.member_id: member for member in config.members}
    for member_id, command in commands.items():
        if member_id in by_id:
            times.add(member_expectation_end(by_id[member_id], command))
    for member_state in state.members:
        tracking = member_state.tracking
        member = by_id.get(member_state.member_id)
        if member is not None and tracking.rested_at is not None:
            times.add(tracking.rested_at + settle_time(member, tracking))
    if state.person_at_window is not None:
        times.add(state.person_at_window.ends_at)
    override = state.manual_override
    if override is not None:
        if override.ends_at is not None:
            times.add(override.ends_at)
        if override.room_empty_since is not None:
            times.add(override.room_empty_since + config.override_room_empty_after)
    return tuple(sorted(time for time in times if time > now))


def expectation_window_end(
    gate: GateInput, member_id: str, command: OwnCommand
) -> datetime | None:
    """Return until when an own command counts as pending; an upper bound.

    See ``member_expectation_end``. A command to a member the window no
    longer has is ignored.
    """
    for member in gate.config.members:
        if member.member_id == member_id:
            return member_expectation_end(member, command)
    return None


def _pending(gate: GateInput) -> dict[str, tuple[OwnCommand, datetime]]:
    """Return the own commands whose expectation window is still running."""
    pending: dict[str, tuple[OwnCommand, datetime]] = {}
    for member_id, command in gate.own_commands.items():
        end = expectation_window_end(gate, member_id, command)
        if end is not None and gate.snapshot.time < end:
            pending[member_id] = (command, end)
    return pending


def _stands_at_target(gate: GateInput, member: MemberConfig) -> bool:
    """Return whether a member reports a position within tolerance of its target.

    A member without position feedback cannot be judged and never stands.
    """
    if has_no_position_feedback(member.capabilities):
        return False
    position = gate.current_positions.get(member.member_id)
    target = next(
        (t.position for t in gate.to_send if t.member_id == member.member_id), None
    )
    return (
        position is not None
        and target is not None
        and abs(position.value - target.value) <= member.capabilities.tolerance
    )


def _all_commanded(gate: GateInput, pending: Mapping[str, OwnCommand]) -> bool:
    """Return whether a send now would repeat what is under way.

    A send commands the addressed members only (``addressed_members``). So
    a send would repeat the pending commands if every addressed member has a
    pending command with its target, and there is at least one.
    """
    targets = {target.member_id: target.position for target in gate.to_send}
    commanded = addressed_members(gate)
    return bool(commanded) and all(
        member.member_id in pending
        and pending[member.member_id].target == targets[member.member_id]
        for member in commanded
    )


def _repeats(gate: GateInput, pending: dict[str, tuple[OwnCommand, datetime]]) -> bool:
    """Return whether a send now would repeat the pending commands."""
    return _all_commanded(gate, {key: value[0] for key, value in pending.items()})


def _same_command_pending(gate: GateInput) -> GateOutcome | None:
    """Do not send what is already under way; a higher class takes it over."""
    pending = _pending(gate)
    if not _repeats(gate, pending):
        return None
    taken_over = any(
        outranks(gate.wish.wish_class, pending[target.member_id][0].wish_class)
        for target in gate.to_send
        if target.member_id in pending
    )
    return GateOutcome.suppress(
        GateRule.MOVEMENT_IN_FLIGHT,
        ReasonCode.MOVEMENT_TAKEN_OVER if taken_over else ReasonCode.DUPLICATE_COMMAND,
    )


def fire_command_pending(gate: GateInput) -> bool:
    """Return whether a real fire command with these targets is still pending.

    For the safety net of the arbiter: a fire wish that passed a gate rule
    that raised is not sent again while every target at the gate is the
    target of an own command of class fire whose expectation window still
    runs. It reads the **persisted, real** own commands
    (``WindowState.members``), never the simulated ones and never
    ``GateInput.own_commands``: what passed a failed rule was really sent,
    also for a window in dry-run whose dry-run rule failed.
    """
    pending: dict[str, OwnCommand] = {}
    for member in gate.snapshot.state.members:
        command = member.last_own_command
        if command is None or command.wish_class is not WishClass.FIRE:
            continue
        end = expectation_window_end(gate, member.member_id, command)
        if end is not None and gate.snapshot.time < end:
            pending[member.member_id] = command
    return _all_commanded(gate, pending)


def _wait_for_rest(gate: GateInput) -> GateOutcome | None:
    """Hold back a comfort wish while another movement is under way.

    A pending own command with other targets counts, and for an armed window
    a movement that a member reports, whoever started it, or that the
    tracker sees (``WindowState.moving``: from the first member that moves
    until the last one has settled, also for a member without transit
    states), so a comfort movement never interrupts a person. What moves a
    window in dry-run is another controller; such a window is judged by its
    simulated commands.
    """
    pending = _pending(gate)
    moving = not gate.controls.dry_run and (
        gate.snapshot.observation.reports_movement or gate.snapshot.state.moving
    )
    if (not pending and not moving) or _repeats(gate, pending):
        return None
    return GateOutcome.defer(
        GateRule.MOVEMENT_IN_FLIGHT,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        reevaluate_no_later_than=max(
            (end for _, end in pending.values()),
            default=gate.snapshot.time + gate.config.reevaluate_after,
        ),
    )


# --- 9 Motor protection ---------------------------------------------------------


def _is_fresh(gate: GateInput) -> bool:
    """Return whether the trigger of the wish lies after the last comfort movement.

    A fresh wish is something new: a boundary of the schedule fired, sleep
    mode was switched, a request arrived, an episode began. The minimum
    interval exists against flapping and does not hold it back. Not fresh are
    tracking inside an episode and an older wish that wins again because
    another layer dropped out, and a wish that states no trigger at all.
    """
    trigger = gate.wish.triggered_at
    moved_at = gate.last_comfort_movement
    return trigger is not None and moved_at is not None and trigger > moved_at


def _drives_to_an_end_position(gate: GateInput) -> bool:
    """Return whether a member is sent to 0 or 100 and is not there yet."""
    reported = gate.current_positions
    tolerances = {
        member.member_id: member.capabilities.tolerance
        for member in gate.config.members
    }
    return any(
        target.position in (FULLY_OPEN, FULLY_CLOSED)
        and (position := reported.get(target.member_id)) is not None
        and abs(target.position.value - position.value) > tolerances[target.member_id]
        for target in gate.to_send
    )


def _motor_protection(gate: GateInput) -> GateOutcome | None:
    """Judge the largest change among the members, then the minimum interval.

    Exempt from the minimum change, never from the minimum interval: a target
    of 0 or 100 that is not reached (a shutter must not stay a few percent
    open because the rest is "not worth a movement"), and a movement that
    restores a constraint the current position violates.

    The completion of a command that a member missed while it was
    unavailable is not subject to the minimum interval: the wish was fresh
    when the command was given (``GateInput.completes_command``).
    """
    settings = gate.config.motor_protection
    reported = gate.current_positions
    changes = [
        abs(target.position.value - position.value)
        for target in gate.to_send
        if target.position is not None
        and (position := reported.get(target.member_id)) is not None
    ]
    exempt = gate.restores_constraint or _drives_to_an_end_position(gate)
    if changes and max(changes) < settings.min_change and not exempt:
        return GateOutcome.suppress(GateRule.MOTOR_PROTECTION, ReasonCode.MIN_CHANGE)
    if gate.completes_command:
        return None
    if gate.last_comfort_movement is not None and not _is_fresh(gate):
        end = gate.last_comfort_movement + settings.min_interval
        if gate.snapshot.time < end:
            # A wish that states no trigger cannot be judged. It is held like
            # one that is not fresh, and the record says why, so that a layer
            # that forgot its trigger shows up, also in dry-run.
            reason = (
                ReasonCode.TRIGGER_TIME_MISSING
                if gate.wish.triggered_at is None
                else ReasonCode.MIN_INTERVAL
            )
            return GateOutcome.defer(GateRule.MOTOR_PROTECTION, reason, until=end)
    return None


# --- 12 Dry-run -----------------------------------------------------------------


def _dry_run(gate: GateInput) -> GateOutcome | None:
    """Suppress what reaches the last barrier: it would have been sent."""
    if not gate.controls.dry_run:
        return None
    return GateOutcome.would_have_sent(gate.to_send)


BUILT_IN_GATE_RULES: Final = (
    GateRuleRegistration(
        GateRule.MAINTENANCE_LOCK, ALL_CLASSES, _maintenance_lock, None
    ),
    GateRuleRegistration(
        GateRule.NO_MEMBER_CAN_EXECUTE, ALL_CLASSES, _no_member_can_execute, None
    ),
    GateRuleRegistration(GateRule.TARGET_REACHED, ALL_CLASSES, _target_reached, None),
    GateRuleRegistration(
        GateRule.OPERATING_MODE, _PROTECTION_AND_COMFORT, _operating_mode, None
    ),
    GateRuleRegistration(GateRule.PAUSE, _COMFORT, _pause, FunctionId.PAUSE),
    PERSON_AT_WINDOW_DAM.registration(),
    MANUAL_OVERRIDE_DAM.registration(),
    GateRuleRegistration(
        GateRule.MOVEMENT_IN_FLIGHT,
        _COMFORT,
        _wait_for_rest,
        None,
        reasons=frozenset({ReasonCode.MOVEMENT_IN_FLIGHT}),
    ),
    GateRuleRegistration(
        GateRule.MOVEMENT_IN_FLIGHT,
        ALL_CLASSES,
        _same_command_pending,
        None,
        reasons=frozenset(
            {ReasonCode.DUPLICATE_COMMAND, ReasonCode.MOVEMENT_TAKEN_OVER}
        ),
    ),
    GateRuleRegistration(
        GateRule.MOTOR_PROTECTION,
        _COMFORT,
        _motor_protection,
        FunctionId.MOTOR_PROTECTION,
    ),
    GateRuleRegistration(GateRule.DRY_RUN, ALL_CLASSES, _dry_run, None),
)
"""The gate rules of this block. The arbiter sorts rules by their place."""
