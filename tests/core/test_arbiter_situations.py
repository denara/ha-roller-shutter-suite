"""The reference situations of section 4 of the design specification, as a table.

Covered here are the situations that need no real feature layer: the stub
layers of ``arbiter_kit`` stand in for fire, protection, sleep, shading and the
schedule. Situations 4, 5, 6 and 11 need the constraints of later blocks
(lockout protection, the sleep-room exception, the ventilation floor); 10a,
14 and 15 need the blocks that end dams, hold inputs and track members.

Dams are part of the persisted state a test hands in: the rules that arm and
end them belong to later blocks.
"""

from dataclasses import dataclass, field
from datetime import timedelta

import pytest

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    ControlLevel,
    Controls,
    FrostSettings,
    ManualOverrideDam,
    OperatingMode,
    OverrideEndRule,
    PersonAtWindowDam,
    Position,
    SourceValue,
    WindowConfig,
    WindowObservation,
    WindowState,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    ARMED,
    DRY_RUN,
    LEFT,
    NOW,
    RIGHT,
    day,
    engine,
    fire,
    night,
    observed,
    snapshot,
    storm,
    window,
)

NEW = WindowState()
ONE_MEMBER = window()
FROSTY = window(frost=FrostSettings(source="outdoor_temperature"))
COLD = SourceValue.of(-4.0)
OVERRIDE = ManualOverrideDam(
    armed_at=NOW - timedelta(hours=2),
    end_rule=OverrideEndRule.NEXT_PART_OF_DAY,
    ends_at=NOW + timedelta(hours=6),
    remembered_position=Position(40),
)
PERSON = PersonAtWindowDam(ends_at=NOW + timedelta(minutes=15))


@dataclass(frozen=True)
class Situation:
    """One row: what the world looks like, and what the decision has to say."""

    number: str
    sources: dict[str, AnySourceValue]
    winner: ReasonCode
    gate: ReasonCode | None
    target: int | None
    constraints: list[ReasonCode] = field(default_factory=list)
    would_send: int | None = None
    position: int = 50
    observation: WindowObservation | None = None
    state: WindowState = NEW
    controls: Controls = ARMED
    config: WindowConfig = ONE_MEMBER


