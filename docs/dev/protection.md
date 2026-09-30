# Protection: fire, protection events, the return and the watchdog

The integration exists first of all to keep a house safe when the weather turns and to open every escape route when a smoke detector fires (goals G1 and G2 of the brief, features D1 to D9). This page explains how the fire layer and the protection layer of the core work: the state machine of a trigger, the life cycle of an event from its start to the return, the watchdog, the fire alarm and its acknowledgement, and what the Home Assistant layer feeds in. The rules come from sections 2.1, 2.2, 2.4, 3, 10 and 11 of the [domain design specification](../architecture.md); the arbiter that evaluates the layers is described in [The arbiter](arbiter.md).

| Module under `core/` | Content |
|---|---|
| `model/protection.py` | an event of the house as a value: trigger, direction, rank, waiting time, maximum duration; the marker of a list that cannot be read |
| `protection/trigger.py` | what a trigger source says: active, inactive, inside the band, unknown |
| `protection/blind.py` | the clock of a source without a value, one for every kind of source |
| `protection/events.py` | the life cycle of an event: start, end, watchdog, waiting time, return; the protection part of `Engine.elapse` and of `Engine.wake_ups`; the function the restart judges an event with |
| `protection/layer.py` | layer 2, the protection events |
| `protection/fire.py` | layer 1, the fire alarm, and its acknowledgement |
| `constraints/sleep_exception.py` | constraint 2, the sleep-room exception |
| `constraints/no_intermediate.py` | constraint 7, no intermediate position during a protection event |

## The settings

| Setting | Kind | Default | Fault value | Meaning |
|---|---|---|---|---|
| `fire_source` | optional reference | none | configured, but blind | the fire alarm of the house, an on/off source |
| `protection_events` | list | no events | configured, but unreadable | the protection events of the house |
| `protection_sleep_exception` | list | no exception | no exception | the events that must not open this window while sleep mode is active |
| `source_blind_after` | duration, 1 minute to 1 week | 1 hour | 1 hour | how long a source may be without a value before it is reported as blind |

All four belong to a function that falls back on a fault (`fire`, `protection_events`), so a data fault never switches fire or protection off. `source_blind_after` is one setting of the house for every kind of source (ruling of the project owner of 2026-09-29): the trigger sources of the events, the fire source, and the external pause entity of the Home Assistant layer, whose repair issue reads the same value (`controls.py`); from block C08 the blocking contact of lockout protection uses it too.

**One stored event** is an object with these keys:

```json
{
  "event_id": "storm",
  "source": "binary_sensor.example_storm",
  "trigger": "binary",
  "invert": false,
  "direction": "closed",
  "rank": 10,
  "waiting_time": 1800,
  "max_duration": 43200
}
```

- `trigger` is `binary` (on is active; `invert` makes off active, for a "calm" sensor), `states` (active while the state is one of `states`, compared as text: `on` and `off` for a switch, a whole number without a fraction) or `threshold` (active from `threshold` on, inactive below `threshold - hysteresis`; with `invert` active at or below the threshold and inactive above `threshold + hysteresis`). Inside the band the persisted state holds, so the trigger does not flap at the value.
- `direction` is `open` or `closed`. There is no default and no cautious direction: whether hail means up or down depends on the glass and the curtain (section 6 of the brief).
- `rank` is a whole number from 1 to 1000; the higher rank wins. Hail ranks above storm by default in the forms of block H08.
- `waiting_time` (default 30 minutes, at most a day) and `max_duration` (default 12 hours, at most a week, zero switches the watchdog off) are whole seconds.

**Faults are read leniently, field by field** (ruling of the project owner of 2026-10-01). The reader (`as_protection_events` in `core/settings.py`) refuses the list as a whole only when it is no list, an entry is no object, or an identifier is missing, blank or given twice, because the persisted state of an event is found by its identifier; the fault value then applies. Every other key that cannot be read takes its cautious value, and the event names the stored key in `ProtectionEventConfig.faulty_fields`, so that block H08 can report it:

