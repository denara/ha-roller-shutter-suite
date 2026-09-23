"""The astral-backed sun port: reference values, polar days, a clock change.

The implementation lives outside the domain core
(``custom_components/roller_shutter_suite/sun_astral.py``), because the core
imports no third-party library. Its tests still stand here: the module itself
needs nothing of Home Assistant, so they run on every platform; and because
the conftest of this folder registers a stand-in for the integration package
(whose ``__init__`` would otherwise import Home Assistant), the purity proof
shows that the module and what it imports pull in nothing of Home Assistant.

Where the expected numbers come from:

- **The worked example of the ``astral`` documentation** (its front page):
  "London" at 51.5 north, 0.116 west, zone ``Europe/London``, on 22 April
  2009, with sunrise at 04:50:17 UTC and sunset at 19:08:41 UTC. The
  coordinates are the ones of that example, not of any installation.
- **A made-up round point**, 50 north and 10 east in the zone
  ``Europe/Berlin``, for everything else. Its expected values follow from
  textbook facts and are derived in the comments: the elevation at solar noon
  is 90 minus the latitude plus the declination of the sun (23.44 degrees on
  the June solstice, minus that on the December one), and the length of the
  day follows from the sunrise equation with the apparent radius of the sun
  and the standard refraction at the horizon (0.833 degrees below it).
- **A made-up polar point**, 80 north and 20 east, for the polar night and
  the polar day.
- Two made-up points far from Greenwich, 40 south at 175 east and 20 north
  at 155 west, whose sunrise or sunset falls on another calendar date in UTC
  than on the local clock.
"""

from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.roller_shutter_suite.core.model import (
    DayTriggers,
    SunAlmanac,
    SunPosition,
    TriggerKind,
)
from custom_components.roller_shutter_suite.core.ports import Sun
from custom_components.roller_shutter_suite.core.schedule import (
    ALMANAC_DAYS_AHEAD,
    ALMANAC_DAYS_BEFORE,
    build_sun_almanac,
)
from custom_components.roller_shutter_suite.sun_astral import AstralSun
from tests.core.schedule_kit import config, elevation_trigger, fixed

LONDON = AstralSun(51.5, -0.116, 0.0, "Europe/London")
"""The location of the worked example of the ``astral`` documentation."""

ROUND_POINT = AstralSun(50.0, 10.0, 0.0, "Europe/Berlin")
BERLIN_ZONE = ZoneInfo("Europe/Berlin")
POLAR_POINT = AstralSun(80.0, 20.0, 0.0, "Europe/Oslo")

JUNE_SOLSTICE = date(2026, 6, 21)
DECEMBER_SOLSTICE = date(2026, 12, 21)
CLOCKS_FORWARD = date(2026, 3, 29)
CLOCKS_BACK = date(2026, 10, 25)

DECLINATION_AT_SOLSTICE = 23.44
HALF_A_DEGREE = 0.5
TWO_DEGREES = 2.0
A_TWENTIETH_OF_A_DEGREE = 0.05
A_TENTH_OF_A_DEGREE = 0.1
EAST = (60.0, 120.0)
WEST = (240.0, 300.0)
FULL_CIRCLE = 360.0
THREE_MINUTES = timedelta(minutes=3)


def local(day: date, hour: int, minute: int = 0) -> datetime:
    """Return a local time of the round point's zone."""
    return datetime.combine(day, time(hour, minute), tzinfo=BERLIN_ZONE)


def test_the_port_is_a_sun() -> None:
    """The class satisfies the protocol; the four values are plain."""
    sun: Sun = ROUND_POINT

    assert isinstance(sun.position(local(JUNE_SOLSTICE, 12)), SunPosition)
    assert AstralSun(50, 10, 0, "Europe/Berlin") == ROUND_POINT
    assert hash(ROUND_POINT) == hash(AstralSun(50.0, 10.0, 0.0, "Europe/Berlin"))


def test_sunrise_and_sunset_of_the_documentation_example() -> None:
    """The worked example of the astral documentation, within two seconds."""
    day = date(2009, 4, 22)
    sunrise = LONDON.sunrise(day)
    sunset = LONDON.sunset(day)

    assert sunrise is not None
    assert sunset is not None
    assert abs(sunrise - datetime(2009, 4, 22, 4, 50, 17, tzinfo=UTC)) < timedelta(
        seconds=2
    )
    assert abs(sunset - datetime(2009, 4, 22, 19, 8, 41, tzinfo=UTC)) < timedelta(
        seconds=2
    )
    # The answers are in the local zone: British Summer Time in April.
    assert sunrise.utcoffset() == timedelta(hours=1)
    assert sunrise.tzinfo == ZoneInfo("Europe/London")


