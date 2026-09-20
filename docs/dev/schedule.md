# The schedule

The schedule is the lowest layer of the arbiter: it always has an opinion, so a window never lacks a target. It lives in `custom_components/roller_shutter_suite/core/schedule/` and implements section 6 of the [domain design specification](../architecture.md). This page says how, and it records the points where the specification left a choice. The data types it builds on are described in [the core model](core-model.md). For users, the same rules are explained in [the daily routine](../features/daily-routine.md).

| Module of `schedule` | Content |
|---|---|
| `settings` | the resolved settings: triggers per day type, targets per profile key, sources, season, brightness, random offset |
| `local_time` | local wall-clock times as instants, including the two days of a clock change |
| `triggers` | the instant of one trigger on one date: kind, random offset, clamps |
| `day_types` | the day type from the inputs, and reading an on/off or a numeric source without guessing |
| `layer` | `evaluate_schedule`: the wish, the part of the day, the day type with its latch, the next planned action |

Import from the package: `from custom_components.roller_shutter_suite.core.schedule import evaluate_schedule`.

## One pure function

```python
result = evaluate_schedule(settings, window, snapshot, sun, seed=seed)
```

| Argument | Meaning |
|---|---|
| `settings` | `ScheduleSettings`, the resolved settings of this window |
| `window` | `WindowConfig` of the model: the window identifier (for the random offset), the profile key of the schedule, the condition input of the morning opening |
| `snapshot` | `WorldSnapshot`: the time, the source values, the persisted window state |
| `sun` | the sun port |
| `seed` | the installation's seed for random offsets, from the storage port |

The function reads no clock, computes nothing astronomical and keeps nothing between two calls. The same arguments give the same `ScheduleResult`:

| Field | Meaning |
|---|---|
| `wish` | the wish of the schedule layer: by day the morning position with `raise_only` and `schedule_day`, by night the evening position with `lower_only` and `schedule_night` |
| `part_of_day` | `day` or `night` |
| `morning_trigger`, `evening_trigger` | today's triggers as instants in UTC; the evening trigger is the effective one |
| `evening_by_brightness` | whether the brightness began this evening before the time did |
| `day_type`, `day_type_latched`, `day_type_reason` | today's day type, whether it is fixed for the date, and `day_type_fallback` while the day of the week stands in for an input without a value |
| `summer`, `season_reason` | the season the evening position was chosen by (`None` without a seasonal setup), and `input_held_last_known`, `input_unavailable` or `input_unknown` when it is not a fresh value |
| `brightness_reason` | why the brightness source gives no value at the moment |
| `next_action` | the next planned action: instant in UTC, target, reason |
| `recheck_at` | an instant at which the window has to be evaluated again although no planned action is due |
| `state` | the persisted window state with what the schedule has to remember; the caller persists it |

A window without schedule settings gets the constant `SCHEDULE_NOT_CONFIGURED`, a wish without an opinion and with the reason `not_configured`.

## State-based, nothing is replayed

The part of the day is a function of the time: it is `day` from the morning trigger of the local date up to its evening trigger, and `night` otherwise. The function never asks whether a trigger "was seen". After a restart, a pause or a week without a single evaluation it states what applies now, and the direction of the wish keeps that safe: the day target only raises, the night target only lowers. The arbiter's direction constraint enforces the direction; the schedule only states it.

The night between two dates is one part of the day. It needs nothing from yesterday: before today's morning trigger it is night, whatever yesterday was.

Three facts are persisted, because they cannot be derived from the present: the latched day type, the last known season, and the two instants of the brightness trigger. A freshly started core with the same persisted state gives the same answer as one that ran for days; a test steps through a week and compares the two at every hour.

## Triggers and clamps

Per day type, morning and evening each have one `Trigger`:

| Kind | Moment | Clamps |
|---|---|---|
| `fixed_time` | a local time | optional |
| `sun_event` | sunrise (morning) or sunset (evening) plus an offset | both mandatory |
| `elevation` | the sun passes an elevation, upwards (morning) or downwards (evening) | both mandatory |

