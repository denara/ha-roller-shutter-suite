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

How closely a name is matched follows from what Home Assistant does when it
is used (the ``behavior`` of the entry):

- ``silent``: Home Assistant logs nothing, so this list is the only net, and
  the name is matched broadly, wherever it appears; ``allowed_receivers``
  names the objects on which an attribute of that name is known to be fine.
- ``logs``: Home Assistant logs a report, which the log guard turns into a
  failing test as soon as a test reaches the code, and coverage sees to that.
  The name is therefore matched narrowly, where Home Assistant exposes it:
  an ``identifier`` when it is imported, or read from one of the ``receivers``
  of the entry; an ``attribute`` or ``mapping`` on the ``receivers`` of the
  entry and on the result of a call (``async_get(hass).devices``); a
  ``keyword`` when it is passed to a call of the entry's ``method`` on those
  receivers. An own attribute of the same name on another object, or the
  same keyword on another call, is not reported.

Limits, stated honestly. The script does not know types. A broad entry of kind
``attribute`` or ``mapping`` is matched by the attribute's name alone, so it
can flag an unrelated attribute of the same name; a narrow entry can miss the
deprecated name on a receiver that is not on its list, and then the log guard
catches it. A deprecated name that is built at runtime (``getattr`` with a
computed string) is not seen.

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: the list file is missing, unreadable, malformed or has no entry (a
list without names checks nothing); one of the scanned folders does not exist
or holds no Python file; a Python file cannot be read or parsed. Exit status 1
means references to deprecated names; 0 means that the files were really
parsed, and the last line says how many files and how many names.

Anything unforeseen inside the script ends with status 2 as well, with the type
of the error only, never its text or a traceback, which may name a local path.

