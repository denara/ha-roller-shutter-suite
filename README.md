# Roller Shutter Suite for Home Assistant

A custom integration that becomes the single authority over roller shutters: schedules, sun shading, window interaction, protection events and manual override, configured per window.

## Status

**In development, not usable yet.** The integration can be installed and set up, but it does nothing so far. Do not install it on a system you rely on.

Requires Home Assistant 2026.9 or newer.

## Installation

The integration is installed through [HACS](https://hacs.xyz) as a custom repository:

1. Open HACS in Home Assistant.
2. Open the menu in the top right corner and choose **Custom repositories**.
3. Enter `https://github.com/denara/ha-roller-shutter-suite` as the repository, choose **Integration** as the type and select **Add**.
4. Search for **Roller Shutter Suite** in HACS, open it and select **Download**.
5. Restart Home Assistant.
6. Go to **Settings** > **Devices & services** > **Add integration** and choose **Roller Shutter Suite**.

The integration can be set up only once per Home Assistant installation.

## Documentation

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

The Home Assistant tests do not run on native Windows. [Testing](docs/dev/testing.md) explains the two test folders and the way through WSL.

Work is planned in blocks: see [`TASKS.md`](TASKS.md) and the [`tasks/`](tasks/) folder.

## License

[MIT](LICENSE)
