"""Constraints: the registry, the direction of a wish, and frost protection."""

from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.arbiter import (
    Arbiter,
    ConstraintInput,
    ConstraintRegistration,
)
from custom_components.roller_shutter_suite.core.constraints import (
    DIRECTION_CONSTRAINT,
    FROST_CONSTRAINT,
    FROST_HOLD_LIMIT,
    FrostState,
    frost_state,
    held_frost_after,
)
from custom_components.roller_shutter_suite.core.engine import (
    BUILT_IN_CONSTRAINTS,
    Engine,
    build_arbiter,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    Constraint,
    ConstraintResult,
    Decision,
    Direction,
    FrostSettings,
    GateKind,
    HeldInput,
    Layer,
    MemberTarget,
    Position,
    SourceValue,
    WindowConfig,
    WindowState,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from tests.core.arbiter_kit import (
    LEFT,
    NOW,
    RIGHT,
    STUB_LAYERS,
    day,
    engine,
    fire,
    night,
    observed,
    profile,
    registered,
    snapshot,
    storm,
    window,
)

FROST = FrostSettings(source="outdoor_temperature")
COLD = SourceValue.of(-3.0)
MILD = SourceValue.of(6.0)


def _reasons(decision: Decision) -> list[ReasonCode]:
    return [result.reason for result in decision.constraints]


def _frosty(config: WindowConfig | None = None, **frost: Any) -> Engine:
    settings = FrostSettings(source="outdoor_temperature", **frost)
    if config is None:
        return engine(window(frost=settings))
    return engine(config)


# --- Registry ---------------------------------------------------------------------


def test_constraints_are_applied_in_the_specified_order() -> None:
    """Direction is the first constraint, frost the sixth, however registered."""
    arbiter = build_arbiter(STUB_LAYERS)
    reversed_order = build_arbiter(()).constraints[::-1]

    assert [entry.constraint for entry in arbiter.constraints] == [
        Constraint.DIRECTION,
        Constraint.FROST_PROTECTION,
    ]
    assert BUILT_IN_CONSTRAINTS == (DIRECTION_CONSTRAINT, FROST_CONSTRAINT)
    assert (
        Arbiter(constraints=reversed_order, gate_rules=arbiter.gate_rules).constraints
        == arbiter.constraints
    )


def test_every_constraint_names_the_classes_it_applies_to() -> None:
    """None of them can name fire: fire is subject to no constraint at all."""
    for registration in BUILT_IN_CONSTRAINTS:
        assert registration.applies_to
        assert WishClass.FIRE not in registration.applies_to
    with pytest.raises(ValueError, match="fire is subject to no constraint"):
        ConstraintRegistration(
            Constraint.LOCKOUT_PROTECTION, frozenset(WishClass), lambda _input: None
        )
    with pytest.raises(ValueError, match="names the wish classes"):
        ConstraintRegistration(
            Constraint.LOCKOUT_PROTECTION, frozenset(), lambda _input: None
        )
    bad: Any = "lockout"
    with pytest.raises(TypeError, match="member of 'Constraint'"):
        ConstraintRegistration(bad, frozenset({WishClass.COMFORT}), lambda _input: None)


def _floor(position: int, classes: frozenset[WishClass]) -> ConstraintRegistration:
    """Return a stand-in for the ventilation floor: not lower than ``position``."""

    def apply(constraint: ConstraintInput) -> ConstraintResult | None:
        targets = tuple(
            MemberTarget(
                target.member_id,
                None
                if target.position is None
                else max(target.position, Position(position)),
            )
            for target in constraint.targets
        )
        if targets == constraint.targets:
            return None
        return ConstraintResult(
            Constraint.VENTILATION_FLOOR, ReasonCode.VENTILATION_FLOOR, targets
        )

    return ConstraintRegistration(Constraint.VENTILATION_FLOOR, classes, apply)


def test_adding_a_constraint_is_a_registration() -> None:
    """It limits the winning wish, is recorded, and the gate sees the new target."""
    comfort_only = frozenset({WishClass.COMFORT})
    arbiter = build_arbiter(STUB_LAYERS, constraints=[_floor(30, comfort_only)])

    decision = arbiter.recompute(window(), snapshot(sources=night(), position=100))

    assert decision.winning_wish is not None
    assert decision.winning_wish.position == FULLY_CLOSED
    assert _reasons(decision) == [ReasonCode.VENTILATION_FLOOR]
    assert decision.target == Position(30)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_a_constraint_is_skipped_for_the_classes_it_does_not_name() -> None:
    """The comfort floor does not limit a storm, and nothing limits fire."""
    every_other_class = frozenset({WishClass.COMFORT, WishClass.PROTECTION})
    comfort_only = build_arbiter(
        STUB_LAYERS, constraints=[_floor(30, frozenset({WishClass.COMFORT}))]
    )
    both = build_arbiter(STUB_LAYERS, constraints=[_floor(30, every_other_class)])

    assert comfort_only.recompute(
        window(), snapshot(sources=storm())
    ).target == Position(0)
    assert both.recompute(window(), snapshot(sources=storm())).target == Position(30)
    burning = both.recompute(window(), snapshot(sources=fire()))
    assert burning.constraints == ()
    assert burning.target == FULLY_OPEN


_RAISE_TO_60 = registered(
    Layer.SCHEDULE,
    lambda _config, _world: Wish.target(
        Layer.SCHEDULE,
        ReasonCode.SCHEDULE_DAY,
        Position(60),
        direction=Direction.RAISE_ONLY,
    ),
)


def test_a_target_pinned_for_every_member_never_reaches_the_gate() -> None:
    """Nothing moves, and the reason is the constraint's."""
    pinned = build_arbiter([_RAISE_TO_60]).recompute(window(), snapshot(position=80))

    assert _reasons(pinned) == [ReasonCode.ONLY_RAISE]
    assert pinned.targets == (MemberTarget(LEFT, None),)
    assert pinned.target is None
    assert pinned.gate is None


def test_a_constraint_that_breaks_the_interface_is_refused() -> None:
    """It answers in its own name, names the same members, and invents no target."""

    def registered(result: ConstraintResult) -> ConstraintRegistration:
        return ConstraintRegistration(
            Constraint.VENTILATION_FLOOR,
            frozenset({WishClass.COMFORT}),
            lambda _input: result,
        )

    def recompute(result: ConstraintResult, position: int = 30) -> None:
        arbiter = build_arbiter([_RAISE_TO_60], constraints=[registered(result)])
        arbiter.recompute(window(), snapshot(position=position))

    with pytest.raises(ValueError, match="answered as 'rain_while_ventilating'"):
        recompute(
            ConstraintResult(
                Constraint.RAIN_WHILE_VENTILATING,
                ReasonCode.RAIN_VENTILATION_FLOOR,
                (MemberTarget(LEFT, Position(10)),),
            )
        )
    floor = ReasonCode.VENTILATION_FLOOR
    with pytest.raises(ValueError, match="target of every member"):
        recompute(
            ConstraintResult(
                Constraint.VENTILATION_FLOOR,
                floor,
                (MemberTarget(LEFT, Position(10)), MemberTarget(RIGHT, Position(10))),
            )
        )
    with pytest.raises(ValueError, match="members in their order"):
        recompute(
            ConstraintResult(
                Constraint.VENTILATION_FLOOR,
                floor,
                (MemberTarget(RIGHT, Position(10)),),
            )
        )
    with pytest.raises(ValueError, match="never gives a pinned member a target"):
        # The wish only raises, so the direction pinned the member that stands at 80.
        recompute(
            ConstraintResult(
                Constraint.VENTILATION_FLOOR, floor, (MemberTarget(LEFT, Position(10)),)
            ),
            position=80,
        )


# --- Direction --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sources", "position", "expected", "reasons"),
    [
        pytest.param(day(), 30, 100, [], id="morning-raises"),
        pytest.param(night(), 70, 0, [], id="evening-lowers"),
        pytest.param(day(), 100, 100, [], id="already-there-is-not-forbidden"),
    ],
)
def test_a_movement_in_the_allowed_direction_passes(
    sources: dict[str, Any], position: int, expected: int, reasons: list[ReasonCode]
) -> None:
    """The direction constraint has nothing to report."""
    decision = engine().recompute(snapshot(sources=sources, position=position))

    assert decision.target == Position(expected)
    assert _reasons(decision) == reasons


