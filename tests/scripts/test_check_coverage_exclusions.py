"""Exclusions from coverage need a reason, and the configuration is pinned."""

from pathlib import Path

import pytest

from scripts.check_coverage_exclusions import (
    EXIT_CANNOT_CHECK,
    CannotCheckError,
    configuration_problems,
    find_pragmas,
    main,
    other_configuration_files,
    pragmas_in_tree,
)

REPOSITORY_ROOT = Path(__file__).parents[2]
# Put together at runtime so that this file contains no pragma of its own.
NO_COVER = "# pragma" + ": no cover"
NO_BRANCH = "# pragma" + ": no branch"
PYPROJECT = (REPOSITORY_ROOT / "pyproject.toml").read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("comment", "kind", "reason"),
    [
        (
            f"{NO_COVER} - only evaluated by the type checker",
            "cover",
            "only evaluated by the type checker",
        ),
        (
            f"{NO_BRANCH} - the loop never ends normally",
            "branch",
            "the loop never ends normally",
        ),
        (
            f"{NO_COVER.upper()} - Reason With Three Words",
            "cover",
            "Reason With Three Words",
        ),
    ],
)
def test_pragma_with_a_reason_is_listed(comment: str, kind: str, reason: str) -> None:
    """A justified pragma is reported with its reason."""
    (pragma,) = find_pragmas(f"VALUE = 1\nif VALUE:  {comment}\n    pass\n", "x.py")

    assert (pragma.line, pragma.kind, pragma.reason) == (2, kind, reason)
    assert reason in str(pragma)


@pytest.mark.parametrize(
    "comment",
    [
        NO_COVER,
        NO_BRANCH,
        f"{NO_COVER} -",
        f"{NO_COVER} - untestable",
        f"{NO_COVER} - too short",
        f"{NO_COVER} because nobody wanted to write a test",
        f"{NO_COVER}: see above for the reason",
        "#pragma:no cover",
    ],
)
def test_pragma_without_a_reason_is_found(comment: str) -> None:
    """No reason, a reason of one or two words, or another form: not justified."""
    (pragma,) = find_pragmas(f"def f():  {comment}\n    pass\n", "x.py")

    assert pragma.reason is None
    assert "NO REASON GIVEN" in str(pragma)


def test_pragma_in_a_string_is_not_a_pragma() -> None:
    """Only comments count; coverage.py itself is stricter than that."""
    source = f'TEXT = "{NO_COVER}"\n# an ordinary comment about coverage\n'

    assert find_pragmas(source, "x.py") == []


def test_only_the_integration_is_scanned(tmp_path: Path) -> None:
    """Tests and scripts are not measured, so pragmas there do not matter."""
    for folder in ("custom_components/example", "tests"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "module.py").write_text(f"X = 1  {NO_COVER}\n", "utf-8")

    found = pragmas_in_tree(tmp_path)

    assert [pragma.path for pragma in found] == ["custom_components/example/module.py"]


def test_configuration_of_this_repository_is_the_expected_one() -> None:
    """The pinned set matches what pyproject.toml says today."""
    assert configuration_problems(PYPROJECT) == []


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ("branch = true", 'branch = true\nomit = ["*/config_flow.py"]'),
        ("branch = true", "branch = false"),
        (
            'exclude_also = ["if TYPE_CHECKING:"]',
            'exclude_also = ["if TYPE_CHECKING:", "def async_step_"]',
        ),
        ('exclude_also = ["if TYPE_CHECKING:"]', 'exclude_lines = ["def "]'),
        (
            'exclude_also = ["if TYPE_CHECKING:"]',
            'exclude_also = ["if TYPE_CHECKING:"]\npartial_branches = ["if "]',
        ),
        (
            'source = ["custom_components/roller_shutter_suite"]',
            'source = ["custom_components/roller_shutter_suite/core"]',
        ),
    ],
)
def test_changed_configuration_is_found(old: str, new: str) -> None:
    """Every way of measuring less is a finding."""
    assert old in PYPROJECT

    assert len(configuration_problems(PYPROJECT.replace(old, new))) >= 1


def test_competing_configuration_file_is_found(tmp_path: Path) -> None:
    """A ``.coveragerc`` would replace the section in pyproject.toml."""
    (tmp_path / ".coveragerc").write_text("[run]\nomit = *\n", encoding="utf-8")
    (tmp_path / "setup.cfg").write_text("[coverage:run]\nomit = *\n", encoding="utf-8")
    (tmp_path / "tox.ini").write_text("[tox]\n", encoding="utf-8")

    assert other_configuration_files(tmp_path) == [".coveragerc", "setup.cfg"]


def test_this_repository_has_no_unjustified_pragma() -> None:
    """Every pragma in the integration, if any, carries its reason."""
    assert [p for p in pragmas_in_tree(REPOSITORY_ROOT) if p.reason is None] == []


def _tree(root: Path) -> None:
    (root / "custom_components").mkdir()
    (root / "custom_components" / "module.py").write_text("X = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(PYPROJECT, encoding="utf-8")


def test_complete_tree_passes_and_names_the_number_of_files(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The counterpart of the cases below."""
    _tree(tmp_path)

    assert main(tmp_path) == 0
    assert "0 pragma(s) in the 1 Python file(s)" in capsys.readouterr().out


@pytest.mark.parametrize("removed", ["custom_components/module.py", "pyproject.toml"])
def test_incomplete_tree_cannot_be_checked(
    tmp_path: Path, removed: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """No file to search, or no configuration to compare, is a failure."""
    _tree(tmp_path)
    (tmp_path / removed).unlink()

    assert main(tmp_path) == EXIT_CANNOT_CHECK
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_file_that_cannot_be_read_as_python_cannot_be_checked(tmp_path: Path) -> None:
    """A file without tokens may hide a pragma."""
    _tree(tmp_path)
    (tmp_path / "custom_components" / "module.py").write_text("X = (\n", "utf-8")

    with pytest.raises(CannotCheckError, match="cannot be split into tokens"):
        pragmas_in_tree(tmp_path)
    assert main(tmp_path) == EXIT_CANNOT_CHECK


def test_configuration_that_is_not_toml_cannot_be_checked() -> None:
    """A broken ``pyproject.toml`` is not "no deviation"."""
    with pytest.raises(CannotCheckError, match="not valid TOML"):
        configuration_problems("= =")


@pytest.mark.parametrize(
    "text", ["tool = 1", "[tool]\ncoverage = 'x'", "[tool.coverage]\nrun = 1"]
)
def test_configuration_that_is_not_made_of_tables_cannot_be_checked(text: str) -> None:
    """A value where a table belongs ends as "could not check", not as a traceback."""
    with pytest.raises(CannotCheckError, match="is not a table"):
        configuration_problems(text)
