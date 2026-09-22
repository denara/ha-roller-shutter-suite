"""The Python patch version is pinned, and the tests run on exactly that one.

``.python-version`` is what ``uv`` reads when it creates the environment, on
every system and in CI alike. ``requires-python`` in ``pyproject.toml`` stays
the lower bound that Home Assistant sets. This test fails when the pin and the
interpreter that runs the tests differ, so a stale environment is noticed.
"""

import platform
import re
import tomllib
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).parents[2]
PIN_FILE = REPOSITORY_ROOT / ".python-version"
PATCH_VERSION = re.compile(r"3\.\d+\.\d+")


def _pin() -> str:
    content = PIN_FILE.read_bytes()
    assert content.endswith(b"\n")
    assert b"\r" not in content
    return content.decode("ascii").strip()


def test_pin_is_one_full_patch_version() -> None:
    """A minor version alone would let the patch level drift between systems."""
    assert PATCH_VERSION.fullmatch(_pin())


def test_pin_satisfies_the_lower_bound_of_the_project() -> None:
    """The pinned version is one the project accepts."""
    project = tomllib.loads(
        (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    bound = project["project"]["requires-python"]
    assert bound.startswith(">=")
    minimum = tuple(int(part) for part in bound.removeprefix(">=").split("."))

    assert tuple(int(part) for part in _pin().split(".")) >= minimum


def test_tests_run_on_the_pinned_version() -> None:
    """The environment was made from the pin; if not, sync it again."""
    assert platform.python_version() == _pin(), (
        "the interpreter differs from .python-version; run 'uv sync --locked'"
    )
