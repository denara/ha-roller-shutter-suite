"""The member level: what a member states itself, inheritance from the window, faults."""

import dataclasses
from datetime import timedelta
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core import settings as settings_module
from custom_components.roller_shutter_suite.core.geometry import (
    ShadedElement,
    compute_shading,
)
from custom_components.roller_shutter_suite.core.model import (
    MEMBER_MEASUREMENT_FIELDS,
    NO_CALIBRATION,
    NO_MEASUREMENTS,
    CapabilityProfile,
    FaultBehavior,
    FunctionId,
    GlassCalibration,
    MemberConfig,
    MemberGlass,
    MemberGlassError,
    MemberMeasurements,
    Position,
    ShadingGeometrySettings,
    SunPosition,
    WindowConfig,
    member_glass_for,
)
from custom_components.roller_shutter_suite.core.settings import (
    MEMBER_SETTINGS,
    SETTINGS_KEY,
    WINDOW_SETTINGS,
    Capability,
    CapabilityRequirement,
    FaultAction,
    GroupLevel,
    Level,
    MemberSettingsRegistry,
    PartialSettings,
    ReportedFault,
    ResolvedSettings,
    ResolvedValue,
    SettingDefinition,
    SettingKind,
    SettingProblem,
    SettingsRegistry,
    WindowResolution,
    resolve_window,
    settings_from_stored,
)

UPPER = "cover.example_upper"
LOWER = "cover.example_lower"
HUGE = 10**400
ROOF_DEPTH = 1.5


def _member(member_id: str, **changes: Any) -> MemberConfig:
    profile = CapabilityProfile(
        supports_open_close=True,
        supports_set_position=True,
        supports_stop=True,
        reports_position=True,
        travel_time_up=timedelta(seconds=24),
        travel_time_down=timedelta(seconds=21),
    )
    return MemberConfig(member_id, profile, **changes)


MEMBERS = (_member(UPPER), _member(LOWER))

# A roof element of two rows, and values of functions that fall back.
WINDOW = {
    "shading_use_measurements": True,
    "shading_orientation_known": True,
    "shading_orientation": 180,
    "shading_element_bottom": 1.0,
    "shading_element_height": 1.7,
    "shading_depth": ROOF_DEPTH,
    "shading_pitch": 40,
    "frost_source": "sensor.example_outdoor_temperature",
    "frost_position": 70,
    "motor_min_change": 8,
}
ROWS = {
    UPPER: {"glass_height": 1.0},
    LOWER: {"glass_height": 0.6, "top_offset": 1.1},
}


def _resolve(
    members: dict[str, Any],
    window: dict[str, Any] | None = None,
    group: dict[str, Any] | None = None,
) -> WindowResolution:
    return resolve_window(
        window_id="window_example",
        members=MEMBERS,
        global_settings=PartialSettings(),
        window_settings=settings_from_stored(
            WINDOW if window is None else window, WINDOW_SETTINGS
        ),
        group=None
        if group is None
        else GroupLevel("group_example", settings_from_stored(group, WINDOW_SETTINGS)),
        member_settings={
            member_id: settings_from_stored(data, MEMBER_SETTINGS.registry)
            for member_id, data in members.items()
        },
    )


def _config(resolution: WindowResolution) -> WindowConfig:
    assert resolution.config is not None
    return resolution.config


def _protection_is_untouched(resolution: WindowResolution) -> None:
    """Assert that whatever falls back kept the values the window set."""
    config = _config(resolution)
    assert config.frost_source == "sensor.example_outdoor_temperature"
    assert config.frost_position == Position(70)
    assert config.motor_min_change == 8  # noqa: PLR2004 - the value of WINDOW
    for function in config.disabled_functions:
        assert function.fault_behavior is FaultBehavior.PAUSE
    for key in ("frost_source", "frost_position", "motor_min_change"):
        assert resolution.settings.values[key].level is Level.WINDOW
    assert not [
        fault
        for fault in resolution.settings.faults
        if fault.action is FaultAction.FELL_BACK
    ]


# --- The values of the model ---------------------------------------------------------------


