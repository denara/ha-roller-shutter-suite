"""The pre-push hook runs the instance data guard and refuses what it must.

``.githooks/pre-push`` is a POSIX ``sh`` script. The tests of its text run
everywhere. The tests that start it need an ``sh``: on Linux and macOS there
always is one, on Windows it comes with git for Windows, which the guard and
its tests need anyway. Only where no ``sh`` can be found are these tests
skipped, and nothing is hidden by that: without an ``sh`` git cannot run the
hook either, so there is no hook whose behavior could differ, and CI runs them
all on Linux.

Every private-looking value is made up and put together at runtime, because
this file is scanned by the guard itself. No test changes a git configuration:
the hook is started directly, or handed to one ``git push`` of a throw-away
repository with ``-c core.hooksPath``. The commit of such a repository is
written as an object by hand, so that no identity is configured or passed.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.check_instance_data import listing_commands

REPOSITORY_ROOT = Path(__file__).parents[2]
HOOKS_FOLDER = REPOSITORY_ROOT / ".githooks"
HOOK = HOOKS_FOLDER / "pre-push"
HOOK_IN_GIT = ".githooks/pre-push"
GUARD = "scripts/check_instance_data.py"
GUARD_CALL = '"$@" "$guard" </dev/null'
PRIVATE_VALUE = ".".join(["192", "168", "9", "9"])
# A commit object written by hand; the address is a documentation value.
COMMIT = (
    "tree {tree}\n"
    "author Example <someone@example.com> 0 +0000\n"
    "committer Example <someone@example.com> 0 +0000\n"
    "\n"
    "Made-up commit of a throw-away repository\n"
)


def _code_lines() -> list[str]:
    lines = [line.strip() for line in HOOK.read_text(encoding="utf-8").splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def test_hook_is_a_posix_script_with_unix_line_endings() -> None:
    """``sh`` on every system has to read it, so no carriage return, no bash."""
    content = HOOK.read_bytes()

    assert content.startswith(b"#!/bin/sh\n")
    assert b"\r" not in content
    assert content.endswith(b"\n")
    assert not content.startswith(b"\xef\xbb\xbf")


def test_hook_is_tracked_as_executable() -> None:
    """Git on Linux and macOS ignores a hook without the executable bit.

    The mode is read from the index with the commands the guard uses to reach
    git, so the test also works where the guard works (a worktree of git for
    Windows seen from inside WSL). Never skipped: no answer is a failure.
    """
    answers = []
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }
    for command in listing_commands(REPOSITORY_ROOT):
        git = command[: command.index("ls-files")]
        result = subprocess.run(  # noqa: S603 - the guard's own way of reaching git
            [*git, "ls-files", "--stage", "--", HOOK_IN_GIT],
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            answers.append(result.stdout)
            break

    assert len(answers) == 1, "git cannot be asked about this checkout"
    assert answers[0].startswith("100755 ")
    assert answers[0].rstrip("\n").endswith(f"\t{HOOK_IN_GIT}")


def test_nothing_in_the_hook_can_swallow_the_status_of_the_guard() -> None:
    """No pipe at all, no ``||``, no ``set +e``, no trap; the status is read at once."""
    code = _code_lines()

    assert [line for line in code if "|" in line] == []
    options = [line for line in code if line.startswith("set ") and "--" not in line]
    assert options == ["set -u"]
    assert [line for line in code if "trap" in line or line.startswith("!")] == []
    assert code.count(GUARD_CALL) == 1
    assert [line for line in code if GUARD in line] == [f'guard_path="{GUARD}"']
    assert code[code.index(GUARD_CALL) + 1] == "status=$?"
    # The only way to end with 0 is the line after the comparison with 0.
    assert [line for line in code if line.startswith("exit")] == ["exit 1", "exit 0"]
    position = code.index("exit 0")
    assert code[position - 1] == 'if [ "$status" -eq 0 ]; then'
    assert code[position - 2] == "status=$?"


def test_hook_does_not_read_what_git_writes_to_it() -> None:
    """The refs on standard input are not needed; the guard gets an empty input."""
    code = _code_lines()

    assert [line for line in code if line.startswith(("read ", "cat "))] == []
    assert GUARD_CALL.endswith("</dev/null")


def _find_sh() -> str | None:
    """Return an ``sh``: from PATH, or the one that git for Windows ships."""
    found = shutil.which("sh")
    git = shutil.which("git")
    if found is not None or git is None:
        return found
    for top in Path(git).resolve().parents[:3]:
        for candidate in (top / "bin" / "sh.exe", top / "usr" / "bin" / "sh.exe"):
            if candidate.is_file():
                return str(candidate)
    return None


SH = _find_sh()
needs_sh = pytest.mark.skipif(
    SH is None, reason="no sh here, so git cannot run the hook either"
)


def _environment(path: str | None = None) -> dict[str, str]:
    """Return the environment without the variables that redirect git."""
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }
    if path is not None:
        environment["PATH"] = path
    return environment


def _git(root: Path, *arguments: str, text: str | None = None) -> str:
    git = shutil.which("git")
    assert git is not None, "these tests need git, like the guard itself"
    result = subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
        [git, *arguments],
        cwd=root,
        env=_environment(),
        # Bytes, so that Windows does not turn the line ends of an object into CRLF.
        input=None if text is None else text.encode(),
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8").strip()


def _run_hook(
    folder: Path, path: str | None = None
) -> subprocess.CompletedProcess[str]:
    assert SH is not None
    return subprocess.run(  # noqa: S603 - the hook of this repository
        [SH, HOOK.as_posix()],
        cwd=folder,
        env=_environment(path),
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
    )


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a throw-away repository with a copy of the guard and one commit."""
    root = tmp_path / "checkout"
    (root / "scripts").mkdir(parents=True)
    (root / "docs").mkdir()
    shutil.copyfile(REPOSITORY_ROOT / GUARD, root / GUARD)
    (root / "docs" / "notes.md").write_text("harmless\n", encoding="utf-8")
    _git(root, "init", "--quiet")
    _git(root, "symbolic-ref", "HEAD", "refs/heads/main")
    _git(root, "add", GUARD, "docs/notes.md")
    tree = _git(root, "write-tree")
    commit = _git(
        root,
        "hash-object",
        "-t",
        "commit",
        "-w",
        "--stdin",
        text=COMMIT.format(tree=tree),
    )
    _git(root, "update-ref", "refs/heads/main", commit)
    return root


