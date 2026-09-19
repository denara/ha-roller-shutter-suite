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
    TravelDirection,
    WindowState,
    WishClass,
)

NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
LOCAL = datetime(2026, 3, 1, 7, 15, 30, 250000, tzinfo=timezone(timedelta(hours=1)))
NAIVE = datetime(2026, 3, 1, 12, 0)  # noqa: DTZ001 - the rejected case
NAIVE_TEXT = "2026-03-01T12:00:00"

LEFT = "cover.example_left"
RIGHT = "cover.example_right"


def _command(target: Any, time: Any, wish_class: Any, **more: Any) -> OwnCommand:
    arguments: dict[str, Any] = {
        "command_id": "command-1",
        "target": target,
        "direction": TravelDirection.DOWN,
        "time": time,
        "wish_class": wish_class,
    }
    return OwnCommand(**(arguments | more))


def _full_state() -> WindowState:
    """Return a state that uses every field of section 11."""
    return WindowState(
        owner=PositionOwner.USER,
        members=[
            MemberState(
                LEFT,
                last_own_command=_command(
                    Position(30), LOCAL, WishClass.COMFORT, context_id="context-1"
                ),
                last_observation=Observation(MovementState.RESTING, Position(30)),
                position_reference=PositionReference.UNCERTAIN,
                command_attempts=2,
                last_attempt_at=LOCAL,
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
                released_at=NOW - timedelta(minutes=30),
                remembered_position=Position(100),
                remembered_owner=PositionOwner.ENGINE,
            ),
            ProtectionEventState("hail", ended_at=NOW - timedelta(minutes=10)),
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
                MemberCommand(LEFT, _command(Position(0), NOW, WishClass.PROTECTION))
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


def test_persisted_instants_are_kept_in_utc() -> None:
    """A datetime in a named zone is the same instant afterwards, in UTC."""
    armed_at = datetime(2026, 7, 1, 21, 45, tzinfo=ZoneInfo("Europe/Paris"))
    dam = ManualOverrideDam(armed_at, OverrideEndRule.NEXT_PART_OF_DAY)

    restored = ManualOverrideDam.from_data(dam.to_data())

    assert dam.armed_at == armed_at
    assert dam.armed_at.utcoffset() == timedelta(0)
    assert dam.armed_at.hour == armed_at.hour - 2
    assert restored == dam
    assert restored.armed_at.utcoffset() == timedelta(0)


@pytest.mark.parametrize("fold", [0, 1], ids=["first pass", "second pass"])
def test_round_trip_in_the_repeated_hour_of_a_clock_change(fold: int) -> None:
    """02:30 exists twice on the last Sunday of October; both survive as equal."""
    zone = ZoneInfo("Europe/Paris")
    repeated = datetime(2026, 10, 25, 2, 30, tzinfo=zone, fold=fold)
    state = WindowState(
        members=[
            MemberState(
                LEFT,
                _command(Position(0), repeated, WishClass.COMFORT),
                command_attempts=1,
                last_attempt_at=repeated,
            )
        ],
        manual_override=ManualOverrideDam(
            repeated, OverrideEndRule.FIXED_MINUTES, ends_at=repeated
        ),
        person_at_window=PersonAtWindowDam(repeated),
        protection_events=[
            ProtectionEventState(
                "storm", status=ProtectionEventStatus.ACTIVE, active_since=repeated
            ),
            ProtectionEventState("hail", ended_at=repeated),
        ],
        shading_episode=ShadingEpisodeState(repeated, repeated),
        solar_heating_episode=SolarHeatingEpisodeState(repeated),
        external_request=ExternalRequest(Position(1), "scene", expires_at=repeated),
        last_comfort_movement=repeated,
        held_frost=HeldInput(value=True, seen_at=repeated),
        frost_waiver_until=repeated,
        simulated=SimulatedState(last_comfort_movement=repeated),
    )

    restored = WindowState.from_data(json.loads(json.dumps(state.to_data())))

    assert restored == state
    assert hash(restored) == hash(state)
    assert state.last_comfort_movement is not None
    assert state.last_comfort_movement.utcoffset() == timedelta(0)
    assert state.last_comfort_movement.hour == fold


@pytest.mark.parametrize(
    "value",
    [
        _command(Position(0), NOW, WishClass.FIRE),
        MemberCommand(LEFT, _command(Position(0), NOW, WishClass.FIRE)),
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
        lambda: _command(Position(0), NAIVE, WishClass.COMFORT),
        lambda: ManualOverrideDam(NAIVE, OverrideEndRule.NEXT_PART_OF_DAY),
        lambda: ManualOverrideDam(NOW, OverrideEndRule.FIXED_MINUTES, ends_at=NAIVE),
        lambda: PersonAtWindowDam(NAIVE),
        lambda: ProtectionEventState(
            "storm", status=ProtectionEventStatus.ACTIVE, active_since=NAIVE
        ),
        lambda: ProtectionEventState("storm", ended_at=NAIVE),
        lambda: ProtectionEventState("storm", released_at=NAIVE),
        lambda: ShadingEpisodeState(active_since=NAIVE),
        lambda: ShadingEpisodeState(rain_lock_until=NAIVE),
        lambda: SolarHeatingEpisodeState(NAIVE),
        lambda: ExternalRequest(Position(1), "scene", expires_at=NAIVE),
        lambda: HeldInput(value=True, seen_at=NAIVE),
        lambda: SimulatedState(last_comfort_movement=NAIVE),
        lambda: MemberState(
            LEFT,
            _command(Position(0), NOW, WishClass.COMFORT),
            command_attempts=1,
            last_attempt_at=NAIVE,
        ),
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
        ("protection_events", 1, "ended_at"),
        ("protection_events", 0, "released_at"),
        ("shading_episode", "active_since"),
        ("shading_episode", "rain_lock_until"),
        ("solar_heating_episode", "active_since"),
        ("external_request", "expires_at"),
        ("held_frost", "seen_at"),
        ("held_season", "seen_at"),
        ("members", 0, "last_own_command", "time"),
        ("members", 0, "last_attempt_at"),
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
        (("members", 0, "command_attempts"), -1, "must not be negative"),
        (("members", 0, "command_attempts"), 1.0, "expected an integer"),
        (("members", 0, "command_attempts"), 0, "belong together"),
        (("members", 0, "last_attempt_at"), None, "belong together"),
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


@pytest.mark.parametrize(
    ("path", "message"),
    [
        (("surprise",), "unknown key 'surprise'"),
        (("members", 0, "surprise"), "members: unknown key 'surprise'"),
        (
            ("members", 0, "last_own_command", "surprise"),
            "members: last_own_command: unknown key 'surprise'",
        ),
        (("members", 0, "last_observation", "surprise"), "last_observation: unknown"),
        (("manual_override", "surprise"), "manual_override: unknown key"),
        (("person_at_window", "surprise"), "person_at_window: unknown key"),
        (("protection_events", 0, "surprise"), "protection_events: unknown key"),
        (("shading_episode", "surprise"), "shading_episode: unknown key"),
        (("solar_heating_episode", "surprise"), "solar_heating_episode: unknown key"),
        (("external_request", "surprise"), "external_request: unknown key"),
        (("latched_day_types", 0, "surprise"), "latched_day_types: unknown key"),
        (("held_frost", "surprise"), "held_frost: unknown key"),
        (("simulated", "surprise"), "simulated: unknown key"),
        (("simulated", "commands", 0, "surprise"), "commands: unknown key"),
    ],
    ids=lambda value: ".".join(map(str, value)) if isinstance(value, tuple) else None,
)
def test_unknown_key_in_persisted_data_is_rejected(
    path: tuple[str | int, ...], message: str
) -> None:
    """A key the code does not know means code and data disagree: fail loudly."""
    with pytest.raises(ValueError, match=message):
        WindowState.from_data(_changed(path, 1))


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
    command = _command(Position(0), NOW, WishClass.COMFORT)
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


@pytest.mark.parametrize(
    "field",
    [
        "manual_override",
        "person_at_window",
        "shading_episode",
        "solar_heating_episode",
        "external_request",
        "held_frost",
        "held_season",
        "simulated",
    ],
)
def test_single_object_fields_of_the_window_state_check_their_type(field: str) -> None:
    """A wrong object is refused on construction, not later when it is saved."""
    wrong: Any = {"ends_at": NOW}
    with pytest.raises(TypeError, match=field):
        WindowState(**{field: wrong})


def test_protection_event_state_is_consistent() -> None:
    """Active: since when, not ended. Inactive: not active since; maybe ended at."""
    ended = ProtectionEventState("storm", ended_at=NOW)

    assert ended.status is ProtectionEventStatus.INACTIVE
    assert ended.ended_at == NOW
    assert ProtectionEventState("storm").ended_at is None
    with pytest.raises(ValueError, match="states since when"):
        ProtectionEventState("storm", status=ProtectionEventStatus.ACTIVE)
    with pytest.raises(ValueError, match="has not ended"):
        ProtectionEventState(
            "storm",
            status=ProtectionEventStatus.ACTIVE,
            active_since=NOW,
            ended_at=NOW,
        )


@pytest.mark.parametrize("active", [True, False], ids=["active", "inactive"])
@pytest.mark.parametrize("released", [True, False], ids=["released", "not released"])
@pytest.mark.parametrize("ended", [True, False], ids=["ended at", "no end"])
@pytest.mark.parametrize("zone", ["offset", "repeated hour"])
def test_end_and_release_of_a_protection_event_in_every_combination(
    *, active: bool, released: bool, ended: bool, zone: str
) -> None:
    """Only "active" and "ended at" exclude each other; the release is separate."""
    if zone == "offset":
        release, end = LOCAL, LOCAL + timedelta(hours=1)
    else:
        paris = ZoneInfo("Europe/Paris")
        release = datetime(2026, 10, 25, 2, 30, tzinfo=paris, fold=0)
        end = datetime(2026, 10, 25, 2, 30, tzinfo=paris, fold=1)
    # Compare in UTC: across zones, a time in the repeated hour never compares equal.
    release_utc, end_utc = release.astimezone(UTC), end.astimezone(UTC)
    arguments: dict[str, Any] = {
        "status": (
            ProtectionEventStatus.ACTIVE if active else ProtectionEventStatus.INACTIVE
        ),
        "active_since": NOW - timedelta(days=200) if active else None,
        "released_at": release if released else None,
        "ended_at": end if ended else None,
    }
    if active and ended:
        with pytest.raises(ValueError, match="has not ended"):
            ProtectionEventState("storm", **arguments)
        return

    event = ProtectionEventState("storm", **arguments)
    restored = ProtectionEventState.from_data(json.loads(json.dumps(event.to_data())))

    assert restored == event
    assert hash(restored) == hash(event)
    assert event.released is released
    assert "released" not in event.to_data()
    if released:
        assert event.released_at == release_utc
        assert event.released_at is not None
        assert event.released_at.utcoffset() == timedelta(0)
        assert event.return_clock_start == release_utc
    elif ended:
        assert event.return_clock_start == end_utc
    else:
        assert event.return_clock_start is None


def test_inactive_protection_event_is_not_active_since_a_time() -> None:
    """The start time belongs to an active event only."""
    with pytest.raises(ValueError, match="not active since"):
        ProtectionEventState("storm", active_since=NOW)


def test_released_is_a_read_only_view_of_the_release_time() -> None:
    """One source of truth: there is no flag that could contradict the time."""
    event: Any = ProtectionEventState(
        "storm",
        status=ProtectionEventStatus.ACTIVE,
        active_since=NOW,
        released_at=NOW,
    )
    construct: Any = ProtectionEventState

    assert event.released is True
    with pytest.raises(AttributeError):
        event.released = False
    with pytest.raises(TypeError):
        construct("storm", released=True)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (NAIVE_TEXT, "released_at: .*timezone-aware"),
        (True, "released_at: expected a string"),
        ("soon", "released_at"),
    ],
)
def test_malformed_release_time_in_persisted_data_is_rejected(
    value: object, message: str
) -> None:
    """The release time is read as strictly as every other timestamp."""
    with pytest.raises(ValueError, match=message):
        WindowState.from_data(_changed(("protection_events", 0, "released_at"), value))
    with pytest.raises(ValueError, match="unknown key 'released'"):
        WindowState.from_data(_changed(("protection_events", 0, "released"), True))


def test_command_backoff_is_persisted_as_facts() -> None:
    """Attempts and the time of the last one; never the time of the next retry."""
    bad: Any = 1.5
    fresh = MemberState(LEFT)
    command = _command(Position(0), NOW, WishClass.COMFORT)
    retried = MemberState(LEFT, command, command_attempts=3, last_attempt_at=LOCAL)

    assert (fresh.command_attempts, fresh.last_attempt_at) == (0, None)
    assert retried.last_attempt_at == LOCAL
    assert retried.last_attempt_at is not None
    assert retried.last_attempt_at.utcoffset() == timedelta(0)
    assert MemberState.from_data(retried.to_data()) == retried
    assert set(retried.to_data()) >= {"command_attempts", "last_attempt_at"}
    assert not [key for key in retried.to_data() if "retry" in key or "next" in key]
    with pytest.raises(ValueError, match="must not be negative"):
        MemberState(LEFT, command_attempts=-1)
    with pytest.raises(ValueError, match="belong together"):
        MemberState(LEFT, command, command_attempts=1)
    with pytest.raises(ValueError, match="without a last own command"):
        MemberState(LEFT, command_attempts=1, last_attempt_at=NOW)
    with pytest.raises(ValueError, match="belong together"):
        MemberState(LEFT, last_attempt_at=NOW)
    with pytest.raises(TypeError, match="must be an integer"):
        MemberState(LEFT, command_attempts=bad, last_attempt_at=NOW)
    with pytest.raises(TypeError, match="must be an integer"):
        MemberState(LEFT, command_attempts=True, last_attempt_at=NOW)


def test_own_command_carries_what_the_tracker_remembers() -> None:
    """Identifier, target, direction, time, wish class and the context."""
    bad: Any = 1
    command = OwnCommand(
        command_id="command-7",
        target=Position(100),
        direction=TravelDirection.UP,
        time=LOCAL,
        wish_class=WishClass.FIRE,
    )

    assert command.context_id is None
    assert command.direction is TravelDirection.UP
    assert command.time == LOCAL
    assert command.time.utcoffset() == timedelta(0)
    assert [value.value for value in TravelDirection] == ["up", "down"]
    with pytest.raises(ValueError, match="must not be empty"):
        _command(Position(0), NOW, WishClass.COMFORT, command_id="")
    with pytest.raises(TypeError, match="direction"):
        _command(Position(0), NOW, WishClass.COMFORT, direction="down")
    with pytest.raises(TypeError, match="context"):
        _command(Position(0), NOW, WishClass.COMFORT, context_id=bad)


def test_parts_of_the_state_check_their_types() -> None:
    """Wrong types are refused where the value is created."""
    bad: Any = 1.5
    command = _command(Position(0), NOW, WishClass.COMFORT)
    with pytest.raises(TypeError, match="target"):
        _command(bad, NOW, WishClass.COMFORT)
    with pytest.raises(TypeError, match="time of a command"):
        _command(Position(0), bad, WishClass.COMFORT)
    with pytest.raises(TypeError, match="wish class"):
        _command(Position(0), NOW, bad)
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
    with pytest.raises(TypeError, match="release"):
        ProtectionEventState("storm", released_at=bad)
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
