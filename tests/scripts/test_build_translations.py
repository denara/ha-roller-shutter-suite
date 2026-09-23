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

    assert [feature.feature_id for feature in catalog.features] == [
        "daily_routine",
        "movement",
    ]
    assert (build_translations.PACKAGE in sys.modules) is before


def test_every_language_has_the_keys_and_placeholders_of_english() -> None:
    """A key or a placeholder that one language lacks would show up as raw text."""
    codes = list(build_translations.languages())
    english = _flatten(build_translations.build("en"))

    assert codes[0] == "en"
    assert {"en", "de"} <= set(codes)
    for code in codes[1:]:
        other = _flatten(build_translations.build(code))
        assert sorted(english) == sorted(other), code
        for path, text in english.items():
            assert sorted(_PLACEHOLDER.findall(text)) == sorted(
                _PLACEHOLDER.findall(other[path])
            ), (code, path)
            assert text.strip()
            assert other[path].strip(), (code, path)


def test_a_language_is_added_by_adding_its_sources_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A base file and one fragment per feature; nothing in the script changes."""
    sources = build_translations.SOURCES
    (tmp_path / "features").mkdir()
    for path in [*sources.glob("*.json"), *sources.glob("features/*.json")]:
        target = tmp_path / path.relative_to(sources)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    for path in [tmp_path / "base.de.json", *tmp_path.glob("features/*.de.json")]:
        path.with_name(path.name.replace(".de.", ".xx.")).write_text(
            path.read_text(encoding="utf-8"), encoding="utf-8"
        )
    monkeypatch.setattr(build_translations, "SOURCES", tmp_path)

    found = build_translations.languages()

    assert found["xx"] == ("translations/xx.json",)
    assert found["en"] == ("strings.json", "translations/en.json")
    assert build_translations.build("xx") == build_translations.build("de")


def test_a_language_without_a_fragment_of_a_feature_cannot_be_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing fragment is never skipped silently."""
    sources = build_translations.SOURCES
    (tmp_path / "features").mkdir()
    for path in [*sources.glob("*.json"), *sources.glob("features/*.json")]:
        target = tmp_path / path.relative_to(sources)
        target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "base.xx.json").write_text(
        (tmp_path / "base.de.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    monkeypatch.setattr(build_translations, "SOURCES", tmp_path)
    monkeypatch.setattr(build_translations, "ROOT", tmp_path)

    with pytest.raises(build_translations.SourceError, match=r"daily_routine.xx"):
        build_translations.build("xx")


def test_shipped_files_have_the_keys_of_strings_json() -> None:
    """``strings.json`` and every translation carry exactly the same keys."""
    files = [
        _flatten(json.loads((build_translations.INTEGRATION / name).read_text("utf-8")))
        for names in build_translations.languages().values()
        for name in names
    ]

    assert len(files) >= 3  # noqa: PLR2004 - strings.json, English, German
    assert all(sorted(item) == sorted(files[0]) for item in files)
    assert "_templates" not in json.dumps(sorted(files[0]))


def test_sources_live_outside_the_shipped_integration() -> None:
    """Nothing but what Home Assistant needs is shipped."""
    assert build_translations.INTEGRATION not in build_translations.SOURCES.parents
    shipped = {path.name for path in build_translations.INTEGRATION.rglob("*.json")}
    expected = {
        Path(name).name
        for names in build_translations.languages().values()
        for name in names
    }
    assert shipped == {"manifest.json", *expected}


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
