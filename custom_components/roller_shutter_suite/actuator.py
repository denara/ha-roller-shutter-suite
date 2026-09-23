"""The actuator port until the block that sends commands exists.

The runtime calls the actuator port with what the gate lets through. Turning
that into service calls, verifying the command and handling its result is
the job of a later block. Until then :class:`RecordingActuator` records
every command it is given and calls nothing, so the runtime can be built and
tested end to end, and a window that is armed by mistake still moves
nothing. The recorded commands are visible in the status of the window.
"""

from dataclasses import dataclass, field

from .core.model import Position


@dataclass(frozen=True, slots=True)
class RecordedCommand:
    """One command as the runtime handed it to the actuator port."""

    command_id: str
    member_id: str
    target: Position


@dataclass(slots=True)
class RecordingActuator:
    """An actuator that keeps the commands and sends nothing."""

    commands: list[RecordedCommand] = field(default_factory=list)

    def move_to(self, command_id: str, member_id: str, target: Position) -> None:
        """Record the command."""
        self.commands.append(RecordedCommand(command_id, member_id, target))
