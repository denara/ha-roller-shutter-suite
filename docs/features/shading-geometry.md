# Shading by geometry

On a sunny day a shutter does not have to be closed to keep a room cool and the screen readable. It only has to come down far enough that the sun reaches no further into the room than you allow: half a metre behind the window, say, but not onto the desk. How far that is changes all day with the position of the sun, and the integration works it out for you from a few measurements of the window.

**Status: in development.** This page describes what the integration computes and what you will have to measure. The forms in which you enter the numbers are being built; their names may differ slightly from the names used here. When shading is active at all (how warm, how bright, for how long) is a separate topic with a page of its own.

## Two ways to shade

- **Simple mode, the start for every window.** You state the direction of the window and one **shading position**, for example 30 %, and the shutter goes there while the sun is on the window. No tape measure needed.
- **Computed mode.** You switch on "use measurements" and enter the measurements below. The shutter then follows the sun: low in the morning when the sun is low and shines deep into the room, higher around noon, and it opens as soon as the sun has left the window.

You can switch between the two at any time; the numbers you entered stay.

**Both need the direction of the window.** Until you have entered it, the integration cannot tell whether the sun is on the window, and it does not shade the window at all. It never guesses: a guess would lower the shutters of a north window on every sunny day.

## The direction of the window

| Setting | What to enter | Default |
|---|---|---|
| Orientation known | Switch it on once you have entered the orientation. While it is off, the integration does not know where the window looks and does not shade it. The switch alone is not enough: if it is on, for example for the whole house, but no orientation was entered for the window, its group or the house, the window still counts as "direction unknown" and is not shaded. That is not reported as an error, because nothing you stored is wrong; the window simply stays unshaded until it has a direction. | off |
| Orientation | The compass direction you face when you look **out** of the window, in degrees clockwise from north: north 0, east 90, south 180, west 270. A compass app held flat against the glass, pointing outwards, shows it. A few degrees do not matter. | 180 |
| Field of view, left and right | How far to the side the sun can stand and still reach the window, in degrees, seen **from inside looking out**. Without an obstacle that is 90 on both sides. If a wall, a neighbouring house or a deep reveal blocks the sun on one side, enter a smaller number there: a projecting wall on the left that cuts the sun off at about 40 degrees gives "left 40, right 90". | 90 and 90 |
| Minimum elevation | How high the sun has to stand before shading **starts**. Use it when a hill, trees or houses hide the low sun: if the sun only clears them at 12 degrees, enter 12. | 0 |
| End elevation | Below this elevation the sun no longer counts as being on the window, and shading **ends**. | 0 |

Looking out of a window that faces south, the east is on your left and the west on your right. The morning sun therefore comes from the left, the afternoon sun from the right.

## The measurements of a normal window

You need a tape measure. All lengths are in metres, measured on the inside.

```text
        ┌───────────────┐ ─┬─
        │               │  │
        │     glass     │  │  height of the glass
        │               │  │
        └───────────────┘ ─┴─ ─┬─
        wall below the window  │  lower edge of the glass above the floor
   ════════════════════════════╧══════════  floor
        |←──── depth ────→|   how far the sun may shine into the room
```

| Setting | What to measure | Default |
|---|---|---|
| Lower edge of the glass | From the floor up to where the glass begins (not the window sill board, the glass). A balcony door whose glass starts at the floor has 0.1 or so. | 0.9 m |
| Height of the glass | From the lower edge of the glass to its upper edge. | 1.2 m |
| Permitted depth | How far the sun may shine into the room, measured on the floor, straight away from the window. 0 means "no direct sun at all". | 0.5 m |
| Pitch | Only for roof windows, see below. A normal window has 90. | 90 |

**What the integration does with it.** From the sun's elevation and the permitted depth follows a height at the window: light that enters below that height lands on the floor within the permitted depth; light that enters above it would reach further. The shutter covers the glass above that height.

Example: the glass begins 0.9 m above the floor and is 1.4 m high, and you allow 1.0 m of sun. The sun stands straight in front of the window.

| Sun elevation | The sun may enter up to a height of | Glass that gets covered | Shutter position |
|---|---|---|---|
| 35° | 0.70 m, which is below the glass | all of it | closed |
| 50° | 1.19 m | the upper 1.11 m of 1.4 m | 21 % |
| 60° | 1.73 m | the upper 0.57 m of 1.4 m | 59 % |
| 70° | 2.75 m, which is above the glass | nothing | open |

**Sun from the side.** When the sun does not stand straight in front of the window but well to the side, its light travels a long way along the wall before it gets deep into the room. The same permitted depth then allows a higher shutter. The integration takes that into account by itself. Very close to the wall's own direction this effect would grow without limit, and a small error in the orientation would change the result a lot, so it is **capped**: by default the shutter is never raised to more than what twice the straight-ahead height allows, which is reached when the sun stands 60 degrees to the side. The cap can be changed (1 switches the effect off; at most 10).

## Several shutters side by side

Shutters that are always operated together form one window with several members. If they are equal, there is nothing more to do: they share the window's measurements and get the same position.

If they differ, measure the window as **one element**: from the lowest glass edge to the highest glass edge. Then state for each member that differs

- its own **glass height**, and
- its **top offset**: how far the upper edge of its glass lies **below** the upper edge of the highest glass. A member that reaches up to the top has 0. A member with a top offset always needs its own glass height as well.

