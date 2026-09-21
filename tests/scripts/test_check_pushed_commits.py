"""The instance data guard judges every commit that a push would send.

The checkout shows only the end state. These tests build small histories in
throw-away repositories and hand the guard the lines git would write to a
pre-push hook. ``tests/scripts/test_pre_push_hook.py`` proves the same from end
to end, with a real ``git push``.

This file is tracked and therefore scanned by the guard itself. Every value
that must be found is made up and put together at runtime.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import check_instance_data
from scripts.check_instance_data import (
    EXIT_CANNOT_CHECK,
    EXIT_FINDINGS,
    SUPPORTED_MODES,
    CannotCheckError,
    IdentityFinding,
    PushedReport,
    check_pushed,
    main,
    parse_pushed,
)
from tests.scripts.throwaway_repository import (
    ADDRESS,
    MAIN,
    OTHER_ADDRESS,
    ZEROS,
    Repository,
    hook_line,
)

PRIVATE_VALUE = ".".join(["192", "168", "9", "9"])
OTHER_PRIVATE_VALUE = "/home" + "/someone/checkout"
REMOTE = "origin"
URL = "https://example.com/example.git"
TRACKED_MAIN = f"refs/remotes/{REMOTE}/main"
GUARD = Path(check_instance_data.__file__)


@pytest.fixture
def repository(tmp_path: Path) -> Repository:
    """Return a repository with one clean commit that the remote already has."""
    repository = Repository.create(tmp_path / "checkout")
    repository.write("notes.md", "harmless\n")
    base = repository.commit()
    repository.git("update-ref", TRACKED_MAIN, base)
    return repository


def _judge(repository: Repository, *lines: str, name: str = REMOTE) -> PushedReport:
    return check_pushed(repository.root, "".join(lines).encode(), name, URL)


def _shown(report: PushedReport) -> str:
    return "\n".join(str(finding) for finding in report.findings)


def _base(repository: Repository) -> str:
    base = repository.tip(TRACKED_MAIN)
    assert base is not None
    return base


def test_value_that_the_next_commit_removes_is_found(repository: Repository) -> None:
    """The combined difference of the two commits is clean; the first commit is not."""
    repository.write("notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    mistake = repository.commit("Add a host")
    repository.write("notes.md", "harmless\nhost: example\n")
    corrected = repository.commit("Use a neutral host")

    report = _judge(repository, hook_line(corrected, _base(repository)))

    assert _shown(report) == (
        f"commit {mistake[:10]}: notes.md:2: looks like: private IPv4 address"
    )
    assert report.commits == 2  # noqa: PLR2004 - the mistake and its correction
    assert PRIVATE_VALUE not in _shown(report)


def test_value_in_a_commit_message_only_is_found(repository: Repository) -> None:
    """Subject, body and trailers are published with the commit."""
    repository.write("notes.md", "harmless\nmore\n")
    commit = repository.commit(f"Add more\n\nSeen on {PRIVATE_VALUE}\n\nRef: none")

    report = _judge(repository, hook_line(commit, _base(repository)))

    assert _shown(report) == (
        f"commit {commit[:10]}: message:3: looks like: private IPv4 address"
    )
    assert PRIVATE_VALUE not in _shown(report)


def test_session_link_in_a_commit_message_is_found(repository: Repository) -> None:
    """Some tools append a link to their session; the usual attribution passes."""
    attribution = (
        "\N{ROBOT FACE} Generated with [Claude Code](https://claude.com/claude-code)\n\n"
        "Co-Authored-By: Claude Fable 5.1 <noreply" + "@" + "anthropic.com>"
    )
    session = "https://claude" + ".ai/code/" + "session_0123ABCdef"
    repository.write("notes.md", "harmless\nmore\n")
    usual = repository.commit(f"Add more\n\n{attribution}")
    repository.write("notes.md", "harmless\nmore\nand more\n")
    linked = repository.commit(f"Add even more\n\n{session}\n\n{attribution}")

    report = _judge(repository, hook_line(linked, _base(repository)))

    assert _shown(report) == (
        f"commit {linked[:10]}: message:3: looks like: "
        "link to a session of an assistant tool"
    )
    assert usual[:10] not in _shown(report)
    assert session not in _shown(report)


def test_additional_header_of_a_commit_is_judged(repository: Repository) -> None:
    """Whatever else a commit object carries as text is published too."""
    repository.write("notes.md", "harmless\nmore\n")
    commit = repository.commit(headers=f"note seen on {PRIVATE_VALUE}\n continued\n")

    report = _judge(repository, hook_line(commit, _base(repository)))

    assert _shown(report) == (
        f"commit {commit[:10]}: an additional header line: looks like: "
        "private IPv4 address"
    )


def _repository_of(tmp_path: Path, address: str | None) -> tuple[Repository, str]:
    """Return a repository with that ``user.email`` and the commit the remote has."""
    repository = Repository.create(tmp_path / "other-checkout", address=address)
    repository.write("notes.md", "harmless\n")
    base = repository.commit()
    repository.git("update-ref", TRACKED_MAIN, base)
    repository.write("notes.md", "harmless\nmore\n")
    return repository, base


def test_identity_lines_are_compared_not_judged_by_content(tmp_path: Path) -> None:
    """An address that the content rules would flag passes as the configured one.

    Upper and lower case are not told apart.
    """
    real_looking = "someone" + "@" + "provider.test"
    repository, base = _repository_of(tmp_path, real_looking)
    shouting = real_looking.upper()
    commit = repository.commit(addresses=(real_looking, shouting))

    report = _judge(repository, hook_line(commit, base))

    assert real_looking in repository.git("cat-file", "commit", commit)
    assert report.findings == []
    assert report.identities == 1


@pytest.mark.parametrize(
    ("addresses", "roles"),
    [
        ((OTHER_ADDRESS, ADDRESS), ["author"]),
        ((ADDRESS, OTHER_ADDRESS), ["committer"]),
        ((OTHER_ADDRESS, OTHER_ADDRESS), ["author", "committer"]),
    ],
)
def test_commit_with_another_identity_is_found_without_any_address(
    repository: Repository, addresses: tuple[str, str], roles: list[str]
) -> None:
    """A commit from another environment, or one of somebody else, pushed onward."""
    repository.write("notes.md", "harmless\nmore\n")
    foreign = repository.commit(addresses=addresses)
    repository.write("notes.md", "harmless\nmore\nand more\n")
    own = repository.commit()

    report = _judge(repository, hook_line(own, _base(repository)))

    assert [
        (finding.subject, finding.role)
        for finding in report.findings
        if isinstance(finding, IdentityFinding)
    ] == [(f"commit {foreign[:10]}", role) for role in roles]
    assert len(report.findings) == len(roles)
    assert all(
        f"commit {foreign[:10]}: " in line for line in _shown(report).splitlines()
    )
    assert ADDRESS not in _shown(report)
    assert OTHER_ADDRESS not in _shown(report)
    assert report.identities == 2  # noqa: PLR2004 - both commits were compared
    assert report.tracking_refs is True


def test_tagger_of_a_pushed_tag_is_compared_too(repository: Repository) -> None:
    """A tag made in another environment publishes that address like a commit."""
    base = _base(repository)
    own = repository.tag("own", base, "harmless")
    foreign = repository.tag("foreign", base, "harmless", tagger=OTHER_ADDRESS)

    report = _judge(
        repository,
        hook_line(own, ZEROS, "refs/tags/own"),
        hook_line(foreign, ZEROS, "refs/tags/foreign"),
    )

    assert [
        (finding.subject, finding.role)
        for finding in report.findings
        if isinstance(finding, IdentityFinding)
    ] == [("line 2 of what git handed to the hook: tag object", "tagger")]
    assert len(report.findings) == 1
    assert OTHER_ADDRESS not in _shown(report)
    assert report.identities == 2  # noqa: PLR2004 - both tag objects were compared


def test_refusal_says_to_fetch_when_no_remote_tracking_ref_exists(
    repository: Repository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A clone without them compares what came from the server, and says so.

    A squash made on the server has the address of the server as committer.
    With the remote-tracking ref it is outside the range; without any, it is
    compared, and the explanation names the fetch as the way out.
    """
    repository.write("notes.md", "harmless\nmore\n")
    squashed = repository.commit(addresses=(ADDRESS, OTHER_ADDRESS))
    repository.write("notes.md", "harmless\nmore\nand more\n")
    own = repository.commit()
    line = hook_line(own, ZEROS, "refs/heads/topic").encode()
    specific = "has no remote-tracking ref of this remote"

    repository.git("update-ref", "-d", TRACKED_MAIN)
    status, output = _run_main(repository, line, monkeypatch, capsys)

    assert status == EXIT_FINDINGS
    assert f"commit {squashed[:10]}: " in output
    assert specific in output
    assert "git fetch <remote>" in output
    assert OTHER_ADDRESS not in output

    repository.git("update-ref", TRACKED_MAIN, _first(repository))
    status, output = _run_main(repository, line, monkeypatch, capsys)

    assert status == EXIT_FINDINGS
    assert specific not in output
    assert "git fetch <remote>" in output

    repository.git("update-ref", TRACKED_MAIN, squashed)
    status, output = _run_main(repository, line, monkeypatch, capsys)

    assert status == 0, output
    assert "git fetch" not in output


