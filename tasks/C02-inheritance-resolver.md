# C02 — Inheritance resolver

| | |
|---|---|
| Kind | Implementation, pure domain core |
| Depends on | C01 |
| Blocks | H01 |
| Parallel with | C03, C04, C09 |

## Goal and reason

Configuration is per window with defaults flowing from global to group to window (G2, E12): a window only states what differs. Resolving that is pure logic and must be testable without Home Assistant. The configuration UI (H01) stores raw, partial settings; the arbiter wants a complete, resolved window configuration. This block is the function in between.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: vocabulary, tie-breaking between global, group and window level, window configuration
- `docs/dev/core-model.md`
- `docs/project-brief.md`: G2, E12, N4

## Scope

- A representation of **partial settings** in which every value is either set or "inherit". "Inherit" is a distinct marker, never `None` with a second meaning, never a missing key that could also mean "not asked yet". A set value of `0` or `False` is a set value.
- The resolver: global settings + optional group settings + window settings → complete window configuration. A window without a group inherits from global directly.
- **Provenance:** for every resolved value the level it came from (built-in default, global, group, window), so the UI and the diagnostics can show "inherited from group …".
- Validation of the resolved result with errors that name the field and the level that set the offending value.
- Behavior for a window whose group reference points to a group that no longer exists (N4): a defined, tested outcome as specified in the architecture document.
- **Capability mask for inherited values.** A group cannot know what the covers of its windows can do, so a window can inherit an option that its own cover cannot execute (for example hold-to-move for a cover without stop, or a shading position for a cover without set position). The resolver therefore takes the window's capabilities (lowest common denominator of its members) and masks the resolved result: a setting that requires a missing capability resolves to "not available", with the provenance kept and the missing capability and the limiting member named, so that the UI (block H12) can explain it and the arbiter never acts on it. Which setting requires which capability is declared with the setting, in the same single place as its other properties.
- Settings that cannot be inherited (the cover itself, measurements of the window) are marked as such in one place.

## Out of scope

- The form and storage format of Home Assistant (H01). The list of concrete settings of features that do not exist yet: the resolver is generic over the settings structure; this block registers only the settings that C01 defines.

## Deliverables

Resolver module, tests, a section "Inheritance" in `docs/dev/core-model.md`. For users: `docs/concepts.md` with the section "Global, group, window: how settings are inherited", including a worked example with three windows.

## Acceptance criteria

- Window value beats group value beats global value beats built-in default, for every setting type.
- A window can return a value to "inherit" and then resolves to the group's value again.
- `0`, `False` and an empty list are respected as set values at every level.
- Provenance is correct for each of the four levels.
- A dangling group reference produces the specified outcome and never an exception that would stop other windows.
- A value inherited from a group is masked when the window's capabilities do not allow it; the result names the capability and the member, and the provenance still shows the group. A window's own value for such a setting is rejected by validation with the same explanation.
- Adding a new setting later requires a change in one place only; show this in the pull request description.

## Required tests

Table-driven unit tests under `tests/core/` covering all combinations of set / inherit over three levels for a boolean, a number with valid zero, an enumeration and an optional source; provenance; validation errors; dangling group.

## Open questions that block this block

None beyond D00.
