"""The instance data guard recognizes the shapes of real installations.

This file is tracked and therefore scanned by the guard itself. Every example
that must be found is put together from pieces at runtime, so that the file
contains no line that looks like instance data. All values are made up.
"""

import os
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
    run,
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
    assert report.links == []
    assert report.nested == []
    assert report.name_findings == []
    assert report.summary() == (
        "judged 4 path text(s) (names of files and folders); "
        "checked 1 file(s), 0 of them symbolic link(s) judged by their target "
        "text; skipped: 1 binary, 1 generated, 0 folder(s) of nested checkouts, "
        "1 deleted but still listed by git"
    )


def _link(link: Path, target: str, *, to_folder: bool = False) -> bool:
    """Create a symbolic link the way a checkout would have it.

    Returns whether the platform made a real link. Where it refuses (Windows
    without the right to create links), git itself does not create one either:
    with ``core.symlinks=false`` it checks a link out as a plain text file that
    holds the target. That file is written instead, so the principle "the
    target text of a link is judged" is tested on every platform and no test
    is skipped.
    """
    try:
        link.symlink_to(target, target_is_directory=to_folder)
    except OSError:
        link.write_text(target, encoding="utf-8")
        return False
    return True


def test_broken_link_with_a_private_looking_target_is_found(tmp_path: Path) -> None:
    """Git publishes the target text of a link, whether the target exists or not."""
    target = "/home" + "/someone/notes.txt"
    real = _link(tmp_path / "shortcut", target)

    report = check_tree(tmp_path, ["shortcut"])

    assert [(f.path, f.line) for f in report.findings] == [("shortcut", 1)]
    assert report.findings[0].kind == "path inside a user's home directory"
    assert target not in str(report.findings[0])
    assert report.checked == ["shortcut"]
    assert report.links == (["shortcut"] if real else [])
    assert report.absent == []


def test_link_with_a_harmless_target_is_checked_and_passes(tmp_path: Path) -> None:
    """A link counts as checked; it is not "listed but not present"."""
    (tmp_path / "notes.md").write_text("harmless\n", encoding="utf-8")
    real = _link(tmp_path / "shortcut", "notes.md")

    report = check_tree(tmp_path, ["notes.md", "shortcut"])

    assert report.findings == []
    assert report.checked == ["notes.md", "shortcut"]
    assert report.links == (["shortcut"] if real else [])
    assert report.absent == []


def test_link_is_not_followed_to_the_content_behind_it(tmp_path: Path) -> None:
    """What is judged is the link, not a file outside the list that it names."""
    outside = tmp_path / "outside.txt"
    outside.write_text(".".join(["192", "168", "3", "3"]), encoding="utf-8")
    _link(tmp_path / "shortcut", "outside.txt")

    assert check_tree(tmp_path, ["shortcut"]).findings == []


def test_link_to_a_folder_is_judged_by_its_target_too(tmp_path: Path) -> None:
    """A link to a folder is a link, not a nested checkout."""
    (tmp_path / "folder").mkdir()
    real = _link(tmp_path / "harmless", "folder", to_folder=True)
    _link(tmp_path / "private", "/Users" + "/someone/folder", to_folder=True)

    report = check_tree(tmp_path, ["harmless", "private"])

    assert [finding.path for finding in report.findings] == ["private"]
    assert report.checked == ["harmless", "private"]
    assert report.nested == []
    assert len(report.links) == (2 if real else 0)


def test_folder_of_a_nested_checkout_is_counted_not_read(tmp_path: Path) -> None:
    """Git lists a folder only for a checkout of its own and publishes a commit id."""
    (tmp_path / "nested").mkdir()
    (tmp_path / "module").mkdir()

    report = check_tree(tmp_path, ["nested/", "module"])

    assert report.nested == ["module", "nested"]
    assert report.checked == []
    assert "2 folder(s) of nested checkouts" in report.summary()


# Absent on Windows; looked up by name so that the type checker accepts both systems.
MAKE_NAMED_PIPE = getattr(os, "mkfifo", None)


@pytest.mark.skipif(MAKE_NAMED_PIPE is None, reason="the platform has no named pipes")
def test_path_of_an_unknown_kind_cannot_be_judged(tmp_path: Path) -> None:
    """Skipped where no such path can exist, so nothing is hidden there.

    Without named pipes (Windows) the branch under test cannot be reached by
    any path git could list; every kind that exists there has its own test.
    """
    assert MAKE_NAMED_PIPE is not None
    MAKE_NAMED_PIPE(tmp_path / "pipe")

    with pytest.raises(CannotCheckError, match="neither a file, a link nor a folder"):
        check_tree(tmp_path, ["pipe"])


