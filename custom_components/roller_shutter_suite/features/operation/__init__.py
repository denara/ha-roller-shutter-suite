"""Operation: an entity that pauses the house, a group or a window.

The setting is the entry ``pause_source`` of the registry of the core, an
optional entity with the inheritance pattern (E4). While the entity is on,
it pauses the level in addition to the pause switch; an entity without a
value pauses as well (``controls.py``). This package only says how it appears
in the forms. The page has no switch: it is always shown.

Dry-run and arming are no setting of the registry: they are identity data of
a window, and the window's form asks for them on a page of its own after
this one (``flow/window_flow.py``).
"""

from typing import Final

from custom_components.roller_shutter_suite.flow.model import (
    FeatureForm,
    FieldForm,
    StepForm,
)

PAUSE_ENTITY_DOMAINS: Final = (
    "binary_sensor",
    "input_boolean",
    "switch",
    "schedule",
    "calendar",
)
"""Entities that are on or off: a helper, a sensor, a schedule, a calendar event."""

OPERATION: Final = FeatureForm(
    feature_id="operation",
    steps=(
        StepForm(
            name="pause",
            fields=(FieldForm("pause_source", entity_domains=PAUSE_ENTITY_DOMAINS),),
        ),
    ),
)
