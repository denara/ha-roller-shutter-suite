# C03 — Arbiter: layers, constraints, gate

| | |
|---|---|
| Kind | Implementation, pure domain core |
| Depends on | C01 |
| Blocks | C05, C06, C07, C08, C10, C11, H02 |
| Parallel with | C02, C04, C09 |

## Goal and reason

The arbiter is the central architectural principle (E5, guardrails 1 and 2): one place per window decides, deterministically and explainably (G4), and every other feature only contributes a layer, a constraint or a gate rule. This block builds the mechanism and the rules that do not belong to a single feature. Feature layers are added by later blocks without touching the mechanism.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: arbiter, fire bypass, the two dams, operating modes, reason codes
- `docs/dev/core-model.md`
- `docs/project-brief.md`: guardrails 1–3; features E4, E5, E9, E10, E11, A6, A12, D3

## Scope

- **Layer interface and registry:** a layer receives the window configuration, the world snapshot and the window state, and returns a wish with a reason code. Layers are evaluated in the fixed order of the architecture document; the first opinion wins; every layer that did not win still reports why. Adding a layer is a registration, not a change of the arbiter.
- **Constraint interface and registry**, applied to the winning wish. Built here: evening and night moves downward only (A6) as the generic "never raise" constraint, and frost protection (A12: comfort movements only by default, configurable, never against fire).
- **Gate** with its rules in the specified order. Built here: maintenance lock, operating mode (automatic / protection only / off), pause, dry-run (E11), movement already in flight, target already reached, motor protection (E10: minimum change and minimum interval, comfort movements only), and the **dam mechanism** as such (a dam names what it holds back and until when). The rules that arm the dams belong to C06 and C07.
- **Fire bypass** as the named construct of the architecture document: it skips exactly the listed gate rules and never the maintenance lock and never dry-run. In this block it is exercised with a stub fire layer; the real one comes with C07.
- Operating modes are a closed set of three in this block; the place where a mode maps to "which layers are suppressed" is a table, so that named profiles (E9b, deferred) could be added later without restructuring. Nothing of E9b is built.
- **Decision record:** everything needed for the status entities and reason events: winning layer, reason, constraints applied, gate outcome with its reason, and the skip reasons of all other layers.
- Two trivial layers so the arbiter is testable end to end: a stub "schedule" layer and a stub "protection" layer, living in the tests.

## Out of scope

- Real feature layers (schedule C04, protection C07, window interaction C08, shading C10, sleep and privacy C11).
- Manual detection and the arming of dams (C06, C07). Staggering across windows (H03). Persistence (C12).
- Home Assistant.

## Deliverables

Arbiter modules, tests, `docs/dev/arbiter.md` (how to add a layer, a constraint, a gate rule; the evaluation order; the fire bypass). For users: section "How the integration decides" in `docs/concepts.md`, in plain language with two worked examples.

## Acceptance criteria

- The same inputs always give the same decision; the arbiter holds no hidden state and reads no clock.
- A "leave alone" wish from a higher layer stops lower layers and results in no movement, with its reason.
- An unavailable input in a layer never produces a position; it produces "leave alone" or no opinion as specified.
- Maintenance lock: nothing is sent, including for the stub fire layer; the decision record still names fire as the winning wish, so the event can be fired.
- Dry-run: nothing is sent, including for fire; the gate outcome says what would have been sent.
- Mode "off": comfort and protection wishes are suppressed, fire is sent. Mode "protection only": comfort suppressed, protection and fire sent.
- Motor protection holds back a comfort movement below the minimum change or inside the minimum interval with a "defer until" outcome, and never holds back protection or fire.
- A dam that holds back comfort layers lets protection pass; a dam that holds back protection never holds back fire; an expired dam has no effect.
- Frost limits a comfort movement and, in the default configuration, not a protection movement.
- Every outcome carries a reason code from the closed list; no free-text reasons.

## Required tests

Unit tests under `tests/core/` for each rule; table-driven tests for the situations listed in the acceptance criteria of D00 that do not need a real feature layer; a property-style test that fire is sent in every combination of mode, pause, dams and motor protection unless maintenance lock or dry-run is active.

## Open questions that block this block

None beyond D00.
