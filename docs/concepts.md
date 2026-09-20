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

The same happens if the stored settings of a group cannot be read: the group is ignored as a whole, its windows follow the house, and the problem is reported. Other windows are never affected.
