"""The arbiter: one place per window that decides.

``world snapshot → layers (first opinion wins) → constraints → gate``. Every
feature contributes a layer, a constraint or a gate rule by registering it;
the evaluation in ``arbiter`` never changes for a feature. See
``docs/dev/arbiter.md``.

Import from the package: ``from ...core.arbiter import Arbiter``.
"""

from .arbiter import Arbiter
from .controls import MODE_TABLE, EffectiveControls, ModeEntry, effective_controls
from .dry_run import (
    arm,
    direction_of,
    is_standing,
    remember_would_be_send,
    simulated_state,
)
from .fire_bypass import FIRE_BYPASS, NEVER_BYPASSED, bypassed_rules, skips
from .gate import (
    BUILT_IN_GATE_RULES,
    MANUAL_OVERRIDE_DAM,
    PERSON_AT_WINDOW_DAM,
    ArmedDam,
    Dam,
    expectation_window_end,
)
from .layers import disabled_functions, wish_for_missing_input
from .registry import (
    ALL_CLASSES,
    ConstraintFunction,
    ConstraintInput,
    ConstraintRegistration,
    GateFunction,
    GateInput,
    GateRuleRegistration,
    LayerFunction,
    LayerRegistration,
    ViolationFunction,
    outranks,
    reported_positions,
)
from .sent import record_sent_commands
from .take_over import apply_take_over

__all__ = [
    "ALL_CLASSES",
    "BUILT_IN_GATE_RULES",
    "FIRE_BYPASS",
    "MANUAL_OVERRIDE_DAM",
    "MODE_TABLE",
    "NEVER_BYPASSED",
    "PERSON_AT_WINDOW_DAM",
    "Arbiter",
    "ArmedDam",
    "ConstraintFunction",
    "ConstraintInput",
    "ConstraintRegistration",
    "Dam",
    "EffectiveControls",
    "GateFunction",
    "GateInput",
    "GateRuleRegistration",
    "LayerFunction",
    "LayerRegistration",
    "ModeEntry",
    "ViolationFunction",
    "apply_take_over",
    "arm",
    "bypassed_rules",
    "direction_of",
    "disabled_functions",
    "effective_controls",
    "expectation_window_end",
    "is_standing",
    "outranks",
    "record_sent_commands",
    "remember_would_be_send",
    "reported_positions",
    "simulated_state",
    "skips",
    "wish_for_missing_input",
]
