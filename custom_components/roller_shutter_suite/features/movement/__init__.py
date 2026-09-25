"""Movement: motor protection, the staggering of motors, the re-evaluation time.

The settings are entries of the registry of the core: ``motor_min_change``
and ``motor_min_interval`` (motor protection, E10), ``stagger_gap``
(staggering between motors, E13) and ``reevaluate_after`` (the upper bound of
a deferral whose end is not known). This package only says how they appear in
the forms. The range and the unit of a number are part of its registry
entry, never of this description.

The feature has no switch: motor protection is never switched off as a whole,
because it restricts movement, and each part has its own "zero switches it
off".
"""

from typing import Final

from custom_components.roller_shutter_suite.flow.model import (
    FeatureForm,
    FieldForm,
    StepForm,
)

_MINUTE: Final = 60

MOVEMENT: Final = FeatureForm(
    feature_id="movement",
    steps=(
        StepForm(
            name="general",
            fields=(
                FieldForm("motor_min_change"),
                FieldForm(
                    "motor_min_interval",
                    seconds_per_unit=_MINUTE,
                ),
                FieldForm("stagger_gap"),
                FieldForm(
                    "reevaluate_after",
                    expert=True,
                    seconds_per_unit=_MINUTE,
                ),
            ),
        ),
    ),
)
