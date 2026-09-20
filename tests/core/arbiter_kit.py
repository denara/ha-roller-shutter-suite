"""Building blocks for the arbiter tests: a window, snapshots and stub layers.

The real feature layers are built by later blocks. The stubs here answer from
plain sources of the snapshot, so a test states a situation as data:

| Stub layer | Source | Answer |
|---|---|---|
| fire | ``fire_alarm`` (bool) | on: open, ``fire_alarm``. Off: "leave alone" with ``fire_unacknowledged`` while the persisted flag is set, else inactive. Missing: holds. |
| protection | ``storm`` (bool), ``return_to`` (int) | storm on: close, ``protection_event``. Off with ``return_to``: the return to the manual position. Missing: holds. |
| sleep | ``sleep`` (bool) | on: close, ``sleep_mode``. Missing: steps aside. |
| shading | ``shading_position`` (int) | the position, ``shading_geometric``. Missing: steps aside. |
| schedule | ``part_of_day`` (str) | ``day``: open, raise only. ``night``: close, lower only. Missing: steps aside. |
"""

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

from custom_components.roller_shutter_suite.core.arbiter import (
    LayerRegistration,
    wish_for_missing_input,
)
from custom_components.roller_shutter_suite.core.engine import Engine, build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    AnySourceValue,
    CapabilityProfile,
    ControlLevel,
    Controls,
    Direction,
    Layer,
    MemberConfig,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    SourceValue,
    SunPosition,
    WindowConfig,
    WindowObservation,
    WindowState,
    Wish,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode

LOCAL = timezone(timedelta(hours=1))
NOW = datetime(2026, 1, 15, 7, 30, tzinfo=LOCAL)

LEFT = "cover.example_left"
RIGHT = "cover.example_right"

ARMED = Controls(dry_run=False)
DRY_RUN = Controls(dry_run=True)


def profile(**changes: Any) -> CapabilityProfile:
    """Return a member that can do and report everything."""
    arguments: dict[str, Any] = {
        "supports_open_close": True,
        "supports_set_position": True,
        "supports_stop": True,
        "reports_position": True,
        "travel_time_up": timedelta(seconds=20),
        "travel_time_down": timedelta(seconds=18),
    }
    return CapabilityProfile(**(arguments | changes))


def window(*member_ids: str, **changes: Any) -> WindowConfig:
    """Return a window with the given members; one member by default."""
    profiles: Mapping[str, CapabilityProfile] = changes.pop("profiles", {})
    members = tuple(
        MemberConfig(member_id, profiles.get(member_id, profile()))
        for member_id in (member_ids or (LEFT,))
    )
    return WindowConfig(window_id="window.example", members=members, **changes)


def observed(**members: int | str | None) -> WindowObservation:
    """Return an observation; ``left=100``, ``right="unavailable"``, ``left=None``.

    An integer is a resting member at that position, ``None`` a resting member
    that reports no position, ``"unavailable"`` an unavailable member, and
    ``"up:40"`` a member that moves up and reports 40.
    """
    names = {"left": LEFT, "right": RIGHT}
    result: list[MemberObservation] = []
    for name, value in members.items():
        if value == "unavailable":
            observation = Observation(MovementState.UNAVAILABLE)
        elif isinstance(value, str):
            direction, _, position = value.partition(":")
            observation = Observation(
                MovementState.MOVING_UP
                if direction == "up"
                else MovementState.MOVING_DOWN,
                Position(int(position)),
            )
        else:
            observation = Observation(
                MovementState.RESTING, None if value is None else Position(value)
            )
        result.append(MemberObservation(names[name], observation))
    return WindowObservation(tuple(result))


def snapshot(
    *,
    sources: Mapping[str, AnySourceValue] | None = None,
    position: int | None = 50,
    observation: WindowObservation | None = None,
    state: WindowState | None = None,
    controls: Controls = ARMED,
) -> WorldSnapshot:
    """Return a snapshot at ``NOW``, of one member unless observed otherwise."""
    return WorldSnapshot(
        time=NOW,
        sun=SunPosition(azimuth=180.0, elevation=20.0),
        sources={} if sources is None else sources,
        observation=observed(left=position) if observation is None else observation,
        state=WindowState() if state is None else state,
        controls=controls,
    )


def on_level(level: str, **settings: Any) -> Controls:
    """Return armed controls with the settings on one of the three levels."""
    return Controls(dry_run=False, **{f"{level}_level": ControlLevel(**settings)})


# --- Stub layers ------------------------------------------------------------------


