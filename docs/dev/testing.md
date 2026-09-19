# Testing

The tests live in two folders that are kept apart on purpose.

| Folder | What it tests | What it needs |
|---|---|---|
| `tests/core/` | The domain core under `custom_components/roller_shutter_suite/core/`: the rules that decide where a shutter goes. | Plain Python and pytest. Runs on Linux, macOS and Windows. |
| `tests/ha/` | The Home Assistant layer: config entry, config flow, entities, translations. | The Home Assistant test harness ([pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)). Runs on Linux and macOS, not on native Windows. |

## Why there are two folders

The domain core is plain Python and imports nothing from Home Assistant. That keeps its tests fast, and it allows running the core in a time-lapse simulation of a whole day or year. The split makes this rule checkable: a run of `tests/core` alone fails when anything it executes imports `homeassistant`.

Two details make that check work:

- The Home Assistant test plugin imports `homeassistant` as soon as pytest loads it. `tests/core/pytest.ini` switches the plugin off. pytest uses the configuration file closest to the paths it is given, so `uv run pytest tests/core` uses that file, and every run that includes `tests/ha` uses `pyproject.toml`. The settings that both files share (warnings as errors, import mode, `asyncio_mode`) must stay identical.
- Importing `custom_components.roller_shutter_suite.core` would normally execute the integration's `__init__.py` first, which belongs to the Home Assistant layer. In a core run, `tests/core/conftest.py` registers an empty stand-in for the integration package, so the core is found without executing that file. Core tests import the core under its real name, for example `from custom_components.roller_shutter_suite.core import ...`.

In a run of everything, `homeassistant` is loaded before the first test, so nothing can be proven there; the check stays passive and the core tests simply run along. The proof is the run of `tests/core` alone.

## Running the tests

Create the environment once with `uv sync`, then:

```sh
uv run pytest tests/core   # core tests only, without Home Assistant
uv run pytest tests/ha     # Home Assistant tests only
uv run pytest              # everything
```

On Windows only the first command works natively; see [Running the Home Assistant tests on Windows](#running-the-home-assistant-tests-on-windows).

To measure coverage, add `--cov`:

```sh
uv run pytest --cov
```

Coverage is measured for `custom_components/roller_shutter_suite` with branch coverage. No minimum is enforced yet.

## What makes a test fail besides its assertions

- **Warnings are errors.** Every Python warning fails the test (`filterwarnings = error`). Exceptions for noise from third-party libraries go into the `filterwarnings` list in `pyproject.toml`, each as narrow as possible (message, category and module) and with a comment that names its origin. The list is empty at present.
- **Logged deprecations are errors.** Home Assistant does not raise Python warnings when an integration uses something deprecated; it writes a log message. Two helpers do that in Home Assistant 2026.9:
  - `homeassistant.helpers.frame.report_usage` logs "Detected that custom integration '…' …" on the logger `homeassistant.helpers.frame`.
  - `homeassistant.helpers.deprecation` (deprecated functions, classes, constants, aliases and arguments) logs "The deprecated … was used from …" on the logger of the module that owns the deprecated name.

  A fixture in `tests/ha/conftest.py` is active for every test under `tests/ha/`. It fails the test when such a message names this integration. Home Assistant logs some of these reports only once per process, so usually only the first test that reaches the deprecated call fails.

  A test that provokes a report on purpose requests the `integration_reports` fixture, asserts on the list and clears it; `tests/ha/test_report_guard.py` shows how.

## How Home Assistant finds the integration in tests

The test plugin requires the `enable_custom_integrations` fixture; `tests/ha/conftest.py` requests it for every test.

The plugin also ships a `custom_components` package of its own inside its test configuration folder. The `hass` fixture puts that folder at the front of the import path while Home Assistant imports `custom_components`. Python keeps whichever `custom_components` package was imported first. `tests/ha/conftest.py` imports from the repository's `custom_components` folder, and pytest loads that file before any test is set up, so the repository's folder wins and Home Assistant finds the integration.

An empty `custom_components/__init__.py` is not needed for this and would not help: if the plugin's package were imported first, it would win with or without that file. `tests/ha/test_harness.py` checks that Home Assistant resolves the integration to the folder in the repository.

## Adding a scenario

For a rule of the domain core:

1. Add a file `tests/core/test_<topic>.py`, or extend the existing one for that topic.
2. Import what you test from `custom_components.roller_shutter_suite.core`. Import nothing from `homeassistant` and nothing from the rest of the integration.
3. Build the situation from plain values: the core gets the time, the sun position and every other input handed in. Use timezone-aware datetimes; never read the clock.
4. Give the test a name that states the situation and the expected result, for example `test_open_door_blocks_closing_during_storm`.
5. Run `uv run pytest tests/core`.

For behavior of the Home Assistant layer:

1. Add a file `tests/ha/test_<topic>.py`, or extend the existing one.
2. Request the `hass` fixture. Create the config entry with `MockConfigEntry` from `pytest_homeassistant_custom_component.common`, add it to `hass` and set it up; `tests/ha/test_config_entry.py` shows the pattern.
3. Use neutral entity IDs such as `cover.example_window`, never names from a real installation.
4. Write the test as `async def`. No marker is needed, because `asyncio_mode = "auto"` is set.
5. Run `uv run pytest tests/ha`.

## Running the Home Assistant tests on Windows

The Home Assistant test harness does not run on native Windows, because Home Assistant imports modules that exist only on POSIX systems. The core tests run everywhere, so `uv run pytest tests/core` works in a Windows shell.

For the Home Assistant tests, use WSL 2 with a current Ubuntu LTS distribution, and use it for `uv` and the tests only:

- Git and the GitHub CLI stay on the Windows side, where the commit identity and the login are configured. Nothing is committed or pushed from inside WSL.
- Install `uv` inside the distribution. It downloads the required Python version by itself.
- The checkout stays where it is on the Windows drive; WSL sees it under its mount point. To get the path of a checkout as WSL sees it, run this in a Windows shell inside the checkout:

  ```sh
  wsl -d <distribution> -e wslpath -a .
  ```

- The virtual environment must live in the Linux file system, not on the mounted Windows drive, because test runs on a mounted drive are very slow. Set `UV_PROJECT_ENVIRONMENT` to a directory under the Linux home directory. Use one environment per checkout or worktree.

The commands below are entered in a Windows shell (PowerShell). Replace `<distribution>` with the name of the WSL distribution, `<path to the repository>` with the path from `wslpath` above, and `<name>` with a name for the environment of this checkout. The login shell (`bash -lc`) is needed so that `uv` is found. In PowerShell the backtick keeps `$HOME` from being expanded on the Windows side.

Create or update the environment:

```powershell
wsl -d <distribution> -e bash -lc "cd '<path to the repository>' && UV_PROJECT_ENVIRONMENT=`$HOME/.venvs/<name> uv sync --locked"
```

Core tests only:

```powershell
wsl -d <distribution> -e bash -lc "cd '<path to the repository>' && UV_PROJECT_ENVIRONMENT=`$HOME/.venvs/<name> uv run pytest tests/core"
```

Home Assistant tests only:

```powershell
wsl -d <distribution> -e bash -lc "cd '<path to the repository>' && UV_PROJECT_ENVIRONMENT=`$HOME/.venvs/<name> uv run pytest tests/ha"
```

Everything:

```powershell
wsl -d <distribution> -e bash -lc "cd '<path to the repository>' && UV_PROJECT_ENVIRONMENT=`$HOME/.venvs/<name> uv run pytest"
```

Before you paste the output of such a run anywhere public, read it: it contains local paths and the local user name.

The authoritative result is the CI run on Linux. A local run speeds up the work; it does not replace CI.
