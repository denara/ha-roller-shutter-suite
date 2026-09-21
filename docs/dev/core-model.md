# The core model

The domain core decides where a shutter goes. Its blocks are written by different people and agents, and they fit together because they exchange the same data types. This page lists those types. They live in these places under `custom_components/roller_shutter_suite/core/`:

| Module | Content |
|---|---|
| `model` | the data types; a package, see below |
| `reasons` | the closed list of reason codes |
| `ports` | what the core needs from outside: clock, sun, actuator, storage |
| `settings` | partial settings, the "inherit" marker and the resolver global → group → window; see [Inheritance](#inheritance) |

The vocabulary and the rules come from the [domain design specification](../architecture.md). This page only says how the vocabulary looks in code. There is no behavior in `model`, `reasons` and `ports`: no arbiter, no schedule, no tracking, no geometry. `settings` holds one piece of logic: the resolver that produces the `WindowConfig`.

`model` is a package, so that blocks that work in parallel edit different files. Always import from the package: `from custom_components.roller_shutter_suite.core.model import Position`. Its modules depend on each other in one direction only, and a test enforces it:

| Module of `model` | Content |
|---|---|
| `values` | position, source value, sun position |
| `functions` | the closed list of functions and their fault behavior |
| `schedule` | the settings of the schedule as values: trigger, day triggers, targets, schedule settings, and their rules |
| `almanac` | the sun almanac: the answers of the sun port that a recompute may look at |
| `window` | capability profile, member and window configuration, settings of motor protection and frost protection |
| `controls` | pause, maintenance lock and operating mode on three levels, dry-run |
| `decision` | wish, constraint result, gate outcome, decision |
| `observation` | observations, the window-level view, own commands |
| `state` | the persisted window state and its serialization |
| `snapshot` | the world snapshot |
| `_validation`, `_data` | private helpers: validation, reading plain data |

## Rules that hold for every type

- **Immutable and compared by value.** Every type is a frozen data class or an enumeration. Two objects with the same content are equal. All types can be used in sets and as dictionary keys, with two exceptions: a source value, on purpose (see below), and the world snapshot, which holds a mapping of source values.
- **Validated on construction.** An object that exists is valid. A position of 101, a naive datetime or a wish without a reason code raises an error where it is created, not later where it is used.
- **100 is open.** A position is an integer from 0 to 100; 100 is fully open, 0 is fully closed.
- **Timestamps are timezone-aware.** A datetime without a time zone is rejected, also when persisted data is read back.
- **Persisted instants are kept in UTC.** Everything in the persisted window state is a point in time, not a wall-clock time. It is converted to UTC on construction, so a state that went through JSON compares equal to the one that was written, also in the repeated hour of a clock change.
- **Local time has one source.** The local zone of the installation is the zone of `Clock.now()` and of `WorldSnapshot.time`, which keeps its zone. Fixed times of the schedule and "local midnight" are read from it, and the `date` arguments of the sun port are local dates in that zone.
- **Positions of members are on the motor scale**: what a member is commanded to and what it reports. The glass calibration of shading is applied before, by the shading layer.
- **No free text in a decision.** Reasons are codes from the closed list in `reasons`, and each place accepts only the codes of its group: a wish for a target only codes of winning layers; other wishes and layer reasons also the codes that say why a layer did not act; a constraint result only the codes of its constraint (`CONSTRAINT_REASONS`); a gate outcome only the codes of its rule (`GATE_RULE_REASONS`, the group "gate" plus `capability_missing`). Two codes fit every constraint and every rule, and only the arbiter writes them: `constraint_failed` and `gate_rule_failed`, for a constraint or a rule that raised an exception. Codes that exist for events only never appear in a decision.
- **Missing data is not good news.** A source value that is unknown or unavailable has no truth value, does not convert to a number, and has no accessor that returns a default. Comparing a source value with a plain value (`contact != "open"`) raises an error too, because it would be true for a missing contact. A source value is not hashable either: a lookup in a set or a dictionary asks the hash before it asks equality, so `contact in {"open", "tilted"}` would silently answer "not contained"; without a hash it raises.

## The types

### Values

| Type | Meaning |
|---|---|
| `Position` | An integer from 0 to 100; `FULLY_OPEN` and `FULLY_CLOSED` name the two ends. |
| `SourceValue` | An input read from a source, in one of three states (`SourceState`): a value, unknown, or unavailable. Reading `value` raises unless the state is "value"; `bool(...)` and a comparison with a plain value always raise. The Home Assistant adapter maps the entity states `unavailable` and `unknown` before it builds a value; the string "unavailable" as a value would be the adapter's bug. |
| `SunPosition` | Azimuth and elevation of the sun in degrees. |

### Wishes, constraints, gate, decision

| Type | Meaning |
|---|---|
| `Layer` | The seven layers of the arbiter in the order in which they are asked, from fire to schedule. |
| `WishClass` | `fire`, `protection` or `comfort`; it follows from the layer. The one exception: the return to the manual position after a protection event (`protection_return_manual`) is a comfort wish of the protection layer, and only that layer can carry this reason. |
| `WishKind` | What a layer answers: `target`, `leave_alone` or `no_opinion`. |
| `Direction` | A limit a wish carries itself: `raise_only` or `lower_only`. |
| `Wish` | The answer of one layer: kind, layer, reason code, and for a target either one position for all members or one position per member, an optional direction, optionally the ray height the positions were computed from, and optionally `triggered_at`, the time of its trigger (see below). |
| `MemberTarget` | The target of one member on the motor scale; a position of `None` means the member stays where it is. |
| `LayerReason` | Why a layer, or one part of a layer, did not win: the layer, a reason code, and the function that spoke (from its registration; none if the registration declares none or nobody registered the layer). A part whose function is disabled for the window says `function_disabled_by_fault`. |
| `Constraint` | The seven constraints in the order in which they are applied. |
| `ConstraintResult` | What one constraint did: the constraint, its reason code, and the target of every member after it. |
| `GateRule` | The twelve rules of the gate in the order in which they are evaluated, from maintenance lock to dry-run. |
| `GateKind` | `send`, `defer` or `suppress`. |
| `GateOutcome` | The answer of the gate: kind, reason code, the rule that decided, for a deferral its time (see below), and for a window in dry-run the hypothetical outcome (see below). |
| `Decision` | The complete result of one recompute: the winning wish, the reasons of the other layers, the constraint results, the target of every member, the gate outcome, and `winning_function`, the function of the registration whose wish won (written by the arbiter from that registration; none if nothing won or the registration declares none). `other_layers` is unique per layer and function: a layer that is registered in parts, one per function, has one entry per part that did not win, and the winning layer appears there only through its other parts. All of them name the same members in the same order. `target` is the target the window shows: the common target if all members have the same one, otherwise none, with the per-member targets as the detail. `faults` lists the layers, constraints and gate rules that raised an exception during the recompute (`EvaluationFault`), in the order of evaluation; it is empty in a sound installation. |
| `EvaluationStage`, `EvaluationFault` | A registered function of the arbiter raised an exception: the stage (`layer`, `constraint`, `gate_rule`), the place (the member of `Layer`, `Constraint` or `GateRule`), the function of the registration, `error` (the name of the exception class, an identifier and no text) and `exception` (the exception itself, for the log of the caller). The exception takes no part in comparing, so the same snapshot still gives an equal decision. A fact for the caller; the consequence is already in the decision as `layer_failed`, `constraint_failed` or `gate_rule_failed`. See [the safety net of the arbiter](arbiter.md#the-safety-net-exceptions). |

**The trigger of a wish.** `Wish.triggered_at` is the moment from which a layer wants what it wants now: a boundary of the schedule fired, sleep mode or privacy was switched, an external request arrived, a shading or solar heating episode began. A layer fills it from a fact it already has (the boundary time, the "active since" of the episode, the time of the request or of the switch) with `wish.triggered(at)`. It does not change while a layer only tracks, and it is the old one when a wish wins again because a higher layer dropped out. Motor protection compares it with the time of the last own comfort movement: a wish whose trigger is later is fresh, and the minimum interval does not hold it back. A wish that states no trigger is never fresh, and when the minimum interval holds such a wish back, the gate says `trigger_time_missing` instead of `min_interval`, so a layer that forgot its trigger is visible in the record.

**Deferral.** Nothing waits forever. A deferral states exactly one of two times: `until`, the time at which it ends, if that is known; or `reevaluate_no_later_than`, if it ends with a condition whose time nobody knows (a member becomes available, the members come to rest). The second is an upper bound: at that time at the latest the window is recomputed from the state it has then, and nothing is replayed. A deferral with neither is refused.

**Dry-run.** A window in dry-run never moves, and its decision shows what would have happened. `GateOutcome.dry_run` is true for such a window. Either the last rule decided: then the reason is `dry_run` and `would_send` lists the command that would have been sent. Or an earlier rule decided: then `rule` and the reason name what would have held the wish back, for example `pause` with `paused`.

**No gate outcome.** `Decision.gate` is `None` when nothing reached the gate: the winning wish was "leave alone", no layer had an opinion, or a constraint pinned every member where it is. In that case the reason of the constraint is the reason why nothing moves.

### Windows and members

A window has one or more members: the covers that are always moved together. Everything a cover can do or report is kept per member, and the window-level view is derived from the members.

| Type | Meaning |
|---|---|
| `CoveringType` | What hangs in front of the glass. Only `roller_shutter` exists; the field is there so venetian blinds can be added later. |
| `CapabilityProfile` | What a member can do and report: open/close, set position, stop, reports a position, position source, transit states, position updates during travel, report delay, travel time up and down, and the tolerance for comparing a reported position with a target (the stated one, else 2 for a calculated and 3 for a measured position; at least 1). A cover without position feedback is a valid profile. `capabilities_known` is false only when nothing is known about what the member can do, not even a last state (a member that was never seen). The four capability flags then carry no information: they must all be off, a profile that is unknown and still claims a capability is refused, and `capability_state(name)` answers `unknown` for every flag instead of `present` or `missing`. The flags come from one report of the member, so they are known or unknown together. |
| `PositionSource` | `measured` by the drive, or `calculated` from run time (the default). |
| `TransitReporting` | Whether a member reports "opening" and "closing": `yes`, `no`, or `unknown` until observed. |
| `PositionUpdates` | `live` during travel, or at the `end_only`. |
| `MemberConfig` | One member: its identifier and its capability profile. |
| `SettingsCombinationError` | What a rule of `WindowConfig` that spans several settings raises: a `ValueError` that names the keys the rule concerns. The contract for every block that adds such a rule; see [Faults in stored settings](#faults-in-stored-settings). |
| `WindowCapabilities` | What all members of a window can do: the lowest common denominator of the flags (`WindowConfig.capabilities`). **These booleans cannot tell "missing" from "unknown":** a member about which nothing is known carries no flag, so every flag of a window with such a member reads false, also when all other members have the capability. Code that decides anything from a `False` must use `capability_states`. |
| `CapabilityState`, `WindowCapabilityStates` | The same four capabilities in three states, `present`, `missing` or `unknown`, from `WindowConfig.capability_states`. `missing` if any member definitely lacks the capability; otherwise `unknown` if the capabilities of any member are not known; otherwise `present`. "Missing" takes precedence, as "no" does in the at-targets view. Unknown is never treated as missing: nothing is concluded from a member about which nothing was ever known. |
| `WindowConfig` | A window after inheritance has been resolved: identifier, covering type, members, and three places for later features (the condition input of the morning opening, the tiers of the temperature condition, the profile key of the schedule). The blocks that build a feature add its settings here, one field per setting so that each can be inherited on its own. Frost protection: `frost_source` (the key of the temperature source; none means not configured; `BLIND_SOURCE` means configured, but blind, see the next row), `frost_threshold` (default 0), `frost_hysteresis` (default 1), `frost_position` (default 90), `frost_applies_to_protection` (default no) and `frost_hold_closed`, the option "do not raise a closed window at all" (default off); `frost` is the view over them. Motor protection: `motor_min_change` in percent (default 5) and `motor_min_interval` between two own comfort movements (default 10 minutes), zero switches a part off; `motor_protection` is the view over them. `reevaluate_after` is the upper bound of a deferral whose end is not known (default 5 minutes). The schedule: `schedule_enabled` and the other `schedule_*` fields, among them six fields per day type and edge (`schedule_workday_morning_time` …); [the schedule](schedule.md#settings) lists them with kinds and defaults, and `schedule` is the view over them. Two rules span several of them (clamps in order for a trigger of the sun; the latest morning before the earliest evening) and raise `SettingsCombinationError` with the keys they concern. `disabled_functions` is the set of functions (`FunctionId`) that are paused for this window because a stored setting of theirs is faulty; the inheritance resolver fills it, it is never stored, and the arbiter skips the layers of such a function and says so in the decision. Only a function whose fault behavior is `pause` is accepted; any other member, and anything that is no `FunctionId`, is refused on construction: whatever protects or restricts movement can never be switched off by a data fault. |
| `BlindSource`, `BLIND_SOURCE` | The one marker for "an optional reference to a source is **configured, but blind**". `None` in such a field means "not configured", the feature is off. The marker means the opposite: a level tried to name a source and the stored value is faulty, or a level that could have named one is unreadable, and no other level names a valid one. The feature stays on and the rules for a blind source apply (the frost limit stays). It is the fault value of such a reference in the settings registry. It is no string, so no stored text can equal it; it has no stored form; a level that sets it is faulty (`invalid`); only the inheritance resolver produces it. The type of such a field is `str \| BlindSource \| None`, so the type checker makes every reader handle three cases: a source, none, blind. Frost protection treats it as a source that is blind at once and does not use a held frost state, because a held state belongs to a source and nobody knows which source the window has. |
| `FunctionId`, `FaultBehavior` | The closed list of functions, each with one fault behavior, `fall_back` or `pause` (`FunctionId.fault_behavior`); see [Functions and their fault behavior](#functions-and-their-fault-behavior). |
| `FrostSettings`, `MotorProtectionSettings` | The settings of frost protection and of motor protection as one value each: read-only views over the fields of `WindowConfig` (`WindowConfig.frost`, `WindowConfig.motor_protection`). They also hold the value rules of those fields. |
| `TemperatureTier` | One tier of the temperature condition of shading: threshold and hysteresis. A window has none or one. |
| `ScheduleProfile` | The key under which the schedule looks up its targets. It has one value, `default`. |
| `TriggerKind`, `Trigger`, `DayTriggers`, `ScheduleTargets`, `ScheduleSettings` | The settings of the schedule as values: a read-only view over the `schedule_*` fields of `WindowConfig` (`WindowConfig.schedule`), with the value rules of those fields. `ScheduleRuleError` is what the view raises for one of its two rules over several settings; `WindowConfig` turns it into a `SettingsCombinationError` with the names of its fields. [The schedule](schedule.md) explains them. |
| `MovementState` | The state class of an observation: `resting`, `moving_up`, `moving_down` or `unavailable`. |
| `Observation` | A normalized report of one member: state class and position, if it reports one. An unavailable member has no position. |
| `MemberObservation` | The current observation of one named member. |
| `WindowObservation` | The observed members of a window and the view over them: available while one member is; `reports_movement` as soon as one member reports a movement (whether it has settled is the tracker's knowledge); `position(tolerances)`; and `members_at_commanded_targets(commanded, tolerances)`, see below. |
| `WorldSnapshot` | Everything one recompute may look at: the time, the sun position, the source values by key, the observed window, the persisted window state, and the controls. Two optional fields carry what the schedule needs from ports, as data, because a recompute asks no port: `almanac` (a `SunAlmanac`) and `installation_seed` (the seed for random offsets from the storage port). A layer that needs one of them and does not find it has no opinion, with `input_unavailable`. |
| `SunAlmanac`, `SunDay`, `ElevationPassage` | The answers of the sun port for a few local dates: sunrise, sunset, the elevation at local noon, and when the sun passes the elevations the schedule of the window names. "None on this day" is an answer; what was never asked is missing and is never guessed. Instants are kept in UTC; `to_data()` and `from_data()` turn it into plain data and back. `build_sun_almanac` of the schedule fills it. |
| `OperatingMode` | `automatic`, `protection_only` or `off`. What each mode holds back is a table of the arbiter. |
| `ControlLevel` | Pause, maintenance lock and operating mode as set on one level; by default nothing is set. |
| `Controls` | What a person has set for a window at the moment of a recompute: the three levels (global, group, window) and `dry_run`. They change while the integration runs, so they belong to the snapshot and not to the configuration. `dry_run` has no default: whether a window may move is never assumed. The arbiter combines the levels; the most restrictive value is in effect. |

**The position of a window.** The window has a position, one number, as soon as all members report the same position within tolerance, whatever was commanded last. Otherwise it has none, and the members' values are there individually. No member speaks for the window. `WindowObservation.position(tolerances)` holds the rules, and `WorldSnapshot.window_position(tolerances)` calls it:

1. Every member reports a position. A member without position feedback or an unavailable member means that the window has no position.
2. The highest and the lowest report differ by no more than the tolerance. If the members have different tolerances, the smallest one applies.
3. The position is the mean of the reports, rounded half up.

A window with one member therefore has a position whenever its member reports one, also right after somebody moved it by hand. A position can be returned while a member still reports a movement; whether a movement has settled is the tracker's knowledge.

**Are the members where they were commanded to?** That is a separate statement. Members shaded to different targets are exactly where they should be, and the window still has no single position; a window moved by hand has a position and is not where it was commanded to. `WindowObservation.members_at_commanded_targets(commanded, tolerances)` answers with `MembersAtTargets`, comparing each member with the target of its own last command (from the persisted state, `WindowState.commanded_targets`) within its own tolerance; `WorldSnapshot.members_at_commanded_targets(tolerances)` puts the two together.

- `no`: a member that can be judged stands outside its tolerance. A single "no" refutes "all members are at their targets", so it wins over members that cannot be judged.
- `cannot_be_judged`: nobody says "no", but at least one member cannot be judged: it reports no position (no feedback, or unavailable), or it was never commanded.
- `yes`: every member can be judged and stands at its target, also when the targets differ.

### Persisted window state

`WindowState` is everything a window has to remember between recomputes and across a restart. `WindowState()` is the state of a window that was just set up. `to_data()` turns it into plain data that can be written as JSON, with a `schema_version`; `from_data()` reads it back and refuses naive datetimes, malformed data, unknown keys and other schema versions, each with the path of the key in the message. Migration between versions is the job of the later `persistence` module.

| Type | Meaning |
|---|---|
| `PositionOwner` | Who put the window where it is: `engine`, `user` or `unknown`. |
| `OwnCommand` | A command of the integration to a member: its identifier, target, direction (`TravelDirection`: `up` or `down`), time, wish class, the reason code of the wish that caused it, and the context under which it was executed once that is known. The reason is a code of the group "winning or contributing layers", it is persisted, and it is authoritative for what the movement is: a decision documents a moment, the command says whose movement this is now. When a wish of a higher class takes a movement in flight over, class and reason of the command become those of that wish. The identifier goes to the actuator and comes back with the result, so a late result is never attributed to a newer command. |
| `MemberCommand` | An own command together with the member it went to. |
| `PositionReference` | Whether a calculated position can be trusted: `referenced` or `uncertain`. |
| `MemberState` | Per member: the last own command with its target, the last observation, the position reference flag, and the command backoff as facts: the number of attempts of the current command and the time of the last attempt (no attempts without a last own command). The time of the next retry is never stored; it is computed from the two facts with the current settings, so a reload right after a failed attempt does not send a second command at once. |
| `ManualOverrideDam` | The armed manual override: armed at, end rule (`OverrideEndRule`), absolute end if the rule has one, and the position the person chose. |
| `PersonAtWindowDam` | The armed person-at-the-window dam: when it ends. |
| `ProtectionEventState` | Per protection event: active or inactive (`ProtectionEventStatus`), active since, ended at, released at, and the position and owner remembered from before the event. An active event has "active since" and no "ended at"; an inactive one may have an "ended at". "Released at" is the time at which the watchdog released the event; the event stays active as long as its trigger is, and an inactive event can still carry it. `released` is a read-only view of it. Times are stored, not deadlines: the waiting time of the return is configuration, and it runs from `return_clock_start`, the release if there was one, otherwise the end. |
| `ShadingEpisodeState` | Active since, and the end of the rain lock. |
| `SolarHeatingEpisodeState` | Active since, and the "opened once" flag. |
| `ExternalRequest` | A position requested by an automation, the text the caller gave as reason, and the expiry. |
| `DayType`, `LatchedDayType` | `workday`, `weekend` or `holiday`, and the day type that was fixed for one date. `fallback` is true if the day of the week was fixed because a day-type input had no value until the morning trigger had passed; see [the schedule](schedule.md#day-types-and-the-latch). |
| `HeldInput` | The last known value of an on/off input that is held while its source is missing (frost, season), and when it was seen. |
| `SimulatedState` | Only in dry-run: the would-be commands per member and a motor protection clock of their own, kept apart from the real state. |

Two plain instants of the window state belong to the brightness trigger of the evening: `brightness_below_since`, the time since which the outdoor brightness has been seen below its threshold without interruption, and `evening_brightness_at`, the instant at which the brightness began the evening. [The schedule](schedule.md#the-evening-by-brightness) explains why both are needed.

### Reason codes

`ReasonCode` is the closed enumeration of section 5 of the design specification, and `ReasonCategory` names its five groups: winning layers, why a layer did not act, constraints, gate, and events of the tracker and the life cycle. A test reads the specification and fails when the code and the document differ. No code claims that a curtain has arrived.

### Ports

| Port | What the core gets from it |
|---|---|
| `Clock` | The current time, in the local zone of the installation. The core never reads a clock itself. |
| `Sun` | The sun position at a time, sunrise and sunset of a local date, and when the sun passes a given elevation. |
| `Actuator` | Sends a position to one member, under the identifier of the command; the result comes back to the engine with the same identifier. |
| `Storage` | Loads, saves and deletes the plain data of a window state, and keeps the installation's seed for random offsets. |

The ports are synchronous: an adapter whose work takes time starts it and returns. The Home Assistant layer implements the ports for the runtime. Tests and the time-lapse simulation implement them with a synthetic world.

## A decision, step by step

The evening has begun. A window has two shutters side by side, `cover.example_left` and `cover.example_right`, and the window behind them is tilted. Its ventilation position is 30.

1. **Layers.** Fire, protection, sleep mode, external request, privacy and shading are asked first. Each of them steps aside and says why: `inactive`, `not_configured`, `outside_episode`. These become the `LayerReason` entries of the decision. The schedule is the first layer with an opinion: a `Wish` of the kind `target`, position 0, reason `schedule_night`, direction `lower_only`. It wins. Its wish class is `comfort`, because it comes from the schedule layer.
2. **Constraints.** The direction constraint has nothing to object to: both shutters are open, so going to 0 is lowering. The ventilation floor applies to comfort wishes while the window is tilted: not lower than 30. It reports a `ConstraintResult` with the reason `ventilation_floor` and the new targets: 30 for both members.
3. **Gate.** No lock, no pause, no dam, no movement in flight, enough change since the last movement. No rule applies, so the outcome is `send` with the reason `sent`.

The resulting `Decision`:

| Part | Content |
|---|---|
| `winning_wish` | schedule, target 0, `schedule_night`, `lower_only` |
| `other_layers` | fire `inactive`, protection `inactive`, sleep `not_configured`, … |
| `constraints` | ventilation floor, `ventilation_floor`, both members at 30 |
| `targets` | left 30, right 30 |
| `target` | 30 (common to both members) |
| `gate` | `send`, `sent` |

The status of the window can now say in one line what happened and why: it went to 30 instead of 0, because of the schedule, limited by the tilted window. When the window is closed later, the floor disappears, the next recompute yields 0, and the shutters close fully. Nothing had to be remembered for that.

Had the window been in dry-run, steps 1 and 2 would be the same. The gate outcome would be `suppress` with the reason `dry_run`, and `would_send` would list left 30 and right 30: the record of what the integration would have done.

## Inheritance

Configuration is stored on three levels: the house (global), a group, a window. Each level stores only what it sets itself. The module `settings` turns that into the complete `WindowConfig` of one window and records, for every value, where it came from. The configuration forms store; the arbiter wants a complete configuration; this module is the function in between. It raises nothing because of what a user stored, and a fault in stored settings never costs a window its configuration: every problem is part of the result.

### The types

| Type | Meaning |
|---|---|
| `INHERIT` (type `Inherit`) | The one marker for "this level does not set the value". It is never `None`: for a setting whose type allows `None`, a set `None` is a set value that beats the levels below it. |
| `PartialSettings` | What one level sets itself: a read-only mapping from key to value; every other key is `INHERIT`. `get(key)` returns the value or the marker, `with_value` and `with_inherit` return changed copies. `faults` lists stored values that could not be read (`SettingFault`: key, English detail, and a `SettingProblem` code). `unreadable` says that the settings of the level could not be read as a whole. Compared by value; not hashable, because it holds a mapping. |
| `SettingDefinition` | Everything the resolver knows about one setting, in one place: `key`, `kind`, `function`, built-in `default`, `fault_value` (the cautious value of a setting whose function falls back; see [Fault values](#fault-values)), `parse` (reads the value from stored data), `inheritable`, `requires`. `NO_FAULT_VALUE` is the marker for "states none"; `None`, `False` and `0` are fault values somebody can state. |
| `SettingKind` | The declared kind of a setting: `boolean`, `number`, `enumeration`, `list`, `time`, `duration`, `day_of_year`, `optional_reference`. Only an optional reference (a source or an entity that may be absent, `str \| None`) can be "explicitly none". |
| `STORED_NONE` | The string `"__none__"`: how stored data says "explicitly none" for an optional reference. It exists in stored data only. |
| `SETTINGS_KEY` | The string `"settings"`: the key under which a level stores its settings; see the obligation for block H01 below. |
| `CapabilityRequirement` | A setting needs a capability of the window (`Capability`, the four fields of `WindowCapabilityStates`), and the value the configuration carries when the capability is definitely missing. |
| `SettingsRegistry` | The settings that exist. The resolver is generic over it. `functions` are the functions that have a setting, `pausable_functions` those of them that a fault pauses. `WINDOW_SETTINGS` is the registry of the settings of `WindowConfig`; `functions_with_settings()` returns its functions. |
| `GroupLevel` | The group a window refers to: its identifier and its partial settings, or `None` as settings when the group no longer exists. A window without a group passes no `GroupLevel`. |
| `Level` | Where a value came from: `built_in`, `global`, `group`, `window`. |
| `ResolvedValue` | One resolved setting: `value` (what the levels yield), `level` and, for the group level, `group_id`; `capability`, the state of the capability the setting requires (`None` if it requires none); `unavailable` (`MissingCapability`: the capability and the members that definitely lack it) when that state is `missing`; `effective`, the value the configuration carries. `own_value_masked` is true when the masked value is the window's own. `cautious` is true when `value` is the fault value of the setting and not its default; `level` is `built_in` in both cases, and the flag tells them apart. |
| `ReportedFault` | A fault as the result reports it: key, level (with `group_id`), a `SettingProblem` code, an English detail for logs, the `FaultAction` (what the fault costs **this** window) and the functions it paused. The Home Assistant layer translates the codes; the detail is never shown to a user. A missing capability is never a fault. |
| `GroupMissing` | The group a window refers to no longer exists. No data fault: the window inherits from the house, nothing is paused. |
| `ResolvedSettings` | The result for one window: one `ResolvedValue` per setting of the registry, every fault on the levels of this window, `disabled_functions` (the functions that are paused, with `faults_of(function)` naming the faults that did it), `group_missing`, and `masked_own_values`. |
| `SettingRules` | The value rules of the structure that is resolved: `check_value(key, value)` and `build(effective, disabled_functions)`. The resolver has no value rules of its own; for a window both are `WindowConfig`. |
| `WindowResolution` | `ResolvedSettings` plus the `WindowConfig`. The configuration is `None` only if the identity of the window is refused (no member, a member twice) or the registry itself is broken; a fault with the action `configuration_withheld` says why. |

### From stored data to partial settings

`settings_from_stored(data, registry)` is the only place that knows how "inherit" is stored. The rules follow the [configuration flow findings](config-flow-findings.md):

| Stored | Meaning |
|---|---|
| the key is absent | inherit |
| `""`, or text of nothing but whitespace | inherit: a form can deliver an emptied text field that way |
| `0`, `false`, `[]` | a set value |
| `null` | a fault (`unreadable`). `null` is never written, so it is not a second way to say "inherit" or "none". |
| `"__none__"` (`STORED_NONE`) on an optional reference | the set value `None`: "explicitly none". It beats the levels below like any set value, so a window can have no source although its group names one. The string never reaches partial settings or the resolved configuration. |
| `"__none__"` on a setting of any other kind | a fault (`none_not_allowed`): a switch, a number, a choice and a list always have a value |
| a value that `parse` refuses | a fault (`unreadable`) with the message of the refusal |
| a key the registry does not know | a fault (`unknown_setting`), so a misspelled key is noticed instead of silently meaning "inherit" |
| data that is no mapping at all | the level is unreadable as a whole (`level_unreadable`) |

**Obligation for block H01: settings live under their own key.** The house, every group and every window store their settings in a mapping of their own under the key `settings` (`SETTINGS_KEY`), apart from identity data such as the covers, the group reference, the name and dry-run. `settings_from_stored` receives that mapping and nothing else, which is why every key in it must be known.

**Shared readers.** The kinds `time`, `duration` and `day_of_year` have one strict reader each in `core/settings`, so that no two blocks read the same kind differently:

- `as_time`, a local time of day: exactly `"HH:MM"` or `"HH:MM:SS"` on the 24-hour clock, for example `"06:30"`. No offset, no zone, no fraction, no compact form, nothing around it. The zone is the local zone of the installation, which the core gets from the clock port.
- `as_duration`: a whole number of seconds from 0 to 31 622 400, which is 366 days (`MAX_DURATION_SECONDS`), for example `900`. No boolean, no fraction, no text. The upper bound is generous on purpose: no setting of a shutter needs more than a year, and it keeps a stored number from being too large for a duration. It is a number, so there is one spelling of every duration; a form that offers hours, minutes and seconds converts before it stores.
- `as_day_of_year`, a month and a day: exactly `"MM-DD"`, for example `"05-01"`, returned as (month, day). The day has to exist in every year, so `"02-29"` is refused.

All three always have a value, so `"__none__"` is a fault on them.

### Functions and their fault behavior

Every setting belongs to a **function**, a member of the closed list `FunctionId` of the model (`core/model/functions.py`). There are no free strings for functions anywhere: the registry of the settings, the layers, constraints and gate rules of the arbiter and `WindowConfig.disabled_functions` all use this list. Every function has one **fault behavior** (`FunctionId.fault_behavior`, a `FaultBehavior`), which says what happens when a stored setting of the function is faulty.

What decides is the **direction of the effect**. A paused layer creates no wish: less movement, which is cautious. A paused constraint or gate rule removes a restriction: more movement, the wrong direction; a data fault would let a shutter close completely in front of a tilted window. Therefore:

- `fall_back`: every function that protects people or hardware, or that **restricts** movement (constraints, gate rules). It is never paused, and a fault never loosens it. A faulty value is passed by; another level supplies a valid one, and if none does, the cautious **fault value** of the setting applies, not its default.
- `pause`: only functions that **create** wishes for convenience. A faulty value pauses the function for the windows it reaches, because falling back to another value could make a window do what was explicitly excluded.

The fault behavior is not the wish class of the arbiter (fire, protection, comfort): `ventilation` is a comfort feature and still falls back, because it restricts movement.

| Function | Fault behavior |
|---|---|
| `schedule` | pause |
| `sleep` | pause |
| `request` | pause |
| `privacy` | pause |
| `shading` | pause |
| `solar_heating` | pause |
| `fire` | fall_back |
| `protection_events` | fall_back |
| `lockout` | fall_back |
| `ventilation` | fall_back |
| `frost` | fall_back |
| `motor_protection` | fall_back |
| `command_verification` | fall_back |
| `manual_override` | fall_back |

`fire` and `protection_events` create wishes too, but they protect. `lockout` is the blocking contacts and the tamper contact. `ventilation` is the floor under comfort wishes while a window is open or tilted, including rain while ventilating. `manual_override` is the detection of a movement by hand and the two dams: a fault there must never make the integration fight a person. The direction constraint of a wish has no function of its own, which is fine as long as it has no settings. A test compares this table with the enumeration. **The order of the members has meaning:** the arbiter asks the parts of one layer in the definition order of `FunctionId`, so reordering or inserting a member changes behavior; a test pins names, values and order. The list is provisional in its members, not in its shape: a block that needs a function adds a member with its fault behavior, in its own pull request, here and in this table.

Today's settings: `morning_condition_source`, `schedule_profile` and every setting whose key begins with `schedule_` belong to `schedule` ([the schedule](schedule.md#settings) lists them), `shading_temperature_tiers` to `shading`. `covering_type` names no function (`function=None`): it describes the window itself, not a function. That is allowed only for a setting that cannot be inherited, and a fault in it falls back.

### The resolver

`resolve_settings(registry, capabilities=…, members=…, global_settings=…, group=…, window_settings=…, rules=…)` resolves every setting of a registry. `resolve_window(window_id=…, members=…, …)` does it for `WINDOW_SETTINGS`, takes the capabilities from the model (`WindowConfig.capability_states`: over all members, missing beats unknown beats present) and builds the `WindowConfig`.

1. **Order.** For every key the levels are walked from the window outwards: window, group, house, built-in default. The first level that sets the key decides, whatever the value is: `0`, `False` and an empty tuple are values. A window without a group inherits from the house directly.
2. **Provenance.** Every resolved value names its level, and the group if that is the level, so the user interface and the diagnostics can say "inherited from group …".
3. **Settings that cannot be inherited** have `inheritable=False` in their definition, and nowhere else. They are read from the window alone; on a group or the house such a key is a fault (`not_inheritable`). Of today's settings that is the covering type. The identifier and the members of a window are no settings at all: the caller hands them in. `disabled_functions` is a result of the resolver and never stored (`WINDOW_FIELDS_THAT_ARE_NO_SETTINGS`).
4. **A group that no longer exists** (`GroupLevel(group_id, None)`): the window inherits from the house and the result carries `GroupMissing`. That is no data fault and pauses nothing; the Home Assistant layer raises the repair issue.
5. **Capability mask.** A group has no covers, so it can set an option that the covers of one of its windows cannot execute; and a cover can be replaced by one that can do less. The capability a setting `requires` has three states for the window:
   - `present`: the value applies.
   - `missing` (a member definitely lacks it): the setting is **not available**. `unavailable` names the capability and the limiting members, the provenance stays, and `effective` is the definition's `value_when_missing`, so the arbiter never acts on the option. This holds for a value from the group, from the house, for the built-in default, and for the window's **own** value. **Mask and report:** an own value stays stored, takes effect again as soon as the capability is back, and is listed in `masked_own_values`, apart from masked inherited values, so the user interface can word it differently and raise a repair issue. A masked own value is validated all the same.
   - `unknown` (nothing was ever known about a member, for example at the very first start with an entity that has never been seen): the value applies unmasked and nothing is reported; `capability` says `unknown`, so nobody mistakes it for confirmed. A sequence present → unknown → present never masks and never reports.

   **For the authors of the Home Assistant layer (blocks H02 and H12): who provides what.** While an entity is not available, the last known state applies, and providing it is your job (entity registry or persistence). Hand the last known flags in with `capabilities_known=True`. Use `capabilities_known=False` only when nothing was ever known about the member, and never just because its entity is unavailable right now. Otherwise a cover without stop would lose its mask and its repair issue for the two minutes its entity is away and get both back afterwards. With the last known flags handed in as known, the resolver sees the same input before, during and after the gap, and its result is identical.

### Faults in stored settings

A data fault must never take the protection of a window away, and it must never make a window move unexpectedly. So the rule is the same on all three levels, and what a fault costs depends on the fault behavior of the setting's function:

- **Fall back, and never loosen.** A faulty setting of a function that protects or restricts movement is passed by. If another level supplies a valid value, that value applies. Otherwise the **fault value** of the setting applies, not its default: a faulty value never makes such a function less restrictive than a valid value would. Fire, protection events, frost protection, the ventilation floor and the rest keep running for every window. See [Fault values](#fault-values).
- **Pause.** A faulty setting of a function that creates wishes for convenience pauses that **function** for exactly those windows for which the faulty value would have been the effective one. There is no fallback to a value that could trigger a movement.
- **Everything is reported**: level, key, problem, and what it costs this window.
- **The window always gets a configuration.** It is not set up only if its covers cannot be read, which is outside the resolver.

**Which windows a fault reaches.** For every key the walk goes from the window outwards, and the first level that **sets** the key decides. If that value is sound, it is effective and nothing is paused, whatever lies further out; a fault further out is reported with the action `no_effect`, so the repair issue of its level still names it. If that value is faulty, it would have been the effective one for this window: the walk goes on outwards for the value, and if the function pauses on a fault, it is paused for this window (the arbiter then does not act on the value). A window that sets a sound value of its own for a key is therefore never reached by a fault of its group or the house in that key.

A **fault** is any of these, for one key on one level. Every set value of every level is judged, whether or not it wins.

| Kind of fault | Problem code |
|---|---|
| a stored value the setting cannot read, a value of the wrong type, `null` | `unreadable` |
| `"__none__"` on a setting that always has a value | `none_not_allowed` |
| a value that was read, but `WindowConfig` refuses it (also a masked own value) | `invalid` |
| a setting that cannot be inherited, set on a group or the house | `not_inheritable`; always `no_effect`, see below |
| the effective values of several settings are refused together by a rule that spans them (see below) | `combination` |

What such a fault costs, by the fault behavior of the setting's function and by whether the fault reaches the window. The outcome is the same for a fault on the window, on the group and on the house:

| | The faulty value would have been effective for the window | A closer level sets a sound value |
|---|---|---|
| **Function falls back**, and another level supplies a valid value | `fell_back`: that level supplies the value; `level` of the resolved value says which. Nothing is paused. | `no_effect`: reported, nothing else. |
| **Function falls back**, and no level supplies a valid value | `fell_back_to_cautious_value`: the fault value of the setting is effective, not its default; `cautious` of the resolved value is true and its `level` is `built_in`. Nothing is paused. | (does not occur: a closer sound value is a valid value) |
| **A setting without a function** | `fell_back`: the next level supplies the value, last the built-in default; it has no fault value, because nothing depends on it. | `no_effect` |
| **Function pauses** | `functions_disabled`: the function of the setting is paused for this window and is part of `WindowConfig.disabled_functions`. | `no_effect`: reported, nothing else. |

**How a repair issue tells the two apart.** After `fell_back` the window runs on a value somebody chose, on another level. After `fell_back_to_cautious_value` it runs on a value **nobody chose**: the restriction is kept or tightened on purpose (frost protection limits although no source can be read, a closed shutter is not raised in frost), and it stays that way until the stored value is repaired. `ReportedFault.action` carries the difference, and `ResolvedValue.cautious` names the settings concerned.

Two kinds of fault do not concern one setting:

| Kind of fault | Problem code | Outcome on every level |
|---|---|---|
| a key the registry does not know | `unknown_setting` | `ignored`: reported, never silently dropped, but it pauses nothing and makes nothing invalid. A newer version may have written it (the downgrade case). |
| the settings of a level are unreadable as a whole (no mapping) | `level_unreadable` | The level counts as not present. `functions_disabled`: **all** functions with settings that pause on a fault are paused for the windows in whose chain the level lies (the window itself; every window of the group; every window of the house), also for a window that overrides some keys, because it is unknown which keys would have been concerned. The functions that fall back take the values of the other levels. Nobody can see whether the unreadable level had set a value, so every setting of a function that falls back **that the level could have held** and for which no other level supplies a valid value takes its fault value. The result lists the level once more for each such setting, with the key and the action `fell_back_to_cautious_value`. A level could have held every setting that can be set on it: the window all of them, a group or the house the inheritable ones only. A setting that only a window can set (a blocking contact) is therefore never touched by an unreadable house or group; otherwise one broken house level would blind the contact of every window. |

**A setting that cannot be inherited, set on a group or the house,** could never have been the effective value of any window. By the rule above it therefore pauses nothing and changes nothing: it is reported as `not_inheritable` with the action `no_effect`.

**Nothing a reader or the model raises escapes.** A refusal is meant to be a `ValueError` or a `TypeError`, but hostile data makes Python raise other things by itself: a whole number with four hundred digits is too large for a float (`OverflowError`), JSON writers can produce infinity and "not a number", data can be nested absurdly deep. The readers of this module refuse such values themselves (`expected a finite number`, the bound of `as_duration`), and as a second line `settings_from_stored`, the check of single values and the final build catch `TypeError`, `ValueError`, `ArithmeticError`, `LookupError`, `AttributeError` and `RecursionError`, so a reader of a later block cannot break the promise either. A test feeds a list of hostile values to every registered setting on every level and asserts: no exception, a configuration for the window, only functions that pause are paused.

**A rule that spans several settings** (for example "the morning lies before the evening") refuses a combination of values that may each be fine on their own. `resolve_window` builds the final `WindowConfig` under the same protection as everything else. The contract: such a rule raises `SettingsCombinationError` (in `core.model`), which **names the keys it concerns**. The invariant: a refusal of the whole never discards or reports a sound value of a setting the rule does not concern, never pauses a function the rule does not concern, and never blames a level whose values are not involved. There is no search for a combination that happens to build.

- Only the named keys become faulty (`combination`), and only on the levels that supply their **effective** values; a built-in default is nobody's fault. The repair issue can say that each value alone is fine.
- A named key of a function that **pauses**: the function is paused for this window by the ordinary rule, and the built-in default stands in for the value. The value of a level further out is not taken: a combination of inherited and own values that the user never chose together must not move a shutter, and the function is paused anyway.
- A named key of a function that **falls back** (only when no pausing key is left to handle, because pausing may already heal the combination): the innermost level that supplies one of these keys is passed by for the keys it supplies, and the build is tried again, level by level. A key that no level is left for ends at its **fault value**, like any faulty key. One test asserts that the defaults alone build, another that the fault values build together.
- While single values are checked, a `SettingsCombinationError` is ignored: the value is sound on its own, and the combination is judged with the effective values of the window.
- A refusal of the whole that names **no** keys (or only keys that no level supplies) cannot be attributed. That is a programming error in a rule, not a fault of stored data, and it is reported as `rule_without_keys` on the level `built_in`. Protection has to keep running all the same, so the window is not given up at once: first every function that pauses is paused and its settings take their defaults (`functions_disabled`); if the whole is still refused, the settings of the functions that fall back take their fault values (`fell_back_to_cautious_value`; a setting without a function its default), because nobody knows which of them the refusal concerned and none may end less restrictive than a level had made it; only if even these built-in values are refused is the configuration withheld. The rules of `WindowConfig` are code in its `__post_init__` and cannot be enumerated, so no test can list rules without declared keys; the step "a rule over several settings" below is the safeguard.

`WindowConfig` has two such rules so far, both of the schedule ([the schedule](schedule.md#triggers-and-clamps)); the generic resolver is also tested with rules over two pausing functions, over a function that falls back, and over one of each.

Only two things withhold a configuration, and neither is a fault of stored settings: an identity the model refuses (key `members` or `window_id`), and built-in defaults that the rules refuse (a broken registry). Both are reported with the action `configuration_withheld`.

### Fault values

Every setting of a function that falls back states a **fault value** next to its default (`SettingDefinition.fault_value`). It is what the function runs on when a level tried to set the value and could not, or is unreadable as a whole, and no other level supplies a valid one. Two rules decide the value, and both were decided by the project owner (decision 15):

1. **A fault never loosens.** A faulty value never makes the function less restrictive than a valid value would. A default often means "not configured" or "off", and falling back to it would lift the restriction: an unreadable frost source once removed the frost limit that way.
2. **A fault never costs protection.** A fault **on its own** never restricts a **protection** wish more than the default does. Cautious values may restrict comfort only: a hail opening must not stop short because of a data fault. Where the user has **validly** switched on that a function that falls back restricts protection wishes (here `frost_applies_to_protection`), the cautious fault values of its other settings reach those wishes exactly as their valid restrictive values would: a faulty "hold closed" keeps a closed shutter closed at hail, as a valid "on" does, and a blind source limits the hail opening to the frost position, as a valid source in frost does. Fire stays untouched in every case.

What that means by kind of setting:

| Kind | Fault value |
|---|---|
| an optional reference to a source | `BLIND_SOURCE`: configured, but blind. The rules for a blind source of that feature apply (the frost limit stays; an unknown contact never leads to closing). |
| a switch that restricts comfort wishes | the more restrictive of the two positions |
| a switch that restricts protection wishes only | its default (rule 2) |
| a number, a position, a duration | usually the default, **stated on purpose**. Such a value has no "most restrictive" end that would still be useful (a frost position of 0 would block every opening in frost), so the approved default is the cautious value; it must never be less restrictive than the default. |

The fault values of the window's settings, each with its reason as a comment at the entry in `WINDOW_SETTINGS`:

| Setting | Default | Fault value | Why it is the cautious one |
|---|---|---|---|
| `frost_source` | none | `BLIND_SOURCE` | "none" means "not configured" and would lift the frost limit; blind keeps it until the setting is repaired or frost protection is waived |
| `frost_threshold` | 0.0 | 0.0 | a higher threshold engages earlier, but a number has no most restrictive value; the freezing point never engages later than approved |
| `frost_hysteresis` | 1.0 | 1.0 | frost never ends earlier than with the approved band |
| `frost_position` | 90 | 90 | lower would open less, and its extreme, no opening at all, was rejected (decision 13) |
| `frost_applies_to_protection` | off | off | "on" restricts more, but it restricts protection wishes only (rule 2) |
| `frost_hold_closed` | off | **on** | the more restrictive of the two: a closed shutter is not raised in frost. It reaches comfort wishes only, because with the fault value of the row above the constraint never touches a protection wish |
| `motor_min_change` | 5 | 5 | never smaller than approved; zero would switch it off |
| `motor_min_interval` | 10 min | 10 min | never shorter than approved |
| `reevaluate_after` | 5 min | 5 min | neither direction is "more restrictive": the bound never lets a command through, it only says when a deferred window is evaluated again at the latest |

An entry of a function that falls back **does not construct** without its fault value, and the argument has no silent default; for a setting of a function that pauses, and for a setting without a function, a fault value is refused. Three tests keep the values honest, and none of them names a setting, so a setting that a later block registers is covered without new test code:

- `test_every_setting_of_the_window_that_falls_back_states_a_valid_fault_value` (`tests/core/test_settings_fault_values.py`): every such entry states a value that `WindowConfig` accepts, and `test_fault_values_of_the_window_build_together` shows that all of them together satisfy every rule over several settings.
- The two generic tests of `tests/core/test_fault_values.py` check rule 1 and rule 2 in the situations of `tests/core/fault_value_situations.py`. [The arbiter](arbiter.md#the-two-generic-tests-of-the-fault-values) says what they prove, what they do not, and how a block adds situations.

### Adding a setting

A real entry of the registry, the optional source of the morning condition:

```python
SettingDefinition[str | None](
    key="morning_condition_source",
    kind=SettingKind.OPTIONAL_REFERENCE,
    function=FunctionId.SCHEDULE,
    default=None,
    parse=as_str,
)
```

| Field | Meaning |
|---|---|
| `key` | The name of the setting in stored data and in the result; for a setting of a window it is the name of its field of `WindowConfig`. |
| `kind` | The declared kind. It decides whether stored data may say `"__none__"`: only an `optional_reference` may. |
| `function` | The function the setting belongs to, a member of `FunctionId`. Its fault behavior decides what a fault costs: `schedule` pauses, so a faulty morning condition pauses the schedule for the windows it reaches. |
| `default` | The built-in default, used when no level sets the value. It equals the default of the field of `WindowConfig`. |
| `fault_value` | Left out here, because `schedule` pauses on a fault: a fault value is refused for such a setting. For a setting of a function that **falls back** it is required: the cautious value that applies when a level tried to set the value and could not, and no other level supplies a valid one. The entry of the frost source states `fault_value=BLIND_SOURCE`, the one of the frost position `fault_value=Position(90)`, its default, stated on purpose. See [Fault values](#fault-values). |
| `parse` | Reads the stored value and raises a `ValueError` if it cannot. It is never called for an absent key, blank text, `null` or `"__none__"`. |
| `inheritable` | Left out here, so `True`. `False` for what belongs to one window only; such a setting is read from the window alone. |
| `requires` | Left out here: the setting needs no capability. Otherwise `CapabilityRequirement(capability, value_when_missing)`, where `value_when_missing` is the value the configuration carries while the capability is definitely missing (`False` for a switch, `None` for an optional position). |

For this entry the resolver returns a `ResolvedValue` with `value` (what the levels yield, for example the group's `"binary_sensor.example_south"`, or `None` if the window said "none"), `effective` (the same, because nothing can mask it), `level` and `group_id` (for example `group` and the group's identifier), `capability` (`None`, because it requires none) and `unavailable` (`None`). For an entry with `requires`, `capability` is `present`, `missing` or `unknown`; while it is `missing`, `unavailable` names the capability and the limiting members, `effective` is `value_when_missing`, and `own_value_masked` is true if the masked value is the window's own. A fault in the entry appears in `ResolvedSettings.faults`, and if it reaches the window, `schedule` is in `disabled_functions`.

**How a later block adds a setting**, step by step:

1. **The function.** Choose the function the setting belongs to from `FunctionId`. If none fits, add a member to `core/model/functions.py` with its fault behavior (`fall_back` for whatever protects people or hardware or restricts movement; `pause` only for a function that creates wishes for convenience), to the pinned mapping in `tests/core/test_model_window.py` and to the table above; a test compares the table with the enumeration.
2. **The field.** Add the field to `WindowConfig` in `core/model/window.py`, with its default, and validate it in `__post_init__`. The value rules of a setting live there and nowhere else; the resolver hands every set value of every level to `WindowConfig` and turns a refusal into a fault of that key on that level.
   **A rule over several settings** goes into `__post_init__` too, and it must raise `SettingsCombinationError(message, keys)` with exactly the fields it concerns, for example `SettingsCombinationError("the morning must lie before the evening", ("morning_time", "evening_time"))`. Never raise a plain `ValueError` for a combination: the resolver could not attribute it and would have to pause every pausable function of the window. The built-in defaults must satisfy the rule. **In `__post_init__`, the checks of single values come before the rules over several settings:** otherwise a combination rule that trips against the defaults hides an invalid single value, and the refusal arrives unattributed. **For a rule over a key of a pausing function and a key of a function that falls back:** the pausing function is paused first, and if its default still conflicts, a sound value of the falling-back function is passed by. So design such a rule, where possible, so that the defaults of the pausing side satisfy it with every allowed value of the other side. Test the rule in the tests of the model, and add one test through `resolve_window` that shows which keys are reported and that an unrelated own value of the window stays.
3. **The one entry.** Add one `SettingDefinition` to `WINDOW_SETTINGS` in `core/settings.py`: `key` is the name of the field, `default` is the default of the field, `kind` is its declared kind, `function` its function, `parse` reads the stored form. Add `inheritable=False` if only a window can set it, and `requires=CapabilityRequirement(...)` if it needs a capability. Nothing else in `settings` changes: reading stored data, the order of the levels, provenance, the mask, the handling of faults and the construction of the `WindowConfig` follow from the entry.
4. **Choose the fault value**, if the function of the setting falls back; the entry does not construct without it. Ask two questions. *Which value never makes the function less restrictive for a comfort wish than a valid value would?* For an optional reference to a source that is `BLIND_SOURCE` (the type of the field is then `str | BlindSource | None`, and the feature treats the marker by its rule for a blind source); for a switch the more restrictive position; for a number, a position or a duration usually the default, stated on purpose, and never a value that is less restrictive than the default. *Can that value restrict a protection wish more than the default does?* Then it is not allowed: **a fault on its own never restricts a protection wish more than the default does**, cautious values may restrict comfort only; a switch that reaches protection wishes only keeps its default. (What a person validly switched on stays their choice: the cautious values of the other settings then reach protection wishes as their valid restrictive values would.) Write the reason as a comment at the entry, add the row to the table under [Fault values](#fault-values), and add situations for the function to `tests/core/fault_value_situations.py` if it has none yet (a comfort wish it restricts, and a protection wish if it can restrict one). The two generic tests then judge your value without new test code, and they fail with advice while a function with such settings has no situation. A setting of a function that pauses, or without a function, states no fault value.
5. **The safety net.** `test_every_setting_of_the_window_that_falls_back_states_a_valid_fault_value` in `tests/core/test_settings_fault_values.py` fails, with advice, for an entry of a function that falls back without a fault value or with one the window configuration refuses. `test_registry_of_the_window_covers_every_field_of_the_window_configuration` in `tests/core/test_settings.py` fails if either half is forgotten or the two defaults differ in type or value. Its message says what to add where: for a field without an entry, the `SettingDefinition(key=…, kind=…, function=…, default=…, parse=…)` to add to `WINDOW_SETTINGS` and its file; for an entry without a field, the field to add to `WindowConfig` and its file; for different defaults, both values and both files. An entry without a function does not construct. No other test of `tests/core/test_settings.py` pins the whole registry, so no other test has to be touched.
6. **The stored form.** Decide how the value is stored and write `parse` for it, or use a shared reader (`as_time`, `as_duration`, `as_day_of_year`, and the readers of plain data in `core/model/_data.py`). An absent key and blank text mean "inherit" and `null` is a fault, for every setting, without any code of yours. `"__none__"` is accepted only if the kind is `optional_reference` and then arrives as the set value `None`, so the type of such a field is `str | None` (`str | BlindSource | None` if its function falls back); on every other kind it is a fault.
7. **Tests.** Test the parser with stored values it accepts and refuses, and the value rules in the tests of the model. The order of the levels, provenance, the mask and the handling of faults are tested once for all settings and need no new test.
8. **Documentation.** Describe the field in the `WindowConfig` row of this page, and the setting for users on the page of its feature: what it does, its default, what happens on a window that lacks a required capability, and what a faulty stored value does: it pauses the function, or it falls back to the next level and, if no level is left, to its fault value (say which value that is and what the user then sees).
