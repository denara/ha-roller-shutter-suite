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

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: the core package does not exist where it is expected, it contains no
Python file, or one of its files cannot be read or parsed. Exit status 1 means
forbidden imports; 0 means that the modules were really parsed, and the last
line says how many.

Anything unforeseen inside the script ends with status 2 as well, with the type
of the error only, never its text or a traceback, which may name a local path.

Run it from anywhere: ``python scripts/check_core_purity.py``. It needs only
the standard library.
"""

import ast
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
INTEGRATION_PACKAGE = "custom_components.roller_shutter_suite"
CORE_PACKAGE = f"{INTEGRATION_PACKAGE}.core"
FORBIDDEN_PACKAGE = "homeassistant"
_DYNAMIC_IMPORT_FUNCTIONS = {"import_module", "__import__"}
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


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
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as error:
        raise CannotCheckError(
            f"{path} cannot be parsed as Python ({type(error).__name__}); fix the "
            "file, its imports cannot be judged like this"
        ) from error
    for node in ast.walk(tree):
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


def core_files(root: Path) -> list[Path]:
    """Return the Python files of the core package; there has to be one."""
    core_dir = root.joinpath(*CORE_PACKAGE.split("."))
    files = sorted(core_dir.rglob("*.py")) if core_dir.is_dir() else []
    if not files:
        raise CannotCheckError(
            f"no Python file found under {'/'.join(CORE_PACKAGE.split('.'))}/. If "
            "the core has moved, change CORE_PACKAGE in this script"
        )
    return files


def check_tree(root: Path) -> list[Finding]:
    """Check every Python file of the core package below ``root``."""
    findings: list[Finding] = []
    for file in core_files(root):
        relative = file.relative_to(root)
        package_parts = relative.parent.parts
        try:
            source = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CannotCheckError(
                f"{relative.as_posix()} cannot be read ({type(error).__name__})"
            ) from error
        findings += check_source(source, ".".join(package_parts), relative.as_posix())
    return findings


def main(root: Path = REPOSITORY_ROOT) -> int:
    """Run the guard on this repository."""
    try:
        checked = len(core_files(root))
        findings = check_tree(root)
    except CannotCheckError as error:
        sys.stdout.write(f"core purity: CANNOT CHECK, so this is a failure: {error}\n")
        return EXIT_CANNOT_CHECK
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    if findings:
        sys.stdout.write(f"core purity: {len(findings)} forbidden import(s)\n")
        return EXIT_FINDINGS
    sys.stdout.write(f"core purity: ok (checked {checked} module(s) of the core)\n")
    return 0


def run(entry: Callable[[], int]) -> int:
    """Run ``entry``; an error nobody foresaw is a failure too, never a pass.

    Only the type of the error is printed. Its text and a traceback may name
    local paths, and the output of this script may be pasted in public.
    """
    try:
        return entry()
    except Exception as error:  # noqa: BLE001 - the net for every unforeseen error
        sys.stdout.write(
            "core purity: CANNOT CHECK, so this is a failure: internal error in "
            f"check_core_purity.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(main))
