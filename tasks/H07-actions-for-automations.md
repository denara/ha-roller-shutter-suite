# H07 — Actions for automations

| | |
|---|---|
| Kind | Implementation, Home Assistant layer |
| Depends on | H02 (the controller and its recompute), H06 (the arming step and the control entities, for the documentation of what an action may not do); for two of the five actions on core functions of C06 (`Engine.resume`) and C07 (`Engine.acknowledge_fire`, and the external request layer if the owner moves it there, see the open questions) |
| Blocks | H14 (buttons call the same core functions); A11 (alarm clock coupling) is only an interface and is done with this block; milestone M2 |
| Parallel with | C07 |

## Goal and reason

Feature F1 is the public interface of the integration for everything a user automates: an alarm clock that opens a bedroom, a scene that asks for a position, a script that clears an override or acknowledges the fire alarm, a maintenance routine that drives a shutter into an end position so that its actuator counts from a known point again. The brief keeps every priority central (A11): an automation never moves a cover of a window itself, it asks the integration, and the arbiter decides. Without this block every user with an existing automation has to move covers behind the integration's back, which is exactly what dry-run and the one-controller rule forbid.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: section 2.1 (layer 4, the external request; decision 2 on its place below sleep mode), section 2.4 (the acknowledgement of the fire alarm), section 3.1 (what ends the override), section 8.4 (the reference run: a request of class comfort, every protection applies), section 11 (the persisted request)
- `docs/dev/runtime.md` ("The recompute, step by step", `async_request_recompute`), `docs/dev/arbiter.md`, `docs/dev/core-model.md` (`ExternalRequest`)
- `tasks/C06-movement-tracking-and-dams.md` (`Engine.resume`), `tasks/C07-protection-events-fire-and-watchdog.md` (`Engine.acknowledge_fire`, open question 3 on the request layer), `tasks/H06-control-entities.md`
- `docs/project-brief.md`: F1, A11, N1 (the reference run), guardrail 1 (no feature moves a cover on its own), section 6 "Home Assistant specifics"
- `TASKS.md`, the row of this block: the note on loading service descriptions

## Verify before you build

