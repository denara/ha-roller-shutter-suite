"""The arbiter asks about capabilities in one place only."""

import ast
from pathlib import Path

from custom_components.roller_shutter_suite.core.arbiter.capabilities import (
    cannot_execute,
    has_no_position_feedback,
)
from tests.core.arbiter_kit import profile

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
