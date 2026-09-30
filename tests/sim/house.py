"""The protection of the simulated house: its fire source and protection events.

Every window of the simulation gets these settings of the house unless a
scenario states others (``World.window``): a fire alarm, a storm that closes
and hail that opens. The real fire and protection layers of block C07 read
them; the scenarios script the sources. The identifiers are neutral examples.
"""

from collections.abc import Mapping
from datetime import timedelta
from types import MappingProxyType
from typing import Any, Final

from custom_components.roller_shutter_suite.core.model import (
    EventDirection,
    ProtectionEventConfig,
    ProtectionTrigger,
)

FIRE_SOURCE: Final = "binary_sensor.example_smoke_alarm"
STORM_SOURCE: Final = "binary_sensor.example_storm_warning"
HAIL_SOURCE: Final = "binary_sensor.example_hail_warning"

STORM: Final = ProtectionEventConfig(
    event_id="storm",
    trigger=ProtectionTrigger(STORM_SOURCE),
    direction=EventDirection.CLOSED,
    rank=10,
    waiting_time=timedelta(minutes=30),
    max_duration=timedelta(hours=12),
)
"""A storm closes; the default waiting time and maximum duration."""

HAIL: Final = ProtectionEventConfig(
    event_id="hail",
    trigger=ProtectionTrigger(HAIL_SOURCE),
    direction=EventDirection.OPEN,
    rank=20,
)
"""Hail opens (a choice of the house) and ranks above the storm."""

HOUSE: Final[Mapping[str, Any]] = MappingProxyType(
    {"fire_source": FIRE_SOURCE, "protection_events": (STORM, HAIL)}
)
"""The settings of the house every window of the simulation inherits."""
