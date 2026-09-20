# The arbiter

One arbiter decides for one window. Every feature of the integration only contributes a **layer**, a **constraint** or a **gate rule**; the evaluation itself never changes for a feature. This page explains the evaluation and shows how to add each of the three. The rules themselves come from the [domain design specification](../architecture.md), sections 2 to 5; the data types are described in [The core model](core-model.md).

```text
world snapshot ─► layers (first opinion wins) ─► constraints ─► gate ─► send / defer / suppress
```

| Module under `core/` | Content |
|---|---|
| `arbiter/arbiter.py` | `Arbiter`: the three registries and the evaluation |
| `arbiter/registry.py` | what a feature registers: `LayerRegistration`, `ConstraintRegistration`, `GateRuleRegistration`, and what their functions receive |
| `arbiter/fire_bypass.py` | the fire bypass |
| `arbiter/gate.py` | the gate rules that belong to no single feature, and the dam mechanism |
| `arbiter/controls.py` | operating modes as a table; the effective pause, lock and mode over three levels |
| `arbiter/dry_run.py` | the simulated state of a window in dry-run; arming |
| `arbiter/take_over.py` | what a take-over of a movement in flight does to the state |
| `arbiter/capabilities.py` | the one place where the gate asks what a member can do |
| `arbiter/layers.py` | help for layers: what a missing input means |
| `constraints/` | one module per constraint; so far `direction` and `frost` |
| `engine.py` | the façade: `recompute(snapshot) → decision`, the state after a decision, arming |

## No state, no clock

`Arbiter` and `Engine` are immutable. A recompute is a pure function of the window configuration and the world snapshot, and the same inputs always give the same decision. Time comes from `snapshot.time`. Whatever has to survive between two recomputes is part of the persisted window state (`snapshot.state`), and a function that changes it takes a state and returns a state.

What a person has set for the window is part of the snapshot too (`snapshot.controls`): pause, maintenance lock and operating mode on global, group and window level, and dry-run. `effective_controls` combines the three levels into what is in effect: **the most restrictive value wins**. A window is paused if any level is paused, locked if any level is locked, and its mode is the most restrictive of the three modes. A window cannot loosen what its group or the installation restricts.

## Evaluation order

The order of layers, constraints and gate rules is the order of the enumerations `Layer`, `Constraint` and `GateRule` of the model, which is the order of the specification. The order in which things are registered does not matter.

1. **Layers.** Every layer is asked, from fire down to the schedule. The first one that answers with a target or with "leave alone" wins. "Leave alone" wins like a target does: no lower layer acts, and nothing moves. Every other layer ends up in `Decision.other_layers` with a reason: a layer above the winner says why it stepped aside (`inactive`, `input_unavailable` …), a layer below the winner says what it would have wanted (`schedule_night`), a layer nobody registered says `not_configured`, and a comfort layer whose function is disabled for the window because of a data fault is not asked and says `function_disabled_by_fault`. Lower layers are asked although they cannot win, because the status of a window shall be able to say "the schedule wants the night position, but the storm has priority".
2. **Constraints** are applied to the winning target, in order, each only to the wish classes it names. A constraint returns the target of every member after it, or nothing if it has nothing to report. A member whose target is `None` is pinned: it stays where it is, and no later constraint can give it a target again. If every member is pinned, nothing reaches the gate, `Decision.gate` is `None`, and the reason of the constraint is the reason why nothing moves. **No constraint applies to a wish of class fire.**
3. **The gate.** The rules are evaluated in order, each only for the wish classes it names, and the first rule that applies decides. If none applies, the outcome is `send` with the reason `sent`.

| # | Gate rule | Holds back | Built by |
|---|---|---|---|
| 1 | maintenance lock | fire, protection, comfort | this block |
| 2 | no member can execute the command | all | this block |
| 3 | target reached | all | this block |
| 4 | operating mode | what `MODE_TABLE` says | this block |
| 5 | pause | comfort | this block |
| 6 | person-at-the-window dam | protection, comfort | this block (the mechanism; arming it is a later block) |
| 7 | manual override dam | comfort, except the return to the manual position | this block (the mechanism; arming it is a later block) |
| 8 | movement in flight | the same command is still pending: fire, protection, comfort. Another movement is under way: comfort | this block |
| 9 | motor protection | comfort | this block |
| 10 | command backoff | protection, comfort | a later block |
| 11 | staggering | protection, comfort | a later block |
| 12 | dry-run | fire, protection, comfort | this block |

