"""The situations of the two generic tests of the fault values. THE ONE PLACE.

Two rules hold for the fault value of every setting of a function that falls
back (``SettingDefinition.fault_value``), and ``tests/core/test_fault_values.py``
checks both over the registry, without knowing a single setting:

1. **A faulty value never leads to a decision that a valid value would have
   forbidden.** For a COMFORT wish, the decision with the fault value never
   sends more than the decision with a valid sample value.
2. **A fault on its own never restricts a PROTECTION wish more than the default
   does.** Cautious values may restrict comfort only: a hail opening must not
   stop short because of a data fault. The scope: a situation of the
   protection class does NOT switch on a setting by which a person lets the
   function restrict protection wishes (``frost_applies_to_protection``).
   Where a person validly did, the cautious values of the other settings
   reach protection wishes exactly as their valid restrictive values would;
   named tests in ``test_fault_values.py`` document that side, and a test
   there fails if a listed situation switches the setting on.

A test over the registry can only judge a setting in a world in which its
function restricts. Those worlds are listed here, in :data:`SITUATIONS`.

**A block that adds a setting of a function that falls back** (C08: the
contacts of lockout protection and of the ventilation floor) adds no test
code. It adds situations to :data:`SITUATIONS`: at least one per function, of
the comfort class if the function can restrict comfort wishes, and one of the
protection class if it can restrict protection wishes. Its layers, constraints
and gate rules reach the tests through :func:`arbiter`. The tests then cover
the new settings by themselves, and they fail with advice for a function that
has settings and no situation.

What a situation states:

- ``function``: the function that restricts in it;
- ``wish_class``: comfort or protection; which of the two tests uses it;
- ``settings``: the valid values (as ``WindowConfig`` carries them) that make
  the function restrict, and nothing else; every other setting has its default;
- ``sources``, ``position``, ``state``: the world.
"""

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Final