@needs_sh
def test_clean_checkout_passes(checkout: Path) -> None:
    """Exit status 0, and the line of the guard that says how much it read."""
    result = _run_hook(checkout)

    assert result.returncode == 0, result.stdout
    assert "instance data: ok; judged 2 path text(s)" in result.stdout
    assert "REFUSED" not in result.stderr


@needs_sh
def test_new_file_with_a_private_looking_value_is_refused(checkout: Path) -> None:
    """Untracked is enough; the value itself appears nowhere in the output."""
    (checkout / "new.md").write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    result = _run_hook(checkout)

    assert result.returncode != 0
    assert "new.md:1: looks like: private IPv4 address" in result.stdout
    assert "PUSH REFUSED: the instance data guard has findings" in result.stderr
    assert "--no-verify" in result.stderr
    assert PRIVATE_VALUE not in result.stdout + result.stderr


@needs_sh
def test_hook_works_from_a_subfolder(checkout: Path) -> None:
    """The checkout is found through git, not through the current folder."""
    assert _run_hook(checkout / "docs").returncode == 0
    (checkout / "new.md").write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    assert _run_hook(checkout / "docs").returncode != 0


@needs_sh
def test_hook_judges_the_worktree_it_is_started_in(checkout: Path) -> None:
    """A worktree has its own files, and its own copy of the guard."""
    worktree = checkout.parent / "worktree"
    _git(checkout, "worktree", "add", "--quiet", "--detach", str(worktree), "main")
    (worktree / "new.md").write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    assert _run_hook(checkout).returncode == 0
    refused = _run_hook(worktree)

    assert refused.returncode != 0
    assert "new.md:1: looks like" in refused.stdout


