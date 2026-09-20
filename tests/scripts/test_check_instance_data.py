"""The instance data guard recognizes the shapes of real installations.

This file is tracked and therefore scanned by the guard itself. Every example
that must be found is put together from pieces at runtime, so that the file
contains no line that looks like instance data. All values are made up.
"""

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_instance_data import (
    EXIT_CANNOT_CHECK,
    EXIT_FINDINGS,
    PATTERNS,
    CannotCheckError,
    check_checkout,
    check_text,
    check_tree,
    list_files,
    listing_commands,
    main,
)

# The repository has far more files; a run that read a handful read the wrong tree.
MINIMUM_FILES_OF_THIS_REPOSITORY = 50

AT = "@"
SUSPICIOUS = {
    "private IPv4 address": [
        ".".join(["192", "168", "0", "10"]),
        "host: " + ".".join(["10", "0", "0", "5"]),
        ".".join(["172", "16", "4", "1"]) + ":8123",
    ],
    "hardware (MAC) address": [":".join(["00", "1a", "2b", "3c", "4d", "5e"])],
    "IPv6 address": [
        ":".join(["fe80", "", "1a2b", "3c4d"]),
        ":".join(["fd12", "3456", "789a", "1", "", "5"]),
        ":".join(["2a02", "1234", "5678", "9abc", "def0", "1234", "5678", "9abc"]),
    ],
    "host name in the local network": [
        "nas" + ".local",
        "http://my-server" + ".local:8123",
    ],
    "pair of coordinates": [
        "12." + "3456, 98." + "7654",
        "home: -12." + "345678 / 123." + "456789",
    ],
    "coordinate next to a latitude or longitude key": [
        "latitude: 12." + "345",
        '"lon": -123.' + "4567",
        "LAT=" + "1.2345",
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
    "DAMPING = 0.0174532925 and a ratio of 1.618033988749",
    "limits = (0.125, 0.98765) and steps of 0.00001",
    "tests/ha/test_x.py::test_y and ignore::DeprecationWarning:module",
    "the documentation address 2001:db8::1 and the loopback ::1",
    "http://homeassistant.local:8123 and threading.local()",
    "relative: ../local/file and a.local_name",
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


def test_tree_accounts_for_every_listed_file(tmp_path: Path) -> None:
    """Only text written by hand is checked, and the rest is counted by reason."""
    address = ".".join(["192", "168", "1", "1"])
    (tmp_path / "notes.md").write_text(address, encoding="utf-8")
    (tmp_path / "uv.lock").write_text(address, encoding="utf-8")
    (tmp_path / "icon.png").write_bytes(b"\x89PNG\x00\xff\xfe" + address.encode())

    report = check_tree(tmp_path, ["notes.md", "uv.lock", "icon.png", "gone.md"])

    assert [finding.path for finding in report.findings] == ["notes.md"]
    assert report.checked == ["notes.md"]
    assert report.generated == ["uv.lock"]
    assert report.binary == ["icon.png"]
    assert report.absent == ["gone.md"]
    assert report.summary().startswith("checked 1 file(s); skipped: 1 binary, ")


def test_text_in_another_encoding_cannot_be_judged(tmp_path: Path) -> None:
    """A text file that is not UTF-8 is not waved through as binary."""
    (tmp_path / "legacy.txt").write_bytes("caf\xe9 and more".encode("latin-1"))

    with pytest.raises(CannotCheckError, match=r"legacy\.txt is neither"):
        check_tree(tmp_path, ["legacy.txt"])


def _git(root: Path, *arguments: str) -> None:
    git = shutil.which("git")
    assert git is not None, "these tests need git, like the guard itself"
    subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
        [git, *arguments], cwd=root, check=True, capture_output=True
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a small repository: tracked, new, and ignored files."""
    _git(tmp_path, "init", "--quiet")
    (tmp_path / ".gitignore").write_text("private/\n*.secret\n", encoding="utf-8")
    (tmp_path / "tracked.md").write_text("tracked\n", encoding="utf-8")
    _git(tmp_path, "add", ".gitignore", "tracked.md")
    (tmp_path / "new.md").write_text("about to be committed\n", encoding="utf-8")
    (tmp_path / "private").mkdir()
    (tmp_path / "private" / "notes.md").write_text("ignored\n", encoding="utf-8")
    (tmp_path / "token.secret").write_text("ignored\n", encoding="utf-8")
    return tmp_path


def test_list_has_tracked_and_new_files_but_no_ignored_ones(checkout: Path) -> None:
    """A new file counts before it is committed; an ignored folder is not read."""
    assert sorted(list_files(checkout)) == [".gitignore", "new.md", "tracked.md"]


def test_new_file_with_instance_data_is_found(checkout: Path) -> None:
    """The file that is about to be committed is the one that matters most."""
    address = ".".join(["10", "1", "2", "3"])
    (checkout / "new.md").write_text(address, encoding="utf-8")
    (checkout / "private" / "notes.md").write_text(address, encoding="utf-8")

    report = check_checkout(checkout, own_path="tracked.md")

    assert [finding.path for finding in report.findings] == ["new.md"]
    assert report.checked == [".gitignore", "new.md", "tracked.md"]


def test_list_of_something_else_is_refused(checkout: Path) -> None:
    """A list without the guard itself does not describe this repository."""
    with pytest.raises(CannotCheckError, match="is not among them"):
        check_checkout(checkout)


def test_no_git_at_all_cannot_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without any git on PATH there is no list, and no guessing either."""
    monkeypatch.setattr("scripts.check_instance_data.shutil.which", lambda _name: None)

    assert listing_commands(tmp_path) == []
    with pytest.raises(CannotCheckError, match="git cannot list the files"):
        list_files(tmp_path)


def test_failing_git_ends_with_a_failure_and_a_clear_message(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A guard that could not check exits with its own non-zero status."""
    failing = [sys.executable, "-c", "import sys; sys.exit('fatal: ' + sys.argv[0])"]
    monkeypatch.setattr(
        "scripts.check_instance_data.listing_commands", lambda _root: [failing]
    )

    status = main()

    output = capsys.readouterr().out
    assert status == EXIT_CANNOT_CHECK
    assert status not in (0, EXIT_FINDINGS)
    assert "CANNOT CHECK" in output
    assert "git cannot list the files of this checkout (1 way(s) tried)" in output
    assert "fatal" not in output, "what git printed may name local paths"
    assert "instance data: ok" not in output


def test_worktree_of_another_system_is_resolved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A ``.git`` file with a path of another system is translated, not skipped."""
    foreign = "Q" + ":/" + "elsewhere/.git/worktrees/example"
    git_dir = tmp_path / "translated"
    git_dir.mkdir()
    root = tmp_path / "worktree"
    root.mkdir()
    (root / ".git").write_text(f"gitdir: {foreign}\n", encoding="utf-8")
    asked: list[list[str]] = []

    def answer(command: list[str], _root: Path) -> list[str]:
        asked.append(command)
        return [f"{git_dir}\n"]

    monkeypatch.setattr(
        "scripts.check_instance_data.shutil.which", lambda name: f"/bin/{name}"
    )
    monkeypatch.setattr("scripts.check_instance_data._answer", answer)

    commands = listing_commands(root)

    assert asked == [["/bin/wslpath", "-u", foreign]]
    assert [command[0] for command in commands] == [
        "/bin/git",
        "/bin/git",
        "/bin/git.exe",
    ]
    assert f"--git-dir={git_dir}" in commands[1]
    assert f"--work-tree={root.as_posix()}" in commands[1]
    assert all("ls-files" in command for command in commands)


def test_ordinary_checkout_needs_no_translation(
    checkout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a ``.git`` folder, or a ``.git`` file git can follow, git is asked once."""
    monkeypatch.setattr(
        "scripts.check_instance_data.shutil.which",
        lambda name: "/bin/git" if name == "git" else None,
    )

    assert [command[0] for command in listing_commands(checkout)] == ["/bin/git"]


def test_this_repository_passes(capsys: pytest.CaptureFixture[str]) -> None:
    """No file of this checkout looks like instance data, and files were read.

    This test is never skipped. Where git cannot list the checkout the guard
    does not work, and then this test has to fail like the guard does.
    """
    status = main()

    lines = capsys.readouterr().out.splitlines()
    assert status == 0, lines
    summary = re.fullmatch(r"instance data: ok; checked (\d+) file\(s\); .*", lines[-1])
    assert summary is not None
    assert int(summary[1]) >= MINIMUM_FILES_OF_THIS_REPOSITORY
