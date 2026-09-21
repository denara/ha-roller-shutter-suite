# The schedule

The schedule is the lowest layer of the arbiter: while it is switched on it always has an opinion, so a window never lacks a target. It lives in `custom_components/roller_shutter_suite/core/schedule/` and implements section 6 of the [domain design specification](../architecture.md). This page says how, and it records the points where the specification left a choice. The data types it builds on are described in [the core model](core-model.md), the arbiter it plugs into in [the arbiter](arbiter.md). For users, the same rules are explained in [the daily routine](../features/daily-routine.md).

| Module | Content |
|---|---|
| `core/model/schedule.py` | the settings of the schedule as values: `Trigger`, `DayTriggers`, `ScheduleTargets`, `ScheduleSettings`, and the two rules over several settings |
| `core/model/almanac.py` | `SunAlmanac`: the answers of the sun port that a recompute may look at |
| `core/schedule/local_time.py` | local wall-clock times as instants, including the two days of a clock change |
| `core/schedule/sun.py` | where sun times come from: the sun port or the almanac; `build_sun_almanac` |
| `core/schedule/triggers.py` | the instant of one trigger on one date: kind, random offset, clamps |
| `core/schedule/day_types.py` | the day type from the inputs, and reading an on/off or a numeric source without guessing |
| `core/schedule/layer.py` | `evaluate_schedule`, the layer `schedule_layer` with its registration `SCHEDULE_LAYER`, and `schedule_state_after` |

Import from the package: `from custom_components.roller_shutter_suite.core.schedule import evaluate_schedule`.

## The layer, and how it gets sun times without asking a port

A layer of the arbiter is a function of the window configuration and the world snapshot, and a recompute asks no port. The schedule needs sun times for several dates and, for the random offset, the seed of the installation. Both reach it as data, the way the clock port reaches a recompute as `snapshot.time`:

- `WorldSnapshot.almanac` is a `SunAlmanac`: per local date sunrise, sunset, the elevation of the sun at local noon, and the passage of every elevation that an elevation trigger of the window names. `build_sun_almanac(config, time, sun_port)` asks the port and writes the answers down. It covers yesterday (`ALMANAC_DAYS_BEFORE`: before today's morning trigger, the night began with yesterday's evening) to seven days ahead (`ALMANAC_DAYS_AHEAD`: the next planned action is searched on a week and a day).
- `WorldSnapshot.installation_seed` is the seed from the storage port.

**Obligation for the block that builds snapshots (H02):** call `build_sun_almanac` whenever a snapshot is built, and build it again when the local date or the settings of the schedule change.

**Missing data is never guessed.** Without an almanac, with an almanac that lacks a needed date or passage, or without a seed while a random offset is configured, `schedule_layer` has no opinion, with the reason `input_unavailable`, and nothing is persisted. "The sun does not rise on this day" is an answer of the port and stands in the almanac; it is not missing data.

```python
SCHEDULE_LAYER = LayerRegistration(
    Layer.SCHEDULE, schedule_layer, function=FunctionId.SCHEDULE
)
```

`SCHEDULE_LAYER` is part of `FEATURE_LAYERS`, so `build_arbiter()` contains it.

- The layer only reads. `schedule_state_after(config, snapshot)` returns the window state with what the schedule has to remember; the runtime persists it after a recompute.
- With `schedule_enabled` off the layer has no opinion, with the reason `not_configured` (`SCHEDULE_NOT_CONFIGURED`).
- If a faulty stored setting has paused the function `schedule` for the window (`WindowConfig.disabled_functions`), the arbiter does not call the layer at all and records `function_disabled_by_fault`. The layer does not look at that set. `schedule_state_after` leaves the state alone in both cases.
- The day wish only raises and the night wish only lowers: the wish states its direction, and the direction constraint of the arbiter enforces it. The schedule reads no capability of the window.
- **The trigger of the wish** (`Wish.triggered_at`) is `part_of_day_since`: the instant at which the current part of the day really began, as a clamp, an offset to the sun, the random offset, the day type or the brightness moved it, and never the first evaluation that noticed it. After a restart shortly after a boundary, a last own comfort movement at or after that boundary was its answer, so the wish is not fresh and the minimum interval of motor protection holds it; equal instants count as not fresh.

