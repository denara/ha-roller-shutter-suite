# Roller Shutter Suite — Domain design specification

| | |
|---|---|
| Status | Approved by the project owner: decisions 1 to 13 on 2026-09-19, decision 14 on 2026-09-20. All were accepted as recommended; the boxes keep the reasons and the rejected alternatives. |
| Refines | [project-brief.md](project-brief.md), where the brief refers to "the domain design specification" or "D00" |
| Audience | Implementing agents and maintainers |

The brief says what is built and why. This document defines the model all work blocks share: the vocabulary, the arbiter, the rules that the brief left open, and the seams between the modules of the domain core. It contains no Home Assistant specifics; configuration flows, entities and adapters belong to the blocks of the Home Assistant layer.

**How to read it.** Every statement is binding. Points that the project owner decided explicitly are set in a box like this one, so the reason and the rejected alternatives stay visible:

> **Decision n — title.** A point the project owner decided. Each states what was recommended and accepted, the reason, and the alternatives that were rejected. All decisions are collected in [section 15](#15-decisions-of-the-project-owner).

Rules that the owner has already decided are stated as rules and marked *(decided)*; they are not reopened here.

---

## 1. Vocabulary

| Term | Meaning |
|---|---|
| **Window** | The unit of configuration, decision and status. One window has one device and one status. |
| **Member** | A single cover entity that belongs to a window. Most windows have one member; a window can have several that are always moved together ([section 9](#9-several-covers-operated-as-one-window)). |
| **Group** | A set of windows that share defaults (façade, floor, room type). Not to be confused with a Home Assistant cover group. |
| **Covering type** | What hangs in front of the glass. Only `roller_shutter` is implemented; the field exists so that venetian blinds (C15) can be added without restructuring. |
| **Position** | Integer 0–100, 100 = fully open, 0 = fully closed (guardrail 11). |
| **Source** | An input read from an entity state or an entity attribute. A source value has exactly three states: a **value**, **unknown**, or **unavailable**. There is no implicit conversion of the last two into a number or a boolean. |
| **Layer** | A part of the logic that answers "where should this window be?" for one concern (fire, a protection event, sleep mode, shading, schedule …). |
| **Wish** | The answer of a layer: a **target position**, **leave alone**, or **no opinion**. Always carries a reason code and its wish class. |
| **Wish class** | `fire`, `protection` or `comfort`. Constraints and gate rules state which classes they apply to. |
| **Constraint** | A rule that limits the winning wish without replacing it, for example "do not go lower than …". |
| **Gate** | The stage that answers "may the integration move now?". Its outcome is **send**, **defer**, or **suppress**, always with a reason code. A deferral names the point in time at which it ends if that is known. If it is not known ("until a member is available", "until the members have come to rest"), it carries a mandatory upper bound instead: the latest time at which the window is evaluated again from its current state. Nothing is replayed when a deferral ends. |
| **Dam** | A gate rule that holds back wishes of certain classes for a while. There are two: the manual override dam and the person-at-the-window dam. |
| **Decision** | The complete result of one recompute: the winning wish, the constraints applied, the gate outcome, and for every other layer the reason why it did not win. |
| **Reason code** | A machine-readable code from a closed list ([section 5](#5-reason-codes)). No free text anywhere in a decision. |
| **Recompute** | Evaluating layers, constraints and gate for one window against a world snapshot. The only operation that produces a decision. |
| **World snapshot** | Everything a recompute may look at: the time, the sun position, all source values, the observed state of the members, and the persisted window state. |
| **Owner of a position** | Who put the window where it is: `engine`, `user` or `unknown`. |
| **Expectation window** | The period after an own command in which reports from the cover are attributed to that command ([section 8](#8-observing-a-movement)). |
| **Capability profile** | What a member can do and report ([section 8.1](#81-capability-profile)). |
| **Part of the day** | `day` or `night`, separated by the morning and the evening trigger of the schedule ([section 6](#6-schedule-parts-of-the-day-day-types)). |
| **Day type** | `workday`, `weekend` or `holiday`. |
| **Episode** | A period during which a condition-driven layer is active for a window, with a defined start and end ([section 7](#7-episodes)). |

---

## 2. The arbiter

One arbiter per window. It has no state of its own and reads no clock: the same world snapshot always yields the same decision. Everything that must survive between recomputes is part of the persisted window state ([section 11](#11-persistence-and-restart)).

```text
world snapshot ─► layers (first opinion wins) ─► constraints ─► gate ─► send / defer / suppress
                        │                              │            │
                        └──────── every stage reports its reason into the decision ───────┘
```

### 2.1 Layers

Layers are evaluated in this order; the first one that returns a target position or "leave alone" wins. "No opinion" passes to the next layer. Every layer that did not win still reports why (inactive, not configured, input unavailable, held by an exception …).

| # | Layer | Class | Wish |
|---|---|---|---|
| 1 | Fire (D3) | fire | While the alarm is active: open fully. After the alarm has ended and until a person acknowledges it: **leave alone** (`fire_unacknowledged`). |
| 2 | Protection events (D1, D2, D8), by rank | protection | The event's end position: fully open or fully closed, never in between. Several active events: the highest rank wins; ranks are unique. Hail ranks above storm by default. |
| 3 | Sleep / night mode (A9) | comfort | Night position. By winning, it keeps shading, solar heating and privacy from acting. |
| 4 | External request (F1, A11) | comfort | The requested position until the request expires or is cleared. |
| 5 | Privacy when lights are on (F2) | comfort | Privacy position, lowering only. |
| 6 | Shading (C1–C7, C9, C12, C14) and solar heating (C8) | comfort | Shading position during a shading episode; open once during a solar heating episode. The two exclude each other by their temperature conditions. |
| 7 | Schedule (A1–A6) | comfort | The target of the current part of the day. Always has an opinion once configured, so a window never lacks a bottom layer. |

Unknown or unavailable input never becomes a guess. Each layer states, per input, whether its absence means "no opinion" (the layer steps aside) or "leave alone" (the layer holds the window where it is). The rule of thumb: a layer whose purpose is safety holds; a layer whose purpose is comfort steps aside.

> **Decision 1 — Window interaction as constraints, not as a layer.** The brief's starting order lists "window interaction (B1, B4, B9)" as a layer between sleep mode and privacy. Recommendation: express it as constraints ([section 2.2](#22-constraints)). An open or tilted window does not want a position of its own; it sets a **floor** under whatever the comfort layers want. With a floor, B1 (raise to the ventilation position), B9 (evening closing stops at the ventilation position) and "back after closing the window" are the same rule, and the return needs no memory: when the window closes, the floor disappears and the recompute yields the full closing. *Rejected:* a layer that returns the ventilation position. It would have to know what the layers below wanted in order not to lower an open shutter, and it would need remembered state for the way back.

> **Decision 2 — Position of the external request layer.** Recommendation: below sleep mode, above privacy and shading. An alarm clock automation (A11) that wants to open a bedroom shutter therefore also has to end sleep mode for that room, which is what waking up means. The documentation of F1 has to state this plainly: an automation that wants to open a window in a room with active sleep mode (an alarm clock) must end the sleep mode of that room first; otherwise its request is accepted, waits below the sleep layer, and nothing moves. *Rejected:* above sleep mode. Any automation could then defeat the sleep switch, and the person who set it would not know why.

### 2.2 Constraints

Constraints are applied to the winning wish in this order. Each one names the classes it applies to. A constraint can raise or lower the target, or pin it to the current position; it never invents a wish where there is none. If the constrained target equals the current position, nothing moves, and the reason is the constraint's.

| # | Constraint | Applies to | Effect |
|---|---|---|---|
| 1 | Direction of the wish (A1, A6, F2) | the wish that carries it | A wish can be `raise_only` or `lower_only`. The morning target only raises; evening, night and privacy only lower. |
| 2 | Sleep-room exception (D4) | protection wishes of events marked for the window, while sleep mode is active | Never raise. |
| 3 | Lockout protection (B2) | comfort and protection | While a blocking contact reports open: never lower. Void while the tamper contact (F6) is active. A blocking contact that is unavailable counts as **open**, because the opposite could lock somebody out. |
| 4 | Ventilation floor (B1, B9) | comfort | While the window contact reports tilted or open: not lower than the ventilation position (tilted) or the open-window position (open). An unavailable window contact sets no floor. |
| 5 | Rain while ventilating (B4) | comfort | While the ventilation floor applies and rain has lasted the configured time: the floor drops to the rain position, and returns the configured time after the rain ends. |
| 6 | Frost protection (A12) | own movements of class comfort; protection too if configured; never fire; never a movement by hand | While frost is active and not waived: do not **open** further than the frost position (default 90). Closing is not limited. Details in [section 2.6](#26-frost-protection). |
| 7 | No intermediate position during a protection event | protection | The target stays an end position. If lockout protection prevents it, the window is left alone rather than driven halfway. If frost protection is configured to apply to protection movements, the frost position counts as the open end position. |

Fire is subject to no constraint at all.

> **Decision 3 — Frost when the temperature is unavailable.** "Missing data is not good news", and frost is the warning here. Recommendation: hold the last known frost state for at most 24 hours; after that the constraint becomes inactive and a repair issue names the source. *Rejected:* treating "unavailable" as frost for an unlimited time (a dead sensor would limit all openings for weeks, and users would learn to disable the feature); treating it as "no frost" at once (contradicts D6's principle).

### 2.3 The gate

The gate rules are evaluated in this order; the first rule that applies decides. "Applies to" names the wish classes a rule can hold back.

| # | Rule | Applies to | Outcome |
|---|---|---|---|
| 1 | Maintenance lock (E4) | fire, protection, comfort | Suppress. The only state in which nothing moves at all *(decided)*. |
| 2 | No member can execute the command (all unavailable, or the capability is missing) | all | Defer until a member is available, or suppress with the capability reason. |
| 3 | Target reached (within tolerance, or no position feedback and the last own command already had this target) | all | Nothing to do. |
| 4 | Operating mode (E9) | `off`: protection and comfort. `protection only`: comfort. | Suppress. |
| 5 | Pause (E4) | comfort | Suppress. |
| 6 | Person-at-the-window dam (guardrail 3) | protection and comfort | Defer until the dam ends. |
| 7 | Manual override dam (E1, E2) | comfort, except the return to the manual position after a protection event ([section 10.2](#102-return-after-a-protection-event-d5)) | Defer or suppress, depending on the end rule of the dam. |
| 8 | Movement in flight | comfort | Same target as the pending own command: suppress as duplicate. Different target: defer until the members have come to rest. Protection retargets at once. |
| 9 | Motor protection (E10) | comfort | Change below the minimum: suppress. Inside the minimum interval since the last own comfort movement: defer until it has passed. |
| 10 | Command backoff (N1) | protection and comfort | Defer until the next retry time. |
| 11 | Staggering (E13) | protection and comfort | Defer by the window's slot in a collective movement. |
| 12 | Dry-run (E11) | fire, protection, comfort | The last barrier before sending. Whatever reaches it would have been sent: suppress it and record the would-be command *(decided: dry-run never moves anything, not even at fire)*. |
| — | none applied | | Send. |

Pause, operating mode and maintenance lock exist on global, group and window level. The effective value for a window is the **most restrictive** of the three: a window is paused if any level is paused, locked if any level is locked, and its mode is the most restrictive mode of the three levels.

**Dry-run is the last rule on purpose.** A window in dry-run runs next to another controller that still moves the same window, and the owner judges the integration by what it *would* have done. If dry-run were an early rule, every decision would read `dry_run` and nothing else. As the last rule, the decision record of a dry-run window shows the complete hypothetical outcome: either "would have sent position X because …" or "would have held back because of rule N". For this to work in dry-run:

- The gate rules that depend on own commands (movement in flight, motor protection, command backoff) are evaluated against **simulated** commands: a would-be send is remembered with target and time, in a state that is separate from the real one. The real motor protection clock is never touched. When a window is armed, the simulated state is discarded.
- "Target reached" compares with the real position. In parallel operation this is the most useful line of all: it means the other controller has put the window where the integration wanted it.
- **Movements are observed and logged, but arm no dam and do not change the owner of the position.** In dry-run the integration never commands, so every movement is foreign; next to a controller that is still active, the manual override dam would be armed permanently and the record would show nothing but `manual_override`. Arming a window starts from a clean state: no dam, owner `unknown`.
- The adapter checks dry-run a second time before any command (defense in depth); that does not change.

### 2.4 The fire bypass

The fire bypass is a named construct of the gate, not a set of exceptions spread over the rules. A wish of class `fire` **skips** these gate rules:

- 4 operating mode, 5 pause, 6 person-at-the-window dam, 7 manual override dam, 8 movement in flight (fire retargets at once), 9 motor protection, 10 command backoff, 11 staggering.

It does **not** skip:

- 1 maintenance lock and 12 dry-run *(decided)*. In both cases the fire event is fired immediately, with the reason code that says why nothing moved.
- 2 and 3, which describe what is physically possible or already true.

Fire is also exempt from every constraint, including frost and the sleep-room exception.

Fire never returns automatically, and it never fights a person. While the alarm is **active**, the wish is "open". When the alarm has **ended** and nobody has acknowledged it yet, the wish is "leave alone": it still wins and therefore holds back every lower layer, but it moves nothing. Without this distinction the integration would, after a false alarm, reopen every shutter somebody closes by hand, because fire skips both dams. Only the acknowledgement (an action or a button) lets the recompute fall through to the lower layers again. A movement by hand in the unacknowledged phase is observed like any other and arms the manual override dam, so the comfort logic does not undo it right after the acknowledgement.

### 2.5 Operating modes

| State | Comfort | Weather and other protection | Fire |
|---|---|---|---|
| automatic | moves | moves | opens |
| protection only | — | moves | opens |
| off | — | — | opens |
| maintenance lock | — | — | event only, no movement |

### 2.6 Frost protection

Frost protection is **preventive**. The integration cannot detect a curtain that is frozen in place ([section 8](#8-observing-a-movement): on many installations the reported position is calculated, not measured). It can only avoid the movement that does the damage, and the documentation has to say exactly that.

> **Decision 13 — Frost protection (A12).** Recommendation, following the source of the feature (issue 24 of the blueprint repository):
>
> - **Basic behavior.** While frost is active, own movements open only up to the frost position (default 90), so the curtain does not run into a frozen end stop. Closing is never limited. "Do not raise a closed window at all" exists as a separate option that is **off** by default (`frost_hold`).
> - **Frost is active** when the frost source is below its threshold (default 0 °C, with hysteresis). The frost source is an ordinary inherited setting, so it can be chosen per group or façade. This matters because false alarms are normal: a regional value or a sensor on the shaded side says little about a sunlit façade.
> - **Waiver by the operator.** The operator can lift frost protection explicitly, per window, per group and globally, **until the next morning trigger** of the window. A window is waived if any of the three levels is waived. The waiver is persisted, shown in the window's status, and fires a warning event when it starts and when it ends (`frost_protection_waived`, `frost_waiver_ended`).
> - **Test movement.** The limit applies only to movements the integration starts itself. A movement by hand, from a locally linked button or from a button on the Home Assistant path (F5), is never limited. This lets the operator check selectively whether a curtain is actually stuck.
> - **Release by sun** (optional, off by default). If the window has been in direct sun for a configurable time (sun inside the field of view and above the minimum elevation, and the radiation or weather condition of shading says "sunny"), the limit is lifted for this window and a warning event is fired (`frost_released_by_sun`). It needs the geometry and the radiation signal and is therefore **not** part of block C03. It is built with the shading conditions in block C10 and wired in H16, as part of A12.
> - After a frost phase, a waiver or a release by sun, positions may be inaccurate until the next end position ([section 8.4](#84-calculated-positions-and-drift)).
>
> *Rejected:* limiting closing ("do not close below a frost position"), which does not address the damage mechanism, a curtain running into a frozen end stop; and blocking all comfort movements during frost, which punishes every false alarm with a dark or a bright house.

---

## 3. The two dams

Both dams are armed by the movement tracker ([section 8](#8-observing-a-movement)) when it attributes a movement to somebody else than the integration, or by a wall button on the full Home Assistant path (F5).

### 3.1 Manual override dam

- **Holds back:** comfort. Protection and fire pass, which is why no rule "protection ignores the override" is needed. One comfort wish passes too: the return to the manual position after a protection event (`protection_return_manual`, [section 10.2](#102-return-after-a-protection-event-d5)), because it restores exactly what the dam protects.
- **Armed when** an external movement is detected while no protection wish is winning. A movement the integration commanded itself never arms it, whatever layer it came from.
- **Remembers** the position the person chose, with the time.
- **Ends** by the configured rule (E2): after fixed minutes; when the shading episode ends (only if it was armed during one); at the next boundary between parts of the day (default); when the room has been empty for the configured time; or at once through the "resume automation" button or action. When it ends, the window is recomputed; nothing is replayed.
- **Switching sleep mode on ends it** for the windows the sleep switch covers. Turning on sleep mode is a deliberate act of a person and says what the room shall look like now; an older hand movement must not keep the bedroom shutter open all night. A movement by hand **during** sleep mode arms the dam again as usual, so somebody who opens the shutter at night is not overruled.
- **In dry-run it is never armed** ([section 2.3](#23-the-gate)).
- **While a protection event is active**, the dam stays armed and its clock keeps running.

> **Decision 4 — Override duration during a protection event (D5 and E2).** Recommendation: the clock keeps running. After the event (plus its waiting time) the remembered manual position is restored only if the dam is still armed at that moment; otherwise the window is simply recomputed. *Rejected:* stopping the clock during the event. It needs extra persisted state, makes the end of an override hard to predict ("until the evening" could become "until tomorrow noon"), and restores a position whose reason may be long gone.

### 3.2 Person-at-the-window dam

- **Holds back:** protection and comfort. Never fire *(decided)*.
- **Armed when** an external movement is detected, or a wall button is used on the full Home Assistant path, while a protection wish is winning.
- **Ends by itself** after the configured time, default 15 minutes *(decided)*. It can be armed again by the next external movement; each arming and each end fires a reason event.
- **When it ends:** if the protection event is still active, protection reasserts itself through the normal recompute. If the event has ended in the meantime, the dam turns into a manual override dam with the position the person chose, so the comfort logic does not immediately undo what the person did.
- The position a person chooses during a protection event does **not** replace the position remembered from before the event.

> **Decision 5 — A wall button on the full Home Assistant path during a maintenance lock.** Recommendation: refuse it and fire a reason event. The lock exists because a moving shutter can injure somebody; a button press in another room must not move it. A button that is linked locally to its actuator cannot be stopped by the integration at all; the documentation says so plainly and recommends cutting the power for real maintenance work. *Rejected:* letting the button through "because a person wins". That rule is about comfort against weather, not about safety of people working on the shutter.

---

## 4. Situations and their outcome

The reference cases. Every one of them becomes a test.

| # | Situation | Outcome | Reason codes (winner / constraint / gate) |
|---|---|---|---|
| 1 | Fire during maintenance lock | No movement. Fire event fired at once. | `fire_alarm` / — / `maintenance_lock` |
| 2 | Fire in dry-run | No movement. Fire event fired at once; the record shows "would open". | `fire_alarm` / — / `dry_run` (would send 100) |
| 2a | Dry-run next to another controller: that controller lowers the window at noon; later a storm starts while the window is paused | The noon movement is logged, no dam is armed. At the storm the record shows "would have sent 0" with `dry_run`, because pause does not hold back protection; a comfort wish at the same moment would show `paused` instead. | `protection_event` / — / `dry_run` (would send 0) |
| 3 | Fire in mode `off` | Opens at once, unstaggered. | `fire_alarm` / — / `sent` |
| 3a | The fire alarm has ended (false alarm), nobody has acknowledged it, a person closes a shutter by hand | The shutter stays closed. Nothing moves until the acknowledgement; afterwards the manual override dam protects what the person did. | `fire_unacknowledged` / — / — + `manual_detected` |
| 4 | Storm (closing) with an open terrace door | No movement while the door is open; closes when the door is shut. | `protection_event` / `lockout_door_open` / — |
| 5 | Same, tamper contact active | Closes. | `protection_event` / `lockout_void_tamper` / `sent` |
| 6 | Hail (opening) with sleep-room exception, sleep mode active | Stays closed. | `protection_event` / `sleep_exception_no_open` / — |
| 7 | Wall button during storm, then 15 minutes pass | The button movement stands for 15 minutes, then the storm position is restored and a reason event is fired. | first `protection_event` / — / `person_at_window`; then `protection_event` / — / `sent` |
| 8 | Manual override active when a storm begins | Closes. The override dam stays armed and keeps the person's position. | `protection_event` / — / `sent` |
| 9 | The storm ends, override dam still armed | After the waiting time the remembered manual position is restored. | `protection_return_manual` |
| 10 | The storm ends, override dam expired meanwhile | After the waiting time the window is recomputed. | whatever layer wins now |
| 10a | A shutter was opened by hand in the afternoon (override until the next part of the day); sleep mode is switched on | The override ends, the window goes to the night position. | `sleep_mode` / — / `sent` + `override_ended` |
| 10b | During sleep mode somebody opens the shutter by hand | It stays open; the override dam is armed with its normal end rule. | `sleep_mode` / — / `manual_override` |
| 11 | Evening closing with a tilted window | Lowers to the ventilation position; closes fully when the window is shut. A reason event makes the deviation visible. | `schedule_night` / `ventilation_floor` / `sent` |
| 12 | Frost during evening closing | Closes fully. Frost does not limit closing. | `schedule_night` / — / `sent` |
| 12a | Frost at the morning opening | Opens to the frost position (90) instead of 100. When frost ends, the recompute opens the rest. | `schedule_day` / `frost_limit` / `sent` |
| 12b | Frost, and the operator waives frost protection for the window | Opens fully. Warning event. The waiver ends at the next morning trigger. | `schedule_day` / — / `sent` + `frost_protection_waived` |
| 13 | Restart in the middle of a shading episode | The episode is restored from the persisted state; the recompute yields the same shading position; no movement if the window is already there. | `shading_geometric` / — / `target_reached` |
| 14 | The source of an active protection event becomes unavailable | The event stays active (D6). The watchdog clock keeps running. | `protection_event` (input held) |
| 15 | One member of a window with several covers is moved by hand | The override dam is armed for the whole window. The other members stay where they are. | `manual_detected_member` |
| 16 | One member is unavailable when a protection event starts | The available members move. The window's status names the missing member. When it returns, it is brought to the common target as an own movement. | `protection_event` / — / `sent` + `member_unavailable` |

---

## 5. Reason codes

A closed enumeration in the core. Adding a code requires an English and a German translation; a test enforces it. Events with a variable subject (which protection event, which member, which source) carry that as a separate attribute, never inside the code.

**Winning or contributing layers:** `fire_alarm`, `fire_unacknowledged`, `protection_event`, `protection_return_manual`, `sleep_mode`, `external_request`, `privacy_lights_on`, `shading_geometric`, `shading_fixed`, `solar_heating`, `schedule_day`, `schedule_night`.

**Why a layer did not act:** `not_configured`, `inactive`, `input_unavailable`, `input_unknown`, `input_held_last_known`, `waiting_for_delay`, `outside_episode`, `episode_locked`, `watchdog_released`, `capability_missing`, `day_type_fallback`.

**Constraints:** `only_raise`, `only_lower`, `sleep_exception_no_open`, `lockout_door_open`, `lockout_void_tamper`, `lockout_contact_unavailable`, `ventilation_floor`, `rain_ventilation_floor`, `frost_limit`, `frost_hold`, `no_intermediate_position`.

**Gate:** `sent`, `maintenance_lock`, `dry_run`, `cover_unavailable`, `target_reached`, `mode_off`, `mode_protection_only`, `paused`, `person_at_window`, `manual_override`, `movement_in_flight`, `duplicate_command`, `min_change`, `min_interval`, `command_backoff`, `staggered`.

**Tracker and life cycle (events only):** `manual_detected`, `manual_detected_member`, `external_movement_observed` (dry-run), `moved_during_downtime`, `person_at_window_started`, `person_at_window_ended`, `override_started`, `override_ended`, `protection_started`, `protection_ended`, `protection_source_blind`, `lockout_contact_blind`, `fire_acknowledged`, `frost_protection_waived`, `frost_waiver_ended`, `frost_released_by_sun`, `position_may_be_inaccurate`, `command_failed`, `actuator_no_reaction`, `movement_not_finished`, `member_unavailable`, `button_refused_maintenance_lock`.

No code claims that a curtain has arrived ([section 8.4](#84-calculated-positions-and-drift)).

---

## 6. Schedule, parts of the day, day types

### 6.1 State-based schedule

The schedule does not fire events that could be missed. It defines, for every point in time, the part of the day and its target:

| Part of the day | From | Target | Direction |
|---|---|---|---|
| `day` | the morning trigger | morning position (A1) | raise only |
| `night` | the evening trigger | evening position, seasonal if configured (A5) | lower only |

Consequences: after a restart, a pause, a protection event or an override, the schedule layer simply states what applies now. Nothing is "caught up", because nothing was missed (brief, open point 3). The direction rules keep this safe: a shutter that is already lower than the evening position is never raised by it (A6), and the morning target never lowers a shutter. One consequence has to be known: when a manual override ends during the day, the schedule raises the window to the day target again. The default end rule of the override, "next part of the day", exists for exactly that reason: a room darkened by hand stays dark until the evening.

*Rejected alternative:* an event-based schedule that replays missed events after a restart or a pause, each with a deadline until which it is still caught up. It needs a rule per event and per kind of interruption, it depends on having seen triggers, and it is the source of the restart problems the brief lists under E6.

The only things with an expiry are one-time actions inside episodes (solar heating, [section 7](#7-episodes)).

### 6.2 Triggers

Per day type, morning and evening each have one trigger kind: a fixed time; sunrise or sunset with an offset; or a sun elevation. Astro and elevation triggers are clamped by "not before" and "not after" (A2). If an elevation is never reached on a day, the trigger falls on the clamp that lies in its direction. The evening can additionally be triggered by an outdoor brightness source below a threshold for a configured time (A4), but only inside the clamps; an unavailable brightness source neither triggers nor blocks the other trigger.

The core receives sun times and sun positions through the sun port and computes nothing astronomical itself.

### 6.3 Day types

Inputs, both optional and chosen by the user: a **workday source** (on = workday) and a **holiday source** (on = public holiday; a calendar entity with an all-day event works the same way). The integration brings no holiday data of its own *(decided)*.

1. Holiday source on → `holiday`.
2. Otherwise workday source on → `workday`, off → `weekend`.
3. No workday source → Monday to Friday `workday`, Saturday and Sunday `weekend`.

The day type of a date is **latched**: determined at the first recompute after local midnight at which the configured inputs have a value, then persisted for that date. Without the latch, a source that changes in the middle of the day would move the morning trigger after the fact and flip the part of the day. If an input is unavailable at that moment, rule 3 applies for the time being with `day_type_fallback`, and the latch is set as soon as the input has a value, as long as the morning trigger of that day has not passed yet. School holidays are not part of the first version.

### 6.4 Season (A5)

> **Decision 6 — Source of the season.** Recommendation: an optional source chosen by the user (on = summer). Without it, an optional date range (first and last day of summer). Without either, there is one evening position. If the source is unavailable, the last known value is held without a time limit, because nothing depends on it except comfort. *Rejected:* deriving the season from temperature or day length; both need tuning that a simple switch or two dates make unnecessary.

### 6.5 Random offsets (E13)

The offset of a trigger is a function of the installation's seed (created once, persisted), the window, the date and the trigger. It is therefore stable within a day, different between windows, reproducible in tests and in the simulation, and it survives a restart. It is drawn uniformly from ± the configured range (default 0 = off, maximum 30 minutes) and applied before the clamps. Staggering between motors is a separate mechanism in the gate: default gap 2 seconds per motor, range 0–10 seconds; never for fire.

---

## 7. Episodes

An episode belongs to one layer and one window. It has a start condition, an end condition, and persisted state. "Once per episode" is always a flag in that state, never a memory of having seen a trigger.

| Episode | Starts when | Ends when | Persisted |
|---|---|---|---|
| **Shading** | all enabled conditions hold: sun inside the field of view and above the minimum elevation; temperature condition (C3, C4, C12); radiation above its threshold for the *fast* delay (C5) or, without a radiation source, an allowed weather condition (C6); shading enabled (C9); no rain lock (C14) | any of: sun outside the field of view or below the end elevation (C7); temperature below threshold minus hysteresis; radiation below its threshold for the *slow* delay; weather stably bad for the configured time (default 10 minutes); persistent rain, which also starts the rain lock (C14); shading disabled (C9); sleep mode | active since; rain lock until |
| **Solar heating** | temperature below its threshold, sun inside the field of view, the window closed or nearly closed, sleep mode off | the sun leaves the field of view, or the temperature condition ends | active since; "opened once" flag |

During a shading episode the position is recalculated cyclically; motor protection (gate rule 9) keeps the number of movements small. When an episode ends, the layer has no opinion any more and the recompute falls through to the schedule.

Details from the brief's list of vague wording (open point 8):

- **C4 "until mid-afternoon":** until a configurable local time, default 15:00. Before it, the temperature condition uses the higher of the current temperature and the forecast daily maximum; after it, the current temperature only. The forecast is refreshed hourly; if it is unavailable, the current temperature is used alone.
- **F3 "more aggressive heat protection":** the roof window profile is a set of different **defaults**, not different logic: geometry from the roof pitch; a lower temperature threshold (default 3 K below the façade default); the shading position may go down to fully closed above a configurable "hot" temperature; rain closes instead of ending the shading. Every value can still be overridden per window.
- **D9 defaults:** see [section 10.3](#103-watchdog-d9).

---

## 8. Observing a movement

Measured facts that this section has to hold under (two cover platforms, about a hundred movements): both report `opening`/`closing` but no intermediate positions; one keeps the old position for the whole travel and jumps to the target at the end; at the end of a movement two state writes arrive within 7 to 30 ms, either the same state twice or the position as an attribute-only write followed by the resting state; a state write with a new change time but identical state and position occurs without any movement; a transit state can follow a transit state directly when a movement is reversed; travel time differs by direction and is not linear in percent, the part that ends in an end stop takes longer; after an unavailable gap a cover returns with the state it had; the start report of one platform already carries a position a few percent into the travel. The context of the state change carries the caller for about five seconds and is gone on the final report. In an active test with known targets, one platform reported the commanded target as end position in six of six movements, with the start report written about 0.5 to 1 s into the movement and already carrying a changed position; seconds per percent varied between 0.17 and 0.22 without a simple rule, so durations derived from reports are not a linear function of the distance. The other platform, with four members commanded at once, delivered reports only on a fixed grid of about 60 seconds, with no transit state and no report at the real end of the movement, although the same platform had reported in real time when a single member moved. A cover group entity stepped through the mean of its members within milliseconds and never showed a transit state.

**The reported position is an estimate on many installations.** Actuators that switch a plain up/down motor know the position only from run time and a reference run. The motor reports nothing back, and it has an overload cut-out: the actuator may apply "up" for ten seconds while the motor cuts out after two, and the actuator still counts to the end and reports the target as reached. "Ten seconds up" does not mean the curtain went up. This matches the measurements: every movement whose target is known ended exactly on it. Consequences run through this whole section and are collected in [section 8.4](#84-calculated-positions-and-drift).

### 8.1 Capability profile

Per member: supports open and close; supports set position; supports stop; **reports a position** (yes / no); **position source** (`measured` by the drive itself, or `calculated` from run time; this cannot be detected, so the user states it, default `calculated`); **reports transit states** (yes / no / unknown until observed); **position updates during travel** (live / end only); **report delay** (how long a report may lag behind reality: 0 for platforms that push their state, in the order of 60 s and more for platforms that are polled; stated by the user, with a default per platform type where one is known); full travel time upwards and downwards. Travel times are **configuration values**. They are never learned from reports: with a report delay they cannot be observed at all, and without one the reports are not linear in the distance. "Reports transit states" is a property that a platform can lose under load (see the measured facts), so the tracker never depends on a transit state for a member that has a report delay. A member without position feedback is valid (N2): for it there is no tracking, no manual detection and no intermediate target; the owner of its position is `unknown`; targets are mapped to open or close (below 50 closes, from 50 opens, unless the wish is an end position anyway).

### 8.2 Normalizing reports

Before anything is interpreted, reports of a member are reduced to **observations**: (state class: resting / moving up / moving down / unavailable, position or none). A report that does not change the observation is dropped. This removes duplicate writes and rewrites with a new change time. A decision is never based on the change time of a state alone.

### 8.3 The tracker

Per member: `idle` → `expecting` (own command sent) → `moving` → `settling` → `idle`.

- **Own command:** remember target, direction, time, wish class and the context ID; enter `expecting`. No expectation is created for a command whose target equals the current position (the gate stops those).
- **Deadline** of the expectation: `report delay + start allowance + travel time of the direction × share of the travel × slack + end allowance`. Defaults: start allowance 10 s, slack 1.5, end allowance 5 s; the report delay comes from the capability profile. The proportional share alone underestimates movements that end in an end stop, and a fixed start allowance alone would raise a false "did not react" on a polled platform. Command verification (N1) and every other timer that waits for a report use the same deadline; none of them uses a fixed number of seconds.
- **A new own command resets the expectation.** Target, direction, time and deadline are replaced as a whole. This is a design assumption: a second command during travel could not be measured, and neither could the real command latency.
- **Members with a report delay:** no transit state is expected. The movement is evaluated at the first report after the command that shows a resting state, or at the deadline. A position change seen in `idle` is external, with the knowledge that it may have happened up to one report delay earlier.
- **Settling:** a movement is evaluated **once**, a settle time (default 2 s) after the resting observation, with the position reported by then. This covers platforms that write the position shortly before or after the resting state.
- **Evaluation:** position within tolerance of the target → own movement, the expectation is consumed. Outside the tolerance → somebody intervened (a stop, another command) → external. The default tolerance depends on the position source: 2 for a `calculated` position, where the report equals the command and a deviation therefore means an intervention, not inaccuracy; 3 for a `measured` one; minimum 1.
- **No reaction:** if no transit state and no position change was observed by the deadline, or the member is unavailable, the result is `actuator_no_reaction`; if a movement started but no resting observation arrived by the deadline, `movement_not_finished`. Both are handled by command verification (N1) and never treated as manual operation.
- **A movement that starts in `idle`** is external. On platforms that report transit states this is reliable, because every movement has a start report.
- **Reversal:** a moving observation in the direction opposite to the commanded one during `expecting` or `moving` is external at once, without waiting for the end.
- **Platforms without transit states:** a position change beyond the tolerance in `idle` is external; during `expecting`, changes are attributed to the own command until the evaluation.
- **Unavailable gap:** returning with the same observation is nothing. Returning with a different position is `moved_during_downtime` and counts as external.
- **Context:** a user ID on a report that arrives within the first seconds after a *foreign* command is recorded as a hint for diagnostics ("moved from the dashboard"). It never decides, and its absence proves nothing (guardrail 6).
- **External movement** arms a dam ([section 3](#3-the-two-dams)) and sets the owner of the position to `user`.
- **Glass calibration (C2)** applies to shading targets only. The tracker compares commanded and reported motor positions, both on the motor scale, so the calibration never enters the comparison.

**The tracker measures itself.** For every own movement it records, per member, the latency from the command to the first report, the time to the resting report, and the deviation between the commanded and the reported end position, and keeps the last values and simple statistics (count, median, maximum) in the diagnostics. This is how a user finds the right report delay and travel times, and how a maintainer sees a platform misbehave. Nothing is tuned automatically from these values.

Not measured and therefore covered by design assumptions rather than data: a second command during travel (the expectation is reset, see above), the real command latency (covered by the start allowance and visible in the diagnostics), and movements from a vendor's remote. Blocks C06 and H15 are no longer blocked by measurements.

### 8.4 Calculated positions and drift

- **What command verification (N1) can and cannot know.** With a `calculated` position, verification can establish only that the **actuator did not react**: the member is unavailable, no transit state appeared, the position did not change. It can never establish that the curtain arrived. Reason codes, entity names and documentation must not claim more: there is no "confirmed" and no "arrived", only `sent`, `actuator_no_reaction`, `movement_not_finished` and `command_failed` (the service call itself raised an error). With a `measured` position the same codes are used; the documentation may then say that the reported position is the drive's own.
- **Drift.** After a blocked or interrupted movement the calculated position is wrong until an end position references it again. The core keeps, per member, a flag **position reference**: `referenced` or `uncertain`. It becomes `uncertain` after a frost phase, a frost waiver or a release by sun in which the member was moved; after a movement that was stopped from outside; after `movement_not_finished`; and after `moved_during_downtime`. It becomes `referenced` again by any complete movement into an end position (0 or 100), whoever commanded it. This is the best available signal, not a proof: a curtain that is still stuck is not referenced by it either, and the documentation says so.
- **Hint event.** When the flag turns `uncertain`, one event is fired (`position_may_be_inaccurate`): shading positions can be off until the next end position. The flag is visible in the window's diagnostics. It changes no decision; in particular it never blocks a movement.
- **Reference run.** An action "reference run" drives a window fully into an end position (open by default) so the actuator counts from a known point again. It is a request of class comfort: lockout protection, maintenance lock, dry-run, an active protection event and frost protection apply to it like to any own movement; during frost it therefore needs a waiver first. It is one of the actions of F1 (block H07). The integration never starts a reference run by itself.
- **Members without `set position`** and members without position feedback have no drift in this sense; the flag stays `referenced`.

---

## 9. Several covers operated as one window

Requirement: covers that sit side by side, are always operated together and are never addressed individually by an automation, only by hand at a vendor's remote. They may differ in size, travel time and glass measurements. For the user the unit is one window with one device and one status; members appear only where they differ. Shading positions must work for such a unit.

> **Decision 7 — How such a unit is modelled.** Recommendation: **(d) a window has one or more members that are always moved together.**
>
> | Option | Verdict |
> |---|---|
> | (a) Reject Home Assistant cover groups | Fails the requirement. |
> | (b) Accept a group entity only in the degraded mode of N2 | Fails the requirement: no shading positions, which the roof window profile needs. |
> | (c) Accept the group entity as the unit, command and observe it as one cover | Commanding works. Observing does not: a group reports a transit state as soon as one member moves and the mean of its members as position. With unequal travel times the mean passes through values no member has, a hand-moved member shows up as a fractional change of the mean that depends on the group size, capabilities and command verification per member are impossible, and members with different glass measurements cannot get different targets. |
> | (d) One window, several members: commanded together, observed individually | Meets the requirement. Costs: decisions and status carry per-member detail; configuration needs a small per-member part. |
>
> If the owner decides for (d), feature N3 of the brief changes from "exactly one cover, which may be a cover group" to "one or more covers operated as a unit". That is a change to the brief for the owner to make.

Rules for option (d):

- **Configuration.** The user selects one or more cover entities. If a selected entity is a Home Assistant cover group, the configuration resolves it into its members, recursively, and shows the result before it is saved; the members are stored, never the group entity. Members are listed only where they differ: measurements, travel times, and what the capability profile found.
- **Validation.** "A cover belongs to at most one window" applies per member. A group whose members are partly used by another window is refused with an explanation that names the member.
- **Commands** go to every available member. Inside a window, the staggering gap applies between members as it does between windows, because the rule exists per motor; it can be switched off per window. Fire is never staggered.
- **Observation** is per member, each with its own tracker, capability profile, travel times and command verification. The window is moving as soon as one member moves and until the last member has settled. The window makes **two separate statements**, because one number cannot carry both. **Position:** one number as soon as all members report the same position within tolerance, whatever was last commanded (the rounded mean of the reports; if the members have different tolerances, the smallest one decides whether the reports agree); otherwise none, and the members' values are shown individually. It is never the position of the first member: with unequal members that would state as the window's position a value that only one of them has. A window with a single member therefore always has a position when its member reports one, also right after it was moved by hand. **All members at their commanded targets:** yes, no, or cannot be judged, measured per member against its own last commanded target, which is part of the persisted state (section 11), within its own tolerance. "No" takes precedence: the question is whether all members are at their targets, and a single "no" refutes it. "Cannot be judged" is the answer only if no member says "no" and at least one cannot be judged (no position report, unavailable, never commanded). Members that stand correctly at different targets, as in geometric shading with unequal members, give "yes" and no position. The window-level capabilities are the lowest common denominator; F7 explains which member limits what.
- **A member that is unavailable:** the others are commanded; the status shows `member_unavailable` with the member; when it returns it is brought to the common target, and that is an own movement. If all members are unavailable, the window is unavailable.

> **Decision 8 — A single member moved by hand.** Recommendation: the override applies to the **whole window**. The other members stay where they are; nothing follows the hand-moved one. Every member stays operable by hand on its own, at its own remote or button; the integration neither prevents that nor corrects it while the dam holds. When the dam ends, the recompute brings all members to their targets. Reason: the person's intent is about the room, not about one motor; and one window must keep one status. *Rejected:* an override per member (four dams, four end times and a status that can no longer be stated in one sentence); and letting the other members follow the hand-moved one (a hand movement that triggers three motors is the kind of surprise the integration exists to remove).

> **Decision 9 — Geometry for members with different glass measurements.** Recommendation: **one decision, mapped per member.** The shading layer decides in a quantity that does not depend on the member: the height above the floor up to which the sun may enter (the "ray height" that follows from the permitted penetration depth and the sun position). Each member translates that height into its own position with its own measurements and its own glass calibration.
>
> The glass calibration (C2) is per motor anyway, so a per-member mapping exists in any case; the only question is whether measurements may differ too.
>
> Neutral example, vertical glass for simplicity: two members with the same sill height of 0.9 m, glass heights 1.4 m and 0.8 m, permitted depth 1.0 m, sun straight ahead.
>
> | Sun elevation | Ray height | Large member | Small member | Same percentage for both |
> |---|---|---|---|---|
> | 50° | 1.19 m | 21 % | 36 % | 21 % for both: the small member lets the sun in only 0.90 m (darker than necessary). 36 % for both: the large one lets it in 1.18 m. |
> | 60° | 1.73 m | 59 % | 100 % | 59 % for both: small member 0.79 m. 100 % for both: large member 1.33 m, a third more than permitted. |
>
> Consequences. C1: measurements per member, orientation and field of view per window. C2: per member, as before. F3: the pitch is per window, the glass measurements per member. Status: the members' targets and positions are attributes of the window; the decision record carries the ray height and the per-member positions. The window itself shows a target only if all members have the same target, and a position only under the rule of the next paragraph. Motor protection is judged on the largest change among the members. *Rejected:* one set of measurements and the same percentage for all members. It is simpler and perfectly adequate when the members are equal, which is why members **inherit the window's measurements unless they state their own**; with unequal members it shades visibly unevenly, as the table shows. A roof window example with a real pitch follows with block C09, when the roof geometry is specified.
>
> **Members above each other: one element, one curtain edge.** Members of a window need not sit side by side. A common roof element is a matrix of two rows: larger windows above, smaller ones below, each with its own shutter, controller and remote. For shading, the element shall act like a single tall window. This needs no special mode, only one more measurement: per member, next to its glass height, the **offset of its top edge within the element**, measured from the top of the element along the glass. Members that sit side by side have the same offset. The shading layer computes the required curtain edge **once for the element**, as the covered length `e` measured from the top of the element (for vertical glass: element bottom above the floor plus element height, minus the ray height; clamped to the element). Each member covers the part of that length that falls into its own range: `covered = clamp(e - offset, 0, glass height)`, and its position follows from `covered / glass height` through its own glass calibration.
>
> Neutral example: upper row with offset 0 and glass height 1.0 m, lower row with offset 1.1 m (the frame in between counts) and glass height 0.6 m.
>
> | Curtain edge `e` | Upper members | Lower members |
> |---|---|---|
> | 0.4 m (in the upper row) | 0.4 of 1.0 m covered: position 60 | nothing covered: fully open |
> | 1.05 m (in the frame) | fully closed | nothing covered: fully open |
> | 1.4 m (in the lower row) | fully closed | 0.3 of 0.6 m covered: position 50 |
>
> If the edge lies in the lower row, the upper members are closed and the lower ones drive to the computed value; if it lies in the upper row, the upper members close partly and the lower ones stay open. The offset is a per-member measurement like the glass height and is configured with it (block H11); a member without an offset has offset 0, which is the side-by-side case.

---

## 10. Protection events

### 10.1 Trigger, direction, rank (D1, D2, D6, D8)

A protection event has a trigger source (binary, a list of states, or a number with a threshold), a direction (open or closed), a unique rank, a waiting time after its end (default 30 minutes), an optional sleep-room exception per window, and a maximum duration for the watchdog.

The trigger has three states. **Active** and **inactive** come from a value of the source. **Unknown** (source unavailable or unknown) changes nothing: an active event stays active, an inactive event stays inactive (D6). The state of each event is persisted, so after a restart an event whose source is still unavailable stays what it was; an event whose source reports active at start is active from then on (caught up).

**A blind protection must not stay silent.** Holding the last state (D6) is the right behavior, but nobody notices that the protection has stopped seeing. If the trigger source of a protection event has been unavailable or unknown for longer than a configurable time (default 1 hour), a repair issue names the event and the source and an event is fired (`protection_source_blind`). The behavior of the event itself does not change. The same applies to lockout protection: a blocking contact that is unavailable counts as open, which means nothing closes any more at that window, not even at storm. After a configurable time (default 1 hour) a repair issue and an event say so (`lockout_contact_blind`). Both issues disappear by themselves when the source has a value again.

### 10.2 Return after a protection event (D5)

> **Decision 14 — The return to the manual position and the override dam.** The return is a wish of class comfort from the protection layer with the reason `protection_return_manual`. As a comfort wish the manual override dam would hold it back, and that dam has to be armed for the return to happen at all. Decided: the manual override dam lets exactly this wish pass, under four conditions. (a) Only if the override is still armed when the waiting time after the protection event has passed; otherwise there is no return wish and the window is evaluated normally. (b) The person-at-the-window dam still holds the return back. (c) All constraints apply to it: lockout protection, the ventilation floor, frost protection, the direction of the wish. (d) The waiting time of this section has passed first; the end time of the event is persisted for that (section 11). Every other gate rule applies as to any comfort wish: maintenance lock, operating mode, pause, movement in flight, motor protection, backoff, staggering, dry-run. *Rejected:* a fourth wish class for the return. It would widen every table of constraints and gate rules for the sake of a single case.

When an event starts, the window remembers its position and the owner of that position. When the event has ended and its waiting time has passed without a new activation, the window is recomputed. Only if the remembered owner was `user` **and** the manual override dam is still armed (decision 4), the remembered position is restored one to one; a remembered position that is unknown is skipped. Fire never returns automatically.

### 10.3 Watchdog (D9)

> **Decision 10 — What "released" means.** Recommendation: an event that has been active longer than its maximum duration is **released for this activation**: its layer has no opinion any more (`watchdog_released`), the return of section 10.2 runs, and a repair issue names the event and the source. The release lasts until the trigger has been genuinely inactive once; only a new activation makes the event effective again. A source that is unavailable does not end the release. This does not contradict D6: D6 says that *missing data* neither triggers nor releases; the watchdog is a separate, explicit and reported decision that a *plausible maximum* has been exceeded, whatever the source says. Default maximum 12 hours, configurable per event, 0 disables it. Not for fire *(decided)*. *Rejected:* releasing only when the source is unavailable (a stuck "active" is the more common failure); releasing without the "inactive once" condition (the event would re-arm at the next recompute).

Locks: a maintenance lock or a pause that lasts longer than seven days is **reported** as a repair issue and never released automatically, because both were set by a person on purpose.

---

## 11. Persistence and restart

Persisted per window, versioned, all timestamps timezone-aware (naive ones are rejected at the boundary):

- owner of the position; per member the last own command (identifier, target, direction, time, wish class, context ID) and the last observation. The identifier is what lets a result be matched to its command. The last commanded target per member is what the statement "all members at their commanded targets" of section 9 is judged against (the window's position does not depend on it), and what lets a reload during a movement continue the same expectation instead of seeing a manual movement or sending the command again;
- per member the **command backoff as facts**: the number of attempts of the current command and the time of the last attempt. The next retry time is not stored; it is computed from these two facts with the current settings. A reload right after a failed attempt therefore cannot trigger an immediate second command;
- manual override dam: armed at, end rule with its absolute end if it has one, remembered position;
- person-at-the-window dam: ends at;
- per protection event: state, active since, **ended at**, **released at**, remembered position and owner. The two times are separate fields with one meaning each: "ended at" is when the trigger became inactive, "released at" is when the watchdog released the event (section 10.3) while its trigger was still active. An event keeps its "released at" when the trigger becomes inactive later, so both times can be set. The waiting time of section 10.2 runs from "released at" if it is set, otherwise from "ended at". An active event that is not released has neither. The times are persisted, not a remaining duration or a deadline: the waiting time of section 10.2 is configuration and is applied to the end time whenever it is evaluated, so it survives a restart and follows a changed setting;
- fire: unacknowledged flag;
- episodes: as listed in [section 7](#7-episodes);
- external request: position, reason, expires at;
- latched day type per date (today and tomorrow);
- time of the last own comfort movement (the motor protection clock);
- last known values of inputs that are held (frost state, season, protection triggers);
- frost waiver: active until; per member the position reference flag (`referenced` / `uncertain`);
- in dry-run only: the simulated commands of [section 2.3](#23-the-gate), kept apart from the real state and discarded when the window is armed.

Per installation: the seed for random offsets.

**Restart reconciliation** is a pure function of (persisted state, live observation) with one of these results: `first_setup` (nothing persisted: owner `unknown`, no dam); `unchanged` (the live position matches the last observation or the last own target within tolerance); `moved_during_downtime` (it does not: owner `user`, the manual override dam is armed with the default end rule); `expectation_expired` (an own command was pending: handled as `movement_not_finished`). Dams and episodes whose end lies in the past are dropped. After reconciliation the window is recomputed, and no decision is made before its members are available.

Removing a window deletes its persisted state (N4).

---

## 12. Privacy when lights are on (F2)

> **Decision 11 — Inputs of F2.** Recommendation: per window, a list of **light entities** (any on = light on), and "dark outside" as **sun elevation below a threshold** (default 0°), or alternatively the outdoor brightness source of A4 below its threshold if one is configured. The wish is the privacy position, lowering only. It starts when both conditions have held for a short delay (default 1 minute) and ends when the lights have been off for a longer delay (default 5 minutes) or it is no longer dark. Unavailable lights count as off (no privacy wish; comfort steps aside). *Rejected:* a room or area lookup for lights (installation structure is not an API, brief section 6); deriving "dark" from the part of the day (F2 is meant to act *before* the evening time).

---

## 13. New windows

> **Decision 12 — New windows start in dry-run.** Recommendation: yes. A window becomes active only by a deliberate step ("arm"), after the user has compared its decisions with reality. It also makes "one controller per window" the default during migration. *Rejected:* armed by default with a warning text; warnings are not read, and the first wrong movement on a live system costs more trust than one extra click.

---

## 14. Module map of the domain core

Everything under `custom_components/roller_shutter_suite/core/`. No import from `homeassistant` and none from the rest of the integration. Time, sun, sources, actuator and storage reach the core only through ports.

| Module | Content | Block |
|---|---|---|
| `model` | position, wish, wish class, constraint result, gate outcome, decision, source value, observation, capability profile, window configuration (resolved), window state (persisted), world snapshot | C01 |
| `reasons` | the closed enumeration of [section 5](#5-reason-codes) | C01 |
| `ports` | protocols: clock, sun, actuator, storage | C01 |
| `settings` | partial settings with the "inherit" marker, resolver global → group → window, provenance | C02 |
| `arbiter` | layer, constraint and gate registries; evaluation; fire bypass; dam mechanism; effective pause / mode / lock over three levels | C03 |
| `constraints/` | direction, frost (C03); sleep exception, no intermediate position (C07); lockout, ventilation floor, rain (C08) | as noted |
| `schedule` | day types with latch, triggers and clamps, parts of the day, random offsets, next planned action; the schedule layer | C04 |
| `tracking` | normalizing reports, tracker per member, expectation window, window-level view over members | C06 |
| `dams` | arming and ending the two dams | C06, C07 |
| `protection` | events, trigger state machine, return, watchdog; the fire and protection layers | C07 |
| `geometry` | sun relative to the window, ray height, glass calibration in both directions, roof pitch | C09 |
| `episodes`, `shading` | episode life cycle; shading and solar heating layer | C10 |
| `comfort` | sleep layer, privacy layer, external request layer | C11 |
| `persistence` | versioned snapshot of the window state, migration, restart reconciliation | C12 |
| `engine` | the façade the Home Assistant layer talks to: `recompute(snapshot) → decision`, `observe(member, report)`, `on_command_result(...)` | C03, extended by later blocks |

The **time-lapse simulation** (N6, block C05) is a development tool and lives outside the shipped integration, under `tests/sim/`. It implements the ports with a synthetic world and drives the `engine` the same way the runtime does.

Doors kept open, as places in the model and nothing more: covering type (C15); a condition input of the morning trigger that is always fulfilled (A7); further protection events are only more instances of section 10 (C13); the temperature condition of shading is a list of tiers with one entry (C3b, C11); the schedule's targets are looked up through a profile key that has one value (D7, E9b).

---

## 15. Decisions of the project owner

| # | Decision | Recommendation |
|---|---|---|
| 1 | Window interaction as constraints, not as a layer | Yes: a floor under the comfort wishes |
| 2 | Position of the external request layer | Below sleep mode, above privacy |
| 3 | Frost when the temperature is unavailable | Hold the last state for at most 24 h, then inactive plus repair issue |
| 4 | Override duration during a protection event | The clock keeps running; restore only if still armed |
| 5 | Wall button on the Home Assistant path during a maintenance lock | Refuse, with a reason event |
| 6 | Source of the season | Optional source, else date range, else one evening position |
| 7 | Several covers as one window | Option (d); changes the wording of N3 in the brief |
| 8 | A single member moved by hand | Override for the whole window; the others do not follow |
| 9 | Geometry for unequal members | One decision (ray height), mapped per member; members inherit the window's measurements unless they state their own |
| 10 | Watchdog: meaning of "released" | Released for this activation until the trigger was inactive once; 12 h default; never for fire |
| 11 | Inputs of F2 | Light entities per window; dark = sun elevation below a threshold, or the brightness source |
| 12 | New windows start in dry-run | Yes |
| 13 | Frost protection | Limits opening to the frost position; inherited source; waiver until the next morning; movements by hand exempt; optional release by sun, built with C10; preventive only |
| 14 | Return to the manual position after a protection event | A comfort wish that the manual override dam lets pass, under four conditions; no fourth wish class |

Also worth a look, because they are proposals stated as rules: the position reference flag, the hint event and the reference run as an action of F1 (section 8.4); the default of one hour before a blind protection source or a blind blocking contact is reported (section 10.1); dry-run as the last gate rule with simulated commands (section 2.3); the final layer order of section 2.1, which follows the brief's starting order except for decisions 1 and 2; the order of the gate rules in section 2.3; the latch of the day type (section 6.3); an unavailable blocking contact counts as open (section 2.2, constraint 3); an unavailable window contact sets no ventilation floor (constraint 4); fire needs an acknowledgement before the window returns to normal operation (section 2.4); the staggering gap also applies between the members of one window (section 9); members of a window without position feedback are mapped to open or close at 50 (section 8.1).
