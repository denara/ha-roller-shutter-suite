# Configuration flow findings (spike S2)

| | |
|---|---|
| Result of | Work block S2, "Spike: subentries, sections and inheritance in the configuration UI" |
| Binding for | Block H01 and every later block that adds a configuration step |
| Tested against | Home Assistant Core 2026.9.2 (installed through `pytest-homeassistant-custom-component` 0.13.365), `probatio` 0.11.4 |
| Spike code | Branch `spike/s2-config-flow`, created from `main` as it was after block T02. It is never merged. Its tests are `tests/ha/test_s2_*.py`; run them with `uv run pytest tests/ha` as described in [testing.md](testing.md). On that branch the whole suite, `ruff check`, `ruff format --check` and `mypy` pass. |
| Date | 2026-09-20 |

Every statement below is backed in one of two ways. **[test]** names a test on the spike branch that runs green, under the log guard of `tests/ha/conftest.py`, which fails a test as soon as Home Assistant logs a deprecation about the integration. **[source]** names a primary source; all of them are listed in [section 13](#13-sources). Statements about what the *browser* does come from the source code of the Home Assistant frontend, because the test harness has no browser; [section 12](#12-what-could-not-be-determined) says what that leaves open.

The spike uses no `voluptuous`, no `show_advanced_options`, no options flow, and adds no warning filter.

---

## 1. Recommendations for H01 at a glance

| Topic | Recommendation |
|---|---|
| Reload | The config entry registers **one update listener that schedules the reload**. Every flow ends with `async_create_entry` or `async_update_and_abort`. No flow ever calls a reloading method. ([section 6](#6-question-5-reload-without-deprecation)) |
| Inheritance in forms | **Pattern (a), refined:** a number is an optional field in box mode, empty means "inherit"; a boolean is a drop-down with "inherit / on / off" whose "inherit" entry names the inherited state; the inherited value and its source appear in the helper text of the field. ([section 5](#5-question-4-inheritance-in-forms)) |
| Module layout | A **feature registry**. Each feature package describes its settings as data and owns one translation fragment per language; the step methods of all three flows and the translation files are generated from the registry. ([section 8](#8-question-7-progressive-configuration-and-the-modular-layout)) |
| Cover groups | Recognize a group by three signals (the entity's group information, the member list in its state, the `group` platform in the entity registry), resolve recursively, show the members in a **menu step** that also offers the way back, store members only. ([section 10](#10-cover-groups-recognizing-resolving-showing)) |
| Group reference | Optional drop-down built from the group subentries when the form is shown. Removal of a group **cannot be prevented**; the window falls back to the house and a repair issue says so. ([section 3](#3-question-2-the-group-reference)) |
| Unavailable options | Leave the field out and put a **read-only stand-in field** in its place whose translated label and helper text give the reason. ([section 7](#7-question-6-capability-aware-options)) |

---

## 2. Question 1: what subentry flows can do

**Answer.** A subentry flow can do everything a config flow can: several steps, sections, selectors, menus, errors, placeholders. `ConfigSubentryFlow` derives from the same base class as `ConfigFlow` (`data_entry_flow.FlowHandler`), which is where `async_show_form`, `async_show_menu`, `add_suggested_values_to_schema` and `section` live [source: CORE-CE, CORE-DEF]. The developer documentation describes only the entry points, not the limits: "An integration can implement subentry flows to allow users to add, and optionally reconfigure, subentries." and "Subentries can be reconfigured, similar to how config entries can be reconfigured." [source: DOC-FLOW]. The open item of the brief ("whether subentry flows officially support several steps and sections") is therefore answered by source and test, not by an explicit sentence in the documentation.

- **[test]** `test_s2_q1_subentry_flows.py::test_subentry_flow_has_several_steps_selectors_and_a_section`: a group flow walks `basics` → `features` → `feature_daily_routine`; the last step has a collapsed section.
- **[test]** `...::test_section_input_arrives_nested_and_is_stored_flat`: the input of a section arrives nested under the section's key, exactly as for config flows.

### The exact API (Core 2026.9.2)

Declaring the subentry types, on the config flow class [source: DOC-FLOW, CORE-CE]:

```python
@classmethod
@callback
def async_get_supported_subentry_types(
    cls, config_entry: ConfigEntry
) -> dict[str, type[ConfigSubentryFlow]]:
    return {"group": GroupSubentryFlow, "window": WindowSubentryFlow}
```

| Operation | Call | Notes |
|---|---|---|
| Create (in a flow) | `self.async_create_entry(title=..., data=..., unique_id=...)` in a `ConfigSubentryFlow` whose source is `user` | Raises `ValueError` for any other source. The flow manager then calls `hass.config_entries.async_add_subentry(entry, ConfigSubentry(...))`. |
| Create (in code) | `hass.config_entries.async_add_subentry(entry, ConfigSubentry(data=MappingProxyType(...), subentry_type=..., title=..., unique_id=...))` | For migrations. |
| Reconfigure step | `async def async_step_reconfigure(self, user_input=None) -> SubentryFlowResult` | The frontend offers "reconfigure" for a subentry type only if this method exists. Inside: `self._get_entry()` and `self._get_reconfigure_subentry()`. |
| Update (in a flow) | `self.async_update_and_abort(entry, subentry, *, unique_id=, title=, data=, data_updates=)` | `data` replaces, `data_updates` merges; both together raise. Ends the flow with abort reason `reconfigure_successful`, which needs a translation. |
| Update and reload (in a flow) | `self.async_update_reload_and_abort(entry, subentry, *, ..., reload_even_if_entry_is_unchanged=True)` | **Raises `ValueError("Cannot update and reload entry with update listeners")` if the entry has an update listener.** See [section 6](#6-question-5-reload-without-deprecation). |
| Update (in code) | `hass.config_entries.async_update_subentry(entry, subentry, *, data=, title=, unique_id=)` | Returns `True` and calls the update listeners only if something changed. |
| Remove | `hass.config_entries.async_remove_subentry(entry, subentry_id)` | Also clears the subentry from the device and entity registries, which deletes its devices and entities. This is what the frontend's delete command calls; **the integration is not asked** ([section 3](#3-question-2-the-group-reference)). |

All signatures are quoted from `homeassistant/config_entries.py` at the tested version [source: CORE-CE]. This closes the brief's open item "the exact signatures for updating a subentry".

- **[test]** `...::test_subentry_is_created_reconfigured_and_removed` runs the whole life cycle through these calls.

The frontend can also rename a subentry without starting a flow: the websocket command `config_entries/subentries/update` accepts a `title` and nothing else [source: CORE-WS]. H01 must therefore treat the **subentry title as the name** of a group or window and never keep a second copy of the name in the data.

Translations of subentry flows live under `config_subentries.<type>` with the keys `entry_type`, `initiate_flow`, `step`, `error`, `abort` (and `progress`, `create_entry`) [source: DOC-I18N, CORE-HASSFEST].

---

## 3. Question 2: the group reference

**Choosing the group.** The window form has an optional `SelectSelector` in drop-down mode. Its options are built each time the form is shown, from the entry's subentries of type `group`: `SelectOptionDict(value=<subentry ID>, label=<subentry title>)`. The field is optional and has no default: left empty, the key is missing from the input, and that means "no group, inherit from the house". If no group exists, the field is left out, because a select without options is useless.

- **[test]** `test_s2_q2_q3_group_reference_and_devices.py::test_group_is_chosen_from_the_groups_that_exist`
- **[test]** `...::test_value_is_inherited_over_two_levels_at_runtime`: house → group → window, observed after the reload through a dummy sensor.

**Removing a group that windows refer to.** Home Assistant offers **no hook** to refuse or even notice the removal before it happens: the delete command calls `async_remove_subentry` directly [source: CORE-WS, CORE-CE]. "Prevented" (N4) is therefore not available; "handled with a defined fallback" is. The spike shows this fallback:

1. The removal changes the entry, the update listener reloads it.
2. During set-up, a window whose `group_id` is not among the entry's subentries inherits from the house only.
3. A repair issue names the window ("The group of window … no longer exists"). It is not fixable by a button; the fix is to open the window's form.
4. The window's form does not pre-select a group that no longer exists, so saving it stores "no group", and the next set-up deletes the issue.

Set-up does **not** correct the stored reference itself: changing subentry data during set-up would call the update listener and reload a second time.

- **[test]** `...::test_removing_a_group_cannot_be_refused_and_falls_back`

An alternative for the owner: the documentation of "removing a group" could simply state this behavior, and H01 could add the number of windows that use a group to the group's device or to a diagnostic sensor, so the user sees it before deleting. No API allows a confirmation dialog of our own.

---

## 4. Question 3: devices

**Answer.** Yes, a group can have a device of its own. The rule "a device belongs to one config entry and to at most one config subentry" [source: BLOG-DEVREG] limits a *device*, not the number of devices per entry: the group's device and each window's device are different devices, each tied to exactly one subentry. What the rule excludes is what guardrail 5 already excludes: a window device that also belongs to its group.

How it is done in the spike:

- Window entities are added with `async_add_entities([...], config_subentry_id=subentry.subentry_id)` and carry `DeviceInfo(identifiers={(DOMAIN, subentry_id)}, name=subentry.title)`.
- The group device, which has no entity yet, is created with `device_registry.async_get_or_create(config_entry_id=..., config_subentry_id=..., identifiers=..., name=...)`.
- Removing the subentry removes its device and entities without any code of ours (`async_remove_subentry` clears both registries).

**Deprecations.** The calls used are free of them: `async_get_or_create` with keyword arguments, `dr.async_entries_for_config_entry`, `async_get_device_by_identifier(identifier, config_entry_id)`, and the singular attributes `DeviceEntry.config_entry_id` / `config_subentry_id`. The device registry of 2026.9.2 reports these as deprecated, and H01 must avoid them [source: CORE-DEVREG]:

| Deprecated | Use instead | Breaks in |
|---|---|---|
| `device_registry.async_get_device(identifiers=..., connections=...)` | `async_get_device_by_identifier`, `async_get_device_by_connection`, `async_get_devices` | 2027.8 |
| `device_registry.devices[...]`, `.devices.get(...)` and the other mapping methods | iterate, or `async_get`, `async_entries_for_config_entry` | 2027.9 |
| `DeviceEntry.config_entries`, `config_entries_subentries` | `config_entry_id`, `config_subentry_id` | A silent compatibility shim: nothing is logged, so the log guard cannot catch it. Removal is possible from 2027.8. |
| `device_registry.deleted_devices`, `async_is_composite_device_id` | none needed | 2027.9 |
| Non-string values in identifiers | strings | 2026.12 |
| `DeviceEntry.suggested_area` (reading it) | none needed | announced for 2026.9, still present and logging |

The spike does not use `via_device` at all. A window could point to its group's device that way, but a window can change its group and have none, and nothing needs the link; H01 should leave it out.

- **[test]** `test_s2_q2_q3_group_reference_and_devices.py::test_groups_and_windows_each_own_one_device`: one device per subentry, the entity is attached to the window's subentry and device, removal deletes both, and the log guard stays silent.

---

## 5. Question 4: inheritance in forms

### 5.1 What forms can and cannot do

These facts decide the comparison:

1. **The browser leaves out empty fields.** When a step is submitted, the frontend sends only values that are neither `undefined` nor `""` [source: FE-FORM]. An emptied optional field is therefore *absent* from `user_input`. A number box that is emptied yields `undefined` [source: FE-NUMBER]. This is what makes "empty means inherit" possible.
2. **A toggle has no empty state.** A `BooleanSelector` is on or off. Once stored, an optional boolean cannot be returned to "absent" by the user. This is the classic trap; any pattern that represents "inherit" as "absent" needs a different control for booleans.
3. **A slider has no empty state** either. `NumberSelector` must use `mode="box"`.
4. **Placeholders reach almost every string.** The frontend passes `description_placeholders` to the step title and description, to field labels, to field helper texts (`data_description`), to error messages, and to menu descriptions and options [source: FE-SUBFLOW]. They do not reach the labels of selector options.
5. **The backend does not know the user's language.** Nothing in the flow context carries it [source: CORE-DEF]. Every text the backend builds and passes as a placeholder is untranslated. Placeholders must therefore carry only language-neutral content: numbers with units, entity IDs, names the user chose.
6. **A form is static.** There is no way to hide, show or disable a field in reaction to another field of the same step, and there is no "back" button. (The development branch of the frontend contains conditional visibility of fields, but Core 2026.9.2 offers no way to send such a condition; see [section 12](#12-what-could-not-be-determined).)

### 5.2 The three patterns

All three were built as real forms over the same three settings (a boolean, a number whose valid value is zero, an expert number), in a subentry type that exists only on the spike branch (`flow/pattern_lab.py`), and put through the same trials.

| | (a) empty means inherit | (b) a switch per value | (c) a list of own values |
|---|---|---|---|
| Form | One field per setting. Number: optional box. Boolean: drop-down "inherit / on / off". | Two fields per setting: a toggle "own value" and the value, which always shows the effective value. | Step 1: a multi-select "values this level sets itself". Step 2: only those fields, required, pre-filled with the inherited value. |
| Effective value visible? | Yes: in the helper text of a number ("Inherited at present: 60 % (from South)") and in the "inherit" entry of a boolean ("Inherit (at present: off)"). | Yes, in the field itself, which is the strongest display. | Only as text in the description of step 1; in step 2 inherited values are not shown at all. |
| Return to "inherit" | Empty the number; pick "Inherit" in the drop-down. | Switch the toggle off. The stale value next to it stays visible and must be reset or ignored. | Remove the entry from the list. |
| Boolean round trip | Works. | Works. | Works. |
| Number with valid zero | Works: only the absence of the key means "inherit". | Works. | Works. |
| Two levels | Works; the source is named. | Works; the source is not shown unless a helper text is added. | Works; the source is named in the description. |
| Traps | None found on the backend. Depends on fact 1 above. | A value changed while its toggle is off is silently lost, or needs an error message ("You changed this value, but 'own value' is switched off"); the same error appears when returning to "inherit" with a stale value. Both are demonstrated. | Two forms per step. The list of options grows with every feature. |
| Strings per setting and language | label + helper text (2). Shared once: 4 option labels, 1 hint sentence. | 2 labels + helper text (3). | option label + label + helper text (3), plus the inherited values in a description that has to list them. |
| Fields on a step with 10 settings | 10 | 20 | 1, then as many as were picked |

- **[test]** `test_s2_q4_inheritance_patterns.py`: `test_pattern_a_shows_inherited_values_from_two_levels`, `test_pattern_a_boolean_round_trip_and_zero`, `test_pattern_a_in_the_window_flow_over_two_levels`, `test_pattern_b_round_trip`, `test_pattern_c_round_trip`. Each round trip overrides a boolean and sets a number to zero, reopens the form, and returns both to "inherit".

### 5.3 Recommendation: pattern (a), refined

**Why.** It is the only pattern with one field per setting, it shows the effective value and its source next to the field, it needs the fewest strings, and the state of a form can be read at a glance: a filled field is an own value, an empty field or "Inherit" is inherited. Pattern (b) doubles every form and has a trap that needs an error message in both directions. Pattern (c) hides inherited values at the moment the user types own ones and adds a form per step. Pattern (c) remains attractive for one case, a window with dozens of settings of which two differ; if the forms of pattern (a) turn out too long in practice, (c) can be added later as an additional entry path without changing the stored data, because all three patterns store the same thing: **a key that is absent is inherited.**

**The rules of the pattern** (implemented in `flow/inheritance.py` on the spike branch):

| Kind | Control on group and window level | "Inherit" is | Own value shown as |
|---|---|---|---|
| Number | `probatio.Optional(key)` with `NumberSelector(mode="box", min, max, unit)` | the field is empty, the key is absent | `suggested_value` (never `default`: a default would come back when the field is emptied) |
| Boolean | `probatio.Required(key, default=<current>)` with `SelectSelector(options=[<inherit entry>, "on", "off"], mode="dropdown", translation_key="inherited_switch")` | the inherit entry is selected | default `"on"` or `"off"` |
| Entity, text, time (not built in the spike) | optional selector; the inherited value goes into the helper text | empty | `suggested_value` |
| Choice from a list (not built) | like a boolean: a drop-down with an additional "inherit" entry | the inherit entry | default |

The boolean drop-down offers exactly **one** of two inherit entries, `inherit_on` or `inherit_off`, chosen by the backend from the inherited state. Both are translated once for the whole integration ("Inherit (at present: on)" / "Inherit (at present: off)"). This is how the effective value of a boolean becomes visible *and* translated although placeholders cannot reach option labels. For a choice from a list this trick does not scale; there the inherited value goes into the helper text as the raw option key, or the drop-down gets a plain "Inherit" entry. H01 has no such setting yet.

For every field the step passes two placeholders: `{<key>_inherited}` (for example `60 %`) and `{<key>_source}` (the title of the group, or the title of the config entry for the house). The helper text of a number on group and window level ends with one shared sentence: "Leave empty to inherit. Inherited at present: {…_inherited} (from {…_source})."

On the **house level** nothing is inherited: every field is required, has a default, and a boolean is a plain toggle.

**What the user sees**, step `feature_daily_routine` of a window in group "South"; the group sets the morning position to 60 %, the house switches "open in the morning" on:

```text
Daily routine
When and how far the shutter moves in the morning and in the evening.

Open in the morning        [ Inherit (at present: on)   v ]
  Switch off for rooms that stay dark in the morning.

Morning position           [            ] %
  100 % is fully open, 0 % fully closed. Leave empty to inherit.
  Inherited at present: 60 % (from South).

Evening position           [ 0          ] %          <- own value; zero is valid
  100 % is fully open, 0 % fully closed. Leave empty to inherit.
  Inherited at present: 0 % (from Roller Shutter Suite).

> Expert values                                       <- collapsed section
```

**Two levels.** The window's form resolves "inherited" over group and house and names the level the value really comes from; the same resolution runs at set-up. The spike contains a small stand-in for the resolver of block C02; H01 uses C02's resolver and its provenance instead.

**Feature switches are settings.** "Shading on/off" is an inheritable boolean like any other, shown with the same drop-down in the step `features`. A façade group can switch shading on for all its windows, and one window can switch it off again.

---

## 6. Question 5: reload without deprecation

**The rule of Home Assistant.** "As of Home Assistant Core 2026.6, using a config entry listener together with any reloading methods in a config flow is deprecated", an error from 2026.12; the combination can "cause the integration to reload twice and/or create a race condition" [source: BLOG-RELOAD]. In Core 2026.9.2 this is implemented differently for the two kinds of flow [source: CORE-CE]:

- `ConfigFlow.async_update_reload_and_abort` with a listener present **logs** a usage report ("has an update listener and should use it for scheduling a reload", breaks in 2026.12.0). The log guard of this repository turns that into a test failure.
- `ConfigSubentryFlow.async_update_reload_and_abort` with a listener present **raises `ValueError`** already today.

**Which of the two allowed combinations.** For this integration only one of them works:

| | No listener, flows reload | Listener reloads, flows only update |
|---|---|---|
| Reconfigure of a subentry | reloads once | reloads once |
| Reconfigure of the entry | reloads once | reloads once |
| **Creating** a subentry | **nothing reloads.** `async_create_entry` of a subentry flow only adds the subentry; the new window would not be set up until the next restart. | reloads once |
| **Removing** a subentry | **nothing reloads**; devices and entities are deleted by Home Assistant, but the integration's runtime objects for that window keep running. | reloads once |
| Renaming a subentry from the UI | nothing reloads | reloads once |

Home Assistant calls the update listeners after `async_add_subentry`, `async_update_subentry`, `async_remove_subentry` and `async_update_entry`, and only if something actually changed [source: CORE-CE]. **Recommendation:**

```python
async def _async_reload_on_update(hass: HomeAssistant, entry: ConfigEntry) -> None:
    hass.config_entries.async_schedule_reload(entry.entry_id)

# in async_setup_entry, after the platforms are forwarded:
entry.async_on_unload(entry.add_update_listener(_async_reload_on_update))
```

and in every flow: `async_create_entry(...)` to create, `async_update_and_abort(...)` to change; for the config entry's own reconfigure flow `self.async_update_and_abort(self._get_reconfigure_entry(), data_updates=...)`. A flow with several steps collects its input in the flow object and saves once, in its last step; that is what keeps a three-step reconfigure at one reload.

- **[test]** `test_s2_q5_reload.py::test_each_change_sets_the_entry_up_exactly_once`: a counter in `async_setup_entry` goes 1 → 2 (group created) → 3 (window created) → 4 (group reconfigured over three steps) → 5 (window reconfigured, title and data at once) → 6 (window removed). After the group's reconfigure the window's dummy sensor shows the group's new value.
- **[test]** `...::test_reconfigure_of_the_house_sets_up_exactly_once`
- **[test]** `...::test_reconfigure_without_a_change_does_not_reload`: saving an unchanged form reloads nothing.
- **[test]** `...::test_reloading_method_is_refused_while_a_listener_exists`: the forbidden combination raises.
- All of them run under the log guard: no deprecation and no usage report about the integration is logged.

---

## 7. Question 6: capability-aware options

**Answer.** Forms cannot disable a field. The alternatives, judged by the requirement "always with a plain-language reason" (F7), which includes "in the user's language":

| Alternative | Verdict |
|---|---|
| Leave the field out and explain in the step description through a placeholder | The reason would be text built by the backend, which does not know the user's language ([section 5.1](#51-what-forms-can-and-cannot-do), fact 5). Only usable for language-neutral parts such as the name of the limiting cover. **Rejected as the carrier of the reason.** |
| `ConstantSelector` as an information field | It shows a text without an input. Its translation is looked up under `selector.<key>.value` [source: FE-CONST], and `hassfest` at 2026.9.2 does not allow a `value` key under `selector` [source: CORE-HASSFEST]; without a translation it shows the untranslated `label`. **Rejected.** |
| Abort the flow with a reason | Translated and with placeholders, but it ends the whole flow. Right when *nothing* can work (the selection contains no cover), wrong for one option of many. |
| **A read-only stand-in field** | **Recommended.** The real field is left out. In its place the step shows an optional `BooleanSelector(read_only=True)` with the key `<key>_unavailable`, switched off. Its label and helper text are ordinary translated strings with placeholders: "Hold to move: not available" / "{limited_by_stop} cannot be stopped, so hold-to-move and stop-on-press are unavailable." The frontend renders a read-only selector as a disabled control and does not submit it [source: DOC-DEF, FE-FORM]. |

Details that H01 and H12 need:

- The stand-in must sit on the **top level** of the form, not inside a section: the frontend strips read-only values only there [source: FE-FORM]. The backend ignores every `*_unavailable` key anyway, so a client that submits one cannot smuggle a value in.
- Capabilities are the lowest common denominator of the window's members, and the placeholder names the member that limits it (architecture document, section 9).
- An own value that was stored for the option earlier is dropped when the step is saved while the option is unavailable.
- Capabilities are known on the window level only. A **group** can therefore set "hold to move: on", and a window whose cover cannot stop inherits it. The window's form explains it; at runtime the inherited value must be masked by the capability profile. This is a requirement for the resolver (C02) or the runtime (H02/H12), not something a form can solve.
- The spike reads `supported_features` and `current_position` from the state. For a cover that has no state at configuration time, `homeassistant.helpers.entity.get_supported_features` falls back to the entity registry [source: CORE-ENTITY]; H01 should use it.

- **[test]** `test_s2_q6_capabilities.py::test_option_is_replaced_by_a_read_only_reason` (two members, one cannot stop) and `...::test_option_is_offered_when_every_member_supports_it`.

---

## 8. Question 7: progressive configuration and the modular layout

**Branching works.** A step returns the result of whichever step comes next, so a flow can branch on stored or freshly entered values. The spike's flows run `basics` → `features` (the feature switches) → one step for every feature whose **effective** switch is on → save. A feature that is off, whether by own choice or by inheritance, gets no step.

- **[test]** `test_s2_q1_subentry_flows.py::test_only_enabled_features_get_a_step`

**The layout.** Home Assistant finds a step by the name of a method on the flow class (`async_step_<step_id>`). That would force every feature block to edit three flow classes (house, group, window). The spike avoids it:

```text
custom_components/roller_shutter_suite/
  config_flow.py            config flow of the house; declares the subentry types
  flow/
    model.py                SettingField, FeatureFlow, LevelContext, resolve (plain dataclasses)
    inheritance.py          the pattern of section 5: schema, placeholders, parsing
    steps.py                FeatureStepsMixin + install_feature_steps (generated step methods)
    covers.py               cover groups, uniqueness, capabilities
    group_flow.py           GroupSubentryFlow
    window_flow.py          WindowSubentryFlow
  features/
    __init__.py             FEATURES = (DAILY_ROUTINE, SHADING, ...)   <- one line per feature
    daily_routine/
      flow.py               FEATURE = FeatureFlow(feature_id, fields, validate)
      strings.en.json       the feature's translation fragment
      strings.de.json
  translations_src/
    base.en.json, base.de.json   everything that is not a feature step, plus shared templates
scripts/build_translations.py    writes strings.json, translations/en.json, translations/de.json
```

- A feature describes its settings as data: key, kind, default, range, unit, "expert" (goes into the collapsed section), "requires" (a capability). It may add a validation function over the effective values of its step.
- `install_feature_steps` is a class decorator. For every feature in the registry it attaches a method `async_step_feature_<id>` to the flow class. All three flows use it, so **a feature block adds its package and one line in the registry and touches no flow class.**
- A feature whose step cannot be described as a list of fields can still ship a hand-written step function; the registry entry then carries the function instead of the field list. The spike did not need this.
- Sections: each generated step has at most one section, `expert`, collapsed. Sections cannot be nested [source: DOC-DEF], and a generated step does not try.

- **[test]** `test_s2_q1_subentry_flows.py::test_every_feature_contributes_its_step_to_every_flow`, `...::test_a_feature_validates_its_own_step`

**Translations are the harder half.** Three facts [source: DOC-I18N, CORE-HASSFEST, FE-SUBFLOW]:

1. Home Assistant loads one file per language; an integration cannot split it.
2. The strings of a step live under the flow that shows it: `config.step.<id>` for the house, `config_subentries.group.step.<id>` and `config_subentries.window.step.<id>`. A feature step that exists on all three levels needs its strings three times.
3. The `[%key:…%]` references that Core uses against such repetition are resolved by Core's own build; a custom integration ships `translations/*.json` as they are.

Written by hand this means six copies of every label (three levels, two languages) and a merge conflict in the same three files for every feature block. **Recommendation:** each feature keeps one fragment per language next to its code; a small script fans the fragments out to the three levels, appends the shared inheritance hint with the field's own placeholder names on the inheriting levels, and writes the three files. A test fails when the committed files differ from what the script produces, and another test checks that both languages use the same placeholders in every string. The existing key-parity test keeps working unchanged.

- **[test]** `test_s2_q7_translations_build.py` (three tests)

---

## 9. Question 8: a cover that already belongs to another window

**Answer.** The first step of the window flow resolves the selection into member covers ([section 10](#10-cover-groups-recognizing-resolving-showing)) and compares them with the members stored in every *other* window subentry of the entry. On a conflict the form is shown again with an error on the covers field; the error text is a translation with placeholders, passed through `description_placeholders`: "{cover} already belongs to the window "{window}". A cover can belong to one window only." The form keeps what the user typed. On reconfigure the window's own subentry is excluded from the comparison. If the conflicting cover came in through a cover group, the error names the **member**, as the architecture document requires.

- **[test]** `test_s2_q8_covers_and_groups.py::test_cover_of_another_window_is_refused_with_an_explanation`, `...::test_window_may_keep_its_own_cover_on_reconfigure`, `...::test_group_with_a_member_of_another_window_is_refused`

The check runs when the form is submitted. Two flows that are open at the same time could both pass it; H01 should repeat the check in the last step, right before saving. The subentry `unique_id` cannot express the rule, because a window has several members.

---

## 10. Cover groups: recognizing, resolving, showing

The architecture document (section 9) requires that a selected Home Assistant cover group is resolved into its members, recursively, shown before saving, and that only members are stored.

**Recognizing.** Home Assistant 2026.9 is in the middle of a change here [source: CORE-GROUPHELPER, CORE-GROUPCOVER]:

- A new mechanism exists: an entity can carry group information (`Entity.group`, classes `GenericGroup` and `IntegrationSpecificGroup`), such entities are listed by `homeassistant.helpers.group.get_group_entities(hass)`, their state gets a `group_entities` attribute, and `expand_entity_ids` resolves them recursively.
- **In 2026.9.2 only the lock group uses it. The cover group does not**, so `expand_entity_ids` leaves a cover group as it is.
- A cover group is still what it always was: an entity of the `group` platform whose state attribute `entity_id` lists the members.

The spike therefore asks three signals, newest first, and treats the first that answers as authoritative: (1) the entity's group information, (2) the member list in the state (`group_entities`, then `entity_id`), (3) the entity registry: platform `group` plus the `entities` option of the group's config entry, which still answers while the group has no state. Signal 2 also covers a cover group defined in YAML without a unique ID, which has no registry entry. When the cover group moves to the new mechanism in a later release, signal 1 takes over without a change.

**Resolving** is recursive with a guard against cycles, keeps the order of the selection, drops duplicates and ignores members that are not covers.

**Showing.** If at least one group was taken apart, the flow shows a **menu step** `members` before it goes on: the description names the group and lists the members (entity IDs, passed as placeholders, which is language-neutral), and the two menu entries are "Continue with these covers" and "Choose other covers". A menu is used because flows have no "back" button: the second entry leads back to the selection form, pre-filled with what the user had entered. Nothing is saved before the last step of the flow. The stored data contains the members; on reconfigure the form shows the members, not the group.

- **[test]** `test_s2_q8_covers_and_groups.py::test_real_cover_group_is_recognized_and_resolved` (a real cover group of the `group` integration, and a group inside a group), `...::test_group_without_registry_entry_is_recognized_by_its_state`, `...::test_group_without_state_is_resolved_from_its_config_entry`, `...::test_members_are_shown_before_saving_and_stored_instead_of_the_group`

Groups that a vendor integration provides (`IntegrationSpecificGroup`) are resolved by signal 1 as soon as the integration announces them. A vendor "group cover" that does not announce itself in any of the three ways is indistinguishable from a single cover and is treated as one member.

New windows are stored with `dry_run: true` (architecture document, section 13); the flow does not ask. **[test]** `test_s2_q1_subentry_flows.py::test_subentry_is_created_reconfigured_and_removed`.

---

## 11. Limits of Home Assistant that affect the brief or the architecture document

These are reported to the project owner. None of them was worked around silently; where the spike shows a way to live with a limit, it says so.

1. **The removal of a group cannot be prevented (N4).** Home Assistant removes a subentry without asking the integration. Of N4's two options, "prevented or handled with a defined fallback", only the second exists. Proposed fallback: inherit from the house, repair issue, repaired by saving the window's form ([section 3](#3-question-2-the-group-reference)).
2. **Every change reloads the whole entry, and with it every window (G3).** "Windows can be added … and removed individually without affecting the others" holds for configuration and devices, but at runtime adding, changing or removing one window unloads and sets up all of them, because the reload is per config entry. Restart safety (E6) makes this correct, but it has consequences the runtime blocks must know: an expectation window, a pending deferred command, a staggered collective movement or a dam timer that is in flight during a reload must survive it through the persisted state. If that proves too disruptive, the update listener is the place to become smarter later (compare old and new subentries and add or remove a single window without a reload); the recommended pattern keeps that door open, the other pattern would not.
3. **"Shown disabled" does not exist (F7), and backend-built text is never translated.** An unavailable option is realized as a read-only stand-in field with a translated reason ([section 7](#7-question-6-capability-aware-options)). Anything the backend composes (placeholders) must be language-neutral. This also limits how an inherited *choice from a list* can be displayed ([section 5.3](#53-recommendation-pattern-a-refined)).
4. **Forms are static and have no "back".** No field can react to another field of the same step. Progressive configuration therefore works by steps, never inside a step, and "show the resolved members before saving" is a step of its own ([section 10](#10-cover-groups-recognizing-resolving-showing)). A flow that is closed half-way saves nothing.
5. **A group cannot validate a capability.** Groups have no covers, so a group can set an option that some of its windows cannot support ([section 7](#7-question-6-capability-aware-options)). The effective settings of a window need a capability mask outside the forms.
6. **Cover groups are not yet part of Home Assistant's new group mechanism** in 2026.9.2, so recognizing one relies on the state attribute `entity_id` of the `group` platform ([section 10](#10-cover-groups-recognizing-resolving-showing)). This is long-standing behavior, but it is not a documented API. The three-signal approach is the mitigation; the block that ships it should re-check the cover group at the then-current version.
7. **Translations cannot be modular by themselves.** One file per language, strings repeated per flow type, no key references for custom integrations. The generator of [section 8](#8-question-7-progressive-configuration-and-the-modular-layout) is a build step the repository has to own, including a CI check that the generated files are current (the spike's test does that).
8. **Type checking of schemas.** The flow API of Core 2026.9.2 is still annotated with `voluptuous.Schema`, while the brief requires `probatio` and the repository bans the import of `voluptuous`. At runtime Home Assistant aliases `voluptuous` to `probatio` at import time [source: CORE-INIT], so a `probatio.Schema` is the right object; only `mypy --strict` rejects it as an argument of `async_show_form`, `section` and `add_suggested_values_to_schema`. The spike bridges this in one documented function that returns the schema typed as `Any`. H01 needs the same single bridge, or a decision by the owner to accept a narrower `type: ignore`. This also answers the brief's unverified item: `import voluptuous` keeps working in 2026.9.2 through that alias; how long is not stated anywhere.
9. **The name of a group or window can change outside any flow** (rename in the UI, [section 2](#2-question-1-what-subentry-flows-can-do)). The subentry title is the name; the listener reloads on a rename, and the device name follows at the next set-up.

**Brief and architecture document on N3.** Both now say the same: a window has one or more covers operated as a unit, a selected Home Assistant cover group is resolved visibly into its members, the group entity itself is not used, and "a cover belongs to at most one window" is validated per member. The spike follows that; no contradiction between the two documents was found in the area of this block.

**Members with their own values (architecture document, section 9, decision 9, and the capability profile of section 8.1)** add a third inheritance step *inside* a window: a member inherits the window's measurements unless it states its own, and position source, report delay and travel times are stated per member. The spike did not build this. The recommended pattern covers it without change (a member's form is one more inheriting level whose parent is the window), and a flow can show the same step repeatedly, once per member, with the member's name as a placeholder. This is a proposal, not a tested result; see below.

---

## 12. What could not be determined

| Item | Why | Proposal |
|---|---|---|
| How the forms look and behave **in a browser**: that an emptied number box, a cleared drop-down and an emptied multi-select are really left out of the submission; that a read-only boolean is rendered as a disabled control with its label and helper text; that an emptied field *inside a section* is left out as well | The test harness has no frontend. The statements rest on the frontend's source code, read on its development branch on 2026-09-20, not at a tag that matches Core 2026.9.2. For values inside a section the frontend's filter does not apply (it only looks at the top level); an emptied number there becomes `undefined`, which JSON drops, but an emptied text would arrive as `""`. | H01 checks the three trials of the recommended pattern by hand in a running Home Assistant 2026.9 before the pattern is declared final, and treats `""` like an absent key everywhere. Until then keep inheritable text fields out of sections. |
| Whether `hassfest` accepts everything the spike's translation files contain | `hassfest` is introduced by block T03 and was not available to the spike. The keys used are all in the schema of `script/hassfest/translations.py` at 2026.9.2 as far as it was read; the fragments and `translations_src/` files are extra files inside the integration folder, which `hassfest` may or may not tolerate. | H01 runs `hassfest`. If extra JSON files inside the integration folder are a problem, the fragments move to a folder outside `custom_components/`. |
| Whether importing `homeassistant.components.cover` (for `CoverEntityFeature`) obliges the manifest to list `cover` under `dependencies` or `after_dependencies` | A `hassfest` rule; same reason. | H01 runs `hassfest` and adds what it asks for. |
| Per-member steps (one step shown once per member) | Not built; out of the eight questions. | See the end of [section 11](#11-limits-of-home-assistant-that-affect-the-brief-or-the-architecture-document); first thing to try in the block that adds member-specific values. |
| Conditional visibility of fields | The frontend's development branch evaluates a `visible` condition per field [source: FE-COND]. Core 2026.9.2 has no way to send one. | Watch the developer blog. If it arrives, pattern (b) becomes much better (the value field could appear only while its toggle is on) and the recommendation should be revisited. |
| That the deprecated combination really *logs* for the config entry's own flow | Proving it needs a test that provokes the report and clears it, which the rules of this block exclude. | The source is unambiguous [source: CORE-CE]; nothing to do. |

---

## 13. Sources

Read on 2026-09-19 and 2026-09-20. "Core" is the Home Assistant Core source at version 2026.9.2, read in the installed package and identical to the tag on GitHub.

- **[DOC-FLOW]** Developer documentation, *Config flow*, section on subentry flows: <https://developers.home-assistant.io/docs/config_entries_config_flow_handler/>
- **[DOC-DEF]** Developer documentation, *Data entry flow* (sections: "Only a single level of sections is allowed; it's not possible to have sections inside a section."; read-only fields: "define an optional selector as usual, but with the `read_only` flag set to `True`"; suggested values; menus): <https://developers.home-assistant.io/docs/data_entry_flow_index/>
- **[DOC-I18N]** Developer documentation, *Backend localization* (`config_subentries` is "a map of maps, where the keys are the subentry types supported by the integration"): <https://developers.home-assistant.io/docs/internationalization/core/>
- **[BLOG-RELOAD]** Developer blog, 2026-05-07, *Deprecating config entry listener with reloading methods in config flow*: <https://developers.home-assistant.io/blog/2026/05/07/config-entry-listener-together-with-reloading-methods>
- **[BLOG-DEVREG]** Developer blog, 2026-07-21, *Devices are restricted to a single config entry and at most one subentry*: <https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/>
- **[CORE-CE]** Core, `homeassistant/config_entries.py`: `ConfigSubentryFlow` (`async_create_entry`, `async_update_and_abort`, `async_update_reload_and_abort`, `_get_entry`, `_get_reconfigure_subentry`), `ConfigSubentryFlowManager.async_finish_flow`, `ConfigEntries.async_add_subentry` / `async_update_subentry` / `async_remove_subentry`, `ConfigFlow.async_update_reload_and_abort` (usage report, `breaks_in_ha_version="2026.12.0"`): <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/config_entries.py>
- **[CORE-DEF]** Core, `homeassistant/data_entry_flow.py`: `FlowHandler`, `section`, `async_show_menu`, `add_suggested_values_to_schema`: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/data_entry_flow.py>
- **[CORE-WS]** Core, `homeassistant/components/config/config_entries.py`: websocket commands `config_entries/subentries/update` (title only) and `config_entries/subentries/delete`: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/config/config_entries.py>
- **[CORE-DEVREG]** Core, `homeassistant/helpers/device_registry.py`: `async_get_or_create`, `async_get_device_by_identifier`, `async_clear_config_subentry`, and the usage reports listed in section 4: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/helpers/device_registry.py>
- **[CORE-GROUPHELPER]** Core, `homeassistant/helpers/group.py`: `Group`, `GenericGroup`, `IntegrationSpecificGroup`, `get_group_entities`, `expand_entity_ids`: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/helpers/group.py>
- **[CORE-GROUPCOVER]** Core, `homeassistant/components/group/cover.py` (sets the state attribute `entity_id`, does not set `Entity.group`) and `lock.py` (does): <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/components/group/cover.py>
- **[CORE-ENTITY]** Core, `homeassistant/helpers/entity.py`: `get_supported_features`, the `group_entities` capability attribute: <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/helpers/entity.py>
- **[CORE-INIT]** Core, `homeassistant/__init__.py`: `install_as_voluptuous()`, "Probatio replaces voluptuous as the validation engine": <https://github.com/home-assistant/core/blob/2026.9.2/homeassistant/__init__.py>
- **[CORE-HASSFEST]** Core, `script/hassfest/translations.py`: allowed keys of a step (`title`, `description`, `data`, `data_description`, `menu_options`, `menu_option_descriptions`, `submit`, `sections`), of `selector` (`choices`, `options`, `unit_of_measurement`, `fields`), and of `config_subentries`: <https://github.com/home-assistant/core/blob/2026.9.2/script/hassfest/translations.py>
- **[FE-FORM]** Frontend, development branch, `src/dialogs/config-flow/step-flow-form.ts`: the submission leaves out values that are `undefined` or `""` and fields whose selector is read-only; a read-only selector is rendered disabled: <https://github.com/home-assistant/frontend/blob/dev/src/dialogs/config-flow/step-flow-form.ts>
- **[FE-SUBFLOW]** Frontend, development branch, `src/dialogs/config-flow/show-dialog-sub-config-flow.ts`: translation keys under `config_subentries.<type>`, and `description_placeholders` passed to title, description, field label, field helper, error, menu description and menu option: <https://github.com/home-assistant/frontend/blob/dev/src/dialogs/config-flow/show-dialog-sub-config-flow.ts>
- **[FE-NUMBER]** Frontend, development branch, `src/components/ha-selector/ha-selector-number.ts`: an emptied box yields `undefined`; box mode versus slider: <https://github.com/home-assistant/frontend/blob/dev/src/components/ha-selector/ha-selector-number.ts>
- **[FE-CONST]** Frontend, development branch, `src/components/ha-selector/ha-selector-constant.ts`: the translation is looked up as `<translation_key>.value`: <https://github.com/home-assistant/frontend/blob/dev/src/components/ha-selector/ha-selector-constant.ts>
- **[FE-COND]** Frontend, development branch, `src/components/ha-form/conditions.ts`: conditional visibility of form fields: <https://github.com/home-assistant/frontend/blob/dev/src/components/ha-form/conditions.ts>
