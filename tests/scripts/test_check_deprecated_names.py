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
# Silent entries are matched broadly, entries that log narrowly.
ENTRIES = [
    Deprecated("identifier", "old_shim", "silent", "It is a shim.", "new_shim", SOURCE),
    Deprecated(
        "identifier",
        "old_helper",
        "logs",
        "Going away.",
        "new_helper",
        SOURCE,
        receivers=("example",),
    ),
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
    Deprecated(
        "attribute",
        "old_lookup",
        "logs",
        "It reports.",
        "new_lookup",
        SOURCE,
        receivers=("registry",),
    ),
    Deprecated(
        "mapping",
        "things",
        "logs",
        "Not a mapping.",
        "iterate it",
        SOURCE,
        receivers=("registry", "_registry"),
    ),
    Deprecated(
        "keyword",
        "merge_things",
        "logs",
        "It reports.",
        "new_things",
        SOURCE,
        receivers=("registry",),
        method="update",
    ),
]


@pytest.mark.parametrize(
    "source",
    [
        # A silent identifier: wherever it appears.
        "from homeassistant.helpers.example import old_shim",
        "from homeassistant.helpers import example\nexample.old_shim()",
        "if self.old_shim:\n    pass",
        "call(old_shim=True)",
        "def old_shim() -> None:\n    pass",
        # An identifier that logs: imported, or read from its receivers.
        "from homeassistant.helpers.example import old_helper",
        "from homeassistant.helpers.example import old_helper as helper",
        "import homeassistant.helpers.example.old_helper",
        "from homeassistant.helpers import example\nexample.old_helper()",
        "helpers.example.old_helper(hass)",
        # A module: every way of importing it.
        "import oldlib",
        "import oldlib.validators as v",
        "from oldlib import Schema",
        "from oldlib.validators import Any",
        # A silent attribute: on every object but the allowed ones.
        "device = registry.async_get(device_id)\nfound = device.entries",
        "def f(device: Device) -> None:\n    return device.entries",
        "registry.async_get(device_id).entries",
        "self.device.entries",
        "for entry in device.entries:\n    pass",
        # An attribute that logs: on its receivers and on the result of a call.
        "registry.old_lookup(identifiers={key})",
        "self.registry.old_lookup(identifiers={key})",
        "async_get(hass).old_lookup(identifiers={key})",
        # A mapping that logs: used as a mapping on its receivers.
        "registry.things[device_id]",
        "registry.things.get(device_id)",
        "list(self._registry.things.values())",
        "async_get(hass).things[device_id]",
        # A keyword that logs: passed to a call of its method on its receivers.
        "registry.update(device_id, merge_things={x})",
        "self.registry.update(device_id, name='x', merge_things={x})",
        "async_get(hass).update(device_id, merge_things={x})",
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
        # Own names that only share a name with something that logs: the log
        # guard is the net for these, so they are not reported here.
        "def old_helper(self) -> None:\n    pass",
        "if self.old_helper:\n    pass",
        "call(old_helper=True)",
        "old_helper()",
        "def old_lookup(self) -> None:\n    pass",
        "self.old_lookup(key)",
        "device.old_lookup",
        "self.things[device_id]",
        "entry.runtime_data.things.values()",
        "things[device_id]",
        # The same keyword on another call, method or receiver.
        "update(device_id, merge_things={x})",
        "self.update(device_id, merge_things={x})",
        "registry.other(device_id, merge_things={x})",
        "registry.update(device_id, new_things={x})",
        "merge_things = {x}\nregistry.update(device_id, *merge_things)",
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


def test_every_entry_that_logs_is_narrow_and_every_silent_one_broad() -> None:
    """The rule of the contributing page holds for the whole list.

    Narrow entries name where the name is read; broad attribute entries name
    where it is fine. The classification of every entry is verified against
    the Core source named in its ``source`` field.
    """
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))

    for entry in entries:
        assert entry.narrow == (entry.behavior == "logs"), entry.name
        if entry.narrow and entry.kind != "module":
            assert entry.receivers, entry.name
            assert not entry.allowed_receivers, entry.name
        else:
            assert not entry.receivers, entry.name
    assert {e.name for e in entries if e.narrow} == {
        "show_advanced_options",
        "get_astral_location",
        "get_location_astral_event_next",
        "async_get_device",
        "devices",
        "deleted_devices",
        "async_is_composite_device_id",
        "suggested_area",
        *UPDATE_KEYWORDS,
    }
    assert {e.name for e in entries if not e.narrow} == {
        "voluptuous",
        "config_entries",
        "config_entries_subentries",
        "primary_config_entry",
    }