Example: a wide pane of 1.4 m next to a narrow one of 0.8 m, both beginning 0.9 m above the floor. The element is 1.4 m high. The narrow pane ends 0.6 m lower, so its top offset is 0.6 m. With 1.0 m of permitted sun and the sun at 50°, the wide shutter goes to 21 % and the narrow one to 36 %: different numbers, but the same edge of light on the floor. At 60° the wide one goes to 59 % and the narrow one opens fully, because the sun no longer reaches its glass too deeply.

## A roof element of two rows

A common roof element has two rows of windows above each other, each with its own shutter. For shading, the two rows act like a single tall window: there is one edge of shade, and it moves across both rows.

```text
   seen from the side                        what to measure, along the glass

              ╲  upper row                   top of the element ─┬─────────┬─
               ╲                                                 │ upper   │ glass height 1.0
                ╲  frame                                         │ row     │ top offset 0
                 ╲                                               ├─────────┤
                  ╲  lower row                      frame 0.1 →  ├─────────┤ ─ top offset 1.1
                   ╲                                             │ lower   │ glass height 0.6
     pitch 40°  ____╲                         lower edge ────────┴─────────┴─
                     │ 1.0 m                  of the glass
   ══════════════════╧════  floor             element height 1.7
```

| Setting | What to measure | In the example |
|---|---|---|
| Pitch | The angle of the roof against the horizontal: 90 is a wall, 0 would be a flat roof. The building plans state it; a level app held against the glass shows it too. | 40° |
| Lower edge of the glass | From the floor **straight up** to the lower edge of the lowest glass. | 1.0 m |
| Height of the element | **Along the glass**, from the lower edge of the lowest glass to the upper edge of the highest glass. Frames in between count. | 1.7 m |
| Per member: glass height | Along the glass. | upper row 1.0 m, lower row 0.6 m |
| Per member: top offset | Along the glass, from the top of the element down to the upper edge of this member's glass. Members of the same row have the same offset. | upper row 0, lower row 1.1 m |
| Permitted depth | On the floor, from the point straight below the lower edge of the glass into the room. | 1.5 m |
| Field of view | A roof window is also reached by a high sun from the side and even from behind the ridge, so a field of view of more than 90 degrees makes sense here. | 120 and 120 |

What comes out, for this element facing south:

| Sun | Edge of shade, from the top of the element | Upper row | Lower row |
|---|---|---|---|
| straight ahead, 30° high | 1.70 m: everything | closed | closed |
| straight ahead, 45° high | 1.35 m: in the lower row | closed | 0.25 of 0.6 m covered: 59 % |
| straight ahead, 60° high | 0.89 m: in the upper row | 0.89 of 1.0 m covered: 11 % | open |
| straight ahead, 75° high | 0.39 m: in the upper row | 0.39 of 1.0 m covered: 61 % | open |
| 50 degrees to the right (south-west), 45° high | 0.97 m: in the upper row | 0.97 of 1.0 m covered: 3 % | open |

If the edge lies in the lower row, the upper row is closed and the lower one drives to the computed value; if it lies in the upper row, the upper row closes partly and the lower one stays open. The low sun of the first line reaches too deep even through the lowest strip of glass, so everything closes. In the last line the sun stands at the same height as in the second one, but well to the side, and much more glass may stay free.

## The two calibration values

The percentage of a shutter and the glass it covers rarely match. At 100 % the curtain is rolled up in its box; it travels a little before its lower edge appears at the top of the glass. And it reaches the bottom of the glass before the motor says 0 %, because the slats still close up after that. Two values per shutter correct this, and you find them with the position slider of the cover in Home Assistant:

1. **Position at the upper glass end.** Open the shutter fully. Lower it in small steps until the lower edge of the curtain just reaches the upper edge of the glass. Read the position, for example 88.
2. **Position at the seating point.** Lower it further until the curtain just reaches the lower edge of the glass, before the slats close up. Read the position, for example 12.

The position at the seating point is always the smaller number, and the two must lie at least 10 apart. Between them the integration spreads the glass evenly: with 88 and 12, "half of the glass covered" is position 50, and "a quarter covered" is position 69. If nothing of the glass has to be covered, the shutter opens fully and does not wait at 88. If all of the glass has to be covered, it goes to 12, where the glass is covered, and not to 0.

Without calibration the values are 100 and 0, and the percentage is taken as it is. A tape measure helps to check: with the glass half covered by the integration's reckoning, the curtain's edge should be at half the glass height.

The values of the window apply to all its shutters. A shutter whose motor behaves differently gets its own two values.

**A word on accuracy.** Many shutter actuators do not measure the position; they calculate it from the run time. After a blocked or interrupted movement the calculated position can be off until the shutter has been at an end stop again. Shading positions are then off by the same amount.

## Shutters that cannot stop halfway

A shutter that can only open and close cannot follow the sun. For such a shutter the integration chooses between the two ends: it **closes as soon as any glass would have to be covered**, and opens otherwise. The permitted depth is a limit, and only a closed shutter keeps it.

## What happens with a faulty value

Every measurement can be entered for the house, for a group or for a window; a window uses its own measurement if it has one, otherwise that of its group, otherwise that of the house. If a saved measurement is unreadable or impossible (a pitch of 120, a glass height of 0, calibration values in the wrong order), **shading is suspended** for the windows that would have used that measurement, and the integration reports which setting is the cause and where it is saved. It does not fall back to somebody else's numbers, because a shutter must not move to a position that nobody chose. Everything else, above all the protection functions and the daily routine, keeps running.

The same holds for the values of a single shutter (its glass height, top offset and calibration): if one of them is unreadable, impossible, or does not fit the window (glass that would reach below the element, for example), shading is suspended for the **whole window**, not only for that shutter, and the report names the shutter and the value. The shutters of one window shade together or not at all.
