"""The engine: the façade the Home Assistant layer talks to.

It offers ``recompute(snapshot) → decision``; the state a decision leaves
behind for a window in dry-run or at a take-over; the state a real send
leaves behind; the state the result of a command leaves behind; arming a
window; and, from block C06, the movement tracker and the two dams:
``observe`` (one observation of a member), ``elapse`` (settle times,
deadlines and the ends of the dams), ``resume`` and
``sleep_mode_switched_on`` (the manual override ends), ``position_uncertain``
(the reference flag for the blocks that know of frost), and ``wake_ups``,
the one source of every instant a caller has to wake the window at.

Every method is a pure function of its arguments. The engine keeps the window
configuration and the arbiter, both immutable, and nothing else: no state, no
clock.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime

from . import dams, tracking
from .arbiter import (
    BUILT_IN_GATE_RULES,
    Arbiter,
    ConstraintRegistration,
    GateRuleRegistration,
    LayerRegistration,
    apply_take_over,
    arm,
    record_command_result,
    record_sent_commands,
    remember_would_be_send,
    wake_ups,
)
from .constraints import DIRECTION_CONSTRAINT, FROST_CONSTRAINT
from .model import (
    CommandResult,
    Decision,
    Observation,
    TrackerEvent,
    Transition,
    WindowConfig,
    WindowState,
    WorldSnapshot,
)
from .reasons import ReasonCode
from .schedule import SCHEDULE_LAYER

BUILT_IN_CONSTRAINTS = (DIRECTION_CONSTRAINT, FROST_CONSTRAINT)
"""The constraints that belong to no single feature block."""


FEATURE_LAYERS: tuple[LayerRegistration, ...] = (SCHEDULE_LAYER,)
"""The layers of the feature blocks; a block that builds a layer adds it here.