# The keyword arguments of async_update_device that Core reports.
UPDATE_KEYWORDS = (
    "add_config_entry_id",
    "add_config_subentry_id",
    "remove_config_entry_id",
    "remove_config_subentry_id",
    "merge_connections",
    "merge_identifiers",
)
REAL_USE = {
    **{
        keyword: [
            f"device_registry.async_update_device(device.id, {keyword}=value)",
            f"registry.async_update_device(device.id, name='x', {keyword}=value)",
            f"dr.async_get(hass).async_update_device(device.id, {keyword}=value)",
        ]
        for keyword in UPDATE_KEYWORDS
    },
    "show_advanced_options": [
        "if self.show_advanced_options:\n    pass",
    ],
    "get_astral_location": [
        "from homeassistant.helpers.sun import get_astral_location",
        "from homeassistant.helpers import sun\nsun.get_astral_location(hass)",
    ],
    "get_location_astral_event_next": [
        "from homeassistant.helpers.sun import get_location_astral_event_next",
        "sun.get_location_astral_event_next(location, elevation, event)",
    ],
    "async_get_device": [
        "registry = dr.async_get(hass)\nregistry.async_get_device(identifiers={key})",
        "dr.async_get(hass).async_get_device(identifiers={key})",
        "self._device_registry.async_get_device(connections={key})",
    ],
    "devices": [
        "device_registry.devices[device_id]",
        "dr.async_get(hass).devices.get(device_id)",
        "list(self._registry.devices.values())",
    ],
    "deleted_devices": [
        "registry.deleted_devices",
        "dr.async_get(hass).deleted_devices",
    ],
    "async_is_composite_device_id": [
        "registry.async_is_composite_device_id(device_id)",
    ],
    "suggested_area": [
        "device = registry.async_get(device_id)\narea = device.suggested_area",
        "registry.async_get(device_id).suggested_area",
        "self._device.suggested_area",
    ],
}
# Own names that share the name with an entry that logs; not reported here,
# because Home Assistant logs the real thing and the log guard sees it.
OWN_USE = [
    "self.devices[window_id]",
    "entry.runtime_data.devices.values()",
    "def async_get_device(self, window_id: str) -> Device:\n    pass",
    "self.async_get_device(window_id)",
    "runtime.async_get_device(window_id)",
    "self.data.deleted_devices",
    "form.suggested_area",
    "DeviceInfo(suggested_area=area)",
    "def get_astral_location(self) -> Location:\n    pass",
    "self.get_astral_location()",
    # The same keyword names on an own call or on another method.
    "self.async_update_device(window_id, merge_identifiers=keys)",
    "runtime.update(window_id, add_config_entry_id=entry.entry_id)",
    "device_registry.async_get_or_create(config_entry_id=entry.entry_id)",
    # And the real thing where it is fine.
    "for device in registry.devices:\n    pass",
    "len(registry.devices)",
    "device_registry.async_update_device(device.id, new_config_entry_id=entry_id)",
    "device_registry.async_update_device(device.id, new_identifiers=keys)",
]


@pytest.mark.parametrize(
    ("name", "source"),
    [(name, source) for name, sources in REAL_USE.items() for source in sources],
)
def test_entry_that_logs_is_found_where_home_assistant_exposes_it(
    name: str, source: str
) -> None:
    """The narrow match still sees the usual spelling of every real use."""
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))

    findings = check_source(source, "example.py", entries)

    assert len(findings) == 1, findings
    assert f"'{name}'" in findings[0].message or f".{name}'" in findings[0].message
    assert "logs a report" in findings[0].message
    if name in UPDATE_KEYWORDS:
        assert "keyword argument" in findings[0].message
        assert "'.async_update_device()'" in findings[0].message


@pytest.mark.parametrize("source", OWN_USE)
def test_own_name_that_shares_a_logging_name_passes(source: str) -> None:
    """A plausible own name is not renamed to get around the guard."""
    entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))

    assert check_source(source, "example.py", entries) == []


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


@pytest.mark.parametrize(
    "text",
    [
        _entry(),
        _entry(behavior="silent"),
        _entry(receivers=["sun"]),
        _entry(kind="attribute", receivers=["registry"]),
        _entry(kind="mapping", receivers=["registry"]),
        _entry(kind="attribute", behavior="silent"),
        _entry(kind="attribute", behavior="silent", allowed_receivers=["hass"]),
        _entry(kind="mapping", behavior="silent", allowed_receivers=[]),
        _entry(kind="module", behavior="silent"),
        _entry(kind="keyword", method="update", receivers=["registry"]),
        _entry(kind="keyword", method="update", behavior="silent"),
    ],
)
def test_complete_entry_is_accepted(text: str) -> None:
    """The helper below produces a valid entry, so each refusal has one cause."""
    assert len(parse_list(text)) == 1


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
        _entry(kind="module", behavior="silent", allowed_receivers=["hass"]),
        _entry(kind="module", receivers=["hass"]),
        _entry(kind="attribute", behavior="silent", allowed_receivers=["self.hass"]),
        _entry(kind="attribute", receivers=["self.registry"]),
        # An entry that logs is matched narrowly and names its receivers.
        _entry(kind="attribute"),
        _entry(kind="mapping"),
        _entry(kind="attribute", receivers=[]),
        _entry(kind="attribute", allowed_receivers=["hass"]),
        # A silent entry is matched broadly and has no receivers to name.
        _entry(kind="attribute", behavior="silent", receivers=["registry"]),
        _entry(behavior="silent", receivers=["sun"]),
        # A keyword names its method, and nothing else does.
        _entry(kind="keyword", receivers=["registry"]),
        _entry(kind="keyword", method="", receivers=["registry"]),
        _entry(kind="keyword", method="self.update", receivers=["registry"]),
        _entry(kind="attribute", method="update", receivers=["registry"]),
        _entry(method="update"),
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