| Faulty key | What applies | Why |
|---|---|---|
| `source`, `trigger`, `states`, `threshold`, `hysteresis`, `invert` | the trigger is blind (`trigger` is `None`): it never starts or ends the event, a persisted state is held | missing data is not good news; nothing is guessed from a trigger that cannot be read |
| `direction` | the event is skipped on that level (`direction` is `None`) | there is no cautious direction |
| `rank` | the event loses against every valid rank (`rank` is `None`); among faulty ranks the order of the list decides | a fault never lets an event win |
| `waiting_time`, `max_duration` | the default | a fault never switches the watchdog off |
| a key that does not belong to the kind (a threshold on a binary trigger), an unknown key | nothing: the key is only named | data written by another version must not cost protection |
| a rank that two events state | faulty on both | a duplicate rank never reaches the arbiter |

**A list that cannot be read as a whole** is `EVENTS_UNREADABLE`, "configured, but unreadable". It is not an empty list, which would take protection away. The layer then holds the window where it is ("leave alone", `protection_event`, with the event as the subject) for every persisted event that is active or still in its waiting time, with the default waiting time and the default maximum duration: the watchdog releases a persisted active event after 12 hours and raises `watchdog_released` without a source. No event starts and none returns while the list cannot be read. Because this hold only leaves the window alone, a movement by hand during it arms the manual override, not the person-at-the-window dam, also for an event that is, as far as anyone knows, still active: nothing would be driven against the person, and the override keeps the comfort layers from undoing the movement (the repair issue of block H08 can say so).

## The trigger

`read_trigger` in `protection/trigger.py` returns one of four readings:

```text
 value of the source ──► active   (the event starts, or stays active)
                    └──► inactive (the event ends, or stays inactive)
                    └──► hold     (inside the hysteresis band: nothing changes)
 no value ────────────► unknown  (nothing changes, the blind clock runs)
```

Unknown is a source that is unavailable or unknown, missing from the snapshot, a value of the wrong kind (text for a binary trigger), or a faulty trigger. It changes nothing (D6): an active event stays active, an inactive one inactive. That is why the state of every event is persisted.

**A blind protection must not stay silent.** While a source has had no value for `source_blind_after`, the layer says why the input is held (`input_held_last_known`; before that `input_unavailable` or `input_unknown`), and `protection_source_blind` is raised once per blind phase, with the event and the source. The behavior of the event does not change. The clock is a `BlindClock` (since when, reported or not) on the persisted state of the event; a value drops it, and the repair issue of block H08 disappears then.

## The life cycle of an event

`advance_event` in `protection/events.py` takes one event, its persisted state, the value of its source and the time, and returns the state after this moment and the events it raised. The layer calls it to judge the trigger live, and `Engine.elapse` calls it to persist, so the two always agree, also when `elapse` has not run first.

