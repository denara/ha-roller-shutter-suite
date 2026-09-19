# The core model

The domain core decides where a shutter goes. Its blocks are written by different people and agents, and they fit together because they exchange the same data types. This page lists those types. They live in three modules under `custom_components/roller_shutter_suite/core/`:

| Module | Content |
|---|---|
| `model` | the data types |
| `reasons` | the closed list of reason codes |
| `ports` | what the core needs from outside: clock, sun, actuator, storage |

The vocabulary and the rules come from the [domain design specification](../architecture.md). This page only says how the vocabulary looks in code. There is no behavior in these modules: no arbiter, no schedule, no tracking, no geometry.

## Rules that hold for every type

- **Immutable and compared by value.** Every type is a frozen data class or an enumeration. Two objects with the same content are equal, and all types except the world snapshot can be used in sets and as dictionary keys.
- **Validated on construction.** An object that exists is valid. A position of 101, a naive datetime or a wish without a reason code raises an error where it is created, not later where it is used.
- **100 is open.** A position is an integer from 0 to 100; 100 is fully open, 0 is fully closed.
- **Timestamps are timezone-aware.** A datetime without a time zone is rejected, also when persisted data is read back.
- **No free text in a decision.** Reasons are codes from the closed list in `reasons`.
- **Missing data is not good news.** A source value that is unknown or unavailable has no truth value, does not convert to a number, and has no accessor that returns a default.

## The types

### Values

| Type | Meaning |
|---|---|
| `Position` | An integer from 0 to 100; `FULLY_OPEN` and `FULLY_CLOSED` name the two ends. |
| `SourceValue` | An input read from a source, in one of three states (`SourceState`): a value, unknown, or unavailable. Reading `value` raises unless the state is "value"; `bool(...)` always raises. |
| `SunPosition` | Azimuth and elevation of the sun in degrees. |

### Wishes, constraints, gate, decision

| Type | Meaning |
|---|---|
| `Layer` | The seven layers of the arbiter in the order in which they are asked, from fire to schedule. |
| `WishClass` | `fire`, `protection` or `comfort`; it follows from the layer. |
| `WishKind` | What a layer answers: `target`, `leave_alone` or `no_opinion`. |
| `Direction` | A limit a wish carries itself: `raise_only` or `lower_only`. |
| `Wish` | The answer of one layer: kind, layer, reason code, and for a target the position, an optional direction, and optionally one position per member together with the ray height they were computed from. |
| `MemberTarget` | The target of one member; a position of `None` means the member stays where it is. |
| `LayerReason` | Why a layer did not win: the layer and a reason code. |
| `Constraint` | The seven constraints in the order in which they are applied. |
| `ConstraintResult` | What one constraint did: the constraint, its reason code, and the target of every member after it. |
| `GateRule` | The twelve rules of the gate in the order in which they are evaluated, from maintenance lock to dry-run. |
| `GateKind` | `send`, `defer` or `suppress`. |
| `GateOutcome` | The answer of the gate: kind, reason code, the rule that decided, for a deferral the point in time if there is one, and for a window in dry-run the hypothetical outcome (see below). |
| `Decision` | The complete result of one recompute: the winning wish, the reasons of the other layers, the constraint results, the target of every member, and the gate outcome. `target` is the target the window shows, that of its first member. |

**Dry-run.** A window in dry-run never moves, and its decision shows what would have happened. `GateOutcome.dry_run` is true for such a window. Either the last rule decided: then the reason is `dry_run` and `would_send` lists the command that would have been sent. Or an earlier rule decided: then `rule` and the reason name what would have held the wish back, for example `pause` with `paused`.

**No gate outcome.** `Decision.gate` is `None` when nothing reached the gate: the winning wish was "leave alone", no layer had an opinion, or a constraint pinned every member where it is. In that case the reason of the constraint is the reason why nothing moves.

### Windows and members

A window has one or more members: the covers that are always moved together. Everything a cover can do or report is kept per member, and the window-level view is derived from the members.

