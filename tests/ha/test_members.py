"""What the members of a window report: cover states become observations."""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant

from custom_components.roller_shutter_suite.core.model import (
    CapabilityProfile,
    MemberConfig,
    MovementState,
    Position,
    WindowConfig,
)
from custom_components.roller_shutter_suite.members import (
    observe_member,
    observe_window,
)
from tests.ha.helpers import set_cover

COVER = "cover.example_window"


def _member(*, reports_position: bool = True) -> MemberConfig:
    return MemberConfig(
        COVER,
        CapabilityProfile(
            supports_open_close=True,
            supports_set_position=reports_position,
            supports_stop=True,
            reports_position=reports_position,
            travel_time_up=timedelta(seconds=30),
            travel_time_down=timedelta(seconds=30),
        ),
    )


@pytest.mark.parametrize(
    ("state", "position", "movement", "expected_position"),
    [
        ("open", 100, MovementState.RESTING, 100),
        ("closed", 0, MovementState.RESTING, 0),
        ("opening", 40, MovementState.MOVING_UP, 40),
        ("closing", 60, MovementState.MOVING_DOWN, 60),
        ("unknown", None, MovementState.RESTING, None),
        ("open", None, MovementState.RESTING, None),
        ("open", 101, MovementState.RESTING, None),
        ("open", -1, MovementState.RESTING, None),
    ],
)
async def test_cover_states_become_observations(
    hass: HomeAssistant,
    state: str,
    position: int | None,
    movement: MovementState,
    expected_position: int | None,
) -> None:
    """Opening and closing are movements; a position outside 0 to 100 is none."""
    set_cover(hass, COVER, position=position, state=state)

    observation = observe_member(hass, _member()).observation

    assert observation.state is movement
    expected = None if expected_position is None else Position(expected_position)
    assert observation.position == expected


async def test_a_position_that_is_no_whole_number_is_none(hass: HomeAssistant) -> None:
    """A boolean or text where the position belongs is not a position."""
    hass.states.async_set(COVER, "open", {"current_position": True})
    assert observe_member(hass, _member()).observation.position is None
    hass.states.async_set(COVER, "open", {"current_position": "50"})
    assert observe_member(hass, _member()).observation.position is None


async def test_a_member_without_position_feedback_reports_none(
    hass: HomeAssistant,
) -> None:
    """Whatever the attribute says, the profile decides that the member reports none."""
    set_cover(hass, COVER, position=50)

    observation = observe_member(hass, _member(reports_position=False)).observation

    assert observation.state is MovementState.RESTING
    assert observation.position is None


@pytest.mark.parametrize(
    "state", ["unavailable", None], ids=["unavailable", "no state"]
)
async def test_a_cover_without_a_usable_state_is_unavailable(
    hass: HomeAssistant, state: str | None
) -> None:
    """No state and the state unavailable are the same to the core."""
    if state is not None:
        hass.states.async_set(COVER, state, {"current_position": 50})

    observation = observe_member(hass, _member()).observation

    assert observation.state is MovementState.UNAVAILABLE
    assert observation.position is None


async def test_the_window_is_observed_in_the_order_of_its_members(
    hass: HomeAssistant,
) -> None:
    """Every member, in the order of the configuration; the view is the model's."""
    set_cover(hass, "cover.example_left", position=30)
    config = WindowConfig(
        "w1",
        (
            _member(),
            MemberConfig("cover.example_left", _member().capabilities),
        ),
    )

    observed = observe_window(hass, config)

    assert [m.member_id for m in observed.members] == [COVER, "cover.example_left"]
    assert observed.available
    assert observed.members[0].observation.state is MovementState.UNAVAILABLE
    assert observed.members[1].observation.position == Position(30)