1. **Start** (the trigger becomes active): the event is active since now, and it remembers the position of the window, the owner of that position and the manual override that holds now (`override_armed_at`). What was remembered before is taken over only while it still describes the window (`still_remembers`): an event that starts again keeps its own earlier values during its waiting time while the override in force is still the one it remembered and no person has taken the window since, or while its return applies; an event that starts while another event holds the window, waits under the same conditions, or returns, takes over what that one remembered. Otherwise the window is remembered afresh: a person who moved the window during the waiting time is remembered at the next start (a person lowers to 40, a storm, the person opens to 60 in the waiting time, the storm again: after it the window returns to 60), and a released event, whose window was recomputed, passes nothing on. `protection_started`.
2. **Active**: the end position of its direction wins as a wish of class protection with the reason `protection_event`, the highest rank first. The decision names the event and its source as the subject (`WishSubject`, next to the reason and never inside it), and while the source has no value the subject says why the input is held (situation 14).
3. **End** (the trigger becomes inactive): the event ended now (`ended_at`); a release is kept. `protection_ended`.
4. **Waiting time** (from the release if there was one, otherwise from the end; `return_clock_start`): an event that ended without a release answers "leave alone" with `waiting_for_delay`. No lower layer acts, and nothing is driven: the event has ended, so a movement by hand now arms the manual override, and a person-at-the-window dam that ends now turns into one (section 3.2). Active events outrank waiting ones: hail that has just ended does not keep a storm from closing.
5. **Return** (decision 14): when the waiting time has passed, the remembered position is restored, with a wish of class comfort and the reason `protection_return_manual`, if and only if
   - (a) the remembered owner was a person, the remembered position is known, and the manual override that was armed when the event started is still armed (the same arming, not a later one, and neither past its end nor ended by its condition);
   - (b) the person-at-the-window dam does not hold it back (the gate: the return is a comfort wish, and that dam stands before the override dam);
   - (c) every constraint allows it (the arbiter: lockout, ventilation floor, frost, direction);
   - (d) the waiting time has passed. The waiting time is configuration and is applied when it is evaluated, so a changed setting takes effect at once.
   The trigger of the return wish is the end of the waiting time, so motor protection sees it as fresh. The override dam lets exactly this wish pass (the mechanism of block C03). While it applies, the event keeps its return phase; as soon as it does not (the override ended, a person moved the window again), the event forgets its end, its release and what it remembered, and the window is recomputed normally (situation 10).

A persisted event that is no longer configured is dropped.

## The watchdog

An event that is active longer than its maximum duration is **released for this activation** (decision 10): `released_at` is set to the instant the maximum was reached, `watchdog_released` is raised with the event and the source (the one code of the group "why a layer did not act" that an event may carry, ruling of 2026-10-01), and the layer has no opinion for it any more (`watchdog_released`). The return runs from the release plus the waiting time. The release lasts until the trigger has been genuinely inactive once; a source without a value does not end it, and only a new activation makes the event effective again. The watchdog is judged before the trigger, so a release that fell due before a late evaluation (after a restart) keeps its instant and its order before the end. A maximum duration of zero switches it off. It never applies to fire. The repair issue is block H08's.

## The fire alarm

`fire_layer` in `protection/fire.py`, for the one fire source of the house:

- **Active:** open fully, class fire, reason `fire_alarm`, every member, the source as the subject. The fire bypass applies (section 2.4); no constraint applies to fire.
- **Ended and not acknowledged:** "leave alone" with `fire_unacknowledged`. It wins and holds every lower layer back, but moves nothing, so after a false alarm a shutter somebody closes by hand is not reopened. That hand movement arms the manual override (a fire wish is not a protection wish), which protects it after the acknowledgement (situation 3a).
- **Acknowledged:** `Engine.acknowledge_fire(state)` clears `fire_unacknowledged` and raises `fire_acknowledged`; it can be done at any time, also while the alarm is active. Block H07 calls it from its action, block H14 from a button.
- **A source without a value** changes nothing: `WindowState.fire_alarm_active` holds the state of the last value. The blind clock runs as for a protection source (`WindowState.fire_blind`), and `protection_source_blind` is raised with the source and without an event identifier (ruling of 2026-10-01). A faulty stored source (`BLIND_SOURCE`) holds at once; the resolver reports that fault.
- The flag is set at every activation, so a window whose source was removed after an alarm still needs the acknowledgement.

Under a maintenance lock and in dry-run the decision still names the fire wish as the winner (situations 1 and 2), so the Home Assistant layer fires its reason event at once.

## The two constraints

