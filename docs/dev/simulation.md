# The time-lapse simulation

The domain core can run a whole day or a whole year against a synthetic world in seconds (feature N6, guardrail 4 of the project brief). That is how oscillation, command loops and wrong interactions between layers are seen before a real motor pays for them, and it is the scenario test harness of every core block. It lives under `tests/sim/`, outside the shipped integration, and imports nothing from Home Assistant. This page says how to write a scenario, what the behaviour profiles of the simulated covers are, and how to read a timeline.

| Module under `tests/sim/` | Content |
|---|---|
| `clock.py` | the controllable clock, in the local zone of the installation |
| `sources.py` | scripted and generated time series for every source, with unavailable and unknown phases |
| `storage.py` | the in-memory storage; every save goes through JSON |
| `cover.py` | the simulated cover and its behaviour profile |
| `world.py` | the world: clock, sun, sources, covers, storage, actuator |
| `house.py` | the protection of the simulated house: its fire source, a storm that closes and hail that opens |
| `stand_ins.py` | test-only stand-ins for blocks that do not exist yet: lockout protection (C08) and sleep mode (C11) |
| `runner.py` | the scenario runner: windows, injected events, recomputes, restart |
| `record.py` | the record of a run and the readable timeline |
| `assertions.py` | what a run must satisfy |
| `scenarios.py` | the named scenarios and the profiles they use |
| `__main__.py` | the command-line entry point |

The scenario tests stand under `tests/core/` (`test_sim_scenarios.py`), where the purity proof of the core tests also covers the harness; the unit tests of the cover, the assertions, the small ports and the command line stand next to them (`test_sim_cover.py`, `test_sim_assertions.py`, `test_sim_world.py`, `test_sim_cli.py`).

## Running a scenario

```sh
uv run python -m tests.sim --list
uv run python -m tests.sim workday
uv run python -m tests.sim year --seed 3 --window window_4 --kinds decision,command
```

The command prints the timeline of the run and one line of numbers: recomputes, entries, restarts, seconds. It is a development tool and is not shipped. The year for ten windows takes about half a minute on a developer machine.

**How the simulation imports the core and the sun port.** The harness imports `custom_components.roller_shutter_suite.core` and `custom_components.roller_shutter_suite.sun_astral`. Importing anything through the integration package would execute the package's `__init__`, which belongs to the Home Assistant layer, imports Home Assistant, and does not even import on native Windows. The simulation therefore relies on the same stand-in as the core tests: an empty package registered under the integration's name, so that its modules are found without executing that file. Under pytest `tests/core/conftest.py` installs it, which is why the simulation's tests live under `tests/core`; the command-line entry point installs the same stand-in itself before it imports anything of the harness. A harness that accepted the Home Assistant import instead would lose the purity proof for everything it runs and would not run natively on Windows.

## How the runner drives the core

The runner does what the runtime will do, and nothing on a fixed grid. A window is recomputed when something it looks at changes or at an instant the core named: a report of one of its members, a change of a source, the next planned action of the schedule, the recheck time of the brightness trigger, the end of a deferral (`until` or `reevaluate_no_later_than` of the gate outcome), and every instant of `Engine.wake_ups`: the deadline of every pending own command (`member_expectation_end`, the same deadline the gate reads), the end of every settle time of the tracker, and the end of each dam. The runner computes no time of its own. Time jumps from one due instant to the next, which is why a year runs in seconds.

One recompute:

1. The world snapshot is built: the time of the clock, the sun position, every source as a source value, the members as last observed, the persisted state, the controls, the almanac (built once per local date through `build_sun_almanac`) and the seed from the storage.
2. `Engine.elapse` judges the settle times and deadlines that have passed and ends or turns the dams whose time has come; its events are recorded.
3. `Engine.recompute` gives the decision; the runner keeps it as the window's last decision, which the tracker judges the next reports by.
4. The state after the decision is assembled: what the schedule remembers (one evaluation of `evaluate_schedule`, which also gives the next planned action), what a dry-run or a take-over leaves behind (`Engine.state_after`), and, if the gate said "send", the targets of the members the decision addresses (`Decision.addressed_targets`) are handed to the actuator under an identifier and written down (`Engine.after_send`, which also raises the event of the daily count). The runner filters nothing of its own, exactly as the runtime.
5. The state is persisted if it changed. The storage keeps JSON text, so every save is a real round trip.
6. The next wake-ups are planned.

