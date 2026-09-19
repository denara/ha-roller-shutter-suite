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

## Decided after spike S2

The findings of S2 are in `docs/dev/config-flow-findings.md`; the project owner accepted them. The throwaway code on the branch `spike/s2-config-flow` may be read for orientation, but nothing is copied blindly: it was written to answer questions, not to the standards of this block. Binding for this block:

- **Inheritance in forms: pattern (a).** A number is an optional box-mode number field; empty means inherit; the own value is given as suggested value, never as default; zero is a valid own value because only the absent key means inherit. A boolean is a required drop-down "inherit / on / off" whose inherit entry names the present inherited value. The inherited value and the level it comes from are shown in the field's helper text through placeholders with language-neutral content. At house level fields are required and booleans are plain toggles. Feature switches are inheritable booleans too. **Stored form: an absent key means inherited.**
- **An empty string is treated like an absent key everywhere.** Inheritable text fields are kept out of sections.
- **Reload:** an update listener schedules the reload; flows end with `async_create_entry` or `async_update_and_abort` and never reload themselves (for subentry flows `async_update_reload_and_abort` raises when a listener exists). Save once, in the last step. A test counts set-ups: exactly one per create, reconfigure and remove; none for an unchanged form.
- **Home Assistant cover group:** recognized and resolved recursively with a cycle guard (order kept, non-covers dropped), shown to the user in a menu step before saving ("continue" / "choose other covers", because flows have no back button); the members are stored, never the group entity. The member check "a cover belongs to at most one window" runs when the step is submitted and again right before saving.
- **An option that the hardware cannot do is not offered.** In its place stands a read-only stand-in field at top level of the form (not inside a section) whose translated label and helper text give the reason and name the limiting member through a placeholder. Text built by the backend is never translated, so the reason is always a translation key.
- **Removing a group cannot be prevented** by Home Assistant. The fallback applies: a window whose group is gone inherits from the house, a repair issue names it, and saving the window's form repairs the reference.
- **The subentry title is the name.** The UI can rename a subentry outside any flow.
- **Typing bridge:** Home Assistant 2026.9 still annotates the flow API with `voluptuous.Schema`, and `mypy --strict` rejects a `probatio.Schema` there, although both are the same object at run time. Exactly **one** small, documented bridge function converts the type for the checker; schemas are written with `probatio` only and nothing imports `voluptuous`. The deprecated-names guard must keep passing.
- **Module layout:** a `flow/` package (model, inheritance, step mix-in with the decorator that attaches feature steps, cover resolution, group flow, window flow) and a `features/` package with one sub-package per feature that describes its settings as data (key, kind, default, range, expert flag, required capability, optional validator) plus a registry. A feature block adds a package and one registry line and edits no flow class.
- **Translations:** Home Assistant offers no modular translations for custom integrations. Each feature owns a fragment per language; a script under `scripts/` generates `strings.json`, `translations/en.json` and `translations/de.json` from them; tests check that the generated files are current and that both languages use the same keys and placeholders. **The fragments and their source folder live outside `custom_components/`** (for example `translations_src/` at the repository root), so that nothing but what Home Assistant needs is shipped.
- **Every change reloads the whole config entry**, and with it all windows. Windows are independent in what they do (G3), not in the reload; their runtime state has to survive it through persistence (H02, H05).
- **Out of this block:** steps for per-member values (measurements, position source, report delay, travel times). They were not tried in the spike and belong to the blocks that introduce those values. In this block a window's members are only selected, resolved and validated.
- A browser check of pattern (a) on the spike branch is done by the project owner before this block starts (emptied number, boolean back to inherit, the stand-in field, once inside a section). If it shows a different behavior than assumed here, the orchestrator updates this file first.

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
