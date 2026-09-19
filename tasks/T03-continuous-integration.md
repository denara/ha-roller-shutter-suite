# T03 — Continuous integration

| | |
|---|---|
| Kind | Implementation |
| Depends on | T01, T02 |
| Blocks | Merging of every later block (CI is the first review gate) |

## Goal and reason

Reviews by agents and by the owner are only as good as the checks that run before them. CI enforces mechanically what must never depend on attention: validation by `hassfest` and HACS, tests with deprecations as errors, the purity of the domain core, and the absence of instance data.

## Read first

- `tasks/README.md`
- `docs/project-brief.md`: section 6 "Quality"
- `docs/dev/testing.md` (from T02)

## Verify before you build

- Current usage of the `hassfest` GitHub action and of the HACS validation action (category integration), from their own documentation. The repository is public. Note which HACS checks cannot pass yet for another reason (for example while there is no release, no description or no topics), and ignore exactly those, with a comment that says when to remove the exception.

## Scope

**Hardening, because the repository is public** (binding for every workflow):

- `permissions: contents: read` at workflow level; a job gets more only if it cannot work otherwise, and then the block's pull request says why.
- Triggers are `push`, `pull_request` and `schedule` (plus `workflow_dispatch`). **No `pull_request_target`**, no `workflow_run` that handles untrusted code with more rights.
- No secrets. Nothing in these workflows needs one; do not reference `secrets.*` except the default token that GitHub injects, with the read-only permission above.
- Actions that are not maintained by GitHub itself (`actions/*`) are pinned to a full commit SHA with the version as a comment, including `astral-sh/setup-uv`, `home-assistant/actions` and `hacs/action`. GitHub's own actions are pinned to a SHA as well unless that proves impractical; say which way you chose.
- No raw output with paths or environment dumps in uploaded artifacts. Upload only what is needed (for example the coverage report), and check what it contains. Do not print the environment.
- `persist-credentials: false` on checkout.

GitHub Actions workflows under `.github/workflows/`, running on push and on pull requests:

1. **Validate:** `hassfest` and HACS validation.
2. **Test:** `uv sync`, `ruff check`, `ruff format --check`, `mypy`, `pytest` (core and Home Assistant tests as separate steps so a failure is attributable).
3. **Coverage threshold.** The Home Assistant side of the integration (everything under `custom_components/roller_shutter_suite/` except `core/`) must reach **90 %** line and branch coverage, `config_flow.py` and every later flow module **100 %** (the quality scale asks for full coverage of config flows, and an untested flow path is exactly where a deprecation hides). The domain core must reach **95 %**. The build fails below these values. They are a proposal by the orchestrator; the owner may change them.
4. **Scheduled run against the newest Home Assistant** (weekly, plus `workflow_dispatch`): installs the latest released Home Assistant and the matching test plugin instead of the locked versions and runs the whole suite with the log guard; an optional second job does the same for the current beta. This run does **not** block pull requests, but it fails visibly (a red run, and the workflow summary names the deprecation messages in neutral form). A message found there is fixed before the next release of the integration. The locked versions stay what pull requests are tested against.
5. **Guards,** as small scripts under `scripts/` that also run locally:
   - *Core purity:* nothing under `custom_components/roller_shutter_suite/core/` imports `homeassistant` or anything from the integration outside `core/`. Implemented by parsing the syntax tree, not by text search.
   - *Deprecated helpers:* a list of Home Assistant names known to be deprecated (start with those named in the brief: `show_advanced_options`, `get_astral_location`, `get_location_astral_event_next`, `voluptuous` imports, `DeviceEntry.config_entries`) fails the build when referenced. The list lives in one file and is meant to grow.
   - *Instance data:* fails when a tracked file contains patterns typical for real installations. The pattern list is generic (for example serial-number-like entity IDs, coordinates with many decimals, private IP addresses) and must itself contain no instance data.
- Carried over from the review of T02:
  - *No weakened log guard:* a guard fails the build when any test file other than `tests/ha/test_report_guard.py` requests the `integration_reports` fixture or clears the collected reports; when `filterwarnings` in `pyproject.toml` or `tests/core/pytest.ini` is anything but exactly `["error"]`; and when a test or the integration uses `pytest.mark.filterwarnings`, `warnings.simplefilter`, `warnings.filterwarnings` or `warnings.catch_warnings`. The rule behind it is in `tasks/README.md` ("No deprecation, ever").
  - *The one way out for foreign warnings:* `tests/foreign_warnings.toml`, created empty in this block. Each entry has a module pattern (regular expression), a warning category, a reason and an upstream link. A root `tests/conftest.py` reads the list and installs exactly these filters, for both test folders; nothing else may add a filter. The guard validates every entry: all four fields present, the link is an `https` URL, and the module pattern matches neither this integration's package nor `homeassistant.helpers.frame` or `homeassistant.helpers.deprecation`. The guard accepts only filters that come from this list. Entries are approved by the project owner; say so in the file's header comment.
  - Widen the log guard in `tests/ha/conftest.py` so it also catches usage reports of Home Assistant that name this integration without the word "deprecated" (for example "will stop working", "breaks in", "please report" style messages of the frame helper). Read the message formats in the Core source at the tested tag and extend the guard's self-test accordingly.
  - The core purity guard forbids both directions: nothing under `core/` imports `homeassistant`, and nothing under `core/` imports from the integration outside `core/` (the test-side stand-in module cannot guarantee the second).
  - `tests/core/conftest.py` compares resolved paths when it decides whether the core configuration is active; the pytest configuration test compares all shared keys, not only the three that exist today.
  - `mypy` also checks `tests/`.
  - A note in `docs/dev/testing.md`: recorder fixtures have to be requested before the autouse fixture that enables custom integrations, as the test plugin's README asks.
- Carried over from the review of T01:
  - CI installs with `uv sync --locked`, so a lock file that does not match `pyproject.toml` fails the build.
  - The version number exists in `pyproject.toml` and in `manifest.json`. A guard fails the build when the two differ (or one becomes the single source; say which and why).
  - `ruff format` also formats Markdown. Exclude `TASKS.md`, `tasks/` and `docs/project-brief.md` from the format check: block agents must not edit them, so they must not be able to fail on them.
  - The entry title "Roller Shutter Suite" is a fixed product name in every language; do not flag it as untranslated.
- Branch protection is a manual setting; describe the recommended settings (required checks, automatic branch deletion) in `docs/dev/contributing.md`.

## Out of scope

- Release automation, publishing, coverage thresholds.

## Deliverables

Workflows, guard scripts with tests for the scripts themselves, `docs/dev/contributing.md`.

## Acceptance criteria

- All workflows pass on the branch of this block.
- Each guard is shown to fail on a deliberate violation (demonstrate in the pull request, do not commit the violation). The guard scripts have unit tests with positive and negative examples.
- The weekly run against the newest Home Assistant release is scheduled, can be started by hand, and does not block pull requests.
- Every workflow has `permissions: contents: read`, no `pull_request_target`, no secret, SHA-pinned third-party actions and no artifact with raw output; the pull request lists each action with its pinned SHA and version.
- The coverage thresholds are enforced and currently met.
- `tests/foreign_warnings.toml` exists and is empty; a deliberately added invalid entry (demonstrate once) fails the guard, and so does a warning filter anywhere else.
- A contributor can run every check locally with the commands in `docs/dev/contributing.md`.

## Open questions that block this block

None. The remote exists; the workflow is branch per block plus pull request.