def test_a_member_states_nothing_by_default() -> None:
    """``None`` means "not stated"; it is no value of any measurement."""
    assert _member(UPPER).measurements == NO_MEASUREMENTS
    assert NO_MEASUREMENTS.stated == ()
    assert MemberMeasurements(top_offset=0.0).stated == ("top_offset",)
    assert MemberMeasurements(
        glass_height=0.6, calibration_seat=Position(8)
    ).stated == ("glass_height", "calibration_seat")
    assert tuple(field.name for field in dataclasses.fields(MemberMeasurements)) == (
        MEMBER_MEASUREMENT_FIELDS
    )


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("glass_height", 0.0, ValueError),
        ("glass_height", -0.5, ValueError),
        ("glass_height", 100.5, ValueError),
        ("glass_height", float("nan"), ValueError),
        ("glass_height", HUGE, ValueError),
        ("glass_height", "0.6", TypeError),
        ("top_offset", -0.1, ValueError),
        ("top_offset", True, TypeError),
        ("calibration_seat", 8, TypeError),
        ("calibration_glass_top", 92.0, TypeError),
    ],
)
def test_a_stated_measurement_that_cannot_work_is_refused_and_named(
    field: str, value: Any, error: type[Exception]
) -> None:
    """Each value is checked on its own, with the field in the message."""
    arguments: dict[str, Any] = {field: value}

    with pytest.raises(error, match=field):
        MemberMeasurements(**arguments)
    with pytest.raises(TypeError, match="measurements"):
        _member(UPPER, measurements=arguments)


def test_members_inherit_the_measurements_of_the_window_unless_they_state_their_own() -> (
    None
):
    """Glass as high as the element, offset 0, the calibration of the window."""
    window = ShadingGeometrySettings(
        element_height=1.7,
        calibration_seat=Position(10),
        calibration_glass_top=Position(90),
    )

    inherited = member_glass_for(window, UPPER, NO_MEASUREMENTS)
    own = member_glass_for(
        window,
        LOWER,
        MemberMeasurements(
            glass_height=0.6, top_offset=1.1, calibration_glass_top=Position(95)
        ),
    )

    assert inherited == MemberGlass(
        UPPER, 1.7, 0.0, GlassCalibration(Position(10), Position(90))
    )
    assert own == MemberGlass(
        LOWER, 0.6, 1.1, GlassCalibration(Position(10), Position(95))
    )


@pytest.mark.parametrize(
    ("stated", "fields"),
    [
        ({"glass_height": 2.0}, ("glass_height",)),
        ({"top_offset": 0.2}, ("top_offset",)),
        ({"glass_height": 0.7, "top_offset": 1.1}, ("glass_height", "top_offset")),
        ({"calibration_seat": Position(95)}, ("calibration_seat",)),
        ({"calibration_glass_top": Position(5)}, ("calibration_glass_top",)),
        (
            {"calibration_seat": Position(60), "calibration_glass_top": Position(65)},
            ("calibration_seat", "calibration_glass_top"),
        ),
    ],
)
def test_what_does_not_fit_together_names_the_member_and_what_it_states(
    stated: dict[str, Any], fields: tuple[str, ...]
) -> None:
    """The values of the window are fine among themselves; the member's are named."""
    window = ShadingGeometrySettings(element_height=1.7)

    with pytest.raises(MemberGlassError, match=LOWER) as error:
        member_glass_for(window, LOWER, MemberMeasurements(**stated))

    assert error.value.fields == fields
    assert error.value.member_id == LOWER
    with pytest.raises(ValueError, match=LOWER):
        WindowConfig(
            "window_example",
            (
                _member(UPPER),
                _member(LOWER, measurements=MemberMeasurements(**stated)),
            ),
            shading_element_height=1.7,
        )


def test_a_rule_over_several_measurements_names_its_fields() -> None:
    """As a rule over several settings names its keys."""
    with pytest.raises(ValueError, match="names its fields"):
        MemberGlassError("does not fit", LOWER, ())


def test_the_window_offers_the_glass_that_applies_to_every_member() -> None:
    """What the geometry computes with, in the order of the members."""
    window = WindowConfig(
        "window_example",
        (
            _member(UPPER, measurements=MemberMeasurements(glass_height=1.0)),
            _member(
                LOWER, measurements=MemberMeasurements(glass_height=0.6, top_offset=1.1)
            ),
        ),
        shading_element_height=1.7,
    )

    assert window.member_glass == (
        MemberGlass(UPPER, 1.0),
        MemberGlass(LOWER, 0.6, 1.1),
    )
    assert ShadedElement(window.geometry, window.member_glass)