The instant of a trigger is built in a fixed order: the moment of the kind, plus the random offset, then "not before" and "not after", and last the limits of the local date itself, so a trigger always lies on its own date.

**A moment that never comes.** If the sun port has no sunrise, no sunset or no passage of the elevation on a date, the trigger falls on the clamp that lies in its direction. The elevation of the sun at local noon, asked of the sun port, tells the two cases apart:

| At noon the sun is | Morning trigger | Evening trigger |
|---|---|---|
| below the elevation (deep winter, polar night) | "not after": the morning never comes by itself | "not before": the evening has begun already |
| at or above it (polar day) | "not before": the morning has begun already | "not after": the evening never comes by itself |

This is why both clamps are mandatory for the two kinds that depend on the sun: a date never lacks a trigger. Such a trigger gets no random offset, because it is on a clamp already.

`DayTriggers` refuses a pair whose latest morning (its "not after", or its fixed time) does not lie before the earliest evening. A random offset can still swap two fixed times that are set seconds apart; the evening is then taken at the morning, the date has no part `day`, and the next planned action is found on a later date.

## Local time and clock changes

All instants are compared in UTC. Python compares two aware datetimes that share a zone object by their wall-clock reading, which is wrong in the repeated hour of a clock change.

A local time (a fixed time, a clamp, local midnight) becomes an instant by one rule: **it is read with the UTC offset that is valid before the change.**

- A time that exists twice (clocks set back) means its first occurrence. At the second pass of 02:15, a morning trigger of 02:30 has passed already.
- A time that does not exist (clocks set forward) happens as long after the change as it lies inside the skipped hour: with a change from 02:00 to 03:00, "02:30" happens at 03:30.

Both are the same statement: such a time happens as much elapsed time after local midnight as on any other day. No part of the day is skipped or doubled; a test walks through both clock changes of a named zone in steps of five minutes and counts the changes.

The local zone is the zone of `WorldSnapshot.time`. A naive datetime, from the snapshot or from the sun port, is refused: it would be read in the zone of the machine, and that is a clock the core must not look at.

## Day types and the latch

The inputs are an optional workday source (on = workday) and an optional holiday source (on = public holiday):

1. Holiday source on: `holiday`. It decides alone, whatever the workday source says or lacks.
2. Otherwise workday source on: `workday`, off: `weekend`.
3. No workday source: Monday to Friday `workday`, Saturday and Sunday `weekend`.

A source that is unknown, unavailable, absent from the snapshot or not a boolean has no value. Nothing turns it into "off".

The day type of a date is latched (`WindowState.latched_day_types`):

- At the first evaluation of the date at which the inputs the rules need have a value, the day type is fixed for the date. A source that changes later in the day moves nothing.
- While an input has no value, rule 3 stands in, the result carries `day_type_fallback`, and nothing is latched. As soon as the input has a value, the latch is set, as long as the morning trigger of the stand-in has not passed.
- At the first evaluation after that morning trigger has passed without a value, the stand-in itself is latched, with `LatchedDayType.fallback` set. The result keeps reporting `day_type_fallback` for the rest of the date, and an input that comes back cannot move the morning trigger after the fact.

The third step is what tells "an input came back too late" from "the core was started in the middle of the day". In the second case there is no latch at all, and the inputs are used. The price is small and stated here: if no evaluation at all takes place between the morning trigger and the return of the input, the return is treated like a start in the middle of the day. The runtime evaluates at every planned action, so this takes a core that was not running.

The schedule sets the latch of today only. It keeps a latch for tomorrow if another part of the system has set one, uses it for the next planned action, and drops every other date.

## The evening by brightness

With a brightness source, the evening also begins when the brightness has been below its threshold for the configured time. "For the configured time" is measured with the time of the snapshot, never with a clock: `WindowState.brightness_below_since` is the time of the first evaluation that saw the value below the threshold, and it is dropped by a value at or above the threshold.

The trigger holds only inside the clamps: not before "not before" of the evening trigger, and only ahead of the time-based evening trigger, which never lies after "not after". That is why settings with a brightness source require "not before" on every evening trigger. If it has been dark since noon, the evening begins at "not before".

