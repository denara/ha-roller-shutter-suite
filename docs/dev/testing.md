# Testing

The tests live in three folders that are kept apart on purpose.

| Folder | What it tests | What it needs |
|---|---|---|
| `tests/core/` | The domain core under `custom_components/roller_shutter_suite/core/`: the rules that decide where a shutter goes. | Plain Python and pytest. Runs on Linux, macOS and Windows. |
| `tests/ha/` | The Home Assistant layer: config entry, config flow, entities, translations. | The Home Assistant test harness ([pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component)). Runs on Linux and macOS, not on native Windows. |
| `tests/scripts/` | The guard scripts under `scripts/` that CI runs; see [Contributing](contributing.md). | Plain Python and pytest. Runs on Linux, macOS and Windows. |

## Why the core has a folder of its own

The domain core is plain Python and imports nothing from Home Assistant. That keeps its tests fast, and it allows running the core in a time-lapse simulation of a whole day or year. The split makes this rule checkable: a run of `tests/core` alone fails when anything it executes imports `homeassistant`.

Two details make that check work:

- The Home Assistant test plugin imports `homeassistant` as soon as pytest loads it. `tests/core/pytest.ini` switches the plugin off. pytest uses the configuration file closest to the paths it is given, so `uv run pytest tests/core` uses that file, and every run that includes `tests/ha` uses `pyproject.toml`. `tests/scripts/pytest.ini` does the same for the tests of the guard scripts, so they run on native Windows too. All settings of the three files must stay identical apart from the plugin switch; `tests/core/test_pytest_configuration.py` compares every key and fails when they differ or when a small file no longer switches the plugin off.
- Importing `custom_components.roller_shutter_suite.core` would normally execute the integration's `__init__.py` first, which belongs to the Home Assistant layer. In a core run, `tests/core/conftest.py` registers an empty stand-in for the integration package, so the core is found without executing that file. Core tests import the core under its real name, for example `from custom_components.roller_shutter_suite.core import ...`.

In a run of everything, `homeassistant` is loaded before the first test, so nothing can be proven there; the check stays passive and the core tests simply run along. The proof is the run of `tests/core` alone. Every run prints a line "core purity proof: active" or "core purity proof: passive", so a log shows which one it was. A run that uses `tests/core/pytest.ini` but finds `homeassistant` already imported is refused with an error instead of going passive.

The check covers `homeassistant` only. That the core imports nothing from the rest of the integration is not proven by these tests; the static guard `scripts/check_core_purity.py` enforces both directions.

## Running the tests

Create the environment once with `uv sync`, then:

```sh
uv run pytest tests/core      # core tests only, without Home Assistant
uv run pytest tests/scripts   # tests of the guard scripts, without Home Assistant
uv run pytest tests/ha        # Home Assistant tests only
uv run pytest                 # everything
```