# --- The registry of the member level --------------------------------------------------------


def test_the_member_settings_are_the_four_measurements_of_shading() -> None:
    """Kind, function, reader, and the window setting each inherits from."""
    window_defaults = {
        entry.key: entry.default for entry in WINDOW_SETTINGS.definitions
    }
    expected = {
        "glass_height": ("shading_element_height", 0.6, 0.6),
        "top_offset": (None, 1, 1.0),
        "calibration_seat": ("shading_calibration_seat", 8, Position(8)),
        "calibration_glass_top": ("shading_calibration_glass_top", 92, Position(92)),
    }

    assert MEMBER_SETTINGS.registry.keys == MEMBER_MEASUREMENT_FIELDS
    assert dict(MEMBER_SETTINGS.inherits_from) == {
        key: window_key for key, (window_key, _, _) in expected.items()
    }
    assert MEMBER_SETTINGS.pausable_functions == (FunctionId.SHADING,)
    for definition in MEMBER_SETTINGS.registry.definitions:
        window_key, stored, value = expected[definition.key]
        assert definition.kind is SettingKind.NUMBER
        assert definition.function is FunctionId.SHADING
        assert definition.requires is None
        assert definition.parse(stored) == value
        assert type(definition.parse(stored)) is type(value)
        assert definition.default == (
            0.0 if window_key is None else window_defaults[window_key]
        )


def _definition(**changes: Any) -> SettingDefinition[Any]:
    arguments: dict[str, Any] = {
        "key": "example",
        "kind": SettingKind.NUMBER,
        "function": FunctionId.SHADING,
        "default": 0,
        "parse": int,
    }
    return SettingDefinition(**(arguments | changes))


@pytest.mark.parametrize(
    "function",
    [
        function
        for function in FunctionId
        if function.fault_behavior is FaultBehavior.FALL_BACK
    ],
)
def test_a_member_setting_of_a_function_that_falls_back_is_refused(
    function: FunctionId,
) -> None:
    """Until somebody defines what a member-level fault of such a function means.

    A faulty member value pauses; a function that falls back is never paused
    and would need a cautious value per member. So the fault values of
    decision 15 are not needed on this level, and the registry keeps it so.
    """
    # An entry of such a function states a fault value, so it constructs.
    registry = SettingsRegistry((_definition(function=function, fault_value=0),))

    with pytest.raises(ValueError, match="falls back"):
        MemberSettingsRegistry(registry, {"example": None})


def test_every_function_with_member_settings_pauses_on_a_fault() -> None:
    """The same statement about the registry that ships."""
    assert {
        definition.fault_behavior for definition in MEMBER_SETTINGS.registry.definitions
    } == {FaultBehavior.PAUSE}


def test_a_member_registry_that_cannot_work_is_refused() -> None:
    """No function, a capability requirement, a mapping that does not match."""
    without_function = _definition(function=None, inheritable=False)
    masked = _definition(
        requires=CapabilityRequirement(Capability.SUPPORTS_SET_POSITION, 0)
    )

    with pytest.raises(ValueError, match="falls back"):
        MemberSettingsRegistry(SettingsRegistry((without_function,)), {"example": None})
    with pytest.raises(ValueError, match="capability"):
        MemberSettingsRegistry(SettingsRegistry((masked,)), {"example": None})
    with pytest.raises(ValueError, match="inherits from"):
        MemberSettingsRegistry(SettingsRegistry((_definition(),)), {})
    with pytest.raises(ValueError, match="inherits from"):
        MemberSettingsRegistry(
            SettingsRegistry((_definition(),)), {"example": None, "other": None}
        )
    with pytest.raises(TypeError, match="registry"):
        MemberSettingsRegistry((_definition(),), {"example": None})  # type: ignore[arg-type]


def test_every_inherited_window_key_exists_with_the_same_reader() -> None:
    """A member value and the window value it replaces are read the same way."""
    window = {entry.key: entry for entry in WINDOW_SETTINGS.definitions}
    for definition in MEMBER_SETTINGS.registry.definitions:
        window_key = MEMBER_SETTINGS.inherits_from[definition.key]
        if window_key is not None:
            assert window[window_key].parse is definition.parse
            assert window[window_key].function is definition.function


# --- Through the resolver: inheritance and provenance -------------------------------------------


