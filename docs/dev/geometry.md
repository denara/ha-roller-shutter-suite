# Sun geometry and glass calibration

Shading lets the sun enter a room only up to a permitted depth. How far a shutter has to come down for that is plain geometry, and it lives in one package, `custom_components/roller_shutter_suite/core/geometry/`. The package knows nothing about layers, episodes, temperatures or Home Assistant. It reads no clock and asks no port; every function is pure, every type is frozen. It answers one question:

> For this sun position and this window: is the sun on the window at all, and to which position does each member have to move so that the sun enters no further than permitted?

The shading layer (a later block), the status display and the simulation all use the same answer. What a user has to measure is described in [Shading by geometry](../features/shading-geometry.md).

| Module | Content |
|---|---|
| `core/model/geometry.py` | the measurements as values: `ShadingGeometrySettings` (the window), `MemberGlass` (one member), `GlassCalibration` (one motor), with their value rules |
| `core/geometry/sun.py` | the sun relative to the window: `horizontal_angle`, `incidence`, `sun_on_window` → `SunOnWindow` |
| `core/geometry/element.py` | one element, one curtain edge: `ShadedElement`, `free_glass_length`, `curtain_edge`, `covered_fraction`, `members_for_edge`, and the entry point `compute_shading` → `ShadingGeometry` |
| `core/geometry/calibration.py` | covered fraction ↔ motor position: `position_for_cover`, `cover_at_position`, `ideal_position`, `end_position_for`, and `to_position`, the one place that rounds |

## Conventions

Each is stated once in the code (`core/model/geometry.py`) and tested.

| Convention | Meaning |
|---|---|
| Angles | Degrees. |
| Azimuth | Clockwise from north: east is 90, south 180, west 270. |
| Orientation of a window | The azimuth of the outward normal of the glass, projected onto the ground: the compass direction a person faces who looks out of the window. |
| Left and right | As seen from inside, looking out. |
| Horizontal angle `g` | Sun azimuth minus orientation, wrapped to more than -180 and at most 180. **Positive means that the sun stands to the right.** For a window that faces south, the sun in the south-west is at +45. The subtraction wraps around north: a window that faces 350 sees the sun at 10 at +20. |
| Lengths | Metres. Lengths on the glass are measured **along the glass**, also when it is tilted. |
| Pitch `b` | The angle between the glass and the horizontal: 90 is vertical glass, 0 is glass that lies flat. The top edge of tilted glass leans into the room. |
| Position | As everywhere in the core: 0 is closed, 100 is open. A **covered fraction** runs the other way: 0 means that the glass is free, 1 that it is fully covered. |
| Depth `D` | How far the sun may shine into the room: measured on the floor, perpendicular to the façade, from the point below the lower edge of the glass (for vertical glass: from the inside of the glass plane). |

## The sun relative to the window

`sun_on_window(sun, settings)` returns a `SunOnWindow`:

| Field | Meaning |
|---|---|
| `on_window` | the sun is above the horizon, not below the end elevation, inside the field of view, and in front of the glass |
| `exclusion` | if not: the first reason, a `SunExclusion`, in this order: `below_horizon` (elevation zero or negative), `below_end_elevation`, `left_of_view`, `right_of_view`, `behind_glass`. `None` exactly when the sun is on the window. |
| `start_permitted` | the sun is on the window **and** at least at the minimum elevation for the start of shading |
| `horizontal_angle` | `g`, or `None` when the orientation of the window is not known |

`SunExclusion` is not a reason code. The shading layer turns it into one; this block adds no reason codes.

**Field of view.** The sun is inside while `-view_left ≤ g ≤ view_right`; a limit itself is inside. The two limits are independent, and each may reach 180 degrees, because tilted glass is also reached from behind the ridge.

**Elevation limits (feature C7).** Both are inputs here; what an episode does with them is the shading layer's business. Below `end_elevation` the sun is not on the window. `min_elevation` covers horizon obstruction: between the two, the sun is on the window, so a running episode goes on, but `start_permitted` is false. The two values need no order: a start never happens below the end elevation either, so the higher of the two is what a start needs (`ShadingGeometrySettings.start_elevation`).