def _first(repository: Repository) -> str:
    return repository.git("rev-list", "--max-parents=0", MAIN)


def test_nested_checkout_is_listed_whatever_its_settings_say(
    repository: Repository,
) -> None:
    """``ignore = all`` in ``.gitmodules`` hides an entry from a plain listing."""
    name = f"module-{PRIVATE_VALUE}"
    repository.write(
        ".gitmodules",
        '[submodule "example"]\n\tpath = module\n\turl = https://example.com/m.git\n'
        "\tignore = all\n",
    )
    settings = repository.root / ".git" / "config"
    with settings.open("a", encoding="utf-8", newline="\n") as file:
        file.write("[diff]\n\tignoreSubmodules = all\n")
    repository.git("update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},module")
    repository.git("update-index", "--add", "--cacheinfo", f"160000,{'2' * 40},{name}")
    added = repository.commit()
    repository.git("update-index", "--add", "--cacheinfo", f"160000,{'3' * 40},module")
    repository.git("update-index", "--add", "--cacheinfo", f"160000,{'4' * 40},{name}")
    moved = repository.commit()

    report = _judge(repository, hook_line(moved, _base(repository)))

    # The settings file and two entries, then the two entries once more.
    assert (report.commits, report.nested, report.names) == (2, 4, 5)
    assert [str(finding).split(":")[0] for finding in report.findings] == [
        f"commit {added[:10]}",
        f"commit {moved[:10]}",
    ]
    assert PRIVATE_VALUE not in _shown(report)


