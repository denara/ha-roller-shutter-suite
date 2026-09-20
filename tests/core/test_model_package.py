"""The model is a package with one import surface and one-way dependencies."""

import ast
import importlib
from pathlib import Path

from custom_components.roller_shutter_suite.core import model

PACKAGE_DIR = (
    Path(__file__).parents[2]
    / "custom_components"
    / "roller_shutter_suite"
    / "core"
    / "model"
)

# A module may import only from modules that stand before it in this list.
ORDER = [
    "_validation",
    "_data",
    "values",
    "functions",
    "window",
    "decision",
    "observation",
    "state",
    "snapshot",
]


def test_every_public_name_is_exported_by_the_package() -> None:
    """``from ...core.model import X`` works for every public name of a module."""
    exported = set(model.__all__)
    defined: set[str] = set()
    for name in ORDER:
        if name.startswith("_"):
            continue
        module = importlib.import_module(f"{model.__name__}.{name}")
        defined |= {
            attribute
            for attribute, value in vars(module).items()
            if not attribute.startswith("_")
            and getattr(value, "__module__", module.__name__) == module.__name__
            and attribute[0].isupper()
        }

    assert defined <= exported
    assert exported - defined == {"JsonObject", "JsonValue"}
    assert sorted(model.__all__) == sorted(exported)
    for name in model.__all__:
        assert hasattr(model, name)


def test_the_modules_of_the_package_are_the_expected_ones() -> None:
    """A new module has to be given its place in the dependency order."""
    found = {path.stem for path in PACKAGE_DIR.glob("*.py")} - {"__init__"}

    assert found == set(ORDER)


def test_dependencies_inside_the_package_run_one_way() -> None:
    """No module imports from a module that stands after it; so there is no cycle."""
    for position, name in enumerate(ORDER):
        tree = ast.parse((PACKAGE_DIR / f"{name}.py").read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1:
                assert node.module in ORDER[:position], (name, node.module)
            if isinstance(node, ast.ImportFrom) and node.level > 1:
                raise AssertionError((name, node.module))
            if isinstance(node, ast.ImportFrom) and node.level == 0:
                assert node.module is not None
                inside = node.module.startswith(model.__name__)
                assert not inside, (name, node.module)
