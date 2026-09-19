# Checklist for reviewer agents

A reviewer agent has a fresh context. It reviews exactly one pull request against the block file it implements and against [README.md](README.md) in this folder. It did not write the code and it does not fix it.

## What a reviewer does

1. Read `tasks/README.md`, the block file, and what the block lists under "Read first". Then read the pull request description and the complete diff.
2. Check out the head of the pull request and **run** what can be run: locked sync, the core tests, the Home Assistant tests, the whole suite, `ruff check`, `ruff format --check`, `mypy`, and the guard scripts once they exist. Do not trust the description.
3. Reproduce every "demonstrate once" criterion of the block: make the deliberate violation, see it fail, revert it. Leave the checkout clean.
4. Check every acceptance criterion: met, not met, or not verifiable, and how it was checked.
5. Check Home Assistant API usage against primary sources (developer documentation, developer blog, Core source at the tested tag), not from memory.
6. Go through the fixed checks below.
7. Post exactly one comment with the verdict on the pull request.

## Fixed checks for every pull request

- **No instance data and nothing private** in files, commit messages, the pull request text or comments: no entity IDs, names or addresses of a real installation, no local paths, drive letters, user names, machine or distribution names, e-mail addresses, and no raw shell output.
- **No deprecation, ever** (`tasks/README.md`):
  - the log guard in `tests/ha/conftest.py` is not weakened: its matching rules were not narrowed, it is still active for every test under `tests/ha/`;
  - the `integration_reports` fixture is requested and the collected reports are cleared **only** in the guard's self-test `tests/ha/test_report_guard.py`;
  - there is no new warning filter anywhere: `filterwarnings` is still exactly `["error"]` in every pytest configuration, no `pytest.mark.filterwarnings`, no `warnings.simplefilter` or `catch_warnings` in tests or code that hides a deprecation;
  - `tests/foreign_warnings.toml` is unchanged, or every new entry concerns a warning that originates outside this integration, has a module pattern, a category, a reason and an upstream link, and the pull request description asks the project owner explicitly to approve it;
  - no deprecated Home Assistant name is referenced; no log message was reworded to slip past the guard.
- **Coverage is not bought:** the thresholds are 100 % for flow modules, 90 % for the Home Assistant side and 95 % for the domain core, lines and branches. Every `# pragma: no cover` or `# pragma: no branch` carries a justification on the same line; read each one the guard lists and judge whether the reason holds. The coverage configuration excludes nothing beyond the documented set.
- **Pure domain core:** nothing under `core/` imports `homeassistant` or anything from the integration outside `core/`; the core reads no clock.
- **Missing data is not good news:** no code path turns `unavailable` or `unknown` into a default value.
- **Honest wording:** no reason code, entity name, log message or documentation claims that a curtain has arrived; with a calculated position only "the actuator did not react" can be known.
- **Schemas** use `probatio`; no `voluptuous`, no `show_advanced_options`, no options flow where the brief asks for reconfigure.
- **Translations:** every user-facing string has a key; English and German have identical keys.
- **Repository conventions:** UTF-8 without BOM, LF, final newline, indentation per `.editorconfig`.
- **Scope:** nothing is built that the block does not ask for; `TASKS.md`, `tasks/` and `docs/project-brief.md` are untouched by block agents.
- **Commits:** imperative English messages, the configured repository identity, no force-push, files staged by name.
- **Documentation** named in the block exists, is written in plain language and contains no machine-specific detail.

## The verdict

One comment on the pull request. First line `**Reviewer verdict: ACCEPT**` or `**Reviewer verdict: RETURN WITH FINDINGS**`. Then a table of the acceptance criteria; the result of the fixed checks; findings ordered by severity (blocking, should fix, note), each with file, line and a concrete suggestion; what could not be verified. ACCEPT only without a blocking finding.

The reviewer never merges, pushes, commits or changes the git identity. Merging is done by the project owner. The comment follows the same rules as every public text: no paths, no user names, no raw shell output; write it to a file outside the repository and read it once more before posting.
