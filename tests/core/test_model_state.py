"""The persisted window state: construction, validation and the round trip."""

import copy
import json
from datetime import UTC, date, datetime, timedelta, timezone, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from custom_components.roller_shutter_suite.core.model import (
    WINDOW_STATE_SCHEMA_VERSION,
    DayType,
    ExternalRequest,
    HeldInput,
    LatchedDayType,
    ManualOverrideDam,
    MemberCommand,
    MemberState,
    MovementState,
    Observation,
    OverrideEndRule,
    OwnCommand,
    PersonAtWindowDam,
    Position,
    PositionOwner,
    PositionReference,
    ProtectionEventState,
    ProtectionEventStatus,
    ShadingEpisodeState,
    SimulatedState,
    SolarHeatingEpisodeState,
    WindowState,
    WishClass,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
LOCAL = datetime(2026, 3, 1, 7, 15, 30, 250000, tzinfo=timezone(timedelta(hours=1)))
NAIVE = datetime(2026, 3, 1, 12, 0)  # noqa: DTZ001 - the rejected case
NAIVE_TEXT = "2026-03-01T12:00:00"

LEFT = "cover.example_left"
RIGHT = "cover.example_right"


def _full_state() -> WindowState:
    """Return a state that uses every field of section 11."""
    return WindowState(
        owner=PositionOwner.USER,
        members=[
            MemberState(
                LEFT,
                last_own_command=OwnCommand(Position(30), LOCAL, WishClass.COMFORT),
                last_observation=Observation(MovementState.RESTING, Position(30)),
                position_reference=PositionReference.UNCERTAIN,
            ),
            MemberState(RIGHT, last_observation=Observation(MovementState.UNAVAILABLE)),
        ],
        manual_override=ManualOverrideDam(
            armed_at=NOW,
            end_rule=OverrideEndRule.FIXED_MINUTES,
            ends_at=NOW + timedelta(minutes=90),
            remembered_position=Position(55),
        ),
        person_at_window=PersonAtWindowDam(ends_at=NOW + timedelta(minutes=15)),
        protection_events=[
            ProtectionEventState(
                "storm",
                status=ProtectionEventStatus.ACTIVE,
                active_since=NOW - timedelta(hours=1),
                released=False,
                remembered_position=Position(100),
                remembered_owner=PositionOwner.ENGINE,
            ),
            ProtectionEventState("hail", released=True),
        ],
        fire_unacknowledged=True,
        shading_episode=ShadingEpisodeState(
            active_since=NOW - timedelta(hours=2),
            rain_lock_until=NOW + timedelta(hours=1),
        ),
        solar_heating_episode=SolarHeatingEpisodeState(
            active_since=NOW - timedelta(minutes=5), opened_once=True
        ),
        external_request=ExternalRequest(
            Position(80), "alarm clock", expires_at=NOW + timedelta(hours=1)
        ),
        latched_day_types=[
            LatchedDayType(date(2026, 3, 1), DayType.WEEKEND),
            LatchedDayType(date(2026, 3, 2), DayType.WORKDAY),
        ],
        last_comfort_movement=NOW - timedelta(minutes=20),
        held_frost=HeldInput(value=True, seen_at=NOW - timedelta(hours=3)),
        held_season=HeldInput(value=False, seen_at=NOW - timedelta(days=2)),
        frost_waiver_until=NOW + timedelta(hours=18),
        simulated=SimulatedState(
            commands=[
                MemberCommand(LEFT, OwnCommand(Position(0), NOW, WishClass.PROTECTION))
            ],
            last_comfort_movement=NOW - timedelta(minutes=1),
        ),
    )


# --- Round trip ---------------------------------------------------------------------


def test_new_window_state_is_the_state_after_first_setup() -> None:
    """Nothing persisted: owner unknown, no dam, nothing remembered."""
    state = WindowState()

    assert state.owner is PositionOwner.UNKNOWN
    assert state.members == ()
    assert state.manual_override is None
    assert state.person_at_window is None
    assert state.fire_unacknowledged is False
    assert state.simulated is None


@pytest.mark.parametrize("state", [WindowState(), _full_state()], ids=["new", "full"])
def test_window_state_round_trip_through_json(state: WindowState) -> None:
    """to_data → JSON text → from_data yields an equal state."""
    data = state.to_data()
    text = json.dumps(data)
    restored = WindowState.from_data(json.loads(text))

    assert restored == state
    assert hash(restored) == hash(state)
    assert restored.to_data() == data


def test_window_state_data_is_plain_and_versioned() -> None:
    """The data holds nothing but JSON types and states its schema version."""

    def assert_plain(value: object) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                assert type(key) is str
                assert_plain(item)
        elif isinstance(value, list):
            for item in value:
                assert_plain(item)
        else:
            assert value is None or type(value) in (bool, int, float, str)

    data = _full_state().to_data()

    assert_plain(data)
    assert data["schema_version"] == WINDOW_STATE_SCHEMA_VERSION == 1
    assert data["owner"] == "user"


def test_round_trip_keeps_the_point_in_time_of_a_named_time_zone() -> None:
    """A datetime in a named zone comes back as the same instant, and aware."""
    armed_at = datetime(2026, 7, 1, 21, 45, tzinfo=ZoneInfo("Europe/Paris"))
    dam = ManualOverrideDam(armed_at, OverrideEndRule.NEXT_PART_OF_DAY)

    restored = ManualOverrideDam.from_data(dam.to_data())

    assert restored == dam
    assert restored.armed_at.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize(
    "value",
    [
        OwnCommand(Position(0), NOW, WishClass.FIRE),
        MemberCommand(LEFT, OwnCommand(Position(0), NOW, WishClass.FIRE)),
        Observation(MovementState.MOVING_UP),
        Observation(MovementState.RESTING, Position(0)),
        MemberState(LEFT),
        ManualOverrideDam(NOW, OverrideEndRule.ROOM_EMPTY),
        ManualOverrideDam(NOW, OverrideEndRule.SHADING_EPISODE_END, None, Position(3)),
        PersonAtWindowDam(LOCAL),
        ProtectionEventState("storm"),
        ShadingEpisodeState(),
        ShadingEpisodeState(rain_lock_until=LOCAL),
        SolarHeatingEpisodeState(NOW),
        ExternalRequest(Position(50), ""),
        LatchedDayType(date(2026, 12, 25), DayType.HOLIDAY),
        HeldInput(value=False, seen_at=LOCAL),
        SimulatedState(),
    ],
    ids=lambda value: type(value).__name__,
)
def test_every_persisted_part_round_trips(value: Any) -> None:
    """Each part of the state survives JSON on its own."""
    restored = type(value).from_data(json.loads(json.dumps(value.to_data())))

    assert restored == value
    assert hash(restored) == hash(value)


# --- Naive datetimes are rejected ------------------------------------------------------


@pytest.mark.parametrize(
    "build",
    [
        lambda: OwnCommand(Position(0), NAIVE, WishClass.COMFORT),
        lambda: ManualOverrideDam(NAIVE, OverrideEndRule.NEXT_PART_OF_DAY),
        lambda: ManualOverrideDam(NOW, OverrideEndRule.FIXED_MINUTES, ends_at=NAIVE),
        lambda: PersonAtWindowDam(NAIVE),
        lambda: ProtectionEventState("storm", active_since=NAIVE),
        lambda: ShadingEpisodeState(active_since=NAIVE),
        lambda: ShadingEpisodeState(rain_lock_until=NAIVE),
        lambda: SolarHeatingEpisodeState(NAIVE),
        lambda: ExternalRequest(Position(1), "scene", expires_at=NAIVE),
        lambda: HeldInput(value=True, seen_at=NAIVE),
        lambda: SimulatedState(last_comfort_movement=NAIVE),
        lambda: WindowState(last_comfort_movement=NAIVE),
        lambda: WindowState(frost_waiver_until=NAIVE),
    ],
)
def test_naive_datetime_is_rejected_on_construction(build: Any) -> None:
    """No persisted type accepts a datetime without a time zone."""
    with pytest.raises(ValueError, match="timezone-aware"):
        build()


def test_datetime_with_a_tzinfo_that_gives_no_offset_is_rejected() -> None:
    """A tzinfo object alone is not enough; it has to yield an offset."""

    class NoOffset(tzinfo):
        def utcoffset(self, dt: datetime | None, /) -> None:
            return None

        def dst(self, dt: datetime | None, /) -> None:
            return None

        def tzname(self, dt: datetime | None, /) -> None:
            return None

    with pytest.raises(ValueError, match="timezone-aware"):
        PersonAtWindowDam(datetime(2026, 3, 1, 12, 0, tzinfo=NoOffset()))


@pytest.mark.parametrize(
    "path",
    [
        ("last_comfort_movement",),
        ("frost_waiver_until",),
        ("manual_override", "armed_at"),
        ("manual_override", "ends_at"),
        ("person_at_window", "ends_at"),
        ("protection_events", 0, "active_since"),
        ("shading_episode", "active_since"),
        ("shading_episode", "rain_lock_until"),
        ("solar_heating_episode", "active_since"),
        ("external_request", "expires_at"),
        ("held_frost", "seen_at"),
        ("held_season", "seen_at"),
        ("members", 0, "last_own_command", "time"),
        ("simulated", "last_comfort_movement"),
        ("simulated", "commands", 0, "command", "time"),
    ],
    ids=lambda path: ".".join(str(part) for part in path),
)
def test_naive_datetime_is_rejected_when_reading_persisted_data(
    path: tuple[str | int, ...],
) -> None:
    """Every timestamp of the stored data is checked at the boundary."""
    data: Any = copy.deepcopy(_full_state().to_data())
    holder = data
    for part in path[:-1]:
        holder = holder[part]
    assert isinstance(holder[path[-1]], str)
    holder[path[-1]] = NAIVE_TEXT

    with pytest.raises(ValueError, match="timezone-aware"):
        WindowState.from_data(data)


# --- Malformed persisted data -------------------------------------------------------------


def _changed(path: tuple[str | int, ...], value: object) -> Any:
    data: Any = copy.deepcopy(_full_state().to_data())
    holder = data
    for part in path[:-1]:
        holder = holder[part]
    holder[path[-1]] = value
    return data


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        (("owner",), "nobody", "owner: 'nobody' is not a valid PositionOwner"),
        (("owner",), 3, "owner: expected a string"),
        (("members",), {}, "members: expected a list"),
        (("members", 0), "cover", "members: expected an object"),
        (("members", 0, "member_id"), 7, "member_id: expected a string"),
        (("members", 0, "last_observation", "position"), 101, "within 0 and 100"),
        (("members", 0, "last_observation", "position"), 30.0, "expected an integer"),
        (("members", 0, "last_observation", "position"), True, "expected an integer"),
        (("fire_unacknowledged",), 1, "expected true or false"),
        (("fire_unacknowledged",), None, "expected true or false"),
        (("last_comfort_movement",), "yesterday", "last_comfort_movement"),
        (("latched_day_types", 0, "day"), "2026-13-01", "day"),
        (("latched_day_types", 0, "day_type"), "school_holiday", "DayType"),
        (("manual_override", "end_rule"), "never", "OverrideEndRule"),
        (("protection_events", 0, "status"), "blind", "ProtectionEventStatus"),
        (("members", 0, "position_reference"), "lost", "PositionReference"),
        (("members", 0, "last_own_command", "wish_class"), "fun", "WishClass"),
        (("members", 0, "last_observation", "state"), "flying", "MovementState"),
    ],
)
def test_malformed_persisted_data_is_rejected(
    path: tuple[str | int, ...], value: object, message: str
) -> None:
    """Wrong types and values outside their range raise a ValueError with the key."""
    with pytest.raises(ValueError, match=message):
        WindowState.from_data(_changed(path, value))