def _shim(folder: Path, name: str, body: str) -> None:
    """Write a small ``sh`` program that stands in for ``name`` on PATH."""
    folder.mkdir(exist_ok=True)
    program = folder / name
    program.write_bytes(f"#!/bin/sh\n{body}\n".encode())
    program.chmod(0o755)


def _git_that_only_names_the_checkout(folder: Path) -> None:
    """Put a ``git`` on PATH that answers the hook and refuses the guard."""
    git = shutil.which("git")
    assert git is not None
    real = Path(git).as_posix()
    _shim(
        folder,
        "git",
        f'case "$1" in rev-parse) exec \'{real}\' "$@" ;; esac\nexit 1',
    )


@needs_sh
def test_guard_that_cannot_list_the_files_is_refused(
    checkout: Path, tmp_path: Path
) -> None:
    """Exit status 2 of the guard refuses the push like a finding does.

    PATH holds this interpreter and a ``git`` that names the checkout for the
    hook and answers nothing else, so the guard finds no git that lists files.
    """
    programs = tmp_path / "programs"
    _git_that_only_names_the_checkout(programs)
    path = os.pathsep.join([str(programs), str(Path(sys.executable).parent)])

    result = _run_hook(checkout, path)

    assert result.returncode != 0
    assert "CANNOT CHECK" in result.stdout
    assert "PUSH REFUSED: the instance data guard could not check" in result.stderr
    assert "instance data: ok" not in result.stdout


@needs_sh
@pytest.mark.parametrize("broken_python", [False, True])
def test_no_usable_python_is_refused(
    checkout: Path, tmp_path: Path, *, broken_python: bool
) -> None:
    """No Python, or one that cannot compile the guard: nothing was checked."""
    programs = tmp_path / "programs"
    _git_that_only_names_the_checkout(programs)
    if broken_python:
        _shim(programs, "python3", "exit 1")

    result = _run_hook(checkout, str(programs))

    assert result.returncode != 0
    assert "PUSH REFUSED: no Python that can run" in result.stderr
    assert "instance data: ok" not in result.stdout


@needs_sh
def test_git_that_cannot_name_the_checkout_is_refused(tmp_path: Path) -> None:
    """Outside of every checkout the hook has nothing to check, so it refuses."""
    result = _run_hook(tmp_path, str(tmp_path))

    assert result.returncode != 0
    assert "PUSH REFUSED: git cannot name the checkout" in result.stderr


@needs_sh
def test_checkout_without_the_guard_is_refused(checkout: Path) -> None:
    """A missing guard is not a pass."""
    (checkout / GUARD).unlink()

    result = _run_hook(checkout)

    assert result.returncode != 0
    assert "PUSH REFUSED: the instance data guard" in result.stderr


def _push(checkout: Path, remote: Path) -> subprocess.CompletedProcess[str]:
    """Push with the hook active for this one command only."""
    git = shutil.which("git")
    assert git is not None
    return subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
        [
            git,
            "-c",
            f"core.hooksPath={HOOKS_FOLDER.as_posix()}",
            "push",
            remote.as_posix(),
            "main",
        ],
        cwd=checkout,
        env=_environment(),
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
    )


@needs_sh
def test_push_is_refused_with_a_finding_and_goes_through_without(
    checkout: Path, tmp_path: Path
) -> None:
    """From end to end: git starts the hook and obeys its exit status."""
    remote = tmp_path / "remote.git"
    remote.mkdir()
    _git(remote, "init", "--quiet", "--bare")
    finding = checkout / "new.md"
    finding.write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    refused = _push(checkout, remote)

    assert refused.returncode != 0
    assert "PUSH REFUSED" in refused.stderr
    assert PRIVATE_VALUE not in refused.stdout + refused.stderr
    assert _git(remote, "for-each-ref") == ""

    finding.unlink()
    accepted = _push(checkout, remote)

    assert accepted.returncode == 0, accepted.stderr
    assert _git(remote, "for-each-ref", "--format=%(refname)") == "refs/heads/main"
