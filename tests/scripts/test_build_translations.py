"""The translation generator: the shipped files are current and the languages agree."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from scripts import build_translations

_PLACEHOLDER = re.compile(r"\{[a-z_]+\}")


def _flatten(node: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Return every string of a translation file by its dotted path."""
    strings: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            strings |= _flatten(value, path)
        else:
            strings[path] = value
    return strings


def test_flatten_finds_nested_strings() -> None:
    """The helper walks nested objects, so a missing leaf cannot hide."""
    nested = {"config": {"step": {"user": {"title": "a", "description": "b"}}}}

    assert _flatten(nested) == {
        "config.step.user.title": "a",
        "config.step.user.description": "b",
    }


def test_generated_files_are_current() -> None:
    """Whoever changes a source runs the generator and commits the result."""
    assert build_translations.outdated() == []
    assert build_translations.main(["--check"]) == 0


def test_loading_the_catalog_leaves_no_stand_in_behind() -> None:
    """The catalog is read without Home Assistant, and the import leaves no trace."""
    import sys  # noqa: PLC0415

    before = build_translations.PACKAGE in sys.modules

    catalog = build_translations.load_catalog()

    assert [feature.feature_id for feature in catalog.features] == ["daily_routine"]
    assert (build_translations.PACKAGE in sys.modules) is before


@pytest.mark.parametrize(
    "language",
    [
        language
        for language in build_translations.languages()
        if language != build_translations.SOURCE_LANGUAGE
    ],
)
def test_every_language_has_the_keys_and_placeholders_of_english(
    language: str,
) -> None:
    """A key or a placeholder that one language lacks would show up as raw text."""
    english = _flatten(build_translations.build(build_translations.SOURCE_LANGUAGE))
    other = _flatten(build_translations.build(language))

    assert sorted(english) == sorted(other)
    for path, text in english.items():
        assert sorted(_PLACEHOLDER.findall(text)) == sorted(
            _PLACEHOLDER.findall(other[path])
        ), path
        assert text.strip()
        assert other[path].strip()


def test_the_languages_are_the_base_files_that_exist() -> None:
    """English and German today; neither the list nor the parity pins that."""
    found = build_translations.languages()

    assert next(iter(found)) == "en"
    assert found["en"] == ("strings.json", "translations/en.json")
    assert found["de"] == ("translations/de.json",)


def test_a_language_is_added_by_adding_its_fragments(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A third language needs its base file and its feature fragments, nothing else."""
    sources = tmp_path / "sources"
    (sources / "features").mkdir(parents=True)
    for path in build_translations.SOURCES.rglob("*.json"):
        relative = path.relative_to(build_translations.SOURCES)
        (sources / relative).write_bytes(path.read_bytes())
        if relative.name.endswith(".en.json"):
            added = relative.name.replace(".en.json", ".xx.json")
            (sources / relative.parent / added).write_bytes(path.read_bytes())
    integration = tmp_path / "integration"
    (integration / "translations").mkdir(parents=True)
    catalog = build_translations.load_catalog()
    monkeypatch.setattr(build_translations, "SOURCES", sources)
    monkeypatch.setattr(build_translations, "INTEGRATION", integration)
    monkeypatch.setattr(build_translations, "load_catalog", lambda: catalog)

    assert build_translations.languages()["xx"] == ("translations/xx.json",)
    assert build_translations.main([]) == 0
    assert (integration / "translations" / "xx.json").read_text("utf-8") == (
        integration / "translations" / "en.json"
    ).read_text("utf-8")
    assert build_translations.main(["--check"]) == 0


def test_reason_codes_become_the_states_of_the_reason_sensor() -> None:
    """One list of words per language, written where the entities show a reason."""
    for language in build_translations.languages():
        built = build_translations.build(language)
        sensors = built["entity"]["sensor"]
        states = sensors["active_reason"]["state"]
        assert states
        assert sensors["next_action"]["state_attributes"]["reason"]["state"] == states


def test_shipped_files_have_the_keys_of_strings_json() -> None:
    """``strings.json`` and both translations carry exactly the same keys."""
    files = [
        _flatten(json.loads((build_translations.INTEGRATION / name).read_text("utf-8")))
        for names in build_translations.languages().values()
        for name in names
    ]

    assert all(sorted(item) == sorted(files[0]) for item in files)
    assert "_templates" not in json.dumps(sorted(files[0]))


def test_sources_live_outside_the_shipped_integration() -> None:
    """Nothing but what Home Assistant needs is shipped."""
    assert build_translations.INTEGRATION not in build_translations.SOURCES.parents
    shipped = {path.name for path in build_translations.INTEGRATION.rglob("*.json")}
    assert shipped == {"manifest.json", "strings.json", "icons.json"} | {
        f"{language}.json" for language in build_translations.languages()
    }


def test_outdated_file_fails_the_check(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``--check`` ends with status 1 and names the file; writing repairs it."""
    catalog = build_translations.load_catalog()
    (tmp_path / "translations").mkdir()
    monkeypatch.setattr(build_translations, "INTEGRATION", tmp_path)
    monkeypatch.setattr(build_translations, "load_catalog", lambda: catalog)
    assert build_translations.main(["--check"]) == 1
    assert "out of date: strings.json" in capsys.readouterr().out

    assert build_translations.main([]) == 0
    assert build_translations.main(["--check"]) == 0
    assert (tmp_path / "strings.json").read_bytes().count(b"\r") == 0


@pytest.mark.parametrize(
    "content",
    [None, "{", "[]", '{"config": {}}'],
    ids=["missing", "broken", "list", "keys"],
)
def test_source_that_cannot_be_used_is_cannot_check(
    content: str | None,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A guard that cannot check fails; it never passes."""
    monkeypatch.setattr(build_translations, "SOURCES", tmp_path)
    monkeypatch.setattr(build_translations, "ROOT", tmp_path)
    if content is not None:
        (tmp_path / "base.en.json").write_text(content, encoding="utf-8")

    assert build_translations.main(["--check"]) == 2  # noqa: PLR2004 - the status
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_sources_that_cannot_be_listed_are_cannot_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The languages are found by listing the folder; a folder that fails is a failure."""
    monkeypatch.setattr(build_translations, "SOURCES", tmp_path / "missing")

    assert build_translations.main(["--check"]) == 2  # noqa: PLR2004 - the status
    output = capsys.readouterr().out
    assert "CANNOT CHECK" in output
    assert "cannot be listed" in output
