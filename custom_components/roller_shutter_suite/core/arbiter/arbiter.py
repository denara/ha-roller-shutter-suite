"""The arbiter: layers, then constraints, then the gate.

One arbiter decides for one window. It has no state of its own and reads no
clock: the same window configuration and the same world snapshot always yield
the same decision. It knows no feature. Layers, constraints and gate rules are
registered; their order is the order of the model's enumerations, which is the
order of the design specification.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from custom_components.roller_shutter_suite.core.model import (
    ConstraintResult,
    Decision,
    GateKind,
    GateOutcome,
    GateRule,
    Layer,
    LayerReason,
    MemberTarget,
    WindowConfig,
    Wish,
    WishClass,
    WishKind,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

from .controls import effective_controls
from .dry_run import is_standing, simulated_state
from .fire_bypass import skips
from .layers import disabled_functions
from .registry import (
    ConstraintInput,
    ConstraintRegistration,
    GateInput,
    GateRuleRegistration,
    LayerRegistration,
)

_REQUIRED_GATE_RULES = (GateRule.MAINTENANCE_LOCK, GateRule.DRY_RUN)


def _in_order[R](
    registrations: Iterable[R],
    place: Callable[[R], StrEnum],
    what: str,
    claims: Callable[[R], frozenset[StrEnum]] | None = None,
) -> tuple[R, ...]:
    """Sort registrations by their place in the enumeration; refuse duplicates.

    ``claims`` says which parts of its place a registration takes; without it,
    a registration takes its place as a whole. Two registrations may share a
    place only if their claims do not overlap. They are then sorted by their
    first claim, so the result never depends on the order of registration.
    """
    items = tuple(registrations)
    taken: set[tuple[StrEnum, StrEnum]] = set()
    keys: dict[int, tuple[int, int]] = {}
    for item in items:
        where = place(item)
        parts = frozenset({where}) if claims is None else claims(item)
        if any((where, part) in taken for part in parts):
            raise ValueError(f"the {what} {where.value!r} is registered twice")
        taken |= {(where, part) for part in parts}
        keys[id(item)] = (
            list(type(where)).index(where),
            min(list(type(part)).index(part) for part in parts),
        )
    return tuple(sorted(items, key=lambda item: keys[id(item)]))


@dataclass(frozen=True, slots=True)
class Arbiter:
    """The registries and the evaluation. Immutable; it keeps nothing."""

    layers: tuple[LayerRegistration, ...] = ()
    constraints: tuple[ConstraintRegistration, ...] = ()
    gate_rules: tuple[GateRuleRegistration, ...] = ()

    def __post_init__(self) -> None:
        """Put every registry in the specified order and refuse duplicates."""
        object.__setattr__(
            self, "layers", _in_order(self.layers, lambda r: r.layer, "layer")
        )
        object.__setattr__(
            self,
            "constraints",
            _in_order(self.constraints, lambda r: r.constraint, "constraint"),
        )
        object.__setattr__(
            self,
            "gate_rules",
            _in_order(
                self.gate_rules,
                lambda r: r.rule,
                "gate rule",
                claims=lambda r: frozenset(r.reasons),
            ),
        )
        registered = {registration.rule for registration in self.gate_rules}
        for rule in _REQUIRED_GATE_RULES:
            if rule not in registered:
                raise ValueError(
                    f"an arbiter without the gate rule {rule.value!r} is refused: "
                    "nothing may move under a maintenance lock or in dry-run"
                )

    # --- Layers -------------------------------------------------------------

    def _wishes(self, config: WindowConfig, snapshot: WorldSnapshot) -> list[Wish]:
        """Ask every layer, in order. A layer that is not registered steps aside."""
        registered = {registration.layer: registration for registration in self.layers}
        wishes: list[Wish] = []
        for layer in Layer:
            registration = registered.get(layer)
            if registration is None:
                wishes.append(Wish.no_opinion(layer, ReasonCode.NOT_CONFIGURED))
                continue
            if (
                registration.can_be_paused
                and registration.function in disabled_functions(config)
            ):
                # Comfort becomes cautious: a faulty stored setting never moves a
                # window. The layer is not asked, and the record says why.
                wishes.append(
                    Wish.no_opinion(layer, ReasonCode.FUNCTION_DISABLED_BY_FAULT)
                )
                continue
            wish = registration.evaluate(config, snapshot)
            if wish.layer is not layer:
                raise ValueError(
                    f"the layer {layer.value!r} answered with a wish of the layer "
                    f"{wish.layer.value!r}"
                )
            wishes.append(wish)
        return wishes

    # --- Constraints --------------------------------------------------------

    def _constrain(
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        wish: Wish,
        targets: tuple[MemberTarget, ...],
    ) -> tuple[tuple[ConstraintResult, ...], tuple[MemberTarget, ...]]:
        """Apply the constraints in order. Fire is subject to none."""
        results: list[ConstraintResult] = []
        if wish.wish_class is WishClass.FIRE:
            return (), targets
        for registration in self.constraints:
            if wish.wish_class not in registration.applies_to:
                continue
            result = registration.apply(
                ConstraintInput(config, snapshot, wish, targets)
            )
            if result is None:
                continue
            if result.constraint is not registration.constraint:
                raise ValueError(
                    f"the constraint {registration.constraint.value!r} answered as "
                    f"{result.constraint.value!r}"
                )
            _require_same_members(targets, result.targets)
            results.append(result)
            targets = result.targets
        return tuple(results), targets

    def _violated_by_position(
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        wish: Wish,
        targets: tuple[MemberTarget, ...],
    ) -> bool:
        """Say whether the window stands where a constraint on the wish forbids it."""
        if wish.wish_class is WishClass.FIRE:
            return False
        constraint_input = ConstraintInput(config, snapshot, wish, targets)
        return any(
            registration.violated_by_position is not None
            and wish.wish_class in registration.applies_to
            and registration.violated_by_position(constraint_input)
            for registration in self.constraints
        )

    # --- Gate ---------------------------------------------------------------

    def _gate(
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        wish: Wish,
        to_send: tuple[MemberTarget, ...],
        *,
        restores: bool = False,
    ) -> GateOutcome:
        """Evaluate the gate rules in order; the first rule that applies decides."""
        controls = effective_controls(snapshot.controls)
        state = snapshot.state
        own_commands = {
            member.member_id: member.last_own_command
            for member in state.members
            if member.last_own_command is not None
        }
        clock = state.last_comfort_movement
        if controls.dry_run:
            # A window in dry-run is judged by its simulated commands, and a
            # standing would-be command does not count against itself.
            simulated = simulated_state(state)
            standing = is_standing(simulated, to_send, wish.wish_class)
            own_commands = (
                {}
                if standing
                else {
                    command.member_id: command.command for command in simulated.commands
                }
            )
            clock = None if standing else simulated.last_comfort_movement
        gate_input = GateInput(
            config=config,
            snapshot=snapshot,
            wish=wish,
            to_send=to_send,
            controls=controls,
            own_commands=own_commands,
            last_comfort_movement=clock,
            restores_constraint=restores,
        )
        for registration in self.gate_rules:
            if skips(wish.wish_class, registration.reasons):
                continue
            if wish.wish_class not in registration.applies_to:
                continue
            outcome = registration.evaluate(gate_input)
            if outcome is None:
                continue
            if (
                outcome.kind is GateKind.SEND
                or outcome.rule is not registration.rule
                or outcome.reason not in registration.reasons
            ):
                raise ValueError(
                    f"the gate rule {registration.rule.value!r} holds back in its "
                    "own name or returns nothing"
                )
            return replace(outcome, dry_run=True) if controls.dry_run else outcome
        return GateOutcome.send()

    # --- Recompute ----------------------------------------------------------

    def recompute(self, config: WindowConfig, snapshot: WorldSnapshot) -> Decision:
        """Return the decision for one window against one world snapshot."""
        member_ids = tuple(member.member_id for member in config.members)
        observed = tuple(member.member_id for member in snapshot.observation.members)
        if observed != member_ids:
            raise ValueError(
                "the snapshot observes other members than the window is configured "
                "with, or in another order"
            )
        wishes = self._wishes(config, snapshot)
        winner = next(
            (wish for wish in wishes if wish.kind is not WishKind.NO_OPINION), None
        )
        others = tuple(
            LayerReason(wish.layer, wish.reason)
            for wish in wishes
            if wish is not winner
        )
        if winner is None or winner.kind is not WishKind.TARGET:
            return Decision(winning_wish=winner, other_layers=others)
        targets = _initial_targets(winner, member_ids)
        restores = self._violated_by_position(config, snapshot, winner, targets)
        results, targets = self._constrain(config, snapshot, winner, targets)
        to_send = tuple(target for target in targets if target.position is not None)
        return Decision(
            winning_wish=winner,
            other_layers=others,
            constraints=results,
            targets=targets,
            gate=(
                self._gate(config, snapshot, winner, to_send, restores=restores)
                if to_send
                else None
            ),
        )


def _initial_targets(wish: Wish, member_ids: Sequence[str]) -> tuple[MemberTarget, ...]:
    """Return the target of every member as the winning wish states it."""
    if wish.member_positions:
        if tuple(target.member_id for target in wish.member_positions) != tuple(
            member_ids
        ):
            raise ValueError(
                "a wish per member names the members of the window, in their order"
            )
        return wish.member_positions
    return tuple(MemberTarget(member_id, wish.position) for member_id in member_ids)


def _require_same_members(
    before: tuple[MemberTarget, ...], after: tuple[MemberTarget, ...]
) -> None:
    """Require that a constraint names the same members and invents no target."""
    if len(before) != len(after):
        raise ValueError("a constraint result lists the target of every member")
    for old, new in zip(before, after, strict=True):
        if old.member_id != new.member_id:
            raise ValueError("a constraint result names the members in their order")
        if old.position is None and new.position is not None:
            raise ValueError("a constraint never gives a pinned member a target again")
