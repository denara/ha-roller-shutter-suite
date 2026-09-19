"""SPIKE S2: build the translation files from one fragment per feature.

Home Assistant loads exactly one file per language, and the strings of a step
live under the flow that shows it: ``config.step`` for the house,
``config_subentries.group.step`` for groups and ``config_subentries.window.step``
for windows. A custom integration cannot use ``[%key:...%]`` references, because
only the build of Home Assistant Core resolves them. A feature step that exists
on all three levels would therefore have to be written three times per language.

This script writes them instead: every feature keeps one fragment per language
next to its code, and the script fans it out. A test fails when the generated
files are out of date.

Usage: ``uv run python scripts/build_translations.py``
"""

import copy
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from custom_components.roller_shutter_suite.features import FEATURES  # noqa: E402

INTEGRATION = ROOT / "custom_components" / "roller_shutter_suite"
LANGUAGES = {
    "en": ("strings.json", "translations/en.json"),
    "de": ("translations/de.json",),
}
# (path of the flow in the translation file, does the level inherit?)
LEVELS: tuple[tuple[tuple[str, ...], bool], ...] = (
    (("config",), False),
    (("config_subentries", "group"), True),
    (("config_subentries", "window"), True),
)


def _load(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return result


def _feature_step(
    feature: Any, fragment: dict[str, Any], templates: dict[str, str], inherits: bool
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "title": fragment["step"]["title"],
        "description": fragment["step"]["description"],
        "data": {},
        "data_description": {},
    }
    expert: dict[str, Any] = {"data": {}, "data_description": {}}
    for setting in feature.fields:
        texts = fragment["fields"][setting.key]
        description = texts["description"]
        if inherits and setting.kind == "number":
            hint = (
                templates["inherit_hint"]
                .replace("{inherited}", f"{{{setting.key}_inherited}}")
                .replace("{source}", f"{{{setting.key}_source}}")
            )
            description = f"{description} {hint}"
        target = expert if setting.expert else step
        target["data"][setting.key] = texts["label"]
        target["data_description"][setting.key] = description
        if inherits and setting.requires is not None:
            # Capabilities are known on the window level only, but the keys are
            # harmless elsewhere and keep the levels identical.
            unavailable = fragment["unavailable"][setting.key]
            step["data"][f"{setting.key}_unavailable"] = unavailable["label"]
            step["data_description"][f"{setting.key}_unavailable"] = unavailable[
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


def build(language: str) -> dict[str, Any]:
    """Return the complete translation of one language."""
    result = _load(INTEGRATION / "translations_src" / f"base.{language}.json")
    templates: dict[str, str] = result.pop("_templates")
    fragments = {
        feature.feature_id: _load(
            INTEGRATION / "features" / feature.feature_id / f"strings.{language}.json"
        )
        for feature in FEATURES
    }

    for path, inherits in LEVELS:
        flow = result
        for key in path:
            flow = flow.setdefault(key, {})
        steps = flow.setdefault("step", {})
        errors = flow.setdefault("error", {})
        steps["features"] = {
            "title": templates["features_title"],
            "description": templates[
                "features_description_inheriting"
                if inherits
                else "features_description"
            ],
            "data": {
                feature.switch.key: fragments[feature.feature_id]["switch"]["label"]
                for feature in FEATURES
            },
            "data_description": {
                feature.switch.key: fragments[feature.feature_id]["switch"][
                    "description"
                ]
                for feature in FEATURES
            },
        }
        for feature in FEATURES:
            fragment = fragments[feature.feature_id]
            steps[feature.step_id] = _feature_step(
                feature, fragment, templates, inherits
            )
            errors.update(fragment.get("errors", {}))

    # The lab's pattern (a) shows the fields of the daily routine.
    lab_steps = result["config_subentries"]["pattern_lab"]["step"]
    lab_steps["pattern_a"] = copy.deepcopy(
        result["config_subentries"]["window"]["step"]["feature_daily_routine"]
    )
    return result


def render(language: str) -> str:
    """Return the file content of one language."""
    return json.dumps(build(language), ensure_ascii=False, indent=2) + "\n"


def main() -> None:
    """Write all translation files."""
    for language, targets in LANGUAGES.items():
        content = render(language)
        for target in targets:
            (INTEGRATION / target).write_text(content, encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
