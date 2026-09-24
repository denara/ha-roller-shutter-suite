# Status, reason events and diagnostics

Every window explains itself: why it is where it is, where it should be, and what happens next. This page describes the entities that show it, the event the integration fires when it moves a shutter or holds a movement back, the entries in the logbook, and the diagnostics download.

**Status: pilot.** The entities, the event and the diagnostics exist, and an armed window does send commands to its covers; but no window can be armed in the forms yet, so every window is in dry-run and records the command it would give. Manual operation is not detected yet, so the entity "Manual override" is always off.

## The entities of a window

Each window has a device with the window's name. The device carries five entities. The examples use a window named "Example window".

| Entity | Example | What it shows |
|---|---|---|
| Reason | `sensor.example_window_reason` | The one reason that explains best why the window is where it is, for example "Daily routine: night", "Paused" or "Dry-run: nothing moves". The full list is below. |
| Computed position | `sensor.example_window_computed_position` | The position the window should have, in percent: 100 % is fully open, 0 % fully closed. It is unknown when nothing wants a position, or when the covers of a window with several covers should stand at different positions. |
| Next planned action | `sensor.example_window_next_planned_action` | When the daily routine wants something new next, for example the evening at 20:00. Its attributes say which position it will want (`target`) and why (`reason`). It is a plan, not a promise: something more important can apply at that time, and the evening never raises a shutter that is already lower. |
| Manual override | `binary_sensor.example_window_manual_override` | On while a movement by hand holds the automatic movements back. Always off for now, see above. |
| Dry-run | `binary_sensor.example_window_dry_run` | On while the window decides and records but moves nothing. You find it under the diagnostic entities of the device. New windows start in dry-run; arming a window arrives with a later version. |

The entities update whenever the window is looked at again: when a cover or an entity the window uses changes, at every planned time, and at least every five minutes. They never poll.

**When a cover is unavailable**, the entities of its window are unavailable too, and they come back by themselves with the cover; no reload is needed. A window with several covers stays available as long as at least one of them is.

