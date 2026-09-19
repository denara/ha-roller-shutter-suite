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

GitHub Actions workflows under `.github/workflows/`, running on push, on pull requests and once per day (to notice new Home Assistant releases):

1. **Validate:** `hassfest` and HACS validation.
2. **Test:** `uv sync`, `ruff check`, `ruff format --check`, `mypy`, `pytest` (core and Home Assistant tests as separate steps so a failure is attributable).
3. **Guards,** as small scripts under `scripts/` that also run locally:
   - *Core purity:* nothing under `custom_components/roller_shutter_suite/core/` imports `homeassistant` or anything from the integration outside `core/`. Implemented by parsing the syntax tree, not by text search.
   - *Deprecated helpers:* a list of Home Assistant names known to be deprecated (start with those named in the brief: `show_advanced_options`, `get_astral_location`, `get_location_astral_event_next`, `voluptuous` imports, `DeviceEntry.config_entries`) fails the build when referenced. The list lives in one file and is meant to grow.
   - *Instance data:* fails when a tracked file contains patterns typical for real installations. The pattern list is generic (for example serial-number-like entity IDs, coordinates with many decimals, private IP addresses) and must itself contain no instance data.
- Branch protection is a manual setting; describe the recommended settings (required checks, automatic branch deletion) in `docs/dev/contributing.md`.

## Out of scope

- Release automation, publishing, coverage thresholds.

## Deliverables

Workflows, guard scripts with tests for the scripts themselves, `docs/dev/contributing.md`.

## Acceptance criteria

- All workflows pass on the branch of this block.
- Each guard is shown to fail on a deliberate violation (demonstrate in the pull request, do not commit the violation). The guard scripts have unit tests with positive and negative examples.
- The daily run is scheduled.
- A contributor can run every check locally with the commands in `docs/dev/contributing.md`.

## Open questions that block this block

None. The remote exists; the workflow is branch per block plus pull request.