On Windows only the first two commands work natively; see [Running the Home Assistant tests on Windows](#running-the-home-assistant-tests-on-windows).

To measure coverage, add `--cov`:

```sh
uv run pytest --cov
```

Coverage is measured for `custom_components/roller_shutter_suite` with branch coverage. CI enforces a minimum for each part of the code; [Contributing](contributing.md#coverage) has the values and the commands.

## What makes a test fail besides its assertions

- **Warnings are errors.** Every Python warning fails the test (`filterwarnings = error`), and that setting is never extended. The only way to exempt a warning is the list `tests/foreign_warnings.toml`, and only for a warning that another package causes: each entry names the module (as a regular expression), the warning category, the reason and a link to the upstream issue, and the project owner approves each entry. `tests/conftest.py` turns the list into filters for every test folder, and each test folder has a test that compares the filters actually in effect with the list, so a filter added by a `conftest.py` further down is noticed in the run of that folder. The list is empty at present. A warning that this integration causes is fixed, not listed.
- **Logged deprecations are errors.** Home Assistant does not raise Python warnings when an integration uses something deprecated; it writes a log message. Two helpers do that in Home Assistant 2026.9:
  - `homeassistant.helpers.frame.report_usage` logs "Detected that custom integration '…' …" on the logger `homeassistant.helpers.frame`.
  - `homeassistant.helpers.deprecation` (deprecated functions, classes, constants, aliases and arguments) logs "The deprecated … was used from …" on the logger of the module that owns the deprecated name.

  A fixture in `tests/ha/conftest.py` (the log guard) is active for every test under `tests/ha/`. It fails the test when such a message names this integration, by its domain or by its issue tracker. Not every such message contains the word "deprecated": a usage report may only say "This will stop working in Home Assistant …" or "Please report it …". The guard therefore counts every record of the frame helper, and on every other logger the known phrases of these reports ("detected that", "will stop working", "will be removed", "no longer supported", "please report", "create a bug report" and similar). Every test that reaches the deprecated call fails, not only the first one: Home Assistant remembers the usage reports it has already logged, but the test plugin clears that memory after every test, and the deprecation helper for functions logs on every call anyway.

  The guard does not depend on log levels. While a test runs, loggers of Home Assistant and of integrations create every record from WARNING upwards, even under `caplog.set_level(logging.ERROR)`, `caplog.at_level(...)`, `logging.disable(...)` or a raised level on the reporting logger; what `caplog` captures still follows its own level. At the end of each test the guard also fails the test when such a state is still in effect or its handler is gone, because then it cannot vouch for the test. To capture less, pass the logger you mean: `caplog.set_level(logging.ERROR, logger="some.other.package")`.

  Only the guard's own self-test, `tests/ha/test_report_guard.py`, provokes reports on purpose: it requests the `integration_reports` fixture, asserts on the list and clears it. No other test may do that; `scripts/check_log_guard.py` fails the build otherwise.

## How Home Assistant finds the integration in tests

The test plugin requires the `enable_custom_integrations` fixture; `tests/ha/conftest.py` requests it for every test through the autouse fixture `auto_enable_custom_integrations`.

Some fixtures of the plugin, `recorder_mock` for example, have to be set up before `enable_custom_integrations`; the plugin's README says so. pytest sets up autouse fixtures first, so requesting `recorder_mock` in a test is too late. A test that needs the recorder needs an autouse fixture that requests `recorder_mock` and that `auto_enable_custom_integrations` depends on; no test needs the recorder yet, so none exists.

The plugin also ships a `custom_components` package of its own inside its test configuration folder. The `hass` fixture puts that folder at the front of the import path while Home Assistant imports `custom_components`. Python keeps whichever `custom_components` package was imported first. `tests/ha/conftest.py` imports from the repository's `custom_components` folder, and pytest loads that file before any test is set up, so the repository's folder wins and Home Assistant finds the integration.

An empty `custom_components/__init__.py` is not needed for this and would not help: if the plugin's package were imported first, it would win with or without that file. `tests/ha/test_harness.py` checks that Home Assistant resolves the integration to the folder in the repository.

## Service descriptions and the voice packages

When Home Assistant validates a service description that contains a `supported_features` or an attribute filter, it imports every base platform (`homeassistant/helpers/service.py`, `_base_components`). One of them is the voice pipeline, which needs two native packages, `pymicro-vad` and `pyspeex-noise`. They are not part of this project's test environment, and for the Python version Home Assistant requires today they have no pre-built wheel.

- **In tests** nothing reaches this path at the moment: the integration has no `services.yaml` and no test loads service descriptions. A test that does (`async_get_all_descriptions`, the websocket command `get_services`) while an integration with such a filter is loaded, Home Assistant's own `cover` integration for example, fails with a `ModuleNotFoundError`. The block that adds this integration's actions decides how to handle it: documented stand-in modules in `tests/ha/conftest.py` first, the real packages only if that does not hold. Never a warning filter.
- **When you start a real Home Assistant** from the development environment for a manual check (`uv run hass -c <empty configuration directory>`), the frontend asks for the service descriptions right after the onboarding. Without the two packages the page stays on "Loading". Home Assistant then tries to build them, which needs a C++ compiler and the Python development headers of the interpreter in use. Install them once in your environment, or put two stand-in modules into that throw-away virtual environment. `hass` runs in the foreground and returns no prompt; it is up when the onboarding appears in the browser.

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

The same holds for the test discovery of an IDE: started from the repository root on native Windows it fails, because pytest cannot import the Home Assistant plugin there. Point the IDE's test runner at the folder `tests/core`, which works natively, and run everything else through WSL as described below.

For the Home Assistant tests, use WSL 2 with a current Ubuntu LTS distribution, and use it for `uv` and the tests only:

- Git and the GitHub CLI stay on the Windows side, where the commit identity and the login are configured. Nothing is committed or pushed from inside WSL.
- Install `uv` inside the distribution. It downloads the required Python version by itself.
- Install `git` inside the distribution as well, for reading only: the instance data guard and its test ask git for the list of files, and they fail when no git can answer. [Contributing](contributing.md#what-the-guards-enforce) explains what the guard needs.
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
