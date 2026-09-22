"""Constraint 6: the basic frost protection.

Frost protection is preventive. While frost is active and not waived, own
movements open only up to the frost position, so the curtain does not run into
a frozen end stop. Closing is never limited. It applies to comfort movements;
to protection movements only if configured; never to fire (no constraint
applies to fire) and never to a movement by hand (the arbiter only decides own
movements).

Inputs of the constraint:

- the frost source of the window configuration, with threshold and
  hysteresis, and the held frost state of the persisted state
  (``WindowState.held_frost``) for the hysteresis band and for a source
  without a value. A source that stays silent longer than the held state
  lasts is blind: the limit applies then too, with a reason of its own
  (``frost_limit_source_blind``), so the record tells "blind" apart from
  "frost measured". A source that delivers something that is no temperature
  (text that is not a number, a switch position) is silent in the same way;
  it never raises and never counts as "no frost". Raising the repair issue
  and the event ``frost_source_blind`` is the Home Assistant layer's job;
- the waiver: ``WindowState.frost_waiver_until``. Who sets it (a person, for a
  window, a group or the installation, until the next morning trigger) is not
  the constraint's business. The release by sun is not built here.
"""

import math
from datetime import timedelta
from enum import StrEnum, unique
from typing import Final

from custom_components.roller_shutter_suite.core.arbiter.registry import (
    ConstraintInput,
    ConstraintRegistration,
)
from custom_components.roller_shutter_suite.core.model import (
    BLIND_SOURCE,
    FULLY_CLOSED,
    AnySourceValue,
    BlindSource,
    Constraint,
    ConstraintResult,
    FunctionId,
    HeldInput,
    MemberTarget,
    WindowConfig,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

FROST_HOLD_LIMIT: Final = timedelta(hours=24)
"""How long the last known frost state is held while the source has no value."""


def _temperature(value: AnySourceValue | None) -> float | None:
    """Return the temperature a source delivers; ``None`` if it delivers none.

    A source that is unknown or unavailable has no value, and neither has one
    that delivers something that is no temperature: a switch position, or
    text that is not a finite number. Such a source is silent, and the rules
    for a silent source apply: what was last known is held, and after that
    the source is blind. It never counts as "no frost". Text that spells a
    finite number is that number.
    """
    if value is None or not value.has_value:
        return None
    delivered = value.value
    if isinstance(delivered, bool):
        return None
    try:
        temperature = float(delivered)
    except ValueError, OverflowError:
        # Text that is no number, or a whole number too large to be one.
        return None
    return temperature if math.isfinite(temperature) else None


def _reading(config: WindowConfig, snapshot: WorldSnapshot) -> bool | None:
    """Return what the frost source says now; ``None`` if it has no value.

    Inside the hysteresis band the source says what was last known; without
    anything known, a temperature that is not below the threshold is no frost.
    A window without a source, or with a source nobody knows (the marker
    ``BLIND_SOURCE``), has nothing to read.
    """
    settings = config.frost
    if settings.source is None or isinstance(settings.source, BlindSource):
        return None
    temperature = _temperature(snapshot.sources.get(settings.source))
    if temperature is None:
        return None
    if temperature < settings.threshold:
        return True
    if temperature >= settings.threshold + settings.hysteresis:
        return False
    held = snapshot.state.held_frost
    return held.value if held is not None else False


@unique
class FrostState(StrEnum):
    """What is known about frost at a window."""

    NO_FROST = "no_frost"
    """No frost, measured or held; or frost protection is not configured."""
    FROST = "frost"
    """Frost, measured or held."""
    BLIND = "blind"
    """Nothing is known: the source is silent and no held state is left."""


def frost_state(config: WindowConfig, snapshot: WorldSnapshot) -> FrostState:
    """Return what is known about frost at the window.

    A source without a value is never silently "no frost". The last known
    state is held for at most ``FROST_HOLD_LIMIT``. After that, or if there
    never was a known state, the source is blind, and the constraint applies
    its limit as a cautious value until data returns or the operator waives
    frost protection.

    A source that is configured, but blind because its stored setting is
    faulty (``BLIND_SOURCE``), is blind at once. A held state is not used: it
    belongs to a source, and nobody knows which source this window has.
    """
    if config.frost.source is None:
        return FrostState.NO_FROST
    if config.frost.source is BLIND_SOURCE:
        return FrostState.BLIND
    reading = _reading(config, snapshot)
    if reading is None:
        held = snapshot.state.held_frost
        if held is None or snapshot.time - held.seen_at > FROST_HOLD_LIMIT:
            return FrostState.BLIND
        reading = held.value
    return FrostState.FROST if reading else FrostState.NO_FROST


def held_frost_after(config: WindowConfig, snapshot: WorldSnapshot) -> HeldInput | None:
    """Return the frost state to persist after this snapshot.

    While the source has a value, that is its reading with the time of the
    snapshot; otherwise what was held stays as it is, also for a window
    without a source and for one whose source is ``BLIND_SOURCE``. The
    constraint only reads ``held_frost``; whoever persists the window state
    writes it.
    """
    reading = _reading(config, snapshot)
    if reading is None:
        return snapshot.state.held_frost
    return HeldInput(value=reading, seen_at=snapshot.time)


def frost_is_waived(snapshot: WorldSnapshot) -> bool:
    """Return whether the operator has lifted frost protection for the window."""
    until = snapshot.state.frost_waiver_until
    return until is not None and snapshot.time < until


def _apply(constraint: ConstraintInput) -> ConstraintResult | None:
    return _limit(constraint, frost_state(constraint.config, constraint.snapshot))


def _apply_cautiously(constraint: ConstraintInput) -> ConstraintResult | None:
    """Return the most restrictive result: what applies if ``_apply`` raised.

    Frost protection limits as if nothing were known about frost, without
    asking the source or the held state. Its settings and the waiver of the
    operator still count: they are decisions of a person, not what failed.
    A window without a frost source has no frost protection to keep.
    """
    if constraint.config.frost.source is None:
        return None
    return _limit(constraint, FrostState.BLIND)


def _limit(constraint: ConstraintInput, frost: FrostState) -> ConstraintResult | None:
    config, snapshot = constraint.config, constraint.snapshot
    settings = config.frost
    if (
        constraint.wish.wish_class is WishClass.PROTECTION
        and not settings.applies_to_protection
    ):
        return None
    if frost is FrostState.NO_FROST or frost_is_waived(snapshot):
        return None
    reported = constraint.current_positions
    tolerances = {m.member_id: m.capabilities.tolerance for m in config.members}
    held = False
    targets: list[MemberTarget] = []
    for target in constraint.targets:
        position = reported.get(target.member_id)
        limited = target
        if target.position is None or (
            position is not None and target.position <= position
        ):
            pass  # pinned already, or not an opening: closing is never limited
        elif (
            settings.hold_closed
            and position is not None
            and position.value - FULLY_CLOSED.value <= tolerances[target.member_id]
        ):
            held = True
            limited = MemberTarget(target.member_id, None)
        elif position is not None and position >= settings.position:
            limited = MemberTarget(target.member_id, None)
        elif target.position > settings.position:
            limited = MemberTarget(target.member_id, settings.position)
        targets.append(limited)
    if tuple(targets) == constraint.targets:
        return None
    if frost is FrostState.BLIND:
        reason = ReasonCode.FROST_LIMIT_SOURCE_BLIND
    else:
        reason = ReasonCode.FROST_HOLD if held else ReasonCode.FROST_LIMIT
    return ConstraintResult(Constraint.FROST_PROTECTION, reason, tuple(targets))


FROST_CONSTRAINT: Final = ConstraintRegistration(
    constraint=Constraint.FROST_PROTECTION,
    applies_to=frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
    apply=_apply,
    function=FunctionId.FROST,
    cautious=_apply_cautiously,
)
"""Comfort always; protection only if the window is configured that way."""
