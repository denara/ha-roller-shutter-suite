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
# the settings; 1.3 added the optional mapping of what the user states per
# member of a window (``CONF_MEMBERS``), which data of 1.2 does not need.
CONFIG_VERSION: Final = 1
CONFIG_MINOR_VERSION: Final = 3

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

# What the user states per member of a window (the member pages of the form):
# a mapping from the member's entity ID to its capability settings, keys of
# ``CAPABILITY_SETTINGS`` of the core in their stored form. Only members that
# state something are listed, and of them only what they state (section 9 of
# the specification: "members are listed only where they differ"). An
# absent key is "nothing stated"; a window stored before version 1.3 has none.
CONF_MEMBERS: Final = "members"

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

# Whether the runtime notices a movement by hand. Since block H10 the runtime
# feeds every report of a cover to the tracker of block C06, which tells a
# movement by hand from an own one. Were it false, an armed window would take
# a shutter that a person moved for one that is not where it should be and
# move it back within seconds: the page of the checks would refuse to arm a
# window, and a window stored as armed would run in dry-run with a repair
# issue (maintenance item X10, ruled by the project owner). The one place
# that decides it; the flow and the set-up read it each time they need it.
MOVEMENT_DETECTION_WIRED: Final[bool] = True

# The status of a window (``docs/features/status-and-events.md``).
#
# The one event type of the integration on the bus: fired when a wanted
# movement is held back or deferred, and when a command is sent or would have
# been sent in dry-run.
EVENT_REASON: Final = f"{DOMAIN}_reason"

# How many decisions the diagnostics keep per window, the newest first.
RECENT_DECISIONS: Final = 10

# The controls (``controls.py``).
#
# An external pause entity without a value pauses its level at once; after
# this long without a value a repair issue names the level and the entity.
# One hour, the default of a blind protection source (section 10.3 of the
# specification).
PAUSE_SOURCE_BLIND_AFTER: Final = timedelta(hours=1)


def status_signal(window_id: str) -> str:
    """Return the dispatcher signal that says the status of a window changed."""
    return f"{DOMAIN}_status_{window_id}"