@pytest.mark.parametrize(
    ("day", "solar_noon", "declination"),
    [
        # Solar noon at 10 east lies 40 minutes before noon in UTC, and the
        # equation of time moves it by less than three minutes on both days.
        (JUNE_SOLSTICE, time(13, 20), DECLINATION_AT_SOLSTICE),
        (DECEMBER_SOLSTICE, time(12, 20), -DECLINATION_AT_SOLSTICE),
    ],
)
def test_elevation_at_solar_noon_on_the_solstices(
    day: date, solar_noon: time, declination: float
) -> None:
    """At solar noon the elevation is 90 minus the latitude plus the declination."""
    at = datetime.combine(day, solar_noon, tzinfo=BERLIN_ZONE)
    position = ROUND_POINT.position(at)

    assert abs(position.elevation - (90 - 50 + declination)) < HALF_A_DEGREE
    assert abs(position.azimuth - 180) < TWO_DEGREES


def test_azimuth_runs_from_east_over_south_to_west() -> None:
    """In the morning the sun stands in the east, in the evening in the west."""
    morning = ROUND_POINT.position(local(JUNE_SOLSTICE, 8))
    evening = ROUND_POINT.position(local(JUNE_SOLSTICE, 18))
    midnight = ROUND_POINT.position(local(JUNE_SOLSTICE, 0))

    assert EAST[0] < morning.azimuth < EAST[1]
    assert WEST[0] < evening.azimuth < WEST[1]
    assert midnight.elevation < 0
    assert 0 <= midnight.azimuth < FULL_CIRCLE


@pytest.mark.parametrize(
    ("day", "day_length"),
    [
        # cos(hour angle) = (sin(-0.833) - sin(50) sin(d)) / (cos(50) cos(d))
        # with the declination d of the solstice; the day lasts twice the
        # hour angle, at 15 degrees per hour: 16 h 22 min and 8 h 04 min.
        (JUNE_SOLSTICE, timedelta(hours=16, minutes=22)),
        (DECEMBER_SOLSTICE, timedelta(hours=8, minutes=4)),
    ],
)
def test_length_of_the_day_on_the_solstices(day: date, day_length: timedelta) -> None:
    """Sunset minus sunrise is the length of the day of the sunrise equation."""
    sunrise = ROUND_POINT.sunrise(day)
    sunset = ROUND_POINT.sunset(day)

    assert sunrise is not None
    assert sunset is not None
    assert abs((sunset - sunrise) - day_length) < THREE_MINUTES
    assert sunrise.date() == sunset.date() == day
    assert sunrise.tzinfo == BERLIN_ZONE


@pytest.mark.parametrize("height", [0.0, 500.0, 1000.0])
@pytest.mark.parametrize("elevation", [10.0, 30.0])
def test_a_passage_agrees_with_the_position(height: float, elevation: float) -> None:
    """When the port says the sun passes 10 degrees, its elevation is 10 degrees.

    Also for an observer above sea level: the dip of the horizon counts for
    sunrise and sunset only, never for a passage.
    """
    sun = AstralSun(50.0, 10.0, height, "Europe/Berlin")
    for rising in (True, False):
        passage = sun.elevation_reached(JUNE_SOLSTICE, elevation, rising=rising)

        assert passage is not None
        assert passage.date() == JUNE_SOLSTICE
        assert (
            abs(sun.position(passage).elevation - elevation) < A_TWENTIETH_OF_A_DEGREE
        )
    upwards = sun.elevation_reached(JUNE_SOLSTICE, elevation, rising=True)
    downwards = sun.elevation_reached(JUNE_SOLSTICE, elevation, rising=False)
    assert upwards is not None
    assert downwards is not None
    assert upwards < downwards


def test_a_passage_of_the_horizon_agrees_within_a_tenth_of_a_degree() -> None:
    """At 0 degrees ``astral`` applies its refraction regimes differently.

    The two functions of the library agree within about a tenth of a degree
    there, at every height of the observer; above the horizon they agree
    within a few hundredths (the test above).
    """
    for height in (0.0, 1000.0):
        sun = AstralSun(50.0, 10.0, height, "Europe/Berlin")
        passage = sun.elevation_reached(JUNE_SOLSTICE, 0.0, rising=True)

        assert passage is not None
        assert abs(sun.position(passage).elevation) < A_TENTH_OF_A_DEGREE


