# T02 — Test setup

| | |
|---|---|
| Kind | Implementation |
| Depends on | T01 |
| Blocks | T03, S2, S3, every code block |

## Goal and reason

The project owner has seen integrations break on deprecated patterns. The test setup therefore has to fail loudly on deprecations, and it has to keep the two worlds apart: the domain core is tested without Home Assistant (guardrail 4), the Home Assistant layer with the official test harness. Setting this up once prevents every later block from inventing its own conventions.

## Read first

- `tasks/README.md`
- `docs/project-brief.md`: guardrail 4, section 6 "Quality" and the last item of "Home Assistant specifics" (what could not be verified)

## Verify before you build

- How `pytest-homeassistant-custom-component` is configured today (fixtures such as enabling custom integrations, `asyncio_mode`), from its own README, not from memory.
- How Home Assistant reports deprecated API usage: which cases raise a Python warning and which are only logged through its usage-report helper. Record what you found and at which source.

## Scope

- `tests/core/`: plain pytest, no Home Assistant import anywhere. A `conftest.py` that fails the session if `homeassistant` was imported by a core test (the mechanical proof of purity on the test side).
- `tests/ha/`: tests with the Home Assistant harness; `conftest.py` with the fixtures needed to load the custom integration.
- pytest configuration in `pyproject.toml`: `asyncio_mode = "auto"`, warnings as errors with the narrowest possible, commented list of exceptions for third-party noise.
- A fixture, active for every test under `tests/ha/`, that fails a test when Home Assistant **logs** a deprecation or usage report that names this integration, because `filterwarnings = error` does not catch logged messages.
- First tests: config entry sets up, a second entry is refused, entry unloads; translation files have identical key sets (English, German, `strings.json`).
- Coverage measurement configured, no threshold enforced yet.
- A short `docs/dev/testing.md`: how to run core tests only, Home Assistant tests only, everything; how to add a scenario; why the two folders exist.

## Out of scope

- CI (T03). The time-lapse simulation harness (C05). Snapshot testing unless a test in this block needs it.

## Deliverables

Test folders, configuration, fixtures, first tests, `docs/dev/testing.md`.

## Acceptance criteria

- `uv run pytest tests/core` runs without importing `homeassistant`; a deliberately added `import homeassistant` in a core test makes the run fail (demonstrate once, do not commit).
- `uv run pytest` passes with warnings as errors.
- A deliberately used deprecated Home Assistant API in the integration makes a test fail, either through a warning or through the log fixture (demonstrate once with a concrete example, describe it in the pull request, do not commit it).
- The translation parity test fails when a key is missing in one language (demonstrate once).

## Required tests

As listed under scope.

## Open questions that block this block

None.