An arbiter without the rules 1 and 12 is refused when it is built: nothing may ever move under a maintenance lock or in dry-run because somebody forgot a registration. `build_arbiter` in `engine.py` always adds the built-in constraints and gate rules.

Details of the built-in rules that the table of the specification leaves to the implementation:

- **No member can execute (2).** Only the members that have a target and are available right now are looked at. None of them: defer with `cover_unavailable`. All of them definitely lack both "set position" and "open and close": suppress with `capability_missing`. Capabilities are asked through `arbiter/capabilities.py` only; a capability that is not known never blocks.
- **Target reached (3)** always compares with the real, reported position, also in dry-run. Unavailable members are not judged. A member without position feedback counts as reached if its last real own command had this target.
- **Movement in flight (8)** has two parts, registered separately because they hold back different classes.
  - *The same command is still pending* (all classes, fire included). An own command is pending while its **expectation window** runs: from the time of the command for the full travel time of its direction plus the report delay of the member (`expectation_window_end`, an upper bound and the one place to change when the tracker knows more). If every target at the gate is the target of a pending command, nothing is sent again: `duplicate_command`. This hangs on the running window, not on "was sent once". When the window has closed and the target is still not reached, the command is not pending any more: fire is sent again at once, protection and comfort follow their normal rules.
  - **Take-over.** If the wish is of a higher class than a pending command with the same target (a storm begins while the evening closing is under way), the outcome is `movement_taken_over` instead: nothing is sent, and `Engine.state_after` raises the wish class of the pending commands to that of the wish and sets the owner of the position to the integration. From then on the dams, motor protection and the return after a protection event see a protection or fire movement, not a comfort one, and the next recompute reads `duplicate_command`. Class, reason and owner all change: the reason on the command (`OwnCommand.reason`) is authoritative for what the movement is, the decision only documents the moment. A wish of the same or a lower class never takes over and changes nothing. The motor protection clock stays as it is. For the author of the block that counts movements: a movement that is taken over counts in the daily count of comfort movements exactly once, when it was sent as comfort; the take-over itself counts nothing, because nothing is sent.
  - *Another movement is under way* (comfort only; protection and fire retarget at once). A pending command with other targets counts, and for an armed window a member that reports a movement, whoever started it, so a comfort movement never interrupts a person: deferred with `movement_in_flight`.
- **Motor protection (9)**, comfort only.
  - *Minimum change:* judged on the largest change among the members that report a position; below it: `min_change`. Two kinds of movement are exempt, however small they are: a member is sent to an end position (0 or 100) that it has not reached within its tolerance, so a shutter never stays a few percent open because the rest is "not worth a movement"; and the movement restores a constraint that the current position violates (see "How to add a constraint"). Neither exemption lifts the minimum interval.
  - *Minimum interval:* since `last_comfort_movement`: `min_interval`, deferred until it has passed. It exists against flapping, so it does not hold back a **fresh** wish: one whose trigger (`Wish.triggered_at`) lies strictly after the last own comfort movement. A boundary of the schedule fired, sleep mode was switched, a request arrived, an episode began. Not fresh are tracking inside an episode (the episode began before the last movement), an older wish that wins again because another layer dropped out (the day position after the end of shading), a trigger at the very instant of the last movement (that movement was its answer, which matters after a restart), and a wish that states no trigger. The last case is a fault of the layer, and the record shows it: a wish that is held inside the interval *because it states no trigger* reads `trigger_time_missing` instead of `min_interval`, with the same end time, for an armed window and in dry-run alike.
  - Zero switches a part off.
### Operating modes are a table

