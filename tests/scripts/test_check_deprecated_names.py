"""The guard against deprecated Home Assistant names finds references, not words."""

import re
from pathlib import Path

import pytest

from scripts.check_deprecated_names import (
    EXIT_CANNOT_CHECK,
    LIST_FILE,
    CannotCheckError,
    Deprecated,
    ListError,
    check_source,
    check_tree,
    load_list,
    main,
    parse_list,
)

SOURCE = "example/module.py, version 1"
ENTRIES = [
    Deprecated("identifier", "old_helper", "logs", "Going away.", "new_helper", SOURCE),
    Deprecated("module", "oldlib", "silent", "It was replaced.", "newlib", SOURCE),
    Deprecated(
        "attribute",
        "entries",
        "silent",
        "It is a shim.",
        "entry_id",
        SOURCE,
        allowed_receivers=("hass", "_hass"),
    ),
    Deprecated("mapping", "things", "logs", "Not a mapping.", "iterate it", SOURCE),
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
        "device = registry.async_get(device_id)\nfound = device.entries",
        "def f(device: Device) -> None:\n    return device.entries",
        "registry.async_get(device_id).entries",
        "self.device.entries",
        "for entry in device.entries:\n    pass",
        "registry.things[device_id]",
        "registry.things.get(device_id)",
        "list(self._registry.things.values())",
    ],
)
def test_reference_is_found(source: str) -> None:
    """Imports, attributes, keyword arguments and mapping use are seen."""
    findings = check_source(source, "example.py", ENTRIES)

    assert len(findings) == 1
    assert "deprecated" in findings[0].message
    assert "Use instead:" in findings[0].message
    assert SOURCE in findings[0].message


@pytest.mark.parametrize(
    "source",
    [
        "# old_helper is gone\nTEXT = 'old_helper and import oldlib'",
        "from homeassistant.helpers.example import new_helper",
        "import oldlib_successor",
        "hass.entries.async_entries('example')",
        "self.hass.entries",
        "entry.hass.entries",
        "self._hass.entries",
        "for thing in registry.things:\n    pass",
        "count = len(registry.things)",
        "things = {}\nthings['a']",
    ],
)
def test_harmless_source_passes(source: str) -> None:
    """Comments, strings, similar names and allowed receivers do not count."""
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

    assert {
        "show_advanced_options",
        "get_astral_location",
        "get_location_astral_event_next",
        "voluptuous",
        "config_entries",
    } <= {entry.name for entry in entries}


def test_silent_device_entry_shim_is_found_in_its_usual_form() -> None:
    """The real list catches the shim without any annotation, but not ``hass``."""
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))
    source = (
        "device = registry.async_get(device_id)\n"
        "owners = device.config_entries\n"
        "loaded = hass.config_entries.async_entries(DOMAIN)\n"
        "other = self.hass.config_entries.async_get_entry(entry_id)\n"
    )

    findings = check_source(source, "example.py", entries)

    assert [finding.line for finding in findings] == [2]
    assert "logs nothing" in findings[0].message
    assert "config_entry_id" in findings[0].message


def _entry(**changes: object) -> str:
    fields: dict[str, object] = {
        "kind": "identifier",
        "name": "x",
        "behavior": "logs",
        "reason": "r",
        "replacement": "n",
        "source": "s",
        **changes,
    }
    lines = [
        f"{key} = {value!r}" if isinstance(value, list) else f'{key} = "{value}"'
        for key, value in fields.items()
        if value is not None
    ]
    return "[[deprecated]]\n" + "\n".join(lines)


def test_complete_entry_is_accepted() -> None:
    """The helper below produces a valid entry, so each refusal has one cause."""
    assert len(parse_list(_entry())) == 1
    assert len(parse_list(_entry(kind="attribute", allowed_receivers=["hass"]))) == 1
    assert len(parse_list(_entry(kind="mapping"))) == 1


@pytest.mark.parametrize(
    "text",
    [
        '[[other]]\nname = "x"',
        _entry(reason=None),
        _entry(replacement=None),
        _entry(source=None),
        _entry(behavior=None),
        _entry(source=" "),
        _entry(kind="word"),
        _entry(behavior="loud"),
        _entry(owner="Device"),
        _entry(kind="module", allowed_receivers=["hass"]),
        _entry(kind="attribute", allowed_receivers=["self.hass"]),
    ],
)
def test_malformed_list_is_refused(text: str) -> None:
    """An entry without reason, replacement or source, or with unknown values fails."""
    with pytest.raises(ListError):
        parse_list(text)


def test_this_repository_passes() -> None:
    """Neither the integration nor its tests reference a listed name."""
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))

    assert check_tree(Path(__file__).parents[2], entries) == []


def test_missing_scanned_folder_cannot_be_checked(tmp_path: Path) -> None:
    """Zero files in a scanned folder is a failure, not zero findings."""
    (tmp_path / "custom_components").mkdir()
    (tmp_path / "custom_components" / "module.py").write_text("X = 1\n", "utf-8")

    with pytest.raises(CannotCheckError, match="no Python file found under tests/"):
        check_tree(tmp_path, ENTRIES)
    assert main(tmp_path) == EXIT_CANNOT_CHECK


@pytest.mark.parametrize("content", [None, "", "[[deprecated]]\nkind = 'x'\n", "= ="])
def test_list_that_cannot_be_used_cannot_check(
    tmp_path: Path, content: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    """A missing, empty, malformed or unparsable list checks nothing."""
    list_file = tmp_path / "names.toml"
    if content is not None:
        list_file.write_text(content, encoding="utf-8")

    with pytest.raises(CannotCheckError):
        load_list(list_file)
    assert main(list_file=list_file) == EXIT_CANNOT_CHECK
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_file_that_cannot_be_parsed_cannot_be_checked() -> None:
    """A syntax error hides every name of the file."""
    with pytest.raises(CannotCheckError, match="cannot be parsed"):
        check_source("def broken(:\n", "tests/example.py", ENTRIES)


def test_pass_says_how_much_was_checked(capsys: pytest.CaptureFixture[str]) -> None:
    """The last line names the number of files and of names."""
    assert main() == 0
    assert re.search(
        r"ok \(checked [1-9]\d* file\(s\) against [1-9]\d* names",
        capsys.readouterr().out,
    )