**Reports go to the tracker.** A cover writes raw reports (a state, a position or none, an instant, and the user in its context for a movement from a dashboard). The runner reduces every report to an observation of the core and hands it to `Engine.observe`, with the window's last decision; the core drops a report whose observation equals the member's last one (section 8.2 of the architecture): a repeated write, a rewrite with a new change time. `Record.dropped_reports` counts them. At the start and after a restart the runner reads every member once and hands that to the tracker too; after a restart it is what the persisted state knows already, and changes nothing. What the tracker raises is recorded ([The movement tracker and the dams](tracking.md)).

**Restart.** `Simulation.restart()` throws the engines away, reads every window state back from the storage, reads the covers once, and recomputes every window whose members are available. The covers keep their state, as real covers do. The scenario `restarts` does this at four points of a day, and a test shows that the commands after every restart equal those of the uninterrupted run.

**Injected events**, scheduled with `simulation.at(instant, label, action)`: `move_by_hand(window, target, member_id=..., user_id=...)` (a whole window or one member; with a user, a movement from a dashboard whose first reports carry the user in their context), `stop_by_hand(window, member)`, `dropout(window, member, duration)`, `set_controls(window, controls)` (pause, lock, mode, dry-run; leaving dry-run arms the window), `other_controller_moves(window, target)` (a scripted second controller), `resume(window)` (the "resume automation" button), `sleep_mode_switched_on(window)`, `acknowledge_fire(window)` (the action and the button that acknowledge the fire alarm), `request(window, position, reason, expires)` and `clear_request(window)` (an automation requests a position and clears it), and `restart()`. The movements by hand, the stops, the other controller and the dropouts are marked as foreign in the record (`Entry.foreign`).

**Layers.** By default every window's arbiter is the one of the integration (`build_arbiter()`): the real fire, protection and schedule layers and the built-in constraints and gate rules. The stubs of fire and protection that stood here until block C07 are gone. Every window inherits the protection of the simulated house (`house.py`, applied by `World.window` unless a scenario states other values): the fire source `binary_sensor.example_smoke_alarm`, a storm that closes (`binary_sensor.example_storm_warning`, rank 10) and hail that opens (`binary_sensor.example_hail_warning`, rank 20); `calm_sources` scripts all three off. A scenario hands in other layers or additional constraints with `Simulation(world, layers=..., constraints=...)`. For features whose block does not exist yet the scenarios of block C07 use the **stand-ins** of `stand_ins.py`: a lockout constraint (sources `door`, `tamper`) for C08 and a sleep layer (source `sleep`) for C11. They are test-only and are replaced by the real constraint and layer when those blocks arrive; no other scenario exists for a feature that does not exist.

## Writing a scenario

A scenario is a function of a seed that returns a `Simulation` ready to run. The pieces:

```python
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from tests.sim.cover import CoverProfile, SimulatedCover
from tests.sim.runner import Simulation
from tests.sim.scenarios import ARMED, calm_sources
from tests.sim.sources import Series
from tests.sim.world import World

start = datetime(2026, 9, 21, tzinfo=ZoneInfo("Europe/Berlin"))
script = calm_sources(start).with_series(
    "storm", Series.of((start, False), (start + timedelta(hours=14), True))
)
world = World(start, seed=1, script=script)
world.add_cover(
    SimulatedCover(
        "cover.example_left", CoverProfile("live"), position=0, available_since=start
    )
)
simulation = Simulation(world)
simulation.add_window(world.window("window_example", "cover.example_left"), ARMED)
simulation.at(
    start + timedelta(hours=12),
    "a person lowers the window",
    lambda sim: sim.move_by_hand("window_example", 40),
)
record = simulation.run(start + timedelta(days=1))
```

