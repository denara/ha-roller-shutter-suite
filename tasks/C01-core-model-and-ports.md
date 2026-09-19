# C01 — Core model and ports

| | |
|---|---|
| Kind | Implementation, pure domain core |
| Depends on | D00 (approved), T01, T02 |
| Blocks | C02, C03, C04, C09 and every later core block |

## Goal and reason

All core blocks after this one run in parallel and are written by different agents. They can only fit together if the data types they exchange exist first and are stable. C01 turns the vocabulary and the module map of `docs/architecture.md` into code: types and ports, no behavior.

## Read first

- `tasks/README.md`
- `docs/architecture.md` completely (vocabulary, module map, ports, reason codes, persistence model)
- `docs/project-brief.md`: guardrails 1, 4, 8, 11; features N2, N3, C15, A7

## Scope

Under `custom_components/roller_shutter_suite/core/`, as immutable, fully typed data types:

- **Position** with the convention 100 = open, 0 = closed (guardrail 11), validated on construction.
- **Wish** (target position, "leave alone", or no opinion), always with a **reason code** and the layer it came from; **constraint**; **gate decision** (send / defer until a point in time / suppress), each with a reason code; the final **decision** that carries the winning wish, the constraints applied, the gate outcome and the reasons of the layers that did not win.
- **Reason codes** as the closed enumeration from the architecture document.
- **Source value** with its three states: value, unknown, unavailable. No helper may turn "unavailable" into a default value.
- **Window configuration** as the core sees it after inheritance is resolved (input type of the arbiter), including **covering type** (only "roller shutter" is implemented; the field exists for C15) and an optional **condition input** for the morning opening (exists for A7, unused).
- **Capability profile** of a cover: supports open/close, set position, stop; reports position; **position source** (`measured` or `calculated` from run time; stated by the user, default `calculated`); reports transit states; position updates during travel. A cover without position feedback is a valid profile (N2). Per member also the **position reference** flag (`referenced` / `uncertain`) of the architecture document ("Calculated positions and drift").
- Whether a window has one cover or several operated as a unit, and whether a decision carries one target position or one per member, is decided in `docs/architecture.md` ("Several covers operated as one window"). Model exactly what it says: capability profile, observed state and own-command bookkeeping per member if it says so, with the window-level view derived from the members.
- **Window state** as observed (position or none, moving or not, available or not) and **world snapshot** (time, sun position, sources) that a recompute receives.
- **Ports** as protocols: clock, sun position provider, actuator, storage. The core never reads a clock or the sun itself.

## Out of scope

- Any behavior: no arbiter, no schedule, no geometry. Only construction, validation, equality and serialization helpers that the persistence model needs.
- Anything that imports `homeassistant`.

## Deliverables

The modules, their tests, and `docs/dev/core-model.md`: one page that lists the types with one sentence each and shows a worked example of a decision in prose.

## Acceptance criteria

- Names and meanings match `docs/architecture.md`; every deviation is listed in the pull request with its reason.
- Invalid values are rejected on construction (position outside 0–100, naive datetime, a wish with a position but no reason).
- Types are immutable and hashable where that makes sense; `mypy` strict passes.
- "Unavailable" and "unknown" cannot be converted into a number or a boolean by accident: there is no implicit truth value and no default-returning accessor.
- The core purity guard of CI passes.

## Required tests

Unit tests under `tests/core/` for construction, validation, equality and for the round trip of everything that the persistence model stores, including the rejection of naive datetimes.

## Open questions that block this block

- Approval of D00 by the project owner.
