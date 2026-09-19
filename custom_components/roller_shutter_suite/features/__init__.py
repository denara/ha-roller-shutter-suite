"""SPIKE S2: the registry of features that contribute configuration steps.

A feature block adds its package and one line here. Nothing else in the flows
changes: steps, schemas and translations are generated from the registry.
"""

from custom_components.roller_shutter_suite.flow.model import FeatureFlow

from .buttons.flow import FEATURE as BUTTONS
from .daily_routine.flow import FEATURE as DAILY_ROUTINE
from .shading.flow import FEATURE as SHADING

FEATURES: tuple[FeatureFlow, ...] = (DAILY_ROUTINE, SHADING, BUTTONS)
