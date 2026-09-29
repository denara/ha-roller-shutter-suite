# Pause, maintenance lock, operating mode and dry-run

Four controls decide how much a window may move. Three of them are switches you can use at any time: **pause**, **maintenance lock** and **operating mode**. The fourth, **dry-run**, is a deliberate step in the settings of a window. This page shows what each of them holds back, what still moves, and how they work together on the house, a group and a window.

## What each control holds back

| Control | Comfort movements (daily routine, later shading and more) | Protection (storm, hail; a later version adds them) | Fire alarm (a later version adds it) | Where you set it |
|---|---|---|---|---|
| **Pause** on | held back | moves | opens | the switch **Pause**, or a pause entity of your own |
| **Operating mode** "Protection only" | held back | moves | opens | the select **Operating mode** |
| **Operating mode** "Off" | held back | held back | opens | the select **Operating mode** |
| **Maintenance lock** on | held back | held back | **held back**; the fire alarm is still reported at once | the switch **Maintenance lock** |
| **Dry-run** | nothing moves; the window writes down what it would have done | nothing moves | nothing moves; the fire alarm is still reported at once | the settings of the window, see [Dry-run](dry-run.md) |
| Nothing of this (operating mode "Automatic") | moves | moves | opens | |

"Comfort movements" are everything except protection and the fire alarm: the daily routine today, and later shading, sleep mode, privacy and requests from your automations.

**The maintenance lock is the only control that also holds back the fire alarm.** It exists for the moment somebody works on a shutter: a shutter that starts to move could hurt them. The fire alarm is still reported at once, as an event and in the logbook, with the reason "Maintenance lock".

A pause and the operating mode are for comfort. Use them when you do not want the daily routine to move the shutters for a while; storms and the fire alarm still do their job. A pause is also the way to keep a position you set by hand: this version does not notice a movement by hand yet, and an armed window that is not paused moves the shutter back within a few seconds.

## The entities

The house, every group and every window have the three controls on a device of their own. The house device carries the name of the integration, "Roller Shutter Suite"; a group device carries the name of the group; a window has the device it already had. The controls are configuration entities, so you find them under **Configuration** on the page of the device.

| Entity | Example for the window "Example window" | Example for the house |
|---|---|---|
| Pause | `switch.example_window_pause` | `switch.roller_shutter_suite_pause` |
| Maintenance lock | `switch.example_window_maintenance_lock` | `switch.roller_shutter_suite_maintenance_lock` |
| Operating mode | `select.example_window_operating_mode` (Automatic, Protection only, Off) | `select.roller_shutter_suite_operating_mode` |

A group "Example group" has `switch.example_group_pause` and so on.

A change takes effect within about a second, for every window it concerns. It never reloads the integration. When a pause or a lock ends, each window looks at the situation again and goes where it should be now; nothing that was held back is caught up afterwards.

**After a restart of Home Assistant** every control has the value it had before, also if the window was unavailable at that moment. Without a stored value (a new installation, or a new window) a control is off, and the operating mode is "Automatic".

The controls of a window are unavailable while the window itself is not running, for example while its covers cannot be read. The controls of the house and of the groups are always available.

## Three levels: the strictest one wins

A window is paused if the house, its group or the window itself is paused. It is locked if any of the three is locked. Its operating mode is the strictest of the three: "Off" before "Protection only" before "Automatic".

| House | Group | Window | What applies to the window |
|---|---|---|---|
| Automatic | Automatic | Off | Off |
| Protection only | Automatic | Automatic | Protection only |
| Off | Automatic | Protection only | Off |
| paused | not paused | not paused | paused |

A window cannot lift a pause or a lock of its group or of the house. To let one window move while the others are paused, pause the others one by one, or put them into a group of their own and pause the group.

The **Reason** of a window says what holds it back, for example "Paused" or "Maintenance lock". Its attribute `paused_by` lists every level that pauses it: `global` for the house, `group` or `window`, and, if the pause comes from a pause entity, that entity and its state.

## A pause entity of your own

Instead of switching the pause by hand, you can let an entity of your own do it: a helper you turn on while you are away, a calendar with an event for your holidays, a sensor of another integration. Choose it on the page **Operation** of the house, a group or a window (Settings > Devices & services > Roller Shutter Suite > **Reconfigure**, or the menu of the group or window). While the entity is **on**, it pauses its level in addition to the switch **Pause**; when it turns **off**, the level runs again, unless the switch is on.

Like every entity of the forms, the pause entity is inherited: a window uses the one of its group, a group the one of the house, unless it chooses its own or "None". The pause entity of the house always pauses the house, so every window; "None" on a window only means that no further entity pauses the window itself.

**An entity that has no state pauses.** If the pause entity is unavailable, its state is unknown, or it reports something else than on or off, its level is paused, and protection and the fire alarm still move the shutters. That is the cautious side: a pause holds back comfort only, and you should be able to rely on the pause exactly when the entity that decides it fails. The attribute `paused_by` of the reason names the entity and its state, for example `unavailable`. After an hour without a state, a repair issue names the house, the group or the window that chose the entity, and the entity itself; it disappears by itself as soon as the entity reports on or off again. An entity that a window only inherits is reported once, at the house or the group that chose it.

If the saved setting of the pause entity cannot be read, the level is paused too, and the repair issue about the faulty setting tells you how to repair it.

There is no entity of your own for the maintenance lock or the operating mode. Both are meant to be set by a person on purpose.

## Worked examples

### Scaffolding in front of the house for a week

Workers put up scaffolding in front of the south side, and the shutters there must not move at all while they work. Put the south windows into a group (for example "South side"), if they are not already in one, and turn on the **Maintenance lock** of that group: `switch.south_side_maintenance_lock`. From then on no shutter of the south side moves, not for the daily routine, not for a storm, not for a fire alarm; the other sides of the house carry on as usual. When the scaffolding is gone, turn the lock off; each window of the group looks at the situation again and goes to where it should be at that time of day.

If only one window is concerned, use the maintenance lock of that window instead.

### A party evening

You have guests on the terrace, and the living room shutters shall stay open tonight, although the evening would close them. Turn on **Pause** for the living room window, or for its group. The evening passes without a movement, while a storm warning would still close the shutters. The next morning, turn the pause off: the window looks again, and since it is day by then, it opens where it should be open, or stays where it is.

To make this a habit, create a helper "Party" (an input boolean) and choose it as the pause entity of the living room on the page **Operation**. Then an automation, a button on your dashboard or a voice command can turn the party on and off, and the switch **Pause** stays free for other purposes.

### A window that shall only follow the weather

The shutter of a studio shall never move for comfort, only to protect the window from a storm or hail, and open at a fire alarm. Set the **Operating mode** of that window to **Protection only**. The daily routine no longer moves it (the reason reads "Operating mode: protection only"), and protection and the fire alarm still do. Unlike a pause, the operating mode is meant to stay as it is for a long time.

## Dry-run next to the controls

Dry-run is not one of the switches. It belongs to the settings of a window, and leaving it takes a deliberate step with a confirmation; see [Arming a window](dry-run.md#arming-a-window). While a window is in dry-run, the controls still decide what it *would* do: a paused window in dry-run writes down "would have held back, because the window is paused".