## One pure function

```python
result = evaluate_schedule(
    window, snapshot
)  # as a recompute runs: almanac and seed of the snapshot
result = evaluate_schedule(
    window, snapshot, sun_port, seed=seed
)  # as the simulation may run
```

The settings are `window.schedule`. Both ways give exactly the same result, because the almanac is filled with the port's answers; a test compares them across both clock changes and across midnight. The function raises `ScheduleInputMissingError` if a needed answer is missing. It reads no clock, computes nothing astronomical and keeps nothing between two calls. The same arguments give the same `ScheduleResult`:

| Field | Meaning |
|---|---|
| `wish` | the wish of the schedule layer: by day the morning position with `raise_only` and `schedule_day`, by night the evening position with `lower_only` and `schedule_night`; its trigger is `part_of_day_since` |
| `evaluated_at` | the time of the snapshot as an instant in UTC |
| `part_of_day` | `day` or `night` |
| `part_of_day_since` | the instant at which the current part of the day really began. Before today's morning trigger it is yesterday's evening, which is why yesterday's latch and brightness instant are kept until the morning; without them it is computed with the day of the week |
| `morning_trigger`, `evening_trigger` | today's triggers as instants in UTC; the evening trigger is the effective one |
| `evening_by_brightness` | whether the brightness began this evening before the time did |
| `day_type`, `day_type_latched`, `day_type_reason` | today's day type, whether it is fixed for the date, and `day_type_fallback` while the day of the week stands in for an input without a value |
| `summer`, `season_reason` | the season the evening position was chosen by (`None` without a season source and without dates), and `input_held_last_known`, `input_unavailable` or `input_unknown` when it is not a fresh value |
| `brightness_reason` | why the brightness source gives no value at the moment |
| `next_action` | the next planned action: instant in UTC, target, reason |
| `recheck_at` | an instant at which the window has to be evaluated again although no planned action is due. It lies strictly after `evaluated_at`, or it is none; the result type refuses anything else. A minimum distance between such wake-ups is the business of the Home Assistant layer (block H02) |
| `state` | the persisted window state with what the schedule has to remember |

## State-based, nothing is replayed

The part of the day is a function of the time: it is `day` from the morning trigger of the local date up to its evening trigger, and `night` otherwise. The function never asks whether a trigger "was seen". After a restart, a pause or a week without a single evaluation it states what applies now, and the direction of the wish keeps that safe: the day target only raises, the night target only lowers. The arbiter's direction constraint enforces the direction; the schedule only states it.

The night between two dates is one part of the day. **Which** part of the day applies needs nothing from yesterday: before today's morning trigger it is night, whatever yesterday was. **Since when** it applies does: the night began with yesterday's evening, which is why yesterday's latch and brightness instant are kept until the morning. A core that starts with no persisted state at all computes the start of that night with the day of the week instead, so during the night before the morning trigger `triggered_at` can differ from that of a long-running core, while the wish itself is identical. With persisted state it is exact. The consequence is limited to the "fresh wish" rule of motor protection for that one night.

Three facts are persisted, because they cannot be derived from the present: the latched day type, the last known season, and the two instants of the brightness trigger. A freshly started core with the same persisted state gives the same answer as one that ran for days; a test steps through a week and compares the two at every hour.

## Triggers and clamps

Per day type, morning and evening each have one `Trigger`:

| Kind | Moment | Clamps |
|---|---|---|
| `fixed_time` | a local time (`time`) | ignored |
| `sun_event` | sunrise (morning) or sunset (evening) plus `offset_minutes`, a signed whole number of minutes within ±720 | apply |
| `elevation` | the sun passes `elevation`, upwards (morning) or downwards (evening) | apply |

