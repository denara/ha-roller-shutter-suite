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
    CommandResult,
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


def record_command_result(state: WindowState, result: CommandResult) -> WindowState:
    """Return the state after the actuator reported the result of a command.

    The result is written into the member's last own command, and only if
    that command has the identifier of the result: a late result of an older
    command is never attributed to a newer one, and a result for a member
    without a record changes nothing. It adds the context ID under which the
    command was executed and, for ``command_failed``, marks the command as
    failed, so that "target reached" does not count a target the actuator
    never received.

    For an accepted command whose result names the instant of the call
    (``called_at``), the time of the command and the time of its attempt
    move to that instant: a staggered command is called after the hand-over,
    and its expectation window (``member_expectation_end``, which reads the
    time of the command) must start when the cover was really commanded.
    The motor protection clock stays at the hand-over, so motor protection
    judges exactly as before. A failed command keeps its times, and
    retrying is not decided here.
    """
    changed = False
    members: list[MemberState] = []
    for member in state.members:
        command = member.last_own_command
        if (
            member.member_id != result.member_id
            or command is None
            or command.command_id != result.command_id
        ):
            members.append(member)
            continue
        updated = replace(command, context_id=result.context_id, failed=result.failed)
        attempt_at = member.last_attempt_at
        if not result.failed and result.called_at is not None:
            updated = replace(updated, time=result.called_at)
            if member.command_attempts > 0:
                attempt_at = result.called_at
        if updated == command and attempt_at == member.last_attempt_at:
            members.append(member)
            continue
        changed = True
        members.append(
            replace(member, last_own_command=updated, last_attempt_at=attempt_at)
        )
    return replace(state, members=tuple(members)) if changed else state
