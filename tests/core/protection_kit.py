"""Building blocks for the tests of the fire and protection layers (block C07).

Events of the house as values, the worlds they are judged in, and an engine
with the real fire and protection layers, the built-in constraints and gate
rules, the schedule stub of the arbiter kit, and the stand-ins of
``tests/sim/stand_ins.py`` for lockout protection (C08) and sleep mode (C11).
"""

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Final

from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    EventDirection,
    Layer,
    ManualOverrideDam,
    OverrideEndRule,
    Position,
    PositionOwner,
    ProtectionEventConfig,
    ProtectionEventState,
    ProtectionEventStatus,
    ProtectionTrigger,
    SourceValue,
    TriggerType,
    WindowConfig,
    WindowState,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.protection import (
    FIRE_LAYER,
    PROTECTION_LAYER,
)
from tests.core.arbiter_kit import (
    NOW,
    STUB_LAYERS,
    day,
    snapshot,
    window,
)
from tests.sim.stand_ins import LOCKOUT_STAND_IN, SLEEP_STAND_IN

FIRE: Final = "binary_sensor.example_smoke"
STORM: Final = "binary_sensor.example_storm"
HAIL: Final = "binary_sensor.example_hail"
WIND: Final = "sensor.example_wind_speed"
WEATHER: Final = "sensor.example_warning_level"

STORM_EVENT: Final = ProtectionEventConfig(
    event_id="storm",
    trigger=ProtectionTrigger(STORM),
    direction=EventDirection.CLOSED,
    rank=10,
)
HAIL_EVENT: Final = ProtectionEventConfig(
    event_id="hail",
    trigger=ProtectionTrigger(HAIL),
    direction=EventDirection.OPEN,
    rank=20,
)
WIND_EVENT: Final = ProtectionEventConfig(
    event_id="wind",
    trigger=ProtectionTrigger(
        WIND, kind=TriggerType.THRESHOLD, threshold=50.0, hysteresis=10.0
    ),
    direction=EventDirection.CLOSED,
    rank=5,
)


def protected(*events: ProtectionEventConfig, **changes: Any) -> WindowConfig:
    """Return the window of the kit with a fire source and the given events."""
    fields: dict[str, Any] = {
        "fire_source": FIRE,
        "protection_events": events or (STORM_EVENT,),
    }
    return window(**(fields | changes))


def calm(**extra: AnySourceValue) -> dict[str, AnySourceValue]:
    """Return a calm day: no fire, no storm, no hail; the schedule opens."""
    return day(
        **{
            FIRE: SourceValue.of(False),
            STORM: SourceValue.of(False),
            HAIL: SourceValue.of(False),
        }
    ) | dict(extra)


def with_(**sources: AnySourceValue) -> dict[str, AnySourceValue]:
    """Return a calm day with some sources changed, by the key of the kit."""
    keys = {"fire": FIRE, "storm": STORM, "hail": HAIL, "wind": WIND}
    return calm() | {keys.get(name, name): value for name, value in sources.items()}


ON = SourceValue.of(True)
OFF = SourceValue.of(False)
AWAY: AnySourceValue = SourceValue.unavailable()


def world(
    sources: Mapping[str, AnySourceValue],
    *,
    state: WindowState | None = None,
    position: int | None = 50,
    at: datetime = NOW,
) -> WorldSnapshot:
    """Return a snapshot of the kit at an instant."""
    base = snapshot(sources=sources, position=position, state=state)
    return WorldSnapshot(
        time=at,
        sun=base.sun,
        sources=base.sources,
        observation=base.observation,
        state=base.state,
        controls=base.controls,
    )


def active(
    event_id: str = "storm",
    since: datetime = NOW - timedelta(minutes=30),
    **changes: Any,
) -> ProtectionEventState:
    """Return the persisted state of an active event."""
    return ProtectionEventState(
        event_id, ProtectionEventStatus.ACTIVE, active_since=since, **changes
    )


def ended(
    event_id: str = "storm",
    at: datetime = NOW - timedelta(minutes=10),
    **changes: Any,
) -> ProtectionEventState:
    """Return the persisted state of an event that ended."""
    return ProtectionEventState(event_id, ended_at=at, **changes)


ARMED_AT: Final = NOW - timedelta(hours=2)


def override(
    armed_at: datetime = ARMED_AT, position: int = 40, **changes: Any
) -> ManualOverrideDam:
    """Return a manual override until the next part of the day, five hours ahead."""
    arguments: dict[str, Any] = {
        "armed_at": armed_at,
        "end_rule": OverrideEndRule.NEXT_PART_OF_DAY,
        "ends_at": NOW + timedelta(hours=5),
        "remembered_position": Position(position),
    }
    return ManualOverrideDam(**(arguments | changes))


def remembering(
    base: ProtectionEventState, position: int = 40, armed_at: datetime = ARMED_AT
) -> ProtectionEventState:
    """Return the state of an event that remembered a person's position."""
    return ProtectionEventState(
        base.event_id,
        base.status,
        active_since=base.active_since,
        ended_at=base.ended_at,
        released_at=base.released_at,
        remembered_position=Position(position),
        remembered_owner=PositionOwner.USER,
        override_armed_at=armed_at,
    )


def engine(config: WindowConfig | None = None, *, stand_ins: bool = False) -> Engine:
    """Return an engine with the real fire and protection layers.

    ``stand_ins`` adds the stand-ins for lockout protection (C08) and sleep
    mode (C11) of ``tests/sim/stand_ins.py``.
    """
    comfort = [
        entry
        for entry in STUB_LAYERS
        if entry.layer not in (Layer.FIRE, Layer.PROTECTION)
        and not (stand_ins and entry.layer is Layer.SLEEP)
    ]
    layers = [*comfort, FIRE_LAYER, PROTECTION_LAYER]
    constraints = []
    if stand_ins:
        layers.append(SLEEP_STAND_IN)
        constraints.append(LOCKOUT_STAND_IN)
    return Engine(
        protected() if config is None else config,
        build_arbiter(layers, constraints=constraints),
    )
