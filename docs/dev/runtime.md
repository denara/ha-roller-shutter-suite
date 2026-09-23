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
| `actuator.py` | the recording actuator that stands in until the block that sends commands exists |

## The life cycle of a window controller

```text
set-up ─► start ─► waiting for members ─► running ─► stop
                          │                  ▲
                          └── members appear ┘
```

1. **Set-up.** `async_setup_entry` builds the ports first: the clock in the named local zone, the sun port from the observer of the installation, the storage. A zone that is not a named one fails the set-up closed, before any window is looked at. Then it resolves the windows as before (`windows.resolve_entry`), creates the devices and the repair issues, and starts the runtime with the windows that have a configuration.
2. **Start.** `SuiteRuntime.async_add_window` creates the controller of one window and starts it. If that raises, the failure is logged once with the window's name and the type of the exception, the window is listed in `SuiteRuntime.failed`, and every other window is started all the same; nothing propagates out of the set-up of the entry. A window whose configuration the resolver withheld is listed there too (`configuration_withheld`). The controller loads the window's state from the storage (a state that cannot be read is logged and replaced by a fresh one), subscribes to the state changes of its members and the entities of its sources, starts the safety tick, and asks for a first recompute.
3. **Waiting for members.** No decision is made before the members are available. A cover platform that comes up late is normal: the window waits, and when the cover appears the next state change starts it, without a reload. With several members the controller waits until all of them are available, or until `STARTUP_GRACE` (two minutes) has passed since the start and at least one is; from then on the window decides with what is known, and a member that is away is the business of the gate ("no member can execute", `cover_unavailable` when no addressed member is available) and is shown in the status. A member that has not reported by then stays unknown: no position is assumed for it, and no capability (see [Deviations](#deviations)). A window whose cover never comes stays in this phase and reports it; the entry is loaded.
4. **Running.** Every trigger leads to a recompute (below). The status carries the decision, the faults, the facts of the schedule, the sources with their values, the commands given and the next wake-up.
5. **Stop.** `async_unload_entry` stops every controller: every listener and timer is cancelled, the debouncer is shut down, and the state is saved. Removing one window stops its controller alone; the listeners and timers of the others are untouched. Reloading one window replaces its controller with a fresh one.

**Every configuration change reloads the whole config entry**, and therefore every window. That is harmless because the runtime state of a window lives in the storage port, not in the controller: the pending own command with its expectation, the dams, a deferral, the latched day type, the held inputs. After the reload the window continues where it was. In this block the storage is in memory (`storage.py`) and survives a reload but not a restart; the block that builds persistence replaces it behind the same port.

## Triggers of a recompute

| Trigger | Mechanism |
|---|---|
| a state change of a member or of an entity a source refers to | `async_track_state_change_event` on the entity IDs of the window |
| a point in time the core asked for | one timer per window, `async_track_point_in_utc_time`, at the earliest of: the end of a deferral (`until`), the upper bound of a re-evaluation (`reevaluate_no_later_than`), the next planned action of the schedule, its recheck (`recheck_at`), the end of the expectation window of every pending own command (the simulated ones for a window in dry-run); and, while waiting for members, the end of the start-up grace |
| the periodic safety tick | `async_track_time_interval` every `SAFETY_TICK`, so a missed event cannot leave a window in the wrong state for long |
| an explicit request | `WindowController.async_request_recompute()` |

**One deadline source.** The end of an expectation window is never computed in the runtime. Every timer that waits for it takes `member_expectation_end(member, command)` of the core (`core.arbiter`), the function the gate itself reads through `expectation_window_end`: the time of the command plus the full travel time of its direction plus the report delay of the member. At that instant the gate stops counting the command as pending, so a command the cover did not answer is judged again at once; the same holds after a reload, because the command and its time are part of the persisted state.

Every trigger goes through one `Debouncer` per window (cooldown `COALESCE_SECONDS`, not immediate). A burst of changes therefore yields one recompute after the last of them, and two recomputes of the same window never run at the same time. The price is that a reaction is delayed by up to a second, which is nothing for a shutter.

**Wake-up times cannot form a loop.** A time the core asks for is accepted only if it lies strictly in the future. Otherwise it is moved to `MIN_WAKE_UP_DISTANCE` after now and the fault is logged once (and again only after a sound time was seen in between). Recomputes that come from wake-ups are at least `MIN_WAKE_UP_DISTANCE` apart, so a layer or rule that keeps asking for "now" costs a few recomputes per minute and nothing more. The one constant is the only place that says how far. The status shows the accepted wake-up with its reason.

## The recompute, step by step

1. **Observe the members** (`members.py`). No state or `unavailable` is an unavailable member; `opening` and `closing` are movements; everything else, including `unknown`, is resting. The position is `current_position` if the attribute holds a whole number from 0 to 100 and the capability profile does not say that the member definitely reports none; a boolean, text, a float or a number outside the range is no position. A profile whose capabilities are not known keeps the position: unknown is never taken for missing.

   **Capabilities are never re-read**, with one exception. The resolved configuration of the set-up holds the last known capabilities of every member for the lifetime of the entry, so a cover that is away for a while changes nothing (no mask, no repair issue, the same configuration; "capabilities do not flap"). The exception is a member about which nothing was known at set-up, no usable state and no entity-registry entry (a cover without a unique ID that loads late): its profile says `capabilities_known=False`, and the controller reads its capabilities from the entity once, the first time it is available, and replaces the configuration and the engine with the learned profile. A known profile is never read again, so nothing flaps.
2. **Read the sources** (`sources.py`), see below. For every source the controller keeps the value and the time of the first recompute that saw it (`SourceReading.since`), with its own clock; a restored state after a restart counts from the first observation, never from the change time of the entity. `since` lives in the controller and is a value of the status only: it starts again with every reload of the entry. The durations the decisions depend on (the brightness of the evening, for example) live in the persisted window state and survive the reload.
3. **Build the snapshot.** `time` is the clock port's now, in the named local zone. `sun` is the sun port's position. `sources` are the values by their configured reference. `state` is the window's persisted state. `controls` are pause, maintenance lock and operating mode of the three levels and dry-run; until the block that builds the switches exists, the levels are neutral and dry-run is what the subentry says (`runtime.neutral_controls`). `almanac` is the sun almanac of the core (`build_sun_almanac`), built once per local date and settings of the schedule and kept until either changes. `installation_seed` is the seed of the storage port, created once and stored.
4. **Decide.** `Engine.recompute(snapshot)`. Nothing that a layer, a constraint or a gate rule raises leaves the arbiter; what does are the `faults` of the decision, which the controller logs once per change with the window's name, the stage, the place, the function and the type of the exception, never its message, and passes on in the status. An exception outside the safety net (a bug in the adapter itself) is caught by the controller, logged with its traceback, shown as `error` in the status, and the window is evaluated again at the next trigger; no other window is affected.
5. **The state after the decision.** `Engine.state_after` (a take-over, a would-be command in dry-run), then the schedule's state (`evaluate_schedule`, only while the schedule runs for the window: switched on, not paused by a faulty setting, with every input it needs), then the own commands of a send (below). What changed is written to the storage at once, so the latched day type of a date is stored right after the recompute at the morning trigger, not only at shutdown.
6. **Send.** A decision whose gate outcome is `send` names the target of every member. The controller checks dry-run a second time: a window in dry-run sends nothing, with one exception the project owner decided, a fire wish that was sent because the dry-run rule itself raised (`Decision.faults` names the rule). Then it hands the target of every member that is available to the actuator port under a fresh command identifier (a member that is away is not commanded and gets no record, section 9 of the specification) and has the core record the send: `Engine.state_after_send(snapshot, decision, command_ids)` is the one recorder of own commands ([The arbiter](arbiter.md)). It writes, per commanded member, the last own command (target, direction, time, wish class, reason) with one attempt at the time of the send, sets the owner of the position to the integration, and for a comfort wish sets the clock of motor protection. The runtime calls it right after each member's call returned, on the state the decision left behind, with the identifiers of every member sent so far, and stores the result at once: an actuator that raises for a later member leaves the commands that were given recorded, and the next recompute does not send them again. That record is what the gate rules about own commands read on the next recompute, and what survives a reload. The context ID that section 11 lists with the own command is left empty here; the block that sends commands fills it. Until the block that sends commands exists, the actuator is `RecordingActuator`: it records and calls nothing.
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

The core computes nothing astronomical. There is exactly one implementation of its `Sun` port, backed by the `astral` library that Home Assistant ships, in `sun_astral.py` of this integration (`AstralSun`, built from latitude, longitude, elevation and the name of the zone). `location.py` obtains the observer through Home Assistant's current helper, `homeassistant.helpers.sun.get_astral_observer` (Core 2026.9.2; `get_astral_location` is deprecated), hands plain values to that class, and never depends on the `sun` entity. An elevation that is not a height in metres (`astral` also accepts a pair of height and distance) fails the set-up closed. `location.py` imports `AstralSun` at the top of the module, like any other module of the integration; Home Assistant imports the integration's modules outside the event loop, and nothing is imported by name while the loop runs (an `importlib` call there trips Home Assistant's detection of blocking calls).

## The status and its readers

`WindowStatus` is read, never written, by three modules. After every recompute, and when the phase changes, the controller sends the dispatcher signal `const.status_signal(window_id)` (`_publish_status`); the signal carries nothing, and each reader looks the controller up in `SuiteRuntime.windows` and reads its status. Looking it up by the window's ID each time means a reader never keeps a controller that was replaced.

| Module | What it reads | What it makes of it |
|---|---|---|
| `entity.py`, `sensor.py`, `binary_sensor.py` | the decision, the schedule's next action, the observation, the controls | the entities of the window, unavailable while no member is available or the window has no controller |
| `events.py` | the decision, whether commands were given, dry-run | one reason event per change of outcome (`record.reason_outcome`), and the last decisions for the diagnostics |
| `diagnostics.py` | everything, plus the resolved configuration and the persisted state | the download, redacted |

`record.py` turns a decision into plain data for all three; it imports nothing from Home Assistant. A fault of the safety net appears there as stage, place, function and reason code (`layer_failed`, `constraint_failed`, `gate_rule_failed`); `EvaluationFault.exception` is never read outside the controller's log line. The memory of the last event per window and the recent decisions live in `hass.data` next to the storage (`events.history_of`), so a reload does not fire the same outcome again; like the storage, they are lost at a restart. `SourceReading.since` appears in the diagnostics as `seen_unchanged_since`, documented as starting again with every reload; it is never presented as a persisted fact. The logbook platform (`logbook.py`) builds its messages from the translations Home Assistant already holds for the language of the installation, which the set-up of the entry loads; see [Status, reason events and diagnostics](../features/status-and-events.md) for the user's view.

## What the runtime does not do yet

- **Persistence to disk.** The storage is in memory; a restart starts every window with a fresh state and a new seed. Restart reconciliation (section 11 of the specification) belongs to the persistence block.
- **Results of commands, backoff, the tracker, manual detection.** The runtime has the core record that a command was given; everything after that is the block that sends commands and the block that tracks movements.
- **Repair issues about faults of the arbiter.** Faults are logged and shown in the status entities and the diagnostics; a repair issue for them belongs to a later block.
- **Switches for pause, operating mode and maintenance lock.** The controls are neutral until that block exists; `SuiteRuntime.controls_of` is the seam.
- **Cleaning up the state of a removed window.** The storage keeps it until the persistence block decides.

## Deviations

**The start-up grace of two minutes.** Section 11 of the specification says that no decision is made before the members of a window are available. Taken by the letter, one member that never reports would keep the whole window, and every member that is there, without a decision for ever, which contradicts section 9 (a member that is unavailable: the others are commanded). The runtime therefore waits for all members, but at most `STARTUP_GRACE` (two minutes, `const.py`, the one place) after the start, and only once at least one member is available. The two minutes come from the S1 measurement: covers that Home Assistant polls report with a delay of up to 60 seconds, so a member that is merely slow has reported within the grace. After the grace the window decides with what is known. A member that is still silent stays unknown: no position is assumed and no capability; the gate addresses only the members that are available and defers with `cover_unavailable` when none of them is; the status shows the member as unavailable. The wake-up at the end of the grace is shown in the status. The project owner records this in the specification with the next documentation change.

## Testing the runtime

The tests under `tests/ha/` control the time with the `freezer` fixture and never sleep. `tests/ha/runtime_kit.py` has what they share: an invented sun (`FakeSun`) that answers with fixed local times in the zone the runtime hands it, a schedule with fixed times, and helpers that set a window up and let the coalescing run out (`settle`, `advance`). The fixture `fake_sun` of `tests/ha/conftest.py` replaces `AstralSun` in `location.py` with a factory of that sun for every test, so no test depends on astronomy; the plain values the runtime handed in are recorded on the factory.
