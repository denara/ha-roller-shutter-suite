# Roller Shutter Suite for Home Assistant — Project Brief

| | |
|---|---|
| Status | Draft 1 — definition phase, no code written yet |
| Date | 2026-09-19 |
| Working name / repository | `ha-roller-shutter-suite` (integration domain proposal: `roller_shutter_suite`, see [Open points](#9-open-points)) |
| Next step | Derive `TASKS.md` from this brief as the basis for the orchestrator / plan agent |
| Audience | Implementing agents and maintainers. Instance-specific details of the first installation live in `docs-internal/` and are not part of the public repository. |

How to read the source markers: **[BP]** is the Simon42 blueprint documentation, **[#n]** an issue or pull request in the same repository, **[HA-DEV]** the Home Assistant developer documentation, **[OWN]** experience from the project owner's existing installation. Statements without a marker are decisions taken by the project owner during the definition session on 2026-09-19. All sources are listed in [section 10](#10-sources).

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

Totals: 53 will be implemented, 8 not yet, 6 will not be implemented.

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
| A12 | Frost protection | At frost do not drive, or only to about 90 %, to avoid tearing a frozen curtain. Temperature source freely selectable. | Will be implemented | [#24] |

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
| C1 | Geometric shading | Per window: orientation, field of view left and right, glass top and sill height, maximum sun penetration depth. Position is recalculated cyclically; very flat sun is treated more mildly. Additional simple mode with a fixed shading position for windows without measurements. | Will be implemented | [BP] |
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
| D3 | Fire alarm | Smoke detector triggers: all shutters open (escape routes). Overrides sleep exceptions, pauses and staggering. **No automatic return** after the alarm ends; a human decides. | Will be implemented | [#4] |
| D4 | Sleep-room exception | Per window: "protection event X must not open while sleep mode is active". Fire always ignores the exception. | Will be implemented | [OWN] |
| D5 | State-based return after protection | After the event ends (plus waiting time) the integration recomputes what applies **now**; only manually set positions are restored one to one. Remembered positions are persisted; unknown positions are skipped. | Will be implemented | [OWN] |
| D6 | Robust protection logic | A running event is detected and caught up after a restart. `unavailable` and `unknown` are neither a warning nor an all-clear: they do not trigger and do not release. | Will be implemented | [#18], [OWN] |
| D7 | Absence / vacation profile | Presence simulation or deviating times and positions during longer absence. The first version only delivers random time offsets (E13). | Not yet | [#2] |
| D8 | Alarm system coupling | No separate feature; any entity can trigger a "close" protection event through D1. | Will be implemented (covered by D1) | project owner |
| D9 | Watchdog | A protection event or lock that lasts implausibly long is released and reported as a Home Assistant repair issue. Maximum duration per event configurable. | Will be implemented | [OWN] |

### E — Override, operation, diagnostics

| ID | Feature | Summary | Status | Source |
|---|---|---|---|---|
| E1 | Manual operation detection | A position change outside a tolerance band that was not caused by the integration makes the comfort logic leave the window alone. Protection events ignore the override. | Will be implemented | [BP] |
| E2 | Override duration | Selectable: fixed minutes, until the shading episode ends, or until the next part of the day (default). Additionally, with an optional presence sensor: ends after the room has been empty for X minutes. A "resume automation" button ends it immediately. | Will be implemented | [#6] item 2, [#16], project owner |
| E3 | Grace period after own movement | Position reports during and shortly after a self-initiated movement do not count as manual. Travel time configurable per window; the cover's `opening`/`closing` state is used where available. | Will be implemented | [#6] item 3 |
| E4 | Pause and maintenance lock | Pause per window, per group and global as switch entities plus optional external pause entities; protection keeps running. After a pause the target state is recomputed instead of replaying missed events. A separate **maintenance lock** also suppresses protection movements (scaffolding, open shutter box). | Will be implemented | [BP], [#19] |
| E5 | Priority model | Central architectural principle, see [section 5](#5-architectural-guardrails). | Will be implemented | [BP] |
| E6 | Restart recovery | Episodes, overrides, remembered positions and locks are persistent. After start the target state is recomputed and missed daily events are caught up. | Will be implemented | [#6] item 1 |
| E7 | Status entities | Per window: active reason (enum), override active, next planned action, computed target position; plus diagnostics download. | Will be implemented | [#16] |
| E8 | Reason events | When an action is skipped or blocked, the integration fires an event and writes a logbook entry with the reason. Push delivery is left to user automations. | Will be implemented | [#6] item 12 |
| E9 | Operating mode | Select entity per window and global: automatic, protection only, off. | Will be implemented | [#14] |
| E9b | Named profiles | Freely definable profiles such as "Christmas". | Not yet | [#14] |
| E10 | Motor protection | Minimum change (blueprint: below 5 % no movement) and minimum interval between comfort movements. Does not apply to protection movements. | Will be implemented | [BP] |
| E11 | Dry-run | Per window the integration decides and logs but does not move. Enables side-by-side migration on a productive system. | Will be implemented | project owner |
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

## 5. Architectural guardrails

These are decisions and constraints, not a design. The design is part of the implementation phase.

1. **One arbiter instead of competing rules.** Every feature reports a position wish with a priority for a window; one arbiter per window picks the winner. The target state is always derivable from the current situation. This makes restart recovery (E6), pause end (E4) and return after protection (D5) the same operation: recompute.
2. **Proposed priority order** (highest first; to be finalized in the design, see open points): maintenance lock (no movement at all) → fire → local manual operation during a protection event (time-limited) → lockout protection (blocks closing only; void when tamper is active) → hail → storm and other protection events by rank → operating mode and pause → manual override → sleep / night mode → window interaction (B1, B4, B9) → privacy (F2) → shading and solar heating → schedule.
3. **A person at the window wins, for a limited time.** A wall button always moves the shutter, even during storm or hail. After a configurable time the protection event reasserts itself and a reason event is fired.
4. **Pure domain core.** Geometry, episodes, priorities and override handling are plain Python without Home Assistant imports, so they can be unit-tested and run in a time-lapse simulation of a whole day or year. The Home Assistant layer only adapts entities, time and storage.
5. **Configuration structure.** One config entry for the house (global sources, defaults, protection events); groups and windows as config subentries, each window with its own device. Reconfigure flows instead of delete-and-recreate. Same pattern as the owner's `room_presence` integration.
6. **Manual operation detection via context.** Working hypothesis: a state change caused by a service call with a user context is manual, one carrying the integration's own context is an own movement, one without a parent context is a hardware button. This must be verified per cover platform before it is relied upon; E3 remains the fallback.
7. **Buttons: hybrid.** Where the hardware supports a local link between button and actuator, up/down/stop stay local and work without Home Assistant; the integration sees the resulting movement as manual operation and only adds special functions. A full Home Assistant path exists for buttons without a local link and for rooms that only have a wall display. Not every user has a CCU or a comparable system.
8. **Sources are inputs, never assumptions.** Every sensor input is optional, accepts an entity or an entity attribute where that is common in practice, and has a defined behavior when unavailable.
9. **Configuration UX is settled: progressive configuration with sections (F4).** Feature switches first, steps only for enabled features, expert values in collapsed `section`s, everything else inherited. There is no "basic/advanced" mode and no use of `show_advanced_options` [HA-DEV-ADV]. Decided by the project owner on 2026-09-19; not an open point.
10. **Capabilities are detected, never assumed (F7).** What a cover, button or contact can do is read from the entity at configuration time. Options that cannot work are not silently accepted and do not fail silently at runtime.
11. **Position convention.** 100 % is fully open, 0 % fully closed, as in Home Assistant and [BP]. Glass calibration (C2) applies to shading calculations only.

## 6. Things that must be observed during implementation

### Safety and behavior

- Fire opens everything, immediately and unstaggered, and never returns automatically (D3).
- Never an intermediate position during storm: a half-lowered shutter offers the wind a surface and can be torn out of its guide rails [OWN]. Whether hail means "up" or "down" is disputed between glass and curtain types, so the direction is configurable per event (D2).
- An open door blocks closing even during storm, so nobody is locked out in bad weather; with an active tamper contact this trust is withdrawn (B2, F6).
- Missing data is not good news. `unavailable` and `unknown` must never be evaluated as "no warning", "no rain" or "window closed" (D6) [OWN].
- One controller per window at any time. During migration a window is either still controlled by its old program or by the integration, never both. Dry-run (E11) exists for the overlap.
- Order of change matters on a live system: first change the consumers (triggers), then the data source. The reverse order produced a false storm notification in the owner's installation on 2026-09-17 [OWN].

### Home Assistant specifics

- Restored entities carry the restart time as `last_changed`, and a `for:` duration on a state trigger never starts after a restart because a restore is not a state change. Durations must be tracked with own timestamps [OWN].
- After start, wait until the managed covers are available before computing or moving. Bus and radio integrations need time, and late position feedback is normal (E3).
- Cover capabilities differ. Check `supported_features` per cover: some covers offer no STOP (for example roof window shutters connected through HomeKit), so hold-to-move and stop-on-press (F5) are impossible there. Some report no position at all. This must be detected and explained during configuration (F7), not discovered at runtime.
- Button hardware usually delivers `press_short`, `press_long_start`, `press_long` and `press_long_release` as event entity types, but no native double press. Double press has to be detected by timing inside the integration, which adds latency to the single press; this trade-off must be configurable (F5).
- Some thermostats expose temperature only as an attribute of a `climate` entity (C12).
- `FlowHandler.show_advanced_options` is deprecated since 2026-05-26 and will be removed in Home Assistant Core 2027.6; the recommended replacement is grouping additional options in sections [HA-DEV-ADV]. F4 follows this.
- Use current APIs only: config subentries, reconfigure, sections, repairs, diagnostics, translation keys for every user-facing string. Before each rollout check the developer blog for breaking changes since the tested version [HA-DEV-BLOG].
- Labels, areas and naming conventions of an installation are not an API. The integration works on explicitly configured entities.

### Quality

- The Integration Quality Scale is used as a checklist: Silver rules are binding, Gold rules where sensible (diagnostics, reconfiguration via the UI, fully translatable entities) [HA-DEV-IQS]. Custom integrations are not formally graded on the scale; it serves as a guideline only.
- Tests with `pytest-homeassistant-custom-component` against the current Home Assistant version (2026.9.2 at the time of writing), deprecation warnings treated as errors. Python 3.14 via `uv` is required for current Home Assistant versions; `asyncio_mode = "auto"` [OWN].
- `hassfest` and the HACS validation action run in CI from the first commit, even while the repository is private.
- Code rules: English, documented, clean code, readable names. The owner is a software engineer and will read and adjust the code.

### Repository and documentation

- The content of the project folder becomes the repository. Proposed layout: `custom_components/<domain>/`, `tests/`, `docs/` (public), `docs-internal/` (git-ignored), `TASKS.md`, `README.md`, `hacs.json`, `.github/workflows/`.
- Public documentation: no secrets, no instance data, worked examples, plain language, no background knowledge assumed beyond operating Home Assistant. A dedicated writing skill for this tone can be created later; none exists yet.
- Internal documentation: entity IDs, migration plan and decisions specific to the first installation.
- Before the repository is created, check the name and the domain for collisions with Home Assistant Core, the HACS default list and existing projects. A web search on 2026-09-19 found no project named "roller shutter suite"; it did find projects with overlapping purpose, see related work. The search was not exhaustive.

## 7. Related work

To be evaluated at the start of implementation for ideas, terminology and pitfalls, not as dependencies:

- Simon42 "Intelligente Rollladensteuerung" blueprint [BP] — the feature baseline of this brief. One automation instance per window, helpers for state, exactly one mandatory window contact.
- [`basbruss/adaptive-cover`](https://github.com/basbruss/adaptive-cover) — HACS integration that controls covers based on the sun's position. Found by web search, not reviewed in this session.
- [`jrhubott/adaptive-cover-pro`](https://github.com/jrhubott/adaptive-cover-pro) — fork describing itself as sun-tracking control for blinds, awnings and venetian tilts "with climate-aware positioning and a priority override pipeline". Closest to guardrail 1; should be reviewed first. Not reviewed in this session.
- [`refael302/hai-shutter-manager`](https://github.com/refael302/hai-shutter-manager) and [`pujux/hass-cover-automation`](https://github.com/pujux/hass-cover-automation) — smaller integrations with overlapping purpose (sun, season, weather, frost, door sensors, schedules). Found by web search, not reviewed.

The decision for an own integration stands (section 1, items 3 and 5; none of the above was chosen as a base), but the review may show that parts of the geometry or the override pipeline are solved problems.

## 8. Outlook

Without commitment:

- **Self-calibration and learning.** Propose travel times, glass calibration and radiation thresholds from observation instead of asking the user to measure them.
- **LLM-assisted setup.** An assistant that derives geometry and groups from a description or floor plan.
- The deferred features A7, C3b, C10, C11, C13, C15, D7 and E9b.
- Submission to the HACS default list once the integration has proven itself in the first installation.

## 9. Open points

1. Final name and domain after the collision check.
2. Final priority order, in particular the position of the maintenance lock relative to fire, and the default duration of "person at the window wins".
3. Verification of the context-based manual detection per cover platform (guardrail 6).
4. License.
5. Detailed catch-up rules: which missed daily events are caught up after a restart or pause, and until when.
6. School holidays as a day type (A3): calendar entity or dedicated source.

## 10. Sources

- **[BP]** Simon42, *Intelligente Rollladensteuerung (cover_automation_v2)*, documentation: <https://github.com/TheRealSimon42/ha-blueprints/blob/main/docs/cover_automation_v2.md>
- **[#n]** Issues and pull requests of the same repository, read individually on 2026-09-19: <https://github.com/TheRealSimon42/ha-blueprints/issues>. At that date the repository had 22 issues (all open, none answered by the maintainer) and 4 pull requests (#18, #19, #22, #23). Referenced here: #1 sunrise/sunset, #2 vacation mode, #3 insect screen door, #4 smoke detector, #5 brightness-based closing, #6 twelve suggestions from practice (restart, manual override, evening, shading), #7 presence condition and awning, #8 venetian blinds, #9 hail protection, #10 weekend and astro times, #11 optional window sensor, #12 ideas, #13 heat self-protection, #14 intermediate position and mode select, #15 ventilation recommendation, #16 external shading enable and override timeout, #17 PV-based shading, #18 storm protection hardening (PR), #19 pause helper consistency (PR), #20 rain protection while ventilating, #21 calendar confirmation, #23 weekend opening time (PR), #24 frost protection, #25 motion-based opening, #26 light sensor.
- **[HA-DEV-ADV]** Home Assistant Developer Docs, *Deprecation of advanced mode in data entry flow*, 2026-05-26: <https://developers.home-assistant.io/blog/2026/05/26/advanced-mode-config-flow-deprecation/>
- **[HA-DEV-BLOG]** Home Assistant developer blog: <https://developers.home-assistant.io/blog>
- **[HA-DEV-IQS]** Home Assistant Integration Quality Scale: <https://developers.home-assistant.io/docs/core/integration-quality-scale/>
- **[OWN]** Documentation of the project owner's installation (shading of the west façade, storm and hail protection, comfort functions August 2026, lessons from the storm protection rework of 2026-09-17). Internal, not part of the repository; summarized in `docs-internal/`.
