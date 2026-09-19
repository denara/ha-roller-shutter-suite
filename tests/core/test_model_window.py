"""Capability profile, observation, window configuration and world snapshot."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    CoveringType,
    MemberConfig,
    MemberObservation,
    MovementState,
    Observation,
    Position,
    PositionReference,
    PositionSource,
    PositionUpdates,
    ScheduleProfile,
    SourceValue,
    SunPosition,
    TemperatureTier,
    TransitReporting,
    WindowCapabilities,
    WindowConfig,
    WindowObservation,
    WindowState,
    WorldSnapshot,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
NAIVE = datetime(2026, 3, 1, 12, 0)  # noqa: DTZ001 - the rejected case

LEFT = "cover.example_left"
RIGHT = "cover.example_right"


def _profile(**changes: Any) -> CapabilityProfile:
    arguments: dict[str, Any] = {
        "supports_open_close": True,
        "supports_set_position": True,
        "supports_stop": True,
        "reports_position": True,
        "travel_time_up": timedelta(seconds=24),
        "travel_time_down": timedelta(seconds=21),
    }
    return CapabilityProfile(**(arguments | changes))


# --- Capability profile ---------------------------------------------------------


def test_capability_profile_defaults_follow_the_architecture() -> None:
    """Calculated position, no report delay, transit states unknown until seen."""
    profile = _profile()

    assert profile.position_source is PositionSource.CALCULATED
    assert profile.report_delay == timedelta(0)
    assert profile.reports_transit_states is TransitReporting.UNKNOWN
    assert profile.position_updates is PositionUpdates.END_ONLY
    assert profile.travel_time_up != profile.travel_time_down


def test_capability_profile_of_a_polled_platform_with_a_measuring_drive() -> None:
    """All stated properties are carried as given."""
    profile = _profile(
        position_source=PositionSource.MEASURED,
        reports_transit_states=TransitReporting.NO,
        position_updates=PositionUpdates.LIVE,
        report_delay=timedelta(seconds=60),
    )

    assert profile.position_source is PositionSource.MEASURED
    assert profile.report_delay == timedelta(seconds=60)
    assert profile.reports_transit_states is TransitReporting.NO
    assert profile.position_updates is PositionUpdates.LIVE


def test_a_cover_without_position_feedback_is_a_valid_profile() -> None:
    """Feature N2: open and close only, no position, no stop."""
    profile = _profile(
        supports_set_position=False, supports_stop=False, reports_position=False
    )

    assert profile.reports_position is False
    assert profile.supports_open_close is True


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        ({"travel_time_up": timedelta(0)}, ValueError, "longer than zero"),
        ({"travel_time_down": timedelta(seconds=-1)}, ValueError, "longer than zero"),
        ({"travel_time_up": 24}, TypeError, "travel_time_up"),
        ({"report_delay": timedelta(seconds=-1)}, ValueError, "not be negative"),
        ({"report_delay": 60}, TypeError, "report delay"),
        ({"supports_stop": 1}, TypeError, "supports_stop"),
        ({"reports_position": None}, TypeError, "reports_position"),
        ({"position_source": "measured"}, TypeError, "position source"),
        ({"reports_transit_states": True}, TypeError, "transit reporting"),
        ({"position_updates": "live"}, TypeError, "position updates"),
    ],
)
def test_capability_profile_is_validated(
    changes: dict[str, Any], error: type[Exception], message: str
) -> None:
    """Durations are durations, flags are flags."""
    with pytest.raises(error, match=message):
        _profile(**changes)


def test_capability_profile_is_immutable_and_hashable() -> None:
    """Profiles are values."""
    profile = _profile()

    assert profile == _profile()
    assert hash(profile) == hash(_profile())
    with pytest.raises(dataclasses.FrozenInstanceError):
        profile.supports_stop = False  # type: ignore[misc]


def test_enumerations_of_a_member() -> None:
    """The values are those of the architecture document."""
    assert [value.value for value in PositionSource] == ["measured", "calculated"]
    assert [value.value for value in PositionReference] == ["referenced", "uncertain"]
    assert [value.value for value in PositionUpdates] == ["live", "end_only"]
    assert [value.value for value in TransitReporting] == ["yes", "no", "unknown"]
    assert [value.value for value in MovementState] == [
        "resting",
        "moving_up",
        "moving_down",
        "unavailable",
    ]
    assert [value.value for value in CoveringType] == ["roller_shutter"]
    assert [value.value for value in ScheduleProfile] == ["default"]


# --- Observation ------------------------------------------------------------------


def test_observation_carries_state_class_and_position() -> None:
    """An observation is (state class, position or none)."""
    resting = Observation(MovementState.RESTING, Position(40))
    blind = Observation(MovementState.MOVING_DOWN)

    assert resting.available is True
    assert resting.moving is False
    assert blind.position is None
    assert blind.moving is True
    assert Observation(MovementState.MOVING_UP).moving is True
    assert resting == Observation(MovementState.RESTING, Position(40))
    assert hash(resting) == hash(Observation(MovementState.RESTING, Position(40)))


def test_unavailable_observation_has_no_position() -> None:
    """Missing data is not good news: unavailable never carries a position."""
    unavailable = Observation(MovementState.UNAVAILABLE)

    assert unavailable.available is False
    assert unavailable.moving is False
    with pytest.raises(ValueError, match="no position"):
        Observation(MovementState.UNAVAILABLE, Position(0))


def test_observation_types_are_checked() -> None:
    """State and position are typed values."""
    bad: Any = 40
    with pytest.raises(TypeError, match="state"):
        Observation(bad)
    with pytest.raises(TypeError, match="position"):
        Observation(MovementState.RESTING, bad)


# --- Window configuration -----------------------------------------------------------


def _window(**changes: Any) -> WindowConfig:
    arguments: dict[str, Any] = {
        "window_id": "window_example",
        "members": [MemberConfig(LEFT, _profile())],
    }
    return WindowConfig(**(arguments | changes))


def test_window_with_one_member_and_the_doors_kept_open() -> None:
    """Defaults: roller shutter, no morning condition, no tier, one profile key."""
    window = _window()

    assert window.covering_type is CoveringType.ROLLER_SHUTTER
    assert window.morning_condition_source is None
    assert window.shading_temperature_tiers == ()
    assert window.schedule_profile is ScheduleProfile.DEFAULT
    assert isinstance(window.members, tuple)
    assert hash(window) == hash(_window())


def test_window_carries_the_places_for_later_features() -> None:
    """A condition input and one temperature tier can be stated."""
    window = _window(
        morning_condition_source="somebody_awake",
        shading_temperature_tiers=[TemperatureTier(threshold=24.0, hysteresis=1.5)],
    )

    assert window.morning_condition_source == "somebody_awake"
    assert window.shading_temperature_tiers == (TemperatureTier(24.0, 1.5),)


def test_window_capabilities_are_the_lowest_common_denominator() -> None:
    """Section 9: what one member cannot do, the window cannot do."""
    window = _window(
        members=[
            MemberConfig(LEFT, _profile()),
            MemberConfig(
                RIGHT,
                _profile(supports_stop=False, reports_position=False),
            ),
        ]
    )

    assert window.capabilities == WindowCapabilities(
        supports_open_close=True,
        supports_set_position=True,
        supports_stop=False,
        reports_position=False,
    )
    assert _window().capabilities == WindowCapabilities(True, True, True, True)


@pytest.mark.parametrize(
    ("changes", "error", "message"),
    [
        ({"window_id": ""}, ValueError, "must not be empty"),
        ({"members": []}, ValueError, "at least one member"),
        ({"members": ["cover.example_left"]}, TypeError, "member of a window"),
        ({"covering_type": "venetian_blind"}, TypeError, "covering type"),
        ({"morning_condition_source": ""}, ValueError, "must not be empty"),
        ({"shading_temperature_tiers": [24.0]}, TypeError, "temperature tier"),
        ({"schedule_profile": "vacation"}, TypeError, "schedule profile"),
    ],
)
def test_window_configuration_is_validated(
    changes: dict[str, Any], error: type[Exception], message: str
) -> None:
    """A window that cannot exist is refused."""
    with pytest.raises(error, match=message):
        _window(**changes)


def test_window_members_are_unique() -> None:
    """A cover belongs to a window once."""
    with pytest.raises(ValueError, match="occurs twice"):
        _window(
            members=[MemberConfig(LEFT, _profile()), MemberConfig(LEFT, _profile())]
        )


def test_more_than_one_temperature_tier_is_not_supported_yet() -> None:
    """The list exists for multi-stage thresholds; only one entry is accepted."""
    tier = TemperatureTier(24.0, 1.0)
    with pytest.raises(ValueError, match="not supported yet"):
        _window(shading_temperature_tiers=[tier, TemperatureTier(30.0, 1.0)])


def test_member_config_and_temperature_tier_are_validated() -> None:
    """Identifiers are non-empty, numbers are finite, hysteresis is not negative."""
    bad: Any = "profile"
    with pytest.raises(ValueError, match="must not be empty"):
        MemberConfig("", _profile())
    with pytest.raises(TypeError, match="capability profile"):
        MemberConfig(LEFT, bad)
    with pytest.raises(ValueError, match="not be negative"):
        TemperatureTier(24.0, -0.5)
    with pytest.raises(ValueError, match="finite"):
        TemperatureTier(float("nan"), 1.0)
    with pytest.raises(TypeError, match="number"):
        TemperatureTier(True, 1.0)


# --- Window observation ---------------------------------------------------------------


def _observed(*members: tuple[str, Observation]) -> WindowObservation:
    return WindowObservation(
        [
            MemberObservation(member_id, observation)
            for member_id, observation in members
        ]
    )


def test_window_view_shows_the_first_member_and_moves_with_any_member() -> None:
    """Position of the first member; moving while any member moves."""
    window = _observed(
        (LEFT, Observation(MovementState.RESTING, Position(20))),
        (RIGHT, Observation(MovementState.MOVING_DOWN, Position(70))),
    )

    assert window.position == Position(20)
    assert window.moving is True
    assert window.available is True
    assert isinstance(window.members, tuple)


def test_window_is_available_while_one_member_is() -> None:
    """One missing member does not make the window unavailable."""
    window = _observed(
        (LEFT, Observation(MovementState.UNAVAILABLE)),
        (RIGHT, Observation(MovementState.RESTING, Position(70))),
    )

    assert window.available is True
    assert window.moving is False
    assert window.position is None


def test_window_is_unavailable_when_all_members_are() -> None:
    """Section 9: if all members are unavailable, the window is."""
    window = _observed(
        (LEFT, Observation(MovementState.UNAVAILABLE)),
        (RIGHT, Observation(MovementState.UNAVAILABLE)),
    )

    assert window.available is False
    assert window.position is None


def test_window_observation_is_validated() -> None:
    """At least one member, unique members, typed entries."""
    resting = Observation(MovementState.RESTING)
    bad: Any = "x"
    with pytest.raises(ValueError, match="at least one member"):
        WindowObservation([])
    with pytest.raises(ValueError, match="occurs twice"):
        _observed((LEFT, resting), (LEFT, resting))
    with pytest.raises(TypeError, match="member observation"):
        WindowObservation([bad])
    with pytest.raises(ValueError, match="must not be empty"):
        MemberObservation("", resting)
    with pytest.raises(TypeError, match="observation of a member"):
        MemberObservation(LEFT, bad)


# --- Sun position and world snapshot ------------------------------------------------------


def test_sun_position_ranges() -> None:
    """Azimuth from 0 up to but excluding 360, elevation from -90 to 90."""
    assert SunPosition(0, -90) == SunPosition(0.0, -90.0)
    assert SunPosition(359.9, 90.0) != SunPosition(0.0, 90.0)
    for azimuth, elevation in [(360.0, 10.0), (-0.1, 10.0), (180.0, 90.1)]:
        with pytest.raises(ValueError, match="must be"):
            SunPosition(azimuth, elevation)
    with pytest.raises(ValueError, match="finite"):
        SunPosition(float("inf"), 0.0)
    with pytest.raises(TypeError, match="number"):
        SunPosition("south", 0.0)  # type: ignore[arg-type]


def _snapshot(**changes: Any) -> WorldSnapshot:
    arguments: dict[str, Any] = {
        "time": NOW,
        "sun": SunPosition(azimuth=180.0, elevation=35.0),
        "sources": {
            "outdoor_temperature": SourceValue.of(4.5),
            "window_contact": SourceValue[str].unavailable(),
        },
        "observation": _observed(
            (LEFT, Observation(MovementState.RESTING, Position(100)))
        ),
        "state": WindowState(),
    }
    return WorldSnapshot(**(arguments | changes))


def test_world_snapshot_carries_everything_a_recompute_may_look_at() -> None:
    """Time, sun, sources, observed members and the persisted state."""
    snapshot = _snapshot()

    assert snapshot.time == NOW
    assert snapshot.sun == SunPosition(azimuth=180.0, elevation=35.0)
    assert snapshot.sources["outdoor_temperature"] == SourceValue.of(4.5)
    assert snapshot.sources["window_contact"].has_value is False
    assert snapshot.observation.position == Position(100)
    assert snapshot.state == WindowState()
    assert snapshot == _snapshot()


def test_world_snapshot_rejects_a_naive_time() -> None:
    """The core never sees a naive datetime."""
    with pytest.raises(ValueError, match="timezone-aware"):
        _snapshot(time=NAIVE)


def test_world_snapshot_copies_and_freezes_its_sources() -> None:
    """Changing the mapping that was handed in does not change the snapshot."""
    sources = {"rain": SourceValue.of(False)}
    snapshot = _snapshot(sources=sources)
    sources["rain"] = SourceValue.of(True)
    frozen: Any = snapshot.sources

    assert snapshot.sources["rain"].value is False
    with pytest.raises(TypeError):
        frozen["rain"] = SourceValue.of(True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.time = NOW  # type: ignore[misc]


def test_world_snapshot_types_are_checked() -> None:
    """Sources are source values, never raw states."""
    bad: Any = "x"
    with pytest.raises(TypeError, match="rain"):
        _snapshot(sources={"rain": False})
    with pytest.raises(ValueError, match="must not be empty"):
        _snapshot(sources={"": SourceValue.of(1)})
    with pytest.raises(TypeError, match="sun position"):
        _snapshot(sun=bad)
    with pytest.raises(TypeError, match="observed window"):
        _snapshot(observation=bad)
    with pytest.raises(TypeError, match="persisted window state"):
        _snapshot(state=bad)
    with pytest.raises(TypeError, match="time of a world snapshot"):
        _snapshot(time=bad)