`MODE_TABLE` in `arbiter/controls.py` has one row per `OperatingMode`: its rank among the modes, the wish classes it holds back, and the reason code. The gate rule reads the table and nothing else. No row holds back fire.

## The fire bypass

The fire bypass is one named construct, `FIRE_BYPASS` in `arbiter/fire_bypass.py`, and not a set of exceptions spread over the rules. It names, as reason codes, what can never hold back a wish of class fire, and fire skips every registered rule, or part of a rule, that can give only such reasons:

- operating mode, pause, both dams, motor protection, command backoff and staggering as whole rules;
- of "movement in flight" only the deferral (`movement_in_flight`): fire retargets at once.

It never skips the maintenance lock and never dry-run, never "no member can execute" and "target reached", which describe what is possible or already true, and never the other part of "movement in flight": a fire command whose expectation window is still running is not sent a second time, and a pending comfort or protection command with the same target is taken over.

The registry keeps this exact in both directions. A registration whose reasons all belong to the bypass cannot name the class fire; one whose reasons are all outside it has to apply to all three classes; one that mixes the two is refused and has to be split into parts. A test compares the rules the bypass touches with the list in section 2.4 of the specification. A dam cannot be defined to hold back fire either, and a constraint cannot be registered for fire.
Under a maintenance lock and in dry-run the decision still names the fire wish as the winner, with its target, so the fire event can be fired although nothing moves.

The fire layer itself belongs to a later block. What the arbiter guarantees for it: while its wish is a target, the bypass applies; while its wish is "leave alone" (`fire_unacknowledged`, after the alarm has ended and until somebody acknowledges it), it wins, no lower layer acts, and nothing is sent.

## Dams

A dam is a gate rule that holds back wishes of certain classes for a while. `Dam` in `arbiter/gate.py` is the mechanism: a dam names the classes it holds back (never fire), the reason codes of wishes it lets pass anyway, and how to read it from the persisted state. The gate only reads a dam. **Arming and ending a dam is not the gate's business**; the blocks that detect a movement by hand do that.

- A dam whose end lies in the past has no effect, whether or not somebody has cleared it.
- A dam with a known end defers until that end. A dam without one (the room becomes empty, the shading episode ends) suppresses.
- The manual override dam lets exactly one comfort wish pass: the return to the manual position after a protection event, which a layer expresses as a wish of the protection layer with the reason `protection_return_manual`. It restores what the dam protects. It is still a comfort wish: every constraint applies to it, the person-at-the-window dam stands before the override dam and holds it back, and pause, operating mode, movement in flight and motor protection apply as to any comfort wish. Whether that wish exists at all (the override is still armed, the waiting time after the event has passed) is decided by the protection layer.

## Deferrals

A deferral never waits forever. It states exactly one of two times, and the model refuses a deferral with neither:

| Deferred by | States | Value |
|---|---|---|
| a dam with a known end | `until` | the end of the dam |
| motor protection, minimum interval | `until` | last own comfort movement plus the interval |
| no member available | `reevaluate_no_later_than` | the time of the recompute plus `WindowConfig.reevaluate_after` (default 5 minutes) |
| movement in flight | `reevaluate_no_later_than` | the latest end of the expectation windows of the pending own commands; without one (somebody else is moving the window), the time of the recompute plus `reevaluate_after` |

**What ends a deferral without a time** is the condition it waits for: a member becomes available again, or the members come to rest. Both are changes of the observed state, and the runtime recomputes a window whenever its observed state changes. `reevaluate_no_later_than` is only the safety net for the case that no such change is ever reported: at that time at the latest, the runtime recomputes the window from the state it has then. Nothing is replayed when a deferral ends; the window is simply recomputed, and the new decision may well be another deferral.

## Dry-run

Dry-run is the last gate rule on purpose: whatever reaches it would have been sent. The decision of a window in dry-run therefore shows the complete hypothetical outcome. `GateOutcome.dry_run` is true, and either the rule `dry_run` decided and `would_send` lists the command, or an earlier rule decided and its reason says what would have held the wish back. No rule except the last one knows about dry-run; the arbiter marks the outcome.

