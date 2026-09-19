# S2 — Spike: subentries, sections and inheritance in the configuration UI

| | |
|---|---|
| Kind | Spike (throwaway code on its branch, written result is the deliverable) |
| Depends on | T02 |
| Blocks | H01, and through it the whole Home Assistant layer |

## Goal and reason

Guardrail 5 puts the whole configuration on config subentries (groups and windows), F4 on sections, and E12 on inheritance from global to group to window. Three things are unproven: whether subentry flows really support what is needed (several steps, sections, reconfigure); how a user sees an inherited value, overrides it and later returns to "inherit" within the limits of Home Assistant forms; and how a reconfigure flow updates data without triggering the deprecated double reload. None of the related projects has solved inheritance. Finding the limits now is cheap; finding them after six feature blocks have added their configuration steps is not.

## Read first

- `tasks/README.md`
- `docs/project-brief.md`: goals G2, G3; features E12, F4, F7, N3, N4; guardrails 5, 9, 10; section 6 "Home Assistant specifics" (one subentry per device, update listener and reload, sections cannot be nested, the list of unverified items)

## Questions to answer

1. **Subentry flows:** Do they support several steps, sections and selectors like config flows? What are the exact, current methods to create, update and remove a subentry, and what does the reconfigure step of a subentry look like? Quote the source.
2. **Group reference:** A window stores the subentry ID of its group. How is the group chosen in the form (selector with dynamic options), what happens when the group is removed while windows refer to it, and how can removal be prevented or handled (N4)?
3. **Devices:** one device per window subentry, entities attached to the subentry. Do groups get a device of their own (for their switches) and does the single-subentry rule allow it? Are the device registry calls used free of the deprecations named in the brief?
4. **Inheritance in forms:** Compare at least these patterns on a real form and recommend one: (a) optional fields where empty means inherit, with the inherited value shown as placeholder or in the description; (b) an explicit "use own value" toggle per field or per section; (c) a separate "overrides" step that lists only the values that differ. Judge each by: can the user see the effective value, can the user return to "inherit", do booleans and numbers with a valid zero work (the classic trap: an optional boolean that cannot be switched back), how many translation strings does it need.
5. **Reload without deprecation:** which combination of update listener and flow method is used so that a reconfigure applies changes exactly once? Prove it with a test that counts setups.
6. **Capability-aware options (F7):** how can an option be shown as unavailable with a plain-language reason? Forms cannot disable a field; evaluate the alternatives (omit the field and explain in the step description with placeholders, a read-only information field, an abort reason).
7. **Progressive configuration (F4):** feature switches first, then only the steps of enabled features. Show that a flow can branch like this inside a subentry flow and that a **modular layout** works, in which each feature contributes its step and its schema from its own module, so later blocks do not all edit one file.
8. **Validation (N3):** refuse a cover that already belongs to another window, with an explanation.

## Out of scope

- Production code. The spike's code stays on its branch and is not merged; only the written result is.
- Real feature logic, entities beyond a dummy.

## Deliverables

- `docs/dev/config-flow-findings.md`: answers to the eight questions with sources, the recommended inheritance pattern with screenshots or form descriptions, the recommended module layout for H01, and a list of limits that affect the brief (to be reported to the owner, not worked around silently).
- The spike branch, referenced from the document, with tests that demonstrate questions 1, 2, 5 and 8.

## Acceptance criteria

- Every question has an answer backed by a running test or a quoted primary source; "could not be determined" is an acceptable answer only with the reason and a proposal.
- The reload test proves exactly one setup per reconfigure and no deprecation in the log.
- The recommended inheritance pattern handles: a boolean returned to "inherit", a number whose valid value is zero, and a value inherited over two levels.
- Nothing in the spike uses `voluptuous` or `show_advanced_options`.

## Open questions that block this block

None.
