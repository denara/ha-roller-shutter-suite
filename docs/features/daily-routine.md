# The daily routine

The daily routine opens your shutters in the morning and closes them in the evening. It is the basis of everything else: whenever nothing more important applies (no storm, no shading, no sleep mode), the daily routine decides where a shutter belongs.

**Status: in development.** This page describes the rules the integration follows. The forms in which you enter the settings are being built; their names may differ slightly from the names used here.

## Day and night

The routine knows two parts of the day:

| Part of the day | Begins at | The shutter is sent to | Direction |
|---|---|---|---|
| Day | the morning trigger | the morning position, for example fully open | it is only ever raised |
| Night | the evening trigger | the evening position, for example fully closed | it is only ever lowered |

The direction matters more than it seems:

- **In the morning, a shutter is only raised.** If it is already higher than the morning position, it stays where it is.
- **In the evening, a shutter is only lowered.** If it is already lower than the evening position, it stays where it is. A shutter you closed completely in the afternoon is not raised to an evening position of 30 %.

## What you can set

For each **day type** (workday, weekend, public holiday), separately for the morning and the evening:

- **How the time is found:**
  - a **fixed time**, for example 06:30;
  - **sunrise** (morning) or **sunset** (evening), with an offset such as "20 minutes before" or "30 minutes after";
  - a **sun elevation**, for example "when the sun has sunk to 3 degrees below the horizon". An elevation follows the real brightness outside more closely than sunset plus a fixed number of minutes.
- **"Not before" and "not after"**, the two limits for times that depend on the sun. See the next section.

For the window (or inherited from its group):

- the **morning position** and the **evening position**;
- optionally a separate **evening position for the summer**, for example 30 % so that air can get in, while the winter position is fully closed;
- optionally an **outdoor brightness sensor** for the evening, with a threshold and a duration;
- optionally a **random offset** of up to 30 minutes.

For the day types:

- optionally a **workday sensor** (on = workday). Home Assistant's Workday integration provides one.
- optionally a **public holiday sensor** (on = public holiday). A calendar with an all-day event works as well. The integration brings no holiday data of its own.

## Sun times and the two limits

Sunrise in midsummer is before five in the morning, and in midwinter after eight. Nobody wants the bedroom shutter to follow that all the way. That is what the two limits are for:

- **Not before:** however early the sun says so, the trigger waits until this time.
- **Not after:** however late the sun says so, the trigger happens at this time at the latest.

Example: "at sunrise, not before 06:30, not after 08:00".

| Sunrise | The shutter is raised at | Why |
|---|---|---|
| 04:50 (June) | 06:30 | sunrise is earlier than "not before" |
| 07:10 (October) | 07:10 | sunrise lies between the limits |
| 08:20 (December) | 08:00 | sunrise is later than "not after" |

The same works in the evening: "at sunset, not before 17:30, not after 21:30" closes at 17:30 in December and at 21:30 in June, and at sunset in the months between.

Both limits are required for sunrise, sunset and sun elevation. The reason is a case you may never meet: far in the north the sun does not rise at all on some winter days, and an elevation such as "20 degrees above the horizon" is not reached anywhere in central Europe in December. On such a day the trigger falls on the limit that fits the situation. If the sun stays too low, it is dark: the morning happens at "not after", the evening at "not before". If the sun never sinks low enough, it is bright: the morning happens at "not before", the evening at "not after".

The morning always has to come before the evening: the latest possible morning ("not after", or the fixed time) has to lie before the earliest possible evening ("not before", or the fixed time). Settings that violate this are refused.

## Closing earlier when it gets dark

On a day with heavy clouds it gets dark well before the time the sun position suggests. With an outdoor brightness sensor you can let the evening begin earlier: **when the brightness has been below the threshold for the configured duration**, for example below 50 lx for 10 minutes. The duration keeps a short, dark shower from closing the house.

- This only happens **inside the limits**: never before "not before" of the evening. A thunderstorm at noon closes nothing. For this reason every evening trigger needs a "not before" when you use a brightness sensor, also one with a fixed time.
- Once the brightness has begun the evening, it stays evening, even if it gets brighter again or a car's headlights hit the sensor.
- **If the sensor fails**, nothing happens because of it: a sensor without a value is not treated as "dark", so it closes nothing by itself. It does not hold anything up either: the evening begins at its normal time.

## Workdays, weekends and public holidays

The day type decides which pair of times applies:

1. If the public holiday sensor is on, the day is a **public holiday**.
2. Otherwise, if you have a workday sensor: on means **workday**, off means **weekend**.
3. Without a workday sensor: Monday to Friday are workdays, Saturday and Sunday are weekend.

The day type is decided once per day, shortly after midnight, and then kept for that day. If your workday sensor changes its mind at noon, the evening still follows the day type from the morning; otherwise the shutters might move at a moment nobody expects.

**If a sensor has no value** (unavailable or unknown) when the day begins, the integration uses the day of the week for the time being and says so in the window's status (`day_type_fallback`). If the sensor comes back before the morning trigger of that day, its value is used. If it comes back later, the day stays as it began.