Rules that depend on own commands must not read them from `snapshot.state`. They read `GateInput.own_commands` and `GateInput.last_comfort_movement`. For an armed window these are the real commands and the real motor protection clock. For a window in dry-run they are the **simulated** ones from `WindowState.simulated`, and never the real ones. `Engine.state_after(snapshot, decision)` returns the state with a would-be send remembered as simulated commands (and, for a comfort wish, the simulated clock); for a window in dry-run it never touches a real command, the real clock, a dam or the owner of the position. `Engine.arm(state)` discards the simulated state and starts the window clean: no dam, owner unknown.

**The standing would-be command.** An armed window that has sent a command moves, arrives, and reads `target_reached` from then on. A window in dry-run does not move. If its simulated command counted against the very wish it stands for, the record would flap between "would have sent 30" and `duplicate_command` or `min_interval`. So while the simulated commands have the same targets as the wish at the gate, and none of them is of a lower class than the wish, they *are* that wish's command: the own-command rules do not count them against it, the outcome stays "would have sent", and nothing new is remembered, which also means that a recompute that changes nothing writes nothing. A wish with other targets is judged against the simulated commands and the simulated clock like any new command: inside the minimum interval it reads `min_interval` with the time at which it ends. A test recomputes a hundred times under constant inputs, also with advancing time, and expects one distinct record. A take-over happens in dry-run too, on the simulated commands only: a wish of a higher class meets a simulated command with its target whose expectation window still runs, the record reads `movement_taken_over` once, the simulated command becomes the wish's own, and the record is stable again.

## How to add a layer

A layer is a pure function from the window configuration and the world snapshot to a `Wish`; the persisted state is `snapshot.state`.

```python
def sleep_layer(config: WindowConfig, snapshot: WorldSnapshot) -> Wish:
    switch = snapshot.sources.get(SLEEP_SOURCE)
    missing = wish_for_missing_input(Layer.SLEEP, switch, hold=False)
    if missing is not None:
        return missing
    ...
    return Wish.target(Layer.SLEEP, ReasonCode.SLEEP_MODE, night_position)


SLEEP_LAYER = LayerRegistration(Layer.SLEEP, sleep_layer, function=FunctionId.SLEEP)
```

- The layer answers for its own place in `Layer`; an answer in another layer's name is refused. The wish class follows from the layer.
- **Declare the function** the layer belongs to: a member of the closed enumeration `FunctionId` of the core model (`FunctionId.SCHEDULE`, `FunctionId.SHADING` …), never a free string. A comfort layer has to declare a function with the fault behavior `PAUSE`, a function that creates wishes; the fire layer and the protection layer declare `FunctionId.FIRE` and `FunctionId.PROTECTION_EVENTS`, which fall back, and a function that can be paused is refused for them. The settings registry and the disabled functions of a window use the same enumeration; see "Functions and faults" below. The resolved window configuration can list functions that are disabled for the window because a stored setting in their inheritance chain is faulty (`WindowConfig.disabled_functions`, read through `disabled_functions(config)` in `arbiter/layers.py`). Comfort becomes cautious then: the arbiter does not ask the layer at all, the layer counts as "no opinion" with the reason `function_disabled_by_fault`, lower layers act as usual, and the decision record and a dry-run show why nothing happens. The fire layer and the protection layer are never paused; that includes the return to the manual position, which comes from the protection layer. A function that falls back cannot even be put into the set: the window configuration refuses it.
- Always return a wish with a reason code: a target, "leave alone", or "no opinion" with the reason why the layer steps aside.
- **A missing input never becomes a position.** Decide per input whether its absence means "no opinion" (comfort steps aside) or "leave alone" (safety holds the window); `wish_for_missing_input` builds either answer.
- **A comfort wish for a target states its trigger:** `wish.triggered(at)`, with the moment from which the layer wants what it wants now, taken from a fact the layer already has (the boundary of the schedule, the "active since" of the episode, the time of the request or of the switch). It stays the same while the layer only tracks. Without it the wish is never fresh, and its record reads `trigger_time_missing` whenever the minimum interval holds it back. The test `tests/core/test_layer_triggers.py` fails for a registered comfort layer that forgets it.
- Read time from `snapshot.time`. Keep nothing in the function or in a module.
- Settings of the feature are added to `WindowConfig`, state that has to survive to `WindowState`.
- Hand the registration to `build_arbiter(layers=[...])`. Nothing in `arbiter/` changes.