- **The sleep-room exception** (constraint 2, `SLEEP_EXCEPTION_CONSTRAINT`): for a protection wish of an event the window lists in `protection_sleep_exception`, while sleep mode is active, no member is raised. "Sleep mode is active" means that the sleep layer wants a position in this very recompute: the arbiter hands the answers of every layer to the constraints (`ConstraintInput.answers`), because the window configuration has no sleep source. A member without a known position is not raised either. Its cautious result pins every member that would be raised, if the window lists any event at all.
- **No intermediate position** (constraint 7, `NO_INTERMEDIATE_CONSTRAINT`): a protection target that is neither 0 nor 100 after the constraints before it is pinned, so the window is left alone rather than driven halfway; with `frost_applies_to_protection` the frost position counts as the open end.

Both belong to the function `protection_events`. `tests/core/test_constraint_registrations.py` compares the table of section 2.2 of the specification with the constraints `build_arbiter()` registers.

## What the Home Assistant layer feeds in

The core reads every source from the snapshot by its key, never an entity. For block H08, which builds the forms and wires the sources:

- the fire source is an optional reference and reaches the snapshot as every such setting does (`window_sources` in `sources.py`); the trigger sources of the events are inside the list and have to be added to what the runtime reads;
- the runtime calls `Engine.elapse` before every recompute and at every instant of `Engine.wake_ups` (block H10): the release by the watchdog, the end of every waiting time, and the moment a source is reported as blind are among them;
- the events of a transition (`protection_started`, `protection_ended`, `protection_source_blind`, `watchdog_released`, `fire_acknowledged`) carry the event and the source as attributes; the repair issues of a blind source and of a release are H08's, and they read `faulty_fields` for the faults inside an event;
- at a restart, `Engine.judge_protection_event(snapshot, event_id)` judges a persisted event against its live source (block C12): a source that is away leaves it as it was, a source that reports active catches it up.

## Sentences the user pages will need

Block H08 writes `docs/features/protection.md` and `docs/features/fire-alarm.md`. What they have to say:

- A protection event drives a shutter fully open or fully closed, never in between. Several events at once: the one with the higher rank wins; an event that is active wins over one that has just ended.
- The waiting time: after an event ends, the shutter stays where the event put it for this long (default 30 minutes), so it does not go up between two gusts. Then the integration works out what applies now. A position a person had set by hand before the event is restored only if the manual override is still in force by then.
- Whether hail opens or closes is a choice per event; the right answer depends on the glass and the curtain.
- A source that is unavailable or unknown changes nothing: an event stays active or inactive. After the blind time (default one hour, one setting for every kind of source) a repair issue says that the protection is blind.
- The watchdog: an event that lasts longer than its maximum duration (default 12 hours; 0 switches it off) is released and reported; it takes effect again only after its source has been off once.
- The sleep-room exception: a window can say that an event must not open it while sleep mode is on. Fire ignores it.
- Fire opens every shutter at once, in every operating mode, except under a maintenance lock and in dry-run, where the event is still fired. After the alarm nothing moves until somebody acknowledges it: "acknowledge" means telling the integration that the alarm is over and it may go back to normal operation. A shutter closed by hand before the acknowledgement stays closed afterwards.

## Testing

`tests/core/test_protection_trigger.py` (every kind of trigger, the blind clock), `test_protection_events.py` (the life cycle, the watchdog, the return with one test per condition of decision 14, a list that cannot be read), `test_protection_layers.py` (the fire layer, the two constraints, situations 1 to 6 and 14 at the arbiter), `test_protection_settings.py` (the lenient reader and the fault values), `test_model_protection.py`, `test_constraint_registrations.py`, and the scenarios of `test_sim_protection.py` (situations 1 to 10 and 14, a source that drops out and returns, the watchdog, two events, fire during a storm, restarts). `tests/core/protection_kit.py` has the events and the worlds. Situations 4, 5 and 6 need lockout protection (block C08) and sleep mode (block C11); until those exist the tests use the **stand-ins** of `tests/sim/stand_ins.py`, which are test-only and replaced by the real constraint and layer when those blocks arrive.
