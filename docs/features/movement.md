# Movement

The page "Movement" of the forms holds the settings that spare the motors of your shutters. Like every setting they can be set for the house, a group or a single window, and a level that leaves a field empty inherits it ([Concepts](../concepts.md)).

| Setting | Default | What it does |
|---|---|---|
| Minimum change | 5 % | A comfort movement smaller than this is left out. |
| Minimum interval | 10 minutes | The shortest time between two comfort movements of a window. |
| Gap between motors | 2 seconds | When many shutters move together, the next motor starts this long after the previous one. |
| Look again at the latest after (expert value) | 5 minutes | How long a window waits at most, when it waits for something whose end nobody knows, before it is looked at again. |

## Minimum change and minimum interval

Comfort movements are those of the daily routine, shading and the like. Protection movements (storm, hail) and a fire alarm are never held back by these two settings.

- **Minimum change.** Shading that follows the sun would otherwise move a shutter by one or two percent again and again. A movement smaller than the minimum change is left out. A shutter is still driven fully open or fully closed, however small the rest is, so it never stays a slit open at night. A movement that restores a limit the shutter violates right now, for example the ventilation position in front of a tilted window, is driven too. The minimum change can only be judged for a cover that reports its position; a cover that reports none is always moved. 0 switches it off.
- **Minimum interval.** Between two comfort movements of a window at least this much time passes. It exists against flapping: shading that starts and stops every few minutes moves the shutter at most once per interval. Something new is not held back by it: the morning or the evening, sleep mode switched on, a request from an automation, or the start of shading moves at once. 0 switches it off.

Example: shading closes a shutter to 40 % at 13:00. At 13:04 the sun wanders and shading wants 37 %: that is less than 5 %, nothing moves. At 13:06 a cloud ends the shading, and the day position would be 100 %: the minimum interval holds that back until 13:10. At 20:00 the evening begins: that is something new, and the shutter closes at once.

## Gap between motors

When many shutters move at the same moment, for example at the evening, their motors start one after the other, with this gap between two motors. That spares the supply of the house and makes the movement quieter. It applies between windows and between the covers of one window that has several.

- A window with a gap of 0 does not stagger its own covers: they start together, when the window's turn comes.
- The largest gap is 10 seconds. With 20 shutters and the default of 2 seconds, the last one starts 38 seconds after the first.
- **A fire alarm is never staggered.** Every shutter opens at once.

The gap between the covers of one window only matters for a window with several covers.

## Look again at the latest after

Sometimes a window waits for something whose end nobody can know in advance: for a cover that is unavailable to come back, or for the covers of a window to come to rest. The window is looked at again as soon as something changes; this setting is only the safety net for the case that no change is ever reported. It is an expert value, and the default suits almost every installation.

## Faulty stored values

If a stored value of one of these settings cannot be read, the value of the next level applies (group, then house), and a repair issue names the setting. If no level has a valid value, the default applies. None of these settings is ever switched off by a fault: they protect the motors.