``tests/core/test_layer_triggers.py`` asks every comfort layer in this list for
a wish and fails if the wish does not state its trigger.
"""


def build_arbiter(
    layers: Iterable[LayerRegistration] | None = None,
    constraints: Iterable[ConstraintRegistration] = (),
    gate_rules: Iterable[GateRuleRegistration] = (),
) -> Arbiter:
    """Return an arbiter with the built-in constraints and gate rules plus these.

    Without ``layers`` the arbiter has the layers of the feature blocks
    (``FEATURE_LAYERS``); tests hand in their own.

    The order of the arguments does not matter; the arbiter puts everything
    in the specified order.
    """
    return Arbiter(
        layers=FEATURE_LAYERS if layers is None else tuple(layers),
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
          behind is recorded by ``state_after_send``.
        """
        if (
            decision.gate is not None
            and decision.gate.reason is ReasonCode.MOVEMENT_TAKEN_OVER
        ):
            return apply_take_over(snapshot, decision)
        return remember_would_be_send(snapshot, decision)

    def state_after_send(
        self,
        snapshot: WorldSnapshot,
        decision: Decision,
        command_ids: Mapping[str, str],
    ) -> WindowState:
        """Return the window state after the targets of the decision were sent.

        The caller hands the target of every addressed member
        (``Decision.addressed_targets``) to the actuator under a command
        identifier and then records the send here: per addressed member the
        last own command (target, direction, time, wish class, reason, start
        position) with one attempt, the tracker expecting it, the owner of
        the position (the integration), and for a comfort wish that completes
        no missed command the motor protection clock and one more comfort
        movement of the day. A member left out because it is unavailable
        remembers the command it missed. A decision that did not send leaves
        the state as it is.
        """
        return record_sent_commands(self.config, snapshot, decision, command_ids)

    def after_send(
        self,
        snapshot: WorldSnapshot,
        decision: Decision,
        command_ids: Mapping[str, str],
    ) -> Transition:
        """Return ``state_after_send`` and the event of the daily count, if it is due.

        Above the threshold of comfort movements (``comfort_movements_threshold``,
        default 40) the count is reported once per local day, with the count
        and the threshold as attributes (``comfort_movements_threshold``). It
        blocks nothing.
        """
        state = self.state_after_send(snapshot, decision, command_ids)
        count = state.comfort_movements
        threshold = self.config.comfort_movements_threshold
        if (
            count is None
            or count.reported
            or count.count <= threshold
            or count == snapshot.state.comfort_movements
        ):
            return Transition(state)
        state = replace(state, comfort_movements=replace(count, reported=True))
        return Transition(
            state,
            (
                TrackerEvent(
                    ReasonCode.COMFORT_MOVEMENTS_THRESHOLD,
                    count=count.count,
                    threshold=threshold,
                ),
            ),
        )

    @staticmethod
    def on_command_result(state: WindowState, result: CommandResult) -> WindowState:
        """Return the window state after the actuator reported a command's result.

        The last own command of the member gets the context ID, and a failed
        command is marked (``command_failed``), if its identifier is the one
        of the result; a late result of an older command changes nothing. The
        tracker no longer expects a failed command.
        """
        return record_command_result(state, result)

    @staticmethod
    def arm(state: WindowState) -> WindowState:
        """Return the state an armed window starts with: no simulated state, no dam."""
        return arm(state)

    def observe(  # noqa: PLR0913 - the observation, its member, the time and the facts it is judged by
        self,
        state: WindowState,
        member_id: str,
        observation: Observation,
        now: datetime,
        last_decision: Decision | None,
        *,
        dry_run: bool,
        user_id: str | None = None,
    ) -> Transition:
        """Return the state after one observation of a member, and the events it raised.

        An observation that does not change what the tracker knows (the last
        observation of the member) is dropped: the same state object comes
        back, with no event. ``last_decision`` is the decision of the last
        recompute; whether a protection wish won it decides which dam an
        external movement arms. ``dry_run`` is whether the window is in
        dry-run. ``user_id`` is the user in the context of the report, if
        any: a hint for the diagnostics that never decides. See
        ``core/tracking``.
        """
        return tracking.observe(
            self.config,
            state,
            member_id,
            observation,
            now=now,
            last_decision=last_decision,
            dry_run=dry_run,
            user_id=user_id,
        )

    def elapse(
        self, snapshot: WorldSnapshot, last_decision: Decision | None
    ) -> Transition:
        """Return the state after the time of the snapshot has come, and the events.

        Called before every recompute and at every wake-up (``wake_ups``):
        the tracker judges every member whose settle time or deadline has
        passed, and the dams end, turn into one another, or learn their end.
        The caller recomputes with the state that comes back.
        """
        dry_run = snapshot.controls.dry_run
        tracked = tracking.elapse(
            self.config, snapshot.state, snapshot.time, last_decision, dry_run=dry_run
        )
        if tracked.state is not snapshot.state:
            snapshot = replace(snapshot, state=tracked.state)
        dammed = dams.update_dams(self.config, snapshot, last_decision)
        if not tracked.events:
            return dammed
        return Transition(dammed.state, (*tracked.events, *dammed.events))

    @staticmethod
    def resume(state: WindowState) -> Transition:
        """End the manual override at once: the "resume automation" button and action.

        Nothing is replayed; the window is recomputed. Without an override
        nothing changes.
        """
        return dams.end_override(state)

    @staticmethod
    def sleep_mode_switched_on(state: WindowState) -> Transition:
        """End the manual override because sleep mode was switched on (section 3.1).

        Switching sleep mode on is a deliberate act of a person and says what
        the room shall look like now. Block C11 calls this for the windows
        the sleep switch covers.
        """
        return dams.end_override(state)

    def position_uncertain(
        self, state: WindowState, member_ids: tuple[str, ...]
    ) -> Transition:
        """Set the position reference of members to ``uncertain`` (frost, C10, C11)."""
        return tracking.position_uncertain(self.config, state, member_ids)

    def wake_ups(
        self, state: WindowState, now: datetime, *, dry_run: bool
    ) -> tuple[datetime, ...]:
        """Return every instant after ``now`` at which the caller wakes the window.

        The deadlines of the pending own commands, the ends of the settle
        times, and the ends of the dams (``wake_ups`` of the gate). At each,
        the caller hands the snapshot to :meth:`elapse` and recomputes.
        """
        return wake_ups(self.config, state, now, dry_run=dry_run)
