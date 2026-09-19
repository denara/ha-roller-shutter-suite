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
- **Constraint interface and registry**, applied to the winning wish. Built here: the direction of a wish (`raise_only`, `lower_only`; A1, A6), and the basic frost protection of the architecture document ("Frost protection"): while frost is active and not waived, own movements open only up to the frost position; closing is never limited; comfort movements only by default, protection configurable, never fire, never a movement by hand; the optional "do not raise" is off by default; the waiver is an input of the constraint (its entities come with H16). The release by sun needs the geometry and is **not** part of this block (C10).
- **Gate** with its rules in the specified order. Built here: maintenance lock, operating mode (automatic / protection only / off), pause, movement already in flight, target already reached, motor protection (E10: minimum change and minimum interval, comfort movements only), the **dam mechanism** as such (a dam names what it holds back and until when), and **dry-run (E11) as the last rule**: whatever reaches it would have been sent. The decision of a dry-run window therefore shows the complete hypothetical outcome ("would have sent X" or "would have held back because of rule N"). Rules that depend on own commands are evaluated against simulated commands kept apart from the real state, which is discarded when the window is armed; the real motor protection clock is never touched in dry-run; no dam is ever armed in dry-run. The rules that arm the dams belong to C06 and C07.
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
- Dry-run: nothing is sent, including for fire. The decision shows the full hypothetical outcome: for a wish that another rule holds back (pause, mode, motor protection, a dam) that rule's reason; otherwise `dry_run` with the would-be target. A would-be send is remembered as a simulated command, so a minimum interval is reported realistically; the real clocks stay untouched, and arming the window discards the simulated state.
- **The dry-run record is stable:** the same inputs produce the same decision record, field by field, however often the window is recomputed; a recompute that changes nothing produces no new entry. In a simulated day of a dry-run window with constant conditions the record does not flap between two outcomes (for example between "would send" and `min_interval` because of its own simulated command). A test recomputes one hundred times under constant inputs and expects exactly one distinct record.
- The fire layer returns "open" while the alarm is active and "leave alone" (`fire_unacknowledged`) after it has ended until it is acknowledged; in that phase nothing is sent and no lower layer acts (exercised with the stub fire layer).
- Mode "off": comfort and protection wishes are suppressed, fire is sent. Mode "protection only": comfort suppressed, protection and fire sent.
- Motor protection holds back a comfort movement below the minimum change or inside the minimum interval with a "defer until" outcome, and never holds back protection or fire.
- A dam that holds back comfort layers lets protection pass; a dam that holds back protection never holds back fire; an expired dam has no effect.
- Frost limits the opening of a comfort movement to the frost position and never limits closing; in the default configuration it does not limit a protection movement; a waiver lifts it; fire ignores it.
- Every outcome carries a reason code from the closed list; no free-text reasons.

## Required tests

Unit tests under `tests/core/` for each rule; table-driven tests for the situations listed in the acceptance criteria of D00 that do not need a real feature layer; a property-style test that fire is sent in every combination of mode, pause, dams and motor protection unless maintenance lock or dry-run is active.

## Open questions that block this block

None beyond D00.
