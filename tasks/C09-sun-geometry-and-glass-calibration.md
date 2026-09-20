# C09 — Sun geometry and glass calibration

| | |
|---|---|
| Kind | Implementation, pure domain core |
| Depends on | C01 (merged), C02 (merged; for the way settings are declared) |
| Blocks | C10 (shading episodes), H11 (wiring of shading), H13 (roof window profile) |
| Parallel with | C03, C04, H01 |

## Goal and reason

Shading shall let the sun enter a room only up to a permitted depth, and it shall do so for windows of different size, for several covers that act as one window, and for roof windows (features C1, C2, C7, the geometric part of F3). All of that is plain geometry. It belongs in one module that knows nothing about layers, episodes, temperatures or Home Assistant, so that it can be tested with numbers on paper and reused by the shading layer (C10), the status display and the simulation. The block answers one question: **for this sun position and this window, to which position does each member have to move so that the sun enters no further than permitted, and is the sun on this window at all?**

## Read first

- `tasks/README.md`
- `docs/architecture.md`: section 9 "Several covers operated as one window", in particular **decision 9** (one decision, mapped per member; ray height; members above each other: one element, one curtain edge, top-edge offset per member) and both neutral examples there; section 14 (module `geometry`); section 8.1 (capability profile: a member without position control cannot take an intermediate position)
- `docs/dev/core-model.md`: `Position`, `SunPosition`, `WindowConfig` and its members, and "Inheritance" with "How a later block adds a setting"
- `docs/project-brief.md`: features C1, C2, C7, F3; guardrail on calculated positions (E10/N1 context: reported positions are estimates)

## Scope

All under `custom_components/roller_shutter_suite/core/geometry/` (a package or a module, your choice), pure functions and frozen value types, no clock, no ports, no imports from `homeassistant`.

- **The sun relative to the window.** From the sun position (azimuth, elevation) and the window's orientation (azimuth of the outward normal): the horizontal angle between sun and normal, whether the sun is inside the window's field of view (separate limits to the left and to the right, as seen from inside looking out; state the convention and test it for windows facing every quarter, including the wrap-around at north), and whether it is above the configured minimum elevation and below nothing (C7: a minimum elevation for the start that covers horizon obstruction, and an elevation below which shading ends; both are inputs here, the episode logic is C10). Result type: "sun on the window" yes or no with a reason a later layer can turn into a reason code; this block adds no reason codes.
- **Ray height.** The height above the floor up to which the sun may enter, from the permitted penetration depth, the sun elevation and the horizontal angle: the more obliquely the sun strikes the façade, the longer its path across the floor per unit of depth into the room, so the shutter may stay higher; this follows from the geometry and is not a separate rule (C1). **The amplification is capped** as the sun approaches the façade plane; the cap is a parameter with a documented default. Say in the documentation what "depth" means (perpendicular to the façade, measured on the floor from the inside of the glass plane) and show the formula.
- **Roof pitch (F3, geometric part).** Glass that is tilted by a pitch angle from the horizontal (90° is vertical glass, which must give exactly the results of the vertical case). Lengths along the glass, the top edge of the element above the floor, and the curtain edge are computed in the plane of the glass. State the formula and the convention for the pitch, and what happens when the sun is behind the glass plane (it is not on the window).
- **One curtain edge per element.** The covered length `e`, measured from the top of the element along the glass, clamped to the element, from the ray height and the element's measurements. Then **per member**: the part of `e` that falls into the member's own range, from the member's top-edge offset and glass height, as a covered fraction of that member. A member without an offset has offset 0. Members inherit the window's measurements unless they state their own. Both neutral examples of decision 9 are required tests, with the numbers of the document.
- **Glass calibration (C2), in both directions, per member.** Two values per motor: the position at which the curtain reaches the lower end of the free glass ("seating point") and the position at which it reaches the upper glass end. Between them the mapping between "covered fraction of the glass" and motor position is linear; outside them the glass is fully free or fully covered. Forward (covered fraction → target position) and backward (reported position → covered fraction, for the status display and for the decision record). Defaults that mean "no calibration": the full range. Position convention as in the core model: 0 is closed, 100 is open; say so where a formula could be read either way. Round to whole positions in ONE documented place, and make forward-then-backward stable (a test).
- **Members that cannot take an intermediate position** (capability profile: no position control): the geometry still reports the ideal position; it additionally offers the documented conservative choice between the two end positions (covered as soon as the ideal position covers any glass, or a threshold — propose one, with the reason, as an interpretation). Whether it is used is C10's decision.
- **Simple mode.** A window without measurements gets a fixed shading position instead of a computed one (C1). The geometry module offers the same interface for it, so C10 does not branch: "sun on the window" is still computed from orientation and field of view if those are given, the member positions are the fixed position.
- **The result for one recompute** is one frozen value: sun on the window (with the reason if not), ray height, curtain edge `e`, and per member the covered fraction, the ideal position and the position after calibration. The decision record of C10 will carry ray height and per-member positions (decision 9), so the type has to be serializable the way the core model's values are.
- **Measurements as configuration.** Define the value types for the window-level measurements (orientation, field of view left and right, sill or element-bottom height, element height or glass top, permitted depth, pitch, minimum elevation, end elevation, cap, simple-mode position) and for the member-level ones (glass height, top-edge offset, the two calibration values), with validation in the types (ranges, top above bottom, offsets inside the element, calibration points in order and apart). **How they reach `WindowConfig`:** window-level values that a group or the house may set are inheritable settings of the function `shading` in the registry of C02, added by the seven documented steps. Member-level values live with the member; they inherit from the window, not from group and house, which the registry does not model today. **Propose** how member-level values are declared (your recommendation, one rejected alternative) **before** you build that part, because it changes the C01 model and block H11 builds forms from it. Everything else in this block does not depend on the answer; build it first.

