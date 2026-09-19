"""Validation helpers shared by the modules of the model. Not part of its surface."""

import math
from collections.abc import Iterable
from datetime import UTC, datetime


def require_type(value: object, expected: type, what: str) -> None:
    """Raise a ``TypeError`` unless the value has the expected type."""
    if not isinstance(value, expected):
        raise TypeError(
            f"{what} must be of type {expected.__name__}, not {type(value).__name__}"
        )


def require_optional_type(value: object, expected: type, what: str) -> None:
    """Raise a ``TypeError`` unless the value is ``None`` or has the expected type."""
    if value is not None:
        require_type(value, expected, what)


def require_aware(value: datetime, what: str) -> None:
    """Reject everything that is not a timezone-aware datetime."""
    require_type(value, datetime, what)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{what} must be timezone-aware, got a naive datetime")


def require_aware_or_none(value: datetime | None, what: str) -> None:
    """Reject a naive datetime; ``None`` passes."""
    if value is not None:
        require_aware(value, what)


def to_utc(value: datetime, what: str) -> datetime:
    """Return the same instant in UTC; reject a naive datetime.

    Persisted types hold instants. Two aware datetimes in different zones do
    not compare equal when one of them lies in the repeated hour of a clock
    change, so an instant kept in a named zone would not survive the round
    trip through plain data as an equal value. In UTC it does.
    """
    require_aware(value, what)
    return value.astimezone(UTC)


def to_utc_or_none(value: datetime | None, what: str) -> datetime | None:
    """Return the same instant in UTC; ``None`` passes."""
    return None if value is None else to_utc(value, what)


def require_identifier(value: str, what: str) -> None:
    """Reject everything that is not a non-empty string."""
    require_type(value, str, what)
    if not value:
        raise ValueError(f"{what} must not be empty")


def require_unique(identifiers: Iterable[str], what: str) -> None:
    """Reject an identifier that occurs twice."""
    seen: set[str] = set()
    for identifier in identifiers:
        if identifier in seen:
            raise ValueError(f"{what} must be unique, {identifier!r} occurs twice")
        seen.add(identifier)


def require_finite(value: float, what: str) -> None:
    """Reject everything that is not a finite number."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{what} must be a number, not {type(value).__name__}")
    if not math.isfinite(value):
        raise ValueError(f"{what} must be a finite number")
