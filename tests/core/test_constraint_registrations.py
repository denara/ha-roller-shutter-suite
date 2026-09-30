"""Every constraint of section 2.2 of the specification is registered in the code.

The specification and the documentation of the blocks said since block C03
that the sleep-room exception (constraint 2) and "no intermediate position
during a protection event" (constraint 7) existed, while only their members
of the enumeration and their reason codes did; ``constraints/`` held
direction and frost. Block C07 built the two, and this test keeps it from
happening again (ruling of the project owner of 2026-10-01): it reads the
table of section 2.2, checks it against the enumeration ``Constraint``, and
fails for a constraint of the table that the arbiter of the integration
(``build_arbiter()``) has no registration for.

Feature blocks arrive one by one. A constraint whose block is still to come
stands in ``NOT_BUILT_YET``, with the block. That list can only shrink: the
test fails for an entry that is registered by now.
"""

import re
from pathlib import Path
from typing import Final

from custom_components.roller_shutter_suite.core.engine import (
    BUILT_IN_CONSTRAINTS,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import Constraint

ARCHITECTURE = Path(__file__).parents[2] / "docs" / "architecture.md"

NAMES: Final = {
    Constraint.DIRECTION: "Direction of the wish",
    Constraint.SLEEP_ROOM_EXCEPTION: "Sleep-room exception",
    Constraint.LOCKOUT_PROTECTION: "Lockout protection",
    Constraint.VENTILATION_FLOOR: "Ventilation floor",
    Constraint.RAIN_WHILE_VENTILATING: "Rain while ventilating",
    Constraint.FROST_PROTECTION: "Frost protection",
    Constraint.NO_INTERMEDIATE_POSITION: (
        "No intermediate position during a protection event"
    ),
}
"""The name of each constraint in the table of section 2.2, feature IDs left out."""

NOT_BUILT_YET: Final = {
    Constraint.LOCKOUT_PROTECTION: "C08",
    Constraint.VENTILATION_FLOOR: "C08",
    Constraint.RAIN_WHILE_VENTILATING: "C08",
}
"""Constraints of the specification whose block is still to come, with the block."""


def documented_constraints() -> list[tuple[int, str]]:
    """Return (number, name) of every row of the table of section 2.2."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = text.split("### 2.2 Constraints", 1)[1].split("\n### ", 1)[0]
    rows: list[tuple[int, str]] = []
    for line in section.splitlines():
        match = re.match(r"\| (?P<number>\d+) \| (?P<name>[^|]+?) \|", line)
        if match is None:
            continue
        name = re.sub(r"\s*\([^)]*\)$", "", match["name"].strip())
        rows.append((int(match["number"]), name))
    return rows


def check_registrations(
    registered: set[Constraint], not_built_yet: dict[Constraint, str]
) -> list[str]:
    """Return what is wrong: a constraint of the table without a registration, a needless entry."""
    findings: list[str] = []
    for number, name in documented_constraints():
        constraint = next(c for c, known in NAMES.items() if known == name)
        if constraint in registered and constraint in not_built_yet:
            findings.append(
                f"constraint {number} ({name}) is registered now: remove it from "
                "NOT_BUILT_YET in tests/core/test_constraint_registrations.py"
            )
        if constraint not in registered and constraint not in not_built_yet:
            findings.append(
                f"constraint {number} ({name}) stands in section 2.2 of the "
                "specification, but the arbiter of the integration has no "
                "registration for it. Build it and add it to BUILT_IN_CONSTRAINTS "
                "in core/engine.py, or name its block in NOT_BUILT_YET"
            )
    return findings


def test_the_table_of_section_two_two_is_the_enumeration_in_its_order() -> None:
    """Number, name and order of every row match the members of ``Constraint``."""
    rows = documented_constraints()

    assert [number for number, _ in rows] == list(range(1, len(Constraint) + 1))
    assert [name for _, name in rows] == [NAMES[member] for member in Constraint]


def test_every_constraint_of_the_specification_is_registered() -> None:
    """For the arbiter the integration builds; the list of what is to come shrinks."""
    registered = {entry.constraint for entry in build_arbiter().constraints}

    assert not check_registrations(registered, NOT_BUILT_YET), "\n".join(
        check_registrations(registered, NOT_BUILT_YET)
    )
    assert {entry.constraint for entry in BUILT_IN_CONSTRAINTS} == registered


def test_a_constraint_of_the_table_without_a_registration_is_named_with_advice() -> (
    None
):
    """The case of block C03, shown: constraints 2 and 7 without a registration."""
    registered = {Constraint.DIRECTION, Constraint.FROST_PROTECTION}

    findings = check_registrations(registered, NOT_BUILT_YET)

    assert len(findings) == 2  # noqa: PLR2004 - constraints 2 and 7
    assert "constraint 2 (Sleep-room exception) stands in section 2.2" in findings[0]
    assert "constraint 7 (No intermediate position" in findings[1]


def test_an_entry_that_is_registered_by_now_fails() -> None:
    """The list of what is still to come can only shrink."""
    registered = {entry.constraint for entry in build_arbiter().constraints}

    findings = check_registrations(
        registered | {Constraint.LOCKOUT_PROTECTION}, NOT_BUILT_YET
    )

    assert findings == [
        "constraint 3 (Lockout protection) is registered now: remove it from "
        "NOT_BUILT_YET in tests/core/test_constraint_registrations.py"
    ]
