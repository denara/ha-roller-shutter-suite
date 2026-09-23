"""An in-memory implementation of the storage port.

It keeps the plain data as JSON text, so a state really goes through the
serialization on every save and load, as it does with a file. A restart of
the simulated core reads from here.
"""

import json

from custom_components.roller_shutter_suite.core.model import JsonObject


class MemoryStorage:
    """The storage port of the synthetic world."""

    def __init__(self) -> None:
        """Start empty."""
        self._windows: dict[str, str] = {}
        self._seed: int | None = None
        self.saves = 0
        """How often a window state was saved; a state that did not change is not."""

    def load_window_state(self, window_id: str) -> JsonObject | None:
        """Return the persisted data of a window, or ``None``."""
        text = self._windows.get(window_id)
        if text is None:
            return None
        loaded: JsonObject = json.loads(text)
        return loaded

    def save_window_state(self, window_id: str, data: JsonObject) -> None:
        """Persist the data of a window as JSON text."""
        self._windows[window_id] = json.dumps(data, sort_keys=True)
        self.saves += 1

    def delete_window_state(self, window_id: str) -> None:
        """Forget a window."""
        self._windows.pop(window_id, None)

    def load_seed(self) -> int | None:
        """Return the installation's seed, or ``None``."""
        return self._seed

    def save_seed(self, seed: int) -> None:
        """Keep the installation's seed."""
        self._seed = seed