Every field of a trigger always has a value, because only an optional reference can be "none" in the settings registry. Which fields count depends on the kind; a field of another kind is checked on its own and otherwise ignored, so the kind can be switched without clearing what was entered before. Whether the clamps limit a trigger is said in one place, `Trigger.clamps_apply`: they limit the two kinds that depend on the sun, and a fixed time ignores them. "Not before" of the evening trigger bounds the brightness trigger for every kind.

The instant of a trigger is built in a fixed order: the moment of the kind, plus the random offset, then "not before" and "not after" where they apply, and last the limits of the local date itself, so a trigger always lies on its own date.

**A moment that never comes.** If the sun does not rise, does not set, or never passes the elevation on a date, a clamp decides, and **the side on which the sun stays all day chooses it**. The threshold is the horizon for sunrise and sunset and the configured elevation for an elevation trigger; the elevation of the sun at local noon (`SunDay.noon_elevation`, asked of the sun port) tells the side.

| The sun stays | Morning trigger | Evening trigger |
|---|---|---|
| below the threshold: the **dark side** (the polar night; a December day on which "20 degrees" is never reached) | "not after": the morning does not come by itself, open late | "not before": it has been "below" all day, close early |
| above the threshold: the **bright side** (the polar day) | "not before": the morning has begun already | "not after": the evening does not come by itself |

A noon elevation that equals the threshold exactly counts as the dark side. All of this is an answer of the sun port, not missing data: the port returns no time, the almanac records "none on this date" (`SunDay.sunrise` is `None`, `ElevationPassage.at` is `None`), and the layer has an opinion. Missing data is something else: a date or a passage that is not in the almanac at all (`SunAlmanac.day(...)` or `SunDay.passage(...)` returns `None`), which makes the layer step aside with `input_unavailable`. Both states survive `to_data()` and `from_data()`.

This is what the clamps of the two kinds that depend on the sun are for: a date never lacks a trigger. Such a trigger gets no random offset, because it is on a clamp already.

**Two rules span several settings.** For a kind that depends on the sun, "not before" must not lie after "not after". And per day type the latest morning (its "not after", or its fixed time) must lie before the earliest evening (its "not before", or its fixed time), so every date has a part `day` and a part `night`. `WindowConfig` raises both as `SettingsCombinationError` with exactly the flat keys they concern (for the second rule the two kinds and the two values in use), after every single value of the window has been checked; the built-in defaults satisfy both. A random offset can still swap two fixed times that are set seconds apart; the evening is then taken at the morning, the date has no part `day`, and the next planned action is found on a later date.

## Local time and clock changes

All instants are compared in UTC. Python compares two aware datetimes that share a zone object by their wall-clock reading, which is wrong in the repeated hour of a clock change.

A local time (a fixed time, a clamp, local midnight) becomes an instant by a rule that concerns only the times inside the skipped or the repeated hour:

- A time that does not exist (clocks set forward) moves forward by the length of the gap: with a change from 02:00 to 03:00, "02:30" happens at 03:30.
- A time that exists twice (clocks set back) means its first occurrence. At the second pass of 02:15, a morning trigger of 02:30 has passed already.
- Every other time is simply that local time. A trigger at 07:00 runs at 07:00 on the clock of that day, on both days of a change; a test says so.

This is the usual behavior for such times, and it is what Python yields for a wall-clock time with `fold=0`. No part of the day is skipped or doubled; a test walks through both clock changes of a named zone in steps of five minutes and counts the changes.

The local zone is the zone of `WorldSnapshot.time`. A naive datetime, from the snapshot or from the sun port, is refused: it would be read in the zone of the machine, and that is a clock the core must not look at.

## Day types and the latch

The inputs are an optional workday source (on = workday) and an optional holiday source (on = public holiday):

1. Holiday source on: `holiday`. It decides alone, whatever the workday source says or lacks.
2. Otherwise workday source on: `workday`, off: `weekend`.
3. No workday source: Monday to Friday `workday`, Saturday and Sunday `weekend`.

