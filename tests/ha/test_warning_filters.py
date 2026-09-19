"""The warning filters in effect for the Home Assistant tests are the approved list.

``tests/core`` has the same test. Both are needed: CI runs the test folders one
by one, and a ``conftest.py`` below this folder is only loaded for a run that
includes this folder.
"""

import pytest

from tests.conftest import unapproved_filters


def test_filters_in_effect_are_the_approved_list(
    pytestconfig: pytest.Config,
) -> None:
    """Warnings are errors, except the entries of ``foreign_warnings.toml``."""
    assert unapproved_filters(pytestconfig) == []