**A cover that reports its position as a decimal number**, such as `100.0` instead of `100`, is treated as a cover without position feedback: this version reads a position only as a whole number. The template cover and the cover group of Home Assistant report it that way. For such a cover the reason never reads "Already where it should be", and the diagnostics show `position: null`. The [pilot guide](../pilot.md#5-compare-with-your-existing-control) explains how to check a cover.

### What the reason tells you

The reason is chosen like this:

- If the window got the position it wanted, its command is still under way, or it is already there, the reason is **why it wanted it**: "Daily routine: night", "Fire alarm". That the command is under way is in the attributes (`gate_reason` is `duplicate_command`).
- If something held the movement back, the reason is **what held it back**: "Paused", "Maintenance lock", "Waiting for the minimum interval between two movements".
- If a limit left no movement at all, the reason is **the limit**: "Not lowered while the door is open".
- In dry-run, the reason is "Dry-run: nothing moves" whenever a command would have been sent. What would have been sent, or what would have held it back, is in the attributes.

### The attributes of the reason

The entity "Reason" carries the complete explanation as attributes. They change only when the decision changes, so the history of the entity is the history of the decisions. While the window waits for something whose end is not known (a cover to become available, a movement it did not start to end), the window is looked at again at least every few minutes; that time is not an attribute, because it moves on with every look while nothing else changes.

| Attribute | Meaning |
|---|---|
| `layer`, `wish`, `wish_class`, `wish_reason`, `function` | What won: for example `schedule` (the daily routine) wanting a `target` for `schedule_night`. `wish_class` is `fire`, `protection` or `comfort`. `wish` is `target` (a position), or `leave_alone` (hold the window where it is). |
| `target` | The position after all limits, if all covers share one. |
| `constraints` | Every limit that applied, in order, each with its reason and the position after it; for example the ventilation position in front of an open window. |
| `gate_outcome`, `gate_reason`, `gate_rule` | Whether the movement was sent (`send`), deferred (`defer`) or held back (`suppress`), with the reason and the rule that decided. |
| `deferred_until` | For a deferral with a known end: when it ends, for example the end of the minimum interval between two movements. Empty when the end is not known. |
| `dry_run`, `would_send` | Whether the window is in dry-run, and the position that would have been sent. |
| `other_layers` | For every other part of the logic (fire, protection, sleep mode, requests, privacy, shading, the daily routine) the reason why it did not decide: not set up, not active, a required entity that is unavailable or unknown, suspended because of a faulty setting, and so on. |
| `faults` | Parts that failed with an internal error during this decision, each with where it happened and its reason (`layer_failed`, `constraint_failed`, `gate_rule_failed`). Empty in a sound installation. Protection never stops because of such an error; the error text itself is written to the log, not here. |

**In dry-run** the attributes show the outcome as if the window were armed: either `would_send` with the position, or `gate_rule` with the rule that would have held it back. "Already where it should be" (`target_reached`) is especially useful while another controller still moves the window: it means that the other controller put the window where this integration wanted it.

## Reason events

The integration fires one event type, `roller_shutter_suite_reason`, when:

- a position is wanted and a command is sent;
- a window in dry-run would have sent a command;
- a wanted movement is deferred or held back, for example by the pause, the maintenance lock, the minimum interval between two movements, or an open door.

**The fire alarm is always reported at once**, also when the maintenance lock or dry-run keeps the shutter where it is; the event then names the reason why nothing moved.

The event is not repeated while the outcome stays the same. A paused window fires one event when the evening begins, not one every five minutes. It fires again when the outcome changes, for example when the pause ends and the command is sent. Changing the configuration does not repeat the last event either; after a restart of Home Assistant the present outcome is reported once more.

The data of the event:

| Field | Example | Meaning |
|---|---|---|
| `subentry_id` | `01J…` | The identifier of the window in the configuration. |
| `device_id` | `4f9c…` | The device of the window, for device-based automations. |
| `name` | `Example window` | The name of the window. |
| `reason` | `paused` | What happened: `sent`, `dry_run`, or what held the movement back. |
| `layer` | `schedule` | The part of the logic that wanted the movement: `fire`, `protection`, `sleep`, `external_request`, `privacy`, `shading` or `schedule`. |
| `wish_class` | `comfort` | `fire`, `protection` or `comfort`. |
| `wish_reason` | `schedule_night` | Why the movement was wanted. |
| `target` | `0` | The position, in percent; empty if the covers of the window have different targets. |
| `gate` | `suppress` | `send`, `defer`, `suppress`, or empty if a limit left no movement. |
| `gate_rule` | `pause` | The rule that decided, if one did. |
| `dry_run` | `false` | Whether the window is in dry-run. |
| `until` | | For a deferral with a known end: when it ends. |

### Example: a notification when a movement is held back

This automation sends a notification to the Home Assistant sidebar whenever a movement of any window is held back or deferred. Create it in **Settings → Automations & scenes → Create automation**, open the menu at the top right, choose **Edit in YAML**, and paste:

```yaml
alias: Shutter movement held back
triggers:
  - trigger: event
    event_type: roller_shutter_suite_reason
conditions:
  - condition: template
    value_template: "{{ trigger.event.data.reason not in ['sent', 'dry_run'] }}"
actions:
  - action: persistent_notification.create
    data:
      title: "{{ trigger.event.data.name }}"
      message: >-
        A movement to {{ trigger.event.data.target }} % was held back
        ({{ trigger.event.data.reason }}).
mode: queued
```

To be told about the fire alarm only, replace the condition with one that checks `{{ trigger.event.data.layer == 'fire' }}`. To use your phone instead of the sidebar, replace the action with the notification action of your phone.

## The logbook

Every reason event appears in the logbook, under the name of the window and linked to its entity "Reason", in the language of your Home Assistant installation. Examples:

- *Example window* command sent: move to 0 %. Reason: Daily routine: night.
- *Example window* dry-run, nothing moved: it would have moved to 100 %. Reason: Daily routine: day.
- *Example window* movement to 0 % held back: Paused. Wanted because of: Daily routine: night.

## Diagnostics

The diagnostics help when something does not behave as you expect, and when you report a problem.

- **For all windows:** Settings → Devices & services → Roller Shutter Suite → the menu (three dots) → **Download diagnostics**.
- **For one window:** open the device of the window → the menu (three dots) → **Download diagnostics**.

The file contains, per window: every setting with where it comes from (the house, a group, the window, or the built-in default) and whether a cautious choice stands in for it because its saved setting is faulty; what each cover can do; the state of the window (the entities it reads, the daily routine of today, the next planned time); the last ten decisions with the time each was first made; and what the window remembers between two decisions.

**Before you share the file**, know what it contains and what it leaves out. Like the diagnostics of other integrations, it keeps the names of your windows and groups, the IDs of your entities and the values those entities report, because a problem can only be traced with them. Removed, and replaced by `**REDACTED**` wherever they would appear, are the location of your home (latitude, longitude, elevation) and anything secret, such as passwords, tokens and API keys; none of these is part of a window today. The message of an error inside the integration is never included, only where it happened and its reason code. If a name of a window or an entity says more than you want to share, replace it in the file before you attach it. The covers of a window appear in the order of its configuration, so the same place in each list means the same cover.

Each entity the window reads has the time since which its present value has been seen (`seen_unchanged_since`). That time is counted from the last start or reload of the integration, not from the change of the entity, so after a restart it starts again.

## All reasons

The reason entity and the events use these codes. The column "Shown as" is the English text of the reason entity.

### Why a window moves or holds

| Code | Shown as |
|---|---|
| `fire_alarm` | Fire alarm |
| `fire_unacknowledged` | Fire alarm over, waiting for acknowledgement |
| `protection_event` | Protection from storm, hail or similar |
| `protection_return_manual` | Back to the position set by hand before the protection |
| `sleep_mode` | Sleep mode |
| `external_request` | Request from an automation |
| `privacy_lights_on` | Privacy while the lights are on |
| `shading_geometric` | Shading that follows the sun |
| `shading_fixed` | Shading at a fixed position |
| `solar_heating` | Letting the sun warm the room |
| `schedule_day` | Daily routine: day |
| `schedule_night` | Daily routine: night |

### Why a function is not acting

| Code | Shown as |
|---|---|
| `not_configured` | Not set up |
| `inactive` | Not active right now |
| `input_unavailable` | A required entity is unavailable |
| `input_unknown` | The state of a required entity is unknown |
| `input_held_last_known` | Using the last known state of an entity |
| `waiting_for_delay` | Waiting for the set delay |
| `outside_episode` | Conditions not met right now |
| `episode_locked` | Stays off until its conditions are no longer met |
| `watchdog_released` | Ended because it lasted implausibly long |
| `capability_missing` | The cover cannot do this |
| `day_type_fallback` | Kind of day unknown, the day of the week is used |
| `function_disabled_by_fault` | Suspended because a saved setting is faulty |
| `layer_failed` | Skipped because of an internal error |

### What limits a movement

| Code | Shown as |
|---|---|
| `only_raise` | Only raised at this time of day |
| `only_lower` | Only lowered at this time of day |
| `sleep_exception_no_open` | Not opened while someone is sleeping |
| `lockout_door_open` | Not lowered while the door is open |
| `lockout_void_tamper` | Lowered despite the open door: the tamper contact is active |
| `lockout_contact_unavailable` | Not lowered: the door contact is unavailable |
| `ventilation_floor` | Stops at the ventilation position because the window is open |
| `rain_ventilation_floor` | Lowered to the rain position while the window is open |
| `frost_limit` | Opens only up to the frost position because of frost |
| `frost_limit_source_blind` | Opens only up to the frost position, because the temperature is unknown |
| `frost_hold` | Not raised during frost |
| `no_intermediate_position` | No position in between while protection is active |
| `constraint_failed` | Limit kept because of an internal error |

### Whether it may move now

| Code | Shown as |
|---|---|
| `sent` | Command sent |
| `maintenance_lock` | Maintenance lock |
| `dry_run` | Dry-run: nothing moves |
| `cover_unavailable` | The cover is unavailable |
| `target_reached` | Already where it should be |
| `mode_off` | Operating mode: off |
| `mode_protection_only` | Operating mode: protection only |
| `paused` | Paused |
| `person_at_window` | Someone is at the window |
| `manual_override` | Moved by hand; automatic movements wait |
| `movement_in_flight` | Waiting for the current movement to end |
| `duplicate_command` | Command already under way |
| `movement_taken_over` | Carries on with the movement already running |
| `min_change` | Change too small to be worth a movement |
| `min_interval` | Waiting for the minimum interval between two movements |
| `trigger_time_missing` | Held back: it is not known since when the movement has been wanted |
| `command_backoff` | Waiting before the next attempt |
| `staggered` | Waiting for its turn |
| `gate_rule_failed` | Held back because of an internal error |

### Only in events, later

These codes belong to functions that are not built yet. They will appear in events, never as the state of the reason entity.

| Code | Shown as |
|---|---|
| `manual_detected` | Moved by hand |
| `manual_detected_member` | One cover of the window was moved by hand |
| `external_movement_observed` | Moved by something else during the dry-run |
| `moved_during_downtime` | Moved while Home Assistant was not running |
| `person_at_window_started` | Someone came to the window |
| `person_at_window_ended` | Nobody at the window any more |
| `override_started` | Manual override started |
| `override_ended` | Manual override ended |
| `protection_started` | Protection started |
| `protection_ended` | Protection ended |
| `protection_source_blind` | An entity used for protection is unavailable or unknown |
| `lockout_contact_blind` | The door contact is unavailable or unknown |
| `fire_acknowledged` | Fire alarm acknowledged |
| `frost_protection_waived` | Frost protection lifted until the next morning |
| `frost_waiver_ended` | Frost protection applies again |
| `frost_released_by_sun` | Frost protection lifted by the sun |
| `frost_source_blind` | The entity used for frost is unavailable or unknown |
| `position_may_be_inaccurate` | The position may be inaccurate |
| `command_failed` | Command failed |
| `actuator_no_reaction` | The cover did not react |
| `movement_not_finished` | The end of the movement was not reported in time |
| `member_unavailable` | One cover of the window is unavailable |
| `button_refused_maintenance_lock` | Button press ignored because of the maintenance lock |

No reason says that a shutter has arrived at a position. Many covers report a calculated position, not a measured one; the integration can only know whether a cover reacted.
