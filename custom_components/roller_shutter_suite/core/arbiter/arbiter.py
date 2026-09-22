"""The arbiter: layers, then constraints, then the gate.

One arbiter decides for one window. It has no state of its own and reads no
clock: the same window configuration and the same world snapshot always yield
the same decision. It knows no feature. Layers, constraints and gate rules are
registered; their order is the order of the model's enumerations, which is the
order of the design specification.

**The safety net.** No exception that a registered function raises leaves
``recompute``, and none loosens a restriction or stops a fire or a protection
decision. A layer that raises has no opinion; a constraint that raises
applies its cautious result; a gate rule that raises holds the wish back
(decided by the project owner for a fire wish: only a failed maintenance lock
holds it back, every other failed rule sends it, and never twice inside one
expectation window). Each case is a reason code in the decision and a fact in
``Decision.faults``; the core does not log. Only ``Exception`` is caught,
never ``BaseException``.
"""

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum

from custom_components.roller_shutter_suite.core.model import (
    ConstraintResult,
    Decision,
    EvaluationFault,
    FunctionId,
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
from .gate import fire_command_pending
from .layers import disabled_functions
from .registry import (
    ConstraintFunction,
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


def _layers_in_order(
    registrations: Iterable[LayerRegistration],
) -> tuple[LayerRegistration, ...]:
    """Sort the layers, and the parts of a layer by their function.

    A comfort layer can be registered in several parts, one per function
    (shading and solar heating are one layer). The parts are sorted in the
    order of ``FunctionId``, never in the order of registration. The same
    function twice is refused, and so is a second registration of the fire
    layer or the protection layer.
    """
    items = tuple(registrations)
    seen: set[tuple[Layer, FunctionId | None]] = set()
    for item in items:
        if item.layer.wish_class is not WishClass.COMFORT and any(
            layer is item.layer for layer, _ in seen
        ):
            raise ValueError(f"the layer {item.layer.value!r} is registered twice")
        if (item.layer, item.function) in seen:
            function = "" if item.function is None else item.function.value
            raise ValueError(
                f"the layer {item.layer.value!r} is registered twice for the "
                f"function {function!r}; the parts of a layer have different "
                "functions"
            )
        seen.add((item.layer, item.function))
    functions = list(FunctionId)
    return tuple(
        sorted(
            items,
            key=lambda item: (
                list(Layer).index(item.layer),
                -1 if item.function is None else functions.index(item.function),
            ),
        )
    )


@dataclass(frozen=True, slots=True)
class Arbiter:
    """The registries and the evaluation. Immutable; it keeps nothing."""

    layers: tuple[LayerRegistration, ...] = ()
    constraints: tuple[ConstraintRegistration, ...] = ()
    gate_rules: tuple[GateRuleRegistration, ...] = ()

    def __post_init__(self) -> None:
        """Put every registry in the specified order and refuse duplicates."""
        object.__setattr__(self, "layers", _layers_in_order(self.layers))
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

    def _answers(
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        faults: list[EvaluationFault],
    ) -> list[tuple[Wish, FunctionId | None]]:
        """Ask every layer, in order; return each answer with the function that spoke.

        A layer that is not registered steps aside. A layer can have several
        parts, one registration per function; they stand in the order of
        ``FunctionId``, and each part answers for itself. Every part is
        asked, as every layer is, except a part whose function is disabled
        for the window: comfort becomes cautious, a faulty stored setting
        never moves a window, and its code does not even run. Such a part
        answers "no opinion" with ``function_disabled_by_fault``.

        **A layer or a part that raises has no opinion** (``layer_failed``),
        and every other layer is still asked: whatever a comfort layer
        raises, the fire layer and the protection layer are evaluated. An
        answer that is no answer of this layer (another layer's wish, targets
        for other members) counts as raised. An exception in the fire layer
        or the protection layer itself cannot be replaced by a cautious
        value; it is reported, and the layers below still run.
        """
        disabled = disabled_functions(config)
        member_ids = tuple(member.member_id for member in config.members)
        answers: list[tuple[Wish, FunctionId | None]] = []
        for layer in Layer:
            parts = [entry for entry in self.layers if entry.layer is layer]
            if not parts:
                answers.append(
                    (Wish.no_opinion(layer, ReasonCode.NOT_CONFIGURED), None)
                )
            for part in parts:
                if part.function is not None and part.function in disabled:
                    wish = Wish.no_opinion(layer, ReasonCode.FUNCTION_DISABLED_BY_FAULT)
                else:
                    try:
                        wish = part.evaluate(config, snapshot)
                        _require_answer_of(layer, wish, member_ids)
                    except Exception as error:  # noqa: BLE001 - the safety net: a layer that raises has no opinion
                        faults.append(EvaluationFault.of(layer, part.function, error))
                        wish = Wish.no_opinion(layer, ReasonCode.LAYER_FAILED)
                answers.append((wish, part.function))
        return answers

    # --- Constraints --------------------------------------------------------

    def _constrain(
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        wish: Wish,
        targets: tuple[MemberTarget, ...],
        faults: list[EvaluationFault],
    ) -> tuple[tuple[ConstraintResult, ...], tuple[MemberTarget, ...]]:
        """Apply the constraints in order. Fire is subject to none.

        **A constraint that raises applies its cautious result**
        (``constraint_failed``): the most restrictive result it could have
        produced for this wish, if its registration states one (``cautious``),
        and otherwise, or if that raises too, every member is pinned and the
        wish is not executed. A result that is no result of this constraint
        counts as raised. The later constraints still apply.
        """
        results: list[ConstraintResult] = []
        if wish.wish_class is WishClass.FIRE:
            return (), targets
        for registration in self.constraints:
            if wish.wish_class not in registration.applies_to:
                continue
            constraint_input = ConstraintInput(config, snapshot, wish, targets)
            try:
                result = _result_of(registration.apply, registration, constraint_input)
            except Exception as error:  # noqa: BLE001 - the safety net: a constraint that raises keeps restricting
                faults.append(
                    EvaluationFault.of(
                        registration.constraint, registration.function, error
                    )
                )
                result = _cautious_result(registration, constraint_input, faults)
            if result is None:
                continue
            results.append(result)
            targets = result.targets
        return tuple(results), targets

    def _violated_by_position(
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        wish: Wish,
        targets: tuple[MemberTarget, ...],
        faults: list[EvaluationFault],
    ) -> bool:
        """Say whether the window stands where a constraint on the wish forbids it.

        The answer "yes" exempts the movement from the minimum change of
        motor protection, so a check that raises answers "no": no exemption
        is granted because of an exception.
        """
        if wish.wish_class is WishClass.FIRE:
            return False
        constraint_input = ConstraintInput(config, snapshot, wish, targets)
        violated = False
        for registration in self.constraints:
            if (
                registration.violated_by_position is None
                or wish.wish_class not in registration.applies_to
            ):
                continue
            try:
                violated = violated or bool(
                    registration.violated_by_position(constraint_input)
                )
            except Exception as error:  # noqa: BLE001 - the safety net: no exemption because of an exception
                faults.append(
                    EvaluationFault.of(
                        registration.constraint, registration.function, error
                    )
                )
        return violated

    # --- Gate ---------------------------------------------------------------

    def _gate(  # noqa: PLR0913 - what reached the gate, and the list of faults
        self,
        config: WindowConfig,
        snapshot: WorldSnapshot,
        wish: Wish,
        to_send: tuple[MemberTarget, ...],
        faults: list[EvaluationFault],
        *,
        restores: bool = False,
    ) -> GateOutcome:
        """Evaluate the gate rules in order; the first rule that applies decides.

        **A rule that raises holds the wish back** (``gate_rule_failed``), for
        every wish class it was asked for: the restriction applies. It is a
        deferral with the upper bound of every deferral whose end nobody
        knows, so the window is evaluated again. An outcome that is no
        outcome of this rule counts as raised. A fire wish is never asked
        the rules of the fire bypass, so whatever they raise cannot stop it.
        For the rules the bypass does not skip the project owner decided:
        only a failed maintenance lock holds a fire wish back, because it
        protects a person working at the shutter; every other failed rule
        lets a pending fire wish pass, because an escape route that stays
        closed in a fire is the greater evil. See ``_failed_rule_lets_pass``.

        A fire wish that passed a failed rule is still never repeated inside
        the expectation window of its own command: a rule that fails at
        every recompute must not send at every recompute, and the failed
        rule may be the one that suppresses duplicates. The arbiter checks
        that itself, from the persisted own commands and without calling any
        rule (``fire_command_pending``). When the window has ended and the
        alarm is still active, the command is sent again, as on the normal
        path.
        """
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
        passed_a_failed_rule = False
        outcome: GateOutcome | None = None
        for registration in self.gate_rules:
            if skips(wish.wish_class, registration.reasons):
                continue
            if wish.wish_class not in registration.applies_to:
                continue
            try:
                outcome = _outcome_of(registration, gate_input)
            except Exception as error:  # noqa: BLE001 - the safety net: a gate rule that raises holds the wish back
                faults.append(
                    EvaluationFault.of(registration.rule, registration.function, error)
                )
                if _failed_rule_lets_pass(registration.rule, wish.wish_class):
                    passed_a_failed_rule = True
                    continue
                outcome = GateOutcome.defer(
                    registration.rule,
                    ReasonCode.GATE_RULE_FAILED,
                    reevaluate_no_later_than=snapshot.time + config.reevaluate_after,
                )
            if outcome is not None:
                break
        if (
            outcome is None
            and passed_a_failed_rule
            and fire_command_pending(gate_input)
        ):
            # The rule that failed may be the very one that keeps a command
            # from being repeated, so the safety net guarantees that itself.
            outcome = GateOutcome.suppress(
                GateRule.MOVEMENT_IN_FLIGHT, ReasonCode.DUPLICATE_COMMAND
            )
        if outcome is None:
            return GateOutcome.send()
        return replace(outcome, dry_run=True) if controls.dry_run else outcome

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
        faults: list[EvaluationFault] = []
        answers = self._answers(config, snapshot, faults)
        won = next(
            (
                index
                for index, (wish, _) in enumerate(answers)
                if wish.kind is not WishKind.NO_OPINION
            ),
            None,
        )
        winner, winning_function = (None, None) if won is None else answers[won]
        others = tuple(
            LayerReason(wish.layer, wish.reason, function)
            for index, (wish, function) in enumerate(answers)
            if index != won
        )
        if winner is None or winner.kind is not WishKind.TARGET:
            return Decision(
                winning_wish=winner,
                other_layers=others,
                winning_function=winning_function,
                faults=tuple(faults),
            )
        targets = _initial_targets(winner, member_ids)
        restores = self._violated_by_position(config, snapshot, winner, targets, faults)
        results, targets = self._constrain(config, snapshot, winner, targets, faults)
        to_send = tuple(target for target in targets if target.position is not None)
        gate = (
            self._gate(config, snapshot, winner, to_send, faults, restores=restores)
            if to_send
            else None
        )
        return Decision(
            winning_wish=winner,
            other_layers=others,
            constraints=results,
            targets=targets,
            gate=gate,
            winning_function=winning_function,
            faults=tuple(faults),
        )


def _require_answer_of(layer: Layer, wish: Wish, member_ids: Sequence[str]) -> None:
    """Require that a layer answered for itself and for the members of the window."""
    if not isinstance(wish, Wish):
        raise TypeError(f"the layer {layer.value!r} answers with a wish")
    if wish.layer is not layer:
        raise ValueError(
            f"the layer {layer.value!r} answered with a wish of the "
            f"layer {wish.layer.value!r}"
        )
    if wish.reason is ReasonCode.LAYER_FAILED:
        raise ValueError("only the arbiter says that a layer failed")
    if wish.member_positions and tuple(
        target.member_id for target in wish.member_positions
    ) != tuple(member_ids):
        raise ValueError(
            "a wish per member names the members of the window, in their order"
        )


def _initial_targets(wish: Wish, member_ids: Sequence[str]) -> tuple[MemberTarget, ...]:
    """Return the target of every member as the winning wish states it."""
    if wish.member_positions:
        return wish.member_positions
    return tuple(MemberTarget(member_id, wish.position) for member_id in member_ids)


def _result_of(
    function: ConstraintFunction,
    registration: ConstraintRegistration,
    constraint_input: ConstraintInput,
) -> ConstraintResult | None:
    """Apply a function of a constraint and require a result of that constraint."""
    result = function(constraint_input)
    if result is None:
        return None
    if not isinstance(result, ConstraintResult):
        raise TypeError("a constraint answers with a constraint result or nothing")
    if result.constraint is not registration.constraint:
        raise ValueError(
            f"the constraint {registration.constraint.value!r} answered as "
            f"{result.constraint.value!r}"
        )
    if result.reason is ReasonCode.CONSTRAINT_FAILED:
        raise ValueError("only the arbiter says that a constraint failed")
    _require_same_members(constraint_input.targets, result.targets)
    return result


def _cautious_result(
    registration: ConstraintRegistration,
    constraint_input: ConstraintInput,
    faults: list[EvaluationFault],
) -> ConstraintResult:
    """Return what applies instead of the result of a constraint that raised.

    The most restrictive result the constraint could have produced for this
    wish, if its registration states one. Without one, or if that raises as
    well, every member is pinned: the wish is not executed. The reason is
    ``constraint_failed`` either way, so the record shows the failure also
    where the cautious result changes nothing.
    """
    targets = tuple(
        MemberTarget(target.member_id, None) for target in constraint_input.targets
    )
    if registration.cautious is not None:
        try:
            limited = _result_of(registration.cautious, registration, constraint_input)
        except Exception as error:  # noqa: BLE001 - the safety net: without a cautious result nothing moves
            faults.append(
                EvaluationFault.of(
                    registration.constraint, registration.function, error
                )
            )
        else:
            targets = constraint_input.targets if limited is None else limited.targets
    return ConstraintResult(
        registration.constraint, ReasonCode.CONSTRAINT_FAILED, targets
    )


def _outcome_of(
    registration: GateRuleRegistration, gate_input: GateInput
) -> GateOutcome | None:
    """Evaluate a gate rule and require an outcome of that rule."""
    outcome = registration.evaluate(gate_input)
    if outcome is None:
        return None
    if (
        not isinstance(outcome, GateOutcome)
        or outcome.kind is GateKind.SEND
        or outcome.rule is not registration.rule
        or outcome.reason not in registration.reasons
    ):
        raise ValueError(
            f"the gate rule {registration.rule.value!r} holds back in its "
            "own name or returns nothing"
        )
    return outcome


def _failed_rule_lets_pass(rule: GateRule, wish_class: WishClass) -> bool:
    """Say whether a wish passes a gate rule that raised: only fire, never the lock.

    Decided by the project owner. For a protection and a comfort wish every
    rule that raises holds the wish back. A fire wish is held back by one
    failed rule only, the **maintenance lock**, because the lock protects a
    person working at the shutter. Every other failed rule that a fire wish
    is asked lets it pass: "no member can execute", "target reached", the part
    of "movement in flight" about a command that is still pending, and
    dry-run. An escape route that stays closed in a fire is the greater evil
    than a test window that opens on a fire alarm, or a command that goes to
    a member that cannot execute it.
    """
    return wish_class is WishClass.FIRE and rule is not GateRule.MAINTENANCE_LOCK


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