def test_error_names_the_path_of_the_broken_key() -> None:
    """The message leads from the top-level key to the broken one."""
    data = _changed(("members", 0, "last_own_command", "target"), -5)

    with pytest.raises(ValueError, match=r"members: last_own_command: target: "):
        WindowState.from_data(data)


def test_missing_key_is_rejected() -> None:
    """Persisted data of the current version is complete."""
    data = _full_state().to_data()
    del data["fire_unacknowledged"]

    with pytest.raises(ValueError, match="'fire_unacknowledged' is missing"):
        WindowState.from_data(data)


@pytest.mark.parametrize("data", [None, [], "state", 1])
def test_data_that_is_not_an_object_is_rejected(data: Any) -> None:
    """The top level is an object."""
    with pytest.raises(ValueError, match="expected an object"):
        WindowState.from_data(data)


@pytest.mark.parametrize("version", [0, 2, "1", None, True])
def test_other_schema_versions_are_refused(version: object) -> None:
    """Migration belongs to the persistence module; the model reads its own version."""
    data = WindowState().to_data()
    data["schema_version"] = version  # type: ignore[assignment]

    with pytest.raises(ValueError, match="schema"):
        WindowState.from_data(data)


def test_data_without_a_schema_version_is_refused() -> None:
    """Unversioned data is never guessed at."""
    data = WindowState().to_data()
    del data["schema_version"]

    with pytest.raises(ValueError, match="'schema_version' is missing"):
        WindowState.from_data(data)