The instant at which the brightness began the evening is persisted as `WindowState.evening_brightness_at` and counts for the local date it lies on. Without it the schedule would not be state-based: the headlights of a car or a source that drops out would bring the day back, and the day target would raise the shutter again.

**Missing data is not good news.** A brightness source without a value is not "dark": `brightness_below_since` is dropped, nothing is triggered, and `brightness_reason` says why. It does not block anything either: the time-based evening trigger is not affected, and an evening that the brightness has begun already stays.

While the delay is running, `recheck_at` names the instant at which it will be over, because a source that does not change causes no evaluation by itself.

## Season

The evening position is seasonal if the targets have a summer position. The season comes from the season source (on = summer); while that source has no value, from its last known value (`WindowState.held_season`, without a time limit, reported as `input_held_last_known`); if there is none, from the date range; and without a date range there is one evening position, with the reason why the source counts for nothing. The date range includes both days and may run across the turn of the year.

The held value is renewed when the source reports another value than the held one, not at every evaluation. Nothing depends on its age, and a state that does not change needs no write.

## Random offset

`random_offset(seed, window_id, day, edge, maximum)` hashes its arguments (SHA-256) into a whole number of seconds, uniform within plus and minus the range. It is therefore stable within a day, different between windows, dates and the two triggers, reproducible in tests and in the simulation, and it survives a restart. The range is 0 (off, the default) to 30 minutes. The offset is applied before the clamps, so a trigger never leaves them.

## Next planned action

The first change of the part of the day after the time of the snapshot: today's morning or evening trigger, otherwise the morning trigger of the next date that has a part `day`, searched over a week and a day. It works across midnight and across a change of the day type. A later date counts with its latched day type if it has one, otherwise with the day of the week. With a workday or holiday source that is a forecast: it becomes final when the date begins and its day type is latched. A forecast that was too late corrects itself at the planned instant, when the evaluation finds that the morning has not come yet; one that was too early is corrected by the first evaluation of the new date.

The brightness is not part of the forecast. `evening_trigger` and `next_action` name the time-based evening until the brightness has begun it.

## Doors kept open

- **Conditional morning opening.** `morning_condition_fulfilled(window, snapshot)` is where the condition of the morning opening will be read from `WindowConfig.morning_condition_source`. It returns true, whatever the source reports.
- **Profiles.** The targets are looked up through the profile key of the window (`ScheduleSettings.targets_for(window.schedule_profile)`). The key has one value.

## Settings and the settings registry

`ScheduleSettings` is the definition of the schedule's settings until the settings registry adopts them. Every leaf is one scalar, so the registry can take them over with one entry per leaf:

| Leaf | Kind of value |
|---|---|
| `Trigger.kind` | enumeration |
| `Trigger.at`, `not_before`, `not_after` | local time |
| `Trigger.offset`, `brightness_delay`, `random_offset` | duration |
| `Trigger.elevation`, `brightness_threshold` | number |
| the three positions of `ScheduleTargets` | position (a whole number from 0 to 100) |
| `workday_source`, `holiday_source`, `season_source`, `brightness_source` | optional reference to a source |
| `summer_first_day`, `summer_last_day` | day of the year (month and day), optional, only together |

A field that belongs to another trigger kind is type-checked and otherwise ignored, so a user can switch the kind without clearing what was entered before.

## Plugging into the arbiter

The arbiter defines how a layer is registered. The schedule does not define a second layer interface; the glue is one small adapter. It needs:

1. the resolved `ScheduleSettings` of the window, or none;
2. the `WindowConfig`, the `WorldSnapshot`, the sun port and the seed from the storage port;
3. to return `SCHEDULE_NOT_CONFIGURED` without settings, otherwise `evaluate_schedule(...).wish`;
4. to hand `result.state` on as the persisted window state of the recompute, and to have the window evaluated again at `result.next_action.at` and at `result.recheck_at`;
5. to expose `part_of_day`, `day_type`, `day_type_reason`, `next_action` and the reasons to the status of the window.