def test_path_text_outside_ascii_is_judged_as_it_is(tmp_path: Path) -> None:
    """With ``core.quotePath`` git prints such a path in quotes and as octal codes.

    The setting is written into the configuration file of the throw-away
    repository, both ways; the listing must not depend on it.
    """
    for number, setting in enumerate(("true", "false")):
        repository = Repository.create(tmp_path / f"checkout-{number}")
        settings = repository.root / ".git" / "config"
        with settings.open("a", encoding="utf-8", newline="\n") as file:
            file.write(f"[core]\n\tquotePath = {setting}\n")
        clean = "docs/\N{LATIN SMALL LETTER U WITH DIAERESIS}bersicht \N{SNOWMAN}.md"
        private = f"docs/\N{LATIN SMALL LETTER U WITH DIAERESIS}ber-{PRIVATE_VALUE}.md"
        repository.write(clean, f"host: {PRIVATE_VALUE}\n")
        repository.write(private, "harmless\n")
        commit = repository.commit()

        report = _judge(repository, hook_line(commit, ZEROS))

        shown = _shown(report).splitlines()
        assert len(shown) == 2, shown  # noqa: PLR2004 - one line, one path text
        assert f"commit {commit[:10]}: {clean}:1: looks like: " in "".join(shown)
        assert "its name, which is not printed here" in "".join(shown)
        assert PRIVATE_VALUE not in "".join(shown)


def test_identity_of_what_the_remote_has_is_not_compared(
    repository: Repository,
) -> None:
    """A merge or squash made on the server has the server's address as committer.

    It reaches a branch by merging the remote main line and stays outside the
    range, so only the merge commit itself is compared.
    """
    base = _base(repository)
    repository.write("topic.md", "harmless\n")
    topic = repository.commit(ref="refs/heads/topic", parents=[base])
    repository.write("main.md", "harmless\n")
    squashed = repository.commit(ref=TRACKED_MAIN, addresses=(ADDRESS, OTHER_ADDRESS))
    merge = repository.commit(ref="refs/heads/topic", parents=[topic, squashed])

    report = _judge(repository, hook_line(merge, ZEROS, "refs/heads/topic"))

    assert report.findings == []
    assert (report.commits, report.identities) == (2, 2)


