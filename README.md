# Roller Shutter Suite for Home Assistant

A custom integration that becomes the single authority over roller shutters: schedules, sun shading, window interaction, protection events and manual override, configured per window.

## Status

**Pilot.** Version 0.3.0 can be installed next to the control you use today. Every window starts in dry-run: it decides what it would do with a shutter, shows it and writes it down, and moves nothing. Once you trust a window, you arm it in its settings, and from then on it moves its shutter. It notices when you move a shutter by hand and leaves it where you put it. The [pilot guide](docs/pilot.md) takes you through installing it, adding one window, comparing its decisions with your existing control, arming it, and removing it again.

What works:

- the forms for the house, groups and windows, with values inherited from the house to groups to windows;
- the daily routine: morning and evening on workdays, weekends and public holidays, fixed times or the sun with "not before" and "not after", a separate summer evening position, an outdoor brightness sensor, a random offset;
- the settings of movement: minimum change, minimum interval, the gap between motors;
- a page for every cover of a window: where its position comes from, a tolerance for a shutter that settles a little off, how the cover reports its movements and how late, and its travel times;
- noticing a movement by hand, the manual override that then leaves the shutter alone until the next change between day and night, and the button Resume automation that ends it;
- arming a window after a page of checks, for covers that report their movements by themselves;
- pause, maintenance lock and operating mode for the house, every group and every window, and an external pause entity per level; the strictest of the three levels wins, and they survive a restart;
- for every window: the entities Reason, Target position, Next planned action, Manual override and Dry-run, the button Resume automation, the event `roller_shutter_suite_reason`, logbook entries and a diagnostics download;
- every text of the forms, the status and the logbook in English and German, written in plain language.

What does not work yet:

- shading, storm and hail, the fire alarm, sleep mode, reactions to open windows and doors;
- a check of every command an armed window sends; until it exists, a window with a cover that Home Assistant only asks for its state on a schedule (polled) cannot be armed;
- remembering the state of a window across a restart of Home Assistant: a restart ends a manual override, see the [pilot guide](docs/pilot.md#7-after-a-restart-of-home-assistant).

Requires Home Assistant 2026.9 or newer.

## Installation

The integration is installed through [HACS](https://hacs.xyz) as a custom repository:

1. Open HACS in Home Assistant.
2. Open the menu in the top right corner and choose **Custom repositories**.
3. Enter `https://github.com/denara/ha-roller-shutter-suite` as the repository, choose **Integration** as the type and select **Add**.
4. Search for **Roller Shutter Suite** in HACS, open it and select **Download**; choose the version **0.3.0** in the dialog.
5. Restart Home Assistant.
6. Go to **Settings** > **Devices & services** > **Add integration** and choose **Roller Shutter Suite**.

The integration can be set up only once per Home Assistant installation.

## Documentation

- [Pilot guide](docs/pilot.md): one window from dry-run to armed, step by step
- [Documentation](docs/index.md)
- [Project brief](docs/project-brief.md): what is being built and why

## Development

The project uses [uv](https://docs.astral.sh/uv/). uv downloads the required Python version (3.14.2 or newer, as required by Home Assistant 2026.9) by itself; nothing has to be installed system-wide.

Create the environment from a clean checkout:

```sh
uv sync
```

Run the checks:

```sh
uv run ruff check
uv run ruff format --check
uv run mypy
```

Run the tests:

```sh
uv run pytest
```

The Home Assistant tests do not run on native Windows. [Testing](docs/dev/testing.md) explains the test folders and the way through WSL. [Contributing](docs/dev/contributing.md) lists every check that CI runs, including the guard scripts, and how to run it locally.

Work is planned in blocks: see [`TASKS.md`](TASKS.md) and the [`tasks/`](tasks/) folder.

## License

[MIT](LICENSE)
