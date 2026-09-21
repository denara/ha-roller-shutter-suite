"""Constants of the Roller Shutter Suite integration.

This module imports nothing from Home Assistant, so the description of the
forms (``flow/model.py``, ``features/``) and the translation generator can use
it without Home Assistant.
"""

from datetime import timedelta
from typing import Final

from .core.settings import SETTINGS_KEY

DOMAIN: Final = "roller_shutter_suite"

# Title of the single config entry. It is the product name and therefore the
# same in every language.
ENTRY_TITLE: Final = "Roller Shutter Suite"

# Version of the stored layout: config entry data and the data of all its
# subentries. Home Assistant keeps one version per config entry and none per
# subentry, so this pair covers the subentries too; ``async_migrate_entry``
# migrates both. 1.1 was the entry without any data; 1.2 added the mapping of
# the settings.
CONFIG_VERSION: Final = 1
CONFIG_MINOR_VERSION: Final = 2

SUBENTRY_GROUP: Final = "group"
SUBENTRY_WINDOW: Final = "window"

# Identity data of a subentry. The settings live apart from it, in a mapping
# of their own under ``CONF_SETTINGS`` that holds nothing but registry keys.
# "No group" is an absent key; ``null`` is never written.
CONF_COVERS: Final = "covers"
CONF_GROUP_ID: Final = "group_id"
CONF_DRY_RUN: Final = "dry_run"
CONF_SETTINGS: Final = SETTINGS_KEY

# Form field only: the name is stored as the title of the subentry, never in
# its data, because the user interface can rename a subentry outside any flow.
CONF_NAME: Final = "name"

# The core's capability profile needs travel times, which are configuration
# values of a later block (per-member values). Until that block exists, every
# member carries this provisional value; nothing acts on it yet.
PROVISIONAL_TRAVEL_TIME: Final = timedelta(seconds=60)
