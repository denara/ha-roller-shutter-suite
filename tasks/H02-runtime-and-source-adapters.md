# H02 — Runtime and source adapters

| | |
|---|---|
| Kind | Implementation, Home Assistant layer |
| Depends on | C03, C04, H01 |
| Blocks | H03, H04, and every wiring block after M1 |

## Goal and reason

The core decides; something has to feed it and call it. This block is the thin adapter of guardrail 4 on the input side: it turns Home Assistant entities, time and the sun into the core's world snapshot and triggers a recompute when something relevant changes. It is where two rules of the brief are enforced once for everybody: "missing data is not good news" (D6, guardrail 8) and "durations are tracked with own timestamps" (section 6).

## Read first

- `tasks/README.md`
- `docs/architecture.md`: ports, source states, recompute triggers, startup behavior
- `docs/dev/core-model.md`, `docs/dev/arbiter.md`
- `docs/project-brief.md`: G5, G6; guardrails 1, 4, 8; section 6 ("Safety and behavior", "Home Assistant specifics")

## Scope

- **Runtime object** per config entry in `entry.runtime_data`: owns one window controller per window subentry; windows can be added, reloaded and removed individually without affecting the others (G3).
- **Source adapter:** reads an entity state **or an entity attribute** (guardrail 8), converts units where Home Assistant provides them, and maps to the core's three states. `unavailable`, `unknown`, a missing entity and a non-numeric value where a number is expected all become "unavailable" or "unknown", never a default.
- **Duration tracking:** "condition has held for X" is measured with the integration's own timestamps, started when the adapter first sees the condition; a restored state after a restart does not count as the start and does not count as a change.
- **Clock and sun ports:** time from Home Assistant; sun position through the `astral` library with the observer from the current, non-deprecated Home Assistant helper. No dependency on the `sun` entity.
- **Recompute triggers:** state changes of the entities a window uses, points in time the core asked for ("defer until", "re-evaluate no later than", the next schedule change, the schedule's `recheck_at`), a periodic safety tick, and an explicit request. Recomputes of one window are serialized; a burst of changes is coalesced. **Wake-up times cannot form a loop:** a time the core asks for is accepted only if it lies strictly in the future, and the runtime enforces a minimum distance between recomputes that come from wake-up times (default a few seconds, a constant in one place), so that a fault in a layer that keeps asking for "now" cannot spin. A test feeds the runtime a core stub that always asks to be woken at once and checks that the number of recomputes stays bounded and that the fault is logged once.
- **Startup:** wait until the managed cover is available before the first decision; late availability is normal and not an error; a window whose cover stays unavailable reports that as its state instead of failing the entry.
- **Unload and reload** cancel every listener and timer.
- The actuator port is called with the gate's outcome; its implementation is H03. Until then a recording stub is used in tests.

## Added after blocks C03 and C04 were merged

- **The snapshot carries the sun times as data.** A recompute asks no port. Whenever the runtime builds a `WorldSnapshot` it calls `build_sun_almanac(config, time, sun_port)` of the core and passes the result as `almanac`, and it rebuilds the almanac when the local date or the schedule settings change. It provides the `installation_seed` (stable per installation, stored). Without them the schedule has no opinion (`input_unavailable`).
- **Local time zone.** `WorldSnapshot.time` and the time handed to `build_sun_almanac` carry the NAMED local zone of the installation. A time in UTC or with a fixed offset would silently put every local time of the schedule into the wrong zone or lose the rule for clock changes. A test with a zone that changes its clock.
- **Schedule state.** The runtime persists what `schedule_state_after` returns right after a recompute at a boundary, not only on shutdown (day-type latch, brightness instants).
- **`recheck_at` and the next planned action** are strictly in the future; the runtime enforces a minimum distance between wake-ups.
- **`WorldSnapshot.controls`** carries pause, operating mode, maintenance lock and dry-run of the three levels; the arbiter works out what is effective.
- **From the review of H01:** `WindowRuntime` is the hand-over point from the configuration side. The provisional travel time of 60 seconds that H01 uses for the core's capability profile lives in memory only; it is never stored and never treated as a value the user set, and it disappears with the block that introduces per-member values. Runtime state must survive the full reload that every configuration change causes. A window that is no longer set up keeps its old device until the subentry is removed (clean-up in H05).
- **Fault details** that come from a caught exception should name the exception type when it is not a plain refusal of a value, so that diagnostics can tell a programming error from bad data.

## Out of scope

- Sending commands (H03), entities and events (H04), persistence (H05), forecasts and weather (H11).

## Deliverables

Runtime and adapter modules, tests, `docs/dev/runtime.md` (life cycle of a window controller, recompute triggers, how to add a source).

## Acceptance criteria

- A source given as attribute of another entity works like a source given as entity.
- For each of: `unavailable`, `unknown`, entity removed, non-numeric state — the core receives "unavailable" or "unknown" and no number; a test shows that a schedule decision with an unavailable day-type input follows the specified fallback.
- After a simulated restart with restored states, no duration condition is considered fulfilled until it has held for its full time as observed by the integration.
- No decision is made for a window before its cover is available; when the cover appears later, the window starts working without a reload.
- Adding, reloading and removing one window leaves the listeners and timers of other windows untouched; after unload no listener or timer remains (checked in the test).
- A burst of ten state changes within a second causes one recompute.
- **Capabilities do not flap.** The resolver of block C02 takes each capability as present, missing or unknown. The runtime reads capabilities from the entity; while a member's entity is unavailable, at start or for a while, it hands in the last known state (from the entity registry, or from what was persisted), and "unknown" only if there is none. A restart with a cover that becomes available late, and a cover that is unavailable for a few minutes, produce no mask, no repair issue and no change of the resolved configuration. Tests cover both.
- **One faulty window does not stop the others, and a fault never costs a window its protection.** Faulty stored settings are handled by the resolver of block C02 as decision 15 of `docs/architecture.md` says: the window still gets a configuration, with protection intact and the comfort functions concerned switched off; the runtime passes the disabled functions on to the arbiter and shows them in the window's status. If a window's covers cannot be read (block H01 reports it as a repair issue), or if creating its controller raises, the runtime sets up every other window and keeps running; the failure is logged once with the window's name and never propagates out of the entry's set-up. The protection and fire functions of the other windows must not depend on a single stored entry. A test sets up an entry with one valid and one faulty window and checks that the valid one decides and the entry is loaded.
- **A reload is harmless.** Every configuration change reloads the whole config entry and therefore every window. A reload while a movement is in flight, while a dam is armed or while a gate outcome is deferred produces **no false manual detection and no duplicate command**: the pending own command, its expectation deadline, the dams and the deferral survive the reload (in this block through the interface to the storage port with an in-memory implementation; the real storage is block H05). The test covers a member with a report delay of 60 seconds, whose end report arrives long after the reload.
- Time in tests is controlled; no test sleeps.

## Required tests

Under `tests/ha/`: each acceptance criterion as a test, using fake entities and the frozen-time facilities of the test harness.

## Open questions that block this block

None beyond D00.
