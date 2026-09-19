# T01 — Repository scaffolding

| | |
|---|---|
| Kind | Implementation |
| Depends on | — (can run in parallel with D00) |
| Blocks | T02, T03, every code block |

## Goal and reason

The repository is HACS-ready from the first commit (G7). This block creates the project skeleton and an integration that loads and does nothing, so every later block adds to a structure that already passes validation instead of being made valid at the end.

T01 is the first block to run: the repository is public and has no `LICENSE` file yet, so "all rights reserved" applies until this block adds the MIT license the brief names. Commit the `LICENSE` file first.

## Read first

- `tasks/README.md`
- `docs/project-brief.md`: goals G6–G8, section 6 ("Home Assistant specifics", "Quality", "Repository and documentation")
- `.editorconfig`, `.gitattributes`, `.gitignore`

## Verify before you build

Check against the primary source and record the result in the pull request:

- The manifest keys required for a custom integration and the valid values of `integration_type`; the brief's working assumption is `hub`, `iot_class: calculated`, `single_config_entry: true`.
- The current keys of `hacs.json` and whether the HACS validation requires the `brand/` folder (marked unverified in the brief).
- That Home Assistant 2026.9 ships `probatio` and how it is imported; whether `import voluptuous` still works is irrelevant, it is not used.
- The exact Python version Home Assistant 2026.9 requires.

## Scope

- `pyproject.toml` managed with `uv`: Python as required by Home Assistant 2026.9, development dependencies pinned (`pytest-homeassistant-custom-component` in the version that tracks Home Assistant 2026.9.x, `ruff`, `mypy`), tool configuration for `ruff` (lint and format) and `mypy` (strict for the integration package).
- `custom_components/roller_shutter_suite/`: `manifest.json` (domain `roller_shutter_suite`, version, documentation and issue tracker URL of the repository, code owner, no requirements that Core already ships), `__init__.py` with `async_setup_entry` / `async_unload_entry` using `entry.runtime_data` with a typed config entry, `const.py`, a minimal `config_flow.py` that creates the single config entry without options, `strings.json` and `translations/en.json`, `translations/de.json`, `brand/icon.png` placeholder, empty package `core/` with a docstring that states the purity rule.
- `hacs.json`, `LICENSE` (MIT), `README.md` skeleton (what it is, status "in development, not usable yet", installation via HACS custom repository, link to `docs/`), `docs/index.md` skeleton.
- `.gitignore` additions for `uv` and build artifacts, if needed.

## Out of scope

- Tests and test configuration (T02), CI workflows (T03).
- Subentries, entities, any logic.
- A final icon design; a neutral placeholder is enough.

## Deliverables

The files above; a pull request description that records the verification results.

## Acceptance criteria

- `uv sync` creates a working environment from a clean checkout; the commands for it are in the README's development section.
- `ruff check`, `ruff format --check` and `mypy` pass.
- The integration can be set up in a Home Assistant 2026.9 instance through the UI, creates exactly one config entry, refuses a second one, and unloads cleanly.
- No hard dependency on other integrations in `manifest.json` beyond what is verified as necessary; optional ones are `after_dependencies`.
- English and German translation files have identical keys.
- No instance data anywhere.

## Required tests

None in this block; T02 adds the first test, which sets up and unloads the config entry.

## Documentation (part of done)

`README.md` and `docs/index.md` skeletons as described.

## Open questions that block this block

None. Name, domain, license (MIT) and minimum version (2026.9) are decided.
