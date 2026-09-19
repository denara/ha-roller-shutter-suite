# H04 — Status entities, reason events, logbook, diagnostics

| | |
|---|---|
| Kind | Implementation, Home Assistant layer |
| Depends on | H02 |
| Blocks | Milestone M1 |
| Parallel with | H03 |

## Goal and reason

Goal G4 is that the integration can explain why a window is where it is and what happens next. During the pilot this is also the only output: a window in dry-run moves nothing, so the owner judges the integration by comparing its stated decisions with what the old system actually did. If the explanation is poor, the pilot proves nothing.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: decision record, reason codes
- `docs/dev/runtime.md`
- `docs/project-brief.md`: E7, E8, D3 (the fire event is fired even when nothing moves); non-goals (no built-in notifications); section 6 (translation keys, quality scale)

## Verify before you build

- The current way for a custom integration to describe its own events in the logbook (the documentation page was not reachable during planning; check the Core source of the logbook component at the tested tag and quote it).
- The current rules for enumeration sensors with translated states, entity categories, entity naming with `has_entity_name`, and icon translations.
- The diagnostics platform API and redaction helper.

## Scope

- **Per window, on the window's device:** active reason (enumeration sensor whose options are the reason codes, translated), computed target position, next planned action (timestamp sensor with target and reason as attributes), override active (binary sensor, always off until C06/H10 exist), dry-run state. Attributes of the reason sensor carry the decision record in a compact, stable form: winning layer, constraints applied, gate outcome, and the skip reasons of the other layers.
- Entities follow the quality scale rules the brief makes binding: unique IDs, `has_entity_name`, translation keys, sensible entity categories, unavailable when the window's cover is unavailable, no polling.
- **Reason events (E8):** one event type on the bus, fired when a wanted movement is skipped, blocked or deferred, and when a command is sent or would have been sent in dry-run. Payload: window (subentry ID, device ID, name), reason code, layer, target, gate outcome. No event storm: an unchanged outcome is not fired again on every recompute. The **fire event** is fired immediately even if maintenance lock or dry-run prevent the movement.
- **Logbook entries** for these events with translated, readable messages.
- **Diagnostics download** for the config entry and per window device: resolved configuration with provenance, capability profile, last decision records, persisted state; entity IDs and names of the installation are redacted or clearly a user's own data, following the diagnostics guidance.

## Out of scope

- Control entities such as pause, mode and maintenance lock (H06). Notifications. A dashboard card. Repairs (H08, H12, H15).

## Deliverables

Entity platforms, event and logbook modules, diagnostics, translations, tests. For users: `docs/features/status-and-events.md` — what each entity means, the list of reason codes in plain language, an example automation that turns a reason event into a notification, how to download diagnostics.

## Acceptance criteria

- Every reason code of the core has an English and a German translation; a test fails when one is missing.
- The reason sensor changes when and only when the decision changes; its attributes allow reconstructing why lower layers did not win.
- A deferred or suppressed movement produces exactly one event per change of outcome, not one per recompute.
- A stub fire trigger on a window in dry-run and on a window under maintenance lock fires the fire event at once and sends nothing.
- Diagnostics contain no secrets and nothing the redaction guidance asks to remove; the test snapshot is free of instance data.
- Entities become unavailable with the cover and recover without a reload.

## Required tests

Under `tests/ha/`: entity setup and naming, state changes driven by decisions, event de-duplication, fire event under both blocks, logbook descriptions, diagnostics snapshot, translation completeness against the core's reason codes.

## Open questions that block this block

None beyond D00.
