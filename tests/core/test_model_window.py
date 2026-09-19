"""Capability profile, observation, window configuration and world snapshot."""

import dataclasses
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_TOLERANCE_CALCULATED,
    DEFAULT_TOLERANCE_MEASURED,
    MIN_TOLERANCE,
    CapabilityProfile,
    CoveringType,
    MemberConfig,
    MemberObservation,
    MemberState,
    MovementState,
    Observation,
    OwnCommand,
    Position,
    PositionReference,
    PositionSource,
    PositionUpdates,
    ScheduleProfile,
    SourceValue,
    SunPosition,
    TemperatureTier,
    TransitReporting,
    TravelDirection,
    WindowCapabilities,
    WindowConfig,
    WindowObservation,
    WindowState,
    WishClass,
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


def test_tolerance_defaults_follow_the_position_source() -> None:
    """Section 8.3: 2 for a calculated position, 3 for a measured one, minimum 1."""
    assert (
        MIN_TOLERANCE,
        DEFAULT_TOLERANCE_CALCULATED,
        DEFAULT_TOLERANCE_MEASURED,
    ) == (
        1,
        2,
        3,
    )
    assert _profile().tolerance == DEFAULT_TOLERANCE_CALCULATED
    assert (
        _profile(position_source=PositionSource.MEASURED).tolerance
        == DEFAULT_TOLERANCE_MEASURED
    )
    assert _profile(stated_tolerance=MIN_TOLERANCE).tolerance == MIN_TOLERANCE
    assert (
        _profile(
            position_source=PositionSource.MEASURED, stated_tolerance=MIN_TOLERANCE
        ).tolerance
        == MIN_TOLERANCE
    )


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
        ({"stated_tolerance": 0}, ValueError, "within 1 and 100"),
        ({"stated_tolerance": 101}, ValueError, "within 1 and 100"),
        ({"stated_tolerance": 2.0}, TypeError, "tolerance must be an integer"),
        ({"stated_tolerance": True}, TypeError, "tolerance must be an integer"),
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


def test_window_capabilities_validate_their_flags() -> None:
    """An object that exists is valid: flags are booleans."""
    bad: Any = 1
    for position in range(4):
        flags: list[Any] = [True, True, True, True]
        flags[position] = bad
        with pytest.raises(TypeError, match="the capability"):
            WindowCapabilities(*flags)


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


TOLERANCES = {LEFT: 2, RIGHT: 2}


def _resting(left: int | None, right: int | None) -> WindowObservation:
    def observation(value: int | None) -> Observation:
        position = None if value is None else Position(value)
        return Observation(MovementState.RESTING, position)

    return _observed((LEFT, observation(left)), (RIGHT, observation(right)))


def _both(left: int | None, right: int | None) -> dict[str, Position]:
    """Return the last commanded targets; ``None`` means never commanded."""
    commanded = {LEFT: left, RIGHT: right}
    return {
        member: Position(value)
        for member, value in commanded.items()
        if value is not None
    }


def test_window_reports_movement_as_soon_as_one_member_does() -> None:
    """Whether the movement has settled is the tracker's knowledge, not this view's."""
    window = _observed(
        (LEFT, Observation(MovementState.RESTING, Position(20))),
        (RIGHT, Observation(MovementState.MOVING_DOWN, Position(70))),
    )

    assert window.reports_movement is True
    assert window.available is True
    assert isinstance(window.members, tuple)
    assert not hasattr(window, "moving")
    assert _resting(20, 20).reports_movement is False


def test_window_has_its_common_target_as_position_when_every_member_is_there() -> None:
    """Every member within its own tolerance of its last commanded target."""
    assert _resting(30, 31).position(_both(30, 30), TOLERANCES) == Position(30)
    assert _resting(28, 32).position(_both(30, 30), TOLERANCES) == Position(30)


def test_window_has_no_position_while_a_member_is_not_at_its_target() -> None:
    """No member speaks for the window, the first one included."""
    assert _resting(30, 70).position(_both(30, 30), TOLERANCES) is None
    assert _resting(70, 30).position(_both(30, 30), TOLERANCES) is None
    assert _resting(30, 33).position(_both(30, 30), TOLERANCES) is None


