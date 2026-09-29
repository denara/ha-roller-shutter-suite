"""The position source of a member in the settings registry of the core (section 8.1).

It cannot be detected, so the user states it per member; block H10 builds the
form from ``CAPABILITY_SETTINGS``. A faulty stored value is read as
``calculated``, the cautious default: a smaller tolerance never lets a
movement by hand pass as the integration's own.
"""

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DEFAULT_TOLERANCE_CALCULATED,
    DEFAULT_TOLERANCE_MEASURED,
    PositionSource,
)
from custom_components.roller_shutter_suite.core.settings import (
    CAPABILITY_SETTINGS,
    SettingKind,
    position_source_from_stored,
)
from tests.core.arbiter_kit import profile


def test_the_position_source_is_a_setting_of_one_member_without_a_fault_value() -> None:
    """A value of the capability profile: no function, not inherited, no fault value."""
    (definition,) = CAPABILITY_SETTINGS.definitions

    assert definition.key == "position_source"
    assert definition.kind is SettingKind.ENUMERATION
    assert definition.function is None
    assert definition.inheritable is False
    assert not definition.has_fault_value
    assert definition.default is PositionSource.CALCULATED


@pytest.mark.parametrize(
    ("stored", "source"),
    [
        ({"position_source": "measured"}, PositionSource.MEASURED),
        ({"position_source": "calculated"}, PositionSource.CALCULATED),
        ({}, PositionSource.CALCULATED),
        ({"position_source": "laser"}, PositionSource.CALCULATED),
        ({"position_source": None}, PositionSource.CALCULATED),
        ({"position_source": "__none__"}, PositionSource.CALCULATED),
        ("not a mapping", PositionSource.CALCULATED),
    ],
    ids=["measured", "calculated", "absent", "unknown", "null", "none", "unreadable"],
)
def test_a_faulty_stored_position_source_is_read_as_calculated(
    stored: object, source: PositionSource
) -> None:
    """Absent, unknown, null, "none" or unreadable: the cautious default."""
    assert position_source_from_stored(stored) is source


def test_the_position_source_decides_the_default_tolerance() -> None:
    """2 for a calculated position, 3 for a measured one (section 8.3)."""
    calculated = profile(position_source=PositionSource.CALCULATED)
    measured = profile(position_source=PositionSource.MEASURED)

    assert calculated.tolerance == DEFAULT_TOLERANCE_CALCULATED
    assert measured.tolerance == DEFAULT_TOLERANCE_MEASURED
