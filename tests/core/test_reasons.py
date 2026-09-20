"""The reason codes are exactly those of the architecture document."""

import re
from pathlib import Path

import pytest

from custom_components.roller_shutter_suite.core.reasons import (
    ReasonCategory,
    ReasonCode,
    codes_of,
)

ARCHITECTURE = Path(__file__).parents[2] / "docs" / "architecture.md"

# The bold lead-in of each paragraph of section 5, and the group it defines.
GROUP_HEADINGS = {
    "Winning or contributing layers:": ReasonCategory.LAYER,
    "Why a layer did not act:": ReasonCategory.LAYER_INACTIVE,
    "Constraints:": ReasonCategory.CONSTRAINT,
    "Gate:": ReasonCategory.GATE,
    "Tracker and life cycle (events only):": ReasonCategory.EVENT,
}


def _documented_codes() -> dict[ReasonCategory, list[str]]:
    """Read the code lists of section 5 from the architecture document."""
    text = ARCHITECTURE.read_text(encoding="utf-8")
    section = text.split("## 5. Reason codes", 1)[1].split("\n## ", 1)[0]
    documented: dict[ReasonCategory, list[str]] = {}
    for line in section.splitlines():
        match = re.match(r"\*\*(?P<heading>[^*]+)\*\* (?P<codes>.+)", line)
        if match is None:
            continue
        category = GROUP_HEADINGS[match["heading"]]
        documented[category] = re.findall(r"`([a-z_]+)`", match["codes"])
    return documented


def test_every_group_of_the_document_is_found() -> None:
    """The parser of this test sees all five paragraphs of section 5."""
    assert set(_documented_codes()) == set(ReasonCategory)


@pytest.mark.parametrize("category", list(ReasonCategory))
def test_codes_of_a_group_match_the_document_in_content_and_order(
    category: ReasonCategory,
) -> None:
    """Each group holds the documented codes, in the documented order."""
    assert [code.value for code in codes_of(category)] == _documented_codes()[category]


def test_the_enumeration_is_closed_over_the_documented_codes() -> None:
    """No code exists that the document does not list, and none is missing."""
    documented = [code for codes in _documented_codes().values() for code in codes]

    assert [code.value for code in ReasonCode] == documented
    assert len(set(documented)) == len(documented)


def test_every_code_knows_its_category() -> None:
    """The category of a code is the group that lists it."""
    for category in ReasonCategory:
        for code in codes_of(category):
            assert code.category is category
    assert ReasonCode.SENT.category is ReasonCategory.GATE
    assert ReasonCode.CAPABILITY_MISSING.category is ReasonCategory.LAYER_INACTIVE


def test_a_code_is_its_string_and_the_name_follows_the_value() -> None:
    """Codes serialize as their value; names are the upper-case value."""
    assert ReasonCode.FIRE_ALARM.value == "fire_alarm"
    assert str(ReasonCode.FIRE_ALARM) == "fire_alarm"
    assert ReasonCode("dry_run") is ReasonCode.DRY_RUN
    for code in ReasonCode:
        assert code.name == code.value.upper()


def test_an_unknown_code_is_rejected() -> None:
    """The enumeration is closed: free text is not a reason code."""
    with pytest.raises(ValueError, match="arrived"):
        ReasonCode("arrived")


def test_no_code_claims_that_a_curtain_arrived() -> None:
    """Honest wording: there is no "confirmed", "arrived" or "reached position"."""
    for code in ReasonCode:
        assert "arrived" not in code.value
        assert "confirmed" not in code.value