**The plane of the glass.** In a frame with `x` to the right, `y` outwards along the normal and `z` up, the direction to the sun is `(cos h · sin g, cos h · cos g, sin h)` for the elevation `h`, and the outward normal of glass with the pitch `b` is `(0, sin b, cos b)`. Their product is the **incidence**:

```text
incidence = cos h · cos g · sin b + sin h · cos b
```

The sun shines onto the glass while the incidence is positive (above `GRAZING`, a value far below anything a sun position can resolve). For vertical glass that is `cos h · cos g`: at and beyond the façade plane (`|g| ≥ 90`) the sun is not on the window, and neither is a sun in the zenith. Tilted glass is reached by a high sun from behind: straight from behind, as soon as the elevation exceeds the pitch. The sine and cosine of this package are exact at the right angles, so a pitch of exactly 90 and a sun exactly in the façade plane are computed without a rounding residue.

**Without a known orientation** (`orientation_known` is off, the default) the horizontal direction is not judged: only the elevation limits and the glass plane decide, and every computation assumes the sun straight ahead. That is the deepest the sun can shine into the room, so the result never shades less than the real angle would need.

## Ray height and the curtain edge

The glass of a window is treated as one **element**: a strip of the height `L` (`element_height`, along the glass) whose lower edge lies `B` (`element_bottom`) above the floor.

```text
   vertical glass (b = 90)                 tilted glass (b < 90)

   top of element ──┐                          top ╲
                    │ ▓ e (covered)                 ╲ ▓ e
     curtain edge ──┤─ ─ ─ ray ─ ─ ─ ╲               ╲─ ─ ─ ray ─ ╲
                    │  t_free          ╲       t_free  ╲            ╲
   lower edge ──────┤                   ╲               ╲ lower edge ╲
                    │ B                  ╲              │ B           ╲
   floor ═══════════╧═════════════════════╲═     ═══════╧══════════════╲══
                    |←──────── D ────────→|              |←───── D ────→|
```

A point of the glass at the length `t` above the lower edge lies `B + t · sin b` above the floor and `t · cos b` inside the room. The ray through it reaches the floor at the depth

```text
d(t) = t · cos b + (B + t · sin b) · cos g / tan h
```

`d` grows with `t`, so the glass may stay free from its lower edge up to the length at which `d` reaches the permitted depth `D`:

```text
t_free = (D · sin h − B · c) / (c · sin b + sin h · cos b)        with c = cos h · cos g
```

The denominator is the incidence, which is positive whenever the sun is on the window: nothing divides by zero, for no sun position.

**Vertical glass.** With `b = 90` this is `t_free = D · tan h / cos g − B`. The first term is the **ray height**: the height above the floor up to which the sun may enter.

```text
ray height = D · tan h / cos g
```

The more obliquely the sun strikes the façade, the longer its path across the floor per unit of depth, so the shutter may stay higher: that is the factor `1 / cos g`, and it follows from the geometry, not from a separate rule (feature C1). Close to the façade plane the factor grows without bound, and an error of a few degrees in the orientation changes it a lot. It is therefore **capped**: `cos g` never counts as less than `1 / amplification_cap`. The default cap is 2, which is reached at 60 degrees; beyond that the shutter stays where it is at 60. For tilted glass the same capped cosine is used, also for a sun behind the ridge, which errs towards more shade.

**In general** the ray height is the height at which the limiting ray passes the glass, `B + t_free · sin b`. It is the quantity the decision is made in (decision 9 of the design specification): the same for all members, not clamped to the element, and what the decision record will carry.

**The curtain edge** is the covered length from the top of the element, clamped to it:

```text
e = clamp(L − t_free, 0, L)
```

**Per member:** each member covers the part of `e` that falls into its own range, from its `top_offset` (how far the top edge of its glass lies below the top of the element) and its `glass_height`:

```text
covered fraction = clamp(e − top_offset, 0, glass_height) / glass_height
```

