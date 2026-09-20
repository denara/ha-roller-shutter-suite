"""Turn a JUnit report of pytest into a short, neutral Markdown summary.

The scheduled run against the newest Home Assistant release uses this script
for the summary page of the workflow. It lists the tests that failed and the
first lines of each failure, which for the log guard are the deprecation and
usage reports that Home Assistant logged.

"Neutral" means: directories in front of well-known folders are cut off, so a
summary names ``custom_components/...`` or ``homeassistant/...`` but never
where a checkout or an environment lives.

    uv run pytest --junitxml=report.xml
    python scripts/summarize_test_report.py report.xml "Home Assistant 2026.9.2"

The summary goes to standard output. Whether the tests failed is decided by
pytest, not by this script: a report with failures is summarized with exit
status 0.

**The script fails closed.** A summary that could not be written must not look
like "nothing to report". "Could not summarize" means here, and ends with exit
status 2: no report is named on the command line; the report is missing (pytest
did not get as far as writing it), unreadable or not XML; or it contains not a
single test. In each case the summary says so as well, so the page of the run
is never empty. Anything unforeseen inside the script ends with status 2 as
well, with the type of the error only, never its text. It needs only the standard library.
"""

import re
import sys

# The report is written by pytest in the same job, so it is trusted input.
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

MAX_LINES_PER_FAILURE = 12
_MINIMUM_ARGUMENTS = 2
EXIT_CANNOT_SUMMARIZE = 2


class CannotSummarizeError(RuntimeError):
    """There is no usable report. That is a failure, never an empty summary."""


_ANCHORS = "custom_components|homeassistant|site-packages|tests|scripts"
_PATH_PREFIX = re.compile(
    rf"(?:[A-Za-z]:)?[\\/][^\s'\":]*?[\\/](?=(?:{_ANCHORS})[\\/])"
)
_SITE_PACKAGES = re.compile(r"site-packages[\\/]")


def neutralize(text: str) -> str:
    """Remove the machine-specific part of every path in ``text``."""
    return _SITE_PACKAGES.sub("", _PATH_PREFIX.sub("", text))


def failures(report: str) -> list[tuple[str, list[str]]]:
    """Return the failed tests of a JUnit report with their first lines."""
    found: list[tuple[str, list[str]]] = []
    try:
        root = ET.fromstring(report)  # noqa: S314 - see the import above
    except ET.ParseError as error:
        raise CannotSummarizeError("The test report is not valid XML.") from error
    cases = list(root.iter("testcase"))
    if not cases:
        raise CannotSummarizeError("The test report contains not a single test.")
    for case in cases:
        for outcome in (*case.findall("failure"), *case.findall("error")):
            name = f"{case.get('classname', '')}::{case.get('name', '')}"
            text = outcome.get("message") or outcome.text or ""
            lines = [line.rstrip() for line in text.splitlines() if line.strip()]
            found.append((name, [neutralize(line) for line in lines]))
    return found


def render(report: str, title: str) -> str:
    """Render the Markdown summary."""
    found = failures(report)
    lines = [f"## {title}", ""]
    if not found:
        lines.append("All tests passed; Home Assistant logged no report about the")
        lines.append("integration and no warning was raised.")
        return "\n".join(lines) + "\n"
    lines += [
        f"**{len(found)} failed.** Deprecation and usage reports found here are",
        "fixed before the next release of the integration.",
        "",
    ]
    for name, text in found:
        lines += [f"### `{name}`", "", "```text", *text[:MAX_LINES_PER_FAILURE]]
        if len(text) > MAX_LINES_PER_FAILURE:
            lines.append(f"... ({len(text) - MAX_LINES_PER_FAILURE} more lines)")
        lines += ["```", ""]
    return "\n".join(lines)


def main(arguments: list[str]) -> int:
    """Summarize the report named on the command line."""
    if len(arguments) < _MINIMUM_ARGUMENTS:
        sys.stdout.write("usage: summarize_test_report.py <report.xml> [title]\n")
        return EXIT_CANNOT_SUMMARIZE
    path = Path(arguments[1])
    title = " ".join(arguments[2:]) or "Test run"
    try:
        try:
            report = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            raise CannotSummarizeError(
                "No readable test report was written; the tests did not get that far."
            ) from error
        summary = render(report, title)
    except CannotSummarizeError as error:
        sys.stdout.write(f"## {title}\n\n**No summary is possible.** {error}\n")
        return EXIT_CANNOT_SUMMARIZE
    sys.stdout.write(summary)
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
            "test summary: NO SUMMARY IS POSSIBLE: internal error in "
            f"summarize_test_report.py ({type(error).__name__})\n"
        )
        return EXIT_CANNOT_SUMMARIZE


if __name__ == "__main__":
    sys.exit(run(lambda: main(sys.argv)))
