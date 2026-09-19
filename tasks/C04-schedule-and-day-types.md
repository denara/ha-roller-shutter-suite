# C04 — Schedule and day types

| | |
|---|---|
| Kind | Implementation, pure domain core |
| Depends on | C01 (the layer interface of C03 is needed to finish; start against `docs/architecture.md`) |
| Blocks | C05, milestone M1 |
| Parallel with | C02, C03, C09 |

## Goal and reason

The daily routine replaces the time programs of the old controller and is the lowest layer of the arbiter. It is also the only feature layer of the walking skeleton (M1), so it is the first proof that "the target state is a function of the current situation" works: after a restart or a pause nothing is replayed, the schedule simply says what applies now (G5, guardrail 1).

## Read first

- `tasks/README.md`
- `docs/architecture.md`: parts of the day, schedule and catch-up, day types, random offsets
- `docs/dev/core-model.md`, `docs/dev/arbiter.md`
- `docs/project-brief.md`: features A1–A6, A3, E13 (random offset only), A7 and D7 (doors to keep open)

## Scope

- **Day type** of a date from the day-type inputs defined in the architecture document (workday, weekend, public holiday), with the specified behavior when an input is unavailable.
- **Trigger times** per day type for morning and evening: fixed time, sunrise or sunset with offset, or sun elevation, clamped by "not before" and "not after" (A2). Evening additionally by an optional outdoor brightness source with the delay rules of the architecture document (A4). Sun times come through the sun port; the core computes nothing astronomical on its own here.
- **Parts of the day** derived from these triggers, and the **target state per part of the day**: morning target position (A1), evening position, seasonal evening position (A5) with the season source from the architecture document.
- The **schedule layer**: returns the wish of the current part of the day. Morning opening only raises (A1: only if the shutter is lower than the target); evening and night only lower (A6), expressed through the constraint of C03, not re-implemented.
- **Random offset** (E13) per window and day, deterministic for a given seed so tests and the simulation are reproducible; the seed handling follows the architecture document.
- **Next planned action:** time, target and reason of the next schedule change, for the status entity (E7).
- The **condition input** of the morning opening (A7) exists in the interface and is always "fulfilled".

## Out of scope

- Sleep mode (C11), evening closing with an open window (C08), staggering between motors (H03), absence profiles (D7), school holidays.
- Reading entities, calendars or the sun from Home Assistant (H02).

## Deliverables

Schedule modules, tests. For users: `docs/features/daily-routine.md` — what can be set, how astro times and the clamps interact, what happens after a restart, with a worked example for a workday and a weekend.

## Acceptance criteria

- For any point in time the layer returns the same wish, whether the core has been running for days or was just started: no dependency on having seen a trigger.
- "Not before" and "not after" clamp astro and elevation triggers on both sides; a trigger that never occurs on a day (polar or deep-winter edge cases for elevation) falls back to the clamp.
- Daylight saving time changes and the change of day are handled without a skipped or doubled part of the day.
- An unavailable day-type input leads to the specified fallback and a reason code, never to an exception.
- An unavailable brightness source never triggers the evening closing by itself and never blocks the time-based closing.
- The random offset is stable within a day for a window, differs between windows, and stays inside the clamps.
- "Next planned action" is correct across midnight and across a change of day type.

## Required tests

Table-driven tests under `tests/core/` with a fake clock and a fake sun port: each trigger kind, the clamps, each day type, daylight saving time changes in both directions, midnight, unavailable inputs, random offset determinism, next planned action.

## Open questions that block this block

- D00 decisions on catch-up, parts of the day, day-type mapping and season source.
