# Concepts

This page explains the ideas behind Roller Shutter Suite in plain language. You do not need them to install the integration, but they help you understand why a shutter moved, or why it did not.

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
- **Frost protection.** While it is freezing, the integration opens a shutter only up to the frost position (90 % by default) instead of fully, so the shutter does not run into a frozen end stop. Closing is never limited. You can lift this for a window when you know the shutter is free. If the temperature sensor stops reporting, the integration keeps what it last knew for a day. After that it does not assume "no frost": it applies the limit as a precaution, says so in its record (`frost_limit_source_blind`), and carries on normally as soon as the sensor reports again or you lift the limit. The integration cannot detect a shutter that is frozen in place; it can only avoid the movement that does the damage.

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
