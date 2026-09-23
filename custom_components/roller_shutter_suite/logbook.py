"""Logbook entries for the reason events.

The logbook finds this platform by its name and calls
``async_describe_events(hass, async_describe_event)`` with a callback that
takes the domain, the event type and a function from an event to a mapping
with a name, a message and, optionally, an entity ID
(``homeassistant/components/logbook/__init__.py``,
``_process_logbook_platform``, Core 2026.9.2).

The logbook calls that function while it answers a request, without a way to
wait, so the message is built from the translations Home Assistant already
holds for the language of the installation: the set-up of the entry loads
them. The words for each reason are those of the reason sensor
(``entity.sensor.active_reason.state``); the sentence around them is in
``common``. If a text is missing (the language of the installation was
changed while the entry was loaded), the entry names the reason codes
instead of failing.
"""

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.components.logbook.const import (
    LOGBOOK_ENTRY_ENTITY_ID,
    LOGBOOK_ENTRY_MESSAGE,
    LOGBOOK_ENTRY_NAME,
)
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.translation import async_get_cached_translations

from .const import DOMAIN, EVENT_REASON
from .core.reasons import ReasonCode
from .events import ATTR_NAME, ATTR_SUBENTRY_ID
from .sensor import KEY_ACTIVE_REASON

CATEGORY_ENTITY = "entity"
CATEGORY_COMMON = "common"

MESSAGE_SENT = "logbook_sent"
MESSAGE_DRY_RUN = "logbook_dry_run"
MESSAGE_HELD_BACK = "logbook_held_back"
NO_TARGET = "_no_target"
"""The suffix of the message for a decision without one common target."""


def _reason_text(texts: Mapping[str, str], code: str) -> str:
    key = (
        f"component.{DOMAIN}.{CATEGORY_ENTITY}.sensor.{KEY_ACTIVE_REASON}.state.{code}"
    )
    return texts.get(key, code)


def describe(
    data: Mapping[str, Any], entity_texts: Mapping[str, str], common: Mapping[str, str]
) -> str:
    """Return the message of the logbook entry for the data of a reason event."""
    reason = str(data.get("reason"))
    cause = _reason_text(entity_texts, str(data.get("wish_reason")))
    held = _reason_text(entity_texts, reason)
    target = data.get("target")
    if reason == ReasonCode.SENT:
        name = MESSAGE_SENT
    elif reason == ReasonCode.DRY_RUN:
        name = MESSAGE_DRY_RUN
    else:
        name = MESSAGE_HELD_BACK
    if target is None:
        name += NO_TARGET
    template = common.get(f"component.{DOMAIN}.{CATEGORY_COMMON}.{name}")
    if template is None:
        return f"{reason} ({data.get('wish_reason')})"
    return (
        template.replace("{target}", str(target))
        .replace("{cause}", cause)
        .replace("{held}", held)
    )


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict[str, Any]]], None],
) -> None:
    """Describe the reason events of the integration to the logbook."""

    @callback
    def async_describe_reason_event(event: Event) -> dict[str, Any]:
        language = hass.config.language
        data = event.data
        entry: dict[str, Any] = {
            LOGBOOK_ENTRY_NAME: data.get(ATTR_NAME),
            LOGBOOK_ENTRY_MESSAGE: describe(
                data,
                async_get_cached_translations(hass, language, CATEGORY_ENTITY, DOMAIN),
                async_get_cached_translations(hass, language, CATEGORY_COMMON, DOMAIN),
            ),
        }
        entity_id = er.async_get(hass).async_get_entity_id(
            Platform.SENSOR, DOMAIN, f"{data.get(ATTR_SUBENTRY_ID)}_{KEY_ACTIVE_REASON}"
        )
        if entity_id is not None:
            entry[LOGBOOK_ENTRY_ENTITY_ID] = entity_id
        return entry

    async_describe_event(DOMAIN, EVENT_REASON, async_describe_reason_event)
