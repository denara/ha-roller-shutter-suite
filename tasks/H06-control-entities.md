# H06 — Control entities: pause, maintenance lock, operating mode, resume, arming

| | |
|---|---|
| Kind | Implementation, Home Assistant layer |
| Depends on | H02 (the controls seam), H04 (entity conventions of the window device) |
| Blocks | H16; the pilot window can only be armed with this block; milestone M2 |
| Parallel with | C06 |

## Goal and reason

The arbiter has known pause, maintenance lock and operating mode since C03, and the runtime hands it neutral controls since H02 (`runtime.neutral_controls`). A user cannot touch any of them, and a window cannot be armed at all: version 0.1.0 stores `dry_run` for every window and offers nothing that changes it (gap list of `docs/pilot.md`). This block gives the user the four states the brief keeps distinct (E4, E9; guardrail 2: automatic, protection only, off, maintenance lock), the "resume automation" button (E2), and the deliberate step that arms a window (E11). It is the block after which the pilot window can leave dry-run.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: section 2.3 (gate rules 1, 4 and 5; the most restrictive value of the three levels), section 2.5 (the operating modes as a table), section 3.1 (what ends the manual override), section 13 (new windows start in dry-run), section 2.3 again for what arming discards
- `docs/dev/runtime.md`: "The recompute, step by step" (step 3, the controls), "What the runtime does not do yet" (the seam `SuiteRuntime.controls_of`), "Testing the runtime"
- `docs/dev/config-flow.md`: "Adding settings to an existing feature", "Adding a feature", "Reload"
- `docs/features/dry-run.md` ("Arming a window"), `docs/pilot.md` (section 8, the checks before arming), `docs/features/status-and-events.md`
- `docs/project-brief.md`: E2 (the button), E4, E9, E11; guardrail 2 (the four states), guardrail 5 (subentries, devices); section 6 "Home Assistant specifics" (the update-listener rule, devices and subentries)

## Verify before you build

- The current rules for `switch`, `select` and `button` entities with `has_entity_name`, translation keys, translated select options, entity categories and icon translations, at the Core tag the tests run against.
- How an entity is restored after a restart (`RestoreEntity`, `async_get_last_state`) and what it does not restore.
- Whether a config entry may own a device that belongs to no subentry next to the devices of its subentries, and whether a group subentry may own a device of its own (section 6 of the brief lists the device registry rules and their deprecations); quote the source.
- The current way to update the data of a subentry from outside a flow, and the rule of the brief that an update listener and a reloading flow method are not combined.

## Scope

- **Entities per level.** On the device of every window: a switch **Pause**, a switch **Maintenance lock**, a select **Operating mode** (automatic, protection only, off) and a button **Resume automation**. For every group and for the house: pause, maintenance lock and operating mode, on a device of their own (ruling 1 below). Switches and selects are configuration entities; all of them are translated in English and German, the select's options too. The help texts say plainly what each state does; the maintenance lock's text says that it also holds fire back, which is why it exists (guardrail 2).
- **Effective controls.** `SuiteRuntime.controls_of` reads the three levels and dry-run into `Controls`; the core works out the most restrictive value, as it does since C03. A change of any control recomputes the windows it concerns at once, through `async_request_recompute`, and never reloads the entry: a house-level pause reaches every window within the coalescing time. When a pause ends, the window is recomputed; nothing is replayed (E4).
- **External pause entities** (E4). An optional entity per level, in the settings registry of the core with the inheritance pattern, whose `on` state pauses the level in addition to the switch. A form page "Operation" contributes the setting for the house, the groups and the windows as `docs/dev/config-flow.md` describes, without a change to a flow class. An external entity that is `unavailable` or `unknown` **pauses** its level (ruling 4 below): a pause holds back comfort only, protection and fire keep running (gate rule 5, brief E4), so the cautious side is the one that stops comfort, as with a blind protection source. The status and the diagnostics of the windows concerned show that the pause comes from a source without a value, and after a configurable time (default one hour, as for a blind protection source in section 10.3 of the specification) a repair issue names the level and the entity; the issue disappears by itself when the entity has a value again. No new reason code: the decision reads `paused`, and the source is an attribute. There is no external entity for the maintenance lock or the mode.
- **Restart.** Pause, lock and mode survive a restart of Home Assistant (E6: locks are persistent), independently of the window state that block H05 writes to disk (ruling 2 below).
- **Arming a window** (E11). Arming is a deliberate step in the window's form, not an entity: the page "Operation" of the window's reconfigure flow offers **Dry-run** and **Armed**, and the transition from dry-run to armed leads to a page of its own that repeats the checks of `docs/pilot.md`, section 8 (one controller per window; switch the old control off first; compare once more), and requires a confirmation before the flow saves (ruling 3 below). The controller already starts an armed window with a clean state (`Engine.arm`, `controller.py`); a test proves that the transition through the form reaches it. Going back to dry-run needs no confirmation. The dry-run state of H04's status entity follows.
- **Resume automation** (E2). The button calls `Engine.resume` of block C06 for the window and recomputes it. Build it last: if C06 is merged by then, merge `origin/main` into the branch and wire it; if C06 is not merged when everything else of this block is done, leave the button out, say so in the pull request, and block H10 adds it (ruling 5 below).
- **Status, events and diagnostics.** The reason codes `paused`, `maintenance_lock`, `mode_off` and `mode_protection_only` exist and are translated; the decision of a held-back window reads them today already. The diagnostics of the entry and of a window show the controls of each level and the effective value. No new reason code.
- **Every entity follows the rules H04 made binding:** unique IDs, `has_entity_name`, translation keys, entity categories, unavailable when the window has no controller, no polling; the pilot safety test of M1 is extended, see the acceptance criteria.

