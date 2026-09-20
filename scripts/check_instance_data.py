"""Guard: no file that is or may become public contains data of a real machine.

The repository is public. This script reads every file that git tracks and
every untracked file that git does not ignore (a new file that is about to be
committed is the one that matters most), and fails when a line looks like it
came from a real installation or from somebody's computer. Ignored files are
not read: they are never published, and some of them hold such data on purpose.
The patterns are generic shapes, not a list of known values: a list of real
values would itself be instance data.

A finding names the file, the line and the kind of pattern, but never the text
that matched, because the output of this script ends up in public CI logs. For
the same reason the script never repeats what git printed.

The check is a net with holes. It cannot know that a harmless looking room
name is real. It complements the rule in ``tasks/README.md``, it does not
replace reading what you publish.

**Names are judged too.** Git publishes the name of a file or folder exactly
like its content, so the whole relative path of every listed entry is judged
with the same patterns and the same allowed documentation values (once as it
is and once without file extensions, so that an address in front of ``.md`` is
seen), also for
entries whose content is skipped (binary, generated, nested checkouts, deleted
files). Here the name itself is the private text, so such an entry is never
named in the output, neither in the finding about its name nor in a finding
about its content: it is called by its position in the list of git, and the
message says how to see that list locally.

**The guard fails closed.** A guard that could not check never looks like a
pass. "Could not check" means here, and ends with exit status 2:

- no way of asking git for the files worked (see below);
- git answered, but this script is not on its list or was not among the files
  checked, so the list does not describe this checkout (this also rules out a
  run that checked no file at all);
- a listed path exists but cannot be examined (no permission for its folder, a
  path that is too long, an input/output error): only "there is no such file"
  counts as deleted, every other answer of the operating system is a failure;
- a listed file cannot be read, or it is neither UTF-8 text nor binary (binary
  means it contains a NUL byte, which is how git decides it), so it cannot be
  judged;
- a listed path is something this script does not know how to judge (a named
  pipe, a socket, a device);
- anything unforeseen happens inside the script. Then only the type of the
  error is printed, never its text, which may name a local path.

**What git lists, and what happens to each kind.** Every listed path ends in
exactly one of these groups, and the last line of a run counts each group:

- a regular text file: checked;
- a symbolic link: checked. What git publishes of a link is the text of its
  target, so that text is judged like a line of a file, whether the target
  exists or not, and whatever it points to. The link is never followed;
- a binary file, and the generated lock file: skipped, nothing in them is
  written by hand;
- a folder: skipped. Git lists a folder only when it is a checkout of its own
  (a submodule, or a nested repository that is not ignored), and git publishes
  of it nothing but a commit id;
- a path that does not exist at all: skipped. That is a tracked file that was
  deleted and whose deletion is not committed yet; there is nothing to publish.

Exit status 1 means findings, 0 means that the files were really read; the
last line then says how many path texts were judged, how many files were
checked and how many were skipped and why.

**How the files are listed.** Only git knows faithfully what is ignored, so
the list always comes from ``git ls-files --cached --others
--exclude-standard``; the script never walks the tree with its own reading of
``.gitignore``. The ways of reaching a git that can answer are tried in this
order, each found through ``PATH``, none through a fixed location:

1. ``git`` in the checkout. ``safe.directory`` is passed for this one call on
   the command line, because a checkout on a mounted drive may belong to
   another user in git's eyes. No configuration is written.
2. ``git`` with the git directory resolved by this script. A worktree that git
   for Windows created has a ``.git`` file with a Windows path in it, which a
   Linux git inside WSL takes for a relative path and gives up. ``wslpath``
   translates that path.
3. ``git.exe``, which WSL can start through its Windows interoperability, for
   a distribution that has no git of its own.

If none of them answers, the guard fails and says what to install.

Variables of the environment that point git to another repository or change
its configuration (``GIT_DIR``, ``GIT_WORK_TREE``, ``GIT_INDEX_FILE`` and the
other ``GIT_*`` variables) are not handed to git, so the list always describes
the checkout this script lives in.

Run it from anywhere: ``python scripts/check_instance_data.py``. It needs git
and the standard library.

**The second mode: what a push really sends.** The checkout shows the end state
only. A private value that was committed by mistake and corrected in the next
commit is gone from the checkout, but it leaves with the history of the branch
and stays retrievable on the server. ``python scripts/check_instance_data.py
--pushed <name of the remote> <URL of the remote>`` is what the pre-push hook
(``.githooks/pre-push``) calls after the check of the checkout. It reads the
lines git hands to such a hook on standard input, one per ref::

    <local ref> <local object name> <remote ref> <remote object name>

and judges, with the patterns and allowed values above and nothing else:

- the name of every remote ref that is created or updated (a branch name is
  published like a file name);
- every commit the push would send, one by one and never as one combined
  difference, because the correcting commit would hide the mistake. The commits
  of a line are those reachable from the local object and neither from the
  remote object (if the ref exists there) nor from a remote-tracking ref of the
  named remote. A remote that has no name, only a URL, has no remote-tracking
  refs of its own; then those of all remotes are taken. A commit that several
  refs reach is judged once;
- of each commit the message (subject, body, trailers; also every header line
  other than ``tree``, ``parent``, ``author``, ``committer`` and a signature),
  the path text of every entry that differs from the first parent and is not
  deleted (for a commit without a parent: every entry), and the added lines of
  these entries. An added line is a line of the new content whose text does not
  occur in the first parent's content of the same path; such a text is either
  public already or was judged in the commit that brought it. Renames are not
  detected, so a renamed file counts as new: its new path and all its lines are
  judged. Deleted lines and deleted paths are not judged;
- content is sorted into the groups of the first mode: text and the target
  text of a symbolic link are judged, a binary file and the generated lock
  file are skipped, of a nested checkout git publishes a commit id only;
- a ref outside ``refs/heads/`` (a tag, for example) is judged in the same way.
  If the local object is an annotated tag, the message of the tag object is
  judged too, and the tag has to lead to a commit.

The lines of the author and the committer are not judged by these patterns.
They are compared instead: the e-mail address of the author and the one of
the committer of every judged commit have to equal ``user.email`` as git
resolves it for this checkout (read, never written; upper and lower case are
not told apart). This catches a commit that was made in another environment
with another identity. A finding names the commit and says whether it is the
author or the committer; it prints neither address. Without a configured
address the identity cannot be compared, and that is a failure. Commits that
the remote already has, such as a merge made on the server with the address of
the server as committer, are outside the range and are not compared. The
tagger of a tag object is not compared.
A line whose local object name consists of zeros deletes a ref, sends nothing
and is only counted.

This mode fails closed like the first one, with exit status 2: a line that
cannot be parsed; an object that is not known locally (the remote object of a
ref after somebody else pushed: fetch first); a ref that leads to something
other than a commit; a message, path or content that is neither UTF-8 nor
binary; any failure of git; no input at all from something that is not a pipe
or a file (git always hands the hook a pipe; without a line in it git has
nothing to push, and the last line of the run says so). The only way to exit
status 0 is that every listed commit was judged and is clean; the last line
then starts with ``instance data, pushed commits: ok; judged <n> commit(s)``.
A finding names the commit by its abbreviated object name, the kind of place
and the kind of pattern, never the text, and never a path that looks private.
"""

