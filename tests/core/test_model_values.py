"""Position and source value: construction, validation, equality."""

import dataclasses
from typing import Any

import pytest

from custom_components.roller_shutter_suite.core.model import (
    FULLY_CLOSED,
    FULLY_OPEN,
    MissingSourceValueError,
    Position,
    SourceState,
    SourceValue,
)

# --- Position ---------------------------------------------------------------


@pytest.mark.parametrize("value", [0, 1, 50, 99, 100])
def test_position_accepts_0_to_100(value: int) -> None:
    """Every integer from fully closed to fully open is a position."""
    assert Position(value).value == value


@pytest.mark.parametrize("value", [-1, 101, 1000])
def test_position_outside_0_to_100_is_rejected(value: int) -> None:
    """A position outside the range never exists."""
    with pytest.raises(ValueError, match="within 0 and 100"):
        Position(value)


@pytest.mark.parametrize("value", [50.0, "50", None, True])
def test_position_that_is_not_an_integer_is_rejected(value: Any) -> None:
    """Floats, strings, ``None`` and booleans are not positions."""
    with pytest.raises(TypeError, match="must be an integer"):
        Position(value)


def test_position_convention_100_is_open() -> None:
    """The named end positions follow guardrail 11."""
    assert Position(100) == FULLY_OPEN
    assert Position(0) == FULLY_CLOSED
    assert FULLY_CLOSED < Position(30) < FULLY_OPEN


def test_position_is_immutable_hashable_and_compares_by_value() -> None:
    """Positions work as values: equal, hashable, frozen."""
    position = Position(40)

    assert position == Position(40)
    assert position != Position(41)
    assert len({position, Position(40)}) == 1
    with pytest.raises(dataclasses.FrozenInstanceError):
        position.value = 10  # type: ignore[misc]


# --- Source value -----------------------------------------------------------


def test_source_value_with_a_value() -> None:
    """A value is readable once the state says there is one."""
    reading = 21.5
    temperature = SourceValue.of(reading)

    assert temperature.state is SourceState.VALUE
    assert temperature.has_value is True
    assert temperature.value == reading


@pytest.mark.parametrize(
    ("source", "state"),
    [
        (SourceValue[bool].unknown(), SourceState.UNKNOWN),
        (SourceValue[bool].unavailable(), SourceState.UNAVAILABLE),
    ],
)
def test_missing_source_value_has_no_value(
    source: SourceValue[bool], state: SourceState
) -> None:
    """Unknown and unavailable are states of their own, and reading them raises."""
    assert source.state is state
    assert source.has_value is False
    with pytest.raises(MissingSourceValueError, match=state.value):
        _ = source.value


@pytest.mark.parametrize(
    "source",
    [
        SourceValue.of(True),
        SourceValue.of(False),
        SourceValue.of(0),
        SourceValue[bool].unknown(),
        SourceValue[bool].unavailable(),
    ],
)
def test_source_value_has_no_truth_value(source: SourceValue[Any]) -> None:
    """``if source:`` raises instead of reading a missing input as "off"."""
    with pytest.raises(TypeError, match="no truth value"):
        bool(source)
    with pytest.raises(TypeError, match="no truth value"):
        assert not source


@pytest.mark.parametrize(
    "source", [SourceValue[float].unknown(), SourceValue[float].unavailable()]
)
def test_missing_source_value_does_not_convert_to_a_number(
    source: SourceValue[float],
) -> None:
    """There is no accidental way from "unavailable" to a number."""
    value: Any = source
    with pytest.raises(TypeError):
        int(value)
    with pytest.raises(TypeError):
        float(value)
    with pytest.raises(TypeError):
        _ = value + 1
    with pytest.raises(TypeError):
        _ = value < 1


def test_source_value_offers_no_accessor_with_a_default() -> None:
    """The public surface is the state, the flag and the raising accessor."""
    public = {name for name in dir(SourceValue) if not name.startswith("_")}

    assert public == {"of", "unknown", "unavailable", "state", "has_value", "value"}


def test_source_value_construction_is_validated() -> None:
    """State and value have to fit together."""
    broken: Any = None
    with pytest.raises(ValueError, match="needs a value"):
        SourceValue(SourceState.VALUE)
    with pytest.raises(ValueError, match="has no value"):
        SourceValue(SourceState.UNAVAILABLE, 3)
    with pytest.raises(TypeError, match="boolean, a number or a string"):
        SourceValue.of([1])  # type: ignore[type-var]
    with pytest.raises(ValueError, match="finite"):
        SourceValue.of(float("nan"))
    with pytest.raises(TypeError, match="SourceState"):
        SourceValue(broken)


def test_source_value_equality_and_hash() -> None:
    """Equal by state, value and type of the value; ``True`` is not ``1``."""
    assert SourceValue.of("on") == SourceValue.of("on")
    assert SourceValue.of(True) != SourceValue.of(1)
    assert SourceValue.of(1) != SourceValue.of(1.0)
    assert SourceValue[bool].unknown() == SourceValue[float].unknown()
    assert SourceValue[bool].unknown() != SourceValue[bool].unavailable()
    assert SourceValue.of("on") != "on"
    assert hash(SourceValue.of(2.5)) == hash(SourceValue.of(2.5))
    assert {SourceValue.of(True), SourceValue.of(1), SourceValue.of(True)} == {
        SourceValue.of(1),
        SourceValue.of(True),
    }


def test_source_value_is_immutable() -> None:
    """Neither assignment nor deletion works, and there is no instance dict."""
    source: Any = SourceValue.of(1)

    with pytest.raises(AttributeError, match="immutable"):
        source.anything = 2
    with pytest.raises(AttributeError, match="immutable"):
        source._value = 2  # noqa: SLF001
    with pytest.raises(AttributeError, match="immutable"):
        del source._value  # noqa: SLF001
    assert not hasattr(source, "__dict__")


def test_source_value_repr_names_state_and_value() -> None:
    """The representation is readable in a failing test."""
    assert repr(SourceValue.of("rain")) == "SourceValue.of('rain')"
    assert repr(SourceValue[str].unavailable()) == "SourceValue.unavailable()"
