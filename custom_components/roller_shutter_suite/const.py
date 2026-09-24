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
# member carries this provisional value. It lives in memory only: it is never
# stored, never shown as a value the user set, and it disappears with the
# block that introduces per-member values.
PROVISIONAL_TRAVEL_TIME: Final = timedelta(seconds=60)

# The runtime (``docs/dev/runtime.md``).
#
# A burst of state changes is coalesced: a recompute runs this long after the
# last trigger, and never while another recompute of the same window runs.
COALESCE_SECONDS: Final = 1.0

# Wake-up times that the core asks for ("defer until", "re-evaluate no later
# than", the next planned action of the schedule, its recheck) are accepted
# only if they lie strictly in the future, and two recomputes that come from
# wake-ups are at least this far apart. A layer that keeps asking for "now"
# therefore cannot spin; the one constant is the only place that says how far.
MIN_WAKE_UP_DISTANCE: Final = timedelta(seconds=5)

# The periodic safety tick: a recompute that needs no trigger, so that a missed
# event or a timer that never fired cannot leave a window in the wrong state
# for longer than this.
SAFETY_TICK: Final = timedelta(minutes=5)

# After a start, a window waits for its members before the first decision.
# Late availability is normal. Once one member is available and this much
# time has passed since the start, the window decides with the members it
# has; the others are handled by the gate and reported in the status. Two
# minutes because polled covers report with a delay of up to 60 seconds (the
# S1 measurement). A deviation from the letter of section 11; see
# docs/dev/runtime.md, "Deviations".
STARTUP_GRACE: Final = timedelta(minutes=2)

# The status of a window (``docs/features/status-and-events.md``).
#
# The one event type of the integration on the bus: fired when a wanted
# movement is held back or deferred, and when a command is sent or would have
# been sent in dry-run.
EVENT_REASON: Final = f"{DOMAIN}_reason"

# How many decisions the diagnostics keep per window, the newest first.
RECENT_DECISIONS: Final = 10


def status_signal(window_id: str) -> str:
    """Return the dispatcher signal that says the status of a window changed."""
    return f"{DOMAIN}_status_{window_id}"