School holidays are not part of the first version.

## A little randomness

With a random offset of, say, 15 minutes, each trigger is moved by a random amount of up to 15 minutes earlier or later. Every window gets its own amount, and a new one every day, so the house does not close like clockwork at exactly the same minute. The amount does not change during the day and survives a restart. The offset is applied before the two limits: a trigger never leaves "not before" and "not after". The default is 0, which switches the randomness off.

## Summer and winter

If you set a separate evening position for the summer, the integration needs to know when it is summer:

1. from a **season switch** of your choice (on = summer), for example a helper you flip twice a year or an automation of your own;
2. otherwise from a **date range**, the first and the last day of summer;
3. without either there is just the one evening position.

If the season switch is unavailable, the integration keeps using the last value it saw, for as long as it takes. Nothing but comfort depends on it.

## What happens after a restart

Nothing is "caught up", because nothing can be missed. The routine does not work with events such as "it is 06:30 now, open". It works with a statement that holds at any moment: "it is day, and by day this shutter belongs at the morning position."

- Home Assistant restarts at 07:00, after the morning trigger of 06:30: as soon as the integration runs again, it sees that it is day and raises the shutters that are lower than the morning position.
- Home Assistant was down from 19:00 to 23:00, across the evening trigger: when it is back, it is night, and the shutters are lowered.
- You paused the automation in the afternoon and resume it at 22:00: the same. It is night, the shutters are lowered.

In all three cases a shutter that is already where it belongs, or beyond it in the permitted direction, is not moved.

One consequence is worth knowing. If you lower a shutter by hand during the day, the integration leaves it alone: your manual override holds until the next part of the day by default, which is the evening. If you choose a shorter duration for the override, the routine raises the shutter again when the override ends, because it is still day.

## A workday, step by step

Settings: on workdays the morning is "sunrise, not before 06:30, not after 07:30", the evening is "sun 3 degrees below the horizon, not before 17:00, not after 21:30". Morning position 100 %, evening position 0 %. Random offset 10 minutes. It is a Tuesday in October; sunrise is at 07:41, and the sun reaches 3 degrees below the horizon at 18:52.

| Time | What happens |
|---|---|
| 00:00 | The day type is decided: no holiday, the workday sensor is on. Workday. |
| 00:00–07:30 | Night. The shutter stays closed. The status shows the next planned action: 07:30, 100 %. |
| 07:30 | Sunrise at 07:41 plus this window's random amount of 6 minutes would be 07:47. That is later than "not after", so the morning happens at 07:30. It is day; the shutter is raised to 100 %. |
| 11:00 | Home Assistant is restarted. It is still day, the shutter is at 100 %. Nothing moves. |
| 14:00 | You lower the shutter to 40 % by hand. The integration leaves it alone until the evening. |
| 18:48 | The elevation is reached at 18:52; this window's random amount for the evening is minus 4 minutes. It is night; the shutter is lowered from 40 % to 0 %. |

## A weekend, step by step

Settings: on weekends the morning is a fixed 09:00, the evening is "sunset plus 30 minutes, not before 17:30, not after 22:00". A brightness sensor closes below 50 lx after 10 minutes. No random offset. It is a Saturday in October with heavy clouds; sunset is at 18:20.

| Time | What happens |
|---|---|
| 00:00 | The workday sensor is off: weekend. |
| 07:30 | On a workday the shutters would open now. Today they stay closed until 09:00. |
| 09:00 | It is day; the shutter is raised to the morning position. |
| 17:10 | The brightness drops below 50 lx. It is before 17:30, "not before" of the evening, so the brightness cannot begin the evening yet. |
| 17:30 | It has been darker than 50 lx for more than 10 minutes, and "not before" has come. The evening begins now instead of at 18:50; the shutter is lowered. |
| 17:40 | The clouds open up and the brightness rises to 300 lx. It stays evening. |
| Sunday 00:00 | A new day, again a weekend. The status shows the next planned action: Sunday 09:00. On Sunday evening it will show Monday with the workday time. |

If the brightness sensor had been unavailable that afternoon, the shutter would have been lowered at 18:50, 30 minutes after sunset.

## When the clocks change

On the night the clocks go forward, the hour from 02:00 to 03:00 does not exist; on the night they go back, it exists twice. If a time of your routine lies in that hour, the rule is: it happens as long after midnight as on any other night. "02:30" happens once in either night: at 03:30 new time when the clocks go forward, and at the first 02:30 when they go back. Times outside that hour are not affected; 06:30 is 06:30 on the new clock.

## Good to know

- The next planned action in the window's status is what the routine will ask for. Whether the shutter then moves also depends on everything that ranks higher: a storm, an open window, your manual override, a pause.
- For a day in the future, the status assumes the day type from the day of the week, or the one that is already known. If your holiday sensor turns a Monday into a public holiday, the status corrects itself shortly after midnight.
- The integration sends the shutter to a position. With most actuators the reported position is calculated from run time, so the integration can notice that an actuator did not react, but it cannot know that a curtain has actually arrived.
