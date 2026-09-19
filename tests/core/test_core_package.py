"""The domain core can be imported on its own."""

import importlib


def test_core_package_is_importable() -> None:
    """The core package imports under its real name.

    ``conftest.py`` fails this test if the import pulled in Home Assistant.
    """
    core = importlib.import_module("custom_components.roller_shutter_suite.core")

    assert core.__name__ == "custom_components.roller_shutter_suite.core"