def test_the_height_of_the_observer_moves_sunrise_but_not_a_passage() -> None:
    """The dip of the horizon: an earlier sunrise, the same passage."""
    at_sea = ROUND_POINT
    on_the_hill = AstralSun(50.0, 10.0, 1000.0, "Europe/Berlin")

    assert on_the_hill.sunrise(JUNE_SOLSTICE) != at_sea.sunrise(JUNE_SOLSTICE)
    assert on_the_hill.elevation_reached(
        JUNE_SOLSTICE, 10.0, rising=True
    ) == at_sea.elevation_reached(JUNE_SOLSTICE, 10.0, rising=True)
    assert on_the_hill.position(local(JUNE_SOLSTICE, 12)) == at_sea.position(
        local(JUNE_SOLSTICE, 12)
    )


def test_a_passage_the_sun_never_makes_is_none() -> None:
    """On the December solstice the sun at 50 north stays below 20 degrees."""
    assert ROUND_POINT.elevation_reached(DECEMBER_SOLSTICE, 20.0, rising=True) is None
    assert ROUND_POINT.elevation_reached(DECEMBER_SOLSTICE, 20.0, rising=False) is None
    assert ROUND_POINT.elevation_reached(JUNE_SOLSTICE, 20.0, rising=True) is not None


def test_polar_night_and_polar_day() -> None:
    """At 80 north the sun neither rises nor sets on either solstice."""
    for day in (DECEMBER_SOLSTICE, JUNE_SOLSTICE):
        assert POLAR_POINT.sunrise(day) is None
        assert POLAR_POINT.sunset(day) is None
    winter_noon = POLAR_POINT.position(
        datetime(2026, 12, 21, 12, tzinfo=ZoneInfo("Europe/Oslo"))
    )
    summer_midnight = POLAR_POINT.position(
        datetime(2026, 6, 21, 0, tzinfo=ZoneInfo("Europe/Oslo"))
    )

    assert winter_noon.elevation < 0
    assert summer_midnight.elevation > 0
    # The polar night reaches no elevation above the horizon; in the polar day
    # the sun still climbs and descends, so a passage of 20 degrees exists.
    assert POLAR_POINT.elevation_reached(DECEMBER_SOLSTICE, 20.0, rising=True) is None
    assert POLAR_POINT.elevation_reached(JUNE_SOLSTICE, 20.0, rising=True) is not None
    assert POLAR_POINT.elevation_reached(JUNE_SOLSTICE, 20.0, rising=False) is not None


@pytest.mark.parametrize(
    ("day", "offset"),
    [
        # The clocks change at night, before the sunrise of the same date.
        (CLOCKS_FORWARD, timedelta(hours=2)),
        (CLOCKS_BACK, timedelta(hours=1)),
    ],
)
def test_the_day_of_a_clock_change(day: date, offset: timedelta) -> None:
    """Sunrise and sunset carry the offset that holds after the change."""
    before = day - timedelta(days=1)
    sunrise = ROUND_POINT.sunrise(day)
    sunset = ROUND_POINT.sunset(day)
    sunrise_before = ROUND_POINT.sunrise(before)

    assert sunrise is not None
    assert sunset is not None
    assert sunrise_before is not None
    assert sunrise.utcoffset() == offset
    assert sunset.utcoffset() == offset
    assert sunrise.date() == sunset.date() == day
    # As instants two sunrises are about a day apart; on the clock they differ
    # by about an hour, because the clock moved between them. (Python subtracts
    # two datetimes of the same zone object by their wall-clock reading, so
    # the instants are compared in UTC.)
    as_instants = sunrise.astimezone(UTC) - sunrise_before.astimezone(UTC)
    assert abs(as_instants - timedelta(days=1)) < THREE_MINUTES
    offset_before = sunrise_before.utcoffset()
    assert offset_before is not None
    on_the_clock = sunrise.replace(tzinfo=None) - sunrise_before.replace(tzinfo=None)
    expected = timedelta(days=1) + offset - offset_before
    assert abs(on_the_clock - expected) < THREE_MINUTES


def test_a_date_is_a_local_date_and_not_a_date_in_utc() -> None:
    """The sunrise of a local date can lie on another calendar date in UTC."""
    east = AstralSun(-40.0, 175.0, 0.0, "Pacific/Auckland")
    west = AstralSun(20.0, -155.0, 0.0, "Pacific/Honolulu")
    day = date(2026, 1, 10)
    sunrise_east = east.sunrise(day)
    sunset_west = west.sunset(day)

    assert sunrise_east is not None
    assert sunset_west is not None
    assert sunrise_east.date() == day
    assert sunrise_east.astimezone(UTC).date() == day - timedelta(days=1)
    assert sunset_west.date() == day
    assert sunset_west.astimezone(UTC).date() == day + timedelta(days=1)


