"""Constants of the Roller Shutter Suite integration.

SPIKE S2: everything below the entry title is throwaway code of the spike and
is not meant to reach ``main``.
"""

from typing import Final

DOMAIN: Final = "roller_shutter_suite"

# Title of the single config entry. It is the product name and therefore the
# same in every language.
ENTRY_TITLE: Final = "Roller Shutter Suite"

SUBENTRY_GROUP: Final = "group"
SUBENTRY_WINDOW: Final = "window"
SUBENTRY_PATTERN_LAB: Final = "pattern_lab"

CONF_NAME: Final = "name"
CONF_COVERS: Final = "covers"
CONF_GROUP_ID: Final = "group_id"
CONF_DRY_RUN: Final = "dry_run"
CONF_SETTINGS: Final = "settings"
CONF_PATTERN: Final = "pattern"

# Key under ``hass.data`` where the spike counts how often the entry was set up.
DATA_SETUP_COUNT: Final = f"{DOMAIN}_setup_count"
