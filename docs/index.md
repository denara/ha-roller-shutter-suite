# Roller Shutter Suite documentation

Roller Shutter Suite is a custom integration for Home Assistant that controls roller shutters: daily schedules, sun shading, reactions to open windows and doors, protection during storm, hail or fire, and a manual override that respects the person at the window.

**Status: in development, not usable yet.** The pages below are written together with the features they describe. A page that is not linked does not exist yet.

## For users

- Installation: see the [README](../README.md#installation)
- Setting up the integration: to be written
- Adding groups and windows: to be written
- [Concepts](concepts.md): how settings are inherited from the house to groups to windows, and how the integration decides where a shutter goes, each with worked examples
- [The daily routine](features/daily-routine.md): morning and evening, workdays, weekends and public holidays, sun times with "not before" and "not after", and what happens after a restart
- [Shading by geometry](features/shading-geometry.md): what to measure at a window, at several shutters side by side and at a roof element of two rows; how the shutter follows the sun; the two calibration values and how to find them
- Actions and events for your own automations: to be written
- Troubleshooting: to be written

## For contributors

- [Project brief](project-brief.md): goals, feature catalog and architectural guardrails
- [Development setup](../README.md#development)
- [The core model](dev/core-model.md): the data types and ports of the domain core, with a worked example of a decision
- [The arbiter](dev/arbiter.md): layers, constraints and the gate; the evaluation order, the fire bypass, dams, deferrals and dry-run; how to add a layer, a constraint or a gate rule
- [The schedule](dev/schedule.md): parts of the day, triggers and clamps, day types and their latch, the rule for clock changes, random offsets, and how the schedule plugs into the arbiter
- [Sun geometry and glass calibration](dev/geometry.md): conventions, the formulas for vertical and tilted glass, one curtain edge for several members, calibration in both directions, the result type, and how the shading layer calls it
- [Testing](dev/testing.md): the two test folders, how to run them, how to add a scenario, and how to run the Home Assistant tests on Windows
- [Contributing](dev/contributing.md): every check that CI runs and how to run it locally, the guards, the workflows and the recommended repository settings
- [Configuration flow findings](dev/config-flow-findings.md): what config subentry flows can do, the pattern for inherited values in forms, reloading exactly once, cover groups, and the module layout for configuration steps
