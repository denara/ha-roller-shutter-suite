"""The engine: the façade the Home Assistant layer talks to.

So far it offers what the arbiter needs: ``recompute(snapshot) → decision``,
the state a decision leaves behind for a window in dry-run, and arming a
window. Observing members and command results are added by later blocks.

Every method is a pure function of its arguments. The engine keeps the window
configuration and the arbiter, both immutable, and nothing else: no state, no
clock.
"""

from collections.abc import Iterable
from dataclasses import dataclass

from .arbiter import (
    BUILT_IN_GATE_RULES,
    Arbiter,
    ConstraintRegistration,
    GateRuleRegistration,
    LayerRegistration,
    apply_take_over,
    arm,
    remember_would_be_send,
)
from .constraints import DIRECTION_CONSTRAINT, FROST_CONSTRAINT
from .model import Decision, WindowConfig, WindowState, WorldSnapshot
from .reasons import ReasonCode

BUILT_IN_CONSTRAINTS = (DIRECTION_CONSTRAINT, FROST_CONSTRAINT)
"""The constraints that belong to no single feature block."""


def build_arbiter(
    layers: Iterable[LayerRegistration],
    constraints: Iterable[ConstraintRegistration] = (),
    gate_rules: Iterable[GateRuleRegistration] = (),
) -> Arbiter:
    """Return an arbiter with the built-in constraints and gate rules plus these.

    The order of the arguments does not matter; the arbiter puts everything
    in the specified order.
    """
    return Arbiter(
        layers=tuple(layers),
        constraints=(*BUILT_IN_CONSTRAINTS, *constraints),
        gate_rules=(*BUILT_IN_GATE_RULES, *gate_rules),
    )


@dataclass(frozen=True, slots=True)
class Engine:
    """One window: its configuration and the arbiter that decides for it."""

    config: WindowConfig
    arbiter: Arbiter

    def recompute(self, snapshot: WorldSnapshot) -> Decision:
        """Return the decision for the window against the world snapshot."""
        return self.arbiter.recompute(self.config, snapshot)

    def state_after(self, snapshot: WorldSnapshot, decision: Decision) -> WindowState:
        """Return the window state after the decision was made.

        - A take-over (``movement_taken_over``) raises the wish class of the
          pending commands: of the real ones for an armed window, of the
          simulated ones for a window in dry-run.
        - For a window in dry-run a would-be send is remembered as a simulated
          command; the real state is never touched.
        - Otherwise the state is returned as it is: what a real command leaves
          behind is recorded by the blocks that send and track commands.
        """
        if (
            decision.gate is not None
            and decision.gate.reason is ReasonCode.MOVEMENT_TAKEN_OVER
        ):
            return apply_take_over(snapshot, decision)
        return remember_would_be_send(snapshot, decision)

    @staticmethod
    def arm(state: WindowState) -> WindowState:
        """Return the state an armed window starts with: no simulated state, no dam."""
        return arm(state)