- **The world** takes the start instant, whose zone is the local zone of the installation, a seed, an optional `Location` (the default is a made-up round point, 50 north and 10 east; never use the coordinates of a real installation), the script of the sources and the covers. The sun is the shared astral-backed port (`custom_components/roller_shutter_suite/sun_astral.py`), so a simulated year runs with the same sun times as the operation.
- **Sources** are series of steps: from an instant on, a value, `UNKNOWN` or `UNAVAILABLE`; before the first step a source is unavailable. `Series.generated(start, end, step, function)` computes a series once, when the scenario is built, and keeps only the changes; noise comes from `world.random`, a generator seeded with the scenario's seed, so the run is reproducible.
- **Covers** are the members; `world.window(window_id, *member_ids, **fields)` builds a `WindowConfig` whose capability profiles are what a user would state for these covers, and `fields` are fields of `WindowConfig` (`schedule_morning_position=Position(30)`).
- **Controls** are the `Controls` of the core: `ARMED`, `DRY_RUN`, `LOCKED`, `PAUSED` and `mode(...)` stand in `scenarios.py`.
- **Running** returns the record; `simulation.recomputes` and `simulation.restarts` count.

Add the scenario to `SCENARIOS` in `scenarios.py` with a description and its length, so the command line and `test_every_named_scenario_runs` know it, and write its test in `tests/core/test_sim_scenarios.py`.

## The behaviour profiles of a cover

`CoverProfile` describes how a cover travels and how it reports, after the measured facts of section 8 of the architecture and the pitfalls of the brief's section 7. The profiles that `scenarios.py` names, each used by at least one window of the year scenario:

| Profile | Behaviour |
|---|---|
| `live` | transit states, a position every two seconds during the travel, the resting state at the target |
| `end_only` | keeps the old position during the travel and jumps to the target at the end |
| `polled` | reports only on a grid of 60 seconds, no transit state, no report at the real end of the movement |
| `settles_off` | a measured position that settles 2 short upwards and 1 short downwards; the start report is 3 percent into the travel; a movement into an end stop takes 3 seconds longer |
| `no_stop` | ignores a stop |
| `no_position` | reports no position and knows only open and close (a target below 50 closes) |
| `late_report` | the last report arrives 8 seconds late, as a position write 20 milliseconds before the resting state, and is repeated 10 milliseconds later |
| `chatty` | repeats its writes and rewrites an unchanged state every 20 minutes with a new change time |
| `no_transit` | reports positions but never `opening` or `closing` |
| `blocked` | a calculated position: the motor cuts out at 60, the actuator counts to the target and reports it |

The fields behind them: `travel_time_up`, `travel_time_down`, `end_stop_extra` (not linear in percent), `supports_set_position`, `supports_stop`, `reports_position`, `position_source` (`calculated` or `measured`), `transit_states`, `reporting` (`live`, `end_only`, `grid`), `live_interval`, `grid_interval`, `start_latency`, `start_offset_percent`, `settle_offset_up`, `settle_offset_down`, `report_delay`, `position_before_rest`, `repeat_last_write`, `rewrite_unchanged_every`, `blocked_at`. `CoverProfile.capability_profile()` is what the user would state for the cover; a polled platform states its grid as the report delay.

**The real position and the reported one.** Every cover keeps where the curtain really is apart from what the actuator reports (`real_position(at)`, `reported_position(at)`). With a calculated position the report at the end is the commanded target whatever happened; with a measured one it is where the curtain is. The `blocked` profile shows the drift: the report says 100, the curtain stands at 60, the core reads "target reached" and does not fight it, which is the honest outcome, because a calculated position cannot know more (section 8.4). The drift persists: the motor runs in the direction and for the time the count asks for, so a later movement moves the curtain by the counted distance (after the block, a command to 80 lowers the curtain from 60 to 40). Only a movement into an end position runs the curtain into the end stop and references it again; a curtain that is still blocked on the way stops at the block once more.

