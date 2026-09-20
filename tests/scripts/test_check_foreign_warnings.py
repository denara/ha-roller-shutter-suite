"""The list of foreign warnings accepts only complete, truly foreign entries."""

from pathlib import Path

import pytest

from scripts.check_foreign_warnings import (
    EXIT_CANNOT_CHECK,
    CannotCheckError,
    EntryError,
    load_entries,
    main,
    own_module_names,
    parse_entries,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
OWN_MODULES = own_module_names(REPOSITORY_ROOT)
VALID = {
    "module": r"^some_package\.submodule",
    "category": "DeprecationWarning",
    "reason": "The package warns about its own internals.",
    "upstream": "https://github.com/example/some-package/issues/1",
}


def _entry(**changes: str | None) -> str:
    fields = {**VALID, **changes}
    lines = [f"{key} = '{value}'" for key, value in fields.items() if value is not None]
    return "[[warning]]\n" + "\n".join(lines) + "\n"


def test_valid_entry_becomes_an_ignore_filter() -> None:
    """A complete entry is turned into the filter pytest understands."""
    (entry,) = parse_entries(_entry(), OWN_MODULES)

    assert entry.as_filter() == r"ignore::DeprecationWarning:^some_package\.submodule"


def test_empty_file_and_comments_are_valid() -> None:
    """The list may be empty."""
    assert parse_entries("# nothing yet\n", OWN_MODULES) == []


@pytest.mark.parametrize("field", ["module", "category", "reason", "upstream"])
def test_missing_or_empty_field_is_refused(field: str) -> None:
    """All four fields are required and must say something."""
    with pytest.raises(EntryError, match="entry 1"):
        parse_entries(_entry(**{field: None}), OWN_MODULES)
    with pytest.raises(EntryError, match="entry 1"):
        parse_entries(_entry(**{field: " "}), OWN_MODULES)


@pytest.mark.parametrize(
    "pattern",
    [
        "custom_components",
        r"custom_components\.roller_shutter_suite",
        r".*roller_shutter_suite",
        r"custom_components\.roller_shutter_suite\.config_flow$",
        r"homeassistant\.helpers\.frame",
        r"homeassistant\.helpers\.(frame|deprecation)",
        r"homeassistant\.helpers\.deprecation$",
        "homeassistant",
        r"tests\.ha",
        "",
        ".*",
        r"\w+",
        "(unbalanced",
    ],
)
def test_pattern_that_covers_own_code_is_refused(pattern: str) -> None:
    """The integration, its tests and the reporting helpers cannot be exempted."""
    with pytest.raises(EntryError):
        parse_entries(_entry(module=pattern), OWN_MODULES)


@pytest.mark.parametrize(
    "upstream",
    [
        "http://github.com/example/issues/1",
        "github.com/example",
        "https://",
        "see chat",
    ],
)
def test_upstream_must_be_an_https_link(upstream: str) -> None:
    """A reviewer must be able to follow the link."""
    with pytest.raises(EntryError, match="https"):
        parse_entries(_entry(upstream=upstream), OWN_MODULES)


@pytest.mark.parametrize(
    "text",
    [
        _entry(extra="field"),
        _entry(category="not a class"),
        "[warning]\nmodule = 'x'\n",
        "[[ignore]]\nmodule = 'x'\n",
        "not toml at all [",
    ],
)
def test_malformed_file_is_refused(text: str) -> None:
    """Unknown tables, unknown fields and broken syntax fail."""
    with pytest.raises(EntryError):
        parse_entries(text, OWN_MODULES)


@pytest.mark.parametrize("category", ["Warning", "builtins.Warning", "Exception"])
def test_category_that_covers_every_warning_is_refused(category: str) -> None:
    """``Warning`` would exempt whatever the module ever warns about."""
    with pytest.raises(EntryError, match="covers every warning"):
        parse_entries(_entry(category=category), OWN_MODULES)


@pytest.mark.parametrize("pattern", [r"^(?:some|other)_package", "some_package:sub"])
def test_module_pattern_with_a_colon_is_refused(pattern: str) -> None:
    """Pytest splits a filter at colons, so the pattern would be cut in two."""
    with pytest.raises(EntryError, match="colon"):
        parse_entries(_entry(module=pattern), OWN_MODULES)


def test_group_without_a_colon_is_accepted() -> None:
    """The message names the alternative, and the alternative works."""
    (entry,) = parse_entries(_entry(module=r"^(some|other)_package\."), OWN_MODULES)

    assert ":" not in entry.module


def test_own_modules_cover_the_integration_and_the_tests() -> None:
    """The protected names are derived from the files of the repository."""
    assert "custom_components.roller_shutter_suite.config_flow" in OWN_MODULES
    assert "custom_components.roller_shutter_suite.core" in OWN_MODULES
    assert "tests.ha.conftest" in OWN_MODULES


def test_list_of_this_repository_is_valid() -> None:
    """The list in the repository passes its own guard."""
    assert isinstance(load_entries(REPOSITORY_ROOT), list)


def _tree(root: Path, *, with_list: bool) -> None:
    for folder in ("custom_components", "tests", "scripts"):
        (root / folder).mkdir()
        (root / folder / "module.py").write_text("", encoding="utf-8")
    if with_list:
        (root / "tests" / "foreign_warnings.toml").write_text("", encoding="utf-8")


def test_missing_list_cannot_be_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """An empty list is a file without entries; a missing file is a failure."""
    _tree(tmp_path, with_list=False)

    with pytest.raises(CannotCheckError, match="cannot be read"):
        load_entries(tmp_path)
    assert main(tmp_path) == EXIT_CANNOT_CHECK
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_repository_without_own_modules_cannot_be_checked(tmp_path: Path) -> None:
    """Comparing a pattern with no module at all would accept every pattern."""
    _tree(tmp_path, with_list=True)
    (tmp_path / "scripts" / "module.py").unlink()

    with pytest.raises(CannotCheckError, match="no Python file found under scripts/"):
        own_module_names(tmp_path)
    assert main(tmp_path) == EXIT_CANNOT_CHECK


def test_pass_says_how_much_was_compared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero entries is the normal state, so the pass names both numbers."""
    _tree(tmp_path, with_list=True)

    assert main(tmp_path) == 0
    assert "0 entries, each compared with 7 module names" in capsys.readouterr().out
