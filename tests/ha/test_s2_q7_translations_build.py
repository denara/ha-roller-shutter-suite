"""SPIKE S2, question 7: translations come from one fragment per feature."""

import importlib.util
import re
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).parents[2]
INTEGRATION = ROOT / "custom_components" / "roller_shutter_suite"


def _builder() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "build_translations", ROOT / "scripts" / "build_translations.py"
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    ("language", "target"),
    [
        ("en", "strings.json"),
        ("en", "translations/en.json"),
        ("de", "translations/de.json"),
    ],
)
def test_generated_files_are_up_to_date(language: str, target: str) -> None:
    """The committed file equals what the builder produces from the fragments."""
    expected = _builder().render(language)

    assert (INTEGRATION / target).read_text(encoding="utf-8") == expected


def test_fragment_is_fanned_out_to_all_three_levels() -> None:
    """One label in the fragment, three places in the result."""
    built = _builder().build("en")

    house = built["config"]["step"]["feature_daily_routine"]
    group = built["config_subentries"]["group"]["step"]["feature_daily_routine"]
    window = built["config_subentries"]["window"]["step"]["feature_daily_routine"]
    assert (
        house["data"]["morning_position"]
        == group["data"]["morning_position"]
        == window["data"]["morning_position"]
        == "Morning position"
    )
    # Only the inheriting levels explain inheritance, with per-field placeholders.
    assert (
        "{morning_position_inherited}"
        not in house["data_description"]["morning_position"]
    )
    assert (
        "{morning_position_inherited}" in window["data_description"]["morning_position"]
    )
    assert window["sections"]["expert"]["data"] == {"random_offset": "Random offset"}


def test_placeholders_are_the_same_in_both_languages() -> None:
    """A placeholder missing in one language would show up as raw text."""
    builder = _builder()

    def placeholders(node: object, path: str = "") -> dict[str, set[str]]:
        if isinstance(node, dict):
            found: dict[str, set[str]] = {}
            for key, value in node.items():
                found |= placeholders(value, f"{path}.{key}")
            return found
        return {path: set(re.findall(r"\{(\w+)\}", str(node)))}

    assert placeholders(builder.build("en")) == placeholders(builder.build("de"))
