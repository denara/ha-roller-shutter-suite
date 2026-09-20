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
uv run python scripts/check_coverage_exclusions.py
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
| `check_deprecated_names.py` | the integration or a test references a Home Assistant name that is known to be deprecated. The names are listed in `scripts/deprecated_names.toml`, and the message tells you what to use instead. See [Deprecated names](#deprecated-names). |
| `check_instance_data.py` | a tracked file contains something that looks like data of a real installation or a real computer: a private IP address, an IPv6 address, a hardware address, a host name ending in `.local`, a pair of coordinates or a coordinate next to a latitude or longitude key, an entity ID with a serial number in it, a path with a drive letter or a home directory, an e-mail address. The script reports file, line and kind, never the text itself. It needs git to list the tracked files. |
| `check_versions.py` | `pyproject.toml` and `manifest.json` state different versions. Both files need the version (uv requires one, Home Assistant and HACS read the other), so a release changes both. |
| `check_log_guard.py` | anything weakens the rule that warnings and logged deprecations are errors. A test other than `tests/ha/test_report_guard.py` uses the fixtures of the log guard, or any file outside `tests/ha/conftest.py` defines a function with the name of one of them. `filterwarnings` in a pytest configuration is anything but exactly `error`. `addopts` or a `pytest` command line in a workflow carries `-W`, `-o`/`--override-ini`, `-c`, `-p no:warnings`, `-p no:logging` or `--disable-warnings`, or a workflow sets `PYTHONWARNINGS`. A test or the integration filters or catches warnings, with the `warnings` module or with `pytest.warns`, `pytest.deprecated_call` or the `recwarn` fixture. |
| `check_foreign_warnings.py` | an entry of `tests/foreign_warnings.toml` is incomplete, has no `https` link, names the category `Warning` (which covers everything), or has a module pattern that contains a colon or matches this integration, its tests, or the Home Assistant helpers that report deprecated usage. |
| `check_coverage.py` | coverage is below a threshold; see below. |
| `check_coverage_exclusions.py` | a coverage pragma has no reason, or the coverage configuration was changed; see below. |

The instance data guard looks for shapes, so it can be wrong in both directions. If it flags a made-up example, change the example (use `cover.example_window`, addresses from the documentation ranges such as `192.0.2.7` and `2001:db8::1`, `homeassistant.local`, `someone@example.com`). A single number with many decimals is not reported, because constants look like that; two of them next to each other are, because that is what coordinates look like. It cannot recognize a real room name or a real device name; reading what you publish stays your job.

### No deprecation, ever

The integration must not use deprecated Home Assistant functionality and must not cause a deprecation message in Home Assistant's log. Home Assistant reports such usage through its log, not as a Python warning, so the log guard in `tests/ha/conftest.py` fails every Home Assistant test during which such a message names this integration.

This can be demonstrated only for the Home Assistant versions the tests ran against and for the code the tests reach. That is why coverage has a threshold and why a scheduled run tests against the newest Home Assistant release.

If a warning comes from another package and cannot be avoided, the only way out is an entry in `tests/foreign_warnings.toml`. The file explains the format. Every entry has to be approved by the project owner: say so explicitly in your pull request and include the link to the upstream issue.

A test must not catch a warning to get past this rule: `pytest.warns`, `pytest.deprecated_call` and `recwarn` are refused like `warnings.catch_warnings`. Fix the cause of the warning.

A test must not end with a raised log level for Home Assistant or the integration either. The log guard makes Home Assistant create its reports whatever the log levels are, and at the end of each test it fails the test if it finds a state that would have hidden a report: `caplog.set_level(logging.ERROR)` without a logger, `logging.disable(logging.WARNING)`, a raised level on a logger of Home Assistant or of the integration, or its handler removed. To capture less in a test, name the logger you mean: `caplog.set_level(logging.ERROR, logger="some.other.package")`.

### Deprecated names

Some deprecated parts of Home Assistant are compatibility shims that log nothing, `DeviceEntry.config_entries` for example. No test can notice them, so the static list `scripts/deprecated_names.toml` is the only net. Each entry says how the name is matched, whether Home Assistant logs a report or stays silent, why the name is deprecated, what replaces it, and where that was verified. Add an entry when you learn of a deprecation that concerns this integration, and verify it in the Core source of the tested version first.

The script does not know types. For names that are common, it reports the attribute on every object except the ones on the entry's allow-list: `.config_entries` is fine on `hass` (also `self.hass`, `entry.hass`, `self._hass`) and on the module `homeassistant`, and is reported everywhere else. If the script flags an attribute of your own that only shares the name, **do not rename a plausible name to get around the guard**. Report the false positive; the guard is then made narrower. The rule for that: an entry for something Home Assistant logs anyway is matched narrowly, because the log guard of the tests is a second net there; only entries for silent shims, which no test can notice, stay broad.

### Coverage

Lines and branches are measured separately, and both have to reach the threshold.

| Part of the code | Threshold |
|---|---|
| `config_flow.py` and every other module outside `core/` whose file name ends in `flow.py` | 100 % |
| Everything under `custom_components/roller_shutter_suite/` except `core/` | 90 % |
| Everything under `custom_components/roller_shutter_suite/core/` | 95 % |

A module that no test imports counts as not covered. The thresholds are confirmed by the project owner and changed by nobody else. Do not write tests that merely execute lines; a test asserts a behavior.

Excluding code from the measurement is possible, but only in the open:

- A `# pragma: no cover` or `# pragma: no branch` under `custom_components/` needs its reason on the same line, in the form `# pragma: no cover - <reason>`, with a reason of at least three words that says why the code cannot be tested. A pragma without a reason fails the build.
- `scripts/check_coverage_exclusions.py` prints every pragma with file, line and reason on every run, also when it passes. A reviewer reads that list in the log of the job "Static checks and guards" and judges the reasons.
- The coverage configuration in `pyproject.toml` is pinned: the measured source, branch measurement, no `omit`, no `exclude_lines`, no `partial_branches`, and `exclude_also` with the single entry `if TYPE_CHECKING:` (imports for the type checker never run). Any other value fails the build, and so does a second coverage configuration file. Whoever has a good reason to change the set changes `EXPECTED` in the script in the same pull request, where the reviewer sees it.

## Workflows on GitHub

| Workflow | Runs on | Does |
|---|---|---|
| Validate (`validate.yml`) | every push, every pull request, weekly, by hand | `hassfest` and the HACS validation |
| Test (`test.yml`) | every push, every pull request, by hand | static checks, guards, tests and coverage thresholds with the locked versions |
| Newest Home Assistant (`newest-home-assistant.yml`) | weekly, by hand, and when the workflow itself changes | the whole test suite against the newest Home Assistant release with the matching test plugin; a second, optional job does the same with the newest version including betas |

GitHub switches scheduled workflows of a public repository off after 60 days without activity in the repository, and says so by e-mail; switch them on again under **Actions**.

"Newest Home Assistant" does not block pull requests. When it fails, the summary page of the run names the tests that failed and what Home Assistant logged. Such a finding is fixed before the next release of the integration. To start it by hand, open **Actions** > **Newest Home Assistant** > **Run workflow**. The optional beta job may fail without turning the run red, because no release of the test plugin matches a beta.

### Rules for every workflow

The repository is public, so every workflow follows these rules. A change to a workflow is reviewed against them.

- `permissions: contents: read` at the top of the workflow. A job gets more only if it cannot work otherwise, and the pull request says why.
- The triggers are `push`, `pull_request`, `schedule` and `workflow_dispatch`. Never `pull_request_target`, and no `workflow_run` that handles code of a pull request with more rights.
- No secrets. The only token is the one GitHub injects, with the read-only permission above.
- Every action is pinned to a full commit SHA, with the version as a comment behind it; this includes GitHub's own actions. Two actions offer no current version tags (`home-assistant/actions` and `hacs/action`); they are pinned to a commit of their main branch, and the comment names the branch and the date.
- Dependabot (`.github/dependabot.yml`) keeps the pinned action SHAs current, including the two actions that are pinned to a branch head, with one grouped pull request per week. Python dependencies are updated deliberately by hand, because the Home Assistant version the tests run against is a decision, not a routine update. If Dependabot leaves one of the two branch-pinned actions alone for long, look up the head commit of its branch and change SHA and comment together.
- The two validators run a container image with a floating tag, which the actions do not let us pin. That is a conscious decision: both are meant to follow Home Assistant and HACS as they change, and the jobs have a read-only token, no secrets and no persisted credentials.
- `persist-credentials: false` on every checkout.
- No dependency cache, so nothing a pull request writes can reach a later run.
- Nothing prints the environment, and no artifact is uploaded. Reports go to the summary page of the run, with paths relative to the repository.

## Recommended settings of the repository on GitHub

These are set by hand by the project owner under **Settings**; a workflow cannot set them.

Under **General** > **Pull Requests**:

- Enable **Automatically delete head branches**. Every block of work has a branch of its own that is no longer needed after the merge.

Under **Branches** (or **Rules** > **Rulesets**), a rule for `main` with exactly these settings:

- **Require a pull request before merging**, with **zero** required approvals. The verdict of the reviewer agent is a comment, and the project owner merges.
- **Require status checks to pass before merging**, with these four required checks:
  - `hassfest`
  - `HACS`
  - `Static checks and guards`
  - `Tests and coverage`
- **Require linear history.** Block pull requests are **squash-merged**: every work block becomes one commit on `main`, with the pull request title as its subject and the description as its body. Every commit on a block branch still has to import and pass the tests on its own, because reviewers read a branch commit by commit and a follow-up after a review has to be checkable on its own.
- **Do not allow force pushes.**
- The rule **applies to administrators** as well ("Do not allow bypassing the above settings").

The four names are the `name:` of the jobs in `validate.yml` and `test.yml`. GitHub does not notice when a required job is renamed; the check then simply never arrives. `tests/scripts/test_workflows.py` fails when one of the names changes, so change the branch protection in the same breath.

Do **not** add `Newest release` or `Current beta (optional)` to the required checks. They test against versions that change without any change in this repository, so they must not block a pull request.
Under **Actions** > **General**:

- **Workflow permissions:** "Read repository contents and packages permissions".
- **Fork pull request workflows from outside collaborators:** require approval for all outside collaborators.

Give the repository a description and topics (under **About** on the front page). The HACS validation asks for both; until they exist, `validate.yml` ignores exactly these two checks, and the comment there says to remove the exception afterwards.