- The current way to register actions of an integration and to describe them: `services.yaml` next to the integration, the `services` section of `strings.json` (names, descriptions, field names, field descriptions, translated in both languages through `translations_src`; check that `scripts/build_translations.py` can carry that section and extend it if not), selectors of the fields, `SupportsResponse` for an action that answers, and how an action targets a window: by device (`device_id` of the window's device) and by the window's entities, so that the target selector of the frontend works. Quote the developer documentation and, where it is silent, the Core source at the tested tag.
- **The note of the index row:** loading service descriptions with a `supported_features` or attribute filter makes Home Assistant import every base platform, including the voice pipeline, whose native packages are not part of the test environment. Find out whether the tests of this block reach that path. If they do: first try documented stand-in modules for the two native packages in `tests/ha/conftest.py` (no warning filter, nothing weakened); add the real packages as development dependencies only if that does not hold, because they have no wheel for the current Python, would be compiled in every CI run without a cache, and would make a C++ toolchain a build dependency of a pure Python project. Report which path you took.
- The quality scale rules for actions: registered in `async_setup` (not per entry), raising `ServiceValidationError` with a translation key for a wrong call, `HomeAssistantError` for a failure, no silent no-op.

## Scope

Five actions, each targeting one or more windows (by device; an action without a valid window target raises a translated validation error and does nothing):

1. **Request a position** (`request_position`): a position from 0 to 100, a reason text the caller gives (shown in the status and the logbook as the reason of the request, never as a reason code), and an optional duration after which the request expires (default: until cleared or until the next boundary between parts of the day; state the default you chose and why). The request is a wish of class comfort of the external request layer (layer 4), so it ranks below sleep mode: the documentation says plainly that an alarm clock automation must end sleep mode for that room first (decision 2). Every constraint and every gate rule applies; a window in dry-run records the request and moves nothing.
2. **Clear a request** (`clear_request`): removes the request of the window and recomputes it.
3. **Clear the override** (`clear_override`, the "resume automation" of E2 as an action): calls `Engine.resume` and recomputes; the button of H06 does the same.
4. **Recompute** (`recompute`): asks the controller for a recompute (`async_request_recompute`); useful after a change of a source the integration cannot see, and as a diagnostic step in the pilot guide. Nothing else changes.
5. **Acknowledge the fire alarm** (`acknowledge_fire`): calls `Engine.acknowledge_fire` of C07 and recomputes; the button of H14 does the same. Without an unacknowledged alarm it changes nothing and says so in the log at debug level.
6. **Reference run** (`reference_run`): drives a window fully into an end position (open by default, "closed" as an option) so that an actuator that calculates its position counts from a known point again (section 8.4). It is a request of class comfort with its own reason, so lockout protection, the maintenance lock, dry-run, an active protection event and frost protection apply to it like to any own movement; during frost it needs a waiver first (the waiver is H16's; until then the documentation says that a reference run during frost is refused with a reason). The integration never starts a reference run by itself. When the position reference flag of C06 exists, a complete movement into the end position sets it to `referenced`; the action does nothing with the flag itself.

Every action writes one logbook line through the existing reason event (a request arrives, is cleared, an override is cleared, a fire alarm is acknowledged, a reference run is requested) with the caller's reason text as an attribute where there is one; the status of H04 shows an active request with its reason and its expiry. The diagnostics show the request. A reload of the entry keeps a request (it is part of the window state); a restart forgets it until H05.

## Out of scope

- Buttons (H14). The arming of a window through an action (decided against in H06; a later block may add it). Notifications. Scenes as a feature of the integration: a scene calls `request_position` like any automation, and the user page shows one example. A request that names a group or the house: a request targets windows; the user page shows how to target all windows of an area or a label through the target selector of Home Assistant.

## Deliverables

`services.yaml`, the action handlers (one module, no cover call: `tests/ha/test_single_mover.py` must still pass), the translations of names, descriptions and fields in both languages, tests, and documentation: a section "Actions" in `docs/dev/runtime.md`; for users a new `docs/features/actions.md` with one worked example per action in the style of X08 (an alarm clock that ends sleep mode and requests 100 for the bedroom; a scene "TV evening" that asks for 30 with a reason; clearing an override from a wall display; the reference run on the first of the month; acknowledging the fire alarm from a notification action), the sentence about sleep mode and alarm clocks, and what an action does to a window in dry-run. The pilot guide gets one line: `recompute` as a diagnostic step.

## Acceptance criteria

- Each of the five actions exists with translated name, description and fields in both languages; a test drives each one against a window and observes the decision, the state and the logbook line; a call with an invalid target, position or duration raises `ServiceValidationError` with a translation key that exists in both languages, and nothing changes.
- A request ranks below sleep mode and above privacy and shading (tested against stub layers where the real ones do not exist yet); it expires when its duration has passed and is cleared by `clear_request`; it survives a reload of the entry.
- A request to a window in dry-run yields a "would have sent" record and zero calls on the cover; the pilot safety test of M1 is extended by one request to the dry-run window.
- The reference run is held back by the maintenance lock, dry-run, an active protection event (stub) and lockout protection (stub constraint) with the respective reason, and sent otherwise as an end position; it never bypasses anything.
- `acknowledge_fire` clears an unacknowledged alarm (C07 layer, or a stub until C07 is merged) and the next decision falls through to the lower layers; `clear_override` ends an armed dam (state injected) and recomputes.
- No code outside `actuator.py` calls a cover action; the service descriptions load without importing the voice pipeline in the tests, or the block reports which stand-in it needed; no deprecation, both translations complete.

## Required tests

Under `tests/ha/`: one test module for the actions (registration, each action, validation errors, targets by device, dry-run, reload), the extension of `test_pilot_safety.py`, the translation completeness of the `services` section.

## Open questions

None blocks the start; each has a recommendation, and the project owner answers in the pull request or before.

1. **Who builds the external request layer?** By the index it is C11's; this block needs it for `request_position` and the reference run. Recommendation: C07 builds it as its last item (see open question 3 of the C07 block file), and this block wires it; if C07 has not landed when this block is otherwise done, the two actions are registered with their descriptions and raise a translated "not available yet" error, and the pull request says so. *Rejected:* an own layer in a Home Assistant block (a Home Assistant block does not change the core); waiting for C11.
2. **Default expiry of a request.** Recommendation: until the next boundary between parts of the day, like the default end rule of the override, so that a request made in the afternoon does not still stand tomorrow morning; a caller who wants "until cleared" says so with a duration of zero. *Rejected:* no expiry by default (a forgotten request would freeze a window for ever) and a fixed number of minutes (the wrong number for every use).
3. **Targeting.** Recommendation: by device of the window, and also by any entity of the window (the frontend's target selector resolves both to the window's device); the house and a group are not targets. *Rejected:* a `window` field with the subentry ID, which no user knows.
4. **Reason text in the logbook.** Recommendation: the caller's text is shown as given, after the same check the forms apply to names (length, no control characters), and it is never translated. *Rejected:* a fixed list of reasons.
