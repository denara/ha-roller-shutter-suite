"""What a real send leaves behind in the persisted state.

When the gate says ``send``, the caller hands every target to the actuator
under a command identifier, and then it has to write the command down: the
own-command rules of the gate ("movement in flight", motor protection) read
the last own command of every member and the motor protection clock from the
persisted state, and without the record the next recompute would send the
same command again while the cover is still travelling.

This module is that record, as one pure function from a state to a state. It
knows nothing about tracking: the tracker of a later block evaluates the
movement and consumes the expectation; here the command is only remembered.
Per commanded member the last own command is replaced as a whole (a new own
command resets the expectation), with one attempt at the time of the send;
the owner of the position becomes the integration; and for a comfort wish
the motor protection clock is set to the time of the send. A window in
dry-run never sends, so its state is never touched by this.
"""

from collections.abc import Mapping
from dataclasses import replace

from custom_components.roller_shutter_suite.core.model import (
    Decision,
    GateKind,
    MemberState,
    OwnCommand,
    PositionOwner,
    WindowState,
    WishClass,
    WorldSnapshot,
)

from .dry_run import direction_of
from .registry import reported_positions


def record_sent_commands(
    snapshot: WorldSnapshot, decision: Decision, command_ids: Mapping[str, str]
) -> WindowState:
    """Return the state after the targets of a decision were really sent.

    ``command_ids`` maps every member that was commanded to the identifier
    the actuator received; a member that has a target in the decision and no
    identifier here was not commanded and is left alone. A decision whose
    gate outcome is not ``send`` leaves the state as it is.
    """
    state = snapshot.state
    gate = decision.gate
    wish = decision.winning_wish
    if gate is None or gate.kind is not GateKind.SEND or wish is None:
        return state
    reported = reported_positions(snapshot)
    members = {member.member_id: member for member in state.members}
    for target in decision.targets:
        if target.position is None or target.member_id not in command_ids:
            continue
        command = OwnCommand(
            command_id=command_ids[target.member_id],
            target=target.position,
            direction=direction_of(target.position, reported.get(target.member_id)),
            time=snapshot.time,
            wish_class=wish.wish_class,
            reason=wish.reason,
        )
        existing = members.get(target.member_id, MemberState(target.member_id))
        members[target.member_id] = replace(
            existing,
            last_own_command=command,
            command_attempts=1,
            last_attempt_at=snapshot.time,
        )
    clock = (
        snapshot.time
        if wish.wish_class is WishClass.COMFORT
        else state.last_comfort_movement
    )
    return replace(
        state,
        members=tuple(members.values()),
        owner=PositionOwner.ENGINE,
        last_comfort_movement=clock,
    )