import contextlib
import itertools
import os
import re
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

# ``__file__`` is absolute; nothing at module level touches the file system.
REPOSITORY_ROOT = Path(__file__).parents[1]
# A correct list of this checkout contains the guard itself.
OWN_PATH = "scripts/check_instance_data.py"
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2
LIST_COMMAND_IN_WORDS = "git ls-files --cached --others --exclude-standard"
_LIST_ARGUMENTS = ("ls-files", "-z", "--cached", "--others", "--exclude-standard")
_GIT_TIMEOUT_SECONDS = 120
_GITDIR_PREFIX = "gitdir:"
# One or more extensions at the end of a part of a path: ``.md``, ``.tar.gz``.
_EXTENSION = re.compile(r"(?:\.[A-Za-z][A-Za-z0-9]*)+(?=/|$)")
# Not handed to git: they could make it list another repository.
_GIT_VARIABLE_PREFIX = "GIT_"

# The lock file is generated by uv and consists of package names, versions,
# URLs of the package index and hashes. Nothing in it is written by hand, and
# long hexadecimal hashes would only produce false findings.
SKIPPED_FILES = frozenset({"uv.lock"})

_ENTITY_DOMAINS = (
    "binary_sensor|button|climate|cover|device_tracker|event|fan|input_boolean|"
    "input_number|input_select|light|lock|media_player|number|person|scene|"
    "select|sensor|sun|switch|update|weather|zone"
)

# Documentation addresses that are reserved for examples and therefore allowed.
_ALLOWED_MAIL_DOMAINS = ("example.com", "example.org", "example.net")
# The no-reply address in the co-author trailer of generated commits may also
# appear in contributor documentation.
_ALLOWED_MAIL_SUFFIXES = ("noreply@anthropic.com", "users.noreply.github.com")
# The IPv6 documentation range, and the host names every installation has.
_ALLOWED_IPV6_PREFIX = "2001:db8:"
_ALLOWED_HOST_NAMES = ("homeassistant.local", "example.local")

PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "private IPv4 address",
        re.compile(
            r"(?<![\d.])(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))"
            r"\.\d{1,3}\.\d{1,3}(?![\d.])"
        ),
    ),
    (
        "hardware (MAC) address",
        re.compile(
            r"(?<![0-9A-Fa-f:-])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![:-])"
        ),
    ),
    (
        "IPv6 address",
        re.compile(
            r"(?<![\w:.])(?:"
            r"(?:[0-9A-Fa-f]{1,4}:){7}[0-9A-Fa-f]{1,4}"
            r"|(?:[0-9A-Fa-f]{1,4}:){1,6}:(?:[0-9A-Fa-f]{1,4}(?::[0-9A-Fa-f]{1,4}){0,5})?"
            r")(?![\w:])"
        ),
    ),
    (
        "host name in the local network",
        re.compile(r"(?<![\w.-])[A-Za-z0-9][A-Za-z0-9-]*\.local(?![\w.(-])"),
    ),
    # A plain number with many decimals is not reported: constants of the
    # domain core look like that. A coordinate is recognized by its company.
    (
        "pair of coordinates",
        re.compile(
            r"(?<![\w.])-?\d{1,2}\.\d{4,}\s*[,;/ ]\s*-?\d{1,3}\.\d{4,}(?![\w.])"
        ),
    ),
    (
        "coordinate next to a latitude or longitude key",
        re.compile(
            r"(?i)(?<![a-z])(?:lat|latitude|lon|lng|long|longitude)[\"']?\s*[:=]\s*"
            r"[\"']?-?\d{1,3}\.\d{3,}"
        ),
    ),
    (
        "entity ID with a serial-number-like part",
        re.compile(
            rf"\b(?:{_ENTITY_DOMAINS})\.[a-z0-9_]*?"
            r"(?:\d{5,}|(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,})[a-z0-9_]*"
        ),
    ),
    (
        "path with a Windows drive letter",
        re.compile(r"(?<![A-Za-z])[A-Za-z]:[\\/]{1,2}[A-Za-z_]"),
    ),
    (
        "path inside a user's home directory",
        re.compile(r"(?:/home/|/Users/|\\Users\\)[A-Za-z0-9][\w.-]*"),
    ),
    (
        "path of a mounted Windows drive",
        re.compile(r"/mnt/[a-z]/"),
    ),
    (
        "e-mail address",
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+"),
    ),
    # A link to one session or conversation of an assistant tool, which some
    # tools append to a commit message by themselves. It leads to a private
    # page of whoever worked there. Matched narrowly: the host of a known tool,
    # then the part of the path under which that tool keeps sessions, shared
    # conversations included, then the beginning of an identifier. The plain
    # link to a product (the attribution line of generated commits has one) has
    # no such path and is not matched, nor is the co-author trailer.
    (
        "link to a session of an assistant tool",
        re.compile(
            r"(?i)(?<![\w.-])(?:www\.)?(?:"
            r"claude\.ai/(?:code|chat|share)"
            r"|chatgpt\.com/(?:c|share)"
            r"|chat\.openai\.com/(?:c|share)"
            r"|gemini\.google\.com/(?:app|share)"
            r"|g\.co/gemini/share"
            r"|copilot\.microsoft\.com/(?:chats|shares)"
            r"|github\.com/copilot/(?:c|share)"
            r")/[\w-]"
        ),
    ),
)


@dataclass(frozen=True)
class Finding:
    """One suspicious line. The matched text is deliberately not kept."""

    path: str
    line: int
    kind: str

    def __str__(self) -> str:
        """Render as ``path:line: kind``."""
        return f"{self.path}:{self.line}: looks like: {self.kind}"


def _is_allowed(kind: str, matched: str) -> bool:
    lowered = matched.lower()
    if kind == "IPv6 address":
        return lowered.startswith(_ALLOWED_IPV6_PREFIX)
    if kind == "host name in the local network":
        return lowered in _ALLOWED_HOST_NAMES
    if kind != "e-mail address":
        return False
    return lowered.endswith(_ALLOWED_MAIL_SUFFIXES) or lowered.rsplit("@", 1)[
        -1
    ].endswith(_ALLOWED_MAIL_DOMAINS)


def _kinds(line: str) -> list[str]:
    """Return the kinds of pattern that one line of text looks like."""
    return [
        kind
        for kind, pattern in PATTERNS
        if any(not _is_allowed(kind, m.group()) for m in pattern.finditer(line))
    ]


def check_text(text: str, path: str) -> list[Finding]:
    """Check the content of one file."""
    return [
        Finding(path, number, kind)
        for number, line in enumerate(text.splitlines(), start=1)
        for kind in _kinds(line)
    ]


@dataclass(frozen=True)
class NameFinding:
    """A listed entry whose name looks private. The name is deliberately not kept."""

    entry: int
    kind: str

    def __str__(self) -> str:
        """Render without the name: position in the list of git, and the kind."""
        return (
            f"{entry_label(self.entry)}: its name looks like: {self.kind}. The name "
            f"is not printed here; it is line {self.entry} of the output of "
            f"'{LIST_COMMAND_IN_WORDS}'"
        )


def entry_label(entry: int) -> str:
    """Return the neutral label of an entry whose name must not be printed."""
    return f"entry {entry} of the list of git"


def check_name(listed: str, entry: int) -> list[NameFinding]:
    """Judge the path text of one entry, exactly as git reports it.

    The patterns end an address or a host name where a dot follows, which is
    right for prose and wrong for ``<address>.md``. The path is therefore
    judged a second time with the file extensions taken off every part of it.
    """
    return [NameFinding(entry, kind) for kind in name_kinds(listed)]


def name_kinds(listed: str) -> list[str]:
    """Return the kinds of pattern a path text looks like; see ``check_name``."""
    without_extensions = _EXTENSION.sub(" ", listed)
    return list(dict.fromkeys([*_kinds(listed), *_kinds(without_extensions)]))


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


@dataclass
class Report:
    """What a run looked at, and what it found."""

    findings: list[Finding] = field(default_factory=list)
    name_findings: list[NameFinding] = field(default_factory=list)
    # Every entry of the list, whatever became of its content.
    names_judged: int = 0
    checked: list[str] = field(default_factory=list)
    # Symbolic links, judged by the text of their target; part of ``checked``.
    links: list[str] = field(default_factory=list)
    binary: list[str] = field(default_factory=list)
    generated: list[str] = field(default_factory=list)
    # Folders: checkouts of their own, of which git publishes a commit id only.
    nested: list[str] = field(default_factory=list)
    # Neither a file nor a link nor a folder: deleted and not yet committed.
    absent: list[str] = field(default_factory=list)

    def summary(self) -> str:
        """Say how much was checked and what was skipped, and why."""
        return (
            f"judged {self.names_judged} path text(s) (names of files and folders); "
            f"checked {len(self.checked)} file(s), {len(self.links)} of them "
            f"symbolic link(s) judged by their target text; skipped: "
            f"{len(self.binary)} binary, {len(self.generated)} generated, "
            f"{len(self.nested)} folder(s) of nested checkouts, {len(self.absent)} "
            "deleted but still listed by git"
        )


def _environment() -> dict[str, str]:
    """Return the environment for git: without the variables that redirect it."""
    return {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(_GIT_VARIABLE_PREFIX)
    }


def _answer(command: list[str], root: Path) -> list[str] | None:
    """Run a command that prints NUL-separated text; ``None`` if it cannot.

    What the command writes to standard error is dropped on purpose: git names
    local paths there, and the output of this script may be pasted in public.
    """
    try:
        result = subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
            command,
            cwd=root,
            env=_environment(),
            check=True,
            capture_output=True,
            timeout=_GIT_TIMEOUT_SECONDS,
        )
        return [name for name in result.stdout.decode("utf-8").split("\0") if name]
    except OSError, subprocess.SubprocessError, UnicodeDecodeError:
        return None


def _unreachable_git_dir(root: Path) -> str | None:
    """Return the git directory a ``.git`` file names, if it is not reachable.

    That is the mark of a worktree created by a git of another system: inside
    WSL the file holds a Windows path. A path that exists as written needs no
    help, git follows it by itself.
    """
    pointer = root / ".git"
    try:
        lines = pointer.read_text(encoding="utf-8").splitlines()
    except OSError, UnicodeDecodeError:
        return None
    if not lines or not lines[0].startswith(_GITDIR_PREFIX):
        return None
    target = lines[0].removeprefix(_GITDIR_PREFIX).strip()
    if not target:
        return None
    try:
        (root / target).stat()
    except OSError:
        # Not reachable, for whatever reason: worth a translation. If that does
        # not help either, no way answers and the guard fails closed.
        return target
    return None


def _translated_git_dir(root: Path) -> str | None:
    """Return the git directory of a Windows worktree as a path of this system."""
    target = _unreachable_git_dir(root)
    translator = shutil.which("wslpath")
    if target is None or translator is None:
        return None
    answer = _answer([translator, "-u", target], root)
    if not answer:
        return None
    translated = answer[0].strip()
    return translated if translated and Path(translated).is_dir() else None


def listing_commands(root: Path) -> list[list[str]]:
    """Return the commands that may list the files, in the order to try them."""
    return [[*git, *_LIST_ARGUMENTS] for git in git_commands(root)]


def git_commands(root: Path) -> list[list[str]]:
    """Return the ways of calling git for this checkout, in the order to try them.

    Each is the beginning of a command line, to be followed by a git command.
    Every program is looked up through ``PATH``; see the module documentation
    for the reason behind each entry.
    """
    commands: list[list[str]] = []
    git = shutil.which("git")
    if git is not None:
        # Git compares safe.directory with the real path of the checkout.
        try:
            real_root = root.resolve().as_posix()
        except (OSError, RuntimeError) as error:
            raise CannotCheckError(
                f"the folder of the checkout cannot be resolved ({type(error).__name__})"
            ) from error
        safe = [git, "-c", f"safe.directory={real_root}"]
        commands.append(safe)
        git_dir = _translated_git_dir(root)
        if git_dir is not None:
            commands.append(
                [*safe, f"--git-dir={git_dir}", f"--work-tree={root.as_posix()}"]
            )
    windows_git = shutil.which("git.exe")
    if windows_git is not None and windows_git != git:
        commands.append([windows_git])
    return commands


def list_files(root: Path) -> list[str]:
    """Return tracked and untracked-but-not-ignored files, relative to ``root``.

    Raises :class:`CannotCheckError` when no git can answer. There is no
    fallback that guesses: a list that git did not write is not used.
    """
    commands = listing_commands(root)
    for command in commands:
        paths = _answer(command, root)
        if paths is not None:
            return paths
    raise CannotCheckError(
        f"git cannot list the files of this checkout ({len(commands)} way(s) "
        "tried). Install git where this script runs and make sure it is on PATH. "
        "Inside WSL with a worktree that git for Windows created, the Linux git "
        "also needs 'wslpath' on PATH; a distribution without git needs 'git.exe' "
        "on PATH, which WSL provides unless its Windows interoperability or the "
        "Windows PATH is switched off"
    )


def _read_text(file: Path, relative: str) -> str | None:
    """Return the text of a file, or ``None`` for a binary file."""
    try:
        content = file.read_bytes()
    except OSError as error:
        raise CannotCheckError(
            f"{relative} cannot be read ({type(error).__name__}); make it readable "
            "or have git ignore it"
        ) from error
    return _decoded(content, relative)


def _decoded(content: bytes, shown: str) -> str | None:
    """Return content as text, or ``None`` if it is binary; else it cannot be judged."""
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        if b"\0" in content:
            return None
        raise CannotCheckError(
            f"{shown} is neither UTF-8 text nor binary, so it cannot be judged; "
            "save it as UTF-8, as .editorconfig demands"
        ) from error


def _link_text(file: Path, relative: str) -> str:
    """Return the target of a symbolic link as written, which is what git stores."""
    try:
        target = os.readlink(file)  # noqa: PTH115 - as written, Path would normalize it
    except OSError as error:
        raise CannotCheckError(
            f"the target of the link {relative} cannot be read ({type(error).__name__})"
        ) from error
    return os.fsdecode(target)


def _mode(file: Path, entry: int, shown: str) -> int | None:
    """Return the kind of a listed path without following a link; ``None`` if gone.

    Exactly one question is put to the file system, and only "there is no such
    file" counts as deleted. ``Path.exists``, ``is_dir`` and ``is_symlink``
    answer ``False`` for every error (no permission, a path that is too long,
    an input/output error of a mounted drive), and a file that exists but cannot
    be examined would then pass as deleted while git publishes its content.
    """
    try:
        return file.lstat().st_mode
    except FileNotFoundError, NotADirectoryError:
        return None
    except OSError as error:
        label = entry_label(entry)
        where = shown if shown == label else f"{shown} ({label})"
        raise CannotCheckError(
            f"{where} is listed but cannot be examined "
            f"({type(error).__name__}), so it cannot be told whether it still "
            "exists; make it and its folder accessible, or have git ignore it"
        ) from error


def check_tree(root: Path, paths: list[str]) -> Report:
    """Check the given files below ``root`` and account for every one of them."""
    report = Report()
    # The position counts from 1 in the order of git, so that it can be looked up.
    for entry, listed in sorted(enumerate(paths, start=1), key=lambda item: item[1]):
        # Git marks an untracked nested checkout with a slash at the end.
        relative = listed.rstrip("/")
        file = root / relative
        named = check_name(listed, entry)
        report.name_findings += named
        report.names_judged += 1
        # What is printed about this entry: never a name that looks private.
        shown = entry_label(entry) if named else relative
        mode = _mode(file, entry, shown)
        if mode is None:
            report.absent.append(relative)
        elif stat.S_ISLNK(mode):
            # First of all: a link is never followed, whatever it points to.
            report.links.append(relative)
            report.checked.append(relative)
            report.findings += check_text(_link_text(file, shown), shown)
        elif relative in SKIPPED_FILES:
            report.generated.append(relative)
        elif stat.S_ISDIR(mode):
            report.nested.append(relative)
        elif not stat.S_ISREG(mode):
            raise CannotCheckError(
                f"{shown} is neither a file, a link nor a folder, so it cannot "
                "be judged; remove it or have git ignore it"
            )
        elif (text := _read_text(file, shown)) is None:
            report.binary.append(relative)
        else:
            report.checked.append(relative)
            report.findings += check_text(text, shown)
    return report


def check_checkout(root: Path, own_path: str = OWN_PATH) -> Report:
    """List the files of a checkout and check them; refuse a list that is off."""
    paths = list_files(root)
    if own_path not in paths:
        raise CannotCheckError(
            f"git listed {len(paths)} file(s), but {own_path} is not among them, "
            "so the list does not describe this checkout. Run the script from "
            "a complete checkout of the repository"
        )
    report = check_tree(root, paths)
    if own_path not in report.checked:
        raise CannotCheckError(f"{own_path} is listed by git but was not checked")
    return report


PUSHED_OPTION = "--pushed"
_OBJECT_NAME = re.compile(r"[0-9a-f]{40}|[0-9a-f]{64}")
_RAW_ENTRY = re.compile(r":(\d{6}) (\d{6}) ([0-9a-f]+) ([0-9a-f]+) ([AMDT])")
_ABBREVIATED = 10
_MODE_LINK = "120000"
_MODE_NESTED = "160000"
_MODE_NONE = "000000"
_GLOB_CHARACTERS = frozenset("*?[\\")
# An annotated tag may name another tag; nobody nests them deeply.
_MAXIMUM_TAG_DEPTH = 10
# Header lines of a commit or tag object that are not judged: object names, the
# identities (see the module documentation) and signatures.
_UNJUDGED_HEADERS = frozenset(
    {
        "tree",
        "parent",
        "author",
        "committer",
        "gpgsig",
        "gpgsig-sha256",
        "object",
        "type",
        "tagger",
    }
)
_HOOK_INPUT = "what git handed to the hook"
# The line of an author or committer: a name, the address, seconds, time zone.
_IDENTITY_ADDRESS = re.compile(r"[^<>]*<([^<>]*)> -?\d+ [+-]\d{4}")


@dataclass(frozen=True)
class PlaceFinding:
    """Something suspicious that is not a line of a file. The text is not kept."""

    place: str
    kind: str

    def __str__(self) -> str:
        """Render as ``place: kind``."""
        return f"{self.place}: looks like: {self.kind}"


@dataclass(frozen=True)
class IdentityFinding:
    """A commit that was not made with the identity of this clone. No address is kept."""

    commit: str
    role: str

    def __str__(self) -> str:
        """Render without any address."""
        return (
            f"commit {self.commit}: the e-mail address of its {self.role} is not the "
            "one configured for this clone ('git config user.email'); neither "
            "address is printed here"
        )


@dataclass(frozen=True)
class PushedRef:
    """One line of the hook's input. ``None`` stands for an object name of zeros."""

    line: int
    remote_ref: str
    local_object: str | None
    remote_object: str | None


@dataclass
class PushedReport:
    """What the check of a push looked at, and what it found."""

    findings: list[Finding | PlaceFinding | IdentityFinding] = field(
        default_factory=list
    )
    refs: int = 0
    deletions: int = 0
    commits: int = 0
    identities: int = 0
    messages: int = 0
    names: int = 0
    files: int = 0
    lines: int = 0
    binary: int = 0
    generated: int = 0
    nested: int = 0

    def summary(self) -> str:
        """Say how much was judged; the number of commits comes first."""
        if self.refs == 0 and self.deletions == 0:
            return (
                "judged 0 commit(s): git named no ref to push, as it does when "
                "the remote is up to date"
            )
        return (
            f"judged {self.commits} commit(s) that {self.refs} ref(s) would send: "
            f"{self.messages} message(s) of commits and tags, {self.names} path "
            f"text(s), {self.lines} added line(s) in {self.files} file(s); skipped: "
            f"{self.binary} binary, {self.generated} generated, {self.nested} "
            f"nested checkout(s); compared the addresses of author and committer of "
            f"{self.identities} commit(s) with the one configured for this clone; "
            f"{self.deletions} deletion(s) of a remote ref, which send nothing"
        )


def parse_pushed(data: bytes) -> list[PushedRef]:
    """Parse the lines git writes to a pre-push hook; refuse what is off."""
    try:
        lines = data.decode("utf-8").split("\n")
    except UnicodeDecodeError as error:
        raise CannotCheckError(f"{_HOOK_INPUT} is not UTF-8 text") from error
    if lines.pop():
        raise CannotCheckError(
            f"the last line of {_HOOK_INPUT} does not end with a line feed, so it "
            "may be cut off"
        )
    refs: list[PushedRef] = []
    for number, line in enumerate(lines, start=1):
        parts = line.rsplit(" ", 3)
        if (
            len(parts) != 4  # noqa: PLR2004 - the four fields of the line
            or not parts[0]
            or not parts[2].startswith("refs/")
            or _OBJECT_NAME.fullmatch(parts[1]) is None
            or _OBJECT_NAME.fullmatch(parts[3]) is None
            or len(parts[1]) != len(parts[3])
        ):
            raise CannotCheckError(
                f"line {number} of {_HOOK_INPUT} cannot be parsed; expected "
                "'<local ref> <local object name> <remote ref> <remote object name>'"
            )
        sent, present = (
            None if set(name) == {"0"} else name for name in (parts[1], parts[3])
        )
        refs.append(PushedRef(number, parts[2], sent, present))
    return refs


class _Git:
    """The first way of calling git that answers for this checkout."""

    def __init__(self, root: Path) -> None:
        self.root = root
        commands = git_commands(root)
        for command in commands:
            if _answer([*command, "rev-parse", "--git-dir"], root) is not None:
                self.command = command
                break
        else:
            raise CannotCheckError(
                f"git cannot be asked about this checkout ({len(commands)} way(s) "
                "tried). Install git where this script runs and make sure it is "
                "on PATH"
            )
        # The objects that are pushed are the real ones, not their replacements.
        self.environment = {**_environment(), "GIT_NO_REPLACE_OBJECTS": "1"}
        # ``user.email`` of this checkout, asked for once; see ``_configured_address``.
        self.address: str | None = None

    def output(self, *arguments: str) -> bytes:
        """Return what a git command prints; its failure is a failure of the guard.

        What git writes to standard error is dropped, as in ``_answer``.
        """
        try:
            return subprocess.run(  # noqa: S603 - object names are checked, program from PATH
                [*self.command, *arguments],
                cwd=self.root,
                env=self.environment,
                check=True,
                capture_output=True,
                timeout=_GIT_TIMEOUT_SECONDS,
            ).stdout
        except (OSError, subprocess.SubprocessError) as error:
            raise CannotCheckError(
                f"'git {arguments[0]}' failed ({type(error).__name__}), so the "
                "commits of this push cannot be read"
            ) from error


class _Objects:
    """One running ``git cat-file --batch`` that hands out objects by name."""

    def __init__(self, git: _Git) -> None:
        self._git = git
        self._process: subprocess.Popen[bytes] | None = None

    def __enter__(self) -> _Objects:
        try:
            self._process = subprocess.Popen(  # noqa: S603 - fixed arguments, program from PATH
                [*self._git.command, "cat-file", "--batch"],
                cwd=self._git.root,
                env=self._git.environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as error:
            raise CannotCheckError(
                f"'git cat-file' cannot be started ({type(error).__name__})"
            ) from error
        return self

    def __exit__(self, *_details: object) -> None:
        process = self._process
        if process is None:
            return
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                # The answers are all read by now; nothing depends on this.
                with contextlib.suppress(OSError):
                    stream.close()
        try:
            process.wait(timeout=_GIT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()

    def read(self, name: str) -> tuple[str, bytes] | None:
        """Return kind and content of an object, or ``None`` if git has it not."""
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise CannotCheckError("'git cat-file' is not running")
        try:
            process.stdin.write(name.encode("ascii") + b"\n")
            process.stdin.flush()
            header = process.stdout.readline().split()
            if header[1:] == [b"missing"]:
                return None
            _, kind, size = header
            content = process.stdout.read(int(size))
            if len(content) != int(size) or process.stdout.read(1) != b"\n":
                raise CannotCheckError("'git cat-file' answered with a short object")
        except (OSError, ValueError) as error:
            raise CannotCheckError(
                f"'git cat-file' gave no usable answer ({type(error).__name__})"
            ) from error
        return kind.decode("ascii", "replace"), content

    def blob(self, name: str, shown: str) -> bytes:
        """Return the content of a file or of a link as git stores it."""
        found = self.read(name)
        if found is None or found[0] != "blob":
            raise CannotCheckError(f"the content of {shown} is not known to git here")
        return found[1]


def _split_object(content: bytes, shown: str) -> tuple[list[tuple[str, str]], str]:
    """Return the header lines and the message of a commit or tag object."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise CannotCheckError(
            f"{shown} is not UTF-8 text, so its message cannot be judged"
        ) from error
    head, _, message = text.partition("\n\n")
    headers: list[tuple[str, str]] = []
    for line in head.split("\n"):
        if line.startswith(" ") and headers:
            key, value = headers[-1]
            headers[-1] = (key, f"{value}\n{line}")
        else:
            key, _, value = line.partition(" ")
            headers.append((key, value))
    return headers, message


def _judge_object_text(
    headers: list[tuple[str, str]], message: str, place: str, report: PushedReport
) -> None:
    """Judge the message of a commit or tag, and every header that carries text."""
    report.messages += 1
    report.findings += check_text(message, f"{place}: message")
    for key, value in headers:
        if key not in _UNJUDGED_HEADERS:
            report.findings += [
                PlaceFinding(f"{place}: an additional header line", kind)
                for kind in dict.fromkeys(_kinds(f"{key} {value}".replace("\n", " ")))
            ]


def _commit_behind(objects: _Objects, ref: PushedRef, report: PushedReport) -> str:
    """Return the commit a local object leads to; judge tag objects on the way."""
    name = ref.local_object
    where = f"line {ref.line} of {_HOOK_INPUT}"
    for _ in range(_MAXIMUM_TAG_DEPTH):
        found = None if name is None else objects.read(name)
        if name is None or found is None:
            raise CannotCheckError(f"the local object of {where} is not known to git")
        kind, content = found
        if kind == "commit":
            return name
        if kind != "tag":
            raise CannotCheckError(
                f"{where} pushes a {kind}, not a commit, which this guard cannot judge"
            )
        headers, message = _split_object(content, f"the tag object of {where}")
        _judge_object_text(headers, message, f"{where}: tag object", report)
        name = dict(headers).get("object")
        if name is not None and _OBJECT_NAME.fullmatch(name) is None:
            name = None
    raise CannotCheckError(f"the tags of {where} are nested too deeply")


@dataclass(frozen=True)
class _Entry:
    """One entry of a commit that differs from the first parent, as git tells it."""

    old_mode: str
    new_mode: str
    old_object: str
    new_object: str
    status: str
    path: str


def _changed_entries(
    git: _Git, name: str, parents: list[str]
) -> tuple[str, list[_Entry]]:
    """Return how to list them by hand, and the entries that differ from the parent."""
    short = name[:_ABBREVIATED]
    if parents:
        ends = [parents[0], name]
        by_hand = f"{parents[0][:_ABBREVIATED]} {short}"
    else:
        ends = ["--root", "--no-commit-id", name]
        by_hand = f"--root --no-commit-id {short}"
    raw = git.output("diff-tree", "-r", "-z", "--no-renames", "--no-abbrev", *ends)
    fields = raw.split(b"\0")
    if fields.pop() or len(fields) % 2:
        raise CannotCheckError(f"git listed the entries of commit {short} unreadably")
    entries = []
    for described, path in itertools.batched(fields, 2, strict=True):
        match = _RAW_ENTRY.fullmatch(described.decode("ascii", "replace"))
        if match is None:
            raise CannotCheckError(
                f"git described an entry of commit {short} in a way this guard "
                "does not know"
            )
        old_mode, new_mode, old_object, new_object, status = match.groups()
        try:
            entries.append(
                _Entry(
                    old_mode,
                    new_mode,
                    old_object,
                    new_object,
                    status,
                    path.decode("utf-8"),
                )
            )
        except UnicodeDecodeError as error:
            raise CannotCheckError(
                f"a path text of commit {short} is not UTF-8, so it cannot be judged"
            ) from error
    return f"git diff-tree -r --no-renames --name-only {by_hand}", entries


def _configured_address(git: _Git) -> str:
    """Return ``user.email`` as git resolves it for this checkout; never written."""
    if git.address is None:
        try:
            answer = git.output("config", "--get", "user.email")
            address = answer.decode("utf-8").strip().casefold()
        except (CannotCheckError, UnicodeDecodeError) as error:
            address = ""
            cause: Exception | None = error
        else:
            cause = None
        if not address:
            raise CannotCheckError(
                "git names no 'user.email' for this checkout, so the identity of "
                "the pushed commits cannot be compared with it. A human configures "
                "the identity of the clone; agents never change git configuration"
            ) from cause
        git.address = address
    return git.address


def _judge_identity(
    git: _Git, headers: list[tuple[str, str]], short: str, report: PushedReport
) -> None:
    """Compare the addresses of author and committer with the one of this clone.

    Not a content rule: which address is right is the business of whoever owns
    the clone. What is caught is a commit made in another environment, with an
    identity that was never meant for this repository. Upper and lower case
    are not told apart, as mail systems do not tell them apart in practice.
    """
    expected = _configured_address(git)
    for role in ("author", "committer"):
        lines = [value for key, value in headers if key == role]
        match = _IDENTITY_ADDRESS.fullmatch(lines[0]) if len(lines) == 1 else None
        if match is None:
            raise CannotCheckError(f"commit {short} names its {role} unreadably")
        if match[1].strip().casefold() != expected:
            report.findings.append(IdentityFinding(short, role))
    report.identities += 1


def _judge_commit(
    git: _Git, objects: _Objects, name: str, report: PushedReport
) -> None:
    """Judge message, path texts and added lines of one commit."""
    short = name[:_ABBREVIATED]
    found = objects.read(name)
    if found is None or found[0] != "commit":
        raise CannotCheckError(f"commit {short} is not known to git here")
    headers, message = _split_object(found[1], f"commit {short}")
    parents = [value for key, value in headers if key == "parent"]
    if any(_OBJECT_NAME.fullmatch(parent) is None for parent in parents):
        raise CannotCheckError(f"commit {short} names a parent unreadably")
    report.commits += 1
    _judge_object_text(headers, message, f"commit {short}", report)
    _judge_identity(git, headers, short, report)
    by_hand, entries = _changed_entries(git, name, parents)
    for position, entry in enumerate(entries, start=1):
        if entry.status == "D":
            continue
        report.names += 1
        label = f"entry {position} of its changed entries"
        kinds = name_kinds(entry.path)
        report.findings += [
            PlaceFinding(
                f"commit {short}: {label}: its name, which is not printed here "
                f"(line {position} of the output of '{by_hand}')",
                kind,
            )
            for kind in kinds
        ]
        # Never a path that looks private, not in a finding about its content either.
        shown = f"commit {short}: {label if kinds else entry.path}"
        _judge_content(objects, entry, shown, report)


def _judge_content(
    objects: _Objects, entry: _Entry, shown: str, report: PushedReport
) -> None:
    """Sort the new content of an entry into its group; judge its added lines."""
    if entry.new_mode == _MODE_NESTED:
        report.nested += 1
        return
    if entry.new_mode != _MODE_LINK and entry.path in SKIPPED_FILES:
        report.generated += 1
        return
    text = _decoded(objects.blob(entry.new_object, shown), shown)
    if text is None:
        report.binary += 1
        return
    known: set[str] = set()
    if entry.old_mode not in (_MODE_NONE, _MODE_NESTED):
        try:
            old = objects.blob(entry.old_object, shown).decode("utf-8")
            known = set(old.splitlines())
        except UnicodeDecodeError:
            # Nothing of an old content that is not text counts as known.
            known = set()
    report.files += 1
    for number, line in enumerate(text.splitlines(), start=1):
        if line not in known:
            report.lines += 1
            report.findings += [Finding(shown, number, kind) for kind in _kinds(line)]


def check_pushed(
    root: Path, data: bytes, remote_name: str, remote_url: str
) -> PushedReport:
    """Judge every commit that the push described by ``data`` would send."""
    refs = parse_pushed(data)
    report = PushedReport()
    if not refs:
        return report
    if not remote_name or _GLOB_CHARACTERS & set(remote_name):
        raise CannotCheckError("the name of the remote is not one git would accept")
    # A remote without a name has no remote-tracking refs of its own.
    known = "--remotes" if remote_name == remote_url else f"--remotes={remote_name}"
    git = _Git(root)
    judged: set[str] = set()
    with _Objects(git) as objects:
        for ref in refs:
            if ref.local_object is None:
                report.deletions += 1
                continue
            report.refs += 1
            where = f"line {ref.line} of {_HOOK_INPUT}"
            report.findings += [
                PlaceFinding(f"{where}: the name of the remote ref", kind)
                for kind in name_kinds(ref.remote_ref)
            ]
            commit = _commit_behind(objects, ref, report)
            exclude = [known]
            if ref.remote_object is not None:
                if objects.read(ref.remote_object) is None:
                    raise CannotCheckError(
                        f"the object that {where} names as the present state of "
                        "the remote ref is not known locally, so the new commits "
                        "cannot be told from the old ones; fetch first "
                        "('git fetch'), then push again"
                    )
                exclude.append(ref.remote_object)
            listed = git.output("rev-list", "--reverse", commit, "--not", *exclude)
            for name in listed.decode("ascii", "replace").split():
                if _OBJECT_NAME.fullmatch(name) is None:
                    raise CannotCheckError(
                        f"git listed the commits of {where} unreadably"
                    )
                if name not in judged:
                    judged.add(name)
                    _judge_commit(git, objects, name, report)
    return report


def _hook_input() -> bytes:
    """Return what git wrote to the hook; an empty input must come from a pipe."""
    stream = sys.stdin.buffer
    data = stream.read()
    if data:
        return data
    try:
        mode = os.fstat(stream.fileno()).st_mode
    except (OSError, ValueError) as error:
        raise CannotCheckError(
            f"standard input cannot be examined ({type(error).__name__})"
        ) from error
    if not (stat.S_ISFIFO(mode) or stat.S_ISREG(mode)):
        raise CannotCheckError(
            "standard input is empty and is not a pipe, so this run was not "
            "started by git for a push. Git hands the refs to the hook on "
            "standard input; without them nothing can be judged"
        )
    return data


def main_pushed(remote_name: str, remote_url: str) -> int:
    """Run the guard on what a push would send; called by the pre-push hook."""
    label = "instance data, pushed commits"
    try:
        report = check_pushed(REPOSITORY_ROOT, _hook_input(), remote_name, remote_url)
    except CannotCheckError as error:
        sys.stdout.write(f"{label}: CANNOT CHECK, so this is a failure: {error}\n")
        return EXIT_CANNOT_CHECK
    for finding in report.findings:
        sys.stdout.write(f"{finding}\n")
    if any(isinstance(finding, IdentityFinding) for finding in report.findings):
        sys.stdout.write(
            "A commit with another address was made in another environment (inside "
            "WSL, on another computer), or it is the work of somebody else. Do not "
            "change the configured identity to get past this. Make your own commit "
            "again in this clone, on a new branch if the old one was never pushed "
            "(docs/dev/contributing.md says how); commits of somebody else are "
            "pushed by the project owner, or reach a branch by merging what is "
            "already on the remote.\n"
        )
    if report.findings:
        sys.stdout.write(
            f"{label}: {len(report.findings)} suspicious place(s); {report.summary()}\n"
        )
        return EXIT_FINDINGS
    sys.stdout.write(f"{label}: ok; {report.summary()}\n")
    return 0


def main(arguments: Sequence[str] = ()) -> int:
    """Run the guard: on this checkout, or with ``--pushed`` on what a push sends."""
    if len(arguments) == 3 and arguments[0] == PUSHED_OPTION:  # noqa: PLR2004 - option, name, URL
        return main_pushed(arguments[1], arguments[2])
    if arguments:
        sys.stdout.write(
            "instance data: CANNOT CHECK, so this is a failure: unknown arguments; "
            f"use none, or '{PUSHED_OPTION} <name of the remote> <URL of the remote>'\n"
        )
        return EXIT_CANNOT_CHECK
    try:
        report = check_checkout(REPOSITORY_ROOT)
    except CannotCheckError as error:
        sys.stdout.write(
            f"instance data: CANNOT CHECK, so this is a failure: {error}\n"
        )
        return EXIT_CANNOT_CHECK
    for finding in (*report.name_findings, *report.findings):
        sys.stdout.write(f"{finding}\n")
    if report.findings or report.name_findings:
        sys.stdout.write(
            f"instance data: {len(report.findings)} suspicious line(s) and "
            f"{len(report.name_findings)} suspicious name(s); {report.summary()}\n"
        )
        return EXIT_FINDINGS
    sys.stdout.write(f"instance data: ok; {report.summary()}\n")
    return 0


def run(entry: Callable[[], int]) -> int:
    """Run ``entry``; an error nobody foresaw is a failure too, never a pass.

    Only the type of the error is printed. Its text and a traceback may name
    local paths, and the output of this script may be pasted in public.
    """
    try:
        return entry()
    except Exception as error:  # noqa: BLE001 - the net for every unforeseen error
        sys.stdout.write(
            "instance data: CANNOT CHECK, so this is a failure: internal error in "
            f"check_instance_data.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(lambda: main(sys.argv[1:])))