A source that is unknown, unavailable, absent from the snapshot or not a boolean has no value. Nothing turns it into "off".

The day type of a date is latched (`WindowState.latched_day_types`):

- **The day type latches at the first boundary between parts of the day of the date, which is the morning trigger, and not before.** A workday sensor is updated at midnight or shortly after it; an evaluation at 00:00:10 may still see the value of yesterday, and it must not write that down for the whole day.
- Until then the day type is a preview, and nothing is persisted for the date: it follows the inputs, or rule 3 with `day_type_fallback` while an input has no value, and it may correct itself with every evaluation. The morning trigger and the next planned action follow the preview.
- The first evaluation at or after the morning trigger of the preview fixes the day type for the date. A source that changes later in the day moves nothing.
- If an input has no value at that moment, rule 3 is latched with `LatchedDayType.fallback` set. The result keeps reporting `day_type_fallback` for the rest of the date, and an input that comes back cannot move the morning trigger after the fact.

A core that is started in the middle of the day finds no latch for the date and sets it at once, from the inputs if they have a value, because the morning trigger has passed. The fallback mark is what tells this case from "an input came back too late". The price is small and stated here: if no evaluation at all takes place between the morning trigger and the return of the input, the return is treated like a start in the middle of the day. The runtime evaluates at every planned action, so this takes a core that was not running.

The schedule sets the latch of today only. It keeps a latch for tomorrow if another part of the system has set one and uses it for the next planned action. Until the latch of today is set, the latch of yesterday is kept in its place, because the night that is still running began with the evening trigger of yesterday (`part_of_day_since`). Every other date is dropped.

## The evening by brightness

With a brightness source, the evening also begins when the brightness has been below its threshold for the configured time. **The threshold (`schedule_brightness_threshold`) is in lux**, and the source has to report the outdoor brightness in lux; the key carries no unit, its documented meaning does. "For the configured time" is measured with the time of the snapshot, never with a clock: `WindowState.brightness_below_since` is the time of the first evaluation that saw the value below the threshold, and it is dropped by a value at or above the threshold.

The trigger holds only inside the clamps: not before "not before" of the evening trigger, and only ahead of the time-based evening trigger, which never lies after "not after". "Not before" counts here for every kind of evening trigger, also for a fixed time. If it has been dark since noon, the evening begins at "not before".

The instant at which the brightness began the evening is persisted as `WindowState.evening_brightness_at` and counts for the local date it lies on. It is kept until the morning trigger of the next date, because until then it is the start of the night that is running. Without it the schedule would not be state-based: the headlights of a car or a source that drops out would bring the day back, and the day target would raise the shutter again.

**Missing data is not good news.** A brightness source without a value is not "dark": `brightness_below_since` is dropped, nothing is triggered, and `brightness_reason` says why. It does not block anything either: the time-based evening trigger is not affected, and an evening that the brightness has begun already stays.

While the delay is running, `recheck_at` names the instant at which it will be over, because a source that does not change causes no evaluation by itself.

## Season

The evening position is seasonal if a season source is set or `schedule_summer_by_date` is on; the summer position always has a value. The season comes from the season source (on = summer); while that source has no value, from its last known value (`WindowState.held_season`, without a time limit, reported as `input_held_last_known`); if there is none, from the date range if `schedule_summer_by_date` is on; and otherwise there is one evening position, with the reason why the source counts for nothing. The date range includes both days and may run across the turn of the year.

The held value is renewed when the source reports another value than the held one, not at every evaluation. Nothing depends on its age, and a state that does not change needs no write.

## Random offset

`random_offset(seed, window_id, day, edge, maximum)` hashes its arguments (SHA-256) into a whole number of seconds, uniform within plus and minus the range. It is therefore stable within a day, different between windows, dates and the two triggers, reproducible in tests and in the simulation, and it survives a restart. The range is 0 (off, the default) to 30 minutes. The offset is applied before the clamps, so a trigger never leaves them.

