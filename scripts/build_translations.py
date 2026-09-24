"""Build the translation files of the integration from their sources.

Home Assistant loads exactly one file per language, and the strings of a step
live under the flow that shows it: ``config.step`` for the house,
``config_subentries.group.step`` for a group and
``config_subentries.window.step`` for a window. A custom integration cannot use
``[%key:...%]`` references, because only the build of Home Assistant Core
resolves them. A feature step that exists on all three levels would have to be
written three times per language, and every feature block would edit the same
three files.

This script writes them instead. The sources live in ``translations_src/`` at
the root of the repository, outside ``custom_components/``, so nothing but what
Home Assistant needs is shipped:

- ``base.<language>.json``: everything that is not a feature step, plus the
  shared templates under ``_templates``;
- ``features/<feature>.<language>.json``: the fragment of one feature.

Which fields a step has, which of them sit in the section of expert values,
and of which kind they are comes from the catalog of the integration
(``features/`` and the registry of the core), never from a second list here.
On the levels that inherit, the script appends the shared inheritance hint to
the helper text of a field, with the placeholders of that field. It also fans
out the repair issues about stored settings: one per level and problem, and
the words for the reason codes (``_templates.reason_codes``) to the states of
the reason sensor and to the attribute ``reason`` of the next planned action.

**Languages** are the ``base.<language>.json`` files that exist. English is
written to ``strings.json`` and ``translations/en.json``, every other language
to ``translations/<language>.json``. A language is added by adding its
fragments, nothing else.

Usage::

    uv run python scripts/build_translations.py          # write the files
    uv run python scripts/build_translations.py --check  # fail if they differ

Exit status 0: the files are written, or current. 1: ``--check`` found a file
that differs. 2: ``CANNOT CHECK``, a source is missing or cannot be used, or a
generated file cannot be read. Anything unforeseen inside the script ends with
status 2 as well, with the type of the error only, never its text or a
traceback, which may name a local path.
"""

import importlib
import json
import os
import sys
from collections.abc import Callable
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec
from pathlib import Path
from typing import Any

# `__file__` is absolute; nothing at module level touches the file system.
ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "roller_shutter_suite"
SOURCES = ROOT / "translations_src"
PACKAGE = "custom_components.roller_shutter_suite"

# The language of `strings.json`; every other language is compared with it.
SOURCE_LANGUAGE = "en"


def languages() -> dict[str, tuple[str, ...]]:
    """Return every language that has a base source, with the files it writes.

    A language is there when ``translations_src/base.<language>.json`` is:
    a new language is added with that file and one fragment per feature, and
    nothing here changes. The source language comes first and also writes
    ``strings.json``. A folder of sources that cannot be listed is a
    ``SourceError``, never "no languages".
    """
    try:
        with os.scandir(SOURCES) as entries:
            names = [entry.name for entry in entries]
    except OSError as error:
        raise SourceError(
            f"translations_src cannot be listed ({type(error).__name__})"
        ) from error
    found = sorted(
        name.removeprefix("base.").removesuffix(".json")
        for name in names
        if name.startswith("base.") and name.endswith(".json")
    )
    if SOURCE_LANGUAGE not in found:
        raise SourceError(f"translations_src/base.{SOURCE_LANGUAGE}.json is missing")
    ordered = [SOURCE_LANGUAGE, *(code for code in found if code != SOURCE_LANGUAGE)]
    return {
        code: (("strings.json",) if code == SOURCE_LANGUAGE else ())
        + (f"translations/{code}.json",)
        for code in ordered
    }


# (path of the flow in the translation file, level, does the level inherit?)
LEVELS: tuple[tuple[tuple[str, ...], str, bool], ...] = (
    (("config",), "global", False),
    (("config_subentries", "group"), "group", True),
    (("config_subentries", "window"), "window", True),
)

