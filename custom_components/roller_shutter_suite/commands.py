"""What the runtime remembers when the gate lets a wish through.

A decision whose gate outcome is "send" names the target of every member.
The runtime hands each target to the actuator port under a fresh command
identifier and writes the command down as the **own command** of the member
in the persisted window state, with the class and the reason of the wish.
That record is what the gate rules about own commands read on the next
recompute (a command that is still inside its expectation window is not
sent again; a wish of a higher class takes it over), and it is what survives
a reload, so that a reload during a movement continues the same expectation
instead of sending the command a second time.

The result of a command, the backoff and the movement tracker belong to
later blocks; this module only records that a command was given.
"""

from dataclasses import replace
from datetime import datetime
from uuid import uuid4

from .core.model import (
    Decision,
    GateKind,
    MemberCommand,
    MemberState,
    OwnCommand,
    Position,
    TravelDirection,
    WindowState,
    WishClass,
    WorldSnapshot,
)

_MIDDLE = Position(50)
"""Without a position, a target from 50 upwards is an opening (section 8.1)."""


def _direction(
    snapshot: WorldSnapshot, member_id: str, target: Position
) -> TravelDirection:
    for member in snapshot.observation.members:
        if member.member_id == member_id and member.observation.position is not None:
            current = member.observation.position
            return TravelDirection.UP if target > current else TravelDirection.DOWN
    return TravelDirection.UP if target >= _MIDDLE else TravelDirection.DOWN


def commands_of(
    snapshot: WorldSnapshot, decision: Decision, at: datetime
) -> tuple[MemberCommand, ...]:
    """Return the own commands a "send" decision gives, one per member with a target.

    An empty tuple for every other outcome.
    """
    if (
        decision.gate is None
        or decision.gate.kind is not GateKind.SEND
        or decision.winning_wish is None
    ):
        return ()
    wish = decision.winning_wish
    return tuple(
        MemberCommand(
            target.member_id,
            OwnCommand(
                command_id=uuid4().hex,
                target=target.position,
                direction=_direction(snapshot, target.member_id, target.position),
                time=at,
                wish_class=wish.wish_class,
                reason=wish.reason,
            ),
        )
        for target in decision.targets
        if target.position is not None
    )


def state_with_commands(
    state: WindowState, commands: tuple[MemberCommand, ...]
) -> WindowState:
    """Return the state with the commands as the last own commands of their members.

    A new command replaces the old one as a whole, with no attempts yet. A
    comfort command moves the clock of motor protection
    (``last_comfort_movement``).
    """
    if not commands:
        return state
    by_member = {command.member_id: command.command for command in commands}
    members = list(state.members)
    known = {member.member_id for member in members}
    for index, member in enumerate(members):
        if member.member_id in by_member:
            members[index] = replace(
                member,
                last_own_command=by_member[member.member_id],
                command_attempts=0,
                last_attempt_at=None,
            )
    members.extend(
        MemberState(member_id, last_own_command=command)
        for member_id, command in by_member.items()
        if member_id not in known
    )
    comfort = [
        c.command.time for c in commands if c.command.wish_class is WishClass.COMFORT
    ]
    return replace(
        state,
        members=tuple(members),
        last_comfort_movement=max(comfort) if comfort else state.last_comfort_movement,
    )