def test_lower_only_never_raises_a_shutter() -> None:
    """A privacy position of 20 does not raise a shutter that stands at 5."""
    privacy = registered(
        Layer.PRIVACY,
        lambda _config, _world: Wish.target(
            Layer.PRIVACY,
            ReasonCode.PRIVACY_LIGHTS_ON,
            Position(20),
            direction=Direction.LOWER_ONLY,
        ),
    )
    arbiter = build_arbiter([privacy])

    lower = arbiter.recompute(window(), snapshot(position=5))
    higher = arbiter.recompute(window(), snapshot(position=60))

    assert _reasons(lower) == [ReasonCode.ONLY_LOWER]
    assert lower.targets == (MemberTarget(LEFT, None),)
    assert lower.gate is None
    assert higher.target == Position(20)
    assert higher.constraints == ()


def test_direction_is_judged_per_member() -> None:
    """One member is pinned, the other moves; a member without a position passes."""
    config = window(LEFT, RIGHT)
    privacy = registered(
        Layer.PRIVACY,
        lambda _config, _world: Wish.target(
            Layer.PRIVACY,
            ReasonCode.PRIVACY_LIGHTS_ON,
            Position(20),
            direction=Direction.LOWER_ONLY,
        ),
    )
    arbiter = build_arbiter([privacy])

    mixed = arbiter.recompute(config, snapshot(observation=observed(left=5, right=60)))
    blind = arbiter.recompute(
        config, snapshot(observation=observed(left=None, right=60))
    )

    assert mixed.targets == (
        MemberTarget(LEFT, None),
        MemberTarget(RIGHT, Position(20)),
    )
    assert _reasons(mixed) == [ReasonCode.ONLY_LOWER]
    assert mixed.gate is not None
    assert mixed.gate.kind is GateKind.SEND
    assert blind.constraints == ()
    assert blind.target == Position(20)


