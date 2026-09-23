"""The storage port of the runtime: in memory, surviving the reload of the entry.

Every configuration change reloads the whole config entry, and the runtime
state of a window (a pending own command with its expectation, the dams, a
deferral, the latched day type, the held inputs) has to survive that. This
implementation keeps the plain data of every window and the seed of the
installation in ``hass.data``, which Home Assistant keeps while it runs,
apart from ``entry.runtime_data``, which it discards on unload.

It survives a reload, not a restart: writing to disk is the job of the block
that builds persistence, which replaces this implementation behind the same
port. Until then a restart starts every window with a fresh state and a new
seed, and the documentation says so.
"""

import copy
import secrets
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant
from homeassistant.util.hass_dict import HassKey

from .const import DOMAIN
from .core.model import JsonObject
from .core.ports import Storage

STORAGE_KEY: HassKey[MemoryStorage] = HassKey(f"{DOMAIN}_storage")

_SEED_BITS = 63
"""The seed is a positive whole number that JSON writes without loss."""


@dataclass(slots=True)
class MemoryStorage:
    """The storage port, in memory."""

    windows: dict[str, JsonObject] = field(default_factory=dict)
    seed: int | None = None

    def load_window_state(self, window_id: str) -> JsonObject | None:
        """Return a copy of the persisted data of a window, or ``None``."""
        data = self.windows.get(window_id)
        return None if data is None else copy.deepcopy(data)

    def save_window_state(self, window_id: str, data: JsonObject) -> None:
        """Keep a copy of the data of a window, replacing what was there."""
        self.windows[window_id] = copy.deepcopy(data)

    def delete_window_state(self, window_id: str) -> None:
        """Forget the data of a window."""
        self.windows.pop(window_id, None)

    def load_seed(self) -> int | None:
        """Return the seed of the installation, or ``None``."""
        return self.seed

    def save_seed(self, seed: int) -> None:
        """Keep the seed of the installation."""
        self.seed = seed


def storage_of(hass: HomeAssistant) -> MemoryStorage:
    """Return the storage of the installation, creating it on first use."""
    if STORAGE_KEY not in hass.data:
        hass.data[STORAGE_KEY] = MemoryStorage()
    return hass.data[STORAGE_KEY]


def forget_storage(hass: HomeAssistant) -> None:
    """Drop the storage; the entry it belonged to was removed."""
    hass.data.pop(STORAGE_KEY, None)


def installation_seed(storage: Storage) -> int:
    """Return the seed for random offsets, creating and saving it once."""
    seed = storage.load_seed()
    if seed is None:
        seed = secrets.randbits(_SEED_BITS)
        storage.save_seed(seed)
    return seed
