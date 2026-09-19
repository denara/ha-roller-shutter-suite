"""The guard against deprecated Home Assistant names finds references, not words."""

from pathlib import Path

import pytest

from scripts.check_deprecated_names import (
    LIST_FILE,
    Deprecated,
    ListError,
    check_source,
    check_tree,
    parse_list,
)

ENTRIES = [
    Deprecated("identifier", "old_helper", "It is going away.", "new_helper"),
    Deprecated("module", "oldlib", "It was replaced.", "newlib"),
    Deprecated("attribute", "entries", "It is a shim.", "entry_id", owner="Device"),
]


@pytest.mark.parametrize(
    "source",
    [
        "from homeassistant.helpers.example import old_helper",
        "from homeassistant.helpers import example\nexample.old_helper()",
        "if self.old_helper:\n    pass",
        "call(old_helper=True)",
        "import oldlib",
        "import oldlib.validators as v",
        "from oldlib import Schema",
        "from oldlib.validators import Any",
        "def f(device: Device) -> None:\n    device.entries",
        "def f(device: 'registry.Device | None') -> None:\n    device.entries",
        "found: dr.Device = lookup()\nfound.entries",
        "Device.entries",
    ],
)
def test_reference_is_found(source: str) -> None:
    """Imports, attributes, keyword arguments and annotated owners are seen."""
    findings = check_source(source, "example.py", ENTRIES)

    assert len(findings) == 1
    assert "deprecated" in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "# old_helper is gone\nTEXT = 'old_helper and import oldlib'",
        "from homeassistant.helpers.example import new_helper",
        "import oldlib_successor",
        "hass.entries",
        "def f(other: Other) -> None:\n    other.entries",
    ],
)
def test_harmless_source_passes(source: str) -> None:
    """Comments, strings, similar names and other owners do not count."""
    assert check_source(source, "example.py", ENTRIES) == []


def test_tree_scans_integration_and_tests(tmp_path: Path) -> None:
    """Both scanned folders are read, other folders are not."""
    for folder in ("custom_components/example", "tests/ha", "elsewhere"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "module.py").write_text("import oldlib\n", "utf-8")

    findings = check_tree(tmp_path, ENTRIES)

    assert [finding.path for finding in findings] == [
        "custom_components/example/module.py",
        "tests/ha/module.py",
    ]


def test_list_of_this_repository_is_valid_and_names_the_brief_entries() -> None:
    """The list starts with the names the project brief calls deprecated."""
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))

    names = {(entry.owner, entry.name) for entry in entries}
    assert {
        (None, "show_advanced_options"),
        (None, "get_astral_location"),
        (None, "get_location_astral_event_next"),
        (None, "voluptuous"),
        ("DeviceEntry", "config_entries"),
    } <= names


@pytest.mark.parametrize(
    "text",
    [
        '[[other]]\nname = "x"',
        '[[deprecated]]\nkind = "identifier"\nname = "x"',
        '[[deprecated]]\nkind = "word"\nname = "x"\nreason = "r"\nreplacement = "n"',
        '[[deprecated]]\nkind = "attribute"\nname = "x"\nreason = "r"\n'
        'replacement = "n"',
        '[[deprecated]]\nkind = "module"\nowner = "C"\nname = "x"\nreason = "r"\n'
        'replacement = "n"',
        '[[deprecated]]\nkind = "module"\nname = ""\nreason = "r"\nreplacement = "n"',
    ],
)
def test_malformed_list_is_refused(text: str) -> None:
    """An entry without reason, with an unknown kind or a misplaced owner fails."""
    with pytest.raises(ListError):
        parse_list(text)


def test_this_repository_passes() -> None:
    """Neither the integration nor its tests reference a listed name."""
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))

    assert check_tree(Path(__file__).parents[2], entries) == []