# --- Frost: when it is active -----------------------------------------------------


def _world(
    temperature: SourceValue[float] | None, state: WindowState | None = None
) -> WorldSnapshot:
    sources = day() if temperature is None else day(outdoor_temperature=temperature)
    return snapshot(sources=sources, position=0, state=state)


def test_frost_is_active_below_the_threshold_and_ends_above_the_hysteresis() -> None:
    """Inside the band the last known state decides; nothing known is no frost."""
    config = window(frost=FrostSettings(source="outdoor_temperature", hysteresis=2.0))
    frost_held = WindowState(held_frost=HeldInput(value=True, seen_at=NOW))
    thaw_held = WindowState(held_frost=HeldInput(value=False, seen_at=NOW))
    in_band = SourceValue.of(1.0)

    assert frost_state(config, _world(SourceValue.of(-0.1))) is FrostState.FROST
    assert frost_state(config, _world(SourceValue.of(0))) is FrostState.NO_FROST
    assert frost_state(config, _world(SourceValue.of(2.0), frost_held)) is (
        FrostState.NO_FROST
    )
    assert frost_state(config, _world(in_band, frost_held)) is FrostState.FROST
    assert frost_state(config, _world(in_band, thaw_held)) is FrostState.NO_FROST
    assert frost_state(config, _world(in_band)) is FrostState.NO_FROST


def test_frost_without_a_configured_source_is_never_active() -> None:
    """The default configuration has no frost protection, and nothing is blind."""
    held = WindowState(held_frost=HeldInput(value=True, seen_at=NOW))

    assert frost_state(window(), _world(COLD, held)) is FrostState.NO_FROST
    assert frost_state(window(), _world(None)) is FrostState.NO_FROST
    assert held_frost_after(window(), _world(COLD, held)) == held.held_frost


MISSING = [SourceValue[float].unavailable(), SourceValue[float].unknown(), None]


