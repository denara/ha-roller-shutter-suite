# The runtime

The core decides; the runtime feeds it and calls it. This page describes the Home Assistant side of guardrail 4 on the input side: how the entities a window uses, the time and the sun become a `WorldSnapshot`, when a window is recomputed, and what happens with the decision. The rules themselves are in the [domain design specification](../architecture.md); the data types in [The core model](core-model.md); the evaluation in [The arbiter](arbiter.md) and [The schedule](schedule.md).

| Module | Content |
|---|---|
| `runtime.py` | `SuiteRuntime`: one controller per window of the config entry; add, reload and remove one window; stop all |
| `controller.py` | `WindowController`: the life cycle of one window, the triggers of a recompute, the snapshot, the decision, the state, the status |
| `sources.py` | the source adapter: an entity state or an entity attribute becomes a `SourceValue` |
| `members.py` | the members of a window: cover states become observations |
| `location.py` | the clock port in the named local zone; the observer of the installation and the sun port |
| `storage.py` | the storage port in memory, surviving the reload of the entry |
| `commands.py` | what the runtime remembers when the gate lets a wish through |
| `actuator.py` | the recording actuator that stands in until the block that sends commands exists |

## The life cycle of a window controller

```text
set-up ─► start ─► waiting for members ─► running ─► stop
                          │                  ▲
                          └── members appear ┘
```

1. **Set-up.** `async_setup_entry` builds the ports first: the clock in the named local zone, the sun port from the observer of the installation, the storage. A zone that is not a named one or a missing sun port fails the set-up closed, before any window is looked at. Then it resolves the windows as before (`windows.resolve_entry`), creates the devices and the repair issues, and starts the runtime with the windows that have a configuration.
2. **Start.** `SuiteRuntime.async_add_window` creates the controller of one window and starts it. If that raises, the failure is logged once with the window's name and the type of the exception, the window is listed in `SuiteRuntime.failed`, and every other window is started all the same; nothing propagates out of the set-up of the entry. A window whose configuration the resolver withheld is listed there too (`configuration_withheld`). The controller loads the window's state from the storage (a state that cannot be read is logged and replaced by a fresh one), subscribes to the state changes of its members and the entities of its sources, starts the safety tick, and asks for a first recompute.
3. **Waiting for members.** No decision is made before the members are available. A cover platform that comes up late is normal: the window waits, and when the cover appears the next state change starts it, without a reload. With several members the controller waits until all of them are available, or until `STARTUP_GRACE` has passed since the start and at least one is; from then on a member that is away is the business of the gate ("no member can execute") and is shown in the status. A window whose cover never comes stays in this phase and reports it; the entry is loaded.
4. **Running.** Every trigger leads to a recompute (below). The status carries the decision, the faults, the facts of the schedule, the sources with their values, the commands given and the next wake-up.
5. **Stop.** `async_unload_entry` stops every controller: every listener and timer is cancelled, the debouncer is shut down, and the state is saved. Removing one window stops its controller alone; the listeners and timers of the others are untouched. Reloading one window replaces its controller with a fresh one.

**Every configuration change reloads the whole config entry**, and therefore every window. That is harmless because the runtime state of a window lives in the storage port, not in the controller: the pending own command with its expectation, the dams, a deferral, the latched day type, the held inputs. After the reload the window continues where it was. In this block the storage is in memory (`storage.py`) and survives a reload but not a restart; the block that builds persistence replaces it behind the same port.

## Triggers of a recompute

| Trigger | Mechanism |
|---|---|
| a state change of a member or of an entity a source refers to | `async_track_state_change_event` on the entity IDs of the window |
| a point in time the core asked for | one timer per window, `async_track_point_in_utc_time`, at the earliest of: the end of a deferral (`until`), the upper bound of a re-evaluation (`reevaluate_no_later_than`), the next planned action of the schedule, its recheck (`recheck_at`); and, while waiting for members, the end of the start-up grace |
| the periodic safety tick | `async_track_time_interval` every `SAFETY_TICK`, so a missed event cannot leave a window in the wrong state for long |
| an explicit request | `WindowController.async_request_recompute()` |

Every trigger goes through one `Debouncer` per window (cooldown `COALESCE_SECONDS`, not immediate). A burst of changes therefore yields one recompute after the last of them, and two recomputes of the same window never run at the same time. The price is that a reaction is delayed by up to a second, which is nothing for a shutter.

**Wake-up times cannot form a loop.** A time the core asks for is accepted only if it lies strictly in the future. Otherwise it is moved to `MIN_WAKE_UP_DISTANCE` after now and the fault is logged once (and again only after a sound time was seen in between). Recomputes that come from wake-ups are at least `MIN_WAKE_UP_DISTANCE` apart, so a layer or rule that keeps asking for "now" costs a few recomputes per minute and nothing more. The one constant is the only place that says how far. The status shows the accepted wake-up with its reason.

## The recompute, step by step

