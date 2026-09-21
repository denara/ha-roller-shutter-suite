# Configuration

This page shows how to set up Roller Shutter Suite, how to add groups and windows, how to change and remove them, and how values that are inherited look in the forms. Everything happens in the user interface of Home Assistant. Nothing needs a restart.

**Status.** The integration is in development. The forms described here exist and store what you enter, but the integration does not move any shutter yet. At present the forms hold the settings of [the daily routine](features/daily-routine.md); that page explains what each of them means. More settings arrive with the features they belong to, and they will look and behave exactly as described here.

If you have not read [Concepts](concepts.md) yet: settings live on three levels, the **house**, a **group** and a **window**. A window states only what is different about it. Everything else comes from its group, and what the group does not set comes from the house.

## First set-up: the house

1. Open **Settings** > **Devices & services** and choose **Add integration**.
2. Search for **Roller Shutter Suite** and select it.
3. Confirm the first page.
4. The page **Features** asks what is switched on for the house. Only a feature that is switched on gets pages of its own.
5. The pages of the daily routine follow: one general page (positions, how workdays and public holidays are recognized, summer, outdoor brightness) and one page each for workdays, weekends and public holidays (when the morning and the evening begin). Every field is filled with a sensible value, so you can simply save each page and adjust things later.
6. Save the last page. The integration appears in the list.

The integration can be added once. It stands for the whole house.

Groups and windows inherit the values of the house unless they set their own. On the house level every field therefore has a value: a field cannot be left empty there, and a switch is a plain on/off switch.

### Changing the values of the house

Open the integration, open the menu with the three dots and choose **Reconfigure**. The same pages appear, filled with the present values. Nothing is saved before the last page. When you save it, the integration reloads once, and every group and window that inherits a value follows the new one.

**Worked example.** On workdays the shutters of the whole house shall open at 06:45 instead of 07:00. Choose **Reconfigure**, save the pages **Features** and **Daily routine** as they are, set **Morning: time** to 06:45 on the page **Daily routine on workdays**, and save the remaining pages. Every window that does not say otherwise now opens at 06:45 on workdays.

## Adding a group

A group holds values that several windows share: a side of the house, a floor, a kind of room. A window belongs to one group or to none. Groups are optional; a small house may not need any.

