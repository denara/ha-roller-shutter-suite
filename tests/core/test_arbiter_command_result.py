"""The result of a command, and which members a send commands.

``Engine.on_command_result`` writes what the actuator reported back into the
last own command: the context ID, and whether the call failed
(``command_failed``). A failed command is not counted by "target reached". The
duplicate part of "movement in flight" judges only the members a send would
command: the available ones that do not stand at their target within
tolerance.
"""

from dataclasses import replace
from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.arbiter import member_expectation_end
from custom_components.roller_shutter_suite.core.engine import Engine
from custom_components.roller_shutter_suite.core.model import (
    CommandResult,
    GateKind,
    MemberState,
    OwnCommand,
    Position,
    TravelDirection,
    WindowState,
    WishClass,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    LEFT,
    LONG_AGO,
    NOW,
    RIGHT,
    day,
    engine,
    fire,
    observed,
    profile,
    snapshot,
    window,
)


def _command(
    command_id: str = "command-1",
    target: int = 100,
    *,
    at: Any = LONG_AGO,
    wish_class: WishClass = WishClass.COMFORT,
    **changes: Any,
) -> OwnCommand:
    reason = (
        ReasonCode.FIRE_ALARM
        if wish_class is WishClass.FIRE
        else ReasonCode.SCHEDULE_DAY
    )
    return OwnCommand(
        command_id,
        Position(target),
        TravelDirection.UP,
        at,
        wish_class,
        reason,
        **changes,
    )


def _state(*members: tuple[str, OwnCommand]) -> WindowState:
    return WindowState(
        members=tuple(
            MemberState(
                member_id,
                last_own_command=command,
                command_attempts=1,
                last_attempt_at=command.time,
            )
            for member_id, command in members
        )
    )


# --- The result reaches the record --------------------------------------------------


def test_a_result_adds_the_context_to_the_command_it_answers() -> None:
    """Everything else of the record stays as it was."""
    before = _state((LEFT, _command()))

    after = Engine.on_command_result(
        before, CommandResult("command-1", LEFT, "context-1", failed=False)
    )

    (member,) = after.members
    assert member.last_own_command == _command(context_id="context-1")
    assert member.command_attempts == 1
    assert member.last_attempt_at == LONG_AGO


def test_a_failed_result_marks_the_command() -> None:
    """``command_failed``: the context of the attempt is kept as well."""
    after = Engine.on_command_result(
        _state((LEFT, _command())),
        CommandResult("command-1", LEFT, "context-1", failed=True),
    )

    assert after.members[0].last_own_command == _command(
        context_id="context-1", failed=True
    )


@pytest.mark.parametrize(
    "result",
    [
        CommandResult("command-old", LEFT, "context-1", failed=True),
        CommandResult("command-1", RIGHT, "context-1", failed=True),
    ],
    ids=["late result of an older command", "member without a record"],
)
def test_a_result_that_answers_no_current_command_changes_nothing(
    result: CommandResult,
) -> None:
    """A late result is never attributed to a newer command."""
    before = _state((LEFT, _command()))

    assert Engine.on_command_result(before, result) is before


def test_the_same_result_twice_changes_nothing_the_second_time() -> None:
    """Nothing to write, so the state is returned as it is."""
    result = CommandResult("command-1", LEFT, "context-1", failed=False)
    once = Engine.on_command_result(_state((LEFT, _command())), result)

    assert Engine.on_command_result(once, result) is once


def test_the_mark_survives_plain_data() -> None:
    """``failed`` is persisted with the command; a faulty value is refused."""
    command = _command(context_id="context-1", failed=True)
    data = command.to_data()

    assert data["failed"] is True
    assert OwnCommand.from_data(data) == command
    with pytest.raises(ValueError, match="failed"):
        OwnCommand.from_data(data | {"failed": "yes"})


def test_version_one_data_written_before_the_mark_loads_as_not_failed() -> None:
    """Within schema version 1 the key is optional; C12 brings the schema step."""
    state = _state((LEFT, _command(context_id="context-1")))
    data = state.to_data()
    members = data["members"]
    assert isinstance(members, list)
    member = members[0]
    assert isinstance(member, dict)
    command = member["last_own_command"]
    assert isinstance(command, dict)
    del command["failed"]

    loaded = WindowState.from_data(data)

    assert data["schema_version"] == 1
    assert loaded == state
    assert loaded.members[0].last_own_command is not None
    assert not loaded.members[0].last_own_command.failed


# --- The time of the call starts the expectation window -----------------------------


def test_an_accepted_result_moves_the_command_to_the_time_of_the_call() -> None:
    """A staggered call: command time and attempt move, the comfort clock stays."""
    handed_over = NOW - timedelta(seconds=30)
    called = NOW - timedelta(seconds=20)
    before = replace(
        _state((LEFT, _command(at=handed_over))), last_comfort_movement=handed_over
    )

    after = Engine.on_command_result(
        before, CommandResult("command-1", LEFT, "context-1", False, called_at=called)
    )

    (member,) = after.members
    assert member.last_own_command is not None
    assert member.last_own_command.time == called
    assert member.last_attempt_at == called
    assert member.command_attempts == 1
    assert after.last_comfort_movement == handed_over
    end = member_expectation_end(window().members[0], member.last_own_command)
    assert end == called + profile().travel_time_up