def test_a_zone_a_day_ahead_of_its_sun_still_gets_the_event_of_its_date() -> None:
    """A made-up point at 170 west in a zone at UTC+14: the clock runs a day ahead.

    ``astral`` computes a transit for a calendar date in UTC around the solar
    day of that date; here every event falls on the next local date, so the
    port has to look at the neighbouring UTC date to serve the local one.
    """
    ahead = AstralSun(0.0, -170.0, 0.0, "Etc/GMT-14")
    day = date(2026, 1, 10)
    sunrise = ahead.sunrise(day)
    sunset = ahead.sunset(day)
    passage = ahead.elevation_reached(day, 30.0, rising=False)

    assert sunrise is not None
    assert sunset is not None
    assert passage is not None
    assert sunrise.date() == sunset.date() == passage.date() == day
    assert sunrise < passage < sunset
    assert sunrise.astimezone(UTC).date() == day - timedelta(days=1)


def test_an_elevated_observer_sees_the_sun_earlier() -> None:
    """A location above sea level has a lower horizon and an earlier sunrise."""
    high = AstralSun(50.0, 10.0, 1000.0, "Europe/Berlin")
    at_sea = ROUND_POINT.sunrise(JUNE_SOLSTICE)
    on_the_hill = high.sunrise(JUNE_SOLSTICE)

    assert at_sea is not None
    assert on_the_hill is not None
    assert on_the_hill < at_sea


def test_naive_datetimes_are_refused() -> None:
    """A time without a zone would be read in the zone of the machine."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ROUND_POINT.position(datetime(2026, 6, 21, 12))  # noqa: DTZ001
    # A datetime is a date in Python's eyes, but not a local date of the port.
    with pytest.raises(TypeError, match="local date"):
        ROUND_POINT.sunrise(local(JUNE_SOLSTICE, 12))
    with pytest.raises(TypeError, match="local date"):
        ROUND_POINT.elevation_reached(local(JUNE_SOLSTICE, 12), 5.0, rising=True)


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ((91.0, 10.0, 0.0, "Europe/Berlin"), "latitude"),
        ((50.0, 181.0, 0.0, "Europe/Berlin"), "longitude"),
        ((float("nan"), 10.0, 0.0, "Europe/Berlin"), "latitude"),
        ((50.0, 10.0, float("inf"), "Europe/Berlin"), "elevation"),
        ((50.0, 10.0, 0.0, "Nowhere/Example"), "time zone"),
    ],
)
def test_an_impossible_location_is_refused(
    arguments: tuple[float, float, float, str], message: str
) -> None:
    """Latitude, longitude, elevation and the zone name are validated once."""
    with pytest.raises(ValueError, match=message):
        AstralSun(*arguments)


def test_wrong_types_are_refused() -> None:
    """Booleans and text are not numbers; the zone is a name; rising is a flag."""
    with pytest.raises(TypeError):
        AstralSun(True, 10.0, 0.0, "Europe/Berlin")
    with pytest.raises(TypeError):
        AstralSun(50.0, 10.0, 0.0, "")
    with pytest.raises(TypeError):
        ROUND_POINT.position("noon")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ROUND_POINT.sunrise("2026-06-21")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        ROUND_POINT.elevation_reached(JUNE_SOLSTICE, 5.0, rising=1)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="finite"):
        ROUND_POINT.elevation_reached(JUNE_SOLSTICE, float("nan"), rising=True)


def test_the_almanac_of_the_schedule_is_built_through_the_port() -> None:
    """``build_sun_almanac`` asks this port like any other implementation."""
    window = config(
        workday=DayTriggers(
            elevation_trigger(10.0, (time(5, 0), time(9, 0))), fixed(20, 0)
        )
    )
    at = local(JUNE_SOLSTICE, 12)
    almanac = build_sun_almanac(window, at, ROUND_POINT)

    assert isinstance(almanac, SunAlmanac)
    assert len(almanac.days) == ALMANAC_DAYS_BEFORE + 1 + ALMANAC_DAYS_AHEAD
    today = almanac.day(JUNE_SOLSTICE)
    assert today is not None
    assert today.sunrise == ROUND_POINT.sunrise(JUNE_SOLSTICE)
    assert today.sunset == ROUND_POINT.sunset(JUNE_SOLSTICE)
    # At 12:00 on the clock the sun is still climbing towards its 63 degrees.
    assert abs(today.noon_elevation - 59.0) < HALF_A_DEGREE * 2
    passage = today.passage(10.0, rising=True)
    assert passage is not None
    assert passage.at == ROUND_POINT.elevation_reached(JUNE_SOLSTICE, 10.0, rising=True)
    assert window.schedule.workday.morning.kind is TriggerKind.ELEVATION
