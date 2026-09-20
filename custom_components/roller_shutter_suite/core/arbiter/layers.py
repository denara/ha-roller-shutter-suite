"""Help for writing layers: what a missing input means.

Unknown or unavailable input never becomes a guess, and therefore never a
position. Each layer states, per input, what the absence of that input means:

- **step aside** (no opinion): the layer passes to the next one. This is for
  layers whose purpose is comfort.
- **hold** (leave alone): the layer wins and keeps the window where it is.
  This is for layers whose purpose is safety.
"""

from custom_components.roller_shutter_suite.core.model import (
    AnySourceValue,
    Layer,
    SourceState,
    WindowConfig,
    Wish,
)
from custom_components.roller_shutter_suite.core.reasons import ReasonCode


def disabled_functions(config: WindowConfig) -> frozenset[str]:
    """Return the comfort functions that are disabled for the window.

    The one place where the arbiter reads them from the configuration.
    """
    return config.disabled_functions


def wish_for_missing_input(
    layer: Layer, value: AnySourceValue | None, *, hold: bool
) -> Wish | None:
    """Return the wish of a layer whose input is missing; ``None`` if it has a value.

    ``value`` is the source value as the snapshot has it; ``None`` means that
    the snapshot does not contain the source at all, which counts as
    unavailable. With ``hold`` the layer holds the window where it is,
    otherwise it steps aside. Neither answer carries a position.
    """
    if value is not None and value.has_value:
        return None
    reason = (
        ReasonCode.INPUT_UNKNOWN
        if value is not None and value.state is SourceState.UNKNOWN
        else ReasonCode.INPUT_UNAVAILABLE
    )
    if hold:
        return Wish.leave_alone(layer, reason)
    return Wish.no_opinion(layer, reason)