## How to add a constraint

A constraint is a pure function from a `ConstraintInput` (configuration, snapshot, the winning wish, the targets so far) to a `ConstraintResult`, or to `None` if it has nothing to report.

```python
LOCKOUT = ConstraintRegistration(
    constraint=Constraint.LOCKOUT_PROTECTION,
    applies_to=frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
    apply=_apply,
    function=FunctionId.LOCKOUT,
)
```

- Its place is its member of `Constraint`; `CONSTRAINT_REASONS` of the model says which reason codes it can report.
- State the function it belongs to, a member of `FunctionId`; the argument has no default. Frost protection states `FunctionId.FROST`, the later ventilation floor `FunctionId.VENTILATION`, lockout protection `FunctionId.LOCKOUT`. **A constraint restricts movement, so its function must have the fault behavior `FALL_BACK`; a function that can be paused is refused, and a constraint is never skipped because of `disabled_functions`** (see "Functions and faults"). `None` is for a constraint that has no function of its own because it belongs to whatever function the limited wish comes from; the direction of a wish is the one such constraint, and the cross-check test lists it by name.
- Name the wish classes it applies to. Fire cannot be named. A constraint that applies to a class only under a setting names the class and checks the setting itself, as `frost` does for protection.
- Return the target of **every** member, in order. Limit a target, or pin a member with `None`; never give a pinned member a target again, and never invent a target.
- Compare with `ConstraintInput.current_positions`. A member that reports no position cannot be judged; say in the module what that means for the constraint.
- A constraint that says where a window may **stand** (a floor, a ceiling) can be violated by the position the window has right now: somebody tilts the window while the shutter stands just below the ventilation floor. Such a constraint also registers `violated_by_position`, a function that answers whether a member stands on the wrong side at this moment. The movement that restores it is then exempt from the minimum change of motor protection. A constraint that says which **movements** are allowed leaves it out.
- Put it in its own module under `constraints/` and hand it to `build_arbiter(constraints=[...])`.

The two constraints of this block. Neither can be violated by a position, because both are about movements: the direction is judged relative to where the member stands, and frost protection forbids opening further, not standing open. A shutter that is fully open when frost begins stays where it is.

- **Direction** (`raise_only`, `lower_only`): a member whose target lies in the forbidden direction is pinned. A member without a known position passes.
- **Frost** (`FrostSettings` of the window): while frost is active and not waived, an opening goes only up to the frost position; a member that already stands at or above it is pinned, never closed; closing is never limited. Comfort always, protection only with `applies_to_protection`, fire never. `hold_closed` ("do not raise a closed window at all") is off by default and reports `frost_hold`. Frost is active below the threshold and ends at threshold plus hysteresis; inside the band, and while the source has no value, `WindowState.held_frost` decides, the latter for at most 24 hours. **A silent source is never silently "no frost":** after those 24 hours, or if there never was a known state, the source is blind (`FrostState.BLIND`), and the limit applies as a cautious value until data returns or the operator waives frost protection. The record tells the two apart: `frost_limit` means frost was measured (or is still held), `frost_limit_source_blind` means nothing is known. The event-only code `frost_source_blind` exists for the repair issue and the event, which a later block of the Home Assistant layer raises. `held_frost_after` returns what to persist; the constraint itself only reads. The waiver is an input: `WindowState.frost_waiver_until`. Who sets it, on which level, and the release by sun are later blocks.

## How to add a gate rule

A gate rule is a pure function from a `GateInput` to a `GateOutcome`, or to `None` if it does not apply.

