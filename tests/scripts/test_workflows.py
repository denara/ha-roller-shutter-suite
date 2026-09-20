"""The workflows keep what the repository settings and the reviews rely on.

The branch protection of ``main`` requires four status checks by the name of
their job. GitHub does not complain when such a job is renamed: the check
simply never arrives, or worse, stops being required. The hardening rules of
``docs/dev/contributing.md`` are checked here as well, as far as a line-by-line
look at the files can tell.
"""

import re
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).parents[2]
WORKFLOWS = sorted((REPOSITORY_ROOT / ".github" / "workflows").glob("*.yml"))
REQUIRED_CHECKS = {
    "validate.yml": ["hassfest", "HACS"],
    "test.yml": ["Static checks and guards", "Tests and coverage"],
}
PINNED_ACTION = re.compile(r"uses: [\w./-]+@[0-9a-f]{40} # \S.*")


def _lines(workflow: Path) -> list[str]:
    return workflow.read_text(encoding="utf-8").splitlines()


def test_the_three_workflows_exist() -> None:
    """A deleted workflow would make every test below pass vacuously."""
    assert [workflow.name for workflow in WORKFLOWS] == [
        "newest-home-assistant.yml",
        "test.yml",
        "validate.yml",
    ]


@pytest.mark.parametrize(
    ("workflow", "job_name"),
    [(file, name) for file, names in REQUIRED_CHECKS.items() for name in names],
)
def test_required_status_check_keeps_its_name(workflow: str, job_name: str) -> None:
    """The job names that the branch protection requires are still there."""
    lines = _lines(REPOSITORY_ROOT / ".github" / "workflows" / workflow)

    assert f"    name: {job_name}" in lines


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_workflow_follows_the_hardening_rules(workflow: Path) -> None:
    """Read-only, no dangerous trigger, no secret, pinned actions."""
    lines = _lines(workflow)
    code = [line for line in lines if not line.lstrip().startswith("#")]
    text = "\n".join(code)

    assert "permissions:\n  contents: read\n" in text
    assert text.count("permissions:") == 1, "no job may ask for more"
    assert "pull_request_target" not in text
    assert "workflow_run" not in text
    assert "secrets." not in text
    uses = [line.strip().removeprefix("- ") for line in code if "uses:" in line]
    assert uses
    assert [line for line in uses if not PINNED_ACTION.fullmatch(line)] == []
    assert text.count("actions/checkout@") == text.count("persist-credentials: false")


GUARDS = sorted((REPOSITORY_ROOT / "scripts").glob("check_*.py"))
SWALLOWED_STATUS = re.compile(r"\|\||\bset \+e\b|;\s*true\b|(?<!\|)\|(?!\|)")


def _commands(workflow: Path) -> list[str]:
    """Return the shell lines of a workflow: ``run:`` lines and block content."""
    lines = [line.strip() for line in _lines(workflow)]
    code = [line for line in lines if line and not line.startswith("#")]
    keys = re.compile(r"(- )?[\w-]+:( |$)")
    commands = [
        line.removeprefix("- ").removeprefix("run:").strip()
        for line in code
        if line.removeprefix("- ").startswith("run:") or not keys.match(line)
    ]
    # `run: |` only opens a block; its content follows as lines of its own.
    return [line for line in commands if line not in {"|", ">"}]


def test_every_guard_runs_in_ci_as_a_command_of_its_own() -> None:
    """A guard fails closed only if CI runs it and sees its exit status."""
    commands = _commands(REPOSITORY_ROOT / ".github" / "workflows" / "test.yml")

    assert GUARDS, "the guards are expected under scripts/check_*.py"
    for guard in GUARDS:
        runs = [line for line in commands if f"scripts/{guard.name}" in line]
        assert len(runs) == 1, guard.name
        assert runs[0].startswith("uv run --no-sync python scripts/"), guard.name


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_no_command_swallows_an_exit_status(workflow: Path) -> None:
    """No ``|| true``, no ``set +e``, no pipe that hides the status of a guard."""
    commands = _commands(workflow)

    assert [line for line in commands if SWALLOWED_STATUS.search(line)] == []


def test_only_the_optional_beta_job_may_fail_without_turning_the_run_red() -> None:
    """``continue-on-error`` anywhere else would hide a guard that failed."""
    allowed = {"newest-home-assistant.yml": 1}

    for workflow in WORKFLOWS:
        code = [line for line in _lines(workflow) if not line.lstrip().startswith("#")]
        found = sum("continue-on-error" in line for line in code)
        assert found == allowed.get(workflow.name, 0), workflow.name


@pytest.mark.parametrize(
    "line",
    ["python guard.py || true", "set +e", "python guard.py; true", "guard.py | tee x"],
)
def test_swallowed_exit_status_is_recognized(line: str) -> None:
    """The pattern of the test above sees the usual ways of hiding a failure."""
    assert SWALLOWED_STATUS.search(line)
    assert not SWALLOWED_STATUS.search("uv run --no-sync python scripts/guard.py")
