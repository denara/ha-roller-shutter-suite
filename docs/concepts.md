# Concepts

This page explains ideas that appear everywhere in Roller Shutter Suite. You do not need it to get started, but it helps when you wonder why a window behaves the way it does.

## Global, group, window: how settings are inherited

A house has many windows, and most of them should behave alike. You do not want to enter the same values twenty times, and you do not want to change them twenty times later. That is why settings live on three levels:

| Level | What it is | Typical use |
|---|---|---|
| **Global** (the house) | The values for the whole house. | "In the evening, shutters close completely." |
| **Group** | A set of windows that belong together: a side of the house, a floor, a kind of room. A window belongs to one group or to none. | "On the south side, shading is switched on." |
| **Window** | One window. | "This one window stays a little open in the evening." |

### The rule

For every single setting, the integration looks for a value in this order and takes the first one it finds:

1. the **window** itself,
2. the window's **group**, if it has one,
3. the **house**,
4. the **built-in default** of the integration.

So a window only states what is different about it. Everything you do not set on a window comes from its group, and everything the group does not set comes from the house.

Three details matter:

- **Every setting is looked up on its own.** A window that sets its own evening position still takes everything else from its group and the house.
- **Zero and "off" are values.** An evening position of 0 % or a switch set to "off" is something you set, and it wins like any other value. Only a field you leave empty, or the choice "Inherit" in a drop-down list, means "take the value from the level above".
- **You can always go back.** Empty the field again, or pick "Inherit" again, and the window follows its group as if it had never had a value of its own.

There is one more choice for settings that name an optional source, such as a sensor that a feature may use but does not need: **"none"**. Leaving such a field empty means "inherit", so a window whose group names a sensor would always get that sensor. If the window shall use no sensor at all, choose "none" on the window. That is a value of its own: it wins over the group like any other value, and you can return to "inherit" at any time. Settings that always need a value, such as a position or a switch, have no "none".

The integration always shows where a value comes from, for example "inherited from group South side", so you never have to guess which level you need to change.

### A worked example with three windows

The settings below only serve as examples of the rule; which settings exist is described with each feature.

The **house** sets:

| Setting | Value |
|---|---|
| Evening position | 10 % |
| Shading | off |
| Hold the button to move | off |

The group **South side** sets two things and leaves the evening position empty:

| Setting | Value |
|---|---|
| Evening position | *(empty: inherited)* |
| Shading | on |
| Hold the button to move | on |

There are three windows:

- **Living room** belongs to the group South side and sets nothing itself.
- **Study** belongs to the group South side. It sets its evening position to 0 %. Its shutter motor is a simple one that cannot be stopped half-way.
- **Kitchen** belongs to no group and sets nothing itself.

This is what each window ends up with, and why:

| Setting | Living room | Study | Kitchen |
|---|---|---|---|
| Evening position | 10 % (from the house) | 0 % (own value) | 10 % (from the house) |
| Shading | on (from South side) | on (from South side) | off (from the house) |
| Hold the button to move | on (from South side) | **not available** (from South side, but this shutter cannot be stopped) | off (from the house) |

Reading the table:

- The **living room** shows the normal case. The group says nothing about the evening position, so the value of the house applies. For shading and the button, the group's value beats the house's.
- The **study** has one value of its own, and it is 0 %. Zero is not "nothing": the study's shutter closes completely although the house says 10 %. If you later empty that field, the study goes back to 10 %.
- The **kitchen** has no group, so it takes everything straight from the house.

### When a window cannot do what its group asks for

A group does not know the shutters of its windows. It can therefore switch on an option that one of its windows cannot carry out. In the example, "hold the button to move" needs a shutter that can be stopped, and the study's shutter cannot.

The integration does not pretend otherwise and does not fail either. For the study, the option counts as **not available**: it is simply not used for this window, the other windows of the group keep it, and the integration tells you the reason: which ability is missing, which shutter lacks it, and that the value came from the group South side. If a window has several shutters that move together, one shutter without the ability is enough; it is named.

The same holds for an option you switched on **on the window itself**, for example before a shutter was replaced by a simpler one. The integration keeps what you entered, does not use it while the shutter cannot do it, and reports the window so you know. Everything else about the window keeps working. If the shutter can do it again later, your value applies again without any action of yours.

A shutter that is merely not reachable for a while changes nothing: the integration goes on with what it last knew about it, so an option stays switched off, and stays reported, while the shutter is away. Only for a shutter the integration has never seen does it know nothing; then it neither switches anything off nor reports anything until the shutter has answered once.

### What cannot be inherited

A few things belong to exactly one window and are never taken from a group or the house: the shutter or shutters the window consists of, the kind of covering, and the measurements of the window. You enter them on the window.

