# Pilot guide: one window in dry-run

This guide takes you from nothing to one window that Roller Shutter Suite watches in **dry-run**: it decides what it would do with the shutter, writes it down, and moves nothing. You compare its decisions with what your existing control does, for as long as you like, and remove everything again without a trace when you are done.

**What this version is.** Version 0.1.0 is a pilot. Use it in dry-run only.

- **It works:** the forms for the house, groups and windows; the daily routine (morning and evening, workdays, weekends and public holidays, sunrise and sunset with "not before" and "not after"); the settings of movement; the status entities of every window, the reason event, the logbook entries and the diagnostics download.
- **It does not exist yet:** shading, storm and hail, the fire alarm, sleep mode, reactions to open windows and doors, the detection of a movement by hand, switches for pause and maintenance, and a way to arm a window. The last one matters most: **in this version no window can be armed at all**, so nothing you do in the forms makes the integration move a shutter.
- **It does not remember across a restart:** see [After a restart of Home Assistant](#after-a-restart-of-home-assistant).

Try it on a test instance of Home Assistant first if you have one. Nothing moves in either case, but a test instance lets you look at every form without any doubt.

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
5. Select **Download**. In the dialog, choose the version **v0.1.0** and confirm. HACS offers the newest release by default and lets you pick a specific version in the same dialog.
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
2. Enter a name, for example "Example window", and choose the cover of the window in **Covers**. Leave **Group** empty; groups are not needed for one window.
3. Go through the pages and change only what is different for this window. Save the last page.

Every new window starts in dry-run. The form does not ask for it and cannot change it. Check it: the window's device has a diagnostic entity **Dry-run**, and it must be **on**.

## 4. What to watch

The window's device (Settings > Devices & services > Roller Shutter Suite > the window) shows these entities. The names below assume the window is called "Example window".

| Entity | What to look for |
|---|---|
| **Reason** (`sensor.example_window_reason`) | Why the window is where it is. In dry-run it reads **"Dry-run: nothing moves"** whenever the integration would have moved the shutter, and otherwise the reason of the daily routine, for example **"Daily routine: day"**. |
| **Next planned action** (`sensor.example_window_next_planned_action`) | When the daily routine wants something new next, for example today at 20:00. Its attributes `target` and `reason` say which position it will want and why. |
| **Dry-run** (`binary_sensor.example_window_dry_run`) | Must stay **on** for the whole pilot. |
| **Computed position** (`sensor.example_window_computed_position`) | The position the window should have, in percent (100 % is fully open). |
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

What does not change: the decision itself. It is worked out from the present time and the present state of the shutter, not from triggers that had to be seen, so it is the same after a restart as before. And nothing moves either way, because the window is in dry-run.

## 8. Before a window may ever be armed

**In this version a window cannot be armed.** The switch for it comes with a later version. When it exists, check these points first, for every window you arm:

1. **One controller per window.** Remove the window from every other controller before you arm it: automations, scripts, scenes, blueprints, schedules in another integration or in the app of the shutter's vendor. Two controllers that move the same shutter fight each other, and each one sees the other's movements as a person at the window. Dry-run is the only state in which two controllers may watch the same shutter.
2. **Switch off the old control first, then arm.** Change the thing that moves the shutter before you change anything it listens to. Disable the old automation, check that it no longer moves the shutter, and only then arm the window.
3. **Compare once more.** The last days before arming, the reason should read `target_reached` shortly after each movement of the old control, or you should understand every difference.

## 9. Removing everything

1. Open **Settings** > **Devices & services** > **Roller Shutter Suite**, select the three dots and choose **Delete**. This removes the house, every group and window, their devices and entities, and their repair issues.
2. Open **HACS**, open **Roller Shutter Suite**, select the three dots and choose **Remove**. HACS says itself that removing a repository does not remove the related data, which is why step 1 comes first.
3. Restart Home Assistant.

What the tests of this version prove about step 1: after the integration is deleted, no entity, no device and no repair issue of it is left, and it leaves no storage file behind; this version never writes one. Your cover and its history are not touched: they belong to the cover's own integration.

Automations of your own that use the reason event or the entities of a window are yours; delete them yourself if you made any.
