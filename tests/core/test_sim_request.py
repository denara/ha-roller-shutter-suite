"""The scenarios of the external request layer, kept apart from protection.

A request below an active sleep mode is accepted and moves nothing (the
stand-in for sleep mode of block C11); a request expires; a request is
cleared; a request in dry-run shows what would have been sent.
"""

from datetime import datetime, time
from typing import Final

from custom_components.roller_shutter_suite.core.model import Decision, Layer
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.sim.assertions import assert_no_command_loop, assert_no_commands
from tests.sim.record import Record
from tests.sim.scenarios import ALARM_CLOCK, MONDAY, REQUESTED, local, run_named

WINDOW: Final = "window_example"


def at(hour: int, minute: int = 0) -> datetime:
    """Return a local time of the Monday of the scenarios."""
    return local(MONDAY, time(hour, minute))


def first_decision(record: Record, moment: datetime) -> Decision:
    """Return the first decision of the window at or after a moment."""
    return next(
        entry.decision
        for entry in record.decisions(WINDOW)
        if entry.decision is not None and entry.at >= moment
    )


def sends(record: Record) -> list[tuple[str, int, str]]:
    """Return (local time, target, reason) of every command before the evening."""
    return [
        (
            entry.at.astimezone(record.zone).strftime("%H:%M"),
            entry.target.value,
            entry.summary.rsplit(", ", 1)[1].rstrip(")"),
        )
        for entry in record.commands(WINDOW)
        if entry.target is not None and entry.at < at(18)
    ]


def test_a_request_below_an_active_sleep_mode_is_accepted_and_moves_nothing() -> None:
    """Decision 2: the sleep layer wins; the request waits and acts after it."""
    record = run_named("request-below-sleep").record

    accepted = first_decision(record, at(6, 30))
    assert accepted.winning_wish is not None
    assert accepted.winning_wish.reason is ReasonCode.SLEEP_MODE
    (waiting,) = (e for e in accepted.other_layers if e.layer is Layer.EXTERNAL_REQUEST)
    assert waiting.reason is ReasonCode.EXTERNAL_REQUEST
    assert sends(record) == [
        ("06:50", ALARM_CLOCK, "external_request"),
        ("08:00", 100, "schedule_day"),
    ]


def test_a_request_expires_and_the_window_is_recomputed() -> None:
    """From 10:00 to 11:00 the requested 40, then the schedule's day position."""
    record = run_named("request-expires").record

    assert sends(record) == [
        ("10:00", REQUESTED, "external_request"),
        ("11:00", 100, "schedule_day"),
    ]
    assert_no_command_loop(record)


def test_a_request_that_is_cleared_ends_at_once() -> None:
    """Cleared at 10:30: the schedule acts again."""
    record = run_named("request-cleared").record

    assert sends(record) == [
        ("10:00", REQUESTED, "external_request"),
        ("10:30", 100, "schedule_day"),
    ]


def test_a_request_in_dry_run_would_have_been_sent_and_moves_nothing() -> None:
    """The record shows ``dry_run`` with the would-be command."""
    record = run_named("request-dry-run").record

    decision = first_decision(record, at(10))
    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is ReasonCode.EXTERNAL_REQUEST
    assert decision.gate is not None
    assert decision.gate.reason is ReasonCode.DRY_RUN
    assert decision.gate.would_send[0].position is not None
    assert decision.gate.would_send[0].position.value == REQUESTED
    assert_no_commands(record, WINDOW)
