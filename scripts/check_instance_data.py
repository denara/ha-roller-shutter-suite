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
"""

import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
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
    without_extensions = _EXTENSION.sub(" ", listed)
    kinds = [*_kinds(listed), *_kinds(without_extensions)]
    return [NameFinding(entry, kind) for kind in dict.fromkeys(kinds)]


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


def _answer(command: list[str], root: Path) -> list[str] | None:
    """Run a command that prints NUL-separated text; ``None`` if it cannot.

    What the command writes to standard error is dropped on purpose: git names
    local paths there, and the output of this script may be pasted in public.
    """
    environment = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith(_GIT_VARIABLE_PREFIX)
    }
    try:
        result = subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
            command,
            cwd=root,
            env=environment,
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
    if not target or (root / target).exists():
        return None
    return target


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
    """Return the commands that may list the files, in the order to try them.

    Every program is looked up through ``PATH``; see the module documentation
    for the reason behind each entry.
    """
    commands: list[list[str]] = []
    git = shutil.which("git")
    if git is not None:
        safe = [git, "-c", f"safe.directory={root.as_posix()}"]
        commands.append([*safe, *_LIST_ARGUMENTS])
        git_dir = _translated_git_dir(root)
        if git_dir is not None:
            commands.append(
                [
                    *safe,
                    f"--git-dir={git_dir}",
                    f"--work-tree={root.as_posix()}",
                    *_LIST_ARGUMENTS,
                ]
            )
    windows_git = shutil.which("git.exe")
    if windows_git is not None and windows_git != git:
        commands.append([windows_git, *_LIST_ARGUMENTS])
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
    try:
        return content.decode("utf-8")
    except UnicodeDecodeError as error:
        if b"\0" in content:
            return None
        raise CannotCheckError(
            f"{relative} is neither UTF-8 text nor binary, so it cannot be judged; "
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
        if file.is_symlink():
            # First of all: a link is never followed, whatever it points to.
            report.links.append(relative)
            report.checked.append(relative)
            report.findings += check_text(_link_text(file, shown), shown)
        elif relative in SKIPPED_FILES:
            report.generated.append(relative)
        elif file.is_dir():
            report.nested.append(relative)
        elif not file.exists():
            report.absent.append(relative)
        elif not file.is_file():
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


def main() -> int:
    """Run the guard on this repository."""
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
    sys.exit(run(main))
