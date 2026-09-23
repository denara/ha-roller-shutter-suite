"""Stub layers for features whose blocks do not exist yet.

The fire layer and the protection layer are built by block C07. Until then
the simulation registers these two stubs, which answer from plain sources of
the world, so a scenario can show what the gate does with a fire or a
protection wish: the bypass, the maintenance lock, dry-run, "no intermediate
position". They are **extension points**: when the real layers exist, a
scenario registers them instead (``Simulation(layers=...)``) and scripts the
sources those layers read.

| Stub | Source | Answer |
|---|---|---|
| fire | ``fire_alarm`` (bool) | on: open fully, ``fire_alarm``; off: inactive; missing: holds |
| protection | ``storm`` (bool) | on: close fully, ``protection_event``; off: inactive; missing: holds |

A missing input holds the window ("leave alone"), because both are safety
layers; that is the rule of thumb of the architecture, not a decision of
this stub.
"""

from typing import Final

from custom_components.roller_shutter_suite.core.arbiter import (
    LayerRegistration,
    wish_for_missing_input,
)
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    FunctionId,
    Layer,
    WindowConfig,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.schedule import SCHEDULE_LAYER

FIRE_SOURCE: Final = "fire_alarm"
STORM_SOURCE: Final = "storm"


def stub_fire_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Open fully while the alarm source is on."""
    alarm = world.sources.get(FIRE_SOURCE)
    missing = wish_for_missing_input(Layer.FIRE, alarm, hold=True)
    if missing is not None:
        return missing
    assert alarm is not None
    if alarm.value is True:
        return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN)
    return Wish.no_opinion(Layer.FIRE, ReasonCode.INACTIVE)


def stub_protection_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Close fully while the storm source is on."""
    storm = world.sources.get(STORM_SOURCE)
    missing = wish_for_missing_input(Layer.PROTECTION, storm, hold=True)
    if missing is not None:
        return missing
    assert storm is not None
    if storm.value is True:
        return Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED)
    return Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE)


STUB_FIRE_LAYER: Final = LayerRegistration(
    Layer.FIRE, stub_fire_layer, function=FunctionId.FIRE
)
STUB_PROTECTION_LAYER: Final = LayerRegistration(
    Layer.PROTECTION, stub_protection_layer, function=FunctionId.PROTECTION_EVENTS
)

DEFAULT_LAYERS: Final = (SCHEDULE_LAYER, STUB_FIRE_LAYER, STUB_PROTECTION_LAYER)
"""The real schedule layer and the two stubs."""