def test_without_member_settings_every_member_inherits_the_window() -> None:
    """Also when the caller passes none at all; equal members get equal positions."""
    resolution = resolve_window(
        window_id="window_example",
        members=MEMBERS,
        global_settings=PartialSettings(),
        window_settings=settings_from_stored(WINDOW, WINDOW_SETTINGS),
    )
    config = _config(resolution)

    assert resolution.settings.faults == ()
    assert config.member_glass == (MemberGlass(UPPER, 1.7), MemberGlass(LOWER, 1.7))
    assert {member.measurements for member in config.members} == {NO_MEASUREMENTS}
    for member_id in (UPPER, LOWER):
        values = resolution.settings.member_values[member_id]
        assert tuple(values) == MEMBER_MEASUREMENT_FIELDS
        assert values["glass_height"].level is Level.WINDOW
        assert values["top_offset"].level is Level.BUILT_IN
        assert values["calibration_seat"].level is Level.BUILT_IN
    result = compute_shading(
        SunPosition(180.0, 60.0), ShadedElement(config.geometry, config.member_glass)
    )
    assert len({member.position for member in result.members}) == 1


def test_members_state_their_own_and_the_roof_example_comes_out() -> None:
    """From stored data of the window and of two members to the positions."""
    resolution = _resolve(ROWS)
    config = _config(resolution)

    assert resolution.settings.faults == ()
    assert config.disabled_functions == frozenset()
    assert config.member_glass == (
        MemberGlass(UPPER, 1.0),
        MemberGlass(LOWER, 0.6, 1.1),
    )
    result = compute_shading(
        SunPosition(180.0, 45.0), ShadedElement(config.geometry, config.member_glass)
    )
    assert [member.position.value for member in result.members] == [0, 59]
    _protection_is_untouched(resolution)


def test_every_member_value_says_where_it_came_from() -> None:
    """The member itself, or the level that gave the window's value."""
    resolution = _resolve(
        {UPPER: {"calibration_glass_top": 92}, LOWER: {}},
        window={"shading_element_height": 1.3},
        group={"shading_calibration_seat": 8},
    )
    upper = resolution.settings.member_values[UPPER]
    lower = resolution.settings.member_values[LOWER]

    assert resolution.settings.faults == ()
    assert upper["calibration_glass_top"] == ResolvedValue(
        "calibration_glass_top",
        Position(92),
        Position(92),
        Level.MEMBER,
        member_id=UPPER,
    )
    assert lower["calibration_glass_top"].level is Level.BUILT_IN
    assert lower["calibration_glass_top"].member_id is None
    assert upper["calibration_seat"] == ResolvedValue(
        "calibration_seat", Position(8), Position(8), Level.GROUP, "group_example"
    )
    assert upper["glass_height"].value == lower["glass_height"].value
    assert upper["glass_height"].level is Level.WINDOW
    with pytest.raises(TypeError):
        resolution.settings.member_values[UPPER]["glass_height"] = upper["top_offset"]  # type: ignore[index]


def test_the_existing_constructions_keep_working() -> None:
    """The member level is additive: no member, no member identifier."""
    fault = ReportedFault(
        "frost_position",
        Level.GROUP,
        SettingProblem.INVALID,
        "x",
        FaultAction.FELL_BACK,
    )
    value = ResolvedValue("frost_position", 1, 1, Level.WINDOW)

    assert fault.member_id is None
    assert value.member_id is None
    assert ResolvedSettings({}).member_values == {}
    assert Level.MEMBER.value == "member"
    assert list(Level)[-1] is Level.MEMBER


# --- Through the resolver: faults ---------------------------------------------------------------

FAULTY = [
    ({"glass_height": "tall"}, "glass_height", SettingProblem.UNREADABLE),
    ({"glass_height": None}, "glass_height", SettingProblem.UNREADABLE),
    ({"top_offset": HUGE}, "top_offset", SettingProblem.UNREADABLE),
    (
        {"calibration_seat": "__none__"},
        "calibration_seat",
        (SettingProblem.NONE_NOT_ALLOWED),
    ),
    ({"calibration_seat": 101}, "calibration_seat", SettingProblem.UNREADABLE),
    ({"glass_height": 0}, "glass_height", SettingProblem.INVALID),
    ({"top_offset": -0.5}, "top_offset", SettingProblem.INVALID),
]


