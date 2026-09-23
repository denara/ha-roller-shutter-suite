"""The time-lapse simulation: a synthetic world that drives the domain core.

A development tool, not part of the shipped integration (feature N6, block
C05). It implements the core's ports with a controllable clock, the shared
astral-backed sun port, scripted sources, simulated covers and an in-memory
storage, and it drives the engine the way the runtime will: a recompute on
every change of an input, every report of a cover and every planned wake-up;
the decision is acted on, the state is persisted. Nothing here imports Home
Assistant. ``docs/dev/simulation.md`` explains how to write a scenario, the
behaviour profiles of the covers, and how to read a timeline.

| Module | Content |
|---|---|
| ``clock`` | the controllable clock |
| ``sources`` | scripted and generated time series, with unavailable phases |
| ``storage`` | the in-memory storage |
| ``cover`` | the simulated cover and its behaviour profiles |
| ``world`` | the world: clock, sun, sources, covers, storage, actuator |
| ``record`` | the record of a run and the readable timeline |
| ``assertions`` | what a run must satisfy |
| ``runner`` | the scenario runner: windows, events, recomputes, restart |
| ``scenarios`` | the named scenarios |
| ``__main__`` | the command-line entry point |
"""
