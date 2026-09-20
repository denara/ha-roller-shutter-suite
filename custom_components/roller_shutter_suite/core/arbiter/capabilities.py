"""The one place where the arbiter asks what a member can do.

The gate never looks at a capability flag itself. It asks the questions below,
and they all go through ``_is_missing``. Only a capability that is definitely
missing counts: it makes the gate say ``capability_missing``, and it makes a
member one "without position feedback". A capability that is not known is
treated like a present one for the decision. It never blocks and is never
reported, and nothing here claims that it is confirmed.
"""

from custom_components.roller_shutter_suite.core.model import CapabilityProfile


def _is_missing(capability: bool) -> bool:
    """Return whether the member definitely lacks the capability.

    This is the only line that knows how a capability is stored.
    """
    return capability is False


def cannot_execute(profile: CapabilityProfile) -> bool:
    """Return whether the member can definitely not be commanded to a position.

    A target needs "set position" or, mapped to an end position by the
    adapter, "open and close". Only if both are missing, nothing can be sent.
    """
    return _is_missing(profile.supports_set_position) and _is_missing(
        profile.supports_open_close
    )


def has_no_position_feedback(profile: CapabilityProfile) -> bool:
    """Return whether the member definitely reports no position."""
    return _is_missing(profile.reports_position)