## Next planned action

The first change of the part of the day after the time of the snapshot: today's morning or evening trigger, otherwise the morning trigger of the next date that has a part `day`, searched over a week and a day. It works across midnight and across a change of the day type. A later date counts with its latched day type if it has one, otherwise with the day of the week. With a workday or holiday source that is a forecast: once the date has begun it follows the preview of the inputs, and it is final when the day type latches at the morning trigger. A forecast that named too early a time corrects itself at the planned instant, when the evaluation finds that the morning has not come yet; one that named too late a time is corrected by the first evaluation of the new date that sees the inputs of that date.

The brightness is not part of the forecast. `evening_trigger` and `next_action` name the time-based evening until the brightness has begun it.

## Doors kept open

- **Conditional morning opening.** `morning_condition_fulfilled(window, snapshot)` is where the condition of the morning opening will be read from `WindowConfig.morning_condition_source`. It returns true, whatever the source reports.
- **Profiles.** The targets are looked up through the profile key of the window (`ScheduleSettings.targets_for(window.schedule_profile)`). The key has one value.

## Settings

Every setting of the schedule is a flat field of `WindowConfig`, so that each is inherited on its own, and one entry of `WINDOW_SETTINGS` with the function `schedule`; `WindowConfig.schedule` is the read-only view over them, a `ScheduleSettings`. The value rules live in the model (`core/model/schedule.py`); the stored form is read by the shared readers of `core/settings`. The built-in defaults stand in one place, the block "The built-in defaults of the schedule" at the top of `core/model/window.py`; the registry reads them from the fields.

The 36 trigger settings are generated, not written out: `schedule_<day type>_<edge>_<field>` for the day types `workday`, `weekend`, `holiday`, the edges `morning`, `evening`, and the fields of `Trigger`. `schedule_trigger_keys()` is that list, and the tests walk it the same way.

| Key | Kind | Reader | Default |
|---|---|---|---|
| `schedule_enabled` | boolean | `as_bool` | on |
| `schedule_<day type>_<edge>_kind` | enumeration | `as_enum(TriggerKind)` | morning `fixed_time`, evening `sun_event` |
| `schedule_<day type>_<edge>_time` | time | `as_time` | morning 07:00 on workdays and 08:30 on weekends and holidays, evening 20:00 |
| `schedule_<day type>_<edge>_offset_minutes` | number | whole number, may be negative | 0 |
| `schedule_<day type>_<edge>_elevation` | number | finite number | 0 |
| `schedule_<day type>_<edge>_not_before` | time | `as_time` | morning 06:00, evening 17:00 |
| `schedule_<day type>_<edge>_not_after` | time | `as_time` | morning 09:00, evening 22:00 |
| `schedule_morning_position`, `schedule_evening_position`, `schedule_evening_position_summer` | number | position, 0 to 100 | 100, 0, 0 |
| `schedule_workday_source`, `schedule_holiday_source`, `schedule_season_source`, `schedule_brightness_source` | optional reference | `as_str` | none |
| `schedule_summer_by_date` | boolean | `as_bool` | off |
| `schedule_summer_first_day`, `schedule_summer_last_day` | day of the year | `as_day_of_year` | 05-01, 09-30 |
| `schedule_brightness_threshold` | number, **in lux** | finite number | 50 lux |
| `schedule_brightness_delay` | duration | `as_duration` | 10 minutes |
| `schedule_random_offset` | duration | `as_duration`, at most 30 minutes | 0 |

`schedule_profile` and `morning_condition_source` existed before and belong to the schedule too.

The function `schedule` pauses on a fault: a stored value that cannot be read, a value the window refuses, or a combination that one of the two rules refuses pauses the schedule for exactly the windows for which the faulty value would have been the effective one. A window with a sound own value for that key is not reached. Nothing falls back to a time or a position that the user did not choose.