SITUATIONS = [
    Situation(
        "1 fire during maintenance lock",
        fire(),
        winner=ReasonCode.FIRE_ALARM,
        gate=ReasonCode.MAINTENANCE_LOCK,
        target=100,
        controls=Controls(
            dry_run=False, global_level=ControlLevel(maintenance_lock=True)
        ),
    ),
    Situation(
        "2 fire in dry-run",
        fire(),
        winner=ReasonCode.FIRE_ALARM,
        gate=ReasonCode.DRY_RUN,
        target=100,
        would_send=100,
        controls=DRY_RUN,
    ),
    Situation(
        "2a storm in dry-run while the window is paused",
        storm(),
        winner=ReasonCode.PROTECTION_EVENT,
        gate=ReasonCode.DRY_RUN,
        target=0,
        would_send=0,
        controls=Controls(dry_run=True, window_level=ControlLevel(paused=True)),
    ),
    Situation(
        "2a a comfort wish at the same moment",
        night(),
        winner=ReasonCode.SCHEDULE_NIGHT,
        gate=ReasonCode.PAUSED,
        target=0,
        controls=Controls(dry_run=True, window_level=ControlLevel(paused=True)),
    ),
    Situation(
        "3 fire in mode off",
        fire(),
        winner=ReasonCode.FIRE_ALARM,
        gate=ReasonCode.SENT,
        target=100,
        controls=Controls(
            dry_run=False, window_level=ControlLevel(mode=OperatingMode.OFF)
        ),
    ),
    Situation(
        "3a the alarm has ended, nobody acknowledged it, a person closed the shutter",
        day(),
        winner=ReasonCode.FIRE_UNACKNOWLEDGED,
        gate=None,
        target=None,
        position=0,
        state=WindowState(fire_unacknowledged=True),
    ),
    Situation(
        "7 wall button during a storm: the movement stands for 15 minutes",
        storm(),
        winner=ReasonCode.PROTECTION_EVENT,
        gate=ReasonCode.PERSON_AT_WINDOW,
        target=0,
        position=60,
        state=WindowState(person_at_window=PERSON),
    ),
    Situation(
        "7 then the dam has ended and the storm position is restored",
        storm(),
        winner=ReasonCode.PROTECTION_EVENT,
        gate=ReasonCode.SENT,
        target=0,
        position=60,
        state=WindowState(person_at_window=PersonAtWindowDam(ends_at=NOW)),
    ),
    Situation(
        "8 manual override active when a storm begins",
        storm(),
        winner=ReasonCode.PROTECTION_EVENT,
        gate=ReasonCode.SENT,
        target=0,
        position=40,
        state=WindowState(manual_override=OVERRIDE),
    ),
    Situation(
        "9 the storm ends, the override dam is still armed",
        day(return_to=SourceValue.of(40)),
        winner=ReasonCode.PROTECTION_RETURN_MANUAL,
        gate=ReasonCode.SENT,
        target=40,
        position=0,
        state=WindowState(manual_override=OVERRIDE),
    ),
    Situation(
        "10 the storm ends, the override dam has expired meanwhile",
        day(),
        winner=ReasonCode.SCHEDULE_DAY,
        gate=ReasonCode.SENT,
        target=100,
        position=0,
        state=WindowState(
            manual_override=ManualOverrideDam(
                armed_at=NOW - timedelta(hours=8),
                end_rule=OverrideEndRule.FIXED_MINUTES,
                ends_at=NOW - timedelta(hours=6),
            )
        ),
    ),
    Situation(
        "10b during sleep mode somebody opens the shutter by hand",
        night(sleep=SourceValue.of(True)),
        winner=ReasonCode.SLEEP_MODE,
        gate=ReasonCode.MANUAL_OVERRIDE,
        target=0,
        position=80,
        state=WindowState(manual_override=OVERRIDE),
    ),
    Situation(
        "12 frost during evening closing",
        night(outdoor_temperature=COLD),
        winner=ReasonCode.SCHEDULE_NIGHT,
        gate=ReasonCode.SENT,
        target=0,
        position=100,
        config=FROSTY,
    ),
    Situation(
        "12a frost at the morning opening",
        day(outdoor_temperature=COLD),
        winner=ReasonCode.SCHEDULE_DAY,
        constraints=[ReasonCode.FROST_LIMIT],
        gate=ReasonCode.SENT,
        target=90,
        position=0,
        config=FROSTY,
    ),
    Situation(
        "12a when frost has ended, the recompute opens the rest",
        day(outdoor_temperature=SourceValue.of(5.0)),
        winner=ReasonCode.SCHEDULE_DAY,
        gate=ReasonCode.SENT,
        target=100,
        position=90,
        config=FROSTY,
    ),
    Situation(
        "12b frost, and the operator waives frost protection for the window",
        day(outdoor_temperature=COLD),
        winner=ReasonCode.SCHEDULE_DAY,
        gate=ReasonCode.SENT,
        target=100,
        position=0,
        state=WindowState(frost_waiver_until=NOW + timedelta(hours=20)),
        config=FROSTY,
    ),
    Situation(
        "13 after a restart the shading position is the one the window already has",
        day(shading_position=SourceValue.of(35)),
        winner=ReasonCode.SHADING_GEOMETRIC,
        gate=ReasonCode.TARGET_REACHED,
        target=35,
        position=36,
    ),
    Situation(
        "16 one member is unavailable when a protection event starts",
        storm(),
        winner=ReasonCode.PROTECTION_EVENT,
        gate=ReasonCode.SENT,
        target=0,
        observation=observed(left=100, right="unavailable"),
        config=window(LEFT, RIGHT),
    ),
]


@pytest.mark.parametrize(
    "situation", SITUATIONS, ids=[situation.number for situation in SITUATIONS]
)
def test_reference_situation(situation: Situation) -> None:
    """Winner, constraints and gate carry the reason codes of the specification."""
    world = snapshot(
        sources=situation.sources,
        position=situation.position,
        observation=situation.observation,
        state=situation.state,
        controls=situation.controls,
    )

    decision = engine(situation.config).recompute(world)

    assert decision.winning_wish is not None
    assert decision.winning_wish.reason is situation.winner
    assert [result.reason for result in decision.constraints] == situation.constraints
    assert decision.target == (
        None if situation.target is None else Position(situation.target)
    )
    if situation.gate is None:
        assert decision.gate is None
        return
    assert decision.gate is not None
    assert decision.gate.reason is situation.gate
    assert decision.gate.dry_run is situation.controls.dry_run
    would_send = {target.position for target in decision.gate.would_send}
    assert would_send == (
        set() if situation.would_send is None else {Position(situation.would_send)}
    )


def test_the_table_covers_the_situations_that_need_no_real_feature_layer() -> None:
    """A row that disappears from the table is noticed."""
    numbers = {situation.number.split(" ")[0] for situation in SITUATIONS}

    assert numbers == {
        "1",
        "2",
        "2a",
        "3",
        "3a",
        "7",
        "8",
        "9",
        "10",
        "10b",
        "12",
        "12a",
        "12b",
        "13",
        "16",
    }
