"""The summary of the scheduled run names failures without machine details.

The example paths are put together at runtime, because this file is scanned by
the instance data guard. They are made up.
"""

from pathlib import Path

from scripts.summarize_test_report import main, neutralize, render

CHECKOUT = "/home" + "/runner/work/example/example"
WINDOWS_CHECKOUT = "D" + ":\\" + "work\\example"
ENVIRONMENT = CHECKOUT + "/.venv/lib/python3.14/site-packages"

FAILED = f"""<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="2" failures="1">
<testcase classname="tests.ha.test_config_entry" name="test_entry_sets_up">
<failure message="Home Assistant logged a deprecation or usage report about
 'roller_shutter_suite':&#10;homeassistant.helpers.frame: Detected that custom
 integration 'roller_shutter_suite' does something at
 {CHECKOUT}/custom_components/roller_shutter_suite/cover.py, line 12">details
</failure>
</testcase>
<testcase classname="tests.ha.test_harness" name="test_other" />
</testsuite></testsuites>
"""
PASSED = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="1">
<testcase classname="tests.core.test_core_package" name="test_x" />
</testsuite></testsuites>
"""


def test_paths_lose_their_machine_specific_part() -> None:
    """What remains starts at a folder everybody knows."""
    assert (
        neutralize(f"at {CHECKOUT}/custom_components/example/cover.py, line 3")
        == "at custom_components/example/cover.py, line 3"
    )
    assert (
        neutralize(f'File "{ENVIRONMENT}/homeassistant/helpers/frame.py"')
        == 'File "homeassistant/helpers/frame.py"'
    )
    assert (
        neutralize(f"{WINDOWS_CHECKOUT}\\tests\\ha\\test_example.py:7")
        == "tests\\ha\\test_example.py:7"
    )
    assert neutralize("no path in here") == "no path in here"


def test_failed_run_lists_the_test_and_the_report() -> None:
    """The summary shows which test failed and what Home Assistant logged."""
    summary = render(FAILED, "Home Assistant 2099.1.0")

    assert "## Home Assistant 2099.1.0" in summary
    assert "**1 failed.**" in summary
    assert "tests.ha.test_config_entry::test_entry_sets_up" in summary
    assert "Detected that custom" in summary
    assert "custom_components/roller_shutter_suite/cover.py, line 12" in summary
    assert CHECKOUT not in summary
    assert "test_other" not in summary


def test_passed_run_says_so() -> None:
    """A green run gets a summary too, so the page is never empty."""
    summary = render(PASSED, "Home Assistant 2099.1.0")

    assert "All tests passed" in summary


def test_missing_report_does_not_fail_the_step(tmp_path: Path) -> None:
    """When pytest could not even start, the summary step stays quiet."""
    assert main(["summarize_test_report.py", str(tmp_path / "none.xml"), "Title"]) == 0
