# Contributing

This page lists every check that runs on GitHub, how to run the same check on your own computer, and how the repository on GitHub should be configured. [Testing](testing.md) explains the tests themselves.

## Set up

The project uses [uv](https://docs.astral.sh/uv/). It downloads the required Python version by itself.

```sh
uv sync --locked
```

`--locked` makes the command fail when `uv.lock` does not match `pyproject.toml`. If you changed a dependency, run `uv lock` and commit the new `uv.lock` together with `pyproject.toml`.

On Windows, everything on this page works natively except the one command that is marked "not on native Windows": the Home Assistant tests need WSL; see [Running the Home Assistant tests on Windows](testing.md#running-the-home-assistant-tests-on-windows).

## Run every check locally

Run the commands from the root of the repository. This is the complete list of what CI runs with the locked versions, in the same order.

Static checks:

```sh
uv run ruff check
uv run ruff format --check
uv run mypy
```

`ruff format` also formats code blocks in Markdown files. `TASKS.md`, `tasks/` and `docs/project-brief.md` are excluded, because they are maintained by the project's orchestrator and not by the author of a change. `mypy` checks the integration, the tests and the scripts.

Guards (each needs only Python, no Home Assistant):

```sh
uv run python scripts/check_core_purity.py
uv run python scripts/check_deprecated_names.py
uv run python scripts/check_instance_data.py
uv run python scripts/check_versions.py
uv run python scripts/check_log_guard.py
uv run python scripts/check_foreign_warnings.py
```

Tests:

```sh
uv run pytest tests/core --cov --cov-report=
uv run pytest tests/scripts
uv run pytest tests/ha --cov --cov-append --cov-report=    # not on native Windows
```

Give pytest one test folder at a time, as above, or none at all (`uv run pytest` runs everything, not on native Windows). Coverage thresholds (after the two test runs with `--cov` above):

```sh
uv run coverage json -q -o coverage.json
uv run python scripts/check_coverage.py coverage.json
uv run coverage report
```

Validation by `hassfest` and HACS runs on GitHub only. `hassfest` can be run locally with Docker, as the [Home Assistant developer blog](https://developers.home-assistant.io/blog/2020/04/16/hassfest/) describes; the HACS validation looks at the repository on GitHub and cannot run locally.

A local run speeds up the work. The authoritative result is the run on GitHub.

## What the guards enforce

Each guard is a small script under `scripts/` with a description at its top, and each has tests under `tests/scripts/`.

| Script | Fails when |
|---|---|
| `check_core_purity.py` | a module under `custom_components/roller_shutter_suite/core/` imports `homeassistant`, or imports anything of the integration outside `core/`. The core is plain Python and gets all its inputs handed in. |
| `check_deprecated_names.py` | the integration or a test references a Home Assistant name that is known to be deprecated. The names are listed in `scripts/deprecated_names.toml`. Add a name there when you learn of a deprecation that concerns this integration, with the reason and the replacement. |
| `check_instance_data.py` | a tracked file contains something that looks like data of a real installation or a real computer: a private IP address, a hardware address, a coordinate with many decimals, an entity ID with a serial number in it, a path with a drive letter or a home directory, an e-mail address. The script reports file, line and kind, never the text itself. It needs git to list the tracked files. |
| `check_versions.py` | `pyproject.toml` and `manifest.json` state different versions. Both files need the version (uv requires one, Home Assistant and HACS read the other), so a release changes both. |
| `check_log_guard.py` | anything weakens the rule that warnings and logged deprecations are errors: a test other than `tests/ha/test_report_guard.py` uses the `integration_reports` fixture, `filterwarnings` in a pytest configuration is anything but exactly `error`, or a test or the integration filters or catches warnings. |
| `check_foreign_warnings.py` | an entry of `tests/foreign_warnings.toml` is incomplete, has no `https` link, or has a module pattern that matches this integration, its tests, or the Home Assistant helpers that report deprecated usage. |
| `check_coverage.py` | coverage is below a threshold; see below. |

The instance data guard looks for shapes, so it can be wrong in both directions. If it flags a made-up example, change the example (use `cover.example_window`, addresses from the documentation ranges, `someone@example.com`). It cannot recognize a real room name or a real device name; reading what you publish stays your job.

### No deprecation, ever

The integration must not use deprecated Home Assistant functionality and must not cause a deprecation message in Home Assistant's log. Home Assistant reports such usage through its log, not as a Python warning, so the log guard in `tests/ha/conftest.py` fails every Home Assistant test during which such a message names this integration.

This can be demonstrated only for the Home Assistant versions the tests ran against and for the code the tests reach. That is why coverage has a threshold and why a scheduled run tests against the newest Home Assistant release.

If a warning comes from another package and cannot be avoided, the only way out is an entry in `tests/foreign_warnings.toml`. The file explains the format. Every entry has to be approved by the project owner: say so explicitly in your pull request and include the link to the upstream issue.

### Coverage

Lines and branches are measured separately, and both have to reach the threshold.

| Part of the code | Threshold |
|---|---|
| `config_flow.py` and every other module outside `core/` whose file name ends in `flow.py` | 100 % |
| Everything under `custom_components/roller_shutter_suite/` except `core/` | 90 % |
| Everything under `custom_components/roller_shutter_suite/core/` | 95 % |

A module that no test imports counts as not covered. The thresholds are changed by the project owner only. Do not write tests that merely execute lines; a test asserts a behavior.

## Workflows on GitHub

| Workflow | Runs on | Does |
|---|---|---|
| Validate (`validate.yml`) | every push, every pull request, weekly, by hand | `hassfest` and the HACS validation |
| Test (`test.yml`) | every push, every pull request, by hand | static checks, guards, tests and coverage thresholds with the locked versions |
| Newest Home Assistant (`newest-home-assistant.yml`) | weekly, by hand, and when the workflow itself changes | the whole test suite against the newest Home Assistant release with the matching test plugin; a second, optional job does the same with the newest version including betas |

"Newest Home Assistant" does not block pull requests. When it fails, the summary page of the run names the tests that failed and what Home Assistant logged. Such a finding is fixed before the next release of the integration. To start it by hand, open **Actions** > **Newest Home Assistant** > **Run workflow**. The optional beta job may fail without turning the run red, because no release of the test plugin matches a beta.

### Rules for every workflow

The repository is public, so every workflow follows these rules. A change to a workflow is reviewed against them.

- `permissions: contents: read` at the top of the workflow. A job gets more only if it cannot work otherwise, and the pull request says why.
- The triggers are `push`, `pull_request`, `schedule` and `workflow_dispatch`. Never `pull_request_target`, and no `workflow_run` that handles code of a pull request with more rights.
- No secrets. The only token is the one GitHub injects, with the read-only permission above.
- Every action is pinned to a full commit SHA, with the version as a comment behind it; this includes GitHub's own actions. Two actions offer no current version tags (`home-assistant/actions` and `hacs/action`); they are pinned to a commit of their main branch, and the comment names the branch and the date. To update a pin, look up the commit of the new tag in the action's repository and change SHA and comment together.
- `persist-credentials: false` on every checkout.
- No dependency cache, so nothing a pull request writes can reach a later run.
- Nothing prints the environment, and no artifact is uploaded. Reports go to the summary page of the run, with paths relative to the repository.

## Recommended settings of the repository on GitHub

These are set by hand by the project owner under **Settings**; a workflow cannot set them.

Under **General** > **Pull Requests**:

- Enable **Automatically delete head branches**. Every block of work has a branch of its own that is no longer needed after the merge.

Under **Branches** (or **Rules** > **Rulesets**), a rule for `main`:

- **Require a pull request before merging.** Nobody pushes to `main` directly.
- **Require status checks to pass before merging**, with **Require branches to be up to date before merging**, and these required checks:
  - `hassfest`
  - `HACS`
  - `Static checks and guards`
  - `Tests and coverage`
- Do **not** add `Newest release` or `Current beta (optional)` to the required checks. They test against versions that change without any change in this repository, so they must not block a pull request.
- **Do not allow force pushes** and **do not allow deletions**.
- Apply the rule to administrators as well.

Under **Actions** > **General**:

- **Workflow permissions:** "Read repository contents and packages permissions".
- **Fork pull request workflows from outside collaborators:** require approval for all outside collaborators.

Give the repository a description and topics (under **About** on the front page). The HACS validation asks for both; until they exist, `validate.yml` ignores exactly these two checks, and the comment there says to remove the exception afterwards.