def test_a_failed_result_keeps_the_times_of_the_command() -> None:
    """Only an accepted command was really given at the time of the call."""
    handed_over = NOW - timedelta(seconds=30)
    before = _state((LEFT, _command(at=handed_over)))

    after = Engine.on_command_result(
        before,
        CommandResult("command-1", LEFT, "context-1", True, called_at=NOW),
    )

    assert after.members[0].last_own_command is not None
    assert after.members[0].last_own_command.time == handed_over
    assert after.members[0].last_attempt_at == handed_over


def test_a_command_without_an_attempt_gets_no_attempt_time() -> None:
    """The two facts of the backoff belong together; a result adds no attempt."""
    before = WindowState(members=(MemberState(LEFT, last_own_command=_command()),))

    after = Engine.on_command_result(
        before, CommandResult("command-1", LEFT, None, False, called_at=NOW)
    )

    assert after.members[0].last_attempt_at is None
    assert after.members[0].last_own_command is not None
    assert after.members[0].last_own_command.time == NOW


def test_the_time_of_the_call_is_kept_in_utc_and_must_be_aware() -> None:
    """A naive time is refused at the boundary."""
    result = CommandResult("c", LEFT, None, False, called_at=NOW)

    assert result.called_at == NOW
    assert result.called_at is not None
    assert result.called_at.utcoffset() == timedelta(0)
    with pytest.raises(ValueError, match="time"):
        CommandResult("c", LEFT, None, False, called_at=NOW.replace(tzinfo=None))


@pytest.mark.parametrize(
    "arguments",
    [
        {"command_id": "", "member_id": LEFT, "context_id": None, "failed": False},
        {"command_id": "c", "member_id": "", "context_id": None, "failed": False},
        {"command_id": "c", "member_id": LEFT, "context_id": 7, "failed": False},
        {"command_id": "c", "member_id": LEFT, "context_id": None, "failed": 1},
    ],
)
def test_a_command_result_refuses_what_is_not_a_result(
    arguments: dict[str, Any],
) -> None:
    """Identifiers are text; the flag is a boolean."""
    with pytest.raises((TypeError, ValueError)):
        CommandResult(**arguments)


def test_the_failed_flag_of_a_command_is_a_boolean() -> None:
    """Not 1, not "yes"."""
    with pytest.raises(TypeError):
        _command(failed=1)


# --- Target reached does not count a failed command ---------------------------------


def _blind() -> Any:
    return window(profiles={LEFT: profile(reports_position=False)})


@pytest.mark.parametrize(
    ("failed", "reason"),
    [(False, ReasonCode.TARGET_REACHED), (True, ReasonCode.SENT)],
)
def test_a_member_without_feedback_is_reached_only_if_its_command_did_not_fail(
    failed: bool, reason: ReasonCode
) -> None:
    """Gate rule 3: an actuator that never got the command did not move the cover."""
    state = _state((LEFT, _command(failed=failed)))
    world = snapshot(sources=day(), position=None, state=state)

    decision = engine(_blind()).recompute(world)

    assert decision.gate is not None
    assert decision.gate.reason is reason


# --- Movement in flight judges the members a send would command ---------------------


def test_a_member_at_its_target_does_not_make_a_pending_fire_command_a_new_one() -> (
    None
):
    """The left member stands at 100; the right one's fire command is under way."""
    config = window(LEFT, RIGHT)
    state = _state(
        (
            RIGHT,
            _command(
                "command-r", at=NOW - timedelta(seconds=1), wish_class=WishClass.FIRE
            ),
        )
    )
    world = snapshot(
        sources=fire(), observation=observed(left=100, right=0), state=state
    )

    decision = engine(config).recompute(world)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.DUPLICATE_COMMAND


def test_an_unavailable_member_does_not_make_a_pending_fire_command_a_new_one() -> None:
    """The right member is away and is not commanded; the left one is under way."""
    config = window(LEFT, RIGHT)
    state = _state(
        (
            LEFT,
            _command(
                "command-l", at=NOW - timedelta(seconds=1), wish_class=WishClass.FIRE
            ),
        )
    )
    world = snapshot(
        sources=fire(),
        observation=observed(left=0, right="unavailable"),
        state=state,
    )

    decision = engine(config).recompute(world)

    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.DUPLICATE_COMMAND


def test_a_member_that_needs_a_command_and_has_none_pending_is_sent() -> None:
    """Both members are away from 100; only the left one has a pending command."""
    config = window(LEFT, RIGHT)
    state = _state(
        (
            LEFT,
            _command(
                "command-l", at=NOW - timedelta(seconds=1), wish_class=WishClass.FIRE
            ),
        )
    )
    world = snapshot(sources=fire(), observation=observed(left=0, right=0), state=state)

    decision = engine(config).recompute(world)

    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_a_member_without_feedback_never_stands_at_its_target() -> None:
    """It cannot be judged, so a pending command of the other member is not enough."""
    config = window(LEFT, RIGHT, profiles={RIGHT: profile(reports_position=False)})
    state = _state(
        (
            LEFT,
            _command(
                "command-l", at=NOW - timedelta(seconds=1), wish_class=WishClass.FIRE
            ),
        )
    )
    world = snapshot(
        sources=fire(), observation=observed(left=0, right=None), state=state
    )

    decision = engine(config).recompute(world)

    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND
