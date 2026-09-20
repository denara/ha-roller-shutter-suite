"""The pre-push hook runs the instance data guard and refuses what it must.

``.githooks/pre-push`` is a POSIX ``sh`` script. The tests of its text run
everywhere. The tests that start it need an ``sh``: on Linux and macOS there
always is one, on Windows it comes with git for Windows, which the guard and
its tests need anyway. Only where no ``sh`` can be found are these tests
skipped, and nothing is hidden by that: without an ``sh`` git cannot run the
hook either, so there is no hook whose behavior could differ, and CI runs them
all on Linux.

The hook makes two calls of the guard: one judges the checkout, the other the
commits that the push would send (``tests/scripts/test_check_pushed_commits.py``
tests that judgment in detail). Here both are proven from end to end, most of
it with a real ``git push`` into a bare repository.

Every private-looking value is made up and put together at runtime, because
this file is scanned by the guard itself. No test changes a git configuration:
the hook is started directly, or handed to one ``git push`` of a throw-away
repository with ``-c core.hooksPath``; a named remote exists for that one
command only, through ``-c`` as well. The commits of such a repository are
written as objects by hand, so that no identity is configured or passed.

The tests read numbers out of the last line of each run. Documented and stable
are its beginnings, ``instance data: ok; judged <n> path text(s)`` and
``instance data, pushed commits: ok; judged <n> commit(s)``; the rest of the
wording may change.
"""

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from scripts.check_instance_data import listing_commands
from tests.scripts.throwaway_repository import (
    MAIN,
    ZEROS,
    Repository,
    environment,
    hook_line,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
HOOKS_FOLDER = REPOSITORY_ROOT / ".githooks"
HOOK = HOOKS_FOLDER / "pre-push"
HOOK_IN_GIT = ".githooks/pre-push"
GUARD = "scripts/check_instance_data.py"
CHECKOUT_CALL = '"$@" "$guard" </dev/null'
PUSHED_CALL = '"$@" "$guard" --pushed "$remote_name" "$remote_url"'
PRIVATE_VALUE = ".".join(["192", "168", "9", "9"])
TOPIC = "refs/heads/topic"
REMOTE = "origin"
FILES_OF_THE_CHECKOUT = 2


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
    for command in listing_commands(REPOSITORY_ROOT):
        git = command[: command.index("ls-files")]
        result = subprocess.run(  # noqa: S603 - the guard's own way of reaching git
            [*git, "ls-files", "--stage", "--", HOOK_IN_GIT],
            cwd=REPOSITORY_ROOT,
            env=environment(),
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


def _words(line: str) -> list[str]:
    """Return the words of a line of ``sh``, without text in single quotes.

    Such text is never run by ``sh``; the Python of the probe stands there.
    """
    return re.findall(r"[A-Za-z_]+", re.sub(r"'[^']*'", "''", line))


def test_nothing_in_the_hook_can_swallow_or_pass_by_a_status() -> None:
    """Both statuses are read at once, and the only ``exit 0`` stands behind both.

    Forbidden altogether: a pipe, ``&`` in every form (``&&``, a job in the
    background, and with it ``||``), ``set +e``, a trap, a negation, and every
    word that leaves a script or a function before the status is looked at or
    runs text as code. The behavior tests below stay the real proof.
    """
    code = _code_lines()

    # The one use of an ampersand that is allowed: a message to standard error.
    plain = [line.removesuffix(" >&2") for line in code]
    assert [line for line in plain if "|" in line or "&" in line] == []
    options = [line for line in code if line.startswith("set ") and "--" not in line]
    assert options == ["set -u"]
    forbidden = {"exec", "return", "trap", "eval", "source", "break", "continue"}
    forbidden |= {"alias", "unset", "wait", "kill"}
    assert [line for line in code if forbidden & set(_words(line))] == []
    assert [line for line in code if line.startswith(("!", ". "))] == []
    assert [line for line in code if "if !" in line or "`" in line] == []

    assert [line for line in code if GUARD in line] == [f'guard_path="{GUARD}"']
    assert [line for line in code if '"$@" "$guard"' in line] == [
        CHECKOUT_CALL,
        PUSHED_CALL,
    ]
    assert code[code.index(CHECKOUT_CALL) + 1] == "checkout_status=$?"
    assert code[code.index(PUSHED_CALL) + 1] == "pushed_status=$?"
    for status in ("checkout_status", "pushed_status"):
        assert [line for line in code if line.startswith(f"{status}=")] == [
            f"{status}=$?"
        ]

    # The only way to end with 0 stands behind the comparison of both with 0.
    assert [line for line in code if _words(line)[:1] == ["exit"]] == [
        "exit 1",
        "exit 0",
    ]
    position = code.index("exit 0")
    assert code[position - 2 : position] == [
        'if [ "$checkout_status" -eq 0 ]; then',
        'if [ "$pushed_status" -eq 0 ]; then',
    ]
    assert code[position - 3] == "pushed_status=$?"


def test_standard_input_reaches_exactly_one_call() -> None:
    """The lines of git belong to the call that judges the pushed commits.

    Every other command that could read them gets an empty input: the first
    call of the guard, git, uv and the probes of the Python candidates.
    """
    code = _code_lines()

    assert [line for line in code if line.startswith(("read ", "cat "))] == []
    assert "<" not in PUSHED_CALL
    starts_a_program = [
        line
        for line in code
        if ('"$@"' in line or "$(" in line or line.startswith("if command "))
        and line != PUSHED_CALL
    ]
    assert len(starts_a_program) == 5  # noqa: PLR2004 - git, the probe, uv twice, the guard
    assert [line for line in starts_a_program if "</dev/null" not in line] == []


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


def _run_hook(
    folder: Path,
    path: str | None = None,
    lines: str | None = None,
    remote: tuple[str, ...] = ("example", "example"),
) -> subprocess.CompletedProcess[str]:
    """Start the hook as git would; ``lines=None`` stands for the null device.

    The hook file lives in this repository, outside of the throw-away checkout
    it is started in, as it does for a worktree when ``core.hooksPath`` names
    the folder of another checkout: the hook judges the checkout it runs in,
    with the guard of that checkout. The lines are handed over as bytes, so
    that Windows does not change their ends.
    """
    assert SH is not None
    result = subprocess.run(  # noqa: S603 - the hook of this repository
        [SH, HOOK.as_posix(), *remote],
        cwd=folder,
        env=environment(path),
        stdin=subprocess.DEVNULL if lines is None else None,
        input=None if lines is None else lines.encode(),
        check=False,
        capture_output=True,
    )
    return subprocess.CompletedProcess(
        result.args,
        result.returncode,
        result.stdout.decode("utf-8"),
        result.stderr.decode("utf-8"),
    )


def _judged(output: str) -> tuple[int, int]:
    """Return the path texts of the checkout and the commits the hook judged."""
    checkout = re.search(
        r"^instance data: ok; judged (\d+) path text\(s\)", output, re.M
    )
    pushed = re.search(
        r"^instance data, pushed commits: ok; judged (\d+) commit\(s\)", output, re.M
    )
    assert checkout is not None, output
    assert pushed is not None, output
    return int(checkout[1]), int(pushed[1])


@pytest.fixture
def checkout(tmp_path: Path) -> Repository:
    """Return a throw-away repository with a copy of the guard and one commit."""
    repository = Repository.create(tmp_path / "checkout")
    repository.write(GUARD, (REPOSITORY_ROOT / GUARD).read_bytes())
    repository.write("docs/notes.md", "harmless\n")
    repository.commit()
    return repository


def _first_push(checkout: Repository) -> str:
    """Return the line git writes when ``main`` is new on the remote."""
    tip = checkout.tip()
    assert tip is not None
    return hook_line(tip, ZEROS)


@needs_sh
def test_clean_checkout_and_clean_commits_pass(checkout: Repository) -> None:
    """Exit status 0, and both runs say how much they judged."""
    result = _run_hook(checkout.root, lines=_first_push(checkout))

    assert result.returncode == 0, result.stdout
    assert _judged(result.stdout) == (FILES_OF_THE_CHECKOUT, 1)
    assert "REFUSED" not in result.stderr


@needs_sh
def test_new_file_with_a_private_looking_value_is_refused(checkout: Repository) -> None:
    """Untracked is enough; the value itself appears nowhere in the output."""
    (checkout.root / "new.md").write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    result = _run_hook(checkout.root, lines=_first_push(checkout))

    assert result.returncode != 0
    assert "new.md:1: looks like: private IPv4 address" in result.stdout
    assert "PUSH REFUSED: the check of the checkout did not pass" in result.stderr
    assert "exit status 1;" in result.stderr
    assert "--no-verify" in result.stderr
    assert PRIVATE_VALUE not in result.stdout + result.stderr
    # The second run still happened, and it found nothing in the commits.
    assert "instance data, pushed commits: ok; judged 1 commit(s)" in result.stdout


@needs_sh
def test_hook_works_from_a_subfolder(checkout: Repository) -> None:
    """The checkout is found through git, not through the current folder."""
    folder = checkout.root / "docs"
    assert _run_hook(folder, lines=_first_push(checkout)).returncode == 0
    (checkout.root / "new.md").write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    assert _run_hook(folder, lines=_first_push(checkout)).returncode != 0


@needs_sh
def test_hook_judges_the_worktree_it_is_started_in(checkout: Repository) -> None:
    """A worktree has its own files, and its own copy of the guard."""
    worktree = checkout.root.parent / "worktree"
    checkout.git("worktree", "add", "--quiet", "--detach", str(worktree), "main")
    (worktree / "new.md").write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    assert _run_hook(checkout.root, lines=_first_push(checkout)).returncode == 0
    refused = _run_hook(worktree, lines=_first_push(checkout))

    assert refused.returncode != 0
    assert "new.md:1: looks like" in refused.stdout


@needs_sh
@pytest.mark.parametrize(
    "lines", ["garbage\n", f"{MAIN} {'1' * 40} {MAIN}\n", "\n", None]
)
def test_input_that_is_not_what_git_writes_is_refused(
    checkout: Repository, lines: str | None
) -> None:
    """Garbage, a line with too few fields, or no input at all from no pipe."""
    result = _run_hook(checkout.root, lines=lines)

    assert result.returncode != 0
    assert "instance data: ok" in result.stdout, "the checkout itself is clean"
    assert "instance data, pushed commits: CANNOT CHECK" in result.stdout
    assert "PUSH REFUSED: the check of the pushed commits did not pass" in result.stderr
    assert "exit status 2;" in result.stderr


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
        f'case "$1" in rev-parse) case "$2" in --show-toplevel) '
        f"exec '{real}' \"$@\" ;; esac ;; esac\nexit 1",
    )


@needs_sh
def test_guard_that_cannot_ask_git_is_refused(
    checkout: Repository, tmp_path: Path
) -> None:
    """Exit status 2 of the guard refuses the push like a finding does.

    PATH holds this interpreter and a ``git`` that names the checkout for the
    hook and answers nothing else, so neither run finds a git that answers.
    """
    programs = tmp_path / "programs"
    _git_that_only_names_the_checkout(programs)
    path = os.pathsep.join([str(programs), str(Path(sys.executable).parent)])

    result = _run_hook(checkout.root, path, _first_push(checkout))

    assert result.returncode != 0
    assert result.stdout.count("CANNOT CHECK") == 2  # noqa: PLR2004 - both runs
    assert "PUSH REFUSED: neither check passed" in result.stderr
    assert "ok;" not in result.stdout


@needs_sh
@pytest.mark.parametrize(
    "stand_in",
    [None, "exit 1", "exit 0", "printf '%s' 'Python 3.99.0'", "printf '%s' \"$*\""],
)
def test_no_usable_python_is_refused(
    checkout: Repository, tmp_path: Path, stand_in: str | None
) -> None:
    """No Python, one that fails, or a program that merely ends with status 0.

    A candidate has to print the expected token, exactly. A stand-in that
    succeeds silently, prints something else, or repeats its arguments is not
    taken for a Python, so nothing it would "check" counts.
    """
    programs = tmp_path / "programs"
    _git_that_only_names_the_checkout(programs)
    if stand_in is not None:
        _shim(programs, "python3", stand_in)

    result = _run_hook(checkout.root, str(programs), _first_push(checkout))

    assert result.returncode != 0
    assert "PUSH REFUSED: no Python that can run" in result.stderr
    assert "ok;" not in result.stdout


@needs_sh
def test_git_that_cannot_name_the_checkout_is_refused(tmp_path: Path) -> None:
    """Outside of every checkout the hook has nothing to check, so it refuses."""
    result = _run_hook(tmp_path, str(tmp_path), "")

    assert result.returncode != 0
    assert "PUSH REFUSED: git cannot name the checkout" in result.stderr


@needs_sh
def test_top_of_a_checkout_is_not_taken_on_trust(
    checkout: Repository, tmp_path: Path
) -> None:
    """If git does not answer, a folder that looks like a checkout is not enough."""
    result = _run_hook(checkout.root, str(tmp_path), _first_push(checkout))

    assert result.returncode != 0
    assert "PUSH REFUSED: git cannot name the checkout" in result.stderr
    assert "ok;" not in result.stdout


@needs_sh
def test_checkout_without_the_guard_is_refused(checkout: Repository) -> None:
    """A missing guard is not a pass."""
    (checkout.root / GUARD).unlink()

    result = _run_hook(checkout.root, lines=_first_push(checkout))

    assert result.returncode != 0
    assert "PUSH REFUSED: the instance data guard" in result.stderr


@pytest.fixture
def remote(tmp_path: Path) -> Repository:
    """Return an empty bare repository to push into."""
    return Repository.create(tmp_path / "remote.git", bare=True)


def _push(
    checkout: Repository, remote: Repository, *refspecs: str, named: bool = True
) -> subprocess.CompletedProcess[str]:
    """Push with the hook active, and the remote named, for this one command only."""
    git = shutil.which("git")
    assert git is not None
    url = remote.root.as_posix()
    settings = ["-c", f"core.hooksPath={HOOKS_FOLDER.as_posix()}"]
    if named:
        settings += [
            "-c",
            f"remote.{REMOTE}.url={url}",
            "-c",
            f"remote.{REMOTE}.fetch=+refs/heads/*:refs/remotes/{REMOTE}/*",
        ]
    return subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
        [git, *settings, "push", REMOTE if named else url, *refspecs],
        cwd=checkout.root,
        env=environment(),
        stdin=subprocess.DEVNULL,
        check=False,
        capture_output=True,
        text=True,
    )


