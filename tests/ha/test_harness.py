"""The test harness loads the integration from this repository."""

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.loader import async_get_integration

from custom_components.roller_shutter_suite.const import DOMAIN

REPOSITORY_ROOT = Path(__file__).parents[2]


async def test_home_assistant_finds_the_repository_integration(
    hass: HomeAssistant,
) -> None:
    """Home Assistant resolves the domain to the folder in this repository.

    The test plugin ships a ``custom_components`` package of its own. If that
    one were imported first, Home Assistant would not find this integration;
    ``conftest.py`` explains why it is not.
    """
    integration = await async_get_integration(hass, DOMAIN)

    assert integration.file_path == (REPOSITORY_ROOT / "custom_components" / DOMAIN)
    assert not integration.is_built_in
