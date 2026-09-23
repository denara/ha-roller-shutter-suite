"""Every reason code of the core has words in every language, and every entity a name.

Section 5 of the design specification: adding a reason code requires an
English and a German translation, and a test enforces it. This is that test.
It reads the shipped files, one per language, so a language that is added
later is checked in the same way.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from custom_components.roller_shutter_suite import binary_sensor, logbook, sensor
from custom_components.roller_shutter_suite.core.reasons import ReasonCode
from custom_components.roller_shutter_suite.record import FAULT_REASONS
from scripts import build_translations

INTEGRATION_DIR = (
    Path(__file__).parents[2] / "custom_components" / "roller_shutter_suite"
)
FILES = [name for names in build_translations.languages().values() for name in names]
WORDS_FOR_INSIDERS = re.compile(r"\b(layer|constraint|gate|arbiter)s?\b", re.IGNORECASE)
"""Words of the design that a user does not need to know."""


def _load(relative_path: str) -> dict[str, Any]:
    content: dict[str, Any] = json.loads(
        (INTEGRATION_DIR / relative_path).read_text(encoding="utf-8")
    )
    return content


@pytest.mark.parametrize("path", FILES)
def test_every_reason_code_of_the_core_has_words(path: str) -> None:
    """The reason sensor and the logbook show a text for every code, and nothing else."""
    states = _load(path)["entity"]["sensor"][sensor.KEY_ACTIVE_REASON]["state"]

    assert set(states) == {code.value for code in ReasonCode}
    for code, text in states.items():
        assert text.strip(), code
        assert not WORDS_FOR_INSIDERS.search(text), (code, text)


@pytest.mark.parametrize("path", FILES)
def test_the_codes_of_the_safety_net_have_words(path: str) -> None:
    """``layer_failed``, ``constraint_failed`` and ``gate_rule_failed`` are covered too."""
    states = _load(path)["entity"]["sensor"][sensor.KEY_ACTIVE_REASON]["state"]

    for code in FAULT_REASONS.values():
        assert states[code.value]


def test_a_missing_word_fails_the_test() -> None:
    """The check above is not vacuous: a code without words is found."""
    states = dict(_load(FILES[0])["entity"]["sensor"]["active_reason"]["state"])
    del states[ReasonCode.GATE_RULE_FAILED.value]

    assert set(states) != {code.value for code in ReasonCode}


@pytest.mark.parametrize("path", FILES)
def test_every_status_entity_has_a_name_and_the_logbook_its_sentences(
    path: str,
) -> None:
    """Names by translation key; the six sentences of the logbook."""
    strings = _load(path)
    entities = strings["entity"]
    for key in (
        sensor.KEY_ACTIVE_REASON,
        sensor.KEY_TARGET_POSITION,
        sensor.KEY_NEXT_ACTION,
    ):
        assert entities["sensor"][key]["name"]
    for key in (binary_sensor.KEY_OVERRIDE_ACTIVE, binary_sensor.KEY_DRY_RUN):
        assert entities["binary_sensor"][key]["name"]
    for message in (
        logbook.MESSAGE_SENT,
        logbook.MESSAGE_DRY_RUN,
        logbook.MESSAGE_HELD_BACK,
    ):
        for name in (message, message + logbook.NO_TARGET):
            assert strings["common"][name]
            assert not WORDS_FOR_INSIDERS.search(strings["common"][name])


def test_every_icon_belongs_to_an_entity_with_a_translation_key() -> None:
    """``icons.json`` names the same keys as the entities, and only known states."""
    icons = _load("icons.json")["entity"]
    strings = _load("strings.json")["entity"]

    for domain, keys in icons.items():
        for key, icon in keys.items():
            assert key in strings[domain], (domain, key)
            assert icon["default"].startswith("mdi:")
            for state in icon.get("state", {}):
                if domain == "sensor":
                    assert state in strings[domain][key]["state"], state
                else:
                    assert state in {"on", "off"}