**What the harness shows today.** A measured cover that settles 6 short of its target was sent again every minimum interval until block C06; the tracker now takes such a movement for an intervention, as section 8.3 says (a measured position has a tolerance of 3), and the manual override holds the window until the next part of the day (`test_a_cover_that_settles_beyond_its_tolerance_is_taken_for_an_intervention`, the former pin test). A cover that really settles that far off needs a larger tolerance, which its user states per member (`tolerance` in `CAPABILITY_SETTINGS`, 1 to 20 percent). On the polled platform a person who reverses an own movement within one grid interval is invisible: the cover is back where it started before its first report, the tracker says `actuator_no_reaction`, and the command is sent again once the minimum interval has passed; what follows is command verification (block H15). A member without position feedback is commanded once when a run starts, because nobody knows where it stands.

**The tracking scenarios** (`tests/core/test_sim_tracking.py`): `profile_case(profile, case)` runs one window over a cover of one profile through its morning opening and one of the cases of `TRACKING_CASES` (an own movement, a movement by hand, a stop in mid-travel, a dropout with the same and with another position, a reversal); `polled_four` commands four members of a polled platform at once; `pair_one_by_hand` moves one of two members by hand; `override_end(how)` ends a manual override by each of its rules, by "resume automation" and by sleep mode; `person_at_window(storm_until)` opens a window during a storm that ends before or after the dam; `dry_run_whole_day` runs a window in dry-run next to a second controller that moves it four times; `hand_movement_with_restart` and `own_movement_with_restart` restart during a movement, a settle time and an armed dam and compare what follows with the uninterrupted run. The **year** scenario moves every window by hand to 70 at noon every day: the override holds it until the evening, when the schedule closes it.

## Assertions

Every assertion raises `ScenarioAssertionError` with what went wrong, when, and the timeline around that moment, so a failed scenario points at the place.

| Assertion | Judges |
|---|---|
| `movements_per_day`, `assert_at_most_movements_per_day(record, limit, since=...)` | a movement is one decision that sent, whatever the number of members; `since` leaves the start of a run out |
| `assert_min_interval(record, configs)` | two comfort movements of a window closer than its minimum interval |
| `assert_no_command_loop(record)` | the same member commanded to the same target twice without a report of that member in between |
| `assert_no_intermediate_position(record, window, since, until)` | every command inside the span targets 0 or 100 |
| `assert_schedule_commands_inside_clamps(record, config, since=...)` | a schedule movement lies at its fixed time or between the clamps of its trigger, on the local clock |
| `assert_no_commands(record, window)` | nothing was sent at all (dry-run, maintenance lock) |
| `assert_dams_follow_foreign_movements(record, within=...)` | no own movement arms a dam: every `manual_detected`, `manual_detected_member`, `override_started` and `person_at_window_started` follows an action from outside the integration on that window within the bound (ten minutes by default); an override a person-at-the-window dam turns into follows the end of that dam |

The unit tests of the assertions (`tests/core/test_sim_assertions.py`) build records by hand and show that each one finds what it is for and stays quiet otherwise.

## Reading a timeline

One line per entry, in the local zone:

```text
2026-09-21 07:00:00.000 +0200  decision  window_example                            schedule: schedule_day | wants 100 | send: sent
2026-09-21 07:00:00.000 +0200  command   window_example [cover.example_window]     send 100 (comfort, schedule_day)
2026-09-21 07:00:00.700 +0200  report    window_example [cover.example_window]     opening at 4
2026-09-21 07:00:00.700 +0200  decision  window_example                            schedule: schedule_day | wants 100 | suppress: duplicate_command
2026-09-21 07:00:20.000 +0200  report    window_example [cover.example_window]     open at 100
2026-09-21 07:00:20.000 +0200  decision  window_example                            schedule: schedule_day | wants 100 | suppress: target_reached
```