def test_tolerance_is_per_member() -> None:
    """A measured member may be three off, a calculated one only two."""
    tolerances = {LEFT: 2, RIGHT: 3}

    assert _resting(30, 33).position(_both(30, 30), tolerances) == Position(30)
    assert _resting(33, 30).position(_both(30, 30), tolerances) is None


def test_window_with_different_targets_per_member_has_no_single_position() -> None:
    """Members shaded to 21 and 36 are where they should be; there is no one number."""
    assert _resting(21, 36).position(_both(21, 36), TOLERANCES) is None
    assert _resting(21, 22).position(_both(21, 22), TOLERANCES) is None


def test_window_that_was_never_commanded_needs_members_that_agree() -> None:
    """No last own command for any member: the same position within tolerance."""
    assert _resting(50, 50).position({}, TOLERANCES) == Position(50)
    assert _resting(50, 52).position({}, TOLERANCES) == Position(51)
    assert _resting(50, 51).position({}, TOLERANCES) == Position(51)
    assert _resting(50, 53).position({}, TOLERANCES) is None
    assert _resting(50, 52).position({}, {LEFT: 3, RIGHT: 1}) is None


def test_window_with_only_some_members_commanded_has_no_position() -> None:
    """The fallback is for a window that was never commanded, not for a partial one."""
    assert _resting(60, 60).position(_both(None, 60), TOLERANCES) is None
    assert _resting(60, 60).position(_both(60, None), TOLERANCES) is None


def test_window_has_no_position_when_a_member_reports_none() -> None:
    """A member without feedback or an unavailable member: no window position."""
    assert _resting(None, 30).position(_both(30, 30), TOLERANCES) is None
    assert _resting(30, None).position({}, TOLERANCES) is None


def test_window_position_needs_consistent_arguments() -> None:
    """Commanded targets name members of the window; every member has a tolerance."""
    with pytest.raises(ValueError, match="not a member of this window"):
        _resting(1, 1).position({"cover.example_other": Position(1)}, TOLERANCES)
    with pytest.raises(ValueError, match="no tolerance given"):
        _resting(1, 1).position({}, {LEFT: 2})


def test_snapshot_takes_the_commanded_targets_from_the_persisted_state() -> None:
    """The last own command per member is persisted; the snapshot combines the two."""

    def commanded(member: str, target: int) -> MemberState:
        command = OwnCommand(
            command_id=f"command-{member}",
            target=Position(target),
            direction=TravelDirection.DOWN,
            time=NOW,
            wish_class=WishClass.COMFORT,
        )
        return MemberState(member, last_own_command=command)

    state = WindowState(members=[commanded(LEFT, 30), commanded(RIGHT, 30)])
    partly = WindowState(members=[commanded(LEFT, 30), MemberState(RIGHT)])

    assert state.commanded_targets == {LEFT: Position(30), RIGHT: Position(30)}
    assert partly.commanded_targets == {LEFT: Position(30)}
    assert WindowState().commanded_targets == {}
    assert _snapshot(observation=_resting(30, 31), state=state).window_position(
        TOLERANCES
    ) == Position(30)
    assert (
        _snapshot(observation=_resting(30, 50), state=state).window_position(TOLERANCES)
        is None
    )
    assert (
        _snapshot(observation=_resting(30, 30), state=partly).window_position(
            TOLERANCES
        )
        is None
    )
    assert _snapshot(observation=_resting(30, 30)).window_position(TOLERANCES) == (
        Position(30)
    )


def test_window_is_available_while_one_member_is() -> None:
    """One missing member does not make the window unavailable."""
    window = _observed(
        (LEFT, Observation(MovementState.UNAVAILABLE)),
        (RIGHT, Observation(MovementState.RESTING, Position(70))),
    )

    assert window.available is True
    assert window.reports_movement is False
    assert window.position({}, TOLERANCES) is None


def test_window_is_unavailable_when_all_members_are() -> None:
    """Section 9: if all members are unavailable, the window is."""
    window = _observed(
        (LEFT, Observation(MovementState.UNAVAILABLE)),
        (RIGHT, Observation(MovementState.UNAVAILABLE)),
    )

    assert window.available is False
    assert window.position({}, TOLERANCES) is None


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
    assert snapshot.window_position({LEFT: 2}) == Position(100)
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