from custom_components.roller_shutter_suite.core.arbiter import Arbiter
from custom_components.roller_shutter_suite.core.engine import build_arbiter
from custom_components.roller_shutter_suite.core.model import (
    FULLY_OPEN,
    AnySourceValue,
    Decision,
    FunctionId,
    GateKind,
    HeldInput,
    Layer,
    Position,
    SourceValue,
    WindowConfig,
    WindowState,
    Wish,
    WishClass,
    WorldSnapshot,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.core.settings import (
    WINDOW_SETTINGS,
    PartialSettings,
    SettingDefinition,
    SettingFault,
    SettingKind,
    SettingsRegistry,
    resolve_window,
)
from tests.core.arbiter_kit import (
    NOW,
    STUB_LAYERS,
    day,
    observed,
    protection_layer,
    registered,
    snapshot,
    window,
)

FROST_SOURCE: Final = "sensor.example_outdoor_temperature"
_HERE: Final = "tests/core/fault_value_situations.py"


@dataclass(frozen=True)
class Situation:
    """A world in which a function restricts a wish of one class."""

    name: str
    function: FunctionId
    wish_class: WishClass
    sources: Mapping[str, AnySourceValue]
    position: int | None = 50
    """Where the one member stands; ``None``: the member is unavailable."""
    settings: Mapping[str, object] = field(default_factory=dict)
    state: WindowState = field(default_factory=WindowState)

    def world(self) -> WorldSnapshot:
        """Return the snapshot of the situation."""
        standing = "unavailable" if self.position is None else self.position
        return snapshot(
            sources=self.sources,
            observation=observed(left=standing),
            state=self.state,
        )


def _hail_or_storm(config: WindowConfig, world: WorldSnapshot) -> Wish:
    """Open fully while it hails; otherwise answer like the protection stub."""
    hail = world.sources.get("hail")
    if hail is not None and hail.has_value and hail.value is True:
        return Wish.target(Layer.PROTECTION, ReasonCode.PROTECTION_EVENT, FULLY_OPEN)
    return protection_layer(config, world)


def arbiter() -> Arbiter:
    """Return the arbiter of the situations: the built-in rules and the stub layers.

    A block whose constraint or gate rule is not built in adds it here.
    """
    layers = [entry for entry in STUB_LAYERS if entry.layer is not Layer.PROTECTION]
    return build_arbiter([*layers, registered(Layer.PROTECTION, _hail_or_storm)])


_FROST = {"frost_source": FROST_SOURCE}
_MOVED_RECENTLY = WindowState(last_comfort_movement=NOW - timedelta(minutes=7))


def _cold(temperature: float, **extra: AnySourceValue) -> dict[str, AnySourceValue]:
    return day(**{FROST_SOURCE: SourceValue.of(temperature)}, **extra)


_HAIL = SourceValue.of(True)

SITUATIONS: Final = (
    # --- Frost protection, comfort: the morning opening ---------------------------
    Situation(
        "frost just below the threshold, a wish to open",
        FunctionId.FROST,
        WishClass.COMFORT,
        _cold(-0.1),
        settings=_FROST,
    ),
    Situation(
        "inside the hysteresis band while frost is held, a wish to open",
        FunctionId.FROST,
        WishClass.COMFORT,
        _cold(0.5),
        settings=_FROST,
        state=WindowState(held_frost=HeldInput(True, NOW - timedelta(hours=1))),
    ),
    Situation(
        "frost and a closed shutter, a wish to open",
        FunctionId.FROST,
        WishClass.COMFORT,
        _cold(-5.0),
        position=0,
        settings=_FROST,
    ),
    # --- Frost protection, protection: a hail opening ------------------------------
    Situation(
        "frost, hail opens a half open shutter",
        FunctionId.FROST,
        WishClass.PROTECTION,
        _cold(-5.0, hail=_HAIL),
        settings=_FROST,
    ),
    Situation(
        "frost, hail opens a closed shutter",
        FunctionId.FROST,
        WishClass.PROTECTION,
        _cold(-5.0, hail=_HAIL),
        position=0,
        settings=_FROST,
    ),
    Situation(
        "no frost source anywhere, hail opens a closed shutter",
        FunctionId.FROST,
        WishClass.PROTECTION,
        day(hail=_HAIL),
        position=0,
    ),
    # --- Motor protection ----------------------------------------------------------
    Situation(
        "a comfort change below the minimum change",
        FunctionId.MOTOR_PROTECTION,
        WishClass.COMFORT,
        day(shading_position=SourceValue.of(53)),
    ),
    Situation(
        "a comfort wish that is not fresh, inside the minimum interval",
        FunctionId.MOTOR_PROTECTION,
        WishClass.COMFORT,
        day(),
        state=_MOVED_RECENTLY,
    ),
    Situation(
        "hail opens by a small change right after a comfort movement",
        FunctionId.MOTOR_PROTECTION,
        WishClass.PROTECTION,
        day(hail=_HAIL),
        position=96,
        state=_MOVED_RECENTLY,
    ),
    # --- Command verification: the bound of a deferral without a known end --------
    Situation(
        "no member is available, a comfort wish",
        FunctionId.COMMAND_VERIFICATION,
        WishClass.COMFORT,
        day(),
        position=None,
    ),
    Situation(
        "no member is available, hail",
        FunctionId.COMMAND_VERIFICATION,
        WishClass.PROTECTION,
        day(hail=_HAIL),
        position=None,
    ),
)
"""Every world in which a function with settings that fall back restricts."""


# --- What the two tests compare -----------------------------------------------------


def sent(decision: Decision) -> dict[str, Position]:
    """Return what the decision sends, per member; empty if it holds back."""
    if decision.gate is None or decision.gate.kind is not GateKind.SEND:
        return {}
    return {
        target.member_id: target.position
        for target in decision.targets
        if target.position is not None
    }


def sends_more(one: Decision, other: Decision, world: WorldSnapshot) -> bool:
    """Return whether ``one`` moves a member that ``other`` does not, or further.

    "Further" is judged from where the member stands, in the same direction.
    A movement in the other direction counts as more: the two decisions are
    about the same wish, so it cannot be a smaller step of the same movement.
    """
    stands = {
        member.member_id: member.observation.position
        for member in world.observation.members
    }
    theirs = sent(other)
    for member_id, target in sent(one).items():
        if member_id not in theirs:
            return True
        here = stands.get(member_id)
        if here is None:
            if target != theirs[member_id]:
                return True
            continue
        mine, yours = target.value - here.value, theirs[member_id].value - here.value
        if mine * yours < 0 or abs(mine) > abs(yours):
            return True
    return False


def valid_samples(
    definition: SettingDefinition[Any], situation: Situation
) -> list[object]:
    """Return the valid values a faulty value is compared with, by kind of setting.

    Always the default and what the situation sets. Both positions of a
    switch. For an optional reference "none" and the source of the situation.
    A number has no most restrictive value, so its samples end there: the
    test proves "never less restrictive than the default", not "than any
    number somebody could have meant".
    """
    samples: list[object] = [definition.default]
    if definition.key in situation.settings:
        samples.append(situation.settings[definition.key])
    if definition.kind is SettingKind.BOOLEAN:
        samples += [False, True]
    if definition.kind is SettingKind.OPTIONAL_REFERENCE:
        samples.append(None)
    return samples


FAULT_CASES: Final = ("a faulty value on the only level", "an unreadable house")


def decide(  # noqa: PLR0913 - the registry, the situation and what is stored
    registry: SettingsRegistry,
    situation: Situation,
    key: str,
    *,
    value: object = None,
    fault_case: str | None = None,
    inherit: bool = False,
) -> Decision:
    """Resolve the window of a situation and decide.

    ``value`` is a valid value of the setting on the window. ``fault_case``
    makes the setting faulty instead: its stored value cannot be read, or the
    house level is unreadable as a whole while no level sets the key.
    ``inherit`` leaves the key to its default.
    """
    own = {name: item for name, item in situation.settings.items() if name != key}
    house = PartialSettings()
    if fault_case == FAULT_CASES[0]:
        window_settings = PartialSettings(own, (SettingFault(key, "cannot be read"),))
    elif fault_case == FAULT_CASES[1]:
        window_settings, house = PartialSettings(own), PartialSettings(unreadable=True)
    elif inherit:
        window_settings = PartialSettings(own)
    else:
        window_settings = PartialSettings({**own, key: value})
    resolution = resolve_window(
        window_id="window.example",
        members=window().members,
        global_settings=house,
        window_settings=window_settings,
        registry=registry,
    )
    assert resolution.config is not None, resolution.settings.faults
    # An unreadable level also pauses every function that creates comfort
    # wishes. That is a different rule with its own tests, and it would hide
    # what is judged here: without a wish nothing is sent, whatever the
    # fault values are. So the wishes are kept and the restriction is judged.
    config = dataclasses.replace(resolution.config, disabled_functions=frozenset())
    return arbiter().recompute(config, situation.world())


def _cautious(registry: SettingsRegistry) -> list[SettingDefinition[Any]]:
    return [entry for entry in registry.definitions if entry.falls_back_cautiously]


def missing_situations(registry: SettingsRegistry = WINDOW_SETTINGS) -> list[str]:
    """Name the functions with settings that fall back and no situation, with advice."""
    covered = {situation.function for situation in SITUATIONS}
    return [
        f"The function {function.value!r} has settings that fall back "
        f"({', '.join(e.key for e in _cautious(registry) if e.function is function)}) "
        f"and no situation in which it restricts. Add one to SITUATIONS in {_HERE}: "
        f"a comfort wish it limits or holds back, and a protection wish if it can "
        f"restrict one. Without a situation no test can see whether the fault "
        f"values are cautious."
        for function in sorted(
            {entry.function for entry in _cautious(registry) if entry.function},
            key=list(FunctionId).index,
        )
        if function not in covered
    ]


def loosened_by_a_fault(registry: SettingsRegistry = WINDOW_SETTINGS) -> list[str]:
    """Rule 1: name every comfort situation in which a fault sends more than a valid value."""
    findings: list[str] = []
    for definition in _cautious(registry):
        for situation in SITUATIONS:
            if (
                situation.function is not definition.function
                or situation.wish_class is not WishClass.COMFORT
            ):
                continue
            for fault_case in FAULT_CASES:
                faulty = decide(
                    registry, situation, definition.key, fault_case=fault_case
                )
                for sample in valid_samples(definition, situation):
                    valid = decide(registry, situation, definition.key, value=sample)
                    if sends_more(faulty, valid, situation.world()):
                        findings.append(
                            f"{definition.key}: with {fault_case} the window sends "
                            f"{_shown(faulty)} in the situation {situation.name!r}; "
                            f"the valid value {sample!r} allows only "
                            f"{_shown(valid)}. The fault value "
                            f"{definition.fault_value!r} is less restrictive than a "
                            f"valid value; state a cautious one in WINDOW_SETTINGS."
                        )
    return findings


def protection_restricted_by_a_fault(
    registry: SettingsRegistry = WINDOW_SETTINGS,
) -> list[str]:
    """Rule 2: name every protection situation in which a fault sends less than the default.

    Every setting is judged in every protection situation, whatever its
    function: a fault value must not reach a protection wish by any path.
    """
    findings: list[str] = []
    for definition in _cautious(registry):
        for situation in SITUATIONS:
            if situation.wish_class is not WishClass.PROTECTION:
                continue
            default = decide(registry, situation, definition.key, inherit=True)
            for fault_case in FAULT_CASES:
                faulty = decide(
                    registry, situation, definition.key, fault_case=fault_case
                )
                if sends_more(default, faulty, situation.world()):
                    findings.append(
                        f"{definition.key}: with {fault_case} the protection wish of "
                        f"the situation {situation.name!r} sends {_shown(faulty)}; "
                        f"with the default {definition.default!r} it sends "
                        f"{_shown(default)}. A fault value never restricts a "
                        f"protection wish more than the default does; the fault "
                        f"value {definition.fault_value!r} does."
                    )
    return findings


def tells_apart(definition: SettingDefinition[Any]) -> bool:
    """Return whether any situation of the function gives two samples two decisions."""
    for situation in SITUATIONS:
        if situation.function is not definition.function:
            continue
        outcomes = {
            tuple(
                sorted(
                    sent(
                        decide(WINDOW_SETTINGS, situation, definition.key, value=sample)
                    ).items()
                )
            )
            for sample in valid_samples(definition, situation)
        }
        if len(outcomes) > 1:
            return True
    return False


def _shown(decision: Decision) -> str:
    moved = sent(decision)
    if not moved:
        return "nothing"
    return ", ".join(
        f"{member} to {position.value}" for member, position in moved.items()
    )


def with_fault_value(key: str, fault_value: object) -> SettingsRegistry:
    """Return the registry of the window with one fault value changed: a mutation."""
    return SettingsRegistry(
        tuple(
            dataclasses.replace(entry, fault_value=fault_value)
            if entry.key == key
            else entry
            for entry in WINDOW_SETTINGS.definitions
        )
    )
