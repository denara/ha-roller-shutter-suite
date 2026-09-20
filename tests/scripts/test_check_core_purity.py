"""The core purity guard sees forbidden imports in both directions."""

import re
from pathlib import Path

import pytest

from scripts.check_core_purity import (
    CORE_PACKAGE,
    EXIT_CANNOT_CHECK,
    CannotCheckError,
    check_source,
    check_tree,
    main,
)

SUBPACKAGE = f"{CORE_PACKAGE}.model"


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ("import homeassistant", CORE_PACKAGE),
        ("import homeassistant.core as ha", CORE_PACKAGE),
        ("from homeassistant.const import STATE_ON", CORE_PACKAGE),
        ("from homeassistant import core", CORE_PACKAGE),
        ("def f():\n    from homeassistant.util import dt\n", CORE_PACKAGE),
        (
            "import importlib\nimportlib.import_module('homeassistant.core')",
            CORE_PACKAGE,
        ),
        ("__import__('homeassistant')", CORE_PACKAGE),
        (
            "from importlib import import_module\nimport_module(name='homeassistant')",
            CORE_PACKAGE,
        ),
        ("__import__(name='homeassistant.core')", CORE_PACKAGE),
        ("from .. import const", CORE_PACKAGE),
        ("from ..const import DOMAIN", CORE_PACKAGE),
        ("from ... import const", SUBPACKAGE),
        ("from ...const import DOMAIN", SUBPACKAGE),
        ("import custom_components.roller_shutter_suite.const", CORE_PACKAGE),
        ("from custom_components.roller_shutter_suite import const", CORE_PACKAGE),
        ("from custom_components.roller_shutter_suite.const import X", CORE_PACKAGE),
        ("import custom_components.other_integration", CORE_PACKAGE),
    ],
)
def test_forbidden_import_is_found(source: str, package: str) -> None:
    """Imports of Home Assistant and of the integration outside core/ fail."""
    findings = check_source(source, package, "example.py")

    assert len(findings) == 1
    assert findings[0].path == "example.py"


@pytest.mark.parametrize(
    ("source", "package"),
    [
        ("import dataclasses\nfrom datetime import datetime", CORE_PACKAGE),
        ("import astral.sun", CORE_PACKAGE),
        ("from . import model", CORE_PACKAGE),
        ("from .model import Window", CORE_PACKAGE),
        ("from .. import ports", SUBPACKAGE),
        ("from ..ports import Clock", SUBPACKAGE),
        (f"from {CORE_PACKAGE} import model", CORE_PACKAGE),
        (f"import {CORE_PACKAGE}.model", CORE_PACKAGE),
        (
            "# import homeassistant\nTEXT = 'from homeassistant import core'",
            CORE_PACKAGE,
        ),
        ("import homeassistant_lookalike", CORE_PACKAGE),
    ],
)
def test_allowed_import_passes(source: str, package: str) -> None:
    """The standard library, libraries and the core itself are allowed."""
    assert check_source(source, package, "example.py") == []


def test_tree_is_checked_with_the_package_of_each_file(tmp_path: Path) -> None:
    """Relative imports are resolved from where the file lies."""
    core = tmp_path.joinpath(*CORE_PACKAGE.split("."))
    (core / "model").mkdir(parents=True)
    (core / "__init__.py").write_text("from . import model\n", encoding="utf-8")
    (core / "model" / "__init__.py").write_text(
        "from .. import ports\nfrom ... import const\n", encoding="utf-8"
    )
    outside = core.parent / "sensor.py"
    outside.write_text("import homeassistant\n", encoding="utf-8")

    findings = check_tree(tmp_path)

    assert [(finding.path, finding.line) for finding in findings] == [
        ("custom_components/roller_shutter_suite/core/model/__init__.py", 2)
    ]


def test_this_repository_passes() -> None:
    """The core of this repository is pure."""
    assert check_tree(Path(__file__).parents[2]) == []


def test_missing_core_cannot_be_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A core that is not where the guard looks is a failure, not zero findings."""
    with pytest.raises(CannotCheckError, match="no Python file found"):
        check_tree(tmp_path)

    assert main(tmp_path) == EXIT_CANNOT_CHECK
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_module_that_cannot_be_parsed_cannot_be_checked(tmp_path: Path) -> None:
    """A syntax error hides every import of the file."""
    core = tmp_path.joinpath(*CORE_PACKAGE.split("."))
    core.mkdir(parents=True)
    (core / "broken.py").write_text("import (\n", encoding="utf-8")

    assert main(tmp_path) == EXIT_CANNOT_CHECK


def test_pass_says_how_many_modules_were_checked(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A pass over nothing would say "0 modules", and cannot happen anyway."""
    assert main() == 0
    assert re.search(r"ok \(checked [1-9]\d* module", capsys.readouterr().out)