1. **Observe the members** (`members.py`). No state or `unavailable` is an unavailable member; `opening` and `closing` are movements; everything else, including `unknown`, is resting. The position is `current_position` if the capability profile says the member reports one and the attribute holds a whole number from 0 to 100; anything else is no position. Dropping reports that carry nothing new, the tracker and manual detection belong to the block that builds the tracking.
2. **Read the sources** (`sources.py`), see below. For every source the controller keeps the value and the time of the first recompute that saw it (`SourceReading.since`), with its own clock; a restored state after a restart counts from the first observation, never from the change time of the entity.
3. **Build the snapshot.** `time` is the clock port's now, in the named local zone. `sun` is the sun port's position. `sources` are the values by their configured reference. `state` is the window's persisted state. `controls` are pause, maintenance lock and operating mode of the three levels and dry-run; until the block that builds the switches exists, the levels are neutral and dry-run is what the subentry says (`runtime.neutral_controls`). `almanac` is the sun almanac of the core (`build_sun_almanac`), built once per local date and settings of the schedule and kept until either changes. `installation_seed` is the seed of the storage port, created once and stored.
4. **Decide.** `Engine.recompute(snapshot)`. Nothing that a layer, a constraint or a gate rule raises leaves the arbiter; what does are the `faults` of the decision, which the controller logs once per change with the window's name, the stage, the place, the function and the type of the exception, never its message, and passes on in the status. An exception outside the safety net (a bug in the adapter itself) is caught by the controller, logged with its traceback, shown as `error` in the status, and the window is evaluated again at the next trigger; no other window is affected.
5. **The state after the decision.** `Engine.state_after` (a take-over, a would-be command in dry-run), then the schedule's state (`evaluate_schedule`, only while the schedule runs for the window: switched on, not paused by a faulty setting, with every input it needs), then the own commands of a send (below). What changed is written to the storage at once, so the latched day type of a date is stored right after the recompute at the morning trigger, not only at shutdown.
6. **Send.** A decision whose gate outcome is `send` names the target of every member. The controller checks dry-run a second time: a window in dry-run sends nothing, with one exception the project owner decided, a fire wish that was sent because the dry-run rule itself raised (`Decision.faults` names the rule). Then it hands every target to the actuator port under a fresh command identifier and writes the command down as the member's last own command, with the class and the reason of the wish; a comfort command also moves the clock of motor protection. That record is what the gate rules about own commands read on the next recompute, and what survives a reload. Until the block that sends commands exists, the actuator is `RecordingActuator`: it records and calls nothing.
7. **The next wake-up.** The earliest of the times listed above, accepted under the loop rule, and the status.

## Sources: an entity state or an entity attribute

A source reference is an entity ID, or an entity ID, `#` and an attribute name:

```text
binary_sensor.example_workday
climate.example_room#current_temperature
```

An entity ID can never contain `#`, so the two forms cannot be confused. The runtime finds the sources of a window in its resolved configuration: every setting of the kind "optional reference" whose value names a source (`window_sources`); "none" and a source that is configured but blind name nothing to read. The key of a source in the snapshot is the reference exactly as configured, because that is the key under which the layers look it up.

What the adapter delivers, and why:

| What Home Assistant has | What the core receives |
|---|---|
| no such entity, or the state `unavailable` | unavailable |
| the state `unknown` (also for an attribute of that entity) | unknown |
| an attribute that is absent or `None`, or a value that is no scalar (a list, a mapping) | unknown |
| the state `on` or `off` | `True` or `False` |
| a state that spells a finite number | that number |
| any other state | the text as it is |
| an attribute that is a boolean, a number or text | that value, unchanged |
| a temperature: a state with a temperature unit, or `current_temperature`, `temperature`, `target_temp_high` and `target_temp_low` of a `climate` entity (which Home Assistant reports in the unit system of the installation) | the value in degrees Celsius |

Nothing is ever turned into a default. What a value means for a layer is decided by the reader of the core, which refuses a value of the wrong kind: text where a number is expected is "unknown" to `read_number`, and the schedule falls back to the day of the week with `day_type_fallback` while a day-type input has no value. A malformed reference is unavailable, and the status shows it.

**To add a source** to a feature: register the setting as an optional reference in the registry of the core ([Adding a setting](core-model.md#adding-a-setting)) and read it in the layer through `snapshot.sources`. The runtime listens to its entity and reads it without any change here. A source of a new kind (a unit the core expects that Home Assistant states differently) is added to `sources.py`, in one place for every layer.

## The clock and the sun

The clock port reports the time in the **named** local zone of the installation, the zone Home Assistant was configured with (`dt_util.get_default_time_zone()`, a `ZoneInfo`). The core reads everything local from that zone, and only a named zone knows when its clocks change; a zone without a name is refused at set-up.

The core computes nothing astronomical. There is exactly one implementation of its `Sun` port, backed by the `astral` library that Home Assistant ships, in `sun_astral.py` of this integration (`AstralSun`, built from latitude, longitude, elevation and the name of the zone). `location.py` obtains the observer through Home Assistant's current helper, `homeassistant.helpers.sun.get_astral_observer` (Core 2026.9.2; `get_astral_location` is deprecated), hands plain values to that class, and never depends on the `sun` entity. If the module is missing, the set-up fails closed with an error that names it, because a schedule without sun data would be a schedule that guesses.

## What the runtime does not do yet

- **Persistence to disk.** The storage is in memory; a restart starts every window with a fresh state and a new seed. Restart reconciliation (section 11 of the specification) belongs to the persistence block.
- **Results of commands, backoff, the tracker, manual detection.** The runtime records that a command was given; everything after that is the block that sends commands and the block that tracks movements.
- **Entities, events, repair issues about faults of the arbiter.** The status of a window is a plain object (`WindowStatus`) for the block that builds the entities.
- **Switches for pause, operating mode and maintenance lock.** The controls are neutral until that block exists; `SuiteRuntime.controls_of` is the seam.
- **Cleaning up the state of a removed window.** The storage keeps it until the persistence block decides.

## Testing the runtime

The tests under `tests/ha/` control the time with the `freezer` fixture and never sleep. `tests/ha/runtime_kit.py` has what they share: an invented sun (`FakeSun`) that answers with fixed local times in the zone the runtime hands it, a schedule with fixed times, and helpers that set a window up and let the coalescing run out (`settle`, `advance`). The fixture `fake_sun` of `tests/ha/conftest.py` replaces the astral-backed sun port with that sun for every test, so no test depends on astronomy; the plain values the runtime handed in are recorded on the factory.