def fire_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Open while the alarm is active; hold until it is acknowledged afterwards."""
    alarm = world.sources.get("fire_alarm")
    missing = wish_for_missing_input(Layer.FIRE, alarm, hold=True)
    if missing is not None:
        return missing
    if alarm is not None and alarm.value is True:
        return Wish.target(Layer.FIRE, ReasonCode.FIRE_ALARM, FULLY_OPEN)
    if world.state.fire_unacknowledged:
        return Wish.leave_alone(Layer.FIRE, ReasonCode.FIRE_UNACKNOWLEDGED)
    return Wish.no_opinion(Layer.FIRE, ReasonCode.INACTIVE)


def protection_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Close during a storm; afterwards return to the manual position if told to."""
    storm = world.sources.get("storm")
    missing = wish_for_missing_input(Layer.PROTECTION, storm, hold=True)
    if missing is not None:
        return missing
    if storm is not None and storm.value is True:
        return Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_CLOSED)
    return_to = world.sources.get("return_to")
    if return_to is not None and return_to.has_value:
        return Wish.target(
            Layer.PROTECTION,
            ReasonCode.PROTECTION_RETURN_MANUAL,
            Position(int(return_to.value)),
        )
    return Wish.no_opinion(Layer.PROTECTION, ReasonCode.INACTIVE)


def sleep_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Close while sleep mode is on."""
    sleep = world.sources.get("sleep")
    if sleep is None:
        return Wish.no_opinion(Layer.SLEEP, ReasonCode.NOT_CONFIGURED)
    missing = wish_for_missing_input(Layer.SLEEP, sleep, hold=False)
    if missing is not None:
        return missing
    if sleep.value is True:
        return Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, FULLY_CLOSED)
    return Wish.no_opinion(Layer.SLEEP, ReasonCode.INACTIVE)


def shading_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Go to the shading position the source states."""
    wanted = world.sources.get("shading_position")
    if wanted is None:
        return Wish.no_opinion(Layer.SHADING, ReasonCode.OUTSIDE_EPISODE)
    missing = wish_for_missing_input(Layer.SHADING, wanted, hold=False)
    if missing is not None:
        return missing
    return Wish.target(
        Layer.SHADING, ReasonCode.SHADING_GEOMETRIC, Position(int(wanted.value))
    )


def schedule_layer(_config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Open during the day, raising only; close at night, lowering only."""
    part = world.sources.get("part_of_day")
    if part is None:
        return Wish.no_opinion(Layer.SCHEDULE, ReasonCode.NOT_CONFIGURED)
    missing = wish_for_missing_input(Layer.SCHEDULE, part, hold=False)
    if missing is not None:
        return missing
    if part.value == "day":
        return Wish.target(
            Layer.SCHEDULE,
            ReasonCode.SCHEDULE_DAY,
            FULLY_OPEN,
            direction=Direction.RAISE_ONLY,
        )
    return Wish.target(
        Layer.SCHEDULE,
        ReasonCode.SCHEDULE_NIGHT,
        FULLY_CLOSED,
        direction=Direction.LOWER_ONLY,
    )


STUB_LAYERS = (
    LayerRegistration(Layer.SCHEDULE, schedule_layer),
    LayerRegistration(Layer.SHADING, shading_layer),
    LayerRegistration(Layer.SLEEP, sleep_layer),
    LayerRegistration(Layer.PROTECTION, protection_layer),
    LayerRegistration(Layer.FIRE, fire_layer),
)
"""Registered in the wrong order on purpose: the arbiter sorts them."""


def engine(config: WindowConfig | None = None) -> Engine:
    """Return an engine with the stub layers and the built-in rules."""
    return Engine(window() if config is None else config, build_arbiter(STUB_LAYERS))


def day(**extra: AnySourceValue) -> dict[str, AnySourceValue]:
    """Return the sources of a calm day: no fire, no storm, the schedule opens."""
    sources: dict[str, AnySourceValue] = {
        "fire_alarm": SourceValue.of(False),
        "storm": SourceValue.of(False),
        "part_of_day": SourceValue.of("day"),
    }
    return sources | extra


def night(**extra: AnySourceValue) -> dict[str, AnySourceValue]:
    """Return the sources of a calm night: the schedule closes."""
    return day(**extra) | {"part_of_day": SourceValue.of("night")}


def fire(**extra: AnySourceValue) -> dict[str, AnySourceValue]:
    """Return the sources of a day on which the fire alarm is active."""
    return day(**extra) | {"fire_alarm": SourceValue.of(True)}


def storm(**extra: AnySourceValue) -> dict[str, AnySourceValue]:
    """Return the sources of a day with a storm."""
    return day(**extra) | {"storm": SourceValue.of(True)}
