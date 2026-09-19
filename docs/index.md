# Roller Shutter Suite documentation

Roller Shutter Suite is a custom integration for Home Assistant that controls roller shutters: daily schedules, sun shading, reactions to open windows and doors, protection during storm, hail or fire, and a manual override that respects the person at the window.

**Status: in development, not usable yet.** The pages below are written together with the features they describe. A page that is not linked does not exist yet.

## For users

- Installation: see the [README](../README.md#installation)
- Setting up the integration: to be written
- Adding groups and windows: to be written
- How the integration decides where a shutter goes: to be written
- Actions and events for your own automations: to be written
- Troubleshooting: to be written

## For contributors

- [Project brief](project-brief.md): goals, feature catalog and architectural guardrails
- [Development setup](../README.md#development)
- [Testing](dev/testing.md): the two test folders, how to run them, how to add a scenario, and how to run the Home Assistant tests on Windows
- [Contributing](dev/contributing.md): every check that CI runs and how to run it locally, the guards, the workflows and the recommended repository settings
- [Configuration flow findings](dev/config-flow-findings.md): what config subentry flows can do, the pattern for inherited values in forms, reloading exactly once, cover groups, and the module layout for configuration steps
