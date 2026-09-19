"""The instance data guard recognizes the shapes of real installations.

This file is tracked and therefore scanned by the guard itself. Every example
that must be found is put together from pieces at runtime, so that the file
contains no line that looks like instance data. All values are made up.
"""

from pathlib import Path

import pytest

from scripts.check_instance_data import (
    PATTERNS,
    GitUnavailableError,
    check_text,
    check_tree,
    tracked_files,
)

AT = "@"
SUSPICIOUS = {
    "private IPv4 address": [
        ".".join(["192", "168", "0", "10"]),
        "host: " + ".".join(["10", "0", "0", "5"]),
        ".".join(["172", "16", "4", "1"]) + ":8123",
    ],
    "hardware (MAC) address": [":".join(["00", "1a", "2b", "3c", "4d", "5e"])],
    "coordinate with five or more decimals": [
        "latitude: 12." + "345678",
        "-0." + "123456",
    ],
    "entity ID with a serial-number-like part": [
        "cover." + "shutter_" + "0012345678",
        "sensor." + "device_" + "00a1b2c3d4" + "_temperature",
        "binary_sensor." + "contact_" + "123456",
    ],
    "path with a Windows drive letter": ["C" + ":\\" + "projects", "d" + ":/" + "work"],
    "path inside a user's home directory": [
        "/home" + "/someone/checkout",
        "/Users" + "/someone",
        "\\Users" + "\\someone",
    ],
    "path of a mounted Windows drive": ["/mnt" + "/c/" + "checkout"],
    "e-mail address": [
        "someone" + AT + "provider.test",
        "a.b" + AT + "mail.provider.test",
    ],
}
HARMLESS = [
    "cover.example_window",
    "sensor.living_room_temperature",
    "binary_sensor.example_door_2",
    "homeassistant==2026.9.2 and pytest-homeassistant-custom-component==0.13.365",
    "version 10.1.0 of an action, pinned as 3d3c42e5aac5ba805825da76410c181273ba90b1",
    "an elevation of 12.5 degrees and an azimuth of 180.25",
    "https://github.com/example/example and http://localhost:8123",
    "the address 127.0.0.1 and the network 192.0.2.7 from the documentation range",
    "codeowners: @example",
    "someone" + AT + "example.com",
    "12345+someone" + AT + "users.noreply.github.com",
    "Use `$HOME/.venvs/<name>` and '<path to the repository>'",
    "10:30:00 is a time, not an address",
]


def test_every_pattern_has_an_example() -> None:
    """No pattern of the guard is left without a positive example here."""
    assert {kind for kind, _ in PATTERNS} == set(SUSPICIOUS)


@pytest.mark.parametrize(
    ("kind", "text"),
    [(kind, text) for kind, texts in SUSPICIOUS.items() for text in texts],
)
def test_suspicious_text_is_found(kind: str, text: str) -> None:
    """Each shape is found, with the right kind and the right line."""
    findings = check_text(f"harmless first line\nvalue = '{text}'\n", "example.yaml")

    assert [(finding.line, finding.kind) for finding in findings] == [(2, kind)]


@pytest.mark.parametrize("text", HARMLESS)
def test_harmless_text_passes(text: str) -> None:
    """Neutral examples, versions, hashes and documentation addresses pass."""
    assert check_text(text, "example.md") == []


def test_finding_does_not_repeat_the_matched_text() -> None:
    """The output lands in public CI logs, so it names only place and kind."""
    secret = ".".join(["192", "168", "7", "7"])

    (finding,) = check_text(secret, "example.txt")

    assert secret not in str(finding)
    assert str(finding).startswith("example.txt:1: ")


def test_tree_skips_binary_and_generated_files(tmp_path: Path) -> None:
    """Only text written by hand is checked."""
    address = ".".join(["192", "168", "1", "1"])
    (tmp_path / "notes.md").write_text(address, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(address, encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\xff\xfe" + address.encode())

    findings = check_tree(tmp_path, ["notes.md", "uv.lock", "icon.png", "gone.md"])

    assert [finding.path for finding in findings] == ["notes.md"]


def test_this_repository_passes() -> None:
    """No tracked file of this repository looks like instance data.

    Where git does not work for the checkout (inside WSL, when git lives on
    the Windows side), the test is skipped. CI runs the script itself.
    """
    root = Path(__file__).parents[2]
    try:
        paths = tracked_files(root)
    except GitUnavailableError as error:
        pytest.skip(str(error))

    assert check_tree(root, paths) == []