@pytest.mark.parametrize("missing", MISSING)
def test_a_silent_frost_source_holds_the_last_state_for_a_day_and_is_blind_afterwards(
    missing: SourceValue[float] | None,
) -> None:
    """Never silently "no frost": held for 24 hours, then blind."""
    config = window(frost=FROST)

    def state(value: bool, hours: float) -> WorldSnapshot:
        seen_at = NOW - timedelta(hours=hours)
        return _world(missing, WindowState(held_frost=HeldInput(value, seen_at)))

    assert timedelta(hours=24) == FROST_HOLD_LIMIT
    assert frost_state(config, state(True, 24)) is FrostState.FROST
    assert frost_state(config, state(False, 23)) is FrostState.NO_FROST
    assert frost_state(config, state(False, 25)) is FrostState.BLIND
    assert frost_state(config, state(True, 25)) is FrostState.BLIND
    assert frost_state(config, _world(missing)) is FrostState.BLIND
    fresh = state(True, 1)
    assert held_frost_after(config, fresh) == fresh.state.held_frost


def _morning(
    temperature: SourceValue[float] | None, state: WindowState | None = None
) -> Decision:
    sources = day() if temperature is None else day(outdoor_temperature=temperature)
    return _frosty().recompute(snapshot(sources=sources, position=0, state=state))


@pytest.mark.parametrize("missing", MISSING)
def test_a_frost_source_that_is_silent_from_the_start_limits_the_opening(
    missing: SourceValue[float] | None,
) -> None:
    """The limit applies as a cautious value, and the reason says "blind"."""
    decision = _morning(missing)

    assert _reasons(decision) == [ReasonCode.FROST_LIMIT_SOURCE_BLIND]
    assert decision.constraints[0].constraint is Constraint.FROST_PROTECTION
    assert decision.target == Position(90)


def test_silent_for_23_hours_with_the_last_state_no_frost_sets_no_limit() -> None:
    """The held state still counts."""
    held = WindowState(held_frost=HeldInput(False, NOW - timedelta(hours=23)))

    decision = _morning(SourceValue[float].unavailable(), held)

    assert decision.constraints == ()
    assert decision.target == FULLY_OPEN


def test_silent_for_25_hours_with_the_last_state_no_frost_limits_as_blind() -> None:
    """What was known a day ago says nothing about now."""
    held = WindowState(held_frost=HeldInput(False, NOW - timedelta(hours=25)))

    decision = _morning(SourceValue[float].unavailable(), held)

    assert _reasons(decision) == [ReasonCode.FROST_LIMIT_SOURCE_BLIND]
    assert decision.target == Position(90)


def test_held_frost_is_frost_measured_not_blind() -> None:
    """Silent for an hour after a frost reading: the ordinary reason."""
    held = WindowState(held_frost=HeldInput(True, NOW - timedelta(hours=1)))

    decision = _morning(SourceValue[float].unknown(), held)

    assert _reasons(decision) == [ReasonCode.FROST_LIMIT]


def test_a_waiver_lifts_the_limit_of_a_blind_source() -> None:
    """The operator knows better than a dead sensor."""
    waived = WindowState(frost_waiver_until=NOW + timedelta(hours=3))

    decision = _morning(None, waived)

    assert decision.constraints == ()
    assert decision.target == FULLY_OPEN


def test_data_that_returns_lifts_the_limit_of_a_blind_source() -> None:
    """A mild reading ends it at once; a cold one turns it into measured frost."""
    stale = WindowState(held_frost=HeldInput(False, NOW - timedelta(days=3)))

    assert _reasons(_morning(None, stale)) == [ReasonCode.FROST_LIMIT_SOURCE_BLIND]
    assert _morning(MILD, stale).constraints == ()
    assert _reasons(_morning(COLD, stale)) == [ReasonCode.FROST_LIMIT]


def test_a_blind_source_never_limits_closing_and_never_fire() -> None:
    """Blind is the cautious reading of the same constraint, nothing more."""
    closing = _frosty().recompute(snapshot(sources=night(), position=100))
    burning = _frosty().recompute(snapshot(sources=fire(), position=0))

    assert closing.constraints == ()
    assert closing.target == FULLY_CLOSED
    assert burning.constraints == ()
    assert burning.target == FULLY_OPEN


