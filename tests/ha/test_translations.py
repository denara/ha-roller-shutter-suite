"""English, German and ``strings.json`` carry exactly the same translation keys."""

import json
from pathlib import Path
from typing import Any

import pytest

INTEGRATION_DIR = (
    Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
)
REFERENCE = "strings.json"
TRANSLATIONS = ["translations/en.json", "translations/de.json"]


def _flatten_keys(node: dict[str, Any], prefix: str = "") -> set[str]:
    """Return the dotted paths of all strings in a translation file."""
    keys: set[str] = set()
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            keys |= _flatten_keys(value, path)
        else:
            keys.add(path)
    return keys


def _load_keys(relative_path: str) -> set[str]:
    content = json.loads((INTEGRATION_DIR / relative_path).read_text(encoding="utf-8"))
    return _flatten_keys(content)


@pytest.mark.parametrize("translation", TRANSLATIONS)
def test_translation_has_the_keys_of_strings_json(translation: str) -> None:
    """No key is missing and no key is left over in a translation."""
    reference_keys = _load_keys(REFERENCE)
    translation_keys = _load_keys(translation)

    missing = sorted(reference_keys - translation_keys)
    unexpected = sorted(translation_keys - reference_keys)

    assert not missing, f"{translation} lacks keys of {REFERENCE}: {missing}"
    assert not unexpected, (
        f"{translation} has keys unknown to {REFERENCE}: {unexpected}"
    )


def test_flatten_keys_finds_nested_strings() -> None:
    """The helper walks nested objects, so a missing leaf cannot hide."""
    nested = {"config": {"step": {"user": {"title": "a", "description": "b"}}}}

    assert _flatten_keys(nested) == {
        "config.step.user.title",
        "config.step.user.description",
    }