Run it from anywhere: ``python scripts/check_deprecated_names.py``. It needs
only the standard library.
"""

import ast
import os
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ``__file__`` is absolute; nothing at module level touches the file system.
REPOSITORY_ROOT = Path(__file__).parents[1]
LIST_FILE = Path(__file__).with_name("deprecated_names.toml")
SCANNED_FOLDERS = ("custom_components", "tests")
BEHAVIORS = {"silent", "logs"}
_KINDS = {"identifier", "module", "attribute", "mapping", "keyword"}
_TEXT_FIELDS = ("kind", "name", "behavior", "reason", "replacement", "source")
# Broad entries (silent) name where the attribute is fine; narrow entries
# (logs) name where the deprecated attribute is read.
_ALLOWED_FIELD = "allowed_receivers"
_RECEIVERS_FIELD = "receivers"
# A keyword argument belongs to a call of this method.
_METHOD_FIELD = "method"
_KINDS_WITH_ALLOWED = {"attribute", "mapping", "keyword"}
_KINDS_WITH_RECEIVERS = {"identifier", "attribute", "mapping", "keyword"}
_KINDS_NEEDING_RECEIVERS = {"attribute", "mapping", "keyword"}
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2


class CannotCheckError(RuntimeError):
    """The guard could not do its job. That is a failure, never a pass."""


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
    # Broad entries: where the attribute is fine. Narrow entries: where the
    # deprecated name is read. See the module documentation.
    allowed_receivers: tuple[str, ...] = ()
    receivers: tuple[str, ...] = ()
    # For a keyword: the method whose call carries it.
    method: str = ""

    @property
    def narrow(self) -> bool:
        """Tell whether the entry is matched narrowly: Home Assistant logs it."""
        return self.behavior == "logs"


@dataclass(frozen=True)
class Finding:
    """One reference to a deprecated name."""

    path: str
    line: int
    message: str

    def __str__(self) -> str:
        """Render as ``path:line: message``."""
        return f"{self.path}:{self.line}: {self.message}"


def _names(raw: dict[str, Any], field: str) -> tuple[str, ...]:
    """Return the list of plain names under ``field``, empty if absent."""
    names = raw.get(field, [])
    if not isinstance(names, list) or not all(
        isinstance(name, str) and name.isidentifier() for name in names
    ):
        raise ListError(f"'{field}' is a list of plain names")
    return tuple(names)


def _parse_entry(raw: dict[str, Any]) -> Deprecated:
    known = {*_TEXT_FIELDS, _ALLOWED_FIELD, _RECEIVERS_FIELD, _METHOD_FIELD}
    if not set(_TEXT_FIELDS) <= set(raw) or set(raw) - known:
        raise ListError(
            f"the fields are {', '.join(_TEXT_FIELDS)}; a silent entry of the kinds "
            f"{sorted(_KINDS_WITH_ALLOWED)} may add {_ALLOWED_FIELD}, an entry that "
            f"logs, of the kinds {sorted(_KINDS_WITH_RECEIVERS)}, {_RECEIVERS_FIELD}; "
            f"a keyword names its {_METHOD_FIELD}"
        )
    if not all(isinstance(raw[f], str) and raw[f].strip() for f in _TEXT_FIELDS):
        raise ListError("every text field is a non-empty string")
    if raw["kind"] not in _KINDS:
        raise ListError(f"kind must be one of {sorted(_KINDS)}")
    method = raw.get(_METHOD_FIELD, "")
    if (raw["kind"] == "keyword") != (_METHOD_FIELD in raw) or not (
        isinstance(method, str) and (method.isidentifier() or _METHOD_FIELD not in raw)
    ):
        raise ListError(
            f"'{_METHOD_FIELD}' is a plain name and belongs to a keyword, which needs it"
        )
    if raw["behavior"] not in BEHAVIORS:
        raise ListError(f"behavior must be one of {sorted(BEHAVIORS)}")
    narrow = raw["behavior"] == "logs"
    if _ALLOWED_FIELD in raw and (narrow or raw["kind"] not in _KINDS_WITH_ALLOWED):
        raise ListError(
            f"'{_ALLOWED_FIELD}' belongs to silent entries of the kinds "
            f"{sorted(_KINDS_WITH_ALLOWED)}; an entry that logs is matched narrowly "
            f"and names its '{_RECEIVERS_FIELD}' instead"
        )
    if _RECEIVERS_FIELD in raw and (
        not narrow or raw["kind"] not in _KINDS_WITH_RECEIVERS
    ):
        raise ListError(
            f"'{_RECEIVERS_FIELD}' belongs to entries that log, of the kinds "
            f"{sorted(_KINDS_WITH_RECEIVERS)}"
        )
    receivers = _names(raw, _RECEIVERS_FIELD)
    if narrow and raw["kind"] in _KINDS_NEEDING_RECEIVERS and not receivers:
        raise ListError(
            f"an entry that logs, of the kinds {sorted(_KINDS_NEEDING_RECEIVERS)}, "
            f"names at least one of the '{_RECEIVERS_FIELD}' on which the name is read"
        )
    texts = {field: raw[field] for field in _TEXT_FIELDS}
    return Deprecated(
        **texts,
        allowed_receivers=_names(raw, _ALLOWED_FIELD),
        receivers=receivers,
        method=method,
    )


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


def _is_access(node: ast.AST, entry: Deprecated, name: str | None = None) -> bool:
    """Tell whether ``node`` reads ``name`` where the entry reports it.

    ``name`` is the entry's name unless given (the method of a keyword). A
    broad entry is read everywhere except on its allowed receivers. A narrow
    entry is read on its receivers and on the result of a call, which has no
    name: ``async_get(hass).devices``.
    """
    if not isinstance(node, ast.Attribute) or node.attr != (name or entry.name):
        return False
    receiver = _receiver_name(node.value)
    if entry.narrow:
        return receiver in entry.receivers or isinstance(node.value, ast.Call)
    return receiver not in entry.allowed_receivers


def _is_keyword_use(node: ast.AST, entry: Deprecated) -> bool:
    """Tell whether ``node`` calls the entry's method with the keyword ``entry.name``.

    The call has to be a call of the method on a receiver the entry reports,
    ``device_registry.async_update_device(..., merge_identifiers=...)``; the
    same keyword on any other call is not the deprecated one.
    """
    return (
        isinstance(node, ast.Call)
        and _is_access(node.func, entry, entry.method)
        and any(keyword.arg == entry.name for keyword in node.keywords)
    )


def _is_narrow_identifier_use(node: ast.AST, entry: Deprecated) -> bool:
    """Tell whether ``node`` imports ``entry.name`` or reads it from a receiver."""
    if isinstance(node, ast.alias):
        return node.name.rsplit(".", 1)[-1] == entry.name
    return (
        isinstance(node, ast.Attribute)
        and node.attr == entry.name
        and _receiver_name(node.value) in entry.receivers
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
        "keyword": f"the keyword argument '{entry.name}' of '.{entry.method}()'",
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
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError) as error:
        raise CannotCheckError(
            f"{path} cannot be parsed as Python ({type(error).__name__}); fix the "
            "file, its names cannot be judged like this"
        ) from error
    identifiers = {
        e.name: e for e in entries if e.kind == "identifier" and not e.narrow
    }
    narrow_identifiers = [e for e in entries if e.kind == "identifier" and e.narrow]
    modules = [e for e in entries if e.kind == "module"]
    attributes = [e for e in entries if e.kind == "attribute"]
    mappings = [e for e in entries if e.kind == "mapping"]
    keywords = [e for e in entries if e.kind == "keyword"]
    findings: list[Finding] = []
    for node in ast.walk(tree):
        line = getattr(node, "lineno", 0)
        found = [identifiers[i] for i in _identifiers(node) if i in identifiers]
        found += [e for e in narrow_identifiers if _is_narrow_identifier_use(node, e)]
        found += [e for e in keywords if _is_keyword_use(node, e)]
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


def _exists(path: Path, shown: str) -> bool:
    """Tell whether a path exists; an error other than "not there" is not a "no".

    ``Path.exists`` and its relatives answer ``False`` for every error of the
    operating system, so a file that cannot be examined would look absent.
    """
    try:
        path.lstat()
    except FileNotFoundError, NotADirectoryError:
        return False
    except OSError as error:
        raise CannotCheckError(
            f"{shown} cannot be examined ({type(error).__name__})"
        ) from error
    return True


def _walk(folder: Path, shown: str, wanted: Callable[[str], bool]) -> list[Path]:
    """Return the wanted files below ``folder``, sorted; empty if it is not there.

    ``Path.rglob`` passes over a folder it cannot read without a word, and the
    files in it would simply not be checked. Here such a folder is a failure.
    """
    if not _exists(folder, shown):
        return []

    def refuse(error: OSError) -> None:
        raise CannotCheckError(
            f"a folder under {shown}/ cannot be listed ({type(error).__name__})"
        ) from error

    found: list[Path] = []
    for directory, _folders, names in os.walk(folder, onerror=refuse):
        found += [Path(directory) / name for name in names if wanted(name)]
    return sorted(found)


def _is_python(name: str) -> bool:
    return name.endswith(".py")


def scanned_files(root: Path) -> list[Path]:
    """Return the Python files to check; every scanned folder has to hold one."""
    files: list[Path] = []
    for folder in SCANNED_FOLDERS:
        found = _walk(root / folder, folder, _is_python)
        if not found:
            raise CannotCheckError(
                f"no Python file found under {folder}/. If the folder has moved, "
                "change SCANNED_FOLDERS in this script"
            )
        files += found
    return files


def check_tree(root: Path, entries: list[Deprecated]) -> list[Finding]:
    """Check every Python file in the scanned folders below ``root``."""
    findings: list[Finding] = []
    for file in scanned_files(root):
        relative = file.relative_to(root).as_posix()
        try:
            source = file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CannotCheckError(
                f"{relative} cannot be read ({type(error).__name__})"
            ) from error
        findings += check_source(source, relative, entries)
    return findings


def load_list(list_file: Path) -> list[Deprecated]:
    """Read the list file; a list that cannot be used cannot check anything."""
    try:
        entries = parse_list(list_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(
            f"{list_file.name} cannot be read ({type(error).__name__}); it belongs "
            "next to this script"
        ) from error
    except (ListError, tomllib.TOMLDecodeError) as error:
        raise CannotCheckError(f"{list_file.name} is not valid: {error}") from error
    if not entries:
        raise CannotCheckError(
            f"{list_file.name} has no entry, so nothing would be checked"
        )
    return entries


def main(root: Path = REPOSITORY_ROOT, list_file: Path = LIST_FILE) -> int:
    """Run the guard on this repository."""
    try:
        entries = load_list(list_file)
        checked = len(scanned_files(root))
        findings = check_tree(root, entries)
    except CannotCheckError as error:
        sys.stdout.write(
            f"deprecated names: CANNOT CHECK, so this is a failure: {error}\n"
        )
        return EXIT_CANNOT_CHECK
    for finding in findings:
        sys.stdout.write(f"{finding}\n")
    if findings:
        sys.stdout.write(f"deprecated names: {len(findings)} reference(s)\n")
        return EXIT_FINDINGS
    sys.stdout.write(
        f"deprecated names: ok (checked {checked} file(s) against "
        f"{len(entries)} names on the list)\n"
    )
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
            "deprecated names: CANNOT CHECK, so this is a failure: internal error in "
            f"check_deprecated_names.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(main))
