"""Guard: ``tests/foreign_warnings.toml`` exempts only warnings of other packages.

The file is the one way out for warnings that this integration does not cause
(see "No deprecation, ever" in ``tasks/README.md``). ``tests/conftest.py`` turns
its entries into warning filters and uses :func:`parse_entries` of this module
to read it, so a test run refuses an invalid file as well.

Every entry needs exactly four fields:

- ``module``: a regular expression for the module that triggers the warning.
  Python matches it against the start of the module name. It must not match
  this integration, its tests, or the Home Assistant helpers that report
  deprecated usage, it must not match every module, and it must not contain a
  colon, which pytest reads as the end of the pattern.
- ``category``: the warning class, as a built-in name or a dotted path. The
  base class ``Warning`` is refused, because it covers every warning.
- ``reason``: why the warning exists and cannot be avoided here.
- ``upstream``: an ``https`` link to the upstream issue or change.

**The guard fails closed.** "Could not check" means here, and ends with exit
status 2: the list file is missing, unreadable or not valid TOML (an empty
list is a file without entries, not a missing file), or one of the folders of this repository
holds no Python file, so that "must not match this repository" would compare
with nothing. A file that is TOML but holds an invalid entry, or anything but
``[[warning]]`` tables, ends with exit status 1: that is a finding about its
content. With 0 the last
line says how many entries were checked against how many module names; zero
entries is the normal state.

Anything unforeseen inside the script ends with status 2 as well, with the type
of the error only, never its text or a traceback, which may name a local path.

Run it from anywhere: ``python scripts/check_foreign_warnings.py``. It needs
only the standard library.
"""

import re
import sys
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
LIST_FILE = "tests/foreign_warnings.toml"
FIELDS = ("module", "category", "reason", "upstream")
_OWN_FOLDERS = ("custom_components", "tests", "scripts")
_PROTECTED_HELPERS = (
    "homeassistant.helpers.frame",
    "homeassistant.helpers.deprecation",
)
# A pattern that matches one of these matches (nearly) every module.
_CATCH_ALL_PROBES = ("", "a", "zz_unrelated_package.module")
_TOO_BROAD_CATEGORIES = {"Warning", "Exception", "BaseException"}
_CATEGORY = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*")
EXIT_FINDINGS = 1
EXIT_CANNOT_CHECK = 2


class EntryError(ValueError):
    """The list of foreign warnings is invalid."""


class CannotCheckError(EntryError):
    """The guard could not do its job. That is a failure, never a pass.

    It is an :class:`EntryError`, so a test run (``tests/conftest.py``) refuses
    to start in this case as well.
    """


@dataclass(frozen=True)
class ForeignWarning:
    """One approved exemption."""

    module: str
    category: str
    reason: str
    upstream: str

    def as_filter(self) -> str:
        """Return the entry in the syntax of pytest's ``filterwarnings``."""
        return f"ignore::{self.category}:{self.module}"


def own_module_names(root: Path) -> list[str]:
    """Return the module names that belong to this repository.

    Each module is listed with its dotted path from the repository root and
    with its bare name, because pytest may import a test module under either.
    """
    names: set[str] = set(_OWN_FOLDERS)
    for folder in _OWN_FOLDERS:
        files = sorted((root / folder).rglob("*.py"))
        if not files:
            raise CannotCheckError(
                f"no Python file found under {folder}/, so no pattern could be "
                "compared with the modules of this repository. If the folder has "
                "moved, change _OWN_FOLDERS in this script"
            )
        for file in files:
            parts = list(file.relative_to(root).with_suffix("").parts)
            if parts[-1] == "__init__":
                parts.pop()
            names.update(".".join(parts[:end]) for end in range(1, len(parts) + 1))
            names.add(parts[-1])
    return sorted(names)


def _check_module_pattern(pattern: str, protected: list[str]) -> None:
    if ":" in pattern:
        raise EntryError(
            "'module' must not contain a colon: pytest separates the parts of a "
            "filter with colons. Write a group as (a|b), not as (?:a|b)"
        )
    try:
        compiled = re.compile(pattern)
    except re.error as error:
        raise EntryError(f"'module' is not a regular expression: {error}") from error
    if any(compiled.match(probe) for probe in _CATCH_ALL_PROBES):
        raise EntryError("'module' matches every module; name the foreign package")
    for name in protected:
        if compiled.match(name):
            raise EntryError(
                f"'module' matches '{name}', which is not a foreign module. A "
                "warning that this integration causes is fixed, not exempted"
            )


def _check_entry(raw: object, protected: list[str]) -> ForeignWarning:
    if not isinstance(raw, dict) or set(raw) != set(FIELDS):
        raise EntryError(f"the fields must be exactly {', '.join(FIELDS)}")
    if not all(isinstance(raw[f], str) and raw[f].strip() for f in FIELDS):
        raise EntryError("every field is a non-empty string")
    entry = ForeignWarning(**{field: raw[field] for field in FIELDS})
    _check_module_pattern(entry.module, protected)
    if not _CATEGORY.fullmatch(entry.category):
        raise EntryError("'category' is a class name such as DeprecationWarning")
    if entry.category.rsplit(".", 1)[-1] in _TOO_BROAD_CATEGORIES:
        raise EntryError(
            f"'category' {entry.category} covers every warning of the module; "
            "name the class of the one warning, such as DeprecationWarning"
        )
    link = urlsplit(entry.upstream)
    if link.scheme != "https" or "." not in link.netloc:
        raise EntryError("'upstream' must be an https URL")
    return entry


def parse_entries(text: str, own_modules: list[str]) -> list[ForeignWarning]:
    """Parse and validate the content of the list file."""
    try:
        content = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CannotCheckError(f"not valid TOML: {error}") from error
    if set(content) - {"warning"}:
        raise EntryError("only [[warning]] tables are allowed")
    raw_entries = content.get("warning", [])
    if not isinstance(raw_entries, list):
        raise EntryError("'warning' must be an array of tables: [[warning]]")
    protected = [*own_modules, *_PROTECTED_HELPERS]
    entries: list[ForeignWarning] = []
    for number, raw in enumerate(raw_entries, start=1):
        try:
            entries.append(_check_entry(raw, protected))
        except EntryError as error:
            raise EntryError(f"entry {number}: {error}") from error
    return entries


def load_entries(root: Path = REPOSITORY_ROOT) -> list[ForeignWarning]:
    """Read and validate the list of this repository."""
    try:
        text = (root / LIST_FILE).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CannotCheckError(
            f"the file cannot be read ({type(error).__name__}). An empty list is "
            "a file with comments only, not a missing file"
        ) from error
    return parse_entries(text, own_module_names(root))


def main(root: Path = REPOSITORY_ROOT) -> int:
    """Run the guard on this repository."""
    try:
        entries = load_entries(root)
        compared = len(own_module_names(root))
    except CannotCheckError as error:
        sys.stdout.write(
            f"foreign warnings: CANNOT CHECK, so this is a failure: {LIST_FILE}: "
            f"{error}\n"
        )
        return EXIT_CANNOT_CHECK
    except EntryError as error:
        sys.stdout.write(f"{LIST_FILE}: {error}\n")
        return EXIT_FINDINGS
    sys.stdout.write(
        f"foreign warnings: ok ({len(entries)} entries, each compared with "
        f"{compared} module names of this repository)\n"
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
            "foreign warnings: CANNOT CHECK, so this is a failure: internal error in "
            f"check_foreign_warnings.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_CHECK


if __name__ == "__main__":
    sys.exit(run(main))