## Out of scope

- Actions for automations, among them "clear override" and requests (H07). Wall buttons (H14). Sleep mode, privacy and the frost switches (H16). Per-window arming through an action or a switch entity. A dashboard card. Persisting the window state (H05).

## Deliverables

Platforms `switch.py`, `select.py`, `button.py` (or the extension of the existing platforms), the controls provider that replaces `neutral_controls`, the "Operation" form page with its translations, the arming step, tests, and documentation: a section "Controls" in `docs/dev/runtime.md`; for users a new `docs/features/controls.md` (pause, maintenance lock, operating mode and dry-run side by side in one table, what each holds back and what still moves, the three levels and "most restrictive wins", worked examples: scaffolding for a week, a party evening, a window that shall only follow the weather), the arming section of `docs/features/dry-run.md` rewritten for the real step, section 8 of `docs/pilot.md` (how to arm, once the checks are done), and the status paragraphs of `docs/configuration.md` that say a window cannot be armed.

## Acceptance criteria

- Pause on any of the three levels makes the next decision of every window concerned read `paused` for a comfort wish, while a protection wish (stub layer) still passes; the maintenance lock suppresses every class, and a stub fire trigger under lock fires its event and moves nothing; the operating mode follows the table of section 2.5; the effective value is the most restrictive of the three levels. Each of these is a test that toggles the entity and observes the decision, without a reload of the entry (a test counts reloads).
- An external pause entity that turns `on` pauses its level; one that is `unavailable` or `unknown` pauses it as well, the status names the source, protection and a stub fire trigger still pass, and after the configured time a repair issue appears and disappears again with the next value.
- After a restart of Home Assistant in the test, pause, lock and mode have the values they had before; without a stored state they are off, off and automatic.
- A window is armed only through the form's confirmation page; the test that arms the control window in `tests/ha/test_pilot_safety.py` uses that path instead of writing the subentry data, and the window starts armed with no dam and no simulated commands. The dry-run window of that test, with every control of every level toggled in every combination the test can reach, still causes zero calls on its cover.
- The resume button ends an armed override (state injected) and recomputes the window; without an armed override it changes nothing and logs nothing above debug. If the button is left out, this criterion moves to H10 and the pull request says so.
- No code outside `actuator.py` calls a cover action (`tests/ha/test_single_mover.py` passes unchanged); every user-facing string has both translations; the entity snapshot tests of H04 still pass, extended by the new entities.

## Required tests

Under `tests/ha/`: the entity platforms (set-up, naming, categories, availability), the effective controls per level, no reload on a control change, the restore after a restart, the arming flow, the external pause entity, the resume button, and the extension of `test_pilot_safety.py`.

## Rulings of the project owner (2026-09-25)

The questions the block file raised were answered before the start; the answers are binding.

1. **Where the house-level and group-level entities live:** one device for the house, owned by the config entry and no subentry, and one device per group, owned by the group's subentry; both are service devices with the integration's name. Guardrail 5 forbids groups to own window devices, not devices of their own, and a device per subentry is what the device registry expects. *Rejected:* house-level entities without a device (they would be orphans in the user interface), and group-level controls as settings in the group's form (a switch in a reconfigure form reloads the entry for every pause).
2. **How the controls survive a restart:** `RestoreEntity` for the switches and the select; it is Home Assistant's own mechanism for exactly this, works before block H05 exists and stays right after it, because the controls are entity state, not window state. Without a restored state the defaults are off, off and automatic, and the status shows the controls, so a lock that was lost is visible at once. *Rejected:* keeping the controls in the storage port, which is in memory until H05 and would lose a maintenance lock at every restart until then.
3. **How a window is armed:** a page of the window's reconfigure form with a confirmation page, as described in the scope, and no entity. Arming is the one step the brief calls deliberate; a switch on a dashboard is one tap away from a window that fights the old control. *Rejected:* a switch entity "Dry-run" per window (convenient, but the confirmation would have to be a text nobody reads), and an action for automations (H07 may add it later for advanced users, with the same core call).
4. **An external pause entity that is unavailable pauses.** The block file recommended the opposite; the project owner ruled differently, under the condition that a pause holds back comfort only, which section 2.3 of the specification (gate rule 5) and E4 of the brief confirm: protection and fire keep running under a pause. Then the cautious side is the pause, as with a blind protection source, with the status showing the source and a repair issue after the usual time. *Rejected:* "keeps running", because the user could then not stop the automation exactly when the source fails.
5. **The resume button and block C06.** The button needs `Engine.resume`, which C06 provides; both blocks run in parallel. As in the scope: build the button last, merge `origin/main` once C06 is on it, otherwise leave it to H10. *Rejected:* an own core function in this block (a Home Assistant block does not change the core), and waiting for C06 before starting (the rest of the block does not depend on it).