@pytest.mark.parametrize(("stored", "key", "problem"), FAULTY)
def test_a_faulty_member_value_pauses_shading_for_the_whole_window(
    stored: dict[str, Any], key: str, problem: SettingProblem
) -> None:
    """No fall-back to the window's value; level, member and key are reported.

    The other member's sound values are not applied either: nobody acts on
    measurements while the function is paused. Protection keeps its values.
    """
    resolution = _resolve({UPPER: {"glass_height": 1.0}, LOWER: stored})
    config = _config(resolution)

    assert resolution.settings.faults == (
        ReportedFault(
            key,
            Level.MEMBER,
            problem,
            resolution.settings.faults[0].detail,
            FaultAction.FUNCTIONS_DISABLED,
            (FunctionId.SHADING,),
            member_id=LOWER,
        ),
    )
    assert config.disabled_functions == frozenset({FunctionId.SHADING})
    assert resolution.settings.disabled_functions == config.disabled_functions
    assert {member.measurements for member in config.members} == {NO_MEASUREMENTS}
    assert resolution.settings.member_values[UPPER]["glass_height"].level is (
        Level.WINDOW
    )
    _protection_is_untouched(resolution)


@pytest.mark.parametrize(
    ("stored", "keys"),
    [
        ({"glass_height": 0.7, "top_offset": 1.1}, {"glass_height", "top_offset"}),
        ({"top_offset": 1.1}, {"top_offset"}),
        ({"glass_height": 1.8}, {"glass_height"}),
        ({"calibration_seat": 95}, {"calibration_seat"}),
        (
            {"calibration_seat": 50, "calibration_glass_top": 55, "glass_height": 1.0},
            {"calibration_seat", "calibration_glass_top"},
        ),
    ],
)
def test_a_member_value_refused_together_with_the_windows_values_pauses_shading(
    stored: dict[str, Any], keys: set[str]
) -> None:
    """Each value is fine on its own; together with the window they do not fit."""
    resolution = _resolve({LOWER: stored})
    config = _config(resolution)
    faults = resolution.settings.faults

    assert {fault.key for fault in faults} == keys
    assert {fault.problem for fault in faults} == {SettingProblem.COMBINATION}
    assert {(fault.level, fault.member_id) for fault in faults} == {
        (Level.MEMBER, LOWER)
    }
    assert {fault.action for fault in faults} == {FaultAction.FUNCTIONS_DISABLED}
    assert config.disabled_functions == frozenset({FunctionId.SHADING})
    assert config.member_glass == (MemberGlass(UPPER, 1.7), MemberGlass(LOWER, 1.7))
    _protection_is_untouched(resolution)


def test_an_unknown_member_key_is_reported_and_ignored() -> None:
    """A newer version may have written it; nothing is paused."""
    resolution = _resolve({LOWER: {"glass_height": 0.6, "top_offset": 1.1, "tint": 3}})
    in_code = resolve_window(
        window_id="window_example",
        members=MEMBERS,
        global_settings=PartialSettings(),
        window_settings=settings_from_stored(WINDOW, WINDOW_SETTINGS),
        member_settings={LOWER: PartialSettings({"tint": 3, "glass_height": 1.2})},
    )

    for result in (resolution, in_code):
        assert [
            (fault.key, fault.level, fault.member_id, fault.problem, fault.action)
            for fault in result.settings.faults
        ] == [
            (
                "tint",
                Level.MEMBER,
                LOWER,
                SettingProblem.UNKNOWN_SETTING,
                FaultAction.IGNORED,
            )
        ]
        assert _config(result).disabled_functions == frozenset()
    assert _config(resolution).member_glass[1] == MemberGlass(LOWER, 0.6, 1.1)
    assert _config(in_code).member_glass[1] == MemberGlass(LOWER, 1.2)


def test_member_settings_that_are_unreadable_as_a_whole_pause_shading() -> None:
    """For the window, because nobody knows what the member would have stated."""
    resolution = _resolve(
        {UPPER: {"glass_height": 1.0}, LOWER: ["not", "a", "mapping"]}
    )

    assert [
        (fault.key, fault.level, fault.member_id, fault.problem, fault.action)
        for fault in resolution.settings.faults
    ] == [
        (
            SETTINGS_KEY,
            Level.MEMBER,
            LOWER,
            SettingProblem.LEVEL_UNREADABLE,
            FaultAction.FUNCTIONS_DISABLED,
        )
    ]
    assert _config(resolution).disabled_functions == frozenset({FunctionId.SHADING})
    _protection_is_untouched(resolution)


