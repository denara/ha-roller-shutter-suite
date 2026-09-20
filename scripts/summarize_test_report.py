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

The summary goes to standard output. The exit code is always 0; whether the
run failed is decided by pytest, not by this script. It needs only the standard
library.
"""

import re
import sys

# The report is written by pytest in the same job, so it is trusted input.
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_LINES_PER_FAILURE = 12
_MINIMUM_ARGUMENTS = 2
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
    root = ET.fromstring(report)  # noqa: S314 - see the import above
    for case in root.iter("testcase"):
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
        return 0
    path = Path(arguments[1])
    title = " ".join(arguments[2:]) or "Test run"
    if not path.is_file():
        sys.stdout.write(f"## {title}\n\nNo test report was written.\n")
        return 0
    sys.stdout.write(render(path.read_text(encoding="utf-8"), title))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
