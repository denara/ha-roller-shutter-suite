"""The one place where the arbiter asks what a member can do.

The gate never looks at a capability flag itself. It asks the questions below,
and they all go through ``_is_missing``, which reads the three-valued state of
a capability (``CapabilityProfile.capability_state``) and never the boolean
flag: for a member about which nothing is known, every flag reads ``False``,
and that must not be taken for "missing". Only a capability that is definitely
missing counts: it makes the gate say ``capability_missing``, and it makes a
member one "without position feedback". A capability that is not known is
treated like a present one for the decision. It never blocks and is never
reported, and nothing here claims that it is confirmed.
"""

from datetime import timedelta

from custom_components.roller_shutter_suite.core.model import (
    MAX_REPORTING_TIME,
    CapabilityProfile,
    CapabilityState,
)


def _is_missing(profile: CapabilityProfile, capability: str) -> bool:
    """Return whether the member definitely lacks the capability.

    This is the only line that knows how a capability is stored.
    """
    return profile.capability_state(capability) is CapabilityState.MISSING


def cannot_execute(profile: CapabilityProfile) -> bool:
    """Return whether the member can definitely not be commanded to a position.

    A target needs "set position" or, mapped to an end position by the
    adapter, "open and close". Only if both are missing, nothing can be sent.
    """
    return _is_missing(profile, "supports_set_position") and _is_missing(
        profile, "supports_open_close"
    )


def has_no_position_feedback(profile: CapabilityProfile) -> bool:
    """Return whether the member definitely reports no position."""
    return _is_missing(profile, "reports_position")


def is_tracked(profile: CapabilityProfile) -> bool:
    """Return whether the movement tracker follows and judges the member.

    Not a member without position feedback (section 8.1), and not a member
    whose reporting time the user has not stated: for it the tracker answers
    "unknown" rather than judge with a time nobody entered.
    """
    return not has_no_position_feedback(profile) and profile.movement_detection_known


def reporting_time_bound(
    profile: CapabilityProfile, *, simulated: bool = False
) -> timedelta:
    """Return how long a report of the member may lag behind: an upper bound.

    The stated reporting time; while it is unknown, the largest one a user
    can state (``MAX_REPORTING_TIME``), never zero: a deadline that is too
    long keeps a command pending a little longer, one that is too short
    would judge a movement that is still being reported.

    A **simulated** command of a window in dry-run is the exception
    (decision of the orchestrator from the review of block H10): for it an
    unknown reporting time contributes nothing. Nothing reports a simulated
    command, and the bound would hold the dry-run record in "movement in
    flight" for up to twelve minutes after every would-be command, which an
    armed window never shows: an armed window never has a member with an
    unknown reporting time, and the tracker judges nothing for one.
    """
    if profile.reporting_time is None:
        return timedelta(0) if simulated else MAX_REPORTING_TIME
    return profile.reporting_time
