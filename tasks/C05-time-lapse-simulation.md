# C05 — Time-lapse simulation harness

| | |
|---|---|
| Kind | Implementation, pure domain core plus test tooling |
| Depends on | C03, C04 |
| Blocks | Scenario tests of every later core block; milestone M1 uses it for its evidence |

## Goal and reason

Guardrail 4 demands that the core can run a whole day or year in time lapse, and feature N6 makes that a deliverable. It is the only way to see oscillation, command loops and wrong interactions between layers before a real motor pays for them. Built early, it becomes the scenario test harness of all later core blocks; built late, it would only confirm bugs that are already installed.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: ports, persistence model
- `docs/dev/core-model.md`, `docs/dev/arbiter.md`
- `docs/project-brief.md`: N6, guardrail 4, section 7 (pitfalls from related work)

## Scope

- A **synthetic world** that implements the core's ports: a controllable clock; a sun port backed by the `astral` library for a configurable location; sources that follow scripted or generated time series (temperature, brightness, rain, contacts, protection triggers) including phases of "unavailable"; an in-memory storage.
- A **simulated cover** behind the actuator port with a configurable behavior profile: travel time, reports transit states or not, reports intermediate positions or only the end, settles exactly or a few percent off (also asymmetric), supports stop or not, reports position or not, delivers its last report late, keeps the old position during travel and jumps to the target at the end, writes the position shortly before the resting state, repeats its last write after a few milliseconds, rewrites an unchanged state with a new change time, has a travel time that differs by direction and is not linear in percent, **reports the commanded target although the curtain was blocked** (a calculated position: the actuator counts run time, the motor cut out), with the real position kept separately by the simulation so a scenario can show the drift. A window can consist of several simulated covers with different travel times, if the architecture document defines such units. Plus injected events: a manual movement of a window or of a single member, a stop in mid-travel, a connectivity dropout after which the cover returns in the same state.
- A **runner** that advances time in steps, triggers recomputation the way the runtime will, and records every decision and every command.
- **Assertions and reports** on the record: number of movements per window and day, no two commands closer than the minimum interval for comfort movements, no command loop (repeated commands to the same target without a state change in between), no intermediate position during a storm scenario, and a readable timeline for a failed scenario.
- A **restart** operation: throw the core away, rebuild it from the storage, continue.
- A small command-line entry point for developers to run a named scenario and print the timeline. It is a development tool and is not shipped as part of the integration's runtime behavior.
- First scenarios with the features that exist: a workday and a weekend with the schedule only; a full year with daylight saving time changes; a restart at several points of the day; dry-run; maintenance lock; a stub fire trigger in each operating mode.

## Out of scope

- Scenarios for features that do not exist yet; their blocks add them.
- Any Home Assistant import. Plots or a graphical front end.

## Deliverables

Harness under `tests/` (or a development package outside the shipped integration, as the architecture document's module map says), scenarios, `docs/dev/simulation.md`: how to write a scenario, the cover behavior profiles, how to read a timeline.

## Acceptance criteria

- A simulated year for ten windows runs in well under a minute on a developer machine; the measured time is in the pull request.
- A run is fully reproducible: same scenario and seed, same record.
- Restarting the core at any of the tested points of the day yields the same subsequent commands as the uninterrupted run.
- With the schedule layer only, each window moves at most twice per day in the year scenario, and never at a time outside its clamps.
- In dry-run and under maintenance lock the record contains decisions but no commands, including for the stub fire trigger. A dry-run window next to a scripted second controller that moves the same cover arms no dam, and its decisions show the hypothetical outcome ("would have sent", or the rule that would have held the wish back).
- Each cover behavior profile is exercised by at least one scenario without a command loop.
- A deliberately broken rule (demonstrate once, do not commit) is caught by an assertion with a timeline that points to the moment.

## Required tests

The scenarios listed above as tests under `tests/core/`; unit tests for the simulated cover's profiles and for the assertions themselves.

## Open questions that block this block

None beyond D00. The parameter ranges of the cover profiles are refined when S1 has delivered; start with the taxonomy in the brief's section 7.
