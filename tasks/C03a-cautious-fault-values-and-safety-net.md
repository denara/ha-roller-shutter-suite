# C03a — Cautious fault values and the arbiter's safety net

| | |
|---|---|
| Kind | Implementation, pure domain core |
| Depends on | C02, C03, C04 (all merged) |
| Blocks | Milestone M1 and any real installation |
| Parallel with | H01 (review), C09 |

## Goal and reason

Decision 15 says that no restriction is ever lifted by a data fault. The review of the arbiter found a case where exactly that happened: an unreadable frost source on the only level that set one fell back to the built-in default, the default "no source" means "frost protection is not configured", and the frost limit disappeared. With a valid source the shutter opened to 90 in frost; with the unreadable one it opened to 100. The resolver followed the letter of the rule; the rule had a gap. The same gap exists for every optional reference and every switch of a function that falls back (a lockout contact, a window contact, "frost applies to protection").

The project owner closed the gap with a principle, now part of decision 15: **a faulty value of a function that falls back never makes that function less restrictive than a valid value would. If another level supplies a valid value, it applies; otherwise the cautious value of the setting applies, not its default.**

The same direction must hold for programming errors: an exception inside the arbiter must never loosen a restriction and must never stop a fire or protection decision. The first known case is the frost reader, which raises a `TypeError` for a source that delivers text.

## Read first

- `tasks/README.md`
- `docs/architecture.md`: section 13a (decision 15 with the principle and the paragraph on exceptions), section 2 (arbiter, fire bypass), section 2.6 (frost, blind source), the rules for blind sources wherever they appear (frost limit stays; an unknown contact never leads to closing)
- `docs/dev/core-model.md` ("Inheritance", fault tables, "How a later block adds a setting"), `docs/dev/arbiter.md`
- The code: `core/settings.py`, `core/model/window.py`, `core/arbiter/`, the frost constraint

## Scope

**Part 1 — fault values in the registry and the resolver.**

- `SettingDefinition` gets a **fault value** next to `default`. For a setting of a function that falls back it is REQUIRED and stated on purpose (no silent default of the parameter; often it equals `default`, and then the entry says so explicitly). For a setting of a function that pauses, and for a setting without a function, it does not exist (refused), because a fault pauses the function or nothing depends on it.
- The resolver: a faulty value of a function that falls back is skipped as today. If another level supplies a valid value, that value is effective (unchanged). If none does, the **fault value** is effective instead of the default. The report says so (a new action next to `fell_back`, for example `fell_back_to_cautious_value`; say in the pull request how a repair issue can tell the two apart). A `combination` fault among keys of a function that falls back ends at the fault values, not at the defaults, when no level is left; the fault values together must satisfy every rule over several settings (a test, like the one for the defaults).
- **A level that is unreadable as a whole** (rule 5 of decision 15): for every INHERITABLE setting of a function that falls back for which no other level supplies a valid value, the fault value is effective, because nobody can see whether the unreadable level had set one; the report names the level and the action. A setting that is not inheritable is never affected by an unreadable house or group level (only by an unreadable window), otherwise one broken house level would stop every window from closing. Tests: unreadable house, unreadable group, unreadable window; with and without a valid value on another level; a non-inheritable reference stays untouched by an unreadable house.
- **Optional references to a source:** the fault value means "configured, but blind". `WindowConfig` must be able to carry that fact without a made-up entity ID. Propose the shape (recommendation and one rejected alternative) before building; one possibility is a marker value of the core next to the existing "none" marker, which can never be stored, only produced by the resolver. The frost constraint treats it exactly like a configured source that delivers nothing: the existing blind path (`frost_limit_source_blind`), the cautious limit stays.
- **Decided later by the project owner:** a fault value never restricts PROTECTION wishes more than the default does; cautious fall-back values may restrict comfort only (`frost_applies_to_protection` keeps "no", `frost_hold_closed` takes "yes"; the blind source is a marker value of the core model, `BLIND_SOURCE`). A second generic test shows it for every setting of every function that falls back.
- **Switches:** the fault value is the more restrictive of the two values, within that limit. Go through every boolean of a function that falls back and state which value is the restrictive one and why (for `frost_applies_to_protection` and `frost_hold_closed` in particular; if "more restrictive" is not obvious for one, stop and ask).
- **Numbers, positions, durations:** state for each why the fault value is cautious (for example the frost threshold: a fault value that makes frost protection engage earlier, not later; the minimum interval of motor protection: not shorter than the default). Where the default already is the cautious value, say so in the entry.
- Go through ALL registered settings of functions that fall back, those of C03 and whatever C04 registered under such a function, and give each its fault value. The safety-net test of the registry fails for an entry of a falling-back function without one.
- **The mandatory test of the project owner:** for every setting of every function that falls back, a faulty value never leads to a decision that a valid value would have forbidden. Build it generically over the registry, so that a setting added later is covered without a new test: for each such setting, for a set of world situations in which the function restricts (frost below the threshold with a wish to open, a movement inside the minimum interval, and so on; a later block adds situations for its function in one documented place), compare the decision with the faulty value against the decisions with valid values and show that the faulty one is never less restrictive than the most permissive valid configuration would allow in a way a valid value of THIS setting would have forbidden. Say precisely in the documentation what the test proves and what it does not.
- The sentence in the frost paragraph of `docs/concepts.md` that the review called too optimistic becomes true; check it.