### When a group is removed

Home Assistant lets you delete a group even while windows still belong to it. Nothing breaks: from then on, such a window takes its values **from the house**, as if it had no group. In the example, living room and study would lose "shading on" and fall back to the house's "off"; the study's own evening position stays, because it never came from the group. The integration reports the window, so you notice it. To tidy up, open the window's settings and save them: you can choose another group there, or none.

### If a stored setting is faulty

Stored settings can become faulty: a file was edited by hand, a backup from another version was restored, an update changed what a value may be. The integration is built so that such a fault can neither take the protection of your windows away nor move a shutter in a way you did not ask for.

- **Whatever protects or holds a shutter back keeps working.** Fire, storm, frost protection, motor protection, the rule that a shutter stays partly open in front of a tilted window, and everything else that protects people or the hardware or limits a movement never stops because of a faulty setting. The faulty value is skipped and the value of the next level is used: the group's instead of the window's, the house's instead of the group's, and at last the built-in default.
- **A convenience function that the fault concerns pauses.** For functions that move shutters for your convenience, such as the schedule or shading, the integration does not guess. If the faulty value is the one a window would have used, that function pauses for this window until the setting is repaired. The shutter then simply stays where it is as far as that function is concerned; everything else keeps running.
- **Only the windows concerned.** A faulty setting of a group concerns the windows of that group that take this setting from the group. A window that has its own valid value for it keeps running, and so do the windows of other groups. A faulty setting of the house concerns every window that takes this setting from the house.
- **You get a repair notice that names the setting** and the level it is stored on, so you know what to open and save again.

If the settings of a whole level cannot be read at all, the integration cannot know which settings are concerned. It then pauses all convenience functions for the windows of that level, and everything that protects or holds back carries on with the values of the other levels. A group that was removed is not such a case: as described above, its windows simply take their values from the house, and nothing pauses.

## How the integration decides

For every window there is exactly one place that decides where the shutter goes. Whenever something changes (the time, the weather, a window contact, a switch you flipped), the integration works out the answer again from scratch, in three steps. It never "remembers" an order that it still has to carry out; it always looks at the situation as it is now.

### Step 1: Who wants something?

Several parts of the integration can have an opinion about a window. They are asked in a fixed order, and **the first one that has an opinion wins**:

1. Fire alarm
2. Weather protection (storm, hail and similar events)
3. Sleep mode
4. A request from one of your automations
5. Privacy when the lights are on
6. Sun shading and solar heating
7. The daily schedule

Most of the time only the schedule has an opinion, so the schedule decides. When a storm begins, weather protection has an opinion too, stands higher in the list, and wins. When the storm is over, it has no opinion any more and the schedule decides again. Nothing has to be "restored" for that.

A part can also say **"leave the window alone"**. That counts as an opinion: nothing moves, and the parts further down the list are not allowed to move the window either. The fire alarm uses this. After an alarm has ended, the shutters stay where they are until somebody confirms that the alarm is over. If you close a shutter by hand in that time, it stays closed.

If a part cannot see what it needs, for example because a sensor is unavailable, it never guesses a position. A part that protects something holds the window where it is; a part that is only about comfort steps aside and lets the next one decide.

### Step 2: Is there a limit?

The winning wish can be limited, but it is never replaced by something else. Two limits are built in so far:

- **Direction.** The morning opening only ever raises a shutter, and the evening closing only ever lowers one. A shutter that you have already lowered further than the evening position is not raised again in the evening.
- **Frost protection.** While it is freezing, the integration opens a shutter only up to the frost position (90 % by default) instead of fully, so the shutter does not run into a frozen end stop. Closing is never limited. You can lift this for a window when you know the shutter is free. If the temperature sensor stops reporting, the integration keeps what it last knew for a day. After that it does not assume "no frost": it applies the limit as a precaution, says so in its record (`frost_limit_source_blind`), and carries on normally as soon as the sensor reports again or you lift the limit. The integration cannot detect a shutter that is frozen in place; it can only avoid the movement that does the damage. Every frost setting (the temperature source, the threshold, the frost position and so on) can be set for the house, for a group or for a single window, like any other setting. Frost protection and motor protection restrict movement, so a faulty stored value never switches them off: the value of the next level applies, last the built-in default, and the fault is reported.

No limit ever applies to a fire alarm.

### Step 3: May the integration move now?

Finally the integration checks whether it is allowed to move the shutter at this moment. The checks run in a fixed order, and the first one that says "no" decides. The most important ones:

