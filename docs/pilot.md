# Pilot guide: one window in dry-run

This guide takes you from nothing to one window that Roller Shutter Suite watches in **dry-run**: it decides what it would do with the shutter, writes it down, and moves nothing. You compare its decisions with what your existing control does, for as long as you like, and remove everything again without a trace when you are done.

**What this version is.** A pilot. Watch windows in dry-run. This version cannot arm a window yet, because it does not notice a movement by hand; [section 8](#8-before-you-arm-a-window) explains why and what to prepare for a later version.

- **It works:** the forms for the house, groups and windows; the daily routine (morning and evening, workdays, weekends and public holidays, sunrise and sunset with "not before" and "not after"); the settings of movement; pause, maintenance lock and operating mode for the house, every group and every window, and a pause entity of your own ([Pause, maintenance lock, operating mode and dry-run](features/controls.md)); the status entities of every window, the reason event, the logbook entries and the diagnostics download; and the page of checks for arming a window in its settings, which in this version says why it cannot arm yet and saves nothing.
- **It does not exist yet:** shading, storm and hail, the fire alarm, sleep mode, reactions to open windows and doors, and the detection of a movement by hand. Without it no window can be armed, so no window moves its shutter.
- **It does not remember everything across a restart:** see [After a restart of Home Assistant](#7-after-a-restart-of-home-assistant).

Try it on a test instance of Home Assistant first if you have one. Nothing moves in dry-run, but a test instance lets you look at every form without any doubt.

## What you need

- Home Assistant 2026.9 or newer.
- [HACS](https://hacs.xyz), installed and working.
- One shutter (a cover entity in Home Assistant) whose movements you want to compare. It may stay under the control of your existing automations, scripts or other integrations during the whole pilot; that is what dry-run is for.

## 1. Install through HACS as a custom repository

These steps follow the HACS documentation on [custom repositories](https://www.hacs.xyz/docs/faq/custom_repositories/) and on [downloading a repository](https://www.hacs.xyz/docs/use/repositories/dashboard/):

1. Open **HACS** in the sidebar of Home Assistant.
2. Select the three dots in the top right corner and choose **Custom repositories**.
3. Enter `https://github.com/denara/ha-roller-shutter-suite` as the repository, choose **Integration** as the type, and select **Add**.
4. Search for **Roller Shutter Suite** in HACS and open it.
5. Select **Download**. HACS downloads the newest release by default; pause, maintenance lock and operating mode need version 0.2.0 or newer. To pick a version, open **Need a different version?** in the same dialog, choose it and confirm.
6. Restart Home Assistant: HACS marks the repository as "pending restart" until you do.

## 2. Add the house

1. Open **Settings** > **Devices & services** and choose **Add integration**.
2. Search for **Roller Shutter Suite** and select it.
3. Confirm the first page.
4. On the page **Features**, leave the daily routine switched on.
5. The pages of the daily routine and the page **Movement** follow. Every field already has a sensible value. If your existing control opens and closes at fixed times, enter those times on the pages for workdays, weekends and public holidays, so the two can be compared directly. Otherwise save each page as it is.

The built-in values are in [The daily routine](features/daily-routine.md#what-applies-if-you-set-nothing); [Configuration](configuration.md) explains every page.

## 3. Add one window

1. Open the integration and choose **Add window**.
2. Enter a name, for example "Example window", and choose the cover of the window in **Covers**. If a **Group** field is shown, leave it empty; groups are not needed for one window. As long as the house has no group, the form does not show the field at all.
3. Go through the pages and change only what is different for this window. Save the last page.

Every new window starts in dry-run; the form that adds a window does not ask. Check it: the window's device has a diagnostic entity **Dry-run**, and it must be **on**. Only the settings of the window can arm it later, with a confirmation ([section 8](#8-before-you-arm-a-window)).

## 4. What to watch

The window's device (Settings > Devices & services > Roller Shutter Suite > the window) shows these entities. The names below assume the window is called "Example window".

| Entity | What to look for |
|---|---|
| **Reason** (`sensor.example_window_reason`) | Why the window is where it is. In dry-run it reads **"Dry-run: nothing moves"** whenever the integration would have moved the shutter, and otherwise the reason of the daily routine, for example **"Daily routine: day"**. |
| **Next planned action** (`sensor.example_window_next_planned_action`) | When the daily routine wants something new next, for example today at 20:00. Its attributes `target` and `reason` say which position it will want and why. |
| **Dry-run** (`binary_sensor.example_window_dry_run`) | Must stay **on** until you arm the window. |
| **Target position** (`sensor.example_window_target_position`) | The position the window should have, in percent (100 % is fully open). |
| **Manual override** (`binary_sensor.example_window_manual_override`) | Always off in this version. |

**The attributes of the reason tell the whole story.** Open **Developer tools** > **States** (or select the entity and open its attributes) and look at:

- `would_send`: the position the integration would have sent. Filled whenever the reason reads "Dry-run: nothing moves".
- `wish_reason`: why it wanted that position, for example `schedule_night` for the evening.
- `gate_reason`: what decided. `dry_run` means "it would have moved now"; `target_reached` means "the shutter is already where it should be". Any other value names what would have held the movement back.

**The logbook** shows one line whenever the outcome changes, in the language of your Home Assistant, for example:

- *Example window* dry-run, nothing moved: it would have moved to 100 %. Reason: Daily routine: day.

The same moment is also fired as the event `roller_shutter_suite_reason`, which your own automations can use; [Status, reason events and diagnostics](features/status-and-events.md) has an example that sends a notification.

A few minutes after you saved the window, check that the two values are plausible: the next planned action lies at the next morning or evening time you expect, and the reason names the part of the day it is now.

## 5. Compare with your existing control

Your existing control keeps moving the shutter. Each time it does, look at the reason of the window:

| What you see | What it means |
|---|---|
| "Dry-run: nothing moves" with `would_send` at the morning or evening time | At this moment the integration would have moved the shutter to `would_send`. |
| `gate_reason` becomes `target_reached` shortly after your control moved the shutter | Your control put the shutter exactly where the integration wanted it. This is the line you want to see most. |
| "Dry-run: nothing moves" stays long after your control moved the shutter | The two disagree: your control chose another position, or another time. Compare the times in the logbook of the window with the logbook or history of the cover. |
| A reason other than the daily routine, or a repair issue | Something is configured differently from what you expect; the reason names it. |

Movements of your existing control never count as a movement by hand here: the integration observes the new position and judges its next decision against it, but it arms no manual override, and the reason never reads "Moved by hand" during the pilot. The movements themselves appear in the logbook and history of the **cover**, not of the window; this version does not yet write a line of its own for a movement it did not make.

Remember the direction rules of the daily routine: the morning only ever raises a shutter and the evening only ever lowers it. A shutter your control closed completely in the afternoon is "already where it should be" at an evening position of 30 %.

**If `target_reached` never appears.** Suppose the reason keeps reading "Dry-run: nothing moves" with `would_send` equal to the position the shutter already stands at, and nothing changes when your control moves it. Then check how your cover reports its position: open **Developer tools** > **States**, select the cover, and look at its attribute `current_position`. This version reads a position only if it is a whole number such as `100`. Some covers, among them the template cover and the cover group of Home Assistant, report a decimal number such as `100.0`; this version cannot read that position and treats the cover as one without position feedback. The diagnostics of the window then show `position: null` for that cover. For the pilot this means that such a window can never show "already where it should be", so the comparison with your control only works through the times of the logbook. It is not a safety matter: the window still moves nothing. Whether a decimal number without a fraction will be read as a position is a decision of the project owner for a later version.

**Diagnostics** help when a decision surprises you: the window's device > the three dots > **Download diagnostics** contains the last ten decisions with their times and every setting with the level it comes from. Read [what the file contains](features/status-and-events.md#diagnostics) before you share it.

## 6. How long to observe

**At least two full weeks, and across a change of the clocks if one falls into the next month.** The reasons:

- Each kind of day has its own times. Two weeks contain ten workdays and four weekend days, so each of them is seen more than once. If you use a public holiday sensor, include a public holiday.
- The evening follows the sun by default and moves by a few minutes every day; two weeks show whether "not before" and "not after" fit your house.
- A restart of Home Assistant, an update or a cover that is away for a while should happen at least once during the pilot, so you see that nothing changes because of them.

There is no reason to stop early: dry-run costs nothing, and you can let the window run as long as you like.

## 7. After a restart of Home Assistant

This version keeps the memory of a window in memory only; storing it on disk comes with a later version. What a restart forgets, and what that means during the pilot:

- **What the window would have sent last.** After a restart the next decision says "would have sent" once more, and the reason event is fired again for the present outcome.
- **The kind of day fixed at the morning.** After a restart it is worked out again from your workday and holiday sensors as they are then. If a sensor changed its value during the day, the restarted window may choose the other kind of day.
- **The random offset.** If you set one, a restart draws new amounts for the window. The default is no offset.
- **The memory of the last reason event** and of the last ten decisions in the diagnostics.

What does not change: the decision itself. It is worked out from the present time and the present state of the shutter, not from triggers that had to be seen, so it is the same after a restart as before. In dry-run nothing moves either way.

What a restart keeps: pause, maintenance lock and operating mode of every level, and whether a window is in dry-run or armed.

**For an armed window** a restart also forgets the last command it sent and when. If the shutter is not where the daily routine wants it when Home Assistant has started again, for example because you moved it by hand, the window sends the command again at once, and the minimum interval between two movements starts anew.

## 8. Before you arm a window

**In version 0.2.0 no window can be armed yet.** This version does not notice when you move a shutter by hand. An armed window would take a shutter you moved for one that is not where it should be, and move it back within a few seconds. So the page **Arm the window** says so and saves nothing, whatever you tick, and every window stays in dry-run. What 0.2.0 brings for a window in dry-run are the **Pause**, the **Maintenance lock** and the **Operating mode** of the house, every group and every window: try them now, and the window writes down what it would have held back ([Pause, maintenance lock, operating mode and dry-run](features/controls.md)). A later version notices a movement by hand; from then on the page arms a window, and this list is what you go through first. Read it now to prepare, and keep your old control running: if you switched it off (point 2) now, nothing would move the shutter at all.

Arming a window is the step after which Roller Shutter Suite moves its shutter. Go through this list for every window you arm, in this order, one point after the other. The page **Arm the window** of the form asks you to confirm points 1 to 6 and point 9 before it saves; the other points tell you how to get there and what to watch afterwards. The examples use the window "Example window" in the group "Example group".

1. <!-- check: one_controller --> **One controller per window.** Nothing else may move this shutter once it is armed. *Look at:* your automations, scripts, scenes and blueprints (Settings > Automations & scenes; the page of the cover entity lists under **Related** what uses it), the schedules of other integrations, and the timers or sun programs in the app of the shutter's vendor. *Expect:* nothing of it moves this cover, or you know exactly what you switch off in point 2. Two controllers that move the same shutter fight each other, and each one takes the other's movements for a person at the window. Dry-run is the only state in which two controllers may watch the same shutter.
2. <!-- check: old_control_off --> **Switch off the old control first, and check it.** Change the thing that moves the shutter before you arm anything. Disable the old automation, or the timer in the vendor's app. *Look at:* the history and the logbook of the cover at the next time the old control would have moved it. *Expect:* the cover does not move at that time any more. The window is still in dry-run, so nobody moves the shutter now; its reason reads "Dry-run: nothing moves" whenever it would have moved it.
3. <!-- check: compared --> **Compare the last days once more.** *Look at:* the logbook of the window and of the cover for the days before you switched the old control off, and the attribute `gate_reason` of the entity **Reason**. *Expect:* shortly after each movement of the old control the reason read "Already where it should be" (`target_reached`), or you understand every difference, for example a time you chose differently on purpose. See [section 5](#5-compare-with-your-existing-control).
4. <!-- check: controls_checked --> **Look at the operating mode, the pause and the maintenance lock of the house, the group and the window once.** *Look at:* the configuration entities of the device "Roller Shutter Suite" (the house), of the device of the group and of the device of the window: **Pause**, **Maintenance lock** and **Operating mode**, and the pause entity on the page **Operation** of each, if you chose one. *Expect:* what you intend, usually both switches off and "Automatic". Remember what each holds back: a pause and "Protection only" hold back the daily routine; "Off" also holds back protection; the maintenance lock holds back everything, the fire alarm included. The strictest of the three levels applies ([Pause, maintenance lock, operating mode and dry-run](features/controls.md)).
5. <!-- check: reports_at_once --> **Every cover of the window reports its movements by itself, not on a schedule.** Some cover integrations tell Home Assistant about a movement when it happens, even if the message arrives a little late; others are asked for the state of the shutter on a schedule, for example once a minute (polled), and then nothing that happens between two questions is ever seen. *Look at:* the page of the cover entity, or **Developer tools** > **States**, while you move the shutter with its wall switch or its app. *Expect:* the state reads "Opening" or "Closing" while the shutter moves, or the position changes step by step; a cover that only ever jumps from the old to the new position exactly once a minute is polled. A delay is fine and is entered as the reporting time of the cover; polling is not. Until a later version checks every command it sends, a window with a polled cover is not safe to arm: if somebody moves such a shutter by hand between two questions, the window does not see it, and a command it sends again undoes what that person did. If a cover of the window is polled, leave the window in dry-run.
6. <!-- check: fresh_start --> **Know what arming discards.** *Look at:* the entity **Dry-run** of the window: it is **on**. *Expect:* when you arm, the window starts fresh. It forgets the commands it would have sent in dry-run, so the minimum interval between two movements starts anew; it assumes no movement by hand; and its next decision is a real one. **If the shutter is not where the daily routine wants it at that moment, it moves within a few seconds after you save.** Arm at a moment when that is fine, ideally just after the reason read "Already where it should be".
7. **Arm the window.** Open **Settings** > **Devices & services** > **Roller Shutter Suite**, find the window, open its menu with the three dots and choose **Reconfigure**. Go through the pages as they are, up to the last one, **Operation: dry-run or armed**. Choose **Armed: move the shutters** and select **Next**. The page **Arm the window** lists seven points: nothing else moves the shutter, the old control is switched off and checked, the last days are compared, you have looked at operating mode, pause and maintenance lock, every cover reports at once, you know that the window starts fresh, and you know the way back (point 9). Tick each one and select **Submit**. If one of them is not true yet, close the dialog: nothing is saved, and the window stays in dry-run. *Expect:* "The window was saved.", and the entity **Dry-run** turns **off**. In version 0.2.0 the page instead says at the top that this version cannot arm a window yet, and saves nothing; close the dialog. If the integration knows that a cover of the window reports late, the page names it and saves nothing either.
8. **Watch the first hour and the first day.** *Look at:* the entities **Reason**, **Target position** and **Next planned action** of the window, the logbook of the window, and the shutter itself. *Expect in the first hour:* at most the one movement of point 6, with the logbook line "command sent to move to …", and after it no further movement until the time of **Next planned action**, unless somebody moves the shutter by hand (see below). The reason reads the part of the day, for example "Daily routine: day", and its attribute `gate_reason` reads `target_reached` once the cover reports its new position. *Expect on the first day:* at the morning and at the evening one command each, at the time the entity **Next planned action** showed, to the position its attribute `target` showed; no movement at any other time, and no repair issue. If you move the shutter by hand: a version that does not notice this would take the shutter for one that is not where it should be and **move it back within a few seconds**, which is why version 0.2.0 arms no window at all. The version that arms a window describes here what it does after a movement by hand.
9. <!-- check: way_back --> **If the shutter moves when it should not: maintenance lock first, then back to dry-run.** Turn on the **Maintenance lock** of the window (`switch.example_window_maintenance_lock`). From that moment the window sends no command at all, not even at a fire alarm, so do not leave it on longer than needed. Then choose **Reconfigure** for the window and, on the last page, **Dry-run: decide and record, move nothing**; going back needs no confirmation. Turn the maintenance lock off again. The logbook of the window and its diagnostics show what it decided and why; [Status, reason events and diagnostics](features/status-and-events.md) explains them.

## 9. Removing everything

1. Open **Settings** > **Devices & services** > **Roller Shutter Suite**, select the three dots and choose **Delete**. This removes the house, every group and window, their devices and entities, and their repair issues.
2. Open **HACS**, open **Roller Shutter Suite**, select the three dots and choose **Remove**. HACS says itself that removing a repository does not remove the related data, which is why step 1 comes first.
3. Restart Home Assistant.

What the tests of this version prove about step 1: after the integration is deleted, no entity, no device and no repair issue of it is left, and it leaves no storage file behind; this version never writes one. Home Assistant itself keeps a record of the deleted entities and devices in its own registry files for a while, as it does for every integration that is removed, so that they get their old names back if the integration is added again; that record belongs to Home Assistant, not to Roller Shutter Suite. Your cover and its history are not touched: they belong to the cover's own integration.

Automations of your own that use the reason event or the entities of a window are yours; delete them yourself if you made any.
