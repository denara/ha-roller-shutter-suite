# The core model

The domain core decides where a shutter goes. Its blocks are written by different people and agents, and they fit together because they exchange the same data types. This page lists those types. They live in three places under `custom_components/roller_shutter_suite/core/`:

| Module | Content |
|---|---|
| `model` | the data types; a package, see below |
| `reasons` | the closed list of reason codes |
| `ports` | what the core needs from outside: clock, sun, actuator, storage |

The vocabulary and the rules come from the [domain design specification](../architecture.md). This page only says how the vocabulary looks in code. There is no behavior in these modules: no arbiter, no schedule, no tracking, no geometry.

`model` is a package, so that blocks that work in parallel edit different files. Always import from the package: `from custom_components.roller_shutter_suite.core.model import Position`. Its modules depend on each other in one direction only, and a test enforces it:

| Module of `model` | Content |
|---|---|
| `values` | position, source value, sun position |
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
- **No free text in a decision.** Reasons are codes from the closed list in `reasons`, and each place accepts only the codes of its group: a wish for a target only codes of winning layers; other wishes and layer reasons also the codes that say why a layer did not act; a constraint result only the codes of its constraint (`CONSTRAINT_REASONS`); a gate outcome only the codes of its rule (`GATE_RULE_REASONS`, the group "gate" plus `capability_missing`). Codes that exist for events only never appear in a decision.
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
| `Wish` | The answer of one layer: kind, layer, reason code, and for a target either one position for all members or one position per member, an optional direction, and optionally the ray height the positions were computed from. |
| `MemberTarget` | The target of one member on the motor scale; a position of `None` means the member stays where it is. |
| `LayerReason` | Why a layer did not win: the layer and a reason code. |
| `Constraint` | The seven constraints in the order in which they are applied. |
| `ConstraintResult` | What one constraint did: the constraint, its reason code, and the target of every member after it. |
| `GateRule` | The twelve rules of the gate in the order in which they are evaluated, from maintenance lock to dry-run. |
| `GateKind` | `send`, `defer` or `suppress`. |
| `GateOutcome` | The answer of the gate: kind, reason code, the rule that decided, for a deferral its time (see below), and for a window in dry-run the hypothetical outcome (see below). |
| `Decision` | The complete result of one recompute: the winning wish, the reasons of the other layers, the constraint results, the target of every member, and the gate outcome. All of them name the same members in the same order. `target` is the target the window shows: the common target if all members have the same one, otherwise none, with the per-member targets as the detail. |

**Deferral.** Nothing waits forever. A deferral states exactly one of two times: `until`, the time at which it ends, if that is known; or `reevaluate_no_later_than`, if it ends with a condition whose time nobody knows (a member becomes available, the members come to rest). The second is an upper bound: at that time at the latest the window is recomputed from the state it has then, and nothing is replayed. A deferral with neither is refused.

**Dry-run.** A window in dry-run never moves, and its decision shows what would have happened. `GateOutcome.dry_run` is true for such a window. Either the last rule decided: then the reason is `dry_run` and `would_send` lists the command that would have been sent. Or an earlier rule decided: then `rule` and the reason name what would have held the wish back, for example `pause` with `paused`.

**No gate outcome.** `Decision.gate` is `None` when nothing reached the gate: the winning wish was "leave alone", no layer had an opinion, or a constraint pinned every member where it is. In that case the reason of the constraint is the reason why nothing moves.

### Windows and members

A window has one or more members: the covers that are always moved together. Everything a cover can do or report is kept per member, and the window-level view is derived from the members.

