# The configuration flows

This page describes how the configuration of the house, of groups and of windows is built, and what a block does that adds settings or a feature. The patterns come from the [configuration flow findings](config-flow-findings.md) of spike S2; the settings themselves come from the registry of the core, described in [The core model](core-model.md#inheritance). For the user's view see [Configuration](../configuration.md).

## What is stored

One config entry is the house. Groups and windows are config subentries of the types `group` and `window`.

| Level | Identity data | Settings |
|---|---|---|
| House (entry data) | none | `settings` |
| Group (subentry data) | none; the name is the title of the subentry | `settings` |
| Window (subentry data) | `covers` (list of cover entity IDs, always members, never a group entity), `group_id` (subentry ID of the group), `dry_run`; the name is the title of the subentry | `settings` |

Rules that hold everywhere:

- **Settings live in a mapping of their own** under the key `settings` (`SETTINGS_KEY` of the core). It holds nothing but keys of the registry of the core, in the stored form that the reader of each setting takes.
- **An absent key is the only way to say "inherited" and "no group".** `null` is never written. "Explicitly none" for an optional reference is the marker constant `STORED_NONE` of the core. An empty text counts as an absent key.
- **The title is the name.** The user interface can rename a subentry outside any flow, so no second copy of the name exists.
- **Versions.** Home Assistant keeps one version per config entry and none per subentry (`ConfigSubentry` has no version field). "Subentry data carry version numbers" is therefore read as: the pair `VERSION`/`MINOR_VERSION` of the config flow, at present 1.2, covers the data of the subentries too. `async_migrate_entry` migrates both. It reports an error by raising `ConfigEntryError`, never by returning `False`, and it never fails because of a faulty *value*: judging stored values is the job of the fault rule at set-up.

`stored.py` is the one place that reads stored data. Settings go to `settings_from_stored` of the core; identity data is read tolerantly (`read_window_identity`), and nothing there raises for anything somebody stored.

## Modules

```text
custom_components/roller_shutter_suite/
  __init__.py        set-up, update listener, migration
  config_flow.py     flow of the house; declares the subentry types
  stored.py          reading stored data: settings and identity
  capabilities.py    what a cover can do -> capability profile of the core
  windows.py         stored entry -> resolved windows and repair issues
  issues.py          creating and deleting repair issues
  runtime.py, controller.py, sources.py, members.py, location.py,
  storage.py, commands.py, actuator.py
                     the runtime that feeds the core and calls it; see runtime.md
  flow/
    model.py         FieldForm, FeatureForm, Catalog, LevelContext (no Home Assistant import)
    inheritance.py   the pattern of the forms: schema, placeholders, reading input, the typing bridge
    steps.py         FeatureStepsMixin and install_feature_steps (generated step methods)
    covers.py        cover groups, "a cover belongs to one window"
    group_flow.py    GroupSubentryFlow
    window_flow.py   WindowSubentryFlow
  features/
    __init__.py      FEATURES and the catalog     <- one line per feature
    daily_routine/   the form of the feature
translations_src/    sources of the translations, outside the shipped integration
scripts/build_translations.py
```

## One description of the settings

The registry of the core (`core/settings.py`) is the only description of a setting: key, kind, function, default, reader, whether it is inherited, the capability it requires. The forms repeat none of it. A `FieldForm` adds only what the core does not know because it concerns nothing but the form:

| Field of `FieldForm` | Meaning |
|---|---|
| `key` | the key of the registry entry |
| `expert` | the field sits in the collapsed section "Expert values" |
| `minimum`, `maximum`, `step`, `unit` | the number box of a number or a duration. **A convenience of the control, not a rule**: whether a value is valid is decided by the core |
| `seconds_per_unit` | the unit a duration is entered in (60 for minutes); it is stored in whole seconds |
| `entity_domains` | limits the entity selector of an optional reference |
| `options_key` | the translation key of the options of an enumeration; settings that offer the same choice share one (the six trigger kinds of the schedule) |
| `form_name` | the name of the field in the form and in the translations, where it differs from the key: `schedule_brightness_threshold` appears as `schedule_brightness_threshold_lux`, because the key leaves the unit to its documentation. Stored data always uses the key |

A `FeatureForm` lists the pages of one feature (`StepForm`: a name and its fields; a page has at most one section, because sections cannot be nested) and names the switch of the feature, if the registry has one. A `Catalog` ties the registry, the feature forms and the resolver together and refuses a form description that does not fit the registry: an unknown key, a switch that is no inheritable boolean, a list (which needs a step of its own), a key in two forms, two pages with the same step ID, and a day of the year or a reference inside the section. A day of the year is a text field, and an emptied text inside a section was never confirmed in a browser. A time has a selector of its own and may sit in the section; like every field, an empty text from it counts as an absent key.

**A setting that is not offered yet** simply has no `FieldForm`. It stays in the registry, its stored value is kept when a form is saved, and the set-up resolves it like any other. At present these are `morning_condition_source` (the conditional morning opening is not built) and `schedule_profile` (one value), plus the settings of functions that have no form yet (frost protection, motor protection).

**A bound is never wider than the core.** `tests/ha/test_flow_model.py` hands every `minimum` and `maximum` of the shipped forms to the resolver of the core as the own value of a window and fails on a fault, so a form cannot offer a value that the core refuses.

What follows from the registry, without any code in a form:

| Kind of the registry | Control on a group and a window | Control on the house |
|---|---|---|
| `boolean` | required drop-down "inherit / on / off"; one of two inherit entries names the inherited state | toggle |
| `number` | optional number box; empty means inherit; own value as suggested value | required number box |
| `duration` | like a number, entered in the unit of the form, stored in whole seconds | required |
| `time` | optional time selector | required |
| `day_of_year` | optional text `MM-DD` | required |
| `enumeration` | required drop-down of the values of the enumeration plus "inherit" | required drop-down |
| `optional_reference` | required drop-down "inherit / none / own selection" (field `<key>_choice`) plus an entity field, which counts only with "own selection" | "none / own selection" |
| `list` | no generated field | |

- A setting with `inheritable=False` is offered to a window only.
- A setting with `requires=...` whose capability is **missing** for the window is replaced by the read-only stand-in `<key>_unavailable` on the top level of the form. The decision uses the capability *state* of the resolver: `unknown` neither masks nor reports. The own value of a masked option **stays stored** and applies again when the capability is back, as the core model specifies; `masked_own_values` of the resolver becomes a repair issue.
- Placeholders of a field: `{<key>_inherited}` and `{<key>_source}`, and `{limited_by_<capability>}` for a stand-in. Their content is language-neutral: numbers with units, entity IDs, names the user chose.

### Validation is the core's

`read_step_input` in `flow/inheritance.py` turns the input of a step into stored values and lets the core judge them:

1. **The number selector delivers floats.** A whole float is stored as an `int`. A value with a fraction is kept only if the reader of the setting accepts it; if the reader refuses it but accepts the whole number next to it, the error is `fraction_not_allowed`. A duration is always a whole number of its unit. This is the single place for the normalization.
2. The own values of the level are resolved with the resolver of the catalog. A fault on the edited level becomes a form error: `invalid_value`; for a day of the year `invalid_day_of_year`, or `leap_day_not_allowed` for 29 February, which the core's `as_day_of_year` refuses. A refusal by a rule that spans several settings (`SettingsCombinationError`) becomes `invalid_combination` at every field of the page that is concerned and can show an error, and on the form; the placeholder `{combination}` names the keys of all settings concerned, also those of another level. A field inside the section cannot show an error of its own, so its errors stand on the form. A problem code that this layer does not know is shown as `invalid_value`.
3. The house and a group have no covers. Their values are judged, and their inherited values are shown, through an imaginary window that sets nothing itself and whose one member has unknown capabilities, so nothing is masked (`PROBE_MEMBER`).

A form starts from the stored values the core can read (`sound_own_values`) and saves all own values of the level, not only those of the steps that were shown. So saving a form drops faulty values and unknown keys, and keeps values of steps that were skipped, of masked options, and of settings that no form shows.

## Adding settings to an existing feature

1. Add the settings to the registry of the core, as [The core model](core-model.md#adding-a-setting) describes.
2. Add one `FieldForm` per setting to a page of the feature's `FeatureForm` (for the daily routine: `features/daily_routine/__init__.py`), or add a page.
3. Add label and helper text to the fragments `translations_src/features/<feature>.en.json` and `.de.json`, run `uv run python scripts/build_translations.py`, and commit the generated files.

No flow class is edited. The settings of the schedule arrived this way: about fifty registry entries of the kinds `boolean`, `number`, `enumeration`, `time`, `duration`, `day_of_year` and `optional_reference`, the form description in `features/daily_routine/`, and the fragments. The 36 settings of the triggers are generated in the core from three lists (day type, edge, field); their `FieldForm`s and their texts are generated from the same lists, and tests compare both with `schedule_trigger_keys()`. `tests/ha/test_flow_inheritance.py` shows the pattern with these settings. Two things have no real setting yet, a setting that requires a capability and a setting that only a window can set and a form shows; for them `EXAMPLE_CATALOG` in `tests/ha/helpers.py` adds two made-up registry entries, put into effect by the fixture `example_catalog`.

**All fields of a trigger are shown, whatever its kind.** A form is static: a field cannot appear with the choice of another field of the same page. Showing only the fields of the chosen kind would need a page per kind and therefore a special case in a flow; it is left as a carry-over.

## Adding a feature

1. A package under `features/` with the `FeatureForm` of the feature.
2. One line in `FEATURES` in `features/__init__.py`. `install_feature_steps` attaches one method `async_step_feature_<id>_<page>` per page to all three flow classes; the method looks its page up in the catalog when it runs.
3. The fragments `translations_src/features/<feature>.<language>.json`.

If the registry has an inheritable boolean that switches the feature, name it as `switch` (`schedule_enabled` for the daily routine). The step `features` then lists it, and only the features that are effectively switched on, by an own value or by inheritance, get their pages. A feature without a switch is always on and has no entry in the step `features`; without any switch that step is skipped.

## Translations are generated

Home Assistant loads one file per language, the strings of a step live under the flow that shows it, and a custom integration cannot use key references. `scripts/build_translations.py` therefore writes `strings.json`, `translations/en.json` and `translations/de.json` from `translations_src/`:

- `base.<language>.json`: everything that is not a feature step, and the shared templates under `_templates` (the inheritance hints, the section of expert values, the errors of the generated steps, and the parts of the repair issues about stored settings);
- `features/<feature>.<language>.json`: `steps.<page>` (title, description), `fields.<name>` (label, description; for an optional reference also `entity_label` and `entity_description`), `switch` (label, description) if the feature has one, `unavailable.<name>` (label, description of the stand-in) for a setting that requires a capability, and `options.<translation key>` for the values of an enumeration.
- `generated` in a fragment holds the texts of settings that are generated from lists: a `pattern` of the field name (`schedule_{day_type}_{edge}_{field}`), the `words` of each part in this language, and under `texts` one label and one helper text per value of the last part, in which `[edge]` stands for the word of the part `edge`. Six texts per language describe the 36 trigger settings.

Which fields a step has, their kind and their section come from the catalog, which the script imports without Home Assistant. The script fans a feature step out to the three levels, appends the inheritance hint of the field's kind on the levels that inherit, and generates one repair issue per level and problem code. **Never edit the three generated files by hand.** `tests/scripts/test_build_translations.py` fails when they are not current, when English and German differ in a key or a placeholder, or when a source ends up inside the shipped integration; `uv run python scripts/build_translations.py --check` does the first of these on the command line. `tests/ha/test_translations.py` asks the forms what they show and fails when a field, an error, a menu entry or an issue has no translation.

## What a flow took from an earlier page may be gone

Home Assistant removes a subentry without asking, also while a flow is open that refers to it. A flow therefore never looks a subentry up by an ID it took earlier without checking, on the first page and again right before saving:

- **The group a window chose is gone:** the flow goes back to its first page, which no longer offers the group, with the translated error `group_removed`. It goes on as the set-up does for a group that is gone: the window inherits from the house unless another group is chosen, and no reference to the removed group is stored.
- **The group or window that is being changed is gone:** the flow ends with the translated abort reason `subentry_removed` and saves nothing.
- **A cover taken by another flow in the meantime:** the first page comes back with `cover_in_use`.
- A cover that lost its entity in the meantime needs nothing: its capabilities are read as unknown.

A name of nothing but blanks is refused (`name_blank`), because the name is the title of the subentry, which issues and messages show; blanks around a name are dropped.

## Reload

An update listener schedules the reload; every flow ends with `async_create_entry` or `async_update_and_abort` and never reloads itself. A flow collects its input and saves once, in its last step. `tests/ha/test_reload.py` counts the set-ups: one per create, reconfigure, rename and remove, none for an unchanged form.

## Set-up and repair issues

`windows.resolve_entry` reads the house, the groups and the windows, isolated per subentry, and resolves every window with the resolver of the core. What a fault costs is decided there (decision 15 of the [design specification](../architecture.md)); the Home Assistant layer only reports it:

| Issue | When |
|---|---|
| `setting_fault_<level>_<problem>` | a fault in stored settings; placeholders `{name}` (the name of the group or window) and `{key}`. Problems: `unreadable`, `none_not_allowed`, `invalid`, `not_inheritable`, `unknown_setting`, `level_unreadable`, and `other` for a problem code that a later version of the core adds. What a fault costs (its action) is not part of an issue, so an action that is added later needs nothing here |
| `setting_combination` | a rule that spans several settings refuses the effective values; `{settings}` names every reported key with the name of the level that stores it |
| `rule_without_keys` | a refusal that names no keys: an error of the integration |
| `window_covers_unreadable` | the covers of a window cannot be read; **only such a window is not set up** |
| `group_missing` | the group of a window is gone; the window inherits from the house |
| `group_reference_unreadable` | the reference to the group is no identifier (`null`, for example): a data fault, the group level counts as unreadable as a whole |
| `dry_run_unreadable` | dry-run is no boolean; the window counts as being in dry-run |
| `option_unavailable` | the window sets an option itself that its covers cannot do at present |

The house and every group are also judged through an imaginary window, so a fault is reported while no window inherits from them. None of the issues has a fix button: saving the form of the level, or removing it, repairs it, and the next set-up deletes every issue that is no longer reported.

## Capabilities

`capabilities.member_config` builds the capability profile of a cover. A cover with a usable state is read from it. A cover that is unavailable or has no state yet keeps what the entity registry last knew and is handed in as **known**; whether it reports a position cannot be seen then, so a cover that can be driven to a position is taken to report one. Only a cover without a state and without a registry entry is unknown: nothing is masked and nothing is reported for it.

## Carried over to later blocks

- **Travel times.** The capability profile of the core needs them, and they are per-member configuration values of a later block. Until then every member carries `PROVISIONAL_TRAVEL_TIME` (60 seconds). It exists in memory only, is never stored and nothing acts on it; the block that introduces per-member values replaces it and must not treat it as a value a user set.
- **Bounds and units in the registry of the core.** The bounds and units of the number boxes live in the form description. A proposal for the core: carry the range and the unit of a number in its registry entry, so forms, documentation and value rules read one source. Until then the test named above keeps the forms inside the rules of the core.
- **Fields by trigger kind.** See above: all fields of a trigger are shown.
- **Durations in minutes.** A duration that was stored by hand with seconds that are no whole minutes is shown with a fraction, and saving it unchanged is refused as a fraction.