```python
STAGGERING = GateRuleRegistration(
    rule=GateRule.STAGGERING,
    applies_to=frozenset({WishClass.PROTECTION, WishClass.COMFORT}),
    evaluate=_evaluate,
)
```

- Its place is its member of `GateRule`; `GATE_RULE_REASONS` says which reason codes it can give.
- State the function the rule belongs to, or `None` for a rule without a feature of its own (maintenance lock, no member can execute, target reached, operating mode, pause, movement in flight, dry-run). Motor protection states `FunctionId.MOTOR_PROTECTION`, both dams `FunctionId.MANUAL_OVERRIDE`. The argument has no default. As for a constraint, the function must fall back, and a gate rule is never skipped because of `disabled_functions`.
- Name the classes it can hold back. Do not write an exception for fire into the rule: a rule that is part of the fire bypass cannot name fire, and the arbiter skips it.
- Return `GateOutcome.suppress(...)` or `GateOutcome.defer(...)` under the rule's own name, never `send`. A deferral states `until` or `reevaluate_no_later_than`.
- A rule whose parts hold back different classes is registered once per part, each with `reasons=` naming the reason codes of that part; the parts must not depend on the order in which they are asked. "Movement in flight" is the example.
- Do not think about dry-run. Read own commands from `GateInput.own_commands` and the motor protection clock from `GateInput.last_comfort_movement`, and the rule works for a dry-run window as well.
- Ask about capabilities through `arbiter/capabilities.py`.
- Hand it to `build_arbiter(gate_rules=[...])`.

A new dam is a `Dam(...)` and its `registration()`.

## Functions and faults

The functions of the integration have one definition, the closed enumeration `FunctionId` in `core/model/functions.py`. Three places use it and nothing else: the settings registry (every setting belongs to a function), `WindowConfig.disabled_functions` (filled by the resolver of the settings when a stored setting is faulty), and the registrations of the arbiter.

Every function has a **fault behavior**, `FunctionId.fault_behavior`: what happens to it for a window when one of its stored settings is faulty. **What decides is the direction of the effect.**

- A function that **creates wishes** is paused (`FaultBehavior.PAUSE`): schedule, sleep, request, privacy, shading, solar heating. A paused layer creates no wish. That means less movement, the cautious side: a window never moves unexpectedly because of a data fault.
- A function that **restricts movement** falls back to the value of the next level and keeps working (`FaultBehavior.FALL_BACK`): everything a constraint or a gate rule belongs to, such as frost, lockout, ventilation, motor protection and the manual override, and also fire and the protection events. Pausing a restriction would mean *more* movement, the wrong direction: a faulty ventilation setting would let the shutter close completely in front of a tilted window.

So only layers can be paused, and only those of `PAUSE` functions; `disabled_functions` accepts nothing else. Constraints and gate rules are never skipped because of it. The two behaviors are named by what they do, so they are not confused with the wish classes of the arbiter.

`tests/core/test_function_cross_check.py` keeps this true, for the arbiter that `build_arbiter()` returns and for the registrations of the test kit:

- **No function of a constraint or a gate rule can be paused.** The registry refuses such a registration, and the test checks every registered one again, because a registration can also be built from data. If this fails for you, your function restricts movement: give it the fault behavior `FALL_BACK`.
- **Somebody listens to every function that has settings.** A `PAUSE` function with settings has a registered layer; a `FALL_BACK` function with settings has a layer, a constraint or a gate rule. Otherwise the resolver would pause something that nothing stops doing, or settings would configure nothing.

Feature blocks arrive one by one, so a function can have settings before its block exists. Such a function stands in `NOT_BUILT_YET` in that test. The list can only shrink: the test fails for an entry that has a listener by now, for an entry without settings, and for a function with settings that has neither a listener nor an entry. When you build the layer, the constraint or the gate rule of a function, remove its entry in the same pull request. `functions_with_settings()` in the test is the one place that connects to the settings registry.
## Reason codes

Every wish, constraint result and gate outcome carries a code from the closed list in `core/reasons.py`, and the model refuses a code from the wrong group. A new code needs an entry in the specification, in the enumeration and in both translations.
