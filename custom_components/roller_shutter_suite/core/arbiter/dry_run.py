"""The simulated state of a window in dry-run.

A window in dry-run never commands anything. So that its decisions still read
like those of an armed window, a would-be send is remembered as a simulated
command, with its time, in ``WindowState.simulated``. The gate rules that
depend on own commands judge a dry-run window by these commands and never by
the real ones; the real motor protection clock is never touched.

**The standing would-be command.** An armed window that has sent a command
moves, reaches the target, and its next decisions read ``target_reached``. A
window in dry-run does not move. If the simulated command counted against the
very wish it stands for, the record would flap: "would have sent 30", then
``duplicate_command`` or ``min_interval`` because of that simulated command,
and so on. Therefore: while the simulated command has the same targets as
the wish at the gate, it *is* that wish's command. The own-command rules do
not count it against itself, the outcome stays "would have sent", and nothing
new is remembered. A wish with other targets is judged against the simulated
command and its clock like any new command would be.

Everything here is a pure function from a state to a state. Nothing arms a
dam, and nothing changes the owner of the position.
"""

from dataclasses import replace

from custom_components.roller_shutter_suite.core.model import (
    Decision,
    GateRule,
    MemberCommand,
    MemberTarget,
    OwnCommand,
    Position,
    PositionOwner,
    SimulatedState,
    TravelDirection,
    WindowState,
    WishClass,
    WorldSnapshot,
)

from .registry import outranks, reported_positions

_HALFWAY = 50


def simulated_state(state: WindowState) -> SimulatedState:
    """Return the simulated state of a window; an empty one if there is none."""
    return state.simulated if state.simulated is not None else SimulatedState()


def is_standing(
    simulated: SimulatedState, to_send: tuple[MemberTarget, ...], wish_class: WishClass
) -> bool:
    """Return whether the simulated commands are the would-be command of this wish.

    They are if every target at the gate is the target of a simulated command
    and no such command is of a lower class than the wish. A command of a
    lower class is not the wish's own: while its expectation window runs, the
    wish takes it over, and afterwards the wish would have sent anew.
    """
    commanded = {command.member_id: command.command for command in simulated.commands}
    return all(
        (command := commanded.get(target.member_id)) is not None
        and command.target == target.position
        and not outranks(wish_class, command.wish_class)
        for target in to_send
    )


def _direction(target: Position, reported: Position | None) -> TravelDirection:
    if reported is not None and reported != target:
        return TravelDirection.UP if target > reported else TravelDirection.DOWN
    return TravelDirection.UP if target.value >= _HALFWAY else TravelDirection.DOWN


def remember_would_be_send(snapshot: WorldSnapshot, decision: Decision) -> WindowState:
    """Return the state after a decision: a would-be send is remembered.

    Only the outcome of the rule ``dry_run`` is a would-be send. Every other
    decision, a standing would-be command, and every decision of an armed
    window leave the state as it is. The real state is never touched: no own
    command, no motor protection clock, no dam, no owner.
    """
    state = snapshot.state
    gate = decision.gate
    if (
        not snapshot.controls.dry_run
        or gate is None
        or gate.rule is not GateRule.DRY_RUN
        or decision.winning_wish is None
    ):
        return state
    simulated = simulated_state(state)
    wish_class = decision.winning_wish.wish_class
    if is_standing(simulated, gate.would_send, wish_class):
        return state
    reported = reported_positions(snapshot)
    commands = {command.member_id: command for command in simulated.commands}
    would_send = [
        (target.member_id, target.position)
        for target in gate.would_send
        if target.position is not None
    ]
    for member_id, position in would_send:
        commands[member_id] = MemberCommand(
            member_id,
            OwnCommand(
                command_id=f"dry-run:{member_id}:{snapshot.time.isoformat()}",
                target=position,
                direction=_direction(position, reported.get(member_id)),
                time=snapshot.time,
                wish_class=wish_class,
                reason=decision.winning_wish.reason,
            ),
        )
    clock = (
        snapshot.time
        if wish_class is WishClass.COMFORT
        else simulated.last_comfort_movement
    )
    return replace(
        state,
        simulated=SimulatedState(
            commands=tuple(commands.values()), last_comfort_movement=clock
        ),
    )


def arm(state: WindowState) -> WindowState:
    """Return the state a window starts with when it is armed.

    The simulated state is discarded, and the window starts clean: no dam, and
    nobody is known to own the position.
    """
    return replace(
        state,
        simulated=None,
        manual_override=None,
        person_at_window=None,
        owner=PositionOwner.UNKNOWN,
    )