def test_blind_takes_precedence_over_hold_in_the_reason() -> None:
    """The closed member is still held; the record says why the limit applies at all."""
    config = window(frost=FrostSettings(source="outdoor_temperature", hold_closed=True))

    decision = engine(config).recompute(snapshot(sources=day(), position=0))

    assert _reasons(decision) == [ReasonCode.FROST_LIMIT_SOURCE_BLIND]
    assert decision.targets == (MemberTarget(LEFT, None),)


def test_the_frost_state_to_persist_follows_the_source() -> None:
    """While the source has a value, its reading is what is held from now on."""
    config = window(frost=FROST)
    held = WindowState(held_frost=HeldInput(True, NOW - timedelta(hours=3)))

    assert held_frost_after(config, _world(COLD)) == HeldInput(True, NOW)
    assert held_frost_after(config, _world(MILD, held)) == HeldInput(False, NOW)
    assert held_frost_after(config, _world(SourceValue.of(0.5), held)) == HeldInput(
        True, NOW
    )


@pytest.mark.parametrize("value", [SourceValue.of("cold"), SourceValue.of(True)])
def test_a_frost_source_that_is_no_temperature_is_refused(value: Any) -> None:
    """A switch or a text is a configuration error, not a temperature."""
    with pytest.raises(TypeError, match="temperature as a number"):
        frost_state(window(frost=FROST), _world(value))


# --- Frost: what it limits --------------------------------------------------------


def test_frost_limits_the_opening_of_a_comfort_movement() -> None:
    """The morning opening stops at the frost position."""
    decision = _frosty().recompute(
        snapshot(sources=day(outdoor_temperature=COLD), position=0)
    )

    assert _reasons(decision) == [ReasonCode.FROST_LIMIT]
    assert decision.constraints[0].constraint is Constraint.FROST_PROTECTION
    assert decision.target == Position(90)
    assert decision.gate is not None
    assert decision.gate.kind is GateKind.SEND


def test_frost_never_limits_closing() -> None:
    """The evening closing closes fully."""
    decision = _frosty().recompute(
        snapshot(sources=night(outdoor_temperature=COLD), position=100)
    )

    assert decision.constraints == ()
    assert decision.target == FULLY_CLOSED


def test_without_frost_the_window_opens_fully() -> None:
    """When frost ends, the recompute opens the rest."""
    decision = _frosty().recompute(
        snapshot(sources=day(outdoor_temperature=MILD), position=90)
    )

    assert decision.constraints == ()
    assert decision.target == FULLY_OPEN


def test_a_window_above_the_frost_position_is_not_opened_further_and_not_closed() -> (
    None
):
    """The limit never turns an opening into a closing."""
    above = _frosty().recompute(
        snapshot(sources=day(outdoor_temperature=COLD), position=95)
    )
    at = _frosty().recompute(
        snapshot(sources=day(outdoor_temperature=COLD), position=90)
    )

    assert above.targets == (MemberTarget(LEFT, None),)
    assert _reasons(above) == [ReasonCode.FROST_LIMIT]
    assert above.gate is None
    assert at.targets == (MemberTarget(LEFT, None),)


def test_an_opening_that_stays_below_the_frost_position_is_not_limited() -> None:
    """Shading from 20 to 60 during frost is an ordinary movement."""
    decision = _frosty().recompute(
        snapshot(
            sources=day(outdoor_temperature=COLD, shading_position=SourceValue.of(60)),
            position=20,
        )
    )

    assert decision.constraints == ()
    assert decision.target == Position(60)


def test_a_member_without_a_known_position_is_limited_to_the_frost_position() -> None:
    """Whether it opens cannot be told, so its target is limited."""
    config = window(LEFT, RIGHT, frost=FROST)
    decision = engine(config).recompute(
        snapshot(
            sources=day(outdoor_temperature=COLD),
            observation=observed(left=None, right=40),
        )
    )

    assert decision.targets == (
        MemberTarget(LEFT, Position(90)),
        MemberTarget(RIGHT, Position(90)),
    )


