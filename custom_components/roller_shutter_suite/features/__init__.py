"""The features of the integration and the catalog the forms are built from.

A feature block adds a package next to this file that describes the form of
its step (``FeatureForm``), adds one line to :data:`FEATURES`, adds its
settings to the registry of the core and its translation fragments to
``translations_src/``. It edits no flow class.

This package imports nothing from Home Assistant: the translation generator
reads it too.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    resolve_window,
)
from custom_components.roller_shutter_suite.flow.model import Catalog, FeatureForm

from .daily_routine import DAILY_ROUTINE

FEATURES: Final[tuple[FeatureForm, ...]] = (DAILY_ROUTINE,)

CATALOG: Catalog = Catalog(
    registry=WINDOW_SETTINGS, features=FEATURES, resolve=resolve_window
)
"""The registry of the core, the forms above, and the resolver of the core."""


def get_catalog() -> Catalog:
    """Return the catalog in effect; the flows ask each time a step is shown."""
    return CATALOG
