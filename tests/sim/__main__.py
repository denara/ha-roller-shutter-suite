"""Run a named scenario and print its timeline: a tool for developers.

    uv run python -m tests.sim workday
    uv run python -m tests.sim year --seed 3 --window window_4 --kinds decision,command
    uv run python -m tests.sim --list

It is not part of the integration and is not shipped; it needs the domain
core, the astral-backed sun port and nothing of Home Assistant. Run it from
the root of the repository.
"""

import argparse
import sys
import time as wall_clock
from collections.abc import Sequence
from importlib.machinery import ModuleSpec
from importlib.util import module_from_spec
from pathlib import Path


def _without_the_integration_package() -> None:
    """Register an empty stand-in for the integration package.

    Importing the core normally executes the integration's ``__init__.py``
    first, which belongs to the Home Assistant layer. The core tests do the
    same as this (``tests/core/conftest.py``), for the same reason.
    """
    name = "custom_components.roller_shutter_suite"
    if name in sys.modules:
        return
    folder = (
        Path(__file__).resolve().parents[2]
        / "custom_components"
        / "roller_shutter_suite"
    )
    spec = ModuleSpec(name, loader=None, is_package=True)
    spec.submodule_search_locations = [str(folder)]
    sys.modules[name] = module_from_spec(spec)


def main(arguments: Sequence[str] | None = None) -> int:
    """Parse the command line, run the scenario, print the timeline."""
    _without_the_integration_package()
    from .record import EntryKind  # noqa: PLC0415 - after the stand-in
    from .scenarios import SCENARIOS, run_named  # noqa: PLC0415 - after the stand-in

    parser = argparse.ArgumentParser(
        prog="python -m tests.sim",
        description="Run a scenario of the time-lapse simulation.",
    )
    parser.add_argument("scenario", nargs="?", help="the name of the scenario")
    parser.add_argument(
        "--seed", type=int, default=1, help="the seed of the run (default 1)"
    )
    parser.add_argument("--window", help="print the timeline of this window only")
    parser.add_argument(
        "--kinds",
        help="print these kinds of entries only, comma-separated: "
        + ", ".join(kind.value for kind in EntryKind),
    )
    parser.add_argument("--list", action="store_true", help="list the scenarios")
    options = parser.parse_args(arguments)
    out = sys.stdout
    if options.list or options.scenario is None:
        for name, scenario in SCENARIOS.items():
            out.write(f"{name:<24} {scenario.description}\n")
        return 0
    if options.scenario not in SCENARIOS:
        sys.stderr.write(f"unknown scenario {options.scenario!r}; --list shows them\n")
        return 2
    kinds = None
    if options.kinds:
        try:
            kinds = [EntryKind(kind.strip()) for kind in options.kinds.split(",")]
        except ValueError:
            sys.stderr.write("unknown kind of entry; see --help\n")
            return 2
    started = wall_clock.perf_counter()
    simulation = run_named(options.scenario, options.seed)
    seconds = wall_clock.perf_counter() - started
    out.write(simulation.record.timeline(window_id=options.window, kinds=kinds))
    out.write("\n")
    out.write(
        f"--- {options.scenario}, seed {options.seed}: {simulation.recomputes} recomputes, "
        f"{len(simulation.record.entries)} entries, {simulation.restarts} restarts, "
        f"{seconds:.2f} s\n"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