def _refs(repository: Repository) -> list[str]:
    return repository.git("for-each-ref", "--format=%(refname)").split()


@needs_sh
@pytest.mark.parametrize("named", [True, False])
def test_push_is_refused_with_a_finding_and_goes_through_without(
    checkout: Repository, remote: Repository, *, named: bool
) -> None:
    """From end to end: git starts the hook and obeys its exit status."""
    finding = checkout.root / "new.md"
    finding.write_text(f"host: {PRIVATE_VALUE}\n", encoding="utf-8")

    refused = _push(checkout, remote, "main", named=named)

    assert refused.returncode != 0
    assert "PUSH REFUSED" in refused.stderr
    assert PRIVATE_VALUE not in refused.stdout + refused.stderr
    assert _refs(remote) == []

    finding.unlink()
    accepted = _push(checkout, remote, "main", named=named)

    assert accepted.returncode == 0, accepted.stderr
    assert _refs(remote) == [MAIN]


def _mistake_in_a_file(checkout: Repository) -> None:
    checkout.write("docs/notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    checkout.commit("Add a host")
    checkout.write("docs/notes.md", "harmless\nhost: example\n")
    checkout.commit("Use a neutral host")


def _mistake_in_a_message(checkout: Repository) -> None:
    checkout.write("docs/notes.md", "harmless\nmore\n")
    checkout.commit(f"Add more\n\nSeen on {PRIVATE_VALUE}")
    checkout.write("docs/notes.md", "harmless\nmore\nand more\n")
    checkout.commit("Add even more")


def _mistake_in_a_path_text(checkout: Repository) -> None:
    checkout.write(f"docs/{PRIVATE_VALUE}.md", "harmless\n")
    checkout.commit("Add a page")
    checkout.remove(f"docs/{PRIVATE_VALUE}.md")
    checkout.write("docs/page.md", "harmless\n")
    checkout.commit("Rename the page")


@needs_sh
@pytest.mark.parametrize(
    ("mistake", "place"),
    [
        (_mistake_in_a_file, "docs/notes.md:2: looks like"),
        (_mistake_in_a_message, "message:3: looks like"),
        (_mistake_in_a_path_text, "entry 1 of its changed entries: its name"),
    ],
)
def test_mistake_that_the_next_commit_corrected_is_refused(
    checkout: Repository,
    remote: Repository,
    mistake: Callable[[Repository], None],
    place: str,
) -> None:
    """The checkout is clean, the history is not: nothing reaches the remote."""
    assert _push(checkout, remote, "main").returncode == 0
    mistake(checkout)
    mistaken = checkout.git("rev-parse", "main~1")

    refused = _push(checkout, remote, "main")

    output = refused.stdout + refused.stderr
    assert refused.returncode != 0
    assert "instance data: ok" in output, "the checkout itself is clean"
    assert f"commit {mistaken[:10]}: {place}" in output
    assert "PUSH REFUSED: the check of the pushed commits did not pass" in output
    assert "exit status 1;" in output
    assert PRIVATE_VALUE not in output
    assert remote.tip() == checkout.git("rev-parse", "main~2")


@needs_sh
def test_mistake_on_a_new_branch_is_refused(
    checkout: Repository, remote: Repository
) -> None:
    """A branch the remote does not know yet: judged up to what the remote has."""
    assert _push(checkout, remote, "main").returncode == 0
    base = checkout.tip()
    assert base is not None
    checkout.write("docs/notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    checkout.commit(ref=TOPIC, parents=[base])
    checkout.write("docs/notes.md", "harmless\n")
    checkout.commit(ref=TOPIC)

    refused = _push(checkout, remote, "topic")

    assert refused.returncode != 0
    assert "2 commit(s)" in refused.stdout + refused.stderr
    assert PRIVATE_VALUE not in refused.stdout + refused.stderr
    assert _refs(remote) == [MAIN]


@needs_sh
def test_one_new_clean_commit_on_an_existing_branch_passes(
    checkout: Repository, remote: Repository
) -> None:
    """The summary counts exactly the commit that is new for the remote."""
    assert _push(checkout, remote, "main").returncode == 0
    checkout.write("docs/notes.md", "harmless\nmore\n")
    commit = checkout.commit("Add more")

    accepted = _push(checkout, remote, "main")

    assert accepted.returncode == 0, accepted.stderr
    assert _judged(accepted.stdout + accepted.stderr) == (FILES_OF_THE_CHECKOUT, 1)
    assert remote.tip() == commit


@needs_sh
def test_push_with_nothing_to_send_passes_and_says_so(
    checkout: Repository, remote: Repository
) -> None:
    """Git starts the hook with an empty pipe when the remote is up to date."""
    assert _push(checkout, remote, "main").returncode == 0

    again = _push(checkout, remote, "main")

    assert again.returncode == 0, again.stderr
    assert _judged(again.stdout + again.stderr) == (FILES_OF_THE_CHECKOUT, 0)
    assert "git named no ref to push" in again.stdout + again.stderr


@needs_sh
def test_deletion_of_a_remote_branch_passes(
    checkout: Repository, remote: Repository
) -> None:
    """A deletion sends no commit."""
    assert _push(checkout, remote, "main", "main:topic").returncode == 0
    assert _refs(remote) == [MAIN, TOPIC]

    deleted = _push(checkout, remote, ":topic")

    assert deleted.returncode == 0, deleted.stderr
    assert _judged(deleted.stdout + deleted.stderr) == (FILES_OF_THE_CHECKOUT, 0)
    assert "1 deletion(s) of a remote ref" in deleted.stdout + deleted.stderr
    assert _refs(remote) == [MAIN]


@needs_sh
def test_one_bad_ref_among_several_refuses_the_whole_push(
    checkout: Repository, remote: Repository
) -> None:
    """Git sends all refs or none; one flagged commit keeps all of them at home."""
    assert _push(checkout, remote, "main").returncode == 0
    base = checkout.tip()
    assert base is not None
    checkout.write("docs/more.md", "harmless\n")
    checkout.commit("Add a page")
    checkout.write("docs/other.md", f"host: {PRIVATE_VALUE}\n")
    checkout.commit(ref=TOPIC, parents=[base])
    checkout.remove("docs/other.md")
    checkout.commit(ref=TOPIC)

    refused = _push(checkout, remote, "main", "topic")

    assert refused.returncode != 0
    assert PRIVATE_VALUE not in refused.stdout + refused.stderr
    assert "docs/other.md:1: looks like" in refused.stdout + refused.stderr
    assert _refs(remote) == [MAIN]
    assert remote.tip() == base


@needs_sh
def test_remote_object_that_is_unknown_locally_is_refused(
    checkout: Repository, remote: Repository, tmp_path: Path
) -> None:
    """Somebody else pushed in between: the hook says to fetch first."""
    assert _push(checkout, remote, "main").returncode == 0
    other = Repository.create(tmp_path / "other")
    other.write("docs/elsewhere.md", "harmless\n")
    other.commit("Work of somebody else")
    # No hook is active in a throw-away repository unless a test hands it over.
    other.git("push", "--force", remote.root.as_posix(), "main")
    theirs = remote.tip()
    checkout.write("docs/notes.md", "harmless\nmore\n")
    checkout.commit("Add more")

    refused = _push(checkout, remote, "+main")

    output = refused.stdout + refused.stderr
    assert refused.returncode != 0
    assert "fetch first" in output
    assert "instance data, pushed commits: CANNOT CHECK" in output
    assert "PUSH REFUSED: the check of the pushed commits did not pass" in output
    assert remote.tip() == theirs


@needs_sh
def test_merge_of_the_remote_main_line_is_not_judged_again(
    checkout: Repository, remote: Repository
) -> None:
    """What the remote has stays outside, whatever its messages look like.

    The flagged message reaches the remote without the hook, as a commit would
    that was merged on the server. The topic branch then merges it.
    """
    assert _push(checkout, remote, "main").returncode == 0
    base = checkout.tip()
    assert base is not None
    checkout.write("docs/topic.md", "harmless\n")
    topic = checkout.commit("Add a topic", ref=TOPIC, parents=[base])
    assert _push(checkout, remote, "topic").returncode == 0
    checkout.remove("docs/topic.md")
    checkout.write("docs/main.md", "harmless\n")
    on_main = checkout.commit(f"Seen on {PRIVATE_VALUE}")
    checkout.git("push", remote.root.as_posix(), "main")
    checkout.git("update-ref", f"refs/remotes/{REMOTE}/main", on_main)
    checkout.write("docs/topic.md", "harmless\n")
    checkout.commit("Merge the main line", ref=TOPIC, parents=[topic, on_main])

    accepted = _push(checkout, remote, "topic")

    assert accepted.returncode == 0, accepted.stdout + accepted.stderr
    assert _judged(accepted.stdout + accepted.stderr)[1] == 1