1. Open the integration and choose **Add group**.
2. Enter a name, for example "Bedrooms".
3. The next pages are the same pages as for the house, but now every value can be inherited; see [How inherited values look](#how-inherited-values-look). Change only what is different for this group.
4. Save the last page.

**Worked example.** The bedrooms shall stay dark longer on weekends. Add a group "Bedrooms", leave everything as it is until the page **Daily routine on weekends**, and enter 10:00 in **Morning: time**. Every window that you put into this group opens at 10:00 on weekends, while the rest of the house keeps its time. Everything else in the group stays empty and therefore follows the house, also when you change the house later.

To change a group, open its menu with the three dots and choose **Reconfigure**. You can also rename it there, or with the rename function of Home Assistant; both do the same.

## Adding a window

A window is what the integration decides about. It has one device in Home Assistant and, later, one status.

1. Open the integration and choose **Add window**.
2. Enter a name and choose the **cover** of the window. Only cover entities are offered.
3. If you have groups, you can choose one. Leave the field empty and the window inherits from the house directly.
4. Go through the pages and change only what is different for this window.
5. Save the last page.

New windows start in **dry-run**: the integration will decide and record what it would do, but it will not move the shutter. You arm a window deliberately, once you have compared its decisions with reality. (Arming arrives with a later version.)

### Several covers at one window

Some windows have two or more shutters side by side that are always moved together. Choose all of them in the field **Covers**. They form one window: one device, one status, moved together, each one watched on its own.

If you choose a **cover group** of Home Assistant, the integration takes it apart and shows you the members on an extra page before anything is saved:

```text
Members of the cover group
cover.example_bay is a cover group. A group reports only the mean of its
members, so the window stores and moves the members themselves:

cover.example_bay_left, cover.example_bay_right

  > Continue with these covers
  > Choose other covers
```

The window stores the members, never the group. A group inside a group is taken apart as well. If that is not what you wanted, **Choose other covers** takes you back to the first page with your input still there.

### A cover belongs to one window only

If you choose a cover that another window already has, the form refuses it and says which cover and which window:

```text
cover.example_kitchen already belongs to the window "Kitchen".
A cover can belong to one window only.
```

This also holds for the members of a cover group: the message names the member, not the group. Remove the cover from the other window first, or choose another one.

### A cover without positions

Some covers can only be opened and closed, or do not report where they are. Such a cover is accepted. An extra page tells you what this means:

```text
Cover without positions
These covers cannot be driven to a position, or do not report one:
cover.example_garage

They are accepted and are only opened and closed. For them shading
positions, other positions in between and the detection of manual
operation are inactive.
```

If a cover is merely unavailable while you configure the window, that is no problem: the integration uses what Home Assistant last knew about it.

### An option your cover cannot do

Some options will need something from the cover, for example that it can be stopped. If one of the covers of the window cannot do that, the option is not offered. In its place stands a greyed-out field that says why and names the cover that limits it. If the window had a value of its own for that option, the value stays stored and applies again as soon as the cover can do it; a repair issue tells you about it in the meantime. None of the settings of the daily routine needs anything special from a cover.

### Changing a window

Open the menu of the window and choose **Reconfigure**. The pages show what is stored: the name, the covers (always the members, never a group), the group and the window's own values. Saving reloads the integration once. Dry-run is neither asked for nor changed by this form.

## How inherited values look

On the pages of a group and of a window every value can be inherited. What "inherit" looks like depends on the kind of field.

**A number, a time, a date: leave the field empty.** An empty field means "inherit". The line below the field tells you what is inherited at present and from where:

```text
Evening position           [            ] %
  Where the shutter goes in the evening. ... Leave empty to inherit.
  Inherited at present: 0 % (from Roller Shutter Suite).
```

Type a value and the window has its own. **Zero is a value**: an evening position of 0 % is something you set, and it wins like any other value. To go back to inheriting, empty the field again.

A day of the year, such as the first day of summer, is entered as month and day with two digits each: `05-01` is 1 May. 29 February is not accepted, because it does not exist in every year.

**A switch: choose "Inherit" in the list.** A switch on these pages is a list with three entries, because a plain on/off switch could not say "inherit":

```text
Summer by date             [ Inherit (at present: off)  v ]
                             On
                             Off
```

The first entry tells you what inheriting means right now. Choose **On** or **Off** to decide for this window, and choose **Inherit** again to follow the level above. A choice from a list, such as the trigger of the morning, works the same way: its list has the additional entry **Inherit**, and the line below names what is inherited.

**An entity that may be absent: inherit, none, or an own selection.** Such a setting has a list and an entity field below it:

```text
Workday entity             [ Inherit (at present: the entity named below) v ]
  ... Inherited at present: binary_sensor.example_workday (from Roller Shutter Suite).

Entity for workdays        [                                   ]
  Counts only with "Own selection" above.
```

- **Inherit** follows the level above.
- **None** means: this window has no such entity, although its group or the house names one.
- **Own selection** uses the entity in the field below. With the other two choices the field is ignored, also if an entity is still in it.

**Worked example: override and return.** The house closes to 0 % in the evening. The kitchen shall keep a slit open:

1. Open the window "Kitchen", choose **Reconfigure** and go to the page **Daily routine**.
2. Enter 15 in **Evening position** and save the pages. The kitchen now has a value of its own and closes to 15 %.
3. Later you change your mind. Open the same page, empty the field and save. The kitchen follows the house again, as if it had never had a value of its own.

**Expert values** sit in a section that is folded shut at the bottom of a page. Sensible defaults apply, and you only open the section if you know why. For the daily routine these are the offset to sunrise or sunset, the elevation of the sun, "not before" and "not after", the delay of the brightness and the random offset. All fields of a trigger are always shown; which of them count depends on the trigger you chose, and the text below each field says so.

**Feature switches.** The first page after the name lists the feature switches, and only the features that are switched on get pages of their own. A feature switch is inherited like any other switch: the house can switch the daily routine on, a group can switch it off for its windows, and one window of that group can switch it on again. What you had entered for a feature stays stored while it is switched off.

**Values that do not fit together.** Some values are fine one by one and still contradict each other: a morning at 21:00 cannot come before an evening that begins at 17:00. The page then shows an error at the fields concerned and names the settings, and nothing is saved until they fit.

## Removing a window or a group

Open the menu of the window or group and choose **Delete**.

- **Removing a window** removes its device and everything that belongs to it. The other windows are not affected in what they do; the integration reloads once.
- **Removing a group** that windows still refer to is possible, and Home Assistant does not ask the integration first. Nothing breaks: such a window **inherits from the house** from then on, and a repair issue names it ("The group of window ... no longer exists"). To repair it, open the window, choose another group or leave the field empty, and save. The issue disappears.

**Worked example.** You remove the group "Bedrooms", which opened at 10:00 on weekends. The windows that were in it now follow the house again, so they open at the time of the house. Home Assistant shows one repair issue per window until you have saved each of them.

## When stored settings are faulty

You will normally never see this. Stored settings can be faulty after a failed update, after a downgrade to an older version, or if somebody edited the storage by hand. The integration then does not give up:

- **The integration always loads**, and every window that can be read is set up.
- **Protection never depends on a single stored value.** A faulty setting of a function that protects people or hardware, or that restricts movement, is skipped, and the value of the next level applies: the group, then the house, then the built-in default.
- **Comfort becomes cautious.** A faulty setting of a comfort function, such as the daily routine or shading, pauses that function for the windows that would have used the value. No shutter moves unexpectedly because of a data fault.
- **Everything is reported.** A repair issue names where the fault is (the house, a group or a window, by its name), which setting it is, and what is wrong with it. If stored values of several levels do not fit together, one issue names all of them and where each is stored.
- **Only a window whose covers cannot be read is not set up.** A repair issue names it. Every other window runs as usual.

To repair a fault, open the form of the level the issue names, check the values and save. The form starts from the values that can be read, so saving writes a clean set. Removing the window or group also removes its issue.
