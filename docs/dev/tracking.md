# The movement tracker and the dams

The arbiter decides where a window should be; the tracker says who moved it. Every movement of a member is judged once: the integration's own, or somebody else's. What the tracker attributes wrongly either freezes the automation or overrules a person, so its rules are those of section 8 of the [domain design specification](../architecture.md) exactly, and this page says how they look in code. The dams it arms are gate rules of the [arbiter](arbiter.md#dams); the data types are in [The core model](core-model.md).

| Module under `core/` | Content |
|---|---|
| `tracking.py` | normalizing reports, the tracker per member, the reference flag, the self-measurement |
| `dams.py` | arming and ending the two dams |
| `arbiter/gate.py` | the deadline (`member_expectation_end`), the settle time (`settle_time`), every wake-up (`wake_ups`), and what the gate reads of the dams |
| `model/tracking.py` | what the tracker keeps per member, what it measures, the events |
| `engine.py` | the façade: `observe`, `elapse`, `after_send`, `resume`, `sleep_mode_switched_on`, `position_uncertain`, `wake_ups` |

## What the runtime feeds in, and what comes back

The core receives observations, never states: the runtime reduces a state of Home Assistant to an `Observation` (`members.py`: resting, moving up, moving down, unavailable, and a position if the member reports one). Every call is a pure function of its arguments, and every call that can change something returns a `Transition`: the state after the call, and the events it raised (`TrackerEvent`: a code of the group "tracker and life cycle", with the member, a position, the count and the threshold, or the user of a dashboard as attributes). The caller persists the state and hands the events on; the Home Assistant layer (block H10) puts them on the bus and into the logbook.

| Call | When | What it does |
|---|---|---|
| `Engine.observe(state, member_id, observation, now, last_decision, *, dry_run, user_id=None)` | for every state change of a member | normalizes and follows the member (below); `last_decision` is the decision of the last recompute; `user_id` the user in the context of the report, a hint only |
| `Engine.elapse(snapshot, last_decision)` | before every recompute, and at every wake-up | judges every member whose settle time or deadline has passed, ends the dams whose time has come, turns the person-at-the-window dam into an override, and learns the end of an override that ends at the next part of the day |
| `Engine.after_send(snapshot, decision, command_ids)` | after a send | `state_after_send`, which sets the tracker of every addressed member to `expecting` and counts a comfort movement, and the event of the daily count once it is due |
| `Engine.on_command_result(state, result)` | when the actuator reports | a failed command is not expected any more |
| `Engine.resume(state)`, `Engine.sleep_mode_switched_on(state)` | the "resume automation" button and action (H06, H07); sleep mode switched on (C11) | the manual override ends at once |
| `Engine.position_uncertain(state, member_ids)` | a frost phase, a frost waiver or a release by sun in which a member moved (C10, C11) | the reference flag turns `uncertain` |
| `Engine.wake_ups(state, now, *, dry_run)` | after every recompute | every instant the caller has to wake the window at: the deadline of every pending own command, the end of every settle time, the end of each dam, the end of an empty room |

**The runtime computes no time of its own**, and neither does the time-lapse simulation: every timer comes from `wake_ups`, and at each the caller calls `elapse` and recomputes. The deadline is the one of section 8.3 (`member_expectation_end`: report delay + 10 s + travel time × share of the travel × 1.5 + 5 s); the report delay is the reporting time of the capability profile, the delay of an event-driven platform or the poll interval of a polled one. The settle time is 2 s, and for a foreign movement on a member that shows no transit state it grows by the member's reporting time, so a person's movement on a polled platform is judged once, at its end.

**A reporting time nobody stated** (block H10, ruling of the project owner of 2026-10-01): the reporting kind and the reporting time are stated by the user per member and have no default. While the time is unknown, the tracker does not follow the member at all (`arbiter.capabilities.is_tracked`): it keeps the observations and judges nothing, no expectation after a send, no external movement, no "no reaction", the answer "unknown" of the start-up grace and decision 15, never a guess of zero. Only the gate and the timers still need a deadline for its commands; they count with the largest reporting time a user can state (`MAX_REPORTING_TIME`, ten minutes, `reporting_time_bound`), so a command counts as pending rather longer than shorter. A window with such a member cannot be armed.

The runtime controller of the Home Assistant layer calls them as the simulation runner does (`tests/sim/runner.py`); [The runtime](runtime.md#the-movement-tracker-in-the-runtime) says when, and how it treats an expectation that is left over from before a start.

## The state machine

```text
                own command (state_after_send)
      ┌─────────────────────────────────────────────┐
      ▼                                             │
   idle ──► expecting ──► moving ──► settling ──► idle (judged once)
     │          │            │           ▲
     │          │ reversal   │ reversal  │ a report of rest
     │          ▼            ▼           │
     └──────► external: arms a dam, owner "user"
```

Per member, `MemberTracking` in `MemberState.tracking` (persisted, so a restart continues the same movement):

- **Normalizing.** An observation equal to the member's last one (`MemberState.last_observation`) is dropped: `observe` returns the same state object and no event. That removes an identical write, a rewrite of an unchanged state with a new change time, and an attribute-only write that the same resting state follows. Nothing is ever decided from a change time.
- **`expecting`.** A send sets it with the command (`command_id`); a new own command replaces the expectation as a whole. A member without position feedback is never tracked.
- **`moving`.** The first report of a movement (a transit state, or a changed position) starts it, and its instant is the start of the movement (`moved_at`). A transit state against the commanded direction is a **reversal**: external at once.
- **`settling`.** A report of rest ends the movement when a transit state was seen during it, or when the member stands within its tolerance of the target. A member that shows no transit state writes rest on every report, so its reports in between stay `moving`, attributed to the own command, until the target or the deadline.
- **Judging** happens once, the settle time after the report of rest, with the position reported by then: within the tolerance of the target (2 for a calculated position, 3 for a measured one, the stated one if any; a user states it per member in `CAPABILITY_SETTINGS`, 1 to 20 percent, to widen it for a cover that settles off its target) it is the own movement, the expectation is consumed, and the owner stays the integration; outside it somebody intervened, and the movement is external.
- **The deadline.** Nothing seen by then is `actuator_no_reaction`; a movement still under way is `movement_not_finished`. Both are for command verification (block H15); neither arms a dam nor changes the owner. A member without transit states that came to rest short of its target is judged at the deadline as if it had settled there. A report of rest without a position cannot be judged; at the deadline it is not finished.
- **`idle`.** A movement that starts here is external. With a transit state that is reliable at its start, so the movement is reported and its dam armed at once: protection must not close a shutter on a person who is still moving it, and the end of the movement only brings the position the person chose up to date. A change of position beyond the tolerance on a member without a transit state is judged after its settle time.
- **An unavailable gap.** The last available observation is kept (`before_gap`). A return with the same observation is nothing; a return with another position is `moved_during_downtime` and counts as external; a return in motion is a movement that starts in `idle`. A gap during an own movement continues the expectation. A deadline that passes during the gap ends the expectation (`actuator_no_reaction` or `movement_not_finished`) but not the gap: `before_gap` is kept, so a person who moved the cover while its link was down is still seen as `moved_during_downtime` on its return, and the next decision does not overrule them. A return at the target of the last own command is nothing, as in the restart reconciliation (section 11), but only after a gap in which a deadline ended the expectation of that command (`MemberTracking.ended_in_gap`, next to `before_gap`): the own movement may have finished during the gap. After a gap that began when the own movement had been judged, a return at the old target is somebody's movement (narrowed with block H10, from the review of C06). A member that went away while settling is judged when it returns, whatever the deadline.

**External movements.** The tracker raises `manual_detected` (the window, with its position if the members agree) and `manual_detected_member` (the member, its position, and the user of a dashboard seen within the first five seconds of the movement, a hint that never decides), and the dams module arms a dam. **A movement detected while it is still under way** (at its first transit state in `idle`, or a reversal) raises these events, and `override_started` or `person_at_window_started`, **without a position**: it is not yet the position the person chooses, and a platform that reports the transit state before the position (`end_only`) still reports where the movement began. The dam remembers the position once the movement has come to rest, and the decision record and the status show it from then on; no second event is raised. A movement judged at rest carries the position it rests at. One movement of the window arms its dam once: a member detected while another member is still moving, or whose movement began before the dam was armed (on a member with a report delay, up to that delay earlier than it was seen), belongs to the same movement of the window and raises its member event only (decision 8). **In dry-run** the only event is `external_movement_observed`, once per foreign movement, and nothing else changes: no dam, no owner, no reference flag.

**The window-level view.** The window is moving from the first member that moves until the last one has settled: `WindowState.moving`. The gate rule "movement in flight" reads it, so a comfort wish never interrupts a person, also on a member without transit states.

## The dams

`dams.py` arms and ends; the gate only reads ([The arbiter](arbiter.md#dams)).

- **Arming.** While a protection wish won the last decision, the person-at-the-window dam (default 15 minutes, `person_at_window_duration`); otherwise the manual override dam with the position the person chose and the configured end rule (`override_end_rule`, default `next_part_of_day`). Without a decision nobody knows whether a protection event is under way, and the person-at-the-window dam is armed. The owner becomes `user`. Every arming raises `override_started` or `person_at_window_started`; a second movement by hand later arms the override again, with a new end.
- **The end rules of the override** (E2): `fixed_minutes` ends at arming + `override_minutes`; `next_part_of_day` ends at the next boundary of the schedule, which `elapse` learns from `evaluate_schedule` (while the schedule cannot say, the dam holds); it does so also on a window whose schedule is switched off, because the parts of the day exist without the schedule moving anything, and a rule that never ended there would hold the override for good; `shading_episode_end` ends with the shading episode it was armed during; `room_empty` ends once the presence source (`override_presence_source`, on means occupied) has said "empty" without interruption for `override_room_empty_after` (`ManualOverrideDam.room_empty_since`; a source without a value never says "empty"). A rule the window cannot meet at arming (no episode running, no readable presence source) is replaced by `next_part_of_day`. `resume` and switching sleep mode on end it at once. Every end raises `override_ended`; the window is recomputed, nothing is replayed.
- **During a protection event** the clock of the override keeps running (decision 4): every end is an instant or a condition.
- **The person-at-the-window dam** ends by itself. If protection still won the last decision, protection reasserts itself through the recompute; otherwise the dam turns into a manual override with the person's position (`override_started`), so the comfort logic does not undo what the person did. Unknown counts as "turn".

The settings of the dams belong to the function `manual_override`, which falls back on a fault; the fault values are the default end rule and the default durations, and a faulty presence source is configured but blind, so a data fault never lets the automation overrule a person earlier than the default would (ruling 4 of the project owner for this block). `test_fault_values.py` judges them in the situations of `fault_value_situations.py`.

## The position reference flag

`MemberState.position_reference` turns `uncertain` after an own movement that was stopped or reversed from outside, after `movement_not_finished` and after `moved_during_downtime`, and through `position_uncertain` for the frost cases; it turns `referenced` again after any complete movement into an end position, whoever commanded it. When it turns `uncertain`, `position_may_be_inaccurate` is raised once. Members without "set position" and members without position feedback keep `referenced`. The flag changes no decision; it is not a proof that a curtain is free (section 8.4).

## The daily count of comfort movements

`WindowState.comfort_movements`: the local date, the count, and whether it was reported. A send of class comfort counts one movement, however many members it addresses; a take-over, protection and fire count nothing, and neither does the completion of a command for a member that returns. A new local day starts at one. Above `comfort_movements_threshold` (default 40) `after_send` raises `comfort_movements_threshold` once per day, with the count and the threshold as attributes. It blocks nothing.

## How to read the self-measurement

For every own movement that came to rest on a member whose reporting kind is `event_driven`, whatever its reporting time, the tracker keeps three samples in `MemberState.self_measurement`: the latency from the command to the first report, the time from the command to the report of rest (both in milliseconds), and the deviation of the reported end position from the target (in percent). The last twenty samples per value are persisted with the member state, so a restart keeps them (ruling of the project owner). `SelfMeasurement.latency`, `time_to_rest` and `end_deviation` give count, median and maximum; the median, never the mean, so that one movement cut short by the overload protection of a motor does not distort it.

A polled member is not measured: it reports on its grid, and its numbers would say nothing about the cover. An event-driven member with a delay is measured since the reporting kind and the reporting time were separated (ruling of the project owner of 2026-10-01): its latency is how a user finds the reporting time to state.

How to use them: a median time to rest well below the configured travel time of its direction, less the reporting time, says the travel time is too long; above it, too short. A median latency of several seconds says that the reports of the platform are delayed by about that much; the maximum latency is the reporting time to state. A maximum deviation of a few percent on a measured position says the tolerance may need to be stated larger. Nothing is tuned automatically.

## Testing

`tests/core/test_tracking.py` walks the tracker through every transition with the driver of `tests/core/tracking_kit.py`; `tests/core/test_dams.py` covers every end rule and the wake-ups; `tests/core/test_comfort_count.py` the daily count; `tests/core/test_model_tracking.py` the types. The time-lapse simulation runs every behaviour profile in every case (`tests/core/test_sim_tracking.py`), and the year scenario, with a movement by hand of every window every day, asserts that no own movement ever arms a dam ([The time-lapse simulation](simulation.md)).