FAULT_PROBLEMS = (
    "unreadable",
    "none_not_allowed",
    "invalid",
    "not_inheritable",
    "unknown_setting",
    "level_unreadable",
    # A problem code that the Home Assistant layer does not know yet.
    "other",
)


class SourceError(Exception):
    """A source of the translations is missing or cannot be used."""


def load_catalog() -> Any:
    """Import the catalog of the integration without Home Assistant.

    Importing the package of the integration would execute its
    ``__init__.py``, which needs Home Assistant, and Home Assistant does not
    import on every platform. The catalog itself is plain Python. If the
    package is not imported yet, an empty stand-in is registered under its
    name for the duration of the import, so Python finds ``features`` through
    it; afterwards every trace of the stand-in is removed again.
    """
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if PACKAGE in sys.modules:
        return importlib.import_module(f"{PACKAGE}.features").get_catalog()
    before = set(sys.modules)
    spec = ModuleSpec(PACKAGE, loader=None, is_package=True)
    spec.submodule_search_locations = [str(INTEGRATION)]
    sys.modules[PACKAGE] = module_from_spec(spec)
    try:
        return importlib.import_module(f"{PACKAGE}.features").get_catalog()
    finally:
        for name in set(sys.modules) - before:
            if name == PACKAGE or name.startswith(f"{PACKAGE}."):
                del sys.modules[name]


def _load(path: Path) -> dict[str, Any]:
    try:
        content = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SourceError(f"{path.relative_to(ROOT).as_posix()}: {error}") from error
    if not isinstance(content, dict):
        raise SourceError(f"{path.relative_to(ROOT).as_posix()}: not an object")
    return content


def _hint(template: str, key: str) -> str:
    return template.replace("{inherited}", f"{{{key}_inherited}}").replace(
        "{source}", f"{{{key}_source}}"
    )