Members side by side at the same height have the same offset; a member without an offset has offset 0. A `ShadedElement` refuses a member whose glass reaches below the element.

## Glass calibration

The motor percentage and the free glass rarely match: the curtain travels a bit before it reaches the glass, and it reaches the sill before the motor reports 0. Two positions per motor correct that (`GlassCalibration`, feature C2):

| Value | Meaning | Default |
|---|---|---|
| `glass_top_position` | the position at which the lower edge of the curtain reaches the upper end of the glass | 100 |
| `seat_position` | the position at which the curtain reaches the lower end of the free glass (the seating point) | 0 |

The seating point is the **smaller** number, and the two lie at least 10 apart. Between them the mapping is linear; above the glass top the glass is fully free, below the seating point fully covered:

```text
forward:   position = glass_top − covered · (glass_top − seat)
backward:  covered  = (glass_top − position) / (glass_top − seat)
```

- `position_for_cover` (forward) gives the target on the motor scale. A result that would not lie below `glass_top` covers no glass; the answer is then **fully open**, not a curtain that hangs in front of the frame. A fully covered glass gives the seating point, not 0.
- `cover_at_position` (backward) is for the status display and the decision record. A reported position is an estimate on many installations, and so is this fraction.
- `ideal_position` is the forward mapping without a calibration: the position "on the glass scale".
- **Rounding happens in one place**, `to_position`: half up to a whole position. Forward, backward and forward again gives the same position; tests walk every calibration in steps of a thousandth.
- The defaults change nothing: without a calibration, `position` equals `ideal_position`.

The tracker compares commanded and reported positions on the motor scale, so the calibration never enters that comparison.

## Members that cannot take an intermediate position

The geometry always reports the computed position. Next to it, every member gets an `end_position`: **closed as soon as the computed position covers any glass, open otherwise.** Reason: the permitted depth is an upper limit, and of the two end positions only "closed" keeps it. A threshold in the middle (the general rule for members without position control closes below 50) would let the sun in further than permitted for half of the range. Whether `end_position` is used is the shading layer's decision; the geometry does not look at capabilities.

## Simple mode

A window without measurements (`use_measurements` is off, the default) gets a fixed shading position instead of a computed one. `compute_shading` offers the same interface for it, so the shading layer does not branch: `sun` is computed as above, `computed` is false, ray height and curtain edge are `None`, every member has the `fixed_position` of the window (a motor position; no calibration is applied) and no covered fraction.

## The result

`compute_shading(sun, element)` returns one frozen `ShadingGeometry`:

| Field | Meaning |
|---|---|
| `sun` | the `SunOnWindow` from above |
| `computed` | the positions follow from measurements; false in the simple mode |
| `ray_height` | metres above the floor; `None` while the sun is not on the window and in the simple mode |
| `curtain_edge` | `e` in metres; `None` like the ray height |
| `members` | one `MemberShading` per member, in the order of the element: `member_id`, `covered_fraction`, `ideal_position`, `position` (after calibration, the one to command), `end_position` |

While the sun is not on the window, the geometry asks for nothing: every member is open, and `exclusion` says why. `to_data()` and `from_data()` turn the result into plain data and back, like the values of the core model.

It never raises for a sun position and an element that exist, and every position lies within 0 and 100. A test walks a grid of sun positions (elevation 0, 90, negative, the smallest numbers a float can hold, a sun exactly in the plane of tilted glass) over measurements at the ends of their ranges.

## How the shading layer will call it

```python
element = ShadedElement(config.geometry, members)  # members: one MemberGlass each
result = compute_shading(snapshot.sun, element)

if not result.sun.on_window:
    ...  # no opinion, or the end of an episode; result.sun.exclusion says why
elif starting and not result.sun.start_permitted:
    ...  # the sun is on the window, but too low for a start
else:
    wish = Wish.target_per_member(..., ray_height=result.ray_height)
```

