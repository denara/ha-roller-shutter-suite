"""Guard: no deprecated Home Assistant name is referenced.

The names live in ``scripts/deprecated_names.toml``; that file explains the
three kinds of entries. This script parses every Python file under
``custom_components/`` and ``tests/`` and fails when one of the names is
referenced. It reads the syntax tree, so a name in a comment or in a string
does not count.

Limits, stated honestly: an entry of kind ``attribute`` is only found on the
owning class itself and on variables and parameters that are annotated with
that class. An attribute access on an unannotated value cannot be attributed
to a class without running a type checker. The log guard of the Home Assistant
tests stays the main line of defense; this list catches what Home Assistant
does not log.

Run it from anywhere: ``python scripts/check_deprecated_names.py``. It needs
only the standard library.
"""

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIST_FILE = Path(__file__).with_name("deprecated_names.toml")
SCANNED_FOLDERS = ("custom_components", "tests")
_KINDS = {"identifier", "module", "attribute"}
_REQUIRED_FIELDS = {"kind", "name", "reason", "replacement"}


class ListError(ValueError):
    """The list of deprecated names is malformed."""


@dataclass(frozen=True)
class Deprecated:
    """One entry of the list."""

    kind: str
    name: str
    reason: str
    replacement: str
    owner: str | None = None


@dataclass(frozen=True)
class Finding:
    """One reference to a deprecated name."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        """Render as ``path:line: message``."""
        return f"{self.path}:{self.line}: {self.message}"


def parse_list(text: str) -> list[Deprecated]:
    """Parse and validate the content of the list file."""
    content = tomllib.loads(text)
    if set(content) - {"deprecated"}:
        raise ListError("only [[deprecated]] tables are allowed")
    entries: list[Deprecated] = []
    for number, raw in enumerate(content.get("deprecated", []), start=1):
        allowed = _REQUIRED_FIELDS | {"owner"}
        if not set(raw) >= _REQUIRED_FIELDS or set(raw) - allowed:
            raise ListError(f"entry {number}: fields must be {sorted(allowed)}")
        if not all(isinstance(value, str) and value for value in raw.values()):
            raise ListError(f"entry {number}: every field is a non-empty string")
        if raw["kind"] not in _KINDS:
            raise ListError(f"entry {number}: kind must be one of {sorted(_KINDS)}")
        if (raw["kind"] == "attribute") != ("owner" in raw):
            raise ListError(f"entry {number}: 'owner' belongs to kind 'attribute'")
        entries.append(Deprecated(**raw))
    return entries


def _annotated_class_names(annotation: ast.expr | None) -> set[str]:
    """Return the class names an annotation mentions, without their module."""
    if annotation is None:
        return set()
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return set()
    names: set[str] = set()
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return names


def _variables_annotated_with(tree: ast.AST, owner: str) -> set[str]:
    variables: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.arg) and owner in _annotated_class_names(
            node.annotation
        ):
            variables.add(node.arg)
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and owner in _annotated_class_names(node.annotation)
        ):
            variables.add(node.target.id)
    return variables


def _identifiers(node: ast.AST) -> list[str]:
    """Return the identifiers a syntax node introduces or references."""
    if isinstance(node, ast.Name):
        return [node.id]
    if isinstance(node, ast.Attribute):
        return [node.attr]
    if isinstance(node, ast.alias):
        return [node.name.rsplit(".", 1)[-1], *([node.asname] if node.asname else [])]
    if isinstance(node, (ast.keyword, ast.arg)):
        return [node.arg] if node.arg else []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return [node.name]
    return []


def _imported_modules(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and not node.level and node.module:
        return [node.module]
    return []


def _describe(entry: Deprecated) -> str:
    shown = f"{entry.owner}.{entry.name}" if entry.owner else entry.name
    return f"'{shown}' is deprecated: {entry.reason} Use instead: {entry.replacement}"


def check_source(source: str, path: str, entries: list[Deprecated]) -> list[Finding]:
    """Check one Python module against the list."""
    tree = ast.parse(source, filename=path)
    identifiers = {e.name: e for e in entries if e.kind == "identifier"}
    modules = [e for e in entries if e.kind == "module"]
    attributes = [
        (e, {e.owner, *_variables_annotated_with(tree, e.owner)})
        for e in entries
        if e.kind == "attribute" and e.owner
    ]
    findings: list[Finding] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        for identifier in _identifiers(node):
            if identifier in identifiers:
                findings.append(Finding(path, line, _describe(identifiers[identifier])))
        for module in _imported_modules(node):
            findings += [
                Finding(path, line, _describe(e))
                for e in modules
                if module == e.name or module.startswith(f"{e.name}.")
            ]
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
            findings += [
                Finding(path, line, _describe(e))
                for e, holders in attributes
                if node.attr == e.name and node.value.id in holders
            ]
    return findings


def check_tree(root: Path, entries: list[Deprecated]) -> list[Finding]:
    """Check every Python file in the scanned folders below ``root``."""
    findings: list[Finding] = []
    for folder in SCANNED_FOLDERS:
        for file in sorted((root / folder).rglob("*.py")):
            findings += check_source(
                file.read_text(encoding="utf-8"),
                file.relative_to(root).as_posix(),
                entries,
            )
    return findings


def main() -> int:
    """Run the guard on this repository."""
    try:
        entries = parse_list(LIST_FILE.read_text(encoding="utf-8"))
    except (ListError, tomllib.TOMLDecodeError) as error:
        sys.stdout.write(f"{LIST_FILE.name}: {error}\n")
        return 1
    findings = check_tree(REPOSITORY_ROOT, entries)
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    if findings:
        sys.stdout.write(f"deprecated names: {len(findings)} reference(s)\n")
        return 1
    sys.stdout.write(f"deprecated names: ok ({len(entries)} names on the list)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