# --- Validation on construction --------------------------------------------------------------


def test_window_state_lists_are_validated() -> None:
    """Members, events and latched dates are unique; two dates at most."""
    with pytest.raises(ValueError, match="occurs twice"):
        WindowState(members=[MemberState(LEFT), MemberState(LEFT)])
    with pytest.raises(ValueError, match="occurs twice"):
        WindowState(
            protection_events=[
                ProtectionEventState("storm"),
                ProtectionEventState("storm"),
            ]
        )
    with pytest.raises(ValueError, match="occurs twice"):
        WindowState(
            latched_day_types=[
                LatchedDayType(date(2026, 3, 1), DayType.WORKDAY),
                LatchedDayType(date(2026, 3, 1), DayType.HOLIDAY),
            ]
        )
    with pytest.raises(ValueError, match="today and tomorrow"):
        WindowState(
            latched_day_types=[
                LatchedDayType(date(2026, 3, day), DayType.WORKDAY) for day in (1, 2, 3)
            ]
        )
    command = OwnCommand(Position(0), NOW, WishClass.COMFORT)
    with pytest.raises(ValueError, match="occurs twice"):
        SimulatedState([MemberCommand(LEFT, command), MemberCommand(LEFT, command)])


def test_window_state_types_are_checked() -> None:
    """Every part has its type."""
    bad: Any = "x"
    with pytest.raises(TypeError, match="owner"):
        WindowState(owner=bad)
    with pytest.raises(TypeError, match="member state"):
        WindowState(members=[bad])
    with pytest.raises(TypeError, match="protection event state"):
        WindowState(protection_events=[bad])
    with pytest.raises(TypeError, match="fire flag"):
        WindowState(fire_unacknowledged=bad)
    with pytest.raises(TypeError, match="latched day type"):
        WindowState(latched_day_types=[bad])
    with pytest.raises(TypeError, match="simulated command"):
        SimulatedState([bad])