**Part 2 — the safety net of the arbiter for exceptions.**

- An exception in a **comfort layer** (or one of its parts): that layer or part has no opinion; the decision record carries an entry with a reason code for it, and the fault is reported to the caller as a fact (the Home Assistant layer will log it and may raise a repair issue; the core does not log).
- An exception in a **constraint**: its cautious result applies. Define "cautious" per kind in one documented place: a constraint that limits keeps limiting to the most restrictive value it could have produced for this wish (for frost: the frost position limits opening); if a constraint cannot state that, the wish is not executed for comfort and protection class. An exception in a **gate rule**: the rule holds the wish back. Reported as above.
- **Fire and protection are never stopped by this.** The fire layer and the protection layers are evaluated even if every comfort layer raised. A fire wish still passes the named fire bypass when a constraint or gate rule that the bypass skips anyway raised. For rules the bypass does NOT skip, the project owner decided per rule. **Maintenance lock:** an exception holds every wish back, fire included, because the lock protects a person working at the shutter. **Dry-run: the other way round for fire.** If the dry-run rule raises while a fire wish is pending, the command IS sent: an escape route that stays closed in a fire is the greater evil than a test window that opens on a fire alarm. For every other class the cautious result of a failed dry-run rule stays "do not send". Test both rules with a fire wish, a protection wish and a comfort wish. **Decided later by the project owner:** every further rule the bypass does not skip ("no member can execute", "target reached", the pending-command part of "movement in flight") SENDS a pending fire wish when it fails, like the dry-run rule; only the maintenance lock holds fire back. The suppression of duplicates over the expectation window stays effective for such a fire command, guaranteed by the safety net itself. An exception in the fire layer or a protection layer itself cannot be replaced by a cautious value; it is reported, the other layers still run, and the decision says that the layer failed. Do not catch `BaseException`; catch `Exception`.
- New reason codes are allowed for this part, as few as possible (for example one for a failed layer, one for a failed restriction). They go into the closed enumeration AND into the lists of section 5 of `docs/architecture.md`; a test compares the two. Those lists are the ONLY part of `docs/architecture.md` you may touch, and you name the codes in the pull request.
- **First test case:** the frost reader with a source that delivers text (`TypeError` today). Fix the reader as well (text that is not a number is "no value", the blind path), and keep a test that forces an exception through a stub, so that the safety net stays tested after the reader is fixed. The same reader is used in `held_frost_after`; cover it.
- Stubs that raise, for every kind: comfort layer, part of a layer, constraint, gate rule that the fire bypass skips, gate rule that it does not skip, fire layer, protection layer. Determinism is kept (the same snapshot gives the same decision).

## Out of scope

- Repair issues, logging and translations for these faults (H01, H02, H04). Blind-source rules for contacts that do not exist yet (C08 declares the fault values of its own settings; this block provides the mechanism and the test that forces it).
- A change of what pausing functions do on a fault.

## Deliverables

Code and tests in the core; `docs/dev/core-model.md` (the entry shape with the fault value, the fault table with the new action, the step "choose the fault value" in "How a later block adds a setting"); `docs/dev/arbiter.md` (the safety net, what "cautious" means per kind, how a later block adds situations to the mandatory test); `docs/concepts.md` (one plain paragraph: a faulty setting never loosens protection).

## Acceptance criteria

- The frost case of the review: with an unreadable frost source on the only level that sets one, in frost, a wish to open is limited to the frost position, the decision names the blind source, and the fault is reported with the new action. With a valid source on another level, that source is used.
- Every setting of every function that falls back has a stated fault value; an entry without one does not construct or fails the safety net with an advising message.
- The mandatory test exists, is generic over the registry, and fails when a fault value is changed to a less restrictive one (show it once by mutation and say so in the pull request).
- No exception raised by a layer, a part, a constraint or a gate rule leaves `recompute`; each ends as specified above; a fire wish and a protection wish are still decided.
- The frost reader no longer raises for text; the forced-exception tests remain.
- Core coverage stays at or above its threshold without coverage pragmas; the purity guard passes; the model change is additive and named in the pull request (type and field, reason, persisted, approved by).

## Required tests

Under `tests/core/`: resolver tests per kind of setting (reference, switch, number, position, duration) on all three levels, with and without a valid value on another level; the combination case; the generic mandatory test with its situations; the arbiter's safety net with raising stubs of every kind; the frost reader; the registry safety net for a missing fault value.

## Open questions that block this block

None. The shape of "configured, but blind" in `WindowConfig` is proposed by the implementer before that part is built.
