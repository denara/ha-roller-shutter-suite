# Dry-run

Dry-run lets you watch what the integration would do with a window before you let it move that window. A window in dry-run makes every decision exactly as an armed window does, writes down what it would have sent, and moves nothing.

## What it is for

- **Trying the integration out.** You set up a window, leave it in dry-run for a few days, and compare what it would have done with what you wanted.
- **Moving from another controller.** Your shutters may still be driven by automations or by another integration. While the window is in dry-run, the old controller keeps doing its work, and the new one only watches. There is never a moment in which two controllers fight over the same shutter.

Every new window starts in dry-run. A window moves only after you have armed it on purpose.

## It never moves anything

A window in dry-run sends no command to its covers, for no reason at all: not for the daily routine, not for shading, not for a storm or hail, and **not at a fire alarm either**. The fire event is still raised at once, so a fire alarm never goes unnoticed, but the shutter stays where it is.

Two separate checks see to it. The decision itself ends in "dry-run: would have sent", and the one part of the integration that talks to covers checks dry-run a second time before every command. If anything ever slipped past the first check, the second one still sends nothing and writes an error to the log.

**The one exception.** Suppose the check of dry-run in the decision itself fails with a programming error during a fire alarm. Then the integration cannot tell whether the window is in dry-run, and it opens the shutter: a closed escape route in a fire is the greater danger than a test window that opens once when it should not have. This is the only case in which a window in dry-run moves. It needs a fire alarm and a fault of the integration at the same moment, and the fault is written to the log.

Movements that you or another controller make are still observed in dry-run. They do not count as a manual override: next to another controller that is still active, every one of its movements would otherwise look like a person at the window. At present such a movement shows in the history and logbook of the cover and in the next decision of the window; a logbook line of the window itself for it arrives with the detection of movements by hand.

## Comparing its decisions with reality

For every decision a window in dry-run records the complete outcome, with its reason:

- "would have sent 30 %, because shading wants it", or
- "would have held back, because the window is paused", or
- "nothing to do: the target is reached". This line is the most useful one next to another controller: it means the other controller has put the shutter exactly where the integration wanted it.

The integration also remembers the last command it would have sent, with its target and its reason, and judges the next decision against it as if it had been sent: the minimum interval between two comfort movements, for example, runs from that would-be command. So the record shows the movements the integration would really have made, not one on every change of a sensor.

The status of each window and its diagnostics show these records in Home Assistant; [Status and events](status-and-events.md) explains what you see.

## Arming a window

Arming a window switches dry-run off for it: from then on it moves its covers. It is a deliberate step in the settings of the window, never a switch on a dashboard, because a window that is armed while another control still moves its shutter fights that control.

1. Open **Settings** > **Devices & services** > **Roller Shutter Suite**, find the window, open its menu with the three dots and choose **Reconfigure**.
2. Go through the pages as they are. The last page is **Operation: dry-run or armed**. Choose **Armed: move the shutters** and select **Next**.
3. The page **Arm the window** repeats the checks of the [pilot guide](../pilot.md#8-before-you-arm-a-window): nothing else moves the shutter, the old control is switched off, you have compared the decisions, you have looked at the pause, the maintenance lock and the operating mode, you know that the window starts fresh, and you know the way back. Tick each point and select **Submit**. If a point is not true yet, close the dialog: nothing is saved, and the window stays in dry-run.

The integration reloads once and starts the armed window with a clean state: nothing it would have sent in dry-run counts as sent, no manual override is armed, and nobody is taken to have moved the shutter last. Its next decision is a real one: if the shutter is not where the daily routine wants it, it moves within a few seconds. The entity **Dry-run** of the window turns off.

**A movement by hand is not noticed yet.** An armed window takes a shutter you moved by hand for one that is not where it should be, and moves it back within a few seconds; only if the integration itself moved it less than the minimum interval before (10 minutes by default) does it wait until that interval has passed. To keep a position you set by hand, turn on the **Pause** of the window before you move the shutter.

**Going back to dry-run** needs no confirmation: choose **Reconfigure** again and, on the last page, **Dry-run: decide and record, move nothing**. If a shutter moves when it should not, turn on the **Maintenance lock** of the window first, after which it sends no further command, and then go back to dry-run; see [Pause, maintenance lock, operating mode and dry-run](controls.md).

A new window always starts in dry-run; the form that adds it does not ask. Before you arm a window, switch off whatever else still drives its shutters, so that one controller moves one window.