def test_parts_of_the_state_check_their_types() -> None:
    """Wrong types are refused where the value is created."""
    bad: Any = 1.5
    command = OwnCommand(Position(0), NOW, WishClass.COMFORT)
    with pytest.raises(TypeError, match="target"):
        OwnCommand(bad, NOW, WishClass.COMFORT)
    with pytest.raises(TypeError, match="time of a command"):
        OwnCommand(Position(0), bad, WishClass.COMFORT)
    with pytest.raises(TypeError, match="wish class"):
        OwnCommand(Position(0), NOW, bad)
    with pytest.raises(ValueError, match="must not be empty"):
        MemberCommand("", command)
    with pytest.raises(TypeError, match="command of a member"):
        MemberCommand(LEFT, bad)
    with pytest.raises(ValueError, match="must not be empty"):
        MemberState("")
    with pytest.raises(TypeError, match="last own command"):
        MemberState(LEFT, last_own_command=bad)
    with pytest.raises(TypeError, match="last observation"):
        MemberState(LEFT, last_observation=bad)
    with pytest.raises(TypeError, match="position reference"):
        MemberState(LEFT, position_reference=bad)
    with pytest.raises(TypeError, match="end rule"):
        ManualOverrideDam(NOW, bad)
    with pytest.raises(TypeError, match="remembered position"):
        ManualOverrideDam(NOW, OverrideEndRule.ROOM_EMPTY, remembered_position=bad)
    with pytest.raises(ValueError, match="must not be empty"):
        ProtectionEventState("")
    with pytest.raises(TypeError, match="status"):
        ProtectionEventState("storm", status=bad)
    with pytest.raises(TypeError, match="released"):
        ProtectionEventState("storm", released=bad)
    with pytest.raises(TypeError, match="remembered position"):
        ProtectionEventState("storm", remembered_position=bad)
    with pytest.raises(TypeError, match="remembered owner"):
        ProtectionEventState("storm", remembered_owner=bad)
    with pytest.raises(TypeError, match="opened once"):
        SolarHeatingEpisodeState(NOW, opened_once=bad)
    with pytest.raises(TypeError, match="position of a request"):
        ExternalRequest(bad, "scene")
    with pytest.raises(TypeError, match="reason of a request"):
        ExternalRequest(Position(1), bad)
    with pytest.raises(TypeError, match="value of a held input"):
        HeldInput(value=bad, seen_at=NOW)


def test_day_type_is_latched_for_a_date_not_for_a_point_in_time() -> None:
    """A datetime is not accepted where a calendar date is meant."""
    bad: Any = "2026-03-01"
    with pytest.raises(TypeError, match="not for a datetime"):
        LatchedDayType(NOW, DayType.WORKDAY)
    with pytest.raises(TypeError, match="date of a latched day type"):
        LatchedDayType(bad, DayType.WORKDAY)
    with pytest.raises(TypeError, match="latched day type"):
        LatchedDayType(date(2026, 3, 1), bad)


def test_enumerations_of_the_state() -> None:
    """The values are those of the architecture document."""
    assert [value.value for value in PositionOwner] == ["engine", "user", "unknown"]
    assert [value.value for value in DayType] == ["workday", "weekend", "holiday"]
    assert [value.value for value in OverrideEndRule] == [
        "fixed_minutes",
        "shading_episode_end",
        "next_part_of_day",
        "room_empty",
    ]
    assert [value.value for value in ProtectionEventStatus] == ["active", "inactive"]
