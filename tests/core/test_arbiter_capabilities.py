"""The arbiter asks about capabilities in one place only."""

import ast
from datetime import timedelta
from pathlib import Path

from custom_components.roller_shutter_suite.core.arbiter.capabilities import (
    cannot_execute,
    has_no_position_feedback,
)
from custom_components.roller_shutter_suite.core.model import (
    CapabilityState,
    GateOutcome,
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
    NOW,
    RIGHT,
    engine,
    observed,
    profile,
    snapshot,
    storm,
    window,
)

CORE = Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite" / "core"
FLAGS = {
    "supports_open_close",
    "supports_set_position",
    "supports_stop",
    "reports_position",
}


def test_a_member_cannot_execute_only_if_both_ways_are_missing() -> None:
    """Set position, or open and close mapped by the adapter, is enough."""
    assert cannot_execute(profile()) is False
    assert cannot_execute(profile(supports_set_position=False)) is False
    assert cannot_execute(profile(supports_open_close=False)) is False
    assert (
        cannot_execute(profile(supports_set_position=False, supports_open_close=False))
        is True
    )


def test_position_feedback() -> None:
    """A member that reports a position is compared with its reports."""
    assert has_no_position_feedback(profile()) is False
    assert has_no_position_feedback(profile(reports_position=False)) is True


NEVER_SEEN = profile(
    supports_open_close=False,
    supports_set_position=False,
    supports_stop=False,
    reports_position=False,
    capabilities_known=False,
)
"""A member about which nothing is known: every flag is off, none is missing."""


def test_an_unknown_capability_is_never_taken_for_a_missing_one() -> None:
    """Every flag of a never-seen member reads False; that says nothing."""
    assert cannot_execute(NEVER_SEEN) is False
    assert has_no_position_feedback(NEVER_SEEN) is False


def test_a_never_seen_member_is_commanded_and_nothing_is_reported_as_missing() -> None:
    """Alone, and next to a member that definitely cannot be commanded."""
    unable = profile(supports_open_close=False, supports_set_position=False)
    alone = engine(window(profiles={LEFT: NEVER_SEEN}))
    mixed = engine(window(LEFT, RIGHT, profiles={LEFT: NEVER_SEEN, RIGHT: unable}))

    lonely = alone.recompute(snapshot(sources=storm(), position=None))
    both = mixed.recompute(
        snapshot(sources=storm(), observation=observed(left=None, right=50))
    )
    # The boolean view would call the whole window incapable.
    assert alone.config.capabilities.supports_set_position is False
    assert alone.config.capability_states.supports_set_position is (
        CapabilityState.UNKNOWN
    )
    assert lonely.gate == GateOutcome.send()
    assert both.gate == GateOutcome.send()


def test_a_never_seen_member_is_not_one_without_position_feedback() -> None:
    """Its last own command does not make its target "reached"."""
    state = WindowState(
        members=(
            MemberState(
                LEFT,
                last_own_command=OwnCommand(
                    "command-1",
                    Position(0),
                    TravelDirection.DOWN,
                    NOW - timedelta(hours=1),
                    WishClass.PROTECTION,
                    ReasonCode.PROTECTION_EVENT,
                ),
            ),
        )
    )
    never_seen = engine(window(profiles={LEFT: NEVER_SEEN}))
    no_feedback = engine(window(profiles={LEFT: profile(reports_position=False)}))
    world = snapshot(sources=storm(), position=None, state=state)

    assert never_seen.recompute(world).gate == GateOutcome.send()
    gate = no_feedback.recompute(world).gate
    assert gate is not None
    assert gate.reason is ReasonCode.TARGET_REACHED


def test_no_other_module_of_the_block_reads_a_capability_flag() -> None:
    """So a change of how capabilities are stored is a change in one place."""
    files = [
        *sorted((CORE / "arbiter").glob("*.py")),
        *sorted((CORE / "constraints").glob("*.py")),
        CORE / "engine.py",
    ]

    for path in files:
        if path.name == "capabilities.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        read = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        assert not read & FLAGS, path.name
        # The boolean view of a window cannot tell "missing" from "unknown".
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "capabilities":
                owner = node.value
                name = owner.attr if isinstance(owner, ast.Attribute) else ""
                name = owner.id if isinstance(owner, ast.Name) else name
                assert name != "config", path.name
