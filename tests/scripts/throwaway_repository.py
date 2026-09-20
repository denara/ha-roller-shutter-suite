"""Throw-away git repositories for the tests of the guard and of the hook.

No identity is passed to git and no ``git config`` is run: a commit is put
together as an object by hand, with a made-up address from a documentation
domain, and the branch is moved with ``git update-ref``. A remote-tracking ref
is a ref like any other and is set the same way, so no remote has to be
configured either.

The guard compares the addresses of pushed commits with ``user.email`` of the
checkout it judges. A throw-away repository therefore gets that one setting,
written into its own configuration file in the temporary folder when it is
created. The configuration of this repository and of the user is never touched.
"""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

ZEROS = "0" * 40
MAIN = "refs/heads/main"
# Made-up addresses from a documentation domain, put together at runtime.
ADDRESS = "someone" + "@" + "example.com"
OTHER_ADDRESS = "somebody.else" + "@" + "example.org"
_COMMIT = (
    "tree {tree}\n"
    "{parents}"
    "author Example <{author}> 0 +0000\n"
    "committer Example <{committer}> 0 +0000\n"
    "{headers}"
    "\n"
    "{message}\n"
)
_TAG = (
    "object {target}\n"
    "type {kind}\n"
    "tag {name}\n"
    "tagger Example <{tagger}> 0 +0000\n"
    "\n"
    "{message}\n"
)


def environment(path: str | None = None) -> dict[str, str]:
    """Return the environment without the variables that redirect git."""
    result = {
        name: value
        for name, value in os.environ.items()
        if not name.upper().startswith("GIT_")
    }
    if path is not None:
        result["PATH"] = path
    return result


def run_git(root: Path, *arguments: str, data: bytes | None = None) -> str:
    """Run git in ``root`` and return what it printed."""
    git = shutil.which("git")
    assert git is not None, "these tests need git, like the guard itself"
    result = subprocess.run(  # noqa: S603 - fixed arguments, program from PATH
        [git, *arguments],
        cwd=root,
        env=environment(),
        # Bytes, so that Windows does not turn the line ends of an object into CRLF.
        input=data,
        check=True,
        capture_output=True,
    )
    return result.stdout.decode("utf-8").strip()


def hook_line(local: str, remote: str, ref: str = MAIN, local_ref: str = "") -> str:
    """Return one line as git writes it to a pre-push hook."""
    return f"{local_ref or ref} {local} {ref} {remote}\n"


@dataclass
class Repository:
    """A repository in a temporary folder whose commits are written by hand."""

    root: Path

    @classmethod
    def create(
        cls, root: Path, *, bare: bool = False, address: str | None = ADDRESS
    ) -> Repository:
        """Create an empty repository whose ``HEAD`` names the branch ``main``.

        ``address`` becomes ``user.email`` of this repository alone; ``None``
        leaves it without one.
        """
        root.mkdir(parents=True)
        run_git(root, "init", "--quiet", *(["--bare"] if bare else []))
        run_git(root, "symbolic-ref", "HEAD", MAIN)
        if address is not None:
            settings = root / "config" if bare else root / ".git" / "config"
            with settings.open("a", encoding="utf-8", newline="\n") as file:
                file.write(f"[user]\n\temail = {address}\n")
        return cls(root)

    def git(self, *arguments: str, data: bytes | None = None) -> str:
        """Run git in this repository."""
        return run_git(self.root, *arguments, data=data)

    def write(self, relative: str, content: str | bytes) -> None:
        """Write a file and put it into the index."""
        file = self.root / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(content.encode() if isinstance(content, str) else content)
        self.git("add", "--", relative)

    def remove(self, relative: str) -> None:
        """Delete a file and take it out of the index."""
        self.git("rm", "--quiet", "--force", "--", relative)

    def tip(self, ref: str = MAIN) -> str | None:
        """Return the commit a ref names, or ``None`` if there is no such ref."""
        names = self.git("for-each-ref", "--format=%(objectname)", ref)
        return names or None

    def commit(
        self,
        message: str = "Made-up commit of a throw-away repository",
        *,
        ref: str = MAIN,
        parents: list[str] | None = None,
        headers: str = "",
        addresses: tuple[str, str] = (ADDRESS, ADDRESS),
    ) -> str:
        """Turn the index into a commit on ``ref`` and return its object name."""
        if parents is None:
            tip = self.tip(ref)
            parents = [] if tip is None else [tip]
        text = _COMMIT.format(
            tree=self.git("write-tree"),
            parents="".join(f"parent {parent}\n" for parent in parents),
            headers=headers,
            message=message,
            author=addresses[0],
            committer=addresses[1],
        )
        return self.store("commit", text.encode(), ref)

    def tag(
        self,
        name: str,
        target: str,
        message: str,
        kind: str = "commit",
        tagger: str = ADDRESS,
    ) -> str:
        """Write an annotated tag by hand and return the name of the tag object."""
        text = _TAG.format(
            target=target, kind=kind, name=name, message=message, tagger=tagger
        )
        return self.store("tag", text.encode(), f"refs/tags/{name}")

    def store(self, kind: str, content: bytes, ref: str | None = None) -> str:
        """Write an object as it is and let ``ref`` name it."""
        name = self.git("hash-object", "-t", kind, "-w", "--stdin", data=content)
        if ref is not None:
            self.git("update-ref", ref, name)
        return name