## Out of scope

- Episodes, temperature and radiation conditions, hysteresis in time, the shading and solar-heating layers, reason codes (C10). The recompute cycle (H02). Forms and entities (H11, H13). The rain and heat rules of the roof window profile (C07, C10, H13). Computing the sun position (it arrives through the snapshot).

## Deliverables

The geometry module, tests, and documentation: for developers `docs/dev/geometry.md` (conventions, formulas with a drawing in text or Mermaid, the result type, how C10 calls it); for users `docs/features/shading-geometry.md` — what to measure and how, with a drawing, for a normal window, for several covers side by side, for a roof element of two rows, and what the two calibration values are and how to find them with a tape measure and the cover's position slider. **A worked roof window example with a real pitch**, neutral numbers, in the style of the two tables of decision 9; the architecture document announces it for this block. All numbers in examples are made up and neutral.

## Acceptance criteria

- Vertical glass, sun straight ahead: the numbers of the first example of decision 9 (ray heights 1.19 m and 1.73 m; positions 21, 36, 59, 100) come out of the module.
- Two rows: the three rows of the second example of decision 9 come out of the module (positions 60 and open; closed and open; closed and 50).
- A pitch of 90° gives exactly the vertical results; the roof example of the documentation is a test.
- The more oblique the sun, the higher the shutter stays, monotonically, up to the cap; at and beyond the façade plane the sun is not on the window. No division by zero, no exception and no position outside 0–100 for any sun position, including elevation 0, 90 and negative, and for any valid measurements (a property-style test over a grid).
- The field of view works for every orientation including the wrap-around at north, with different limits left and right.
- Calibration: forward and backward are inverse within rounding; the defaults change nothing; invalid calibration values are refused by the type with a message that names the field.
- Members inherit the window's measurements unless they state their own; equal members get equal positions.
- The module imports nothing from `homeassistant` and reads no clock (the purity guard passes), and core coverage stays at or above its threshold without coverage pragmas.

## Required tests

Table-driven tests under `tests/core/` with the numbers of the architecture document and of the new documentation; the grid test; the orientation and field-of-view table; calibration round trips; validation of every measurement type; the registry entries of the window-level settings through the safety-net test of C02 and one test through `resolve_window`.

## Open questions that block this block

None for the geometry. The declaration of member-level values is decided with the orchestrator during the block (see "Measurements as configuration").
