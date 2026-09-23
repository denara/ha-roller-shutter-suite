# The time-lapse simulation

The domain core can run a whole day or a whole year against a synthetic world in seconds (feature N6, guardrail 4 of the project brief). That is how oscillation, command loops and wrong interactions between layers are seen before a real motor pays for them, and it is the scenario test harness of every core block. It lives under `tests/sim/`, outside the shipped integration, and imports nothing from Home Assistant. This page says how to write a scenario, what the behaviour profiles of the simulated covers are, and how to read a timeline.

| Module under `tests/sim/` | Content |
|---|---|
| `clock.py` | the controllable clock, in the local zone of the installation |
| `sources.py` | scripted and generated time series for every source, with unavailable and unknown phases |
| `storage.py` | the in-memory storage; every save goes through JSON |
| `cover.py` | the simulated cover and its behaviour profile |
| `world.py` | the world: clock, sun, sources, covers, storage, actuator |
| `stubs.py` | stub layers for fire and protection until their block exists |
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

## How the runner drives the core

The runner does what the runtime will do, and nothing on a fixed grid. A window is recomputed when something it looks at changes or at an instant the core named: a report of one of its members, a change of a source, the next planned action of the schedule, the recheck time of the brightness trigger, the end of a deferral (`until` or `reevaluate_no_later_than` of the gate outcome), and the end of the expectation window of a pending own command. Time jumps from one due instant to the next, which is why a year runs in seconds.

One recompute:

1. The world snapshot is built: the time of the clock, the sun position, every source as a source value, the members as last observed, the persisted state, the controls, the almanac (built once per local date through `build_sun_almanac`) and the seed from the storage.
2. `Engine.recompute` gives the decision.
3. The state after the decision is assembled: what the schedule remembers (one evaluation of `evaluate_schedule`, which also gives the next planned action), what a dry-run or a take-over leaves behind (`Engine.state_after`), and, if the gate said "send", the commands are handed to the actuator under an identifier and written down (`Engine.state_after_send`).
4. The state is persisted if it changed. The storage keeps JSON text, so every save is a real round trip.
5. The next wake-ups are planned.

**Normalizing reports.** A cover writes raw reports (a state, a position or none, an instant). The runner reduces every report to an observation of the core and drops a report that changes nothing, as the tracker of the runtime will (section 8.2 of the architecture): a repeated write, a rewrite with a new change time, a return from a dropout in the same state. `Record.dropped_reports` counts them.

**Restart.** `Simulation.restart()` throws the engines away, reads every window state back from the storage, reads the covers once, and recomputes every window whose members are available. The covers keep their state, as real covers do. The scenario `restarts` does this at four points of a day, and a test shows that the commands after every restart equal those of the uninterrupted run.

**Injected events**, scheduled with `simulation.at(instant, label, action)`: `move_by_hand(window, target, member_id=...)` (a whole window or one member), `stop_by_hand(window, member)`, `dropout(window, member, duration)`, `set_controls(window, controls)` (pause, lock, mode, dry-run; leaving dry-run arms the window), `other_controller_moves(window, target)` (a scripted second controller), and `restart()`.

**Layers.** By default every window's arbiter gets the real schedule layer and two stubs (`tests/sim/stubs.py`): a fire layer that opens while the source `fire_alarm` is on and a protection layer that closes while `storm` is on. These are extension points. When block C07 delivers the real layers, a scenario hands them in with `Simulation(world, layers=...)` and scripts the sources they read; the same goes for shading, sleep mode and the rest as their blocks arrive. No scenario exists for a feature that does not exist.

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
| `settles_off` | a measured position that settles 2 short upwards and 1 beyond downwards; the start report is 3 percent into the travel; a movement into an end stop takes 3 seconds longer |
| `no_stop` | ignores a stop |
| `no_position` | reports no position and knows only open and close (a target below 50 closes) |
| `late_report` | the last report arrives 8 seconds late, as a position write 20 milliseconds before the resting state, and is repeated 10 milliseconds later |
| `chatty` | repeats its writes and rewrites an unchanged state every 20 minutes with a new change time |
| `no_transit` | reports positions but never `opening` or `closing` |
| `blocked` | a calculated position: the motor cuts out at 60, the actuator counts to the target and reports it |

The fields behind them: `travel_time_up`, `travel_time_down`, `end_stop_extra` (not linear in percent), `supports_set_position`, `supports_stop`, `reports_position`, `position_source` (`calculated` or `measured`), `transit_states`, `reporting` (`live`, `end_only`, `grid`), `live_interval`, `grid_interval`, `start_latency`, `start_offset_percent`, `settle_offset_up`, `settle_offset_down`, `report_delay`, `position_before_rest`, `repeat_last_write`, `rewrite_unchanged_every`, `blocked_at`. `CoverProfile.capability_profile()` is what the user would state for the cover; a polled platform states its grid as the report delay.

**The real position and the reported one.** Every cover keeps where the curtain really is apart from what the actuator reports (`real_position(at)`, `reported_position(at)`). With a calculated position the report at the end is the commanded target whatever happened; with a measured one it is where the curtain is. The `blocked` profile shows the drift: the report says 100, the curtain stands at 60, the core reads "target reached" and does not fight it, which is the honest outcome, because a calculated position cannot know more (section 8.4).

**What the harness shows today.** A measured cover that settles beyond its tolerance is sent again every minimum interval, because "target reached" never holds and command verification with its backoff (N1) is not built yet; `test_a_cover_that_settles_beyond_its_tolerance_is_sent_every_interval` pins that and shows how the assertion on the movements per day finds it. A member without position feedback is commanded once when a run starts, because nobody knows where it stands.

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
- **event**: an injected event, or what a scenario action did (moved by hand, stopped, a dropout, changed controls, another controller).
- **restart**: the core restarted and read its states from the storage.

`Record.timeline(window_id=..., since=..., until=..., kinds=...)` filters; `Record.around(moment)` is what a failed assertion shows. The decision entries keep the whole `Decision`, so a test asserts on reasons and targets without parsing text.

Reading a failed scenario: the message names the window, the moment and the rule that was broken; the excerpt below it shows the decisions before and after. A `send` that should not have happened is read backwards: the decision above it names the layer whose wish won and the constraints that applied; the reports before it say what the core knew about the members.

## What is out of scope

Plots and a graphical front end. Scenarios for shading, protection events beyond the stub, sleep mode, privacy, tracking and the dams: their blocks add them, with the real layers in place of the stubs.
