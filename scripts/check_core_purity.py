"""Guard: the domain core imports nothing from Home Assistant or the integration.

Everything under ``custom_components/roller_shutter_suite/core/`` is plain
Python (guardrail 4 of the project brief). This script parses every Python file
of the core package and fails when an import

- names ``homeassistant`` or one of its submodules, or
- reaches the integration outside ``core/``, either absolutely
  (``custom_components.roller_shutter_suite.const``) or relatively
  (``from .. import const``).

The imports are read from the syntax tree, so comments and strings cannot
trigger or hide a finding. Calls of ``importlib.import_module`` and
``__import__`` with a literal module name are checked as well; a module name
that is computed at runtime cannot be seen by a static check.

Run it from anywhere: ``python scripts/check_core_purity.py``. It needs only
the standard library.
"""

import ast
import sys
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_PACKAGE = "custom_components.roller_shutter_suite"
CORE_PACKAGE = f"{INTEGRATION_PACKAGE}.core"
FORBIDDEN_PACKAGE = "homeassistant"
_DYNAMIC_IMPORT_FUNCTIONS = {"import_module", "__import__"}


@dataclass(frozen=True)
class Finding:
    """One forbidden import."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        """Render as ``path:line: message``."""
        return f"{self.path}:{self.line}: {self.message}"


def _is_inside(module: str, package: str) -> bool:
    return module == package or module.startswith(f"{package}.")


def _judge(module: str) -> str | None:
    """Return why an absolute module name is forbidden, or ``None``."""
    if _is_inside(module, FORBIDDEN_PACKAGE):
        return f"the core imports '{module}' from Home Assistant"
    if _is_inside(module, "custom_components") and not _is_inside(module, CORE_PACKAGE):
        return f"the core imports '{module}' from the integration outside core/"
    return None


def _resolve_relative(package: str, level: int, module: str | None) -> str:
    """Resolve ``from <dots><module> import ...`` inside ``package``."""
    parts = package.split(".")
    base = parts[: len(parts) - (level - 1)]
    if module:
        base.append(module)
    return ".".join(base)


def _imported_modules(node: ast.ImportFrom, package: str) -> list[str]:
    """Return every module an ``from ... import ...`` statement may load.

    ``from .. import const`` loads the package two levels up and possibly its
    submodule ``const``; both are judged.
    """
    if node.level:
        origin = _resolve_relative(package, node.level, node.module)
    else:
        origin = node.module or ""
    return [origin, *(f"{origin}.{alias.name}" for alias in node.names)]


def _literal_dynamic_import(node: ast.Call) -> str | None:
    function = node.func
    name = (
        function.attr
        if isinstance(function, ast.Attribute)
        else function.id
        if isinstance(function, ast.Name)
        else None
    )
    if name not in _DYNAMIC_IMPORT_FUNCTIONS:
        return None
    named = [keyword.value for keyword in node.keywords if keyword.arg == "name"]
    if not node.args and not named:
        return None
    first = node.args[0] if node.args else named[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return None


def check_source(source: str, package: str, path: str) -> list[Finding]:
    """Check one module of the core.

    ``package`` is the dotted name of the package the module belongs to; it is
    needed to resolve relative imports.
    """
    findings: list[Finding] = []
    for node in ast.walk(ast.parse(source, filename=path)):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = _imported_modules(node, package)
        elif isinstance(node, ast.Call) and (name := _literal_dynamic_import(node)):
            modules = [name]
        for module in modules:
            if reason := _judge(module):
                findings.append(Finding(path, getattr(node, "lineno", 0), reason))
                break
    return findings


def check_tree(root: Path) -> list[Finding]:
    """Check every Python file of the core package below ``root``."""
    core_dir = root.joinpath(*CORE_PACKAGE.split("."))
    findings: list[Finding] = []
    for file in sorted(core_dir.rglob("*.py")):
        relative = file.relative_to(root)
        package_parts = relative.parent.parts
        findings += check_source(
            file.read_text(encoding="utf-8"),
            ".".join(package_parts),
            relative.as_posix(),
        )
    return findings


def main() -> int:
    """Run the guard on this repository."""
    findings = check_tree(REPOSITORY_ROOT)
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    if findings:
        sys.stdout.write(f"core purity: {len(findings)} forbidden import(s)\n")
        return 1
    sys.stdout.write("core purity: ok\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
