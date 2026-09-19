# Roller Shutter Suite for Home Assistant — Project Brief

| | |
|---|---|
| Status | Draft 2 — definition phase, no code written yet |
| Date | 2026-09-19 |
| Name / repository | `ha-roller-shutter-suite`, integration domain `roller_shutter_suite` (confirmed after the collision check, see [section 6](#repository-and-documentation)) |
| Minimum Home Assistant version | 2026.9 |
| License | MIT |
| Next step | Domain design specification (work block D00 in `TASKS.md`), which refines this brief where it says so |
| Audience | Implementing agents and maintainers. Instance-specific details of the first installation live in `docs-internal/` and are not part of the public repository. |

How to read the source markers: **[BP]** is the Simon42 blueprint documentation, **[#n]** an issue or pull request in the same repository, **[HA-DEV]** the Home Assistant developer documentation, **[HA-SRC]** the Home Assistant Core source code at tag 2026.9.2, **[OWN]** experience from the project owner's existing installation. Statements without a marker are decisions taken by the project owner during the definition session on 2026-09-19 or in the planning review of the same day; "planning review" in a source column refers to the latter. A statement marked **(unverified)** comes from research that was not checked against a primary source; it must be verified by the work block that relies on it. All sources are listed in [section 10](#10-sources).

---

## 1. Motivation

1. The current shutter control runs as time programs on a Homematic CCU3. It is not flexible enough, the CCU3 is no longer being developed further, and its successor requires a cloud connection. Apart from heating (a slow system that is excluded for now) the CCU shall no longer execute any control logic; everything converges in Home Assistant.
2. Several Home Assistant automations already move shutters (sun shading, rain, storm and hail protection, alarm clock). They collide with the CCU programs because neither side knows about the other.
3. Once a certain complexity is reached, an integration with a clean architecture is easier to maintain, test and reason about than a set of interdependent blueprints, automations and scripts.
4. The trigger for the project was the "Intelligente Rollladensteuerung" blueprint by Simon42 [BP]. Its feature set and the wishes of its users [#1–#26] were used as the starting catalog.
5. Configuration has to happen per window, and windows have to be addable one at a time: the house is under core renovation and rooms become available in stages.

## 2. Goals

- **G1 — Single authority.** One integration decides the position of every managed shutter. No CCU program, Node-RED flow or automation moves a managed shutter on its own; external automations request movements through the integration's actions.
- **G2 — Per-window configuration with inheritance.** Defaults flow from global to group (façade, floor, room type) to window. Adding a window means choosing the cover, a group and the window measurements.
- **G3 — Incremental rollout.** Windows can be added, put into dry-run, armed and removed individually without affecting the others.
- **G4 — Deterministic, explainable decisions.** A fixed priority model resolves competing wishes. For every window the integration exposes why it is where it is and what will happen next.
- **G5 — Restart-safe and failure-aware.** The target state is a function of the current situation, not of missed triggers. Unavailable data never counts as "all clear".
- **G6 — Hardware- and source-neutral.** Any `cover` entity, any sensor source. No assumption about Homematic, DWD, a PV system or the first installation may end up in code.
- **G7 — Publishable.** Developed privately first, but HACS-ready from the first commit: English code and documentation, English and German UI translations, public documentation that assumes no knowledge beyond operating Home Assistant, no secrets or instance data in the repository.
- **G8 — Future-proof API usage.** Only current Home Assistant APIs (config subentries, reconfigure flows, sections, repairs, diagnostics); no deprecated patterns.

## 3. Non-goals

- Heating control and ventilation advice (#15). Window monitoring in general (open-window reminders, [BP] notifications).
- Light control. The blueprint's "mosquito mode" is out of scope; the integration only emits an event other automations can use.
- Built-in notification delivery. The integration fires events and writes logbook entries; pushes are built by user automations.
- Built-in evaluation of specific weather services (DWD, MeteoSwiss, wind thresholds). Protection events accept generic trigger entities instead.
- Proxy `cover` entities. Existing dashboards keep using the original entities.
- Slat/tilt control for venetian blinds in the first version (kept open in the domain model, see C15).
- A custom dashboard card (not even in the outlook for now).
- Programming in the definition phase. This document defines; `TASKS.md` plans; agents implement.

## 4. Feature catalog

Status values: **Will be implemented** · **Not yet** (considered, deferred) · **Will not be implemented**.

Totals: 59 will be implemented, 8 not yet, 6 will not be implemented.

### A — Daily routine

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| A1 | Morning opening | Drive to a target position at a fixed time, only if the shutter is lower than the target. | Will be implemented | [BP] |
| A2 | Astro times | Sunrise, sunset or sun elevation as trigger, clamped by "not before" and "not after". | Will be implemented | [#1], [#10] |
| A3 | Day types | Separate times for workday, weekend and public holiday. School holidays are a later extension. | Will be implemented | [#10], [#23] |
| A4 | Evening closing | Triggered by time, sun elevation or an optional outdoor brightness source. | Will be implemented | [#5], [#6] item 5, [#14] |
| A5 | Seasonal evening position | For example 30 % for privacy in summer, fully closed in winter. | Will be implemented | [#6] item 5 |
| A6 | Evening moves downward only | A shutter already lower than the evening or night position is never raised by it. | Will be implemented | [#6] item 4 |
| A7 | Conditional morning opening | Open only once a condition holds (motion, somebody awake), with a mandatory latest time. The architecture must already allow a condition input. | Not yet | [#6] item 6, [#25] |
| A8 | Calendar confirmation before opening | Actionable push instead of automatic opening on days with an all-day event. Can be built with pause (E4) plus a user automation. | Will not be implemented | [#21] |
| A9 | Sleep / night mode | Switch, global and per window or room. Closes, blocks shading and solar heating, replaces fixed night time windows. | Will be implemented | [BP], [#12] |
| A10 | Presence-dependent night position | Partially closed when somebody is home. | Will not be implemented | [#12] |
| A11 | Alarm clock coupling | Not a built-in feature: alarm automations call the integration's action (F1) so priorities and locks stay central. | Will be implemented (as interface) | [OWN] |
| A12 | Frost protection | At frost do not drive, or only to about 90 %, to avoid tearing a frozen curtain. Temperature source freely selectable. By default it limits comfort movements only; whether it also limits protection movements is configurable. Fire (D3) always ignores it. | Will be implemented | [#24] |

### B — Window interaction

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| B1 | Ventilation position | Tilted or open window drives the shutter to a ventilation or open position and back after closing. Supports two- and three-state sensors. Not counted as manual operation. | Will be implemented | [BP] |
| B2 | Lockout protection | An open door (terrace, balcony, insect screen door with its own contact) blocks every closing movement, including evening, night and storm. Closing is caught up once the door is shut. Several blocking contacts per window. | Will be implemented | [BP], [#3] |
| B3 | Window contact optional | Windows without a contact work; contact-dependent features are simply inactive. | Will be implemented | [#11], [#14] |
| B4 | Rain protection while ventilating | Window open and rain for X minutes: close to Y %, return Z minutes after the rain ends. Rain source freely selectable. | Will be implemented | [#20] |
| B5 | Mosquito mode | Switch room lights off when a window is opened after sunset. Light control is outside the integration's responsibility. | Will not be implemented | [BP] |
| B6 | Open-window notification | Push with a "close shutter" button. Window monitoring is a separate concern. | Will not be implemented | [BP] |
| B7 | Ventilation recommendation | Out of scope; requested as a separate blueprint in the issue itself. | Will not be implemented | [#15] |
| B8 | Night cooling | Separate logic for hot nights. Covered sufficiently by B1 and B9. | Will not be implemented | [#6] item 11 |
| B9 | Evening closing respects an open window | With a tilted or open window the evening or night closing stops at the ventilation position; the full closing is caught up when the window is closed. A reason event (E8) makes the deviation visible early. Solves a problem of the current installation, where a window opened for cooling is silently shut in at dusk. | Will be implemented | [BP] night mode, project owner |

### C — Shading

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| C1 | Geometric shading | Per window: orientation, field of view left and right, glass top and sill height, maximum sun penetration depth. Position is recalculated cyclically. The more obliquely the sun strikes the façade (azimuth far from the window normal), the higher the shutter stays; this follows from the geometry and is not a separate rule. The amplification is capped as the sun approaches the façade plane. Additional simple mode with a fixed shading position for windows without measurements. | Will be implemented | [BP] |
| C2 | Glass calibration | Two values per window (seating point, upper glass end) correct the difference between motor percentage and free glass area. Optional, with sensible defaults. | Will be implemented | [BP] |
| C3 | Temperature threshold | One outdoor threshold with hysteresis. | Will be implemented | [BP] |
| C3b | Multi-stage thresholds | Warm, hot and extreme tiers with their own minimum shading. | Not yet | [#6] item 9 |
| C4 | Forecast daily maximum | Until mid-afternoon the forecast daily high counts instead of the current temperature, so hot days are shaded early. Uses `weather.get_forecasts`. | Will be implemented | [#6] item 8 |
| C5 | Radiation signal | Freely selectable source (lux, PV power, irradiance) with threshold and asymmetric delays: shade quickly, reopen slowly. | Will be implemented | [#6] item 7, [#17], [#26], [OWN] |
| C6 | Weather condition filter | No shading in overcast or rainy conditions; resume only after a stable improvement (blueprint: 10 minutes). Fallback for users without a radiation sensor. | Will be implemented | [BP] |
| C7 | Elevation limits | Shading ends below a configurable sun elevation; a minimum elevation for the start covers horizon obstruction. | Will be implemented | [#6] item 10 |
| C8 | Solar heating | Below a temperature threshold (blueprint default 12 °C) a still closed shutter is opened once per episode when the sun is in the field of view. Strictly respects sleep mode. | Will be implemented | [BP] |
| C9 | External shading enable | Any entity enables or disables shading only, global and per window. Protection keeps running. | Will be implemented | [#16], [OWN] |
| C10 | Dependency on other shading | Suppress shading while another entity is in a given state, for example an extended awning. | Not yet | [#7], [#12] |
| C11 | Glare protection position | Second shading profile without temperature condition. Makes sense together with C3b. | Not yet | [#14] |
| C12 | Indoor temperature condition | Shade only, or earlier, when the room is already warm. Must accept an entity **or an attribute** as source. | Will be implemented | project owner, [OWN] |
| C13 | Heat self-protection of the curtain | Raise PVC curtains at extreme temperatures. Fits the protection event scheme (D1) and can be added there. | Not yet | [#13] |
| C14 | Rain ends shading | Persistent rain ends the shading episode and starts a lock time against oscillation. | Will be implemented | [OWN] |
| C15 | Venetian blinds / tilt | Slat tracking is its own domain logic and cannot be tested without hardware. The domain model shall carry a "covering type" so it can be added without restructuring. | Not yet | [#8] |

### D — Protection

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| D1 | Generic protection events | A protection event has a freely selectable trigger (binary, list of states, or number with threshold), a target direction and a rank. Storm is the first instance. Evaluation of weather services stays outside in template sensors. | Will be implemented | [BP], [#18], [OWN] |
| D2 | Hail protection | A further protection event. Direction configurable per event; never an intermediate position. | Will be implemented | [#9], [OWN] |
| D3 | Fire alarm | Smoke detector triggers: all shutters open (escape routes). Overrides sleep exceptions, pauses, staggering, motor protection, frost protection, the manual override and every operating mode including "off". Only two things stop the movement: the maintenance lock (E4) and dry-run (E11). In both cases the fire event is still fired immediately so the situation never goes unnoticed. **No automatic return** after the alarm ends; a human decides. | Will be implemented | [#4] |
| D4 | Sleep-room exception | Per window: "protection event X must not open while sleep mode is active". Fire always ignores the exception. | Will be implemented | [OWN] |
| D5 | State-based return after protection | After the event ends (plus waiting time) the integration recomputes what applies **now**; only manually set positions are restored one to one. Remembered positions are persisted; unknown positions are skipped. | Will be implemented | [OWN] |
| D6 | Robust protection logic | A running event is detected and caught up after a restart. `unavailable` and `unknown` are neither a warning nor an all-clear: they do not trigger and do not release. | Will be implemented | [#18], [OWN] |
| D7 | Absence / vacation profile | Presence simulation or deviating times and positions during longer absence. The first version only delivers random time offsets (E13). | Not yet | [#2] |
| D8 | Alarm system coupling | No separate feature; any entity can trigger a "close" protection event through D1. | Will be implemented (covered by D1) | project owner |
| D9 | Watchdog | A protection event or lock that lasts implausibly long is released and reported as a Home Assistant repair issue. Maximum duration per event configurable. Does not apply to fire (D3). What "released" means while the trigger is genuinely still active, and how that fits D6, is defined in the domain design specification. | Will be implemented | [OWN] |

### E — Override, operation, diagnostics

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| E1 | Manual operation detection | A position change outside a tolerance band that was not caused by the integration makes the comfort logic leave the window alone. Protection events ignore the override. "Not caused by the integration" is decided by an expectation window (commanded target, tolerance, travel time, `opening`/`closing` state), not by the Home Assistant context; see guardrail 6. A movement the integration commanded itself, from whatever layer, never arms the override. | Will be implemented | [BP] |
| E2 | Override duration | Selectable: fixed minutes, until the shading episode ends, or until the next part of the day (default). Additionally, with an optional presence sensor: ends after the room has been empty for X minutes. A "resume automation" button ends it immediately. | Will be implemented | [#6] item 2, [#16], project owner |
| E3 | Grace period after own movement | Position reports during and shortly after a self-initiated movement do not count as manual. Travel time configurable per window; the cover's `opening`/`closing` state is used where available. This is the primary mechanism of E1 (guardrail 6). It must also hold for covers that never report `opening`/`closing`, that report their final position late, or that settle a few percent away from the commanded position. | Will be implemented | [#6] item 3 |
| E4 | Pause and maintenance lock | Pause per window, per group and global as switch entities plus optional external pause entities; protection keeps running. After a pause the target state is recomputed instead of replaying missed events. A separate **maintenance lock** also suppresses protection movements (scaffolding, open shutter box). The maintenance lock is the only state in which nothing moves at all; it also wins against fire, because the risk of injury comes first. | Will be implemented | [BP], [#19] |
| E5 | Priority model | Central architectural principle, see [section 5](#5-architectural-guardrails). It consists of layers, constraints and a gate instead of a single ladder (guardrails 1 and 2). | Will be implemented | [BP] |
| E6 | Restart recovery | Episodes, overrides, remembered positions and locks are persistent. After start the target state is recomputed and missed daily events are caught up. | Will be implemented | [#6] item 1 |
| E7 | Status entities | Per window: active reason (enum), override active, next planned action, computed target position; plus diagnostics download. | Will be implemented | [#16] |
| E8 | Reason events | When an action is skipped or blocked, the integration fires an event and writes a logbook entry with the reason. Push delivery is left to user automations. | Will be implemented | [#6] item 12 |
| E9 | Operating mode | Select entity per window and global: automatic, protection only, off. "Protection only" means no comfort movements. "Off" means no comfort movements and no weather protection; fire (D3) still opens. "Nothing moves at all" exists only as the maintenance lock (E4), so the four states have clearly distinct meanings. | Will be implemented | [#14] |
| E9b | Named profiles | Freely definable profiles such as "Christmas". | Not yet | [#14] |
| E10 | Motor protection | Minimum change (blueprint: below 5 % no movement) and minimum interval between comfort movements. Does not apply to protection movements. | Will be implemented | [BP] |
| E11 | Dry-run | Per window the integration decides and logs but does not move. Enables side-by-side migration on a productive system. Dry-run never moves anything, not even at fire (D3): it only records what it would have done. During side-by-side migration the old system still controls the same window, and two controllers must never act on it (section 6). | Will be implemented | project owner |
| E12 | Inheritance | Global to group to window; a window only overrides what differs. | Will be implemented | project owner |
| E13 | Staggered and randomized movements | Collective movements run with a short gap per motor; optional random offset for schedules. Fire alarm is never staggered. | Will be implemented | [#2], project owner |

### F — Added during the session

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| F1 | Actions for automations | Public actions such as "request position with reason", "clear override", "recompute target state". Basis for A11 and for scenes. | Will be implemented | project owner |
| F2 | Privacy when lights are on | Dark outside and light on in the room: drive to a privacy position, also before the evening time. | Will be implemented | project owner |
| F3 | Roof window profile | Own window type: geometry via roof pitch, rain closes instead of opens, more aggressive heat protection. | Will be implemented | project owner |
| F4 | Progressive configuration | Feature switches first, then only the steps of enabled features; expert values in collapsed sections; most values inherited. Replaces a "basic/advanced" split, because Home Assistant's advanced mode is being removed. | Will be implemented | [HA-DEV-ADV] |
| F5 | Wall button integration | Per shutter or group: up, down, hold-to-move with stop on release, press during movement stops, optional special functions such as double press to 50 %. Which functions are offered depends on the detected capabilities of cover and button (F7). Hybrid approach, see guardrail 7. | Will be implemented | project owner |
| F6 | Tamper contact | Optional per window or door. When tampering is reported, the "open" signal is no longer trusted: lockout protection (B2) does not block, protection and evening movements run, and an event is fired. A push is optional so it does not collide with an alarm system. | Will be implemented | project owner |
| F7 | Capability-aware configuration | During setup and reconfiguration the integration inspects what each selected entity can actually do: cover (stop, set position, tilt), button (available event types such as long-press release), contact (two- or three-state). Options that cannot work with the selected hardware are not offered, or are shown disabled, **always with a plain-language reason** (for example: "This cover cannot be stopped, so hold-to-move and stop-on-press are unavailable"). If capabilities change later (entity replaced, integration update), a repair issue names the affected window and option. | Will be implemented | project owner |

### N — Added after the planning review

Pieces a working integration needs beyond the feature wishes above.

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| N1 | Command verification | After a movement command the integration checks that the cover reacted and arrived. A command without effect (cover unavailable, radio contact lost) is retried with backoff and, if it keeps failing, reported as a repair issue and a reason event. A cover that settles slightly off the commanded position must not cause a command loop. | Will be implemented | planning review, related work |
| N2 | Covers without position feedback | A cover that reports no position or does not support `set_position` is supported in a degraded mode (open and close only), not rejected. Features that need a position (shading, intermediate positions, manual operation detection) are inactive for it, and F7 explains this in plain language. | Will be implemented | planning review, project owner |
| N3 | Window and cover cardinality | A window has exactly one cover; that cover may be a Home Assistant cover group. A cover belongs to at most one window; configuration validates this and explains a conflict. | Will be implemented | planning review, project owner |
| N4 | Removing windows and groups | Removing a window deletes its device, entities and persisted state (episodes, overrides, remembered positions). Removing a group that windows still reference is either prevented or handled with a defined fallback; no orphaned references remain. | Will be implemented | planning review |
| N5 | Configuration and storage versioning | Config entry data, subentry data and the integration's own storage carry a version from the first release and have a tested migration path, so an update never loses configuration or persisted state. | Will be implemented | planning review |
| N6 | Time-lapse simulation | The domain core can be run against a synthetic world (sun, weather, contacts, cover travel time, connectivity dropouts) for a whole day or year in seconds. It is a deliverable of its own and doubles as the scenario test harness of the core (guardrail 4). | Will be implemented | planning review, guardrail 4 |

## 5. Architectural guardrails

These are decisions and constraints, not a design. The design is part of the implementation phase.

1. **One arbiter instead of competing rules, in three stages.** One arbiter per window decides; no feature moves a cover on its own. A single priority ladder with one winner is not enough: several rules are not position wishes at all (lockout protection only blocks closing, frost only limits travel, the maintenance lock forbids movement), and the sleep-room exception (D4) would let a lower entry beat a higher one. The arbiter therefore has three stages:
   - **Layers** answer "where should this window be?". Each layer returns a target position, "leave alone", or no opinion, always with a machine-readable reason. Layers are evaluated in a fixed order and the first opinion wins. Unknown or unavailable input never becomes a guess: it yields "leave alone" or no opinion, as defined per input (guardrail 8).
   - **Constraints** limit the winning wish without replacing it: lockout protection (B2, void while tamper is active, F6), evening moves downward only (A6), frost protection (A12), no intermediate position during storm (section 6), the sleep-room exception (D4).
   - **The gate** answers "may the integration move now?": maintenance lock, operating mode, pause, dry-run (E11), manual override, a movement already in flight, motor protection (E10), staggering (E13), command backoff (N1). The gate sends, defers until a point in time, or suppresses, always with a reason.

   The target state is always derivable from the current situation. This makes restart recovery (E6), pause end (E4) and return after protection (D5) the same operation: recompute.
2. **Decided rules of the arbiter.** The exact layer order, the list of constraints and gate rules, and the reason codes are defined in the domain design specification (work block D00) and approved by the project owner. These rules are fixed:
   - The **maintenance lock** wins against everything, including fire: scaffolding or an open shutter box mean a risk of injury. It is the only state in which nothing moves at all. A fire alarm during a maintenance lock still fires its event immediately.
   - **Fire** (D3) comes next. It must be able to bypass the gate rules that would delay or stop it: staggering, motor protection, the manual override, pause and every operating mode. This bypass has to be an explicit, named part of the design, not a special case that emerges in code. Fire also ignores frost protection and the sleep-room exception. Fire does **not** bypass the maintenance lock and does **not** bypass dry-run (E11): a window in dry-run never moves, it only records what would have happened.
   - The **manual override** (E1, E2) is not a layer. It is a gate rule that holds the comfort layers back (a "dam") while protection layers pass. This makes special cases such as "protection ignores the override" or "ventilation does not count as manual" unnecessary.
   - **"A person at the window wins" (guardrail 3) needs a second, time-limited dam.** The override dam lets protection layers pass, but a person at the window shall win against storm and hail for a limited time. This second dam also holds protection layers back, ends by itself after the configured time, and never holds back fire. How the two dams relate (what arms each, whether one can turn into the other, what happens when the time-limited dam ends while the override is still active) is defined in D00.
   - **Operating modes** have four distinct meanings: automatic; protection only (no comfort movements); off (no comfort movements and no weather protection, fire still opens); maintenance lock (nothing moves).
   - **Relative order of the layers** as the starting point for D00 (highest first): fire → local manual operation during a protection event (time-limited, guardrail 3) → hail → storm and other protection events by rank → sleep / night mode → window interaction (B1, B4, B9) → privacy (F2) → shading and solar heating → schedule. Maintenance lock, lockout protection, operating mode, pause and the manual override are not part of this order; they are gate rules or constraints as described above.
3. **A person at the window wins, for a limited time.** A wall button always moves the shutter, even during storm or hail. After a configurable time (default 15 minutes) the protection event reasserts itself and a reason event is fired. In the arbiter this is the time-limited dam of guardrail 2; fire is never held back by it.
4. **Pure domain core.** Geometry, episodes, priorities and override handling are plain Python without Home Assistant imports, so they can be unit-tested and run in a time-lapse simulation of a whole day or year. The Home Assistant layer only adapts entities, time and storage.
5. **Configuration structure.** One config entry for the house (global sources, defaults, protection events); groups and windows as config subentries, each window with its own device. Reconfigure flows instead of delete-and-recreate. Same structural pattern as the owner's `room_presence` integration. Two limits apply. Subentries are a flat list and a device belongs to at most one subentry (section 6), so a window refers to its group by the group's subentry ID stored in the window's own data; groups own no window devices. And the reference integration predates some current APIs (it still builds its schemas with `voluptuous`), so it is a model for structure, not for API usage; section 6 is binding for the latter.
6. **Manual operation detection by expectation, not by context.** The Home Assistant context cannot tell own, user and hardware movements apart reliably and is therefore not the primary mechanism. Home Assistant keeps the context of a service call on the target entity for only five seconds (`CONTEXT_RECENT_TIME_SECONDS = 5` [HA-SRC-CTX]); every later state write gets a fresh context without user and without parent. The final position report of a shutter that travels 20 to 60 seconds therefore looks exactly like a press on a wall button, and a button press within five seconds of an own command inherits the integration's context. Cover platforms that debounce their updates longer than that never deliver the context at all (unverified). The rule is therefore: the expectation window of E3 decides (commanded target, tolerance, a grace period proportional to the travel, `opening`/`closing` where the platform reports it). The context may raise confidence (a user ID proves a dashboard action), but it never decides alone, and its absence proves nothing. What each cover platform actually reports (latency, settling time, deviation from the commanded position, transit states) is measured in a spike before E1 is built.
7. **Buttons: hybrid.** Where the hardware supports a local link between button and actuator, up/down/stop stay local and work without Home Assistant; the integration sees the resulting movement as manual operation and only adds special functions. A full Home Assistant path exists for buttons without a local link and for rooms that only have a wall display. Not every user has a CCU or a comparable system.
8. **Sources are inputs, never assumptions.** Every sensor input is optional, accepts an entity or an entity attribute where that is common in practice, and has a defined behavior when unavailable.
9. **Configuration UX is settled: progressive configuration with sections (F4).** Feature switches first, steps only for enabled features, expert values in collapsed `section`s, everything else inherited. There is no "basic/advanced" mode and no use of `show_advanced_options` [HA-DEV-ADV]. Decided by the project owner on 2026-09-19; not an open point.
10. **Capabilities are detected, never assumed (F7).** What a cover, button or contact can do is read from the entity at configuration time. Options that cannot work are not silently accepted and do not fail silently at runtime.
11. **Position convention.** 100 % is fully open, 0 % fully closed, as in Home Assistant and [BP]. Glass calibration (C2) applies to shading calculations only.

## 6. Things that must be observed during implementation

### Safety and behavior

- Fire opens everything, immediately and unstaggered, and never returns automatically (D3). The only exceptions are a window under maintenance lock and a window in dry-run (E11), which do not move; the fire event is fired regardless.
- Never an intermediate position during storm: a half-lowered shutter offers the wind a surface and can be torn out of its guide rails [OWN]. Whether hail means "up" or "down" is disputed between glass and curtain types, so the direction is configurable per event (D2).
- An open door blocks closing even during storm, so nobody is locked out in bad weather; with an active tamper contact this trust is withdrawn (B2, F6).
- Missing data is not good news. `unavailable` and `unknown` must never be evaluated as "no warning", "no rain" or "window closed" (D6) [OWN].
- One controller per window at any time. During migration a window is either still controlled by its old program or by the integration, never both. Dry-run (E11) exists for the overlap.
- Order of change matters on a live system: first change the consumers (triggers), then the data source. The reverse order produced a false storm notification in the owner's installation on 2026-09-17 [OWN].

### Home Assistant specifics

- Restored entities carry the restart time as `last_changed`, and a `for:` duration on a state trigger never starts after a restart because a restore is not a state change. Durations must be tracked with own timestamps [OWN].
- After start, wait until the managed covers are available before computing or moving. Bus and radio integrations need time, and late position feedback is normal (E3).
- Cover capabilities differ. Check `supported_features` per cover: some covers offer no STOP (for example roof window shutters connected through HomeKit), so hold-to-move and stop-on-press (F5) are impossible there. Some report no position at all. This must be detected and explained during configuration (F7), not discovered at runtime.
- Button hardware usually delivers `press_short`, `press_long_start`, `press_long` and `press_long_release` as event entity types, but no native double press. Double press has to be detected by timing inside the integration, which adds latency to the single press; this trade-off must be configurable (F5). Since 2026-07 Home Assistant also defines standard event types for button event entities (`ButtonEventType`: `PRESS_START`, `PRESS_END`, `LONG_PRESS_START`, `LONG_PRESS_END`, `MULTI_PRESS_ONGOING`, `MULTI_PRESS_END`, the last two with a `multi_press_count` attribute) [HA-DEV-BTN]. F5 and F7 must map both the standard types and vendor-specific types; where a button reports multi press natively, the integration's own timing detection is not needed.
- Some thermostats expose temperature only as an attribute of a `climate` entity (C12).
- `FlowHandler.show_advanced_options` is deprecated since 2026-05-26 and will be removed in Home Assistant Core 2027.6; the recommended replacement is grouping additional options in sections [HA-DEV-ADV]. F4 follows this.
- Use current APIs only: config subentries, reconfigure, sections, repairs, diagnostics, translation keys for every user-facing string. Before each rollout check the developer blog for breaking changes since the tested version [HA-DEV-BLOG].
- Labels, areas and naming conventions of an installation are not an API. The integration works on explicitly configured entities.

Each of the following items was checked against the named primary source on 2026-09-19 unless it is marked unverified:

- **Schemas are written with `probatio`, not `voluptuous`.** Home Assistant Core 2026.9.2 depends on `probatio` and no longer lists `voluptuous` [HA-SRC-DEPS]; the developer documentation uses `import probatio` in its examples [HA-DEV-FLOW]; on the development branch importing `voluptuous` is banned by lint with the message "use probatio instead". No developer blog post announces the change. That `import voluptuous` keeps working through a compatibility shim, and for how long, is unverified; the scaffolding block checks the installed version before anything is built on it.
- **Python 3.14.2 or newer** is required (`requires-python = ">=3.14.2"` [HA-SRC-DEPS]), not just 3.14.
- **A device belongs to one config entry and to at most one config subentry** (Home Assistant 2026.8, deprecated behavior supported until 2027.8) [HA-DEV-DEVREG]. There is no hierarchy between subentries; see guardrail 5. Follow-up deprecations in the device registry (`DeviceEntry.config_entries`, `async_get_device`, `via_device`) were announced on 2026-08-24 and 2026-09-15 and are partly enforced already (unverified in detail; the block that creates devices checks them).
- **A config entry update listener combined with a reloading flow method is deprecated** since 2026.6 and becomes an error in 2026.12 [HA-DEV-RELOAD]. Use one or the other: either no update listener and `async_update_reload_and_abort()`, or an update listener with `async_update_and_abort()`. This affects every reconfigure flow of guardrail 5.
- **Sections cannot be nested**: "Only a single level of sections is allowed" [HA-DEV-FLOW]. The input of a section arrives nested under the section key. F4 has to be designed within this limit.
- **Brand images ship inside the integration** since 2026.3: a `brand/` folder next to `manifest.json` with at least `icon.png` [HA-DEV-BRANDS]. No pull request to the Home Assistant brands repository is needed. That the HACS validation requires this folder is unverified.
- **Sun position.** `homeassistant.helpers.sun.get_astral_location` is deprecated and breaks in 2027.7; `get_astral_observer` is current [HA-SRC-SUN]. Home Assistant has no helper that returns azimuth and elevation for an arbitrary point in time. The `astral` library is a Core dependency and plain Python, so the domain core may use it without violating guardrail 4, and the time-lapse simulation (N6) needs it for exactly that reason.
- **Not verifiable on 2026-09-19** and therefore to be checked by the block that needs it: the logbook platform API for custom event descriptions (the documentation page returned 404), the exact signatures for updating a subentry, whether subentry flows officially support several steps and sections, how deprecation messages that Home Assistant logs instead of raising as warnings can be turned into test failures, and the removal of the legacy `forecast` attribute of weather entities (C4 uses the `weather.get_forecasts` action either way).

### Quality

- The Integration Quality Scale is used as a checklist: Silver rules are binding, Gold rules where sensible (diagnostics, reconfiguration via the UI, fully translatable entities) [HA-DEV-IQS]. Custom integrations are not formally graded on the scale; it serves as a guideline only.
- Tests with `pytest-homeassistant-custom-component` against the current Home Assistant version (2026.9.2 at the time of writing), deprecation warnings treated as errors. Python 3.14 via `uv` is required for current Home Assistant versions (precisely: 3.14.2 or newer, see above); `asyncio_mode = "auto"` [OWN].
- CI additionally enforces two rules mechanically: the domain core imports nothing from `homeassistant` (guardrail 4), and no tracked file contains instance data (section "Repository and documentation").
- `hassfest` and the HACS validation action run in CI from the first commit, even while the repository is private.
- Code rules: English, documented, clean code, readable names. The owner is a software engineer and will read and adjust the code.

### Repository and documentation

- The content of the project folder becomes the repository. Proposed layout: `custom_components/<domain>/`, `tests/`, `docs/` (public), `docs-internal/` (git-ignored), `TASKS.md` with one file per work block in `tasks/`, `README.md`, `hacs.json`, `.github/workflows/`.
- Public documentation: no secrets, no instance data, worked examples, plain language, no background knowledge assumed beyond operating Home Assistant. A dedicated writing skill for this tone can be created later; none exists yet. Public documentation is English only; German exists in the UI translations, where parity between English and German is mandatory.
- Internal documentation: entity IDs, migration plan and decisions specific to the first installation.
- Before the repository is created, check the name and the domain for collisions with Home Assistant Core, the HACS default list and existing projects. A web search on 2026-09-19 found no project named "roller shutter suite"; it did find projects with overlapping purpose, see related work. The search was not exhaustive. A second check found no Home Assistant Core integration, no entry of the HACS default list and no GitHub code search hit that uses the domain `roller_shutter_suite` or the name (unverified). Name and domain are confirmed. The license is MIT.

## 7. Related work

To be evaluated at the start of implementation for ideas, terminology and pitfalls, not as dependencies:

- Simon42 "Intelligente Rollladensteuerung" blueprint [BP] — the feature baseline of this brief. One automation instance per window, helpers for state, exactly one mandatory window contact.
- [`basbruss/adaptive-cover`](https://github.com/basbruss/adaptive-cover) — HACS integration that controls covers based on the sun's position. Found by web search, not reviewed in this session.
- [`jrhubott/adaptive-cover-pro`](https://github.com/jrhubott/adaptive-cover-pro) — fork describing itself as sun-tracking control for blinds, awnings and venetian tilts "with climate-aware positioning and a priority override pipeline". Closest to guardrail 1; should be reviewed first. Not reviewed in this session.
- [`refael302/hai-shutter-manager`](https://github.com/refael302/hai-shutter-manager) and [`pujux/hass-cover-automation`](https://github.com/pujux/hass-cover-automation) — smaller integrations with overlapping purpose (sun, season, weather, frost, door sensors, schedules). Found by web search, not reviewed.

The decision for an own integration stands (section 1, items 3 and 5; none of the above was chosen as a base), but the review may show that parts of the geometry or the override pipeline are solved problems.

**Result of a first look** (details unverified, to be re-read by the blocks that use them):

- Nothing found argues against the architecture. Two of the projects arrived independently at what guardrail 1 now describes: `adaptive-cover-pro` at handlers with priorities that also report why they did not act, `hass-cover-automation` at a Home-Assistant-free engine with layers, a separate gate, a "leave alone" outcome, stable reason codes, config subentries and a day-replay test harness. The latter only opens and closes and has no geometry.
- The most valuable material is the list of pitfalls in manual operation detection that `adaptive-cover-pro` documents: covers that never report `opening`/`closing`, a final position that arrives tens of seconds late, covers that settle one percent off and cause command loops, and protection inputs that silently drop protection when their sensor becomes unavailable. These become acceptance criteria of E1, E3, N1 and D6.
- `adaptive-cover-pro` is also a warning about scope: within eight months it grew to several megabytes of Python. Non-goals (section 3) are to be defended.
- Geometry: the core of the blueprint's calculation is elementary trigonometry that `adaptive-cover` contains as well. The blueprint adds the sill height, a cap on the amplification at oblique sun and the two-point glass calibration (C2). The calibration has to be applied in both directions, to the command and to the position read back, or E1 compares two different scales.
- Licenses: the four integrations are MIT licensed; the blueprint repository has no license. Ideas and formulas may be used; no code, template or text is copied from the blueprint. The recommendation is to copy no code at all.

## 8. Outlook

Without commitment:

- **Self-calibration and learning.** Propose travel times, glass calibration and radiation thresholds from observation instead of asking the user to measure them.
- **LLM-assisted setup.** An assistant that derives geometry and groups from a description or floor plan.
- The deferred features A7, C3b, C10, C11, C13, C15, D7 and E9b.
- Submission to the HACS default list once the integration has proven itself in the first installation.

## 9. Open points

To be settled by the domain design specification (work block D00) as a reasoned proposal that the project owner approves:

1. Final layer order and the complete list of constraints and gate rules, including the explicit fire bypass and its two exceptions, maintenance lock and dry-run (guardrail 2).
2. The two dams of the gate: the manual override dam, which lets protection pass, and the time-limited "person at the window" dam, which also holds protection back but never fire (guardrails 2 and 3). What arms each, how they relate and how they end; also whether a wall button on the full Home Assistant path (guardrail 7) is refused during a maintenance lock, given that a locally linked button cannot be stopped by the integration anyway.
3. Detailed catch-up rules: which missed daily events are caught up after a restart or pause, and until when. Direction: state-based, in line with guardrail 1. The schedule defines a target state per part of the day and nothing is replayed; only one-time actions such as C8 need an expiry.
4. Definitions of "episode" (C8, C14, E2) and "part of the day" (E2), and the source of the season for A5.
5. Watchdog (D9): what "released" means while the trigger is genuinely still active, without contradicting D6.
6. Interaction of D5 and E2: whether the override duration keeps running during a protection event, and what is restored if it expires meanwhile.
7. Inputs of F2: which lights count for a window, and what "dark outside" is derived from.
8. Remaining vague wording: "until mid-afternoon" (C4), "more aggressive heat protection" (F3), gap and random offset of E13, default durations of D9.
9. Day types (A3): the source is one or more entities chosen by the user (for example a workday sensor or a calendar); the integration does not bring its own holiday data. How these entities map to workday, weekend and public holiday is part of D00.

Open beyond D00:

10. School holidays as a day type (A3): calendar entity or dedicated source. Not part of the first version.

## 10. Sources

- **[BP]** Simon42, *Intelligente Rollladensteuerung (cover_automation_v2)*, documentation: <https://github.com/TheRealSimon42/ha-blueprints/blob/main/docs/cover_automation_v2.md>
- **[#n]** Issues and pull requests of the same repository, read individually on 2026-09-19: <https://github.com/TheRealSimon42/ha-blueprints/issues>. At that date the repository had 22 issues (all open, none answered by the maintainer) and 4 pull requests (#18, #19, #22, #23). Referenced here: #1 sunrise/sunset, #2 vacation mode, #3 insect screen door, #4 smoke detector, #5 brightness-based closing, #6 twelve suggestions from practice (restart, manual override, evening, shading), #7 presence condition and awning, #8 venetian blinds, #9 hail protection, #10 weekend and astro times, #11 optional window sensor, #12 ideas, #13 heat self-protection, #14 intermediate position and mode select, #15 ventilation recommendation, #16 external shading enable and override timeout, #17 PV-based shading, #18 storm protection hardening (PR), #19 pause helper consistency (PR), #20 rain protection while ventilating, #21 calendar confirmation, #23 weekend opening time (PR), #24 frost protection, #25 motion-based opening, #26 light sensor.
- **[HA-DEV-ADV]** Home Assistant Developer Docs, *Deprecation of advanced mode in data entry flow*, 2026-05-26: <https://developers.home-assistant.io/blog/2026/05/26/advanced-mode-config-flow-deprecation/>
- **[HA-DEV-BLOG]** Home Assistant developer blog: <https://developers.home-assistant.io/blog>
- **[HA-DEV-FLOW]** Home Assistant Developer Docs, *Data entry flow* (sections, schema examples): <https://developers.home-assistant.io/docs/data_entry_flow_index/>
- **[HA-DEV-DEVREG]** Developer blog, *Devices are restricted to a single config entry and at most one subentry*, 2026-07-21: <https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/>
- **[HA-DEV-RELOAD]** Developer blog, *Deprecating config entry listener with reloading methods in config flow*, 2026-05-07: <https://developers.home-assistant.io/blog/2026/05/07/config-entry-listener-together-with-reloading-methods>
- **[HA-DEV-BRANDS]** Developer blog, *Custom integrations can now ship their own brand images*, 2026-02-24: <https://developers.home-assistant.io/blog/2026/02/24/brands-proxy-api>
- **[HA-DEV-BTN]** Developer blog, *Standard event types for button event entities*, 2026-07-22: <https://developers.home-assistant.io/blog/2026/07/22/button-standard-event-types>
- **[HA-SRC-CTX]** Home Assistant Core 2026.9.2, `homeassistant/helpers/entity.py` (`CONTEXT_RECENT_TIME_SECONDS`, `async_set_context`): <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/helpers/entity.py>
- **[HA-SRC-DEPS]** Home Assistant Core, `pyproject.toml` at tag 2026.9.2 (dependencies, `requires-python`) and on the development branch (lint ban): <https://github.com/home-assistant/core/blob/2026.9.2/pyproject.toml>
- **[HA-SRC-SUN]** Home Assistant Core 2026.9.2, `homeassistant/helpers/sun.py`: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/helpers/sun.py>
- **[HA-DEV-IQS]** Home Assistant Integration Quality Scale: <https://developers.home-assistant.io/docs/core/integration-quality-scale/>
- **[OWN]** Documentation of the project owner's installation (shading of the west façade, storm and hail protection, comfort functions August 2026, lessons from the storm protection rework of 2026-09-17). Internal, not part of the repository; summarized in `docs-internal/`.