| Type | Meaning |
|---|---|
| `CoveringType` | What hangs in front of the glass. Only `roller_shutter` exists; the field is there so venetian blinds can be added later. |
| `CapabilityProfile` | What a member can do and report: open/close, set position, stop, reports a position, position source, transit states, position updates during travel, report delay, travel time up and down. A cover without position feedback is a valid profile. |
| `PositionSource` | `measured` by the drive, or `calculated` from run time (the default). |
| `TransitReporting` | Whether a member reports "opening" and "closing": `yes`, `no`, or `unknown` until observed. |
| `PositionUpdates` | `live` during travel, or at the `end_only`. |
| `MemberConfig` | One member: its identifier and its capability profile. |
| `WindowCapabilities` | What all members of a window can do: the lowest common denominator. |
| `WindowConfig` | A window after inheritance has been resolved: identifier, covering type, members, and three places for later features (the condition input of the morning opening, the tiers of the temperature condition, the profile key of the schedule). The blocks that build a feature add its settings here. |
| `TemperatureTier` | One tier of the temperature condition of shading: threshold and hysteresis. A window has none or one. |
| `ScheduleProfile` | The key under which the schedule looks up its targets. It has one value, `default`. |
| `MovementState` | The state class of an observation: `resting`, `moving_up`, `moving_down` or `unavailable`. |
| `Observation` | A normalized report of one member: state class and position, if it reports one. An unavailable member has no position. |
| `MemberObservation` | The current observation of one named member. |
| `WindowObservation` | The observed members of a window and the view over them: available while one member is, moving while one member moves, and the position of the first member. |
| `WorldSnapshot` | Everything one recompute may look at: the time, the sun position, the source values by key, the observed window, and the persisted window state. |

### Persisted window state

`WindowState` is everything a window has to remember between recomputes and across a restart. `WindowState()` is the state of a window that was just set up. `to_data()` turns it into plain data that can be written as JSON, with a `schema_version`; `from_data()` reads it back and refuses naive datetimes, malformed data and other schema versions. Migration between versions is the job of the later `persistence` module.

| Type | Meaning |
|---|---|
| `PositionOwner` | Who put the window where it is: `engine`, `user` or `unknown`. |
| `OwnCommand` | A command of the integration to a member: target, time and wish class. |
| `MemberCommand` | An own command together with the member it went to. |
| `PositionReference` | Whether a calculated position can be trusted: `referenced` or `uncertain`. |
| `MemberState` | Per member: the last own command, the last observation and the position reference flag. |
| `ManualOverrideDam` | The armed manual override: armed at, end rule (`OverrideEndRule`), absolute end if the rule has one, and the position the person chose. |
| `PersonAtWindowDam` | The armed person-at-the-window dam: when it ends. |
| `ProtectionEventState` | Per protection event: active or inactive (`ProtectionEventStatus`), active since, released by the watchdog, and the position and owner remembered from before the event. |
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
| `Clock` | The current time. The core never reads a clock itself. |
| `Sun` | The sun position at a time, sunrise and sunset of a date, and when the sun passes a given elevation. |
| `Actuator` | Sends a position to one member. |
| `Storage` | Loads, saves and deletes the plain data of a window state, and keeps the installation's seed for random offsets. |

The Home Assistant layer implements the ports for the runtime. Tests and the time-lapse simulation implement them with a synthetic world.

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
| `target` | 30 (the first member's) |
| `gate` | `send`, `sent` |

The status of the window can now say in one line what happened and why: it went to 30 instead of 0, because of the schedule, limited by the tilted window. When the window is closed later, the floor disappears, the next recompute yields 0, and the shutters close fully. Nothing had to be remembered for that.

Had the window been in dry-run, steps 1 and 2 would be the same. The gate outcome would be `suppress` with the reason `dry_run`, and `would_send` would list left 30 and right 30: the record of what the integration would have done.