def _refuse_lstat(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make the operating system refuse to examine every path called ``name``."""
    original = Path.lstat

    def lstat(path: Path) -> os.stat_result:
        if path.name == name:
            raise PermissionError(13, "refused for the test", str(path))
        return original(path)

    monkeypatch.setattr(Path, "lstat", lstat)


def test_file_that_cannot_be_examined_is_not_counted_as_deleted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Any error but "no such file" is a failure; runs on every platform."""
    (tmp_path / "locked.md").write_text(".".join(["10", "9", "8", "7"]), "utf-8")
    _refuse_lstat(monkeypatch, "locked.md")

    with pytest.raises(CannotCheckError, match="cannot be examined") as caught:
        check_tree(tmp_path, ["locked.md"])
    assert "PermissionError" in str(caught.value)
    assert "entry 1 of the list of git" in str(caught.value)
    assert str(tmp_path) not in str(caught.value)


def test_unexaminable_file_with_a_private_looking_name_is_not_named(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The message of the failure keeps to the position of the entry."""
    name = "notes-" + ".".join(["10", "9", "8", "7"]) + ".md"
    (tmp_path / name).write_text("harmless\n", encoding="utf-8")
    _refuse_lstat(monkeypatch, name)

    with pytest.raises(CannotCheckError) as caught:
        check_tree(tmp_path, ["harmless.md", name])
    assert str(caught.value).startswith("entry 2 of the list of git is listed but")
    assert name not in str(caught.value)


def test_failure_to_examine_ends_the_run_with_status_two(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Through ``main``: never "deleted but still listed", never a pass."""
    _refuse_lstat(monkeypatch, "new.md")

    status, output = _run_on(checkout, monkeypatch, capsys)

    assert status == EXIT_CANNOT_CHECK
    assert "CANNOT CHECK" in output
    assert "instance data: ok" not in output


CAN_LOCK_FOLDERS = os.name == "posix" and getattr(os, "geteuid", lambda: 0)() != 0


@pytest.mark.skipif(
    not CAN_LOCK_FOLDERS, reason="permissions cannot be taken away here"
)
def test_staged_file_in_a_folder_without_permission_is_not_a_pass(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The real case: git has the content staged, the folder can no longer be entered.

    Skipped where a folder cannot be locked (Windows, or a run as root, for
    which permissions do not hold). Nothing is hidden by that: the test above
    forces the same answer of the operating system on every platform, and this
    one runs on Linux, which is where CI runs.
    """
    folder = checkout / "locked"
    folder.mkdir()
    (folder / "staged.md").write_text(".".join(["10", "9", "8", "7"]), "utf-8")
    _git(checkout, "add", "locked/staged.md")
    folder.chmod(0)
    try:
        status, output = _run_on(checkout, monkeypatch, capsys)
    finally:
        folder.chmod(0o700)

    assert status == EXIT_CANNOT_CHECK
    assert "cannot be examined (PermissionError)" in output
    assert "deleted but still listed" not in output


def test_entry_that_is_really_gone_is_still_counted_as_deleted(tmp_path: Path) -> None:
    """Only "no such file" means deleted, also below a path that is a file now."""
    (tmp_path / "now-a-file").write_text("harmless\n", encoding="utf-8")

    report = check_tree(tmp_path, ["gone.md", "now-a-file/inner.md", "now-a-file"])

    assert report.absent == ["gone.md", "now-a-file/inner.md"]
    assert report.checked == ["now-a-file"]


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


def test_link_in_a_checkout_is_listed_and_found(checkout: Path) -> None:
    """From the list of git to the finding, for a new link that is not ignored."""
    _link(checkout / "shortcut", "/home" + "/someone/elsewhere")

    report = check_checkout(checkout, own_path="tracked.md")

    assert [finding.path for finding in report.findings] == ["shortcut"]
    assert "shortcut" in report.checked


def test_inherited_git_variables_cannot_redirect_the_list(
    checkout: Path,
    tmp_path_factory: pytest.TempPathFactory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``GIT_DIR`` and its relatives of the environment are not handed to git."""
    other = tmp_path_factory.mktemp("other")
    _git(other, "init", "--quiet")
    (other / "other.md").write_text("other\n", encoding="utf-8")
    _git(other, "add", "other.md")
    monkeypatch.setenv("GIT_DIR", str(other / ".git"))
    monkeypatch.setenv("GIT_WORK_TREE", str(other))
    monkeypatch.setenv("GIT_INDEX_FILE", str(other / ".git" / "index"))

    assert sorted(list_files(checkout)) == [".gitignore", "new.md", "tracked.md"]


def test_unforeseen_error_is_a_failure_without_its_text(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The net below everything: status 2, the type of the error, nothing else."""
    private = "/home" + "/someone/checkout"

    def entry() -> int:
        raise KeyError(private)

    assert run(entry) == EXIT_CANNOT_CHECK
    output = capsys.readouterr().out
    assert "CANNOT CHECK" in output
    assert "internal error in check_instance_data.py (KeyError)" in output
    assert private not in output
    assert run(lambda: 0) == 0


# Made-up names that look private; put together at runtime like every example here.
PRIVATE_ADDRESS = ".".join(["192", "168", "9", "9"])
PRIVATE_ENTITY = "cover." + "shutter_" + "0012345678"


def _run_on(
    root: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> tuple[int, str]:
    """Run ``main`` on a small repository, as the command line would."""
    monkeypatch.setattr("scripts.check_instance_data.REPOSITORY_ROOT", root)
    # The small repository does not contain the guard; its own file stands in.
    monkeypatch.setattr(
        "scripts.check_instance_data.check_checkout",
        lambda root: check_checkout(root, own_path="tracked.md"),
    )
    status = main()
    return status, capsys.readouterr().out


def test_harmless_names_pass_and_are_counted(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The pass line says that path texts were judged, and how many."""
    allowed = checkout / ("homeassistant" + ".local") / "address-192.0.2.7.md"
    allowed.parent.mkdir()
    allowed.write_text("documentation values in a name\n", encoding="utf-8")

    status, output = _run_on(checkout, monkeypatch, capsys)

    assert status == 0, output
    assert (
        "judged 4 path text(s) (names of files and folders); checked 4 file(s)"
        in output
    )


@pytest.mark.parametrize("private", [PRIVATE_ADDRESS, PRIVATE_ENTITY])
def test_new_file_with_a_private_looking_name_is_found_without_naming_it(
    checkout: Path,
    private: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The name is the private text here, so the output calls the entry by position."""
    name = f"notes-{private}.md"
    (checkout / name).write_text(PRIVATE_ADDRESS, encoding="utf-8")

    status, output = _run_on(checkout, monkeypatch, capsys)

    assert status == EXIT_FINDINGS
    assert private not in output
    assert name not in output
    assert PRIVATE_ADDRESS not in output
    position = list_files(checkout).index(name) + 1
    assert f"entry {position} of the list of git: its name looks like: " in output
    assert f"line {position} of the output of 'git ls-files" in output
    # The finding in the content of that file does not give the name away either.
    assert f"entry {position} of the list of git:1: looks like: private IPv4" in output
    assert "1 suspicious line(s) and 1 suspicious name(s)" in output


def test_private_looking_folder_name_is_found_for_a_harmless_file(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole relative path is judged, so the names of folders count."""
    folder = checkout / f"host-{PRIVATE_ADDRESS}"
    folder.mkdir()
    (folder / "readme.md").write_text("harmless\n", encoding="utf-8")

    status, output = _run_on(checkout, monkeypatch, capsys)

    assert status == EXIT_FINDINGS
    assert PRIVATE_ADDRESS not in output
    assert "readme.md" not in output
    assert "0 suspicious line(s) and 1 suspicious name(s)" in output


def test_name_is_judged_where_the_content_is_skipped(tmp_path: Path) -> None:
    """Binary, nested and deleted entries have a published name too.

    The generated lock file is skipped by its exact name in the root only; the
    same name inside a private-looking folder is judged like any other entry.
    """
    binary = f"icon-{PRIVATE_ADDRESS}.png"
    (tmp_path / binary).write_bytes(b"\x89PNG\x00\xff\xfe")
    nested = f"module-{PRIVATE_ADDRESS}"
    (tmp_path / nested).mkdir()
    deleted = f"gone-{PRIVATE_ADDRESS}.md"
    generated = f"{PRIVATE_ENTITY}/uv.lock"
    (tmp_path / "harmless.md").write_text("harmless\n", encoding="utf-8")
    real_link = _link(tmp_path / f"link-{PRIVATE_ADDRESS}", "harmless.md")
    listed = [binary, f"{nested}/", deleted, generated, "harmless.md"]
    listed.append(f"link-{PRIVATE_ADDRESS}")

    report = check_tree(tmp_path, listed)

    assert [finding.entry for finding in report.name_findings] == [4, 3, 1, 6, 2]
    assert report.names_judged == len(listed)
    assert report.binary == [binary]
    assert report.nested == [nested]
    assert report.absent == [generated, deleted]
    assert len(report.links) == (1 if real_link else 0)
    assert report.findings == []
    assert all(PRIVATE_ADDRESS not in str(f) for f in report.name_findings)
    assert all(PRIVATE_ENTITY not in str(f) for f in report.name_findings)


def test_ignored_file_with_a_private_looking_name_is_not_listed(
    checkout: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """What git ignores is never published, whatever it is called."""
    (checkout / "private" / f"{PRIVATE_ADDRESS}.md").write_text("x\n", "utf-8")
    (checkout / f"{PRIVATE_ADDRESS}.secret").write_text("x\n", encoding="utf-8")

    status, output = _run_on(checkout, monkeypatch, capsys)

    assert status == 0, output
    assert "judged 3 path text(s)" in output


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
    summary = re.fullmatch(
        r"instance data: ok; judged (\d+) path text\(s\) .*; checked (\d+) file\(s\), .*",
        lines[-1],
    )
    assert summary is not None
    assert int(summary[2]) >= MINIMUM_FILES_OF_THIS_REPOSITORY
    assert int(summary[1]) >= int(summary[2]), "skipped entries have a name too"
