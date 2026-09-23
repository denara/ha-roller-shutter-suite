"""Movement: motor protection, the staggering of motors, the re-evaluation time.

The settings are entries of the registry of the core: ``motor_min_change``
and ``motor_min_interval`` (motor protection, E10), ``stagger_gap``
(staggering between motors, E13) and ``reevaluate_after`` (the upper bound of
a deferral whose end is not known). This package only says how they appear in
the forms. The bounds are a convenience of the controls; the core decides
what is valid, and a test fails if a bound is wider than what the core
accepts.

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
                FieldForm("motor_min_change", minimum=0, maximum=100, unit="%"),
                FieldForm(
                    "motor_min_interval",
                    minimum=0,
                    unit="min",
                    seconds_per_unit=_MINUTE,
                ),
                FieldForm("stagger_gap", minimum=0, maximum=10, unit="s"),
                FieldForm(
                    "reevaluate_after",
                    expert=True,
                    minimum=1,
                    unit="min",
                    seconds_per_unit=_MINUTE,
                ),
            ),
        ),
    ),
)
