"""Guard: no deprecated Home Assistant name is referenced.

The names live in ``scripts/deprecated_names.toml``; that file explains the
kinds of entries. This script parses every Python file under
``custom_components/`` and ``tests/`` and fails when one of the names is
referenced. It reads the syntax tree, so a name in a comment or in a string
does not count. Every finding says why the name is deprecated and what to use
instead.

The log guard of the Home Assistant tests stays the main line of defense. This
list is the net for what the log guard cannot see: compatibility shims that
Home Assistant keeps without logging anything, and code paths no test reaches.

Limits, stated honestly. The script does not know types. An entry of kind
``attribute`` or ``mapping`` is matched by the attribute's name alone, so it
can flag an unrelated attribute of the same name; ``allowed_receivers`` lists
the objects on which the name is known to be fine. A deprecated name that is
built at runtime (``getattr`` with a computed string) is not seen.

Run it from anywhere: ``python scripts/check_deprecated_names.py``. It needs
only the standard library.
"""

import ast
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIST_FILE = Path(__file__).with_name("deprecated_names.toml")
SCANNED_FOLDERS = ("custom_components", "tests")
BEHAVIORS = {"silent", "logs"}
_KINDS = {"identifier", "module", "attribute", "mapping"}
_TEXT_FIELDS = ("kind", "name", "behavior", "reason", "replacement", "source")
_RECEIVER_FIELD = "allowed_receivers"
_KINDS_WITH_RECEIVERS = {"attribute", "mapping"}


class ListError(ValueError):
    """The list of deprecated names is malformed."""


@dataclass(frozen=True)
class Deprecated:
    """One entry of the list."""

    kind: str
    name: str
    behavior: str
    reason: str
    replacement: str
    source: str
    allowed_receivers: tuple[str, ...] = ()


@dataclass(frozen=True)
class Finding:
    """One reference to a deprecated name."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        """Render as ``path:line: message``."""
        return f"{self.path}:{self.line}: {self.message}"


def _parse_entry(raw: dict[str, Any]) -> Deprecated:
    if not set(_TEXT_FIELDS) <= set(raw) or set(raw) - {*_TEXT_FIELDS, _RECEIVER_FIELD}:
        raise ListError(
            f"the fields are {', '.join(_TEXT_FIELDS)} and, for the kinds "
            f"{sorted(_KINDS_WITH_RECEIVERS)}, {_RECEIVER_FIELD}"
        )
    if not all(isinstance(raw[f], str) and raw[f].strip() for f in _TEXT_FIELDS):
        raise ListError("every text field is a non-empty string")
    if raw["kind"] not in _KINDS:
        raise ListError(f"kind must be one of {sorted(_KINDS)}")
    if raw["behavior"] not in BEHAVIORS:
        raise ListError(f"behavior must be one of {sorted(BEHAVIORS)}")
    receivers = raw.get(_RECEIVER_FIELD, [])
    if _RECEIVER_FIELD in raw and raw["kind"] not in _KINDS_WITH_RECEIVERS:
        raise ListError(
            f"'{_RECEIVER_FIELD}' belongs to {sorted(_KINDS_WITH_RECEIVERS)}"
        )
    if not isinstance(receivers, list) or not all(
        isinstance(receiver, str) and receiver.isidentifier() for receiver in receivers
    ):
        raise ListError(f"'{_RECEIVER_FIELD}' is a list of plain names")
    texts = {field: raw[field] for field in _TEXT_FIELDS}
    return Deprecated(**texts, allowed_receivers=tuple(receivers))


def parse_list(text: str) -> list[Deprecated]:
    """Parse and validate the content of the list file."""
    content = tomllib.loads(text)
    if set(content) - {"deprecated"}:
        raise ListError("only [[deprecated]] tables are allowed")
    entries: list[Deprecated] = []
    for number, raw in enumerate(content.get("deprecated", []), start=1):
        try:
            entries.append(_parse_entry(raw))
        except ListError as error:
            raise ListError(f"entry {number}: {error}") from error
    return entries


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


def _receiver_name(node: ast.expr) -> str | None:
    """Return the last name of the object an attribute is read from.

    ``hass`` for ``hass.x``, ``hass`` as well for ``self.hass.x``; ``None`` for
    a call result or anything else without a name.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _is_access(node: ast.AST, entry: Deprecated) -> bool:
    """Tell whether ``node`` reads ``entry.name`` from a receiver not allowed."""
    return (
        isinstance(node, ast.Attribute)
        and node.attr == entry.name
        and _receiver_name(node.value) not in entry.allowed_receivers
    )


def _is_mapping_use(node: ast.AST, entry: Deprecated) -> bool:
    """Tell whether ``node`` uses ``<receiver>.<name>`` like a mapping.

    That is a subscription (``registry.devices[device_id]``) or any attribute
    of it (``registry.devices.get(...)``, ``.values()``, ``.items()``).
    Iterating it and ``len()`` are not flagged.
    """
    if isinstance(node, (ast.Subscript, ast.Attribute)):
        return _is_access(node.value, entry)
    return False


def _describe(entry: Deprecated) -> str:
    shown = {
        "attribute": f"the attribute '.{entry.name}'",
        "mapping": f"'.{entry.name}' used as a mapping",
    }.get(entry.kind, f"'{entry.name}'")
    noise = (
        "Home Assistant logs nothing about it, so no test will notice"
        if entry.behavior == "silent"
        else "Home Assistant logs a report when it is used"
    )
    return (
        f"{shown} is deprecated: {entry.reason} Use instead: {entry.replacement} "
        f"({noise}; source: {entry.source})"
    )


def check_source(source: str, path: str, entries: list[Deprecated]) -> list[Finding]:
    """Check one Python module against the list."""
    tree = ast.parse(source, filename=path)
    identifiers = {e.name: e for e in entries if e.kind == "identifier"}
    modules = [e for e in entries if e.kind == "module"]
    attributes = [e for e in entries if e.kind == "attribute"]
    mappings = [e for e in entries if e.kind == "mapping"]
    findings: list[Finding] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        found = [identifiers[i] for i in _identifiers(node) if i in identifiers]
        found += [
            e
            for module in _imported_modules(node)
            for e in modules
            if module == e.name or module.startswith(f"{e.name}.")
        ]
        found += [e for e in attributes if _is_access(node, e)]
        found += [e for e in mappings if _is_mapping_use(node, e)]
        findings += [Finding(path, line, _describe(e)) for e in found]
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