| Check | Holds back |
|---|---|
| **Maintenance lock** | everything, including the fire alarm. Use it when somebody works on the shutter. |
| **The shutter is already there** | everything; there is nothing to do. |
| **Operating mode** | "Protection only": comfort movements. "Off": comfort and weather protection. The fire alarm still opens. |
| **Pause** | comfort movements. Weather protection and the fire alarm still move the shutter. |
| **Somebody just used the shutter during a storm** | weather protection and comfort, for a short time (15 minutes by default). |
| **Manual override** | comfort movements: what you set by hand stays, until the override ends. Weather protection and the fire alarm still move the shutter. |
| **The shutter is still moving** | comfort movements, until it has come to rest. A command that is already under way is never sent a second time, whoever wants it; if a storm or a fire alarm wants exactly the movement that is already running, it simply takes that movement over. |
| **Motor protection** | comfort movements that would change the position by only a few percent (fully open and fully closed are always driven), and repeated adjustments that come too soon after the last one (10 minutes by default). Something new is not a repetition: the evening closing, switching on sleep mode or the start of shading run on time, even right after another movement. |
| **Dry-run** | everything. See below. |

Pause, maintenance lock and operating mode can be set for a single window, for a group, or for the whole installation. **The strictest setting wins**: if the group is paused, every window in it is paused, whatever the window itself says.

"Comfort movements" are everything except weather protection and the fire alarm: the schedule, shading, sleep mode, privacy and requests from automations.

A fire alarm ignores almost all of these checks: operating mode, pause, manual override and motor protection do not hold it back. Only two things stop it: the maintenance lock, because a moving shutter could injure somebody who works on it, and dry-run, because a window in dry-run never moves at all. In both cases the integration still reports the alarm.

### Every decision has a reason

Whatever the outcome is, the integration records why: which part won, which limit applied, and which check held the movement back, each as a fixed reason such as `schedule_night`, `frost_limit` or `paused`. There are no free-text explanations that could mean different things on different days. The parts that did not win report their reason too, so you can see, for example, that shading would have liked 40 % while a storm kept the shutter closed.

When a movement is only postponed, the decision says until when. If the integration cannot know when (it waits for a shutter to become available again), it says when it will look again at the latest.

### Dry-run: watching without moving

A new window starts in dry-run. In dry-run the integration decides exactly as it would otherwise, but never moves the shutter. Its record shows what *would* have happened: "would have sent 30 %", or the reason why it would not have moved, such as `paused`. This lets you compare the integration with what your existing automations do before you hand a window over. To make this realistic, the integration remembers what it would have sent, so it can tell you, for example, that a second movement five minutes later would have been held back by motor protection. When you arm the window, these pretend movements are forgotten and the window starts fresh.

### Example 1: An evening with frost

It is a winter evening, -3 °C outside, and frost protection is set up for the living room window. The shutter is fully open.

1. **Who wants something?** No fire alarm, no storm, no sleep mode, no shading. The schedule says: it is night, close the shutter (0 %), lowering only. The schedule wins with the reason `schedule_night`.
2. **Is there a limit?** Going from 100 % to 0 % is lowering, so the direction is fine. Frost protection only limits opening, so it has nothing to say.
3. **May it move?** No lock, no pause, no manual override, the shutter is at rest, and the change is large enough. Nothing holds the movement back.

Result: the shutter closes fully. Reason: `schedule_night`, outcome `sent`.

The next morning it is still -3 °C. The schedule now wants 100 %, raising only. Frost protection limits the opening to 90 %, and the record says `schedule_day`, limited by `frost_limit`, outcome `sent`. Around noon the temperature climbs clearly above freezing. The integration works out the answer again, frost protection no longer applies, and the shutter opens the remaining 10 %.

### Example 2: A storm while the window is paused

You have paused the bedroom window because you are painting the frame, and the shutter is half open. In the afternoon a storm warning becomes active.

1. **Who wants something?** Weather protection wants the shutter closed (0 %) with the reason `protection_event`. It stands above the schedule and wins. The schedule still reports that it would have liked the day position.
2. **Is there a limit?** No limit that is built in so far applies to this movement.
3. **May it move?** The window is paused, but pause only holds back comfort movements. Weather protection is not a comfort movement, so the shutter closes. Outcome: `sent`.

Had you set the **maintenance lock** instead of pause, nothing would have moved, and the record would say `protection_event`, held back by `maintenance_lock`. That is the difference between the two: pause means "leave the comfort automation out of this for a while", the maintenance lock means "nothing may move this shutter".

If the same window were still in **dry-run**, the shutter would not move either, and the record would say `protection_event`, `dry_run`, would have sent 0 %. A schedule movement at the same moment would show `paused` instead, because that is what would have held it back.
