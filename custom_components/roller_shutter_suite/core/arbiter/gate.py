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

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from custom_components.roller_shutter_suite.core.model import (
    GateOutcome,
    GateRule,
    MemberConfig,
    OwnCommand,
    TravelDirection,
    WindowState,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .capabilities import cannot_execute, has_no_position_feedback
from .controls import MODE_TABLE
from .registry import ALL_CLASSES, GateInput, GateRuleRegistration

_COMFORT: Final = frozenset({WishClass.COMFORT})
_PROTECTION_AND_COMFORT: Final = frozenset({WishClass.PROTECTION, WishClass.COMFORT})


# --- 1 Maintenance lock ---------------------------------------------------------


def _maintenance_lock(gate: GateInput) -> GateOutcome | None:
    if not gate.controls.maintenance_lock:
        return None
    return GateOutcome.suppress(GateRule.MAINTENANCE_LOCK, ReasonCode.MAINTENANCE_LOCK)


# --- 2 No member can execute the command ----------------------------------------


def _addressed_members(gate: GateInput) -> list[MemberConfig]:
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


def _no_member_can_execute(gate: GateInput) -> GateOutcome | None:
    addressed = _addressed_members(gate)
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
    command already had this target. Members that are unavailable are not
    commanded and therefore not judged.
    """
    targets = {
        target.member_id: target.position
        for target in gate.to_send
        if target.position is not None
    }
    reported = gate.current_positions
    real_commands = gate.snapshot.state.commanded_targets
    addressed = _addressed_members(gate)
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
    - ``armed``: reads the dam from the persisted state; ``None`` if it is not
      armed. Arming and ending a dam is not the gate's business.

    A dam whose end lies in the past has no effect. A dam with a known end
    defers until that end; a dam without one suppresses.
    """

    rule: GateRule
    reason: ReasonCode
    holds_back: frozenset[WishClass]
    lets_pass: frozenset[ReasonCode]
    armed: Callable[[WindowState], ArmedDam | None]

    def __post_init__(self) -> None:
        """Refuse a dam that would hold back fire."""
        if WishClass.FIRE in self.holds_back:
            raise ValueError("a dam never holds back fire")

    def evaluate(self, gate: GateInput) -> GateOutcome | None:
        """Return the outcome of the dam for the wish at the gate."""
        armed = self.armed(gate.snapshot.state)
        if armed is None or gate.wish.reason in self.lets_pass:
            return None
        if armed.ends_at is None:
            return GateOutcome.suppress(self.rule, self.reason)
        if armed.ends_at <= gate.snapshot.time:
            return None
        return GateOutcome.defer(self.rule, self.reason, until=armed.ends_at)

    def registration(self) -> GateRuleRegistration:
        """Return the dam as a gate rule."""
        return GateRuleRegistration(self.rule, self.holds_back, self.evaluate)


def _person_at_window(state: WindowState) -> ArmedDam | None:
    dam = state.person_at_window
    return None if dam is None else ArmedDam(dam.ends_at)


def _manual_override(state: WindowState) -> ArmedDam | None:
    dam = state.manual_override
    return None if dam is None else ArmedDam(dam.ends_at)


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


def _travel_end(
    gate: GateInput, member_id: str, command: OwnCommand
) -> datetime | None:
    """Return until when a command can still be travelling; an upper bound.

    It is the full travel time of the direction plus the report delay of the
    member. A command to a member the window no longer has is ignored.
    """
    for member in gate.config.members:
        if member.member_id == member_id:
            profile = member.capabilities
            travel_time = (
                profile.travel_time_up
                if command.direction is TravelDirection.UP
                else profile.travel_time_down
            )
            return command.time + travel_time + profile.report_delay
    return None


def _movement_in_flight(gate: GateInput) -> GateOutcome | None:
    """Hold back a comfort wish while an own command or a movement is under way.

    A command is pending until its travel end. A movement that a member
    reports counts too, whoever started it, but only for an armed window: what
    moves a window in dry-run is another controller, and a dry-run window is
    judged by its simulated commands.
    """
    time = gate.snapshot.time
    pending: dict[str, OwnCommand] = {}
    ends: list[datetime] = []
    for member_id, command in gate.own_commands.items():
        end = _travel_end(gate, member_id, command)
        if end is not None and time < end:
            pending[member_id] = command
            ends.append(end)
    moving = not gate.controls.dry_run and gate.snapshot.observation.reports_movement
    if not pending and not moving:
        return None
    if pending and all(
        target.member_id in pending
        and pending[target.member_id].target == target.position
        for target in gate.to_send
    ):
        return GateOutcome.suppress(
            GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND
        )
    return GateOutcome.defer(
        GateRule.MOVEMENT_IN_FLIGHT,
        ReasonCode.MOVEMENT_IN_FLIGHT,
        reevaluate_no_later_than=max(ends, default=time + gate.config.reevaluate_after),
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


def _motor_protection(gate: GateInput) -> GateOutcome | None:
    """Judge the largest change among the members, then the minimum interval."""
    settings = gate.config.motor_protection
    reported = gate.current_positions
    changes = [
        abs(target.position.value - position.value)
        for target in gate.to_send
        if target.position is not None
        and (position := reported.get(target.member_id)) is not None
    ]
    if changes and max(changes) < settings.min_change:
        return GateOutcome.suppress(GateRule.MOTOR_PROTECTION, ReasonCode.MIN_CHANGE)
    if gate.last_comfort_movement is not None and not _is_fresh(gate):
        end = gate.last_comfort_movement + settings.min_interval
        if gate.snapshot.time < end:
            return GateOutcome.defer(
                GateRule.MOTOR_PROTECTION, ReasonCode.MIN_INTERVAL, until=end
            )
    return None


# --- 12 Dry-run -----------------------------------------------------------------


def _dry_run(gate: GateInput) -> GateOutcome | None:
    """Suppress what reaches the last barrier: it would have been sent."""
    if not gate.controls.dry_run:
        return None
    return GateOutcome.would_have_sent(gate.to_send)


BUILT_IN_GATE_RULES: Final = (
    GateRuleRegistration(GateRule.MAINTENANCE_LOCK, ALL_CLASSES, _maintenance_lock),
    GateRuleRegistration(
        GateRule.NO_MEMBER_CAN_EXECUTE, ALL_CLASSES, _no_member_can_execute
    ),
    GateRuleRegistration(GateRule.TARGET_REACHED, ALL_CLASSES, _target_reached),
    GateRuleRegistration(
        GateRule.OPERATING_MODE, _PROTECTION_AND_COMFORT, _operating_mode
    ),
    GateRuleRegistration(GateRule.PAUSE, _COMFORT, _pause),
    PERSON_AT_WINDOW_DAM.registration(),
    MANUAL_OVERRIDE_DAM.registration(),
    GateRuleRegistration(GateRule.MOVEMENT_IN_FLIGHT, _COMFORT, _movement_in_flight),
    GateRuleRegistration(GateRule.MOTOR_PROTECTION, _COMFORT, _motor_protection),
    GateRuleRegistration(GateRule.DRY_RUN, ALL_CLASSES, _dry_run),
)
"""The gate rules of this block. The arbiter sorts rules by their place."""