def test_without_a_configured_address_nothing_can_be_compared(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No identity in the clone, none of the user: a failure, never a pass.

    The folders in which git looks for the configuration of the user are
    pointed at an empty one for this test, through the environment of this
    process only.
    """
    empty = tmp_path / "no-settings"
    empty.mkdir()
    for variable in ("HOME", "USERPROFILE", "XDG_CONFIG_HOME"):
        monkeypatch.setenv(variable, str(empty))
    repository, base = _repository_of(tmp_path, None)
    commit = repository.commit()

    with pytest.raises(CannotCheckError, match=r"git names no 'user\.email'"):
        _judge(repository, hook_line(commit, base))


def test_identity_line_that_cannot_be_read_cannot_be_checked(
    repository: Repository,
) -> None:
    """An author line without an address in angle brackets is not skipped."""
    tree = repository.git("write-tree")
    content = (
        f"tree {tree}\nauthor Example 0 +0000\n"
        f"committer Example <{ADDRESS}> 0 +0000\n\nharmless\n"
    )
    repository.git("update-ref", "refs/heads/topic", _base(repository))
    unreadable = repository.git(
        "hash-object",
        "-t",
        "commit",
        "-w",
        "--stdin",
        "--literally",
        data=content.encode(),
    )

    with pytest.raises(CannotCheckError, match="names its author unreadably"):
        _judge(repository, hook_line(unreadable, ZEROS, "refs/heads/topic"))


def test_value_in_a_path_text_only_is_found_without_naming_it(
    repository: Repository,
) -> None:
    """A file that was added under a private-looking name and renamed afterwards."""
    private_path = f"hosts/{PRIVATE_VALUE}.md"
    repository.write(private_path, f"harmless\nhome: {OTHER_PRIVATE_VALUE}\n")
    mistake = repository.commit("Add a host file")
    repository.remove(private_path)
    repository.write("hosts/example.md", "harmless\n")
    renamed = repository.commit("Rename the host file")

    report = _judge(repository, hook_line(renamed, _base(repository)))

    shown = _shown(report)
    short = mistake[:10]
    assert [str(finding).rsplit(": ", 1)[-1] for finding in report.findings] == [
        "private IPv4 address",
        "path inside a user's home directory",
    ]
    assert f"commit {short}: entry 1 of its changed entries: its name" in shown
    assert "line 1 of the output of 'git diff-tree " in shown
    assert f" --name-only {_base(repository)[:10]} {short}'" in shown
    # The finding in the content of that file does not give the name away either.
    assert f"commit {short}: entry 1 of its changed entries:2: looks like: " in shown
    assert PRIVATE_VALUE not in shown
    assert OTHER_PRIVATE_VALUE not in shown
    assert "hosts/" not in shown
    # The new path of the rename and the old one: only the new one is judged.
    assert report.names == 2  # noqa: PLR2004 - see the comment above


def test_new_branch_judges_only_what_the_remote_does_not_have(
    repository: Repository,
) -> None:
    """Without a remote object the remote-tracking refs of the remote are the limit."""
    repository.write("notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    mistake = repository.commit(ref="refs/heads/topic", parents=[_base(repository)])
    repository.write("notes.md", "harmless\n")
    tip = repository.commit(ref="refs/heads/topic")

    report = _judge(repository, hook_line(tip, ZEROS, "refs/heads/topic"))

    assert report.commits == 2  # noqa: PLR2004 - the mistake and its correction
    assert [str(f).split(":")[0] for f in report.findings] == [f"commit {mistake[:10]}"]


def test_existing_branch_with_one_clean_commit_passes(repository: Repository) -> None:
    """One commit is judged, and the summary says so."""
    repository.write("notes.md", "harmless\nmore\n")
    commit = repository.commit("Add more")

    report = _judge(repository, hook_line(commit, _base(repository)))

    assert report.findings == []
    assert (report.commits, report.refs, report.names, report.files) == (1, 1, 1, 1)
    assert report.lines == 1
    assert report.summary().startswith("judged 1 commit(s) that 1 ref(s) would send: ")


def test_deletion_of_a_remote_ref_sends_nothing(repository: Repository) -> None:
    """The local object name of a deletion consists of zeros."""
    line = hook_line(ZEROS, _base(repository), "refs/heads/gone", "(delete)")

    report = _judge(repository, line)

    assert report.findings == []
    assert (report.commits, report.refs, report.deletions) == (0, 0, 1)
    assert "1 deletion(s) of a remote ref" in report.summary()


def test_one_bad_ref_among_several_is_found(repository: Repository) -> None:
    """Every line is judged, and a commit that several refs reach only once."""
    base = _base(repository)
    repository.write("notes.md", "harmless\nmore\n")
    clean = repository.commit()
    repository.write("other.md", f"host: {PRIVATE_VALUE}\n")
    bad = repository.commit(ref="refs/heads/topic", parents=[clean])
    repository.remove("other.md")
    fixed = repository.commit(ref="refs/heads/topic")

    report = _judge(
        repository,
        hook_line(clean, base),
        hook_line(fixed, ZEROS, "refs/heads/topic"),
        hook_line(ZEROS, base, "refs/heads/gone", "(delete)"),
    )

    assert _shown(report) == (
        f"commit {bad[:10]}: other.md:1: looks like: private IPv4 address"
    )
    assert (report.commits, report.refs, report.deletions) == (3, 2, 1)


def test_remote_object_that_is_unknown_locally_cannot_be_checked(
    repository: Repository,
) -> None:
    """Somebody else pushed: what is new cannot be told from what is old."""
    repository.write("notes.md", "harmless\nmore\n")
    commit = repository.commit()

    with pytest.raises(CannotCheckError, match="fetch first"):
        _judge(repository, hook_line(commit, "1" * 40))


def test_local_object_that_is_unknown_cannot_be_checked(repository: Repository) -> None:
    """An object name that git cannot resolve here is never skipped."""
    with pytest.raises(CannotCheckError, match="local object of line 1"):
        _judge(repository, hook_line("1" * 40, _base(repository)))


GARBAGE = [
    b"garbage\n",
    b"refs/heads/main refs/heads/main\n",
    f"{MAIN} {'1' * 40} {MAIN}\n".encode(),
    f"{MAIN} {'1' * 39} {MAIN} {ZEROS}\n".encode(),
    f"{MAIN} {'1' * 64} {MAIN} {ZEROS}\n".encode(),
    f"{MAIN} {'g' * 40} {MAIN} {ZEROS}\n".encode(),
    f"{MAIN} {'1' * 40} main {ZEROS}\n".encode(),
    f" {'1' * 40} {MAIN} {ZEROS}\n".encode(),
    f"{MAIN} {'1' * 40} {MAIN} {ZEROS}".encode(),
    f"{MAIN} {'1' * 40} {MAIN} {ZEROS}\r\n".encode(),
    f"{MAIN} {'1' * 40} {MAIN} {ZEROS}\n\n".encode(),
    b"\xff\xfe\n",
]


@pytest.mark.parametrize("data", GARBAGE)
def test_input_that_cannot_be_parsed_is_refused(data: bytes) -> None:
    """Too few fields, a name that is no object name, a cut-off line, no text."""
    with pytest.raises(CannotCheckError) as caught:
        parse_pushed(data)
    assert "1" * 39 not in str(caught.value), "the input is not repeated"


def test_local_ref_may_contain_spaces() -> None:
    """``HEAD@{1 day ago}`` is a local ref; the other three fields never have one."""
    (ref,) = parse_pushed(
        hook_line("1" * 40, ZEROS, local_ref="HEAD@{1 day ago}").encode()
    )

    assert (ref.line, ref.remote_ref, ref.local_object, ref.remote_object) == (
        1,
        MAIN,
        "1" * 40,
        None,
    )


def test_merge_of_the_remote_main_line_does_not_judge_it_again(
    repository: Repository,
) -> None:
    """What the remote has is outside the range, whatever its messages look like."""
    base = _base(repository)
    repository.write("topic.md", "harmless\n")
    topic = repository.commit(ref="refs/heads/topic", parents=[base])
    repository.git("update-ref", f"refs/remotes/{REMOTE}/topic", topic)
    repository.write("main.md", "harmless\n")
    remote_main = repository.commit(f"Seen on {PRIVATE_VALUE}", ref=TRACKED_MAIN)
    # The index holds both files now: the tree of the merge.
    merge = repository.commit(
        "Merge the main line", ref="refs/heads/topic", parents=[topic, remote_main]
    )

    report = _judge(repository, hook_line(merge, topic, "refs/heads/topic"))

    assert report.findings == []
    assert report.commits == 1
    # The merge is compared with its first parent: the file of the main line.
    assert (report.names, report.files) == (1, 1)


def test_merge_of_a_local_branch_judges_the_commits_of_that_branch(
    repository: Repository,
) -> None:
    """The second parent is not on the remote, so its history is sent and judged."""
    base = _base(repository)
    repository.write("side.md", f"host: {PRIVATE_VALUE}\n")
    side_mistake = repository.commit(ref="refs/heads/side", parents=[base])
    repository.write("side.md", "host: example\n")
    side = repository.commit(ref="refs/heads/side")
    merge = repository.commit("Merge the side branch", parents=[base, side])

    report = _judge(repository, hook_line(merge, base))

    assert report.commits == 3  # noqa: PLR2004 - two of the side branch, one merge
    assert [str(f).split(":")[0] for f in report.findings] == [
        f"commit {side_mistake[:10]}"
    ]


def test_root_commit_is_judged_as_a_whole(tmp_path: Path) -> None:
    """A commit without a parent adds everything it contains."""
    repository = Repository.create(tmp_path / "checkout")
    repository.write("notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    root = repository.commit()
    repository.write("notes.md", "harmless\n")
    tip = repository.commit()

    report = _judge(repository, hook_line(tip, ZEROS))

    assert _shown(report) == (
        f"commit {root[:10]}: notes.md:2: looks like: private IPv4 address"
    )
    assert report.commits == 2  # noqa: PLR2004 - the mistake and its correction


def test_only_new_line_texts_of_a_changed_file_are_judged(
    repository: Repository,
) -> None:
    """A line the first parent already has is public or was judged with its commit."""
    repository.write("notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    on_remote = repository.commit()
    repository.git("update-ref", TRACKED_MAIN, on_remote)
    repository.write(
        "notes.md",
        f"first\nhost: {PRIVATE_VALUE}\nharmless\nhome: {OTHER_PRIVATE_VALUE}\n",
    )
    commit = repository.commit()

    report = _judge(repository, hook_line(commit, on_remote))

    assert _shown(report) == (
        f"commit {commit[:10]}: notes.md:4: looks like: "
        "path inside a user's home directory"
    )
    assert report.lines == 2  # noqa: PLR2004 - the first and the last line are new


def test_content_is_sorted_into_the_groups_of_the_checkout_check(
    repository: Repository,
) -> None:
    """Binary and generated content is skipped, its path text is judged."""
    repository.write("icon.png", b"\x89PNG\x00\xff\xfe" + PRIVATE_VALUE.encode())
    repository.write("uv.lock", f"host: {PRIVATE_VALUE}\n")
    blob = repository.git(
        "hash-object", "-w", "--stdin", data=OTHER_PRIVATE_VALUE.encode()
    )
    repository.git("update-index", "--add", "--cacheinfo", f"120000,{blob},shortcut")
    repository.git("update-index", "--add", "--cacheinfo", f"160000,{'1' * 40},module")
    commit = repository.commit()

    report = _judge(repository, hook_line(commit, _base(repository)))

    assert _shown(report) == (
        f"commit {commit[:10]}: shortcut:1: looks like: "
        "path inside a user's home directory"
    )
    assert (report.names, report.files) == (4, 1)
    assert (report.binary, report.generated, report.nested) == (1, 1, 1)


def test_content_that_is_neither_text_nor_binary_cannot_be_checked(
    repository: Repository,
) -> None:
    """Not waved through as binary, exactly as in the checkout."""
    repository.write("legacy.txt", "caf\xe9 and more".encode("latin-1"))
    commit = repository.commit()

    with pytest.raises(CannotCheckError, match="neither UTF-8 text nor binary"):
        _judge(repository, hook_line(commit, _base(repository)))


def test_message_that_is_not_utf8_cannot_be_checked(repository: Repository) -> None:
    """A message that cannot be read cannot be judged."""
    tree = repository.git("write-tree")
    content = (
        f"tree {tree}\nauthor Example <{ADDRESS}> 0 +0000\n"
        f"committer Example <{ADDRESS}> 0 +0000\n\ncaf"
    ).encode() + b"\xe9\n"
    commit = repository.store("commit", content, "refs/heads/topic")

    with pytest.raises(CannotCheckError, match="is not UTF-8 text"):
        _judge(repository, hook_line(commit, ZEROS, "refs/heads/topic"))


def test_tags_are_judged_like_branches(repository: Repository) -> None:
    """A lightweight tag sends commits; an annotated one also its own message."""
    base = _base(repository)
    repository.write("notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    commit = repository.commit(ref="refs/tags/light", parents=[base])
    tag = repository.tag("annotated", base, f"Released from {OTHER_PRIVATE_VALUE}")

    report = _judge(
        repository,
        hook_line(commit, ZEROS, "refs/tags/light"),
        hook_line(tag, ZEROS, "refs/tags/annotated"),
    )

    assert _shown(report).splitlines() == [
        f"commit {commit[:10]}: notes.md:2: looks like: private IPv4 address",
        "line 2 of what git handed to the hook: tag object: message:1: looks like: "
        "path inside a user's home directory",
    ]
    assert (report.commits, report.refs, report.messages) == (1, 2, 2)


def test_ref_that_leads_to_no_commit_cannot_be_checked(repository: Repository) -> None:
    """Git can push a file or a tree to a ref; this guard judges commits."""
    blob = repository.git("hash-object", "-w", "--stdin", data=b"harmless\n")
    tag = repository.tag("to-a-file", blob, "harmless", kind="blob")

    with pytest.raises(CannotCheckError, match="pushes a blob, not a commit"):
        _judge(repository, hook_line(blob, ZEROS, "refs/heads/file"))
    with pytest.raises(CannotCheckError, match="pushes a blob, not a commit"):
        _judge(repository, hook_line(tag, ZEROS, "refs/tags/to-a-file"))


def test_private_looking_name_of_a_remote_ref_is_found_without_naming_it(
    repository: Repository,
) -> None:
    """A branch name is published like a file name."""
    ref = f"refs/heads/host-{PRIVATE_VALUE}"

    report = _judge(repository, hook_line(_base(repository), ZEROS, ref))

    assert _shown(report) == (
        "line 1 of what git handed to the hook: the name of the remote ref: "
        "looks like: private IPv4 address"
    )
    assert report.commits == 0


def test_remote_without_a_name_is_limited_by_all_remote_tracking_refs(
    repository: Repository,
) -> None:
    """A named remote is limited by its own refs only; a bare URL by all of them."""
    repository.write("notes.md", "harmless\nmore\n")
    elsewhere = repository.commit(ref="refs/remotes/elsewhere/main")
    repository.write("notes.md", "harmless\nmore\nand more\n")
    tip = repository.commit(ref="refs/heads/topic", parents=[elsewhere])
    line = hook_line(tip, ZEROS, "refs/heads/topic")

    assert _judge(repository, line, name=REMOTE).commits == 2  # noqa: PLR2004 - both
    assert _judge(repository, line, name=URL).commits == 1
    with pytest.raises(CannotCheckError, match="name of the remote"):
        _judge(repository, line, name="*")


def test_failure_of_git_for_one_commit_cannot_be_checked(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No commit is skipped because git could not show it."""
    repository.write("notes.md", "harmless\nmore\n")
    commit = repository.commit()
    original = check_instance_data._Git.output  # noqa: SLF001 - the seam for a failing git

    def output(git: check_instance_data._Git, *arguments: str) -> bytes:
        if arguments[0] == "diff-tree":
            return original(git, "diff-tree", "--no-such-option")
        return original(git, *arguments)

    monkeypatch.setattr(check_instance_data._Git, "output", output)  # noqa: SLF001

    with pytest.raises(CannotCheckError, match="'git diff-tree' failed"):
        _judge(repository, hook_line(commit, _base(repository)))


def test_no_git_at_all_cannot_be_checked(
    repository: Repository, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a git that answers, nothing was judged."""
    line = hook_line(_base(repository), ZEROS, "refs/heads/topic")
    monkeypatch.setattr("scripts.check_instance_data.shutil.which", lambda _name: None)

    with pytest.raises(CannotCheckError, match="git cannot be asked"):
        _judge(repository, line)


def _run_main(
    repository: Repository,
    data: bytes,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> tuple[int, str]:
    monkeypatch.setattr("scripts.check_instance_data.REPOSITORY_ROOT", repository.root)
    monkeypatch.setattr("scripts.check_instance_data._hook_input", lambda: data)
    status = main(["--pushed", REMOTE, URL])
    return status, capsys.readouterr().out


def test_run_prints_places_and_a_summary_but_never_the_text(
    repository: Repository,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Status 1 with findings, 0 with the number of commits, 2 when it cannot check."""
    base = _base(repository)
    repository.write("notes.md", f"harmless\nhost: {PRIVATE_VALUE}\n")
    mistake = repository.commit()
    repository.write("notes.md", "harmless\nmore\n")
    tip = repository.commit()

    status, output = _run_main(
        repository, hook_line(tip, base).encode(), monkeypatch, capsys
    )

    assert status == EXIT_FINDINGS
    assert PRIVATE_VALUE not in output
    assert f"commit {mistake[:10]}: notes.md:2: looks like: " in output
    assert (
        "instance data, pushed commits: 1 suspicious place(s); judged 2 commit(s)"
        in output
    )
    assert "pushed commits: ok" not in output

    repository.git("update-ref", TRACKED_MAIN, mistake)
    status, output = _run_main(
        repository, hook_line(tip, mistake).encode(), monkeypatch, capsys
    )

    assert status == 0, output
    summary = re.fullmatch(
        r"instance data, pushed commits: ok; judged (\d+) commit\(s\) .*",
        output.strip(),
    )
    assert summary is not None
    assert int(summary[1]) == 1

    status, output = _run_main(repository, b"garbage\n", monkeypatch, capsys)

    assert status == EXIT_CANNOT_CHECK
    assert "instance data, pushed commits: CANNOT CHECK" in output
    assert "pushed commits: ok" not in output


def test_unknown_arguments_are_a_failure(capsys: pytest.CaptureFixture[str]) -> None:
    """A call the guard does not understand never looks like a pass."""
    assert main(["--pushed"]) == EXIT_CANNOT_CHECK
    assert main(["--pushed", REMOTE, URL, "more"]) == EXIT_CANNOT_CHECK
    assert main(["--other"]) == EXIT_CANNOT_CHECK
    assert main(["--supports"]) == EXIT_CANNOT_CHECK
    assert main(["--supports", "something-else"]) == EXIT_CANNOT_CHECK
    assert main(["--supports", "pushed", "more"]) == EXIT_CANNOT_CHECK
    output = capsys.readouterr().out
    assert "instance data: ok" not in output
    assert SUPPORTED_MODES["pushed"] not in output


def test_guard_proves_that_it_knows_the_mode() -> None:
    """The hook compares the whole output, so it is the token and nothing else."""
    answer = subprocess.run(  # noqa: S603 - this interpreter, the guard of this checkout
        [sys.executable, str(GUARD), "--supports", "pushed"],
        check=False,
        capture_output=True,
        stdin=subprocess.DEVNULL,
    )

    assert answer.returncode == 0
    assert answer.stdout == SUPPORTED_MODES["pushed"].encode()
    assert answer.stderr == b""


def _start_guard(data: bytes | None) -> subprocess.CompletedProcess[bytes]:
    """Start the guard like the hook does; ``None`` stands for the null device."""
    command = [sys.executable, str(GUARD), "--pushed", REMOTE, URL]
    if data is None:
        return subprocess.run(  # noqa: S603 - this interpreter, the guard of this checkout
            command, check=False, capture_output=True, stdin=subprocess.DEVNULL
        )
    return subprocess.run(  # noqa: S603 - this interpreter, the guard of this checkout
        command, check=False, capture_output=True, input=data
    )


def test_empty_input_counts_only_if_it_comes_through_a_pipe() -> None:
    """Git always hands the hook a pipe, without a line when nothing is to push.

    An empty input from anything else (the null device, a terminal) means that
    the lines of git did not arrive, and that is never a pass.
    """
    nothing_to_push = _start_guard(b"")
    not_from_git = _start_guard(None)

    assert nothing_to_push.returncode == 0, nothing_to_push.stdout
    assert (
        b"pushed commits: ok; judged 0 commit(s): git named no ref"
        in nothing_to_push.stdout
    )
    assert not_from_git.returncode == EXIT_CANNOT_CHECK
    assert b"CANNOT CHECK" in not_from_git.stdout
    assert b"standard input is empty and is not a pipe" in not_from_git.stdout
