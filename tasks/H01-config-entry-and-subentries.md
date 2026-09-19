# H01 — Config entry, group and window subentries

| | |
|---|---|
| Kind | Implementation, Home Assistant layer |
| Depends on | S2 (accepted), C02, T03 |
| Blocks | H02 and every later Home Assistant block |

## Goal and reason

Windows have to be addable one at a time while the house is renovated in stages (G2, G3, motivation 5), and adding one must mean: choose the cover, a group and a few values. This block builds the configuration skeleton that every feature block later extends with its own step, in the modular layout that S2 recommended, so feature blocks do not collide in one file.

## Read first

- `tasks/README.md`
- `docs/dev/config-flow-findings.md` (result of S2) — binding for patterns and module layout
- `docs/architecture.md`: window configuration, default for new windows, dangling group reference
- `docs/dev/core-model.md` (inheritance section)
- `docs/project-brief.md`: G2, G3; E12, F4, F7, N3, N4, N5; guardrails 5, 9, 10; section 6 "Home Assistant specifics"

## Scope

- **Main config entry** (one per installation): global settings that exist so far (day-type inputs, schedule defaults, operating defaults). Reconfigure flow instead of an options flow, using the update pattern that S2 proved to reload exactly once.
- **Group subentry:** name and the group-level settings; reconfigure.
- **Window subentry:** cover (entity selector restricted to covers), optional group, name, the schedule settings of C04 with the inheritance pattern of S2, dry-run with the default from the architecture document; reconfigure. One device per window, tied to its subentry.
- **Progressive configuration (F4):** feature switches first, then only the steps of enabled features, expert values in collapsed sections. In this block the only feature is the daily routine; the mechanism must be the general one, with each feature contributing step, schema and translations from its own module.
- **Validation (N3):** which covers a window may have (one, or several operated as a unit), how a Home Assistant cover group is treated, and what "a cover belongs to at most one window" means for members is defined in `docs/architecture.md` ("Several covers operated as one window"); implement that. A cover already used by another window is refused with a plain-language explanation.
- **Capabilities at configuration time (F7, first part):** read the cover's supported features and whether it reports a position; build the core's capability profile; a cover without position feedback is accepted and explained (N2). The full F7 (buttons, contacts, repairs on change) is block H12.
- **Removal (N4, first part):** removing a window removes its device and entities; removing a group that windows still refer to behaves as the architecture document specifies. Storage cleanup follows in H05.
- **Versioning (N5, first part):** config entry and subentry data carry version numbers; `async_migrate_entry` exists with a test, using the current exception-based error reporting for migrations.
- Conversion of stored settings into the partial settings of C02 in one place.

## Out of scope

- Runtime behavior, entities beyond what a device needs to exist (H02–H04). Settings of features that do not exist yet. Buttons, contacts.

## Deliverables

Config flow modules, translations (English and German), tests. For users: `docs/configuration.md` — first setup, adding a group, adding a window, changing and removing them, how inherited values look in the forms, each with a worked example.

## Acceptance criteria

- A user can create the entry, a group and two windows through the UI, reconfigure each, and remove each, without restarting Home Assistant.
- A reconfigure triggers exactly one reload and no deprecation message in the log.
- A value can be overridden at window level and returned to "inherit"; this works for a boolean and for a number whose valid value is zero.
- Selecting a cover that another window uses is refused with an explanation; selecting a cover without position feedback is accepted with an explanation of what will be inactive.
- The device of a window belongs to exactly one subentry; no deprecated device registry call is used.
- Every string a user sees comes from a translation key; English and German are complete.
- No use of `voluptuous`, `show_advanced_options`, or an options flow.

## Required tests

Under `tests/ha/`: full flow tests for entry, group and window (create, reconfigure, remove), each error path, inheritance round trip, cover uniqueness, capability explanation, migration from a fabricated older version, reload count.

## Open questions that block this block

- Acceptance of S2 by the project owner, in particular the inheritance pattern.