| Type | Meaning |
|---|---|
| `CoveringType` | What hangs in front of the glass. Only `roller_shutter` exists; the field is there so venetian blinds can be added later. |
| `CapabilityProfile` | What a member can do and report: open/close, set position, stop, reports a position, position source, transit states, position updates during travel, report delay, travel time up and down, and the tolerance for comparing a reported position with a target (the stated one, else 2 for a calculated and 3 for a measured position; at least 1). A cover without position feedback is a valid profile. |
| `PositionSource` | `measured` by the drive, or `calculated` from run time (the default). |
| `TransitReporting` | Whether a member reports "opening" and "closing": `yes`, `no`, or `unknown` until observed. |
| `PositionUpdates` | `live` during travel, or at the `end_only`. |
| `MemberConfig` | One member: its identifier and its capability profile. |
| `WindowCapabilities` | What all members of a window can do: the lowest common denominator. |
| `WindowConfig` | A window after inheritance has been resolved: identifier, covering type, members, and three places for later features (the condition input of the morning opening, the tiers of the temperature condition, the profile key of the schedule). The blocks that build a feature add its settings here; so far `motor_protection`, `frost` and `reevaluate_after`, the upper bound of a deferral whose end is not known (default 5 minutes). |
| `MotorProtectionSettings` | The minimum change in percent (default 5) and the minimum interval between two own comfort movements (default 10 minutes); zero switches a part off. |
| `FrostSettings` | Frost protection of a window: the key of the temperature source (none means not configured), threshold (default 0) and hysteresis (default 1), the frost position (default 90), whether protection movements are limited too (default no), and `hold_closed`, the option "do not raise a closed window at all" (default off). |
| `TemperatureTier` | One tier of the temperature condition of shading: threshold and hysteresis. A window has none or one. |
| `ScheduleProfile` | The key under which the schedule looks up its targets. It has one value, `default`. |
| `MovementState` | The state class of an observation: `resting`, `moving_up`, `moving_down` or `unavailable`. |
| `Observation` | A normalized report of one member: state class and position, if it reports one. An unavailable member has no position. |
| `MemberObservation` | The current observation of one named member. |
| `WindowObservation` | The observed members of a window and the view over them: available while one member is; `reports_movement` as soon as one member reports a movement (whether it has settled is the tracker's knowledge); `position(tolerances)`; and `members_at_commanded_targets(commanded, tolerances)`, see below. |
| `WorldSnapshot` | Everything one recompute may look at: the time, the sun position, the source values by key, the observed window, the persisted window state, and the controls. |
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
| `OwnCommand` | A command of the integration to a member: its identifier, target, direction (`TravelDirection`: `up` or `down`), time, wish class, and the context under which it was executed once that is known. The identifier goes to the actuator and comes back with the result, so a late result is never attributed to a newer command. |
| `MemberCommand` | An own command together with the member it went to. |
| `PositionReference` | Whether a calculated position can be trusted: `referenced` or `uncertain`. |
| `MemberState` | Per member: the last own command with its target, the last observation, the position reference flag, and the command backoff as facts: the number of attempts of the current command and the time of the last attempt (no attempts without a last own command). The time of the next retry is never stored; it is computed from the two facts with the current settings, so a reload right after a failed attempt does not send a second command at once. |
| `ManualOverrideDam` | The armed manual override: armed at, end rule (`OverrideEndRule`), absolute end if the rule has one, and the position the person chose. |
| `PersonAtWindowDam` | The armed person-at-the-window dam: when it ends. |
| `ProtectionEventState` | Per protection event: active or inactive (`ProtectionEventStatus`), active since, ended at, released at, and the position and owner remembered from before the event. An active event has "active since" and no "ended at"; an inactive one may have an "ended at". "Released at" is the time at which the watchdog released the event; the event stays active as long as its trigger is, and an inactive event can still carry it. `released` is a read-only view of it. Times are stored, not deadlines: the waiting time of the return is configuration, and it runs from `return_clock_start`, the release if there was one, otherwise the end. |
| `ShadingEpisodeState` | Active since, and the end of the rain lock. |
| `SolarHeatingEpisodeState` | Active since, and the "opened once" flag. |
| `ExternalRequest` | A position requested by an automation, the text the caller gave as reason, and the expiry. |
| `DayType`, `LatchedDayType` | `workday`, `weekend` or `holiday`, and the day type that was fixed for one date. |
| `HeldInput` | The last known value of an on/off input that is held while its source is missing (frost, season), and when it was seen. |
| `SimulatedState` | Only in dry-run: the would-be commands per member and a motor protection clock of their own, kept apart from the real state. |

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
