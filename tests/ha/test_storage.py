"""The storage port in memory: copies, the seed, the life with the entry."""

from homeassistant.core import HomeAssistant

from custom_components.roller_shutter_suite.core.model import JsonObject, JsonValue
from custom_components.roller_shutter_suite.storage import (
    MemoryStorage,
    forget_storage,
    installation_seed,
    storage_of,
)


def test_window_data_is_copied_on_the_way_in_and_out() -> None:
    """What was saved cannot be changed from outside, and what was loaded neither."""
    storage = MemoryStorage()
    members: list[JsonValue] = [{"member_id": "cover.example_window"}]
    data: JsonObject = {"schema_version": 1, "members": members}

    storage.save_window_state("w1", data)
    members.clear()
    loaded = storage.load_window_state("w1")
    assert loaded == {
        "schema_version": 1,
        "members": [{"member_id": "cover.example_window"}],
    }
    assert loaded is not None
    loaded["members"] = []

    assert storage.load_window_state("w1") != loaded
    assert storage.load_window_state("w2") is None

    storage.delete_window_state("w1")
    storage.delete_window_state("w1")
    assert storage.load_window_state("w1") is None


def test_the_seed_is_created_once() -> None:
    """The first call creates and saves it, every later call returns the same one."""
    storage = MemoryStorage()
    assert storage.load_seed() is None

    seed = installation_seed(storage)

    assert isinstance(seed, int)
    assert not isinstance(seed, bool)
    assert seed > 0
    assert installation_seed(storage) == seed
    assert storage.load_seed() == seed


async def test_the_storage_of_the_installation_lives_in_hass_data(
    hass: HomeAssistant,
) -> None:
    """One storage per Home Assistant, until the entry is removed."""
    storage = storage_of(hass)

    assert storage_of(hass) is storage
    forget_storage(hass)
    forget_storage(hass)
    assert storage_of(hass) is not storage