`Wish` already carries `ray_height` and one target per member. For a member without position control the layer takes `end_position` instead of `position`. The layer will need reason codes for the five `SunExclusion` values (or one code for "sun not on the window" with the exclusion as detail) and for "below the start elevation"; they are added with the layer, in the closed list of the specification.

## Settings

The window-level measurements are flat, inheritable settings of the function `shading`, one field of `WindowConfig` each (`shading_<name>`), with `WindowConfig.geometry` as the view. `shading` pauses on a fault: a faulty measurement never moves a shutter to a position that somebody else's numbers gave. Every setting always has a value; "no measurements" is expressed by two switches, not by "none".

| Key | Kind | Default | Range | Reader |
|---|---|---|---|---|
| `shading_use_measurements` | boolean | off (simple mode) | | `as_bool` |
| `shading_fixed_position` | number | 30 | position 0 to 100 | `_as_position` |
| `shading_orientation_known` | boolean | off | | `as_bool` |
| `shading_orientation` | number | 180 | 0 up to, not including, 360 | `_as_number` |
| `shading_view_left`, `shading_view_right` | number | 90 | more than 0, at most 180 | `_as_number` |
| `shading_min_elevation`, `shading_end_elevation` | number | 0 | 0 to 90 | `_as_number` |
| `shading_element_bottom` | number | 0.9 m | 0 to 100 | `_as_number` |
| `shading_element_height` | number | 1.2 m | more than 0, at most 100 | `_as_number` |
| `shading_depth` | number | 0.5 m | 0 to 100 | `_as_number` |
| `shading_pitch` | number | 90 | 0 to 90 | `_as_number` |
| `shading_amplification_cap` | number | 2 | 1 to 10 | `_as_number` |
| `shading_calibration_seat` | number | 0 | position | `_as_position` |
| `shading_calibration_glass_top` | number | 100 | position | `_as_position` |

One rule spans two settings: the glass top lies at least 10 above the seating point. It raises `SettingsCombinationError` with exactly these two keys, after all single values are checked, and the built-in defaults satisfy it. The numbers behind a switch that is off are checked on their own and otherwise ignored, so a user can switch back and forth without clearing what was entered.

The element is described by its lower edge and its height rather than by "glass top above the floor": both are lengths one reads off a tape measure, the height is the same number for vertical and for tilted glass, and no rule "top above bottom" is needed that two levels of inheritance could violate together.

## The examples on paper

Both examples of decision 9 of the [design specification](../architecture.md#9-several-covers-operated-as-one-window) are tests with the numbers of that document (`tests/core/test_geometry_element.py`). In the first one the element is as high as the large member (1.4 m), and the small member (0.8 m, same sill) states a top offset of 0.6 m.

The roof example of the user documentation is a test as well: pitch 40 degrees, lower edge of the glass 1.0 m above the floor, an upper row of 1.0 m, a frame of 0.1 m, a lower row of 0.6 m (element 1.7 m along the glass), permitted depth 1.5 m, window facing south.

| Sun (azimuth, elevation) | `t_free` | Ray height | Curtain edge `e` | Upper row | Lower row |
|---|---|---|---|---|---|
| 180, 30 | negative | 0.92 m | 1.70 m | closed | closed |
| 180, 45 | 0.35 m | 1.23 m | 1.35 m | closed | 0.25 of 0.6 m covered: position 59 |
| 180, 60 | 0.81 m | 1.52 m | 0.89 m | 0.89 of 1.0 m covered: position 11 | open |
| 180, 75 | 1.31 m | 1.84 m | 0.39 m | 0.39 of 1.0 m covered: position 61 | open |
| 230, 45 | 0.73 m | 1.47 m | 0.97 m | 0.97 of 1.0 m covered: position 3 | open |

For the second row on paper: `tan 45 = 1`, so `d(t) = t · cos 40 + 1.0 + t · sin 40`, and `d = 1.5` at `t_free = 0.5 / (0.766 + 0.643) = 0.35 m`. The curtain edge is `1.7 − 0.35 = 1.35 m` from the top: the upper row and the frame (1.1 m) are covered, and 0.25 m of the lower row.