- **decision**: the winning layer and its reason, what it wants, every constraint that applied with its reason, and the gate outcome with its reason. A deferral names its end; a dry-run outcome names what would have been sent, or the rule that would have held the wish back. Faults of the safety net are listed at the end.
- **command**: what was really sent to which member, with the class and the reason of the wish.
- **report**: the normalized observation of a member after a write that changed something; `-` stands for a member that reports no position.
- **source**: a source of the world changed; every window is recomputed.
- **event**: an injected event, or what a scenario action did (moved by hand, stopped, a dropout, changed controls, another controller, resume, sleep mode).
- **tracker**: what the movement tracker and the dams raised (`manual_detected`, `override_started`, `actuator_no_reaction` …), with the member, the position, the count or the user; `Record.events(window, *codes)` filters them.
- **restart**: the core restarted and read its states from the storage.

`Record.timeline(window_id=..., since=..., until=..., kinds=...)` filters; `Record.around(moment)` is what a failed assertion shows. The decision entries keep the whole `Decision`, so a test asserts on reasons and targets without parsing text.

Reading a failed scenario: the message names the window, the moment and the rule that was broken; the excerpt below it shows the decisions before and after. A `send` that should not have happened is read backwards: the decision above it names the layer whose wish won and the constraints that applied; the reports before it say what the core knew about the members.

## What is out of scope

Plots and a graphical front end. Scenarios for shading, sleep mode and privacy: their blocks add them, with the real layers in place of the stand-ins.

## The scenarios of protection (block C07)

`tests/core/test_sim_protection.py` runs them and names, for each situation of section 4 of the specification, the reason codes of its row.

| Scenario | Shows |
|---|---|
| `fire-locked`, `fire-dry-run`, `fire-off` | situations 1 to 3: under the lock and in dry-run nothing moves and the decision names the fire wish; in mode `off` fire opens at once |
| `fire-unacknowledged` | situation 3a: after a false alarm a person closes the shutter; nothing reopens it, and after the acknowledgement the manual override protects it |
| `storm-door-open`, `storm-door-tamper` | situations 4 and 5, with the lockout stand-in: no movement while the door is open; with the tamper contact the storm closes |
| `hail-sleep-exception` | situation 6, with the sleep stand-in: hail does not open a room marked for the exception while sleep mode is on |
| `person-at-window` | situation 7: a person opens the window during a storm; after 15 minutes the storm position is restored and a reason event is fired |
| `storm-return`, `storm-override-expired` | situations 8 to 10: an override before the storm stays armed, and after the waiting time the person's position is restored; with an override that expired, the window is recomputed |
| `storm-twice` | a person opens the window in the waiting time and the storm comes back: the second start remembers the person's 60, and the window returns to it |
| `storm-source-away` | situation 14 and D6: the source is away, the event holds, the source is reported blind after an hour, and the event ends when the source returns with "off" |
| `storm-stuck` | the watchdog releases a stuck source after 12 hours and makes the event effective again after one genuine "off" |
| `storm-and-hail` | two events at once: hail ranks above the storm; when it ends, the active storm closes again |
| `fire-during-storm` | fire wins over the storm, and after the acknowledgement the storm applies again |

`storm_return_with_restart` and `storm_stuck_with_restart` restart during the storm, during its waiting time, after the return and during a release; the tests compare the commands with the uninterrupted run. The `storm` scenario of block C05 runs against the real layer: never an intermediate position, and the schedule opens the window again after the waiting time.

## The scenarios of the external request layer

Kept apart from protection; `tests/core/test_sim_request.py` runs them.

| Scenario | Shows |
|---|---|
| `request-below-sleep` | an alarm clock requests 60 while sleep mode is on (the sleep stand-in): accepted, nothing moves; after sleep mode the request wins; at its expiry the schedule opens |
| `request-expires` | a request for 40 for an hour, then the schedule's day position again |
| `request-cleared` | a request without an expiry, cleared half an hour later |
| `request-dry-run` | a window in dry-run: the record shows "would have sent 40", nothing is sent |
