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
