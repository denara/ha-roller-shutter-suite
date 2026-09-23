"""The command-line entry point of the simulation."""

import pytest

from tests.sim.__main__ import main
from tests.sim.scenarios import SCENARIOS

USAGE_ERROR = 2


def test_the_list_names_every_scenario(capsys: pytest.CaptureFixture[str]) -> None:
    """Without a scenario, or with --list, the names and descriptions are printed."""
    assert main(["--list"]) == 0
    listed = capsys.readouterr().out
    for name, scenario in SCENARIOS.items():
        assert name in listed
        assert scenario.description in listed
    assert main([]) == 0


def test_a_scenario_prints_its_timeline_and_a_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The timeline of the chosen window and kinds, then one line of numbers."""
    assert main(["storm", "--kinds", "command", "--window", "window_example"]) == 0
    out = capsys.readouterr().out.splitlines()

    assert all("command" in line for line in out[:-1])
    assert "send 0 (protection, protection_event)" in "\n".join(out)
    assert out[-1].startswith("--- storm, seed 1:")


def test_an_unknown_scenario_or_kind_is_refused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Both end with status 2 and a hint on the error stream."""
    assert main(["no-such-scenario"]) == USAGE_ERROR
    assert "--list" in capsys.readouterr().err
    assert main(["storm", "--kinds", "no-such-kind"]) == USAGE_ERROR
    assert "--help" in capsys.readouterr().err
