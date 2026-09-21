"""Repair issues about stored configuration.

Every text a user sees is a translation key with placeholders. The
placeholders carry only language-neutral content: names the user chose, keys
of settings, entity IDs. The English detail of a fault that the core provides
is for logs and never shown.

None of these issues has a fix button. They are repaired by saving the form
of the level they name, or by removing it; the next set-up then no longer
reports them, and :func:`async_sync_issues` deletes what is no longer
reported.
"""

from collections.abc import Iterable
from dataclasses import dataclass, field

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


@dataclass(frozen=True, slots=True)
class Issue:
    """One repair issue: its identifier, its translation key, its placeholders."""

    issue_id: str
    translation_key: str
    placeholders: dict[str, str] = field(default_factory=dict)


@callback
def async_sync_issues(hass: HomeAssistant, issues: Iterable[Issue]) -> None:
    """Create or update the given issues and delete every other one of the integration."""
    current = {issue.issue_id: issue for issue in issues}
    registry = ir.async_get(hass)
    stale = [
        issue_id
        for domain, issue_id in registry.issues
        if domain == DOMAIN and issue_id not in current
    ]
    for issue_id in stale:
        ir.async_delete_issue(hass, DOMAIN, issue_id)
    for issue in current.values():
        ir.async_create_issue(
            hass,
            DOMAIN,
            issue.issue_id,
            is_fixable=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=issue.translation_key,
            translation_placeholders=issue.placeholders,
        )