def test_settings_of_a_member_the_window_does_not_have_are_reported_and_ignored() -> (
    None
):
    """A cover that was removed from the window leaves them behind."""
    resolution = _resolve({"cover.example_removed": {"glass_height": 0.5}, **ROWS})

    assert [
        (fault.key, fault.member_id, fault.problem, fault.action)
        for fault in resolution.settings.faults
    ] == [
        (
            SETTINGS_KEY,
            "cover.example_removed",
            SettingProblem.UNKNOWN_SETTING,
            FaultAction.IGNORED,
        )
    ]
    assert _config(resolution).disabled_functions == frozenset()
    assert tuple(resolution.settings.member_values) == (UPPER, LOWER)


def test_while_the_window_levels_pause_shading_members_are_not_judged_against_stand_ins() -> (
    None
):
    """The element height is unreadable, so the default stands in for it.

    The lower row would not fit into the default. That is no fault of the
    member, and it is not reported as one. A value of the member that is
    faulty on its own still is.
    """
    window = WINDOW | {"shading_element_height": "high"}
    sound = _resolve(ROWS, window=window)
    faulty = _resolve(ROWS | {UPPER: {"glass_height": -1}}, window=window)

    assert [(fault.key, fault.level) for fault in sound.settings.faults] == [
        ("shading_element_height", Level.WINDOW)
    ]
    assert _config(sound).disabled_functions == frozenset({FunctionId.SHADING})
    assert {member.measurements for member in _config(sound).members} == {
        NO_MEASUREMENTS
    }
    assert [(fault.key, fault.level) for fault in faulty.settings.faults] == [
        ("shading_element_height", Level.WINDOW),
        ("glass_height", Level.MEMBER),
    ]
    _protection_is_untouched(faulty)


HOSTILE: list[Any] = [
    None,
    True,
    -1,
    HUGE,
    float("nan"),
    float("inf"),
    "",
    "__none__",
    "x" * 1000,
    [],
    [[]],
    {},
    {"glass_height": HUGE},
]


@pytest.mark.parametrize("value", HOSTILE, ids=lambda value: repr(value)[:20])
def test_no_hostile_member_value_costs_the_window_anything_but_shading(
    value: Any,
) -> None:
    """Stored and handed in as a typed value, for every key and as a whole."""
    attempts: list[dict[str, PartialSettings]] = [
        {LOWER: settings_from_stored(value, MEMBER_SETTINGS.registry)}
    ]
    for key in (*MEMBER_MEASUREMENT_FIELDS, "unheard_of"):
        attempts.append(
            {LOWER: settings_from_stored({key: value}, MEMBER_SETTINGS.registry)}
        )
        attempts.append({LOWER: PartialSettings({key: value})})
    for member_settings in attempts:
        resolution = resolve_window(
            window_id="window_example",
            members=MEMBERS,
            global_settings=PartialSettings(),
            window_settings=settings_from_stored(WINDOW, WINDOW_SETTINGS),
            member_settings=member_settings,
        )

        assert _config(resolution).disabled_functions <= {FunctionId.SHADING}
        _protection_is_untouched(resolution)


def test_member_settings_of_the_wrong_type_are_a_programming_error() -> None:
    """The caller hands in partial settings, one per member."""
    with pytest.raises(TypeError, match="settings of a member"):
        resolve_window(
            window_id="window_example",
            members=MEMBERS,
            global_settings=PartialSettings(),
            window_settings=PartialSettings(),
            member_settings={LOWER: {"glass_height": 0.6}},  # type: ignore[dict-item]
        )


def test_no_calibration_is_what_a_member_of_a_new_window_has() -> None:
    """The defaults all the way down."""
    resolution = _resolve({}, window={})

    assert {glass.calibration for glass in _config(resolution).member_glass} == {
        NO_CALIBRATION
    }


def test_a_withheld_configuration_stays_withheld(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without a window configuration there is nothing a member could inherit from."""
    withheld = ResolvedSettings({})
    monkeypatch.setattr(settings_module, "_resolve", lambda *_, **__: (withheld, None))

    resolution = _resolve(ROWS)

    assert resolution.config is None
    assert resolution.settings is withheld
