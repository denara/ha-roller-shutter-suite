# Manual operation

When you move a shutter yourself, with its wall switch, its remote, the app of its vendor or a dashboard, Roller Shutter Suite notices it and leaves the shutter where you put it for a while. This time is the **manual override**. After it the window goes back to what it should do, for example the daily routine.

**Status: pilot.** This works for every cover that reports its position and whose reporting you have stated on its page in the window's settings (see [How your covers report](#how-your-covers-report)). A window in [dry-run](dry-run.md) only writes down that something else moved the cover.

## How it tells its own movements from yours

Roller Shutter Suite remembers every command it sends: to which position, in which direction, and when. A movement that fits such a command is its own: it starts in the right direction and ends within a small tolerance of the target. Everything else is yours:

- the shutter moves although no command was sent;
- it moves in the other direction than the command asked for;
- it stops clearly short of the target, because somebody stopped it.

On a cover that reports "Opening" and "Closing" while it moves, your movement is noticed the moment it starts. On a cover that only reports its new position, it is noticed when the new position arrives.

It is a guess based on what the cover reports, never a certainty. That is why the values on the page of each cover matter: a cover that reports late, or that stops a little off its target, needs to be described as it is.

## The manual override

While the override lasts, the automatic comfort movements of the window wait: the daily routine, and in later versions shading and the other comfort functions. Protection from storm or hail and the fire alarm still move the shutter, because they protect people and hardware.

You see the override in three places:

- the entity **Manual override** of the window is on;
- the entity **Reason** reads "Moved by hand; automatic movements wait", and its attribute `manual_override` names when the override ends (`ends_at`) and the position you chose (`remembered_position`);
- the logbook of the window says "Moved by hand" and "Manual override started".

**When it ends.** By default at the next change between day and night of the daily routine: if you lower a shutter in the afternoon, the window leaves it there until the evening, and then the evening closes it as usual. To end it earlier, press the button **Resume automation** of the window: the window then moves at once to where it should be now. Nothing the window held back in the meantime is replayed; it simply decides again. Moving the shutter by hand again starts a new override.

**A restart of Home Assistant ends the override** in this version, because the window does not store it yet: if the shutter you moved by hand is not where the daily routine wants it when Home Assistant has started again, the window moves it there at once (see [section 7 of the pilot guide](../pilot.md#7-after-a-restart-of-home-assistant)). A reload of the integration, which every change of its settings causes, keeps the override.

You no longer need to switch on the **Pause** after moving a shutter by hand.

**A window with several covers** has one override for all of them. If you move one of its covers by hand, the whole window waits, and the other covers stay where they are; nothing follows the cover you moved. When the override ends, all covers go to their positions.

**Someone at the window.** A later version brings protection from storm and hail. If you move a shutter by hand while such protection holds it, the window waits 15 minutes for you instead of starting an override. After that, protection takes over again if it still applies; otherwise the window keeps your position as a manual override.

## How your covers report

Every cover of a window has a page of its own in the window's settings: open **Settings** > **Devices & services** > **Roller Shutter Suite**, find the window, choose **Reconfigure**, and go through the pages; the page of each cover follows the pages of the features ("Cover 1 of 2: cover.example_left").

| Field | What to enter | If you leave it empty |
|---|---|---|
| **Position source** | Where the position comes from. Most actuators of a plain up and down motor calculate it from the running time; some drives measure it themselves. | Calculated |
| **Tolerance** | How far the reported position may lie from the target and still count as reached. Widen it only for a cover that always stops a little off its target, and keep it as small as needed: a movement by hand smaller than the tolerance is taken for an automatic one. | 2 % for a calculated position, 3 % for a measured one |
| **How the cover reports** | **Event-driven**: the cover tells Home Assistant about every change by itself, perhaps a little late. **Polled**: Home Assistant asks the cover on a schedule and sees nothing that happens between two questions. | Not stated |
| **Reporting time** | For an event-driven cover, how late its reports arrive at most, 0 if at once. For a polled cover, how often it is asked. | Not known |
| **Travel time up**, **Travel time down** | How long the shutter takes from fully closed to fully open, and back. | 60 seconds each |

Home Assistant cannot tell by itself how a cover reports, so you state it. Two examples: many radio actuators report event-driven, some of them up to a minute late, which is a reporting time of 60 seconds; a cover that Home Assistant reaches through a HomeKit bridge is often polled, for example every 60 seconds. To find out, open the page of the cover entity, or **Developer tools** > **States**, and move the shutter with its wall switch: if the state reads "Opening" or "Closing", or the position changes step by step, the cover is event-driven; if the position only ever jumps from the old to the new value on a fixed grid, it is polled.

**While the reporting time of a cover is not stated**, Roller Shutter Suite does not judge its movements at all: it does not guess. Such a window cannot be armed, and neither can a window with a polled cover, until a later version checks every command it sends. A reporting time above zero is fine: the window simply waits that much longer before it judges a movement.

**The travel times** tell the window how long to wait for a movement before it judges it. A wrong value makes it wait too long or too short; the measurements below show the right one.

**Covers that only open and close.** A cover that does not report its position cannot tell Roller Shutter Suite that you moved it by hand. For it there is no manual override: the window takes it to be where it sent it last.

## The measurements in the diagnostics

For every movement of its own, Roller Shutter Suite measures, per cover that reports event-driven, how long the cover took to report the start (`latency_ms`), how long until it reported that it came to rest (`time_to_rest_ms`), and how far from the target it stopped (`end_deviation`). The diagnostics download of the window shows them under `movement_tracking`, next to what you stated for the cover, each with the number of movements, the median and the largest value. They keep the last twenty movements, also across a reload of the integration; a restart of Home Assistant loses them in this version, until a later version stores them.

How to use them:

- A **latency** of several seconds means the cover reports late: enter the largest latency, rounded up, as its **reporting time**.
- A **time to rest** well below the travel time of that direction, less the reporting time, means the travel time is set too long; above it, too short.
- An **end deviation** that is always a few percent means the cover stops off its target; widen the **tolerance** to just that much.

Nothing is changed automatically; the values are there for you.

## The daily count

The diagnostics also show how many comfort movements the window made today, under `comfort_movements`. If a window makes more than 40 comfort movements on one day, it says so once that day, with an event and the logbook line "More comfort movements today than the threshold". It holds nothing back; it is a hint that something moves the window more often than it should.

## If the window moves when it should not

If the window moves a shutter back after you moved it by hand, turn on its **Maintenance lock** first, then look at the logbook of the window: it names what it noticed. Check the page of the cover: is it really event-driven, is the reporting time long enough, is the tolerance too wide? Go back to dry-run if you are not sure; see [the pilot guide](../pilot.md#8-before-you-arm-a-window).

The events and logbook lines of manual operation are listed in [Status, reason events and diagnostics](status-and-events.md#events-of-manual-operation).