def test_the_frost_position_is_a_setting() -> None:
    """Default 90."""
    decision = _frosty(position=Position(80)).recompute(
        snapshot(sources=day(outdoor_temperature=COLD), position=0)
    )

    assert decision.target == Position(80)


def test_by_default_frost_does_not_limit_a_protection_movement() -> None:
    """Configured for protection, it does; fire ignores it either way."""
    hail = registered(
        Layer.PROTECTION,
        lambda _config, _world: Wish.target(
            Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_OPEN
        ),
    )
    arbiter = build_arbiter([*STUB_LAYERS[:3], *STUB_LAYERS[4:], hail])
    cold_day = snapshot(sources=day(outdoor_temperature=COLD), position=0)
    configured = window(
        frost=FrostSettings(source="outdoor_temperature", applies_to_protection=True)
    )

    default = arbiter.recompute(window(frost=FROST), cold_day)
    limited = arbiter.recompute(configured, cold_day)
    burning = arbiter.recompute(
        configured, snapshot(sources=fire(outdoor_temperature=COLD), position=0)
    )

    assert default.constraints == ()
    assert default.target == FULLY_OPEN
    assert _reasons(limited) == [ReasonCode.FROST_LIMIT]
    assert limited.target == Position(90)
    assert burning.constraints == ()
    assert burning.target == FULLY_OPEN


def test_a_waiver_lifts_frost_protection_until_it_ends() -> None:
    """The waiver is an input of the constraint; it ends by its time."""
    cold = day(outdoor_temperature=COLD)
    waived = WindowState(frost_waiver_until=NOW + timedelta(hours=2))
    over = WindowState(frost_waiver_until=NOW)

    lifted = _frosty().recompute(snapshot(sources=cold, position=0, state=waived))
    again = _frosty().recompute(snapshot(sources=cold, position=0, state=over))

    assert lifted.constraints == ()
    assert lifted.target == FULLY_OPEN
    assert _reasons(again) == [ReasonCode.FROST_LIMIT]


def test_do_not_raise_a_closed_window_is_off_by_default() -> None:
    """Switched on, a closed member stays closed; an open one is still only limited."""
    cold = day(outdoor_temperature=COLD)
    config = window(
        LEFT,
        RIGHT,
        frost=FrostSettings(source="outdoor_temperature", hold_closed=True),
        profiles={LEFT: profile(stated_tolerance=3)},
    )

    default = _frosty().recompute(snapshot(sources=cold, position=0))
    held = engine(config).recompute(
        snapshot(sources=cold, observation=observed(left=3, right=40))
    )
    open_already = engine(config).recompute(
        snapshot(sources=cold, observation=observed(left=4, right=40))
    )

    assert _reasons(default) == [ReasonCode.FROST_LIMIT]
    assert _reasons(held) == [ReasonCode.FROST_HOLD]
    assert held.targets == (MemberTarget(LEFT, None), MemberTarget(RIGHT, Position(90)))
    assert _reasons(open_already) == [ReasonCode.FROST_LIMIT]
    assert open_already.target == Position(90)


def test_direction_and_frost_are_both_recorded_in_order() -> None:
    """Two members: one pinned by the direction, the other limited by frost."""
    config = window(LEFT, RIGHT, frost=FROST)
    wish = Wish.target_per_member(
        Layer.SHADING,
        ReasonCode.SHADING_FIXED,
        (MemberTarget(LEFT, Position(40)), MemberTarget(RIGHT, Position(95))),
        direction=Direction.RAISE_ONLY,
    )
    arbiter = build_arbiter([registered(Layer.SHADING, lambda _config, _world: wish)])

    decision = arbiter.recompute(
        config,
        snapshot(
            sources={"outdoor_temperature": COLD},
            observation=observed(left=70, right=50),
        ),
    )

    assert _reasons(decision) == [ReasonCode.ONLY_RAISE, ReasonCode.FROST_LIMIT]
    assert decision.constraints[0].targets == (
        MemberTarget(LEFT, None),
        MemberTarget(RIGHT, Position(95)),
    )
    assert decision.targets == (
        MemberTarget(LEFT, None),
        MemberTarget(RIGHT, Position(90)),
    )
