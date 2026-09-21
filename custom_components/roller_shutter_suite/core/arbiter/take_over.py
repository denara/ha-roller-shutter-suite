"""Taking over a movement in flight.

A wish of a higher class can meet an own command that is still pending and
already has the wish's target: a storm begins while the evening closing is
under way. Nothing is sent again, but the movement is not merely kept quiet
either. It is taken over: from now on it is a movement of the higher class, so
that the dams, motor protection and the return after a protection event see a
protection or fire movement and not a comfort one. The gate says so with the
reason ``movement_taken_over``; this module applies it to the state.

What changes is the wish class and the reason of the pending commands, which
become those of the wish, and the owner of the position, which is the
integration. The reason on the command is authoritative for what the movement
is; the decision documents the moment. The motor protection clock stays as it
is: the movement was sent as a comfort movement, and nothing is sent now. For
a window in dry-run the same happens to the simulated commands and to nothing
else.
"""

from dataclasses import replace

from custom_components.roller_shutter_suite.core.model import (
    Decision,
    MemberCommand,
    OwnCommand,
    PositionOwner,
    WindowState,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .dry_run import simulated_state
from .registry import outranks


def _raised(command: OwnCommand, wish: Wish) -> OwnCommand:
    """Return the command as the wish's own, if the wish is of a higher class."""
    if not outranks(wish.wish_class, command.wish_class):
        return command
    return replace(command, wish_class=wish.wish_class, reason=wish.reason)


def apply_take_over(snapshot: WorldSnapshot, decision: Decision) -> WindowState:
    """Return the state after a decision whose gate outcome is a take-over.

    Every other decision leaves the state as it is.
    """
    state = snapshot.state
    gate = decision.gate
    if (
        gate is None
        or gate.reason is not ReasonCode.MOVEMENT_TAKEN_OVER
        or decision.winning_wish is None
    ):
        return state
    wish = decision.winning_wish
    taken = {
        target.member_id for target in decision.targets if target.position is not None
    }
    if gate.dry_run:
        simulated = simulated_state(state)
        commands = tuple(
            MemberCommand(entry.member_id, _raised(entry.command, wish))
            if entry.member_id in taken
            else entry
            for entry in simulated.commands
        )
        return replace(state, simulated=replace(simulated, commands=commands))
    members = tuple(
        replace(member, last_own_command=_raised(member.last_own_command, wish))
        if member.member_id in taken and member.last_own_command is not None
        else member
        for member in state.members
    )
    return replace(state, members=members, owner=PositionOwner.ENGINE)
