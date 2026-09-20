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


GUARDS = sorted(file.name for file in (REPOSITORY_ROOT / "scripts").glob("check_*.py"))
# The one guard that takes an argument; every other command line is the bare script.
GUARD_ARGUMENTS = {"check_coverage.py": " coverage.json"}
GUARD_WORKFLOW = "test.yml"
# The only job that may fail without turning its run red.
ALLOWED_CONTINUE_ON_ERROR = {"newest-home-assistant.yml": 1}
# The only condition in the workflow of the guards, and the step it belongs to.
ALLOWED_CONDITION = ("- name: Coverage summary", "if: always()")
TRIGGER_FILTERS = (
    "paths:",
    "paths-ignore:",
    "branches:",
    "branches-ignore:",
    "tags:",
    "tags-ignore:",
)
SWALLOWED_STATUS = re.compile(
    r"\|\|"  # a || b
    r"|(?<!\|)\|(?!\|)"  # a pipe: the status of its left side is lost
    r"|\bset\b[^\n]*\s\+[a-z]"  # set +e, set +o errexit, set -o pipefail +e
    r"|\bexit\b"  # ; exit 0
    r"|\btrap\b"
    r"|;\s*(true|:)\s*$"
    r"|^!"  # ! command
)


def _code(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    return [line for line in lines if line and not line.startswith("#")]


def _commands(text: str) -> list[str]:
    """Return the shell lines of a workflow: ``run:`` lines and block content."""
    keys = re.compile(r"(- )?[\w-]+:( |$)")
    commands = [
        line.removeprefix("- ").removeprefix("run:").strip()
        for line in _code(text)
        if line.removeprefix("- ").startswith("run:") or not keys.match(line)
    ]
    # `run: |` only opens a block; its content follows as lines of its own.
    return [line for line in commands if line not in {"|", ">"}]


def status_problems(name: str, text: str) -> list[str]:
    """Return every way in which a workflow could hide a failed command."""
    code = _code(text)
    problems = [
        f"hides an exit status: {line}"
        for line in _commands(text)
        if SWALLOWED_STATUS.search(line)
    ]
    # A shell of its own may lack -e, with which a failing line ends the step.
    problems += [f"sets a shell: {line}" for line in code if "shell:" in line]
    tolerated = sum("continue-on-error" in line for line in code)
    if tolerated != ALLOWED_CONTINUE_ON_ERROR.get(name, 0):
        problems.append(f"continue-on-error appears {tolerated} time(s)")
    if name in REQUIRED_CHECKS:
        # A required check that a filter keeps from running looks like a pass.
        problems += [
            f"filters a trigger of a required check: {line}"
            for line in code
            if line.startswith(TRIGGER_FILTERS)
        ]
    if name != GUARD_WORKFLOW:
        return problems
    conditions = [
        (code[position - 1], line)
        for position, line in enumerate(code)
        if line.removeprefix("- ").startswith("if:")
    ]
    if conditions != [ALLOWED_CONDITION]:
        problems.append(f"conditions other than the known one: {conditions}")
    for guard in GUARDS:
        expected = (
            f"uv run --no-sync python scripts/{guard}{GUARD_ARGUMENTS.get(guard, '')}"
        )
        runs = [line for line in _commands(text) if f"scripts/{guard}" in line]
        if runs != [expected]:
            problems.append(f"{guard} must run exactly once and exactly as: {expected}")
    return problems


def test_guards_are_found() -> None:
    """Without this the comparison below would compare nothing."""
    assert "check_instance_data.py" in GUARDS
    assert set(GUARD_ARGUMENTS) <= set(GUARDS)


@pytest.mark.parametrize("workflow", WORKFLOWS, ids=lambda path: path.name)
def test_no_workflow_hides_a_failed_command(workflow: Path) -> None:
    """Every guard runs exactly as documented, and nothing swallows a status."""
    assert status_problems(workflow.name, workflow.read_text(encoding="utf-8")) == []


VERSIONS_GUARD = "run: uv run --no-sync python scripts/check_versions.py"
COVERAGE_GUARD = "uv run --no-sync python scripts/check_coverage.py coverage.json"


@pytest.mark.parametrize(
    ("old", "new"),
    [
        (VERSIONS_GUARD, f"{VERSIONS_GUARD}; exit 0"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD} || true"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD} || echo failed"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD}; true"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD} | tee log"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD} --help"),
        (VERSIONS_GUARD, VERSIONS_GUARD.replace("run: ", "run: ! ")),
        (VERSIONS_GUARD, f"if: false\n        {VERSIONS_GUARD}"),
        (VERSIONS_GUARD, f"if: always()\n        {VERSIONS_GUARD}"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD}\n        shell: bash {{0}}"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD}\n        continue-on-error: true"),
        (VERSIONS_GUARD, "run: echo skipped"),
        (VERSIONS_GUARD, f"{VERSIONS_GUARD}\n        {VERSIONS_GUARD}"),
        (COVERAGE_GUARD, f"set +e\n          {COVERAGE_GUARD}"),
        (COVERAGE_GUARD, f"set +o errexit\n          {COVERAGE_GUARD}"),
        (COVERAGE_GUARD, f"set -o pipefail +e\n          {COVERAGE_GUARD}"),
        (COVERAGE_GUARD, f"set -eu +o errexit\n          {COVERAGE_GUARD}"),
        ("  push:\n", "  push:\n    paths-ignore:\n      - docs/**\n"),
        ("  pull_request:\n", "  pull_request:\n    branches-ignore:\n      - main\n"),
        (COVERAGE_GUARD, f"trap 'exit 0' ERR\n          {COVERAGE_GUARD}"),
        (COVERAGE_GUARD, COVERAGE_GUARD.removesuffix(" coverage.json")),
        ("permissions:\n", "defaults:\n  run:\n    shell: sh\n\npermissions:\n"),
    ],
)
def test_every_known_way_of_hiding_a_failure_is_found(old: str, new: str) -> None:
    """Each change is made to the real workflow of the guards and has to be seen."""
    text = (REPOSITORY_ROOT / ".github" / "workflows" / GUARD_WORKFLOW).read_text(
        encoding="utf-8"
    )
    assert text.count(old) == 1

    assert status_problems(GUARD_WORKFLOW, text.replace(old, new)) != []


def test_trigger_filter_on_the_validators_is_found() -> None:
    """``hassfest`` and ``HACS`` are required checks as well."""
    text = (REPOSITORY_ROOT / ".github" / "workflows" / "validate.yml").read_text(
        encoding="utf-8"
    )
    assert text.count("  push:\n") == 1
    filtered = text.replace(
        "  push:\n", "  push:\n    paths-ignore:\n      - docs/**\n"
    )

    assert status_problems("validate.yml", text) == []
    assert status_problems("validate.yml", filtered) != []
