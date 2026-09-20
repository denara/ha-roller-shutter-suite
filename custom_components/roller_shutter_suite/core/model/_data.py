"""Plain JSON-compatible data and the helpers that read it back.

Every helper raises a ``ValueError``. :func:`read` prefixes the key, so the
message of a nested error leads from the top-level key to the broken one.
"""

from collections.abc import Callable
from datetime import date, datetime
from enum import StrEnum

from ._validation import require_aware

type JsonValue = (
    bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
)
"""Plain data that a JSON encoder accepts without any help."""

type JsonObject = dict[str, JsonValue]
"""A JSON object: what the storage port stores for one window."""


def as_object(value: JsonValue, *keys: str) -> JsonObject:
    """Return the object; refuse a key that is not one of the expected keys.

    An unknown key means that the stored data and the code disagree within
    one schema version. That is never ignored.
    """
    if not isinstance(value, dict):
        raise ValueError("expected an object")  # noqa: TRY004
    for key in value:
        if key not in keys:
            raise ValueError(f"unknown key {key!r}")
    return value


def as_list(value: JsonValue) -> list[JsonValue]:
    """Return the list."""
    if not isinstance(value, list):
        raise ValueError("expected a list")  # noqa: TRY004
    return value


def as_str(value: JsonValue) -> str:
    """Return the string."""
    if not isinstance(value, str):
        raise ValueError("expected a string")  # noqa: TRY004
    return value


def as_bool(value: JsonValue) -> bool:
    """Return the boolean."""
    if not isinstance(value, bool):
        raise ValueError("expected true or false")  # noqa: TRY004
    return value


def as_int(value: JsonValue) -> int:
    """Return the integer; a boolean is not an integer."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("expected an integer")  # noqa: TRY004
    return value


def as_datetime(value: JsonValue) -> datetime:
    """Return the timezone-aware datetime; refuse a naive one."""
    parsed = datetime.fromisoformat(as_str(value))
    require_aware(parsed, "a persisted timestamp")
    return parsed


def as_date(value: JsonValue) -> date:
    """Return the calendar date."""
    return date.fromisoformat(as_str(value))


def as_enum[E: StrEnum](enum: type[E]) -> Callable[[JsonValue], E]:
    """Return a converter to a member of the enumeration."""

    def convert_enum(value: JsonValue) -> E:
        return enum(as_str(value))

    return convert_enum


def optional[T](convert: Callable[[JsonValue], T]) -> Callable[[JsonValue], T | None]:
    """Return a converter that lets ``None`` pass."""

    def convert_optional(value: JsonValue) -> T | None:
        return None if value is None else convert(value)

    return convert_optional


def tuple_of[T](
    convert: Callable[[JsonValue], T],
) -> Callable[[JsonValue], tuple[T, ...]]:
    """Return a converter from a list to a tuple."""

    def convert_list(value: JsonValue) -> tuple[T, ...]:
        return tuple(convert(item) for item in as_list(value))

    return convert_list


def read[T](data: JsonObject, key: str, convert: Callable[[JsonValue], T]) -> T:
    """Read one key of persisted data; errors name the key they concern."""
    if key not in data:
        raise ValueError(f"the key {key!r} is missing")
    try:
        return convert(data[key])
    except ValueError as err:
        raise ValueError(f"{key}: {err}") from err


def datetime_data(value: datetime | None) -> str | None:
    """Return the ISO 8601 text of a datetime; ``None`` passes."""
    return None if value is None else value.isoformat()
