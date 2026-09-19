"""Values: position, source value, sun position."""

import math
from dataclasses import dataclass
from enum import StrEnum, unique
from typing import Final, NoReturn, Self

from ._data import JsonValue, as_int
from ._validation import require_finite, require_type

_MAX_POSITION: Final = 100

_FULL_CIRCLE: Final = 360.0

_ZENITH: Final = 90.0


@dataclass(frozen=True, slots=True, order=True)
class Position:
    """A position of a curtain: 100 is fully open, 0 is fully closed."""

    value: int

    def __post_init__(self) -> None:
        """Reject everything that is not an integer from 0 to 100."""
        if isinstance(self.value, bool) or not isinstance(self.value, int):
            raise TypeError(
                f"a position must be an integer, not {type(self.value).__name__}"
            )
        if not 0 <= self.value <= _MAX_POSITION:
            raise ValueError(f"a position must be within 0 and 100, got {self.value}")


FULLY_OPEN: Final = Position(100)

FULLY_CLOSED: Final = Position(0)


def _as_position(value: JsonValue) -> Position:
    """Read a position from plain data (helper of the package)."""
    return Position(as_int(value))


def _position_data(value: Position | None) -> int | None:
    """Return a position as plain data (helper of the package)."""
    return None if value is None else value.value


type SourceScalar = bool | int | float | str
"""What a source can deliver once the adapter has read the entity."""


@unique
class SourceState(StrEnum):
    """The three states of a source value."""

    VALUE = "value"
    UNKNOWN = "unknown"
    UNAVAILABLE = "unavailable"


class MissingSourceValueError(LookupError):
    """The value of a source was read although the source has none."""


class SourceValue[T: SourceScalar]:
    """An input read from a source: a value, unknown, or unavailable.

    Missing data is not good news. The type therefore has no truth value and
    no accessor that returns a default: ``bool(value)`` raises, numeric
    conversion is not defined, and :attr:`value` raises unless the state is
    :attr:`SourceState.VALUE`. Code that reads a source has to look at
    :attr:`state` first and say what "unknown" and "unavailable" mean for it.

    Comparing a source value with a plain value (``contact != "open"``) raises
    as well: the comparison would be false for every source value, so a
    missing contact would read as "not open". Two source values compare by
    state, value and type of the value.

    The adapter of the Home Assistant layer maps the entity states
    ``unavailable`` and ``unknown`` to the states of this type *before* it
    builds a value. The string ``"unavailable"`` as a value is therefore a bug
    of the adapter, not a missing value; this type cannot tell.
    """

    __slots__ = ("_state", "_value")

    _state: SourceState
    _value: T | None

    def __init__(self, state: SourceState, value: T | None = None) -> None:
        """Create a source value; prefer :meth:`of`, :meth:`unknown`, :meth:`unavailable`."""
        require_type(state, SourceState, "the state of a source value")
        if state is SourceState.VALUE:
            if value is None:
                raise ValueError("a source value in the state 'value' needs a value")
            if not isinstance(value, (bool, int, float, str)):
                raise TypeError(
                    "a source value must be a boolean, a number or a string, "
                    f"not {type(value).__name__}"
                )
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("a source value must be a finite number")
        elif value is not None:
            raise ValueError(
                f"a source value in the state {state.value!r} has no value"
            )
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_value", value)

    @classmethod
    def of(cls, value: T) -> Self:
        """Return a source value that has a value."""
        return cls(SourceState.VALUE, value)

    @classmethod
    def unknown(cls) -> Self:
        """Return the source value "unknown"."""
        return cls(SourceState.UNKNOWN)

    @classmethod
    def unavailable(cls) -> Self:
        """Return the source value "unavailable"."""
        return cls(SourceState.UNAVAILABLE)

    @property
    def state(self) -> SourceState:
        """Return which of the three states this is."""
        return self._state

    @property
    def has_value(self) -> bool:
        """Return whether the state is :attr:`SourceState.VALUE`."""
        return self._state is SourceState.VALUE

    @property
    def value(self) -> T:
        """Return the value; raise if the source is unknown or unavailable."""
        if self._value is None:
            raise MissingSourceValueError(
                f"the source is {self._state.value}; it has no value"
            )
        return self._value

    def __bool__(self) -> NoReturn:
        """Refuse a truth value, so a missing input never reads as "off"."""
        raise TypeError(
            "a source value has no truth value; check its state and read its value"
        )

    def __setattr__(self, name: str, value: object) -> NoReturn:
        """Refuse assignment: source values are immutable."""
        raise AttributeError(f"cannot assign to {name!r}: source values are immutable")

    def __delattr__(self, name: str) -> NoReturn:
        """Refuse deletion: source values are immutable."""
        raise AttributeError(f"cannot delete {name!r}: source values are immutable")

    def __eq__(self, other: object) -> bool:
        """Compare with another source value; refuse a plain value.

        Two source values are equal if state, value and the type of the value
        are (``True`` is not ``1``). ``!=`` follows this method, so it raises
        for a plain value as well.
        """
        if isinstance(other, (bool, int, float, str)):
            raise TypeError(
                "a source value does not compare with a plain value; check its "
                "state and compare its value"
            )
        if not isinstance(other, SourceValue):
            return NotImplemented
        return (
            self._state is other._state
            and type(self._value) is type(other._value)
            and self._value == other._value
        )

    def __hash__(self) -> int:
        """Hash consistently with equality."""
        return hash((self._state, type(self._value), self._value))

    def __repr__(self) -> str:
        """Show the state, and the value if there is one."""
        if self._value is None:
            return f"SourceValue.{self._state.value}()"
        return f"SourceValue.of({self._value!r})"


@dataclass(frozen=True, slots=True)
class SunPosition:
    """Where the sun is: azimuth clockwise from north and elevation, in degrees."""

    azimuth: float
    elevation: float

    def __post_init__(self) -> None:
        """Validate the ranges."""
        require_finite(self.azimuth, "the azimuth of the sun")
        require_finite(self.elevation, "the elevation of the sun")
        if not 0 <= self.azimuth < _FULL_CIRCLE:
            raise ValueError("the azimuth must be at least 0 and below 360 degrees")
        if not -_ZENITH <= self.elevation <= _ZENITH:
            raise ValueError("the elevation must be within -90 and 90 degrees")


type AnySourceValue = (
    SourceValue[bool] | SourceValue[int] | SourceValue[float] | SourceValue[str]
)
"""A source value of any of the scalar types."""