def field_texts(fragment: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Return the texts of every field of a fragment, by the name of the field.

    ``fields`` holds texts that are written out. ``generated`` holds texts for
    settings that are generated from lists, like the triggers of the schedule
    (day type, edge, field): a ``pattern`` of the field name, the ``words`` of
    each part of it in this language, and under ``texts`` one label and one
    helper text per value of the last part. In them ``[edge]`` stands for the
    word of the part ``edge``; square brackets, because braces belong to the
    placeholders of Home Assistant.
    """
    texts: dict[str, dict[str, str]] = dict(fragment.get("fields", {}))
    for block in fragment.get("generated", []):
        (last, last_texts), *_ = block["texts"].items()
        combinations: list[dict[str, str]] = [{}]
        for part, words in block["words"].items():
            combinations = [
                {**chosen, part: value} for chosen in combinations for value in words
            ]
        for chosen in combinations:
            for value, entry in last_texts.items():
                name = block["pattern"].format(**chosen, **{last: value})
                texts[name] = {
                    role: _with_words(text, block["words"], chosen)
                    for role, text in entry.items()
                }
    return texts


def _with_words(
    text: str, words: dict[str, dict[str, str]], chosen: dict[str, str]
) -> str:
    for part, value in chosen.items():
        text = text.replace(f"[{part}]", words[part][value])
    return text


def _add_field(
    target: dict[str, Any],
    item: Any,
    kind: str,
    texts: dict[str, str],
    hints: dict[str, Any] | None,
) -> None:
    """Add label and helper text of one field, with the hint of its kind.

    ``hints`` are the templates of the inheritance hints, or ``None`` on the
    level of the house, which inherits from nothing.
    """
    name = item.name
    description = texts["description"]
    if kind == "optional_reference":
        if hints is not None:
            description = f"{description} {_hint(hints['inherit_hint_choice'], name)}"
        target["data"][f"{name}_choice"] = texts["label"]
        target["data_description"][f"{name}_choice"] = description
        target["data"][name] = texts["entity_label"]
        target["data_description"][name] = texts["entity_description"]
        return
    if hints is not None:
        template = {
            "boolean": "inherit_hint_switch",
            "enumeration": "inherit_hint_choice",
        }.get(kind, "inherit_hint_empty")
        description = f"{description} {_hint(hints[template], name)}"
    target["data"][name] = texts["label"]
    target["data_description"][name] = description


def feature_step(
    catalog: Any,
    page: Any,
    fragment: dict[str, Any],
    templates: dict[str, Any],
    level: str,
) -> dict[str, Any]:
    """Return the translation of one page of a feature on one level."""
    definitions = catalog.definitions
    texts = field_texts(fragment)
    try:
        titles = fragment["steps"][page.name]
    except KeyError as error:
        raise SourceError(
            f"a fragment has no texts for the page {page.name!r}"
        ) from error
    step: dict[str, Any] = {
        "title": titles["title"],
        "description": titles["description"],
        "data": {},
        "data_description": {},
    }
    expert: dict[str, Any] = {"data": {}, "data_description": {}}
    for item in page.fields:
        definition = definitions[item.key]
        if not definition.inheritable and level != "window":
            continue
        if item.name not in texts:
            raise SourceError(f"a fragment has no texts for the field {item.name!r}")
        _add_field(
            expert if item.expert else step,
            item,
            definition.kind.value,
            texts[item.name],
            None if level == "global" else templates,
        )
        if level == "window" and definition.requires is not None:
            # Only a window has covers, so only its form shows a stand-in.
            try:
                unavailable = fragment["unavailable"][item.name]
            except KeyError as error:
                raise SourceError(
                    f"a fragment has no texts for the stand-in of {item.name!r}"
                ) from error
            step["data"][f"{item.name}_unavailable"] = unavailable["label"]
            step["data_description"][f"{item.name}_unavailable"] = unavailable[
                "description"
            ]
    if expert["data"]:
        step["sections"] = {
            "expert": {
                "name": templates["expert_name"],
                "description": templates["expert_description"],
                **expert,
            }
        }
    return step


def features_step(
    catalog: Any,
    fragments: dict[str, dict[str, Any]],
    templates: dict[str, Any],
    inherits: bool,
) -> dict[str, Any] | None:
    """Return the translated step of the feature switches, if there are any."""
    switches = [feature for feature in catalog.features if feature.switch is not None]
    if not switches:
        return None
    step: dict[str, Any] = {
        "title": templates["features_title"],
        "description": templates[
            "features_description_inheriting" if inherits else "features_description"
        ],
        "data": {},
        "data_description": {},
    }
    for feature in switches:
        texts = fragments[feature.feature_id]["switch"]
        description = texts["description"]
        if inherits:
            hint = _hint(templates["inherit_hint_switch"], feature.switch)
            description = f"{description} {hint}"
        step["data"][feature.switch] = texts["label"]
        step["data_description"][feature.switch] = description
    return step


def _fault_issues(templates: dict[str, Any]) -> dict[str, Any]:
    """Return one issue per level and problem: level, key and reason in words."""
    issues: dict[str, Any] = {}
    for level, phrase in templates["fault_levels"].items():
        for problem in FAULT_PROBLEMS:
            issues[f"setting_fault_{level}_{problem}"] = {
                "title": templates["fault_title"].replace("{level}", phrase),
                "description": " ".join(
                    (
                        templates["fault_problems"][problem],
                        templates["fault_consequence"],
                        templates["fault_repairs"][level],
                    )
                ),
            }
    return issues


def _reason_texts(result: dict[str, Any], templates: dict[str, Any]) -> None:
    """Write the words for the reason codes where the entities show them."""
    reasons = dict(templates["reason_codes"])
    sensors = result.setdefault("entity", {}).setdefault("sensor", {})
    sensors.setdefault("active_reason", {})["state"] = reasons
    next_action = sensors.setdefault("next_action", {})
    attributes = next_action.setdefault("state_attributes", {})
    attributes.setdefault("reason", {})["state"] = dict(reasons)


def build(language: str, catalog: Any | None = None) -> dict[str, Any]:
    """Return the complete translation of one language."""
    catalog = load_catalog() if catalog is None else catalog
    result = _load(SOURCES / f"base.{language}.json")
    try:
        templates: dict[str, Any] = result.pop("_templates")
        fragments = {
            feature.feature_id: _load(
                SOURCES / "features" / f"{feature.feature_id}.{language}.json"
            )
            for feature in catalog.features
        }
        for path, level, inherits in LEVELS:
            flow = result
            for key in path:
                flow = flow.setdefault(key, {})
            steps = flow.setdefault("step", {})
            flow.setdefault("error", {}).update(templates["errors"])
            switches_step = features_step(catalog, fragments, templates, inherits)
            if switches_step is not None:
                steps["features"] = switches_step
            for feature in catalog.features:
                for page in feature.steps:
                    steps[feature.step_id(page)] = feature_step(
                        catalog, page, fragments[feature.feature_id], templates, level
                    )
        selectors = result.setdefault("selector", {})
        for feature in catalog.features:
            options = fragments[feature.feature_id].get("options", {})
            for key, labels in options.items():
                selectors[key] = {
                    "options": {
                        "inherit": templates["enumeration_inherit_option"],
                        **labels,
                    }
                }
        result.setdefault("issues", {}).update(_fault_issues(templates))
        _reason_texts(result, templates)
    except KeyError as error:
        raise SourceError(
            f"language {language!r}: the key {error} is missing"
        ) from error
    return result


def render(language: str, catalog: Any | None = None) -> str:
    """Return the file content of one language."""
    return json.dumps(build(language, catalog), ensure_ascii=False, indent=2) + "\n"


def outdated() -> list[str]:
    """Return the generated files that differ from what the sources yield."""
    catalog = load_catalog()
    found: list[str] = []
    for language, targets in languages().items():
        content = render(language, catalog)
        for target in targets:
            try:
                current = (INTEGRATION / target).read_text(encoding="utf-8")
            except FileNotFoundError:
                current = None
            except (OSError, UnicodeDecodeError) as error:
                raise SourceError(
                    f"{target} cannot be read ({type(error).__name__})"
                ) from error
            if current != content:
                found.append(target)
    return found


def main(arguments: list[str] | None = None) -> int:
    """Write the translation files, or check them with ``--check``."""
    arguments = sys.argv[1:] if arguments is None else arguments
    try:
        if arguments == ["--check"]:
            found = outdated()
            for target in found:
                sys.stdout.write(f"out of date: {target}\n")
            if found:
                sys.stdout.write(
                    "run `uv run python scripts/build_translations.py` and commit\n"
                )
                return 1
            compared = sum(map(len, languages().values()))
            sys.stdout.write(
                f"translations: ok; compared {compared} generated file(s)\n"
            )
            return 0
        catalog = load_catalog()
        for language, targets in languages().items():
            content = render(language, catalog)
            for target in targets:
                (INTEGRATION / target).write_text(
                    content, encoding="utf-8", newline="\n"
                )
    except SourceError as error:
        sys.stdout.write(f"translations: CANNOT CHECK, so this is a failure: {error}\n")
        return 2
    return 0


def run(entry: Callable[[], int]) -> int:
    """Run ``entry``; an error nobody foresaw is a failure too, never a pass.

    Only the type of the error is printed. Its text and a traceback may name
    local paths, and the output of this script may be pasted in public.
    """
    try:
        return entry()
    except Exception as error:  # noqa: BLE001 - the net for every unforeseen error
        sys.stdout.write(
            "translations: CANNOT CHECK, so this is a failure: internal error in "
            f"build_translations.py ({type(error).__name__})\n"
        )
        return 2


if __name__ == "__main__":
    sys.exit(run(main))
